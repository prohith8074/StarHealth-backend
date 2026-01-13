"""
Script to add unique product variations/keywords to Top_Products collection.
Each product gets unique keywords that won't match other products.

Run: python scripts/add_product_variations.py
"""
import sys
import os

# Fix for Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# Define unique keywords for each Star Health product
# These are designed to NOT overlap with other products
PRODUCT_KEYWORDS = {
    # Family Health Plans
    "Star Health Assure Insurance Policy": [
        "Star Assure",
        "Health Assure",
        "Assure Policy",
        "Star Health Assure",
        "Assure Insurance",
        "ஸ்டார் ஹெல்த் அஷ்யூர்",  # Tamil
    ],
    "Star Comprehensive Insurance Policy": [
        "Star Comprehensive",
        "Comprehensive Policy",
        "Comprehensive Insurance",
        "ஸ்டார் காம்ப்ரிஹென்சிவ்",  # Tamil
    ],
    "Star Family Health Optima Insurance Policy": [
        "Family Health Optima",
        "Star Optima",
        "Optima Policy",
        "Health Optima",
        "Family Optima",
        "ஃபேமிலி ஹெல்த் ஆப்டிமா",  # Tamil
    ],
    
    # Women's Health Plans
    "Star Women Care Insurance Policy": [
        "Star Women Care",
        "Women Care",
        "Women Care Policy",
        "Star Women",
        "ஸ்டார் விமன் கேர்",  # Tamil
    ],
    
    # Senior Citizen Plans
    "Star Senior Citizens Red Carpet Insurance Policy": [
        "Senior Citizens Red Carpet",
        "Red Carpet Policy",
        "Senior Red Carpet",
        "Star Red Carpet",
        "Senior Citizens Policy",
        "சீனியர் சிட்டிசன்ஸ் ரெட் கார்பெட்",  # Tamil
    ],
    "Star Medi Classic Insurance Policy": [
        "Star Medi Classic",
        "Medi Classic",
        "Medi Classic Policy",
        "மெடி கிளாசிக்",  # Tamil
    ],
    
    # Individual Plans
    "Star Health Premier Insurance Policy": [
        "Star Premier",
        "Health Premier",
        "Premier Insurance",
        "Premier Policy",
        "ஸ்டார் பிரீமியர்",  # Tamil
    ],
    "Young Star Insurance Policy": [
        "Young Star",
        "Young Star Policy",
        "Young Star Insurance",
        "யங் ஸ்டார்",  # Tamil
    ],
    "Star Super Surplus Insurance Policy": [
        "Star Super Surplus",
        "Super Surplus",
        "Super Surplus Policy",
        "சூப்பர் சர்ப்ளஸ்",  # Tamil
    ],
    
    # Critical Illness Plans
    "Star Cardiac Care Insurance Policy": [
        "Star Cardiac Care",
        "Cardiac Care",
        "Cardiac Care Policy",
        "Heart Care Policy",
        "கார்டியாக் கேர்",  # Tamil
    ],
    "Star Cancer Care Platinum Insurance Policy": [
        "Star Cancer Care Platinum",
        "Cancer Care Platinum",
        "Cancer Care Policy",
        "Cancer Platinum",
        "கேன்சர் கேர் பிளாட்டினம்",  # Tamil
    ],
    
    # Accident Plans
    "Star Personal & Caring Accident Insurance Policy": [
        "Star Personal Accident",
        "Personal Accident Policy",
        "Caring Accident",
        "Personal Caring Accident",
        "பர்சனல் ஆக்சிடென்ட்",  # Tamil
    ],
    "Star Micro Rural & Farmers Care Insurance Policy": [
        "Micro Rural Farmers Care",
        "Rural Farmers Care",
        "Star Micro Rural",
        "Farmers Care Policy",
        "ரூரல் ஃபார்மர்ஸ் கேர்",  # Tamil
    ],
    
    # Special Plans
    "Star Outpatient Care Insurance Policy": [
        "Star Outpatient Care",
        "Outpatient Care",
        "OPD Care Policy",
        "Outpatient Policy",
        "அவுட்பேஷன்ட் கேர்",  # Tamil
    ],
    "Star Hospital Daily Cash Insurance Policy": [
        "Star Hospital Daily Cash",
        "Hospital Daily Cash",
        "Daily Cash Policy",
        "Hospital Cash",
        "ஹாஸ்பிடல் டெய்லி கேஷ்",  # Tamil
    ],
    "Star Diabetes Safe Insurance Policy": [
        "Star Diabetes Safe",
        "Diabetes Safe",
        "Diabetes Safe Policy",
        "Diabetes Insurance",
        "டயாபட்டிஸ் சேஃப்",  # Tamil
    ],
    "Star Arogya Sanjeevani Insurance Policy": [
        "Star Arogya Sanjeevani",
        "Arogya Sanjeevani",
        "Arogya Sanjeevani Policy",
        "ஆரோக்ய சஞ்சீவினி",  # Tamil
    ],
    
    # Corporate & Group Plans
    "Star Group Health Insurance Policy": [
        "Star Group Health",
        "Group Health Policy",
        "Group Health Insurance",
        "குரூப் ஹெல்த்",  # Tamil
    ],
    "Star SME Care Insurance Policy": [
        "Star SME Care",
        "SME Care",
        "SME Care Policy",
        "SME Insurance",
        "எஸ்எம்இ கேர்",  # Tamil
    ],
}


def add_product_variations():
    """Add unique keywords/variations to existing products"""
    
    # Use MONGODB_URI or MONGODB_URI
    mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/Star_Health_Whatsapp_bot"
    
    print("🔌 Connecting to MongoDB...")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    
    # Get database name from URI or use default
    db_name = "Star_Health_Whatsapp_bot"
    try:
        if "/" in mongo_uri:
            parts = mongo_uri.split("/")
            if len(parts) > 3:
                potential_db = parts[-1].split("?")[0]
                if potential_db and potential_db.strip():
                    db_name = potential_db.strip()
    except:
        pass
    
    db = client[db_name]
    products_collection = db["Top_Products"]
    
    print(f"📚 Using database: {db_name}")
    
    # Get existing products
    existing_products = list(products_collection.find({}))
    print(f"\n📦 Found {len(existing_products)} existing products")
    
    # Track all keywords to ensure uniqueness
    all_keywords = set()
    keyword_to_product = {}
    
    # First pass: collect all existing keywords
    for product in existing_products:
        product_name = product.get("productName", "")
        existing_keywords = product.get("keywords", [])
        for kw in existing_keywords:
            if kw in all_keywords:
                print(f"⚠️ Duplicate keyword found: '{kw}' - already assigned to '{keyword_to_product.get(kw)}'")
            else:
                all_keywords.add(kw)
                keyword_to_product[kw] = product_name
    
    # Update/add products with unique keywords
    updated_count = 0
    added_count = 0
    
    for product_name, keywords in PRODUCT_KEYWORDS.items():
        # Check for duplicates in new keywords
        unique_keywords = []
        for kw in keywords:
            kw_lower = kw.lower().strip()
            if kw_lower in [k.lower() for k in all_keywords]:
                existing_product = keyword_to_product.get(kw, "unknown")
                if existing_product != product_name:
                    print(f"⚠️ Skipping keyword '{kw}' for '{product_name}' - already used by '{existing_product}'")
                    continue
            unique_keywords.append(kw)
            all_keywords.add(kw)
            keyword_to_product[kw] = product_name
        
        # Find existing product
        existing = products_collection.find_one({"productName": product_name})
        
        now = datetime.utcnow()
        
        if existing:
            # Update existing product with new keywords
            existing_keywords = set(existing.get("keywords", []))
            merged_keywords = list(existing_keywords.union(set(unique_keywords)))
            
            products_collection.update_one(
                {"productName": product_name},
                {
                    "$set": {
                        "keywords": merged_keywords,
                        "updatedAt": now
                    }
                }
            )
            print(f"✅ Updated '{product_name}' with {len(unique_keywords)} keywords")
            updated_count += 1
        else:
            # Create new product entry
            new_product = {
                "productName": product_name,
                "productNameTamil": "",  # Will be populated by Tamil translation agent
                "keywords": unique_keywords,
                "productRecommendationCount": 0,
                "salesPitchCount": 0,
                "createdAt": now,
                "updatedAt": now
            }
            products_collection.insert_one(new_product)
            print(f"➕ Added new product '{product_name}' with {len(unique_keywords)} keywords")
            added_count += 1
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    print(f"   Updated: {updated_count} products")
    print(f"   Added: {added_count} new products")
    print(f"   Total unique keywords: {len(all_keywords)}")
    
    # List all products with their keywords
    print("\n📋 All products with keywords:")
    all_products = list(products_collection.find({}).sort("productName", 1))
    for product in all_products:
        name = product.get("productName", "Unknown")
        keywords = product.get("keywords", [])
        print(f"\n   {name}")
        if keywords:
            for kw in keywords[:5]:  # Show first 5 keywords
                print(f"      - {kw}")
            if len(keywords) > 5:
                print(f"      ... and {len(keywords) - 5} more")
        else:
            print(f"      (no keywords)")
    
    print("\n✅ Product variations added successfully!")
    client.close()


def validate_keyword_uniqueness():
    """Validate that no keyword matches multiple products"""
    
    mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/Star_Health_Whatsapp_bot"
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = client["Star_Health_Whatsapp_bot"]
    products_collection = db["Top_Products"]
    
    print("\n🔍 Validating keyword uniqueness...")
    
    keyword_map = {}
    products = list(products_collection.find({}))
    
    duplicates_found = False
    
    for product in products:
        product_name = product.get("productName", "")
        keywords = product.get("keywords", [])
        
        for kw in keywords:
            kw_lower = kw.lower().strip()
            if kw_lower in keyword_map:
                print(f"❌ DUPLICATE: '{kw}' is used by both:")
                print(f"      - {keyword_map[kw_lower]}")
                print(f"      - {product_name}")
                duplicates_found = True
            else:
                keyword_map[kw_lower] = product_name
    
    if not duplicates_found:
        print("✅ All keywords are unique - no duplicates found!")
    
    client.close()
    return not duplicates_found


if __name__ == "__main__":
    add_product_variations()
    print("\n" + "=" * 60)
    validate_keyword_uniqueness()
