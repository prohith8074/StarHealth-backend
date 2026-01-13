import redis
import os
from dotenv import load_dotenv
from app.config.logging_config import get_logger
import threading

load_dotenv()

logger = get_logger(__name__)

# 🔒 SINGLETON: Global Redis instance to prevent connection exhaustion
_redis_instance = None
_redis_lock = threading.Lock()


def get_redis_service():
    """
    Get the singleton Redis service instance.
    Thread-safe and prevents multiple connections.
    """
    global _redis_instance
    
    if _redis_instance is None:
        with _redis_lock:
            # Double-check locking pattern
            if _redis_instance is None:
                _redis_instance = RedisService()
    
    return _redis_instance


class RedisService:
    """
    Service for managing Redis connection with connection pooling.
    
    🔒 CRITICAL: Use get_redis_service() to get the singleton instance.
    Do NOT create new RedisService() instances directly in other modules.
    
    NOTE: Redis is used EXCLUSIVELY for Dashboard Snapshots (Permanent Data).
    All session state, chat logs, and other data are stored in MongoDB.
    """
    
    # Class-level connection pool (shared across all instances)
    _connection_pool = None
    _pool_lock = threading.Lock()
    
    def __init__(self):
        # Support Redis Cloud connection URL or individual settings
        redis_url = os.getenv("REDIS_URL")
        
        # Use shared connection pool if available
        if RedisService._connection_pool is not None:
            logger.debug("♻️ Reusing existing Redis connection pool")
            self.redis_client = redis.Redis(connection_pool=RedisService._connection_pool)
            return
        
        with RedisService._pool_lock:
            # Double-check if pool was created while waiting for lock
            if RedisService._connection_pool is not None:
                self.redis_client = redis.Redis(connection_pool=RedisService._connection_pool)
                return
            
            if redis_url:
                # Use Redis Cloud connection URL (e.g., redis://default:password@host:port)
                logger.info(f"🔌 Creating Redis connection pool (Cloud URL)")
                try:
                    # Log masked URL for debugging
                    masked_url = redis_url.split('@')[0] + "@***" if '@' in redis_url else "rediss://***"
                    logger.debug(f"   URL: {masked_url}")
                except:
                    pass
                
                # 🔒 CONNECTION POOLING: Max 10 connections, prevents exhaustion
                RedisService._connection_pool = redis.ConnectionPool.from_url(
                    redis_url,
                    decode_responses=True,
                    max_connections=10,  # 🔒 LIMIT: Prevents 90% connection issue
                    socket_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=30
                )
            else:
                # Fallback to individual settings (for local Redis)
                redis_host = os.getenv("REDIS_HOST", "localhost")
                redis_port = int(os.getenv("REDIS_PORT", 6379))
                redis_password = os.getenv("REDIS_PASSWORD") or None
                redis_username = os.getenv("REDIS_USERNAME") or None
                
                logger.info(f"🔌 Creating Redis connection pool: {redis_host}:{redis_port}")
                
                # 🔒 CONNECTION POOLING: Max 10 connections
                RedisService._connection_pool = redis.ConnectionPool(
                    host=redis_host,
                    port=redis_port,
                    password=redis_password,
                    username=redis_username,
                    decode_responses=True,
                    max_connections=10,  # 🔒 LIMIT: Prevents 90% connection issue
                    socket_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=30
                )
            
            # Create client from pool
            self.redis_client = redis.Redis(connection_pool=RedisService._connection_pool)
            
            # Test connection
            try:
                self.redis_client.ping()
                logger.info(f"✅ Redis connection pool created successfully (max 10 connections)")
            except Exception as e:
                logger.error(f"❌ Redis connection failed: {e}")
                RedisService._connection_pool = None  # Reset on failure
                raise
    
    def get_connection_info(self):
        """Get current connection pool stats for monitoring"""
        if RedisService._connection_pool:
            return {
                "max_connections": RedisService._connection_pool.max_connections,
                "current_connections": len(RedisService._connection_pool._in_use_connections) if hasattr(RedisService._connection_pool, '_in_use_connections') else "N/A"
            }
        return None
