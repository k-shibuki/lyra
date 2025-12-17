"""
Configuration management for Lancet.
Loads and validates settings from YAML files and environment variables.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class TaskLimitsConfig(BaseModel):
    """Task limits configuration."""
    max_pages_per_task: int = 120
    max_time_minutes_gpu: int = 60
    max_time_minutes_cpu: int = 75
    llm_time_ratio_max: float = 0.30
    max_manual_interventions: int = 3
    max_manual_intervention_time_minutes: int = 5


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
    """DNS policy configuration (§4.3)."""
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
    """Undetected ChromeDriver configuration (§4.3 fallback)."""
    enabled: bool = True
    auto_escalate_captcha_rate: float = 0.5
    auto_escalate_block_score: int = 5
    cloudflare_timeout: int = 45
    prefer_headless: bool = False


class BrowserConfig(BaseModel):
    """Browser configuration."""
    chrome_host: str = "localhost"
    chrome_port: int = 9222
    profile_name: str = "Profile-Research"
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
    
    Per §K.1: Single 3B model for all LLM tasks.
    VRAM budget (8GB) accommodates 3B (~2.5GB) + embedding (~1GB) + reranker (~1GB) + NLI (~0.5GB).
    """
    ollama_host: str = "http://localhost:11434"
    model: str = "qwen2.5:3b"  # Single model for all tasks
    model_context: int = 4096
    temperature: float = 0.3
    gpu_layers: int = -1
    unload_on_task_complete: bool = True  # Per §4.2: Release model context after task


class EmbeddingConfig(BaseModel):
    """Embedding configuration."""
    model_name: str = "BAAI/bge-m3"
    onnx_path: str = "models/bge-m3"
    use_gpu: bool = True
    batch_size: int = 8
    max_length: int = 512


class RerankerConfig(BaseModel):
    """Reranker configuration."""
    model_name: str = "BAAI/bge-reranker-v2-m3"
    onnx_path: str = "models/bge-reranker-v2-m3"
    use_gpu: bool = True
    top_k: int = 100
    max_top_k: int = 150


class NLIConfig(BaseModel):
    """NLI configuration."""
    fast_model: str = "cross-encoder/nli-deberta-v3-xsmall"
    slow_model: str = "cross-encoder/nli-deberta-v3-small"
    use_gpu_for_slow: bool = True


class MLServerConfig(BaseModel):
    """ML Server configuration.
    
    ML models (embedding, reranker, NLI) run in a separate container
    on the internal network (lancet-internal) for security isolation.
    """
    server_url: str = "http://lancet-ml:8100"
    timeout: int = 120  # seconds
    use_remote: bool = True  # When True, use ML server; when False, use local models
    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0


class StorageConfig(BaseModel):
    """Storage configuration."""
    database_path: str = "data/lancet.db"
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
    source_weights: dict[str, float] = Field(default_factory=lambda: {
        "primary": 1.0,
        "government": 0.95,
        "academic": 0.90,
        "trusted_media": 0.75,
        "blog": 0.50,
        "unknown": 0.30,
    })


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


class AcademicAPIRateLimitConfig(BaseModel):
    """Academic API rate limit configuration."""
    requests_per_interval: Optional[int] = None
    interval_seconds: Optional[int] = None
    requests_per_day: Optional[int] = None
    polite_pool: Optional[bool] = None
    min_interval_seconds: Optional[int] = None


class AcademicAPIConfig(BaseModel):
    """Configuration for a single academic API."""
    enabled: bool = True
    base_url: str
    timeout_seconds: int = 30
    priority: int = 999
    rate_limit: Optional[AcademicAPIRateLimitConfig] = None
    headers: Optional[dict[str, str]] = None
    email: Optional[str] = None  # For Unpaywall


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


class GeneralConfig(BaseModel):
    """General configuration."""
    project_name: str = "lancet"
    version: str = "0.1.0"
    log_level: str = "INFO"
    data_dir: str = "data"
    logs_dir: str = "logs"
    
    # Proxy URL for hybrid mode (lancet container proxy server)
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


def _load_yaml_config(config_dir: Path) -> dict[str, Any]:
    """Load configuration from YAML files.
    
    Args:
        config_dir: Configuration directory path.
        
    Returns:
        Merged configuration dictionary.
    """
    config = {}
    
    # Load settings.yaml
    settings_path = config_dir / "settings.yaml"
    if settings_path.exists():
        with open(settings_path, encoding="utf-8") as f:
            settings_data = yaml.safe_load(f) or {}
            config = _deep_merge(config, settings_data)
    
    return config


def _load_academic_apis_config(config_dir: Path) -> dict[str, Any]:
    """Load academic APIs configuration from YAML file.
    
    Args:
        config_dir: Configuration directory path.
        
    Returns:
        Academic APIs configuration dictionary.
    """
    config_path = config_dir / "academic_apis.yaml"
    if not config_path.exists():
        return {}
    
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        return data


@lru_cache(maxsize=1)
def get_academic_apis_config() -> AcademicAPIsConfig:
    """Get academic APIs configuration.
    
    Configuration is loaded from:
    1. config/academic_apis.yaml
    2. Environment variables (highest priority, prefixed with LANCET_ACADEMIC_APIS__)
    
    Returns:
        AcademicAPIsConfig instance.
    """
    # Determine config directory
    config_dir = Path(os.environ.get("LANCET_CONFIG_DIR", "config"))
    
    # Load base configuration
    config_data = _load_academic_apis_config(config_dir)
    
    # Apply environment overrides
    config_data = _apply_env_overrides({"academic_apis": config_data}).get("academic_apis", config_data)
    
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
    
    Environment variables should be prefixed with LANCET_ and use
    double underscores for nested keys.
    
    Example:
        LANCET_GENERAL__LOG_LEVEL=DEBUG
        
    Args:
        config: Configuration dictionary.
        
    Returns:
        Configuration with environment overrides.
    """
    prefix = "LANCET_"
    
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        
        # Remove prefix and split by double underscore
        key_path = key[len(prefix):].lower().split("__")
        
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
    config_dir = Path(os.environ.get("LANCET_CONFIG_DIR", "config"))
    
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

