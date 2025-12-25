"""
Pydantic models for ML Server API.
"""

from pydantic import BaseModel, Field

# ============================================================
# Embedding Models
# ============================================================


class EmbedRequest(BaseModel):
    """Request model for text embedding."""

    texts: list[str] = Field(..., description="List of texts to embed")
    batch_size: int = Field(default=8, ge=1, le=64, description="Batch size for encoding")


class EmbedResponse(BaseModel):
    """Response model for text embedding."""

    embeddings: list[list[float]] = Field(..., description="List of embedding vectors")
    model: str = Field(..., description="Model name used")
    dimension: int = Field(..., description="Embedding dimension")


# ============================================================
# Reranker Models
# ============================================================


class RerankRequest(BaseModel):
    """Request model for reranking."""

    query: str = Field(..., description="Query text")
    documents: list[str] = Field(..., description="List of documents to rerank")
    top_k: int = Field(default=10, ge=1, le=100, description="Number of top results to return")


class RerankResult(BaseModel):
    """Single rerank result."""

    index: int = Field(..., description="Original document index")
    score: float = Field(..., description="Relevance score")


class RerankResponse(BaseModel):
    """Response model for reranking."""

    results: list[RerankResult] = Field(..., description="Ranked results")
    model: str = Field(..., description="Model name used")


# ============================================================
# NLI Models
# ============================================================


class NLIPair(BaseModel):
    """Single NLI pair."""

    pair_id: str = Field(default="", description="Pair identifier")
    premise: str = Field(..., description="Premise text")
    hypothesis: str = Field(..., description="Hypothesis text")


class NLIRequest(BaseModel):
    """Request model for NLI inference."""

    pairs: list[NLIPair] = Field(..., description="List of premise-hypothesis pairs")


class NLIResult(BaseModel):
    """Single NLI result."""

    pair_id: str = Field(..., description="Pair identifier")
    label: str = Field(..., description="Predicted label (supports/refutes/neutral)")
    confidence: float = Field(..., description="Prediction confidence")
    raw_label: str = Field(default="", description="Raw model label")


class NLIResponse(BaseModel):
    """Response model for NLI inference."""

    results: list[NLIResult] = Field(..., description="NLI results")
    model: str = Field(..., description="Model name used")


# ============================================================
# Health Check Models
# ============================================================


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str = Field(..., description="Server status")
    models_loaded: dict[str, bool] = Field(..., description="Model loading status")
    gpu_available: bool = Field(..., description="Whether GPU is available")
