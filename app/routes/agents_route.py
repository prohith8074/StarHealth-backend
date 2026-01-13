"""
Agents routes - ported from Node.js backend
"""
from fastapi import APIRouter, HTTPException, Query
from app.config.database import get_database
from app.config.logging_config import get_logger
from app.models.models import AgentCreate, AgentUpdate, AgentResponse
from datetime import datetime
from bson import ObjectId
from typing import Optional
import os

router = APIRouter()
logger = get_logger(__name__)

@router.get("")
def get_agents(agent_code: Optional[str] = Query(None)):
    """Get all agents (optionally filter by agent_code)"""
    logger.info("📖 Fetching agents list")
    try:
        db = get_database()
        query = {}
        if agent_code:
            query["agent_code"] = agent_code
        
        agent_docs = db.agents.find(query).sort("createdAt", -1)
        agents = []
        for doc in agent_docs:
            doc["_id"] = str(doc["_id"])
            agents.append(doc)
        
        logger.info(f"✅ Retrieved {len(agents)} agents")
        return {"users": agents}
    except Exception as error:
        logger.error(f"❌ Error fetching agents: {error}")
        raise HTTPException(status_code=500, detail="Failed to fetch users")

@router.post("/", status_code=201)
def create_agent(agent: AgentCreate):
    """Create a new agent"""
    logger.info("➕ Creating agent")
    logger.debug(f"   Data: {agent.dict()}")
    
    try:
        if not agent.agent_code or not agent.agent_name:
            raise HTTPException(status_code=400, detail="agent_code and agent_name are required")
        
        db = get_database()
        agent_doc = {
            "agent_code": agent.agent_code,
            "agent_name": agent.agent_name,
            "role": agent.role,
            "phone_number": agent.phone_number,
            "email": agent.email,
            "createdAt": datetime.now(),
            "updatedAt": datetime.now()
        }
        result = db.agents.insert_one(agent_doc)
        agent_doc["_id"] = str(result.inserted_id)
        logger.info(f"✅ Agent created: {result.inserted_id}")
        return {"user": agent_doc}
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"❌ Error creating agent: {error}")
        raise HTTPException(status_code=500, detail="Failed to create user")

@router.put("/{id}")
def update_agent(id: str, agent: AgentUpdate):
    """Update an existing agent"""
    logger.info(f"✏️ Updating agent {id}")
    logger.debug(f"   Data: {agent.dict()}")
    
    try:
        # If agent_code or agent_name is provided, both must be provided
        if (agent.agent_code is not None or agent.agent_name is not None) and \
           (agent.agent_code is None or agent.agent_name is None):
            raise HTTPException(status_code=400, detail="agent_code and agent_name are required")
        
        db = get_database()
        update_data = {"updatedAt": datetime.now()}
        if agent.agent_code is not None:
            update_data["agent_code"] = agent.agent_code
        if agent.agent_name is not None:
            update_data["agent_name"] = agent.agent_name
        if agent.role is not None:
            update_data["role"] = agent.role
        if agent.phone_number is not None:
            update_data["phone_number"] = agent.phone_number
        if agent.email is not None:
            update_data["email"] = agent.email
        
        result = db.agents.find_one_and_update(
            {"_id": ObjectId(id)},
            {"$set": update_data},
            return_document=True
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="User not found")
        
        result["_id"] = str(result["_id"])
        logger.info(f"✅ Agent updated: {id}")
        return {"user": result}
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"❌ Error updating agent: {error}")
        raise HTTPException(status_code=500, detail="Failed to update user")

@router.delete("/{id}")
def delete_agent(id: str):
    """Delete an agent"""
    logger.info(f"🗑️ Deleting agent {id}")
    try:
        db = get_database()
        result = db.agents.find_one_and_delete({"_id": ObjectId(id)})
        if not result:
            raise HTTPException(status_code=404, detail="User not found")
        logger.info(f"✅ Agent deleted: {id}")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"❌ Error deleting agent: {error}")
        raise HTTPException(status_code=500, detail="Failed to delete user")




