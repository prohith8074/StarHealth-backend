# Test Suite Documentation

## Overview
Comprehensive test suite for the FastAPI WhatsApp Bot application, covering critical functionality including:
- Agent stats aggregation and LLM calls calculation
- Timestamp serialization
- Feedback dashboard updates
- Cache invalidation
- WebSocket event broadcasting

## Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Pytest fixtures and configuration
├── test_agents_stats.py     # Agent stats tests
├── test_feedback_dashboard_update.py  # Feedback and dashboard update tests
├── test_dashboard_data.py   # Dashboard data aggregation tests
└── test_chat_storage.py     # Chat storage (agent_stats) tests
```

## Running Tests

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run All Tests
```bash
pytest tests/ -v
```

### Run Specific Test File
```bash
pytest tests/test_agents_stats.py -v
```

### Run with Coverage
```bash
pytest tests/ --cov=app --cov-report=html
```

## Test Coverage

### 1. Agent Stats Tests (`test_agents_stats.py`)
- **TestSerializeDatetime**: Tests datetime serialization function
  - Serializes datetime objects to ISO strings
  - Handles nested dicts and lists
  - Preserves non-datetime values
  
- **TestAgentsStatsDataFetching**: Tests data fetching and aggregation
  - LLM calls are correctly aggregated in traces
  - Timestamps are serialized to strings
  - Response is properly serialized for JSON

- **TestAgentsStatsEndpoint**: Tests API endpoint
  - Response serialization
  - Cache behavior

### 2. Feedback Dashboard Update Tests (`test_feedback_dashboard_update.py`)
- **TestFeedbackCacheInvalidation**: Tests cache invalidation
  - Dashboard cache is invalidated when feedback is created
  - Agents cache is cleared
  - WebSocket events are sent

- **TestFeedbackRouteEndpoint**: Tests feedback route
  - Both caches are invalidated
  - WebSocket events are broadcast

- **TestFeedbackDashboardIntegration**: Integration tests
  - Feedback creation triggers dashboard refresh

### 3. Dashboard Data Tests (`test_dashboard_data.py`)
- **TestDashboardDataAggregation**: Tests data aggregation
  - Total conversations calculation (completed + incomplete)
  - Agent stats integration
  - Recent activity from agent_stats

- **TestDashboardCacheBehavior**: Tests cache behavior
  - Response serialization
  - Version tracking

### 4. Chat Storage Tests (`test_chat_storage.py`)
- **TestAgentStatsStorage**: Tests agent stats storage
  - Lyzr session ID is stored
  - Existing stats are updated correctly
  - User messages are skipped

## Key Test Scenarios

### Bug Fixes Verified

1. **LLM Calls Graph Bug**
   - ✅ Tests verify LLM calls are summed, not counted
   - ✅ Tests verify traces contain correct llmCalls values

2. **Timestamp Accuracy Bug**
   - ✅ Tests verify all timestamps are serialized to strings
   - ✅ Tests verify nested structures are properly serialized

3. **Feedback Dashboard Update Bug**
   - ✅ Tests verify cache invalidation on feedback creation
   - ✅ Tests verify WebSocket events are sent
   - ✅ Tests verify both dashboard and agents caches are cleared

## Fixtures

### Available Fixtures (in `conftest.py`)
- `client`: FastAPI TestClient instance
- `mock_db`: Mock database
- `sample_agent_stats`: Sample agent stats data
- `sample_feedback`: Sample feedback data
- `sample_dashboard_data`: Sample dashboard data
- `mock_redis`: Mock Redis client
- `mock_websocket_manager`: Mock WebSocket manager

## Test Best Practices

1. **Isolation**: Each test is independent and doesn't rely on other tests
2. **Mocking**: External dependencies (DB, Redis, WebSocket) are mocked
3. **Coverage**: Critical paths are covered, especially bug fixes
4. **Readability**: Tests are well-documented and named descriptively

## Continuous Integration

These tests should be run:
- Before every commit
- In CI/CD pipeline
- Before deployment
- After bug fixes

## Notes

- Tests use mocking to avoid requiring actual database/Redis connections
- Some tests use `asyncio.run()` for async functions
- WebSocket tests verify event broadcasting without actual WebSocket connections
- Cache invalidation tests verify the code attempts to invalidate, even if imports fail




