"""
Pydantic models for request/response validation
"""
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime

# User Models
class UserCreate(BaseModel):
    username: str
    agentCode: str
    mobileNumber: Optional[str] = None

class UserResponse(BaseModel):
    _id: str
    username: str
    agentCode: str
    mobileNumber: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime

# Feedback Models
class FeedbackCreate(BaseModel):
    username: str
    agentCode: str
    agentType: str  # 'product_recommendation' or 'sales_pitch'
    feedback: str
    feedbackTamil: Optional[str] = None  # Tamil translation of feedback
    sessionId: Optional[str] = None

class FeedbackResponse(BaseModel):
    _id: str
    username: str
    agentCode: str
    agentType: str
    feedback: str
    sessionId: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime

# Knowledge Models
class KnowledgeCreate(BaseModel):
    type: str  # 'product_recommendation' or 'sales_pitch'
    content: str

class KnowledgeUpdate(BaseModel):
    type: Optional[str] = None
    content: Optional[str] = None

class KnowledgeResponse(BaseModel):
    _id: str
    type: str
    content: str
    createdAt: datetime
    updatedAt: datetime

# Agent Models
class AgentCreate(BaseModel):
    agent_code: str
    agent_name: str
    role: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None

class AgentUpdate(BaseModel):
    agent_code: Optional[str] = None
    agent_name: Optional[str] = None
    role: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None

class AgentResponse(BaseModel):
    _id: str
    agent_code: str
    agent_name: str
    role: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime

# Auth Models
class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    firstName: str
    lastName: str
    phone: Optional[str] = None
    bio: Optional[str] = None

class SignInRequest(BaseModel):
    email: EmailStr
    password: str

class VerifyRequest(BaseModel):
    email: EmailStr

class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str

class ProfileUpdateRequest(BaseModel):
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None

class UserProfileResponse(BaseModel):
    _id: str
    email: str
    firstName: str
    lastName: str
    phone: Optional[str] = None
    bio: Optional[str] = None
    createdAt: datetime
    updatedAt: Optional[datetime] = None
    lastLogin: Optional[datetime] = None

class AuthResponse(BaseModel):
    success: bool
    message: str
    user: Optional[UserProfileResponse] = None

class TwoFactorRequest(BaseModel):
    email: EmailStr
    code: str

class UpdateAdminAccessRequest(BaseModel):
    email: EmailStr
    isAdmin: bool




class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    code: str
    newPassword: str
