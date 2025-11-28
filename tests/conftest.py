"""
Pytest fixtures and configuration for Lancet tests.

Test Classification (§7.1.7):
- @pytest.mark.unit: No external dependencies, fast (<30s total)
- @pytest.mark.integration: Mocked external dependencies (<2min total)
- @pytest.mark.e2e: Real environment, manual execution only

Mock Strategy (§7.1.7):
- External services (Ollama, Chrome): Always mocked in unit/integration
- File I/O: Use tmp_path fixture
- Database: Use in-memory SQLite or temp file
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Set test environment before importing anything else
os.environ["LANCET_CONFIG_DIR"] = str(Path(__file__).parent.parent / "config")
os.environ["LANCET_GENERAL__LOG_LEVEL"] = "DEBUG"


# =============================================================================
# Pytest Hooks for Test Classification
# =============================================================================

def pytest_configure(config):
    """Register custom markers for test classification per §7.1.7."""
    config.addinivalue_line(
        "markers", "unit: Unit tests with no external dependencies (fast, <30s total)"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests with mocked external dependencies (<2min total)"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests requiring real environment (manual execution only)"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take more than 5 seconds"
    )


def pytest_collection_modifyitems(config, items):
    """
    Auto-apply 'unit' marker to tests without explicit classification.
    
    Per §7.1.7, tests should be classified as unit/integration/e2e.
    Tests without explicit markers are assumed to be unit tests.
    """
    for item in items:
        # Check if test already has a classification marker
        has_classification = any(
            marker.name in ("unit", "integration", "e2e")
            for marker in item.iter_markers()
        )
        
        # Default to unit test if no classification
        if not has_classification:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


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
    """Create a temporary test database."""
    from src.storage.database import Database
    
    db = Database(temp_db_path)
    await db.connect()
    await db.initialize_schema()
    
    yield db
    
    await db.close()


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    from src.utils.config import Settings, GeneralConfig, StorageConfig, SearchConfig
    from src.utils.config import CrawlerConfig, LLMConfig, EmbeddingConfig, RerankerConfig
    from src.utils.config import TaskLimitsConfig, TorConfig, BrowserConfig
    from src.utils.config import NLIConfig, NotificationConfig, QualityConfig
    from src.utils.config import CircuitBreakerConfig, MetricsConfig
    
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
# Provider Reset Fixtures (Phase 17.1.1)
# =============================================================================

@pytest.fixture(autouse=True)
def reset_search_provider():
    """Reset search provider singletons between tests.
    
    Ensures that each test starts with a fresh provider state.
    This prevents 'Event loop is closed' errors from provider reuse.
    """
    yield
    # Reset after each test
    from src.search.provider import reset_registry
    reset_registry()


# =============================================================================
# Mock Fixtures for External Services (§7.1.7 Mock Strategy)
# =============================================================================

@pytest.fixture
def mock_ollama():
    """Mock Ollama client for unit tests.
    
    Per §7.1.7: External services (Ollama) should be mocked in unit/integration tests.
    """
    with patch("src.filter.llm_extract.ollama") as mock_ollama:
        mock_ollama.chat = AsyncMock(return_value={
            "message": {"content": "{}"}
        })
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
        assert key in actual, f"Key '{key}' not found in actual dict. Keys present: {list(actual.keys())}"
        assert actual[key] == value, f"Value mismatch for key '{key}': expected {value!r}, got {actual[key]!r}"


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
    """
    yield  # Run all tests first
    
    # Cleanup after all tests complete
    async def _cleanup():
        # Cleanup Ollama client
        try:
            from src.filter.llm import _cleanup_client as cleanup_ollama
            await cleanup_ollama()
        except ImportError:
            pass
    
    # Run cleanup - use asyncio.run() to avoid deprecation warning
    try:
        asyncio.run(_cleanup())
    except RuntimeError:
        # Event loop already running (shouldn't happen in session teardown)
        pass

