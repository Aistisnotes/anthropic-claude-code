#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Meta Ads Analyzer — Start Streamlit + Cloudflare Quick Tunnel
#
# Usage:
#   bash deploy/start_tunnel.sh                 # from project root
#   TOOL_PASSWORD=secret bash deploy/start_tunnel.sh
#
# The public URL is printed once cloudflared starts.
# Both processes are kept alive; Ctrl-C kills both.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PORT="${PORT:-8501}"

# ── Resolve binaries ──────────────────────────────────────────────────────────
STREAMLIT_BIN=""
for candidate in \
    "$PROJECT_ROOT/.venv/bin/streamlit" \
    "$(command -v streamlit 2>/dev/null || true)"; do
    if [ -x "$candidate" ]; then
        STREAMLIT_BIN="$candidate"
        break
    fi
done
if [ -z "$STREAMLIT_BIN" ]; then
    echo "✗ streamlit not found. Run: pip install streamlit" >&2
    exit 1
fi

CLOUDFLARED_BIN="$(command -v cloudflared 2>/dev/null || true)"
if [ -z "$CLOUDFLARED_BIN" ]; then
    echo "✗ cloudflared not found. Run: brew install cloudflared" >&2
    exit 1
fi

# ── Cleanup on exit ───────────────────────────────────────────────────────────
STREAMLIT_PID=""
TUNNEL_PID=""

cleanup() {
    echo ""
    echo "→ Shutting down..."
    [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null || true
    [ -n "$STREAMLIT_PID" ] && kill "$STREAMLIT_PID" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

# ── Start Streamlit if not already running ────────────────────────────────────
if curl -sf "http://localhost:$PORT/_stcore/health" >/dev/null 2>&1; then
    echo "✓ Streamlit already running on port $PORT"
else
    echo "→ Starting Streamlit on port $PORT..."
    cd "$PROJECT_ROOT"
    "$STREAMLIT_BIN" run app.py \
        --server.port "$PORT" \
        --server.headless true \
        --server.enableCORS false \
        --server.enableXsrfProtection false \
        --server.fileWatcherType none \
        &
    STREAMLIT_PID=$!

    # Wait for Streamlit to be ready (up to 30s)
    echo -n "  Waiting for Streamlit"
    for i in $(seq 1 30); do
        if curl -sf "http://localhost:$PORT/_stcore/health" >/dev/null 2>&1; then
            echo " ✓"
            break
        fi
        echo -n "."
        sleep 1
    done
    if ! curl -sf "http://localhost:$PORT/_stcore/health" >/dev/null 2>&1; then
        echo ""
        echo "✗ Streamlit failed to start" >&2
        exit 1
    fi
fi

# ── Start Cloudflare quick tunnel ─────────────────────────────────────────────
echo "→ Starting Cloudflare tunnel → http://localhost:$PORT"
echo "  (public URL will appear below in a few seconds)"
echo "────────────────────────────────────────────────────"

"$CLOUDFLARED_BIN" tunnel --url "http://localhost:$PORT" 2>&1 \
    | while IFS= read -r line; do
        echo "$line"
        # Highlight the public URL
        if echo "$line" | grep -q "trycloudflare.com"; then
            URL=$(echo "$line" | grep -o 'https://[^ ]*trycloudflare.com[^ ]*')
            echo ""
            echo "  ┌─────────────────────────────────────────────────┐"
            echo "  │  🌐  PUBLIC URL:                                 │"
            echo "  │  $URL"
            echo "  └─────────────────────────────────────────────────┘"
            echo ""
        fi
    done &
TUNNEL_PID=$!

# Keep running until Ctrl-C
wait $TUNNEL_PID
