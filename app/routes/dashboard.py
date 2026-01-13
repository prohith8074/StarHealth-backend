"""
Dashboard routes - optimized version with Stale-While-Revalidate (SWR) pattern using Redis
"""
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from app.config.database import get_database, is_mongodb_ready
from app.config.logging_config import get_logger
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import threading
import json
import os
import hashlib
from dotenv import load_dotenv
import redis
import asyncio
import re
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

router = APIRouter()
logger = get_logger(__name__)

from app.services.redis_service import get_redis_service, RedisService

def get_ist_time():
    """Get current time in Indian Standard Time (IST)"""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

class RedisSWRCache:
    def __init__(self, ttl=None):
        """
        🔒 ENTERPRISE: Dashboard cache using centralized RedisService.
        Key format: dashboard:{days}:v{version}
        TTL: None (Permanent) - Requirement for server warmup.
        """
        self.redis_service = get_redis_service()
        # Use the underlying client from RedisService (singleton)
        self.redis_client = self.redis_service.redis_client
        self.available = getattr(self.redis_service, 'redis_client', None) is not None
        
        self._lock = threading.Lock()
        self._refresh_locks: Dict[str, threading.Lock] = {}
        self.ttl = None  # Permanent retention for warmup
    
    def _get_refresh_lock(self, days: int) -> threading.Lock:
        """Get refresh lock for a specific days value"""
        with self._lock:
            key = f"dashboard_{days}"
            if key not in self._refresh_locks:
                self._refresh_locks[key] = threading.Lock()
            return self._refresh_locks[key]
    
    def _get_cache_key(self, days: int, version: str) -> str:
        return f"dashboard:{days}:v{version}"
    
    def _generate_version(self) -> str:
        """
        Generate version string based on current hour.
        Cache invalidates automatically every hour.
        """
        now = get_ist_time()
        return f"{now.strftime('%Y-%m-%dT%H')}_v3"
    
    def get(self, days: int) -> Optional[Dict[str, Any]]:
        """Get cached dashboard data. Tries current version, falls back to any version."""
        if not self.available or not self.redis_client:
            return None
        
        current_version = self._generate_version()
        cache_key = self._get_cache_key(days, current_version)
        
        try:
            # Try exact match first
            cached_entry = self.redis_client.get(cache_key)
            if cached_entry:
                logger.debug(f"💾 CACHE GET (dashboard_{days}): Hit v{current_version}")
                entry = json.loads(cached_entry)
                return entry["data"]
            
            # Fallback: Find most recent version
            pattern = f"dashboard:{days}:v*"
            keys = self.redis_client.keys(pattern)
            if keys:
                keys.sort(reverse=True)
                cached_entry = self.redis_client.get(keys[0])
                if cached_entry:
                    logger.debug(f"💾 CACHE GET (dashboard_{days}): Hit fallback {keys[0]}")
                    entry = json.loads(cached_entry)
                    return entry["data"]
            
            return None
        except Exception as e:
            logger.error(f"❌ Error getting cache for dashboard_{days}: {e}")
            return None
    
    def set(self, days: int, value: Dict[str, Any], version: Optional[str] = None):
        """Cache dashboard data PERMANENTLY (no TTL)."""
        if not self.available or not self.redis_client:
            return
        
        if version is None:
            version = self._generate_version()
        
        cache_key = self._get_cache_key(days, version)
        
        try:
            entry = {
                "data": value,
                "timestamp": datetime.now().timestamp(),
                "version": version
            }
            json_data = json.dumps(entry, default=str)
            
            # Set with 15 minute TTL
            self.redis_client.set(cache_key, json_data, ex=900)
            logger.info(f"💾 CACHE SET (dashboard_{days}): TTL 15m, v{version}")
            
            # Cleanup old versions for this day-span to keep Redis clean (keep only latest)
            pattern = f"dashboard:{days}:v*"
            keys = self.redis_client.keys(pattern)
            if keys:
                keys.sort(reverse=True)
                # Keep top 2, delete rest
                if len(keys) > 2:
                    keys_to_delete = keys[2:]
                    self.redis_client.delete(*keys_to_delete)
                    logger.debug(f"🧹 Cleaned up {len(keys_to_delete)} old dashboard versions")
            
        except Exception as e:
            logger.error(f"❌ Error setting cache: {e}")

    def is_stale(self, days: int) -> bool:
        # With permanent cache, we rely on background refresh to update version.
        # Use simple version check logic if needed, or always false for now.
        return False

    def should_refresh(self, days: int) -> bool:
        # Allow refresh if we don't have the *current hour's* version
        if not self.available or not self.redis_client:
            return True
        current_version = self._generate_version()
        cache_key = self._get_cache_key(days, current_version)
        return not self.redis_client.exists(cache_key)

    def invalidate(self, days: Optional[int] = None):
        if not self.available or not self.redis_client: return
        try:
            pattern = f"dashboard:{days}:v*" if days else "dashboard:*:v*"
            keys = self.redis_client.keys(pattern)
            if keys:
                self.redis_client.delete(*keys)
        except Exception as e:
            logger.error(f"❌ Error invalidating: {e}")

    def is_refreshing(self, days: int) -> bool:
        """Check if a refresh is currently in progress for this day range"""
        if not self.available or not self.redis_client:
            return False
        return self.redis_client.exists(f"dashboard:refreshing:{days}")

    def get_version(self, days: int) -> Optional[str]:
        """Get the version string of the currently cached data"""
        if not self.available or not self.redis_client:
            return None
        
        current_version = self._generate_version()
        cache_key = self._get_cache_key(days, current_version)
        
        try:
            # Try exact match first
            cached_entry = self.redis_client.get(cache_key)
            if cached_entry:
                entry = json.loads(cached_entry)
                return entry.get("version")
            
            # Fallback: Find most recent version
            pattern = f"dashboard:{days}:v*"
            keys = self.redis_client.keys(pattern)
            if keys:
                keys.sort(reverse=True)
                cached_entry = self.redis_client.get(keys[0])
                if cached_entry:
                    entry = json.loads(cached_entry)
                    return entry.get("version")
            
            return None
        except Exception:
            return None

cache = RedisSWRCache()  # No TTL

# 🔒 PUBLIC: Function to invalidate dashboard cache from other modules
def invalidate_dashboard_cache(days: int = None):
    """
    Invalidate dashboard cache. Call this when data changes that affects dashboard.
    If days is None, invalidates all cached versions.
    """
    try:
        cache.invalidate(days)
        logger.info(f"🔄 Dashboard cache invalidated (days={days})")
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate dashboard cache: {e}")

def calculate_trend_percentage(
    current: int,
    previous: int,
    current_has_data: bool,
    previous_has_data: bool,
    gap_days: int,
    window_size: int,
    min_threshold: int = 5
) -> Optional[float]:
    """
    Calculate trend percentage only.
    Returns None if comparison is invalid or insignificant.
    """
    if not previous_has_data:
        return None
    
    if gap_days > window_size:
        return None
    
    if current == 0 and previous == 0:
        return None
    
    if current > 0 and previous == 0:
        return 100.0 # Treat as 100% increase (new)
    
    if current == 0 and previous > 0:
        return -100.0
    
    if current < min_threshold and previous < min_threshold:
        return None
    
    percentage = ((current - previous) / previous) * 100.0
    
    # Cap excessive percentages for display safety (logic moved from full obj)
    if (current < 10 or previous < 10) and abs(percentage) > 200:
        if percentage > 0:
            percentage = 200.0
        else:
            percentage = -100.0 # Should be capped at -100 anyway
            
    return round(percentage, 1)

def _check_data_gap(db, start_date: datetime, end_date: datetime) -> tuple:
    """
    Check if there's data in the period and calculate gap days.
    Returns (has_data, gap_days)
    """
    has_data = db.dashboarddata.count_documents({
        "createdAt": {"$gte": start_date, "$lt": end_date}
    }) > 0
    
    if not has_data:
        last_data_point = db.dashboarddata.find_one(
            {"createdAt": {"$lt": start_date}},
            sort=[("createdAt", -1)]
        )
        if last_data_point:
            last_date = last_data_point.get("createdAt")
            if isinstance(last_date, datetime):
                gap_days = (start_date - last_date).days
            else:
                gap_days = 999
        else:
            gap_days = 999
    else:
        gap_days = 0
    
    return has_data, gap_days

def serialize_datetime(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: serialize_datetime(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_datetime(item) for item in obj]
    return obj

def _calculate_data_hash(data: Dict[str, Any]) -> str:
    """
    Calculate hash of key metrics to detect data changes.
    Uses core metrics that indicate actual data changes.
    Handles both flat (legacy) and compact (new) formats.
    """
    # Check for compact format first (summary dict exists)
    if "summary" in data and isinstance(data["summary"], dict):
        summary = data["summary"]
        key_metrics = {
            "uniqueUsers": summary.get("totalUsers", 0),
            "totalInteractions": summary.get("totalInteractions", 0),
            "feedbackCount": summary.get("feedbackCount", 0),
            "recommendations": summary.get("recommendations", 0),
            "salesPitches": summary.get("salesPitches", 0),
            "completedConversations": summary.get("completed", 0),
            "incompleteConversations": summary.get("incomplete", 0),
            "totalConversations": summary.get("totalConversations", 0),
        }
    else:
        # Legacy flat format
        key_metrics = {
            "uniqueUsers": data.get("uniqueUsers", 0),
            "totalInteractions": data.get("totalInteractions", 0),
            "feedbackCount": data.get("feedbackCount", 0),
            "recommendations": data.get("recommendations", 0),
            "salesPitches": data.get("salesPitches", 0),
            "completedConversations": data.get("completedConversations", 0),
            "incompleteConversations": data.get("incompleteConversations", 0),
            "totalConversations": data.get("totalConversations", 0),
        }
    
    metrics_json = json.dumps(key_metrics, sort_keys=True)
    return hashlib.md5(metrics_json.encode()).hexdigest()

def _fetch_dashboard_data_from_db(days: int) -> Dict[str, Any]:
    db = get_database()
    days = 7 if days <= 0 or days > 30 else days
    # Use IST to align with storage in dashboard_service.py
    now = get_ist_time()
    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    previous_start_date = start_date - timedelta(days=days)
    previous_end_date = start_date
    
    # Check data gaps synchronously (lightweight)
    current_has_data, current_gap = _check_data_gap(db, start_date, now)
    previous_has_data, previous_gap = _check_data_gap(db, previous_start_date, previous_end_date)
    gap_days = max(current_gap, previous_gap)
    
    logger.info(f"🔄 Fetching dashboard data (Parallel Execution)...")

    with ThreadPoolExecutor(max_workers=16) as executor:
        # --- Helper for standard Count queries ---
        def count(collection, query):
            return collection.count_documents(query)

        # ========== ALL-TIME TOTALS (FOR CARDS) ==========
        # These metrics are shown on the dashboard cards as lifetime totals
        
        # --- ALL-TIME Unique Users ---
        f_unique_alltime = executor.submit(lambda: len(db.dashboarddata.distinct("data.agent_code", {
            "eventType": "new_session"
        })) or 0)
        
        # --- ALL-TIME Feedback/Completed ---
        feedback_criteria_alltime = {
            "feedback": {"$nin": ["incomplete", "Pending"]},
            "$or": [{"conversationStatus": {"$exists": False}}, {"conversationStatus": {"$ne": "incomplete"}}]
        }
        f_feedback_alltime = executor.submit(lambda: len(db.feedback.distinct("sessionId", feedback_criteria_alltime)))
        
        # --- ALL-TIME Recommendations ---
        f_rec_alltime = executor.submit(lambda: len(db.feedback.distinct("sessionId", {"agentType": "product_recommendation"})))
        
        # --- ALL-TIME Sales Pitches ---
        f_sales_alltime = executor.submit(lambda: len(db.feedback.distinct("sessionId", {"agentType": "sales_pitch"})))
        
        # --- ALL-TIME Incomplete ---
        f_inc_alltime = executor.submit(lambda: len(db.feedback.distinct("sessionId", {
            "$or": [
                {"conversationStatus": "incomplete"},
                {"feedback": "incomplete"},
                {"feedback": "Pending"}
            ]
        })))
        
        # --- ALL-TIME Repeated Users ---
        f_repeated_alltime = executor.submit(lambda: db["Repeat_users"].count_documents({}) or 0)

        # ========== TIME-FILTERED DATA (FOR GRAPHS & TRENDS) ==========
        # These are for the time-series charts and trend calculations
        
        # --- 1. Unique Users (Time Filtered for Trends) ---
        f_unique_current = executor.submit(lambda: len(db.dashboarddata.distinct("data.agent_code", {
            "eventType": "new_session", "createdAt": {"$gte": start_date, "$lte": now}
        })) or 0)
        f_unique_prev = executor.submit(lambda: len(db.dashboarddata.distinct("data.agent_code", {
            "eventType": "new_session", "createdAt": {"$gte": previous_start_date, "$lt": previous_end_date}
        })) or 0)

        # --- 2. Interactions ---
        def fetch_interactions(s, e, end_inclusive=False):
            op = "$lte" if end_inclusive else "$lt"
            q = {"createdAt": {"$gte": s, op: e}}
            return db.agent_stats.count_documents(q) + db.dashboarddata.count_documents(q)
        
        f_inter_curr = executor.submit(fetch_interactions, start_date, now, True)
        f_inter_prev = executor.submit(fetch_interactions, previous_start_date, previous_end_date, False)

        # --- 3. Feedback & Completed Conversations (Same Source) ---
        feedback_criteria = {
            "feedback": {"$nin": ["incomplete", "Pending"]},
            "$or": [{"conversationStatus": {"$exists": False}}, {"conversationStatus": {"$ne": "incomplete"}}]
        }
        def fetch_feedback(s, e, end_inclusive=False):
            op = "$lte" if end_inclusive else "$lt"
            q = {"$and": [{"createdAt": {"$gte": s, op: e}}, feedback_criteria]}
            # 🔒 FIX: Count UNIQUE sessions, not documents, to handle duplicates
            return len(db.feedback.distinct("sessionId", q))

        f_feedback_curr = executor.submit(fetch_feedback, start_date, now, True)
        f_feedback_prev = executor.submit(fetch_feedback, previous_start_date, previous_end_date, False)

        # --- 4. Recommendations & Sales Pitches (From Feedback acts as Unique Conversation Record) ---
        def fetch_agent_type_count(atype, s, e, end_inclusive=False):
            op = "$lte" if end_inclusive else "$lt"
            # 🔒 FIX: Count UNIQUE sessions for this agent type
            query = {
                "agentType": atype, 
                "createdAt": {"$gte": s, op: e}
            }
            return len(db.feedback.distinct("sessionId", query))

        f_rec_curr = executor.submit(fetch_agent_type_count, "product_recommendation", start_date, now, True)
        f_rec_prev = executor.submit(fetch_agent_type_count, "product_recommendation", previous_start_date, previous_end_date, False)
        f_sales_curr = executor.submit(fetch_agent_type_count, "sales_pitch", start_date, now, True)
        f_sales_prev = executor.submit(fetch_agent_type_count, "sales_pitch", previous_start_date, previous_end_date, False)

        # --- 5. Incomplete Conversations (From Feedback) ---
        def fetch_incomplete_count(s, e, end_inclusive=False):
            op = "$lte" if end_inclusive else "$lt"
            query = {
                "$or": [
                    {"conversationStatus": "incomplete"},
                    {"feedback": "incomplete"},
                    {"feedback": "Pending"} 
                ],
                "createdAt": {"$gte": s, op: e}
            }
            # 🔒 FIX: Count UNIQUE sessions
            return len(db.feedback.distinct("sessionId", query))

        f_inc_curr = executor.submit(fetch_incomplete_count, start_date, now, True)
        f_inc_prev = executor.submit(fetch_incomplete_count, previous_start_date, previous_end_date, False)

        # --- 6. Repeated Users (Already all-time above) ---

        # --- 7. Recent Activity (Complex Logic) ---
        def fetch_recent_activity():
            try:
                # 🔒 FIX: Aggregation to Dedup by SessionID and get truly recent unique activities
                pipeline = [
                    {"$match": {
                        "feedback": {"$nin": ["incomplete", "Pending", "no feedback", "No feedback", "no", "No"]},
                        "$or": [{"conversationStatus": {"$exists": False}}, {"conversationStatus": {"$ne": "incomplete"}}]
                    }},
                    {"$sort": {"createdAt": -1}}, # Newest first
                    {"$group": {
                        "_id": "$sessionId", # Group by Session ID to dedup
                        "doc": {"$first": "$$ROOT"} # Take the most recent doc for that session
                    }},
                    {"$replaceRoot": {"newRoot": "$doc"}}, # Promote that doc back to root
                    {"$sort": {"createdAt": -1}}, # Sort again by date
                    {"$limit": 7}
                ]
                
                items = list(db.feedback.aggregate(pipeline))
                
                # Step 2: Resolve Names
                activity = []
                name_cache = {}
                for item in items:
                    code = item.get("agentCode")
                    display = item.get("userName", "Unknown")
                    if code and code != "N/A":
                        if code in name_cache:
                            if name_cache[code]: display = name_cache[code]
                        else:
                            # Case-insensitive lookup
                            agent = db.agents.find_one({"agent_code": {"$regex": f"^{re.escape(code)}$", "$options": "i"}})
                            if agent and "agent_name" in agent:
                                name_cache[code] = agent["agent_name"]
                                display = agent["agent_name"]
                            else:
                                name_cache[code] = None
                    
                    # 🔒 FIX: Derive timestamp from ObjectId if createdAt is missing
                    # ObjectId encodes creation timestamp - use it as fallback instead of now()
                    created_at = item.get("createdAt")
                    if not created_at:
                        # Fallback: try updatedAt, then derive from _id
                        created_at = item.get("updatedAt")
                        if not created_at and "_id" in item:
                            try:
                                created_at = item["_id"].generation_time
                            except:
                                created_at = datetime.now()
                        if not created_at:
                            created_at = datetime.now()
                    
                    activity.append({
                        "name": display,
                        "code": code or "N/A",
                        "type": item.get("agentType", "General").replace("_", " ").title(),
                        "feedback": item.get("feedback", "No feedback"),
                        "date": created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)
                    })
                return activity
            except Exception as e:
                logger.warning(f"Error fetching recent activity: {e}")
                return []
        
        f_recent = executor.submit(fetch_recent_activity)

        # --- 8. Top Agents ---
        def fetch_top_agents():
            pipeline = [
                {"$match": {"createdAt": {"$gte": start_date, "$lte": now}, "agentCode": {"$exists": True, "$ne": None}}},
                {"$group": {"_id": "$agentCode", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}, {"$limit": 10}
            ]
            try:
                res = list(db.feedback.aggregate(pipeline))
                return [{"code": i["_id"], "count": i["count"]} for i in res]
            except:
                return []
        
        f_top_agents = executor.submit(fetch_top_agents)

        # --- 9. Feedback Distribution ---
        def fetch_feedback_dist():
            pipeline = [
                {"$match": {
                    "createdAt": {"$gte": start_date, "$lte": now},
                    "feedback": {"$nin": ["incomplete", "Pending"]},
                    "$or": [{"conversationStatus": {"$exists": False}}, {"conversationStatus": {"$ne": "incomplete"}}]
                }},
                {"$group": {"_id": "$agentType", "count": {"$sum": 1}}}
            ]
            try:
                res = list(db.feedback.aggregate(pipeline))
                dist = {"product_recommendation": 0, "sales_pitch": 0}
                for r in res:
                    if r["_id"] in dist: dist[r["_id"]] = r["count"]
                return dist
            except:
                return {"product_recommendation": 0, "sales_pitch": 0}
        
        f_feedback_dist = executor.submit(fetch_feedback_dist)

        # --- 10. Completed Conversations Distribution ---
        def fetch_completed_conversations():
            # Build day ranges first (cheap)
            day_ranges = []
            for i in range(days - 1, -1, -1):
                d = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
                day_ranges.append({"date": d, "label": d.strftime("%b %d"), "key": d.strftime("%Y-%m-%d")})
            
            # Completed Conversations
            # OPTIMIZED: Source from Feedback collection (Source of Truth)
            pipeline = [
                {"$match": {
                    "createdAt": {"$gte": start_date},
                    "feedback": {"$nin": ["incomplete", "Pending", "no feedback", "No feedback", "no", "No"]},
                    "$or": [{"conversationStatus": {"$exists": False}}, {"conversationStatus": {"$ne": "incomplete"}}]
                }},
                {"$group": {
                    "_id": "$sessionId", 
                    "doc": {"$first": "$$ROOT"}
                }},
                {"$replaceRoot": {"newRoot": "$doc"}},
                {"$group": {"_id": {"date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$createdAt"}}, "agentType": "$agentType"}, "count": {"$sum": 1}}}
            ]
            try:
                raw_completed = list(db.feedback.aggregate(pipeline))
            except: raw_completed = []
            
            completed_map = {}
            for r in raw_completed:
                d = r["_id"]["date"]
                t = r["_id"].get("agentType")
                if t:
                    if d not in completed_map: completed_map[d] = {"product_recommendation": 0, "sales_pitch": 0}
                    completed_map[d][t] = r["count"]

            # Assemble Arrays
            comp_dist = {"labels": [], "data": {"productRecommendation": [], "salesPitch": []}}
            
            for dr in day_ranges:
                k = dr["key"]
                comp_dist["labels"].append(dr["label"])
                
                # Completed
                comp_dist["data"]["productRecommendation"].append(completed_map.get(k, {}).get("product_recommendation", 0))
                comp_dist["data"]["salesPitch"].append(completed_map.get(k, {}).get("sales_pitch", 0))
                
            return comp_dist

        f_comp_dist = executor.submit(fetch_completed_conversations)
        
        # --- WAIT FOR RESULTS ---
        # Note: .result() blocks until completion
        logger.info("⏳ Waiting for parallel queries...")
        
        # ALL-TIME totals (for cards)
        unique_users_alltime = f_unique_alltime.result()
        feedback_count_alltime = f_feedback_alltime.result()
        recommendations_alltime = f_rec_alltime.result()
        sales_pitches_alltime = f_sales_alltime.result()
        incomplete_alltime = f_inc_alltime.result()
        repeated_users_alltime = f_repeated_alltime.result()
        
        # Time-filtered (for trends/graphs)
        unique_users_current = f_unique_current.result()
        unique_users_previous = f_unique_prev.result()
        
        total_interactions_current = f_inter_curr.result()
        total_interactions_previous = f_inter_prev.result()
        
        feedback_count_current = f_feedback_curr.result()
        feedback_count_previous = f_feedback_prev.result()
        
        recommendations_current = f_rec_curr.result()
        recommendations_previous = f_rec_prev.result()
        
        sales_pitches_current = f_sales_curr.result()
        sales_pitches_previous = f_sales_prev.result()
        
        incomplete_conversations_current = f_inc_curr.result()
        incomplete_conversations_previous = f_inc_prev.result()
        
        recent_activity = f_recent.result()
        top_agents = f_top_agents.result()
        feedback_by_type = f_feedback_dist.result()
        completed_conversations_data = f_comp_dist.result()
        
        # Derived Metrics (time-filtered for trends)
        completed_conversations_current = feedback_count_current
        completed_conversations_previous = feedback_count_previous
        total_conversations_current = completed_conversations_current + incomplete_conversations_current
        total_conversations_previous = completed_conversations_previous + incomplete_conversations_previous
        
        # Derived Metrics (all-time for cards)
        completed_alltime = feedback_count_alltime
        total_conversations_alltime = completed_alltime + incomplete_alltime
        
    logger.info("✅ Parallel fetch complete!")

    trends = {
        "uniqueUsers": calculate_trend_percentage(
            unique_users_current, unique_users_previous,
            current_has_data, previous_has_data, gap_days, days
        ),
        "totalInteractions": calculate_trend_percentage(
            total_interactions_current, total_interactions_previous,
            current_has_data, previous_has_data, gap_days, days
        ),
        "feedback": calculate_trend_percentage(
            feedback_count_current, feedback_count_previous,
            current_has_data, previous_has_data, gap_days, days
        ),
        "recommendations": calculate_trend_percentage(
            recommendations_current, recommendations_previous,
            current_has_data, previous_has_data, gap_days, days
        ),
        "salesPitches": calculate_trend_percentage(
            sales_pitches_current, sales_pitches_previous,
            current_has_data, previous_has_data, gap_days, days
        ),
        "repeatedUsers": None, # Not calculated
        "completedConversations": calculate_trend_percentage(
            completed_conversations_current, completed_conversations_previous,
            current_has_data, previous_has_data, gap_days, days
        ),
        "incompleteConversations": calculate_trend_percentage(
            incomplete_conversations_current, incomplete_conversations_previous,
            current_has_data, previous_has_data, gap_days, days
        ),
        "totalConversations": calculate_trend_percentage(
            total_conversations_current, total_conversations_previous,
            current_has_data, previous_has_data, gap_days, days
        )
    }

    # 🔒 ENTERPRISE: Compact response structure (5-20 KB target)
    # IMPORTANT: Summary uses ALL-TIME totals (for cards), graphs use time-filtered data
    response = {
        "meta": {
            "days": days,
            "generatedAt": datetime.now().isoformat()
        },
        "summary": {
            # ALL-TIME TOTALS for dashboard cards
            "totalUsers": unique_users_alltime,
            "totalConversations": total_conversations_alltime,
            "completed": completed_alltime,
            "incomplete": incomplete_alltime,
            "feedbackCount": feedback_count_alltime,
            "recommendations": recommendations_alltime,
            "salesPitches": sales_pitches_alltime,
            "repeatedUsers": repeated_users_alltime,
            # Time-filtered interaction count (this one can stay as current period)
            "totalInteractions": total_interactions_current
        },
        "trends": {
            "uniqueUsers": trends.get("uniqueUsers"),
            "totalInteractions": trends.get("totalInteractions"),
            "feedbackCount": trends.get("feedback"),
            "recommendations": trends.get("recommendations"),
            "salesPitches": trends.get("salesPitches"),
            "completedConversations": trends.get("completedConversations"),
            "incompleteConversations": trends.get("incompleteConversations"),
            "totalConversations": trends.get("totalConversations")
        },
        "topStats": {
            "topAgents": top_agents,
            "feedbackByType": feedback_by_type
        },
        "recentActivity": recent_activity,
        "completedConversationsData": completed_conversations_data
    }
    
    return response

def _refresh_cache_background(days: int):
    """
    🔒 ENTERPRISE: Background cache refresh - uses Redis lock for cross-instance coordination.
    """
    if not cache.available or not cache.redis_client:
        return

    lock_key = f"dashboard:refreshing:{days}"
    # Try to set lock with 60s timeout (NX=True means only if not exists)
    if not cache.redis_client.set(lock_key, "1", ex=60, nx=True):
        logger.debug(f"⏭️  Refresh already in progress for dashboard_{days}, skipping")
        return

    try:
        logger.info(f"🔄 Starting background dashboard aggregation (days={days})...")
        
        # Calculate new data
        data = _fetch_dashboard_data_from_db(days)
        new_hash = _calculate_data_hash(data)
        
        # Get current version details to check hash
        # Ideally we store hash in a separate key or inside the json
        # For simplicity, we just check if data changed by comparing with cached data logic
        # But we don't have old hash easily available unless we fetch it
        
        # Just update cache - SWR model implies we always update if background task runs
        # But to be efficient we can skip if identical?
        # Let's just set it.
        
        cache.set(days, data)
        logger.info(f"✅ Dashboard pre-warmed successfully")
        
    except Exception as e:
        logger.error(f"❌ Error in background dashboard refresh: {e}", exc_info=True)
    finally:
        # Always release the lock
        cache.redis_client.delete(lock_key)

@router.get("")
async def get_dashboard_data(
    days: int = Query(7, ge=1, le=30), 
    background_tasks: BackgroundTasks = None
):
    """
    Get dashboard analytics data with SWR caching.
    1. Returns cached data immediately if available (stale or fresh).
    2. Triggers background refresh if data is stale or missing.
    """
    try:
        # 1. Try to get from SWR cache
        cached_data = cache.get(days)
        
        if cached_data:
            # 2. Check if refresh needed (Stale-While-Revalidate)
            if cache.should_refresh(days):
                logger.info(f"🔄 Cache stale/missing for dashboard_{days}, triggering background refresh")
                background_tasks.add_task(_refresh_cache_background, days)
                # Return stale data immediately
                return {"success": True, "data": cached_data}
            
            # Return fresh data
            logger.debug(f"✅ CACHE HIT (FRESH): dashboard_{days} - returning fresh data")
            return {"success": True, "data": cached_data}
        
        # 3. Cache Miss - Cold Start
        logger.info(f"🤖 CACHE MISS: dashboard_{days} - triggering background aggregation")
        
        # Check if already refreshing
        if cache.is_refreshing(days):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=202, content={"success": True, "message": "Aggregation in progress"})
            
        # 4. Trigger background refresh
        background_tasks.add_task(_refresh_cache_background, days)
        
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=202, content={"success": True, "message": "Starting background aggregation"})

    except Exception as e:
        logger.error(f"❌ Error fetching dashboard data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

def trigger_dashboard_warmup(days: int = 7):
    """
    Public function to trigger dashboard warmup from other modules (e.g. Auth).
    Runs in a background thread to avoid blocking the caller.
    """
    logger.info(f"🔄 Triggering proactive dashboard warmup for {days} days...")
    threading.Thread(target=_refresh_cache_background, args=(days,), daemon=True).start()



