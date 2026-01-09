#!/usr/bin/env python3
"""
Download ML models for Lyra.
This script downloads models to the host filesystem for persistence.

Models can be updated by:
1. Editing config/settings.yaml or config/local.yaml:
   - embedding.model_name
   - nli.model
2. Then running: make setup-ml-models

Default models:
- BAAI/bge-m3 (embedding, ~1.2GB)
- cross-encoder/nli-deberta-v3-small (NLI, ~200MB)

IMPORTANT: Models are downloaded using huggingface_hub.snapshot_download()
and the local paths are saved to models/model_paths.json for
offline loading.
"""

import json
import os
import sys
from pathlib import Path

# Model names - sourced from Lyra settings (config/settings.yaml + local.yaml)
try:
    from src.utils.config import get_settings

    _settings = get_settings()
    MODEL_EMBEDDING = _settings.embedding.model_name
    MODEL_NLI = _settings.nli.model
except Exception:
    # Fallback for early bootstrap before deps are installed
    MODEL_EMBEDDING = "BAAI/bge-m3"
    MODEL_NLI = "cross-encoder/nli-deberta-v3-small"

# Output path for model paths JSON (host-relative)
SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_MODELS_DIR = SCRIPT_DIR.parent / "models"
MODEL_PATHS_FILE = os.environ.get(
    "LYRA_ML__MODEL_PATHS_FILE",
    str(DEFAULT_MODELS_DIR / "model_paths.json")
)


def download_model(repo_id: str, model_type: str) -> str:
    """Download a model using huggingface_hub and return the local path.

    Args:
        repo_id: HuggingFace model repository ID (e.g., "BAAI/bge-m3")
        model_type: Type description for logging

    Returns:
        Local path to the downloaded model
    """
    import os

    from huggingface_hub import snapshot_download

    print(f"  Downloading {model_type}: {repo_id}")

    # Use HF_HOME if set, otherwise default to models/huggingface
    hf_home = os.environ.get("HF_HOME")
    if not hf_home:
        hf_home = str(DEFAULT_MODELS_DIR / "huggingface")
        os.environ["HF_HOME"] = hf_home

    # Check if offline mode is enabled
    offline_mode = os.environ.get("HF_HUB_OFFLINE", "0") == "1"

    if offline_mode:
        # In offline mode, try to get path from existing cache
        print("  Offline mode detected, checking local cache...")
        try:
            local_path = snapshot_download(
                repo_id=repo_id,
                local_files_only=True,
            )
            print(f"  Found in cache: {repo_id}")
            print(f"  Path: {local_path}")
            return local_path
        except Exception as e:
            print(f"  ERROR: Model not found in cache: {e}")
            raise

    # Online mode: download or get from cache
    # HF_HOME is set above, so models will be cached there
    local_path = snapshot_download(
        repo_id=repo_id,
        # Use HF_HOME/hub as cache dir
    )

    print(f"  Done: {repo_id}")
    print(f"  Path: {local_path}")

    return local_path


def verify_model_loads(model_paths: dict) -> bool:
    """Verify that all models can be loaded from local paths.

    Args:
        model_paths: Dictionary of model type to local path

    Returns:
        True if verification passed, False if skipped (dependencies not available)
    """
    import os

    # Check if ML dependencies are available (they won't be on host)
    try:
        from sentence_transformers import SentenceTransformer
        from transformers import pipeline
    except ImportError:
        print("\n" + "=" * 60)
        print("Skipping model verification (ML dependencies not installed)")
        print("Models will be verified when loaded in the container.")
        print("=" * 60)
        return False

    print("\n" + "=" * 60)
    print("Verifying models load correctly from local paths")
    print("=" * 60)

    # Check if offline mode is enabled
    offline_mode = os.environ.get("HF_HUB_OFFLINE", "0") == "1"
    local_only = offline_mode

    # Embedding
    print("\n[Verify 1/2] Loading embedding model...")
    SentenceTransformer(model_paths["embedding"], local_files_only=local_only)
    print("  OK: Embedding model loads successfully")

    # NLI
    print("\n[Verify 2/2] Loading NLI model...")
    pipeline(
        "text-classification",
        model=model_paths["nli"],
        local_files_only=local_only,
    )
    print("  OK: NLI model loads successfully")
    return True


def main():
    print("=" * 60)
    print("Downloading ML models for Lyra")
    print("=" * 60)

    model_paths = {}

    # Download embedding model
    print("\n[1/2] Embedding model")
    model_paths["embedding"] = download_model(MODEL_EMBEDDING, "embedding")
    model_paths["embedding_name"] = MODEL_EMBEDDING

    # Download NLI model
    print("\n[2/2] NLI model")
    model_paths["nli"] = download_model(MODEL_NLI, "NLI")
    model_paths["nli_name"] = MODEL_NLI

    # Save model paths to JSON file
    print("\n" + "=" * 60)
    print(f"Saving model paths to {MODEL_PATHS_FILE}")
    print("=" * 60)

    os.makedirs(os.path.dirname(MODEL_PATHS_FILE), exist_ok=True)
    with open(MODEL_PATHS_FILE, "w") as f:
        json.dump(model_paths, f, indent=2)

    print(f"\nModel paths saved to {MODEL_PATHS_FILE}")
    print("\nModel paths content:")
    print(json.dumps(model_paths, indent=2))

    # Verify models load correctly (skipped if ML dependencies not available)
    verified = verify_model_loads(model_paths)

    print("\n" + "=" * 60)
    if verified:
        print("All models downloaded and verified successfully!")
    else:
        print("All models downloaded successfully!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: Failed to download models: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
