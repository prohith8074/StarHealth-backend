import httpx
from httpx import ConnectError, TimeoutException
import os
from dotenv import load_dotenv
import asyncio
import json
from datetime import datetime
import uuid
# from app.services.redis_service import RedisService  # COMMENTED OUT - Using Lyzr built-in context
from app.config.logging_config import get_logger
from app.config.database import get_database

load_dotenv()

logger = get_logger(__name__)

# In-memory storage for Lyzr session IDs (simple dict) - fallback cache
# Key: f"{session_id}:{agent_type}", Value: lyzr_session_id
_lyzr_sessions = {}
_lyzr_initialized = set()  # Track which sessions have been initialized

def get_lyzr_session_id_from_db(session_id: str, agent_id: str) -> str:
    """
    Get Lyzr session ID from database for a given session_id and agent_id.
    Returns None if session doesn't exist.
    """
    try:
        db = get_database()
        session_doc = db.lyzr_sessions.find_one({
            "sessionId": session_id,
            "agentId": agent_id,
            "isActive": True
        })
        if session_doc:
            return session_doc.get("lyzrSessionId")
        return None
    except Exception as e:
        logger.warning(f"⚠️ Error getting Lyzr session from DB: {e}")
        return None

def save_lyzr_session_to_db(
    session_id: str,
    agent_id: str,
    lyzr_session_id: str,
    agent_type: str = None,
    agent_code: str = None,
    username: str = None
) -> bool:
    """
    Save or update Lyzr session ID in database.
    Returns True if successful, False otherwise.
    """
    try:
        db = get_database()
        now = datetime.utcnow()
        
        # Upsert: update if exists, insert if new
        db.lyzr_sessions.update_one(
            {
                "sessionId": session_id,
                "agentId": agent_id
            },
            {
                "$set": {
                    "lyzrSessionId": lyzr_session_id,
                    "agentType": agent_type,
                    "agentCode": agent_code,
                    "username": username,
                    "updatedAt": now,
                    "lastMessageAt": now,
                    "isActive": True
                },
                "$setOnInsert": {
                    "createdAt": now
                }
            },
            upsert=True
        )
        logger.debug(f"✅ Lyzr session saved to DB: {session_id[:12]}... -> {lyzr_session_id[:12]}...")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving Lyzr session to DB: {e}", exc_info=True)
        return False

def get_lyzr_session_id(session_id: str, agent_type: str) -> str:
    """
    Get Lyzr session ID for a given session_id and agent_type.
    First checks database, then falls back to in-memory cache.
    Returns None if session doesn't exist.
    """
    # Try to get from database using session_id and agent_type
    try:
        db = get_database()
        session_doc = db.lyzr_sessions.find_one({
            "sessionId": session_id,
            "agentType": agent_type,
            "isActive": True
        })
        if session_doc:
            return session_doc.get("lyzrSessionId")
    except Exception as e:
        logger.debug(f"Error getting Lyzr session from DB: {e}")
    
    # Fallback to in-memory (for backward compatibility during transition)
    session_key = f"{session_id}:{agent_type}"
    return _lyzr_sessions.get(session_key)


def clear_lyzr_session(session_id: str, agent_type: str = None):
    """
    Clear Lyzr session from cache and mark as inactive in DB.
    Used when starting a new conversation after user ends previous one.
    
    Args:
        session_id: Session identifier
        agent_type: Optional agent type. If None, clears all agent types for this session.
    """
    global _lyzr_sessions, _lyzr_initialized
    
    try:
        # Clear from in-memory cache
        if agent_type:
            session_key = f"{session_id}:{agent_type}"
            _lyzr_sessions.pop(session_key, None)
            _lyzr_initialized.discard(session_key)
        else:
            # Clear all agent types for this session
            keys_to_remove = [k for k in _lyzr_sessions.keys() if k.startswith(f"{session_id}:")]
            for key in keys_to_remove:
                _lyzr_sessions.pop(key, None)
                _lyzr_initialized.discard(key)
        
        # Mark as inactive in DB
        db = get_database()
        query = {"sessionId": session_id}
        if agent_type:
            query["agentType"] = agent_type
        
        db.lyzr_sessions.update_many(query, {"$set": {"isActive": False}})
        logger.info(f"✅ Cleared Lyzr session for: {session_id[:12]}... (agent_type={agent_type})")
        
    except Exception as e:
        logger.warning(f"⚠️ Error clearing Lyzr session: {e}")


def clear_lyzr_session_by_key(session_id: str, agent_id: str):
    """
    Clear Lyzr session from memory cache using the session_id:agent_id key format.
    This is used by optimized_call_agent and ensures fresh sessions for new conversations.
    
    Args:
        session_id: The unique_conversation_id (NOT WhatsApp session)
        agent_id: Lyzr agent ID
    """
    global _lyzr_sessions, _lyzr_initialized
    
    session_key = f"{session_id}:{agent_id}"
    
    if session_key in _lyzr_sessions:
        _lyzr_sessions.pop(session_key, None)
        _lyzr_initialized.discard(session_key)
        logger.info(f"🧹 Cleared Lyzr session from memory cache: {session_key[:20]}...")
    else:
        logger.debug(f"📝 No existing Lyzr session in memory for: {session_key[:20]}...")


def log_step(step: str, message: str, data=None):
    """Utility function for timestamped logging (matches daily news agent pattern)"""
    timestamp = datetime.now().isoformat()
    prefix = f"[{timestamp}] [{step}]"
    if data is not None:
        logger.info(f"{prefix} {message}", extra={"data": data})
    else:
        logger.info(f"{prefix} {message}")


def generate_unique_id() -> str:
    """Generate unique ID similar to daily news agent"""
    return str(uuid.uuid4())[:12]


class LyzrService:
    """Service for interacting with Lyzr Agents"""
    
    def __init__(self):
        # Check both naming conventions for API key
        self.api_key = os.getenv("Lyzr_API_KEY") or os.getenv("LYZR_API_KEY")
        self.api_url = os.getenv("LYZR_API_URL", "https://api.lyzr.ai")
        self.product_agent_id = os.getenv("LYZR_PRODUCT_RECOMMENDATION_AGENT_ID")
        self.sales_agent_id = os.getenv("LYZR_SALES_PITCH_AGENT_ID")
        # self.redis_service = RedisService()  # COMMENTED OUT - Using Lyzr built-in context
        
        # Validate configuration
        if not self.api_key:
            logger.warning("⚠️ LYZR_API_KEY not set in environment variables")
        if not self.product_agent_id:
            logger.warning("⚠️ LYZR_PRODUCT_RECOMMENDATION_AGENT_ID not set")
        if not self.sales_agent_id:
            logger.warning("⚠️ LYZR_SALES_PITCH_AGENT_ID not set")
        
        logger.info("LyzrService initialized")
        logger.info(f"   API URL: {self.api_url}")
        logger.info(f"   Product Agent ID: {self.product_agent_id}")
        logger.info(f"   Sales Agent ID: {self.sales_agent_id}")
    
    async def test_connection(self):
        """Test connection to Lyzr API - can be called manually"""
        try:
            async with httpx.AsyncClient() as client:
                # Try to connect to the base API URL
                response = await client.get(
                    self.api_url,
                    timeout=5.0,
                    follow_redirects=True
                )
                logger.info(f"✅ Lyzr API connection test successful (Status: {response.status_code})")
                return {"status": "success", "status_code": response.status_code}
        except ConnectError as e:
            logger.error(f"❌ Cannot connect to Lyzr API: {e}")
            logger.error(f"   Troubleshooting steps:")
            logger.error(f"   1. Check internet connection")
            logger.error(f"   2. Test DNS: ping api.lyzr.ai or nslookup api.lyzr.ai")
            logger.error(f"   3. Check firewall/proxy settings")
            logger.error(f"   4. Verify API URL: {self.api_url}")
            logger.error(f"   5. Try accessing {self.api_url} in a browser")
            return {"status": "error", "error": str(e), "message": "DNS resolution failed"}
        except Exception as e:
            logger.warning(f"⚠️ Connection test failed: {e}")
            return {"status": "error", "error": str(e)}
    
    async def get_agent_id(self, agent_type: str) -> str:
        """
        Get agent ID based on configuration
        Returns customized agent ID if configured, otherwise default
        """
        try:
            from pymongo import MongoClient
            mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/Star_Health_Whatsapp_bot"
            mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            db = mongo_client["Star_Health_Whatsapp_bot"]
            # Read from Prompts collection (one document per agentType)
            prompts_collection = db["Prompts"]
            
            config_type = "product" if agent_type == "product_recommendation" else "sales"
            config = prompts_collection.find_one({"agentType": config_type})
            
            if config and config.get("mode") == "customize":
                # Use customized agent IDs
                if agent_type == "product_recommendation":
                    return "6942d9fd3cc5fbe223b01863"
                else:  # sales_pitch
                    return "6942da32707dd1e4d8ed4b56"
            else:
                # Use default agent IDs
                if agent_type == "product_recommendation":
                    return self.product_agent_id
                else:
                    return self.sales_agent_id
        except Exception as e:
            logger.warning(f"Error getting agent config, using default: {e}")
            # Fallback to default
            if agent_type == "product_recommendation":
                return self.product_agent_id
            else:
                return self.sales_agent_id

    async def get_agent_response(
        self, 
        session_id: str, 
        agent_type: str, 
        message: str,
        username: str = None,
        agent_code: str = None,
        custom_role: str = None,
        custom_goal: str = None,
        custom_instructions: str = None
    ):
        """
        Get response from Lyzr agent with optional customized prompts
        
        Rules:
        - First call: Send ONLY username + agent_code, get session_id
        - Subsequent calls: Send session_id + message + custom prompts (if provided)
        - Custom prompts are sent as context to personalize agent behavior
        
        Args:
            session_id: Session identifier
            agent_type: 'product_recommendation' or 'sales_pitch'
            message: User message
            username: Optional username
            agent_code: Optional agent code
            custom_role: Optional customized role for the agent
            custom_goal: Optional customized goal for the agent
            custom_instructions: Optional customized instructions for the agent
        """
        logger.info("=" * 60)
        logger.info(f"🔗 LYZR AGENT REQUEST")
        logger.info(f"   Session ID: {session_id}")
        logger.info(f"   Agent Type: {agent_type}")
        logger.info(f"   Message: {message[:100]}...")
        logger.info(f"   Username: {username}")
        logger.info(f"   Agent Code: {agent_code}")
        logger.info("=" * 60)
        
        agent_id = await self.get_agent_id(agent_type)
        
        if not agent_id:
            logger.error(f"❌ Agent not configured for type: {agent_type}")
            return "Agent not configured. Please check environment variables."
        
        logger.info(f"✅ Using Agent ID: {agent_id}")
        
        # Check if this is the first call (using in-memory tracking)
        session_key = f"{session_id}:{agent_type}"
        is_first_call = session_key not in _lyzr_initialized
        logger.info(f"📞 First Call: {is_first_call} (using Lyzr built-in context)")
        
        if is_first_call:
            logger.info(f"🆕 FIRST CALL - Creating Lyzr session")
            # First call: Send username, agent_code, AND unique session_id
            # 🔒 FIX: Include session_id to ensure Lyzr creates a truly unique session
            # This prevents context bleeding between different conversations
            payload = {
                "username": username or "User",
                "agent_code": agent_code or "",
                "session_id": session_id  # 🔒 Pass our unique conversation ID to Lyzr
            }
            logger.info(f"📤 Sending to Lyzr API:")
            logger.info(f"   Endpoint: {self.api_url}/agents/{agent_id}/session")
            logger.info(f"   Payload: {payload}")
            logger.info(f"   Our Session ID: {session_id[:12]}...")
            
            try:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    response = await client.post(
                        f"{self.api_url}/agents/{agent_id}/session",
                        json=payload,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        timeout=30.0
                    )
                    
                    logger.info(f"📥 Lyzr API Response:")
                    logger.info(f"   Status Code: {response.status_code}")
                    logger.debug(f"   Response Headers: {dict(response.headers)}")
                    
                    if response.status_code == 200:
                        data = response.json()
                        lyzr_session_id = data.get("session_id")
                        logger.info(f"✅ Lyzr Session Created:")
                        logger.info(f"   Lyzr Session ID: {lyzr_session_id}")
                        logger.info(f"   Our Session ID: {session_id[:12]}...")
                        logger.debug(f"   Full Response: {data}")
                        
                        # Store Lyzr session ID in memory
                        _lyzr_sessions[session_key] = lyzr_session_id
                        _lyzr_initialized.add(session_key)
                        logger.debug(f"💾 Lyzr session ID stored: {lyzr_session_id}")
                        logger.debug(f"✅ First call complete (Lyzr manages context)")
                        
                        # Now send the initial message
                        logger.info(f"📤 Sending initial message to Lyzr...")
                        return await self._send_message_to_lyzr(
                            agent_id, 
                            lyzr_session_id, 
                            message, 
                            session_id,
                            custom_role=custom_role,
                            custom_goal=custom_goal,
                            custom_instructions=custom_instructions
                        )
                    else:
                        # Handle redirects and other errors
                        if response.status_code in [301, 302, 307, 308]:
                            location = response.headers.get("Location") or response.headers.get("location")
                            logger.error(f"❌ API Redirect Error:")
                            logger.error(f"   Status: {response.status_code} (Moved Permanently)")
                            logger.error(f"   Current URL: {self.api_url}")
                            logger.error(f"   Redirect Location: {location}")
                            logger.error(f"   Suggestion: Update LYZR_API_URL in .env file")
                            if location:
                                # Extract base URL from redirect location
                                if location.startswith("http"):
                                    from urllib.parse import urlparse
                                    parsed = urlparse(location)
                                    new_base_url = f"{parsed.scheme}://{parsed.netloc}"
                                    logger.error(f"   Try setting: LYZR_API_URL={new_base_url}")
                                    return f"API endpoint has moved. Please update LYZR_API_URL to: {new_base_url}"
                            return f"API endpoint redirected (301). Check LYZR_API_URL configuration."
                        else:
                            logger.error(f"❌ Lyzr API Error:")
                            logger.error(f"   Status: {response.status_code}")
                            logger.error(f"   Response: {response.text[:500]}")
                            logger.error(f"   URL: {response.url}")
                            return f"Error connecting to agent: {response.status_code}. Check API URL and credentials."
                        
            except ConnectError as e:
                logger.error(f"❌ Connection error to Lyzr API:")
                logger.error(f"   Error: {str(e)}")
                logger.error(f"   This usually means the API URL is incorrect or there's a network issue")
                logger.error(f"   API URL: {self.api_url}")
                return "Error connecting to agent. Please check your network connection and API configuration."
            except TimeoutException as e:
                logger.error(f"❌ Timeout connecting to Lyzr API: {e}")
                return "Agent request timed out. Please try again."
            except Exception as e:
                logger.error(f"❌ Exception in first Lyzr call:", exc_info=True)
                return f"Error connecting to agent: {str(e)}. Please try again."
        else:
            logger.info(f"🔄 SUBSEQUENT CALL - Using existing session")
            # Get stored Lyzr session ID from memory
            session_key = f"{session_id}:{agent_type}"
            lyzr_session_id = _lyzr_sessions.get(session_key)
            logger.info(f"   Stored Lyzr Session ID: {lyzr_session_id}")
            
            if not lyzr_session_id:
                logger.warning(f"⚠️ No stored session ID, creating new session")
                # Fallback: try to create new session
                return await self.get_agent_response(session_id, agent_type, message, username, agent_code)
            
            return await self._send_message_to_lyzr(
                agent_id, 
                lyzr_session_id, 
                message, 
                session_id,
                custom_role=custom_role,
                custom_goal=custom_goal,
                custom_instructions=custom_instructions
            )
    
    async def _send_message_to_lyzr(
        self, 
        agent_id: str, 
        lyzr_session_id: str, 
        message: str, 
        session_id: str,
        custom_role: str = None,
        custom_goal: str = None,
        custom_instructions: str = None
    ):
        """
        Send message to Lyzr agent with optional customized prompts
        
        The custom prompts are included in the message as context to guide agent behavior.
        """
        logger.info(f"📤 Sending message to Lyzr agent")
        logger.debug(f"   Agent ID: {agent_id}")
        logger.debug(f"   Lyzr Session ID: {lyzr_session_id}")
        logger.debug(f"   Message: {message}")
        
        # Build enhanced message with custom prompts if provided
        enhanced_message = message
        if custom_role or custom_goal or custom_instructions:
            logger.info(f"✨ Including customized agent configuration:")
            if custom_role:
                logger.info(f"   Role: {custom_role[:100]}...")
                enhanced_message += f"\n\n[AGENT ROLE]\n{custom_role}"
            if custom_goal:
                logger.info(f"   Goal: {custom_goal[:100]}...")
                enhanced_message += f"\n\n[AGENT GOAL]\n{custom_goal}"
            if custom_instructions:
                logger.info(f"   Instructions: {custom_instructions[:100]}...")
                enhanced_message += f"\n\n[AGENT INSTRUCTIONS]\n{custom_instructions}"
        else:
            logger.info(f"📚 Using Lyzr built-in context (no custom prompts)")
        
        payload = {
            "session_id": lyzr_session_id,
            "message": enhanced_message,
        }
        
        logger.info(f"📤 POST Request to Lyzr:")
        logger.info(f"   URL: {self.api_url}/agents/{agent_id}/chat")
        logger.debug(f"   Payload message length: {len(enhanced_message)} characters")
        
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.post(
                    f"{self.api_url}/agents/{agent_id}/chat",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=30.0
                )
                
                logger.info(f"📥 Lyzr API Response:")
                logger.info(f"   Status Code: {response.status_code}")
                logger.debug(f"   Response Headers: {dict(response.headers)}")
                
                if response.status_code == 200:
                    data = response.json()
                    agent_response = data.get("response", "No response from agent")
                    logger.info(f"✅ Lyzr Agent Response:")
                    logger.info(f"   Length: {len(agent_response)} characters")
                    logger.info(f"   Preview: {agent_response[:200]}...")
                    logger.debug(f"   Full Response: {data}")
                    return agent_response
                else:
                    # Handle redirects and other errors
                    if response.status_code in [301, 302, 307, 308]:
                        location = response.headers.get("Location") or response.headers.get("location")
                        logger.error(f"❌ API Redirect Error:")
                        logger.error(f"   Status: {response.status_code} (Moved Permanently)")
                        logger.error(f"   Current URL: {self.api_url}")
                        logger.error(f"   Redirect Location: {location}")
                        if location:
                            from urllib.parse import urlparse
                            parsed = urlparse(location)
                            new_base_url = f"{parsed.scheme}://{parsed.netloc}"
                            logger.error(f"   Try setting: LYZR_API_URL={new_base_url}")
                            return f"API endpoint has moved. Please update LYZR_API_URL to: {new_base_url}"
                        return f"API endpoint redirected (301). Check LYZR_API_URL configuration."
                    else:
                        logger.error(f"❌ Lyzr API Error:")
                        logger.error(f"   Status: {response.status_code}")
                        logger.error(f"   Response: {response.text[:500]}")
                        logger.error(f"   URL: {response.url}")
                        return f"Error from agent: {response.status_code}. Check API URL and credentials."
                    
        except ConnectError as e:
            logger.error(f"❌ Connection error to Lyzr API:")
            logger.error(f"   Error: {str(e)}")
            logger.error(f"   API URL: {self.api_url}")
            return "Error connecting to agent. Please check your network connection and API configuration."
        except TimeoutException as e:
            logger.error(f"❌ Timeout connecting to Lyzr API: {e}")
            return "Agent request timed out. Please try again."
        except Exception as e:
            logger.error(f"❌ Exception sending message to Lyzr:", exc_info=True)
            return f"Error communicating with agent: {str(e)}. Please try again."

    # ==========================================
    # NEW: Advanced Call-and-Poll Pattern (Daily News Agent approach)
    # ==========================================
    
    async def call_agent_with_polling(
        self,
        agent_id: str,
        message: str,
        session_id: str = None,
        user_id: str = None,
        poll_interval: int = 2000,
        max_attempts: int = 60,
        api_url: str = None
    ):
        """
        Advanced agent call with explicit polling - matches daily news agent pattern.
        
        This is more reliable than implicit session-based calls:
        - Single unified endpoint
        - Session ID returned in response
        - Explicit polling for results
        - Better error handling and retry logic
        
        Args:
            agent_id: Lyzr agent ID
            message: User message/instruction
            session_id: Optional session ID (generated if not provided)
            user_id: User identifier
            poll_interval: Milliseconds to wait between polls (default 2000ms)
            max_attempts: Max polling attempts (default 60 = 2 minutes)
            api_url: Override API URL (defaults to https://agent-prod.studio.lyzr.ai/v3/inference/chat/)
        
        Returns:
            Response from agent (parsed JSON if possible, string otherwise)
        """
        # Use production endpoint as default (matching daily news agent)
        endpoint_url = api_url or "https://agent-prod.studio.lyzr.ai/v3/inference/chat/"
        session_id = session_id or f"{agent_id}-{generate_unique_id()}"
        user_id = user_id or "bot_user"
        
        start_time = datetime.now()
        log_step("CALL_AGENT", "▶️ START - Initiating API call to Lyzr agent", {
            "agent_id": agent_id,
            "session_id": session_id[-12:],
            "message_length": len(message)
        })
        
        # Step 1: Make initial agent call
        log_step("CALL_AGENT", "🔄 Attempt 1/3 - Sending POST request...")
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    endpoint_url,
                    json={
                        "user_id": user_id,
                        "agent_id": agent_id,
                        "session_id": session_id,
                        "message": message
                    },
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": self.api_key
                    }
                )
                
                elapsed = (datetime.now() - start_time).total_seconds()
                
                # Check for error status codes FIRST - before any JSON parsing
                if response.status_code >= 400:
                    error_msg = f"Lyzr API returned {response.status_code}"
                    logger.error(f"❌ {error_msg}")
                    
                    # Try to get response text safely
                    try:
                        response_text = response.text[:500] if response.text else "No response body"
                        logger.error(f"   Response text: {response_text}")
                    except:
                        response_text = "Unable to read response"
                    
                    # Provide user-friendly error messages based on status code
                    if response.status_code == 502:
                        user_message = "The AI service is temporarily unavailable. Please try again in a moment."
                    elif response.status_code == 503:
                        user_message = "The AI service is currently overloaded. Please try again shortly."
                    elif response.status_code == 504:
                        user_message = "The AI service request timed out. Please try again."
                    elif response.status_code >= 500:
                        user_message = "The AI service encountered an error. Please try again."
                    elif response.status_code == 401:
                        user_message = "Authentication failed. Please check API credentials."
                    elif response.status_code == 403:
                        user_message = "Access denied. Please check API permissions."
                    elif response.status_code == 404:
                        user_message = "Agent not found. Please check agent ID configuration."
                    else:
                        user_message = f"Request failed with status {response.status_code}. Please try again."
                    
                    logger.error(f"   User-friendly message: {user_message}")
                    
                    if response.status_code >= 500:
                        logger.error(f"   Server error - Lyzr API might be temporarily unavailable")
                    
                    return {
                        "error": error_msg,
                        "status": "failed",
                        "status_code": response.status_code,
                        "user_message": user_message,
                        "retry": True if response.status_code >= 500 else False
                    }
                
                # Only log success if status is OK
                log_step("CALL_AGENT", f"✅ END - API call successful in {elapsed:.2f}s", {
                    "status": response.status_code,
                    "session_id": session_id[-12:]
                })
                
                # Parse JSON response - only if status is OK
                try:
                    # Check if response has content before parsing
                    if not response.text or len(response.text.strip()) == 0:
                        logger.warning(f"⚠️ Empty response from Lyzr API")
                        return {
                            "error": "Empty response from agent",
                            "status": "failed",
                            "user_message": "The agent returned an empty response. Please try again."
                        }
                    
                    response_data = response.json()
                except ValueError as e:
                    # JSON parsing error
                    logger.error(f"❌ Failed to parse Lyzr response as JSON: {e}")
                    logger.error(f"   Response status: {response.status_code}")
                    logger.error(f"   Response text (first 500 chars): {response.text[:500] if response.text else 'None'}")
                    return {
                        "error": f"Invalid response format: {str(e)}",
                        "status": "failed",
                        "user_message": "The agent returned an invalid response. Please try again."
                    }
                except Exception as e:
                    logger.error(f"❌ Unexpected error parsing response: {e}", exc_info=True)
                    return {
                        "error": f"Unexpected error: {str(e)}",
                        "status": "failed",
                        "user_message": "An unexpected error occurred. Please try again."
                    }
                
                # Check if response already contains the result (no polling needed)
                if response_data.get("response"):
                    log_step("CALL_AGENT", "🎉 Response received immediately (no polling needed)")
                    return await self._parse_agent_response(response_data.get("response"))
                
                # Extract session ID from response (prefer API's session_id)
                returned_session_id = response_data.get("session_id") or session_id
                
                # Step 2: Poll for results
                log_step("CALL_AGENT", f"📥 Step 2/2: Polling for results using session ID: {returned_session_id[-12:]}...", {
                    "poll_interval": f"{poll_interval}ms",
                    "max_attempts": max_attempts
                })
                
                result = await self._poll_agent_results(
                    endpoint_url=endpoint_url,
                    agent_id=agent_id,
                    session_id=returned_session_id,
                    user_id=user_id,
                    poll_interval=poll_interval,
                    max_attempts=max_attempts
                )
                
                total_elapsed = (datetime.now() - start_time).total_seconds()
                log_step("CALL_AGENT", f"✅ END - Agent processing complete in {total_elapsed:.2f}s")
                
                return result
                
        except httpx.HTTPError as e:
            log_step("CALL_AGENT", f"❌ HTTP Error: {str(e)}")
            return {
                "error": str(e),
                "status": "failed",
                "user_message": "Network error connecting to AI service. Please check your connection and try again."
            }
        except Exception as e:
            log_step("CALL_AGENT", f"❌ Exception: {str(e)}")
            return {
                "error": str(e),
                "status": "failed",
                "user_message": "An unexpected error occurred. Please try again."
            }
    
    async def _poll_agent_results(
        self,
        endpoint_url: str,
        agent_id: str,
        session_id: str,
        user_id: str,
        poll_interval: int = 2000,
        max_attempts: int = 60
    ):
        """
        Poll Lyzr agent for results with explicit retry logic.
        
        Pattern:
        1. Send empty message with session_id to check status
        2. If response field present → return results
        3. If status = processing → continue polling
        4. If status = failed → throw error
        """
        start_time = datetime.now()
        log_step("POLL_AGENT", f"▶️ START - Beginning polling for agent results", {
            "agent_id": agent_id,
            "max_attempts": max_attempts,
            "poll_interval": f"{poll_interval}ms"
        })
        
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        for attempt in range(max_attempts):
            if attempt > 0:
                await asyncio.sleep(poll_interval / 1000.0)  # Convert ms to seconds
            
            elapsed = (datetime.now() - start_time).total_seconds()
            
            try:
                log_step("POLL_AGENT", f"🔄 Poll #{attempt + 1}/{max_attempts} ({elapsed:.1f}s elapsed)")
                
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        endpoint_url,
                        json={
                            "user_id": user_id,
                            "agent_id": agent_id,
                            "session_id": session_id,
                            "message": ""  # Empty message = poll for results
                        },
                        headers={
                            "Content-Type": "application/json",
                            "x-api-key": self.api_key
                        }
                    )
                
                # Check for error status codes in polling
                if response.status_code >= 400:
                    error_msg = f"Polling request failed with status {response.status_code}"
                    logger.error(f"❌ {error_msg}")
                    
                    if response.status_code >= 500:
                        # Server error - might be temporary, continue polling for a few more attempts
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            logger.error(f"   Too many consecutive errors ({consecutive_errors}), stopping polling")
                            return {
                                "error": "Agent service unavailable after multiple attempts",
                                "status": "failed",
                                "user_message": "The AI service is temporarily unavailable. Please try again in a moment."
                            }
                        logger.warning(f"   Server error (attempt {consecutive_errors}/{max_consecutive_errors}), will retry...")
                        continue
                    else:
                        # Client error - stop polling
                        logger.error(f"   Client error - stopping polling")
                        return {
                            "error": error_msg,
                            "status": "failed",
                            "user_message": "Request failed. Please try again."
                        }
                
                consecutive_errors = 0
                
                # Parse JSON response safely
                try:
                    data = response.json() if response.text else {}
                except ValueError as e:
                    logger.error(f"❌ Failed to parse polling response: {e}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        return {
                            "error": "Invalid response format from agent",
                            "status": "failed",
                            "user_message": "The agent returned an invalid response. Please try again."
                        }
                    continue
                except Exception as e:
                    logger.error(f"❌ Unexpected error parsing polling response: {e}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        return {
                            "error": f"Unexpected error: {str(e)}",
                            "status": "failed",
                            "user_message": "An unexpected error occurred. Please try again."
                        }
                    continue
                
                # Check primary response field
                if data.get("response"):
                    total_elapsed = (datetime.now() - start_time).total_seconds()
                    log_step("POLL_AGENT", f"✅ END - Results received after {total_elapsed:.2f}s ({attempt + 1} polls)")
                    return await self._parse_agent_response(data.get("response"))
                
                # Check alternative response fields
                for alt_field in ["result", "output", "message", "content", "data"]:
                    if data.get(alt_field):
                        total_elapsed = (datetime.now() - start_time).total_seconds()
                        log_step("POLL_AGENT", f"✅ END - Found response in '{alt_field}' field after {total_elapsed:.2f}s")
                        return await self._parse_agent_response(data.get(alt_field))
                
                # Check for failure status
                if data.get("status") == "failed" or data.get("error"):
                    error_msg = data.get('error') or data.get('message') or "Agent failed"
                    log_step("POLL_AGENT", f"❌ Agent reported failure: {error_msg}")
                    return {
                        "error": error_msg,
                        "status": "failed",
                        "user_message": "The agent encountered an error. Please try again."
                    }
                
                # Progress logging every 5 polls
                if attempt > 0 and attempt % 5 == 0:
                    log_step("POLL_AGENT", f"⏳ Still waiting... ({elapsed:.1f}s, poll {attempt + 1}/{max_attempts})")
                
            except httpx.HTTPError as e:
                consecutive_errors += 1
                log_step("POLL_AGENT", f"⚠️ Poll error #{consecutive_errors}: {str(e)}")
                
                if consecutive_errors >= max_consecutive_errors:
                    log_step("POLL_AGENT", f"❌ END - Failed after {max_consecutive_errors} consecutive errors")
                    return {
                        "error": str(e),
                        "status": "failed",
                        "user_message": "Network error connecting to AI service. Please check your connection and try again."
                    }
                
                continue
            except Exception as e:
                consecutive_errors += 1
                log_step("POLL_AGENT", f"⚠️ Poll error #{consecutive_errors}: {str(e)}")
                
                if consecutive_errors >= max_consecutive_errors:
                    log_step("POLL_AGENT", f"❌ END - Failed after {max_consecutive_errors} consecutive errors")
                    return {
                        "error": str(e),
                        "status": "failed",
                        "user_message": "An unexpected error occurred. Please try again."
                    }
                
                continue
        
        elapsed = (datetime.now() - start_time).total_seconds() / 60
        log_step("POLL_AGENT", f"❌ END - Timeout after {elapsed:.1f} minutes ({max_attempts} attempts)")
        return {
            "error": f"Timeout after {elapsed:.1f} minutes",
            "status": "timeout",
            "user_message": "The agent is taking too long to respond. Please try again."
        }
    
    async def _parse_agent_response(self, response_data):
        """
        Parse agent response - handles multiple formats like daily news agent.
        
        Handles:
        - JSON objects
        - JSON arrays
        - JSON strings (need to parse)
        - Plain text responses
        """
        if isinstance(response_data, dict):
            # Already a dict, return as is
            log_step("PARSE_RESPONSE", "📦 Response is dict")
            return response_data
        
        if isinstance(response_data, list):
            # Already a list, return as is
            log_step("PARSE_RESPONSE", f"📦 Response is list with {len(response_data)} items")
            return response_data
        
        if isinstance(response_data, str):
            log_step("PARSE_RESPONSE", f"📝 Response is string ({len(response_data)} chars)")
            
            # Try to parse as JSON
            if response_data.strip():
                try:
                    # Try direct JSON parse
                    parsed = json.loads(response_data)
                    log_step("PARSE_RESPONSE", "✅ Successfully parsed as JSON")
                    return parsed
                except json.JSONDecodeError:
                    # Try to extract JSON from markdown code blocks
                    try:
                        import re
                        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_data)
                        if match:
                            extracted = match.group(1).strip()
                            parsed = json.loads(extracted)
                            log_step("PARSE_RESPONSE", "✅ Extracted and parsed JSON from markdown")
                            return parsed
                    except:
                        pass
                    
                    # Return as plain string if JSON parsing fails
                    log_step("PARSE_RESPONSE", "⚠️ Response is not valid JSON, returning as string")
                    return response_data
            
            return response_data
        
        # Default: return as is
        return response_data

    # ==========================================
    # OPTIMIZED: Session-based with GET polling
    # ==========================================
    
    async def get_or_create_lyzr_session(
        self,
        agent_id: str,
        session_id: str,
        user_id: str = None,
        username: str = None,
        agent_code: str = None,
        initial_message: str = None
    ) -> str:
        """
        Get Lyzr session ID from the first agent call response (not by creating separately).
        Returns the Lyzr session ID for reuse in subsequent interactions.
        
        Args:
            agent_id: Lyzr agent ID
            session_id: Your application's session ID
            user_id: User identifier
            username: Username (optional)
            agent_code: Agent code (optional)
            initial_message: Initial message to send (optional, for first call)
        
        Returns:
            Lyzr session ID (string)
        """
        session_key = f"{session_id}:{agent_id}"
        
        # Determine agent_type from agent_id
        agent_type = None
        if "693ee504" in agent_id or "product" in agent_id.lower():
            agent_type = "product_recommendation"
        elif "sales" in agent_id.lower():
            agent_type = "sales_pitch"
        
        # Check if we already have a session ID stored (database first, then memory)
        lyzr_session_id = get_lyzr_session_id_from_db(session_id, agent_id)
        if lyzr_session_id:
            logger.info(f"✅ Reusing existing Lyzr session from DB: {lyzr_session_id[:12]}...")
            return lyzr_session_id
        
        # Fallback to memory cache
        if session_key in _lyzr_sessions:
            lyzr_session_id = _lyzr_sessions[session_key]
            logger.info(f"✅ Reusing existing Lyzr session from memory: {lyzr_session_id[:12]}...")
            # Save to DB for persistence
            save_lyzr_session_to_db(
                session_id=session_id,
                agent_id=agent_id,
                lyzr_session_id=lyzr_session_id,
                agent_type=agent_type,
                agent_code=agent_code,
                username=username
            )
            return lyzr_session_id
        
        logger.info(f"🆕 Getting Lyzr session ID from first agent call for agent {agent_id}")
        
        # Use production endpoint pattern
        endpoint_url = "https://agent-prod.studio.lyzr.ai/v3/inference/chat/"
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # First call: POST to chat endpoint to get session_id from response
                # Use a simple initial message if none provided
                first_message = initial_message or "Hello"
                
                payload = {
                    "user_id": user_id or username or "bot_user",
                    "agent_id": agent_id,
                    "session_id": session_id,  # Use our session_id initially
                    "message": first_message
                }
                
                # Add username and agent_code if provided
                if username:
                    payload["username"] = username
                if agent_code:
                    payload["agent_code"] = agent_code
                
                logger.info(f"📤 First call to get session ID from Lyzr Agent")
                logger.debug(f"   Endpoint: {endpoint_url}")
                logger.debug(f"   Agent ID: {agent_id}")
                
                response = await client.post(
                    endpoint_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": self.api_key
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Extract session_id from response
                    lyzr_session_id = data.get("session_id") or data.get("sessionId") or session_id
                    
                    if lyzr_session_id:
                        # Store in database (persistent)
                        save_lyzr_session_to_db(
                            session_id=session_id,
                            agent_id=agent_id,
                            lyzr_session_id=lyzr_session_id,
                            agent_type=agent_type,
                            agent_code=agent_code,
                            username=username
                        )
                        
                        # Also store in memory for fast access (backward compatibility)
                        _lyzr_sessions[session_key] = lyzr_session_id
                        _lyzr_initialized.add(session_key)
                        logger.info(f"✅ Lyzr session ID obtained and stored: {lyzr_session_id[:12]}...")
                        logger.debug(f"   Full session ID: {lyzr_session_id}")
                        return lyzr_session_id
                    else:
                        logger.error(f"❌ No session_id in response: {data}")
                        # Fallback: use our session_id
                        _lyzr_sessions[session_key] = session_id
                        _lyzr_initialized.add(session_key)
                        logger.warning(f"⚠️ Using application session_id as fallback: {session_id}")
                        return session_id
                else:
                    error_text = response.text[:500] if response.text else "No response body"
                    logger.error(f"❌ Failed to get session ID: {response.status_code} - {error_text}")
                    raise Exception(f"Failed to get session ID: {response.status_code}")
                    
        except Exception as e:
            logger.error(f"❌ Error getting Lyzr session ID: {e}", exc_info=True)
            raise

    async def send_message_to_lyzr_session(
        self,
        agent_id: str,
        lyzr_session_id: str,
        message: str
    ) -> dict:
        """
        Send a message to an existing Lyzr session (POST only when sending new message).
        
        Args:
            agent_id: Lyzr agent ID
            lyzr_session_id: Lyzr session ID (from first call response)
            message: User message
        
        Returns:
            Response dict with status and optional response/error
        """
        # Use production endpoint
        endpoint_url = "https://agent-prod.studio.lyzr.ai/v3/inference/chat/"
        
        logger.info(f"📤 Sending message to Lyzr session {lyzr_session_id[:12]}...")
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    endpoint_url,
                    json={
                        "user_id": "bot_user",
                        "agent_id": agent_id,
                        "session_id": lyzr_session_id,
                        "message": message
                    },
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": self.api_key
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # If response is immediately available, return it
                    if data.get("response"):
                        logger.info(f"✅ Immediate response received")
                        return {
                            "status": "success",
                            "response": data.get("response"),
                            "session_id": lyzr_session_id
                        }
                    
                    # Otherwise, return session_id for polling
                    return {
                        "status": "processing",
                        "session_id": lyzr_session_id,
                        "message": "Message sent, polling required"
                    }
                else:
                    logger.error(f"❌ Failed to send message: {response.status_code}")
                    return {
                        "status": "failed",
                        "error": f"HTTP {response.status_code}",
                        "user_message": "Failed to send message to agent"
                    }
                    
        except Exception as e:
            logger.error(f"❌ Error sending message: {e}", exc_info=True)
            return {
                "status": "failed",
                "error": str(e),
                "user_message": "Error communicating with agent"
            }

    async def poll_lyzr_session_get(
        self,
        agent_id: str,
        lyzr_session_id: str,
        poll_interval: int = 2000,
        max_attempts: int = 60
    ) -> dict:
        """
        Poll Lyzr session using GET requests (faster, no POST overhead).
        
        Args:
            agent_id: Lyzr agent ID
            lyzr_session_id: Lyzr session ID
            poll_interval: Milliseconds between polls
            max_attempts: Maximum polling attempts
        
        Returns:
            Response dict with agent response or error
        """
        # Use production endpoint
        endpoint_url = "https://agent-prod.studio.lyzr.ai/v3/inference/chat/"
        
        # Try GET endpoint first (if API supports it)
        get_endpoint = f"https://agent-prod.studio.lyzr.ai/v3/inference/chat/{agent_id}/session/{lyzr_session_id}/status"
        
        logger.info(f"📥 Polling session {lyzr_session_id[:12]}... (GET method)")
        
        for attempt in range(max_attempts):
            if attempt > 0:
                await asyncio.sleep(poll_interval / 1000.0)
            
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    # Try GET request first (preferred - no POST overhead)
                    try:
                        response = await client.get(
                            get_endpoint,
                            headers={
                                "Authorization": f"Bearer {self.api_key}",
                                "x-api-key": self.api_key
                            }
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            
                            if data.get("response"):
                                logger.info(f"✅ Response received via GET (attempt {attempt + 1})")
                                return {
                                    "status": "success",
                                    "response": data.get("response")
                                }
                            
                            if data.get("status") == "completed":
                                logger.info(f"✅ Session completed (attempt {attempt + 1})")
                                return {
                                    "status": "success",
                                    "response": data.get("response", data.get("result", ""))
                                }
                            
                            if data.get("status") == "failed":
                                return {
                                    "status": "failed",
                                    "error": data.get("error", "Agent processing failed")
                                }
                            
                            # Still processing, continue polling
                            if attempt % 5 == 0:
                                logger.debug(f"⏳ Still processing... (attempt {attempt + 1}/{max_attempts})")
                            continue
                            
                    except httpx.HTTPStatusError:
                        # GET endpoint not available, fall back to POST with empty message
                        logger.debug(f"⚠️ GET endpoint not available, using POST fallback")
                        pass
                    
                    # Fallback: POST with empty message (only if GET fails)
                    response = await client.post(
                        endpoint_url,
                        json={
                            "user_id": "bot_user",
                            "agent_id": agent_id,
                            "session_id": lyzr_session_id,
                            "message": ""  # Empty message = poll
                        },
                        headers={
                            "Content-Type": "application/json",
                            "x-api-key": self.api_key
                        }
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        if data.get("response"):
                            logger.info(f"✅ Response received via POST poll (attempt {attempt + 1})")
                            return {
                                "status": "success",
                                "response": data.get("response")
                            }
                        
                        # Still processing
                        if attempt % 5 == 0:
                            logger.debug(f"⏳ Still processing... (attempt {attempt + 1}/{max_attempts})")
                        continue
                    else:
                        logger.warning(f"⚠️ Poll request failed: {response.status_code}")
                        if attempt >= 3:  # Retry a few times
                            return {
                                "status": "failed",
                                "error": f"Polling failed: {response.status_code}"
                            }
                        continue
                        
            except Exception as e:
                logger.warning(f"⚠️ Poll error (attempt {attempt + 1}): {e}")
                if attempt >= max_attempts - 1:
                    return {
                        "status": "failed",
                        "error": str(e)
                    }
                continue
        
        # Timeout
        return {
            "status": "timeout",
            "error": f"Polling timeout after {max_attempts} attempts"
        }

    async def optimized_call_agent(
        self,
        agent_id: str,
        message: str,
        session_id: str,
        user_id: str = None,
        username: str = None,
        agent_code: str = None,
        poll_interval: int = 2000,
        max_attempts: int = 60
    ) -> dict:
        """
        Optimized agent call that:
        1. Gets session ID from first agent call response (not by creating separately)
        2. Reuses session for all interactions
        3. Uses GET requests for polling (minimizes POST requests)
        
        Args:
            agent_id: Lyzr agent ID
            message: User message
            session_id: Application session ID
            user_id: User identifier
            username: Username
            agent_code: Agent code
            poll_interval: Milliseconds between polls
            max_attempts: Maximum polling attempts
        
        Returns:
            Agent response (dict, list, or string)
        """
        try:
            session_key = f"{session_id}:{agent_id}"
            endpoint_url = "https://agent-prod.studio.lyzr.ai/v3/inference/chat/"
            lyzr_session_id = None
            
            # Determine agent_type from agent_id (for database storage)
            agent_type = None
            if "693ee504" in agent_id or "product" in agent_id.lower():
                agent_type = "product_recommendation"
            elif "sales" in agent_id.lower():
                agent_type = "sales_pitch"
            
            # 🔒 LATENCY FIX: Check MEMORY FIRST, then database
            # Memory lookup is ~0ms vs database lookup ~100-500ms
            
            # Step 1a: Check in-memory cache FIRST (fastest)
            if session_key in _lyzr_sessions:
                lyzr_session_id = _lyzr_sessions[session_key]
                logger.info(f"⚡ Found Lyzr session in MEMORY (fast path): {lyzr_session_id[:12]}...")
            else:
                # Step 1b: Fallback to database (slower, but persistent)
                try:
                    lyzr_session_id = get_lyzr_session_id_from_db(session_id, agent_id)
                    if lyzr_session_id:
                        logger.info(f"✅ Found Lyzr session in DB: {lyzr_session_id[:12]}...")
                        # Cache in memory for next call
                        _lyzr_sessions[session_key] = lyzr_session_id
                except Exception as e:
                    logger.debug(f"Error checking DB for session: {e}")
            
            if lyzr_session_id:
                # Step 2: Send message using existing session (POST only when sending new message)
                send_result = await self.send_message_to_lyzr_session(
                    agent_id=agent_id,
                    lyzr_session_id=lyzr_session_id,
                    message=message
                )
                
                if send_result.get("status") == "failed":
                    return send_result
                
                # If immediate response, return it
                if send_result.get("status") == "success":
                    # Update last message time in DB
                    try:
                        db = get_database()
                        db.lyzr_sessions.update_one(
                            {"sessionId": session_id, "agentId": agent_id},
                            {"$set": {"lastMessageAt": datetime.utcnow()}}
                        )
                    except Exception as e:
                        logger.debug(f"Error updating lastMessageAt: {e}")
                    return await self._parse_agent_response(send_result.get("response"))
            else:
                # First call: POST to get session_id from response
                logger.info(f"🆕 First call - Getting session ID from Lyzr Agent response")
                
                async with httpx.AsyncClient(timeout=60.0) as client:
                    payload = {
                        "user_id": user_id or username or "bot_user",
                        "agent_id": agent_id,
                        "session_id": session_id,  # Use our session_id initially
                        "message": message  # Send the actual message
                    }
                    
                    # Add username and agent_code if provided
                    if username:
                        payload["username"] = username
                    if agent_code:
                        payload["agent_code"] = agent_code
                    
                    logger.info(f"📤 POST Request to get session ID and send message")
                    logger.debug(f"   Endpoint: {endpoint_url}")
                    logger.debug(f"   Agent ID: {agent_id}")
                    
                    response = await client.post(
                        endpoint_url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "x-api-key": self.api_key
                        }
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        # Extract session_id from response
                        lyzr_session_id = data.get("session_id") or data.get("sessionId") or session_id
                        
                        # Store in database (persistent)
                        save_lyzr_session_to_db(
                            session_id=session_id,
                            agent_id=agent_id,
                            lyzr_session_id=lyzr_session_id,
                            agent_type=agent_type,
                            agent_code=agent_code,
                            username=username
                        )
                        
                        # Also store in memory for fast access (backward compatibility)
                        _lyzr_sessions[session_key] = lyzr_session_id
                        _lyzr_initialized.add(session_key)
                        logger.info(f"✅ Lyzr session ID obtained and stored: {lyzr_session_id[:12]}...")
                        
                        # Check if response is immediately available
                        if data.get("response"):
                            logger.info(f"✅ Immediate response received in first call")
                            return await self._parse_agent_response(data.get("response"))
                    else:
                        error_text = response.text[:500] if response.text else "No response body"
                        logger.error(f"❌ Failed to get session ID: {response.status_code} - {error_text}")
                        return {
                            "status": "failed",
                            "error": f"HTTP {response.status_code}",
                            "user_message": "Failed to connect to agent. Please try again."
                        }
            
            # Step 3: Poll for results (GET requests, no POST overhead)
            if lyzr_session_id:
                poll_result = await self.poll_lyzr_session_get(
                    agent_id=agent_id,
                    lyzr_session_id=lyzr_session_id,
                    poll_interval=poll_interval,
                    max_attempts=max_attempts
                )
                
                if poll_result.get("status") == "success":
                    # Update last message time in DB
                    try:
                        db = get_database()
                        db.lyzr_sessions.update_one(
                            {"sessionId": session_id, "agentId": agent_id},
                            {"$set": {"lastMessageAt": datetime.utcnow()}}
                        )
                    except Exception as e:
                        logger.debug(f"Error updating lastMessageAt: {e}")
                    return await self._parse_agent_response(poll_result.get("response"))
                else:
                    return {
                        "status": "failed",
                        "error": poll_result.get("error"),
                        "user_message": "Agent processing failed or timed out. Please try again."
                    }
            else:
                return {
                    "status": "failed",
                    "error": "Failed to get session ID",
                    "user_message": "Failed to establish session with agent. Please try again."
                }
                
        except Exception as e:
            logger.error(f"❌ Error in optimized_call_agent: {e}", exc_info=True)
            return {
                "status": "failed",
                "error": str(e),
                "user_message": "An error occurred. Please try again."
            }

