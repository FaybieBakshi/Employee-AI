#!/usr/bin/env bash
# setup_cloud.sh — Idempotent Ubuntu 22.04 provisioner for AI Employee Cloud Agent
#
# Installs: Docker CE, Docker Compose v2, git, certbot, cron, sets up deploy user
# Run as root or with sudo.
#
# Usage:
#   sudo bash scripts/setup_cloud.sh
#   sudo bash scripts/setup_cloud.sh --domain example.com --email admin@example.com

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────
DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"
DEPLOY_USER="${DEPLOY_USER:-aiemployee}"
APP_DIR="${APP_DIR:-/opt/ai-employee}"
VAULT_DIR="${VAULT_DIR:-/opt/ai-employee-vault}"
REPO_URL="${REPO_URL:-}"

# ── Parse CLI args ────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)   DOMAIN="$2";  shift 2 ;;
        --email)    EMAIL="$2";   shift 2 ;;
        --repo)     REPO_URL="$2"; shift 2 ;;
        --user)     DEPLOY_USER="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

log() { echo "[$(date -u +%T)] $*"; }

# ── 1. System packages ────────────────────────────────────────────────
log "Updating apt and installing base packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    lsb-release \
    git \
    cron \
    certbot \
    python3-certbot-nginx \
    openssh-client \
    jq

# ── 2. Docker CE ──────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    log "Installing Docker CE..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    log "Docker CE installed: $(docker --version)"
else
    log "Docker already installed: $(docker --version)"
fi

# ── 3. Docker Compose v2 ──────────────────────────────────────────────
if ! docker compose version &>/dev/null 2>&1; then
    log "Installing Docker Compose plugin..."
    apt-get install -y docker-compose-plugin
fi
log "Docker Compose: $(docker compose version)"

# ── 4. Deploy user ────────────────────────────────────────────────────
if ! id "$DEPLOY_USER" &>/dev/null; then
    log "Creating deploy user: $DEPLOY_USER"
    useradd -m -s /bin/bash "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
log "Deploy user $DEPLOY_USER added to docker group"

# ── 5. Application directory ──────────────────────────────────────────
mkdir -p "$APP_DIR"
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

# ── 6. Vault directory ────────────────────────────────────────────────
mkdir -p "$VAULT_DIR"
chown "$DEPLOY_USER:$DEPLOY_USER" "$VAULT_DIR"

# Clone or update vault repo
if [[ -n "$REPO_URL" ]]; then
    if [[ -d "$VAULT_DIR/.git" ]]; then
        log "Updating vault repo..."
        sudo -u "$DEPLOY_USER" git -C "$VAULT_DIR" pull --rebase
    else
        log "Cloning vault repo..."
        sudo -u "$DEPLOY_USER" git clone "$REPO_URL" "$VAULT_DIR"
    fi
fi

# ── 7. SSH deploy key ─────────────────────────────────────────────────
SSH_DIR="/home/$DEPLOY_USER/.ssh"
mkdir -p "$SSH_DIR"
chown "$DEPLOY_USER:$DEPLOY_USER" "$SSH_DIR"
chmod 700 "$SSH_DIR"

if [[ ! -f "$SSH_DIR/ai_employee_deploy_key" ]]; then
    log "Generating SSH deploy key for git push..."
    sudo -u "$DEPLOY_USER" ssh-keygen -t ed25519 \
        -C "ai-employee-cloud@$(hostname)" \
        -f "$SSH_DIR/ai_employee_deploy_key" \
        -N ""
    log "Deploy key created: $SSH_DIR/ai_employee_deploy_key.pub"
    log "Add the public key to your git repository's deploy keys:"
    cat "$SSH_DIR/ai_employee_deploy_key.pub"
fi

# ── 8. Let's Encrypt certificate ──────────────────────────────────────
if [[ -n "$DOMAIN" && -n "$EMAIL" ]]; then
    if [[ ! -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
        log "Obtaining Let's Encrypt certificate for $DOMAIN..."
        certbot certonly --standalone \
            --non-interactive \
            --agree-tos \
            --email "$EMAIL" \
            -d "$DOMAIN" \
            --pre-hook "docker compose -f $APP_DIR/docker/docker-compose.yml stop nginx || true" \
            --post-hook "docker compose -f $APP_DIR/docker/docker-compose.yml start nginx || true"
    else
        log "Certificate already exists for $DOMAIN"
    fi

    # Auto-renewal cron (runs twice daily)
    CRON_CMD="0 0,12 * * * root certbot renew --quiet --post-hook 'docker compose -f $APP_DIR/docker/docker-compose.yml exec nginx nginx -s reload'"
    if ! grep -q "certbot renew" /etc/crontab 2>/dev/null; then
        echo "$CRON_CMD" >> /etc/crontab
        log "Certbot renewal cron added"
    fi
fi

# ── 9. Git sync cron (cloud push) ─────────────────────────────────────
SYNC_CRON="*/1 * * * * $DEPLOY_USER cd $APP_DIR && python sync/vault_sync.py --role cloud --once >> /var/log/ai-employee-sync.log 2>&1"
if ! grep -q "vault_sync" /etc/crontab 2>/dev/null; then
    echo "# AI Employee vault sync (every minute)" >> /etc/crontab
    echo "$SYNC_CRON" >> /etc/crontab
    log "Vault sync cron added (every minute)"
fi

# ── 10. Log rotation ──────────────────────────────────────────────────
cat > /etc/logrotate.d/ai-employee << 'EOF'
/var/log/ai-employee*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
EOF
log "Log rotation configured"

# ── Summary ───────────────────────────────────────────────────────────
log "Setup complete."
log ""
log "Next steps:"
log "  1. Copy your .env.cloud file to $APP_DIR/"
log "  2. Update $APP_DIR/docker/nginx.conf with your domain"
log "  3. Add deploy key to git repo: cat $SSH_DIR/ai_employee_deploy_key.pub"
log "  4. cd $APP_DIR && docker compose -f docker/docker-compose.yml up -d"
