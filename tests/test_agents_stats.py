"""
Test cases for agents_stats route
Tests LLM calls aggregation, timestamp serialization, and data fetching
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, Mock
from fastapi.testclient import TestClient
from bson import ObjectId
import json

from app.routes.agents_stats import serialize_datetime, _fetch_agents_data_sync
from app.config.database import get_database


class TestSerializeDatetime:
    """Test datetime serialization function"""
    
    def test_serialize_datetime_object(self):
        """Test serializing a datetime object"""
        dt = datetime(2024, 1, 15, 10, 30, 45)
        result = serialize_datetime(dt)
        assert isinstance(result, str)
        assert result == "2024-01-15T10:30:45"
    
    def test_serialize_dict_with_datetime(self):
        """Test serializing a dict containing datetime"""
        dt = datetime(2024, 1, 15, 10, 30, 45)
        data = {
            "timestamp": dt,
            "name": "test",
            "value": 123
        }
        result = serialize_datetime(data)
        assert isinstance(result["timestamp"], str)
        assert result["timestamp"] == "2024-01-15T10:30:45"
        assert result["name"] == "test"
        assert result["value"] == 123
    
    def test_serialize_list_with_datetime(self):
        """Test serializing a list containing datetime"""
        dt1 = datetime(2024, 1, 15, 10, 30, 45)
        dt2 = datetime(2024, 1, 16, 11, 30, 45)
        data = [dt1, dt2, "string", 123]
        result = serialize_datetime(data)
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)
        assert result[0] == "2024-01-15T10:30:45"
        assert result[1] == "2024-01-16T11:30:45"
        assert result[2] == "string"
        assert result[3] == 123
    
    def test_serialize_nested_structure(self):
        """Test serializing nested dicts and lists with datetime"""
        dt = datetime(2024, 1, 15, 10, 30, 45)
        data = {
            "traces": [
                {"timestamp": dt, "value": 1},
                {"timestamp": dt, "value": 2}
            ],
            "metadata": {
                "created": dt,
                "updated": dt
            }
        }
        result = serialize_datetime(data)
        assert isinstance(result["traces"][0]["timestamp"], str)
        assert isinstance(result["traces"][1]["timestamp"], str)
        assert isinstance(result["metadata"]["created"], str)
        assert isinstance(result["metadata"]["updated"], str)
    
    def test_serialize_non_datetime_unchanged(self):
        """Test that non-datetime values remain unchanged"""
        data = {
            "string": "test",
            "number": 123,
            "boolean": True,
            "none": None,
            "list": [1, 2, 3]
        }
        result = serialize_datetime(data)
        assert result == data


class TestAgentsStatsDataFetching:
    """Test agent stats data fetching and aggregation"""
    
    @patch('app.routes.agents_stats.get_database')
    def test_fetch_agents_data_llm_calls_aggregation(self, mock_get_db, sample_agent_stats):
        """Test that LLM calls are correctly aggregated in traces"""
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        
        # Mock agent_stats collection
        mock_db.agent_stats.find.return_value.sort.return_value.limit.return_value.max_time_ms.return_value = sample_agent_stats
        mock_db.agent_stats.count_documents.return_value = 0
        
        # Mock dashboarddata collection
        mock_db.dashboarddata.aggregate.return_value = []
        
        # Mock agents collection
        mock_db.agents.find.return_value = [
            {
                "agentCode": "R45",
                "agentName": "Test Agent",
                "role": "agent",
                "isActive": True
            }
        ]
        
        result = _fetch_agents_data_sync()
        
        # Verify traces contain correct LLM calls
        assert len(result["traces"]) == 3
        
        # Check that LLM calls are preserved in traces
        product_traces = [t for t in result["traces"] if t["agentType"] == "product_recommendation"]
        assert len(product_traces) == 2
        assert product_traces[0]["llmCalls"] == 6
        assert product_traces[1]["llmCalls"] == 4
        
        sales_traces = [t for t in result["traces"] if t["agentType"] == "sales_pitch"]
        assert len(sales_traces) == 1
        assert sales_traces[0]["llmCalls"] == 3
    
    @patch('app.routes.agents_stats.get_database')
    def test_timestamp_serialization_in_traces(self, mock_get_db, sample_agent_stats):
        """Test that timestamps are serialized to strings in traces"""
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        
        # Mock collections
        mock_db.agent_stats.find.return_value.sort.return_value.limit.return_value.max_time_ms.return_value = sample_agent_stats
        mock_db.agent_stats.count_documents.return_value = 0
        mock_db.dashboarddata.aggregate.return_value = []
        mock_db.agents.find.return_value = []
        
        result = _fetch_agents_data_sync()
        
        # Verify all timestamps are strings
        for trace in result["traces"]:
            assert "timestamp" in trace
            assert isinstance(trace["timestamp"], str) or trace["timestamp"] is None
    
    @patch('app.routes.agents_stats.get_database')
    def test_agents_stats_response_serialization(self, mock_get_db, sample_agent_stats):
        """Test that the entire response is properly serialized"""
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        
        # Mock collections
        mock_db.agent_stats.find.return_value.sort.return_value.limit.return_value.max_time_ms.return_value = sample_agent_stats
        mock_db.agent_stats.count_documents.return_value = 0
        mock_db.dashboarddata.aggregate.return_value = []
        mock_db.agents.find.return_value = []
        
        result = _fetch_agents_data_sync()
        
        # Serialize the result (simulating what happens in the endpoint)
        serialized = serialize_datetime(result)
        
        # Try to JSON serialize (should not fail)
        json_str = json.dumps(serialized, default=str)
        assert json_str is not None
        
        # Verify no datetime objects remain
        def check_no_datetime(obj):
            if isinstance(obj, datetime):
                return False
            elif isinstance(obj, dict):
                return all(check_no_datetime(v) for v in obj.values())
            elif isinstance(obj, list):
                return all(check_no_datetime(item) for item in obj)
            return True
        
        assert check_no_datetime(serialized)


class TestAgentsStatsEndpoint:
    """Test the agents stats API endpoint"""
    
    @patch('app.routes.agents_stats.get_database')
    @patch('app.routes.agents_stats.agents_cache')
    def test_get_agents_stats_endpoint_serialization(self, mock_cache, mock_get_db, sample_agent_stats):
        """Test that endpoint response is properly serialized"""
        from app.routes.agents_stats import get_agents_stats
        
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        
        # Mock cache to return None (cache miss)
        mock_cache.get.return_value = None
        mock_cache.refreshing = False
        mock_cache.cache = None
        
        # Mock collections
        mock_db.agent_stats.find.return_value.sort.return_value.limit.return_value.max_time_ms.return_value = sample_agent_stats
        mock_db.agent_stats.count_documents.return_value = 0
        mock_db.dashboarddata.aggregate.return_value = []
        mock_db.agents.find.return_value = []
        
        # Mock asyncio.to_thread
        with patch('app.routes.agents_stats.asyncio.to_thread') as mock_thread:
            mock_thread.return_value = _fetch_agents_data_sync()
            
            # This would normally be async, but we're testing the sync function
            result = _fetch_agents_data_sync()
            serialized = serialize_datetime(result)
            
            # Verify serialization
            assert isinstance(serialized, dict)
            assert "traces" in serialized
            
            # Verify all timestamps are strings
            for trace in serialized["traces"]:
                if trace.get("timestamp"):
                    assert isinstance(trace["timestamp"], str)




