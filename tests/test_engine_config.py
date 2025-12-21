"""
Tests for SearchEngineConfigManager.

Tests:
- Configuration loading and parsing
- Engine configuration retrieval
- Operator mapping
- Category management
- Hot-reload support
- Direct source configuration
"""
import time

from collections.abc import Generator
from pathlib import Path

import pytest
import yaml

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

from src.search.engine_config import (
    EngineConfig,
    EngineDefinitionSchema,
    EngineStatus,
    SearchEngineConfigManager,
    SearchEngineConfigSchema,
    get_available_search_engines,
    get_engine_config,
    get_engine_config_manager,
    get_engine_operator_mapping,
    is_search_engine_available,
    reset_engine_config_manager,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_config_data() -> dict[str, object]:
    """Sample engines.yaml configuration data."""
    return {
        # Engine selection policy (root level)
        "default_engines": ["duckduckgo", "wikipedia"],
        "lastmile_engines": ["brave"],
        "engines": {
            "duckduckgo": {
                "priority": 3,
                "weight": 0.7,
                "categories": ["general"],
                "qps": 0.2,
                "block_resistant": False,
            },
            "wikipedia": {
                "priority": 1,
                "weight": 1.0,
                "categories": ["general", "knowledge"],
                "qps": 0.5,
                "block_resistant": True,
            },
            "arxiv": {
                "priority": 1,
                "weight": 1.0,
                "categories": ["academic", "technical"],
                "qps": 0.25,
                "block_resistant": True,
            },
            "brave": {
                "priority": 5,
                "weight": 0.3,
                "categories": ["general"],
                "qps": 0.1,
                "block_resistant": False,
                "daily_limit": 50,
            },
            "google": {
                "priority": 10,
                "weight": 0.1,
                "categories": ["general"],
                "qps": 0.05,
                "block_resistant": False,
                "daily_limit": 10,
                "disabled": True,
            },
        },
        "operator_mapping": {
            "site": {
                "default": "site:{domain}",
                "google": "site:{domain}",
                "duckduckgo": "site:{domain}",
            },
            "filetype": {
                "default": "filetype:{type}",
                "google": "filetype:{type}",
            },
            "exact": {
                "default": '"{text}"',
            },
        },
        "category_engines": {
            "general": ["duckduckgo", "wikipedia"],
            "academic": ["arxiv", "wikipedia"],
        },
        "direct_sources": {
            "academic": [
                {
                    "domain": "arxiv.org",
                    "priority": 1,
                    "search_url": "https://arxiv.org/search/?query={query}",
                },
                {
                    "domain": "pubmed.ncbi.nlm.nih.gov",
                    "priority": 1,
                },
            ],
        },
    }


@pytest.fixture
def temp_config_file(
    sample_config_data: dict[str, object], tmp_path: Path
) -> Path:
    """Create a temporary config file."""
    config_path = tmp_path / "engines.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_config_data, f)
    return config_path


@pytest.fixture
def manager(temp_config_file: Path) -> Generator[SearchEngineConfigManager, None, None]:
    """Create a SearchEngineConfigManager with test config."""
    manager = SearchEngineConfigManager(
        config_path=temp_config_file,
        enable_hot_reload=False,
    )
    yield manager
    # Cleanup
    SearchEngineConfigManager.reset_instance()


@pytest.fixture(autouse=True)
def reset_singleton() -> Generator[None, None, None]:
    """Reset singleton before and after each test."""
    reset_engine_config_manager()
    yield
    reset_engine_config_manager()


# =============================================================================
# Schema Validation Tests
# =============================================================================


class TestEngineDefinitionSchema:
    """Tests for EngineDefinitionSchema validation."""

    def test_valid_engine_definition(self) -> None:
        """Test valid engine definition is parsed correctly."""
        schema = EngineDefinitionSchema(
            priority=1,
            weight=1.0,
            categories=["general", "academic"],
            qps=0.5,
            block_resistant=True,
        )

        assert schema.priority == 1
        assert schema.weight == 1.0
        assert schema.categories == ["general", "academic"]
        assert schema.qps == 0.5
        assert schema.block_resistant is True
        assert schema.daily_limit is None
        assert schema.disabled is False

    def test_default_values(self) -> None:
        """Test default values are applied correctly."""
        schema = EngineDefinitionSchema()

        assert schema.priority == 5
        assert schema.weight == 1.0
        assert schema.categories == []
        assert schema.qps == 0.25
        assert schema.block_resistant is False
        assert schema.daily_limit is None
        assert schema.disabled is False

    def test_categories_string_to_list(self) -> None:
        """Test single category string is converted to list."""
        schema = EngineDefinitionSchema(categories="general")
        assert schema.categories == ["general"]

    def test_priority_bounds(self) -> None:
        """Test priority validation bounds."""
        # Valid bounds
        assert EngineDefinitionSchema(priority=1).priority == 1
        assert EngineDefinitionSchema(priority=10).priority == 10

        # Invalid bounds
        with pytest.raises(ValueError):
            EngineDefinitionSchema(priority=0)
        with pytest.raises(ValueError):
            EngineDefinitionSchema(priority=11)

    def test_weight_bounds(self) -> None:
        """Test weight validation bounds."""
        assert EngineDefinitionSchema(weight=0.0).weight == 0.0
        assert EngineDefinitionSchema(weight=2.0).weight == 2.0

        with pytest.raises(ValueError):
            EngineDefinitionSchema(weight=-0.1)
        with pytest.raises(ValueError):
            EngineDefinitionSchema(weight=2.1)

    def test_qps_bounds(self) -> None:
        """Test QPS validation bounds."""
        assert EngineDefinitionSchema(qps=0.01).qps == 0.01
        assert EngineDefinitionSchema(qps=2.0).qps == 2.0

        with pytest.raises(ValueError):
            EngineDefinitionSchema(qps=0.001)


# =============================================================================
# Manager Configuration Loading Tests
# =============================================================================


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_load_valid_config(
        self, manager: SearchEngineConfigManager, sample_config_data: dict[str, object]
    ) -> None:
        """Test loading valid configuration file."""
        # Verify default engines
        default_engines = manager.get_default_engines()
        assert "duckduckgo" in default_engines
        assert "wikipedia" in default_engines

        # Verify lastmile engines
        lastmile_engines = manager.get_lastmile_engines()
        assert "brave" in lastmile_engines

        # Verify engine count
        all_engines = manager.get_all_engines()
        assert len(all_engines) == 5

    def test_load_missing_config(self, tmp_path: Path) -> None:
        """Test loading non-existent config file uses defaults."""
        manager = SearchEngineConfigManager(
            config_path=tmp_path / "nonexistent.yaml",
            enable_hot_reload=False,
        )

        # Should use defaults
        assert manager.config is not None
        assert len(manager.get_all_engines()) == 0

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        """Test loading invalid YAML gracefully fails."""
        config_path = tmp_path / "invalid.yaml"
        with open(config_path, "w") as f:
            f.write("invalid: yaml: content: [")

        manager = SearchEngineConfigManager(
            config_path=config_path,
            enable_hot_reload=False,
        )

        # Should use defaults without crashing
        assert manager.config is not None


# =============================================================================
# Engine Configuration Tests
# =============================================================================


class TestEngineConfiguration:
    """Tests for engine configuration retrieval."""

    def test_get_engine_by_name(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving engine by name."""
        config = manager.get_engine("duckduckgo")

        assert config is not None
        assert config.name == "duckduckgo"
        assert config.priority == 3
        assert config.weight == 0.7
        assert "general" in config.categories
        assert config.qps == 0.2
        assert config.block_resistant is False

    def test_get_engine_case_insensitive(self, manager: SearchEngineConfigManager) -> None:
        """Test engine lookup is case-insensitive."""
        config1 = manager.get_engine("DuckDuckGo")
        config2 = manager.get_engine("DUCKDUCKGO")
        config3 = manager.get_engine("duckduckgo")

        assert config1 is not None
        assert config2 is not None
        assert config3 is not None
        assert config1.name == config2.name == config3.name

    def test_get_nonexistent_engine(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving non-existent engine returns None."""
        config = manager.get_engine("nonexistent")
        assert config is None

    def test_engine_status_disabled(self, manager: SearchEngineConfigManager) -> None:
        """Test disabled engine has correct status."""
        config = manager.get_engine("google")

        assert config is not None
        assert config.status == EngineStatus.DISABLED
        assert config.is_available is False

    def test_engine_status_lastmile(self, manager: SearchEngineConfigManager) -> None:
        """Test lastmile engine has correct status."""
        config = manager.get_engine("brave")

        assert config is not None
        assert config.status == EngineStatus.LASTMILE
        assert config.is_lastmile is True

    def test_engine_min_interval(self, manager: SearchEngineConfigManager) -> None:
        """Test min_interval calculation from QPS."""
        config = manager.get_engine("duckduckgo")

        assert config is not None
        assert config.qps == 0.2
        assert config.min_interval == 5.0  # 1 / 0.2 = 5.0

    def test_engine_daily_limit(self, manager: SearchEngineConfigManager) -> None:
        """Test daily limit configuration."""
        config = manager.get_engine("brave")

        assert config is not None
        assert config.daily_limit == 50

    def test_get_all_engines(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving all engines."""
        engines = manager.get_all_engines()

        assert len(engines) == 5
        names = {e.name for e in engines}
        assert names == {"duckduckgo", "wikipedia", "arxiv", "brave", "google"}

    def test_get_available_engines(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving only available engines."""
        available = manager.get_available_engines(include_lastmile=False)

        # Should not include disabled (google) or lastmile (brave)
        names = {e.name for e in available}
        assert "google" not in names
        assert "brave" not in names
        assert "duckduckgo" in names
        assert "wikipedia" in names

    def test_get_available_engines_with_lastmile(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving available engines including lastmile."""
        available = manager.get_available_engines(include_lastmile=True)

        names = {e.name for e in available}
        assert "brave" in names
        assert "google" not in names  # Still disabled

    def test_get_block_resistant_engines(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving block-resistant engines."""
        resistant = manager.get_block_resistant_engines()

        names = {e.name for e in resistant}
        assert "wikipedia" in names
        assert "arxiv" in names
        assert "duckduckgo" not in names  # Not block resistant


# =============================================================================
# Category Management Tests
# =============================================================================


class TestCategoryManagement:
    """Tests for category-based engine retrieval."""

    def test_get_engines_for_category(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving engines for a category."""
        academic = manager.get_engines_for_category("academic")

        {e.name for e in academic}
        # Only engines with parsers should be returned
        # arxiv and wikipedia don't have parsers, so they should be filtered out
        # duckduckgo has a parser and is in category_engines["academic"] via fallback
        # But since category_engines["academic"] explicitly lists arxiv/wikipedia,
        # and those don't have parsers, the list should be empty or contain only parsers
        # Actually, category_engines["academic"] = ["arxiv", "wikipedia"] in test data
        # So after filtering, it should be empty
        # But duckduckgo might be included via fallback if category_engines is empty
        # Let's check that only engines with parsers are returned
        from src.search.search_parsers import get_available_parsers

        available_parsers = set(get_available_parsers())
        for engine in academic:
            assert engine.name in available_parsers, f"Engine {engine.name} should have a parser"

    def test_get_engines_for_category_fallback(self, manager: SearchEngineConfigManager) -> None:
        """Test category lookup falls back to engine categories."""
        technical = manager.get_engines_for_category("technical")

        # Not in category_engines, but arxiv has it in categories
        # However, arxiv doesn't have a parser, so it should be filtered out
        names = {e.name for e in technical}
        # Only engines with parsers should be returned
        from src.search.search_parsers import get_available_parsers

        available_parsers = set(get_available_parsers())
        for engine in technical:
            assert engine.name in available_parsers, f"Engine {engine.name} should have a parser"
        # arxiv should NOT be in the result since it has no parser
        assert "arxiv" not in names

    def test_get_all_categories(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving all categories."""
        categories = manager.get_all_categories()

        assert "general" in categories
        assert "academic" in categories
        assert "technical" in categories
        assert "knowledge" in categories

    def test_get_engines_by_priority(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving engines sorted by priority."""
        engines = manager.get_engines_by_priority(max_priority=3)

        # Should include priority 1-3, sorted by priority then weight
        assert engines[0].priority <= engines[-1].priority

        # First should be highest priority (1), highest weight
        assert engines[0].priority == 1


# =============================================================================
# Operator Mapping Tests
# =============================================================================


class TestOperatorMapping:
    """Tests for operator mapping retrieval."""

    def test_get_operator_mapping_default(self, manager: SearchEngineConfigManager) -> None:
        """Test getting default operator mapping."""
        mapping = manager.get_operator_mapping("site")

        assert mapping == "site:{domain}"

    def test_get_operator_mapping_engine_specific(self, manager: SearchEngineConfigManager) -> None:
        """Test getting engine-specific operator mapping."""
        mapping = manager.get_operator_mapping("site", "google")

        assert mapping == "site:{domain}"

    def test_get_operator_mapping_fallback_to_default(self, manager: SearchEngineConfigManager) -> None:
        """Test fallback to default when engine-specific not available."""
        # filetype is defined for google but not duckduckgo
        mapping = manager.get_operator_mapping("filetype", "duckduckgo")

        assert mapping == "filetype:{type}"  # Falls back to default

    def test_get_operator_mapping_nonexistent(self, manager: SearchEngineConfigManager) -> None:
        """Test getting non-existent operator returns None."""
        mapping = manager.get_operator_mapping("nonexistent")

        assert mapping is None

    def test_get_all_operator_mappings(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving all operator mappings."""
        mappings = manager.get_all_operator_mappings()

        assert "site" in mappings
        assert "filetype" in mappings
        assert "exact" in mappings

    def test_get_supported_operators(self, manager: SearchEngineConfigManager) -> None:
        """Test getting supported operators for an engine."""
        supported = manager.get_supported_operators("google")

        assert "site" in supported
        assert "filetype" in supported
        assert "exact" in supported


# =============================================================================
# Direct Sources Tests
# =============================================================================


class TestDirectSources:
    """Tests for direct source configuration."""

    def test_get_direct_sources_all(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving all direct sources."""
        sources = manager.get_direct_sources()

        assert len(sources) == 2
        domains = {s.domain for s in sources}
        assert "arxiv.org" in domains
        assert "pubmed.ncbi.nlm.nih.gov" in domains

    def test_get_direct_sources_by_category(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving direct sources by category."""
        sources = manager.get_direct_sources("academic")

        assert len(sources) == 2
        assert all(s.category == "academic" for s in sources)

    def test_get_direct_source_for_domain(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving direct source for specific domain."""
        source = manager.get_direct_source_for_domain("arxiv.org")

        assert source is not None
        assert source.domain == "arxiv.org"
        assert source.priority == 1
        assert source.search_url == "https://arxiv.org/search/?query={query}"

    def test_get_direct_source_nonexistent(self, manager: SearchEngineConfigManager) -> None:
        """Test retrieving non-existent direct source returns None."""
        source = manager.get_direct_source_for_domain("example.com")

        assert source is None


# =============================================================================
# Hot-Reload Tests
# =============================================================================


class TestHotReload:
    """Tests for hot-reload functionality."""

    def test_hot_reload_detects_changes(
        self, temp_config_file: Path, sample_config_data: dict[str, object]
    ) -> None:
        """Test that hot-reload detects config file changes."""
        import os

        manager = SearchEngineConfigManager(
            config_path=temp_config_file,
            watch_interval=0.1,  # Short interval for testing
            enable_hot_reload=True,
        )

        # Initial state - 2 default engines
        assert len(manager.get_default_engines()) == 2

        # Modify config - add a new default engine
        sample_config_data["default_engines"].append("arxiv")
        with open(temp_config_file, "w", encoding="utf-8") as f:
            yaml.dump(sample_config_data, f)

        # Explicitly set future mtime to ensure change detection
        # (filesystem mtime precision is often 1 second, sleep(0.2) is insufficient)
        future_time = time.time() + 2
        os.utime(temp_config_file, (future_time, future_time))

        # Access config to trigger reload check
        manager._last_check = 0  # Force check
        assert len(manager.get_default_engines()) == 3

    def test_hot_reload_disabled(
        self, temp_config_file: Path, sample_config_data: dict[str, object]
    ) -> None:
        """Test that hot-reload can be disabled."""
        manager = SearchEngineConfigManager(
            config_path=temp_config_file,
            enable_hot_reload=False,
        )

        # Initial state - 2 default engines
        assert len(manager.get_default_engines()) == 2

        # Modify config - add a new default engine
        sample_config_data["default_engines"].append("arxiv")
        with open(temp_config_file, "w", encoding="utf-8") as f:
            yaml.dump(sample_config_data, f)

        # Should NOT reload
        assert len(manager.get_default_engines()) == 2

    def test_manual_reload(
        self, temp_config_file: Path, sample_config_data: dict[str, object]
    ) -> None:
        """Test manual reload works."""
        manager = SearchEngineConfigManager(
            config_path=temp_config_file,
            enable_hot_reload=False,
        )

        # Modify config - add a new default engine
        sample_config_data["default_engines"].append("arxiv")
        with open(temp_config_file, "w", encoding="utf-8") as f:
            yaml.dump(sample_config_data, f)

        # Manual reload
        manager.reload()

        assert len(manager.get_default_engines()) == 3

    def test_reload_callback(
        self, temp_config_file: Path, sample_config_data: dict[str, object]
    ) -> None:
        """Test reload callbacks are called."""
        manager = SearchEngineConfigManager(
            config_path=temp_config_file,
            enable_hot_reload=False,
        )

        callback_called: list[SearchEngineConfigSchema] = []

        def on_reload(config: SearchEngineConfigSchema) -> None:
            callback_called.append(config)

        manager.add_reload_callback(on_reload)

        # Trigger reload
        manager.reload()

        assert len(callback_called) == 1
        assert isinstance(callback_called[0], SearchEngineConfigSchema)


# =============================================================================
# Cache Tests
# =============================================================================


class TestCache:
    """Tests for caching functionality."""

    def test_engine_caching(self, manager: SearchEngineConfigManager) -> None:
        """Test engines are cached after first retrieval."""
        # First call creates cache
        config1 = manager.get_engine("duckduckgo")

        # Second call should use cache
        config2 = manager.get_engine("duckduckgo")

        assert config1 is config2  # Same object from cache

    def test_cache_clear(self, manager: SearchEngineConfigManager) -> None:
        """Test cache clearing works."""
        # Populate cache
        manager.get_engine("duckduckgo")

        stats = manager.get_cache_stats()
        assert stats["cached_engines"] >= 1

        # Clear cache
        manager.clear_cache()

        stats = manager.get_cache_stats()
        assert stats["cached_engines"] == 0

    def test_usage_tracking(self, manager: SearchEngineConfigManager) -> None:
        """Test daily usage tracking."""
        config = manager.get_engine("duckduckgo")
        assert config is not None
        assert config.current_usage_today == 0

        manager.update_engine_usage("duckduckgo", 5)

        # Get again from cache
        config = manager.get_engine("duckduckgo")
        assert config is not None
        assert config.current_usage_today == 5

    def test_reset_daily_usage(self, manager: SearchEngineConfigManager) -> None:
        """Test resetting daily usage."""
        manager.update_engine_usage("duckduckgo", 5)
        manager.reset_daily_usage()

        config = manager.get_engine("duckduckgo")
        assert config is not None
        assert config.current_usage_today == 0


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_engine_config_function(self, temp_config_file: Path) -> None:
        """Test get_engine_config convenience function."""
        # Reset module-level singleton and set up with test config
        reset_engine_config_manager()
        get_engine_config_manager(
            config_path=temp_config_file,
            enable_hot_reload=False,
        )

        config = get_engine_config("duckduckgo")

        assert config is not None
        assert config.name == "duckduckgo"

    def test_get_available_search_engines_function(self, temp_config_file: Path) -> None:
        """Test get_available_search_engines convenience function."""
        reset_engine_config_manager()
        get_engine_config_manager(
            config_path=temp_config_file,
            enable_hot_reload=False,
        )

        engines = get_available_search_engines()

        # Should have at least 1 engine available
        assert len(engines) >= 1, f"Expected >=1 engines, got {len(engines)}"
        names = {e.name for e in engines}
        assert "google" not in names  # Disabled in test fixture

    def test_get_engine_operator_mapping_function(self, temp_config_file: Path) -> None:
        """Test get_engine_operator_mapping convenience function."""
        reset_engine_config_manager()
        get_engine_config_manager(
            config_path=temp_config_file,
            enable_hot_reload=False,
        )

        mapping = get_engine_operator_mapping("site", "google")

        assert mapping == "site:{domain}"

    def test_is_search_engine_available_function(self, temp_config_file: Path) -> None:
        """Test is_search_engine_available convenience function."""
        reset_engine_config_manager()
        get_engine_config_manager(
            config_path=temp_config_file,
            enable_hot_reload=False,
        )

        assert is_search_engine_available("duckduckgo") is True
        assert is_search_engine_available("google") is False  # Disabled in test fixture


# =============================================================================
# EngineConfig Data Class Tests
# =============================================================================


class TestEngineConfigDataClass:
    """Tests for EngineConfig data class."""

    def test_to_dict(self, manager: SearchEngineConfigManager) -> None:
        """Test EngineConfig serialization."""
        config = manager.get_engine("wikipedia")
        assert config is not None

        data = config.to_dict()

        assert data["name"] == "wikipedia"
        assert data["priority"] == 1
        assert data["weight"] == 1.0
        assert data["is_available"] is True
        assert "min_interval" in data

    def test_daily_limit_availability(self) -> None:
        """Test daily limit affects availability."""
        config = EngineConfig(
            name="test",
            daily_limit=10,
            current_usage_today=10,
        )

        assert config.is_available is False

        config.current_usage_today = 9
        assert config.is_available is True


# =============================================================================
# Integration with Existing Code Tests
# =============================================================================


class TestIntegration:
    """Tests for integration with existing code."""

    def test_query_operator_processor_uses_manager(self, temp_config_file: Path) -> None:
        """Test QueryOperatorProcessor uses SearchEngineConfigManager."""
        # Reset and set up
        reset_engine_config_manager()
        SearchEngineConfigManager._instance = None
        SearchEngineConfigManager.get_instance(
            config_path=temp_config_file,
            enable_hot_reload=False,
        )

        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()

        # Should have loaded mappings from manager
        assert "site" in processor._operator_mapping
        assert processor._operator_mapping["site"]["default"] == "site:{domain}"
