#!/usr/bin/env python3
"""
Download ML models for Lancet.
This script is run during Docker build to include models in the image.

Models can be updated by:
1. Editing the MODEL_* variables below
2. Running: ./scripts/dev.sh rebuild

Models downloaded:
- BAAI/bge-m3 (embedding, ~1.2GB)
- BAAI/bge-reranker-v2-m3 (reranker, ~1.2GB)
- cross-encoder/nli-deberta-v3-xsmall (NLI fast, ~100MB)
- cross-encoder/nli-deberta-v3-small (NLI slow, ~200MB)
"""

import os
import sys

# Model names - edit these to update models
MODEL_EMBEDDING = os.environ.get("LANCET_ML__EMBEDDING_MODEL", "BAAI/bge-m3")
MODEL_RERANKER = os.environ.get("LANCET_ML__RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
MODEL_NLI_FAST = os.environ.get("LANCET_ML__NLI_FAST_MODEL", "cross-encoder/nli-deberta-v3-xsmall")
MODEL_NLI_SLOW = os.environ.get("LANCET_ML__NLI_SLOW_MODEL", "cross-encoder/nli-deberta-v3-small")


def main():
    print("=" * 60)
    print("Downloading ML models for Lancet")
    print("=" * 60)
    
    # Embedding model
    print(f"\n[1/4] Downloading embedding model: {MODEL_EMBEDDING}")
    from sentence_transformers import SentenceTransformer
    SentenceTransformer(MODEL_EMBEDDING)
    print(f"      Done: {MODEL_EMBEDDING}")
    
    # Reranker model
    print(f"\n[2/4] Downloading reranker model: {MODEL_RERANKER}")
    from sentence_transformers import CrossEncoder
    CrossEncoder(MODEL_RERANKER)
    print(f"      Done: {MODEL_RERANKER}")
    
    # NLI fast model
    print(f"\n[3/4] Downloading NLI fast model: {MODEL_NLI_FAST}")
    from transformers import pipeline
    pipeline("text-classification", model=MODEL_NLI_FAST)
    print(f"      Done: {MODEL_NLI_FAST}")
    
    # NLI slow model
    print(f"\n[4/4] Downloading NLI slow model: {MODEL_NLI_SLOW}")
    pipeline("text-classification", model=MODEL_NLI_SLOW)
    print(f"      Done: {MODEL_NLI_SLOW}")
    
    print("\n" + "=" * 60)
    print("All models downloaded successfully!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: Failed to download models: {e}", file=sys.stderr)
        sys.exit(1)

