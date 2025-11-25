"""
Pytest fixtures and configuration for Lancet tests.
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
def mock_searxng_response():
    """Mock SearXNG API response."""
    return {
        "results": [
            {
                "title": "Test Result 1",
                "url": "https://example.com/page1",
                "content": "This is the first test result snippet.",
                "engine": "google",
                "publishedDate": "2024-01-15",
            },
            {
                "title": "Test Result 2 - Academic",
                "url": "https://arxiv.org/abs/1234.5678",
                "content": "This is an academic paper snippet.",
                "engine": "google",
                "publishedDate": "2024-01-10",
            },
            {
                "title": "Government Report",
                "url": "https://www.go.jp/report/2024",
                "content": "Official government report on the topic.",
                "engine": "duckduckgo",
            },
        ],
        "infoboxes": [],
        "suggestions": ["related search 1", "related search 2"],
    }


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


# Utility functions for tests

def assert_dict_contains(actual: dict, expected: dict) -> None:
    """Assert that actual dict contains all key-value pairs from expected."""
    for key, value in expected.items():
        assert key in actual, f"Key '{key}' not found in actual dict"
        assert actual[key] == value, f"Value mismatch for key '{key}': {actual[key]} != {value}"


def assert_async_called_with(mock: AsyncMock, *args, **kwargs) -> None:
    """Assert that async mock was called with specific arguments."""
    mock.assert_called()
    call_args = mock.call_args
    if args:
        assert call_args.args == args
    if kwargs:
        assert call_args.kwargs == kwargs

