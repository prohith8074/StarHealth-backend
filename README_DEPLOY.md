# Quick Deployment Guide

## One-Command Deployment on EC2

```bash
# 1. Transfer your code to EC2 (from your local machine)
scp -r . user@your-ec2-ip:/tmp/starhealth-backend

# 2. SSH into EC2
ssh user@your-ec2-ip

# 3. Move to /opt and run deployment
sudo mkdir -p /opt/starhealth-backend
sudo mv /tmp/starhealth-backend/* /opt/starhealth-backend/
cd /opt/starhealth-backend
sudo chmod +x deploy.sh
sudo ./deploy.sh deploy
```

## After Deployment

1. **Configure `.env` file:**
   ```bash
   sudo nano /opt/starhealth-backend/.env
   ```
   Update MongoDB URI, API keys, and passwords.

2. **Restart services:**
   ```bash
   cd /opt/starhealth-backend
   sudo docker-compose restart
   ```

3. **Check status:**
   ```bash
   sudo ./deploy.sh status
   ```

## What Gets Deployed

- ✅ FastAPI Backend (port 8000)
- ✅ Redis Cache (port 6379)
- ✅ Automatic health checks
- ✅ Log rotation
- ✅ Systemd service
- ✅ Firewall configuration

## Useful Commands

```bash
# View logs
sudo ./deploy.sh logs

# Restart
sudo ./deploy.sh restart

# Stop
sudo ./deploy.sh stop

# Start
sudo ./deploy.sh start

# Status
sudo ./deploy.sh status
```

For detailed documentation, see [DEPLOYMENT.md](./DEPLOYMENT.md)

