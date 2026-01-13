"""
Enhanced Authentication routes with admin/user roles, 2FA, and WhatsApp password reset
"""
from fastapi import APIRouter, HTTPException, Path, Depends, Header, BackgroundTasks, Response, Cookie
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config.database import get_database, is_mongodb_ready
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from app.config.logging_config import get_logger
from app.models.models import (
    SignUpRequest, SignInRequest, VerifyRequest, 
    ChangePasswordRequest, ProfileUpdateRequest, AuthResponse, UserProfileResponse,
    TwoFactorRequest, UpdateAdminAccessRequest,
    PasswordResetRequest, PasswordResetConfirmRequest
)
from datetime import datetime, timedelta
from bson import ObjectId
import bcrypt
import secrets
import string
import jwt
import os
import hashlib
import hmac
from typing import Optional
from app.services.twilio_service import TwilioService

router = APIRouter()
logger = get_logger(__name__)
security = HTTPBearer()

# JWT Configuration
# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    # 🔒 SECURITY: Fail fast if no secret is provided
    logger.error("❌ JWT_SECRET not found in environment variables!")
    raise ValueError("FATAL: JWT_SECRET environment variable is not set. Please add it to your .env file.")
JWT_ALGORITHM = "HS256"
# Short-lived access token for security (15 mins)
ACCESS_TOKEN_EXPIRE_MINUTES = 15
# Long-lived refresh token (7 days)
REFRESH_TOKEN_EXPIRE_DAYS = 7

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    salt = bcrypt.gensalt(rounds=10)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def hash_2fa_code(code: str) -> str:
    """
    Hash 2FA code using HMAC-SHA256
    Even though codes are short-lived, hashing prevents DB leaks from exposing live OTPs
    """
    secret = JWT_SECRET
    return hmac.new(
        secret.encode('utf-8'),
        code.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def verify_2fa_code(input_code: str, stored_hash: str) -> bool:
    """Verify 2FA code against stored hash"""
    computed_hash = hash_2fa_code(input_code)
    return hmac.compare_digest(computed_hash, stored_hash)

def create_refresh_token() -> tuple[str, str]:
    """
    Generate a secure random refresh token and its hash.
    Returns: (plain_token, hashed_token)
    """
    token = secrets.token_urlsafe(64)
    # Hash the token before storing in DB
    hashed = hashlib.sha256(token.encode()).hexdigest()
    return token, hashed

def generate_jwt_token(user_data: dict) -> str:
    """Generate JWT token for authenticated user"""
    payload = {
        "email": user_data["email"],
        "isAdmin": user_data.get("isAdmin", False),
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.utcnow(),
        "type": "access"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token: str) -> Optional[dict]:
    """Verify and decode JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Dependency to get current authenticated user"""
    token = credentials.credentials
    payload = verify_jwt_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    db = get_database()
    user = db.login_details.find_one({"email": payload["email"]})
    
    if not user or not user.get("isActive", True):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    
    return user

async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency to require admin access"""
    if not current_user.get("isAdmin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

def generate_strong_password(length: int = 12) -> str:
    """Generate a strong random password"""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(characters) for _ in range(length))
    # Ensure at least one uppercase, lowercase, digit, and special char
    if not any(c.isupper() for c in password):
        password = password[0].upper() + password[1:]
    if not any(c.islower() for c in password):
        password = password[0].lower() + password[1:]
    if not any(c.isdigit() for c in password):
        password = password[:-1] + '1'
    if not any(c in "!@#$%^&*" for c in password):
        password = password[:-1] + '!'
    return password

def user_to_response(doc: dict) -> dict:
    """Convert user document to response format"""
    return {
        "_id": str(doc["_id"]),
        "email": doc.get("email"),
        "firstName": doc.get("firstName"),
        "lastName": doc.get("lastName"),
        "phone": doc.get("phone", ""),
        "bio": doc.get("bio", ""),
        "isAdmin": doc.get("isAdmin", False),
        "isActive": doc.get("isActive", True),
        "twoFactorEnabled": doc.get("twoFactorEnabled", False),
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
        "lastLogin": doc.get("lastLogin")
    }

@router.post("/signup", status_code=201)
def signup(request: SignUpRequest):
    """Sign up a new user"""
    try:
        if not request.email or not request.password or not request.firstName or not request.lastName:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Email, password, first name, and last name are required"}
            )
        
        db = get_database()
        
        # Check if user already exists
        existing_user = db.login_details.find_one({"email": request.email.lower()})
        if existing_user:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "User with this email already exists"}
            )
        
        # Create new user (non-admin by default)
        user_doc = {
            "email": request.email.lower(),
            "password": hash_password(request.password),
            "firstName": request.firstName,
            "lastName": request.lastName,
            "phone": request.phone or "",
            "bio": request.bio or "",
            "isAdmin": False,
            "isActive": True,
            "twoFactorEnabled": False,
            "createdAt": datetime.now(),
            "updatedAt": datetime.now()
        }
        
        result = db.login_details.insert_one(user_doc)
        user_doc["_id"] = result.inserted_id
        
        logger.info(f"✅ New user registered: {request.email}")
        
        user_data = user_to_response(user_doc)
        token = generate_jwt_token(user_data)
        return {
            "success": True,
            "message": "User registered successfully",
            "user": user_data,
            "token": token
        }
    except Exception as error:
        logger.error(f"❌ Error in signup: {error}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error registering user", "error": str(error)}
        )

@router.post("/signin")
async def signin(response: Response, request: SignInRequest, background_tasks: BackgroundTasks = BackgroundTasks()):
    """Sign in a user"""
    try:
        if not request.email or not request.password:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Email and password are required"}
            )
        
        # 🔒 PRODUCTION FIX: Check MongoDB readiness before any DB operations
        if not is_mongodb_ready():
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "code": "SYSTEM_WARMING_UP",
                    "message": "System is starting up. Please try again in a few seconds.",
                    "retryAfter": 10
                }
            )
        
        # Safely get database with connection error handling
        try:
            db = get_database()
        except (ServerSelectionTimeoutError, ConnectionFailure) as db_error:
            logger.error(f"❌ Database connection error during signin: {db_error}")
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "code": "DATABASE_CONNECTION_LOST",
                    "message": "Database temporarily unavailable. Please retry.",
                    "retryAfter": 10
                }
            )
        user = db.login_details.find_one({"email": request.email.lower()})
        
        if not user:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid email or password"}
            )
        
        # Check if user is active
        if not user.get("isActive", True):
            return JSONResponse(
                status_code=403,
                content={"success": False, "message": "Account is deactivated"}
            )
        
        # Verify password
        if not verify_password(request.password, user["password"]):
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid email or password"}
            )
        
        # 🔒 ADMIN-ONLY ACCESS: Check if user is admin before allowing login
        if not user.get("isAdmin", False):
            logger.warning(f"⚠️ Non-admin user attempted login: {request.email}")
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "code": "ADMIN_ACCESS_REQUIRED",
                    "message": "Access restricted to administrators only. Please contact an admin to grant you access."
                }
            )
        
        # Check if 2FA is enabled
        if user.get("twoFactorEnabled", False):
            # Generate 2FA code
            two_factor_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
            
            # 🔴 SECURITY: Store hashed code, not plain text
            hashed_code = hash_2fa_code(two_factor_code)
            
            db.login_details.update_one(
                {"_id": user["_id"]},
                {"$set": {
                    "twoFactorCode": hashed_code,  # Store hash
                    "twoFactorCodeExpiry": datetime.now() + timedelta(minutes=10)
                }}
            )
            
            # 🔒 ENTERPRISE: Trigger proactive dashboard and stats warmup
            from app.routes.dashboard import trigger_dashboard_warmup
            from app.routes.agents_stats import trigger_agents_stats_warmup
            from app.services.rag_service import trigger_rag_warmup
            background_tasks.add_task(trigger_dashboard_warmup, 7)
            background_tasks.add_task(trigger_agents_stats_warmup)
            background_tasks.add_task(trigger_rag_warmup)
            
            # Send 2FA code via WhatsApp if phone exists (send plain code, not hashed)
            if user.get("phone"):
                twilio_service = TwilioService()
                message = f"Your 2FA code is: {two_factor_code}. Valid for 10 minutes."
                await twilio_service.send_whatsapp_message(user["phone"], message)
            
            return {
                "success": True,
                "message": "Two-factor authentication required",
                "requires2FA": True,
                "email": user["email"]
            }
        
        # 🔒 ENTERPRISE: Trigger proactive dashboard and stats warmup
        from app.routes.dashboard import trigger_dashboard_warmup
        from app.routes.agents_stats import trigger_agents_stats_warmup
        from app.services.rag_service import trigger_rag_warmup
        background_tasks.add_task(trigger_dashboard_warmup, 7)
        background_tasks.add_task(trigger_agents_stats_warmup)
        background_tasks.add_task(trigger_rag_warmup)
        
        # 🔒 ADMIN-ONLY ACCESS: Check if user is admin before completing login (non-2FA path)
        if not user.get("isAdmin", False):
            logger.warning(f"⚠️ Non-admin user attempted login (no 2FA): {request.email}")
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "code": "ADMIN_ACCESS_REQUIRED",
                    "message": "Access restricted to administrators only. Please contact an admin to grant you access."
                }
            )
        
        # Update last login
        db.login_details.update_one(
            {"_id": user["_id"]},
            {"$set": {"lastLogin": datetime.now()}}
        )
        user["lastLogin"] = datetime.now()
        
        logger.info(f"✅ User signed in: {request.email}")
        
        # 🔒 PERFORMANCE: Proactive Dashboard Warmup
        if background_tasks:
            from app.routes.dashboard import trigger_dashboard_warmup
            background_tasks.add_task(trigger_dashboard_warmup, 7)
        
        user_data = user_to_response(user)
        token = generate_jwt_token(user_data)
        
        # PROPOSED: Refresh Token Logic
        plain_refresh, hashed_refresh = create_refresh_token()
        refresh_expiry = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        # Store hash in DB
        db.login_details.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "refreshToken": hashed_refresh,
                "refreshTokenExpiry": refresh_expiry
            }}
        )
        
        # Set HttpOnly Cookie
        response.set_cookie(
            key="refresh_token",
            value=plain_refresh,
            httponly=True,
            secure=True, # Set to False in dev if needed, but True for prod
            samesite="strict",
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )
        
        return {
            "success": True,
            "message": "Sign in successful",
            "user": user_data,
            "token": token
        }
    except Exception as error:
        logger.error(f"❌ Error in signin: {error}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error signing in", "error": str(error)}
        )

@router.post("/verify")
def verify_user(request: VerifyRequest):
    """Verify if user exists"""
    try:
        if not request.email:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Email is required"}
            )
        
        db = get_database()
        user = db.login_details.find_one({"email": request.email.lower()})
        
        if not user:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "User not found"}
            )
        
        user_data = user_to_response(user)
        return {
            "success": True,
            "user": user_data
        }
    except Exception as error:
        logger.error(f"❌ Error verifying user: {error}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error verifying user", "error": str(error)}
        )

@router.get("/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    """Get current user profile (uses authenticated user from token)"""
    try:
        user_data = user_to_response(current_user)
        logger.info(f"✅ Profile fetched for: {current_user.get('email')}")
        return {
            "success": True,
            "user": user_data
        }
    except Exception as error:
        logger.error(f"❌ Error fetching user profile: {error}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error fetching user profile", "error": str(error)}
        )

@router.put("/profile")
async def update_profile(request: ProfileUpdateRequest, current_user: dict = Depends(get_current_user)):
    """Update current user profile (uses authenticated user from token)"""
    try:
        db = get_database()
        user_email = current_user.get("email")
        
        if not user_email:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "User email not found in token"}
            )
        
        update_data = {"updatedAt": datetime.now()}
        if request.firstName is not None:
            update_data["firstName"] = request.firstName
        if request.lastName is not None:
            update_data["lastName"] = request.lastName
        if request.phone is not None:
            update_data["phone"] = request.phone
        if request.bio is not None:
            update_data["bio"] = request.bio
        
        db.login_details.update_one(
            {"_id": current_user["_id"]},
            {"$set": update_data}
        )
        
        # Get updated user
        updated_user = db.login_details.find_one({"_id": current_user["_id"]})
        user_data = user_to_response(updated_user)
        
        logger.info(f"✅ User profile updated: {user_email}")
        return {
            "success": True,
            "message": "Profile updated successfully",
            "user": user_data
        }
    except Exception as error:
        logger.error(f"❌ Error updating user profile: {error}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error updating user profile", "error": str(error)}
        )

@router.put("/change-password/{email}")
def change_password(email: str, request: ChangePasswordRequest):
    """Change user password"""
    try:
        if not request.currentPassword or not request.newPassword:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Current password and new password are required"}
            )
        
        db = get_database()
        user = db.login_details.find_one({"email": email.lower()})
        
        if not user:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "User not found"}
            )
        
        # Verify current password
        if not verify_password(request.currentPassword, user["password"]):
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Current password is incorrect"}
            )
        
        # Update password
        db.login_details.update_one(
            {"_id": user["_id"]},
            {"$set": {"password": hash_password(request.newPassword)}}
        )
        
        logger.info(f"✅ Password changed for user: {email}")
        return {
            "success": True,
            "message": "Password changed successfully"
        }
    except Exception as error:
        logger.error(f"❌ Error changing password: {error}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error changing password", "error": str(error)}
        )

@router.get("/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user info"""
    try:
        user_data = user_to_response(current_user)
        return {
            "success": True,
            "user": user_data
        }
    except Exception as error:
        logger.error(f"❌ Error fetching current user: {error}")
        raise HTTPException(status_code=500, detail="Failed to fetch user info")

@router.get("/users")
def get_all_users(current_user: dict = Depends(require_admin)):
    """Get all users from login_details collection (admin only) - excludes current admin"""
    try:
        db = get_database()
        current_user_email = current_user.get("email", "").lower()
        
        # First, sync agents from agents collection to login_details if they don't exist
        logger.info("🔄 Syncing agents to login_details...")
        try:
            agents = db.agents.find({})
            synced_count = 0
            for agent in agents:
                agent_email = agent.get("email", "").lower().strip()
                if not agent_email:
                    continue
                
                # Check if login_details entry exists
                existing_login = db.login_details.find_one({"email": agent_email})
                if not existing_login:
                    # Create login_details entry for this agent
                    agent_name = agent.get("agent_name", "").strip()
                    name_parts = agent_name.split() if agent_name else []
                    first_name = name_parts[0] if name_parts else ""
                    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
                    
                    login_doc = {
                        "email": agent_email,
                        "password": hash_password("Password@123"),
                        "firstName": first_name,
                        "lastName": last_name,
                        "phone": agent.get("phone_number", "").strip(),
                        "bio": "",
                        "isAdmin": False,
                        "isActive": True,
                        "twoFactorEnabled": False,
                        "createdAt": agent.get("createdAt", datetime.now()),
                        "updatedAt": datetime.now()
                    }
                    db.login_details.insert_one(login_doc)
                    synced_count += 1
                    logger.info(f"   ✓ Synced agent {agent_email} to login_details")
            
            if synced_count > 0:
                logger.info(f"✅ Synced {synced_count} agents to login_details")
        except Exception as sync_error:
            logger.warning(f"⚠️ Error syncing agents: {sync_error}")
        
        # Fetch all users, excluding current admin
        users = db.login_details.find({
            "email": {"$ne": current_user_email}
        }).sort("createdAt", -1)
        
        user_list = []
        for user in users:
            # Include all users, even if some fields are missing
            user_data = user_to_response(user)
            user_list.append(user_data)
        
        logger.info(f"✅ Retrieved {len(user_list)} users from login_details collection (excluding current admin: {current_user_email})")
        return {
            "success": True,
            "users": user_list
        }
    except Exception as error:
        logger.error(f"❌ Error fetching users: {error}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error fetching users", "error": str(error)}
        )

@router.put("/update-admin-access")
def update_admin_access(request: UpdateAdminAccessRequest, current_user: dict = Depends(require_admin)):
    """Update admin access for a user (admin only)"""
    try:
        db = get_database()
        user = db.login_details.find_one({"email": request.email.lower()})
        
        if not user:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "User not found"}
            )
        
        # Prevent self-demotion
        if user["email"].lower() == current_user.get("email", "").lower() and not request.isAdmin:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "You cannot revoke your own admin access"}
            )
        
        db.login_details.update_one(
            {"_id": user["_id"]},
            {"$set": {"isAdmin": request.isAdmin, "updatedAt": datetime.now()}}
        )
        
        updated_user = db.login_details.find_one({"_id": user["_id"]})
        user_data = user_to_response(updated_user)
        
        action = "granted" if request.isAdmin else "revoked"
        logger.info(f"✅ Admin access {action} for user: {request.email}")
        return {
            "success": True,
            "message": f"Admin access {action} successfully",
            "user": user_data
        }
    except Exception as error:
        logger.error(f"❌ Error updating admin access: {error}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error updating admin access", "error": str(error)}
        )
@router.delete("/users/{email}")
def delete_login_user(email: str, current_user: dict = Depends(require_admin)):
    """Delete a login user (admin only) - prevents self-deletion"""
    try:
        db = get_database()
        target_email = email.lower().strip()
        
        # Prevent self-deletion
        if target_email == current_user.get("email", "").lower():
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "You cannot delete your own login account"}
            )
        
        # Check if user exists
        user = db.login_details.find_one({"email": target_email})
        if not user:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "User not found"}
            )
        
        # Delete from login_details
        result = db.login_details.delete_one({"email": target_email})
        
        if result.deleted_count == 0:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "User not found"}
            )
        
        logger.info(f"✅ Login account manually deleted: {target_email} by admin {current_user.get('email')}")
        return {
            "success": True,
            "message": "Login user deleted successfully"
        }
    except Exception as error:
        logger.error(f"❌ Error deleting login user: {error}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error deleting login user", "error": str(error)}
        )

@router.post("/verify-2fa")
async def verify_2fa(response: Response, request: TwoFactorRequest, background_tasks: BackgroundTasks = BackgroundTasks()):
    """Verify 2FA code and complete sign-in"""
    try:
        if not request.email or not request.code:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Email and 2FA code are required"}
            )
        
        # 🔒 PRODUCTION FIX: Check MongoDB readiness before any DB operations
        if not is_mongodb_ready():
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "code": "SYSTEM_WARMING_UP",
                    "message": "System is starting up. Please try again in a few seconds.",
                    "retryAfter": 10
                }
            )
        
        # Safely get database with connection error handling
        try:
            db = get_database()
        except (ServerSelectionTimeoutError, ConnectionFailure) as db_error:
            logger.error(f"❌ Database connection error during 2FA verification: {db_error}")
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "code": "DATABASE_CONNECTION_LOST",
                    "message": "Database temporarily unavailable. Please retry.",
                    "retryAfter": 10
                }
            )
        user = db.login_details.find_one({"email": request.email.lower()})
        
        if not user:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "User not found"}
            )
        
        if not user.get("twoFactorEnabled", False):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Two-factor authentication is not enabled"}
            )
        
        stored_hash = user.get("twoFactorCode")
        code_expiry = user.get("twoFactorCodeExpiry")
        
        if not stored_hash:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No 2FA code found. Please request a new code."}
            )
        
        if code_expiry and datetime.now() > code_expiry:
            db.login_details.update_one(
                {"_id": user["_id"]},
                {"$unset": {"twoFactorCode": "", "twoFactorCodeExpiry": ""}}
            )
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "2FA code has expired. Please request a new code."}
            )
        
        # 🔴 SECURITY: Verify using hash comparison
        if not verify_2fa_code(request.code.strip(), stored_hash):
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid 2FA code"}
            )
        
        # Code valid - clear and complete sign-in
        db.login_details.update_one(
            {"_id": user["_id"]},
            {
                "$unset": {"twoFactorCode": "", "twoFactorCodeExpiry": ""},
                "$set": {"lastLogin": datetime.now()}
            }
        )
        
        # 🔒 ADMIN-ONLY ACCESS: Check if user is admin before completing login
        if not user.get("isAdmin", False):
            logger.warning(f"⚠️ Non-admin user attempted 2FA verification: {request.email}")
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "code": "ADMIN_ACCESS_REQUIRED",
                    "message": "Access restricted to administrators only. Please contact an admin to grant you access."
                }
            )
        
        logger.info(f"✅ 2FA verified successfully for: {request.email}")
        
        # 🔒 PERFORMANCE: Proactive Dashboard Warmup
        # Trigger cache calculation now so dashboard is ready by the time user lands on it
        if background_tasks:
            from app.routes.dashboard import trigger_dashboard_warmup
            background_tasks.add_task(trigger_dashboard_warmup, 7)
        
        user_data = user_to_response(user)
        token = generate_jwt_token(user_data)
        
        # Refresh Token Logic
        plain_refresh, hashed_refresh = create_refresh_token()
        refresh_expiry = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        db.login_details.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "refreshToken": hashed_refresh,
                "refreshTokenExpiry": refresh_expiry
            }}
        )
        
        response.set_cookie(
            key="refresh_token",
            value=plain_refresh,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )
        
        return {
            "success": True,
            "message": "Two-factor authentication verified successfully",
            "user": user_data,
            "token": token
        }
        
    except Exception as error:
        logger.error(f"❌ Error in verify_2fa: {error}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error verifying 2FA code", "error": str(error)}
        )

@router.post("/password-reset-request")
async def request_password_reset(request: PasswordResetRequest, background_tasks: BackgroundTasks = BackgroundTasks()):
    """Request a password reset code via WhatsApp"""
    try:
        if not request.email:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Email is required"}
            )
        
        db = get_database()
        user = db.login_details.find_one({"email": request.email.lower()})
        
        if not user:
            # security: don't reveal if user exists or not, but for this internal app it might be okay. 
            # adhering to security best practices:
            logger.info(f"ℹ️ Password reset requested for non-existent email: {request.email}")
            return JSONResponse(
                status_code=404,  # Or 200 with generic message if strict security needed
                content={"success": False, "message": "User not found"}
            )
        
        if not user.get("isActive", True):
             return JSONResponse(
                status_code=403,
                content={"success": False, "message": "Account is deactivated"}
            )

        # Generate Reset Code
        reset_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
        hashed_code = hash_2fa_code(reset_code)
        
        # Store in DB
        db.login_details.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "resetCode": hashed_code,
                "resetCodeExpiry": datetime.now() + timedelta(minutes=10)
            }}
        )
        
        # Send via WhatsApp
        if user.get("phone"):
            twilio_service = TwilioService()
            message = f"Your Password Reset Code is: {reset_code}. Valid for 10 minutes."
            await twilio_service.send_whatsapp_message(user["phone"], message)
            
            logger.info(f"✅ Password reset code sent to: {request.email}")
            return {
                "success": True,
                "message": "Password reset code sent to your registered WhatsApp number"
            }
        else:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No phone number associated with this account. Contact admin."}
            )

    except Exception as error:
        logger.error(f"❌ Error requesting password reset: {error}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error processing password reset", "error": str(error)}
        )

@router.post("/password-reset-confirm")
def confirm_password_reset(request: PasswordResetConfirmRequest):
    """Confirm password reset with code"""
    try:
        if not request.email or not request.code or not request.newPassword:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Email, code, and new password are required"}
            )
            
        db = get_database()
        user = db.login_details.find_one({"email": request.email.lower()})
        
        if not user:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "User not found"}
            )
            
        stored_hash = user.get("resetCode")
        code_expiry = user.get("resetCodeExpiry")
        
        if not stored_hash:
             return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No reset request found. Please request a new code."}
            )
            
        if code_expiry and datetime.now() > code_expiry:
            db.login_details.update_one(
                {"_id": user["_id"]},
                {"$unset": {"resetCode": "", "resetCodeExpiry": ""}}
            )
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Reset code has expired. Please request a new code."}
            )
            
        # Verify Code
        if not verify_2fa_code(request.code.strip(), stored_hash):
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid reset code"}
            )
            
        # Update Password
        db.login_details.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "password": hash_password(request.newPassword),
                    "updatedAt": datetime.now()
                },
                "$unset": {"resetCode": "", "resetCodeExpiry": ""}
            }
        )
        
        logger.info(f"✅ Password reset successfully for: {request.email}")
        return {
            "success": True,
            "message": "Password reset successfully. You can now login with your new password."
        }

    except Exception as error:
        logger.error(f"❌ Error confirming password reset: {error}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error resetting password", "error": str(error)}
        )

@router.post("/refresh")
async def refresh_token(response: Response, refresh_token: str = Cookie(None)):
    """Refresh access token using HttpOnly cookie"""
    if not refresh_token:
        # Check header just in case (though we prefer cookie)
        raise HTTPException(status_code=401, detail="Refresh token missing")
        
    try:
        db = get_database()
        hashed_input = hashlib.sha256(refresh_token.encode()).hexdigest()
        
        user = db.login_details.find_one({
            "refreshToken": hashed_input
        })
        
        if not user:
            # Token might be valid format but revoked or not found
            response.delete_cookie("refresh_token")
            raise HTTPException(status_code=401, detail="Invalid refresh token")
            
        # Check expiry
        expiry = user.get("refreshTokenExpiry")
        if not expiry or datetime.utcnow() > expiry:
             response.delete_cookie("refresh_token")
             raise HTTPException(status_code=401, detail="Refresh token expired")
             
        # Issue new Access Token
        user_data = user_to_response(user)
        new_access_token = generate_jwt_token(user_data)
        
        # Optional: Rotate Refresh Token (Sliding Window)
        new_plain_refresh, new_hashed_refresh = create_refresh_token()
        new_expiry = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        db.login_details.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "refreshToken": new_hashed_refresh,
                "refreshTokenExpiry": new_expiry
            }}
        )
        
        response.set_cookie(
            key="refresh_token",
            value=new_plain_refresh,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )
        
        return {
            "success": True,
            "token": new_access_token,
            "user": user_data
        }
        
    except Exception as e:
        logger.error(f"❌ Error refreshing token: {e}")
        raise HTTPException(status_code=401, detail="Token refresh failed")

@router.post("/logout")
def logout(response: Response, refresh_token: str = Cookie(None)):
    """Logout user and clear cookies"""
    if refresh_token:
        try:
            db = get_database()
            hashed_input = hashlib.sha256(refresh_token.encode()).hexdigest()
            # Remove refresh token from DB
            db.login_details.update_one(
                {"refreshToken": hashed_input},
                {"$unset": {"refreshToken": "", "refreshTokenExpiry": ""}}
            )
        except Exception as e:
            logger.error(f"⚠️ Error cleaning up refresh token on logout: {e}")
            
    # Always clear cookie
    response.delete_cookie("refresh_token")
    return {"success": True, "message": "Logged out successfully"}




