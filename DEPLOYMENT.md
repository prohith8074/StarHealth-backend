# Star Health Backend - EC2 Deployment Guide

This guide will help you deploy the Star Health Backend application on an EC2 instance using Docker and Docker Compose.

## Prerequisites

- EC2 instance running Ubuntu 20.04+ or Amazon Linux 2
- SSH access to the EC2 instance
- Root or sudo access
- MongoDB instance (can be on the same server or external)

## Quick Start

### 1. Transfer Files to EC2

```bash
# On your local machine, compress the project
tar -czf starhealth-backend.tar.gz \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='venv' \
  --exclude='.env' \
  --exclude='logs' \
  --exclude='*.pyc' \
  .

# Transfer to EC2
scp starhealth-backend.tar.gz user@your-ec2-ip:/tmp/
```

### 2. SSH into EC2 and Deploy

```bash
# SSH into your EC2 instance
ssh user@your-ec2-ip

# Extract the files
cd /opt
sudo mkdir -p starhealth-backend
sudo tar -xzf /tmp/starhealth-backend.tar.gz -C starhealth-backend
cd starhealth-backend

# Make deploy script executable
sudo chmod +x deploy.sh

# Run deployment
sudo ./deploy.sh deploy
```

### 3. Configure Environment Variables

After deployment, edit the `.env` file:

```bash
sudo nano /opt/starhealth-backend/.env
```

Update the following critical variables:
- `MONGODB_URI` - Your MongoDB connection string
- `REDIS_PASSWORD` - Strong password for Redis
- `SECRET_KEY` - Strong random string for JWT
- `OPENAI_API_KEY` - Your OpenAI API key
- `LYZR_API_KEY` - Your Lyzr API key
- `TWILIO_ACCOUNT_SID` - Your Twilio account SID
- `TWILIO_AUTH_TOKEN` - Your Twilio auth token

### 4. Restart Services

```bash
cd /opt/starhealth-backend
sudo docker-compose restart
```

## Deployment Script Usage

The `deploy.sh` script provides several commands:

```bash
# Full deployment (first time)
sudo ./deploy.sh deploy

# Check status
sudo ./deploy.sh status

# View logs
sudo ./deploy.sh logs          # All services
sudo ./deploy.sh logs backend  # Backend only
sudo ./deploy.sh logs redis    # Redis only

# Restart services
sudo ./deploy.sh restart       # All services
sudo ./deploy.sh restart backend  # Backend only

# Stop services
sudo ./deploy.sh stop

# Start services
sudo ./deploy.sh start

# Create backup
sudo ./deploy.sh backup
```

## Architecture

The deployment uses Docker Compose with the following services:

1. **Backend** - FastAPI application (port 8000)
2. **Redis** - Redis cache server (port 6379)

### Network

- Services communicate via Docker bridge network
- Redis is accessible to backend at hostname `redis`
- Backend exposes port 8000 to host

### Volumes

- `redis-data` - Persistent Redis data storage
- `./logs` - Application logs (mounted from host)

## Environment Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `MONGODB_URI` | MongoDB connection string | `mongodb://localhost:27017/Star_Health_Whatsapp_bot` |
| `REDIS_PASSWORD` | Redis password | `your_secure_password` |
| `SECRET_KEY` | JWT secret key | `your_random_secret_key` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |
| `LYZR_API_KEY` | Lyzr API key | `lz-...` |
| `TWILIO_ACCOUNT_SID` | Twilio account SID | `AC...` |
| `TWILIO_AUTH_TOKEN` | Twilio auth token | `...` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Backend port | `8000` |
| `ENVIRONMENT` | Environment name | `production` |
| `REDIS_HOST` | Redis hostname | `redis` |
| `REDIS_PORT` | Redis port | `6379` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Health Checks

The deployment includes health checks for both services:

- **Backend**: `http://localhost:8000/health/live`
- **Redis**: Redis PING command

Check health status:

```bash
# Backend health
curl http://localhost:8000/health/live

# Redis health
docker exec starhealth-redis redis-cli -a $REDIS_PASSWORD ping
```

## Monitoring and Logs

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f redis

# Last 100 lines
docker-compose logs --tail=100 backend
```

### Container Status

```bash
# List running containers
docker ps

# Container stats
docker stats

# Inspect container
docker inspect starhealth-backend
```

## Troubleshooting

### Backend won't start

1. Check logs: `docker-compose logs backend`
2. Verify MongoDB connection in `.env`
3. Check port availability: `netstat -tulpn | grep 8000`
4. Verify environment variables are set correctly

### Redis connection issues

1. Check Redis logs: `docker-compose logs redis`
2. Verify Redis password matches in `.env`
3. Test Redis connection:
   ```bash
   docker exec -it starhealth-redis redis-cli -a $REDIS_PASSWORD ping
   ```

### Port already in use

If port 8000 is already in use:

1. Change `PORT` in `.env` file
2. Update `docker-compose.yml` ports mapping
3. Restart services: `docker-compose restart`

### Out of memory

If containers are being killed:

1. Check system memory: `free -h`
2. Reduce Redis maxmemory in `docker-compose.yml`
3. Reduce backend workers in `Dockerfile` CMD

## Security Best Practices

1. **Change default passwords**: Update `REDIS_PASSWORD` and `SECRET_KEY`
2. **Firewall**: The deploy script configures UFW, but verify:
   ```bash
   sudo ufw status
   ```
3. **SSL/TLS**: Use a reverse proxy (nginx) with Let's Encrypt for HTTPS
4. **Environment variables**: Never commit `.env` file to version control
5. **Regular updates**: Keep Docker images updated:
   ```bash
   docker-compose pull
   docker-compose up -d
   ```

## Backup and Restore

### Backup

```bash
# Manual backup
sudo ./deploy.sh backup

# Backup includes:
# - Application code
# - Environment configuration
# - Logs
```

### Restore

```bash
# Stop services
sudo ./deploy.sh stop

# Restore from backup
sudo cp -r /opt/backups/starhealth/backup-YYYYMMDD-HHMMSS/* /opt/starhealth-backend/

# Start services
sudo ./deploy.sh start
```

## Scaling

To scale the backend service:

1. Edit `docker-compose.yml`:
   ```yaml
   backend:
     deploy:
       replicas: 3
   ```

2. Use Docker Swarm mode:
   ```bash
   docker swarm init
   docker stack deploy -c docker-compose.yml starhealth
   ```

## Maintenance

### Update Application

```bash
cd /opt/starhealth-backend

# Pull latest code
git pull  # or transfer new files

# Rebuild and restart
docker-compose build --no-cache
docker-compose up -d
```

### Update Dependencies

```bash
# Update requirements.txt locally, then:
docker-compose build --no-cache backend
docker-compose up -d backend
```

## Support

For issues or questions:
1. Check logs: `sudo ./deploy.sh logs`
2. Check container status: `docker ps`
3. Review health endpoints: `curl http://localhost:8000/health/live`

---

**Note**: This deployment assumes MongoDB is running separately. If you need to deploy MongoDB as well, add it to `docker-compose.yml` or use MongoDB Atlas.

