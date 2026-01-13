"""
MongoDB Index Creation Script
Run this script to ensure optimal indexes exist for the Star Health Bot application.

This script should be run:
1. After initial deployment
2. After upgrading to a new version that adds new queries
3. If you notice slow query performance

Usage:
    python -m app.db_indexes
    # or
    cd backend-python && python -c "from app.db_indexes import ensure_all_indexes; ensure_all_indexes()"
"""

from app.config.database import get_database
from app.config.logging_config import get_logger
import pymongo

logger = get_logger(__name__)


def ensure_all_indexes():
    """
    Create all necessary indexes for optimal performance.
    These indexes address the performance issues identified:
    1. Dashboard data aggregation
    2. Feedback lookups and updates
    3. Agent stats queries
    4. Session lookups
    """
    
    db = get_database()
    logger.info("🔧 Creating MongoDB indexes for optimal performance...")
    
    # 1. Feedback Collection - Critical for dashboard and feedback updates
    logger.info("📚 Creating indexes on 'feedback' collection...")
    try:
        # Unique index on sessionId - prevents duplicates and speeds up lookups
        db.feedback.create_index(
            [("sessionId", pymongo.ASCENDING)],
            unique=True,
            sparse=True,  # Allow documents without sessionId
            name="idx_feedback_sessionId_unique"
        )
        logger.info("   ✅ Created unique index on feedback.sessionId")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on feedback.sessionId already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    try:
        # Compound index for dashboard queries
        db.feedback.create_index(
            [("createdAt", pymongo.DESCENDING), ("agentType", pymongo.ASCENDING)],
            name="idx_feedback_createdAt_agentType"
        )
        logger.info("   ✅ Created compound index on feedback.createdAt + agentType")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on feedback.createdAt + agentType already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    try:
        # Index for feedback filtering
        db.feedback.create_index(
            [("feedback", pymongo.ASCENDING)],
            name="idx_feedback_feedback"
        )
        logger.info("   ✅ Created index on feedback.feedback")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on feedback.feedback already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    # 2. Agent Stats Collection - Critical for Activity Distribution
    logger.info("📚 Creating indexes on 'agent_stats' collection...")
    try:
        db.agent_stats.create_index(
            [("agentType", pymongo.ASCENDING), ("createdAt", pymongo.DESCENDING)],
            name="idx_agent_stats_type_date"
        )
        logger.info("   ✅ Created compound index on agent_stats.agentType + createdAt")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on agent_stats.agentType + createdAt already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    try:
        db.agent_stats.create_index(
            [("agentCode", pymongo.ASCENDING)],
            name="idx_agent_stats_agentCode"
        )
        logger.info("   ✅ Created index on agent_stats.agentCode")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on agent_stats.agentCode already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    try:
        db.agent_stats.create_index(
            [("timestamp", pymongo.DESCENDING)],
            name="idx_agent_stats_timestamp"
        )
        logger.info("   ✅ Created index on agent_stats.timestamp")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on agent_stats.timestamp already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    # 3. Dashboard Data Collection
    logger.info("📚 Creating indexes on 'dashboarddata' collection...")
    try:
        db.dashboarddata.create_index(
            [("eventType", pymongo.ASCENDING), ("createdAt", pymongo.DESCENDING)],
            name="idx_dashboarddata_event_date"
        )
        logger.info("   ✅ Created compound index on dashboarddata.eventType + createdAt")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on dashboarddata.eventType + createdAt already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    try:
        db.dashboarddata.create_index(
            [("data.agent_code", pymongo.ASCENDING)],
            name="idx_dashboarddata_agent_code"
        )
        logger.info("   ✅ Created index on dashboarddata.data.agent_code")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on dashboarddata.data.agent_code already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    # 4. Lyzr Sessions Collection - For session persistence
    logger.info("📚 Creating indexes on 'lyzr_sessions' collection...")
    try:
        db.lyzr_sessions.create_index(
            [("sessionId", pymongo.ASCENDING), ("agentId", pymongo.ASCENDING)],
            unique=True,
            name="idx_lyzr_sessions_unique"
        )
        logger.info("   ✅ Created unique compound index on lyzr_sessions.sessionId + agentId")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on lyzr_sessions already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    # 5. Sessions Collection - For phone number lookups
    logger.info("📚 Creating indexes on 'sessions' collection...")
    try:
        db.sessions.create_index(
            [("phone_number", pymongo.ASCENDING)],
            unique=True,
            sparse=True,
            name="idx_sessions_phone"
        )
        logger.info("   ✅ Created unique index on sessions.phone_number")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on sessions.phone_number already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    # 6. Agents Collection
    logger.info("📚 Creating indexes on 'agents' collection...")
    try:
        db.agents.create_index(
            [("agent_code", pymongo.ASCENDING)],
            unique=True,
            sparse=True,
            name="idx_agents_code"
        )
        logger.info("   ✅ Created unique index on agents.agent_code")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on agents.agent_code already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    # 7. Repeat Users Collection
    logger.info("📚 Creating indexes on 'Repeat_users' collection...")
    try:
        db["Repeat_users"].create_index(
            [("username", pymongo.ASCENDING), ("agentCode", pymongo.ASCENDING)],
            unique=True,
            name="idx_repeat_users_unique"
        )
        logger.info("   ✅ Created unique compound index on Repeat_users.username + agentCode")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("   ✓ Index on Repeat_users already exists")
        else:
            logger.warning(f"   ⚠️ Error creating index: {e}")
    
    logger.info("✅ All indexes created/verified successfully!")
    
    # Print index stats
    logger.info("\n📊 Current index stats:")
    for collection_name in ["feedback", "agent_stats", "dashboarddata", "lyzr_sessions", "sessions", "agents", "Repeat_users"]:
        try:
            indexes = list(db[collection_name].list_indexes())
            logger.info(f"   {collection_name}: {len(indexes)} indexes")
        except Exception as e:
            logger.warning(f"   {collection_name}: Error listing indexes - {e}")


if __name__ == "__main__":
    ensure_all_indexes()
