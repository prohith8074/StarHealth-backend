"""
Feedback routes - ported from Node.js backend
"""
from fastapi import APIRouter, HTTPException
from app.config.database import get_database
from app.config.logging_config import get_logger
from app.models.models import FeedbackCreate, FeedbackResponse
from datetime import datetime, timedelta
from bson import ObjectId

router = APIRouter()
logger = get_logger(__name__)

def get_ist_time():
    """Get current time in Indian Standard Time (IST)"""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

from app.routes.dashboard import trigger_dashboard_warmup

@router.post("/", status_code=201)
def create_feedback(feedback: FeedbackCreate):
    """Create feedback"""
    logger.info("📝 Creating feedback")
    logger.debug(f"   Data: {feedback.dict()}")
    
    try:
        db = get_database()
        ist_now = get_ist_time()
        feedback_doc = {
            "username": feedback.username,
            "agentCode": feedback.agentCode,
            "agentType": feedback.agentType,
            "feedback": feedback.feedback,
            "feedbackTamil": feedback.feedbackTamil,  # Tamil feedback support
            "sessionId": feedback.sessionId,
            "createdAt": ist_now,
            "updatedAt": ist_now
        }
        result = db.feedback.insert_one(feedback_doc)
        feedback_doc["_id"] = str(result.inserted_id)
        logger.info(f"✅ Feedback created: {result.inserted_id}")
        
        # 🔄 Trigger Dashboard Cache Refresh
        trigger_dashboard_warmup()
        
        return feedback_doc
    except Exception as error:
        logger.error(f"❌ Error creating feedback: {error}")
        raise HTTPException(status_code=500, detail="Failed to create feedback")

@router.get("")
def get_feedback():
    """Get all feedback entries"""
    logger.info("📖 Fetching feedback list")
    try:
        db = get_database()
        feedback_docs = db.feedback.find().sort("createdAt", -1)
        feedback_list = []
        for doc in feedback_docs:
            doc["_id"] = str(doc["_id"])
            feedback_list.append(doc)
        logger.info(f"✅ Retrieved {len(feedback_list)} feedback entries")
        return feedback_list
    except Exception as error:
        logger.error(f"❌ Error fetching feedback: {error}")
        raise HTTPException(status_code=500, detail="Failed to fetch feedback")




