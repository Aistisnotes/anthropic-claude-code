#!/bin/bash
# Start Pain Point Analyzer with Cloudflare Tunnel
# Usage: ./start_tunnel.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Start Streamlit
PORT=${STREAMLIT_PORT:-8502}
echo "Starting Pain Point Analyzer on port $PORT..."

streamlit run app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true &
STREAMLIT_PID=$!

echo "Streamlit PID: $STREAMLIT_PID"

# Start Cloudflare tunnel if cloudflared is available
if command -v cloudflared &>/dev/null; then
    echo "Starting Cloudflare tunnel..."
    cloudflared tunnel --url "http://localhost:$PORT" &
    TUNNEL_PID=$!
    echo "Tunnel PID: $TUNNEL_PID"
fi

wait $STREAMLIT_PID
