#!/bin/bash
# Start Pain Point Analyzer with Cloudflare Tunnel
# Usage: ./start_tunnel.sh
#
# Environment variables:
#   STREAMLIT_PORT    — local port (default 8503, avoids conflict with other tools)
#   TOOL_USERNAME     — login username (default: admin)
#   TOOL_PASSWORD     — login password (bypass auth if unset)
#   ANTHROPIC_API_KEY — required for analysis

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PORT=${STREAMLIT_PORT:-8503}
APP_PY="$PROJECT_DIR/app.py"

STREAMLIT_PID=""
TUNNEL_PID=""

# ── Cleanup on exit ───────────────────────────────────────────────────────────
cleanup() {
    echo ""
    echo "Shutting down..."
    if [[ -n "$TUNNEL_PID" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
        kill "$TUNNEL_PID" 2>/dev/null
        wait "$TUNNEL_PID" 2>/dev/null || true
        echo "  Cloudflare tunnel stopped."
    fi
    if [[ -n "$STREAMLIT_PID" ]] && kill -0 "$STREAMLIT_PID" 2>/dev/null; then
        kill "$STREAMLIT_PID" 2>/dev/null
        wait "$STREAMLIT_PID" 2>/dev/null || true
        echo "  Streamlit stopped."
    fi
    echo "Done."
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

cd "$PROJECT_DIR"

# ── Pre-flight checks ────────────────────────────────────────────────────────
if ! command -v streamlit &>/dev/null; then
    echo "ERROR: streamlit not found. Install with: pip install streamlit"
    exit 1
fi

if ! command -v cloudflared &>/dev/null; then
    echo "ERROR: cloudflared not found."
    echo "  macOS:  brew install cloudflare/cloudflare/cloudflared"
    echo "  Linux:  https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    exit 1
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "WARNING: ANTHROPIC_API_KEY not set. Analysis will fail without it."
fi

# ── Kill anything already on our port ─────────────────────────────────────────
if lsof -ti :"$PORT" &>/dev/null; then
    echo "Killing existing process on port $PORT..."
    lsof -ti :"$PORT" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# ── Start Streamlit (absolute path to pain_point_analyzer/app.py) ─────────────
echo "Starting Pain Point Analyzer on port $PORT..."
echo "  App: $APP_PY"
streamlit run "$APP_PY" \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true &
STREAMLIT_PID=$!

# Wait for Streamlit to be ready
echo -n "Waiting for Streamlit..."
for i in $(seq 1 30); do
    if curl -s "http://localhost:$PORT/_stcore/health" &>/dev/null; then
        echo " ready."
        break
    fi
    if [[ $i -eq 30 ]]; then
        echo " timed out (30s). Continuing anyway."
    fi
    sleep 1
done

# ── Start Cloudflare tunnel ──────────────────────────────────────────────────
echo ""
echo "Starting Cloudflare tunnel -> http://localhost:$PORT"
echo "──────────────────────────────────────────────────"
cloudflared tunnel --url "http://localhost:$PORT" 2>&1 &
TUNNEL_PID=$!

sleep 5
echo ""
echo "──────────────────────────────────────────────────"
echo "Tunnel is running.  Press Ctrl+C to stop both."
echo "──────────────────────────────────────────────────"

# Block until either process exits
wait -n "$TUNNEL_PID" "$STREAMLIT_PID" 2>/dev/null || true
