"""
WebSocket routes for real-time updates
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.config.logging_config import get_logger
from typing import List, Optional
import asyncio
import queue
import threading
import json
from datetime import datetime

router = APIRouter()
logger = get_logger(__name__)

def serialize_message(message: dict):
    """Recursively convert datetime objects in message dict"""
    if isinstance(message, dict):
        return {k: serialize_message(v) for k, v in message.items()}
    elif isinstance(message, list):
        return [serialize_message(item) for item in message]
    elif isinstance(message, datetime):
        return message.isoformat()
    return message

# Store active connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.message_queue = queue.Queue()
        self.event_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """Set the event loop for broadcasting"""
        self.event_loop = loop

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        
        # Set event loop if not set
        if self.event_loop is None:
            self.event_loop = asyncio.get_event_loop()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        # Serialize message to handle datetime objects
        serialized_message = serialize_message(message)
        
        logger.info(f"📢 Broadcasting WS message: {serialized_message.get('type')} to {len(self.active_connections)} clients")
        
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(serialized_message)
            except Exception as e:
                logger.error(f"❌ Error sending message to WebSocket client: {e}")
                disconnected.append(connection)
        
        # Remove disconnected connections
        for conn in disconnected:
            self.disconnect(conn)
    
    def broadcast_sync(self, message: dict):
        """Broadcast message from a synchronous context (thread-safe)"""
        logger.info(f"🔄 Sync Broadcast: {message.get('type')} - Loop running: {self.event_loop and self.event_loop.is_running()}")
        if self.event_loop and self.event_loop.is_running():
            # Schedule broadcast on the event loop
            asyncio.run_coroutine_threadsafe(
                self.broadcast(message),
                self.event_loop
            )
        else:
            # Queue the message if loop not available
            logger.warning(f"⚠️ Event loop not running or not set, queuing message: {message.get('type')}")
            self.message_queue.put(message)

# Global connection manager
manager = ConnectionManager()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time dashboard updates"""
    await manager.connect(websocket)
    
    # Set event loop reference
    if manager.event_loop is None:
        manager.set_event_loop(asyncio.get_event_loop())
    
    try:
        # Process queued messages
        while not manager.message_queue.empty():
            try:
                msg = manager.message_queue.get_nowait()
                await websocket.send_json(msg)
            except queue.Empty:
                break
        
        # Keep connection alive and handle client messages
        while True:
            try:
                # Wait for either a message from client or timeout
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                logger.debug(f"📨 Received WebSocket message: {data}")
                # Echo back or handle message
                await websocket.send_json({"type": "pong", "data": data})
            except asyncio.TimeoutError:
                # Check for queued messages
                try:
                    msg = manager.message_queue.get_nowait()
                    await websocket.send_json(msg)
                except queue.Empty:
                    continue
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        manager.disconnect(websocket)

def get_manager():
    """Get the connection manager instance"""
    return manager




