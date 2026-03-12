#!/usr/bin/env bash
# Start ngrok tunnel for Creative Feedback Loop Analyzer
set -euo pipefail

PORT="${1:-8503}"
echo "Starting ngrok tunnel on port $PORT..."
ngrok http "$PORT" --log stdout
