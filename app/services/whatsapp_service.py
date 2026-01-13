"""
Twilio WhatsApp Integration Service
Handles incoming WhatsApp messages and sends responses via Twilio
"""
from twilio.rest import Client
import os
from dotenv import load_dotenv
from app.config.logging_config import get_logger
from typing import Optional

load_dotenv()

logger = get_logger(__name__)


class WhatsAppService:
    """Service for Twilio WhatsApp integration"""

    def __init__(self):
        """Initialize Twilio client with credentials from environment"""
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.whatsapp_from = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

        # Validate configuration
        if not self.account_sid or not self.auth_token:
            logger.warning("⚠️ Twilio credentials not configured in .env")
            logger.warning("   Set: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")
            logger.warning("   WhatsApp messages will not be sent")
            self.client = None
        else:
            try:
                self.client = Client(self.account_sid, self.auth_token)
                logger.info("✅ Twilio WhatsApp service initialized")
                logger.info(f"   From: {self.whatsapp_from}")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Twilio client: {e}")
                self.client = None

    async def send_whatsapp_message(self, to_number: str, message: str) -> Optional[str]:
        """
        Send a WhatsApp message via Twilio

        Args:
            to_number: Recipient WhatsApp number (format: whatsapp:+1234567890)
            message: Message text to send

        Returns:
            Message SID if successful, None if failed
        """
        if not self.client:
            logger.error("❌ Twilio client not initialized")
            logger.error("   Cannot send WhatsApp message")
            return None

        try:
            logger.info(f"📤 Sending WhatsApp message")
            logger.info(f"   To: {to_number}")
            logger.info(f"   Message length: {len(message)} characters")
            logger.debug(f"   Message: {message[:100]}...")

            # Ensure proper WhatsApp format
            if not to_number.startswith("whatsapp:"):
                to_number = f"whatsapp:{to_number}"

            message_obj = self.client.messages.create(
                from_=self.whatsapp_from, body=message, to=to_number
            )

            logger.info(f"✅ WhatsApp message sent successfully")
            logger.info(f"   Message SID: {message_obj.sid}")
            logger.debug(f"   Status: {message_obj.status}")

            return message_obj.sid

        except Exception as e:
            logger.error(f"❌ Failed to send WhatsApp message: {e}", exc_info=True)
            return None

    async def parse_incoming_webhook(self, data: dict) -> dict:
        """
        Parse incoming WhatsApp webhook from Twilio

        Expected format from Twilio:
        {
            'MessageSid': 'SM...',
            'From': 'whatsapp:+1234567890',
            'To': 'whatsapp:+14155238886',
            'Body': 'message text'
        }

        Returns:
            {
                'from_number': '+1234567890',
                'message': 'message text',
                'message_sid': 'SM...'
            }
        """
        try:
            logger.info(f"📥 Parsing incoming WhatsApp webhook")

            from_number = data.get("From", "").replace("whatsapp:", "")
            message_text = data.get("Body", "").strip()
            message_sid = data.get("MessageSid", "")

            logger.info(f"   From: {from_number}")
            logger.info(f"   Message: {message_text}")
            logger.debug(f"   SID: {message_sid}")

            if not from_number or not message_text:
                logger.error(f"❌ Invalid webhook data")
                return {}

            return {
                "from_number": from_number,
                "message": message_text,
                "message_sid": message_sid,
            }

        except Exception as e:
            logger.error(f"❌ Error parsing webhook: {e}", exc_info=True)
            return {}
