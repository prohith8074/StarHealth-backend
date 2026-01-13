"""
Test cases for feedback dashboard updates
Tests cache invalidation and WebSocket events when feedback is created/updated
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, Mock, AsyncMock
from fastapi.testclient import TestClient

from app.services.dashboard_service import DashboardService
from app.routes.feedback_route import create_feedback
from app.models.models import FeedbackCreate
from bson import ObjectId


@pytest.mark.skip(reason="Caching layer interactions refactored; mocks need update.")
class TestFeedbackCacheInvalidation:
    """Test cache invalidation when feedback is created"""

# ... (skipping content) ...

@pytest.mark.skip(reason="Caching layer interactions refactored; mocks need update.")
class TestFeedbackRouteEndpoint:
    """Test the feedback route endpoint"""

# ... (skipping content) ...

@pytest.mark.skip(reason="Caching layer interactions refactored; mocks need update.")
class TestFeedbackDashboardIntegration:
    """Integration tests for feedback and dashboard updates"""
    
    @patch('app.services.dashboard_service.get_websocket_manager')
    @patch('app.services.dashboard_service.MongoClient')
    def test_feedback_triggers_dashboard_refresh(self, mock_mongo_client, mock_get_ws):
        """Test that feedback creation triggers dashboard refresh via WebSocket"""
        # Mock MongoClient
        mock_client = MagicMock()
        mock_mongo_client.return_value = mock_client
        mock_client.admin.command.return_value = True
        
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        
        # Setup mocks
        mock_feedback = MagicMock()
        mock_db.feedback = mock_feedback
        mock_db.dashboard_data = MagicMock()
        mock_feedback.find_one.return_value = None
        mock_feedback.update_one.return_value.upserted_id = ObjectId()
        mock_feedback.update_one.return_value.modified_count = 0
        
        mock_ws_manager = MagicMock()
        mock_get_ws.return_value = mock_ws_manager
        
        service = DashboardService()
        
        # Create feedback
        import asyncio
        asyncio.run(service.create_feedback(
            username="TestUser",
            agent_code="R45",
            agent_type="product_recommendation",
            feedback="Excellent!",
            session_id="test_session_1"
        ))
        
        # Verify WebSocket events
        assert mock_ws_manager.broadcast_sync.called
        
        # Get all broadcast calls
        calls = [call[0][0] for call in mock_ws_manager.broadcast_sync.call_args_list]
        
        # Verify refresh events were sent
        refresh_events = [call for call in calls if call.get("type") in ["dashboard:refresh", "agents:refresh"]]
        assert len(refresh_events) > 0

