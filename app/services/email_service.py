"""
Email service for sending emails (2FA, password reset, notifications)
"""
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from app.config.logging_config import get_logger
from datetime import datetime

load_dotenv()

logger = get_logger(__name__)

class EmailService:
    """Service for sending emails via SMTP"""
    
    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_username = os.getenv("SMTP_USERNAME", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = os.getenv("FROM_EMAIL", self.smtp_username)
        self.from_name = os.getenv("FROM_NAME", "Star Health Bot")
    
    def send_email(self, to_email: str, subject: str, html_body: str, text_body: str = None) -> bool:
        """Send an email via SMTP"""
        if not self.smtp_username or not self.smtp_password:
            logger.error("❌ SMTP credentials not configured")
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email
            
            if text_body:
                text_part = MIMEText(text_body, 'plain')
                msg.attach(text_part)
            
            html_part = MIMEText(html_body, 'html')
            msg.attach(html_part)
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"✅ Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error sending email to {to_email}: {e}", exc_info=True)
            return False
    
    def send_2fa_code(self, to_email: str, code: str, user_name: str = None) -> bool:
        """Send 2FA code via email"""
        subject = "Your Two-Factor Authentication Code - Star Health Bot"
        
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #0066cc; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background-color: #f9f9f9; }}
                .code {{ font-size: 32px; font-weight: bold; color: #0066cc; text-align: center; padding: 20px; background-color: white; border: 2px dashed #0066cc; margin: 20px 0; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
                .warning {{ color: #d32f2f; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Star Health Bot</h1>
                    <h2>Two-Factor Authentication</h2>
                </div>
                <div class="content">
                    <p>Hello {user_name or 'User'},</p>
                    <p>You have requested to sign in to your account. Please use the following code to complete your login:</p>
                    <div class="code">{code}</div>
                    <p class="warning">⚠️ This code will expire in 10 minutes.</p>
                    <p>If you did not request this code, please ignore this email or contact support immediately.</p>
                </div>
                <div class="footer">
                    <p>This is an automated message. Please do not reply to this email.</p>
                    <p>&copy; {datetime.now().year} Star Health. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
        Star Health Bot - Two-Factor Authentication
        
        Hello {user_name or 'User'},
        
        You have requested to sign in to your account. Please use the following code to complete your login:
        
        {code}
        
        ⚠️ This code will expire in 10 minutes.
        
        If you did not request this code, please ignore this email or contact support immediately.
        """
        
        return self.send_email(to_email, subject, html_body, text_body)



