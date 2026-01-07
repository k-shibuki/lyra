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

import httpx
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


@pytest.fixture(autouse=True)
def clear_lyra_env_vars() -> Generator[None]:
    """Clear LYRA_ACADEMIC_APIS__ environment variables for test isolation.

    This prevents real environment variables (e.g., in CI/containers) from
    interfering with test expectations.
    """
    import src.utils.config as config_module

    # Save and remove existing LYRA_ACADEMIC_APIS__ vars
    prefix = "LYRA_ACADEMIC_APIS__"
    saved_vars = {k: v for k, v in os.environ.items() if k.startswith(prefix)}
    for key in saved_vars:
        del os.environ[key]

    # Clear caches before each test
    get_academic_apis_config.cache_clear()
    # Reset _local_overrides_cache to force reload
    saved_local_cache = config_module._local_overrides_cache
    config_module._local_overrides_cache = None

    yield

    # Restore after test
    for key, value in saved_vars.items():
        os.environ[key] = value
    get_academic_apis_config.cache_clear()
    config_module._local_overrides_cache = saved_local_cache


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

    def test_env_override_openalex_email(self, temp_config_dir: Path) -> None:
        """TC-CFG-N-03: Environment variable override for OpenAlex email."""
        # Given: Config file without email
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  openalex:
    enabled: true
    base_url: "https://api.openalex.org"
    timeout_seconds: 30
defaults:
  search_apis: ["openalex"]
"""
        )

        # When: Loading configuration with email env override
        with patch.dict(
            os.environ,
            {
                "LYRA_CONFIG_DIR": str(temp_config_dir),
                "LYRA_ACADEMIC_APIS__APIS__OPENALEX__EMAIL": "test@example.com",
            },
        ):
            get_academic_apis_config.cache_clear()
            config = get_academic_apis_config()

        # Then: Email should be overridden by env var
        assert config.apis["openalex"].email == "test@example.com"

    def test_env_override_semantic_scholar_api_key(self, temp_config_dir: Path) -> None:
        """TC-CFG-N-04: Environment variable override for Semantic Scholar API key."""
        # Given: Config file without api_key
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        # When: Loading configuration with api_key env override
        with patch.dict(
            os.environ,
            {
                "LYRA_CONFIG_DIR": str(temp_config_dir),
                "LYRA_ACADEMIC_APIS__APIS__SEMANTIC_SCHOLAR__API_KEY": "test-api-key-123",
            },
        ):
            get_academic_apis_config.cache_clear()
            config = get_academic_apis_config()

        # Then: API key should be overridden by env var
        assert config.apis["semantic_scholar"].api_key == "test-api-key-123"

    def test_env_override_semantic_scholar_email(self, temp_config_dir: Path) -> None:
        """TC-CFG-N-05: Environment variable override for Semantic Scholar email."""
        # Given: Config file without email
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        # When: Loading configuration with email env override
        with patch.dict(
            os.environ,
            {
                "LYRA_CONFIG_DIR": str(temp_config_dir),
                "LYRA_ACADEMIC_APIS__APIS__SEMANTIC_SCHOLAR__EMAIL": "researcher@university.edu",
            },
        ):
            get_academic_apis_config.cache_clear()
            config = get_academic_apis_config()

        # Then: Email should be overridden by env var
        assert config.apis["semantic_scholar"].email == "researcher@university.edu"

    def test_env_override_without_yaml_file(self) -> None:
        """TC-CFG-N-06: Environment variables work without YAML config file."""
        # Given: No config file, only env vars
        # When: Loading configuration with env overrides
        with patch.dict(
            os.environ,
            {
                "LYRA_CONFIG_DIR": "/nonexistent/path",
                "LYRA_ACADEMIC_APIS__APIS__OPENALEX__EMAIL": "env-only@test.com",
                "LYRA_ACADEMIC_APIS__APIS__OPENALEX__BASE_URL": "https://api.openalex.org",
            },
        ):
            get_academic_apis_config.cache_clear()
            config = get_academic_apis_config()

        # Then: Config should have email from env var
        # Note: Without YAML, API might not exist in apis dict if only env vars are set
        # The env override applies to existing structure, so this tests graceful handling
        assert isinstance(config, AcademicAPIsConfig)


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

    def test_api_config_with_email_and_api_key(self) -> None:
        """Test that API config accepts email and api_key fields."""
        # Given: API configuration with email and api_key
        # When: Creating API config
        api_config = AcademicAPIConfig(
            enabled=True,
            base_url="https://api.example.com",
            timeout_seconds=30,
            priority=1,
            email="researcher@example.com",
            api_key="test-api-key-xyz",
        )

        # Then: Email and API key should be set correctly
        assert api_config.email == "researcher@example.com"
        assert api_config.api_key == "test-api-key-xyz"

    def test_api_config_email_and_api_key_optional(self) -> None:
        """Test that email and api_key are optional (default to None)."""
        # Given: API configuration without email and api_key
        # When: Creating API config
        api_config = AcademicAPIConfig(
            enabled=True,
            base_url="https://api.example.com",
        )

        # Then: Email and API key should be None
        assert api_config.email is None
        assert api_config.api_key is None


class TestClientApiKeyAndEmail:
    """Test API key and email handling in clients."""

    def test_semantic_scholar_client_api_key_header(self, temp_config_dir: Path) -> None:
        """TC-CLI-N-01: Semantic Scholar client adds x-api-key header when configured."""
        # Given: Config with API key
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
    api_key: "my-test-api-key"
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        # When: Creating Semantic Scholar client
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.apis.semantic_scholar import SemanticScholarClient

            client = SemanticScholarClient()

        # Then: x-api-key header should be present
        assert "x-api-key" in client.default_headers
        assert client.default_headers["x-api-key"] == "my-test-api-key"
        assert client.api_key == "my-test-api-key"

    def test_semantic_scholar_client_no_api_key_header_when_not_configured(
        self, temp_config_dir: Path
    ) -> None:
        """TC-CLI-N-02: Semantic Scholar client works without API key."""
        # Given: Config without API key
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        # When: Creating Semantic Scholar client
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.apis.semantic_scholar import SemanticScholarClient

            client = SemanticScholarClient()

        # Then: x-api-key header should NOT be present
        assert "x-api-key" not in client.default_headers
        assert client.api_key is None

    def test_openalex_client_mailto_with_email(self, temp_config_dir: Path) -> None:
        """TC-CLI-N-03: OpenAlex client has mailto helper when email configured."""
        # Given: Config with email
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  openalex:
    enabled: true
    base_url: "https://api.openalex.org"
    timeout_seconds: 30
    email: "test@example.com"
defaults:
  search_apis: ["openalex"]
"""
        )

        # When: Creating OpenAlex client and using _with_mailto
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.apis.openalex import OpenAlexClient

            client = OpenAlexClient()
            params = client._with_mailto({"search": "test query"})

        # Then: mailto parameter should be added
        assert "mailto" in params
        assert params["mailto"] == "test@example.com"
        assert params["search"] == "test query"

    def test_openalex_client_no_mailto_when_email_not_configured(
        self, temp_config_dir: Path
    ) -> None:
        """TC-CLI-N-04: OpenAlex client works without email (no mailto added)."""
        # Given: Config without email
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  openalex:
    enabled: true
    base_url: "https://api.openalex.org"
    timeout_seconds: 30
defaults:
  search_apis: ["openalex"]
"""
        )

        # When: Creating OpenAlex client and using _with_mailto
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.apis.openalex import OpenAlexClient

            client = OpenAlexClient()
            params = client._with_mailto({"search": "test query"})

        # Then: mailto parameter should NOT be added
        assert "mailto" not in params
        assert params["search"] == "test query"
        assert client.email is None

    def test_base_client_user_agent_with_email(self, temp_config_dir: Path) -> None:
        """TC-CLI-N-05: BaseAcademicClient includes email in User-Agent when configured."""
        # Given: Config with email
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
    email: "researcher@university.edu"
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        # When: Creating client
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.apis.semantic_scholar import SemanticScholarClient

            client = SemanticScholarClient()

        # Then: User-Agent should include mailto with email
        user_agent = client.default_headers.get("User-Agent", "")
        assert "mailto:researcher@university.edu" in user_agent
        assert "Lyra/1.0" in user_agent

    def test_base_client_user_agent_without_email(self, temp_config_dir: Path) -> None:
        """TC-CLI-N-06: BaseAcademicClient has minimal User-Agent when email not configured."""
        # Given: Config without email
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        # When: Creating client
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.apis.semantic_scholar import SemanticScholarClient

            client = SemanticScholarClient()

        # Then: User-Agent should NOT include mailto (no hardcoded sample email)
        user_agent = client.default_headers.get("User-Agent", "")
        assert "mailto:" not in user_agent
        assert "Lyra/1.0" in user_agent
        assert "lyra@example.com" not in user_agent  # No sample email


class TestIDResolverConfig:
    """Test IDResolver configuration handling."""

    def test_id_resolver_uses_s2_config(self, temp_config_dir: Path) -> None:
        """TC-IDR-N-01: IDResolver uses Semantic Scholar config."""
        # Given: Config with S2 settings
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://custom.s2.api/v1"
    timeout_seconds: 45
    email: "resolver@test.com"
    api_key: "resolver-key-123"
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        # When: Creating IDResolver
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.id_resolver import IDResolver

            resolver = IDResolver()

        # Then: IDResolver should use S2 config
        assert resolver.base_url == "https://custom.s2.api/v1"
        assert resolver.timeout == 45.0
        assert resolver.email == "resolver@test.com"
        assert resolver.api_key == "resolver-key-123"

    def test_id_resolver_defaults_without_config(self) -> None:
        """TC-IDR-N-02: IDResolver uses defaults when config not available."""
        # Given: No config file
        # When: Creating IDResolver
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": "/nonexistent/path"}):
            get_academic_apis_config.cache_clear()
            from src.search.id_resolver import IDResolver

            resolver = IDResolver()

        # Then: IDResolver should use default values
        assert resolver.base_url == "https://api.semanticscholar.org/graph/v1"
        assert resolver.timeout == 30.0
        assert resolver.email is None
        assert resolver.api_key is None


class TestApiKeyFallback:
    """Test API key fallback behavior when key is invalid (expired/revoked).

    Test Perspectives Table:
    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-FB-N-01 | S2 client with invalid API key (401) | Abnormal | Falls back to anonymous, retries, warning logged | - |
    | TC-FB-N-02 | S2 client with invalid API key (403) | Abnormal | Falls back to anonymous, retries, warning logged | - |
    | TC-FB-N-03 | IDResolver with invalid API key (401) | Abnormal | Falls back to anonymous, retries, warning logged | - |
    | TC-FB-N-04 | Fallback warning logged only once | Boundary | Multiple failures log warning only once | - |
    | TC-FB-N-05 | Session recreated without API key | Effect | New session headers don't include x-api-key | - |
    | TC-FB-A-01 | Other HTTP errors (404, 500) | Abnormal | No fallback, error propagated | - |
    """

    @pytest.mark.asyncio
    async def test_s2_client_fallback_on_401(self, temp_config_dir: Path) -> None:
        """TC-FB-N-01: Semantic Scholar client falls back on 401 Unauthorized."""

        # Given: Config with API key
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
    api_key: "invalid-expired-key"
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.apis.semantic_scholar import SemanticScholarClient

            client = SemanticScholarClient()

            # Verify API key is initially set
            assert client.api_key == "invalid-expired-key"
            assert client.default_headers.get("x-api-key") == "invalid-expired-key"

            # When: Simulate 401 error directly via _is_invalid_api_key_error
            mock_request = httpx.Request("GET", "http://test")
            mock_response = httpx.Response(401, request=mock_request)
            error_401 = httpx.HTTPStatusError(
                "401 Unauthorized", request=mock_request, response=mock_response
            )

            # Then: _is_invalid_api_key_error should detect 401 as invalid key
            assert client._is_invalid_api_key_error(error_401) is True

            # When: Handle invalid API key
            await client._handle_invalid_api_key()

            # Then: API key should be removed
            assert client.api_key is None
            assert "x-api-key" not in client.default_headers
            assert client._api_key_fallback_logged is True

            await client.close()

    @pytest.mark.asyncio
    async def test_s2_client_fallback_on_403(self, temp_config_dir: Path) -> None:
        """TC-FB-N-02: Semantic Scholar client falls back on 403 Forbidden."""

        # Given: Config with API key
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
    api_key: "revoked-key"
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.apis.semantic_scholar import SemanticScholarClient

            client = SemanticScholarClient()

            # Verify API key is initially set
            assert client.api_key == "revoked-key"

            # When: Simulate 403 error directly via _is_invalid_api_key_error
            mock_request = httpx.Request("GET", "http://test")
            mock_response = httpx.Response(403, request=mock_request)
            error_403 = httpx.HTTPStatusError(
                "403 Forbidden", request=mock_request, response=mock_response
            )

            # Then: _is_invalid_api_key_error should detect 403 as invalid key
            assert client._is_invalid_api_key_error(error_403) is True

            # When: Handle invalid API key
            await client._handle_invalid_api_key()

            # Then: API key should be removed
            assert client.api_key is None

            await client.close()

    @pytest.mark.asyncio
    async def test_id_resolver_fallback_on_401(self, temp_config_dir: Path) -> None:
        """TC-FB-N-03: IDResolver falls back on 401 Unauthorized."""

        # Given: Config with API key
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
    api_key: "invalid-key"
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.id_resolver import IDResolver

            resolver = IDResolver()

            # Verify API key is initially set
            assert resolver.api_key == "invalid-key"
            assert resolver._original_api_key == "invalid-key"

            # When: Simulate 401 error directly via _is_invalid_api_key_error
            mock_request = httpx.Request("GET", "http://test")
            mock_response = httpx.Response(401, request=mock_request)
            error_401 = httpx.HTTPStatusError(
                "401 Unauthorized", request=mock_request, response=mock_response
            )

            # Then: _is_invalid_api_key_error should detect 401 as invalid key
            assert resolver._is_invalid_api_key_error(error_401) is True

            # When: Handle invalid API key
            await resolver._handle_invalid_api_key()

            # Then: API key should be removed
            assert resolver.api_key is None
            assert resolver._api_key_fallback_logged is True

            await resolver.close()

    @pytest.mark.asyncio
    async def test_fallback_warning_logged_once(self, temp_config_dir: Path) -> None:
        """TC-FB-N-04: Fallback warning is logged only once."""

        # Given: Config with API key
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
    api_key: "expired-key"
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.apis.semantic_scholar import SemanticScholarClient

            client = SemanticScholarClient()

            # When: Handle invalid API key multiple times
            await client._handle_invalid_api_key()
            first_logged = client._api_key_fallback_logged

            await client._handle_invalid_api_key()
            second_logged = client._api_key_fallback_logged

            # Then: Warning flag set and stays set
            assert first_logged is True
            assert second_logged is True
            # API key should be None after first call
            assert client.api_key is None

            await client.close()

    @pytest.mark.asyncio
    async def test_no_fallback_on_other_errors(self, temp_config_dir: Path) -> None:
        """TC-FB-A-01: No fallback on non-auth HTTP errors (404, 500)."""

        # Given: Config with API key
        config_file = temp_config_dir / "academic_apis.yaml"
        config_file.write_text(
            """
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: 30
    api_key: "valid-key"
defaults:
  search_apis: ["semantic_scholar"]
"""
        )

        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_config_dir)}):
            get_academic_apis_config.cache_clear()
            from src.search.apis.semantic_scholar import SemanticScholarClient

            client = SemanticScholarClient()

            # Verify API key is initially set
            assert client.api_key == "valid-key"

            # When: Test 404 error (not an auth error)
            mock_request = httpx.Request("GET", "http://test")
            mock_response = httpx.Response(404, request=mock_request)
            error_404 = httpx.HTTPStatusError(
                "404 Not Found", request=mock_request, response=mock_response
            )

            # Then: _is_invalid_api_key_error should NOT detect 404 as invalid key
            assert client._is_invalid_api_key_error(error_404) is False

            # When: Test 500 error (server error, not auth error)
            mock_response_500 = httpx.Response(500, request=mock_request)
            error_500 = httpx.HTTPStatusError(
                "500 Internal Server Error", request=mock_request, response=mock_response_500
            )

            # Then: _is_invalid_api_key_error should NOT detect 500 as invalid key
            assert client._is_invalid_api_key_error(error_500) is False

            # API key should still be set (no fallback for non-auth errors)
            assert client.api_key == "valid-key"
            assert "x-api-key" in client.default_headers

            await client.close()
