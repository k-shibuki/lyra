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
# NLI Models
# ============================================================


class NLIPair(BaseModel):
    """Single NLI pair."""

    pair_id: str = Field(default="", description="Pair identifier")
    premise: str = Field(..., description="Premise text")
    nli_hypothesis: str = Field(
        ...,
        description="NLI hypothesis text (ADR-0017: renamed to avoid conflict with task.hypothesis)",
    )


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
