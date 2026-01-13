# Lyzr Agent Initialization: HI Message Implementation

## Overview
Updated the system to send "HI" as the first message to Lyzr agents when starting a new conversation, instead of sending the agent name. This ensures clean, separate traces for each agent interaction.

## Changes Made

### File: `backend-python/app/routes/chat.py`

**Lines 248-259**: Modified message preparation logic

**Before:**
```python
# Sent agent name with first message
if result.get("start_new_session") and username != 'N/A':
    message_to_send = f"[Agent Name: {username}]\n\n{request.message}"
```

**After:**
```python
# Send "HI" as initialization message
if result.get("start_new_session"):
    message_to_send = "HI"
else:
    message_to_send = request.message
```

---

## How It Works

### Conversation Flow

#### **1. User Selects Agent (First Time)**
```
User Action: Select Option 1 (Product Recommendation)
Bot Response: "Connecting to Product Recommendation Agent..."
System Action:
  ✅ Generate unique_conversation_id: "550e8400-e29b-41d4..."
  ✅ Set start_new_session = True
  ✅ Send "HI" to Lyzr agent
  ✅ Create new trace in Feedback collection
Lyzr Response: "Hello! I'm here to help you find the perfect health insurance..."
User Sees: Lyzr's greeting response
```

#### **2. User Continues Conversation**
```
User Message: "Tell me about health insurance for seniors"
System Action:
  ✅ start_new_session = False
  ✅ Send user's actual message to Lyzr
Lyzr Response: "For seniors, we have excellent plans..."
User Sees: Lyzr's response to their question
```

#### **3. User Switches Agent**
```
User Action: Switch to Sales Pitch agent
System Action:
  ✅ Generate NEW unique_conversation_id: "7c9e6679-7425..."
  ✅ Set start_new_session = True
  ✅ Set agent_switched = True
  ✅ Clear previous Lyzr session
  ✅ Send "HI" to new Lyzr agent
  ✅ Create NEW trace in Feedback collection
Lyzr Response: "Hello! Let me help you close this deal..."
User Sees: New agent's greeting
```

---

## Key Features

### ✅ **Unique Traces for Each Conversation**
Each agent interaction gets its own trace with a unique ID:

```javascript
// Feedback Collection
[
  {
    sessionId: "550e8400-e29b-41d4-a716-446655440000",  // First agent
    agentType: "product_recommendation",
    agentCode: "R45",
    llmCalls: 14,
    totalTokens: 3596
  },
  {
    sessionId: "7c9e6679-7425-40de-944b-e07fc1f90ae7",  // After switch
    agentType: "sales_pitch",
    agentCode: "R45",
    llmCalls: 8,
    totalTokens: 2145
  }
]
```

### ✅ **No Conversation Mixing**
- Each `unique_conversation_id` maps to exactly one Lyzr session
- Switching agents creates a completely new session
- No context bleeding between agent types

### ✅ **Clean Initialization**
- First message to any agent is always "HI"
- No agent name or other metadata sent
- Lyzr agents handle the greeting naturally

---

## Message Sending Logic

```python
# Determination of what to send to Lyzr
if result.get("start_new_session"):
    # First message to this agent
    message_to_send = "HI"
    # This happens when:
    # - User selects agent for first time
    # - User switches to different agent
    # - User returns to menu and selects agent again
else:
    # Subsequent messages
    message_to_send = request.message
    # This happens for all normal conversation messages
```

---

## Database Structure

### Lyzr Sessions Collection
```javascript
{
  sessionId: "550e8400-e29b-41d4-a716-446655440000",  // unique_conversation_id
  agentId: "6942d9fd3cc5fbe223b01863",               // Lyzr agent ID
  lyzrSessionId: "lyzr-abc-def-123",                 // Lyzr's internal session
  agentType: "product_recommendation",
  agentCode: "R45",
  username: "Rohith",
  isActive: true,
  createdAt: ISODate("2026-01-10T03:30:00Z"),
  updatedAt: ISODate("2026-01-10T03:35:00Z")
}
```

### Feedback Collection (Traces)
```javascript
{
  sessionId: "550e8400-e29b-41d4-a716-446655440000",  // Same as lyzr_sessions
  agentType: "product_recommendation",
  agentCode: "R45",
  username: "Rohith",
  feedback: "Pending",  // Or actual feedback when provided
  createdAt: ISODate("2026-01-10T03:30:00Z"),
  llmCalls: 14,
  totalTokens: 3596
}
```

---

## Benefits

1. **Unique Session IDs**: Each conversation gets its own UUID
2. **Clean Traces**: Easy to track and count individual interactions
3. **No Mixing**: Agent switches create completely separate sessions
4. **Natural Greetings**: Lyzr agents respond to "HI" with their configured greeting
5. **Accurate Analytics**: LLM calls and tokens tracked per conversation
6. **Simple Logic**: One message ("HI") for all first interactions

---

## Testing Scenarios

### Test 1: First Agent Selection
```
1. Enter agent code: R45
2. Select Option 1 (Product Recommendation)
3. Verify: Query sent to Lyzr = "HI"
4. Verify: New trace created with unique sessionId
5. User sees: Lyzr's greeting response
```

### Test 2: Agent Switch
```
1. From active Product Recommendation conversation
2. Type "menu" or use switch command
3. Select Option 2 (Sales Pitch)
4. Verify: NEW unique sessionId generated
5. Verify: Query sent to Lyzr = "HI"
6. Verify: NEW trace created in Feedback collection
7. Verify: Previous trace still exists separately
```

### Test 3: Continued Conversation
```
1. After agent greeting
2. User: "Tell me about health insurance"
3. Verify: Query sent to Lyzr = "Tell me about health insurance"
4. Verify: Same sessionId used
5. Verify: Same trace updated (LLM calls incremented)
```

---

## Logging

### When First Message Sent:
```
🆕 First message to agent - sending initialization greeting
   Sending: HI (to initialize Lyzr agent)
   Unique Conversation ID: 550e8400-e29...
```

### When Subsequent Messages Sent:
```
📤 Subsequent message - sending user input
   Message: Tell me about health insurance for seniors...
```

### When Agent Switched:
```
🔄 Agent was switched - creating new feedback trace
   Previous agent type: product_recommendation
   New agent type: sales_pitch
   Trace Session ID: 7c9e6679-742...
✅ New feedback trace created for agent switch
```

---

## Implementation Notes

- The `start_new_session` flag is set in `bot_logic.py` when:
  - User first selects an agent (Option 1 or 2)
  - User switches agents
  - User returns from menu to agent selection

- The `unique_conversation_id` is generated using UUID v4 for each new agent interaction

- Each Lyzr session is isolated using this unique ID

- The "HI" message is hardcoded and should not be changed without updating Lyzr agent configurations

---

## Related Files

- `backend-python/app/routes/chat.py` - Message sending logic
- `backend-python/app/services/bot_logic.py` - Agent selection and switching
- `backend-python/app/services/lyzr_service.py` - Lyzr API integration
- `backend-python/app/services/dashboard_service.py` - Trace/feedback management

---

## Date
Implemented: 2026-01-10
