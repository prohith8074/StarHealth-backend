"""
Database initialization module
Centralized index creation and setup
"""
from app.config.database import get_database
from app.config.logging_config import get_logger

logger = get_logger(__name__)

async def ensure_indexes():
    """
    🔒 ENTERPRISE: Create indexes idempotently.
    Checks existing indexes before creating to avoid conflicts.
    """
    try:
        db = get_database()
        
        def index_exists(collection, index_name: str) -> bool:
            """Check if index already exists"""
            try:
                indexes = list(collection.list_indexes())
                return any(idx.get("name") == index_name for idx in indexes)
            except Exception as e:
                logger.debug(f"Error checking index {index_name}: {e}")
                return False
        
        def create_index_safe(collection, index_spec, name: str, **kwargs):
            """Create index only if it doesn't exist"""
            if index_exists(collection, name):
                logger.debug(f"   ⏭️  Index {name} already exists, skipping")
                return
            try:
                collection.create_index(index_spec, name=name, **kwargs)
                logger.debug(f"   ✅ Created index: {name}")
            except Exception as e:
                # Index might have been created concurrently
                error_msg = str(e).lower()
                if "already exists" in error_msg or "duplicate key" in error_msg:
                    logger.debug(f"   ⏭️  Index {name} created concurrently, skipping")
                else:
                    logger.warning(f"   ⚠️  Error creating index {name}: {e}")
        
        # dashboarddata collection
        create_index_safe(db.dashboarddata, [("createdAt", -1), ("eventType", 1)], "created_at_event_type_idx")
        create_index_safe(db.dashboarddata, [("createdAt", -1)], "created_at_idx")
        create_index_safe(db.dashboarddata, [("data.agent_code", 1)], "agent_code_idx")
        create_index_safe(db.dashboarddata, [("data.session_id", 1)], "session_id_idx")
        create_index_safe(db.dashboarddata, [("eventType", 1)], "event_type_idx")
        
        # feedback collection
        create_index_safe(db.feedback, [("createdAt", 1), ("agentType", 1), ("feedback", 1)], "feedback_activity_idx")
        create_index_safe(db.feedback, [("createdAt", 1), ("conversationStatus", 1)], "created_at_status_idx")
        create_index_safe(db.feedback, [("sessionId", 1)], "session_id_idx")
        create_index_safe(db.feedback, [("conversationStatus", 1)], "conversation_status_idx")
        
        # agent_stats collection
        create_index_safe(db.agent_stats, [("timestamp", -1), ("agentType", 1)], "timestamp_agent_type_idx")
        create_index_safe(db.agent_stats, [("agentCode", 1), ("agentType", 1)], "agent_code_type_idx")
        create_index_safe(db.agent_stats, [("timestamp", -1)], "timestamp_idx")
        create_index_safe(db.agent_stats, [("sessionId", 1), ("agentCode", 1)], "session_agent_idx")
        create_index_safe(db.agent_stats, [("hasError", 1)], "has_error_idx")
        create_index_safe(db.agent_stats, [("lyzrSessionId", 1)], "lyzr_session_id_idx")
        
        # cache_metadata collection (Legacy support or future use)
        # Note: We are migrating to Redis, but keeping this for safety during transition if needed
        create_index_safe(db.cache_metadata, [("key", 1)], "cache_key_idx", unique=True)
        db.cache_metadata.create_index("expiresAt", expireAfterSeconds=0)

        # agents collection
        create_index_safe(db.agents, [("createdAt", -1)], "created_at_idx")
        create_index_safe(db.agents, [("agent_code", 1)], "agent_code_idx", unique=True)
        
        # login_details collection
        create_index_safe(db.login_details, [("email", 1)], "email_idx", unique=True)
        create_index_safe(db.login_details, [("isActive", 1)], "is_active_idx")
        
        # lyzr_sessions collection
        create_index_safe(db.lyzr_sessions, [("sessionId", 1), ("agentId", 1)], "session_agent_unique", unique=True)
        create_index_safe(db.lyzr_sessions, [("lyzrSessionId", 1)], "lyzr_session_id_idx")
        create_index_safe(db.lyzr_sessions, [("createdAt", -1)], "created_at_idx")
        create_index_safe(db.lyzr_sessions, [("isActive", 1)], "is_active_idx")
        create_index_safe(db.lyzr_sessions, [("agentType", 1)], "agent_type_idx")
        
        # Top_Products collection
        create_index_safe(db.Top_Products, [("productName", 1)], "product_name_unique", unique=True)
        create_index_safe(db.Top_Products, [("createdAt", -1)], "created_at_idx")
        
        logger.info("✅ Database indexes verified/created")
    except Exception as e:
        logger.warning(f"⚠️ Error ensuring indexes: {e}")
