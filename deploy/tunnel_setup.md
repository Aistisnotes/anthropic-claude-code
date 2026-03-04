# Cloudflare Tunnel — Permanent Setup with Custom Domain

Use this for a stable URL like `https://tool.yourdomain.com` instead of the
random `*.trycloudflare.com` URL from the quick tunnel.

**Prerequisites:** A domain managed by Cloudflare DNS.

---

## Step 1 — Authenticate

```bash
cloudflared tunnel login
```

This opens a browser. Select your Cloudflare zone (domain). A certificate is
saved to `~/.cloudflared/cert.pem`.

---

## Step 2 — Create the tunnel

```bash
cloudflared tunnel create meta-ads-tool
```

Note the **tunnel UUID** printed (e.g. `a1b2c3d4-...`). A credentials file is
saved to `~/.cloudflared/<UUID>.json`.

---

## Step 3 — Route DNS

Replace `tool.YOURDOMAIN.com` with your actual subdomain:

```bash
cloudflared tunnel route dns meta-ads-tool tool.YOURDOMAIN.com
```

This creates a CNAME record in Cloudflare DNS pointing to the tunnel.

---

## Step 4 — Create tunnel config

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: meta-ads-tool
credentials-file: /Users/YOUR_USER/.cloudflared/<UUID>.json

ingress:
  - hostname: tool.YOURDOMAIN.com
    service: http://localhost:8501
  - service: http_status:404
```

---

## Step 5 — Test the tunnel

With Streamlit already running on port 8501:

```bash
cloudflared tunnel run meta-ads-tool
```

Visit `https://tool.YOURDOMAIN.com` — Cloudflare provisions a TLS cert
automatically (no nginx/certbot needed).

---

## Step 6 — Run as a background service (macOS)

```bash
sudo cloudflared service install
sudo launchctl start com.cloudflare.cloudflared
```

This registers a LaunchDaemon that starts cloudflared on boot.

Check status:
```bash
sudo launchctl list | grep cloudflare
cloudflared tunnel info meta-ads-tool
```

---

## Step 6 (Linux/VPS) — systemd service

```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

Or add to the existing `meta-ads-analyzer.service` by extending the
`ExecStart` to start cloudflared after the Docker container comes up.

---

## Combined Docker + Tunnel (VPS)

Add cloudflared to `deploy/docker-compose.yml`:

```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: always
    command: tunnel --no-autoupdate run
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      - meta-ads-app
    network_mode: host
```

Get the tunnel token from the Cloudflare dashboard:
**Zero Trust → Networks → Tunnels → your tunnel → Configure → Docker**

Add `CLOUDFLARE_TUNNEL_TOKEN=...` to `deploy/.env`.

---

## Quick Reference

| Command | Purpose |
|---|---|
| `cloudflared tunnel list` | List tunnels |
| `cloudflared tunnel info meta-ads-tool` | Tunnel status |
| `cloudflared tunnel delete meta-ads-tool` | Delete tunnel |
| `cloudflared tunnel route dns --overwrite-dns meta-ads-tool tool.YOURDOMAIN.com` | Update DNS |
