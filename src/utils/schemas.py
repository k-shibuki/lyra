"""
Pydantic schemas for inter-module data transfer.

Type-safe Pydantic model definitions for data exchange between modules.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.search.provider import SERPResult

from pydantic import BaseModel, Field


class AuthSessionData(BaseModel):
    """Session data stored in authentication queue.

    Saved after authentication completion and reused in subsequent requests.
    Used for human-in-the-loop authentication workflow (see ADR-0007).
    """

    domain: str = Field(..., description="Domain name (lowercase)")
    cookies: list[dict[str, Any]] = Field(
        default_factory=list, description="List of cookie information"
    )
    completed_at: str = Field(..., description="Authentication completion time (ISO format)")
    task_id: str | None = Field(None, description="Task ID (for task-scoped sessions)")

    class Config:
        json_schema_extra = {
            "example": {
                "domain": "example.com",
                "cookies": [
                    {
                        "name": "session_id",
                        "value": "abc123",
                        "domain": ".example.com",
                        "path": "/",
                        "expires": 1735689600.0,
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "Lax",
                    }
                ],
                "completed_at": "2025-12-11T10:00:00Z",
                "task_id": "task_123",
            }
        }


class StartSessionRequest(BaseModel):
    """Request for start_session().

    Used to initiate authentication session processing from the queue.
    """

    task_id: str = Field(..., description="Task ID")
    queue_ids: list[str] | None = Field(None, description="Specific queue ID list (optional)")
    priority_filter: str | None = Field(
        None, description="Priority filter ('high', 'medium', 'low')"
    )


class QueueItem(BaseModel):
    """Authentication queue item."""

    id: str = Field(..., description="Queue ID")
    url: str = Field(..., description="URL awaiting authentication")
    domain: str = Field(..., description="Domain name")
    auth_type: str = Field(..., description="Authentication type ('captcha', 'login', etc.)")
    priority: str = Field(..., description="Priority ('high', 'medium', 'low')")


class StartSessionResponse(BaseModel):
    """Response for start_session().

    Returns status and processed items from authentication queue.
    """

    ok: bool = Field(..., description="Success flag")
    session_started: bool = Field(..., description="Session started flag")
    count: int = Field(..., description="Number of processed items")
    items: list[QueueItem] = Field(default_factory=list, description="List of processed items")
    message: str | None = Field(None, description="Message (e.g., on error)")


class SessionTransferRequest(BaseModel):
    """Session transfer request.

    Transfers authenticated session (cookies, headers) to a target URL.
    Used for reusing authentication across related requests.
    """

    url: str = Field(..., description="Target URL")
    session_id: str | None = Field(
        None, description="Session ID (if not specified, searched by domain)"
    )
    include_conditional: bool = Field(
        default=True, description="Whether to include ETag/Last-Modified headers"
    )


class TransferResult(BaseModel):
    """Session transfer result.

    Contains transferred session headers and status.
    Maintains compatibility with existing TransferResult (dataclass).
    """

    ok: bool = Field(..., description="Transfer success flag")
    session_id: str | None = Field(None, description="Session ID (if available)")
    headers: dict[str, str] = Field(default_factory=dict, description="Transfer headers")
    reason: str | None = Field(None, description="Error reason (on failure)")

    class Config:
        json_schema_extra = {
            "example": {
                "ok": True,
                "session_id": "session_abc123",
                "headers": {
                    "Cookie": "session_id=abc123; csrf_token=xyz",
                    "If-None-Match": '"abc123"',
                    "If-Modified-Since": "Wed, 11 Dec 2024 10:00:00 GMT",
                    "User-Agent": "Mozilla/5.0 ...",
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                },
                "reason": None,
            }
        }


# =============================================================================
# Dynamic Weight Learning
# =============================================================================


class EngineHealthMetrics(BaseModel):
    """Engine health metrics for dynamic weight calculation.

    Per ADR-0006: EMA metrics from engine_health table used for weight adjustment.
    Includes time decay support for stale metrics.
    """

    engine: str = Field(..., description="Engine name")
    success_rate_1h: float = Field(
        default=1.0, ge=0.0, le=1.0, description="1-hour EMA success rate"
    )
    success_rate_24h: float = Field(
        default=1.0, ge=0.0, le=1.0, description="24-hour EMA success rate"
    )
    captcha_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="CAPTCHA encounter rate")
    median_latency_ms: float = Field(
        default=1000.0, ge=0.0, description="Median latency in milliseconds"
    )
    http_error_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="HTTP error rate (403/429)"
    )
    last_used_at: datetime | None = Field(
        None, description="Last usage timestamp for time decay calculation"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "engine": "duckduckgo",
                "success_rate_1h": 0.95,
                "success_rate_24h": 0.90,
                "captcha_rate": 0.05,
                "median_latency_ms": 800.0,
                "http_error_rate": 0.02,
                "last_used_at": "2025-12-15T10:00:00Z",
            }
        }


class LastmileCheckResult(BaseModel):
    """Result of lastmile slot check.

    Per ADR-0010: "Lastmile slot: Limited allocation targeting the final 10% of harvest rate,
    minimally opening Google/Brave with strict QPS, count, and time-of-day controls."

    Used to determine if lastmile engines should be used based on harvest rate.
    """

    should_use_lastmile: bool = Field(..., description="Whether to use lastmile engine")
    reason: str = Field(..., description="Reason for decision")
    harvest_rate: float = Field(ge=0.0, description="Useful fragments per page (can exceed 1.0)")
    threshold: float = Field(
        default=0.9, ge=0.0, le=1.0, description="Threshold for lastmile activation"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "should_use_lastmile": True,
                "reason": "Harvest rate 0.95 >= threshold 0.9",
                "harvest_rate": 0.95,
                "threshold": 0.9,
            }
        }


class DynamicWeightResult(BaseModel):
    """Result of dynamic weight calculation.

    Per ADR-0010, : Dynamic weight adjusted based on engine health
    with time decay for stale metrics.
    """

    engine: str = Field(..., description="Engine name")
    base_weight: float = Field(
        ..., ge=0.0, le=2.0, description="Base weight from config/engines.yaml"
    )
    dynamic_weight: float = Field(
        ..., ge=0.1, le=1.0, description="Adjusted weight after health-based calculation"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Metrics confidence (decays with time since last use)",
    )
    category: str | None = Field(
        None, description="Query category (general, academic, news, government, technical)"
    )
    metrics_used: EngineHealthMetrics | None = Field(
        None, description="Health metrics used for calculation"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "engine": "duckduckgo",
                "base_weight": 0.7,
                "dynamic_weight": 0.65,
                "confidence": 0.85,
                "category": "general",
                "metrics_used": {
                    "engine": "duckduckgo",
                    "success_rate_1h": 0.95,
                    "success_rate_24h": 0.90,
                    "captcha_rate": 0.05,
                    "median_latency_ms": 800.0,
                    "http_error_rate": 0.02,
                    "last_used_at": "2025-12-15T10:00:00Z",
                },
            }
        }


# =============================================================================
# Tor Daily Limit (Tor daily usage limit)
# =============================================================================


class TorUsageMetrics(BaseModel):
    """Daily Tor usage metrics for rate limiting.

    Per ADR-0006 and : Track global Tor usage to enforce daily limit (20%).
    Metrics are reset at the start of each new day.
    """

    total_requests: int = Field(default=0, ge=0, description="Total requests today (all types)")
    tor_requests: int = Field(default=0, ge=0, description="Tor-routed requests today")
    date: str = Field(..., description="Date in YYYY-MM-DD format for reset detection")

    @property
    def usage_ratio(self) -> float:
        """Calculate current Tor usage ratio.

        Returns:
            Ratio of tor_requests to total_requests (0.0 if no requests).
        """
        if self.total_requests == 0:
            return 0.0
        return self.tor_requests / self.total_requests

    class Config:
        json_schema_extra = {
            "example": {
                "total_requests": 100,
                "tor_requests": 15,
                "date": "2025-12-15",
            }
        }


class DomainTorMetrics(BaseModel):
    """Domain-specific Tor usage metrics.

    Per ADR-0006: Track per-domain Tor usage to enforce domain-specific limits.
    Each domain can have its own tor_usage_ratio limit in domain policy.
    """

    domain: str = Field(..., description="Domain name (lowercase)")
    total_requests: int = Field(default=0, ge=0, description="Total requests to this domain today")
    tor_requests: int = Field(
        default=0, ge=0, description="Tor-routed requests to this domain today"
    )
    date: str = Field(..., description="Date in YYYY-MM-DD format for reset detection")

    @property
    def usage_ratio(self) -> float:
        """Calculate domain Tor usage ratio.

        Returns:
            Ratio of tor_requests to total_requests (0.0 if no requests).
        """
        if self.total_requests == 0:
            return 0.0
        return self.tor_requests / self.total_requests

    class Config:
        json_schema_extra = {
            "example": {
                "domain": "example.com",
                "total_requests": 50,
                "tor_requests": 10,
                "date": "2025-12-15",
            }
        }


# =============================================================================
# Domain Daily Budget (Domain daily budget)
# =============================================================================


class DomainDailyBudget(BaseModel):
    """Daily budget state for a domain.

    Per ADR-0006: "Set time-of-day and daily budget limits" for IP block prevention.
    Tracks requests and pages consumed today for rate limiting.
    """

    domain: str = Field(..., description="Domain name (lowercase)")
    requests_today: int = Field(default=0, ge=0, description="Requests made to this domain today")
    pages_today: int = Field(default=0, ge=0, description="Pages fetched from this domain today")
    max_requests_per_day: int = Field(
        ..., ge=0, description="Maximum requests allowed per day (0 = unlimited)"
    )
    budget_pages_per_day: int = Field(..., ge=0, description="Page budget per day (0 = unlimited)")
    date: str = Field(..., description="Date in YYYY-MM-DD format for reset detection")

    @property
    def requests_remaining(self) -> int:
        """Calculate remaining requests for today.

        Returns:
            Remaining requests (int max if unlimited).
        """
        if self.max_requests_per_day == 0:
            return 2**31 - 1  # Effectively unlimited
        return max(0, self.max_requests_per_day - self.requests_today)

    @property
    def pages_remaining(self) -> int:
        """Calculate remaining pages for today.

        Returns:
            Remaining pages (int max if unlimited).
        """
        if self.budget_pages_per_day == 0:
            return 2**31 - 1  # Effectively unlimited
        return max(0, self.budget_pages_per_day - self.pages_today)

    class Config:
        json_schema_extra = {
            "example": {
                "domain": "example.com",
                "requests_today": 50,
                "pages_today": 25,
                "max_requests_per_day": 200,
                "budget_pages_per_day": 100,
                "date": "2025-12-15",
            }
        }


class DomainBudgetCheckResult(BaseModel):
    """Result of domain daily budget check.

    Per ADR-0006: Used by fetch_url to determine if request should proceed.
    Provides detailed information for logging and debugging.
    """

    allowed: bool = Field(..., description="Whether the request is allowed")
    reason: str | None = Field(None, description="Reason for denial (None if allowed)")
    requests_remaining: int = Field(..., ge=0, description="Remaining requests for today")
    pages_remaining: int = Field(..., ge=0, description="Remaining pages for today")

    class Config:
        json_schema_extra = {
            "example": {
                "allowed": True,
                "reason": None,
                "requests_remaining": 150,
                "pages_remaining": 75,
            }
        }


# =============================================================================
# Academic API Integration (J2)
# =============================================================================


class Author(BaseModel):
    """Paper author."""

    name: str = Field(..., description="Author name")
    affiliation: str | None = Field(None, description="Affiliation")
    orcid: str | None = Field(None, description="ORCID ID")


class Paper(BaseModel):
    """Academic paper metadata."""

    id: str = Field(..., description="Internal ID (provider:external_id format)")
    title: str = Field(..., description="Paper title")
    abstract: str | None = Field(None, description="Abstract")
    authors: list[Author] = Field(default_factory=list, description="Author list")
    year: int | None = Field(None, description="Publication year")
    published_date: date | None = Field(None, description="Publication date")
    doi: str | None = Field(None, description="DOI")
    arxiv_id: str | None = Field(None, description="arXiv ID")
    venue: str | None = Field(None, description="Journal/Conference name")
    citation_count: int = Field(default=0, ge=0, description="Citation count")
    reference_count: int = Field(default=0, ge=0, description="Reference count")
    is_open_access: bool = Field(default=False, description="Open access flag")
    oa_url: str | None = Field(None, description="Open access URL")
    pdf_url: str | None = Field(None, description="PDF URL")
    source_api: str = Field(..., description="Source API name")

    def to_serp_result(self) -> SERPResult:  # noqa: F821
        """Convert to SERPResult format."""
        # F821: SERPResult is imported inside the method to avoid circular imports
        from src.search.provider import SERPResult, SourceTag

        url = self.oa_url or (f"https://doi.org/{self.doi}" if self.doi else "")
        snippet = self.abstract[:500] if self.abstract else ""

        return SERPResult(
            title=self.title,
            url=url,
            snippet=snippet,
            engine=self.source_api,
            rank=0,
            date=str(self.year) if self.year else None,
            source_tag=SourceTag.ACADEMIC,
        )


class Citation(BaseModel):
    """Citation relationship."""

    citing_paper_id: str = Field(..., description="Citing paper ID")
    cited_paper_id: str = Field(..., description="Cited paper ID")
    context: str | None = Field(None, description="Citation context text")
    source_api: str | None = Field(
        default=None,
        description=(
            "Source API that returned this citation pair (semantic_scholar/openalex). "
            "For web-extracted citations, this is typically None and the edge uses "
            "citation_source='extraction'."
        ),
    )


class AcademicSearchResult(BaseModel):
    """Academic API search result."""

    papers: list[Paper] = Field(..., description="Paper list")
    total_count: int = Field(..., ge=0, description="Total count")
    next_cursor: str | None = Field(None, description="Pagination cursor")
    source_api: str = Field(..., description="Source API name")


class PaperIdentifier(BaseModel):
    """Paper identifier (multiple format support).

    Supported identifiers per ADR-0008 (S2 + OpenAlex two-pillar strategy):
    - DOI, PMID, arXiv ID (resolved via Semantic Scholar API)
    """

    doi: str | None = Field(None, description="DOI")
    pmid: str | None = Field(None, description="PubMed ID")
    arxiv_id: str | None = Field(None, description="arXiv ID")
    url: str | None = Field(None, description="URL (fallback)")
    needs_meta_extraction: bool = Field(
        default=False, description="Whether meta tag extraction is needed"
    )

    def get_canonical_id(self) -> str:
        """Return canonical ID (priority: DOI > PMID > arXiv > URL)."""
        if self.doi:
            return f"doi:{self.doi.lower().strip()}"
        if self.pmid:
            return f"pmid:{self.pmid}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        if self.url:
            return f"url:{hashlib.md5(self.url.encode()).hexdigest()[:12]}"
        return f"unknown:{uuid.uuid4().hex[:8]}"


class CanonicalEntry(BaseModel):
    """Canonical paper entry (SERP + Academic integration)."""

    canonical_id: str = Field(..., description="Canonical ID")
    paper: Paper | None = Field(None, description="Data from academic API")
    serp_results: list[Any] = Field(default_factory=list, description="SERP result list")
    source: str = Field(..., description="Source: 'api', 'serp', 'both'")

    @property
    def best_url(self) -> str:
        """Return the best URL."""
        if self.paper and self.paper.oa_url:
            return self.paper.oa_url
        if self.paper and self.paper.doi:
            return f"https://doi.org/{self.paper.doi}"
        if self.serp_results:
            from src.search.provider import SERPResult

            first_serp = self.serp_results[0]
            if isinstance(first_serp, SERPResult):
                return first_serp.url
            if isinstance(first_serp, dict):
                return cast(str, first_serp.get("url", ""))
        return ""

    @property
    def needs_fetch(self) -> bool:
        """Whether fetch/extract is needed."""
        # Fetch not needed if abstract is available from academic API
        return self.paper is None or not self.paper.abstract
