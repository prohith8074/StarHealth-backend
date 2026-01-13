"""Quick check for Star Health Assure keywords"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Fix Windows encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from app.services.product_service import get_product_service

ps = get_product_service()
products = ps.get_all_products()

print(f"Total products: {len(products)}")
print()

# Find Star Health Assure
star_assure = [p for p in products if 'assure' in p.get('productName', '').lower()]
print(f"Found {len(star_assure)} Assure products:")
for p in star_assure:
    print(f"  Name: {p.get('productName')}")
    print(f"  Keywords: {p.get('keywords', [])}")
    print()

# Test if "Star Health Assure" matches
test_text = "I've checked our product catalog, and based on the customer's profile, Star Health Assure would be a good fit."
print(f"Test text: {test_text[:80]}...")
print()

found = ps.find_products_in_text(test_text)
print(f"Products found: {len(found)}")
for p in found:
    print(f"  - {p.get('productName')}")
