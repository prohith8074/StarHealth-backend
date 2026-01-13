"""
Enterprise Readiness Cache
Thread-safe cached flags for service readiness.
NO I/O operations - only in-memory cache.
"""
import threading
from datetime import datetime, timedelta
from app.config.logging_config import get_logger

logger = get_logger(__name__)

# Thread-safe readiness flags cache
_readiness_cache = {
    "mongodb": False,
    "redis": False,
    "last_updated": None,
    "cache_ttl": 5.0  # 5 seconds TTL
}
_cache_lock = threading.Lock()

def update_readiness_flags(mongodb_ready: bool, redis_ready: bool):
    """Update cached readiness flags (called by background monitor)"""
    global _readiness_cache
    with _cache_lock:
        _readiness_cache["mongodb"] = mongodb_ready
        _readiness_cache["redis"] = redis_ready
        _readiness_cache["last_updated"] = datetime.now()
        logger.debug(f"Readiness flags updated: MongoDB={mongodb_ready}, Redis={redis_ready}")

def get_cached_readiness() -> dict:
    """
    Get cached readiness flags (NO I/O, thread-safe).
    Returns flags even if cache is stale (better than blocking).
    """
    global _readiness_cache
    with _cache_lock:
        # Check if cache is stale
        is_stale = False
        if _readiness_cache["last_updated"]:
            age = (datetime.now() - _readiness_cache["last_updated"]).total_seconds()
            is_stale = age > _readiness_cache["cache_ttl"]
        
        return {
            "mongodb": _readiness_cache["mongodb"],
            "redis": _readiness_cache["redis"],
            "is_stale": is_stale,
            "last_updated": _readiness_cache["last_updated"].isoformat() if _readiness_cache["last_updated"] else None
        }

def reset_cache():
    """Reset cache (for testing or error recovery)"""
    global _readiness_cache
    with _cache_lock:
        _readiness_cache["mongodb"] = False
        _readiness_cache["redis"] = False
        _readiness_cache["last_updated"] = None

