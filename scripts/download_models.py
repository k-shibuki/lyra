#!/usr/bin/env python3
"""
Download ML models for Lyra.
This script is run during Docker build to include models in the image.

Models can be updated by:
1. Setting environment variables in .env (recommended):
   - LYRA_ML__EMBEDDING_MODEL
   - LYRA_ML__RERANKER_MODEL
   - LYRA_ML__NLI_MODEL
2. Or editing the MODEL_* variables below directly
3. Then running: make dev-rebuild

Default models:
- BAAI/bge-m3 (embedding, ~1.2GB)
- BAAI/bge-reranker-v2-m3 (reranker, ~1.2GB)
- cross-encoder/nli-deberta-v3-small (NLI, ~200MB)

IMPORTANT: Models are downloaded using huggingface_hub.snapshot_download()
and the local paths are saved to /app/models/model_paths.json for
offline loading.
"""

import json
import os
import sys

# Model names - edit these to update models
MODEL_EMBEDDING = os.environ.get("LYRA_ML__EMBEDDING_MODEL", "BAAI/bge-m3")
MODEL_RERANKER = os.environ.get("LYRA_ML__RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
MODEL_NLI = os.environ.get(
    "LYRA_ML__NLI_MODEL", "cross-encoder/nli-deberta-v3-small"
)

# Output path for model paths JSON
MODEL_PATHS_FILE = os.environ.get(
    "LYRA_ML__MODEL_PATHS_FILE", "/app/models/model_paths.json"
)


def download_model(repo_id: str, model_type: str) -> str:
    """Download a model using huggingface_hub and return the local path.

    Args:
        repo_id: HuggingFace model repository ID (e.g., "BAAI/bge-m3")
        model_type: Type description for logging

    Returns:
        Local path to the downloaded model
    """
    from huggingface_hub import snapshot_download
    import os

    print(f"  Downloading {model_type}: {repo_id}")

    # Check if offline mode is enabled
    offline_mode = os.environ.get("HF_HUB_OFFLINE", "0") == "1"
    
    if offline_mode:
        # In offline mode, try to get path from existing cache
        print(f"  Offline mode detected, checking local cache...")
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
    local_path = snapshot_download(
        repo_id=repo_id,
        # Use default cache dir (HF_HOME/hub)
        # This ensures consistency with HuggingFace's caching
    )

    print(f"  Done: {repo_id}")
    print(f"  Path: {local_path}")

    return local_path


def verify_model_loads(model_paths: dict) -> None:
    """Verify that all models can be loaded from local paths.

    Args:
        model_paths: Dictionary of model type to local path
    """
    import os
    
    print("\n" + "=" * 60)
    print("Verifying models load correctly from local paths")
    print("=" * 60)

    # Check if offline mode is enabled
    offline_mode = os.environ.get("HF_HUB_OFFLINE", "0") == "1"
    local_only = offline_mode

    # Embedding
    print("\n[Verify 1/3] Loading embedding model...")
    from sentence_transformers import SentenceTransformer

    SentenceTransformer(model_paths["embedding"], local_files_only=local_only)
    print("  OK: Embedding model loads successfully")

    # Reranker
    print("\n[Verify 2/3] Loading reranker model...")
    from sentence_transformers import CrossEncoder

    # CrossEncoder doesn't have local_files_only param, but respects HF_HUB_OFFLINE
    CrossEncoder(model_paths["reranker"])
    print("  OK: Reranker model loads successfully")

    # NLI
    print("\n[Verify 3/3] Loading NLI model...")
    from transformers import pipeline

    pipeline(
        "text-classification",
        model=model_paths["nli"],
        local_files_only=local_only,
    )
    print("  OK: NLI model loads successfully")


def main():
    print("=" * 60)
    print("Downloading ML models for Lyra")
    print("=" * 60)

    model_paths = {}

    # Download embedding model
    print(f"\n[1/3] Embedding model")
    model_paths["embedding"] = download_model(MODEL_EMBEDDING, "embedding")
    model_paths["embedding_name"] = MODEL_EMBEDDING

    # Download reranker model
    print(f"\n[2/3] Reranker model")
    model_paths["reranker"] = download_model(MODEL_RERANKER, "reranker")
    model_paths["reranker_name"] = MODEL_RERANKER

    # Download NLI model
    print(f"\n[3/3] NLI model")
    model_paths["nli"] = download_model(MODEL_NLI, "NLI")
    model_paths["nli_name"] = MODEL_NLI

    # Verify models load correctly
    verify_model_loads(model_paths)

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

    print("\n" + "=" * 60)
    print("All models downloaded and verified successfully!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: Failed to download models: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
