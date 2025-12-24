"""
Shared data contracts for the research module.

This file defines Pydantic models that represent cross-module contracts.
In particular, it models the get_materials response as exposed via MCP after L7
sanitization (schema allowlist filtering).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MaterialsSource(BaseModel):
    """Source metadata attached to a claim."""

    url: str = Field(..., description="Source URL")
    title: str = Field("", description="Human readable title (heading context, etc.)")
    domain: str = Field("", description="Lowercased domain")
    domain_category: str | None = Field(None, description="Domain category if available")
    is_primary: bool = Field(False, description="Whether this source is treated as primary")


class EvidenceItem(BaseModel):
    """Evidence item returned from EvidenceGraph Bayesian calculation."""

    relation: str = Field(..., description="Relation type (supports/refutes/neutral)")
    source_id: str | None = Field(None, description="Source object ID")
    source_type: str | None = Field(None, description="Source node type (fragment/page/...)")
    year: int | str | None = Field(None, description="Year extracted from source metadata")
    nli_confidence: float | None = Field(None, description="NLI confidence if available")
    source_domain_category: str | None = Field(None, description="Domain category used for ranking")
    doi: str | None = Field(None, description="DOI if available (academic sources)")
    venue: str | None = Field(None, description="Venue/journal if available (academic sources)")


class EvidenceYears(BaseModel):
    """Summary of evidence years for temporal judgments."""

    oldest: int | None = Field(None, description="Oldest year among evidence (nullable)")
    newest: int | None = Field(None, description="Newest year among evidence (nullable)")


class MaterialsClaim(BaseModel):
    """Claim object returned by get_materials."""

    id: str = Field(..., description="Claim ID")
    text: str = Field("", description="Claim text")

    confidence: float = Field(..., description="Aggregated claim confidence")
    uncertainty: float = Field(0.0, description="Bayesian uncertainty")
    controversy: float = Field(0.0, description="Bayesian controversy")

    evidence_count: int = Field(0, description="Count of evidence edges for this claim")
    has_refutation: bool = Field(False, description="Whether a refuting edge exists")
    sources: list[MaterialsSource] = Field(default_factory=list, description="Source list")

    evidence: list[EvidenceItem] = Field(default_factory=list, description="Evidence items")
    evidence_years: EvidenceYears = Field(
        default_factory=lambda: EvidenceYears(oldest=None, newest=None),
        description="Evidence year summary",
    )

    claim_adoption_status: Literal["adopted", "pending", "not_adopted"] = Field(
        "adopted", description="Adoption status for filtering"
    )
    claim_rejection_reason: str | None = Field(
        None, description="Reason for rejection if not adopted"
    )


class MaterialsFragment(BaseModel):
    """Fragment object returned by get_materials."""

    id: str = Field(..., description="Fragment ID")
    text: str = Field("", description="Fragment text (truncated)")
    source_url: str = Field("", description="Source URL extracted from metadata")
    context: str = Field("", description="Context (heading, section, etc.)")
    is_primary: bool = Field(False, description="Whether this fragment is from a primary source")


class MaterialsSummary(BaseModel):
    """Summary object returned by get_materials."""

    total_claims: int = Field(0, ge=0, description="Total number of claims")
    verified_claims: int = Field(0, ge=0, description="Number of verified claims")
    refuted_claims: int = Field(0, ge=0, description="Number of refuted claims")
    primary_source_ratio: float = Field(
        0.0, ge=0.0, description="Primary source ratio among fragments"
    )


class EvidenceGraphPayload(BaseModel):
    """Evidence graph payload returned by get_materials when include_graph=True."""

    nodes: list[dict[str, Any]] = Field(
        default_factory=list, description="Graph nodes (opaque objects)"
    )
    edges: list[dict[str, Any]] = Field(
        default_factory=list, description="Graph edges (opaque objects)"
    )


class GetMaterialsResponse(BaseModel):
    """get_materials response as delivered to the client after L7 sanitization."""

    ok: bool = Field(..., description="Success flag")
    task_id: str = Field(..., description="Task ID")
    query: str = Field("", description="Original query")
    claims: list[MaterialsClaim] = Field(default_factory=list, description="Claims list")
    fragments: list[MaterialsFragment] = Field(default_factory=list, description="Fragments list")
    summary: MaterialsSummary = Field(..., description="Summary")
    evidence_graph: EvidenceGraphPayload | None = Field(None, description="Evidence graph payload")
    format: Literal["structured", "narrative"] | None = Field(None, description="Output format")
