#!/bin/bash

###############################################################################
# Star Health Backend - EC2 Deployment Script
# This script automates the deployment of the Star Health backend on EC2
###############################################################################

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_DIR="/opt/starhealth-backend"
SERVICE_NAME="starhealth-backend"
BACKUP_DIR="/opt/backups/starhealth"

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "Please run as root or with sudo"
        exit 1
    fi
}

# Install system dependencies
install_dependencies() {
    log "Installing system dependencies..."

    # Update package list
    apt-get update -y

    # Install Docker if not present
    if ! command -v docker &> /dev/null; then
        log "Installing Docker..."
        apt-get install -y \
            ca-certificates \
            curl \
            gnupg \
            lsb-release

        # Add Docker's official GPG key
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg

        # Set up Docker repository
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
          $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

        # Install Docker Engine
        apt-get update -y
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

        # Start and enable Docker
        systemctl start docker
        systemctl enable docker

        log "Docker installed successfully"
    else
        log "Docker is already installed"
    fi

    # Install Docker Compose if not present (standalone)
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log "Installing Docker Compose..."
        curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        chmod +x /usr/local/bin/docker-compose
        log "Docker Compose installed successfully"
    else
        log "Docker Compose is already installed"
    fi

    # Install other utilities
    apt-get install -y \
        git \
        curl \
        wget \
        htop \
        net-tools \
        ufw \
        fail2ban

    log "System dependencies installed"
}

# Setup firewall
setup_firewall() {
    log "Setting up firewall..."

    # Allow SSH
    ufw allow 22/tcp

    # Allow HTTP/HTTPS
    ufw allow 80/tcp
    ufw allow 443/tcp

    # Allow application port (if not using reverse proxy)
    ufw allow ${PORT:-8000}/tcp

    # Enable firewall (non-interactive)
    ufw --force enable

    log "Firewall configured"
}

# Create project directory
setup_project_dir() {
    log "Setting up project directory..."

    mkdir -p "$PROJECT_DIR"
    mkdir -p "$BACKUP_DIR"
    mkdir -p "$PROJECT_DIR/logs"

    # Set permissions
    chown -R $SUDO_USER:$SUDO_USER "$PROJECT_DIR" 2>/dev/null || true
    chown -R $SUDO_USER:$SUDO_USER "$BACKUP_DIR" 2>/dev/null || true

    log "Project directory created at $PROJECT_DIR"
}

# Setup environment file
setup_env_file() {
    log "Setting up environment file..."

    if [ ! -f "$PROJECT_DIR/.env" ]; then
        warning ".env file not found. Creating template..."
        cat > "$PROJECT_DIR/.env" << 'EOF'
# Server Config
PORT=8000
ENVIRONMENT=production

# Database
MONGODB_URI=mongodb://localhost:27017/Star_Health_Whatsapp_bot
MONGODB_DATABASE=Star_Health_Whatsapp_bot

# Redis (will be overridden by docker-compose)
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=changeme
REDIS_USERNAME=default

# Security
SECRET_KEY=your_super_secret_jwt_key_change_this
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Third Party Services
OPENAI_API_KEY=your_openai_api_key
LYZR_API_KEY=your_lyzr_api_key
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token

# Optional: Redis URL (if using external Redis Cloud)
# REDIS_URL=redis://default:password@host:port
EOF
        chmod 600 "$PROJECT_DIR/.env"
        warning "Please edit $PROJECT_DIR/.env with your actual configuration values"
    else
        log ".env file already exists"
    fi
}

# Deploy application
deploy_app() {
    log "Deploying application..."

    cd "$PROJECT_DIR"

    # Stop existing containers
    if [ -f "docker-compose.yml" ]; then
        log "Stopping existing containers..."
        docker-compose down || docker compose down || true
    fi

    # Backup existing deployment if it exists
    if [ -d "$PROJECT_DIR/app" ]; then
        log "Creating backup..."
        BACKUP_NAME="backup-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP_DIR/$BACKUP_NAME"
        cp -r "$PROJECT_DIR"/* "$BACKUP_DIR/$BACKUP_NAME/" 2>/dev/null || true
        log "Backup created at $BACKUP_DIR/$BACKUP_NAME"
    fi

    # Build and start containers
    log "Building and starting containers..."
    docker-compose build --no-cache || docker compose build --no-cache
    docker-compose up -d || docker compose up -d

    # Wait for services to be healthy
    log "Waiting for services to be healthy..."
    sleep 10

    # Check if containers are running
    if docker ps | grep -q "starhealth-backend"; then
        log "Backend container is running"
    else
        error "Backend container failed to start"
        docker-compose logs backend || docker compose logs backend
        exit 1
    fi

    if docker ps | grep -q "starhealth-redis"; then
        log "Redis container is running"
    else
        error "Redis container failed to start"
        docker-compose logs redis || docker compose logs redis
        exit 1
    fi

    log "Application deployed successfully"
}

# Setup systemd service (optional, for better process management)
setup_systemd_service() {
    log "Setting up systemd service..."

    cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=Star Health Backend Service
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=/usr/bin/docker-compose -f ${PROJECT_DIR}/docker-compose.yml up -d
ExecStop=/usr/bin/docker-compose -f ${PROJECT_DIR}/docker-compose.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}.service

    log "Systemd service configured"
}

# Setup log rotation
setup_log_rotation() {
    log "Setting up log rotation..."

    cat > "/etc/logrotate.d/starhealth-backend" << EOF
${PROJECT_DIR}/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
    sharedscripts
    postrotate
        docker-compose -f ${PROJECT_DIR}/docker-compose.yml restart backend || docker compose -f ${PROJECT_DIR}/docker-compose.yml restart backend
    endscript
}
EOF

    log "Log rotation configured"
}

# Health check
health_check() {
    log "Performing health check..."

    sleep 5

    # Check if backend is responding
    if curl -f http://localhost:${PORT:-8000}/health/live > /dev/null 2>&1; then
        log "✅ Backend health check passed"
    else
        warning "⚠️  Backend health check failed (may still be starting)"
    fi

    # Check Redis
    if docker exec starhealth-redis redis-cli -a ${REDIS_PASSWORD:-changeme} ping > /dev/null 2>&1; then
        log "✅ Redis health check passed"
    else
        warning "⚠️  Redis health check failed"
    fi
}

# Show status
show_status() {
    log "Current deployment status:"
    echo ""
    info "Containers:"
    docker ps --filter "name=starhealth" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    info "Logs (last 20 lines):"
    docker-compose logs --tail=20 backend || docker compose logs --tail=20 backend
}

# Main deployment function
main() {
    log "Starting Star Health Backend deployment on EC2..."
    echo ""

    check_root

    # Check if this is a fresh install or update
    if [ -d "$PROJECT_DIR" ] && [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
        info "Existing deployment detected. This will update the application."
        read -p "Continue? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log "Deployment cancelled"
            exit 0
        fi
    fi

    # Run deployment steps
    install_dependencies
    setup_firewall
    setup_project_dir
    setup_env_file
    deploy_app
    setup_systemd_service
    setup_log_rotation
    health_check

    echo ""
    log "=========================================="
    log "✅ Deployment completed successfully!"
    log "=========================================="
    echo ""
    info "Next steps:"
    echo "  1. Edit $PROJECT_DIR/.env with your configuration"
    echo "  2. Restart services: docker-compose -f $PROJECT_DIR/docker-compose.yml restart"
    echo "  3. View logs: docker-compose -f $PROJECT_DIR/docker-compose.yml logs -f"
    echo "  4. Check status: docker ps"
    echo ""
    info "Useful commands:"
    echo "  - View logs: docker-compose -f $PROJECT_DIR/docker-compose.yml logs -f backend"
    echo "  - Restart: docker-compose -f $PROJECT_DIR/docker-compose.yml restart"
    echo "  - Stop: docker-compose -f $PROJECT_DIR/docker-compose.yml down"
    echo "  - Start: docker-compose -f $PROJECT_DIR/docker-compose.yml up -d"
    echo ""

    show_status
}

# Handle script arguments
case "${1:-}" in
    deploy)
        main
        ;;
    status)
        show_status
        ;;
    logs)
        cd "$PROJECT_DIR"
        docker-compose logs -f ${2:-backend} || docker compose logs -f ${2:-backend}
        ;;
    restart)
        cd "$PROJECT_DIR"
        docker-compose restart ${2:-} || docker compose restart ${2:-}
        ;;
    stop)
        cd "$PROJECT_DIR"
        docker-compose down || docker compose down
        ;;
    start)
        cd "$PROJECT_DIR"
        docker-compose up -d || docker compose up -d
        ;;
    backup)
        BACKUP_NAME="backup-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP_DIR/$BACKUP_NAME"
        cp -r "$PROJECT_DIR"/* "$BACKUP_DIR/$BACKUP_NAME/" 2>/dev/null || true
        log "Backup created at $BACKUP_DIR/$BACKUP_NAME"
        ;;
    *)
        echo "Usage: $0 {deploy|status|logs [service]|restart [service]|stop|start|backup}"
        echo ""
        echo "Commands:"
        echo "  deploy   - Full deployment (install dependencies, setup, deploy)"
        echo "  status   - Show current deployment status"
        echo "  logs     - Show logs (optionally for specific service)"
        echo "  restart  - Restart services (optionally specific service)"
        echo "  stop     - Stop all services"
        echo "  start    - Start all services"
        echo "  backup   - Create backup of current deployment"
        exit 1
        ;;
esac

