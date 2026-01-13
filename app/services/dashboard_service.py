"""
Service for creating dashboard events in MongoDB
These events trigger real-time updates via WebSocket
"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from app.config.logging_config import get_logger
from datetime import datetime, timedelta
import asyncio
import functools

load_dotenv()

logger = get_logger(__name__)

def get_ist_time():
    """Get current time in Indian Standard Time (IST)"""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

# Import WebSocket manager for real-time updates
def get_websocket_manager():
    """Get WebSocket manager instance"""
    try:
        from app.routes.websocket import get_manager
        return get_manager()
    except Exception as e:
        logger.warning(f"⚠️ Could not import WebSocket manager: {e}")
        return None

# 🔒 Import cache invalidation for real-time updates
def invalidate_cache():
    """Invalidate dashboard cache to ensure fresh data on next poll"""
    try:
        from app.routes.dashboard import invalidate_dashboard_cache
        invalidate_dashboard_cache()
    except Exception as e:
        logger.warning(f"⚠️ Could not invalidate dashboard cache: {e}")

from app.services.redis_service import get_redis_service

class DashboardService:
    """Service for dashboard event tracking"""
    
    def __init__(self):
        # Prioritize MONGODB_URI, then MONGODB_URI
        mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/star_health"
        logger.info(f"🔌 Connecting to MongoDB for dashboard events")
        
        try:
            self.mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.mongo_client.admin.command('ping')
            logger.info("✅ MongoDB connection successful")
        except Exception as e:
            # Don't raise here - allow application to start in degraded mode
            logger.error(f"❌ MongoDB connection failed: {e}")
            logger.warning("⚠️ Starting without MongoDB - dashboard events will be disabled until connection is restored")
            self.mongo_client = None
            self.db = None
            self.dashboard_data = None
            self.available = False
            self.redis_service = None
            return
        
        # Get database name from URI or use default
        db_name = "Star_Health_Whatsapp_bot"  # Default database name
        
        # Try to extract database name from URI
        try:
            if "/" in mongo_uri:
                parts = mongo_uri.split("/")
                if len(parts) > 3:
                    potential_db = parts[-1].split("?")[0]
                    if potential_db and potential_db.strip():
                        db_name = potential_db.strip()
                elif len(parts) == 3:
                    potential_db = parts[-1].split("?")[0]
                    if potential_db and potential_db.strip():
                        db_name = potential_db.strip()
        except Exception as e:
            logger.warning(f"⚠️ Could not extract database name from URI, using default: {e}")
        
        if not db_name or db_name == "":
            db_name = "Star_Health_Whatsapp_bot"
        
        logger.info(f"📚 Using database: {db_name}")
        self.db = self.mongo_client[db_name]
        self.dashboard_data = self.db.dashboarddata
        self.available = True
        
        # Initialize Redis Service for cache invalidation
        try:
            self.redis_service = get_redis_service()
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize RedisService: {e}")
            self.redis_service = None

        logger.info(f"✅ DashboardService initialized")

    def _ensure_connection(self):
        """Lazy reconnection if initial connection failed"""
        if self.available:
            return True
        
        # Try to reconnect
        try:
            from app.config.database import get_database, is_mongodb_ready
            if is_mongodb_ready():
                self.db = get_database()
                self.dashboard_data = self.db.dashboarddata
                self.available = True
                logger.info("✅ DashboardService re-connected to MongoDB")
                return True
        except Exception as e:
            # Silent fail to avoid log spam, relied on main init logs
            pass
        pass
        return False
    
    async def _run_db(self, func, *args, **kwargs):
        """Helper to run blocking DB calls in a thread pool"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
    
    async def create_event(self, event_type: str, data: dict):
        """
        Create a dashboard event
        
        event_type: 'new_session', 'recommendation', 'sales_pitch', 'feedback', 'session_end'
        data: Event data dictionary
        """
        logger.info(f"📊 Creating dashboard event: {event_type}")
        logger.debug(f"   Data: {data}")
        
        self._ensure_connection()
        
        if not self.available or self.db is None:
            logger.warning("⚠️ Cannot create dashboard event - MongoDB not available")
            return None

        try:
            ist_now = get_ist_time()
            event = {
                "eventType": event_type,
                "data": data,
                "createdAt": ist_now,
                "timestamp": ist_now.isoformat()
            }
            result = await self._run_db(self.dashboard_data.insert_one, event)
            logger.info(f"✅ Dashboard event created successfully")
            logger.debug(f"   Event ID: {result.inserted_id}")
            logger.debug(f"   Type: {event_type}")
            
            # Emit WebSocket event immediately for real-time updates
            try:
                ws_manager = get_websocket_manager()
                if ws_manager:
                    ws_manager.broadcast_sync({
                        "type": "dashboard:event",
                        "event": {
                            "eventType": event_type,
                            "data": data,
                            "timestamp": ist_now.isoformat()
                        }
                    })
                    logger.debug(f"📡 WebSocket event broadcasted: {event_type}")
            except Exception as e:
                logger.warning(f"⚠️ Could not broadcast WebSocket event: {e}")
            
            return result.inserted_id
        except Exception as e:
            logger.error(f"❌ Error creating dashboard event: {e}", exc_info=True)
            raise
    
    async def create_session_event(self, username: str, agent_code: str):
        """Create new session event"""
        logger.info(f"📊 Creating new session event")
        logger.debug(f"   Username: {username}, Agent Code: {agent_code}")
        
        # Also save/update user in User collection
        try:
            user_collection = self.db.users
            await self._run_db(
                user_collection.update_one,
                {"username": username, "agentCode": agent_code},
                {"$set": {"username": username, "agentCode": agent_code}},
                upsert=True
            )
            logger.debug(f"✅ User saved/updated in User collection")
        except Exception as e:
            logger.warning(f"⚠️ Could not save user: {e}")
        
        await self.create_event("new_session", {
            "username": username,
            "agent_code": agent_code
        })
    
    async def create_recommendation_event(self, session_id: str):
        """Create recommendation completed event"""
        logger.info(f"📊 Creating recommendation event")
        logger.debug(f"   Session ID: {session_id}")
        await self.create_event("recommendation", {
            "session_id": session_id
        })
        
        # 🔒 FIX: Update Feedback record with agentType so counting logic works
        # Counting now relies on db.feedback, so we must tag the conversation there.
        try:
            if self.available and self.db is not None:
                await self._run_db(
                    self.db.feedback.update_one,
                    {"sessionId": session_id},
                    {
                        "$set": {
                            "agentType": "product_recommendation", 
                            "updatedAt": get_ist_time()
                        },
                        "$setOnInsert": {
                            "feedback": "Pending", 
                            "createdAt": get_ist_time(),
                            "timestamp": get_ist_time().isoformat()
                        }
                    },
                    upsert=True
                )
                
                # 🔒 OPTIMIZED: Selective cache invalidation (no KEYS scan)
                # KEYS command blocks Redis and is O(N) - avoid in production
                # Instead, use SWR pattern - let WebSocket trigger frontend refresh
                # The cache will be refreshed on next poll with should_refresh() check

                # Trigger refresh because counts changed
                ws_manager = get_websocket_manager()
                if ws_manager:
                    ws_manager.broadcast_sync({"type": "dashboard:refresh", "reason": "recommendation_event"})
                
                # 📡 REAL-TIME: Notify activity distribution update
                await self.notify_activity_update("product_recommendation", 1)

        except Exception as e:
            logger.warning(f"⚠️ Failed to update feedback agentType for recommendation: {e}")
    
    async def create_sales_pitch_event(self, session_id: str):
        """Create sales pitch delivered event"""
        logger.info(f"📊 Creating sales pitch event")
        logger.debug(f"   Session ID: {session_id}")
        await self.create_event("sales_pitch", {
            "session_id": session_id
        })
        
        # 🔒 FIX: Update Feedback record with agentType
        try:
            if self.available and self.db is not None:
                await self._run_db(
                    self.db.feedback.update_one,
                    {"sessionId": session_id},
                    {
                        "$set": {
                            "agentType": "sales_pitch", 
                            "updatedAt": get_ist_time()
                        },
                        "$setOnInsert": {
                            "feedback": "Pending", 
                            "createdAt": get_ist_time(),
                            "timestamp": get_ist_time().isoformat()
                        }
                    },
                    upsert=True
                )
                
                # 🔒 OPTIMIZED: Selective cache invalidation (no KEYS scan)
                # Let SWR pattern handle cache refresh via WebSocket trigger

                # Trigger refresh
                ws_manager = get_websocket_manager()
                if ws_manager:
                    ws_manager.broadcast_sync({"type": "dashboard:refresh", "reason": "sales_pitch_event"})
                    
                # 📡 REAL-TIME: Notify activity distribution update
                await self.notify_activity_update("sales_pitch", 1)

        except Exception as e:
            logger.warning(f"⚠️ Failed to update feedback agentType for sales pitch: {e}")
    
    async def create_feedback(self, username: str, agent_code: str, agent_type: str, feedback: str, session_id: str = None):
        """
        Create or update feedback entry for a session.

        - If a feedback record for this session already exists, it will be updated.
        - Otherwise, a new record is inserted.
        - Dashboard "feedback" + "session_end" events are created on first insert OR when feedback changes from "Pending" to actual feedback.
        """
        logger.info(f"📊 Creating/updating feedback")
        logger.info(f"   📋 Session ID: {session_id}")
        logger.info(f"   👤 Username: {username}, Agent Code: {agent_code}")
        logger.info(f"   💬 Feedback: {feedback[:50]}..." if len(feedback) > 50 else f"   💬 Feedback: {feedback}")
        
        self._ensure_connection()
        
        if not self.available or self.db is None:
            logger.warning("⚠️ Cannot create feedback - MongoDB not available")
            return None

        # 🔒 FIX: Validate session_id
        if not session_id or session_id.strip() == "":
            logger.error("❌ Cannot create feedback - session_id is empty or None")
            return None

        try:
            feedback_collection = self.db.feedback
            ist_now = get_ist_time()

            # 🛠️ ENFORCED: Single Conversation Record per Session
            # We strictly update the record by sessionId to ensure 1 session = 1 conversation.
            
            update_data = {
                "username": username,
                "agentCode": agent_code,
                "agentType": agent_type,
                "feedback": feedback,
                "updatedAt": ist_now,
                "timestamp": ist_now.isoformat()
            }

            # 🔒 FIX: Debug logging to trace feedback update issues
            existing_doc = await self._run_db(
                feedback_collection.find_one,
                {"sessionId": session_id}
            )
            
            if existing_doc:
                logger.info(f"   📝 Found existing record:")
                logger.info(f"      - ID: {existing_doc.get('_id')}")
                logger.info(f"      - Current feedback: {existing_doc.get('feedback', 'N/A')}")
                logger.info(f"      - New feedback: {feedback}")
            else:
                logger.info(f"   🆕 No existing record found, will create new")
            
            was_pending = existing_doc and existing_doc.get("feedback") in ["Pending", "incomplete"]
            is_new = existing_doc is None

            # Prepare update operation
            update_op = {"$set": update_data}
            
            # PUSH to history only if it's actual feedback (not pending/incomplete)
            if feedback not in ["Pending", "incomplete"]:
                update_op["$push"] = {"feedback_history": feedback}

            # Upsert the feedback record based on sessionId
            # 🔒 FIX: Ensure createdAt is set on insert (critical for ordering)
            update_op["$setOnInsert"] = {
                "createdAt": ist_now,
                "sessionId": session_id  # 🔒 Also ensure sessionId is set on insert
            }
            
            result = await self._run_db(
                feedback_collection.update_one,
                {"sessionId": session_id},
                update_op,
                upsert=True
            )
            
            # 🔒 FIX: Log detailed result
            logger.info(f"✅ Feedback upsert result for session: {session_id}")
            logger.info(f"   - matched_count: {result.matched_count}")
            logger.info(f"   - modified_count: {result.modified_count}")
            logger.info(f"   - upserted_id: {result.upserted_id}")
            
            # Logic for creating events
            # Trigger if it's a new record OR if we are transitioning from Pending/Incomplete to actual feedback
            if is_new or (was_pending and feedback not in ["Pending", "incomplete"]):

                # Only create dashboard + session_end events on first insert or when moving from pending
                await self.create_event(
                    "feedback",
                    {
                        "username": username,
                        "agent_code": agent_code,
                        "agent_type": agent_type,
                        "feedback": feedback,
                        "session_id": session_id,
                    },
                )

                await self.create_session_end_event(
                    session_id=session_id,
                    username=username,
                    agent_code=agent_code,
                    agent_type=agent_type
                )
                
            elif was_pending and feedback != "Pending" and feedback != "incomplete":
                # Feedback was updated from "Pending" to actual feedback
                logger.info(f"✅ Feedback updated from 'Pending' to actual feedback for session: {session_id}")
                
                # Check if session_end event already exists
                existing_session_end = await self._run_db(
                    self.dashboard_data.find_one,
                    {
                        "eventType": "session_end",
                        "data.session_id": session_id
                    }
                )
                
                if not existing_session_end:
                    # Create session_end event if it doesn't exist
                    await self.create_session_end_event(
                        session_id=session_id,
                        username=username,
                        agent_code=agent_code,
                        agent_type=agent_type
                    )
                    logger.info(f"✅ Session end event created for updated feedback")
            else:
                logger.info(f"✅ Feedback updated for session: {session_id}")

            # 🔒 CACHE INVALIDATION: Ensure fresh data on next poll
            invalidate_cache()
            
            # 🔒 OPTIMIZED: WebSocket refresh to notify frontend
            try:
                ws_manager = get_websocket_manager()
                if ws_manager:
                    ws_manager.broadcast_sync({
                        "type": "dashboard:refresh",
                        "reason": "feedback_updated"
                    })
                    logger.debug(f"📡 WebSocket refresh broadcasted: feedback_updated")
            except Exception as e:
                logger.warning(f"⚠️ Could not broadcast WebSocket refresh: {e}")

        except Exception as e:
            logger.error(f"❌ Error creating/updating feedback: {e}", exc_info=True)

    async def create_feedback_placeholder(self, username: str, agent_code: str, agent_type: str, session_id: str = None):
        """
        Create a NEW placeholder feedback entry (each interaction gets its own record).
        This enables accurate tracking of multiple conversations in one session.
        """
        logger.info(f"📊 Inserting new feedback placeholder for session: {session_id}")
        
        self._ensure_connection()
        if not self.available or self.db is None:
            return None

        try:
            ist_now = get_ist_time()
            # 🛠️ ENFORCED: Single Conversation Record per Session
            # Only create/update placeholder if it doesn't exist.
            # Use upsert with $setOnInsert to strictly avoid duplicates.
            
            result = await self._run_db(
                self.db.feedback.update_one,
                {"sessionId": session_id},
                {
                    "$setOnInsert": {
                        "username": username,
                        "agentCode": agent_code,
                        "agentType": agent_type,
                        "feedback": "Pending",
                        "createdAt": ist_now
                    },
                    "$set": {
                        "updatedAt": ist_now,
                        "timestamp": ist_now.isoformat()
                    }
                },
                upsert=True
            )
            logger.info(f"✅ Feedback placeholder upserted for session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error creating feedback placeholder: {e}")
            return None
    
    async def create_session_end_event(self, session_id: str, username: str = None, agent_code: str = None, agent_type: str = None):
        """Create session end event (conversation complete)"""
        logger.info(f"📊 Creating session end event")
        logger.debug(f"   Session ID: {session_id}, Username: {username}, Agent Code: {agent_code}, Type: {agent_type}")
        await self.create_event("session_end", {
            "session_id": session_id,
            "username": username,
            "agent_code": agent_code,
            "agent_type": agent_type
        })
        
        # Track repeat users only if both username and agent_code are provided
        if username and agent_code:
            await self.track_repeat_user(username, agent_code)
        else:
            logger.warning(f"⚠️ Cannot track repeat user - missing username or agent_code (username: {username}, agent_code: {agent_code})")
    
    async def create_incomplete_conversation_event(self, session_id: str, username: str = None, agent_code: str = None, agent_type: str = None):
        """Create incomplete conversation event (user left without feedback)"""
        logger.info(f"📊 Creating incomplete conversation event")
        logger.info(f"   Session ID: {session_id}, Username: {username}, Agent Code: {agent_code}, Agent Type: {agent_type}")
        
        # Create the dashboard event
        event_id = await self.create_event("incomplete_conversation", {
            "session_id": session_id,
            "username": username,
            "agent_code": agent_code,
            "agent_type": agent_type
        })
        logger.info(f"✅ Incomplete conversation event created in DashboardData")
        
        # Emit WebSocket update event with only relevant fields (totalConversations and incompleteConversations)
        # Do NOT update feedbackCount or completedConversations for incomplete conversations
        try:
            ws_manager = get_websocket_manager()
            if ws_manager and self.available and self.db is not None:
                # Calculate only the fields that should be updated for incomplete conversations
                incomplete_conversations = await self._run_db(self.dashboard_data.count_documents, {"eventType": "incomplete_conversation"})
                completed_conversations = await self._run_db(self.dashboard_data.count_documents, {"eventType": "session_end"})
                total_conversations = completed_conversations + incomplete_conversations
                
                # Send targeted update with only conversation-related fields
                ws_manager.broadcast_sync({
                    "type": "dashboard:update",
                    "incompleteConversations": incomplete_conversations,
                    "totalConversations": total_conversations,
                    "updateType": "incomplete_conversation"  # Flag to indicate this is an incomplete conversation update
                })
                logger.debug(f"📡 WebSocket update broadcasted: incomplete_conversation (total: {total_conversations}, incomplete: {incomplete_conversations})")
        except Exception as e:
            logger.warning(f"⚠️ Could not broadcast WebSocket update: {e}")
        
        # Also save to Feedback collection with status "incomplete"
        logger.info(f"💾 Saving incomplete conversation to Feedback collection...")
        logger.info(f"   MongoDB available: {self.available}, DB: {self.db is not None}")
        if self.available and self.db is not None:
            try:
                feedback_collection = self.db.feedback
                ist_now = get_ist_time()
                
                # 🛠️ OPTION B: Find the MOST RECENT record for this session
                # Only create if it doesn't exist (don't overwrite actual feedback)
                existing_feedback = await self._run_db(
                    feedback_collection.find_one,
                    {"sessionId": session_id},
                    sort=[("createdAt", -1)]
                )
                
                # Only create if it doesn't exist (don't overwrite actual feedback)
                if not existing_feedback:
                    # Ensure agent_type is valid (product_recommendation or sales_pitch)
                    # If agent_type is None or invalid, default to product_recommendation
                    valid_agent_type = agent_type if agent_type in ["product_recommendation", "sales_pitch"] else "product_recommendation"
                    
                    feedback_doc = {
                        "username": username or "Unknown",
                        "agentCode": agent_code or "N/A",
                        "agentType": valid_agent_type,
                        "feedback": "incomplete",  # Mark as incomplete conversation
                        "sessionId": session_id,
                        "conversationStatus": "incomplete",  # Additional field for status
                        "createdAt": ist_now,
                        "updatedAt": ist_now,
                        "timestamp": ist_now.isoformat()
                    }
                    
                    result = await self._run_db(feedback_collection.insert_one, feedback_doc)
                    logger.info(f"✅ Incomplete conversation saved to Feedback collection: {result.inserted_id}")
                else:
                    # If feedback exists but is "Pending", update it to "incomplete"
                    if existing_feedback.get("feedback") == "Pending":
                        await self._run_db(
                            feedback_collection.update_one,
                            {"sessionId": session_id},
                            {
                                "$set": {
                                    "feedback": "incomplete",
                                    "conversationStatus": "incomplete",
                                    "updatedAt": ist_now,
                                    "timestamp": ist_now.isoformat()
                                }
                            }
                        )
                        logger.info(f"✅ Updated pending feedback to incomplete for session: {session_id}")
                    else:
                        # For any other case where feedback exists but is empty or needs status update
                        # Update the conversation status to incomplete
                        existing_status = existing_feedback.get("conversationStatus", "")
                        existing_feedback_text = existing_feedback.get("feedback", "").strip()
                        
                        # Only update if status is not already "incomplete" or "completed"
                        if existing_status not in ["incomplete", "completed"] and not existing_feedback_text:
                            await self._run_db(
                                feedback_collection.update_one,
                                {"sessionId": session_id},
                                {
                                    "$set": {
                                        "conversationStatus": "incomplete",
                                        "updatedAt": ist_now,
                                        "timestamp": ist_now.isoformat()
                                    }
                                }
                            )
                            logger.info(f"✅ Updated conversation status to incomplete for session: {session_id}")
                        else:
                            logger.info(f"   Feedback already exists with status '{existing_status}' for session {session_id}, not overwriting")
            except Exception as e:
                logger.error(f"❌ Error saving incomplete conversation to Feedback collection: {e}", exc_info=True)
    
    async def track_repeat_user(self, username: str, agent_code: str):
        """Track and store repeat users in Repeat_users collection"""
        if not self.available or self.db is None:
            logger.warning("⚠️ Cannot track repeat user - MongoDB not available")
            return
        
        # Validate inputs
        if not username or not agent_code:
            logger.warning(f"⚠️ Cannot track repeat user - missing username or agent_code (username: {username}, agent_code: {agent_code})")
            return
        
        try:
            # Use 'Repeat_users' collection name (capital R, underscore, lowercase users)
            repeat_users_collection = self.db['Repeat_users']
            ist_now = get_ist_time()
            
            logger.info(f"🔄 Tracking repeat user: {username} ({agent_code})")
            
            # Check if user already exists in repeat_users collection
            existing_user = repeat_users_collection.find_one({
                "username": username,
                "agentCode": agent_code
            })
            
            if existing_user:
                # User already exists - increment session count and update last session date
                current_count = existing_user.get("sessionCount", 1)
                await self._run_db(
                    repeat_users_collection.update_one,
                    {"username": username, "agentCode": agent_code},
                    {
                        "$inc": {"sessionCount": 1},
                        "$set": {
                            "lastSessionDate": ist_now,
                            "updatedAt": ist_now
                        }
                    }
                )
                logger.info(f"✅ Repeat user updated: {username} ({agent_code}) - Session count: {current_count} -> {current_count + 1}")
            else:
                # User doesn't exist - check if they have multiple sessions
                # Try multiple query patterns to count new_session events for this user
                # Handle both snake_case (agent_code) and camelCase (agentCode) field names
                session_count = 0
                
                # Try snake_case first (standard format)
                try:
                    session_count = await self._run_db(
                        self.dashboard_data.count_documents,
                        {
                            "eventType": "new_session",
                            "$or": [
                                {"data.agent_code": agent_code, "data.username": username},
                                {"data.agentCode": agent_code, "data.username": username},
                                {"data.agent_code": agent_code, "data.userName": username}
                            ]
                        }
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Error counting sessions with snake_case, trying alternative: {e}")
                    # Fallback: try with exact match
                    try:
                        session_count = await self._run_db(
                            self.dashboard_data.count_documents,
                            {
                                "eventType": "new_session",
                                "data.agent_code": agent_code,
                                "data.username": username
                            }
                        )
                    except Exception as e2:
                        logger.error(f"❌ Error counting sessions: {e2}")
                        session_count = 0
                
                logger.info(f"   Found {session_count} new_session events for {username} ({agent_code})")
                
                # If user has 2 or more sessions, they are a repeat user
                if session_count >= 2:
                    # Get first session date from dashboarddata
                    first_session = None
                    try:
                        first_session = await self._run_db(
                            self.dashboard_data.find_one,
                            {
                                "eventType": "new_session",
                                "$or": [
                                    {"data.agent_code": agent_code, "data.username": username},
                                    {"data.agentCode": agent_code, "data.username": username}
                                ]
                            },
                            sort=[("createdAt", 1)]  # Sort ascending to get first session
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Error finding first session: {e}")
                    
                    first_session_date = first_session.get("createdAt", ist_now) if first_session else ist_now
                    
                    # Create repeat user record
                    repeat_user_doc = {
                        "username": username,
                        "agentCode": agent_code,
                        "sessionCount": session_count,
                        "firstSessionDate": first_session_date,
                        "lastSessionDate": ist_now,
                        "createdAt": ist_now,
                        "updatedAt": ist_now,
                        "timestamp": ist_now.isoformat()
                    }
                    try:
                        await self._run_db(repeat_users_collection.insert_one, repeat_user_doc)
                        logger.info(f"✅ Repeat user stored: {username} ({agent_code}) - {session_count} sessions")
                    except Exception as e:
                        logger.error(f"❌ Error inserting repeat user: {e}", exc_info=True)
                else:
                    logger.debug(f"   User {username} ({agent_code}) has only {session_count} session(s) - not a repeat user yet")
        except Exception as e:
            logger.error(f"❌ Error tracking repeat user: {e}", exc_info=True)

    async def notify_activity_update(self, agent_type: str, llm_calls: int = 1):
        """
        Notify frontend of new activity (LLM calls) for real-time chart updates
        """
        try:
            ws_manager = get_websocket_manager()
            if ws_manager:
                ist_now = get_ist_time()
                ws_manager.broadcast_sync({
                    "type": "dashboard:activity_update",
                    "data": {
                        "agentType": agent_type,
                        "llmCalls": llm_calls,
                        "timestamp": ist_now.isoformat()
                    }
                })
                logger.debug(f"📡 WebSocket activity update broadcasted for {agent_type}")
        except Exception as e:
            logger.warning(f"⚠️ Could not broadcast activity update: {e}")
