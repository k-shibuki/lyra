"""
Pydantic schemas for ML Server API.
"""

from pydantic import BaseModel, Field

# =============================================================================
# Health Check
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    models_loaded: dict[str, bool] = Field(default_factory=dict)


# =============================================================================
# Embedding
# =============================================================================


class EmbedRequest(BaseModel):
    """Embedding request."""

    texts: list[str] = Field(..., description="Texts to embed")
    batch_size: int = Field(default=8, ge=1, le=64)


class EmbedResponse(BaseModel):
    """Embedding response."""

    ok: bool = True
    embeddings: list[list[float]] = Field(default_factory=list)
    error: str | None = None


# =============================================================================
# Reranking
# =============================================================================


class RerankRequest(BaseModel):
    """Reranking request."""

    query: str = Field(..., description="Query text")
    documents: list[str] = Field(..., description="Documents to rerank")
    top_k: int = Field(default=10, ge=1, le=200)


class RerankResult(BaseModel):
    """Single rerank result."""

    index: int
    score: float


class RerankResponse(BaseModel):
    """Reranking response."""

    ok: bool = True
    results: list[RerankResult] = Field(default_factory=list)
    error: str | None = None


# =============================================================================
# NLI (Natural Language Inference)
# =============================================================================


class NLIPair(BaseModel):
    """Single NLI pair."""

    pair_id: str = Field(default="unknown")
    premise: str
    hypothesis: str


class NLIRequest(BaseModel):
    """NLI request."""

    pairs: list[NLIPair] = Field(..., description="Pairs to judge")


class NLIResult(BaseModel):
    """Single NLI result."""

    pair_id: str
    label: str  # supports, refutes, neutral
    confidence: float
    raw_label: str | None = None


class NLIResponse(BaseModel):
    """NLI response."""

    ok: bool = True
    results: list[NLIResult] = Field(default_factory=list)
    error: str | None = None
