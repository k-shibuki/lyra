"""
Search Engine Configuration Manager.

Centralized management of search engine settings from config/engines.yaml.

This module provides:
- Unified loading of engine configurations from YAML
- Hot-reload support for configuration changes
- Schema validation for engine definitions
- Runtime caching with efficient lookups

Per §17.2.2 of docs/IMPLEMENTATION_PLAN.md:
- Dynamic management of search engine settings
- Engine addition/deletion via YAML only (no code changes)
- External operator normalization rules

References:
- §3.1.1 (Search strategies)
- §3.1.4 (Engine health/normalization)
- §4.3 (Stealth policies)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================

class EngineCategory(str, Enum):
    """Search engine category classification."""
    GENERAL = "general"
    ACADEMIC = "academic"
    NEWS = "news"
    GOVERNMENT = "government"
    TECHNICAL = "technical"
    KNOWLEDGE = "knowledge"
    STRUCTURED = "structured"
    MEDICAL = "medical"


class EngineStatus(str, Enum):
    """Engine availability status."""
    ENABLED = "enabled"
    DISABLED = "disabled"
    LASTMILE = "lastmile"  # Strict limits, last resort


# =============================================================================
# Pydantic Schema Models
# =============================================================================

class EngineDefinitionSchema(BaseModel):
    """Schema for individual search engine definition."""

    priority: int = Field(default=5, ge=1, le=10, description="Priority (1=highest)")
    weight: float = Field(default=1.0, ge=0.0, le=2.0, description="Search weight")
    categories: list[str] = Field(default_factory=list, description="Engine categories")
    qps: float = Field(default=0.25, ge=0.01, le=2.0, description="Requests per second")
    block_resistant: bool = Field(default=False, description="Resistant to blocking")
    daily_limit: int | None = Field(default=None, ge=1, description="Daily request limit")
    disabled: bool = Field(default=False, description="Whether engine is disabled")

    @field_validator("categories", mode="before")
    @classmethod
    def validate_categories(cls, v: Any) -> list[str]:
        """Ensure categories is a list."""
        if isinstance(v, str):
            return [v]
        return v or []


class OperatorMappingSchema(BaseModel):
    """Schema for operator mapping to engine-specific syntax."""

    default: str | None = Field(default=None, description="Default format")
    google: str | None = Field(default=None)
    bing: str | None = Field(default=None)
    duckduckgo: str | None = Field(default=None)
    qwant: str | None = Field(default=None)
    brave: str | None = Field(default=None)

    def get_for_engine(self, engine: str) -> str | None:
        """Get mapping for specific engine or default."""
        engine_lower = engine.lower()
        value = getattr(self, engine_lower, None)
        if value is not None:
            return value
        return self.default


class DirectSourceSchema(BaseModel):
    """Schema for direct source configuration."""

    domain: str = Field(..., description="Domain name")
    priority: int = Field(default=1, ge=1, le=10)
    search_url: str | None = Field(default=None, description="Direct search URL template")

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        return v.lower().strip()


class SearchEngineConfigSchema(BaseModel):
    """Root schema for engines.yaml configuration file."""

    # Engine selection policy
    default_engines: list[str] = Field(default_factory=list)
    lastmile_engines: list[str] = Field(default_factory=list)

    # Engine definitions and mappings
    engines: dict[str, EngineDefinitionSchema] = Field(default_factory=dict)
    operator_mapping: dict[str, dict[str, str | None]] = Field(default_factory=dict)
    category_engines: dict[str, list[str]] = Field(default_factory=dict)
    direct_sources: dict[str, list[DirectSourceSchema]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config(self) -> "SearchEngineConfigSchema":
        """Validate configuration consistency."""
        # Ensure default_engines exist in engines
        for engine in self.default_engines:
            if engine not in self.engines:
                logger.warning(f"Default engine '{engine}' not defined in engines section")

        # Ensure lastmile_engines exist
        for engine in self.lastmile_engines:
            if engine not in self.engines:
                logger.warning(f"Lastmile engine '{engine}' not defined in engines section")

        return self


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class EngineConfig:
    """
    Resolved configuration for a specific search engine.

    Combines static configuration with runtime state.
    """

    name: str
    priority: int = 5
    weight: float = 1.0
    categories: list[str] = field(default_factory=list)
    qps: float = 0.25
    block_resistant: bool = False
    daily_limit: int | None = None
    status: EngineStatus = EngineStatus.ENABLED

    # Runtime state (populated from circuit breaker)
    current_usage_today: int = 0
    last_used_at: datetime | None = None

    @property
    def min_interval(self) -> float:
        """Get minimum interval between requests in seconds."""
        return 1.0 / self.qps if self.qps > 0 else 4.0

    @property
    def is_available(self) -> bool:
        """Check if engine is available for use."""
        if self.status == EngineStatus.DISABLED:
            return False
        if self.daily_limit and self.current_usage_today >= self.daily_limit:
            return False
        return True

    @property
    def is_lastmile(self) -> bool:
        """Check if this is a lastmile engine (strict limits)."""
        return self.status == EngineStatus.LASTMILE

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "priority": self.priority,
            "weight": self.weight,
            "categories": self.categories,
            "qps": self.qps,
            "min_interval": self.min_interval,
            "block_resistant": self.block_resistant,
            "daily_limit": self.daily_limit,
            "status": self.status.value,
            "current_usage_today": self.current_usage_today,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_available": self.is_available,
            "is_lastmile": self.is_lastmile,
        }


@dataclass
class DirectSource:
    """Resolved direct source configuration."""

    domain: str
    priority: int
    search_url: str | None
    category: str


# =============================================================================
# Search Engine Config Manager
# =============================================================================

class SearchEngineConfigManager:
    """
    Centralized manager for search engine configurations.

    Features:
    - Loads all engine configs from config/engines.yaml
    - Provides efficient lookups with caching
    - Supports hot-reload of configuration
    - Thread-safe for concurrent access

    Usage:
        manager = get_engine_config_manager()

        # Get specific engine config
        config = manager.get_engine("duckduckgo")

        # Get engines for category
        engines = manager.get_engines_for_category("academic")

        # Get available engines
        available = manager.get_available_engines()

        # Get operator mapping
        mapping = manager.get_operator_mapping("site", "google")

        # Force reload
        manager.reload()
    """

    _instance: "SearchEngineConfigManager | None" = None
    _lock = threading.Lock()

    def __init__(
        self,
        config_path: Path | str | None = None,
        watch_interval: float = 30.0,
        enable_hot_reload: bool = True,
    ):
        """
        Initialize search engine config manager.

        Args:
            config_path: Path to engines.yaml. Defaults to config/engines.yaml.
            watch_interval: Interval (seconds) for checking file changes.
            enable_hot_reload: Whether to enable automatic hot-reload.
        """
        if config_path is None:
            config_path = Path("config/engines.yaml")
        self._config_path = Path(config_path)
        self._watch_interval = watch_interval
        self._enable_hot_reload = enable_hot_reload

        # Internal state
        self._config: SearchEngineConfigSchema | None = None
        self._last_mtime: float = 0.0
        self._last_check: float = 0.0
        self._engine_cache: dict[str, EngineConfig] = {}
        self._cache_lock = threading.RLock()

        # Callbacks for reload events
        self._reload_callbacks: list[Callable[[SearchEngineConfigSchema], None]] = []

        # Initial load
        self._load_config()

    @classmethod
    def get_instance(cls, **kwargs) -> "SearchEngineConfigManager":
        """Get singleton instance of engine config manager."""
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
                "Engine config not found, using defaults",
                path=str(self._config_path),
            )
            self._config = SearchEngineConfigSchema()
            return

        try:
            with open(self._config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Parse engines section with EngineDefinitionSchema
            if "engines" in data and isinstance(data["engines"], dict):
                engines = {}
                for name, engine_data in data["engines"].items():
                    if isinstance(engine_data, dict):
                        engines[name] = EngineDefinitionSchema(**engine_data)
                data["engines"] = engines

            # Parse direct_sources section
            if "direct_sources" in data and isinstance(data["direct_sources"], dict):
                sources = {}
                for category, source_list in data["direct_sources"].items():
                    if isinstance(source_list, list):
                        sources[category] = [
                            DirectSourceSchema(**s) if isinstance(s, dict) else s
                            for s in source_list
                        ]
                data["direct_sources"] = sources

            self._config = SearchEngineConfigSchema(**data)
            self._last_mtime = self._config_path.stat().st_mtime

            # Clear cache on reload
            with self._cache_lock:
                self._engine_cache.clear()

            logger.info(
                "Engine config loaded",
                path=str(self._config_path),
                engine_count=len(self._config.engines),
                default_engines=len(self._config.default_engines),
                operator_types=len(self._config.operator_mapping),
            )

            # Notify callbacks
            for callback in self._reload_callbacks:
                try:
                    callback(self._config)
                except Exception as e:
                    logger.error("Reload callback failed", error=str(e))

        except yaml.YAMLError as e:
            logger.error(
                "Failed to parse engine config YAML",
                error=str(e),
                path=str(self._config_path),
            )
            if self._config is None:
                self._config = SearchEngineConfigSchema()
        except Exception as e:
            logger.error(
                "Failed to load engine config",
                error=str(e),
                path=str(self._config_path),
            )
            if self._config is None:
                self._config = SearchEngineConfigSchema()

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
                logger.info("Engine config changed, reloading...")
                self._load_config()
        except OSError as e:
            logger.warning("Failed to check config file mtime", error=str(e))

    def reload(self) -> None:
        """Force reload configuration."""
        self._load_config()

    def add_reload_callback(self, callback: Callable[[SearchEngineConfigSchema], None]) -> None:
        """Add callback to be called on config reload."""
        self._reload_callbacks.append(callback)

    def remove_reload_callback(self, callback: Callable[[SearchEngineConfigSchema], None]) -> None:
        """Remove reload callback."""
        if callback in self._reload_callbacks:
            self._reload_callbacks.remove(callback)

    @property
    def config(self) -> SearchEngineConfigSchema:
        """Get current configuration (with hot-reload check)."""
        self._check_reload()
        if self._config is None:
            self._load_config()
        return self._config  # type: ignore

    # =========================================================================
    # Engine Selection Policy
    # =========================================================================

    def get_default_engines(self) -> list[str]:
        """Get list of default enabled engines."""
        return list(self.config.default_engines)

    def get_lastmile_engines(self) -> list[str]:
        """Get list of lastmile engines (strict limits)."""
        return list(self.config.lastmile_engines)

    # =========================================================================
    # Engine Configuration
    # =========================================================================

    def get_engine(self, name: str) -> EngineConfig | None:
        """
        Get configuration for a specific engine.

        Args:
            name: Engine name (case-insensitive).

        Returns:
            EngineConfig or None if not found.
        """
        self._check_reload()
        name_lower = name.lower()

        # Check cache first
        with self._cache_lock:
            if name_lower in self._engine_cache:
                return self._engine_cache[name_lower]

        # Look up in config
        engine_def = self.config.engines.get(name_lower)
        if engine_def is None:
            return None

        # Determine status
        status = EngineStatus.ENABLED
        if engine_def.disabled:
            status = EngineStatus.DISABLED
        elif name_lower in self.config.lastmile_engines:
            status = EngineStatus.LASTMILE

        # Create config object
        engine_config = EngineConfig(
            name=name_lower,
            priority=engine_def.priority,
            weight=engine_def.weight,
            categories=engine_def.categories,
            qps=engine_def.qps,
            block_resistant=engine_def.block_resistant,
            daily_limit=engine_def.daily_limit,
            status=status,
        )

        # Cache and return
        with self._cache_lock:
            self._engine_cache[name_lower] = engine_config

        return engine_config

    def get_all_engines(self) -> list[EngineConfig]:
        """Get all engine configurations."""
        engines = []
        for name in self.config.engines.keys():
            config = self.get_engine(name)
            if config:
                engines.append(config)
        return engines

    def get_available_engines(self, include_lastmile: bool = False) -> list[EngineConfig]:
        """
        Get available (non-disabled) engines.

        Args:
            include_lastmile: Whether to include lastmile engines.

        Returns:
            List of available engine configurations.
        """
        engines = []
        for config in self.get_all_engines():
            if config.status == EngineStatus.DISABLED:
                continue
            if config.status == EngineStatus.LASTMILE and not include_lastmile:
                continue
            if config.is_available:
                engines.append(config)
        return engines

    def get_engines_for_category(self, category: str) -> list[EngineConfig]:
        """
        Get engines for a specific category.

        Args:
            category: Category name (e.g., "academic", "news").

        Returns:
            List of engine configurations for that category.
        """
        # First check category_engines mapping
        category_lower = category.lower()
        engine_names = self.config.category_engines.get(category_lower, [])

        if engine_names:
            # Filter to only engines with available parsers
            filtered_names = self.get_engines_with_parsers(engine_names)
            return [
                config
                for name in filtered_names
                if (config := self.get_engine(name)) is not None
            ]

        # Fall back to engines with matching category in their categories list
        # Filter to only engines with available parsers
        all_matching = [
            config
            for config in self.get_all_engines()
            if category_lower in [c.lower() for c in config.categories]
        ]
        # Filter by parser availability
        matching_names = [cfg.name for cfg in all_matching]
        filtered_names = self.get_engines_with_parsers(matching_names)
        return [
            config
            for config in all_matching
            if config.name in filtered_names
        ]

    def get_block_resistant_engines(self) -> list[EngineConfig]:
        """Get engines marked as block-resistant."""
        return [
            config
            for config in self.get_all_engines()
            if config.block_resistant and config.is_available
        ]

    def get_engines_with_parsers(self, engines: list[str] | None = None) -> list[str]:
        """Filter engines to only those with available parsers.

        Args:
            engines: List of engine names to filter. If None, filters all engines.

        Returns:
            List of engine names that have available parsers.
        """
        from src.search.search_parsers import get_available_parsers
        available_parsers = set(get_available_parsers())

        if engines is None:
            engines = [e.name for e in self.get_all_engines()]

        return [e for e in engines if e in available_parsers]

    def get_engine_qps(self, name: str) -> float:
        """Get QPS limit for an engine."""
        config = self.get_engine(name)
        return config.qps if config else 0.25

    def get_engine_weight(self, name: str) -> float:
        """Get weight for an engine."""
        config = self.get_engine(name)
        return config.weight if config else 1.0

    def get_engine_priority(self, name: str) -> int:
        """Get priority for an engine (1=highest)."""
        config = self.get_engine(name)
        return config.priority if config else 5

    def is_engine_available(self, name: str) -> bool:
        """Check if an engine is available."""
        config = self.get_engine(name)
        return config.is_available if config else False

    def is_engine_disabled(self, name: str) -> bool:
        """Check if an engine is disabled."""
        config = self.get_engine(name)
        if config is None:
            return True  # Unknown engine = disabled
        return config.status == EngineStatus.DISABLED

    # =========================================================================
    # Operator Mapping
    # =========================================================================

    def get_operator_mapping(
        self,
        operator: str,
        engine: str | None = None,
    ) -> str | None:
        """
        Get operator syntax for an engine.

        Args:
            operator: Operator type (site, filetype, intitle, etc.).
            engine: Target engine (None for default).

        Returns:
            Operator template string or None if not supported.
        """
        mapping = self.config.operator_mapping.get(operator.lower())
        if mapping is None:
            return None

        if engine:
            engine_specific = mapping.get(engine.lower())
            if engine_specific is not None:
                return engine_specific

        return mapping.get("default")

    def get_all_operator_mappings(self) -> dict[str, dict[str, str | None]]:
        """Get all operator mappings."""
        return dict(self.config.operator_mapping)

    def get_supported_operators(self, engine: str) -> list[str]:
        """
        Get list of operators supported by an engine.

        Args:
            engine: Engine name.

        Returns:
            List of supported operator names.
        """
        supported = []
        engine_lower = engine.lower()

        for op_name, mapping in self.config.operator_mapping.items():
            if mapping.get(engine_lower) is not None or mapping.get("default") is not None:
                supported.append(op_name)

        return supported

    # =========================================================================
    # Direct Sources
    # =========================================================================

    def get_direct_sources(self, category: str | None = None) -> list[DirectSource]:
        """
        Get direct source configurations.

        Args:
            category: Filter by category (None for all).

        Returns:
            List of DirectSource objects.
        """
        sources = []

        for cat, source_list in self.config.direct_sources.items():
            if category and cat.lower() != category.lower():
                continue

            for source_schema in source_list:
                sources.append(DirectSource(
                    domain=source_schema.domain,
                    priority=source_schema.priority,
                    search_url=source_schema.search_url,
                    category=cat,
                ))

        return sources

    def get_direct_source_for_domain(self, domain: str) -> DirectSource | None:
        """
        Get direct source config for a domain.

        Args:
            domain: Domain name to look up.

        Returns:
            DirectSource or None if not found.
        """
        domain_lower = domain.lower()

        for cat, source_list in self.config.direct_sources.items():
            for source_schema in source_list:
                if source_schema.domain.lower() == domain_lower:
                    return DirectSource(
                        domain=source_schema.domain,
                        priority=source_schema.priority,
                        search_url=source_schema.search_url,
                        category=cat,
                    )

        return None

    # =========================================================================
    # Category Management
    # =========================================================================

    def get_all_categories(self) -> list[str]:
        """Get all defined categories."""
        categories = set(self.config.category_engines.keys())

        # Also collect categories from engine definitions
        for engine_def in self.config.engines.values():
            categories.update(engine_def.categories)

        return sorted(categories)

    def get_engines_by_priority(
        self,
        max_priority: int = 5,
        category: str | None = None,
    ) -> list[EngineConfig]:
        """
        Get engines sorted by priority.

        Args:
            max_priority: Maximum priority level to include (1=highest).
            category: Optional category filter.

        Returns:
            List of engine configs sorted by priority.
        """
        if category:
            engines = self.get_engines_for_category(category)
        else:
            engines = self.get_available_engines()

        # Filter by priority and sort
        filtered = [e for e in engines if e.priority <= max_priority]
        return sorted(filtered, key=lambda e: (e.priority, -e.weight))

    # =========================================================================
    # Cache and Stats
    # =========================================================================

    def clear_cache(self) -> None:
        """Clear engine cache."""
        with self._cache_lock:
            self._engine_cache.clear()

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._cache_lock:
            return {
                "cached_engines": len(self._engine_cache),
                "total_engines": len(self.config.engines),
                "default_engines": len(self.config.default_engines),
                "lastmile_engines": len(self.config.lastmile_engines),
                "operator_types": len(self.config.operator_mapping),
                "categories": len(self.get_all_categories()),
                "direct_source_categories": len(self.config.direct_sources),
            }

    def update_engine_usage(self, name: str, increment: int = 1) -> None:
        """
        Update daily usage count for an engine.

        Args:
            name: Engine name.
            increment: Usage increment.
        """
        name_lower = name.lower()

        with self._cache_lock:
            if name_lower in self._engine_cache:
                self._engine_cache[name_lower].current_usage_today += increment
                self._engine_cache[name_lower].last_used_at = datetime.now(timezone.utc)

    def reset_daily_usage(self) -> None:
        """Reset daily usage counters for all engines."""
        with self._cache_lock:
            for config in self._engine_cache.values():
                config.current_usage_today = 0


# =============================================================================
# Module-level singleton access
# =============================================================================

_manager_instance: SearchEngineConfigManager | None = None
_manager_lock = threading.Lock()


def get_engine_config_manager(**kwargs) -> SearchEngineConfigManager:
    """
    Get the singleton SearchEngineConfigManager instance.

    Usage:
        manager = get_engine_config_manager()
        config = manager.get_engine("duckduckgo")
    """
    global _manager_instance

    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = SearchEngineConfigManager(**kwargs)

    return _manager_instance


def reset_engine_config_manager() -> None:
    """Reset the singleton instance (for testing)."""
    global _manager_instance

    with _manager_lock:
        _manager_instance = None
        SearchEngineConfigManager.reset_instance()


# =============================================================================
# Convenience functions for common operations
# =============================================================================

def get_engine_config(name: str) -> EngineConfig | None:
    """Get configuration for an engine (convenience function)."""
    return get_engine_config_manager().get_engine(name)


def get_available_search_engines(include_lastmile: bool = False) -> list[EngineConfig]:
    """Get available search engines (convenience function)."""
    return get_engine_config_manager().get_available_engines(include_lastmile)


def get_engine_operator_mapping(operator: str, engine: str | None = None) -> str | None:
    """Get operator mapping for an engine (convenience function)."""
    return get_engine_config_manager().get_operator_mapping(operator, engine)


def is_search_engine_available(name: str) -> bool:
    """Check if a search engine is available (convenience function)."""
    return get_engine_config_manager().is_engine_available(name)

