# Lyra Development Container
# Python 3.14 + uv package manager

FROM python:3.14-slim-bookworm AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1

# Install uv (from official image)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

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
    # Editor for development
    vim \
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
    # For undetected-chromedriver / Selenium
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

# Install Rust (required for building sudachipy on Python 3.14)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && \
    . "$HOME/.cargo/env" && \
    rustc --version

# Install Google Chrome for undetected-chromedriver
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y --no-install-recommends google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy dependency files first for caching
# README.md is required by pyproject.toml (readme field) for uv run
COPY pyproject.toml uv.lock README.md ./

# Install Python dependencies with uv (MCP + browser + extraction + tor + dev + test)
# Note: PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 is set in ENV above for sudachipy build
RUN . "$HOME/.cargo/env" && \
    uv sync --frozen --no-install-project --extra mcp --extra browser --extra extraction --extra tor --extra dev --extra test

# Install Playwright browsers
RUN uv run playwright install chromium --with-deps

# Copy application code
COPY . .

# Install the project itself
RUN . "$HOME/.cargo/env" && \
    uv sync --frozen --extra mcp --extra browser --extra extraction --extra tor --extra dev --extra test

# Create necessary directories
RUN mkdir -p data/cache data/warc data/screenshots data/reports logs models

# Set Python path and ensure Rust is in PATH
ENV PYTHONPATH=/app \
    PATH="/root/.cargo/bin:${PATH}"

# Default command: run proxy server for hybrid mode
CMD ["uv", "run", "python", "-m", "src.proxy.server"]

# ---
# GPU-enabled variant (for systems with NVIDIA GPU)
# ---
FROM base AS gpu

# Install PyTorch with CUDA support
RUN uv pip install --system \
    torch --index-url https://download.pytorch.org/whl/cu121

# Note: HEALTHCHECK removed - not supported by Podman OCI format
