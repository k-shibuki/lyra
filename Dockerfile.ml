# Lancet ML Server Container
# Provides embedding, reranking, and NLI inference via FastAPI
# SECURITY: Runs on internal-only network (lancet-internal)
#
# Models are downloaded at build time for:
# - Zero-config deployment (no additional setup needed)
# - Security (container doesn't need internet access at runtime)
# - Fast startup (models already present)
#
# To update models: edit .env and run ./scripts/dev.sh rebuild

FROM python:3.12-slim-bookworm AS base

# Model versions (from .env via build args)
ARG LANCET_ML__EMBEDDING_MODEL=BAAI/bge-m3
ARG LANCET_ML__RERANKER_MODEL=BAAI/bge-reranker-v2-m3
ARG LANCET_ML__NLI_FAST_MODEL=cross-encoder/nli-deberta-v3-xsmall
ARG LANCET_ML__NLI_SLOW_MODEL=cross-encoder/nli-deberta-v3-small

# Set environment variables (offline mode disabled during build for download)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/models/huggingface \
    LANCET_ML__EMBEDDING_MODEL=${LANCET_ML__EMBEDDING_MODEL} \
    LANCET_ML__RERANKER_MODEL=${LANCET_ML__RERANKER_MODEL} \
    LANCET_ML__NLI_FAST_MODEL=${LANCET_ML__NLI_FAST_MODEL} \
    LANCET_ML__NLI_SLOW_MODEL=${LANCET_ML__NLI_SLOW_MODEL}

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build tools for Python packages
    build-essential \
    gcc \
    g++ \
    # curl for health checks
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements for ML server
COPY requirements-ml.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-ml.txt

# Download models at build time
# This ensures models are available without internet access at runtime
COPY scripts/download_models.py /app/scripts/
RUN python /app/scripts/download_models.py

# Copy ML server code
COPY src/ml_server /app/src/ml_server

# Enable offline mode for runtime (models already downloaded)
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PYTHONPATH=/app

# Expose port (internal network only)
EXPOSE 8100

# Run FastAPI server
CMD ["python", "-m", "uvicorn", "src.ml_server.main:app", "--host", "0.0.0.0", "--port", "8100"]

# ---
# GPU-enabled variant
# ---
FROM base AS gpu

# Install PyTorch with CUDA support
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cu121 || \
    pip install --no-cache-dir torch

# Re-install sentence-transformers to pick up GPU torch
RUN pip install --no-cache-dir --force-reinstall sentence-transformers transformers
