"""
Service for storing chat messages in MongoDB
"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from app.config.logging_config import get_logger
from datetime import datetime, timedelta
import asyncio
import functools

logger = get_logger(__name__)

def get_ist_time():
    """Get current time in Indian Standard Time (IST)"""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

class ChatStorage:
    """Service for storing chat messages in MongoDB"""
    
    def __init__(self):
        # Prioritize MONGODB_URI, then MONGODB_URI
        mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/Star_Health_Whatsapp_bot"
        logger.info(f"🔌 Connecting to MongoDB for chat storage")
        
        try:
            self.mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.mongo_client.admin.command('ping')
            logger.info("✅ MongoDB connection successful")
        except Exception as e:
            # Don't raise here - allow application to start in degraded mode
            logger.error(f"❌ MongoDB connection failed: {e}")
            logger.warning("⚠️ Starting without MongoDB - chat storage will be disabled until connection is restored")
            self.mongo_client = None
            self.db = None
            self.lyzr_sessions = None
            self.available = False
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
        
        # Ensure database name is not empty
        if not db_name or db_name == "":
            db_name = "Star_Health_Whatsapp_bot"
        
        logger.info(f"📚 Using database: {db_name}")
        self.db = self.mongo_client[db_name]
        # 🔒 FIX: Moved from chatmessages to lyzr_sessions for session tracking only
        self.lyzr_sessions = self.db.lyzr_sessions
        self.available = True
        self.available = True
        logger.info(f"✅ ChatStorage initialized (Message content storage DISABLED)")
    
    async def _run_db(self, func, *args, **kwargs):
        """Helper to run blocking DB calls in a thread pool"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
    
    async def save_message(
        self,
        session_id: str,
        role: str,
        message: str,
        username: str = None,
        agent_code: str = None,
        agent_name: str = None,
        agent_type: str = None,
        state: str = None,
        lyzr_session_id: str = None,
        total_tokens: int = 0,
        llm_calls: int = 0
    ):
        """
        Stats update and Lyzr Session ID tracking.
        NOTE: Message content is successfully NOT stored as per privacy requirements.
        """
        if not self.available or self.db is None:
            logger.warning("⚠️ Cannot access MongoDB")
            return None

        try:
            ist_now = get_ist_time()
            
            # 1. Store only Lyzr Session ID (if available)
            if lyzr_session_id:
                session_doc = {
                    "$set": {
                        "sessionId": session_id,
                        "lyzrSessionId": lyzr_session_id,
                        "updatedAt": ist_now,
                        "timestamp": ist_now.isoformat()
                    },
                    "$setOnInsert": {
                        "createdAt": ist_now
                    }
                }
                
                # Update agent metadata if available
                if agent_type: session_doc["$set"]["agentType"] = agent_type
                if agent_code: session_doc["$set"]["agentCode"] = agent_code
                if username: session_doc["$set"]["username"] = username
                
                # Upsert into lyzr_sessions collection
                # We key by sessionId AND agentType to handle switches, or just sessionId if 1:1 map desired.
                # User asked for "stored the session id... for each conversation".
                # A conversation is usually defined by session_id.
                
                await self._run_db(
                    self.lyzr_sessions.update_one,
                    {"sessionId": session_id},
                    session_doc,
                    upsert=True
                )
                logger.info(f"✅ Lyzr Session ID stored/updated for session {session_id}")
            
            # 2. Update agent_stats (Metrics) - ONLY if role is agent or user (to track interaction)
            if agent_code and agent_type:
                logger.debug(f"📊 Updating agent_stats for {agent_code}")
                stats_doc = {
                    "$set": {
                        "sessionId": session_id,
                        "agentCode": agent_code,
                        "agentName": agent_name,
                        "agentType": agent_type,
                        "username": username,
                        "updatedAt": ist_now,
                        "timestamp": ist_now # For time-range filtering
                    },
                    "$inc": {
                        "messageCount": 1,
                        "totalTokens": total_tokens or 0,
                        "llmCalls": llm_calls or 0
                    },
                    "$setOnInsert": {
                        "createdAt": ist_now
                    }
                }
                
                if lyzr_session_id:
                    stats_doc["$set"]["lyzrSessionId"] = lyzr_session_id
                
                # 🔒 FIX: Include agentType in filter to create SEPARATE traces for each agent type
                # This ensures switching from Product Recommendation to Sales Pitch creates a NEW trace
                # instead of overwriting the existing one
                stats_filter = {
                    "sessionId": session_id, 
                    "agentCode": agent_code,
                    "agentType": agent_type  # 🔒 NEW: Creates separate trace per agent type
                }
                
                await self._run_db(self.db.agent_stats.update_one, stats_filter, stats_doc, upsert=True)
                logger.debug(f"✅ Agent stats updated for {agent_type}")

            return True 
        except Exception as e:
            logger.error(f"❌ Error in chat storage: {e}", exc_info=True)
            raise
    
    def _extract_product_recommendations(self, message: str) -> list:
        """
        Extract product recommendations from agent response message.
        Looks for patterns like product names, policy names, or structured data.
        """
        products = []
        
        try:
            # Common patterns for product recommendations
            import re
            
            # Pattern 1: Look for numbered lists (1. Product Name, 2. Product Name, etc.)
            numbered_pattern = r'\d+[\.\)]\s*([A-Z][^0-9\n]+?)(?=\d+[\.\)]|$)'
            matches = re.findall(numbered_pattern, message, re.MULTILINE)
            if matches:
                products.extend([m.strip() for m in matches if len(m.strip()) > 3])
            
            # Pattern 2: Look for bullet points (- Product, * Product, • Product)
            bullet_pattern = r'[-*•]\s*([A-Z][^\n]+?)(?=[-*•]|$)'
            matches = re.findall(bullet_pattern, message, re.MULTILINE)
            if matches:
                products.extend([m.strip() for m in matches if len(m.strip()) > 3])
            
            # Pattern 3: Look for "Product:" or "Policy:" patterns
            product_label_pattern = r'(?:Product|Policy|Plan)[:\-]\s*([A-Z][^\n]+?)(?=\n|$)'
            matches = re.findall(product_label_pattern, message, re.IGNORECASE | re.MULTILINE)
            if matches:
                products.extend([m.strip() for m in matches if len(m.strip()) > 3])
            
            # Pattern 4: If message contains structured JSON-like data, try to parse
            if '{' in message and '}' in message:
                import json
                try:
                    # Try to find JSON objects in the message
                    json_pattern = r'\{[^{}]*\}'
                    json_matches = re.findall(json_pattern, message)
                    for json_str in json_matches:
                        try:
                            data = json.loads(json_str)
                            if isinstance(data, dict):
                                # Look for product-related keys
                                for key in ['product', 'products', 'policy', 'policies', 'plan', 'plans', 'name', 'title']:
                                    if key in data:
                                        value = data[key]
                                        if isinstance(value, str) and len(value) > 3:
                                            products.append(value)
                                        elif isinstance(value, list):
                                            products.extend([str(p) for p in value if len(str(p)) > 3])
                        except:
                            pass
                except:
                    pass
            
            # Remove duplicates and clean up
            products = list(set([p.strip() for p in products if len(p.strip()) > 3]))
            
            # If no structured patterns found, but message is from product recommendation agent,
            # consider the entire message as a product recommendation if it's reasonably short
            if not products and len(message) < 500 and len(message) > 10:
                # Split by sentences and take first few as potential product names
                sentences = re.split(r'[.!?]\s+', message)
                products = [s.strip() for s in sentences[:3] if len(s.strip()) > 10 and len(s.strip()) < 200]
            
        except Exception as e:
            logger.warning(f"⚠️ Error extracting product recommendations: {e}")
        
        return products[:10]  # Limit to 10 products max
    
    async def get_conversation(self, session_id: str):
        """Get all messages for a session"""
        # Message storage is disabled
        return []

    async def get_user_conversations(self, agent_code: str):
        """Get all conversations for a specific agent code"""
        # Message storage is disabled
        return []

