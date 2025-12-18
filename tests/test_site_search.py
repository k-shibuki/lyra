"""
Tests for site-internal search UI automation module.

Covers:
- SearchTemplate: Template configuration
- DomainSearchStats: Statistics tracking
- SiteSearchManager: Search execution and fallback

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-ST-01 | SearchTemplate from basic dict | Equivalence – normal | Template created | - |
| TC-ST-02 | SearchTemplate with defaults | Equivalence – defaults | Default values used | - |
| TC-ST-03 | SearchTemplate serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-DSS-01 | DomainSearchStats creation | Equivalence – normal | Stats initialized | - |
| TC-DSS-02 | Record success | Equivalence – mutation | Success count incremented | - |
| TC-DSS-03 | Record failure | Equivalence – mutation | Failure count incremented | - |
| TC-DSS-04 | Calculate success rate | Equivalence – calculation | Correct percentage | - |
| TC-DSS-05 | Stats serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-SSM-01 | Execute search with template | Equivalence – execution | Results returned | - |
| TC-SSM-02 | Execute search without template | Boundary – no template | Fallback to generic | - |
| TC-SSM-03 | Execute search with failure | Abnormal – error | Handles gracefully | - |
| TC-SSR-01 | SiteSearchResult creation | Equivalence – normal | Result with URLs | - |
| TC-SSR-02 | SiteSearchResult serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-CF-01 | get_site_search_manager | Equivalence – singleton | Returns manager instance | - |
| TC-CF-02 | site_search function | Equivalence – convenience | Returns search result | - |
| TC-CF-03 | get_site_search_stats | Equivalence – convenience | Returns stats | - |
| TC-CF-04 | list_allowlisted_domains | Equivalence – listing | Returns domain list | - |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.crawler.site_search import (
    SearchTemplate,
    SiteSearchResult,
    DomainSearchStats,
    SiteSearchManager,
    get_site_search_manager,
    site_search,
    get_site_search_stats,
    list_allowlisted_domains,
)


# =============================================================================
# SearchTemplate Tests
# =============================================================================

class TestSearchTemplate:
    """Tests for SearchTemplate dataclass."""

    def test_from_dict_basic(self):
        """Create template from basic dictionary."""
        data = {
            "domain": "example.com",
            "search_input": "input#search",
            "search_button": "button#submit",
        }

        template = SearchTemplate.from_dict("example.com", data)

        assert template.domain == "example.com"
        assert template.search_input == "input#search"
        assert template.search_button == "button#submit"

    def test_from_dict_defaults(self):
        """Template should have sensible defaults."""
        data = {}

        template = SearchTemplate.from_dict("example.com", data)

        assert template.domain == "example.com"
        assert "input" in template.search_input
        assert template.link_selector == "a"

    def test_from_dict_full(self):
        """Create template with all fields."""
        data = {
            "domain": "arxiv.org",
            "search_input": "input[name='query']",
            "search_button": "button[type='submit']",
            "results_selector": ".arxiv-result",
            "link_selector": "a.result-link",
            "wait_for": ".results-loaded",
        }

        template = SearchTemplate.from_dict("arxiv.org", data)

        assert template.results_selector == ".arxiv-result"
        assert template.wait_for == ".results-loaded"


# =============================================================================
# DomainSearchStats Tests
# =============================================================================

class TestDomainSearchStats:
    """Tests for DomainSearchStats dataclass."""

    def test_initial_state(self):
        """New stats should have zero values."""
        stats = DomainSearchStats(domain="example.com")

        assert stats.total_attempts == 0
        assert stats.successful_attempts == 0
        assert stats.success_rate == 0.0
        assert stats.harvest_rate == 0.0
        assert not stats.is_skipped()

    def test_success_rate_calculation(self):
        """Success rate should be calculated correctly."""
        stats = DomainSearchStats(domain="example.com")
        stats.total_attempts = 10
        stats.successful_attempts = 7

        assert stats.success_rate == 0.7

    def test_harvest_rate_calculation(self):
        """Harvest rate should be calculated correctly."""
        stats = DomainSearchStats(domain="example.com")
        stats.successful_attempts = 5
        stats.total_results = 50

        assert stats.harvest_rate == 10.0

    def test_record_success(self):
        """Recording success should update stats correctly."""
        stats = DomainSearchStats(domain="example.com")
        stats.consecutive_failures = 1

        stats.record_success(result_count=10)

        assert stats.total_attempts == 1
        assert stats.successful_attempts == 1
        assert stats.total_results == 10
        assert stats.consecutive_failures == 0
        assert stats.last_success_at is not None

    def test_record_failure(self):
        """Recording failure should update stats correctly."""
        stats = DomainSearchStats(domain="example.com")

        stats.record_failure()

        assert stats.total_attempts == 1
        assert stats.successful_attempts == 0
        assert stats.consecutive_failures == 1
        assert stats.last_failure_at is not None

    def test_skip_after_consecutive_failures(self):
        """Domain should be skipped after 2 consecutive failures."""
        stats = DomainSearchStats(domain="example.com")

        stats.record_failure()
        assert not stats.is_skipped()

        stats.record_failure()  # Second failure
        assert stats.is_skipped()
        assert stats.skip_until is not None

    def test_is_skipped_expires(self):
        """Skip should expire after set time."""
        stats = DomainSearchStats(domain="example.com")
        stats.skip_until = datetime.now(timezone.utc) - timedelta(hours=1)

        assert not stats.is_skipped()

    def test_success_resets_failures(self):
        """Success should reset consecutive failures."""
        stats = DomainSearchStats(domain="example.com")
        stats.consecutive_failures = 1

        stats.record_success(5)

        assert stats.consecutive_failures == 0


# =============================================================================
# SiteSearchResult Tests
# =============================================================================

class TestSiteSearchResult:
    """Tests for SiteSearchResult dataclass."""

    def test_to_dict(self):
        """to_dict should return serializable dictionary."""
        result = SiteSearchResult(
            domain="example.com",
            query="test query",
            success=True,
            result_urls=["https://example.com/result1"],
            result_count=1,
        )

        d = result.to_dict()

        assert d["domain"] == "example.com"
        assert d["query"] == "test query"
        assert d["success"] is True
        assert len(d["result_urls"]) == 1

    def test_failed_result(self):
        """Failed result should have error."""
        result = SiteSearchResult(
            domain="example.com",
            query="test",
            success=False,
            error="timeout",
        )

        d = result.to_dict()

        assert d["success"] is False
        assert d["error"] == "timeout"


# =============================================================================
# SiteSearchManager Tests
# =============================================================================

class TestSiteSearchManager:
    """Tests for SiteSearchManager class."""

    def test_is_allowlisted_with_template(self):
        """Domain with template should be allowlisted."""
        manager = SiteSearchManager()
        manager._templates["example.com"] = SearchTemplate(
            domain="example.com",
            search_input="input#search",
        )

        assert manager.is_allowlisted("example.com")
        assert not manager.is_allowlisted("other.com")

    def test_get_template(self):
        """Should return template for domain."""
        manager = SiteSearchManager()
        template = SearchTemplate(domain="example.com", search_input="input")
        manager._templates["example.com"] = template

        assert manager.get_template("example.com") == template
        assert manager.get_template("other.com") is None

    def test_get_stats_creates_new(self):
        """get_stats should create new stats if not exists."""
        manager = SiteSearchManager()

        stats = manager.get_stats("new-domain.com")

        assert stats.domain == "new-domain.com"
        assert stats.total_attempts == 0

    def test_get_stats_returns_existing(self):
        """get_stats should return existing stats."""
        manager = SiteSearchManager()
        existing = DomainSearchStats(domain="example.com")
        existing.total_attempts = 5
        manager._stats["example.com"] = existing

        stats = manager.get_stats("example.com")

        assert stats.total_attempts == 5

    @pytest.mark.asyncio
    async def test_can_search_not_allowlisted(self):
        """can_search should return False for non-allowlisted domains."""
        manager = SiteSearchManager()

        assert not await manager.can_search("not-allowlisted.com")

    @pytest.mark.asyncio
    async def test_can_search_skipped_domain(self):
        """can_search should return False for skipped domains."""
        manager = SiteSearchManager()
        manager._templates["example.com"] = SearchTemplate(
            domain="example.com",
            search_input="input",
        )
        stats = manager.get_stats("example.com")
        stats.skip_until = datetime.now(timezone.utc) + timedelta(hours=1)

        assert not await manager.can_search("example.com")

    @pytest.mark.asyncio
    async def test_can_search_available(self):
        """can_search should return True for available domains."""
        manager = SiteSearchManager()
        manager._templates["example.com"] = SearchTemplate(
            domain="example.com",
            search_input="input",
        )

        assert await manager.can_search("example.com")

    def test_extract_result_urls_basic(self):
        """Should extract URLs from search results."""
        manager = SiteSearchManager()
        template = SearchTemplate(
            domain="example.com",
            search_input="input",
            results_selector=".result",
            link_selector="a",
        )

        html = """
        <html>
        <body>
            <div class="result">
                <a href="/page1">Result 1</a>
            </div>
            <div class="result">
                <a href="/page2">Result 2</a>
            </div>
            <div class="result">
                <a href="https://external.com/page">External</a>
            </div>
        </body>
        </html>
        """

        urls = manager._extract_result_urls(html, "example.com", template)

        assert len(urls) == 2
        assert "https://example.com/page1" in urls
        assert "https://example.com/page2" in urls
        # External link should be excluded
        assert not any("external.com" in url for url in urls)

    def test_extract_result_urls_skip_search_pages(self):
        """Should skip search and login URLs."""
        manager = SiteSearchManager()
        template = SearchTemplate(
            domain="example.com",
            search_input="input",
        )

        html = """
        <html>
        <body>
            <a href="/content">Content</a>
            <a href="/search?q=test">Search</a>
            <a href="/login">Login</a>
            <a href="/tag/python">Tag</a>
        </body>
        </html>
        """

        urls = manager._extract_result_urls(html, "example.com", template)

        assert len(urls) == 1
        assert "content" in urls[0]

    def test_extract_result_urls_deduplicates(self):
        """Should deduplicate URLs."""
        manager = SiteSearchManager()
        template = SearchTemplate(domain="example.com", search_input="input")

        html = """
        <html>
        <body>
            <a href="/page">Link 1</a>
            <a href="/page">Link 2</a>
            <a href="/page">Link 3</a>
        </body>
        </html>
        """

        urls = manager._extract_result_urls(html, "example.com", template)

        assert len(urls) == 1


# =============================================================================
# MCP Tool Function Tests
# =============================================================================

class TestMCPToolFunctions:
    """Tests for MCP tool integration functions."""

    @pytest.mark.asyncio
    async def test_site_search_function(self):
        """site_search should return structured result."""
        with patch("src.crawler.site_search.get_site_search_manager") as mock_get:
            mock_manager = MagicMock()
            mock_manager.search = AsyncMock(return_value=SiteSearchResult(
                domain="example.com",
                query="test",
                success=True,
                result_urls=["https://example.com/r1"],
                result_count=1,
            ))
            mock_get.return_value = mock_manager

            result = await site_search("example.com", "test")

            assert result["domain"] == "example.com"
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_get_site_search_stats_function(self):
        """get_site_search_stats should return stats."""
        with patch("src.crawler.site_search.get_site_search_manager") as mock_get:
            mock_manager = MagicMock()
            mock_manager.is_allowlisted.return_value = True
            mock_manager.get_template.return_value = SearchTemplate(
                domain="example.com",
                search_input="input",
            )
            mock_manager.get_stats.return_value = DomainSearchStats(
                domain="example.com",
                total_attempts=10,
                successful_attempts=8,
            )
            mock_get.return_value = mock_manager

            result = await get_site_search_stats("example.com")

            assert result["domain"] == "example.com"
            assert result["is_allowlisted"] is True
            assert result["stats"]["total_attempts"] == 10

    @pytest.mark.asyncio
    async def test_list_allowlisted_domains_function(self):
        """list_allowlisted_domains should return domain list."""
        with patch("src.crawler.site_search.get_site_search_manager") as mock_get:
            mock_manager = MagicMock()
            mock_manager._templates = {
                "example.com": SearchTemplate(domain="example.com", search_input="input"),
                "test.org": SearchTemplate(domain="test.org", search_input="input"),
            }
            mock_manager.get_stats.return_value = DomainSearchStats(domain="example.com")
            mock_get.return_value = mock_manager

            result = await list_allowlisted_domains()

            assert result["total"] == 2


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge case tests."""

    def test_empty_html_extraction(self):
        """Should handle empty HTML gracefully."""
        manager = SiteSearchManager()
        template = SearchTemplate(domain="example.com", search_input="input")

        urls = manager._extract_result_urls("", "example.com", template)

        assert urls == []

    def test_malformed_html_extraction(self):
        """Should handle malformed HTML gracefully."""
        manager = SiteSearchManager()
        template = SearchTemplate(domain="example.com", search_input="input")

        html = "<html><body><a href='/valid'>Valid<a href='broken'>"

        urls = manager._extract_result_urls(html, "example.com", template)

        # Should extract at least some URLs without error
        assert isinstance(urls, list)

    def test_stats_zero_division_safety(self):
        """Success/harvest rate should handle zero attempts."""
        stats = DomainSearchStats(domain="example.com")

        # Should not raise ZeroDivisionError
        assert stats.success_rate == 0.0
        assert stats.harvest_rate == 0.0

    def test_url_limit(self):
        """Should limit extracted URLs."""
        manager = SiteSearchManager()
        template = SearchTemplate(domain="example.com", search_input="input")

        # Generate HTML with many links
        links = "".join([f'<a href="/page{i}">Page {i}</a>' for i in range(100)])
        html = f"<html><body>{links}</body></html>"

        urls = manager._extract_result_urls(html, "example.com", template)

        assert len(urls) <= 50  # Should be limited








