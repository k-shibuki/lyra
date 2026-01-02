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

# Base directory for models (security boundary)
MODELS_BASE_DIR = Path("/app/models")


class ModelPaths(TypedDict):
    """Type definition for model paths."""

    embedding: str
    embedding_name: str
    nli: str
    nli_name: str


# Default path for model_paths.json (set in Dockerfile)
DEFAULT_MODEL_PATHS_FILE = "/app/models/model_paths.json"

# Cached model paths
_model_paths: ModelPaths | None = None


def _transform_host_to_container_path(path: str) -> str:
    """Transform host path to container path if needed.

    When models are downloaded on the host, paths are host-absolute
    (e.g., /home/user/lyra/models/huggingface/hub/...).
    In the container, models are mounted at /app/models/huggingface/.

    Args:
        path: Path string (may be host or container path)

    Returns:
        Container-relative path under /app/models/
    """
    # Look for the huggingface/hub pattern in the path
    # This is the common structure for HuggingFace cached models
    markers = ["huggingface/hub/", "models/huggingface/hub/"]
    for marker in markers:
        if marker in path:
            # Extract everything from 'hub/' onwards
            hub_index = path.find("hub/")
            if hub_index != -1:
                relative_part = path[hub_index:]  # "hub/models--BAAI--bge-m3/..."
                return str(MODELS_BASE_DIR / "huggingface" / relative_part)

    # If no transformation needed, return as-is
    return path


def _validate_and_sanitize_path(path: str, path_name: str) -> str:
    """Validate and sanitize a model path.

    Args:
        path: Path string to validate
        path_name: Name of the path (for error messages)

    Returns:
        Normalized absolute path

    Raises:
        ValueError: If path is invalid or outside allowed directory
    """
    try:
        # Transform host paths to container paths
        path = _transform_host_to_container_path(path)

        # Convert to Path and resolve to absolute path
        path_obj = Path(path).resolve()

        # Check if path is within MODELS_BASE_DIR
        try:
            path_obj.relative_to(MODELS_BASE_DIR.resolve())
        except ValueError as err:
            raise ValueError(f"Path {path_name} is outside allowed directory: {path}") from err

        # Check for path traversal attempts (should be caught by relative_to, but double-check)
        if ".." in str(path_obj):
            raise ValueError(f"Path traversal detected in {path_name}: {path}")

        return str(path_obj)

    except Exception as e:
        logger.error(
            "Path validation failed",
            path=path,
            path_name=path_name,
            error=str(e),
        )
        raise


def get_model_paths() -> ModelPaths | None:
    """Get model paths from the JSON file.

    Returns:
        ModelPaths dictionary if file exists, None otherwise
    """
    global _model_paths

    if _model_paths is not None:
        return _model_paths

    model_paths_file = os.environ.get("LYRA_ML__MODEL_PATHS_FILE", DEFAULT_MODEL_PATHS_FILE)

    if not Path(model_paths_file).exists():
        logger.warning(
            "Model paths file not found, will use model names",
            file=model_paths_file,
        )
        return None

    try:
        with open(model_paths_file) as f:
            raw_paths = json.load(f)

        # Validate and sanitize all paths
        validated_paths: ModelPaths = {
            "embedding": _validate_and_sanitize_path(raw_paths["embedding"], "embedding"),
            "embedding_name": raw_paths["embedding_name"],
            "nli": _validate_and_sanitize_path(raw_paths["nli"], "nli"),
            "nli_name": raw_paths["nli_name"],
        }

        _model_paths = validated_paths
        logger.info("Model paths loaded and validated", file=model_paths_file)
        return _model_paths

    except KeyError as e:
        logger.error("Missing required key in model paths", error=str(e))
        return None
    except ValueError as e:
        logger.error("Path validation failed", error=str(e))
        return None
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
    return os.environ.get("LYRA_ML__EMBEDDING_MODEL", "BAAI/bge-m3")


def get_nli_path() -> str:
    """Get NLI model path or name.

    Returns:
        Local path if available (validated), otherwise model name from env
    """
    paths = get_model_paths()
    if paths and "nli" in paths:
        return paths["nli"]
    return os.environ.get("LYRA_ML__NLI_MODEL", "cross-encoder/nli-deberta-v3-small")


def is_using_local_paths() -> bool:
    """Check if local model paths are being used.

    Returns:
        True if using local paths from JSON file
    """
    return get_model_paths() is not None
