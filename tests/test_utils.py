"""
Tests for src/utils/config.py and src/utils/logging.py

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-DM-01 | Merge simple dicts | Equivalence – simple | Override wins | - |
| TC-DM-02 | Merge nested dicts | Equivalence – nested | Deep merge applied | - |
| TC-DM-03 | Override replaces lists | Equivalence – lists | List replaced, not merged | - |
| TC-DM-04 | None values handled | Boundary – None | None passed through | - |
| TC-LS-01 | Load default settings | Equivalence – defaults | Default config loaded | - |
| TC-LS-02 | Load with environment override | Equivalence – env | ENV var overrides config | - |
| TC-LS-03 | Load missing file | Boundary – missing | Defaults used | - |
| TC-GS-01 | get_settings singleton | Equivalence – singleton | Same instance returned | - |
| TC-GS-02 | get_settings after reload | Equivalence – reload | Fresh config loaded | - |
| TC-LG-01 | Setup logging default | Equivalence – default | INFO level logging | - |
| TC-LG-02 | Setup logging debug | Equivalence – debug | DEBUG level logging | - |
| TC-LG-03 | Logger with component | Equivalence – component | Logger with name prefix | - |
| TC-EC-01 | Invalid YAML file | Abnormal – parse error | Handles gracefully | - |
| TC-EC-02 | Permission denied | Abnormal – permission | Handles gracefully | - |
"""

import os

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
# E402: Intentionally import after pytestmark for test configuration
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


class TestDeepMerge:
    """Tests for _deep_merge function."""

    def test_deep_merge_simple(self):
        """Test merging simple dicts."""
        from src.utils.config import _deep_merge

        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}

        result = _deep_merge(base, override)

        assert result == {"a": 1, "b": 3, "c": 4}

    def test_deep_merge_nested(self):
        """Test merging nested dicts."""
        from src.utils.config import _deep_merge

        base = {
            "level1": {
                "a": 1,
                "b": 2,
            }
        }
        override = {
            "level1": {
                "b": 3,
                "c": 4,
            }
        }

        result = _deep_merge(base, override)

        assert result == {"level1": {"a": 1, "b": 3, "c": 4}}

    def test_deep_merge_preserves_original(self):
        """Test that deep merge doesn't modify original dicts."""
        from src.utils.config import _deep_merge

        base = {"a": 1}
        override = {"b": 2}

        _deep_merge(base, override)

        assert "b" not in base


class TestSettings:
    """Tests for Settings and related config classes."""

    def test_default_settings(self):
        """Test default settings values."""
        from src.utils.config import Settings

        settings = Settings()

        assert settings.general.project_name == "lyra"
        assert settings.general.log_level == "INFO"
        assert settings.search.exploration_depth == 3
        assert settings.crawler.domain_qps == 0.2

    def test_settings_from_dict(self):
        """Test creating settings from dict."""
        from src.utils.config import Settings

        config = {
            "general": {"log_level": "DEBUG"},
            "search": {"initial_query_count_gpu": 20},
        }

        settings = Settings(**config)

        assert settings.general.log_level == "DEBUG"
        assert settings.search.initial_query_count_gpu == 20
        # Defaults preserved
        assert settings.crawler.domain_qps == 0.2

    def test_task_limits_config(self):
        """Test TaskLimitsConfig defaults."""
        from src.utils.config import TaskLimitsConfig

        config = TaskLimitsConfig()

        assert config.max_pages_per_task == 120
        assert config.max_time_minutes_gpu == 60
        assert config.llm_time_ratio_max == 0.30

    def test_search_config(self):
        """Test SearchConfig defaults."""
        from src.utils.config import SearchConfig

        config = SearchConfig()

        assert config.initial_query_count_gpu == 12
        assert config.results_per_query == 7
        assert config.min_independent_sources == 3

    def test_crawler_config(self):
        """Test CrawlerConfig defaults."""
        from src.utils.config import CrawlerConfig

        config = CrawlerConfig()

        assert config.engine_qps == 0.25
        assert config.domain_concurrent == 1
        assert config.request_timeout == 30

    def test_quality_config_source_weights(self):
        """Test QualityConfig source weights."""
        from src.utils.config import QualityConfig

        config = QualityConfig()

        assert config.source_weights["primary"] == 1.0
        assert config.source_weights["government"] == 0.95
        assert config.source_weights["blog"] == 0.50


class TestLoadYamlConfig:
    """Tests for YAML config loading."""

    def test_load_yaml_config_from_file(self):
        """Test loading config from YAML file."""
        from src.utils.config import _load_yaml_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.yaml"

            yaml_content = {
                "general": {"log_level": "DEBUG"},
                "search": {"exploration_depth": 5},
            }

            with open(settings_path, "w") as f:
                yaml.dump(yaml_content, f)

            config = _load_yaml_config(config_dir)

            assert config["general"]["log_level"] == "DEBUG"
            assert config["search"]["exploration_depth"] == 5

    def test_load_yaml_config_missing_file(self):
        """Test loading config when file doesn't exist."""
        from src.utils.config import _load_yaml_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            config = _load_yaml_config(config_dir)

            assert config == {}


class TestApplyEnvOverrides:
    """Tests for environment variable overrides."""

    def test_apply_env_overrides_simple(self):
        """Test simple env var override."""
        from src.utils.config import _apply_env_overrides

        config = {"general": {"log_level": "INFO"}}

        with patch.dict(os.environ, {"LYRA_GENERAL__LOG_LEVEL": "DEBUG"}):
            result = _apply_env_overrides(config)

        assert result["general"]["log_level"] == "DEBUG"

    def test_apply_env_overrides_creates_nested(self):
        """Test env var override creates nested keys."""
        from src.utils.config import _apply_env_overrides

        config = {}

        with patch.dict(os.environ, {"LYRA_SEARCH__EXPLORATION_DEPTH": "10"}):
            result = _apply_env_overrides(config)

        assert result["search"]["exploration_depth"] == 10

    def test_apply_env_overrides_bool(self):
        """Test env var override parses bool values."""
        from src.utils.config import _apply_env_overrides

        config = {}

        with patch.dict(
            os.environ,
            {
                "LYRA_TOR__ENABLED": "false",
                "LYRA_BROWSER__BLOCK_ADS": "true",
            },
        ):
            result = _apply_env_overrides(config)

        assert result["tor"]["enabled"] is False
        assert result["browser"]["block_ads"] is True

    def test_apply_env_overrides_float(self):
        """Test env var override parses float values."""
        from src.utils.config import _apply_env_overrides

        config = {}

        with patch.dict(os.environ, {"LYRA_CRAWLER__DOMAIN_QPS": "0.5"}):
            result = _apply_env_overrides(config)

        assert result["crawler"]["domain_qps"] == 0.5

    def test_apply_env_overrides_string(self):
        """Test env var override preserves string values."""
        from src.utils.config import _apply_env_overrides

        config = {}

        with patch.dict(os.environ, {"LYRA_LLM__MODEL": "llama3:8b"}):
            result = _apply_env_overrides(config)

        assert result["llm"]["model"] == "llama3:8b"

    def test_apply_env_overrides_ignores_non_lyra(self):
        """Test that non-LYRA_ env vars are ignored."""
        from src.utils.config import _apply_env_overrides

        config = {}

        with patch.dict(
            os.environ,
            {
                "OTHER_VAR": "value",
                "HOME": "/home/user",
            },
        ):
            result = _apply_env_overrides(config)

        assert "other_var" not in result
        assert "home" not in result


class TestGetProjectRoot:
    """Tests for get_project_root function."""

    def test_get_project_root(self):
        """Test get_project_root returns expected path."""
        from src.utils.config import get_project_root

        root = get_project_root()

        # Should point to lyra project root
        assert root.is_dir()
        assert (root / "src").is_dir()


class TestEnsureDirectories:
    """Tests for ensure_directories function."""

    def test_ensure_directories_creates_dirs(self):
        """Test ensure_directories creates required directories."""
        from src.utils.config import ensure_directories, get_settings

        # This test depends on real config - just verify it doesn't fail
        ensure_directories()

        settings = get_settings()
        from src.utils.config import get_project_root

        root = get_project_root()

        assert (root / settings.general.data_dir).is_dir()
        assert (root / settings.general.logs_dir).is_dir()


class TestLogging:
    """Tests for logging configuration."""

    def test_get_logger(self):
        """Test get_logger returns a logger."""
        from src.utils.logging import get_logger

        logger = get_logger(__name__)

        assert logger is not None
        assert hasattr(logger, "info")
        assert hasattr(logger, "error")
        assert hasattr(logger, "debug")

    def test_add_timestamp_processor(self):
        """Test _add_timestamp processor adds timestamp."""
        from src.utils.logging import _add_timestamp

        event_dict = {"event": "test"}
        result = _add_timestamp(None, "info", event_dict)

        assert "timestamp" in result
        assert result["timestamp"].endswith("Z")

    def test_add_log_level_processor(self):
        """Test _add_log_level processor adds level."""
        from src.utils.logging import _add_log_level

        event_dict = {"event": "test"}
        result = _add_log_level(None, "warning", event_dict)

        assert result["level"] == "WARNING"


class TestLogContext:
    """Tests for LogContext context manager."""

    def test_log_context_binds_and_unbinds(self):
        """Test LogContext binds and unbinds context variables."""
        import structlog

        from src.utils.logging import LogContext

        # Clear any existing context
        structlog.contextvars.clear_contextvars()

        with LogContext(task_id="test-123", job_id="job-456"):
            # Inside context, vars should be bound
            ctx = structlog.contextvars.get_contextvars()
            assert ctx.get("task_id") == "test-123"
            assert ctx.get("job_id") == "job-456"

        # Outside context, vars should be unbound
        ctx = structlog.contextvars.get_contextvars()
        assert "task_id" not in ctx
        assert "job_id" not in ctx


class TestCausalTrace:
    """Tests for CausalTrace class."""

    def test_causal_trace_generates_id(self):
        """Test CausalTrace generates unique trace ID."""
        from src.utils.logging import CausalTrace

        trace = CausalTrace()

        assert trace.id is not None
        assert len(trace.id) == 36  # UUID format

    def test_causal_trace_stores_parent(self):
        """Test CausalTrace stores parent cause ID."""
        from src.utils.logging import CausalTrace

        parent_id = "parent-123"
        trace = CausalTrace(cause_id=parent_id)

        assert trace.parent_id == parent_id

    def test_causal_trace_context_manager(self):
        """Test CausalTrace as context manager."""
        import structlog

        from src.utils.logging import CausalTrace

        structlog.contextvars.clear_contextvars()

        with CausalTrace() as trace:
            ctx = structlog.contextvars.get_contextvars()
            assert ctx.get("cause_id") == trace.id

        ctx = structlog.contextvars.get_contextvars()
        assert "cause_id" not in ctx


class TestBindUnbindContext:
    """Tests for bind_context and unbind_context functions."""

    def test_bind_context(self):
        """Test bind_context adds context vars."""
        import structlog

        from src.utils.logging import bind_context, clear_context

        clear_context()
        bind_context(custom_key="custom_value")

        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("custom_key") == "custom_value"

        clear_context()

    def test_unbind_context(self):
        """Test unbind_context removes context vars."""
        import structlog

        from src.utils.logging import bind_context, unbind_context

        structlog.contextvars.clear_contextvars()
        bind_context(key1="value1", key2="value2")
        unbind_context("key1")

        ctx = structlog.contextvars.get_contextvars()
        assert "key1" not in ctx
        assert ctx.get("key2") == "value2"

        structlog.contextvars.clear_contextvars()

    def test_clear_context(self):
        """Test clear_context removes all context vars."""
        import structlog

        from src.utils.logging import bind_context, clear_context

        bind_context(key1="value1", key2="value2")
        clear_context()

        ctx = structlog.contextvars.get_contextvars()
        assert ctx == {}
