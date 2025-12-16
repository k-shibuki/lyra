"""
Pydantic schemas for module间データ受け渡し.

モジュール間のデータ受け渡しを型安全にするためのPydanticモデル定義。
"""

import hashlib
import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field
from typing import Optional, Any


class AuthSessionData(BaseModel):
    """認証待ちキューで保存されたセッションデータ（問題3用）.
    
    認証完了後に保存され、後続リクエストで再利用される。
    """
    domain: str = Field(..., description="ドメイン名（小文字）")
    cookies: list[dict[str, Any]] = Field(default_factory=list, description="Cookie情報のリスト")
    completed_at: str = Field(..., description="認証完了時刻（ISO形式）")
    task_id: Optional[str] = Field(None, description="タスクID（タスクスコープセッションの場合）")
    
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
    """start_session()のリクエスト（問題5用）."""
    task_id: str = Field(..., description="タスクID")
    queue_ids: Optional[list[str]] = Field(None, description="特定のキューIDリスト（オプション）")
    priority_filter: Optional[str] = Field(None, description="優先度フィルタ（'high', 'medium', 'low'）")


class QueueItem(BaseModel):
    """認証待ちキューアイテム."""
    id: str = Field(..., description="キューID")
    url: str = Field(..., description="認証待ちURL")
    domain: str = Field(..., description="ドメイン名")
    auth_type: str = Field(..., description="認証タイプ（'captcha', 'login', etc.）")
    priority: str = Field(..., description="優先度（'high', 'medium', 'low'）")


class StartSessionResponse(BaseModel):
    """start_session()のレスポンス（問題5用）."""
    ok: bool = Field(..., description="成功フラグ")
    session_started: bool = Field(..., description="セッション開始フラグ")
    count: int = Field(..., description="処理アイテム数")
    items: list[QueueItem] = Field(default_factory=list, description="処理アイテムリスト")
    message: Optional[str] = Field(None, description="メッセージ（エラー時など）")


class SessionTransferRequest(BaseModel):
    """セッション転送リクエスト（問題12用）."""
    url: str = Field(..., description="ターゲットURL")
    session_id: Optional[str] = Field(None, description="セッションID（指定しない場合はドメインから検索）")
    include_conditional: bool = Field(default=True, description="ETag/Last-Modifiedヘッダーを含めるか")


class TransferResult(BaseModel):
    """セッション転送結果（問題12用）.
    
    既存のTransferResult（dataclass）と互換性を保つため、
    必要に応じて既存コードを移行する。
    """
    ok: bool = Field(..., description="転送成功フラグ")
    session_id: Optional[str] = Field(None, description="セッションID（利用可能な場合）")
    headers: dict[str, str] = Field(default_factory=dict, description="転送ヘッダー")
    reason: Optional[str] = Field(None, description="エラー理由（失敗時）")
    
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
    
    Per §3.1.4: EMA metrics from engine_health table used for weight adjustment.
    Includes time decay support for stale metrics.
    """
    engine: str = Field(..., description="Engine name")
    success_rate_1h: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="1-hour EMA success rate"
    )
    success_rate_24h: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="24-hour EMA success rate"
    )
    captcha_rate: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="CAPTCHA encounter rate"
    )
    median_latency_ms: float = Field(
        default=1000.0, ge=0.0,
        description="Median latency in milliseconds"
    )
    http_error_rate: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="HTTP error rate (403/429)"
    )
    last_used_at: Optional[datetime] = Field(
        None,
        description="Last usage timestamp for time decay calculation"
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
    
    Per §3.1.1: "ラストマイル・スロット: 回収率の最後の10%を狙う限定枠として
    Google/Braveを最小限開放（厳格なQPS・回数・時間帯制御）"
    
    Used to determine if lastmile engines should be used based on harvest rate.
    """
    should_use_lastmile: bool = Field(..., description="Whether to use lastmile engine")
    reason: str = Field(..., description="Reason for decision")
    harvest_rate: float = Field(ge=0.0, description="Useful fragments per page (can exceed 1.0)")
    threshold: float = Field(
        default=0.9, ge=0.0, le=1.0,
        description="Threshold for lastmile activation"
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
    
    Per §3.1.1, §4.6: Dynamic weight adjusted based on engine health
    with time decay for stale metrics.
    """
    engine: str = Field(..., description="Engine name")
    base_weight: float = Field(
        ..., ge=0.0, le=2.0,
        description="Base weight from config/engines.yaml"
    )
    dynamic_weight: float = Field(
        ..., ge=0.1, le=1.0,
        description="Adjusted weight after health-based calculation"
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Metrics confidence (decays with time since last use)"
    )
    category: Optional[str] = Field(
        None,
        description="Query category (general, academic, news, government, technical)"
    )
    metrics_used: Optional[EngineHealthMetrics] = Field(
        None,
        description="Health metrics used for calculation"
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
# Tor Daily Limit (Problem 10)
# =============================================================================


class TorUsageMetrics(BaseModel):
    """Daily Tor usage metrics for rate limiting.
    
    Per §4.3 and §7: Track global Tor usage to enforce daily limit (20%).
    Metrics are reset at the start of each new day.
    """
    total_requests: int = Field(
        default=0, ge=0,
        description="Total requests today (all types)"
    )
    tor_requests: int = Field(
        default=0, ge=0,
        description="Tor-routed requests today"
    )
    date: str = Field(
        ...,
        description="Date in YYYY-MM-DD format for reset detection"
    )
    
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
    
    Per §4.3: Track per-domain Tor usage to enforce domain-specific limits.
    Each domain can have its own tor_usage_ratio limit in domain policy.
    """
    domain: str = Field(..., description="Domain name (lowercase)")
    total_requests: int = Field(
        default=0, ge=0,
        description="Total requests to this domain today"
    )
    tor_requests: int = Field(
        default=0, ge=0,
        description="Tor-routed requests to this domain today"
    )
    date: str = Field(
        ...,
        description="Date in YYYY-MM-DD format for reset detection"
    )
    
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
# Domain Daily Budget (Problem 11)
# =============================================================================


class DomainDailyBudget(BaseModel):
    """Daily budget state for a domain.
    
    Per §4.3: "時間帯・日次の予算上限を設定" for IP block prevention.
    Tracks requests and pages consumed today for rate limiting.
    """
    domain: str = Field(..., description="Domain name (lowercase)")
    requests_today: int = Field(
        default=0, ge=0,
        description="Requests made to this domain today"
    )
    pages_today: int = Field(
        default=0, ge=0,
        description="Pages fetched from this domain today"
    )
    max_requests_per_day: int = Field(
        ..., ge=0,
        description="Maximum requests allowed per day (0 = unlimited)"
    )
    max_pages_per_day: int = Field(
        ..., ge=0,
        description="Maximum pages allowed per day (0 = unlimited)"
    )
    date: str = Field(
        ...,
        description="Date in YYYY-MM-DD format for reset detection"
    )
    
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
        if self.max_pages_per_day == 0:
            return 2**31 - 1  # Effectively unlimited
        return max(0, self.max_pages_per_day - self.pages_today)
    
    class Config:
        json_schema_extra = {
            "example": {
                "domain": "example.com",
                "requests_today": 50,
                "pages_today": 25,
                "max_requests_per_day": 200,
                "max_pages_per_day": 100,
                "date": "2025-12-15",
            }
        }


class DomainBudgetCheckResult(BaseModel):
    """Result of domain daily budget check.
    
    Per §4.3: Used by fetch_url() to determine if request should proceed.
    Provides detailed information for logging and debugging.
    """
    allowed: bool = Field(..., description="Whether the request is allowed")
    reason: Optional[str] = Field(
        None,
        description="Reason for denial (None if allowed)"
    )
    requests_remaining: int = Field(
        ..., ge=0,
        description="Remaining requests for today"
    )
    pages_remaining: int = Field(
        ..., ge=0,
        description="Remaining pages for today"
    )
    
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
    affiliation: Optional[str] = Field(None, description="Affiliation")
    orcid: Optional[str] = Field(None, description="ORCID ID")


class Paper(BaseModel):
    """Academic paper metadata."""
    id: str = Field(..., description="Internal ID (provider:external_id format)")
    title: str = Field(..., description="Paper title")
    abstract: Optional[str] = Field(None, description="Abstract")
    authors: list[Author] = Field(default_factory=list, description="Author list")
    year: Optional[int] = Field(None, description="Publication year")
    published_date: Optional[date] = Field(None, description="Publication date")
    doi: Optional[str] = Field(None, description="DOI")
    arxiv_id: Optional[str] = Field(None, description="arXiv ID")
    venue: Optional[str] = Field(None, description="Journal/Conference name")
    citation_count: int = Field(default=0, ge=0, description="Citation count")
    reference_count: int = Field(default=0, ge=0, description="Reference count")
    is_open_access: bool = Field(default=False, description="Open access flag")
    oa_url: Optional[str] = Field(None, description="Open access URL")
    pdf_url: Optional[str] = Field(None, description="PDF URL")
    source_api: str = Field(..., description="Source API name")
    
    def to_search_result(self) -> "SearchResult":
        """Convert to SearchResult format."""
        from src.search.provider import SearchResult, SourceTag
        
        url = self.oa_url or (f"https://doi.org/{self.doi}" if self.doi else "")
        snippet = self.abstract[:500] if self.abstract else ""
        
        return SearchResult(
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
    context: Optional[str] = Field(None, description="Citation context text")
    is_influential: bool = Field(default=False, description="Semantic Scholar influential citation")


class AcademicSearchResult(BaseModel):
    """Academic API search result."""
    papers: list[Paper] = Field(..., description="Paper list")
    total_count: int = Field(..., ge=0, description="Total count")
    next_cursor: Optional[str] = Field(None, description="Pagination cursor")
    source_api: str = Field(..., description="Source API name")


class PaperIdentifier(BaseModel):
    """Paper identifier (multiple format support)."""
    doi: Optional[str] = Field(None, description="DOI")
    pmid: Optional[str] = Field(None, description="PubMed ID")
    arxiv_id: Optional[str] = Field(None, description="arXiv ID")
    crid: Optional[str] = Field(None, description="CiNii Research ID")
    url: Optional[str] = Field(None, description="URL (fallback)")
    needs_meta_extraction: bool = Field(default=False, description="Whether meta tag extraction is needed")
    
    def get_canonical_id(self) -> str:
        """Return canonical ID (priority: DOI > PMID > arXiv > CRID > URL)."""
        if self.doi:
            return f"doi:{self.doi.lower().strip()}"
        if self.pmid:
            return f"pmid:{self.pmid}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        if self.crid:
            return f"crid:{self.crid}"
        if self.url:
            return f"url:{hashlib.md5(self.url.encode()).hexdigest()[:12]}"
        return f"unknown:{uuid.uuid4().hex[:8]}"


class CanonicalEntry(BaseModel):
    """Canonical paper entry (SERP + Academic integration)."""
    canonical_id: str = Field(..., description="Canonical ID")
    paper: Optional[Paper] = Field(None, description="Data from academic API")
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
            from src.search.provider import SearchResult
            first_serp = self.serp_results[0]
            if isinstance(first_serp, SearchResult):
                return first_serp.url
            if isinstance(first_serp, dict):
                return first_serp.get("url", "")
        return ""
    
    @property
    def needs_fetch(self) -> bool:
        """Whether fetch/extract is needed."""
        # Fetch not needed if abstract is available from academic API
        return self.paper is None or not self.paper.abstract
