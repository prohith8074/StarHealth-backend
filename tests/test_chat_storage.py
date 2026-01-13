"""
Test cases for chat storage (agent_stats collection)
Tests that agent stats are correctly stored with Lyzr session ID
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from bson import ObjectId

from app.services.chat_storage import ChatStorage


class TestAgentStatsStorage:
    """Test agent stats storage functionality"""
    
    @patch('app.services.chat_storage.MongoClient')
    def test_save_message_stores_lyzr_session_id(self, mock_mongo_client):
        """Test that saving agent message stores Lyzr session ID"""
        # Mock MongoClient and database structure
        mock_client = MagicMock()
        mock_mongo_client.return_value = mock_client
        mock_client.admin.command.return_value = True  # ping success
        
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        
        # Mock agent_stats collection
        mock_agent_stats = MagicMock()
        mock_db.agent_stats = mock_agent_stats
        mock_agent_stats.find_one.return_value = None  # New record
        mock_agent_stats.insert_one.return_value.inserted_id = ObjectId()
        
        storage = ChatStorage()
        
        # Save agent message with Lyzr session ID
        import asyncio
        result = asyncio.run(storage.save_message(
            session_id="test_session_1",
            role="agent",
            message="Test response",
            username="TestUser",
            agent_code="R45",
            agent_name="Test Agent",
            agent_type="product_recommendation",
            total_tokens=100,
            llm_calls=1,
            lyzr_session_id="lyzr_session_123"
        ))
        
        # Verify update_one was called (upsert=True)
        assert mock_agent_stats.update_one.called
        
        # Get the arguments passed to update_one
        call_args = mock_agent_stats.update_one.call_args
        update_doc = call_args[0][1] # The update document is the second arg
        filter_doc = call_args[0][0] # The filter is the first arg
        
        # Verify Lyzr session ID is stored in $set
        assert update_doc["$set"].get("lyzrSessionId") == "lyzr_session_123"
        assert update_doc["$set"].get("agentCode") == "R45"
        
        # Verify increment counters
        assert update_doc["$inc"].get("llmCalls") == 1
        assert update_doc["$inc"].get("totalTokens") == 100
        
        # Verify filter uses valid identifiers
        assert filter_doc.get("sessionId") == "test_session_1"
    
    @patch('app.services.chat_storage.MongoClient')
    def test_save_message_updates_existing_stats(self, mock_mongo_client):
        """Test that saving message updates existing stats and preserves Lyzr session ID"""
        # Mock MongoClient and database structure
        mock_client = MagicMock()
        mock_mongo_client.return_value = mock_client
        mock_client.admin.command.return_value = True  # ping success
        
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        
        # Mock existing stats record
        existing_stat = {
            "_id": ObjectId(),
            "sessionId": "test_session_1",
            "agentCode": "R45",
            "agentType": "product_recommendation",
            "llmCalls": 3,
            "totalTokens": 500,
            "lyzrSessionId": "lyzr_session_123"
        }
        
        mock_agent_stats = MagicMock()
        mock_db.agent_stats = mock_agent_stats
        mock_agent_stats.find_one.return_value = existing_stat
        mock_agent_stats.update_one.return_value.modified_count = 1
        
        storage = ChatStorage()
        
        # Save another message (should update existing)
        import asyncio
        result = asyncio.run(storage.save_message(
            session_id="test_session_1",
            role="agent",
            message="Another response",
            username="TestUser",
            agent_code="R45",
            agent_name="Test Agent",
            agent_type="product_recommendation",
            total_tokens=200,
            llm_calls=2,
            lyzr_session_id="lyzr_session_123"
        ))
        
        # Verify update_one was called
        assert mock_agent_stats.update_one.called
        
        # Get the update document
        # update_one is called as: update_one(filter_dict, update_doc)
        # call_args is ((filter_dict, update_doc), {})
        call_args = mock_agent_stats.update_one.call_args
        update_doc = call_args[0][1]  # Second positional argument is the update document
        
        # Verify $inc is used for llmCalls and totalTokens
        assert "$inc" in update_doc
        assert "llmCalls" in update_doc["$inc"]
        assert "totalTokens" in update_doc["$inc"]
        
        # Verify $set includes lyzrSessionId
        assert "$set" in update_doc
        assert "lyzrSessionId" in update_doc["$set"]
        assert update_doc["$set"]["lyzrSessionId"] == "lyzr_session_123"
    
    @patch('app.services.chat_storage.MongoClient')
    def test_save_message_skips_user_messages(self, mock_mongo_client):
        """Test that user messages are not saved to agent_stats"""
        # Mock MongoClient and database structure
        mock_client = MagicMock()
        mock_mongo_client.return_value = mock_client
        mock_client.admin.command.return_value = True  # ping success
        
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        
        mock_agent_stats = MagicMock()
        mock_db.agent_stats = mock_agent_stats
        
        storage = ChatStorage()
        
        # Save user message (should be skipped)
        import asyncio
        result = asyncio.run(storage.save_message(
            session_id="test_session_1",
            role="user",
            message="User question",
            username="TestUser"
        ))
        
        # Verify no database operations were performed
        assert not mock_agent_stats.find_one.called
        assert not mock_agent_stats.insert_one.called
        assert not mock_agent_stats.update_one.called

