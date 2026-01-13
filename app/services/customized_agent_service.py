"""
Service for managing customized agent configurations
Stores and retrieves agent prompts (role, goal, instructions) by session ID
"""

from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime
from app.config.logging_config import get_logger
from typing import Optional, Dict, Any

load_dotenv()

logger = get_logger(__name__)


class CustomizedAgentService:
    """Manages customized agent configurations per session"""
    
    def __init__(self):
        mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/Star_Health_Whatsapp_bot"
        mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        db_name = "Star_Health_Whatsapp_bot"
        self.db = mongo_client[db_name]
        self.customized_agents_collection = self.db["CustomizedAgents"]
        
        # Create indexes for faster queries
        try:
            self.customized_agents_collection.create_index("sessionId")
            self.customized_agents_collection.create_index("agentType")
            logger.info("✅ Customized agents collection indexes created")
        except Exception as e:
            logger.warning(f"⚠️ Could not create indexes: {e}")
    
    async def save_customized_agent(
        self,
        session_id: str,
        agent_type: str,
        role: str,
        goal: str,
        instructions: str,
        username: str = None,
        agent_code: str = None
    ) -> bool:
        """
        Save customized agent configuration for a session
        
        Args:
            session_id: Session identifier
            agent_type: 'product_recommendation' or 'sales_pitch'
            role: Agent role description
            goal: Agent goal description
            instructions: Agent instructions
            username: Optional username
            agent_code: Optional agent code
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            document = {
                "sessionId": session_id,
                "agentType": agent_type,
                "role": role,
                "goal": goal,
                "instructions": instructions,
                "username": username,
                "agentCode": agent_code,
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            }
            
            # Update or insert (upsert)
            result = self.customized_agents_collection.update_one(
                {"sessionId": session_id, "agentType": agent_type},
                {"$set": document},
                upsert=True
            )
            
            logger.info(f"✅ Customized agent saved:")
            logger.info(f"   Session: {session_id}")
            logger.info(f"   Agent Type: {agent_type}")
            logger.info(f"   Matched: {result.matched_count}, Upserted: {result.upserted_id is not None}")
            
            return True
        except Exception as e:
            logger.error(f"❌ Error saving customized agent: {e}")
            return False
    
    async def get_customized_agent(
        self,
        session_id: str,
        agent_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get customized agent configuration for a session and agent type
        
        Args:
            session_id: Session identifier
            agent_type: 'product_recommendation' or 'sales_pitch'
            
        Returns:
            Dict with role, goal, instructions or None if not found
        """
        try:
            config = self.customized_agents_collection.find_one({
                "sessionId": session_id,
                "agentType": agent_type
            })
            
            if config:
                logger.info(f"✅ Customized agent found:")
                logger.info(f"   Session: {session_id}")
                logger.info(f"   Agent Type: {agent_type}")
                return {
                    "role": config.get("role", ""),
                    "goal": config.get("goal", ""),
                    "instructions": config.get("instructions", ""),
                    "username": config.get("username"),
                    "agentCode": config.get("agentCode")
                }
            else:
                logger.debug(f"⚠️ No customized agent found for session {session_id}, agent type {agent_type}")
                return None
        except Exception as e:
            logger.error(f"❌ Error retrieving customized agent: {e}")
            return None
    
    async def delete_customized_agent(
        self,
        session_id: str,
        agent_type: str
    ) -> bool:
        """
        Delete customized agent configuration
        
        Args:
            session_id: Session identifier
            agent_type: 'product_recommendation' or 'sales_pitch'
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            result = self.customized_agents_collection.delete_one({
                "sessionId": session_id,
                "agentType": agent_type
            })
            
            logger.info(f"✅ Customized agent deleted:")
            logger.info(f"   Session: {session_id}")
            logger.info(f"   Agent Type: {agent_type}")
            logger.info(f"   Deleted count: {result.deleted_count}")
            
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"❌ Error deleting customized agent: {e}")
            return False
    
    async def get_all_customized_agents_for_session(
        self,
        session_id: str
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Get all customized agent configurations for a session
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dict with keys 'product_recommendation' and 'sales_pitch'
        """
        try:
            configs = self.customized_agents_collection.find({
                "sessionId": session_id
            })
            
            result = {
                "product_recommendation": None,
                "sales_pitch": None
            }
            
            for config in configs:
                agent_type = config.get("agentType")
                if agent_type in result:
                    result[agent_type] = {
                        "role": config.get("role", ""),
                        "goal": config.get("goal", ""),
                        "instructions": config.get("instructions", ""),
                        "username": config.get("username"),
                        "agentCode": config.get("agentCode")
                    }
            
            logger.debug(f"✅ Retrieved {len([c for c in result.values() if c])} customized agents for session {session_id}")
            return result
        except Exception as e:
            logger.error(f"❌ Error retrieving customized agents: {e}")
            return {
                "product_recommendation": None,
                "sales_pitch": None
            }
