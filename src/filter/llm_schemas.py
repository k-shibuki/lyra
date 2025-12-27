"""Pydantic schemas for LLM output validation.

These schemas define the expected structure of LLM responses.
Lenient mode is used by default:
- Missing optional fields get defaults
- Type coercion is applied (e.g., "0.8" -> 0.8)
- Invalid items in lists are skipped, not rejected

Per docs/review-prompt-templates.md Phase 2.
"""

from pydantic import BaseModel, Field, field_validator


class ExtractedFact(BaseModel):
    """Schema for extracted facts from extract_facts.j2."""

    fact: str = Field(..., min_length=1, description="The factual statement")
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score 0.0-1.0",
    )
    evidence_type: str = Field(
        default="observation",
        description="Type: statistic, citation, or observation",
    )

    @field_validator("evidence_type")
    @classmethod
    def validate_evidence_type(cls, v: str) -> str:
        """Normalize evidence type to allowed values."""
        allowed = {"statistic", "citation", "observation"}
        v_lower = v.lower().strip()
        if v_lower in allowed:
            return v_lower
        return "observation"  # Default fallback

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, v: float | str | int) -> float:
        """Coerce confidence to float and clamp to [0, 1]."""
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                return 0.5
        return max(0.0, min(1.0, float(v)))


class ExtractedClaim(BaseModel):
    """Schema for extracted claims from extract_claims.j2."""

    claim: str = Field(..., min_length=1, description="The claim text")
    type: str = Field(
        default="fact",
        description="Claim type: fact, opinion, or prediction",
    )
    relevance_to_query: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Relevance to research question 0.0-1.0",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score 0.0-1.0",
    )

    @field_validator("type")
    @classmethod
    def validate_claim_type(cls, v: str) -> str:
        """Normalize claim type to allowed values."""
        allowed = {"fact", "opinion", "prediction"}
        v_lower = v.lower().strip()
        if v_lower in allowed:
            return v_lower
        return "fact"

    @field_validator("relevance_to_query", "confidence", mode="before")
    @classmethod
    def coerce_score(cls, v: float | str | int) -> float:
        """Coerce score to float and clamp to [0, 1]."""
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                return 0.5
        return max(0.0, min(1.0, float(v)))


class DensityClaim(BaseModel):
    """Schema for claims in densify/initial_summary output."""

    text: str = Field(..., min_length=1, description="Claim text")
    source_indices: list[int] = Field(
        default_factory=list,
        description="Indices of source documents",
    )
    claim_type: str = Field(
        default="factual",
        description="Type: factual, causal, comparative, temporal, quantitative",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("claim_type")
    @classmethod
    def validate_claim_type(cls, v: str) -> str:
        """Normalize claim type."""
        allowed = {"factual", "causal", "comparative", "temporal", "quantitative"}
        v_lower = v.lower().strip()
        if v_lower in allowed:
            return v_lower
        return "factual"


class DensityMetrics(BaseModel):
    """Schema for density metrics in densify output."""

    entities_added: int = Field(default=0, ge=0)
    entities_total: int = Field(default=0, ge=0)
    compression_ratio: float = Field(default=1.0, ge=0.0)


class DenseSummaryOutput(BaseModel):
    """Schema for densify.j2 output."""

    summary: str = Field(..., min_length=1, description="Densified summary text")
    entities: list[str] = Field(default_factory=list)
    claims: list[DensityClaim] = Field(default_factory=list)
    density_metrics: DensityMetrics | None = None
    conflicts: list[str] = Field(default_factory=list)


class InitialSummaryOutput(BaseModel):
    """Schema for initial_summary.j2 output."""

    summary: str = Field(..., min_length=1, description="Initial summary text")
    entities: list[str] = Field(default_factory=list)
    claims: list[DensityClaim] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class QualityAssessmentOutput(BaseModel):
    """Schema for quality_assessment.j2 output."""

    quality_score: float = Field(default=0.5, ge=0.0, le=1.0)
    is_ai_generated: bool = Field(default=False)
    is_spam: bool = Field(default=False)
    is_aggregator: bool = Field(default=False)
    academic_relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_density: str = Field(default="medium")
    reason: str = Field(default="")

    @field_validator("quality_score", "academic_relevance", mode="before")
    @classmethod
    def coerce_score(cls, v: float | str | int) -> float:
        """Coerce score to float and clamp to [0, 1]."""
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                return 0.5
        return max(0.0, min(1.0, float(v)))

    @field_validator("evidence_density")
    @classmethod
    def validate_evidence_density(cls, v: str) -> str:
        """Normalize evidence density."""
        allowed = {"high", "medium", "low"}
        v_lower = v.lower().strip()
        if v_lower in allowed:
            return v_lower
        return "medium"

    @field_validator("is_ai_generated", "is_spam", "is_aggregator", mode="before")
    @classmethod
    def coerce_bool(cls, v: bool | str | int) -> bool:
        """Coerce to boolean."""
        if isinstance(v, str):
            return v.lower() in ("true", "yes", "1")
        return bool(v)


class DecomposedClaim(BaseModel):
    """Schema for decompose.j2 output items."""

    text: str = Field(..., min_length=1, description="Atomic claim text")
    polarity: str = Field(default="positive")
    granularity: str = Field(default="atomic")
    type: str = Field(default="factual")
    keywords: list[str] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)

    @field_validator("polarity")
    @classmethod
    def validate_polarity(cls, v: str) -> str:
        """Normalize polarity."""
        allowed = {"positive", "negative", "neutral"}
        v_lower = v.lower().strip()
        if v_lower in allowed:
            return v_lower
        return "positive"

    @field_validator("granularity")
    @classmethod
    def validate_granularity(cls, v: str) -> str:
        """Normalize granularity."""
        allowed = {"atomic", "composite"}
        v_lower = v.lower().strip()
        if v_lower in allowed:
            return v_lower
        return "atomic"

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Normalize claim type."""
        allowed = {
            "factual",
            "causal",
            "comparative",
            "definitional",
            "temporal",
            "quantitative",
        }
        v_lower = v.lower().strip()
        if v_lower in allowed:
            return v_lower
        return "factual"
