"""
Readiness Monitor Service
Background task that periodically checks service readiness and updates cache.
Runs independently, never blocks startup.
"""
import asyncio
from app.config.readiness_cache import update_readiness_flags
from app.config.logging_config import get_logger

logger = get_logger(__name__)

class ReadinessMonitor:
    """Monitors service readiness and updates cache"""
    
    def __init__(self):
        self.monitoring = False
        self._task = None
    
    async def start(self):
        """Start monitoring (non-blocking)"""
        if self.monitoring:
            logger.warning("⚠️ Readiness monitor already started")
            return
        
        self.monitoring = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("🔍 Readiness monitor started")
    
    async def stop(self):
        """Stop monitoring"""
        self.monitoring = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 Readiness monitor stopped")
    
    async def _monitor_loop(self):
        """Background loop that checks readiness every 2 seconds"""
        while self.monitoring:
            try:
                # Check MongoDB (with timeout protection)
                mongodb_ready = False
                try:
                    from app.config.database import is_mongodb_ready
                    mongodb_ready = is_mongodb_ready()
                except Exception as e:
                    logger.debug(f"MongoDB check failed: {e}")
                
                # Check Redis (with timeout protection, no circular imports)
                redis_ready = False
                try:
                    from app.config.redis_checker import check_redis_readiness
                    redis_ready = check_redis_readiness()
                except Exception as e:
                    logger.debug(f"Redis check failed: {e}")
                
                # Update cache (thread-safe)
                update_readiness_flags(mongodb_ready, redis_ready)
                
                # Wait 2 seconds before next check
                await asyncio.sleep(2.0)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error in readiness monitor: {e}", exc_info=True)
                # Continue monitoring even on error
                await asyncio.sleep(2.0)

# Global monitor instance
_monitor = ReadinessMonitor()

def get_monitor():
    return _monitor

