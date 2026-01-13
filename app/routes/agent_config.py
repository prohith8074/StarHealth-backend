from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.config.logging_config import get_logger
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
logger = get_logger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agent-config"])

# MongoDB connection
mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/Star_Health_Whatsapp_bot"
mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
db_name = "Star_Health_Whatsapp_bot"
db = mongo_client[db_name]

# New dedicated collection for agent prompts/configs
# Each document:
# {
#   agentType: "product" | "sales",
#   mode: "default" | "customize",
#   role: str,
#   goal: str,
#   instructions: str,
#   createdAt: datetime,
#   updatedAt: datetime
# }
prompts_collection = db["Prompts"]

class AgentConfigRequest(BaseModel):
    agentType: str  # 'product' | 'sales' | 'onboarding'
    mode: str  # 'default' or 'customize'
    # For product/sales: { role, goal, instructions }
    # For onboarding: {
    #   greetingMessage, menuMessage, invalidCodeMessage,
    #   authFailedMessage, invalidOptionMessage
    # }
    config: Optional[dict] = None

@router.get("/config")
async def get_agent_configs():
    """Get current agent configurations"""
    try:
        product_config = prompts_collection.find_one({"agentType": "product"})
        sales_config = prompts_collection.find_one({"agentType": "sales"})
        onboarding_config = prompts_collection.find_one({"agentType": "onboarding"})
        
        # Default onboarding / authentication messages
        default_onboarding = {
            "greetingMessage": "Hi 👋 Please enter your Agent Code.",
            "menuMessage": "Welcome {agent_name}! Please select an option:\n1. Product Recommendation\n2. Sales Pitch",
            "invalidCodeMessage": "❌ Invalid agent code. Please try again with a valid code.",
            "authFailedMessage": "❌ Authentication failed. The phone number associated with this agent code doesn't match your number. Please try again with a valid agent code.",
            "invalidOptionMessage": "Please select option 1 (Product Recommendation) or option 2 (Sales Pitch).",
        }
        
        onboarding = default_onboarding.copy()
        if onboarding_config:
            for key in default_onboarding.keys():
                if key in onboarding_config and onboarding_config.get(key):
                    onboarding[key] = onboarding_config.get(key)
        
        return {
            "success": True,
            "configs": {
                "product": {
                    "mode": product_config.get("mode", "default") if product_config else "default",
                    "role": product_config.get("role", "") if product_config else "",
                    "goal": product_config.get("goal", "") if product_config else "",
                    "instructions": product_config.get("instructions", "") if product_config else "",
                    "createdAt": product_config.get("createdAt") if product_config else None,
                    "updatedAt": product_config.get("updatedAt") if product_config else None,
                } if product_config else {"mode": "default", "role": "", "goal": "", "instructions": ""},
                "sales": {
                    "mode": sales_config.get("mode", "default") if sales_config else "default",
                    "role": sales_config.get("role", "") if sales_config else "",
                    "goal": sales_config.get("goal", "") if sales_config else "",
                    "instructions": sales_config.get("instructions", "") if sales_config else "",
                    "createdAt": sales_config.get("createdAt") if sales_config else None,
                    "updatedAt": sales_config.get("updatedAt") if sales_config else None,
                } if sales_config else {"mode": "default", "role": "", "goal": "", "instructions": ""},
                "onboarding": onboarding,
            }
        }
    except Exception as e:
        logger.error(f"Error fetching agent configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/config")
async def save_agent_config(request: AgentConfigRequest):
    """Save agent configuration"""
    try:
        # For product/sales agents, enforce role/goal/instructions when customizing.
        if request.mode == "customize" and request.agentType in ("product", "sales"):
            if not request.config or not request.config.get("role") or not request.config.get("goal") or not request.config.get("instructions"):
                raise HTTPException(status_code=400, detail="Role, Goal, and Instructions are required for custom agents")
        
        now = datetime.utcnow()

        config_doc = {
            "agentType": request.agentType,
            "mode": request.mode,
            "updatedAt": now,
        }
        
        # Shape the stored document based on agentType
        if request.agentType in ("product", "sales"):
            config_doc.update({
                "role": request.config.get("role", "") if request.config else "",
                "goal": request.config.get("goal", "") if request.config else "",
                "instructions": request.config.get("instructions", "") if request.config else "",
            })
        elif request.agentType == "onboarding":
            cfg = request.config or {}
            config_doc.update({
                "greetingMessage": cfg.get("greetingMessage", ""),
                "menuMessage": cfg.get("menuMessage", ""),
                "invalidCodeMessage": cfg.get("invalidCodeMessage", ""),
                "authFailedMessage": cfg.get("authFailedMessage", ""),
                "invalidOptionMessage": cfg.get("invalidOptionMessage", ""),
            })
        
        # Save version history before updating
        existing_config = prompts_collection.find_one({"agentType": request.agentType})
        if existing_config and request.mode == "customize":
            # Create version history entry
            version_collection = db["PromptVersions"]
            version_number = version_collection.count_documents({"agentType": request.agentType}) + 1
            
            version_doc = {
                "agentType": request.agentType,
                "version": version_number,
                "mode": existing_config.get("mode", "default"),
                "createdAt": existing_config.get("updatedAt", existing_config.get("createdAt", now)),
            }
            
            # Copy config data based on agentType
            if request.agentType in ("product", "sales"):
                version_doc.update({
                    "role": existing_config.get("role", ""),
                    "goal": existing_config.get("goal", ""),
                    "instructions": existing_config.get("instructions", ""),
                })
            elif request.agentType == "onboarding":
                version_doc.update({
                    "greetingMessage": existing_config.get("greetingMessage", ""),
                    "menuMessage": existing_config.get("menuMessage", ""),
                    "invalidCodeMessage": existing_config.get("invalidCodeMessage", ""),
                    "authFailedMessage": existing_config.get("authFailedMessage", ""),
                    "invalidOptionMessage": existing_config.get("invalidOptionMessage", ""),
                })
            
            version_collection.insert_one(version_doc)
            logger.info(f"📝 Saved version {version_number} for {request.agentType} agent")
        
        # Upsert configuration in Prompts collection
        prompts_collection.update_one(
            {"agentType": request.agentType},
            {
                "$set": config_doc,
                "$setOnInsert": {"createdAt": now},
            },
            upsert=True
        )
        
        # 🔒 INVALIDATE BOT LOGIC CACHE for onboarding messages
        if request.agentType == "onboarding":
            try:
                from app.services.bot_logic import invalidate_onboarding_cache
                invalidate_onboarding_cache()
                logger.info("🔄 Onboarding cache invalidated after save")
            except Exception as cache_err:
                logger.warning(f"⚠️ Could not invalidate onboarding cache: {cache_err}")
        
        logger.info(f"✅ Saved {request.agentType} agent configuration: mode={request.mode}")
        
        return {
            "success": True,
            "message": f"{request.agentType} agent configuration saved successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving agent config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/version-history")
async def get_version_history():
    """Get version history for all agent types"""
    try:
        version_collection = db["PromptVersions"]
        
        onboarding_versions = list(version_collection.find(
            {"agentType": "onboarding"}
        ).sort("createdAt", -1).limit(50))
        
        product_versions = list(version_collection.find(
            {"agentType": "product"}
        ).sort("createdAt", -1).limit(50))
        
        sales_versions = list(version_collection.find(
            {"agentType": "sales"}
        ).sort("createdAt", -1).limit(50))
        
        # Convert ObjectId to string for JSON serialization
        from bson import ObjectId
        def convert_objectid(obj):
            if isinstance(obj, ObjectId):
                return str(obj)
            return obj
        
        def process_versions(versions):
            return [{**v, "_id": str(v["_id"])} for v in versions]
        
        return {
            "success": True,
            "versions": {
                "onboarding": process_versions(onboarding_versions),
                "product": process_versions(product_versions),
                "sales": process_versions(sales_versions),
            }
        }
    except Exception as e:
        logger.error(f"Error fetching version history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class RestoreVersionRequest(BaseModel):
    agentType: str
    versionId: str

@router.post("/restore-version")
async def restore_version(request: RestoreVersionRequest):
    """Restore a previous version of agent configuration"""
    try:
        from bson import ObjectId
        
        version_collection = db["PromptVersions"]
        version = version_collection.find_one({"_id": ObjectId(request.versionId), "agentType": request.agentType})
        
        if not version:
            raise HTTPException(status_code=404, detail="Version not found")
        
        # Create new version from current config before restoring
        existing_config = prompts_collection.find_one({"agentType": request.agentType})
        if existing_config:
            version_number = version_collection.count_documents({"agentType": request.agentType}) + 1
            now = datetime.utcnow()
            
            version_doc = {
                "agentType": request.agentType,
                "version": version_number,
                "mode": existing_config.get("mode", "default"),
                "createdAt": existing_config.get("updatedAt", existing_config.get("createdAt", now)),
            }
            
            if request.agentType in ("product", "sales"):
                version_doc.update({
                    "role": existing_config.get("role", ""),
                    "goal": existing_config.get("goal", ""),
                    "instructions": existing_config.get("instructions", ""),
                })
            elif request.agentType == "onboarding":
                version_doc.update({
                    "greetingMessage": existing_config.get("greetingMessage", ""),
                    "menuMessage": existing_config.get("menuMessage", ""),
                    "invalidCodeMessage": existing_config.get("invalidCodeMessage", ""),
                    "authFailedMessage": existing_config.get("authFailedMessage", ""),
                    "invalidOptionMessage": existing_config.get("invalidOptionMessage", ""),
                })
            
            version_collection.insert_one(version_doc)
        
        # Restore the version
        now = datetime.utcnow()
        config_doc = {
            "agentType": request.agentType,
            "mode": version.get("mode", "customize"),
            "updatedAt": now,
        }
        
        if request.agentType in ("product", "sales"):
            config_doc.update({
                "role": version.get("role", ""),
                "goal": version.get("goal", ""),
                "instructions": version.get("instructions", ""),
            })
        elif request.agentType == "onboarding":
            config_doc.update({
                "greetingMessage": version.get("greetingMessage", ""),
                "menuMessage": version.get("menuMessage", ""),
                "invalidCodeMessage": version.get("invalidCodeMessage", ""),
                "authFailedMessage": version.get("authFailedMessage", ""),
                "invalidOptionMessage": version.get("invalidOptionMessage", ""),
            })
        
        prompts_collection.update_one(
            {"agentType": request.agentType},
            {
                "$set": config_doc,
                "$setOnInsert": {"createdAt": now},
            },
            upsert=True
        )
        
        logger.info(f"✅ Restored version {version.get('version')} for {request.agentType} agent")
        
        return {
            "success": True,
            "message": f"Version {version.get('version')} restored successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restoring version: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class CustomizeAgentRequest(BaseModel):
    """Request to customize an agent for a specific session"""
    sessionId: str
    agentType: str  # 'product_recommendation' or 'sales_pitch'
    role: str
    goal: str
    instructions: str
    username: Optional[str] = None
    agentCode: Optional[str] = None


@router.post("/customize")
async def customize_agent(request: CustomizeAgentRequest):
    """
    Save customized agent configuration for a session
    
    This stores the user-provided Role, Goal, and Instructions for the specific agent type.
    These will be sent to Lyzr as dynamic context for each message in that session.
    
    Args:
        sessionId: WhatsApp session identifier
        agentType: 'product_recommendation' or 'sales_pitch'
        role: Custom role for the agent
        goal: Custom goal for the agent
        instructions: Custom instructions for the agent
        username: Optional username
        agentCode: Optional agent code
    """
    try:
        from app.services.customized_agent_service import CustomizedAgentService
        
        # Validate required fields
        if not request.sessionId or not request.agentType:
            raise HTTPException(status_code=400, detail="sessionId and agentType are required")
        
        if not request.role or not request.goal or not request.instructions:
            raise HTTPException(status_code=400, detail="role, goal, and instructions are required")
        
        # Validate agentType
        if request.agentType not in ["product_recommendation", "sales_pitch"]:
            raise HTTPException(status_code=400, detail="agentType must be 'product_recommendation' or 'sales_pitch'")
        
        # Initialize service
        customized_agent_service = CustomizedAgentService()
        
        # Save customized agent
        success = await customized_agent_service.save_customized_agent(
            session_id=request.sessionId,
            agent_type=request.agentType,
            role=request.role,
            goal=request.goal,
            instructions=request.instructions,
            username=request.username,
            agent_code=request.agentCode
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save customized agent")
        
        logger.info(f"✅ Customized agent saved successfully")
        logger.info(f"   Session: {request.sessionId}")
        logger.info(f"   Agent Type: {request.agentType}")
        
        return {
            "success": True,
            "message": f"Customized {request.agentType} agent saved for session {request.sessionId}",
            "sessionId": request.sessionId,
            "agentType": request.agentType
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error customizing agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customize/{session_id}")
async def get_customized_agents(session_id: str):
    """
    Get all customized agent configurations for a session
    
    Returns both product_recommendation and sales_pitch customizations if they exist
    """
    try:
        from app.services.customized_agent_service import CustomizedAgentService
        
        customized_agent_service = CustomizedAgentService()
        
        agents = await customized_agent_service.get_all_customized_agents_for_session(session_id)
        
        logger.info(f"✅ Retrieved customized agents for session {session_id}")
        
        return {
            "success": True,
            "sessionId": session_id,
            "customizedAgents": agents
        }
    except Exception as e:
        logger.error(f"❌ Error retrieving customized agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


