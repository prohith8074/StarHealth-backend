# Refactored to use MongoDB for persistence (Redis is restricted to Dashboard only)
from app.config.database import get_database, is_mongodb_ready
from app.config.logging_config import get_logger
import uuid
from typing import Dict, Optional
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

logger = get_logger(__name__)

# Session expiry configuration (in minutes)
SESSION_EXPIRY_MINUTES = int(os.getenv("SESSION_EXPIRY_MINUTES", "30"))

def get_ist_time():
    """Get current time in Indian Standard Time (IST)"""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

class SessionService:
    """Session service using MongoDB for persistence"""
    
    def __init__(self):
        try:
            if is_mongodb_ready():
                self.db = get_database()
                self.sessions = self.db.sessions
                self._ensure_indexes()
                self.available = True
                logger.info("✅ SessionService connected to MongoDB")
            else:
                self._set_unavailable()
        except Exception as e:
            logger.warning(f"⚠️ SessionService init failed: {e}")
            self._set_unavailable()

    def _set_unavailable(self):
        self.db = None
        self.sessions = None
        self.available = False
        logger.warning("⚠️ SessionService running without DB (Degraded Mode)")

    def _ensure_indexes(self):
        try:
            self.sessions.create_index("session_id", unique=True)
            self.sessions.create_index("phone")
            self.sessions.create_index("updated_at", expireAfterSeconds=SESSION_EXPIRY_MINUTES * 60) # TTL Index
        except Exception as e:
            logger.warning(f"⚠️ Could not create session indexes: {e}")

    def _ensure_connection(self):
        """Lazy reconnection"""
        if self.available:
            return True
        try:
            from app.config.database import get_database, is_mongodb_ready
            if is_mongodb_ready():
                self.db = get_database()
                self.sessions = self.db.sessions
                self._ensure_indexes()
                self.available = True
                logger.info("✅ SessionService re-connected to MongoDB")
                return True
        except Exception:
            pass
        return False
    
    async def get_or_create_session(self) -> str:
        """Create a brand new anonymous session ID"""
        self._ensure_connection()
        session_id = str(uuid.uuid4())
        
        if self.available:
            ist_now = get_ist_time()
            self.sessions.insert_one({
                "session_id": session_id,
                "state": "greeting",
                "created_at": ist_now,
                "updated_at": ist_now
            })
        
        logger.info(f"🆕 New session created: {session_id}")
        return session_id
    
    async def get_or_create_session_for_phone(self, phone_number: Optional[str]) -> str:
        """
        Get or create a stable session ID for a WhatsApp phone number.
        """
        if not phone_number:
            return await self.get_or_create_session()
        
        self._ensure_connection()
            
        if self.available:
            # Try to find active session for phone
            # We look for a session updated recently (auto-cleaned by TTL index, but check anyway)
            cutoff = get_ist_time() - timedelta(minutes=SESSION_EXPIRY_MINUTES)
            existing = self.sessions.find_one({
                "phone": phone_number,
                "updated_at": {"$gt": cutoff}
            })
            
            if existing:
                session_id = existing["session_id"]
                logger.debug(f"🔁 Reusing existing session {session_id} for phone {phone_number}")
                return session_id
        
        # Create new
        session_id = str(uuid.uuid4())
        
        if self.available:
            ist_now = get_ist_time()
            self.sessions.insert_one({
                "session_id": session_id,
                "phone": phone_number,
                "state": "greeting",
                "created_at": ist_now,
                "updated_at": ist_now
            })
            
        logger.info(f"🆕 New session {session_id} created for phone {phone_number}")
        return session_id
    
    async def get_session_state(self, session_id: str) -> dict:
        """Get current session state from MongoDB"""
        self._ensure_connection()
        if not self.available:
            return {"state": "greeting"} # Fallback
            
        # Check expiry logic manually as well
        cutoff = get_ist_time() - timedelta(minutes=SESSION_EXPIRY_MINUTES)
        session = self.sessions.find_one({
            "session_id": session_id,
            "updated_at": {"$gt": cutoff}
        })
        
        if not session:
            return None
            
        # Return state dict (excluding _id)
        state = {k: v for k, v in session.items() if k not in ["_id", "session_id", "created_at", "updated_at", "phone"]}
        # If state field exists directly, use it, otherwise assume top level fields are state
        # But our update logic maps state keys to top level for simplicity?
        # Actually, let's keep it structured.
        # If we saved {"state": "greeting"}, it is in the doc.
        return session
    
    async def is_session_expired(self, session_id: str) -> bool:
        """Check if session has expired"""
        self._ensure_connection()
        if not self.available:
            return False 
            
        cutoff = get_ist_time() - timedelta(minutes=SESSION_EXPIRY_MINUTES)
        session = self.sessions.find_one({
            "session_id": session_id,
            "updated_at": {"$gt": cutoff}
        })
        return session is None
    
    async def update_session_state(self, session_id: str, state: dict):
        """Update session state in MongoDB"""
        self._ensure_connection()
        if not self.available:
            return
            
        # Update fields and refresh updated_at (extends TTL)
        update_data = {**state, "updated_at": get_ist_time()}
        self.sessions.update_one(
            {"session_id": session_id},
            {"$set": update_data},
            upsert=True
        )
        logger.debug(f"💾 Session state updated in MongoDB: {state}")
    
    async def get_session_metadata(self, session_id: str) -> dict:
        """Get session metadata"""
        self._ensure_connection()
        if not self.available:
            return {}
        session = self.sessions.find_one({"session_id": session_id})
        return session.get("metadata", {}) if session else {}
    
    async def set_session_metadata(self, session_id: str, metadata: dict):
        """Set session metadata"""
        self._ensure_connection()
        if not self.available:
            return
        self.sessions.update_one(
            {"session_id": session_id},
            {"$set": {"metadata": metadata, "updated_at": get_ist_time()}}
        )
        logger.debug(f"💾 Session metadata updated: {metadata}")



