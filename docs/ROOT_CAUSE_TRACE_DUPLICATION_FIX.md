# ROOT CAUSE ANALYSIS: Trace Duplication Issue

## Problem Statement
When switching between agents (Product Recommendation ↔ Sales Pitch), the system was **updating the same trace** instead of creating a new one. This resulted in:
- Only one trace visible in the dashboard
- The trace's `agentType` field being overwritten
- Incorrect LLM call and token counts
- Lost conversation history for the previous agent

## Root Cause Identified

### Issue #1: Feedback Placeholder Using Wrong Session ID
**File:** `app/routes/whatsapp.py` - Line 425  
**Problem:** When creating feedback placeholders (when agent asks for feedback), the code was using the main WhatsApp `session_id` instead of the `unique_conversation_id`.

```python
# BEFORE (WRONG):
background_tasks.add_task(
    dashboard_service.create_feedback_placeholder,
    session_id=session_id,  # ❌ Using main session ID
)

# AFTER (FIXED):
trace_id_for_feedback = result["new_state"].get("unique_conversation_id") or session_id
background_tasks.add_task(
    dashboard_service.create_feedback_placeholder,
    session_id=trace_id_for_feedback,  # ✅ Using unique conversation ID
)
```

**Impact:** All feedback placeholders for the same WhatsApp user were linked to the same trace, regardless of agent switches.

---

### Issue #2: Product Tracking Using Wrong Session ID
**Files:** 
- `app/routes/whatsapp.py` - Line 393
- `app/routes/chat.py` - Line 353

**Problem:** Product tracking was using the main `session_id` instead of the `unique_conversation_id`.

```python
# BEFORE (WRONG):
await product_service.track_products_in_response(
    response_text, session_id, result["agent_type"]  # ❌ Using main session ID
)

# AFTER (FIXED):
trace_id_for_tracking = result["new_state"].get("unique_conversation_id") or session_id
await product_service.track_products_in_response(
    response_text, trace_id_for_tracking, result["agent_type"]  # ✅ Using unique ID
)
```

**Impact:** Product mentions were tracked against the main session instead of the specific agent conversation, making it impossible to see which products were mentioned in which agent interaction.

---

## Why This Caused Trace Duplication

### The Flow (BEFORE FIX):

1. **User selects Product Recommendation**
   - bot_logic generates `unique_conversation_id`: `abc-123`
   - Creates feedback record with `sessionId`: `abc-123`
   - ✅ First trace created correctly

2. **Agent asks for feedback**
   - Feedback placeholder created with `sessionId`: `whatsapp-session-456` ❌ WRONG!
   - This OVERWRITES the first trace's sessionId
   - Now the trace has `sessionId`: `whatsapp-session-456`

3. **User switches to Sales Pitch**
   - bot_logic generates NEW `unique_conversation_id`: `xyz-789`
   - Should create NEW feedback record with `sessionId`: `xyz-789`
   - But feedback placeholder was already created with `sessionId`: `whatsapp-session-456`
   - `create_sales_pitch_event` finds existing record with `whatsapp-session-456`
   - UPDATES the agentType from "product_recommendation" to "sales_pitch" ❌ WRONG!

4. **Result:**
   - Only 1 trace exists
   - AgentType changed to "sales_pitch"
   - Previous Product Recommendation conversation lost

---

### The Flow (AFTER FIX):

1. **User selects Product Recommendation**
   - bot_logic generates `unique_conversation_id`: `abc-123`
   - Creates feedback record with `sessionId`: `abc-123`
   - ✅ First trace created

2. **Agent asks for feedback**
   - Feedback placeholder created with `sessionId`: `abc-123` ✅ CORRECT!
   - Updates the SAME trace (correct behavior)
   - Trace still has `sessionId`: `abc-123`

3. **User switches to Sales Pitch**
   - bot_logic generates NEW `unique_conversation_id`: `xyz-789`
   - Creates NEW feedback placeholder with `sessionId`: `xyz-789` ✅ CORRECT!
   - `create_sales_pitch_event` operates on `sessionId`: `xyz-789`
   - Creates/updates SECOND trace (not the first one)

4. **Result:**
   - 2 separate traces exist ✅
   - Trace 1: `abc-123`, agentType: "product_recommendation"
   - Trace 2: `xyz-789`, agentType: "sales_pitch"
   - Both conversations preserved

---

## Technical Details

### Session ID vs Unique Conversation ID

| ID Type | Purpose | Example | Scope |
|---------|---------|---------|-------|
| `session_id` | WhatsApp session (one per user) | `session_123` | Entire WhatsApp conversation |
| `unique_conversation_id` | Agent conversation (one per agent interaction) | `550e8400-e29b...` | Single agent interaction |

### Where Each ID Should Be Used

| Operation | Correct ID | Reason |
|-----------|-----------|---------|
| Save chat message | `session_id` | Chat history is per WhatsApp session |
| Create feedback/trace | `unique_conversation_id` | Each agent interaction needs its own trace |
| Track products | `unique_conversation_id` | Products are mentioned in specific agent conversations |
| Update dashboard events | `unique_conversation_id` | Events are per agent interaction |
| Store Lyzr session | `unique_conversation_id` | Each agent needs isolated context |

---

## Files Modified

### 1. `app/routes/whatsapp.py`
**Lines 389-399:** Fixed product tracking to use `trace_id_for_tracking`  
**Lines 418-430:** Fixed feedback placeholder to use `trace_id_for_feedback`

### 2. `app/routes/chat.py`
**Lines 350-360:** Fixed product tracking to use `trace_id_for_tracking`

---

## How to Verify the Fix

### Test 1: First Agent Selection
```
1. Open WhatsApp chat
2. Enter agent code (R45)
3. Select option 1 (Product Recommendation)
4. Ask a question
5. Check database: Should see 1 trace with unique sessionId
```

### Test 2: Agent Switch
```
1. From active Product Recommendation conversation
2. Type "menu"
3. Select option 2 (Sales Pitch)
4. Ask a question
5. Check database: Should see 2 traces with DIFFERENT sessionIds
```

### Database Verification
```javascript
// MongoDB query
db.feedback.find({agentCode: "R45"}).sort({createdAt: -1})

// Expected result:
[
  {
    sessionId: "xyz789-unique-id-2",  // Different ID
    agentType: "sales_pitch",
    llmCalls: 5,
    totalTokens: 1500
  },
  {
    sessionId: "abc123-unique-id-1",  // Different ID
    agentType: "product_recommendation",
    llmCalls: 10,
    totalTokens: 3000  
  }
]
```

### Log Verification
After the fix, you should see logs like:
```
🔒 Use trace_session_id for product tracking to link to correct trace
   Trace Session ID for tracking: 550e8400-e29...
   
📝 Queuing feedback placeholder (Background)
   Using Trace Session ID: 550e8400-e29...
```

---

## Prevention

To prevent this issue in the future:

1. **Always use `unique_conversation_id`** when creating or updating feedback/trace records
2. **Use `session_id` only** for chat message storage (which spans the entire WhatsApp conversation)
3. **Add logging** to show which session ID is being used for each operation
4. **Test agent switching** as part of QA before deployment

---

## Impact After Fix

✅ **Each agent interaction gets its own trace**  
✅ **Switching agents creates new trace, doesn't update existing one**  
✅ **Product mentions tracked per agent conversation**  
✅ **Accurate LLM call and token counts per trace**  
✅ **Dashboard shows all traces, not just the most recent**  
✅ **Conversation history preserved for each agent**

---

## Date
Fixed: 2026-01-10  
Files Modified: 2 (whatsapp.py, chat.py)  
Lines Changed: ~20 lines  
Severity: Critical (P0) - Core functionality broken  
