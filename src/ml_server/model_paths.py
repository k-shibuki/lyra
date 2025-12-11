"""
Model path management for offline loading.

This module reads model paths from the JSON file created during
Docker build, enabling true offline operation without any
HuggingFace API calls.
"""

import json
import os
from pathlib import Path
from typing import TypedDict

import structlog

logger = structlog.get_logger(__name__)


class ModelPaths(TypedDict):
    """Type definition for model paths."""

    embedding: str
    embedding_name: str
    reranker: str
    reranker_name: str
    nli_fast: str
    nli_fast_name: str
    nli_slow: str
    nli_slow_name: str


# Default path for model_paths.json (set in Dockerfile)
DEFAULT_MODEL_PATHS_FILE = "/app/models/model_paths.json"

# Cached model paths
_model_paths: ModelPaths | None = None


def get_model_paths() -> ModelPaths | None:
    """Get model paths from the JSON file.

    Returns:
        ModelPaths dictionary if file exists, None otherwise
    """
    global _model_paths

    if _model_paths is not None:
        return _model_paths

    model_paths_file = os.environ.get(
        "LANCET_ML__MODEL_PATHS_FILE", DEFAULT_MODEL_PATHS_FILE
    )

    if not Path(model_paths_file).exists():
        logger.warning(
            "Model paths file not found, will use model names",
            file=model_paths_file,
        )
        return None

    try:
        with open(model_paths_file) as f:
            _model_paths = json.load(f)

        logger.info("Model paths loaded", file=model_paths_file)
        return _model_paths

    except Exception as e:
        logger.error("Failed to load model paths", error=str(e))
        return None


def get_embedding_path() -> str:
    """Get embedding model path or name.

    Returns:
        Local path if available, otherwise model name from env
    """
    paths = get_model_paths()
    if paths and "embedding" in paths:
        return paths["embedding"]
    return os.environ.get("LANCET_ML__EMBEDDING_MODEL", "BAAI/bge-m3")


def get_reranker_path() -> str:
    """Get reranker model path or name.

    Returns:
        Local path if available, otherwise model name from env
    """
    paths = get_model_paths()
    if paths and "reranker" in paths:
        return paths["reranker"]
    return os.environ.get("LANCET_ML__RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")


def get_nli_fast_path() -> str:
    """Get NLI fast model path or name.

    Returns:
        Local path if available, otherwise model name from env
    """
    paths = get_model_paths()
    if paths and "nli_fast" in paths:
        return paths["nli_fast"]
    return os.environ.get(
        "LANCET_ML__NLI_FAST_MODEL", "cross-encoder/nli-deberta-v3-xsmall"
    )


def get_nli_slow_path() -> str:
    """Get NLI slow model path or name.

    Returns:
        Local path if available, otherwise model name from env
    """
    paths = get_model_paths()
    if paths and "nli_slow" in paths:
        return paths["nli_slow"]
    return os.environ.get(
        "LANCET_ML__NLI_SLOW_MODEL", "cross-encoder/nli-deberta-v3-small"
    )


def is_using_local_paths() -> bool:
    """Check if local model paths are being used.

    Returns:
        True if using local paths from JSON file
    """
    return get_model_paths() is not None

