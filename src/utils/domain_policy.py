"""
Domain Policy Manager - Centralized domain policy management.

This module provides:
- Unified loading of domain policies from YAML configuration
- Hot-reload support for configuration changes
- Schema validation for policy definitions
- Runtime caching with efficient lookups

Per §17.2.1 of docs/IMPLEMENTATION_PLAN.md:
- Complete externalization of domain policies to config/domains.yaml
- Hot-reload support without restart
- Enhanced schema validation

References:
- §4.3 (Stealth/Anti-detection policies)
- §3.1.2 (Crawling strategies)
- §3.6 (Intervention/cooldown policies)
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================


class DomainCategory(str, Enum):
    """Domain category for ranking adjustment (§3.3 Trust Scoring, §4.4.1 L6).

    Categories (for ranking weight adjustment only, NOT for confidence calculation):
    - PRIMARY: Public institutions, standards bodies (iso.org, ietf.org)
    - GOVERNMENT: Government agencies (go.jp, gov)
    - ACADEMIC: Academic institutions (arxiv.org, ac.jp, pubmed)
    - TRUSTED: Trusted media, knowledge bases (wikipedia.org)
    - LOW: Verified low-trust (promoted from UNVERIFIED via L6 verification)
    - UNVERIFIED: Unknown domains (provisional use, pending verification)
    - BLOCKED: Excluded (dangerous patterns detected)

    Note: DomainCategory is used ONLY for ranking score adjustment (category_weight).
    It is NOT used for confidence calculation or verification decisions.
    """

    PRIMARY = "primary"
    GOVERNMENT = "government"
    ACADEMIC = "academic"
    TRUSTED = "trusted"
    LOW = "low"  # Verified low-trust (promoted via L6)
    UNVERIFIED = "unverified"  # Unknown, pending verification
    BLOCKED = "blocked"  # Excluded (dynamic block)


class SkipReason(str, Enum):
    """Reasons for skipping a domain."""

    SOCIAL_MEDIA = "social_media"
    LOW_QUALITY_AGGREGATOR = "low_quality_aggregator"
    AD_HEAVY = "ad_heavy"
    MANUAL_SKIP = "manual_skip"
    BLOCK_SCORE_HIGH = "block_score_high"
    PERSISTENT_CAPTCHA = "persistent_captcha"


# Category weights for ranking adjustment (§3.3 Trust Scoring, §4.4.1 L6)
# Used ONLY for ranking score adjustment, NOT for confidence calculation
CATEGORY_WEIGHTS: dict[DomainCategory, float] = {
    DomainCategory.PRIMARY: 1.0,
    DomainCategory.GOVERNMENT: 0.95,
    DomainCategory.ACADEMIC: 0.90,
    DomainCategory.TRUSTED: 0.75,
    DomainCategory.LOW: 0.40,  # Verified but low trust
    DomainCategory.UNVERIFIED: 0.30,  # Provisional use
    DomainCategory.BLOCKED: 0.0,  # Excluded from scoring
}


# =============================================================================
# Pydantic Schema Models
# =============================================================================


class DefaultPolicySchema(BaseModel):
    """Schema for default domain policy (config/domains.yaml: default_policy)."""

    qps: float = Field(default=0.2, ge=0.01, le=2.0, description="Requests per second limit")
    concurrent: int = Field(default=1, ge=1, le=10, description="Max concurrent requests")
    headful_ratio: float = Field(default=0.1, ge=0.0, le=1.0, description="Headful browser ratio")
    tor_allowed: bool = Field(default=True, description="Whether Tor routing is allowed")
    cooldown_minutes: int = Field(
        default=60, ge=1, le=1440, description="Cooldown after failure (min)"
    )
    max_retries: int = Field(default=3, ge=0, le=10, description="Max retry attempts")
    domain_category: DomainCategory = Field(
        default=DomainCategory.UNVERIFIED, description="Domain category"
    )
    # Daily budget limits (§4.3 - IP block prevention)
    max_requests_per_day: int = Field(
        default=200, ge=0, description="Max requests per day (0=unlimited)"
    )
    max_pages_per_day: int = Field(default=100, ge=0, description="Max pages per day (0=unlimited)")


class AllowlistEntrySchema(BaseModel):
    """Schema for allowlist domain entries."""

    domain: str = Field(..., description="Domain name (exact or suffix match)")
    domain_category: DomainCategory = Field(default=DomainCategory.UNVERIFIED)
    internal_search: bool = Field(default=False, description="Has usable internal search UI")
    qps: float | None = Field(default=None, ge=0.01, le=2.0)
    headful_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    tor_allowed: bool | None = Field(default=None)
    concurrent: int | None = Field(default=None, ge=1, le=10)
    cooldown_minutes: int | None = Field(default=None, ge=1, le=1440)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    # Daily budget limits (§4.3 - IP block prevention)
    max_requests_per_day: int | None = Field(
        default=None, ge=0, description="Max requests per day (0=unlimited)"
    )
    max_pages_per_day: int | None = Field(
        default=None, ge=0, description="Max pages per day (0=unlimited)"
    )

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        """Validate domain format."""
        if not v or len(v) < 2:
            raise ValueError("Domain must be at least 2 characters")
        return v.lower().strip()


class GraylistEntrySchema(BaseModel):
    """Schema for graylist domain entries (pattern-based)."""

    domain_pattern: str = Field(..., description="Domain pattern (supports glob wildcards)")
    domain_category: DomainCategory | None = Field(default=None)
    headful_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    cooldown_minutes: int | None = Field(default=None, ge=1, le=1440)
    qps: float | None = Field(default=None, ge=0.01, le=2.0)
    skip: bool = Field(default=False)
    reason: SkipReason | str | None = Field(default=None)

    @field_validator("domain_pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        """Validate domain pattern format."""
        if not v or len(v) < 2:
            raise ValueError("Pattern must be at least 2 characters")
        return v.lower().strip()


class UserOverrideEntrySchema(BaseModel):
    """Schema for user override entries (exact match only).

    User overrides allow manual policy adjustments for specific domains.
    These take precedence over allowlist/graylist entries but not denylist.
    Only exact domain matches are supported (no wildcards/patterns).
    """

    domain: str = Field(..., description="Domain name (exact match only, no patterns)")
    domain_category: DomainCategory | None = Field(default=None)
    qps: float | None = Field(default=None, ge=0.01, le=2.0)
    headful_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    tor_allowed: bool | None = Field(default=None)
    concurrent: int | None = Field(default=None, ge=1, le=10)
    cooldown_minutes: int | None = Field(default=None, ge=1, le=1440)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    max_requests_per_day: int | None = Field(default=None, ge=0)
    max_pages_per_day: int | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, description="Audit: reason for override")
    added_at: str | None = Field(default=None, description="Audit: date added (ISO format)")

    @field_validator("domain")
    @classmethod
    def validate_domain_exact_match(cls, v: str) -> str:
        """Validate domain is exact match (no wildcards/patterns)."""
        v = v.lower().strip()
        if not v or len(v) < 2:
            raise ValueError("Domain must be at least 2 characters")
        if "*" in v or v.startswith("."):
            raise ValueError(
                "user_overrides only supports exact domain match (no wildcards/patterns)"
            )
        return v


class DenylistEntrySchema(BaseModel):
    """Schema for denylist domain entries (always skip)."""

    domain_pattern: str = Field(..., description="Domain pattern (supports glob wildcards)")
    reason: SkipReason | str = Field(default=SkipReason.LOW_QUALITY_AGGREGATOR)

    @field_validator("domain_pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        """Validate domain pattern format."""
        if not v or len(v) < 2:
            raise ValueError("Pattern must be at least 2 characters")
        return v.lower().strip()


class CloudflareSiteSchema(BaseModel):
    """Schema for known Cloudflare/challenge sites."""

    domain_pattern: str = Field(..., description="Domain pattern")
    headful_required: bool = Field(default=True)
    tor_blocked: bool = Field(default=True)


class InternalSearchTemplateSchema(BaseModel):
    """Schema for internal search UI templates (§3.1.5)."""

    domain: str = Field(..., description="Target domain")
    search_input: str = Field(..., description="CSS selector for search input")
    search_button: str = Field(..., description="CSS selector for search button")
    results_selector: str = Field(..., description="CSS selector for results")

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        return v.lower().strip()


class LearningStateDomainSchema(BaseModel):
    """Schema for per-domain learning state."""

    block_score: float = Field(default=0.0, ge=0.0, le=100.0)
    captcha_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    success_rate_1h: float = Field(default=1.0, ge=0.0, le=1.0)
    success_rate_24h: float = Field(default=1.0, ge=0.0, le=1.0)
    headful_ratio: float = Field(default=0.1, ge=0.0, le=1.0)
    tor_success_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    last_captcha_at: datetime | None = None
    cooldown_until: datetime | None = None


class SearchEnginePolicySchema(BaseModel):
    """Schema for search engine policy settings (§3.1.4, §4.3)."""

    default_qps: float = Field(
        default=0.25, ge=0.05, le=1.0, description="Default QPS for search engines"
    )
    site_search_qps: float = Field(
        default=0.1, ge=0.01, le=0.5, description="Site-internal search QPS limit"
    )
    cooldown_min: int = Field(default=30, ge=1, le=1440, description="Minimum cooldown in minutes")
    cooldown_max: int = Field(default=120, ge=1, le=1440, description="Maximum cooldown in minutes")
    failure_threshold: int = Field(
        default=2, ge=1, le=10, description="Failures before circuit open"
    )

    @property
    def default_min_interval(self) -> float:
        """Get default minimum interval between requests in seconds."""
        return 1.0 / self.default_qps if self.default_qps > 0 else 4.0

    @property
    def site_search_min_interval(self) -> float:
        """Get site search minimum interval in seconds."""
        return 1.0 / self.site_search_qps if self.site_search_qps > 0 else 10.0


class PolicyBoundsEntrySchema(BaseModel):
    """Schema for a single policy bounds entry (§4.6)."""

    min: float = Field(default=0.0, description="Minimum value")
    max: float = Field(default=1.0, description="Maximum value")
    default: float = Field(default=0.5, description="Default value")
    step_up: float = Field(default=0.1, description="Step for increase")
    step_down: float = Field(default=0.1, description="Step for decrease")


class PolicyBoundsSchema(BaseModel):
    """Schema for policy auto-update bounds (§4.6)."""

    engine_weight: PolicyBoundsEntrySchema = Field(
        default_factory=lambda: PolicyBoundsEntrySchema(
            min=0.1, max=2.0, default=1.0, step_up=0.1, step_down=0.2
        )
    )
    engine_qps: PolicyBoundsEntrySchema = Field(
        default_factory=lambda: PolicyBoundsEntrySchema(
            min=0.1, max=0.5, default=0.25, step_up=0.05, step_down=0.1
        )
    )
    domain_qps: PolicyBoundsEntrySchema = Field(
        default_factory=lambda: PolicyBoundsEntrySchema(
            min=0.05, max=0.3, default=0.2, step_up=0.02, step_down=0.05
        )
    )
    domain_cooldown: PolicyBoundsEntrySchema = Field(
        default_factory=lambda: PolicyBoundsEntrySchema(
            min=30.0, max=240.0, default=60.0, step_up=30.0, step_down=15.0
        )
    )
    headful_ratio: PolicyBoundsEntrySchema = Field(
        default_factory=lambda: PolicyBoundsEntrySchema(
            min=0.0, max=0.5, default=0.1, step_up=0.05, step_down=0.05
        )
    )
    tor_usage_ratio: PolicyBoundsEntrySchema = Field(
        default_factory=lambda: PolicyBoundsEntrySchema(
            min=0.0, max=0.2, default=0.0, step_up=0.02, step_down=0.05
        )
    )
    browser_route_ratio: PolicyBoundsEntrySchema = Field(
        default_factory=lambda: PolicyBoundsEntrySchema(
            min=0.1, max=0.5, default=0.3, step_up=0.05, step_down=0.05
        )
    )


class DomainPolicyConfigSchema(BaseModel):
    """Root schema for domains.yaml configuration file."""

    default_policy: DefaultPolicySchema = Field(default_factory=DefaultPolicySchema)
    search_engine_policy: SearchEnginePolicySchema = Field(default_factory=SearchEnginePolicySchema)
    policy_bounds: PolicyBoundsSchema = Field(default_factory=PolicyBoundsSchema)
    allowlist: list[AllowlistEntrySchema] = Field(default_factory=list)
    user_overrides: list[UserOverrideEntrySchema] = Field(default_factory=list)
    graylist: list[GraylistEntrySchema] = Field(default_factory=list)
    denylist: list[DenylistEntrySchema] = Field(default_factory=list)
    cloudflare_sites: list[CloudflareSiteSchema] = Field(default_factory=list)
    internal_search_templates: dict[str, InternalSearchTemplateSchema] = Field(default_factory=dict)
    learning_state: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config(self) -> DomainPolicyConfigSchema:
        """Validate configuration consistency."""
        # Check for duplicate domains in allowlist
        domains = [e.domain for e in self.allowlist]
        if len(domains) != len(set(domains)):
            logger.warning("Duplicate domains found in allowlist")
        return self


# =============================================================================
# Domain Policy Data Classes
# =============================================================================


@dataclass
class DomainPolicy:
    """
    Resolved domain policy for a specific domain.

    This combines:
    - Default policy values
    - Allowlist/graylist overrides
    - Runtime learning state (from DB)
    """

    domain: str
    qps: float = 0.2
    concurrent: int = 1
    headful_ratio: float = 0.1
    tor_allowed: bool = True
    cooldown_minutes: int = 60
    max_retries: int = 3
    domain_category: DomainCategory = DomainCategory.UNVERIFIED
    internal_search: bool = False
    skip: bool = False
    skip_reason: str | None = None
    headful_required: bool = False
    tor_blocked: bool = False

    # Daily budget limits (§4.3 - IP block prevention)
    max_requests_per_day: int = 200
    max_pages_per_day: int = 100

    # Learning state (populated from DB)
    block_score: float = 0.0
    captcha_rate: float = 0.0
    success_rate_1h: float = 1.0
    success_rate_24h: float = 1.0
    tor_success_rate: float = 0.5
    last_captcha_at: datetime | None = None
    cooldown_until: datetime | None = None

    # Source information
    source: str = (
        "default"  # "user_override", "allowlist", "graylist", "denylist", "cloudflare", "default"
    )

    @property
    def category_weight(self) -> float:
        """Get category weight for ranking adjustment (§3.3)."""
        return CATEGORY_WEIGHTS.get(self.domain_category, 0.3)

    @property
    def min_request_interval(self) -> float:
        """Get minimum interval between requests in seconds."""
        return 1.0 / self.qps if self.qps > 0 else 5.0

    @property
    def is_in_cooldown(self) -> bool:
        """Check if domain is currently in cooldown."""
        if self.cooldown_until is None:
            return False
        return datetime.now(UTC) < self.cooldown_until

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "domain": self.domain,
            "qps": self.qps,
            "concurrent": self.concurrent,
            "headful_ratio": self.headful_ratio,
            "tor_allowed": self.tor_allowed,
            "cooldown_minutes": self.cooldown_minutes,
            "max_retries": self.max_retries,
            "domain_category": self.domain_category.value
            if isinstance(self.domain_category, DomainCategory)
            else self.domain_category,
            "internal_search": self.internal_search,
            "skip": self.skip,
            "skip_reason": self.skip_reason,
            "headful_required": self.headful_required,
            "tor_blocked": self.tor_blocked,
            "max_requests_per_day": self.max_requests_per_day,
            "max_pages_per_day": self.max_pages_per_day,
            "block_score": self.block_score,
            "captcha_rate": self.captcha_rate,
            "success_rate_1h": self.success_rate_1h,
            "success_rate_24h": self.success_rate_24h,
            "tor_success_rate": self.tor_success_rate,
            "last_captcha_at": self.last_captcha_at.isoformat() if self.last_captcha_at else None,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "source": self.source,
            "category_weight": self.category_weight,
            "min_request_interval": self.min_request_interval,
            "is_in_cooldown": self.is_in_cooldown,
        }


@dataclass
class InternalSearchTemplate:
    """Resolved internal search template."""

    domain: str
    search_input: str
    search_button: str
    results_selector: str


# =============================================================================
# Domain Policy Manager
# =============================================================================


class DomainPolicyManager:
    """
    Centralized manager for domain policies.

    Features:
    - Loads all policies from config/domains.yaml
    - Provides efficient lookups with caching
    - Supports hot-reload of configuration
    - Thread-safe for concurrent access

    Usage:
        manager = get_domain_policy_manager()
        policy = manager.get_policy("example.com")

        # Force reload
        manager.reload()

        # Check if domain should be skipped
        if manager.should_skip("spam-site.com"):
            ...
    """

    _instance: DomainPolicyManager | None = None
    _lock = threading.Lock()

    def __init__(
        self,
        config_path: Path | str | None = None,
        watch_interval: float = 30.0,
        enable_hot_reload: bool = True,
    ):
        """
        Initialize domain policy manager.

        Args:
            config_path: Path to domains.yaml. Defaults to config/domains.yaml.
            watch_interval: Interval (seconds) for checking file changes.
            enable_hot_reload: Whether to enable automatic hot-reload.
        """
        if config_path is None:
            config_path = Path("config/domains.yaml")
        self._config_path = Path(config_path)
        self._watch_interval = watch_interval
        self._enable_hot_reload = enable_hot_reload

        # Internal state
        self._config: DomainPolicyConfigSchema | None = None
        self._last_mtime: float = 0.0
        self._last_check: float = 0.0
        self._policy_cache: dict[str, DomainPolicy] = {}
        self._cache_lock = threading.RLock()

        # Callbacks for reload events
        self._reload_callbacks: list[Callable[[DomainPolicyConfigSchema], None]] = []

        # Initial load
        self._load_config()

    @classmethod
    def get_instance(cls, **kwargs: Any) -> DomainPolicyManager:
        """Get singleton instance of domain policy manager."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        if not self._config_path.exists():
            logger.warning(
                "Domain policy config not found, using defaults",
                path=str(self._config_path),
            )
            self._config = DomainPolicyConfigSchema()
            return

        try:
            with open(self._config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Parse internal_search_templates specially
            if "internal_search_templates" in data and isinstance(
                data["internal_search_templates"], dict
            ):
                templates = {}
                for name, template_data in data["internal_search_templates"].items():
                    if isinstance(template_data, dict):
                        templates[name] = InternalSearchTemplateSchema(**template_data)
                data["internal_search_templates"] = templates

            self._config = DomainPolicyConfigSchema(**data)
            self._last_mtime = self._config_path.stat().st_mtime

            # Clear cache on reload
            with self._cache_lock:
                self._policy_cache.clear()

            logger.info(
                "Domain policy config loaded",
                path=str(self._config_path),
                allowlist_count=len(self._config.allowlist),
                user_overrides_count=len(self._config.user_overrides),
                graylist_count=len(self._config.graylist),
                denylist_count=len(self._config.denylist),
            )

            # Notify callbacks
            for callback in self._reload_callbacks:
                try:
                    callback(self._config)
                except Exception as e:
                    logger.error("Reload callback failed", error=str(e))

        except yaml.YAMLError as e:
            logger.error(
                "Failed to parse domain policy YAML",
                error=str(e),
                path=str(self._config_path),
            )
            if self._config is None:
                self._config = DomainPolicyConfigSchema()
        except Exception as e:
            logger.error(
                "Failed to load domain policy config",
                error=str(e),
                path=str(self._config_path),
            )
            if self._config is None:
                self._config = DomainPolicyConfigSchema()

    def _check_reload(self) -> None:
        """Check if config file has changed and reload if needed."""
        if not self._enable_hot_reload:
            return

        now = time.time()
        if now - self._last_check < self._watch_interval:
            return

        self._last_check = now

        if not self._config_path.exists():
            return

        try:
            current_mtime = self._config_path.stat().st_mtime
            if current_mtime > self._last_mtime:
                logger.info("Domain policy config changed, reloading...")
                self._load_config()
        except OSError as e:
            logger.warning("Failed to check config file mtime", error=str(e))

    def reload(self) -> None:
        """Force reload configuration."""
        self._load_config()

    def add_reload_callback(self, callback: Callable[[DomainPolicyConfigSchema], None]) -> None:
        """Add callback to be called on config reload."""
        self._reload_callbacks.append(callback)

    def remove_reload_callback(self, callback: Callable[[DomainPolicyConfigSchema], None]) -> None:
        """Remove reload callback."""
        if callback in self._reload_callbacks:
            self._reload_callbacks.remove(callback)

    @property
    def config(self) -> DomainPolicyConfigSchema:
        """Get current configuration (with hot-reload check)."""
        self._check_reload()
        if self._config is None:
            self._load_config()
        # After _load_config(), _config is guaranteed to be non-None
        assert self._config is not None
        return self._config

    def get_default_policy(self) -> DefaultPolicySchema:
        """Get default policy configuration."""
        return self.config.default_policy

    def _normalize_domain(self, domain: str) -> str:
        """Normalize domain name for matching."""
        domain = domain.lower().strip()
        # Remove www. prefix for matching
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def _match_pattern(self, domain: str, pattern: str) -> bool:
        """
        Check if domain matches pattern.

        Supports:
        - Exact match: "example.com"
        - Glob wildcards: "*.example.com"
        - Suffix match: ".example.com" matches "sub.example.com"
        """
        domain = self._normalize_domain(domain)
        pattern = pattern.lower().strip()

        # Exact match
        if domain == pattern:
            return True

        # Glob pattern match
        if "*" in pattern:
            # Convert glob to regex for more precise matching
            # fnmatch doesn't handle subdomain matching well
            regex_pattern = pattern.replace(".", r"\.").replace("*", r"[^.]*")
            if pattern.startswith("*."):
                # *.example.com should match sub.example.com and sub.sub.example.com
                base_domain = pattern[2:]
                if domain == base_domain or domain.endswith("." + base_domain):
                    return True
            return bool(re.match(f"^{regex_pattern}$", domain))

        # Suffix match (e.g., ".go.jp" matches "example.go.jp")
        if pattern.startswith("."):
            return domain.endswith(pattern) or domain == pattern[1:]

        # Suffix match for exact domain (e.g., "go.jp" matches "example.go.jp")
        if domain.endswith("." + pattern):
            return True

        return False

    def get_policy(self, domain: str) -> DomainPolicy:
        """
        Get resolved policy for a domain.

        Resolution order:
        1. Denylist (skip=True)
        2. Cloudflare sites (headful_required=True)
        3. user_overrides (exact match only, highest priority for policy overrides)
        4. Allowlist (specific overrides)
        5. Graylist (pattern-based overrides)
        6. Default policy

        Args:
            domain: Domain name to look up.

        Returns:
            DomainPolicy with resolved values.
        """
        self._check_reload()
        domain = self._normalize_domain(domain)

        # Check cache first
        with self._cache_lock:
            if domain in self._policy_cache:
                return self._policy_cache[domain]

        config = self.config
        default = config.default_policy

        # Start with default policy
        policy: DomainPolicy = DomainPolicy(
            domain=domain,
            qps=default.qps,
            concurrent=default.concurrent,
            headful_ratio=default.headful_ratio,
            tor_allowed=default.tor_allowed,
            cooldown_minutes=default.cooldown_minutes,
            max_retries=default.max_retries,
            domain_category=default.domain_category,
            max_requests_per_day=default.max_requests_per_day,
            max_pages_per_day=default.max_pages_per_day,
            source="default",
        )

        # Check denylist first (highest priority for skipping)
        for deny_entry in config.denylist:
            if self._match_pattern(domain, deny_entry.domain_pattern):
                policy.skip = True
                policy.skip_reason = (
                    deny_entry.reason
                    if isinstance(deny_entry.reason, str)
                    else deny_entry.reason.value
                )
                policy.source = "denylist"
                with self._cache_lock:
                    self._policy_cache[domain] = policy
                return policy

        # Check cloudflare sites
        for cf_entry in config.cloudflare_sites:
            if self._match_pattern(domain, cf_entry.domain_pattern):
                policy.headful_required = cf_entry.headful_required
                policy.tor_blocked = cf_entry.tor_blocked
                if cf_entry.tor_blocked:
                    policy.tor_allowed = False
                policy.source = "cloudflare"
                break

        # Check user_overrides (exact match only, before allowlist)
        for override in config.user_overrides:
            if domain == override.domain:
                # Apply user override fields
                if override.domain_category is not None:
                    policy.domain_category = override.domain_category
                if override.qps is not None:
                    policy.qps = override.qps
                if override.headful_ratio is not None:
                    policy.headful_ratio = override.headful_ratio
                if override.tor_allowed is not None:
                    policy.tor_allowed = override.tor_allowed
                if override.concurrent is not None:
                    policy.concurrent = override.concurrent
                if override.cooldown_minutes is not None:
                    policy.cooldown_minutes = override.cooldown_minutes
                if override.max_retries is not None:
                    policy.max_retries = override.max_retries
                if override.max_requests_per_day is not None:
                    policy.max_requests_per_day = override.max_requests_per_day
                if override.max_pages_per_day is not None:
                    policy.max_pages_per_day = override.max_pages_per_day
                policy.source = "user_override"
                break

        # Check allowlist (exact and suffix match) if not already matched by user_override
        if policy.source != "user_override":
            for allow_entry in config.allowlist:
                if self._match_pattern(domain, allow_entry.domain):
                    # Apply allowlist overrides
                    if allow_entry.qps is not None:
                        policy.qps = allow_entry.qps
                    if allow_entry.headful_ratio is not None:
                        policy.headful_ratio = allow_entry.headful_ratio
                    if allow_entry.tor_allowed is not None:
                        policy.tor_allowed = allow_entry.tor_allowed
                    if allow_entry.concurrent is not None:
                        policy.concurrent = allow_entry.concurrent
                    if allow_entry.cooldown_minutes is not None:
                        policy.cooldown_minutes = allow_entry.cooldown_minutes
                    if allow_entry.max_retries is not None:
                        policy.max_retries = allow_entry.max_retries
                    # Daily budget limits (§4.3 - IP block prevention)
                    if allow_entry.max_requests_per_day is not None:
                        policy.max_requests_per_day = allow_entry.max_requests_per_day
                    if allow_entry.max_pages_per_day is not None:
                        policy.max_pages_per_day = allow_entry.max_pages_per_day

                    policy.domain_category = allow_entry.domain_category
                    policy.internal_search = allow_entry.internal_search
                    policy.source = "allowlist"
                    break

        # Check graylist if not in allowlist/user_override
        if policy.source not in ("user_override", "allowlist", "cloudflare"):
            for gray_entry in config.graylist:
                if self._match_pattern(domain, gray_entry.domain_pattern):
                    # Apply graylist overrides
                    if gray_entry.domain_category is not None:
                        policy.domain_category = gray_entry.domain_category
                    if gray_entry.headful_ratio is not None:
                        policy.headful_ratio = gray_entry.headful_ratio
                    if gray_entry.cooldown_minutes is not None:
                        policy.cooldown_minutes = gray_entry.cooldown_minutes
                    if gray_entry.qps is not None:
                        policy.qps = gray_entry.qps

                    if gray_entry.skip:
                        policy.skip = True
                        policy.skip_reason = (
                            gray_entry.reason
                            if isinstance(gray_entry.reason, str)
                            else (gray_entry.reason.value if gray_entry.reason else None)
                        )

                    policy.source = "graylist"
                    break

        # Cache and return
        with self._cache_lock:
            self._policy_cache[domain] = policy

        return policy

    def should_skip(self, domain: str) -> bool:
        """Check if domain should be skipped."""
        return self.get_policy(domain).skip

    def get_domain_category(self, domain: str) -> DomainCategory:
        """Get domain category for domain."""
        return self.get_policy(domain).domain_category

    def get_category_weight(self, domain: str) -> float:
        """Get category weight for ranking adjustment (§3.3)."""
        return self.get_policy(domain).category_weight

    def get_qps_limit(self, domain: str) -> float:
        """Get QPS limit for domain."""
        return self.get_policy(domain).qps

    def get_internal_search_template(self, domain: str) -> InternalSearchTemplate | None:
        """Get internal search template for domain if available."""
        domain = self._normalize_domain(domain)

        for _name, template in self.config.internal_search_templates.items():
            if self._match_pattern(domain, template.domain):
                return InternalSearchTemplate(
                    domain=template.domain,
                    search_input=template.search_input,
                    search_button=template.search_button,
                    results_selector=template.results_selector,
                )

        return None

    def has_internal_search(self, domain: str) -> bool:
        """Check if domain has internal search capability."""
        policy = self.get_policy(domain)
        if policy.internal_search:
            return True
        return self.get_internal_search_template(domain) is not None

    def get_all_allowlist_domains(self) -> list[str]:
        """Get list of all allowlist domains."""
        return [entry.domain for entry in self.config.allowlist]

    def get_domains_by_category(self, category: DomainCategory) -> list[str]:
        """Get domains with specific category from allowlist."""
        return [
            entry.domain for entry in self.config.allowlist if entry.domain_category == category
        ]

    def update_learning_state(self, domain: str, state: dict[str, Any]) -> None:
        """
        Update learning state for a domain (runtime only, not persisted to YAML).

        This updates the cached policy with runtime learning data.
        For persistence, use the database.

        Args:
            domain: Domain name.
            state: Learning state fields to update.
        """
        domain = self._normalize_domain(domain)

        with self._cache_lock:
            if domain in self._policy_cache:
                policy = self._policy_cache[domain]

                if "block_score" in state:
                    policy.block_score = state["block_score"]
                if "captcha_rate" in state:
                    policy.captcha_rate = state["captcha_rate"]
                if "success_rate_1h" in state:
                    policy.success_rate_1h = state["success_rate_1h"]
                if "success_rate_24h" in state:
                    policy.success_rate_24h = state["success_rate_24h"]
                if "headful_ratio" in state:
                    policy.headful_ratio = state["headful_ratio"]
                if "tor_success_rate" in state:
                    policy.tor_success_rate = state["tor_success_rate"]
                if "last_captcha_at" in state:
                    policy.last_captcha_at = state["last_captcha_at"]
                if "cooldown_until" in state:
                    policy.cooldown_until = state["cooldown_until"]

    def clear_cache(self) -> None:
        """Clear policy cache."""
        with self._cache_lock:
            self._policy_cache.clear()

    def get_cache_stats(self) -> dict[str, int]:
        """Get cache statistics."""
        with self._cache_lock:
            return {
                "cached_domains": len(self._policy_cache),
                "allowlist_count": len(self.config.allowlist),
                "graylist_count": len(self.config.graylist),
                "denylist_count": len(self.config.denylist),
                "cloudflare_count": len(self.config.cloudflare_sites),
                "search_templates_count": len(self.config.internal_search_templates),
            }

    # =========================================================================
    # Search Engine Policy Access (§3.1.4, §4.3)
    # =========================================================================

    def get_search_engine_policy(self) -> SearchEnginePolicySchema:
        """Get search engine policy configuration.

        Returns:
            SearchEnginePolicySchema with search engine settings.
        """
        return self.config.search_engine_policy

    def get_search_engine_qps(self) -> float:
        """Get default QPS for search engines.

        Returns:
            Default QPS (requests per second).
        """
        return self.config.search_engine_policy.default_qps

    def get_search_engine_min_interval(self) -> float:
        """Get minimum interval between search engine requests in seconds.

        Returns:
            Minimum interval in seconds.
        """
        return self.config.search_engine_policy.default_min_interval

    def get_site_search_qps(self) -> float:
        """Get QPS for site-internal search (§3.1.5).

        Returns:
            Site search QPS.
        """
        return self.config.search_engine_policy.site_search_qps

    def get_site_search_min_interval(self) -> float:
        """Get minimum interval for site-internal search in seconds.

        Returns:
            Minimum interval in seconds.
        """
        return self.config.search_engine_policy.site_search_min_interval

    def get_circuit_breaker_cooldown_min(self) -> int:
        """Get minimum cooldown time for circuit breaker in minutes.

        Returns:
            Minimum cooldown in minutes.
        """
        return self.config.search_engine_policy.cooldown_min

    def get_circuit_breaker_cooldown_max(self) -> int:
        """Get maximum cooldown time for circuit breaker in minutes.

        Returns:
            Maximum cooldown in minutes.
        """
        return self.config.search_engine_policy.cooldown_max

    def get_circuit_breaker_failure_threshold(self) -> int:
        """Get failure threshold for circuit breaker.

        Returns:
            Failure threshold.
        """
        return self.config.search_engine_policy.failure_threshold

    # =========================================================================
    # Policy Bounds Access (§4.6)
    # =========================================================================

    def get_policy_bounds(self) -> PolicyBoundsSchema:
        """Get policy bounds configuration for auto-adjustment.

        Returns:
            PolicyBoundsSchema with all bounds.
        """
        return self.config.policy_bounds

    def get_bounds_for_parameter(self, param_name: str) -> PolicyBoundsEntrySchema | None:
        """Get bounds for a specific parameter.

        Args:
            param_name: Parameter name (e.g., "engine_weight", "domain_qps").

        Returns:
            PolicyBoundsEntrySchema or None if not found.
        """
        bounds = self.config.policy_bounds
        return getattr(bounds, param_name, None)


# =============================================================================
# Module-level singleton access
# =============================================================================

_manager_instance: DomainPolicyManager | None = None
_manager_lock = threading.Lock()


def get_domain_policy_manager(**kwargs: Any) -> DomainPolicyManager:
    """
    Get the singleton DomainPolicyManager instance.

    Usage:
        manager = get_domain_policy_manager()
        policy = manager.get_policy("example.com")
    """
    global _manager_instance

    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = DomainPolicyManager(**kwargs)

    return _manager_instance


def reset_domain_policy_manager() -> None:
    """Reset the singleton instance (for testing)."""
    global _manager_instance

    with _manager_lock:
        _manager_instance = None
        DomainPolicyManager.reset_instance()


# =============================================================================
# Convenience functions for common operations
# =============================================================================


def get_domain_policy(domain: str) -> DomainPolicy:
    """Get policy for a domain (convenience function)."""
    return get_domain_policy_manager().get_policy(domain)


def should_skip_domain(domain: str) -> bool:
    """Check if domain should be skipped (convenience function)."""
    return get_domain_policy_manager().should_skip(domain)


def get_domain_category(domain: str) -> DomainCategory:
    """Get domain category for domain (convenience function)."""
    return get_domain_policy_manager().get_domain_category(domain)


def get_domain_qps(domain: str) -> float:
    """Get QPS limit for domain (convenience function)."""
    return get_domain_policy_manager().get_qps_limit(domain)
