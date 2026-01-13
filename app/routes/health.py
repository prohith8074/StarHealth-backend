"""
Enterprise Health Endpoints
- /health/live: Liveness probe (NO I/O, always 200)
- /health/ready: Readiness probe (reads cached flags only, NO I/O)
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from datetime import datetime
from app.config.logging_config import get_logger
from app.config.readiness_cache import get_cached_readiness

logger = get_logger(__name__)
router = APIRouter()

@router.get("/health/live")
async def liveness_probe():
    """
    🔒 ENTERPRISE: Liveness probe - NEVER performs I/O, ALWAYS returns 200.
    Used by BootGuard to verify backend process is running.
    """
    return {
        "status": "alive",
        "service": "fastapi-backend",
        "timestamp": datetime.now().isoformat()
    }

@router.get("/health/ready")
async def readiness_probe():
    """
    🔒 ENTERPRISE: Readiness probe - reads cached flags ONLY, NO I/O.
    NEVER throws exceptions, NEVER returns 500.
    """
    try:
        # Read from cache (NO I/O, thread-safe)
        readiness = get_cached_readiness()
        
        all_ready = readiness["mongodb"] and readiness["redis"]
        
        response = {
            "status": "ready" if all_ready else "warming_up",
            "service": "fastapi-backend",
            "timestamp": datetime.now().isoformat(),
            "checks": {
                "mongodb": readiness["mongodb"],
                "redis": readiness["redis"]
            }
        }
        
        if all_ready:
            return response
        else:
            return JSONResponse(
                status_code=503,
                content={
                    **response,
                    "message": "Backend is initializing. Please retry in a few seconds."
                }
            )
    except Exception as e:
        # Catch-all: NEVER return 500, always return 503 (warming up)
        logger.error(f"❌ Error in readiness probe: {e}", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={
                "status": "warming_up",
                "service": "fastapi-backend",
                "timestamp": datetime.now().isoformat(),
                "message": "Backend is initializing. Please retry in a few seconds.",
                "checks": {
                    "mongodb": False,
                    "redis": False
                }
            }
        )

