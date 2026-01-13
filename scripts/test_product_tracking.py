"""
Test script to verify product tracking is working.
Run: python scripts/test_product_tracking.py

This script:
1. Gets all products from the database
2. Tests the fuzzy_match_product function with sample text
3. Tests the find_products_in_text function
"""
import sys
import os

# Fix for Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.services.product_service import get_product_service

def test_product_tracking():
    print("=" * 60)
    print("🧪 PRODUCT TRACKING TEST")
    print("=" * 60)
    
    product_service = get_product_service()
    
    # 1. Get all products
    print("\n📦 Step 1: Getting all products from database...")
    products = product_service.get_all_products()
    print(f"   Found {len(products)} products")
    
    if not products:
        print("❌ No products found in database! Run add_product_variations.py first.")
        return
    
    print("\n📋 Products in database:")
    for i, p in enumerate(products[:10], 1):
        name = p.get("productName", "Unknown")[:40]
        keywords = p.get("keywords", [])
        print(f"   {i}. {name}")
        if keywords:
            print(f"      Keywords: {keywords[:3]}...")
    
    if len(products) > 10:
        print(f"   ... and {len(products) - 10} more")
    
    # 2. Test fuzzy matching with sample agent responses
    print("\n" + "=" * 60)
    print("🔍 Step 2: Testing fuzzy matching with sample text...")
    print("=" * 60)
    
    sample_responses = [
        """For a 25-year-old female looking for individual coverage with 50L income, 
        the Star Women Care Insurance Policy is a great fit. It's specifically 
        designed for women and offers sum insured options up to 25 lakhs.""",
        
        """Here's a pitch: Star Health Assure covers comprehensive cancer treatment 
        with cashless access at 14,000+ hospitals including Chennai's best. 
        As India's largest health-only insurer with 97% claim settlement.""",
        
        """Star Comprehensive Insurance Policy covers your entire family under one plan. 
        Cashless treatment at 14,000+ hospitals, and no room rent limits.""",
        
        """Perfect. Star Diabetes Safe is ideal - designed specifically for diabetic patients 
        with pre-existing conditions coverage.""",
        
        """For senior citizens, I recommend the Star Senior Citizens Red Carpet Insurance Policy. 
        It provides excellent coverage for elderly patients.""",
        
        """Young Star Insurance Policy is perfect for young professionals starting their 
        health insurance journey.""",
    ]
    
    for i, response in enumerate(sample_responses, 1):
        print(f"\n📝 Sample Response {i}:")
        print(f"   \"{response[:100]}...\"")
        
        found = product_service.find_products_in_text(response)
        
        if found:
            print(f"   ✅ Found {len(found)} product(s):")
            for p in found:
                print(f"      - {p.get('productName')}")
        else:
            print(f"   ⚠️ No products found!")
    
    # 3. Test direct keyword matching
    print("\n" + "=" * 60)
    print("🔑 Step 3: Testing direct keyword matching...")
    print("=" * 60)
    
    keyword_tests = [
        "Star Women Care",
        "Star Assure",
        "Women Care Policy",
        "Star Health Assure",
        "Diabetes Safe",
        "Cancer Care Platinum",
        "Star Comprehensive",
    ]
    
    for keyword in keyword_tests:
        found = product_service.find_products_in_text(keyword)
        if found:
            print(f"   ✅ '{keyword}' -> {found[0].get('productName')}")
        else:
            print(f"   ⚠️ '{keyword}' -> No match found")
    
    # 4. Show product stats
    print("\n" + "=" * 60)
    print("📊 Step 4: Current product stats...")
    print("=" * 60)
    
    stats = product_service.get_product_stats()
    print(f"   Total Products: {stats['totalProducts']}")
    print(f"   Product Recommendations: {stats['productRecommendationTotal']}")
    print(f"   Sales Pitches: {stats['salesPitchTotal']}")
    
    print("\n   Top tracked products:")
    sorted_products = sorted(
        stats['products'],
        key=lambda x: x['productRecommendationCount'] + x['salesPitchCount'],
        reverse=True
    )[:5]
    
    for p in sorted_products:
        total = p['productRecommendationCount'] + p['salesPitchCount']
        if total > 0:
            print(f"      - {p['productName'][:35]} ({total} mentions)")
    
    if not any(p['productRecommendationCount'] + p['salesPitchCount'] > 0 for p in stats['products']):
        print(f"      (No products have been tracked yet)")
    
    print("\n" + "=" * 60)
    print("✅ TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    test_product_tracking()
