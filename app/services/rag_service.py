"""
RAG Training Service for Lyzr
Handles training RAG system with files, websites, and text
"""
import httpx
import os
import asyncio
from dotenv import load_dotenv
from app.config.logging_config import get_logger
from app.services.redis_service import RedisService
from datetime import datetime, timedelta
import uuid
import json

load_dotenv()

logger = get_logger(__name__)

# Constants
CACHE_TTL = 900  # 15 minutes

class RAGService:
    """Service for training Lyzr RAG system with Redis Caching"""
    
    def __init__(self):
        # Check both naming conventions for API key
        self.api_key = os.getenv("Lyzr_API_KEY") or os.getenv("LYZR_API_KEY")
        # Use provided RAG ID - check both naming conventions
        # Priority: Lyzr_RAG_ID (user specified) > LYZR_RAG_ID (standard) > default
        # Priority: Lyzr_RAG_ID (user specified) > LYZR_RAG_ID (standard)
        self.rag_id = os.getenv("Lyzr_RAG_ID") or os.getenv("LYZR_RAG_ID")
        # Competitor RAG ID - check both naming conventions
        # Priority: Lyzr_RAG_ID_Competitors (user specified) > LYZR_RAG_ID_Competitors (standard)
        self.competitor_rag_id = os.getenv("Lyzr_RAG_ID_Competitors") or os.getenv("LYZR_RAG_ID_Competitors")
        # Lyzr RAG URL format: https://rag-prod.studio.lyzr.ai/v3/train/text/
        self.rag_url = os.getenv("LYZR_RAG_URL", "https://rag-prod.studio.lyzr.ai/v3/train/text/")
        
        # Initialize Redis
        self.redis_service = RedisService()
        
        logger.info(f"🔧 RAG Configuration:")
        logger.info(f"   Star Health RAG ID: {self.rag_id}")
        logger.info(f"   Competitor RAG ID: {self.competitor_rag_id}")
        logger.info(f"   RAG URL: {self.rag_url}")
        
    def _get_file_type(self, filename: str) -> str:
        """Determine file type from filename extension"""
        filename_lower = filename.lower()
        if filename_lower.endswith('.pdf'):
            return 'pdf'
        elif filename_lower.endswith(('.docx', '.doc')):
            return 'docx'
        elif filename_lower.endswith(('.txt', '.md')):
            return 'text'
        else:
            return 'file'
    
    async def train_text(self, text: str, source: str = None, content_type: str = "text", rag_id: str = None) -> dict:
        """
        Train RAG with text content
        """
        # Use provided rag_id or fallback to instance rag_id
        active_rag_id = rag_id or self.rag_id
        
        logger.info(f"📚 Training RAG with {content_type} (RAG ID: {active_rag_id})")
        
        if not active_rag_id:
            return {"success": False, "error": "RAG ID not configured"}
        
        if not self.api_key:
            return {"success": False, "error": "LYZR_API_KEY not configured"}
        
        try:
            payload = {
                "data": [
                    {
                        "text": text,
                        "source": source or text[:100]
                    }
                ],
                "chunk_size": 1000,
                "chunk_overlap": 100
            }
            
            base_url = "https://rag-prod.studio.lyzr.ai/v3/train/text/"
            full_url = f"{base_url}?rag_id={active_rag_id}"
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    full_url,
                    json=payload,
                    headers={
                        "accept": "application/json",
                        "Content-Type": "application/json",
                        "x-api-key": self.api_key
                    }
                )
                
                if response.status_code == 200:
                    result_data = response.json()
                    doc_id = (
                        result_data.get("doc_id") or 
                        result_data.get("document_id") or 
                        result_data.get("id") or 
                        str(uuid.uuid4())
                    )
                    
                    # Invalidate Cache after training
                    self._invalidate_cache(active_rag_id)
                    
                    return {
                        "success": True,
                        "contentId": doc_id,
                        "message": "Content trained successfully"
                    }
                else:
                    error_msg = f"RAG API returned {response.status_code}: {response.text[:200]}"
                    logger.error(f"❌ {error_msg}")
                    return {"success": False, "error": error_msg}
                    
        except Exception as e:
            error_msg = f"Error training RAG: {str(e)}"
            logger.error(f"❌ {error_msg}", exc_info=True)
            return {"success": False, "error": error_msg}
    
    async def train_file(self, file_content: bytes, filename: str, rag_id: str = None) -> dict:
        """Train RAG with file content"""
        active_rag_id = rag_id or self.rag_id
        
        logger.info(f"📄 Training RAG with file: {filename} (RAG ID: {active_rag_id})")
        
        if not active_rag_id:
            return {"success": False, "error": "RAG ID not configured"}
        
        if not self.api_key:
            return {"success": False, "error": "LYZR_API_KEY not configured"}
        
        filename_lower = filename.lower()
        is_pdf = filename_lower.endswith('.pdf')
        is_docx = filename_lower.endswith('.docx') or filename_lower.endswith('.doc')
        is_txt = filename_lower.endswith('.txt') or filename_lower.endswith('.md')
        
        if not filename.startswith('storage/'):
            import os
            base_filename = os.path.basename(filename)
            formatted_filename = f"storage/{base_filename}"
        else:
            formatted_filename = filename
        
        try:
            if is_pdf:
                train_url = "https://rag-prod.studio.lyzr.ai/v3/train/pdf/"
                mime_type = 'application/pdf'
                file_type = "PDF"
            elif is_docx:
                train_url = "https://rag-prod.studio.lyzr.ai/v3/train/docx/"
                mime_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                file_type = "DOCX"
            elif is_txt:
                train_url = "https://rag-prod.studio.lyzr.ai/v3/train/txt/"
                mime_type = 'text/plain'
                file_type = "TXT"
            else:
                logger.warning(f"⚠️ Unknown file type: {filename}, attempting to decode as text")
                try:
                    file_text = file_content.decode('utf-8', errors='ignore')
                except:
                    file_text = file_content.decode('latin-1', errors='ignore')
                return await self.train_text(file_text, source=formatted_filename, content_type="file", rag_id=active_rag_id)
            
            async with httpx.AsyncClient(timeout=120.0) as client:
                files = {
                    'file': (formatted_filename, file_content, mime_type)
                }
                data = {
                    'rag_id': active_rag_id
                }
                
                response = await client.post(
                    train_url,
                    files=files,
                    data=data,
                    headers={
                        "accept": "application/json",
                        "x-api-key": self.api_key
                    }
                )
                
                if response.status_code == 200:
                    try:
                        result_data = response.json()
                        doc_id = (
                            result_data.get("doc_id") or 
                            result_data.get("document_id") or 
                            result_data.get("id") or 
                            result_data.get("filename") or
                            result_data.get("file_name") or
                            formatted_filename
                        )
                        
                        if not doc_id.startswith('storage/'):
                            import os
                            base_name = os.path.basename(doc_id)
                            doc_id = f"storage/{base_name}"
                        
                        # Invalidate Cache
                        self._invalidate_cache(active_rag_id)
                        
                        return {
                            "success": True,
                            "contentId": doc_id,
                            "message": f"{file_type} file uploaded and trained successfully",
                            "docId": doc_id
                        }
                    except Exception as e:
                        self._invalidate_cache(active_rag_id)
                        return {
                            "success": True,
                            "contentId": formatted_filename,
                            "message": f"{file_type} file uploaded successfully"
                        }
                else:
                    error_text = response.text[:500] if hasattr(response, 'text') else str(response.status_code)
                    logger.error(f"❌ {file_type} upload failed: {response.status_code}: {error_text}")
                    return {"success": False, "error": f"{file_type} upload failed: {response.status_code}"}
                
        except Exception as e:
            error_msg = f"Error training file: {str(e)}"
            logger.error(f"❌ {error_msg}", exc_info=True)
            return {"success": False, "error": error_msg}
    
    async def train_website(self, url: str, website_content: str, rag_id: str = None) -> dict:
        """Train RAG with website content"""
        return await self.train_text(website_content, source=url, content_type="website", rag_id=rag_id)
    
    async def get_all_content(self, rag_id: str = None) -> list:
        """
        Get all RAG content for the configured RAG ID.
        Uses Redis for caching (15m TTL).
        """
        active_rag_id = rag_id or self.rag_id
        
        if not active_rag_id:
            logger.error("❌ RAG ID not configured")
            return []

        # 1. Check Redis Cache
        cache_key = f"rag_content:{active_rag_id}"
        try:
            cached_data = self.redis_service.redis_client.get(cache_key)
            if cached_data:
                logger.info(f"✅ REDIS HIT: rag_content")
                return json.loads(cached_data)
        except Exception as e:
            logger.warning(f"⚠️ Redis read error: {e}")

        logger.info(f"🌐 CACHE MISS: Fetching RAG content from Lyzr API")
        
        # 2. Fetch from API (Source of Truth)
        content = await self._fetch_content_from_api(active_rag_id)
        
        # 3. Store in Redis
        if content:
            try:
                self.redis_service.redis_client.setex(
                    cache_key,
                    CACHE_TTL,
                    json.dumps(content)
                )
                logger.info(f"✅ Cached RAG content in Redis (TTL {CACHE_TTL}s)")
            except Exception as e:
                logger.warning(f"⚠️ Redis write error: {e}")
                
        return content

    def _invalidate_cache(self, rag_id: str):
        """Invalidate RAG content cache"""
        try:
            cache_key = f"rag_content:{rag_id}"
            self.redis_service.redis_client.delete(cache_key)
            logger.info(f"🗑️ Invalidated RAG cache for {rag_id}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to invalidate cache: {e}")

    async def _fetch_content_from_api(self, active_rag_id: str) -> list:
        """Fetch content directly from Lyzr API"""
        contents: list[dict] = []
        
        if not self.api_key:
            return []
        
        try:
            fetch_url = f"https://rag-prod.studio.lyzr.ai/v3/rag/documents/{active_rag_id}/"
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    fetch_url,
                    headers={
                        "accept": "application/json",
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json"
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if isinstance(data, list):
                        documents = data
                    elif isinstance(data, dict):
                        documents = data.get("documents", data.get("data", data.get("content", [])))
                    else:
                        documents = []
                    
                    for idx, doc in enumerate(documents):
                        if isinstance(doc, str):
                            filename = doc
                            import os
                            base_filename = os.path.basename(filename)
                            
                            content_item = {
                                "contentId": filename,
                                "ragId": active_rag_id,
                                "type": self._get_file_type(filename),
                                "source": filename,
                                "textPreview": base_filename,
                                "textLength": 0,
                                "trainedAt": datetime.utcnow().isoformat(),
                                "status": "trained",
                                "text": "",
                                "metadata": {
                                    "filename": base_filename,
                                    "full_path": filename
                                },
                            }
                            contents.append(content_item)
                        elif isinstance(doc, dict):
                            text = doc.get("text", doc.get("content", doc.get("data", "")))
                            filename = (
                                doc.get("source") or 
                                doc.get("filename") or 
                                doc.get("file_name") or 
                                doc.get("id") or
                                f"doc_{idx}"
                            )
                            
                            import os
                            base_filename = os.path.basename(filename) if "/" in filename else filename
                            
                            content_item = {
                                "contentId": filename,
                                "ragId": active_rag_id,
                                "type": self._get_file_type(filename),
                                "source": filename,
                                "textPreview": base_filename if not text else (text[:200] + "..." if len(text) > 200 else text),
                                "textLength": len(text),
                                "trainedAt": doc.get("trainedAt", datetime.utcnow().isoformat()),
                                "status": "trained",
                                "text": text,
                                "metadata": doc.get("metadata", {}),
                            }
                            contents.append(content_item)
                    return contents
                    
                elif response.status_code == 404:
                    return []
                else:
                    logger.error(f"❌ Lyzr RAG API returned {response.status_code}")
                    return []
                    
        except Exception as e:
            logger.error(f"❌ Error fetching from Lyzr RAG API: {e}", exc_info=True)
            return []
    
    async def delete_content(self, content_id: str, rag_id: str = None) -> dict:
        """Delete RAG content from Lyzr RAG API"""
        active_rag_id = rag_id or self.rag_id
        
        if not active_rag_id or not self.api_key:
            return {"success": False, "error": "Configuration missing"}
        
        # Invalidate cache before/after deletion attempts
        self._invalidate_cache(active_rag_id)
        
        # Simplification: Try to delete directly. The original logic was complex because it tried to verify existence.
        # For this refactor, I will retain the core logic but simplified.
        
        try:
             # Try to find the document first to get exact ID
            all_content = await self.get_all_content(rag_id=active_rag_id)
            doc_id_to_delete = None
            
            # Match by contentId or source
            for item in all_content:
                if str(item.get("contentId")) == str(content_id) or str(item.get("source")) == str(content_id):
                    doc_id_to_delete = item.get("contentId") or item.get("source")
                    break
            
            if not doc_id_to_delete:
                # If numeric index
                if content_id.isdigit():
                    idx = int(content_id)
                    if 0 <= idx < len(all_content):
                        doc_id_to_delete = all_content[idx].get("contentId")
            
            if not doc_id_to_delete:
                # Fallback to provided ID
                doc_id_to_delete = content_id

            delete_url = f"https://rag-prod.studio.lyzr.ai/v3/rag/{active_rag_id}/docs/"
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    "DELETE",
                    delete_url,
                    json=[doc_id_to_delete],
                    headers={
                        "accept": "application/json",
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json"
                    }
                )
                
                if response.status_code == 200:
                    self._invalidate_cache(active_rag_id)
                    return {"success": True, "contentId": content_id}
                else:
                    return {"success": False, "error": f"Delete failed: {response.status_code}"}
                    
        except Exception as e:
            logger.error(f"Delete error: {e}")
            return {"success": False, "error": str(e)}

async def trigger_rag_warmup():
    """Trigger background warmup of RAG content"""
    service = RAGService()
    await service.get_all_content()

