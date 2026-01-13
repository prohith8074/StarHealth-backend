"""
Agents statistics routes - ported from Node.js backend
This handles agent statistics and traces
"""
from fastapi import APIRouter, HTTPException, Depends, Header
from app.config.database import get_database
from app.config.logging_config import get_logger
from app.services.redis_service import get_redis_service
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from collections import defaultdict
import asyncio
import json

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

def serialize_datetime(obj):
    """Recursively serialize datetime objects to ISO format strings"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: serialize_datetime(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_datetime(item) for item in obj]
    return obj

router = APIRouter()
logger = get_logger(__name__)

# Redis Cache Key
AGENTS_STATS_CACHE_KEY = "agents_stats:v1"
CACHE_TTL = 5  # 5 seconds (Real-time)

# Thread pool for blocking operations
executor = ThreadPoolExecutor(max_workers=4)

def run_blocking_with_timeout(func, timeout_seconds=25):
    """Run blocking function with timeout"""
    try:
        future = executor.submit(func)
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        logger.error(f"⏱️ Blocking operation timed out after {timeout_seconds}s")
        raise HTTPException(status_code=504, detail=f"Database query timed out after {timeout_seconds} seconds")
    except Exception as e:
        logger.error(f"❌ Error in blocking operation: {e}")
        raise

async def get_current_user_optional(authorization: Optional[str] = Header(None)):
    """Optional authentication - doesn't fail if no token provided"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.replace("Bearer ", "")
    from app.routes.auth import verify_jwt_token
    payload = verify_jwt_token(token)
    if not payload:
        return None
    db = get_database()
    user = db.login_details.find_one({"email": payload["email"]})
    if user and user.get("isActive", True):
        return user
    return None

def _fetch_agents_data_sync():
    """Synchronous function to fetch agents data - optimized queries"""
    db = get_database()
    
    logger.info(f"🔍 Fetching agent statistics with optimized queries...")
    
    # Fast counts using aggregation (more efficient than count_documents)
    try:
        product_pipeline = [{"$match": {"eventType": "recommendation"}}, {"$count": "total"}]
        sales_pipeline = [{"$match": {"eventType": "sales_pitch"}}, {"$count": "total"}]
        
        product_result = list(db.dashboarddata.aggregate(product_pipeline, maxTimeMS=5000))
        sales_result = list(db.dashboarddata.aggregate(sales_pipeline, maxTimeMS=5000))
        
        product_recommendations = product_result[0]["total"] if product_result else 0
        sales_pitches = sales_result[0]["total"] if sales_result else 0
    except Exception as e:
        logger.warning(f"   ⚠️ Error counting dashboard data: {e}")
        product_recommendations = 0
        sales_pitches = 0
    
    logger.info(f"   ✓ Product Recommendations: {product_recommendations}")
    logger.info(f"   ✓ Sales Pitches: {sales_pitches}")
    
    # UPDATED: Fetch traces from agent_stats collection (much smaller, faster)
    logger.info(f"🔍 Fetching traces from agent_stats collection (optimized)...")
    try:
        recent_traces = list(db.agent_stats.find(
            {"agentType": {"$in": ["product_recommendation", "sales_pitch"]}},
            {
                "_id": 1,
                "sessionId": 1,
                "agentCode": 1,
                "agentName": 1,
                "agentType": 1,
                "timestamp": 1,
                "totalTokens": 1,
                "llmCalls": 1,
                "hasError": 1,
                "lyzrSessionId": 1  # 🔒 Added for session uniqueness verification
            }
        ).sort("timestamp", -1).limit(200).max_time_ms(5000))
        
        logger.info(f"   ✓ Total traces found: {len(recent_traces)}")
    except Exception as e:
        logger.warning(f"   ⚠️ Error fetching traces from agent_stats: {e}")
        recent_traces = []
    
    # UPDATED: Count errors from agent_stats (faster than regex on messages)
    logger.info(f"🔍 Fetching error stats from agent_stats...")
    try:
        error_count = db.agent_stats.count_documents({
            "hasError": True
        }) or 0
        logger.info(f"   ✓ Error sessions found: {error_count}")
    except Exception as e:
        logger.warning(f"   ⚠️ Error counting errors: {e}")
        error_count = 0
    
    # Process errors (simplified - just count)
    issues = []  # Can be populated from agent_stats.hasError if needed
    
    # Load agent directory with projection
    logger.info(f"🔍 Loading agent directory...")
    agent_directory = []
    try:
        agent_docs = list(db.agents.find(
            {},
            {"_id": 1, "agent_code": 1, "agent_name": 1, "role": 1}
        ).sort("createdAt", -1).limit(100).max_time_ms(5000))
        
        agent_directory = [
            {
                "agentCode": doc.get("agent_code"),
                "agentName": doc.get("agent_name"),
                "role": doc.get("role", "")
            }
            for doc in agent_docs
        ]
        logger.info(f"   ✓ Agents loaded: {len(agent_directory)}")
    except Exception as e:
        logger.warning(f"   ⚠️ Could not load agent directory: {e}")
        agent_directory = []
    
    # UPDATED: Build agents list dynamically from agents collection (not static)
    agents = []
    try:
        # Get all agents from database
        all_agents = list(db.agents.find({}, {
            "_id": 1,
            "agent_code": 1,
            "agent_name": 1,
            "role": 1,
            "is_active": 1
        }).sort("createdAt", -1).limit(100).max_time_ms(5000))
        
        logger.info(f"   ✓ Found {len(all_agents)} agents in database")
        
        # OPTIMIZED: Single aggregation for all agent stats
        try:
            agent_stats_aggregation_pipeline = [
                {
                    "$match": {
                        "agentType": {"$in": ["product_recommendation", "sales_pitch"]}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "agentCode": "$agentCode",
                            "agentType": "$agentType"
                        },
                        "count": {"$sum": 1},
                        "errors": {"$sum": {"$cond": ["$hasError", 1, 0]}}
                    }
                }
            ]
            
            agent_stats_results = list(db.agent_stats.aggregate(
                agent_stats_aggregation_pipeline,
                maxTimeMS=5000
            ))
            
            # Build stats map: {agentCode: {product_recommendation: count, sales_pitch: count, errors: count}}
            agent_stats_map = {}
            for result in agent_stats_results:
                agent_code = result["_id"]["agentCode"]
                agent_type = result["_id"]["agentType"]
                count = result["count"]
                errors = result["errors"]
                
                if agent_code not in agent_stats_map:
                    agent_stats_map[agent_code] = {
                        "product_recommendation": 0,
                        "sales_pitch": 0,
                        "errors": 0
                    }
                
                agent_stats_map[agent_code][agent_type] = count
                agent_stats_map[agent_code]["errors"] = max(agent_stats_map[agent_code]["errors"], errors)
            
            # Build agents list using the map
            for agent in all_agents:
                agent_code = agent.get("agent_code", "")
                agent_name = agent.get("agent_name", "Unknown Agent")
                role = agent.get("role", "").lower()
                is_active = agent.get("is_active", True)
                agent_id = str(agent.get("_id"))
                
                if not agent_code:
                    continue
                
                stats = agent_stats_map.get(agent_code, {
                    "product_recommendation": 0,
                    "sales_pitch": 0,
                    "errors": 0
                })
                
                product_runs = stats["product_recommendation"]
                sales_runs = stats["sales_pitch"]
                error_count_agent = stats["errors"]
                
                # Determine agent type based on role or create entries for both types
                if product_runs > 0 or "product" in role or "recommendation" in role:
                    agents.append({
                        "id": f"{agent_id}_product",
                        "name": f"{agent_name} (Product)",
                        "status": "active" if is_active else "inactive",
                        "runs": product_runs,
                        "errors": error_count_agent,
                        "agentType": "product_recommendation",
                        "agentCode": agent_code,
                        "agentName": agent_name
                    })
                
                if sales_runs > 0 or "sales" in role or "pitch" in role:
                    agents.append({
                        "id": f"{agent_id}_sales",
                        "name": f"{agent_name} (Sales)",
                        "status": "active" if is_active else "inactive",
                        "runs": sales_runs,
                        "errors": error_count_agent,
                        "agentType": "sales_pitch",
                        "agentCode": agent_code,
                        "agentName": agent_name
                    })
        except Exception as e:
            logger.error(f"   ❌ Error aggregating agent stats: {e}", exc_info=True)
            # Fallback to individual queries if aggregation fails
            for agent in all_agents:
                agent_code = agent.get("agent_code", "")
                agent_name = agent.get("agent_name", "Unknown Agent")
                role = agent.get("role", "").lower()
                is_active = agent.get("is_active", True)
                agent_id = str(agent.get("_id"))
                
                if not agent_code:
                    continue
                
                # Count product recommendations for this agent from agent_stats
                product_runs = db.agent_stats.count_documents({
                    "agentCode": agent_code,
                    "agentType": "product_recommendation"
                }) or 0
                
                # Count sales pitches for this agent from agent_stats
                sales_runs = db.agent_stats.count_documents({
                    "agentCode": agent_code,
                    "agentType": "sales_pitch"
                }) or 0
                
                # Count errors for this agent from agent_stats
                error_count_agent = db.agent_stats.count_documents({
                    "agentCode": agent_code,
                    "hasError": True
                }) or 0
                
                # Determine agent type based on role or create entries for both types
                if product_runs > 0 or "product" in role or "recommendation" in role:
                    agents.append({
                        "id": f"{agent_id}_product",
                        "name": f"{agent_name} (Product)",
                        "status": "active" if is_active else "inactive",
                        "runs": product_runs,
                        "errors": error_count_agent,
                        "agentType": "product_recommendation",
                        "agentCode": agent_code,
                        "agentName": agent_name
                    })
            
            if sales_runs > 0 or "sales" in role or "pitch" in role:
                agents.append({
                    "id": f"{agent_id}_sales",
                    "name": f"{agent_name} (Sales)",
                    "status": "active" if is_active else "inactive",
                    "runs": sales_runs,
                    "errors": error_count_agent,
                    "agentType": "sales_pitch",
                    "agentCode": agent_code,
                    "agentName": agent_name
                })
        
        if len(agents) == 0:
            logger.warning("   ⚠️ No agents found in database")
            agents = []
        
        logger.info(f"   ✓ Built {len(agents)} agent entries from database")
    except Exception as e:
        logger.error(f"   ❌ Error building agents list: {e}", exc_info=True)
        agents = []
    
    # UPDATED: Build timeSeries data from agent_stats
    # 🔒 CRITICAL FIX: Use MongoDB aggregation with IST timezone - SAME as Activity Distribution
    # This ensures both Dashboard and Agent Traces display identical counts
    time_series = {"product": {}, "sales": {}}
    try:
        # Use the EXACT same aggregation as Activity Distribution (dashboard.py)
        timeseries_pipeline = [
            {"$match": {
                "$or": [
                    {"timestamp": {"$exists": True}},
                    {"createdAt": {"$exists": True}}
                ],
                "agentType": {"$in": ["product_recommendation", "sales_pitch"]}
            }},
            {"$addFields": {
                "_effectiveDate": {"$ifNull": ["$timestamp", "$createdAt"]}
            }},
            {"$group": {
                "_id": {
                    "date": {"$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$_effectiveDate",
                        "timezone": "+05:30"  # 🔒 IST timezone - MUST match Activity Distribution
                    }},
                    "agentType": "$agentType"
                },
                "count": {"$sum": 1}
            }}
        ]
        
        timeseries_results = list(db.agent_stats.aggregate(timeseries_pipeline, maxTimeMS=5000))
        
        product_by_date = {}
        sales_by_date = {}
        
        for result in timeseries_results:
            date_str = result["_id"]["date"]
            agent_type = result["_id"]["agentType"]
            count = result["count"]
            
            if agent_type == "product_recommendation":
                product_by_date[date_str] = count
            elif agent_type == "sales_pitch":
                sales_by_date[date_str] = count
        
        time_series["product"] = product_by_date
        time_series["sales"] = sales_by_date
        logger.info(f"   ✓ Time series: {len(product_by_date)} product days, {len(sales_by_date)} sales days")
        
    except Exception as e:
        logger.warning(f"Error building time series: {e}")
    
    # UPDATED: Build traces for frontend from agent_stats
    # Create agent lookup map for fast name resolution
    agent_lookup = {}
    try:
        all_agents_for_lookup = list(db.agents.find({}, {
            "agent_code": 1,
            "agent_name": 1
        }).max_time_ms(5000))
        for agent in all_agents_for_lookup:
            agent_code = agent.get("agent_code", "")
            if agent_code:
                agent_lookup[agent_code] = agent.get("agent_name", "")
    except Exception as e:
        logger.warning(f"   ⚠️ Error building agent lookup: {e}")
    
    traces = []
    for trace in recent_traces:
        try:
            session_id = trace.get("sessionId", "")
            agent_code = trace.get("agentCode", "")
            
            # Get exact agent name from database lookup (preferred)
            agent_name = ""
            if agent_code:
                # First try lookup map
                agent_name = agent_lookup.get(agent_code, "")
                # If not found, try agent_directory
                if not agent_name:
                    agent_entry = next((a for a in agent_directory if a.get("agentCode") == agent_code), None)
                    if agent_entry:
                        agent_name = agent_entry.get("agentName", "")
                # If still not found, try username from agent_stats
                if not agent_name:
                    agent_name = trace.get("username", "")
                # Last resort: use stored agentName from trace
                if not agent_name:
                    agent_name = trace.get("agentName", "")
                # Final fallback
                if not agent_name:
                    agent_name = "Unknown Agent"
            
            # Get accurate timestamp: prefer stored timestamp in agent_stats
            timestamp = trace.get("timestamp") or trace.get("updatedAt") or trace.get("createdAt")
            
            # Formatting
            if isinstance(timestamp, datetime):
                # Ensure ISO format
                if timestamp.tzinfo is None:
                    # We are now storing IST naive times, so mark them as +05:30
                    timestamp = timestamp.isoformat() + "+05:30"
                else:
                    timestamp = timestamp.isoformat()
            elif timestamp and isinstance(timestamp, str):
                # If string doesn't look like it has offset/Z, assume it's our stored IST
                if not timestamp.endswith("Z") and "+" not in timestamp:
                    timestamp = timestamp + "+05:30"
            
            # Fallback if still None (rare)
            if not timestamp:
                 # Default to current IST
                 from datetime import timedelta
                 timestamp = (datetime.utcnow() + timedelta(hours=5, minutes=30)).isoformat() + "+05:30"
            
            traces.append({
                "traceId": session_id[:8] if session_id else "unknown",
                "traceRoot": "Product Recommendation" if trace.get("agentType") == "product_recommendation" else "Sales Pitch",
                "totalTokens": trace.get("totalTokens", 0),
                "llmCalls": trace.get("llmCalls", 1),
                "timestamp": timestamp,
                "agentType": trace.get("agentType"),
                "agentCode": agent_code,
                "agentName": agent_name,
                "lyzrSessionId": trace.get("lyzrSessionId", ""),  # 🔒 Added for debugging session uniqueness
                "sessionId": session_id  # 🔒 Full session ID for verification
            })
        except Exception as e:
            logger.debug(f"Error processing trace: {e}")
            continue
    
    return {
        "agents": agents,
        "metrics": {
            "totalRuns": product_recommendations + sales_pitches,
            "totalErrors": error_count
        },
        "issues": issues,
        "agentDirectory": agent_directory,
        "traces": traces,
        "timeSeries": time_series
    }

@router.get("")
async def get_agents_stats(current_user: Optional[dict] = Depends(get_current_user_optional)):
    """Get agent statistics and traces - unified Redis caching (10m TTL)"""
    redis_service = get_redis_service()
    
    # 1. Check Redis Cache
    try:
        cached_data = redis_service.redis_client.get(AGENTS_STATS_CACHE_KEY)
        if cached_data:
            logger.debug(f"✅ REDIS HIT: agents_stats - returning cached data")
            return json.loads(cached_data)
    except Exception as e:
        logger.warning(f"⚠️ Redis read error: {e}")

    logger.info(f"🤖 CACHE MISS: agents_stats - computing fresh data...")
    
    try:
        # 2. Run blocking operation (Source of Truth)
        response = await asyncio.to_thread(
            run_blocking_with_timeout,
            _fetch_agents_data_sync,
            25  # 25 second timeout
        )
        
        logger.info(f"✅ Agents data complete ({len(response['agents'])} agents, {len(response['traces'])} traces)")
        
        # Serialize datetime objects
        response = serialize_datetime(response)
        
        # 3. Store in Redis (Background Task preferred, but blocking here is fast enough for json dump)
        try:
            redis_service.redis_client.setex(
                AGENTS_STATS_CACHE_KEY,
                CACHE_TTL,
                json.dumps(response)
            )
            logger.info(f"✅ Cached agents stats in Redis (TTL {CACHE_TTL}s)")
        except Exception as e:
            logger.warning(f"⚠️ Redis write error: {e}")

        return response
        
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"❌ Error fetching agents: {error}", exc_info=True)
        # Fallback: if aggregation fails, we have no data. Return 500.
        raise HTTPException(status_code=500, detail="Failed to fetch agents")

def trigger_agents_stats_warmup():
    """Proactively trigger agent stats aggregation in background (writes to Redis)"""
    import threading
    
    def _warmup_worker():
        try:
            logger.info("🔄 Pre-warming agents stats (Redis)...")
            response = _fetch_agents_data_sync()
            response = serialize_datetime(response)
            
            redis_service = get_redis_service()
            redis_service.redis_client.setex(
                AGENTS_STATS_CACHE_KEY,
                CACHE_TTL,
                json.dumps(response)
            )
            logger.info("✅ Agents stats pre-warmed in Redis")
        except Exception as e:
            logger.error(f"Error in agents stats warmup: {e}")

    threading.Thread(target=_warmup_worker, daemon=True).start()
