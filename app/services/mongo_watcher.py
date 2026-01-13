"""
MongoDB Polling Watcher - Updates dashboard via WebSocket
"""
from app.config.database import get_database
from app.config.logging_config import get_logger
from app.routes.websocket import get_manager
from datetime import datetime, timedelta
import threading
import time

logger = get_logger(__name__)

class MongoWatcher:
    def __init__(self):
        self.db = None
        self.polling_active = False
        self.polling_thread = None
    
    def emit_dashboard_update(self):


        """Broadcast dashboard refresh trigger to WebSocket clients - triggers full refresh on frontend"""
        try:
            ws_manager = get_manager()
        # Trigger full dashboard refresh (frontend will fetch complete data)
            ws_manager.broadcast_sync({
                "type": "dashboard:refresh",
                "message": "Dashboard data updated"
            })
            # Also trigger agents refresh
            ws_manager.broadcast_sync({
                "type": "agents:refresh",
                "message": "Agents data updated"
            })
        except Exception as e:
            logger.debug(f"WebSocket broadcast error (non-critical): {e}")
    
    def setup_polling(self):
        """Setup polling for dashboard updates"""
        if self.polling_active:
            return
        
        self.polling_active = True
        
        def poll_loop():
            while self.polling_active:
                try:
                    self.emit_dashboard_update()
                except:
                    pass  # Silently fail
                time.sleep(3)  # Poll every 3 seconds for faster updates
        
        self.polling_thread = threading.Thread(target=poll_loop, daemon=True)
        self.polling_thread.start()
        
        # Initial update
        self.emit_dashboard_update()
    
    def setup(self):
        """Setup MongoDB watchers"""
        try:
            db = get_database()
            self.db = db
            self.setup_polling()
        except:
            self.setup_polling()

# Global watcher instance
watcher = MongoWatcher()

def setup_mongo_watcher():
    """Setup MongoDB watcher"""
    watcher.setup()




