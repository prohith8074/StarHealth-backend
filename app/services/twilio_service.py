"""
Twilio WhatsApp REST API Service
Sends messages directly to WhatsApp users via Twilio API
"""
import os
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from app.config.logging_config import get_logger

load_dotenv()

logger = get_logger(__name__)


class TwilioService:
    """Service for sending WhatsApp messages via Twilio REST API"""
    
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.whatsapp_from = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # Default sandbox
        
        # Validate configuration
        if not self.account_sid:
            logger.warning("⚠️ TWILIO_ACCOUNT_SID not set in environment variables")
        if not self.auth_token:
            logger.warning("⚠️ TWILIO_AUTH_TOKEN not set in environment variables")
        
        # Check if credentials are present
        if not self.account_sid or not self.auth_token:
            logger.error("❌ Twilio credentials missing - cannot initialize client")
            logger.error("   Please set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env file")
            self.client = None
            return
        
        # Initialize Twilio client
        try:
            self.client = Client(self.account_sid, self.auth_token)
            
            # Validate credentials by fetching account info
            try:
                account = self.client.api.accounts(self.account_sid).fetch()
                logger.info("✅ TwilioService initialized and credentials validated")
                logger.info(f"   Account SID: {self.account_sid[:10]}...{self.account_sid[-4:] if len(self.account_sid) > 14 else ''}")
                logger.info(f"   Account Status: {account.status}")
                logger.info(f"   Auth Token: {'***' + self.auth_token[-4:] if self.auth_token else 'Not set'}")
                logger.info(f"   WhatsApp From: {self.whatsapp_from}")
            except TwilioRestException as e:
                if e.status == 401 or e.code == 20003:
                    logger.error("=" * 70)
                    logger.error("❌ TWILIO CREDENTIALS VALIDATION FAILED")
                    logger.error("   The Account SID or Auth Token is incorrect or expired")
                    logger.error("=" * 70)
                    logger.error("   Troubleshooting steps:")
                    logger.error("   1. Check your .env file in the project root")
                    logger.error("   2. Verify TWILIO_ACCOUNT_SID starts with 'AC'")
                    logger.error("   3. Verify TWILIO_AUTH_TOKEN is the correct auth token")
                    logger.error("   4. Get fresh credentials from: https://console.twilio.com/")
                    logger.error("   5. Make sure there are no extra spaces or quotes in .env")
                    logger.error("=" * 70)
                    logger.error(f"   Current Account SID: {self.account_sid[:20]}..." if self.account_sid else "   Account SID: NOT SET")
                    logger.error("=" * 70)
                    self.client = None
                else:
                    logger.warning(f"⚠️ Could not validate credentials: {e.code} - {e.msg}")
                    logger.info("✅ TwilioService initialized (validation skipped)")
                    logger.info(f"   Account SID: {self.account_sid[:10]}...{self.account_sid[-4:] if len(self.account_sid) > 14 else ''}")
                    logger.info(f"   Auth Token: {'***' + self.auth_token[-4:] if self.auth_token else 'Not set'}")
                    logger.info(f"   WhatsApp From: {self.whatsapp_from}")
        except Exception as e:
            logger.error(f"❌ Error initializing TwilioService: {e}")
            self.client = None
    
    def _ensure_client_initialized(self) -> bool:
        """
        Ensure Twilio client is initialized, try to re-initialize if needed
        
        Returns:
            True if client is available, False otherwise
        """
        if self.client is not None:
            return True
        
        # Try to re-initialize if credentials are available
        if not self.account_sid or not self.auth_token:
            logger.error("=" * 70)
            logger.error("❌ TWILIO CLIENT NOT INITIALIZED")
            logger.error("   Missing credentials - cannot send messages")
            logger.error("=" * 70)
            logger.error("   Please check your .env file:")
            logger.error(f"   TWILIO_ACCOUNT_SID: {'SET' if self.account_sid else 'NOT SET'}")
            logger.error(f"   TWILIO_AUTH_TOKEN: {'SET' if self.auth_token else 'NOT SET'}")
            logger.error("=" * 70)
            return False
        
        # Try to initialize client
        try:
            self.client = Client(self.account_sid, self.auth_token)
            logger.info("✅ Twilio client re-initialized successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize Twilio client: {e}")
            self.client = None
            return False
    
    async def send_whatsapp_message(self, to_number: str, message_text: str) -> bool:
        """
        Send a WhatsApp message using Twilio REST API
        
        Args:
            to_number: Recipient phone number (format: whatsapp:+918328100813)
            message_text: Message content
            
        Returns:
            True if message sent successfully, False otherwise
        """
        if not self._ensure_client_initialized():
            logger.error("❌ Cannot send message - Twilio client not available")
            return False
        
        # Ensure to_number is in correct format
        if not to_number.startswith("whatsapp:"):
            if to_number.startswith("+"):
                to_number = f"whatsapp:{to_number}"
            else:
                to_number = f"whatsapp:+{to_number}"
        
        logger.info("=" * 70)
        logger.info(f"📤 SENDING WHATSAPP MESSAGE VIA TWILIO API")
        logger.info(f"   To: {to_number}")
        logger.info(f"   From: {self.whatsapp_from}")
        logger.info(f"   Message length: {len(message_text)} chars")
        logger.debug(f"   Content: {message_text[:150]}...")
        logger.info("=" * 70)
        
        try:
            message = self.client.messages.create(
                body=message_text,
                from_=self.whatsapp_from,
                to=to_number
            )
            
            logger.info("=" * 70)
            logger.info(f"✅ MESSAGE SENT SUCCESSFULLY")
            logger.info(f"   Message SID: {message.sid}")
            logger.info(f"   Status: {message.status}")
            logger.info(f"   To: {message.to}")
            logger.info("=" * 70)
            
            return True
            
        except TwilioRestException as e:
            logger.error("=" * 70)
            logger.error(f"❌ TWILIO API ERROR")
            logger.error(f"   Status Code: {e.status}")
            logger.error(f"   Error Code: {e.code}")
            logger.error(f"   Error Message: {e.msg}")
            logger.error(f"   To: {to_number}")
            
            # Handle specific error codes
            if e.status == 401 or e.code == 20003:
                logger.error("=" * 70)
                logger.error("🔐 AUTHENTICATION ERROR (Error Code 20003)")
                logger.error("   Your Twilio Account SID or Auth Token is incorrect or expired")
                logger.error("=" * 70)
                logger.error("   TROUBLESHOOTING STEPS:")
                logger.error("   1. Check your .env file in the project root directory")
                logger.error("   2. Verify TWILIO_ACCOUNT_SID starts with 'AC' (e.g., ACxxxxxxxxxxxxx)")
                logger.error("   3. Verify TWILIO_AUTH_TOKEN is the correct auth token (not the Account SID)")
                logger.error("   4. Get fresh credentials from: https://console.twilio.com/")
                logger.error("      - Go to Account > API Keys & Tokens")
                logger.error("      - Copy your Account SID and Auth Token")
                logger.error("   5. Make sure there are NO extra spaces, quotes, or newlines in .env")
                logger.error("   6. Restart the server after updating .env")
                logger.error("=" * 70)
                logger.error("   CURRENT CONFIGURATION:")
                logger.error(f"   Account SID: {self.account_sid if self.account_sid else 'NOT SET'}")
                logger.error(f"   Account SID Length: {len(self.account_sid) if self.account_sid else 0} chars (should be 34)")
                logger.error(f"   Auth Token: {'SET (' + str(len(self.auth_token)) + ' chars)' if self.auth_token else 'NOT SET'}")
                logger.error(f"   WhatsApp From: {self.whatsapp_from}")
                logger.error("=" * 70)
                logger.error("   EXAMPLE .env FORMAT:")
                logger.error("   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
                logger.error("   TWILIO_AUTH_TOKEN=your_auth_token_here")
                logger.error("   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886")
                logger.error("=" * 70)
            elif e.status == 400:
                logger.error("   Bad Request - Check message format and phone numbers")
            elif e.status == 403:
                logger.error("   Forbidden - Check account permissions and WhatsApp setup")
            elif e.status == 404:
                logger.error("   Not Found - Check Account SID and phone numbers")
            else:
                logger.error(f"   Unexpected error: {e}")
            
            logger.error("=" * 70, exc_info=True)
            return False
            
        except Exception as e:
            logger.error("=" * 70)
            logger.error(f"❌ UNEXPECTED ERROR SENDING MESSAGE")
            logger.error(f"   Error Type: {type(e).__name__}")
            logger.error(f"   Error: {str(e)}")
            logger.error(f"   To: {to_number}")
            logger.error("=" * 70, exc_info=True)
            
            return False
    
    async def send_whatsapp_messages(self, to_number: str, messages: list) -> int:
        """
        Send multiple WhatsApp messages
        
        Args:
            to_number: Recipient phone number
            messages: List of message texts
            
        Returns:
            Number of messages sent successfully
        """
        sent_count = 0
        
        for i, message_text in enumerate(messages, 1):
            logger.info(f"📤 Sending message {i}/{len(messages)}...")
            success = await self.send_whatsapp_message(to_number, message_text)
            if success:
                sent_count += 1
            else:
                logger.warning(f"⚠️ Failed to send message {i}")
        
        logger.info(f"✅ Sent {sent_count}/{len(messages)} messages")
        return sent_count
