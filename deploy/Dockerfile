FROM python:3.11-slim

# ── System dependencies ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    wget \
    curl \
    gnupg \
    git \
    # Playwright chromium dependencies
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ── Python setup ───────────────────────────────────────────────────────────────
WORKDIR /app

# Copy dependency files first (layer caching)
COPY pyproject.toml ./
COPY requirements.txt ./

# Install Python dependencies (generic whisper for non-Apple-Silicon)
RUN pip install --no-cache-dir -e ".[generic]" \
    && pip install --no-cache-dir openai-whisper>=20231117

# Install Playwright and Chromium browser
RUN pip install --no-cache-dir playwright \
    && playwright install chromium \
    && playwright install-deps chromium

# ── Application code ───────────────────────────────────────────────────────────
COPY . .

# Re-install in editable mode now that all source is present
RUN pip install --no-cache-dir -e ".[generic]"

# ── Runtime directories ────────────────────────────────────────────────────────
RUN mkdir -p /app/output/reports /app/output/downloads /app/output/checkpoints

# ── Environment defaults ───────────────────────────────────────────────────────
ENV PDF_OUTPUT_DIR=/app/output/reports \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false

# ── Expose Streamlit port ──────────────────────────────────────────────────────
EXPOSE 8501

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.fileWatcherType=none"]
