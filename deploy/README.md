# Deploying to DigitalOcean (Ubuntu 24.04)

## Quick Start (one command)

```bash
curl -sSL https://raw.githubusercontent.com/Aistisnotes/anthropic-claude-code/main/deploy/setup.sh | sudo bash
```

Or clone manually and run:

```bash
git clone https://github.com/Aistisnotes/anthropic-claude-code.git
cd anthropic-claude-code
sudo bash deploy/setup.sh
```

The script will:
1. Install Docker and docker-compose
2. Clone the repo to `/opt/meta-ads-analyzer`
3. Prompt for API keys and a login password
4. Build and start the container (~5-10 min first run)
5. Configure UFW firewall (ports 22 and 8501 only)
6. Set up auto-restart on reboot via systemd

---

## Manual Setup

### 1. Provision a VPS

Recommended: DigitalOcean Droplet
- **Image:** Ubuntu 24.04 LTS
- **Size:** 4 GB RAM / 2 vCPU minimum (8 GB recommended for video transcription)
- **Region:** closest to you

### 2. SSH in and run setup

```bash
ssh root@YOUR_VPS_IP
bash <(curl -sSL https://raw.githubusercontent.com/Aistisnotes/anthropic-claude-code/main/deploy/setup.sh)
```

### 3. Access the app

```
http://YOUR_VPS_IP:8501
```

---

## Configuration

### Environment Variables

Set in `deploy/.env` (created by setup.sh, never committed to git):

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✓ | Anthropic API key for Claude analysis |
| `OPENAI_API_KEY` | ✓ | OpenAI API key for Whisper transcription |
| `TOOL_PASSWORD` | ✓ | Web UI login password |
| `TOOL_USERNAME` | — | Web UI username (default: `admin`) |
| `PDF_OUTPUT_DIR` | — | PDF output dir (default: `/app/output/reports`) |

### Transcription Backend

On the VPS (no Apple Silicon), the pipeline automatically uses:
1. `openai_api` if `OPENAI_API_KEY` is set (fastest, no GPU needed)
2. `openai-whisper` CPU fallback if key not set (slow on VPS)

Set in `config/default.toml`:
```toml
[transcription]
backend = "openai_api"
```

---

## Persistent Storage

Reports and PDFs are stored at `deploy/reports/` on the host, mounted into the container at `/app/output/reports`. They survive container restarts and rebuilds.

```
deploy/
  reports/        ← all brand reports, compare outputs, PDFs
  .env            ← API keys (600 permissions, never commit)
```

---

## Operations

### View logs
```bash
cd /opt/meta-ads-analyzer/deploy
docker compose logs -f
```

### Restart
```bash
docker compose restart
```

### Update to latest code
```bash
cd /opt/meta-ads-analyzer
git pull
cd deploy
docker compose build
docker compose up -d
```

### Stop
```bash
docker compose down
```

### Rebuild from scratch
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

---

## Security Notes

- Change `TOOL_PASSWORD` to a strong password before deploying publicly
- The UFW firewall allows only SSH (22) and Streamlit (8501)
- `.env` is created with `chmod 600` (owner read-only)
- For HTTPS, put nginx with Let's Encrypt in front of port 8501

### Optional: HTTPS with nginx

```bash
apt install nginx certbot python3-certbot-nginx
# Configure nginx to proxy to localhost:8501
certbot --nginx -d yourdomain.com
```

nginx config snippet:
```nginx
location / {
    proxy_pass http://localhost:8501;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```
