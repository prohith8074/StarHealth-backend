"""
Script to seed MongoDB with initial data
Run: python scripts/seed_database.py
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

def seed_database():
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
    
    if not db_name or db_name == "":
        db_name = "Star_Health_Whatsapp_bot"
    
    db = client[db_name]
    print(f"📚 Using database: {db_name}")
    
    # Seed Agents Collection - 15 dummy records
    agents = db.agents
    sample_agents = [
        {
            "agent_code": "SH001",
            "agent_name": "Rajesh Iyer",
            "phone_number": "919876543201",
            "email": "rajesh.iyer@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH002",
            "agent_name": "Priya Sharma",
            "phone_number": "919876543202",
            "email": "priya.sharma@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH003",
            "agent_name": "Amit Kumar",
            "phone_number": "919876543203",
            "email": "amit.kumar@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH004",
            "agent_name": "Sneha Patel",
            "phone_number": "919876543204",
            "email": "sneha.patel@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH005",
            "agent_name": "Vikram Singh",
            "phone_number": "919876543205",
            "email": "vikram.singh@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH006",
            "agent_name": "Anjali Mehta",
            "phone_number": "919876543218",
            "email": "anjali@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH007",
            "agent_name": "Rahul Desai",
            "phone_number": "919876543216",
            "email": "rahul.desai@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH008",
            "agent_name": "Kavita Nair",
            "phone_number": "919876543217",
            "email": "kavita.nair@starhealth.com",
            "role": "SM",
            "is_active": True
        },
        {
            "agent_code": "SH009",
            "agent_name": "Arjun Reddy",
            "phone_number": "919876543209",
            "email": "arjun.reddy@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH010",
            "agent_name": "Meera Joshi",
            "phone_number": "919876543210",
            "email": "meera.joshi@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH011",
            "agent_name": "Suresh Menon",
            "phone_number": "919876543211",
            "email": "suresh.menon@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH012",
            "agent_name": "Divya Rao",
            "phone_number": "919876543212",
            "email": "divya.rao@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH013",
            "agent_name": "Karan Malhotra",
            "phone_number": "919876543213",
            "email": "karan.malhotra@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH014",
            "agent_name": "Neha Gupta",
            "phone_number": "919876543214",
            "email": "neha.gupta@starhealth.com",
            "role": "Agent",
            "is_active": True
        },
        {
            "agent_code": "SH015",
            "agent_name": "Rohit Verma",
            "phone_number": "919876543215",
            "email": "rohit.verma@starhealth.com",
            "role": "Agent",
            "is_active": True
        }
    ]
    
    print("\n📝 Seeding agents collection with 15 records...")
    for agent in sample_agents:
        agents.update_one(
            {"agent_code": agent["agent_code"]},
            {"$set": agent},
            upsert=True
        )
        print(f"✓ Seeded agent: {agent['agent_code']} - {agent['agent_name']} ({agent['phone_number']})")
    
    # Seed Knowledge Base
    knowledge = db.knowledge
    sample_knowledge = [
        {
            "type": "product_recommendation",
            "content": "Our health insurance plans offer comprehensive coverage including hospitalization, outpatient care, and preventive health checkups."
        },
        {
            "type": "sales_pitch",
            "content": "Star Health Insurance provides affordable premiums with extensive network coverage across India. Get instant policy issuance and 24/7 customer support."
        },
    ]
    
    print("\n📚 Seeding knowledge base...")
    for item in sample_knowledge:
        knowledge.update_one(
            {"type": item["type"]},
            {"$set": item},
            upsert=True
        )
        print(f"✓ Seeded knowledge: {item['type']}")
    
    # Verify data
    print("\n📊 Verifying seeded data...")
    agent_count = agents.count_documents({})
    print(f"   Total agents in database: {agent_count}")
    
    # List all agents with their details
    all_agents = list(agents.find({}, {"agent_code": 1, "agent_name": 1, "phone_number": 1, "email": 1, "role": 1}))
    print(f"\n📋 All {agent_count} agents in database:")
    for agent in all_agents:
        print(f"   - {agent.get('agent_code')}: {agent.get('agent_name')} | Mobile: {agent.get('phone_number', 'N/A')} | Email: {agent.get('email', 'N/A')} | Role: {agent.get('role', 'N/A')}")
    
    print("\n✅ Database seeding completed!")
    client.close()

if __name__ == "__main__":
    seed_database()

