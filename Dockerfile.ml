# Lyra ML Server Container
# Provides embedding, reranking, and NLI inference via FastAPI
# SECURITY: Runs on internal-only network (lyra-internal)
#
# Models are downloaded at build time for:
# - Zero-config deployment (no additional setup needed)
# - Security (container doesn't need internet access at runtime)
# - Fast startup (models already present)
#
# Model paths are saved to /app/models/model_paths.json for
# true offline loading (no HuggingFace API calls at runtime).
#
# To update models: edit .env and run ./scripts/dev.sh rebuild

FROM python:3.12-slim-bookworm AS base

# Model versions (from .env via build args)
ARG LYRA_ML__EMBEDDING_MODEL=BAAI/bge-m3
ARG LYRA_ML__RERANKER_MODEL=BAAI/bge-reranker-v2-m3
ARG LYRA_ML__NLI_FAST_MODEL=cross-encoder/nli-deberta-v3-xsmall
ARG LYRA_ML__NLI_SLOW_MODEL=cross-encoder/nli-deberta-v3-small

# Set environment variables (offline mode disabled during build for download)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/models/huggingface \
    LYRA_ML__MODEL_PATHS_FILE=/app/models/model_paths.json \
    LYRA_ML__EMBEDDING_MODEL=${LYRA_ML__EMBEDDING_MODEL} \
    LYRA_ML__RERANKER_MODEL=${LYRA_ML__RERANKER_MODEL} \
    LYRA_ML__NLI_FAST_MODEL=${LYRA_ML__NLI_FAST_MODEL} \
    LYRA_ML__NLI_SLOW_MODEL=${LYRA_ML__NLI_SLOW_MODEL}

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

# Create models directory
RUN mkdir -p /app/models

# Copy requirements for ML server
COPY requirements-ml.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-ml.txt

# Download models at build time
# This ensures models are available without internet access at runtime
# Model paths are saved to /app/models/model_paths.json
COPY scripts/download_models.py /app/scripts/
RUN python /app/scripts/download_models.py && \
    test -f /app/models/model_paths.json || (echo "ERROR: model_paths.json not created" && exit 1) && \
    echo "Model paths file created successfully"

# Copy ML server code
COPY src/ml_server /app/src/ml_server

# Enable offline mode for runtime (models already downloaded)
# Using local paths from model_paths.json, no HF API calls needed
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
