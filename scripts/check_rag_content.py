"""Check RAG content in MongoDB"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

uri = os.getenv('MONGODB_URI') or os.getenv('MONGODB_URI') or 'mongodb://localhost:27017/Star_Health_Whatsapp_bot'
client = MongoClient(uri)
db = client['Star_Health_Whatsapp_bot']
collection = db['ragcontent']

count = collection.count_documents({})
print(f'Total RAG content items: {count}')

if count > 0:
    items = list(collection.find().limit(10))
    print(f'\nSample items:')
    for item in items:
        print(f"  - ID: {item.get('contentId', 'N/A')}")
        print(f"    Source: {item.get('source', 'N/A')}")
        print(f"    Type: {item.get('type', 'N/A')}")
        print(f"    Status: {item.get('status', 'N/A')}")
        print()
else:
    print('No RAG content found in database')






