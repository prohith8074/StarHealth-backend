"""
Pytest configuration and fixtures for FastAPI tests
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from bson import ObjectId
import os

# Set test environment variables before importing app
os.environ["TESTING"] = "true"
os.environ["MONGODB_URI"] = os.getenv("MONGODB_URI", "mongodb://localhost:27017/test_db")
os.environ["REDIS_HOST"] = "localhost"
os.environ["REDIS_PORT"] = "6379"
os.environ["JWT_SECRET"] = "test-secret-key-for-unit-tests"

from app.main import app
from app.config.database import get_database


@pytest.fixture
def client():
    """Create a test client"""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Mock database for testing"""
    mock_db = MagicMock()
    return mock_db


@pytest.fixture
def sample_agent_stats():
    """Sample agent stats data for testing"""
    now = datetime.utcnow()
    return [
        {
            "_id": ObjectId(),
            "sessionId": "test_session_1",
            "agentCode": "R45",
            "agentName": "Test Agent",
            "agentType": "product_recommendation",
            "llmCalls": 6,
            "totalTokens": 1902,
            "messageCount": 3,
            "timestamp": now,
            "createdAt": now,
            "updatedAt": now,
            "hasError": False,
            "username": "TestUser"
        },
        {
            "_id": ObjectId(),
            "sessionId": "test_session_2",
            "agentCode": "R45",
            "agentName": "Test Agent",
            "agentType": "product_recommendation",
            "llmCalls": 4,
            "totalTokens": 1200,
            "messageCount": 2,
            "timestamp": now - timedelta(hours=1),
            "createdAt": now - timedelta(hours=1),
            "updatedAt": now - timedelta(hours=1),
            "hasError": False,
            "username": "TestUser"
        },
        {
            "_id": ObjectId(),
            "sessionId": "test_session_3",
            "agentCode": "S12",
            "agentName": "Sales Agent",
            "agentType": "sales_pitch",
            "llmCalls": 3,
            "totalTokens": 800,
            "messageCount": 2,
            "timestamp": now - timedelta(hours=2),
            "createdAt": now - timedelta(hours=2),
            "updatedAt": now - timedelta(hours=2),
            "hasError": False,
            "username": "TestUser2"
        }
    ]


@pytest.fixture
def sample_feedback():
    """Sample feedback data for testing"""
    return {
        "username": "TestUser",
        "agentCode": "R45",
        "agentType": "product_recommendation",
        "feedback": "Great recommendation!",
        "sessionId": "test_session_1",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow()
    }


@pytest.fixture
def sample_dashboard_data():
    """Sample dashboard data for testing"""
    now = datetime.utcnow()
    return {
        "uniqueUsers": 10,
        "totalInteractions": 50,
        "feedbackCount": 15,
        "recommendations": 30,
        "salesPitches": 20,
        "repeatedUsers": 5,
        "completedConversations": 12,
        "incompleteConversations": 3,
        "totalConversations": 15,
        "trends": {
            "uniqueUsers": {"percentage": 10.0, "display": "↑ +10.0%"},
            "feedback": {"percentage": 5.0, "display": "↑ +5.0%"}
        },
        "feedbackData": [],
        "recentActivity": [],
        "feedbackByType": {
            "product_recommendation": 10,
            "sales_pitch": 5
        },
        "activityDistribution": {
            "labels": ["Jan 01", "Jan 02"],
            "data": {
                "recommendations": [15, 15],
                "salesPitches": [10, 10],
                "feedback": [5, 5]
            }
        },
        "completedConversationsData": {
            "labels": ["Jan 01", "Jan 02"],
            "data": {
                "productRecommendation": [6, 6],
                "salesPitch": [3, 3]
            }
        },
        "_version": now.isoformat()
    }


@pytest.fixture
def mock_redis():
    """Mock Redis client"""
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.get.return_value = None
    mock_redis.set.return_value = True
    mock_redis.delete.return_value = 1
    return mock_redis


@pytest.fixture
def mock_websocket_manager():
    """Mock WebSocket manager"""
    mock_ws = MagicMock()
    mock_ws.broadcast_sync = MagicMock()
    return mock_ws




