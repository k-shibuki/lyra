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
# To update models: edit .env and run make dev-rebuild

ARG PYTHON_IMAGE=python:3.13-slim-bookworm
ARG TORCH_BACKEND=cu124

# Model versions (from .env via build args)
ARG LYRA_ML__EMBEDDING_MODEL=BAAI/bge-m3
ARG LYRA_ML__RERANKER_MODEL=BAAI/bge-reranker-v2-m3
ARG LYRA_ML__NLI_MODEL=cross-encoder/nli-deberta-v3-small

FROM ${PYTHON_IMAGE} AS builder

# Torch backend (e.g., cu124 for CUDA 12.4)
ARG TORCH_BACKEND=cu124

# Model versions (from .env via build args)
ARG LYRA_ML__EMBEDDING_MODEL=BAAI/bge-m3
ARG LYRA_ML__RERANKER_MODEL=BAAI/bge-reranker-v2-m3
ARG LYRA_ML__NLI_MODEL=cross-encoder/nli-deberta-v3-small

# Install uv (from official image)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Builder-only system deps (never shipped in final image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Virtual environment lives outside /app so we can copy it cleanly into runtime
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/models/huggingface \
    LYRA_ML__MODEL_PATHS_FILE=/app/models/model_paths.json \
    LYRA_ML__EMBEDDING_MODEL=${LYRA_ML__EMBEDDING_MODEL} \
    LYRA_ML__RERANKER_MODEL=${LYRA_ML__RERANKER_MODEL} \
    LYRA_ML__NLI_MODEL=${LYRA_ML__NLI_MODEL} \
    UV_TORCH_BACKEND=${TORCH_BACKEND}

RUN python -m venv "${VIRTUAL_ENV}"

# Copy dependency files first for caching
# README.md is required by pyproject.toml (readme field)
COPY pyproject.toml uv.lock README.md ./

# Install dependencies into the active venv (no project code yet)
RUN uv sync --frozen --no-dev --extra ml --active --no-editable --no-install-project

# Force CUDA-enabled PyTorch into the venv (avoid accidentally keeping a CPU wheel)
RUN uv pip install --python /opt/venv/bin/python --torch-backend ${TORCH_BACKEND} --upgrade --force-reinstall torch && \
    python -c "import torch; assert torch.version.cuda is not None, 'CUDA torch wheel is required'; print('torch', torch.__version__, 'cuda', torch.version.cuda)"

# Download models at build time (online)
RUN mkdir -p /app/models
COPY scripts/download_models.py /app/scripts/
RUN python /app/scripts/download_models.py && \
    test -f /app/models/model_paths.json || (echo "ERROR: model_paths.json not created" && exit 1) && \
    echo "Model paths file created successfully"

# Install the project itself into the venv (non-editable)
COPY src /app/src
RUN uv sync --frozen --no-dev --extra ml --active --no-editable


FROM ${PYTHON_IMAGE} AS gpu

# Runtime-only system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/models/huggingface \
    LYRA_ML__MODEL_PATHS_FILE=/app/models/model_paths.json \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/models /app/models
COPY --from=builder /app/src /app/src

ENV PYTHONPATH=/app

EXPOSE 8100

CMD ["python", "-m", "uvicorn", "src.ml_server.main:app", "--host", "0.0.0.0", "--port", "8100"]
