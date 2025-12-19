"""
Pytest fixtures and configuration for Lancet tests.

=============================================================================
Test Classification (§7.1.7, §16.10.1)
=============================================================================

Test Execution Layers (Cloud Agent Compatible):

L1: CI Layer (Cloud Agent / GitHub Actions / GitLab CI)
    - Runs: unit + integration tests only
    - All external services mocked
    - No display, Chrome, Ollama required
    - Command: pytest -m "not e2e and not slow"

L2: Local Layer (Developer WSL2 environment)
    - Runs: L1 + container integration tests
    - Requires: Podman containers (Ollama, ML Server)
    - Command: pytest -m "not e2e"

L3: E2E Layer (Full environment)
    - Runs: All tests including E2E
    - Requires: Chrome CDP, Ollama, network access, display
    - Command: pytest (all tests) or pytest -m e2e

Primary Markers (Execution Speed):
- @pytest.mark.unit: Single class/function, no external dependencies
  - Fast (<1s per test, <30s total)
  - All external services fully mocked
  - Can run anywhere (CI, local, container)
  - DEFAULT: Tests without marker are auto-classified as unit

- @pytest.mark.integration: Multiple components, mocked external dependencies
  - Medium (<5s per test, <2min total)
  - Component integration verified
  - External services mocked but realistic behavior simulated
  - Can run anywhere

- @pytest.mark.e2e: Real environment, actual external services
  - Variable duration
  - Requires real Chrome, Ollama, network access
  - DEFAULT EXCLUDED: Must use `pytest -m e2e` to run
  - Risk of IP pollution, rate limiting

- @pytest.mark.slow: Tests taking >5 seconds
  - DEFAULT EXCLUDED: Must use `pytest -m slow` to run
  - Typically heavy LLM or large data processing

Risk-Based Sub-Markers (E2E only, §16.10.1):
- @pytest.mark.external: Uses external services with moderate block risk
  - Example: Mojeek, Qwant (block-resistant engines)
  - Run with: `pytest -m "e2e and external"`

- @pytest.mark.rate_limited: Uses services with strict rate limits / high block risk
  - Example: DuckDuckGo, Google (easily blocked)
  - Run with: `pytest -m "e2e and rate_limited"`
  - WARNING: May pollute host IP

- @pytest.mark.manual: Requires human interaction (CAPTCHA, etc.)
  - Run with: `pytest -m "e2e and manual"`
  - Should be run from tests/scripts/ as standalone scripts

=============================================================================
Cloud Agent Environment Detection
=============================================================================

Supported cloud agent environments:
- Cursor Cloud Agent: CURSOR_CLOUD_AGENT, CURSOR_SESSION_ID, CURSOR_BACKGROUND
- Claude Code: CLAUDE_CODE environment variable
- GitHub Actions: GITHUB_ACTIONS=true
- GitLab CI: GITLAB_CI environment variable
- Generic CI: CI=true

In cloud agent environments:
- E2E tests are automatically skipped
- Slow tests are automatically skipped (unless explicitly requested)
- Only unit and integration tests run by default

IMPORTANT: Cloud Agent Limitation
---------------------------------
クラウドエージェント環境（Cursor Cloud Agent、Claude Code等）では、
外部サービス依存のテスト（E2E、slow）は自動的にスキップされます。

**ローカル環境での追加テスト実行が必要です：**
  - E2Eテスト: pytest -m e2e
  - Slowテスト: pytest -m slow
  - 全テスト: pytest

依存関係が不足している場合、該当テストファイルは収集されません。
ローカル環境で `pip install -e ".[dev]"` を実行して全依存関係をインストールしてください。

=============================================================================
Default Execution
=============================================================================

By default, pytest runs: unit + integration (excludes e2e, slow)

To run all tests:
    pytest -m ""  # Empty marker filter

To run E2E tests:
    pytest -m e2e

To run E2E with specific risk level:
    pytest -m "e2e and external"
    pytest -m "e2e and rate_limited"

=============================================================================
Mock Strategy (§7.1.7)
=============================================================================

- External services (Ollama, Chrome): Always mocked in unit/integration
- File I/O: Use tmp_path fixture
- Database: Use in-memory SQLite (:memory:) or temp file
- Network: Prohibited in unit tests (use responses/aioresponses library)
"""

import os
import tempfile
from collections.abc import Generator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Set test environment before importing anything else
os.environ["LANCET_CONFIG_DIR"] = str(Path(__file__).parent.parent / "config")
os.environ["LANCET_GENERAL__LOG_LEVEL"] = "DEBUG"


# =============================================================================
# Cloud Agent Environment Detection
# =============================================================================

class CloudAgentType(Enum):
    """Types of cloud agent environments."""
    NONE = "none"
    CURSOR = "cursor"
    CLAUDE_CODE = "claude_code"
    GITHUB_ACTIONS = "github_actions"
    GITLAB_CI = "gitlab_ci"
    GENERIC_CI = "generic_ci"
    HEADLESS = "headless"


@dataclass
class EnvironmentInfo:
    """Information about the current execution environment."""
    is_cloud_agent: bool
    cloud_agent_type: CloudAgentType
    is_e2e_capable: bool
    is_wsl: bool
    is_container: bool
    has_display: bool


def detect_environment() -> EnvironmentInfo:
    """Detect the current execution environment.

    Returns:
        EnvironmentInfo with details about the environment.
    """
    # Check for display availability
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

    # Check for WSL
    is_wsl = False
    try:
        with open("/proc/version") as f:
            is_wsl = "microsoft" in f.read().lower()
    except (FileNotFoundError, PermissionError):
        pass

    # Check for container
    is_container = (
        os.path.exists("/.dockerenv") or
        os.path.exists("/run/.containerenv")
    )

    # Detect cloud agent type
    is_cloud_agent = False
    cloud_agent_type = CloudAgentType.NONE

    # Cursor Cloud Agent detection
    if (os.environ.get("CURSOR_CLOUD_AGENT") or
        os.environ.get("CURSOR_SESSION_ID") or
        os.environ.get("CURSOR_BACKGROUND") == "true"):
        is_cloud_agent = True
        cloud_agent_type = CloudAgentType.CURSOR

    # Claude Code detection (Anthropic)
    elif os.environ.get("CLAUDE_CODE"):
        is_cloud_agent = True
        cloud_agent_type = CloudAgentType.CLAUDE_CODE

    # GitHub Actions detection
    elif os.environ.get("GITHUB_ACTIONS") == "true":
        is_cloud_agent = True
        cloud_agent_type = CloudAgentType.GITHUB_ACTIONS

    # GitLab CI detection
    elif os.environ.get("GITLAB_CI"):
        is_cloud_agent = True
        cloud_agent_type = CloudAgentType.GITLAB_CI

    # Generic CI detection
    elif os.environ.get("CI") == "true":
        is_cloud_agent = True
        cloud_agent_type = CloudAgentType.GENERIC_CI

    # Headless environment detection (no display, not WSL, not explicitly local)
    elif not has_display and not is_wsl and not os.environ.get("LANCET_LOCAL"):
        is_cloud_agent = True
        cloud_agent_type = CloudAgentType.HEADLESS

    # Determine E2E capability
    is_e2e_capable = (
        os.environ.get("LANCET_HEADLESS") == "true" or
        has_display or
        is_wsl  # WSL can access Windows display via CDP
    )

    return EnvironmentInfo(
        is_cloud_agent=is_cloud_agent,
        cloud_agent_type=cloud_agent_type,
        is_e2e_capable=is_e2e_capable,
        is_wsl=is_wsl,
        is_container=is_container,
        has_display=has_display,
    )


# Detect environment at module load
_env_info = detect_environment()


def is_cloud_agent() -> bool:
    """Check if running in a cloud agent environment."""
    return _env_info.is_cloud_agent


def get_cloud_agent_type() -> CloudAgentType:
    """Get the type of cloud agent environment."""
    return _env_info.cloud_agent_type


def is_e2e_capable() -> bool:
    """Check if the environment can run E2E tests."""
    return _env_info.is_e2e_capable


# =============================================================================
# Dependency Checking for Minimal Environments
# =============================================================================

def _check_core_dependencies() -> tuple[bool, list[str]]:
    """Check if core dependencies are available.

    Returns:
        Tuple of (all_available, missing_packages)
    """
    missing = []

    # Core packages required for most tests
    core_packages = [
        ("aiosqlite", "aiosqlite"),
        ("pydantic_settings", "pydantic-settings"),
        ("warcio", "warcio"),
        ("curl_cffi", "curl_cffi"),
        ("structlog", "structlog"),
        ("networkx", "networkx"),
    ]

    for module_name, package_name in core_packages:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)

    return len(missing) == 0, missing


# Check dependencies at module load
_deps_available, _missing_deps = _check_core_dependencies()


def pytest_ignore_collect(collection_path, config):
    """Skip test modules that require unavailable dependencies.

    ONLY in cloud agent environments with missing dependencies,
    silently skip tests that would fail due to import errors.
    Local environments will show normal import errors.
    """
    # Only apply in cloud agent environments
    if not _env_info.is_cloud_agent:
        return None  # Local: show normal errors

    if _deps_available:
        return None  # All deps available, don't skip

    # Files that can run without full dependencies
    minimal_safe_files = {
        "test_cloud_agent_detection.py",
        "conftest.py",
        "__init__.py",
    }

    filename = collection_path.name

    # Allow minimal-safe files
    if filename in minimal_safe_files:
        return None

    # Skip other test files in cloud agent with missing deps
    if filename.startswith("test_") and filename.endswith(".py"):
        return True  # Skip this file

    return None


# =============================================================================
# Pytest Hooks for Test Classification
# =============================================================================


def pytest_configure(config):
    """Register custom markers for test classification per §7.1.7 and §16.10.1."""
    # Primary classification markers
    config.addinivalue_line(
        "markers", "unit: Unit tests with no external dependencies (fast, <1s/test)"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests with mocked external dependencies (<5s/test)"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests requiring real environment (excluded by default)"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take more than 5 seconds (excluded by default)"
    )

    # Risk-based sub-markers for E2E tests (§16.10.1)
    config.addinivalue_line(
        "markers", "external: E2E using external services with moderate block risk (Mojeek, Qwant)"
    )
    config.addinivalue_line(
        "markers", "rate_limited: E2E using services with high block risk (DuckDuckGo, Google)"
    )
    config.addinivalue_line(
        "markers", "manual: E2E requiring human interaction (CAPTCHA resolution)"
    )

    # Always show cloud agent notice (important for users to know)
    if _env_info.is_cloud_agent:
        print(f"\n{'='*70}")
        print("[Lancet Test] CLOUD AGENT ENVIRONMENT DETECTED")
        print(f"{'='*70}")
        print(f"  Agent Type: {_env_info.cloud_agent_type.value}")
        print(f"  E2E Capable: {_env_info.is_e2e_capable}")
        print()
        print("  ⚠️  E2E/Slow tests are SKIPPED in this environment.")
        print("  📋 Please run the following tests LOCALLY:")
        print()
        print("      pytest -m e2e          # E2E tests (Chrome, Ollama required)")
        print("      pytest -m slow         # Slow tests (>5s)")
        print("      pytest                 # All tests")
        print()
        if not _deps_available:
            print(f"  ⚠️  Missing dependencies: {', '.join(_missing_deps)}")
            print("      Only minimal-safe tests will run.")
            print("      Install with: pip install -e '.[dev]'")
            print()
        print(f"{'='*70}\n")

    # Log environment info for debugging (verbose mode)
    elif config.option.verbose > 0:
        print("\n[Lancet Test] Environment Detection:")
        print(f"  Cloud Agent: {_env_info.is_cloud_agent} ({_env_info.cloud_agent_type.value})")
        print(f"  E2E Capable: {_env_info.is_e2e_capable}")
        print(f"  WSL: {_env_info.is_wsl}, Container: {_env_info.is_container}")
        print(f"  Display: {_env_info.has_display}")

        # Show dependency status
        if not _deps_available:
            print(f"  Dependencies: MINIMAL MODE (missing: {', '.join(_missing_deps)})")
            print("  → Only minimal-safe tests will run")
        else:
            print("  Dependencies: Full")


def pytest_collection_modifyitems(config, items):
    """
    Auto-apply markers and skip tests based on environment.

    Per §7.1.7, tests should be classified as unit/integration/e2e.
    Tests without explicit markers are assumed to be unit tests.

    In cloud agent environments (Cursor, Claude Code, GitHub Actions, etc.):
    - E2E tests are automatically skipped
    - Slow tests are automatically skipped (unless --run-slow is passed)
    """
    # Skip reasons for cloud agent environment
    skip_e2e_reason = pytest.mark.skip(
        reason=f"E2E tests skipped in cloud agent environment ({_env_info.cloud_agent_type.value}). "
               f"Run locally with: pytest -m e2e"
    )
    skip_slow_reason = pytest.mark.skip(
        reason=f"Slow tests skipped in cloud agent environment ({_env_info.cloud_agent_type.value}). "
               f"Run with: pytest -m slow"
    )

    for item in items:
        # Check if test already has a classification marker
        has_classification = any(
            marker.name in ("unit", "integration", "e2e") for marker in item.iter_markers()
        )

        # Default to unit test if no classification
        if not has_classification:
            item.add_marker(pytest.mark.unit)

        # In cloud agent environment, skip E2E and slow tests
        if _env_info.is_cloud_agent:
            # Skip E2E tests
            if any(marker.name == "e2e" for marker in item.iter_markers()):
                item.add_marker(skip_e2e_reason)

            # Skip slow tests (unless explicitly requested)
            if any(marker.name == "slow" for marker in item.iter_markers()):
                # Check if slow tests are explicitly requested via marker expression
                markexpr = config.getoption("-m", default="")
                if "slow" not in markexpr:
                    item.add_marker(skip_slow_reason)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_db_path(temp_dir: Path) -> Path:
    """Get path for temporary test database."""
    return temp_dir / "test_lancet.db"


@pytest_asyncio.fixture
async def test_database(temp_db_path: Path):
    """Create a temporary test database.

    Guards against global database singleton interference by saving
    and restoring the global state around the test.
    """
    from src.storage import database as db_module
    from src.storage.database import Database

    # Save and clear global to prevent interference from previous tests
    saved_global = db_module._db
    db_module._db = None

    db = Database(temp_db_path)
    await db.connect()
    await db.initialize_schema()

    yield db

    await db.close()

    # Restore global (should be None anyway, but be defensive)
    db_module._db = saved_global


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    from src.utils.config import (
        BrowserConfig,
        CircuitBreakerConfig,
        CrawlerConfig,
        EmbeddingConfig,
        GeneralConfig,
        LLMConfig,
        MetricsConfig,
        NLIConfig,
        NotificationConfig,
        QualityConfig,
        RerankerConfig,
        SearchConfig,
        Settings,
        StorageConfig,
        TaskLimitsConfig,
        TorConfig,
    )

    return Settings(
        general=GeneralConfig(log_level="DEBUG"),
        storage=StorageConfig(
            database_path=":memory:",
            warc_dir="/tmp/warc",
            screenshots_dir="/tmp/screenshots",
            reports_dir="/tmp/reports",
            cache_dir="/tmp/cache",
        ),
        search=SearchConfig(
            initial_query_count_gpu=4,
            results_per_query=5,
        ),
        crawler=CrawlerConfig(),
        llm=LLMConfig(),
        embedding=EmbeddingConfig(use_gpu=False),
        reranker=RerankerConfig(use_gpu=False, top_k=10),
        task_limits=TaskLimitsConfig(),
        tor=TorConfig(enabled=False),
        browser=BrowserConfig(),
        nli=NLIConfig(),
        notification=NotificationConfig(),
        quality=QualityConfig(),
        circuit_breaker=CircuitBreakerConfig(),
        metrics=MetricsConfig(),
    )


@pytest.fixture
def sample_passages():
    """Sample passages for ranking tests."""
    return [
        {
            "id": "p1",
            "text": "Artificial intelligence is transforming healthcare through machine learning applications.",
        },
        {
            "id": "p2",
            "text": "The weather forecast predicts rain tomorrow in Tokyo.",
        },
        {
            "id": "p3",
            "text": "Deep learning models have achieved remarkable results in medical imaging diagnosis.",
        },
        {
            "id": "p4",
            "text": "Python is a popular programming language for data science and machine learning.",
        },
        {
            "id": "p5",
            "text": "Healthcare AI systems can assist doctors in detecting diseases early.",
        },
    ]


@pytest.fixture
def mock_aiohttp_session():
    """Create mock aiohttp session."""
    session = AsyncMock()
    return session


class MockResponse:
    """Mock aiohttp response."""

    def __init__(self, json_data: dict, status: int = 200):
        self._json_data = json_data
        self.status = status

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def make_mock_response():
    """Factory for creating mock responses."""

    def _make(json_data: dict, status: int = 200):
        return MockResponse(json_data, status)

    return _make


# =============================================================================
# Provider Reset Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def reset_search_provider():
    """Reset search provider singletons between tests.

    Ensures that each test starts with a fresh provider state.
    This prevents 'Event loop is closed' errors from provider reuse.
    """
    yield
    # Reset after each test
    try:
        from src.search.provider import reset_registry
        reset_registry()
    except ImportError:
        # Dependencies not available in minimal test environment
        pass


@pytest.fixture(autouse=True)
def reset_global_database():
    """Reset global database singleton between tests.

    Prevents asyncio.Lock() from being bound to a stale event loop,
    which can cause intermittent hangs when running multiple tests.
    """
    yield
    # Reset global database after each test
    try:
        from src.storage import database as db_module
        if db_module._db is not None:
            # Force reset without awaiting (connection should already be closed
            # by the test_database fixture if it was used)
            db_module._db = None
    except ImportError:
        # Dependencies not available in minimal test environment
        pass


# =============================================================================
# Mock Fixtures for External Services (§7.1.7 Mock Strategy)
# =============================================================================


@pytest.fixture
def mock_ollama():
    """Mock Ollama client for unit tests.

    Per §7.1.7: External services (Ollama) should be mocked in unit/integration tests.
    """
    with patch("src.filter.llm_extract.ollama") as mock_ollama:
        mock_ollama.chat = AsyncMock(return_value={"message": {"content": "{}"}})
        yield mock_ollama


@pytest.fixture
def mock_browser():
    """Mock Playwright browser for unit tests.

    Per §7.1.7: External services (Chrome) should be mocked in unit/integration tests.
    """
    with patch("src.crawler.browser.playwright") as mock_pw:
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html></html>")
        mock_page.screenshot = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        yield mock_browser


# =============================================================================
# Database Fixtures (§7.1.7 Mock Strategy)
# =============================================================================


@pytest_asyncio.fixture
async def memory_database():
    """Create an in-memory database for fast unit tests.

    Per §7.1.7: Database should use in-memory SQLite for unit tests.
    """
    from src.storage.database import Database

    db = Database(":memory:")
    await db.connect()
    await db.initialize_schema()

    yield db

    await db.close()


# =============================================================================
# Utility Functions for Tests
# =============================================================================


def assert_dict_contains(actual: dict, expected: dict) -> None:
    """Assert that actual dict contains all key-value pairs from expected.

    Provides clear error messages per §7.1.2 (Diagnosability).
    """
    for key, value in expected.items():
        assert key in actual, (
            f"Key '{key}' not found in actual dict. Keys present: {list(actual.keys())}"
        )
        assert actual[key] == value, (
            f"Value mismatch for key '{key}': expected {value!r}, got {actual[key]!r}"
        )


def assert_async_called_with(mock: AsyncMock, *args, **kwargs) -> None:
    """Assert that async mock was called with specific arguments.

    Provides clear error messages per §7.1.2 (Diagnosability).
    """
    mock.assert_called()
    call_args = mock.call_args
    if args:
        assert call_args.args == args, f"Expected args {args}, got {call_args.args}"
    if kwargs:
        assert call_args.kwargs == kwargs, f"Expected kwargs {kwargs}, got {call_args.kwargs}"


def assert_in_range(value: float, min_val: float, max_val: float, name: str = "value") -> None:
    """Assert that a value is within a specified range.

    Per §7.1.2: Range checks should be explicit with tolerance.
    """
    assert min_val <= value <= max_val, (
        f"{name} = {value} is outside expected range [{min_val}, {max_val}]"
    )


# =============================================================================
# Test Data Factories (§7.1.3 Test Data Requirements)
# =============================================================================


@pytest.fixture
def make_fragment():
    """Factory for creating test fragments with realistic data.

    Per §7.1.3: Test data should be realistic and diverse.
    """

    def _make(
        fragment_id: str,
        text: str,
        url: str = "https://example.com/page",
        source_tag: str = "unknown",
    ) -> dict:
        return {
            "id": fragment_id,
            "text": text,
            "url": url,
            "source_tag": source_tag,
            "extracted_at": "2024-01-01T00:00:00Z",
        }

    return _make


@pytest.fixture
def make_claim():
    """Factory for creating test claims with realistic data.

    Per §7.1.3: Test data should be realistic and diverse.
    """

    def _make(
        claim_id: str,
        text: str,
        confidence: float = 0.8,
        verdict: str = "supported",
    ) -> dict:
        return {
            "id": claim_id,
            "text": text,
            "confidence": confidence,
            "verdict": verdict,
            "created_at": "2024-01-01T00:00:00Z",
        }

    return _make


# =============================================================================
# Session-scoped Cleanup Fixtures
# =============================================================================


@pytest.fixture(scope="session", autouse=True)
def cleanup_aiohttp_sessions(request):
    """Cleanup global aiohttp client sessions after all tests complete.

    This prevents 'Unclosed client session' warnings by ensuring all
    singleton clients are properly closed at the end of the test session.

    Note: We use synchronous reset instead of async cleanup to avoid
    creating a new event loop, which can interfere with pytest-asyncio's
    event loop management and cause intermittent hangs.
    """
    yield  # Run all tests first

    # Synchronous cleanup - just reset globals without async operations
    # This avoids event loop conflicts with pytest-asyncio
    try:
        from src.filter import llm

        llm._client = None
    except ImportError:
        pass

    try:
        from src.storage import database as db_module

        db_module._db = None
    except ImportError:
        pass
