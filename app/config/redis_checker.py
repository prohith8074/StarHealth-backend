"""
Redis Readiness Checker
Independent Redis connection checker to avoid circular imports.
Used by readiness monitor.
"""
import redis
import os
from dotenv import load_dotenv
from app.config.logging_config import get_logger

load_dotenv()
logger = get_logger(__name__)

def check_redis_readiness() -> bool:
    """
    Check Redis readiness (with timeout).
    Returns False on any error (never throws).
    """
    try:
        redis_host = os.getenv("REDIS_HOST", "redis-19695.c240.us-east-1-3.ec2.cloud.redislabs.com")
        redis_port = int(os.getenv("REDIS_PORT", 19695))
        redis_username = os.getenv("REDIS_USERNAME", "default")
        redis_password = os.getenv("REDIS_PASSWORD", "3LlxKUIEDmzASiW7gXU7WwBSdWWN9YgR")
        
        # Create temporary client for ping
        test_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            username=redis_username,
            password=redis_password,
            decode_responses=True,
            socket_connect_timeout=2,  # 2 second timeout
            socket_timeout=2
        )
        
        # Ping with timeout
        test_client.ping()
        test_client.close()
        return True
        
    except Exception as e:
        logger.debug(f"Redis readiness check failed: {e}")
        return False

