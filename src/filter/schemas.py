"""
Pydantic schemas for cross-module contracts around EvidenceGraph.

These models are intentionally small and focused on the integration boundary:
- EvidenceGraph.calculate_claim_confidence() output shape
- Evidence items (type + time metadata)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceYears(BaseModel):
    """Year summary extracted from evidence nodes."""

    oldest: int | None = Field(None, description="Oldest year found in evidence (inclusive)")
    newest: int | None = Field(None, description="Newest year found in evidence (inclusive)")


class EvidenceItem(BaseModel):
    """A single evidence item returned by EvidenceGraph confidence calculation."""

    relation: Literal["supports", "refutes", "neutral"] = Field(..., description="Edge relation")
    source_id: str | None = Field(None, description="Evidence node object ID")
    source_type: Literal["claim", "fragment", "page"] | None = Field(
        None, description="Evidence node type"
    )
    year: int | str | None = Field(None, description="Year metadata if available")
    nli_confidence: float | None = Field(None, description="NLI confidence carried by the edge")
    source_domain_category: str | None = Field(
        None, description="Domain category derived from source side (if available)"
    )
    doi: str | None = Field(None, description="DOI (academic pages only)")
    venue: str | None = Field(None, description="Venue (academic pages only)")


class ClaimConfidenceAssessment(BaseModel):
    """Contract for EvidenceGraph.calculate_claim_confidence()."""

    confidence: float = Field(..., ge=0.0, le=1.0)
    uncertainty: float = Field(..., ge=0.0)
    controversy: float = Field(..., ge=0.0, le=1.0)
    supporting_count: int = Field(..., ge=0)
    refuting_count: int = Field(..., ge=0)
    neutral_count: int = Field(..., ge=0)
    independent_sources: int = Field(..., ge=0, description="Count of independent sources")
    alpha: float = Field(..., ge=0.0)
    beta: float = Field(..., ge=0.0)
    evidence_count: int = Field(..., ge=0)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    evidence_years: EvidenceYears = Field(
        default_factory=lambda: EvidenceYears(oldest=None, newest=None)
    )

    # Allow forward-compat fields while keeping strict types for known keys.
    extra: dict[str, Any] | None = Field(default=None, description="Optional extra fields")


# ============================================================================
# LLM/Ollama request contracts (integration boundary)
# ============================================================================


class OllamaRequestOptions(BaseModel):
    """Subset of Ollama request options used by Lyra."""

    temperature: float | None = None
    num_predict: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop: list[str] | None = None


class OllamaGenerateRequest(BaseModel):
    """Contract for Ollama /api/generate request payload as used by Lyra."""

    model: str
    prompt: str
    stream: bool = False
    system: str | None = None
    format: str | None = None
    options: OllamaRequestOptions = Field(default_factory=OllamaRequestOptions)


class OllamaChatMessage(BaseModel):
    """Contract for a single chat message in Ollama /api/chat as used by Lyra."""

    role: str
    content: str
    name: str | None = None


class OllamaChatRequest(BaseModel):
    """Contract for Ollama /api/chat request payload as used by Lyra."""

    model: str
    messages: list[OllamaChatMessage]
    stream: bool = False
    system: str | None = None
    format: str | None = None
    options: OllamaRequestOptions = Field(default_factory=OllamaRequestOptions)
