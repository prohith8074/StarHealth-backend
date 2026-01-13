# create_admin_user.py
import sys
import io
# Fix encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from app.config.database import get_database
from app.routes.auth import hash_password
from datetime import datetime

def create_admin_user():
    """Manually create admin user in login_details collection"""
    db = get_database()
    
    admin_email = "rohith.p@lyzr.ai"
    admin_password = "Password@123"
    
    # Check if user already exists
    existing_user = db.login_details.find_one({"email": admin_email})
    
    if existing_user:
        print(f"[INFO] User {admin_email} already exists")
        # Update to ensure admin access
        db.login_details.update_one(
            {"_id": existing_user["_id"]},
            {"$set": {
                "isAdmin": True,
                "isActive": True,
                "password": hash_password(admin_password),
                "updatedAt": datetime.now()
            }}
        )
        print(f"[SUCCESS] Admin user updated: {admin_email}")
    else:
        # Create new admin user
        admin_doc = {
            "email": admin_email,
            "password": hash_password(admin_password),
            "firstName": "Rohith",
            "lastName": "P",
            "phone": "",
            "bio": "",
            "isAdmin": True,
            "isActive": True,
            "twoFactorEnabled": False,
            "createdAt": datetime.now(),
            "updatedAt": datetime.now()
        }
        
        result = db.login_details.insert_one(admin_doc)
        print(f"[SUCCESS] Admin user created successfully!")
        print(f"   Email: {admin_email}")
        print(f"   Password: {admin_password}")
        print(f"   User ID: {result.inserted_id}")

if __name__ == "__main__":
    try:
        create_admin_user()
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()