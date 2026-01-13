from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import Response
from app.routes import chat, whatsapp, rag, agent_config, dashboard, knowledge, feedback_route, agents_route, agents_stats, users_route, auth, websocket, health, products_route
from app.config.logging_config import setup_logging, get_logger
from app.services.mongo_watcher import setup_mongo_watcher
from app.config.database import get_database
from app.services.readiness_monitor import get_monitor
from fastapi.responses import JSONResponse
import os
import asyncio

# #region agent log
# Instrumentation to debug .env parsing errors
try:
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_path):
        # Get project root directory (two levels up from app/main.py)
        project_root = os.path.dirname(os.path.dirname(__file__))
        log_dir = os.path.join(project_root, '.cursor')
        # Create directory if it doesn't exist (with error handling)
        try:
            os.makedirs(log_dir, exist_ok=True)
        except (OSError, PermissionError) as dir_error:
            # If we can't create the directory, skip logging
            pass
        else:
            log_path = os.path.join(log_dir, 'debug.log')
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    with open(log_path, 'a', encoding='utf-8') as log_file:
                        import json
                        import time
                        for i, line in enumerate(lines, 1):
                            log_file.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"main.py:12","message":f"ENV line {i}","data":{"lineNumber":i,"lineContent":line.rstrip(),"lineLength":len(line),"hasEquals":'=' in line,"startsWithHash":line.strip().startswith('#')},"timestamp":int(time.time()*1000)}) + '\n')
            except (OSError, PermissionError, IOError):
                # Silently fail if we can't write to the log file
                pass
except Exception as e:
    # Get project root directory (two levels up from app/main.py)
    try:
        project_root = os.path.dirname(os.path.dirname(__file__))
        log_dir = os.path.join(project_root, '.cursor')
        # Create directory if it doesn't exist
        try:
            os.makedirs(log_dir, exist_ok=True)
        except (OSError, PermissionError):
            # If we can't create the directory, skip logging
            pass
        else:
            log_path = os.path.join(log_dir, 'debug.log')
            try:
                with open(log_path, 'a', encoding='utf-8') as log_file:
                    import json
                    import time
                    log_file.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"main.py:12","message":"ENV file read error","data":{"error":str(e)},"timestamp":int(time.time()*1000)}) + '\n')
            except (OSError, PermissionError, IOError):
                # Silently fail if we can't write to the log file
                pass
    except Exception:
        # Silently fail if there's any error with logging setup
        pass
# #endregion

# Setup logging
setup_logging()
logger = get_logger(__name__)

app = FastAPI(title="Star Health Bot API")

logger.info("🚀 Star Health Bot API Starting...")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(whatsapp.router, prefix="/api", tags=["whatsapp"])
app.include_router(rag.router, prefix="/api", tags=["rag"])
app.include_router(agent_config.router, tags=["agent-config"])

# Routes ported from Node.js backend
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])
app.include_router(feedback_route.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(agents_route.router, prefix="/api/agents", tags=["agents"])
app.include_router(agents_stats.router, prefix="/api/agents/stats", tags=["agents-stats"])
app.include_router(users_route.router, prefix="/api/users", tags=["users"])
app.include_router(products_route.router, prefix="/api/products", tags=["products"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(websocket.router, tags=["websocket"])

# 🔒 ENTERPRISE: Health endpoints (NO prefix - direct /health/*)
app.include_router(health.router, tags=["health"])

# Root POST "/" endpoint - redirect to /webhook (for misconfigured webhooks)
@app.post("/")
async def root_post_redirect(request: Request, background_tasks: BackgroundTasks):
    """
    Handle POST requests to root "/" - redirects to /webhook handler
    This catches misconfigured webhook URLs pointing to "/" instead of "/webhook"
    """
    logger.warning("⚠️ POST received at root '/' - redirecting to /webhook handler")
    logger.info(f"   Request from: {request.client.host if request.client else 'unknown'}")
    
    # Forward to the webhook handler
    try:
        form_data = await request.form()
        MessageSid = form_data.get("MessageSid")
        From = form_data.get("From")
        To = form_data.get("To")
        Body = form_data.get("Body")
        
        # If it looks like a Twilio webhook, process it
        if MessageSid and From and Body:
            logger.info("📧 Detected Twilio webhook at root, forwarding to handler")
            from app.routes.whatsapp import _process_whatsapp_message
            twiml_response = await _process_whatsapp_message(
                MessageSid=MessageSid, 
                From=From, 
                To=To, 
                Body=Body,
                background_tasks=background_tasks
            )
            return Response(content=str(twiml_response), media_type="application/xml")
        else:
            # Not a valid webhook request
            return {"status": "ok", "message": "Use /webhook for webhooks, /api/* for API endpoints"}
    except Exception as e:
        logger.error(f"❌ Error handling root POST: {e}")
        return {"status": "ok", "message": "Use /webhook for webhooks"}

# Root /webhook endpoint for Twilio (bypasses /api prefix)
@app.post("/webhook")
async def webhook_root(request: Request, background_tasks: BackgroundTasks):
    """
    Root webhook endpoint for Twilio WhatsApp
    Handles incoming messages at /webhook (not /api/webhook)
    Forwards to whatsapp router handler
    """
    logger.info("=" * 70)
    logger.info("📧 WEBHOOK RECEIVED AT ROOT /webhook")
    logger.info("=" * 70)
    
    try:
        # Get form data
        form_data = await request.form()
        MessageSid = form_data.get("MessageSid")
        From = form_data.get("From")
        To = form_data.get("To")
        Body = form_data.get("Body")
        
        logger.info(f"📱 Message Details:")
        logger.info(f"   From: {From}")
        logger.info(f"   To: {To}")
        logger.info(f"   MessageSid: {MessageSid}")
        logger.info(f"   Body: {Body}")
        logger.info("=" * 70)
        
        # Validate required fields
        if not all([MessageSid, From, To, Body]):
            logger.error(f"❌ Missing required fields")
            logger.error(f"   MessageSid: {MessageSid}")
            logger.error(f"   From: {From}")
            logger.error(f"   To: {To}")
            logger.error(f"   Body: {Body}")
            return {"status": "error", "message": "Missing required fields"}
        
        # Import and call the whatsapp webhook handler
        from app.routes.whatsapp import _process_whatsapp_message
        twiml_response = await _process_whatsapp_message(
            MessageSid=MessageSid, 
            From=From, 
            To=To, 
            Body=Body,
            background_tasks=background_tasks
        )
        
        # Convert to string for logging and response
        twiml_str = str(twiml_response)
        logger.info("=" * 70)
        logger.info(f"📤 WEBHOOK RESPONSE READY TO SEND TO TWILIO")
        logger.info(f"   Content-Type: application/xml")
        logger.info(f"   Length: {len(twiml_str)} characters")
        logger.debug(f"   TwiML Content:\n{twiml_str}")
        logger.info("=" * 70)
        
        # Return as XML response (TwiML format)
        return Response(content=twiml_str, media_type="application/xml")
    
    except Exception as e:
        logger.error(f"❌ Error processing webhook: {e}", exc_info=True)
        # Return error as TwiML
        from twilio.twiml.messaging_response import MessagingResponse
        error_response = MessagingResponse()
        error_response.message("Sorry, I encountered an error. Please try again.")
        return Response(content=str(error_response), media_type="application/xml")

# Startup guard to prevent duplicate initialization
_startup_initialized = False
_startup_lock = asyncio.Lock()

@app.on_event("startup")
async def startup_event():
    """
    🔒 ENTERPRISE: Non-blocking startup with guard to prevent duplicates.
    FastAPI starts immediately, services initialize in background.
    """
    global _startup_initialized
    
    # Guard: prevent duplicate initialization
    async with _startup_lock:
        if _startup_initialized:
            logger.warning("⚠️ Startup already initialized, skipping")
            return
        _startup_initialized = True
    
    logger.info("🚀 Initializing services (non-blocking)...")
    
    # Start readiness monitor immediately (non-blocking)
    try:
        monitor = get_monitor()
        await monitor.start()
    except Exception as e:
        logger.error(f"❌ Failed to start readiness monitor: {e}", exc_info=True)
        # Continue startup even if monitor fails
    
    # Schedule background initialization (non-blocking)
    asyncio.create_task(_initialize_services_background())

async def _initialize_services_background():
    """Background service initialization - never blocks FastAPI startup"""
    try:
        # Step 1: Initialize MongoDB (with timeout)
        try:
            await asyncio.wait_for(_init_mongodb(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.error("❌ MongoDB initialization timed out after 30s")
        except Exception as e:
            logger.error(f"❌ MongoDB initialization failed: {e}", exc_info=True)
        
        # Step 2: Initialize Redis (with timeout)
        try:
            await asyncio.wait_for(_init_redis(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("⚠️ Redis initialization timed out (non-critical)")
        except Exception as e:
            logger.warning(f"⚠️ Redis initialization failed (non-critical): {e}")
        
        # Step 3: Create indexes (idempotent, non-blocking)
        asyncio.create_task(_create_indexes_async())
        
        # Step 4: Setup watchers (non-blocking)
        asyncio.create_task(_setup_watchers_async())
        
        # Step 5: Pre-warm dashboard (non-blocking, optional)
        asyncio.create_task(_prewarm_dashboard_async())
        
        # Step 6: Pre-warm RAG content (non-blocking)
        asyncio.create_task(_prewarm_rag_async())
        
        logger.info("✅ Background initialization tasks scheduled")
    except Exception as e:
        logger.error(f"❌ Background initialization error: {e}", exc_info=True)

async def _init_mongodb():
    """Initialize MongoDB connection (with retries)"""
    from app.config.database import get_database, is_mongodb_ready
    
    max_retries = 30
    for attempt in range(max_retries):
        try:
            get_database()
            if is_mongodb_ready():
                logger.info("✅ MongoDB ready")
                return
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
            raise
    raise TimeoutError("MongoDB initialization timeout")

async def _init_redis():
    """Initialize Redis connection (non-blocking check)"""
    try:
        from app.config.redis_checker import check_redis_readiness
        if check_redis_readiness():
            logger.info("✅ Redis ready")
        else:
            logger.warning("⚠️ Redis not available (non-critical)")
    except Exception as e:
        logger.warning(f"⚠️ Redis initialization warning: {e}")

async def _create_indexes_async():
    """Create database indexes (idempotent)"""
    try:
        from app.db_init import ensure_indexes
        await ensure_indexes()
        logger.info("✅ Indexes created")
    except Exception as e:
        logger.warning(f"⚠️ Index creation warning: {e}")

async def _setup_watchers_async():
    """Setup MongoDB watchers and WebSocket manager"""
    try:
        # Set event loop for WebSocket manager
        from app.routes.websocket import get_manager
        get_manager().set_event_loop(asyncio.get_event_loop())
        
        # Setup MongoDB change stream watcher
        setup_mongo_watcher()
        logger.info("✅ Watchers initialized")
    except Exception as e:
        logger.warning(f"⚠️ Watcher setup warning: {e}")

async def _prewarm_dashboard_async():
    """Pre-warm dashboard cache (optional, non-critical)"""
    try:
        # Wait a bit for MongoDB to be ready
        await asyncio.sleep(5)
        from app.services.dashboard_aggregator import DashboardAggregator
        aggregator = DashboardAggregator()
        # Run aggregation with timeout protection
        try:
            await asyncio.wait_for(
                aggregator.aggregate_and_cache(days=7),
                timeout=95.0  # Slightly longer than aggregator timeout
            )
            logger.info("✅ Dashboard pre-warmed successfully")
        except asyncio.TimeoutError:
            logger.warning("⚠️ Dashboard pre-warm timed out (will populate on first request)")
        except Exception as e:
            logger.warning(f"⚠️ Dashboard pre-warm error (non-critical): {e}")
    except Exception as e:
        logger.warning(f"⚠️ Dashboard pre-warm failed (non-critical): {e}")

async def _prewarm_rag_async():
    """Pre-warm RAG content cache (non-critical)"""
    try:
        # Wait a bit for basic systems to be ready
        await asyncio.sleep(10)
        from app.services.rag_service import trigger_rag_warmup
        await trigger_rag_warmup()
        logger.info("✅ RAG content pre-warmed successfully")
    except Exception as e:
        logger.warning(f"⚠️ RAG pre-warm failed (non-critical): {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    try:
        monitor = get_monitor()
        await monitor.stop()
    except Exception as e:
        logger.error(f"❌ Error stopping monitor: {e}")

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    🔒 ENTERPRISE: Global error handler - prevents 500 during startup.
    NEVER exposes exception details to clients.
    """
    # Log internal error (with full details)
    logger.error(
        f"❌ Unhandled exception: {type(exc).__name__}: {exc}",
        exc_info=True,
        extra={
            "path": request.url.path,
            "method": request.method,
            "error_type": type(exc).__name__
        }
    )
    
    # During startup/warmup, return 503 instead of 500
    try:
        from app.config.database import is_warming_up
        if is_warming_up():
            return JSONResponse(
                status_code=503,
                content={
                    "status": "warming_up",
                    "message": "Backend is initializing. Please retry in a few seconds."
                    # NO error details exposed
                }
            )
    except Exception:
        # If check fails, assume warming up
        return JSONResponse(
            status_code=503,
            content={
                "status": "warming_up",
                "message": "Backend is initializing. Please retry in a few seconds."
            }
        )
    
    # Normal operation - return 500 (but no details)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Internal server error",
            "detail": str(exc),
            "trace": str(type(exc).__name__)
        }
    )

@app.get("/api/test-lyzr-connection")
async def test_lyzr_connection():
    """Test connection to Lyzr API"""
    from app.services.lyzr_service import LyzrService
    lyzr_service = LyzrService()
    result = await lyzr_service.test_connection()
    return result

@app.get("/api/test-twiml")
async def test_twiml():
    """Test TwiML response generation"""
    from twilio.twiml.messaging_response import MessagingResponse
    
    response = MessagingResponse()
    response.message("Hello!")
    response.message("This is a test message.")
    response.message("This message has a longer text that might need to be split if it exceeds character limits.")
    
    twiml_str = str(response)
    logger.info(f"Generated TwiML:\n{twiml_str}")
    
    return {
        "twiml": twiml_str,
        "message_count": 3,
        "content_type": "application/xml",
        "note": "This is what gets sent back to Twilio"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

