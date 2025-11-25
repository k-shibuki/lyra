"""
Filtering and evaluation module for Lancet.

Includes:
- Multi-stage ranking (BM25, embedding, reranking)
- LLM extraction
- NLI judgment
- Claim decomposition (§3.3.1)
- Evidence graph
- Deduplication
- Temporal consistency
"""

from src.filter.claim_decomposition import (
    AtomicClaim,
    ClaimDecomposer,
    ClaimGranularity,
    ClaimPolarity,
    ClaimType,
    DecompositionResult,
    decompose_question,
)

__all__ = [
    "AtomicClaim",
    "ClaimDecomposer",
    "ClaimGranularity",
    "ClaimPolarity",
    "ClaimType",
    "DecompositionResult",
    "decompose_question",
]

