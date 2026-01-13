"""
Knowledge routes - integrated with Qdrant (via Lyzr RAG API) and MongoDB
Uses RAG IDs from .env:
- Star_Health: Lyzr_RAG_ID (line 21)
- Competitor: Lyzr_RAG_ID_Competitors (line 22)
"""
from fastapi import APIRouter, HTTPException, Path, Query, Depends, UploadFile, File
from app.config.database import get_database
from app.config.logging_config import get_logger
from app.models.models import KnowledgeCreate, KnowledgeUpdate, KnowledgeResponse
from app.services.rag_service import RAGService
from app.routes.auth import get_current_user, require_admin
from bson import ObjectId
from datetime import datetime
import os
from typing import Optional

router = APIRouter()
logger = get_logger(__name__)

# Initialize RAG service
rag_service = RAGService()

# Get RAG IDs from environment
STAR_HEALTH_RAG_ID = os.getenv("Lyzr_RAG_ID") or os.getenv("LYZR_RAG_ID", "6942898da7d24261d6a569a6")
COMPETITOR_RAG_ID = os.getenv("Lyzr_RAG_ID_Competitors") or os.getenv("LYZR_RAG_ID_Competitors", "69428e11614e37dd3ea60dfe")

def get_rag_id(database_type: str) -> str:
    """Get the appropriate RAG ID based on database type"""
    if database_type.lower() in ["star_health", "starhealth", "star-health"]:
        return STAR_HEALTH_RAG_ID
    elif database_type.lower() in ["competitor", "competitors"]:
        return COMPETITOR_RAG_ID
    else:
        logger.warning(f"⚠️ Unknown database type: {database_type}, defaulting to Star Health")
        return STAR_HEALTH_RAG_ID

def get_knowledge_collection(db):
    """Helper function to get the correct knowledge collection"""
    collection_names = db.list_collection_names()
    if "knowledge" in collection_names:
        logger.info("📚 Using 'knowledge' collection")
        return db.knowledge
    elif "knowledges" in collection_names:
        logger.info("📚 Using 'knowledges' collection")
        return db.knowledges
    else:
        # Default to 'knowledge' (singular) as per seed script
        logger.info("📚 Using default 'knowledge' collection (may be empty)")
        return db.knowledge

@router.get("")
async def get_knowledge(database: str = Query("starHealth", description="Database type: starHealth or competitor"), current_user: dict = Depends(require_admin)):
    """Get all knowledge entries from Qdrant (via Lyzr RAG API)"""
    logger.info(f"📚 Knowledge base data requested for database: {database}")
    try:
        rag_id = get_rag_id(database)
        logger.info(f"   Using RAG ID: {rag_id}")
        
        # Fetch content from Qdrant via RAG service
        content = await rag_service.get_all_content(rag_id=rag_id)
        
        logger.info(f"✅ Retrieved {len(content)} knowledge entries from RAG")
        return {
            "success": True,
            "content": content,
            "database": database,
            "ragId": rag_id
        }
    except Exception as error:
        logger.error(f"❌ Error fetching knowledge: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch knowledge: {str(error)}")

@router.post("/text", status_code=201)
async def create_knowledge_text(
    text: str,
    source: Optional[str] = None,
    database: str = Query("starHealth", description="Database type: starHealth or competitor"),
    current_user: dict = Depends(require_admin)
):
    """Create a new knowledge entry by training text in Qdrant"""
    logger.info(f"📝 Creating new knowledge entry (text) for database: {database}")
    try:
        rag_id = get_rag_id(database)
        
        result = await rag_service.train_text(
            text=text,
            source=source or "Text Input",
            content_type="text",
            rag_id=rag_id
        )
        
        if result.get("success"):
            logger.info(f"✅ Knowledge entry created in RAG: {result.get('contentId')}")
            return {
                "success": True,
                "message": "Knowledge entry created successfully",
                "contentId": result.get("contentId"),
                "database": database,
                "ragId": rag_id
            }
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to create knowledge"))
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"❌ Error creating knowledge: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create knowledge: {str(error)}")

@router.post("/file", status_code=201)
async def create_knowledge_file(
    file: UploadFile = File(...),
    database: str = Query("starHealth", description="Database type: starHealth or competitor"),
    current_user: dict = Depends(require_admin)
):
    """Upload and train a file in Qdrant"""
    logger.info(f"📄 Uploading file for database: {database}")
    try:
        rag_id = get_rag_id(database)
        
        # Read file content
        file_content = await file.read()
        
        result = await rag_service.train_file(
            file_content=file_content,
            filename=file.filename,
            rag_id=rag_id
        )
        
        if result.get("success"):
            logger.info(f"✅ File uploaded and trained in RAG: {result.get('contentId')}")
            return {
                "success": True,
                "message": "File uploaded and trained successfully",
                "contentId": result.get("contentId"),
                "filename": file.filename,
                "database": database,
                "ragId": rag_id
            }
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to upload file"))
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"❌ Error uploading file: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(error)}")

@router.delete("/{content_id}")
async def delete_knowledge(
    content_id: str,
    database: str = Query("starHealth", description="Database type: starHealth or competitor"),
    current_user: dict = Depends(require_admin)
):
    """Delete a knowledge entry from Qdrant"""
    logger.info(f"🗑️ Deleting knowledge entry: {content_id} from database: {database}")
    try:
        rag_id = get_rag_id(database)
        
        result = await rag_service.delete_content(content_id=content_id, rag_id=rag_id)
        
        if result.get("success"):
            logger.info(f"✅ Knowledge entry deleted from RAG: {content_id}")
            return {
                "success": True,
                "message": "Knowledge deleted successfully",
                "contentId": content_id,
                "database": database
            }
        else:
            raise HTTPException(status_code=404, detail=result.get("error", "Failed to delete knowledge"))
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"❌ Error deleting knowledge: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete knowledge: {str(error)}")

@router.get("/databases")
async def get_databases(current_user: dict = Depends(require_admin)):
    """Get available databases with their RAG IDs"""
    return {
        "success": True,
        "databases": {
            "starHealth": {
                "name": "Star Health",
                "ragId": STAR_HEALTH_RAG_ID
            },
            "competitor": {
                "name": "Competitor",
                "ragId": COMPETITOR_RAG_ID
            }
        }
    }




