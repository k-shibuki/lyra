"""
Filtering and evaluation module for Lyra.

Includes:
- Multi-stage ranking (BM25, embedding with dynamic cutoff)
- LLM extraction
- NLI judgment
- Claim decomposition
- Claim timeline (ADR-0005)
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
from src.filter.claim_timeline import (
    ClaimTimeline,
    ClaimTimelineManager,
    TimelineEvent,
    TimelineEventType,
    get_claim_timeline,
    get_timeline_coverage,
    get_timeline_manager,
    integrate_wayback_into_timeline,
    record_confirmation,
    record_first_appeared,
    record_retraction,
)

__all__ = [
    # Claim decomposition
    "AtomicClaim",
    "ClaimDecomposer",
    "ClaimGranularity",
    "ClaimPolarity",
    "ClaimType",
    "DecompositionResult",
    "decompose_question",
    # Claim timeline
    "ClaimTimeline",
    "ClaimTimelineManager",
    "TimelineEvent",
    "TimelineEventType",
    "get_timeline_manager",
    "record_first_appeared",
    "record_confirmation",
    "record_retraction",
    "get_claim_timeline",
    "get_timeline_coverage",
    "integrate_wayback_into_timeline",
]
