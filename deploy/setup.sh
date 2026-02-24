#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Meta Ads Analyzer — One-shot VPS setup for Ubuntu 24.04
# Run as root or with sudo:  bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="https://github.com/Aistisnotes/anthropic-claude-code.git"
INSTALL_DIR="/opt/meta-ads-analyzer"
SERVICE_USER="meta-ads"

echo "═══════════════════════════════════════════════════"
echo "  Meta Ads Analyzer — VPS Setup"
echo "  Ubuntu 24.04 · Docker · Streamlit"
echo "═══════════════════════════════════════════════════"
echo

# ── 1. System updates ─────────────────────────────────────────────────────────
echo "→ Updating system packages..."
apt-get update -qq && apt-get upgrade -y -qq

# ── 2. Install Docker ─────────────────────────────────────────────────────────
echo "→ Installing Docker..."
if ! command -v docker &>/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        | tee /etc/apt/sources.list.d/docker.list >/dev/null

    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "  ✓ Docker installed"
else
    echo "  ✓ Docker already installed"
fi

# ── 3. Clone repo ─────────────────────────────────────────────────────────────
echo "→ Cloning repository to $INSTALL_DIR..."
if [ -d "$INSTALL_DIR" ]; then
    echo "  Directory exists — pulling latest..."
    git -C "$INSTALL_DIR" pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# ── 4. Collect API keys ───────────────────────────────────────────────────────
echo
echo "─── API Keys ───────────────────────────────────────"
read -rp "  ANTHROPIC_API_KEY: " ANTHROPIC_API_KEY
read -rp "  OPENAI_API_KEY: " OPENAI_API_KEY
echo
read -rp "  TOOL_PASSWORD (login password for the web UI): " TOOL_PASSWORD
read -rp "  TOOL_USERNAME [admin]: " TOOL_USERNAME
TOOL_USERNAME="${TOOL_USERNAME:-admin}"
echo "────────────────────────────────────────────────────"

# ── 5. Write .env file ────────────────────────────────────────────────────────
echo "→ Writing deploy/.env..."
cat > "$INSTALL_DIR/deploy/.env" <<EOF
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
OPENAI_API_KEY=$OPENAI_API_KEY
TOOL_USERNAME=$TOOL_USERNAME
TOOL_PASSWORD=$TOOL_PASSWORD
EOF
chmod 600 "$INSTALL_DIR/deploy/.env"
echo "  ✓ .env written"

# ── 6. Create persistent reports directory ────────────────────────────────────
mkdir -p "$INSTALL_DIR/deploy/reports"
echo "  ✓ Reports volume directory created at $INSTALL_DIR/deploy/reports"

# ── 7. Build and start containers ─────────────────────────────────────────────
echo "→ Building Docker image (this takes 5-10 minutes on first run)..."
cd "$INSTALL_DIR/deploy"
docker compose --env-file .env build

echo "→ Starting container..."
docker compose --env-file .env up -d
echo "  ✓ Container started"

# ── 8. Firewall ───────────────────────────────────────────────────────────────
echo "→ Configuring UFW firewall..."
if command -v ufw &>/dev/null; then
    ufw --force enable
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow 22/tcp comment "SSH"
    ufw allow 8501/tcp comment "Meta Ads Analyzer"
    ufw reload
    echo "  ✓ Firewall: SSH (22) and app (8501) open, all else blocked"
else
    echo "  ⚠ ufw not found — install manually: apt install ufw"
fi

# ── 9. Auto-restart on reboot (systemd) ──────────────────────────────────────
echo "→ Configuring auto-restart on reboot..."
cat > /etc/systemd/system/meta-ads-analyzer.service <<EOF
[Unit]
Description=Meta Ads Analyzer (Docker Compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$INSTALL_DIR/deploy
ExecStart=/usr/bin/docker compose --env-file .env up -d
ExecStop=/usr/bin/docker compose --env-file .env down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable meta-ads-analyzer
echo "  ✓ Auto-restart on reboot enabled"

# ── 10. Get server IP ─────────────────────────────────────────────────────────
SERVER_IP=$(curl -s4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo
echo "═══════════════════════════════════════════════════"
echo "  ✓ Setup complete!"
echo
echo "  Access URL:  http://$SERVER_IP:8501"
echo "  Username:    $TOOL_USERNAME"
echo "  Reports:     $INSTALL_DIR/deploy/reports/"
echo
echo "  Useful commands:"
echo "    docker compose -f $INSTALL_DIR/deploy/docker-compose.yml logs -f"
echo "    docker compose -f $INSTALL_DIR/deploy/docker-compose.yml restart"
echo "═══════════════════════════════════════════════════"
