"""
Database connection module
Centralized MongoDB connection for the application
"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from app.config.logging_config import get_logger

load_dotenv()

logger = get_logger(__name__)

# Global MongoDB connection
_mongo_client = None
_db = None
_warming_up = True  # Track MongoDB warm-up state

def is_mongodb_ready() -> bool:
    """Check if MongoDB is ready and responsive"""
    global _warming_up
    if _mongo_client is None:
        return False
    try:
        _mongo_client.admin.command("ping", maxTimeMS=1000)
        _warming_up = False
        return True
    except Exception:
        return False

def is_warming_up() -> bool:
    """Check if MongoDB is still warming up"""
    return _warming_up

def get_database():
    """Get database instance, creating connection if needed"""
    global _mongo_client, _db
    
    if _db is not None:
        return _db
    
    # Prioritize MONGODB_URI, then MONGODB_URI
    mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/Star_Health_Whatsapp_bot"
    
    logger.info("🔌 Connecting to MongoDB...")
    
    try:
        _mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        _mongo_client.admin.command('ping')
        _warming_up = False  # MongoDB is ready
        logger.info("✅ MongoDB connection successful")
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        _warming_up = True  # Still warming up
        raise
    
    # Get database name from environment variable, URI, or use default
    db_name = os.getenv("MONGODB_DATABASE") or os.getenv("DATABASE_NAME") or "Star_Health_Whatsapp_bot"
    
    # Try to extract database name from URI if not set via env var
    if db_name == "Star_Health_Whatsapp_bot" and "/" in mongo_uri:
        try:
            # MongoDB URI format: mongodb://[username:password@]host[:port][/database][?options]
            # Split by '/' and get the last part before '?'
            uri_parts = mongo_uri.split("/")
            if len(uri_parts) > 3:
                # We have a database name in the URI
                potential_db = uri_parts[-1].split("?")[0].split("#")[0]  # Remove query params and fragments
                if potential_db and potential_db.strip():
                    db_name = potential_db.strip()
                    logger.info(f"📝 Extracted database name from URI: {db_name}")
        except Exception as e:
            logger.warning(f"⚠️ Could not extract database name from URI: {e}")
    
    if not db_name or db_name == "":
        db_name = "Star_Health_Whatsapp_bot"
    
    logger.info(f"📚 Using database: {db_name}")
    _db = _mongo_client[db_name]
    return _db

def get_client():
    """Get MongoDB client instance"""
    if _mongo_client is None:
        get_database()  # This will initialize the client
    return _mongo_client

def close_connection():
    """Close MongoDB connection"""
    global _mongo_client, _db
    if _mongo_client:
        _mongo_client.close()
        _mongo_client = None
        _db = None
        logger.info("🔌 MongoDB connection closed")




