"""
Configuration management for Lyra.
Loads and validates settings from YAML files and environment variables.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class TaskLimitsConfig(BaseModel):
    """Task limits configuration."""

    model_config = ConfigDict(extra="forbid")

    budget_pages_per_task: int = 120
    max_time_minutes_gpu: int = 60
    max_time_minutes_cpu: int = 75
    llm_time_ratio_max: float = 0.30
    max_manual_interventions: int = 3
    max_manual_intervention_time_minutes: int = 5
    cursor_idle_timeout_seconds: int = 60  # ADR-0002: Cursor AI idle timeout
    auth_queue_ttl_hours: int = 3  # Default expiration for intervention queue items


class WebCitationDetectionConfig(BaseModel):
    """General web citation detection configuration (b).

    Controls when/where we spend LLM calls to classify outbound links as citations.

    Notes:
    - This is separate from academic citation tracking (search.citation_filter.*).
    - Setting max_* to 0 means "no limit".
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    run_on_primary_sources_only: bool = True
    require_useful_text: bool = True
    min_text_chars: int = 200

    # Candidate selection / LLM cost control
    max_candidates_per_page: int = 10  # max outbound links evaluated per page
    max_edges_per_page: int = 0  # max CITES edges created per page (0 = unlimited)
    budget_pages_per_task: int = (
        0  # max pages to run citation detection on per task (0 = unlimited)
    )

    # Storage behavior for targets:
    # - True: create placeholder pages rows for newly discovered citation URLs.
    # - False: only link to existing pages; otherwise skip.
    create_placeholder_pages: bool = True


class SearchConfig(BaseModel):
    """Search configuration."""

    # BrowserSearchProvider is used for all searches
    use_browser: bool = True
    default_engine: str = "duckduckgo"  # Default search engine for browser provider

    initial_query_count_gpu: int = 12
    initial_query_count_cpu: int = 10
    results_per_query: int = 7
    exploration_depth: int = 3
    max_exploration_depth: int = 4
    min_independent_sources: int = 3
    min_primary_secondary_sources: int = 2
    novelty_threshold: float = 0.10
    novelty_cycles_to_stop: int = 2

    # Academic citation graph integration
    citation_graph_top_n_papers: int = 5
    citation_graph_depth: int = 1
    citation_graph_direction: str = "both"  # references, citations, both
    citation_filter: "CitationFilterConfig" = Field(default_factory=lambda: CitationFilterConfig())
    web_citation_detection: WebCitationDetectionConfig = Field(
        default_factory=WebCitationDetectionConfig
    )


class CitationFilterConfig(BaseModel):
    """Citation relevance filtering configuration .

    Design:
    - Stage 0 uses metadata filter (min_citation_count threshold).
    - Stage 1 uses Embedding similarity + impact_score (source-agnostic).
    - Stage 2 uses LLM "evidence usefulness" score + Stage 1 signals.
    - Impact score is calculated from Paper.citation_count (local normalization)
      and is source-agnostic (works with Semantic Scholar, OpenAlex, etc.).
    """

    # Stage 0: metadata filter
    min_citation_count: int = 0  # 0 = no threshold

    # Stage 1: fast coarse filtering
    stage1_top_k: int = 30
    stage1_weight_embedding: float = 0.5
    stage1_weight_impact: float = 0.5

    # Stage 2: precise LLM evaluation
    stage2_top_k: int = 10
    stage2_weight_llm: float = 0.5
    stage2_weight_embedding: float = 0.3
    stage2_weight_impact: float = 0.2

    # LLM prompt/input limits (to control cost)
    max_source_abstract_chars: int = 1200
    max_target_abstract_chars: int = 1200
    llm_timeout_seconds: float = 60.0
    llm_max_tokens: int = 16


class CrawlerConfig(BaseModel):
    """Crawler configuration."""

    engine_qps: float = 0.25
    domain_qps: float = 0.2
    domain_concurrent: int = 1
    network_concurrent: int = 4
    request_timeout: int = 30
    page_load_timeout: int = 45
    max_fetch_time: int = 90  # Cumulative timeout for entire fetch operation (all stages)
    max_retries: int = 3
    backoff_base: float = 2.0
    backoff_max: int = 120
    domain_cooldown_minutes: int = 60
    delay_min: float = 1.5
    delay_max: float = 5.5
    same_domain_depth: int = 2


class DNSPolicyConfig(BaseModel):
    """DNS policy configuration (ADR-0006)."""

    # Resolve DNS through Tor SOCKS proxy (socks5h://) when using Tor route
    resolve_through_tor: bool = True
    # Disable EDNS Client Subnet (ECS) to prevent location leakage
    disable_edns_client_subnet: bool = True
    # Respect DNS cache TTL to reduce exposure
    respect_cache_ttl: bool = True
    # Minimum cache TTL in seconds
    min_cache_ttl: int = 60
    # Maximum cache TTL in seconds
    max_cache_ttl: int = 3600
    # Enable DNS leak detection metrics
    leak_detection_enabled: bool = True


class TorConfig(BaseModel):
    """Tor configuration."""

    enabled: bool = True
    socks_host: str = "127.0.0.1"
    socks_port: int = 9050
    control_port: int = 9051
    circuit_sticky_minutes: int = 15
    max_usage_ratio: float = 0.20
    default_route: str = "direct"
    dns: DNSPolicyConfig = Field(default_factory=DNSPolicyConfig)


class UndetectedChromeDriverConfig(BaseModel):
    """Undetected ChromeDriver configuration (ADR-0006 fallback)."""

    enabled: bool = True
    auto_escalate_captcha_rate: float = 0.5
    auto_escalate_block_score: int = 5
    cloudflare_timeout: int = 45
    prefer_headless: bool = False


class BrowserConfig(BaseModel):
    """Browser configuration.

    Dynamic Worker Pool: Each worker gets its own Chrome instance.
    Worker N connects to chrome_base_port + N with profile Lyra-{N:02d}.
    """

    chrome_host: str = "localhost"
    chrome_base_port: int = 9222  # Worker 0 = 9222, Worker 1 = 9223, etc.
    chrome_profile_prefix: str = "Lyra-"  # Profile names: Lyra-00, Lyra-01, etc.
    default_headless: bool = True
    headful_ratio_initial: float = 0.1
    block_ads: bool = True
    block_trackers: bool = True
    block_large_media: bool = True
    viewport_width: int = 1920
    viewport_height: int = 1080
    undetected_chromedriver: UndetectedChromeDriverConfig = Field(
        default_factory=UndetectedChromeDriverConfig
    )


class LLMConfig(BaseModel):
    """LLM configuration.

    Per ADR-0004: Single 3B model for all LLM tasks.
    VRAM budget (8GB) accommodates 3B (~2.5GB) + embedding (~1GB) + reranker (~1GB) + NLI (~0.5GB).
    """

    ollama_host: str = "http://localhost:11434"
    model: str = "qwen2.5:3b"  # Single model for all tasks
    model_context: int = 4096
    temperature: float = 0.3
    gpu_layers: int = -1
    unload_on_task_complete: bool = True  # Release model context after task


class EmbeddingConfig(BaseModel):
    """Embedding configuration."""

    model_name: str = "BAAI/bge-m3"
    onnx_path: str = "models/bge-m3"
    batch_size: int = 8
    max_length: int = 512


class RerankerConfig(BaseModel):
    """Reranker configuration."""

    model_name: str = "BAAI/bge-reranker-v2-m3"
    onnx_path: str = "models/bge-reranker-v2-m3"
    top_k: int = 100
    max_top_k: int = 150


class NLIConfig(BaseModel):
    """NLI configuration."""

    model: str = "cross-encoder/nli-deberta-v3-small"


class MLServerConfig(BaseModel):
    """ML Server configuration.

    ML models (embedding, reranker, NLI) run in a separate container
    on the internal network (lyra-internal) for security isolation.
    """

    server_url: str = "http://lyra-ml:8100"
    timeout: int = 120  # seconds
    use_remote: bool = True  # When True, use ML server; when False, use local models
    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0


class StorageConfig(BaseModel):
    """Storage configuration."""

    database_path: str = "data/lyra.db"
    warc_dir: str = "data/warc"
    screenshots_dir: str = "data/screenshots"
    reports_dir: str = "data/reports"
    cache_dir: str = "data/cache"
    archive_dir: str = "data/archive"
    serp_cache_ttl: int = 24
    fetch_cache_ttl: int = 168
    embed_cache_ttl: int = 168


class NotificationConfig(BaseModel):
    """Notification configuration."""

    windows_toast_enabled: bool = True
    linux_notify_enabled: bool = True


class QualityConfig(BaseModel):
    """Quality thresholds configuration."""

    min_confidence_score: float = 0.70
    min_independent_sources: int = 3
    min_primary_sources: int = 1
    min_secondary_sources: int = 1
    source_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "primary": 1.0,
            "government": 0.95,
            "academic": 0.90,
            "trusted_media": 0.75,
            "blog": 0.50,
            "unknown": 0.30,
        }
    )


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration."""

    failure_threshold: int = 2
    cooldown_min: int = 30
    cooldown_max: int = 120
    probe_interval: int = 60


class MetricsConfig(BaseModel):
    """Metrics and adaptation configuration."""

    ema_update_interval: int = 60
    ema_short_alpha: float = 0.1
    ema_long_alpha: float = 0.01
    hysteresis_min_interval: int = 300


# === Concurrency Configuration (ADR-0015) ===


class SearchQueueConcurrencyConfig(BaseModel):
    """Search queue worker concurrency configuration.

    Per ADR-0010/ADR-0015: Config-driven worker count.
    """

    model_config = ConfigDict(extra="forbid")

    num_workers: int = Field(default=2, ge=1, description="Number of parallel search queue workers")


class BrowserSerpConcurrencyConfig(BaseModel):
    """Browser SERP tab pool concurrency configuration.

    Per ADR-0014/ADR-0015: Config-driven max_tabs.
    """

    model_config = ConfigDict(extra="forbid")

    max_tabs: int = Field(
        default=1, ge=1, description="Maximum concurrent browser tabs for SERP fetching"
    )


class AcademicAPIBackoffConfig(BaseModel):
    """Academic API auto-backoff configuration.

    Per ADR-0015: Safe auto-backoff for academic APIs.
    """

    model_config = ConfigDict(extra="forbid")

    recovery_stable_seconds: int = Field(
        default=60,
        ge=1,
        description="Seconds of stability before attempting to increase max_parallel",
    )
    decrease_step: int = Field(
        default=1, ge=1, description="Amount to decrease max_parallel on 429 error"
    )


class BrowserSerpBackoffConfig(BaseModel):
    """Browser SERP auto-backoff configuration.

    Per ADR-0015: Safe auto-backoff for browser SERP (decrease only, no auto-increase).
    """

    model_config = ConfigDict(extra="forbid")

    decrease_step: int = Field(
        default=1, ge=1, description="Amount to decrease max_tabs on CAPTCHA/403 detection"
    )
    # Note: No auto_increase for browser SERP (manual only per ADR-0015)


class BackoffConfig(BaseModel):
    """Auto-backoff configuration for concurrency control.

    Per ADR-0015: Automatically reduce concurrency on errors.
    """

    model_config = ConfigDict(extra="forbid")

    academic_api: AcademicAPIBackoffConfig = Field(default_factory=AcademicAPIBackoffConfig)
    browser_serp: BrowserSerpBackoffConfig = Field(default_factory=BrowserSerpBackoffConfig)


class ConcurrencyConfig(BaseModel):
    """Concurrency control configuration.

    Per ADR-0015: Config-driven concurrency + Safe Auto-Backoff.

    Attributes:
        search_queue: Search queue worker settings (num_workers).
        browser_serp: Browser SERP tab pool settings (max_tabs).
        backoff: Auto-backoff settings for error recovery.
    """

    model_config = ConfigDict(extra="forbid")

    search_queue: SearchQueueConcurrencyConfig = Field(default_factory=SearchQueueConcurrencyConfig)
    browser_serp: BrowserSerpConcurrencyConfig = Field(default_factory=BrowserSerpConcurrencyConfig)
    backoff: BackoffConfig = Field(default_factory=BackoffConfig)


class AcademicAPIRateLimitConfig(BaseModel):
    """Academic API rate limit configuration.

    Per ADR-0013: Worker Resource Contention Control.

    Attributes:
        requests_per_interval: Max requests allowed per interval.
        interval_seconds: Duration of rate limit window in seconds.
        requests_per_day: Daily request limit (alternative to interval-based).
        polite_pool: Whether to use polite/identified request pool.
        min_interval_seconds: Minimum seconds between requests (QPS control).
        max_parallel: Maximum concurrent requests (concurrency control).
    """

    requests_per_interval: int | None = None
    interval_seconds: int | None = None
    requests_per_day: int | None = None
    polite_pool: bool | None = None
    min_interval_seconds: float | None = None  # Changed to float for sub-second precision
    max_parallel: int | None = None  # ADR-0013: Provider-level concurrency cap


class AcademicAPIConfig(BaseModel):
    """Configuration for a single academic API."""

    enabled: bool = True
    base_url: str
    timeout_seconds: int = 30
    priority: int = 999
    rate_limit: AcademicAPIRateLimitConfig | None = None
    headers: dict[str, str] | None = None
    email: str | None = None  # For APIs requiring contact email


class AcademicAPIsDefaultsConfig(BaseModel):
    """Default settings for academic APIs."""

    search_apis: list[str] = Field(default_factory=lambda: ["semantic_scholar", "openalex"])
    citation_graph_api: str = "semantic_scholar"
    max_citation_depth: int = 2
    max_papers_per_search: int = 50


class AcademicAPIsConfig(BaseModel):
    """Academic APIs configuration."""

    apis: dict[str, AcademicAPIConfig] = Field(default_factory=dict)
    defaults: AcademicAPIsDefaultsConfig = Field(default_factory=AcademicAPIsDefaultsConfig)

    # Default base URLs for academic APIs (used when API not configured)
    _DEFAULT_BASE_URLS: dict[str, str] = {
        "semantic_scholar": "https://api.semanticscholar.org/graph/v1",
        "openalex": "https://api.openalex.org",
    }

    def get_api_config(self, api_name: str) -> AcademicAPIConfig:
        """Get API configuration with type-safe fallback.

        Returns the configured AcademicAPIConfig for the API,
        or a default config with the standard base URL if not configured.

        Args:
            api_name: Name of the API (semantic_scholar, openalex, etc.)

        Returns:
            AcademicAPIConfig for the requested API
        """
        if api_name in self.apis:
            return self.apis[api_name]

        # Return default config with standard base URL
        default_url = self._DEFAULT_BASE_URLS.get(api_name, f"https://api.{api_name}.org")
        return AcademicAPIConfig(base_url=default_url, enabled=False)


class GeneralConfig(BaseModel):
    """General configuration."""

    project_name: str = "lyra"
    version: str = "0.1.0"
    log_level: str = "INFO"
    data_dir: str = "data"
    logs_dir: str = "logs"

    # Proxy URL for hybrid mode (lyra container proxy server)
    # MCP server always runs on WSL host, LLM/ML via proxy
    proxy_url: str = "http://localhost:8080"


class Settings(BaseModel):
    """Main settings container."""

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    task_limits: TaskLimitsConfig = Field(default_factory=TaskLimitsConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)
    tor: TorConfig = Field(default_factory=TorConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    ml: MLServerConfig = Field(default_factory=MLServerConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    nli: NLIConfig = Field(default_factory=NLIConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries.

    Args:
        base: Base dictionary.
        override: Override dictionary.

    Returns:
        Merged dictionary.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# Cache for local.yaml content (loaded once per process)
_local_overrides_cache: dict[str, Any] | None = None


def _load_local_overrides(config_dir: Path) -> dict[str, Any]:
    """Load local.yaml overrides (cached).

    local.yaml provides unified local overrides for all YAML config files.
    Top-level keys correspond to config file names (without .yaml extension).

    Example local.yaml:
        settings:
          task_limits:
            cursor_idle_timeout_seconds: 180
        academic_apis:
          apis:
            semantic_scholar:
              enabled: false

    Args:
        config_dir: Configuration directory path.

    Returns:
        Local overrides dictionary (cached after first load).
    """
    global _local_overrides_cache

    if _local_overrides_cache is not None:
        return _local_overrides_cache

    local_path = config_dir / "local.yaml"
    if local_path.exists():
        with open(local_path, encoding="utf-8") as f:
            _local_overrides_cache = yaml.safe_load(f) or {}
    else:
        _local_overrides_cache = {}

    return _local_overrides_cache


def _load_yaml_with_local_override(
    config_dir: Path,
    filename: str,
    section_key: str | None = None,
) -> dict[str, Any]:
    """Load YAML file with local.yaml override support.

    This is the unified loader for all YAML config files.
    It loads the base file, then applies overrides from local.yaml.

    Args:
        config_dir: Configuration directory path.
        filename: YAML filename (e.g., "settings.yaml").
        section_key: Key in local.yaml for overrides.
                     Defaults to filename without extension.

    Returns:
        Merged configuration dictionary.
    """
    config: dict[str, Any] = {}

    # Load base file
    base_path = config_dir / filename
    if base_path.exists():
        with open(base_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    # Apply local.yaml overrides
    local_overrides = _load_local_overrides(config_dir)
    if section_key is None:
        section_key = Path(filename).stem  # e.g., "settings.yaml" -> "settings"

    if section_key in local_overrides:
        config = _deep_merge(config, local_overrides[section_key])

    return config


def _load_yaml_config(config_dir: Path) -> dict[str, Any]:
    """Load main settings configuration.

    Loads settings.yaml with local.yaml overrides (settings section).

    Args:
        config_dir: Configuration directory path.

    Returns:
        Merged configuration dictionary.
    """
    return _load_yaml_with_local_override(config_dir, "settings.yaml", "settings")


def _load_academic_apis_config(config_dir: Path) -> dict[str, Any]:
    """Load academic APIs configuration.

    Loads academic_apis.yaml with local.yaml overrides (academic_apis section).

    Args:
        config_dir: Configuration directory path.

    Returns:
        Academic APIs configuration dictionary.
    """
    return _load_yaml_with_local_override(config_dir, "academic_apis.yaml", "academic_apis")


@lru_cache(maxsize=1)
def get_academic_apis_config() -> AcademicAPIsConfig:
    """Get academic APIs configuration.

    Configuration is loaded from:
    1. config/academic_apis.yaml
    2. Environment variables (highest priority, prefixed with LYRA_ACADEMIC_APIS__)

    Returns:
        AcademicAPIsConfig instance.
    """
    # Determine config directory
    config_dir = Path(os.environ.get("LYRA_CONFIG_DIR", "config"))

    # Load base configuration
    config_data = _load_academic_apis_config(config_dir)

    # Apply environment overrides
    config_data = _apply_env_overrides({"academic_apis": config_data}).get(
        "academic_apis", config_data
    )

    # Parse API configurations
    apis_dict = {}
    if "apis" in config_data:
        for api_name, api_data in config_data["apis"].items():
            # Parse rate_limit if present
            rate_limit_data = api_data.get("rate_limit", {})
            rate_limit = None
            if rate_limit_data:
                rate_limit = AcademicAPIRateLimitConfig(**rate_limit_data)

            # Create API config
            api_config_data = {k: v for k, v in api_data.items() if k != "rate_limit"}
            if rate_limit:
                api_config_data["rate_limit"] = rate_limit

            apis_dict[api_name] = AcademicAPIConfig(**api_config_data)

    # Parse defaults
    defaults_data = config_data.get("defaults", {})
    defaults = AcademicAPIsDefaultsConfig(**defaults_data)

    return AcademicAPIsConfig(apis=apis_dict, defaults=defaults)


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides.

    Environment variables should be prefixed with LYRA_ and use
    double underscores for nested keys.

    Example:
        LYRA_GENERAL__LOG_LEVEL=DEBUG

    Args:
        config: Configuration dictionary.

    Returns:
        Configuration with environment overrides.
    """
    prefix = "LYRA_"

    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue

        # Remove prefix and split by double underscore
        key_path = key[len(prefix) :].lower().split("__")

        # Navigate to the correct nested location
        current = config
        for part in key_path[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        # Set the value (attempt to parse as appropriate type)
        final_key = key_path[-1]
        try:
            # Try to parse as int, float, or bool
            if value.lower() in ("true", "false"):
                current[final_key] = value.lower() == "true"
            elif "." in value:
                current[final_key] = float(value)
            else:
                current[final_key] = int(value)
        except ValueError:
            current[final_key] = value

    return config


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get application settings.

    Settings are loaded from:
    1. Default values
    2. YAML configuration files
    3. Environment variables (highest priority)

    Returns:
        Settings instance.
    """
    # Determine config directory
    config_dir = Path(os.environ.get("LYRA_CONFIG_DIR", "config"))

    # Load base configuration
    config = _load_yaml_config(config_dir)

    # Apply environment overrides
    config = _apply_env_overrides(config)

    # Create and return settings
    return Settings(**config)


def get_project_root() -> Path:
    """Get the project root directory.

    Returns:
        Project root path.
    """
    # Assuming this file is at src/utils/config.py
    return Path(__file__).parent.parent.parent


# =============================================================================
# Dynamic Chrome Worker Pool Helpers
# =============================================================================


def get_num_workers() -> int:
    """Get the number of search queue workers from settings.

    Returns:
        Number of workers configured.
    """
    return get_settings().concurrency.search_queue.num_workers


def get_chrome_port(worker_id: int) -> int:
    """Calculate CDP port for a specific worker.

    Args:
        worker_id: Worker ID (0-indexed).

    Returns:
        CDP port number (base_port + worker_id).
    """
    return get_settings().browser.chrome_base_port + worker_id


def get_chrome_profile(worker_id: int) -> str:
    """Calculate Chrome profile name for a specific worker.

    Args:
        worker_id: Worker ID (0-indexed).

    Returns:
        Profile name (e.g., "Lyra-00", "Lyra-01").
    """
    prefix = get_settings().browser.chrome_profile_prefix
    return f"{prefix}{worker_id:02d}"


def get_all_chrome_ports() -> list[int]:
    """Get all CDP ports for the configured number of workers.

    Returns:
        List of CDP ports for all workers.
    """
    settings = get_settings()
    base = settings.browser.chrome_base_port
    n = settings.concurrency.search_queue.num_workers
    return [base + i for i in range(n)]


def ensure_directories() -> None:
    """Ensure all required directories exist."""
    settings = get_settings()
    root = get_project_root()

    dirs = [
        root / settings.general.data_dir,
        root / settings.general.logs_dir,
        root / settings.storage.warc_dir,
        root / settings.storage.screenshots_dir,
        root / settings.storage.reports_dir,
        root / settings.storage.cache_dir,
        root / settings.storage.archive_dir,
    ]

    for dir_path in dirs:
        dir_path.mkdir(parents=True, exist_ok=True)
