"""
WhatsApp Webhook Routes - Twilio Integration
Receives incoming WhatsApp messages and sends responses
"""
from fastapi import APIRouter, Form, BackgroundTasks
from app.services.bot_logic import BotLogic
from app.services.lyzr_service import LyzrService
from app.services.session_service import SessionService
from app.services.dashboard_service import DashboardService
from app.services.chat_storage import ChatStorage
from app.services.whatsapp_service import WhatsAppService
from app.services.twilio_service import TwilioService
from app.config.logging_config import get_logger
from datetime import datetime
from twilio.twiml.messaging_response import MessagingResponse

router = APIRouter()
logger = get_logger(__name__)

# Initialize services
bot_logic = BotLogic()
lyzr_service = LyzrService()
session_service = SessionService()
dashboard_service = DashboardService()
chat_storage = ChatStorage()
whatsapp_service = WhatsAppService()
twilio_service = TwilioService()


async def _process_whatsapp_message(
    MessageSid: str,
    From: str,
    To: str,
    Body: str,
    background_tasks: BackgroundTasks,
):
    """
    Core WhatsApp message processing logic
    Returns a MessagingResponse object
    """

    logger.info("=" * 70)
    logger.info(f"📱 INCOMING WHATSAPP MESSAGE")
    logger.info(f"   From: {From}")
    logger.info(f"   Message: {Body}")
    logger.info(f"   Twilio SID: {MessageSid}")
    logger.info("=" * 70)

    response = MessagingResponse()

    try:
        # Parse incoming message
        parsed_webhook = await whatsapp_service.parse_incoming_webhook(
            {"MessageSid": MessageSid, "From": From, "To": To, "Body": Body}
        )

        if not parsed_webhook:
            logger.error(f"❌ Failed to parse webhook")
            response.message("Sorry, I couldn't process your message. Please try again.")
            return response

        from_number = parsed_webhook.get("from_number")
        message_text = parsed_webhook.get("message")
        message_sid = parsed_webhook.get("message_sid")
        
        # Use a UUID-based session identifier (no phone number in the ID)
        session_id = await session_service.get_or_create_session_for_phone(from_number)
        logger.info(f"✅ Parsed webhook successfully")
        logger.info(f"   Session ID: {session_id}")
        
        # **LOG USER MESSAGE**
        logger.info("=" * 70)
        logger.info("👤 USER MESSAGE LOGGED")
        logger.info(f"   Session ID: {session_id}")
        logger.info(f"   From Number: {from_number}")
        logger.info(f"   User Input: {message_text}")
        logger.info(f"   Timestamp: {datetime.utcnow().isoformat()}")
        logger.info("=" * 70)

        # Get or create session state
        state = await session_service.get_session_state(session_id)
        logger.debug(f"📊 Current state: {state}")
        logger.info(f"📊 Session State: {state.get('state', 'unknown')}")

        # ------------------------------------------------------------------
        # Optional feedback capture BEFORE passing message to bot logic
        # This allows us to turn natural language ratings like "Very Good"
        # into Feedback documents that power the Dashboard "Recent Activity"
        # and feedback charts.
        # 
        # IMPORTANT: Only detect feedback if:
        # 1. Agent has asked for feedback (awaiting_feedback flag is set), OR
        # 2. Message is EXACTLY a feedback keyword (not just contains it)
        # This prevents "ok" in casual conversation from being treated as feedback.
        # ------------------------------------------------------------------
        try:
            message_lower = (message_text or "").strip().lower()
            
            # Strong feedback keywords - these are ONLY treated as feedback
            # when the message is exactly this or the agent asked for feedback
            exact_feedback_keywords = {
                "very satisfied",
                "satisfied",
                "very good",
                "good",
                "excellent",
                "not good",
                "bad",
                "need improvement"
            }
            
            # Check if agent has asked for feedback (awaiting_feedback flag)
            awaiting_feedback = state.get("awaiting_feedback", False)
            
            # Determine if this is a valid feedback message
            is_exact_feedback = message_lower in exact_feedback_keywords
            
            is_feedback_message = (
                state.get("state") == "agent_active"
                and state.get("agent_type") in ("product_recommendation", "sales_pitch")
                and (is_exact_feedback or awaiting_feedback)  # Must be exact match OR agent asked
                and any(keyword in message_lower for keyword in exact_feedback_keywords)  # Contains feedback word
                and state.get("username")
                and state.get("agent_code")
            )

            if is_feedback_message:
                logger.info("📝 Detected feedback-style message from user, creating Feedback entry (Background)")
                background_tasks.add_task(
                    dashboard_service.create_feedback,
                    username=state.get("username"),
                    agent_code=state.get("agent_code"),
                    agent_type=state.get("agent_type"),
                    feedback=message_text,
                    session_id=session_id,
                )
                
                # 🔒 POST-FEEDBACK FLOW: Transition to awaiting_continuation state
                # Update state to ask if user needs more help
                new_state = {
                    **state,
                    "state": "awaiting_continuation",
                    "feedback_given": True
                }
                await session_service.update_session_state(session_id, new_state)
                logger.info("🔄 Transitioned to awaiting_continuation state after feedback")
                
                # Send continuation prompt directly
                continuation_response = MessagingResponse()
                continuation_msg = "Thank you for your feedback! 🙏\n\nIs this all you need or anything else you need help with?\n\n1. Yes, continue\n2. No, I'm done"
                
                # Send via Twilio API
                await twilio_service.send_whatsapp_message(
                    to_number=from_number,
                    message_text=continuation_msg
                )
                
                # Return empty TwiML response (message already sent via API)
                return continuation_response
                
        except Exception as feedback_error:
            logger.warning(f"⚠️ Failed to queue feedback entry: {feedback_error}")

        # Process message through bot logic (pass phone number for authentication)
        logger.info(f"🤖 Processing message through bot logic...")
        result = await bot_logic.process_message(
            message=message_text, session_id=session_id, current_state=state, phone_number=from_number
        )

        logger.info(f"✅ Bot logic processed")
        logger.info(f"   Current State: {result['new_state'].get('state')}")
        logger.info(f"   Agent active: {result.get('agent_active')}")
        logger.info(f"   Response preview: {result['response'][:100] if result['response'] else 'None'}...")

        # Update session state - Critical path, keep blocking to ensure consistency for next request
        await session_service.update_session_state(session_id, result["new_state"])
        logger.debug(f"💾 Session state updated to: {result['new_state'].get('state')}")

        # Save user message to MongoDB (Background Task)
        background_tasks.add_task(
            chat_storage.save_message,
            session_id=session_id,
            role="user",
            message=message_text,
            username=result.get("username"),
            agent_code=result.get("agent_code"),
            agent_name=result.get("agent_name"),
            state=result["new_state"].get("state"),
        )
        logger.info(f"✅ User message save queued (Background)")

        # Track conversation start (Background Task)
        if (
            result["new_state"].get("state") == "code_entered"
            and result.get("username")
            and result.get("agent_code")
        ):
            logger.info(f"🆕 Conversation started - queuing dashboard event")
            background_tasks.add_task(
                dashboard_service.create_session_event,
                result.get("username"), 
                result.get("agent_code")
            )

        # Track incomplete conversations (Background Task)
        if (
            result.get("conversation_status") == "incomplete"
            and not result.get("has_feedback")
            and result.get("agent_type")
            and result.get("username")
            and result.get("agent_code")
        ):
            logger.info(f"📊 Tracking incomplete conversation (Background)")
            background_tasks.add_task(
                dashboard_service.create_incomplete_conversation_event,
                session_id=session_id,
                username=result.get("username"),
                agent_code=result.get("agent_code"),
                agent_type=result.get("agent_type")
            )

        # If agent is active, get response from Lyzr
        if result.get("agent_active"):
            logger.info(f"🚀 Agent is active - routing to Lyzr")
            logger.info(f"   Agent type: {result['agent_type']}")
            
            # Log username and code when user selects Product Recommendation or Sales Pitch
            username = result.get('username', 'N/A')
            agent_code = result.get('agent_code', 'N/A')
            
            if result.get("agent_type") in ("product_recommendation", "sales_pitch"):
                logger.info("=" * 70)
                logger.info(f"👤 USER SELECTED: {result['agent_type'].upper().replace('_', ' ')}")
                logger.info(f"   Username: {username}")
                logger.info(f"   Agent Code: {agent_code}")
                logger.info(f"   Session ID: {session_id}")
                logger.info(f"   Timestamp: {datetime.utcnow().isoformat()}")
                logger.info("=" * 70)
            
            # 🔒 CRITICAL: Create new feedback/trace entry for EVERY new Lyzr session
            # This happens when: (1) User first selects agent, OR (2) User switches agents
            if result.get("start_new_session"):
                # Get the unique conversation ID for the new trace
                trace_session_id = result["new_state"].get("unique_conversation_id") or session_id
                
                logger.info(f"🆕 NEW LYZR SESSION - Creating feedback trace")
                logger.info(f"   Agent Type: {result['agent_type']}")
                logger.info(f"   Username: {username}")
                logger.info(f"   Agent Code: {agent_code}")
                logger.info(f"   Trace Session ID: {trace_session_id[:12]}...")
                logger.info(f"   Is Agent Switch: {result.get('agent_switched', False)}")
                
                # 🔒 CRITICAL FIX: Clear old Lyzr session from memory cache
                # This ensures a fresh session is created, not reusing old context
                try:
                    from app.services.lyzr_service import clear_lyzr_session_by_key
                    agent_id_temp = await lyzr_service.get_agent_id(result["agent_type"])
                    clear_lyzr_session_by_key(trace_session_id, agent_id_temp)
                    logger.info(f"🧹 Cleared old Lyzr session from memory for new conversation")
                except Exception as clear_err:
                    logger.warning(f"⚠️ Could not clear old Lyzr session: {clear_err}")
                
                # Create feedback placeholder IMMEDIATELY (awaited, not background task)
                # This must complete before Lyzr call to ensure trace exists
                try:
                    await dashboard_service.create_feedback_placeholder(
                        username=username,
                        agent_code=agent_code,
                        agent_type=result["agent_type"],
                        session_id=trace_session_id  # Use unique conversation ID
                    )
                    logger.info(f"✅ New feedback trace created successfully")
                    logger.info(f"   Trace ID: {trace_session_id[:12]}...")
                    logger.info(f"   Agent Type: {result['agent_type']}")
                except Exception as e:
                    logger.error(f"❌ Failed to create feedback trace: {e}", exc_info=True)

            try:
                # Get agent ID based on type
                agent_id = await lyzr_service.get_agent_id(result["agent_type"])

                logger.info(f"🔗 Calling Lyzr Agent")
                logger.info(f"   Agent ID: {agent_id}")
                logger.info(f"   User: {username}")
                
                # 🔒 Use unique_conversation_id for Lyzr session if available (ensures fresh session)
                lyzr_session_id = result["new_state"].get("unique_conversation_id", session_id)
                logger.info(f"🆔 Using Lyzr Session ID: {lyzr_session_id[:12]}... (Original: {session_id[:12]}...)")
                
                # Prepare message to send to Lyzr
                # 🔒 For NEW conversations: Send "HI" as the first message to initialize the agent
                # For subsequent messages: Send the user's actual message
                if result.get("start_new_session"):
                    message_to_send = "HI"
                    logger.info(f"🆕 First message to agent - sending initialization greeting")
                    logger.info(f"   Sending: HI (to initialize Lyzr agent)")
                    logger.info(f"   Unique Conversation ID: {lyzr_session_id[:12]}...")
                else:
                    message_to_send = message_text
                    logger.info(f"📤 Subsequent message - sending user input")
                    logger.info(f"   Message: {message_text[:100]}...")

                # Call Agent - This remains awaited as we need the response text for the user
                # 🔒 LATENCY FIX: Reduced poll_interval from 2000ms to 1000ms
                agent_response = await lyzr_service.optimized_call_agent(
                    agent_id=agent_id,
                    message=message_to_send,
                    session_id=lyzr_session_id,
                    user_id=username if username != 'N/A' else None,
                    username=username if username != 'N/A' else None,
                    agent_code=result.get('agent_code'),
                    poll_interval=1000,  # 🔒 REDUCED: Was 2000ms, now 1000ms for faster response
                    max_attempts=90,     # 🔒 INCREASED: To maintain same total timeout (90s)
                )

                logger.info(f"✅ Lyzr Agent response received")
                logger.info(f"   Type: {type(agent_response)}")

                # Handle response (could be dict, list, or string)
                if isinstance(agent_response, dict):
                    # Check if this is an error response
                    if agent_response.get("status") == "failed" or "error" in agent_response:
                        response_text = agent_response.get("user_message") or agent_response.get("error", "An error occurred. Please try again.")
                        logger.error(f"❌ Lyzr Agent Error Response: {agent_response.get('error')}")
                    else:
                        # Normal response dict - convert to string
                        response_text = str(agent_response)
                elif isinstance(agent_response, list):
                    response_text = str(agent_response)
                else:
                    response_text = str(agent_response)

                logger.info(f"   Response length: {len(response_text)} chars")
                result["response"] = response_text
                logger.info(f"✅ Result response updated with Lyzr agent response")
                
                # **LOG AGENT MESSAGE**
                logger.info("=" * 70)
                logger.info("🤖 AGENT MESSAGE LOGGED")
                logger.info(f"   Session ID: {session_id}")
                logger.info(f"   Agent Response: {response_text[:100]}...")
                logger.info("=" * 70)

                # Save agent response to MongoDB (Background Task)
                try:
                    # 🔒 FIX: Use unique_conversation_id for trace storage
                    # This ensures each agent conversation gets its own trace
                    trace_session_id = result["new_state"].get("unique_conversation_id") or session_id
                    
                    from app.services.lyzr_service import get_lyzr_session_id
                    lyzr_session_id_for_storage = get_lyzr_session_id(trace_session_id, result["agent_type"])
                    estimated_tokens = len(response_text) // 4
                    llm_calls_count = 1

                    background_tasks.add_task(
                        chat_storage.save_message,
                        session_id=trace_session_id,  # 🔒 FIX: Use unique conversation ID, NOT WhatsApp session
                        role="agent",
                        message=response_text,
                        username=result.get("username"),
                        agent_code=result.get("agent_code"),
                        agent_name=result.get("agent_name"),
                        agent_type=result["agent_type"],
                        state=result["new_state"].get("state"),
                        lyzr_session_id=lyzr_session_id_for_storage,
                        total_tokens=estimated_tokens,
                        llm_calls=llm_calls_count
                    )
                    
                    logger.info(f"✅ Agent response save queued")
                    logger.info(f"   Trace Session ID: {trace_session_id[:12]}...")
                    
                    # Notify dashboard of activity (Background Task)
                    if result.get("agent_type"):
                        background_tasks.add_task(
                            dashboard_service.notify_activity_update,
                            result["agent_type"], 
                            llm_calls_count
                        )
                        
                except Exception as e:
                    logger.warning(f"⚠️ Could not queue agent response save: {e}")

                # Create dashboard event for agent completion (Background Task)
                try:
                    # 🔒 Use unique_conversation_id for dashboard/trace events
                    # This ensures each agent interaction gets its own trace
                    trace_session_id = result["new_state"].get("unique_conversation_id") or session_id
                    
                    if result["agent_type"] == "product_recommendation":
                        logger.info(f"📊 Queuing dashboard event: product_recommendation")
                        logger.info(f"   Using Trace Session ID: {trace_session_id[:12]}...")
                        background_tasks.add_task(dashboard_service.create_recommendation_event, trace_session_id)
                    elif result["agent_type"] == "sales_pitch":
                        logger.info(f"📊 Queuing dashboard event: sales_pitch")
                        logger.info(f"   Using Trace Session ID: {trace_session_id[:12]}...")
                        background_tasks.add_task(dashboard_service.create_sales_pitch_event, trace_session_id)
                except Exception as e:
                    logger.warning(f"⚠️ Could not queue dashboard event: {e}")
                
                # 🔒 Track products mentioned in agent response (CRITICAL - must run for every response)
                try:
                    from app.services.product_service import get_product_service
                    product_service = get_product_service()
                    
                    logger.info(f"📦 Starting product tracking for response...")
                    logger.info(f"   Response text length: {len(response_text)} chars")
                    logger.info(f"   Response preview: {response_text[:150]}...")
                    
                    # 🔒 Use trace_session_id for product tracking to link to correct trace
                    trace_id_for_tracking = result["new_state"].get("unique_conversation_id") or session_id
                    
                    # Run product tracking - use background task for non-blocking
                    async def track_products_async():
                        try:
                            await product_service.track_products_in_response(
                                response_text, trace_id_for_tracking, result["agent_type"]
                            )
                        except Exception as e:
                            logger.error(f"❌ Background product tracking error: {e}")
                    
                    background_tasks.add_task(track_products_async)
                    logger.info(f"📦 Product tracking queued (background)")
                except Exception as pe:
                    logger.error(f"❌ Product tracking setup error: {pe}", exc_info=True)

                # Feedback placeholder (Background Task)
                try:
                    lower_response = response_text.lower()
                    feedback_prompt_keywords = [
                        "how was this sales pitch",
                        "how was this recommendation",
                        "how was this product recommendation",
                        "how was this interaction",
                        "please rate this",
                        "how was the sales pitch",
                    ]
                    asked_for_feedback = any(
                        keyword in lower_response for keyword in feedback_prompt_keywords
                    )

                    if asked_for_feedback and result.get("username") and result.get("agent_code"):
                        # 🔒 CRITICAL FIX: Use trace_session_id instead of session_id
                        # This ensures each conversation gets its own trace
                        trace_id_for_feedback = result["new_state"].get("unique_conversation_id") or session_id
                        logger.info("📝 Queuing feedback placeholder (Background)")
                        logger.info(f"   Using Trace Session ID: {trace_id_for_feedback[:12]}...")
                        background_tasks.add_task(
                            dashboard_service.create_feedback_placeholder,
                            username=result.get("username"),
                            agent_code=result.get("agent_code"),
                            agent_type=result.get("agent_type"),
                            session_id=trace_id_for_feedback,  # 🔒 Use unique conversation ID
                        )
                except Exception as placeholder_error:
                    logger.warning(f"⚠️ Failed to queue placeholder feedback: {placeholder_error}")

            except Exception as e:
                logger.error(f"❌ Error calling Lyzr agent: {e}", exc_info=True)
                result["response"] = (
                    "Sorry, I encountered an error. Please try again later."
                )

        else:
            # Save bot response to MongoDB (Background Task)
            try:
                background_tasks.add_task(
                    chat_storage.save_message,
                    session_id=session_id,
                    role="bot",
                    message=result["response"],
                    username=result.get("username"),
                    agent_code=result.get("agent_code"),
                    agent_name=result.get("agent_name"),
                    state=result["new_state"].get("state"),
                )
                logger.info(f"✅ Bot response save queued (Background)")
            except Exception as e:
                logger.warning(f"⚠️ Could not queue bot response save: {e}")
            
            # **LOG BOT MESSAGE**
            logger.info("=" * 70)
            logger.info("🤖 BOT MESSAGE LOGGED")
            logger.info(f"   Session ID: {session_id}")
            logger.info(f"   Bot Response: {result['response']}")
            logger.info("=" * 70)

        # Update session metadata (Background Task)
        if result.get("username"):
            metadata = {
                "username": result.get("username"),
                "agent_code": result.get("agent_code"),
                "agent_type": result.get("agent_type"),
                "state": result["new_state"].get("state"),
                "phone_number": from_number,
            }
            background_tasks.add_task(session_service.set_session_metadata, session_id, metadata)
            logger.debug(f"💾 Session metadata update queued")

        # Send response via WhatsApp
        logger.info("=" * 70)
        logger.info(f"📤 OUTGOING WHATSAPP RESPONSE")
        logger.info(f"   To: {from_number}")
        logger.info(f"   Message length: {len(result['response'])} chars")
        logger.info("=" * 70)

        # Split long messages (Twilio WhatsApp has 1600 char limit for concatenated messages)
        response_text = result["response"]
        max_length = 1600
        
        # Only send if there's actual content
        messages_to_send = []
        
        if response_text and len(response_text.strip()) > 0:
            if len(response_text) > max_length:
                logger.info(f"📝 Response is long ({len(response_text)} chars), splitting into multiple messages...")
                # Split into chunks of max_length, preferably at sentence boundaries
                current_pos = 0
                while current_pos < len(response_text):
                    # Find a good breaking point (period, newline, or just at max_length)
                    end_pos = min(current_pos + max_length, len(response_text))
                    if end_pos < len(response_text):
                        # Try to find last period before end_pos
                        last_period = response_text.rfind('.', current_pos, end_pos)
                        if last_period > current_pos:
                            end_pos = last_period + 1
                        else:
                            # Try to find last newline
                            last_newline = response_text.rfind('\n', current_pos, end_pos)
                            if last_newline > current_pos:
                                end_pos = last_newline + 1
                    
                    chunk = response_text[current_pos:end_pos].strip()
                    if chunk:  # Only add non-empty chunks
                        messages_to_send.append(chunk)
                    current_pos = end_pos
                
                logger.info(f"   Split into {len(messages_to_send)} messages")
                for i, chunk in enumerate(messages_to_send, 1):
                    logger.debug(f"   Chunk {i}: {len(chunk)} chars")
            else:
                # Single message
                logger.info(f"📤 Single message: {len(response_text)} chars")
                messages_to_send.append(response_text)
        else:
            logger.warning(f"⚠️ Empty response, not sending any message")
        
        # Send messages via Twilio API instead of TwiML response
        if messages_to_send:
            logger.info("=" * 70)
            logger.info(f"📤 SENDING {len(messages_to_send)} MESSAGE(S) VIA TWILIO API")
            logger.info(f"   To: {from_number}")
            logger.info("=" * 70)
            
            sent_count = await twilio_service.send_whatsapp_messages(
                to_number=from_number,
                messages=messages_to_send
            )
            
            logger.info(f"✅ Sent {sent_count}/{len(messages_to_send)} messages via Twilio API")
        
        # Return a simple 200 OK response to acknowledge webhook receipt
        response.message("")  # Empty response to Twilio webhook
        return response

    except Exception as e:
        logger.error("=" * 70)
        logger.error(f"❌ ERROR in WhatsApp webhook")
        logger.error(f"   Error: {str(e)}")
        logger.error(f"   From: {From}")
        logger.error("=" * 70, exc_info=True)

        # Still try to send error message via Twilio API
        try:
            await twilio_service.send_whatsapp_message(
                to_number=From,
                message_text="Sorry, I encountered an unexpected error. Please try again later."
            )
        except Exception as api_error:
            logger.error(f"❌ Could not send error message via API: {api_error}")

        response.message("")  # Empty response to Twilio webhook
        return response


# Actual route endpoints (these wrap the core logic and handle TwiML conversion)

@router.post("/whatsapp/webhook")
async def whatsapp_webhook_endpoint(
    background_tasks: BackgroundTasks,
    MessageSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    Body: str = Form(...),
):
    """
    Twilio WhatsApp webhook endpoint
    Receives incoming WhatsApp messages and sends responses
    Available at: POST /api/whatsapp/webhook
    """
    from fastapi.responses import Response
    
    logger.info("📧 Webhook received at /whatsapp/webhook path")
    twiml_response = await _process_whatsapp_message(
        MessageSid=MessageSid, 
        From=From, 
        To=To, 
        Body=Body,
        background_tasks=background_tasks
    )
    twiml_str = str(twiml_response)
    
    logger.info(f"✅ Converting MessagingResponse to TwiML XML")
    logger.debug(f"   Length: {len(twiml_str)} chars")
    
    return Response(content=twiml_str, media_type="application/xml")


@router.post("/webhook")
async def webhook_root(
    background_tasks: BackgroundTasks,
    MessageSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    Body: str = Form(...),
):
    """
    Root webhook endpoint for Twilio WhatsApp
    Compatibility route for ngrok webhook pointing to /webhook
    Available at: POST /api/webhook
    """
    from fastapi.responses import Response
    
    logger.info("📧 Webhook received at root /webhook path")
    twiml_response = await _process_whatsapp_message(
        MessageSid=MessageSid, 
        From=From, 
        To=To, 
        Body=Body,
        background_tasks=background_tasks
    )
    twiml_str = str(twiml_response)
    
    logger.info(f"✅ Converting MessagingResponse to TwiML XML")
    logger.debug(f"   Length: {len(twiml_str)} chars")
    
    return Response(content=twiml_str, media_type="application/xml")


@router.get("/whatsapp/health")
async def whatsapp_health():
    """Health check for WhatsApp webhook"""
    logger.debug("WhatsApp health check requested")
    return {
        "status": "ok",
        "service": "whatsapp-webhook",
        "twilio_configured": whatsapp_service.client is not None,
    }
