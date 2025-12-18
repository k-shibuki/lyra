"""
Search Parser Configuration Manager.

Loads and validates search result parser configurations from config/search_parsers.yaml.

Design Philosophy:
- Selectors are externalized to enable quick fixes without code changes
- Each selector has 'required' flag and 'diagnostic_message' for AI-friendly debugging
- Hot-reload support for configuration changes
- Failed HTML is saved for inspection when parsing fails
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Pydantic Schema Models
# =============================================================================


class SelectorSchema(BaseModel):
    """Schema for a single CSS selector configuration."""

    selector: str = Field(..., description="CSS selector string")
    required: bool = Field(default=False, description="Whether selector is required")
    diagnostic_message: str = Field(
        default="",
        description="AI-friendly diagnostic message for debugging",
    )

    @field_validator("selector")
    @classmethod
    def validate_selector(cls, v: str) -> str:
        """Ensure selector is not empty."""
        if not v.strip():
            raise ValueError("Selector cannot be empty")
        return v.strip()


class CaptchaPatternSchema(BaseModel):
    """Schema for CAPTCHA detection pattern."""

    pattern: str = Field(..., description="Pattern to match in HTML")
    type: str = Field(..., description="CAPTCHA type identifier")
    case_insensitive: bool = Field(default=False, description="Case-insensitive matching")

    def matches(self, html: str) -> bool:
        """Check if pattern matches HTML content."""
        if self.case_insensitive:
            return self.pattern.lower() in html.lower()
        return self.pattern in html


class EngineParserSchema(BaseModel):
    """Schema for a search engine parser configuration."""

    search_url: str = Field(..., description="URL template for search")
    default_region: str | None = Field(default=None)
    default_language: str | None = Field(default=None)
    time_ranges: dict[str, str] = Field(default_factory=dict)
    selectors: dict[str, SelectorSchema] = Field(default_factory=dict)
    captcha_patterns: list[CaptchaPatternSchema] = Field(default_factory=list)

    @field_validator("selectors", mode="before")
    @classmethod
    def parse_selectors(cls, v: Any) -> dict[str, SelectorSchema]:
        """Parse selector configurations."""
        if not isinstance(v, dict):
            return {}

        result = {}
        for name, config in v.items():
            if isinstance(config, dict):
                result[name] = SelectorSchema(**config)
            elif isinstance(config, SelectorSchema):
                result[name] = config
        return result

    @field_validator("captcha_patterns", mode="before")
    @classmethod
    def parse_captcha_patterns(cls, v: Any) -> list[CaptchaPatternSchema]:
        """Parse CAPTCHA patterns."""
        if not isinstance(v, list):
            return []

        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(CaptchaPatternSchema(**item))
            elif isinstance(item, CaptchaPatternSchema):
                result.append(item)
        return result


class ParserSettingsSchema(BaseModel):
    """Schema for global parser settings."""

    debug_html_dir: str = Field(default="debug/search_html")
    save_failed_html: bool = Field(default=True)
    max_results_per_page: int = Field(default=20, ge=1, le=100)
    search_timeout: int = Field(default=30, ge=5, le=120)


class SearchParsersConfigSchema(BaseModel):
    """Root schema for search_parsers.yaml configuration."""

    settings: ParserSettingsSchema = Field(default_factory=ParserSettingsSchema)
    duckduckgo: EngineParserSchema | None = None
    mojeek: EngineParserSchema | None = None
    google: EngineParserSchema | None = None
    brave: EngineParserSchema | None = None
    # Additional engines
    ecosia: EngineParserSchema | None = None
    startpage: EngineParserSchema | None = None
    bing: EngineParserSchema | None = None

    def get_engine(self, name: str) -> EngineParserSchema | None:
        """Get parser config for an engine by name."""
        name_lower = name.lower()
        return getattr(self, name_lower, None)

    def get_available_engines(self) -> list[str]:
        """Get list of configured engine names."""
        engines = []
        # All supported engines
        for name in ["duckduckgo", "mojeek", "google", "brave",
                     "ecosia", "startpage", "bing"]:
            if getattr(self, name, None) is not None:
                engines.append(name)
        return engines


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class SelectorConfig:
    """Resolved selector configuration for runtime use."""

    name: str
    selector: str
    required: bool = False
    diagnostic_message: str = ""

    def get_error_message(self, context: str = "") -> str:
        """Get formatted error message for selector failure."""
        base = f"Selector '{self.name}' ({self.selector}) not found"
        if context:
            base = f"{base} in {context}"
        if self.diagnostic_message:
            base = f"{base}\n\nDiagnostic:\n{self.diagnostic_message}"
        return base


@dataclass
class EngineParserConfig:
    """Resolved parser configuration for a search engine."""

    name: str
    search_url: str
    default_region: str | None = None
    default_language: str | None = None
    time_ranges: dict[str, str] = field(default_factory=dict)
    selectors: dict[str, SelectorConfig] = field(default_factory=dict)
    captcha_patterns: list[CaptchaPatternSchema] = field(default_factory=list)

    def get_selector(self, name: str) -> SelectorConfig | None:
        """Get selector config by name."""
        return self.selectors.get(name)

    def get_required_selectors(self) -> list[SelectorConfig]:
        """Get all required selectors."""
        return [s for s in self.selectors.values() if s.required]

    def get_time_range(self, key: str) -> str:
        """Get time range parameter value."""
        return self.time_ranges.get(key, "")

    def build_search_url(
        self,
        query: str,
        time_range: str = "all",
        region: str | None = None,
        language: str | None = None,
    ) -> str:
        """Build search URL from template."""
        url = self.search_url

        # Replace placeholders
        url = url.replace("{query}", query)
        url = url.replace("{time_range}", self.get_time_range(time_range))
        url = url.replace("{region}", region or self.default_region or "")
        url = url.replace("{language}", language or self.default_language or "")

        # Clean up empty parameters
        url = re.sub(r"[&?][a-z_]+=(?=&|$)", "", url)
        url = url.rstrip("&?")

        return url

    def detect_captcha(self, html: str) -> tuple[bool, str | None]:
        """
        Check if HTML contains CAPTCHA/challenge.

        Returns:
            Tuple of (is_captcha, captcha_type)
        """
        for pattern in self.captcha_patterns:
            if pattern.matches(html):
                return True, pattern.type
        return False, None


@dataclass
class ParserSettings:
    """Resolved global parser settings."""

    debug_html_dir: Path
    save_failed_html: bool = True
    max_results_per_page: int = 20
    search_timeout: int = 30

    def ensure_debug_dir(self) -> None:
        """Ensure debug HTML directory exists."""
        if self.save_failed_html:
            self.debug_html_dir.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Parser Config Manager
# =============================================================================


class ParserConfigManager:
    """
    Centralized manager for search parser configurations.

    Features:
    - Loads parser configs from config/search_parsers.yaml
    - Provides efficient lookups with caching
    - Supports hot-reload of configuration
    - Thread-safe for concurrent access

    Usage:
        manager = get_parser_config_manager()

        # Get parser config for an engine
        config = manager.get_engine_config("duckduckgo")

        # Get selector
        selector = config.get_selector("results_container")

        # Build search URL
        url = config.build_search_url("AI regulations", time_range="week")
    """

    _instance: "ParserConfigManager | None" = None
    _lock = threading.Lock()

    def __init__(
        self,
        config_path: Path | str | None = None,
        watch_interval: float = 30.0,
        enable_hot_reload: bool = True,
    ):
        """
        Initialize parser config manager.

        Args:
            config_path: Path to search_parsers.yaml. Defaults to config/search_parsers.yaml.
            watch_interval: Interval (seconds) for checking file changes.
            enable_hot_reload: Whether to enable automatic hot-reload.
        """
        if config_path is None:
            config_path = Path("config/search_parsers.yaml")
        self._config_path = Path(config_path)
        self._watch_interval = watch_interval
        self._enable_hot_reload = enable_hot_reload

        # Internal state
        self._config: SearchParsersConfigSchema | None = None
        self._settings: ParserSettings | None = None
        self._last_mtime: float = 0.0
        self._last_check: float = 0.0
        self._engine_cache: dict[str, EngineParserConfig] = {}
        self._cache_lock = threading.RLock()

        # Initial load
        self._load_config()

    @classmethod
    def get_instance(cls, **kwargs) -> "ParserConfigManager":
        """Get singleton instance of parser config manager."""
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
                "Parser config not found, using defaults",
                path=str(self._config_path),
            )
            self._config = SearchParsersConfigSchema()
            self._settings = ParserSettings(
                debug_html_dir=Path("debug/search_html"),
            )
            return

        try:
            with open(self._config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Parse engine sections
            for engine_name in ["duckduckgo", "mojeek", "google", "brave",
                                "ecosia", "startpage", "bing"]:
                if engine_name in data and isinstance(data[engine_name], dict):
                    data[engine_name] = EngineParserSchema(**data[engine_name])

            # Parse settings
            if "settings" in data and isinstance(data["settings"], dict):
                data["settings"] = ParserSettingsSchema(**data["settings"])

            self._config = SearchParsersConfigSchema(**data)
            self._last_mtime = self._config_path.stat().st_mtime

            # Build settings
            self._settings = ParserSettings(
                debug_html_dir=Path(self._config.settings.debug_html_dir),
                save_failed_html=self._config.settings.save_failed_html,
                max_results_per_page=self._config.settings.max_results_per_page,
                search_timeout=self._config.settings.search_timeout,
            )

            # Clear cache on reload
            with self._cache_lock:
                self._engine_cache.clear()

            logger.info(
                "Parser config loaded",
                path=str(self._config_path),
                engines=self._config.get_available_engines(),
            )

        except yaml.YAMLError as e:
            logger.error(
                "Failed to parse parser config YAML",
                error=str(e),
                path=str(self._config_path),
            )
            if self._config is None:
                self._config = SearchParsersConfigSchema()
                self._settings = ParserSettings(debug_html_dir=Path("debug/search_html"))
        except Exception as e:
            logger.error(
                "Failed to load parser config",
                error=str(e),
                path=str(self._config_path),
            )
            if self._config is None:
                self._config = SearchParsersConfigSchema()
                self._settings = ParserSettings(debug_html_dir=Path("debug/search_html"))

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
                logger.info("Parser config changed, reloading...")
                self._load_config()
        except OSError as e:
            logger.warning("Failed to check config file mtime", error=str(e))

    def reload(self) -> None:
        """Force reload configuration."""
        self._load_config()

    @property
    def config(self) -> SearchParsersConfigSchema:
        """Get current configuration (with hot-reload check)."""
        self._check_reload()
        if self._config is None:
            self._load_config()
        return self._config  # type: ignore

    @property
    def settings(self) -> ParserSettings:
        """Get parser settings."""
        self._check_reload()
        if self._settings is None:
            self._load_config()
        return self._settings  # type: ignore

    # =========================================================================
    # Engine Configuration
    # =========================================================================

    def get_engine_config(self, name: str) -> EngineParserConfig | None:
        """
        Get parser configuration for a search engine.

        Args:
            name: Engine name (case-insensitive).

        Returns:
            EngineParserConfig or None if not configured.
        """
        self._check_reload()
        name_lower = name.lower()

        # Check cache first
        with self._cache_lock:
            if name_lower in self._engine_cache:
                return self._engine_cache[name_lower]

        # Look up in config
        engine_schema = self.config.get_engine(name_lower)
        if engine_schema is None:
            return None

        # Build resolved config
        selectors = {}
        for sel_name, sel_schema in engine_schema.selectors.items():
            selectors[sel_name] = SelectorConfig(
                name=sel_name,
                selector=sel_schema.selector,
                required=sel_schema.required,
                diagnostic_message=sel_schema.diagnostic_message,
            )

        engine_config = EngineParserConfig(
            name=name_lower,
            search_url=engine_schema.search_url,
            default_region=engine_schema.default_region,
            default_language=engine_schema.default_language,
            time_ranges=dict(engine_schema.time_ranges),
            selectors=selectors,
            captcha_patterns=list(engine_schema.captcha_patterns),
        )

        # Cache and return
        with self._cache_lock:
            self._engine_cache[name_lower] = engine_config

        return engine_config

    def get_available_engines(self) -> list[str]:
        """Get list of configured engine names."""
        return self.config.get_available_engines()

    def is_engine_configured(self, name: str) -> bool:
        """Check if an engine has parser configuration."""
        return self.get_engine_config(name) is not None

    # =========================================================================
    # Debug HTML Saving
    # =========================================================================

    def save_failed_html(
        self,
        html: str,
        engine: str,
        query: str,
        error: str,
    ) -> Path | None:
        """
        Save HTML content for debugging when parsing fails.

        Args:
            html: HTML content that failed to parse.
            engine: Engine name.
            query: Search query.
            error: Error message.

        Returns:
            Path to saved file or None if saving disabled.
        """
        if not self.settings.save_failed_html:
            return None

        try:
            self.settings.ensure_debug_dir()

            # Generate filename
            timestamp = int(time.time())
            safe_query = re.sub(r"[^\w\s-]", "", query)[:30].strip()
            filename = f"{engine}_{timestamp}_{safe_query}.html"
            filepath = self.settings.debug_html_dir / filename

            # Write HTML with metadata header
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"<!-- Parser Debug Info\n")
                f.write(f"Engine: {engine}\n")
                f.write(f"Query: {query}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Error: {error}\n")
                f.write(f"-->\n\n")
                f.write(html)

            logger.info(
                "Saved failed HTML for debugging",
                engine=engine,
                path=str(filepath),
            )

            return filepath

        except Exception as e:
            logger.warning("Failed to save debug HTML", error=str(e))
            return None

    # =========================================================================
    # Cache Management
    # =========================================================================

    def clear_cache(self) -> None:
        """Clear engine config cache."""
        with self._cache_lock:
            self._engine_cache.clear()

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._cache_lock:
            return {
                "cached_engines": len(self._engine_cache),
                "available_engines": len(self.config.get_available_engines()),
                "debug_html_dir": str(self.settings.debug_html_dir),
                "save_failed_html": self.settings.save_failed_html,
            }


# =============================================================================
# Module-level singleton access
# =============================================================================

_manager_instance: ParserConfigManager | None = None
_manager_lock = threading.Lock()


def get_parser_config_manager(**kwargs) -> ParserConfigManager:
    """
    Get the singleton ParserConfigManager instance.

    Usage:
        manager = get_parser_config_manager()
        config = manager.get_engine_config("duckduckgo")
    """
    global _manager_instance

    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = ParserConfigManager(**kwargs)

    return _manager_instance


def reset_parser_config_manager() -> None:
    """Reset the singleton instance (for testing)."""
    global _manager_instance

    with _manager_lock:
        _manager_instance = None
        ParserConfigManager.reset_instance()


# =============================================================================
# Convenience functions
# =============================================================================


def get_engine_parser_config(name: str) -> EngineParserConfig | None:
    """Get parser configuration for an engine (convenience function)."""
    return get_parser_config_manager().get_engine_config(name)


def get_available_parser_engines() -> list[str]:
    """Get list of engines with parser configurations."""
    return get_parser_config_manager().get_available_engines()


def save_debug_html(html: str, engine: str, query: str, error: str) -> Path | None:
    """Save failed HTML for debugging (convenience function)."""
    return get_parser_config_manager().save_failed_html(html, engine, query, error)

