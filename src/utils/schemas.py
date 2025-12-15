"""
Pydantic schemas for module间データ受け渡し.

モジュール間のデータ受け渡しを型安全にするためのPydanticモデル定義。
"""

from datetime import datetime
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
