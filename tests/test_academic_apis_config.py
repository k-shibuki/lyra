"""
Tests for academic APIs configuration loading.

Per ADR-0008: Academic Data Source Strategy.

Tests configuration file loading and legacy behavior.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-CFG-N-01 | Valid academic_apis.yaml with all APIs | Equivalence – normal | Config loaded successfully with all APIs | - |
| TC-CFG-N-02 | Config file with partial APIs | Equivalence – normal | Config loaded with available APIs only | - |
| TC-CFG-N-03 | Environment variable override for email | Equivalence – normal | Email overridden by env var | - |
| TC-CFG-B-01 | Empty config file | Boundary – empty | Empty config returned, no exception | - |
| TC-CFG-B-02 | Config file missing | Boundary – NULL | Empty config returned, no exception | Legacy behavior |
| TC-CFG-B-03 | Empty apis section | Boundary – empty | Config with empty apis dict | - |
| TC-CFG-B-04 | Empty defaults section | Boundary – empty | Config with default defaults | - |
| TC-CFG-A-01 | Invalid YAML syntax | Abnormal – invalid input | YAML parse error handled gracefully | - |
| TC-CFG-A-02 | Missing required field (email for unpaywall) | Abnormal – missing field | Config loaded, email from env/default | - |
| TC-CFG-A-03 | Invalid type (timeout_seconds as string) | Abnormal – invalid type | Validation error or type coercion | - |
| TC-CFG-A-04 | File read permission error | Abnormal – permission | Exception handled gracefully | - |
| TC-CFG-A-05 | Invalid environment variable format | Abnormal – invalid input | Ignored or handled gracefully | - |
| TC-BC-N-01 | API clients initialized without config file | Equivalence – normal | Clients use default values | Legacy behavior |
| TC-BC-B-01 | Config file missing, all clients | Boundary – NULL | All clients initialize with defaults | Legacy behavior |
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.config import (
    AcademicAPIConfig,
    AcademicAPIsConfig,
    AcademicAPIsDefaultsConfig,
    get_academic_apis_config,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_config_dir() -> Generator[Path]:
    """Create temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_config_yaml() -> str:
    """Sample academic_apis.yaml content."""
    return """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
    priority: 1

  openalex:
    enabled: true
    base_url: "https://api.openalex.org"
    timeout_seconds: 30
    priority: 2


defaults:
  search_apis: ["semantic_scholar", "openalex"]
  citation_graph_api: "semantic_scholar"
  max_citation_depth: 2
  max_papers_per_search: 50
"""


# =============================================================================
# Tests
# =============================================================================


class TestConfigLoading:
    """Test configuration loading from YAML file."""

    def test_load_config_from_file(self, temp_config_dir: Path, sample_config_yaml: str) -> None:
        """TC-CFG-N-01: Valid academic_apis.yaml with all APIs."""
        # Given: Valid YAML config file exists
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(sample_config_yaml)

        # When: Loading configuration
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            config = get_academic_apis_config()

        # Then: Config should be loaded successfully with S2 and OpenAlex
        assert isinstance(config, AcademicAPIsConfig)
        assert "semantic_scholar" in config.apis
        assert "openalex" in config.apis

        # Verify semantic_scholar config
        ss_config = config.apis["semantic_scholar"]
        assert ss_config.base_url == "https://api.semanticscholar.org/graph/v1"
        assert ss_config.timeout_seconds == 30
        assert ss_config.priority == 1

        # Verify defaults
        assert config.defaults.search_apis == ["semantic_scholar", "openalex"]
        assert config.defaults.citation_graph_api == "semantic_scholar"

    def test_config_file_not_found(self) -> None:
        """TC-CFG-B-02: Config file missing."""
        # Given: Config file does not exist
        # When: Loading configuration
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": "/nonexistent/path"}):
            get_academic_apis_config.cache_clear()
            config = get_academic_apis_config()

        # Then: Should return empty config, not raise exception
        assert isinstance(config, AcademicAPIsConfig)
        assert len(config.apis) == 0

    def test_empty_config_file(self, temp_config_dir: Path) -> None:
        """TC-CFG-B-01: Empty config file."""
        # Given: Empty config file exists
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text("")

        # When: Loading configuration
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            config = get_academic_apis_config()

        # Then: Should return empty config, not raise exception
        assert isinstance(config, AcademicAPIsConfig)
        assert len(config.apis) == 0

    def test_invalid_yaml_syntax(self, temp_config_dir: Path) -> None:
        """TC-CFG-A-01: Invalid YAML syntax."""
        # Given: Config file with invalid YAML syntax
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text("apis:\n  invalid: [unclosed")

        # When: Loading configuration
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()

            # Then: Should handle YAML parse error gracefully
            # (Implementation may raise or return empty config)
            try:
                config = get_academic_apis_config()
                # If no exception, should return empty or default config
                assert isinstance(config, AcademicAPIsConfig)
            except Exception as e:
                # If exception raised, it should be a YAML-related error
                assert "yaml" in str(e).lower() or "parse" in str(e).lower()

    def test_empty_apis_section(self, temp_config_dir: Path) -> None:
        """TC-CFG-B-03: Empty apis section."""
        # Given: Config file with empty apis section
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text("apis: {}\ndefaults:\n  search_apis: []")

        # When: Loading configuration
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            config = get_academic_apis_config()

        # Then: Should return config with empty apis dict
        assert isinstance(config, AcademicAPIsConfig)
        assert len(config.apis) == 0

    def test_empty_defaults_section(self, temp_config_dir: Path) -> None:
        """TC-CFG-B-04: Empty defaults section."""
        # Given: Config file with empty defaults
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            "apis:\n  semantic_scholar:\n    base_url: 'https://api.example.com'\ndefaults: {}"
        )

        # When: Loading configuration
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            config = get_academic_apis_config()

        # Then: Should use default defaults values
        assert isinstance(config, AcademicAPIsConfig)
        assert config.defaults.search_apis == ["semantic_scholar", "openalex"]  # Default value


class TestMissingConfigDefaults:
    """Test default behavior when config file is missing."""

    def test_api_clients_without_config(self) -> None:
        """TC-BC-N-01: API clients initialized without config file."""
        # Given: Config file does not exist
        # When: Initializing API clients
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": "/nonexistent/path"}, clear=False):
            get_academic_apis_config.cache_clear()

            from src.search.apis.openalex import OpenAlexClient
            from src.search.apis.semantic_scholar import SemanticScholarClient

            ss_client = SemanticScholarClient()
            oa_client = OpenAlexClient()

        # Then: Clients should initialize with default values
        assert ss_client.base_url == "https://api.semanticscholar.org/graph/v1"
        assert ss_client.timeout == 30.0

        assert oa_client.base_url == "https://api.openalex.org"


class TestEnvironmentVariableOverride:
    """Test environment variable overrides."""


class TestConfigValidation:
    """Test configuration validation."""

    def test_defaults_validation(self) -> None:
        """Test that defaults are properly validated."""
        # Given: Valid defaults configuration
        # When: Creating defaults config
        defaults = AcademicAPIsDefaultsConfig(
            search_apis=["semantic_scholar", "openalex"],
            citation_graph_api="semantic_scholar",
            max_citation_depth=2,
            max_papers_per_search=50,
        )

        # Then: Defaults should be set correctly
        assert defaults.search_apis == ["semantic_scholar", "openalex"]
        assert defaults.citation_graph_api == "semantic_scholar"
        assert defaults.max_citation_depth == 2
        assert defaults.max_papers_per_search == 50

    def test_api_config_validation(self) -> None:
        """Test that API config is properly validated."""
        # Given: Valid API configuration
        # When: Creating API config
        api_config = AcademicAPIConfig(
            enabled=True,
            base_url="https://api.example.com",
            timeout_seconds=30,
            priority=1,
        )

        # Then: API config should be set correctly
        assert api_config.enabled is True
        assert api_config.base_url == "https://api.example.com"
        assert api_config.timeout_seconds == 30
        assert api_config.priority == 1
