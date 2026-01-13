# Backend Deployment Guide - Star Health & Allied Insurance Portal

## 🚀 Project Overview
This is the backend API for the Star Health Whatsapp Bot. It is built using **FastAPI** (Python) and acts as the bridge between the frontend dashboard, the AI agents, and the database.

## 🛠️ Technology Stack
- **Framework**: FastAPI
- **Server**: Uvicorn
- **Language**: Python 3.10+
- **Database**: MongoDB (via Motor/PyMongo)
- **Cache/Realtime**: Redis
- **AI/LLM**: Lyzr SDK
- **Authentication**: JWT (JSON Web Tokens) with BCrypt
- **External Services**: Twilio (WhatsApp API)

## 📂 File Structure
```
backend-python/
├── app/
│   ├── routes/          # API Route Controllers (Dashboard, Auth, Agents)
│   ├── core/            # Core Config (DB, Security, Config loaders)
│   ├── models/          # Pydantic Models & Schemas
│   ├── services/        # Business Logic (Lyzr Agent Service, etc.)
│   └── main.py          # Application Entry Point
├── scripts/             # Utility scripts
├── logs/                # Application logs
├── requirements.txt     # Python Dependencies
├── .env                 # Environment Variables (Secrets)
├── admin.py             # Admin Utility Script
└── Dockerfile           # Docker Configuration
```

## ⚙️ Setup & Installation

### Prerequisites
- Python 3.10 or higher
- MongoDB (Running instance)
- Redis (Running instance)

### Installation
1. **Navigate to the backend directory:**
   ```bash
   cd backend-python
   ```
2. **Create a Virtual Environment:**
   ```bash
   python -m venv venv
   ```
3. **Activate the Virtual Environment:**
   - **Windows:** `.\venv\Scripts\activate`
   - **Mac/Linux:** `source venv/bin/activate`
4. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## 🌿 Environment Variables
Create a `.env` file in the `backend-python` root.

```env
# Server Config
PORT=8000
ENVIRONMENT=production

# Database
MONGODB_URL=mongodb://localhost:27017
DB_NAME=whatsapp_bot
REDIS_URL=redis://localhost:6379

# Security
SECRET_KEY=your_super_secret_jwt_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Third Party Services
OPENAI_API_KEY=sk-...
LYZR_API_KEY=lz-...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
```

## 🏃‍♂️ Running the Server

### Development
```bash
uvicorn app.main:app --reload
```

### Production
For production, run without reload and typically with multiple workers or managed by Gunicorn (using Uvicorn workers).
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## 🚫 Files to Exclude from Deployment
When uploading code to your production server, **EXCLUDE** the following:
- `venv/` (Local virtual environment; create a fresh one on the server)
- `__pycache__/` (Compiled python files)
- `.env` (Secrets should be securely injected or created on variables)
- `.git/` (Version control)
- `.pytest_cache/` (Test cache)
- `.cursor/` (IDE settings)
- `*.pyc` (Bytecode)
- `logs/*` (Exclude local logs, keep the folder)

---
**Powered by Lyzr AI**
