"""
Tests for src/search/searxng.py
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import MockResponse


class TestSearXNGClient:
    """Tests for SearXNGClient class."""

    @pytest.mark.asyncio
    async def test_search_basic(self, mock_searxng_response, make_mock_response):
        """Test basic search functionality."""
        from src.search.searxng import SearXNGClient
        
        client = SearXNGClient()
        
        mock_response = make_mock_response(mock_searxng_response)
        
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.get.return_value = mock_response
            mock_get_session.return_value = mock_session
            
            result = await client.search("test query")
        
        assert "results" in result
        assert len(result["results"]) == 3
        
        await client.close()

    @pytest.mark.asyncio
    async def test_search_with_engines(self, mock_searxng_response, make_mock_response):
        """Test search with specific engines."""
        from src.search.searxng import SearXNGClient
        
        client = SearXNGClient()
        mock_response = make_mock_response(mock_searxng_response)
        
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.get.return_value = mock_response
            mock_get_session.return_value = mock_session
            
            await client.search(
                "test query",
                engines=["google", "duckduckgo"],
            )
            
            # Verify engines parameter was included in URL
            call_args = mock_session.get.call_args
            url = call_args[0][0]
            assert "engines=google%2Cduckduckgo" in url or "engines=duckduckgo%2Cgoogle" in url
        
        await client.close()

    @pytest.mark.asyncio
    async def test_search_http_error(self, make_mock_response):
        """Test search handles HTTP errors."""
        from src.search.searxng import SearXNGClient
        
        client = SearXNGClient()
        mock_response = make_mock_response({}, status=500)
        
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.get.return_value = mock_response
            mock_get_session.return_value = mock_session
            
            result = await client.search("test query")
        
        assert result["results"] == []
        assert "error" in result
        assert "500" in result["error"]
        
        await client.close()

    @pytest.mark.asyncio
    async def test_search_timeout(self):
        """Test search handles timeout."""
        import asyncio
        from src.search.searxng import SearXNGClient
        
        client = SearXNGClient()
        
        # Create a mock that raises TimeoutError when used as context manager
        class TimeoutContextManager:
            async def __aenter__(self):
                raise asyncio.TimeoutError()
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
        
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.get.return_value = TimeoutContextManager()
            mock_get_session.return_value = mock_session
            
            result = await client.search("test query")
        
        assert result["results"] == []
        assert result["error"] == "Timeout"
        
        await client.close()

    @pytest.mark.asyncio
    async def test_rate_limiting(self, mock_searxng_response, make_mock_response):
        """Test rate limiting delays requests."""
        import time
        from src.search.searxng import SearXNGClient
        
        client = SearXNGClient()
        client._min_interval = 0.1  # Shorter interval for testing
        mock_response = make_mock_response(mock_searxng_response)
        
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session.get.return_value = mock_response
            mock_get_session.return_value = mock_session
            
            start_time = time.time()
            await client.search("query 1")
            await client.search("query 2")
            elapsed = time.time() - start_time
        
        # Should take at least min_interval between requests
        assert elapsed >= client._min_interval
        
        await client.close()


class TestNormalizeQuery:
    """Tests for query normalization."""

    def test_normalize_query_basic(self):
        """Test basic query normalization."""
        from src.search.searxng import _normalize_query
        
        assert _normalize_query("Test Query") == "test query"
        assert _normalize_query("  Multiple   Spaces  ") == "multiple spaces"
        assert _normalize_query("UPPERCASE") == "uppercase"


class TestGetCacheKey:
    """Tests for cache key generation."""

    def test_cache_key_deterministic(self):
        """Test cache key is deterministic for same inputs."""
        from src.search.searxng import _get_cache_key
        
        key1 = _get_cache_key("test query", ["google"], "day")
        key2 = _get_cache_key("test query", ["google"], "day")
        
        assert key1 == key2

    def test_cache_key_different_for_different_queries(self):
        """Test cache key differs for different queries."""
        from src.search.searxng import _get_cache_key
        
        key1 = _get_cache_key("query 1", ["google"], "day")
        key2 = _get_cache_key("query 2", ["google"], "day")
        
        assert key1 != key2

    def test_cache_key_different_for_different_engines(self):
        """Test cache key differs for different engines."""
        from src.search.searxng import _get_cache_key
        
        key1 = _get_cache_key("query", ["google"], "day")
        key2 = _get_cache_key("query", ["bing"], "day")
        
        assert key1 != key2

    def test_cache_key_engine_order_independent(self):
        """Test cache key is same regardless of engine order."""
        from src.search.searxng import _get_cache_key
        
        key1 = _get_cache_key("query", ["google", "bing"], "day")
        key2 = _get_cache_key("query", ["bing", "google"], "day")
        
        assert key1 == key2


class TestClassifySource:
    """Tests for source classification."""

    def test_classify_academic(self):
        """Test academic source classification."""
        from src.search.searxng import _classify_source
        
        assert _classify_source("https://arxiv.org/abs/1234.5678") == "academic"
        assert _classify_source("https://pubmed.ncbi.nlm.nih.gov/12345") == "academic"
        assert _classify_source("https://www.jstage.jst.go.jp/article/xxx") == "academic"

    def test_classify_government(self):
        """Test government source classification."""
        from src.search.searxng import _classify_source
        
        assert _classify_source("https://www.go.jp/ministry/report") == "government"
        assert _classify_source("https://www.gov.uk/policy") == "government"
        assert _classify_source("https://example.gov/data") == "government"

    def test_classify_standards(self):
        """Test standards source classification."""
        from src.search.searxng import _classify_source
        
        assert _classify_source("https://www.iso.org/standard/12345") == "standards"
        assert _classify_source("https://tools.ietf.org/html/rfc1234") == "standards"
        assert _classify_source("https://www.w3.org/TR/html5") == "standards"

    def test_classify_knowledge(self):
        """Test knowledge source classification."""
        from src.search.searxng import _classify_source
        
        assert _classify_source("https://en.wikipedia.org/wiki/Test") == "knowledge"
        assert _classify_source("https://www.wikidata.org/wiki/Q123") == "knowledge"

    def test_classify_news(self):
        """Test news source classification."""
        from src.search.searxng import _classify_source
        
        assert _classify_source("https://www.bbc.com/news/article") == "news"
        assert _classify_source("https://www.reuters.com/article/xyz") == "news"
        assert _classify_source("https://www.nhk.or.jp/news/html/xxx") == "news"

    def test_classify_technical(self):
        """Test technical source classification."""
        from src.search.searxng import _classify_source
        
        assert _classify_source("https://github.com/user/repo") == "technical"
        assert _classify_source("https://stackoverflow.com/questions/123") == "technical"
        assert _classify_source("https://docs.python.org/3/") == "technical"

    def test_classify_blog(self):
        """Test blog source classification."""
        from src.search.searxng import _classify_source
        
        assert _classify_source("https://medium.com/@user/article") == "blog"
        assert _classify_source("https://qiita.com/user/items/xxx") == "blog"
        assert _classify_source("https://zenn.dev/user/articles/xxx") == "blog"
        assert _classify_source("https://example.com/blog/post") == "blog"

    def test_classify_unknown(self):
        """Test unknown source classification."""
        from src.search.searxng import _classify_source
        
        assert _classify_source("https://random-site.com/page") == "unknown"
        assert _classify_source("https://example.org/article") == "unknown"


class TestSearchSerp:
    """Tests for search_serp function."""

    @pytest.mark.asyncio
    async def test_search_serp_basic(self, test_database, mock_searxng_response, make_mock_response):
        """Test basic search_serp functionality."""
        from src.search import searxng
        
        # Mock the client
        mock_response = make_mock_response(mock_searxng_response)
        
        with patch.object(searxng, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(return_value=mock_searxng_response)
            mock_get_client.return_value = mock_client
            
            with patch.object(searxng, "get_database", return_value=test_database):
                results = await searxng.search_serp(
                    query="test query",
                    limit=10,
                    use_cache=False,
                )
        
        assert len(results) == 3
        assert results[0]["title"] == "Test Result 1"
        assert results[0]["url"] == "https://example.com/page1"
        assert results[0]["rank"] == 1

    @pytest.mark.asyncio
    async def test_search_serp_deduplicates_urls(self, test_database):
        """Test that search_serp removes duplicate URLs."""
        from src.search import searxng
        
        duplicate_response = {
            "results": [
                {"title": "Result 1", "url": "https://example.com/page", "content": "Content 1"},
                {"title": "Result 2", "url": "https://example.com/page", "content": "Content 2"},
                {"title": "Result 3", "url": "https://other.com/page", "content": "Content 3"},
            ]
        }
        
        with patch.object(searxng, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(return_value=duplicate_response)
            mock_get_client.return_value = mock_client
            
            with patch.object(searxng, "get_database", return_value=test_database):
                results = await searxng.search_serp("query", use_cache=False)
        
        # Should only have 2 unique URLs
        assert len(results) == 2
        urls = [r["url"] for r in results]
        assert len(set(urls)) == len(urls)

    @pytest.mark.asyncio
    async def test_search_serp_respects_limit(self, test_database):
        """Test that search_serp respects limit parameter."""
        from src.search import searxng
        
        many_results = {
            "results": [
                {"title": f"Result {i}", "url": f"https://example.com/page{i}", "content": f"Content {i}"}
                for i in range(20)
            ]
        }
        
        with patch.object(searxng, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(return_value=many_results)
            mock_get_client.return_value = mock_client
            
            with patch.object(searxng, "get_database", return_value=test_database):
                results = await searxng.search_serp("query", limit=5, use_cache=False)
        
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_search_serp_classifies_sources(self, test_database, mock_searxng_response):
        """Test that search_serp classifies source types."""
        from src.search import searxng
        
        with patch.object(searxng, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(return_value=mock_searxng_response)
            mock_get_client.return_value = mock_client
            
            with patch.object(searxng, "get_database", return_value=test_database):
                results = await searxng.search_serp("query", use_cache=False)
        
        # Check source tags are assigned
        source_tags = [r["source_tag"] for r in results]
        assert "academic" in source_tags  # arxiv.org
        assert "government" in source_tags  # go.jp

    @pytest.mark.asyncio
    async def test_search_serp_cache_hit(self, test_database, mock_searxng_response):
        """Test search_serp returns cached results."""
        from src.search import searxng
        
        # First call - populate cache
        with patch.object(searxng, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(return_value=mock_searxng_response)
            mock_get_client.return_value = mock_client
            
            with patch.object(searxng, "get_database", return_value=test_database):
                results1 = await searxng.search_serp("cached query", use_cache=True)
        
        # Second call - should use cache
        with patch.object(searxng, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(return_value={"results": []})
            mock_get_client.return_value = mock_client
            
            with patch.object(searxng, "get_database", return_value=test_database):
                results2 = await searxng.search_serp("cached query", use_cache=True)
        
        # Results should be same (from cache)
        assert len(results1) == len(results2)
        assert results1[0]["url"] == results2[0]["url"]

    @pytest.mark.asyncio
    async def test_search_serp_stores_in_database(self, test_database, mock_searxng_response):
        """Test search_serp stores results in database when task_id provided."""
        from src.search import searxng
        
        task_id = await test_database.create_task("test task")
        
        with patch.object(searxng, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(return_value=mock_searxng_response)
            mock_get_client.return_value = mock_client
            
            with patch.object(searxng, "get_database", return_value=test_database):
                await searxng.search_serp(
                    "stored query",
                    task_id=task_id,
                    use_cache=False,
                )
        
        # Check query was stored
        query = await test_database.fetch_one(
            "SELECT * FROM queries WHERE task_id = ?", (task_id,)
        )
        assert query is not None
        assert query["query_text"] == "stored query"
        
        # Check SERP items were stored
        serp_items = await test_database.fetch_all(
            "SELECT * FROM serp_items WHERE query_id = ?", (query["id"],)
        )
        assert len(serp_items) == 3


class TestExpandQuery:
    """Tests for query expansion (placeholder implementation)."""

    @pytest.mark.asyncio
    async def test_expand_query_returns_base(self):
        """Test expand_query returns at least the base query."""
        from src.search.searxng import expand_query
        
        results = await expand_query("test query")
        
        assert "test query" in results


class TestGenerateMirrorQuery:
    """Tests for mirror query generation (placeholder implementation)."""

    @pytest.mark.asyncio
    async def test_generate_mirror_query_returns_none(self):
        """Test generate_mirror_query returns None (not implemented)."""
        from src.search.searxng import generate_mirror_query
        
        result = await generate_mirror_query("テストクエリ", "ja", "en")
        
        # Currently returns None as not implemented
        assert result is None

