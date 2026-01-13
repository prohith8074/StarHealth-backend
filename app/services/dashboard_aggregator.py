"""
Dashboard Aggregator Service
Background service that aggregates dashboard data from MongoDB and caches it in Redis.
This ensures /dashboard endpoint never blocks on MongoDB queries.
"""
import asyncio
from app.config.database import is_mongodb_ready
from app.config.logging_config import get_logger
from app.routes.dashboard import _fetch_dashboard_data_from_db, cache, _calculate_data_hash
from datetime import datetime

logger = get_logger(__name__)

class DashboardAggregator:
    """Service for aggregating dashboard data in the background"""
    
    def __init__(self):
        self.aggregating = False
    
    async def aggregate_and_cache(self, days: int = 7):
        """
        Aggregate dashboard data from MongoDB and cache it in Redis.
        This method is designed to run in the background and never blocks the main thread.
        
        Args:
            days: Number of days to aggregate (default: 7)
        """
        if self.aggregating:
            logger.debug(f"⏭️  Aggregation already in progress, skipping")
            return
        
        self.aggregating = True
        
        try:
            # 🔒 PRODUCTION FIX: Check MongoDB readiness before querying
            if not is_mongodb_ready():
                logger.warning(f"⚠️ MongoDB not ready, skipping aggregation for dashboard_{days}")
                return
            
            logger.info(f"🔄 Starting background dashboard aggregation (days={days})...")
            
            # Run blocking MongoDB query with hard timeout
            # 🔒 ENTERPRISE: 30 second timeout (optimized queries should complete faster)
            try:
                response_data = await asyncio.wait_for(
                    asyncio.to_thread(_fetch_dashboard_data_from_db, days),
                    timeout=30.0  # 30 second timeout (reduced from 90s)
                )
            except asyncio.TimeoutError:
                logger.error(f"❌ Dashboard aggregation timed out after 30s for dashboard_{days}")
                logger.warning(f"⚠️ Will retry aggregation on next cache miss")
                return
            except Exception as fetch_error:
                logger.error(f"❌ Error fetching dashboard data: {fetch_error}", exc_info=True)
                return
            
            # Check if data changed before updating cache
            cached_data = cache.get(days)
            if cached_data is not None:
                new_hash = _calculate_data_hash(response_data)
                old_hash = _calculate_data_hash(cached_data)
                
                if new_hash == old_hash:
                    logger.info(f"⏭️  No data changes detected for dashboard_{days}, skipping Redis update")
                    return
            
            # Cache the aggregated data with hourly version granularity
            version = datetime.now().strftime("%Y-%m-%dT%H")
            try:
                cache.set(days, response_data, version=version)
                logger.info(f"✅ Dashboard aggregation completed and cached (version: {version})")
                logger.info(f"📊 Cached data summary: {response_data.get('uniqueUsers', 0)} users, {response_data.get('totalInteractions', 0)} interactions")
            except Exception as cache_error:
                logger.error(f"❌ Failed to cache dashboard data: {cache_error}", exc_info=True)
                # Don't raise - aggregation succeeded, caching failed (non-critical)
            
        except Exception as error:
            logger.error(f"❌ Error in dashboard aggregation: {error}", exc_info=True)
        finally:
            self.aggregating = False
