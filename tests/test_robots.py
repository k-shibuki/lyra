"""
Tests for robots.txt and sitemap parsing module.

Covers:
- RobotsChecker: robots.txt parsing and compliance
- SitemapParser: sitemap.xml parsing and URL extraction
- RobotsManager: Integration with crawler
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.crawler.robots import (
    RobotsChecker,
    RobotsManager,
    RobotsRule,
    SitemapEntry,
    SitemapParser,
    SitemapResult,
    check_robots_compliance,
    get_sitemap_urls,
)

# =============================================================================
# RobotsRule Tests
# =============================================================================


class TestRobotsRule:
    """Tests for RobotsRule dataclass."""

    def test_is_expired_fresh(self):
        """Fresh RobotsRule should not be expired."""
        rule = RobotsRule(
            domain="example.com",
            fetched_at=datetime.now(UTC),
        )
        assert not rule.is_expired(ttl_hours=24)

    def test_is_expired_old(self):
        """Old RobotsRule should be expired."""
        rule = RobotsRule(
            domain="example.com",
            fetched_at=datetime.now(UTC) - timedelta(hours=25),
        )
        assert rule.is_expired(ttl_hours=24)

    def test_is_expired_custom_ttl(self):
        """Custom TTL should be respected."""
        rule = RobotsRule(
            domain="example.com",
            fetched_at=datetime.now(UTC) - timedelta(hours=2),
        )
        assert rule.is_expired(ttl_hours=1)
        assert not rule.is_expired(ttl_hours=3)


# =============================================================================
# SitemapEntry Tests
# =============================================================================


class TestSitemapEntry:
    """Tests for SitemapEntry dataclass."""

    def test_default_score(self):
        """Default score should be priority value."""
        entry = SitemapEntry(loc="https://example.com/page")
        assert entry.score() == 0.5

    def test_high_priority_score(self):
        """High priority should increase score."""
        entry = SitemapEntry(loc="https://example.com/page", priority=1.0)
        assert entry.score() >= 1.0

    def test_recent_content_boost(self):
        """Recent content should boost score."""
        entry = SitemapEntry(
            loc="https://example.com/page",
            priority=0.5,
            lastmod=datetime.now(UTC) - timedelta(days=1),
        )
        assert entry.score() > 0.5  # Should have boost

    def test_frequent_change_boost(self):
        """Frequently changing content should boost score."""
        entry = SitemapEntry(
            loc="https://example.com/page",
            priority=0.5,
            changefreq="daily",
        )
        assert entry.score() > 0.5

    def test_score_capped_at_one(self):
        """Score should be capped at 1.0."""
        entry = SitemapEntry(
            loc="https://example.com/page",
            priority=1.0,
            lastmod=datetime.now(UTC),
            changefreq="always",
        )
        assert entry.score() <= 1.0


# =============================================================================
# SitemapResult Tests
# =============================================================================


class TestSitemapResult:
    """Tests for SitemapResult dataclass."""

    def test_get_priority_urls_empty(self):
        """Empty result should return empty list."""
        result = SitemapResult(domain="example.com")
        assert result.get_priority_urls() == []

    def test_get_priority_urls_sorted(self):
        """URLs should be sorted by score descending."""
        entries = [
            SitemapEntry(loc="https://example.com/low", priority=0.3),
            SitemapEntry(loc="https://example.com/high", priority=0.9),
            SitemapEntry(loc="https://example.com/mid", priority=0.6),
        ]
        result = SitemapResult(domain="example.com", entries=entries)
        urls = result.get_priority_urls(limit=10, min_score=0.0)

        assert len(urls) == 3
        assert urls[0][0] == "https://example.com/high"
        assert urls[-1][0] == "https://example.com/low"

    def test_get_priority_urls_limit(self):
        """Limit should be respected."""
        entries = [
            SitemapEntry(loc=f"https://example.com/page{i}", priority=0.8) for i in range(10)
        ]
        result = SitemapResult(domain="example.com", entries=entries)
        urls = result.get_priority_urls(limit=3)

        assert len(urls) == 3

    def test_get_priority_urls_min_score_filter(self):
        """URLs below min_score should be filtered."""
        entries = [
            SitemapEntry(loc="https://example.com/low", priority=0.3),
            SitemapEntry(loc="https://example.com/high", priority=0.8),
        ]
        result = SitemapResult(domain="example.com", entries=entries)
        urls = result.get_priority_urls(min_score=0.5)

        assert len(urls) == 1
        assert urls[0][0] == "https://example.com/high"


# =============================================================================
# RobotsChecker Tests
# =============================================================================


class TestRobotsChecker:
    """Tests for RobotsChecker class."""

    def test_path_matches_exact(self):
        """Exact path should match."""
        assert RobotsChecker._path_matches("/admin/", "/admin/")
        assert not RobotsChecker._path_matches("/admin/", "/other/")

    def test_path_matches_prefix(self):
        """Prefix should match longer paths."""
        assert RobotsChecker._path_matches("/admin/page", "/admin/")
        assert RobotsChecker._path_matches("/admin/", "/admin/")

    def test_path_matches_wildcard(self):
        """Wildcard * should match any characters."""
        assert RobotsChecker._path_matches("/page.html", "/*.html")
        assert RobotsChecker._path_matches("/subdir/page.html", "/*.html")
        assert not RobotsChecker._path_matches("/page.txt", "/*.html")

    def test_path_matches_end_anchor(self):
        """Dollar sign should anchor to end."""
        assert RobotsChecker._path_matches("/page.html", "/page.html$")
        assert not RobotsChecker._path_matches("/page.html/extra", "/page.html$")

    def test_parse_robots_txt_basic(self):
        """Basic robots.txt parsing."""
        checker = RobotsChecker()
        content = """
User-agent: *
Disallow: /admin/
Disallow: /private/
Allow: /admin/public/
Crawl-delay: 2
Sitemap: https://example.com/sitemap.xml
"""
        rules = checker._parse_robots_txt("example.com", content)

        assert rules.domain == "example.com"
        assert "/admin/" in rules.disallowed_paths
        assert "/private/" in rules.disallowed_paths
        assert "/admin/public/" in rules.allowed_paths
        assert rules.crawl_delay == 2.0
        assert "https://example.com/sitemap.xml" in rules.sitemap_urls

    def test_parse_robots_txt_multiple_sitemaps(self):
        """Multiple Sitemap directives should be collected."""
        checker = RobotsChecker()
        content = """
User-agent: *
Disallow: /admin/
Sitemap: https://example.com/sitemap1.xml
Sitemap: https://example.com/sitemap2.xml
"""
        rules = checker._parse_robots_txt("example.com", content)

        assert len(rules.sitemap_urls) == 2

    def test_parse_robots_txt_user_agent_specific(self):
        """Specific user-agent rules should be respected."""
        checker = RobotsChecker()
        content = """
User-agent: Lancet
Disallow: /lancet-blocked/
Crawl-delay: 5

User-agent: *
Disallow: /general-blocked/
"""
        rules = checker._parse_robots_txt("example.com", content)

        # Lancet-specific rules should be captured
        assert "/lancet-blocked/" in rules.disallowed_paths
        assert rules.crawl_delay == 5.0

    def test_parse_robots_txt_comments(self):
        """Comments should be ignored per RFC 9309.

        Both standalone comments and inline comments (# ...) should be stripped.
        """
        checker = RobotsChecker()
        content = """
# This is a comment
User-agent: *
Disallow: /admin/  # inline comment
"""
        rules = checker._parse_robots_txt("example.com", content)

        assert rules.domain == "example.com"
        # Inline comment should be stripped, leaving just /admin/
        assert "/admin/" in rules.disallowed_paths, (
            "Expected /admin/ to be parsed with inline comment stripped"
        )
        assert len(rules.disallowed_paths) == 1, (
            f"Expected exactly 1 disallowed path, got {len(rules.disallowed_paths)}"
        )

    @pytest.mark.asyncio
    async def test_can_fetch_allowed(self):
        """Allowed URLs should pass check."""
        checker = RobotsChecker()

        # Mock fetch
        checker._cache["example.com"] = RobotsRule(
            domain="example.com",
            disallowed_paths=["/admin/"],
            allowed_paths=[],
        )

        assert await checker.can_fetch("https://example.com/public/page")
        assert not await checker.can_fetch("https://example.com/admin/settings")

    @pytest.mark.asyncio
    async def test_can_fetch_allow_overrides_disallow(self):
        """More specific Allow should override Disallow."""
        checker = RobotsChecker()

        checker._cache["example.com"] = RobotsRule(
            domain="example.com",
            disallowed_paths=["/admin/"],
            allowed_paths=["/admin/public/"],
        )

        # /admin/public/ is more specific, so it should be allowed
        assert await checker.can_fetch("https://example.com/admin/public/page")
        # But /admin/private/ should still be blocked
        assert not await checker.can_fetch("https://example.com/admin/private/")

    @pytest.mark.asyncio
    async def test_get_crawl_delay(self):
        """Crawl delay should be retrieved from cache."""
        checker = RobotsChecker()

        checker._cache["example.com"] = RobotsRule(
            domain="example.com",
            crawl_delay=3.0,
        )

        delay = await checker.get_crawl_delay("example.com")
        assert delay == 3.0

    @pytest.mark.asyncio
    async def test_get_sitemaps(self):
        """Sitemap URLs should be retrieved from cache."""
        checker = RobotsChecker()

        checker._cache["example.com"] = RobotsRule(
            domain="example.com",
            sitemap_urls=["https://example.com/sitemap.xml"],
        )

        sitemaps = await checker.get_sitemaps("example.com")
        assert "https://example.com/sitemap.xml" in sitemaps


# =============================================================================
# SitemapParser Tests
# =============================================================================


class TestSitemapParser:
    """Tests for SitemapParser class."""

    def test_parse_datetime_iso(self):
        """ISO 8601 datetime parsing."""
        dt = SitemapParser._parse_datetime("2024-01-15T10:30:00Z")
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15

    def test_parse_datetime_date_only(self):
        """Date-only format parsing."""
        dt = SitemapParser._parse_datetime("2024-01-15")
        assert dt is not None
        assert dt.year == 2024

    def test_parse_datetime_invalid(self):
        """Invalid date should return None."""
        dt = SitemapParser._parse_datetime("not-a-date")
        assert dt is None

    def test_extract_url_entries_basic(self):
        """Basic URL entry extraction."""
        import xml.etree.ElementTree as ET

        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://example.com/page1</loc>
        <lastmod>2024-01-15</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>https://example.com/page2</loc>
        <priority>0.5</priority>
    </url>
</urlset>"""

        parser = SitemapParser()
        root = ET.fromstring(xml_content)
        entries = parser._extract_url_entries(root)

        assert len(entries) == 2
        assert entries[0].loc == "https://example.com/page1"
        assert entries[0].priority == 0.8
        assert entries[0].changefreq == "weekly"
        assert entries[1].loc == "https://example.com/page2"

    def test_extract_sitemap_urls_from_index(self):
        """Sitemap index URL extraction."""
        import xml.etree.ElementTree as ET

        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap>
        <loc>https://example.com/sitemap1.xml</loc>
    </sitemap>
    <sitemap>
        <loc>https://example.com/sitemap2.xml</loc>
    </sitemap>
</sitemapindex>"""

        parser = SitemapParser()
        root = ET.fromstring(xml_content)
        urls = parser._extract_sitemap_urls(root)

        assert len(urls) == 2
        assert "https://example.com/sitemap1.xml" in urls
        assert "https://example.com/sitemap2.xml" in urls


# =============================================================================
# RobotsManager Tests
# =============================================================================


class TestRobotsManager:
    """Tests for RobotsManager integration class."""

    @pytest.mark.asyncio
    async def test_can_fetch_integration(self):
        """Integration test for URL compliance checking."""
        manager = RobotsManager()

        # Pre-populate cache
        manager._robots_checker._cache["example.com"] = RobotsRule(
            domain="example.com",
            disallowed_paths=["/admin/"],
        )

        assert await manager.can_fetch("https://example.com/public/")
        assert not await manager.can_fetch("https://example.com/admin/settings")

    @pytest.mark.asyncio
    async def test_get_effective_delay(self):
        """Effective delay should consider multiple sources."""
        manager = RobotsManager()

        # Set robots.txt crawl-delay
        manager._robots_checker._cache["example.com"] = RobotsRule(
            domain="example.com",
            crawl_delay=10.0,
        )

        delay = await manager.get_effective_delay("example.com")
        # Should be at least 10.0 from robots.txt
        assert delay >= 10.0

    def test_clear_cache(self):
        """Cache clearing should work."""
        manager = RobotsManager()

        # Add to caches
        manager._robots_checker._cache["example.com"] = RobotsRule(domain="example.com")
        manager._sitemap_parser._cache["example.com:url"] = SitemapResult(domain="example.com")

        manager.clear_cache()

        assert len(manager._robots_checker._cache) == 0
        assert len(manager._sitemap_parser._cache) == 0


# =============================================================================
# MCP Tool Function Tests
# =============================================================================


class TestMCPToolFunctions:
    """Tests for MCP tool integration functions."""

    @pytest.mark.asyncio
    async def test_check_robots_compliance(self):
        """check_robots_compliance should return structured result."""
        # Mock the manager
        with patch("src.crawler.robots.get_robots_manager") as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.can_fetch = AsyncMock(return_value=True)
            mock_manager.get_effective_delay = AsyncMock(return_value=2.0)
            mock_manager.get_robots_info = AsyncMock(
                return_value={
                    "domain": "example.com",
                    "found": True,
                }
            )
            mock_get_manager.return_value = mock_manager

            result = await check_robots_compliance("https://example.com/page")

            assert result["url"] == "https://example.com/page"
            assert result["domain"] == "example.com"
            assert result["allowed"] is True
            assert result["effective_delay"] == 2.0

    @pytest.mark.asyncio
    async def test_get_sitemap_urls(self):
        """get_sitemap_urls should return URL list."""
        with patch("src.crawler.robots.get_robots_manager") as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.get_priority_urls = AsyncMock(
                return_value=[
                    ("https://example.com/high", 0.9),
                    ("https://example.com/mid", 0.6),
                ]
            )
            mock_get_manager.return_value = mock_manager

            result = await get_sitemap_urls("example.com", limit=10)

            assert result["domain"] == "example.com"
            assert result["total"] == 2
            assert len(result["urls"]) == 2
            assert result["urls"][0]["url"] == "https://example.com/high"

    @pytest.mark.asyncio
    async def test_get_sitemap_urls_with_keywords(self):
        """Keywords should filter URLs."""
        with patch("src.crawler.robots.get_robots_manager") as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.get_priority_urls = AsyncMock(
                return_value=[
                    ("https://example.com/docs/api", 0.9),
                    ("https://example.com/blog/post", 0.8),
                    ("https://example.com/docs/guide", 0.7),
                ]
            )
            mock_get_manager.return_value = mock_manager

            result = await get_sitemap_urls(
                "example.com",
                limit=10,
                keywords=["docs"],
            )

            assert result["total"] == 2  # Only docs URLs
            for url_entry in result["urls"]:
                assert "docs" in url_entry["url"]


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_robots_txt(self):
        """Empty robots.txt should allow all."""
        checker = RobotsChecker()
        rules = checker._parse_robots_txt("example.com", "")

        assert rules.domain == "example.com"
        assert len(rules.disallowed_paths) == 0

    def test_robots_txt_without_user_agent(self):
        """robots.txt without User-agent should be handled.

        Sitemap directives are global and should be extracted regardless.
        """
        checker = RobotsChecker()
        content = """
Disallow: /admin/
Sitemap: https://example.com/sitemap.xml
"""
        rules = checker._parse_robots_txt("example.com", content)

        # Without User-agent, rules may not apply to disallow
        assert rules.domain == "example.com"
        # Sitemap should be extracted (it's a global directive)
        assert "https://example.com/sitemap.xml" in rules.sitemap_urls, (
            "Expected sitemap URL to be extracted"
        )
        assert len(rules.sitemap_urls) == 1, (
            f"Expected exactly 1 sitemap URL, got {len(rules.sitemap_urls)}"
        )

    def test_sitemap_entry_score_old_content(self):
        """Old content should not get recency boost."""
        entry = SitemapEntry(
            loc="https://example.com/page",
            priority=0.5,
            lastmod=datetime.now(UTC) - timedelta(days=365),
        )
        # Score should be close to base priority
        assert entry.score() == pytest.approx(0.5, abs=0.1)

    def test_path_matches_empty_pattern(self):
        """Empty pattern should not match."""
        assert not RobotsChecker._path_matches("/page", "")

    def test_path_matches_root(self):
        """Root pattern should match all."""
        assert RobotsChecker._path_matches("/any/path", "/")
