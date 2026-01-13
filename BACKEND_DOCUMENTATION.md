# Star Health WhatsApp Bot - Backend Technical Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [File Structure & Components](#file-structure--components)
4. [API Endpoints](#api-endpoints)
5. [Database Schema](#database-schema)
6. [Service Layer](#service-layer)
7. [External Integrations](#external-integrations)
8. [Data Flow](#data-flow)
9. [Security & Authentication](#security--authentication)
10. [Deployment & Configuration](#deployment--configuration)

---

## 1. System Overview

### 1.1 Purpose
The backend is a FastAPI-based REST API that:
- Receives WhatsApp messages via Twilio webhooks
- Processes messages through a state machine (BotLogic)
- Routes conversations to Lyzr AI agents (Product Recommendation or Sales Pitch)
- Stores conversation metadata and analytics in MongoDB
- Provides real-time dashboard data via WebSocket
- Manages user authentication and authorization

### 1.2 Technology Stack
- **Framework**: FastAPI 0.104.1
- **Language**: Python 3.11+
- **Database**: MongoDB (via PyMongo 4.9.0, Motor 3.6.0)
- **Cache**: Redis 5.0+ (for dashboard SWR caching)
- **External APIs**: 
  - Twilio (WhatsApp messaging)
  - Lyzr AI (Agent orchestration)
- **Authentication**: JWT (PyJWT 2.8.0), bcrypt 4.2.0
- **WebSocket**: FastAPI WebSocket support

---

## 2. Architecture

### 2.1 High-Level Architecture

```
┌─────────────┐
│   Twilio    │───Webhook───►┌──────────────┐
│  WhatsApp   │              │   FastAPI    │
└─────────────┘              │   Backend    │
                              └──────┬───────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
              ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
              │  MongoDB  │   │   Redis   │   │  Lyzr AI  │
              │  Storage  │   │   Cache   │   │  Agents   │
              └───────────┘   └───────────┘   └───────────┘
```

### 2.2 Request Flow

1. **WhatsApp Message Flow**:
   ```
   Twilio Webhook → /webhook → whatsapp.py → BotLogic → SessionService
                                                      ↓
                                              LyzrService → Lyzr API
                                                      ↓
                                              ChatStorage → MongoDB
                                                      ↓
                                              DashboardService → Events
   ```

2. **Dashboard Data Flow**:
   ```
   Frontend Request → /api/dashboard → dashboard.py → Redis Cache Check
                                                      ↓
                                              MongoDB Aggregation
                                                      ↓
                                              Redis Cache Update
                                                      ↓
                                              JSON Response
   ```

3. **WebSocket Real-Time Updates**:
   ```
   Dashboard Event → DashboardService → WebSocket Manager → Broadcast
                                                              ↓
                                                      All Connected Clients
   ```

---

## 3. File Structure & Components

### 3.1 Root Application Entry
**File**: `backend-python/app/main.py`

**Purpose**: FastAPI application initialization, middleware setup, route registration

**Key Components**:
- `app`: FastAPI application instance
- CORS middleware configuration
- Route registration for all API endpoints
- Startup/shutdown event handlers
- Global exception handler

**Methods**:
- `startup_event()`: Non-blocking initialization of MongoDB, Redis, indexes, watchers
- `_initialize_services_background()`: Background service initialization
- `_init_mongodb()`: MongoDB connection with retries
- `_init_redis()`: Redis connection check
- `_create_indexes_async()`: Database index creation
- `_setup_watchers_async()`: MongoDB change stream watchers
- `_prewarm_dashboard_async()`: Dashboard cache pre-warming
- `_prewarm_rag_async()`: RAG content pre-warming
- `global_exception_handler()`: Enterprise error handling (503 during warmup)

**Routes Registered**:
- `/api/chat/*` → `chat.router`
- `/api/whatsapp/*` → `whatsapp.router`
- `/api/rag/*` → `rag.router`
- `/api/dashboard/*` → `dashboard.router`
- `/api/knowledge/*` → `knowledge.router`
- `/api/feedback/*` → `feedback_route.router`
- `/api/agents/*` → `agents_route.router`
- `/api/agents/stats/*` → `agents_stats.router`
- `/api/users/*` → `users_route.router`
- `/api/auth/*` → `auth.router`
- `/ws` → `websocket.router`
- `/health/*` → `health.router`
- `/webhook` → Root webhook endpoint (bypasses /api prefix)

**Dependencies**:
- `app.config.logging_config`: Logging setup
- `app.config.database`: MongoDB connection
- `app.services.mongo_watcher`: Change stream watchers
- `app.services.readiness_monitor`: Health monitoring

---

### 3.2 Configuration Layer

#### 3.2.1 Database Configuration
**File**: `backend-python/app/config/database.py`

**Purpose**: Centralized MongoDB connection management

**Key Functions**:
- `get_database()`: Returns MongoDB database instance (singleton pattern)
- `get_client()`: Returns MongoDB client instance
- `is_mongodb_ready()`: Health check for MongoDB connection
- `is_warming_up()`: Checks if MongoDB is still initializing
- `close_connection()`: Cleanup connection

**Connection Logic**:
1. Checks environment variables: `MONGODB_URI` or `MONGODB_URI`
2. Extracts database name from URI or uses `MONGODB_DATABASE` env var
3. Default database: `Star_Health_Whatsapp_bot`
4. Implements connection pooling via PyMongo

**Collections Used**:
- `agents`: Agent codes and metadata
- `users`: User information
- `sessions`: Session state management
- `dashboarddata`: Dashboard event tracking
- `feedback`: User feedback entries
- `agent_stats`: Agent performance metrics
- `lyzr_sessions`: Lyzr session ID mapping
- `login_details`: Admin authentication
- `knowledge`: RAG knowledge base
- `Prompts`: Customizable agent prompts

#### 3.2.2 Redis Configuration
**File**: `backend-python/app/services/redis_service.py`

**Purpose**: Redis connection for dashboard caching

**Class**: `RedisService`
- `__init__()`: Connects to Redis (supports Redis Cloud URL or individual settings)
- Connection tested via `ping()`
- Used exclusively for dashboard SWR caching

**File**: `backend-python/app/config/redis_checker.py`

**Purpose**: Independent Redis readiness checker (avoids circular imports)

**Function**: `check_redis_readiness()` → bool
- Tests Redis connection with 2-second timeout
- Returns False on any error (never throws)

#### 3.2.3 Logging Configuration
**File**: `backend-python/app/config/logging_config.py`

**Purpose**: Centralized logging setup

**Functions**:
- `setup_logging()`: Configures logging with file and console handlers
- `get_logger(name)`: Returns logger instance for a module

**Log Files**:
- `logs/app_YYYYMMDD.log`: Application logs
- `logs/error_YYYYMMDD.log`: Error logs

---

### 3.3 Route Handlers

#### 3.3.1 WhatsApp Webhook Handler
**File**: `backend-python/app/routes/whatsapp.py`

**Purpose**: Processes incoming WhatsApp messages from Twilio

**Key Function**: `_process_whatsapp_message(MessageSid, From, To, Body)`

**Flow**:
1. Parse webhook data via `WhatsAppService.parse_incoming_webhook()`
2. Get/create session via `SessionService.get_or_create_session_for_phone()`
3. Get session state from MongoDB
4. Detect feedback messages (natural language ratings)
5. Process message through `BotLogic.process_message()`
6. Update session state
7. Save user message to MongoDB (non-blocking)
8. If agent active:
   - Get agent ID from `LyzrService.get_agent_id()`
   - Call `LyzrService.optimized_call_agent()`
   - Save agent response to MongoDB
   - Create dashboard events
9. Send response via `TwilioService.send_whatsapp_messages()`
10. Return TwiML response

**Routes**:
- `POST /api/whatsapp/webhook`: Main webhook endpoint
- `POST /api/webhook`: Compatibility route
- `GET /api/whatsapp/health`: Health check

**Dependencies**:
- `BotLogic`: State machine processing
- `LyzrService`: AI agent calls
- `SessionService`: Session management
- `ChatStorage`: Message persistence
- `DashboardService`: Event tracking
- `TwilioService`: Message sending

#### 3.3.2 Dashboard Routes
**File**: `backend-python/app/routes/dashboard.py`

**Purpose**: Dashboard analytics with SWR (Stale-While-Revalidate) caching

**Key Class**: `RedisSWRCache`
- Implements SWR pattern for dashboard data
- Cache key format: `dashboard:{days}:v{version}`
- Version based on hour: `YYYY-MM-DDTHH_v3`
- TTL: 15 minutes (with permanent retention option)

**Key Function**: `_fetch_dashboard_data_from_db(days: int)`

**Parallel Query Execution** (ThreadPoolExecutor with 12 workers):
1. Unique Users (current & previous period)
2. Total Interactions (agent_stats + dashboarddata)
3. Feedback Count (completed conversations)
4. Recommendations count
5. Sales Pitches count
6. Incomplete Conversations count
7. Repeated Users count
8. Recent Activity (last 5 feedback entries with agent name resolution)
9. Top Agents (aggregation pipeline)
10. Feedback Distribution by type
11. Activity Distribution (daily breakdown)
12. Completed Conversations Distribution

**Routes**:
- `GET /api/dashboard?days=7`: Get dashboard data (SWR cached)

**Response Structure**:
```json
{
  "meta": {
    "days": 7,
    "generatedAt": "2024-01-01T12:00:00"
  },
  "summary": {
    "totalUsers": 100,
    "totalConversations": 200,
    "completed": 150,
    "incomplete": 50,
    "totalInteractions": 500,
    "feedbackCount": 150,
    "recommendations": 80,
    "salesPitches": 70,
    "repeatedUsers": 30
  },
  "trends": {
    "uniqueUsers": 10.5,
    "totalInteractions": 15.2,
    ...
  },
  "topStats": {
    "topAgents": [...],
    "feedbackByType": {...}
  },
  "recentActivity": [...],
  "activityDistribution": {...},
  "completedConversationsData": {...}
}
```

**Background Refresh**:
- `_refresh_cache_background(days)`: Refreshes cache in background thread
- Uses Redis lock (`dashboard:refreshing:{days}`) to prevent duplicate refreshes
- Triggers on cache miss or stale data

#### 3.3.3 Authentication Routes
**File**: `backend-python/app/routes/auth.py`

**Purpose**: User authentication, authorization, and profile management

**Key Functions**:
- `hash_password(password)`: bcrypt password hashing
- `verify_password(password, hashed)`: Password verification
- `generate_jwt_token(user_data)`: JWT token generation (24h expiry)
- `verify_jwt_token(token)`: JWT verification
- `get_current_user()`: Dependency for authenticated routes
- `require_admin()`: Dependency for admin-only routes

**Routes**:
- `POST /api/auth/signup`: User registration
- `POST /api/auth/signin`: User login (admin-only)
- `POST /api/auth/verify-2fa`: Two-factor authentication verification
- `GET /api/auth/profile`: Get current user profile
- `PUT /api/auth/profile`: Update user profile
- `PUT /api/auth/change-password/{email}`: Change password
- `GET /api/auth/me`: Get current user info
- `GET /api/auth/users`: Get all users (admin only)
- `PUT /api/auth/update-admin-access`: Grant/revoke admin access
- `DELETE /api/auth/users/{email}`: Delete user (admin only)

**Security Features**:
- Password hashing with bcrypt (10 rounds)
- JWT tokens with expiration
- 2FA support (6-digit code via WhatsApp)
- Admin-only access enforcement
- Self-deletion prevention

#### 3.3.4 Other Route Files

**File**: `backend-python/app/routes/chat.py`
- Chat history retrieval

**File**: `backend-python/app/routes/rag.py`
- RAG knowledge base management

**File**: `backend-python/app/routes/knowledge.py`
- Knowledge base CRUD operations

**File**: `backend-python/app/routes/feedback_route.py`
- Feedback submission and retrieval

**File**: `backend-python/app/routes/agents_route.py`
- Agent management (CRUD)

**File**: `backend-python/app/routes/agents_stats.py`
- Agent performance statistics

**File**: `backend-python/app/routes/users_route.py`
- User management

**File**: `backend-python/app/routes/agent_config.py`
- Agent configuration (custom prompts)

**File**: `backend-python/app/routes/health.py`
- Health check endpoints (`/health/ready`, `/health/live`)

**File**: `backend-python/app/routes/websocket.py`
- WebSocket endpoint (`/ws`) for real-time updates

---

### 3.4 Service Layer

#### 3.4.1 Bot Logic Service
**File**: `backend-python/app/services/bot_logic.py`

**Purpose**: Deterministic state machine for conversation flow

**Class**: `BotLogic`

**States**:
1. `greeting`: Initial state, waiting for agent code
2. `code_entered`: Agent code validated, waiting for option selection
3. `agent_active`: Lyzr agent handling conversation

**Key Method**: `process_message(message, session_id, current_state, phone_number)`

**Flow**:
1. **Greeting State**:
   - Validates agent code format (regex: `^[A-Z]{2,}\d{2,}$`)
   - Looks up agent in MongoDB `agents` collection
   - Validates phone number match (if configured)
   - Transitions to `code_entered` state
   - Returns menu message

2. **Code Entered State**:
   - Parses option selection (1 or 2)
   - Sets `agent_type` (product_recommendation or sales_pitch)
   - Transitions to `agent_active` state
   - Returns confirmation message

3. **Agent Active State**:
   - Passes message directly to Lyzr (no bot response)
   - Returns empty response (Lyzr handles it)

**Dependencies**:
- MongoDB `agents` collection
- MongoDB `users` collection
- MongoDB `Prompts` collection (for customizable messages)

#### 3.4.2 Lyzr Service
**File**: `backend-python/app/services/lyzr_service.py`

**Purpose**: Integration with Lyzr AI Agent API

**Class**: `LyzrService`

**Key Methods**:

1. **`get_agent_id(agent_type)`**:
   - Checks `Prompts` collection for customized agent configuration
   - Returns customized agent ID if `mode == "customize"`
   - Otherwise returns default agent ID from environment variables

2. **`optimized_call_agent(agent_id, message, session_id, ...)`**:
   - **First Call**: POST to `/v3/inference/chat/` to get Lyzr session ID
   - Stores session ID in MongoDB `lyzr_sessions` collection
   - **Subsequent Calls**: Reuses session ID, sends message
   - **Polling**: Polls for results using GET requests (or POST with empty message)
   - Returns parsed agent response

3. **`get_or_create_lyzr_session(...)`**:
   - Gets or creates Lyzr session ID
   - Stores in database for persistence

4. **`send_message_to_lyzr_session(...)`**:
   - Sends message to existing Lyzr session

5. **`poll_lyzr_session_get(...)`**:
   - Polls session status via GET requests

**Session Management**:
- Session IDs stored in MongoDB `lyzr_sessions` collection
- Key: `{sessionId, agentId}` → `lyzrSessionId`
- In-memory cache for fast access (fallback)

**API Endpoints Used**:
- `POST https://agent-prod.studio.lyzr.ai/v3/inference/chat/`
- `GET https://agent-prod.studio.lyzr.ai/v3/inference/chat/{agent_id}/session/{session_id}/status` (if available)

**Error Handling**:
- Connection errors → User-friendly messages
- Timeout errors → Retry logic
- Status code errors → Appropriate error messages

#### 3.4.3 Session Service
**File**: `backend-python/app/services/session_service.py`

**Purpose**: Session state management in MongoDB

**Class**: `SessionService`

**Key Methods**:
- `get_or_create_session()`: Creates anonymous session
- `get_or_create_session_for_phone(phone_number)`: Gets or creates session for phone number
- `get_session_state(session_id)`: Retrieves session state from MongoDB
- `update_session_state(session_id, state)`: Updates session state
- `is_session_expired(session_id)`: Checks session expiry
- `get_session_metadata(session_id)`: Gets session metadata
- `set_session_metadata(session_id, metadata)`: Sets session metadata

**Session Expiry**:
- TTL: 30 minutes (configurable via `SESSION_EXPIRY_MINUTES`)
- MongoDB TTL index on `updated_at` field
- Manual expiry check on retrieval

**Collection**: `sessions`
**Schema**:
```json
{
  "session_id": "uuid",
  "phone": "whatsapp:+1234567890",
  "state": "greeting|code_entered|agent_active",
  "username": "string",
  "agent_code": "string",
  "agent_type": "product_recommendation|sales_pitch",
  "created_at": "datetime",
  "updated_at": "datetime",
  "metadata": {}
}
```

#### 3.4.4 Chat Storage Service
**File**: `backend-python/app/services/chat_storage.py`

**Purpose**: Message persistence and agent statistics

**Class**: `ChatStorage`

**Key Method**: `save_message(...)`

**What Gets Stored**:
- **Lyzr Session ID**: Stored in `lyzr_sessions` collection
- **Agent Statistics**: Stored in `agent_stats` collection
  - `messageCount`: Incremented per message
  - `totalTokens`: Estimated tokens (message length / 4)
  - `llmCalls`: LLM call count

**What Does NOT Get Stored** (Privacy Requirement):
- Message content (user messages or agent responses)
- Conversation history

**Collections**:
- `lyzr_sessions`: Session ID mapping
- `agent_stats`: Performance metrics

#### 3.4.5 Dashboard Service
**File**: `backend-python/app/services/dashboard_service.py`

**Purpose**: Dashboard event creation and feedback management

**Class**: `DashboardService`

**Key Methods**:
- `create_event(event_type, data)`: Creates dashboard event
- `create_session_event(username, agent_code)`: New session event
- `create_recommendation_event(session_id)`: Recommendation completed
- `create_sales_pitch_event(session_id)`: Sales pitch delivered
- `create_feedback(...)`: Creates or updates feedback entry
- `create_feedback_placeholder(...)`: Creates pending feedback entry
- `create_incomplete_conversation_event(...)`: Tracks incomplete conversations
- `notify_activity_update(agent_type, llm_calls)`: WebSocket notification

**Event Types**:
- `new_session`: User starts conversation
- `recommendation`: Product recommendation completed
- `sales_pitch`: Sales pitch delivered
- `feedback`: User feedback submitted
- `session_end`: Conversation ended
- `incomplete_conversation`: User left without feedback

**WebSocket Integration**:
- Broadcasts events to all connected clients via `WebSocketManager`

**Collections**:
- `dashboarddata`: Event storage
- `feedback`: Feedback entries
- `users`: User information

#### 3.4.6 Other Services

**File**: `backend-python/app/services/twilio_service.py`
- Twilio WhatsApp message sending
- Message splitting (1600 char limit)

**File**: `backend-python/app/services/whatsapp_service.py`
- WhatsApp webhook parsing

**File**: `backend-python/app/services/rag_service.py`
- RAG knowledge base operations

**File**: `backend-python/app/services/dashboard_aggregator.py`
- Dashboard data aggregation logic

**File**: `backend-python/app/services/customized_agent_service.py`
- Custom agent configuration management

**File**: `backend-python/app/services/email_service.py`
- Email notifications

**File**: `backend-python/app/services/mongo_watcher.py`
- MongoDB change stream watchers for real-time updates

**File**: `backend-python/app/services/readiness_monitor.py`
- System readiness monitoring

---

### 3.5 Models

**File**: `backend-python/app/models/models.py`

**Purpose**: Pydantic models for request/response validation

**Models**:
- `UserCreate`, `UserResponse`
- `FeedbackCreate`, `FeedbackResponse`
- `KnowledgeCreate`, `KnowledgeUpdate`, `KnowledgeResponse`
- `AgentCreate`, `AgentUpdate`, `AgentResponse`
- `SignUpRequest`, `SignInRequest`, `VerifyRequest`
- `ChangePasswordRequest`, `ProfileUpdateRequest`
- `UserProfileResponse`, `AuthResponse`
- `TwoFactorRequest`, `UpdateAdminAccessRequest`

---

## 4. API Endpoints

### 4.1 WhatsApp Endpoints
- `POST /webhook`: Root webhook (Twilio)
- `POST /api/whatsapp/webhook`: Webhook endpoint
- `POST /api/webhook`: Compatibility route
- `GET /api/whatsapp/health`: Health check

### 4.2 Dashboard Endpoints
- `GET /api/dashboard?days=7`: Get dashboard data

### 4.3 Authentication Endpoints
- `POST /api/auth/signup`: Register user
- `POST /api/auth/signin`: Login
- `POST /api/auth/verify-2fa`: Verify 2FA code
- `GET /api/auth/profile`: Get profile
- `PUT /api/auth/profile`: Update profile
- `PUT /api/auth/change-password/{email}`: Change password
- `GET /api/auth/me`: Get current user
- `GET /api/auth/users`: List users (admin)
- `PUT /api/auth/update-admin-access`: Update admin access
- `DELETE /api/auth/users/{email}`: Delete user (admin)

### 4.4 Health Endpoints
- `GET /health/ready`: Readiness probe
- `GET /health/live`: Liveness probe

### 4.5 WebSocket
- `WS /ws`: Real-time updates

---

## 5. Database Schema

### 5.1 Collections

#### `agents`
```json
{
  "_id": "ObjectId",
  "agent_code": "AB123",
  "agent_name": "John Doe",
  "phone_number": "+1234567890",
  "email": "agent@example.com",
  "role": "Sales Agent",
  "createdAt": "datetime",
  "updatedAt": "datetime"
}
```

#### `sessions`
```json
{
  "_id": "ObjectId",
  "session_id": "uuid",
  "phone": "whatsapp:+1234567890",
  "state": "greeting|code_entered|agent_active",
  "username": "string",
  "agent_code": "string",
  "agent_type": "product_recommendation|sales_pitch",
  "created_at": "datetime",
  "updated_at": "datetime",
  "metadata": {}
}
```
**Indexes**: `session_id` (unique), `phone`, `updated_at` (TTL)

#### `dashboarddata`
```json
{
  "_id": "ObjectId",
  "eventType": "new_session|recommendation|sales_pitch|feedback|session_end|incomplete_conversation",
  "data": {
    "username": "string",
    "agent_code": "string",
    "session_id": "uuid",
    "agent_type": "string"
  },
  "createdAt": "datetime",
  "timestamp": "iso_string"
}
```

#### `feedback`
```json
{
  "_id": "ObjectId",
  "username": "string",
  "agentCode": "string",
  "agentType": "product_recommendation|sales_pitch",
  "feedback": "string",
  "sessionId": "uuid",
  "conversationStatus": "completed|incomplete",
  "createdAt": "datetime",
  "updatedAt": "datetime"
}
```

#### `agent_stats`
```json
{
  "_id": "ObjectId",
  "sessionId": "uuid",
  "agentCode": "string",
  "agentName": "string",
  "agentType": "string",
  "username": "string",
  "messageCount": 0,
  "totalTokens": 0,
  "llmCalls": 0,
  "lyzrSessionId": "string",
  "createdAt": "datetime",
  "updatedAt": "datetime",
  "timestamp": "datetime"
}
```

#### `lyzr_sessions`
```json
{
  "_id": "ObjectId",
  "sessionId": "uuid",
  "agentId": "string",
  "lyzrSessionId": "string",
  "agentType": "string",
  "agentCode": "string",
  "username": "string",
  "isActive": true,
  "createdAt": "datetime",
  "updatedAt": "datetime",
  "lastMessageAt": "datetime"
}
```

#### `login_details`
```json
{
  "_id": "ObjectId",
  "email": "string",
  "password": "bcrypt_hash",
  "firstName": "string",
  "lastName": "string",
  "phone": "string",
  "bio": "string",
  "isAdmin": false,
  "isActive": true,
  "twoFactorEnabled": false,
  "twoFactorCode": "hmac_hash",
  "twoFactorCodeExpiry": "datetime",
  "createdAt": "datetime",
  "updatedAt": "datetime",
  "lastLogin": "datetime"
}
```

---

## 6. External Integrations

### 6.1 Twilio WhatsApp API
- **Purpose**: Send/receive WhatsApp messages
- **Service**: `TwilioService`
- **Methods**: `send_whatsapp_message()`, `send_whatsapp_messages()`
- **Message Limit**: 1600 characters (auto-split)

### 6.2 Lyzr AI API
- **Purpose**: AI agent orchestration
- **Service**: `LyzrService`
- **Endpoint**: `https://agent-prod.studio.lyzr.ai/v3/inference/chat/`
- **Authentication**: Bearer token (`LYZR_API_KEY`)
- **Agents**:
  - Product Recommendation Agent
  - Sales Pitch Agent

---

## 7. Security & Authentication

### 7.1 Authentication Flow
1. User signs in → Password verified via bcrypt
2. JWT token generated (24h expiry)
3. Token stored in frontend localStorage
4. Token sent in `Authorization: Bearer {token}` header
5. Backend verifies token on protected routes

### 7.2 2FA Flow
1. User signs in with 2FA enabled
2. 6-digit code generated
3. Code hashed via HMAC-SHA256
4. Code sent via WhatsApp
5. User submits code → Verified against hash
6. JWT token issued

### 7.3 Admin Access
- Only users with `isAdmin: true` can access dashboard
- Enforced at route level via `require_admin()` dependency

---

## 8. Deployment & Configuration

### 8.1 Environment Variables
```bash
# MongoDB
MONGODB_URI=mongodb://...
MONGODB_URI=mongodb://...
MONGODB_DATABASE=Star_Health_Whatsapp_bot

# Redis
REDIS_URL=redis://...
REDIS_HOST=...
REDIS_PORT=...
REDIS_PASSWORD=...
REDIS_USERNAME=...

# Twilio
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_NUMBER=...

# Lyzr
LYZR_API_KEY=...
LYZR_API_URL=https://api.lyzr.ai
LYZR_PRODUCT_RECOMMENDATION_AGENT_ID=...
LYZR_SALES_PITCH_AGENT_ID=...

# JWT
JWT_SECRET=...

# Session
SESSION_EXPIRY_MINUTES=30
```

### 8.2 Startup Sequence
1. FastAPI app starts immediately
2. Background tasks initialize:
   - MongoDB connection (with retries)
   - Redis connection check
   - Database indexes creation
   - MongoDB watchers setup
   - Dashboard cache pre-warming
   - RAG content pre-warming

### 8.3 Health Checks
- `/health/ready`: Checks MongoDB, Redis readiness
- `/health/live`: Basic liveness check

---

## 9. Error Handling

### 9.1 Global Exception Handler
- Returns 503 during warmup phase
- Returns 500 for other errors (no details exposed)
- Logs full error details server-side

### 9.2 Service-Level Error Handling
- All services implement graceful degradation
- MongoDB failures don't crash the app
- Redis failures fall back to direct DB queries

---

## 10. Performance Optimizations

### 10.1 Dashboard Caching
- SWR pattern: Return stale data immediately, refresh in background
- Redis caching with 15-minute TTL
- Parallel query execution (12 workers)

### 10.2 Session Management
- MongoDB TTL indexes for automatic cleanup
- In-memory session cache (fallback)

### 10.3 Background Tasks
- Non-blocking startup
- Background cache refreshes
- WebSocket broadcasts from async context

---

**End of Backend Documentation**

