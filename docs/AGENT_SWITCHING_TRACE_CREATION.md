# Agent Switching - Trace Creation Implementation

## Overview
This document explains the implementation that ensures **a new trace is created every time an agent is switched** in the WhatsApp bot system.

## Problem Statement
Previously, when users switched between agents (e.g., from Product Recommendation to Sales Pitch, or vice versa), the system would update the same conversation/trace instead of creating a new one. This made it difficult to track individual agent interactions separately.

## Solution
We've implemented a solution that:
1. **Generates a unique conversation ID** when agents are switched
2. **Creates a new Feedback/trace entry** for each agent interaction
3. **Ensures proper session isolation** for each Lyzr agent session

---

## Changes Made

### 1. Updated `bot_logic.py` - Agent Switching Logic

**File:** `backend-python/app/services/bot_logic.py`

**Changes (Lines 601-657):**
- When switching to Product Recommendation agent:
  - Generate a new `unique_conversation_id` using UUID
  - Clear any existing Lyzr session for that agent type  
  - Store the new conversation ID in the state
  - Set `start_new_session` and `agent_switched` flags

- When switching to Sales Pitch agent:
  - Same logic as above for sales pitch agent

**Key Code:**
```python
# Generate new unique conversation ID for fresh Lyzr session and new trace
import uuid
new_conversation_id = str(uuid.uuid4())
logger.info(f"🆔 Generated NEW Conversation ID for agent switch: {new_conversation_id}")

# Clear any existing Lyzr session
from app.services.lyzr_service import clear_lyzr_session
clear_lyzr_session(session_id, "product_recommendation")

return {
    "new_state": {
        **current_state,
        "agent_type": "product_recommendation",
        "unique_conversation_id": new_conversation_id  # New ID for fresh trace
    },
    "start_new_session": True,
    "agent_switched": True  # Flag to indicate agent was switched
}
```

### 2. Updated `chat.py` - Trace Creation on Agent Switch

**File:** `backend-python/app/routes/chat.py`

**Changes (Lines 207-231):**
- Added logic to detect when an agent is switched (`agent_switched` flag)
- When switch is detected, create a new feedback placeholder with the unique conversation ID
- This creates a separate trace entry in the database

**Key Code:**
```python
# Create new feedback/trace entry when agent is switched
if result.get("agent_switched"):
    trace_session_id = result["new_state"].get("unique_conversation_id") or session_id
    
    await dashboard_service.create_feedback_placeholder(
        username=username,
        agent_code=agent_code,
        agent_type=result["agent_type"],
        session_id=trace_session_id  # Use unique conversation ID
    )
```

**Changes (Lines 319-337):**
- Updated dashboard event creation to use `unique_conversation_id` instead of main `session_id`
- This ensures each agent selection/switch gets its own trace

**Key Code:**
```python
# Use unique_conversation_id for dashboard/trace events
trace_session_id = result["new_state"].get("unique_conversation_id") or session_id

if result["agent_type"] == "product_recommendation":
    await dashboard_service.create_recommendation_event(trace_session_id)
elif result["agent_type"] == "sales_pitch":
    await dashboard_service.create_sales_pitch_event(trace_session_id)
```

---

## How It Works

### Flow Diagram

```
User Selects Agent (Option 1 or 2)
        ↓
Generate unique_conversation_id (UUID)
        ↓
Store in state["unique_conversation_id"]
        ↓
Create Feedback placeholder with unique_conversation_id
        ↓
[User interacts with Agent A]
        ↓
User switches to Agent B
        ↓
Generate NEW unique_conversation_id (UUID)
        ↓
Clear Lyzr session for Agent B
        ↓
Create NEW Feedback placeholder with NEW unique_conversation_id
        ↓
[User interacts with Agent B]
        ↓
Result: Two separate traces in database
```

### Database Structure

The `Feedback` collection now stores each agent interaction separately:

```javascript
// First agent interaction
{
  _id: ObjectId("..."),
  sessionId: "abc123-unique-id-1",  // unique_conversation_id
  username: "Rohit",
  agentCode: "R45",
  agentType: "product_recommendation",
  feedback: "Pending",
  createdAt: ISODate("2026-01-10T08:00:00Z")
}

// After switching to sales pitch
{
  _id: ObjectId("..."),
  sessionId: "xyz789-unique-id-2",  // NEW unique_conversation_id
  username: "Rohit",
  agentCode: "R45", 
  agentType: "sales_pitch",
  feedback: "Pending",
  createdAt: ISODate("2026-01-10T08:15:00Z")
}
```

---

## Benefits

1. **Accurate Trace Counting**: Each agent interaction is counted as a separate trace
2. **Clean Session Isolation**: Each agent gets its own Lyzr session, preventing context bleeding
3. **Better Analytics**: Can track which agents are used more frequently
4. **Proper Token/LLM Call Tracking**: Each trace has its own LLM call count
5. **Improved Dashboard**: Traces table shows accurate counts per agent type

---

## Testing

To verify the implementation works:

1. **Start a conversation:**
   - Enter agent code (e.g., R45)
   - Select option 1 (Product Recommendation)
   - Verify trace is created in Feedback collection

2. **Switch agents:**
   - Type "switch to sales" or select menu and choose option 2
   - Verify NEW trace is created with different sessionId
   - Check that unique_conversation_id is different

3. **Verify in database:**
   ```javascript
   db.feedback.find({agentCode: "R45"}).sort({createdAt: -1})
   ```
   Should show multiple documents, each with unique sessionId

4. **Check Traces dashboard:**
   - Navigate to Traces page
   - Filter by "All Agents" or specific agent type
   - Verify each agent interaction appears as separate row

---

## Debugging

If traces are not being created:

1. **Check logs for:**
   ```
   🆔 Generated NEW Conversation ID for agent switch: [uuid]
   🔄 Agent was switched - creating new feedback trace
   ✅ New feedback trace created for agent switch
   ```

2. **Verify database:**
   - Check Feedback collection for entries with agent_switched traces
   - Verify each has unique sessionId (unique_conversation_id)

3. **Common issues:**
   - MongoDB connection issues
   - `dashboard_service.create_feedback_placeholder()` errors
   - Missing `unique_conversation_id` in state

---

## Future Enhancements

1. **Link related traces**: Add a parent_session_id to link all traces from same WhatsApp session
2. **Trace analytics**: Track average time per agent type
3. **Agent preference analysis**: Which agents are switched to most frequently
4. **Session flow visualization**: Show agent switching patterns

---

## Related Files

- `backend-python/app/services/bot_logic.py` - Agent switching logic
- `backend-python/app/routes/chat.py` - Trace creation
- `backend-python/app/services/dashboard_service.py` - Feedback collection management
- `backend-python/app/services/lyzr_service.py` - Lyzr session management

---

## Author
Implemented: 2026-01-10
