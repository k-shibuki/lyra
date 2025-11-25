# Lancet Development Container
# Python 3.12 + CUDA support for GPU inference

FROM python:3.12-slim-bookworm AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build tools
    build-essential \
    gcc \
    g++ \
    # Git for version control
    git \
    # curl/wget for downloads
    curl \
    wget \
    gnupg \
    # For Playwright
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    # For undetected-chromedriver / Selenium (§4.3 fallback)
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxi6 \
    libxtst6 \
    # For PDF processing
    libmupdf-dev \
    # For Japanese font support
    fonts-noto-cjk \
    # Tor client
    tor \
    # Network tools
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome for undetected-chromedriver (§4.3 fallback)
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y --no-install-recommends google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data/cache data/warc data/screenshots data/reports logs models

# Set Python path
ENV PYTHONPATH=/app

# Default command
CMD ["python", "-m", "src.main", "mcp"]

# ---
# GPU-enabled variant (for systems with NVIDIA GPU)
# ---
FROM base AS gpu

# Install CUDA-related packages (if available)
# Note: For full GPU support, use nvidia/cuda base image
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cu121 || \
    pip install --no-cache-dir torch

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from src.utils.config import get_settings; print('OK')" || exit 1

