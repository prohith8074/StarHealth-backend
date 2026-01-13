"""
RAG Training API Routes
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Form
from pydantic import BaseModel
from typing import Optional
from app.services.rag_service import RAGService
from app.config.logging_config import get_logger
import httpx

router = APIRouter()
logger = get_logger(__name__)

rag_service = RAGService()


@router.get("/rag/databases")
async def get_databases():
    """Get available RAG databases"""
    return {
        "success": True,
        "databases": {
            "starHealth": {
                "id": rag_service.rag_id,
                "name": "Star Health Database",
                "label": "Star Health"
            },
            "competitor": {
                "id": rag_service.competitor_rag_id,
                "name": "Competitor Database",
                "label": "Competitor"
            }
        }
    }


class TextContentRequest(BaseModel):
    text: str
    source: Optional[str] = None


class WebsiteRequest(BaseModel):
    url: str


@router.post("/rag/text")
async def add_text(request: TextContentRequest, rag_id: Optional[str] = Query(None, description="RAG ID to use (optional)")):
    """Add text content to RAG"""
    logger.info(f"📝 Adding text to RAG (RAG ID: {rag_id or 'default'})")
    try:
        result = await rag_service.train_text(
            text=request.text,
            source=request.source,
            content_type="text",
            rag_id=rag_id
        )
        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to train text"))
    except Exception as e:
        logger.error(f"❌ Error adding text: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag/file")
async def add_file(
    file: UploadFile = File(...), 
    rag_id: Optional[str] = Query(None, description="RAG ID to use (optional)"),
    rag_id_form: Optional[str] = Form(None, description="RAG ID from form data (alternative)")
):
    """Add file content to RAG - supports PDF and text files
    
    Note: rag_id can be provided as query parameter or form data field.
    Form data takes precedence if both are provided.
    """
    # Use form data rag_id if provided, otherwise use query parameter
    active_rag_id = rag_id_form or rag_id
    
    logger.info("=" * 70)
    logger.info(f"📄 FILE UPLOAD REQUEST")
    logger.info(f"   Filename: {file.filename}")
    logger.info(f"   RAG ID from query: {rag_id}")
    logger.info(f"   RAG ID from form: {rag_id_form}")
    logger.info(f"   Active RAG ID: {active_rag_id}")
    logger.info(f"   Content Type: {file.content_type}")
    logger.info("=" * 70)
    
    try:
        # Read file content as bytes
        content = await file.read()
        logger.info(f"   File size: {len(content)} bytes")
        
        # Pass bytes directly to train_file (it will handle PDF parsing or text decoding)
        result = await rag_service.train_file(
            file_content=content,
            filename=file.filename,
            rag_id=active_rag_id
        )
        
        logger.info(f"✅ File upload result: {result.get('success', False)}")
        if not result.get('success'):
            logger.error(f"   Error: {result.get('error', 'Unknown error')}")
        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to train file"))
    except Exception as e:
        logger.error(f"❌ Error adding file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag/website")
async def add_website(request: WebsiteRequest, rag_id: Optional[str] = Query(None, description="RAG ID to use (optional)")):
    """Add website content to RAG"""
    logger.info(f"🌐 Adding website to RAG: {request.url} (RAG ID: {rag_id or 'default'})")
    try:
        # Fetch website content
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(request.url)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Failed to fetch website: {response.status_code}")
            
            # Extract text content (simple - can be enhanced with BeautifulSoup)
            website_text = response.text[:50000]  # Limit to 50k chars
        
        result = await rag_service.train_website(
            url=request.url,
            website_content=website_text,
            rag_id=rag_id
        )
        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to train website"))
    except httpx.ConnectError:
        raise HTTPException(status_code=400, detail="Failed to connect to website")
    except Exception as e:
        logger.error(f"❌ Error adding website: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rag/content")
async def get_all_content(rag_id: Optional[str] = Query(None, description="RAG ID to use (optional)")):
    """Get all RAG content with stats"""
    logger.info(f"📖 Fetching all RAG content (RAG ID: {rag_id or 'default'})")
    try:
        contents = await rag_service.get_all_content(rag_id=rag_id)
        logger.info(f"✅ Returning {len(contents)} content items")
        
        # Calculate stats
        total_items = len(contents)
        total_usage = sum(item.get("usageCount", 0) for item in contents)
        confidence_scores = [item.get("confidence", 95) for item in contents if item.get("confidence")]
        avg_confidence = round(sum(confidence_scores) / len(confidence_scores)) if confidence_scores else 95
        
        # Group by category
        category_counts = {}
        for item in contents:
            category = item.get("category", "General")
            category_counts[category] = category_counts.get(category, 0) + 1
        
        # Ensure all items have required fields with defaults
        formatted_contents = []
        for item in contents:
            formatted_item = {
                "contentId": item.get("contentId", str(item.get("_id", ""))),
                "type": item.get("type", "text"),
                "source": item.get("source", "Unknown"),
                "textPreview": item.get("textPreview", item.get("text", "")[:200] + "..." if len(item.get("text", "")) > 200 else item.get("text", "")),
                "textLength": item.get("textLength", len(item.get("text", ""))),
                "trainedAt": item.get("trainedAt"),
                "status": item.get("status", "trained"),
                "category": item.get("category", "General"),
                "tags": item.get("tags", []),
                "usageCount": item.get("usageCount", 0),
                "confidence": item.get("confidence", 95),
                "question": item.get("question", ""),
                "answer": item.get("answer", item.get("textPreview", ""))
            }
            formatted_contents.append(formatted_item)
        
        # Determine active RAG ID
        active_rag_id = rag_id or rag_service.rag_id
        
        return {
            "success": True,
            "content": formatted_contents,
            "count": len(formatted_contents),
            "ragId": active_rag_id,
            "stats": {
                "totalItems": total_items,
                "totalUsage": total_usage,
                "avgConfidence": avg_confidence,
                "byCategory": category_counts
            }
        }
    except Exception as e:
        logger.error(f"❌ Error fetching content: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/rag/content/{content_id}")
async def delete_content(
    content_id: str, 
    rag_id: Optional[str] = Query(None, description="RAG ID to use (optional)")
):
    """Delete RAG content"""
    logger.info("=" * 70)
    logger.info(f"🗑️ DELETE REQUEST")
    logger.info(f"   Content ID: {content_id}")
    logger.info(f"   RAG ID from query: {rag_id}")
    logger.info("=" * 70)
    
    try:
        result = await rag_service.delete_content(content_id, rag_id=rag_id)
        
        logger.info(f"✅ Delete result: {result.get('success', False)}")
        if not result.get('success'):
            logger.error(f"   Error: {result.get('error', 'Unknown error')}")
        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=404, detail=result.get("error", "Content not found"))
    except Exception as e:
        logger.error(f"❌ Error deleting content: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

