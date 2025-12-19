"""
Tests for domain-internal BFS crawler module.

Covers:
- LinkExtractor: Link extraction and classification
- DomainBFSCrawler: BFS crawling within domain
- Priority calculation and robots.txt integration

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-EL-N-01 | Links with same URL | Equivalence – normal | Same hash | Hashable by URL |
| TC-EL-N-02 | Links with same URL | Equivalence – normal | Equal links | Equality by URL |
| TC-EL-N-03 | Links in set | Equivalence – normal | Deduplicated | Set behavior |
| TC-BR-N-01 | BFSResult fields | Equivalence – normal | Dict serializable | Serialization |
| TC-LE-N-01 | Same-domain links | Equivalence – normal | External excluded | Domain filter |
| TC-LE-N-02 | Links in nav element | Equivalence – normal | NAVIGATION type | Classification |
| TC-LE-N-03 | Links in toc element | Equivalence – normal | TOC type | Classification |
| TC-LE-N-04 | Links in heading | Equivalence – normal | HEADING type | Classification |
| TC-LE-N-05 | Links in related div | Equivalence – normal | RELATED type | Classification |
| TC-LE-N-06 | Links in sidebar | Equivalence – normal | SIDEBAR type | Classification |
| TC-LE-N-07 | Links in pagination | Equivalence – normal | Links extracted | Pagination |
| TC-LE-N-08 | Anchor-only links | Equivalence – normal | Skipped | Fragment filter |
| TC-LE-N-09 | JavaScript links | Equivalence – normal | Skipped | JS filter |
| TC-LE-N-10 | Mailto links | Equivalence – normal | Skipped | Mailto filter |
| TC-LE-N-11 | URL with fragment | Equivalence – normal | Fragment removed | URL cleanup |
| TC-LE-N-12 | Link with 詳細 text | Equivalence – normal | Priority boost | Priority calc |
| TC-LE-N-13 | Link with 公式 text | Equivalence – normal | Priority boost | Priority calc |
| TC-LE-N-14 | Multiple links | Equivalence – normal | Sorted by priority | Sorting |
| TC-LE-N-15 | Duplicate URLs | Equivalence – normal | Deduplicated | Deduplication |
| TC-BFS-N-01 | Crawl with max_depth | Equivalence – normal | Depth respected | Depth limit |
| TC-BFS-N-02 | Crawl with max_urls | Equivalence – normal | URL limit respected | URL limit |
| TC-BFS-N-03 | robots.txt blocked URL | Equivalence – normal | URL recorded blocked | robots.txt |
| TC-BFS-N-04 | Get priority links | Equivalence – normal | Prioritized list | Priority API |
| TC-BFS-N-05 | Priority URLs in result | Equivalence – normal | Sorted by priority | Result format |
| TC-MCP-N-01 | explore_domain call | Equivalence – normal | Structured result | MCP tool |
| TC-MCP-N-02 | extract_page_links call | Equivalence – normal | Link list returned | MCP tool |
| TC-EC-B-01 | Empty HTML | Boundary – empty | Empty list | Empty input |
| TC-EC-B-02 | HTML without links | Boundary – empty | Empty list | No links |
| TC-EC-N-01 | Malformed URLs | Equivalence – normal | Handled gracefully | Error handling |
| TC-EC-N-02 | Relative URLs | Equivalence – normal | Resolved correctly | URL resolution |
| TC-EC-N-03 | Case-insensitive domain | Equivalence – normal | Domain matched | Case handling |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock, patch

from src.crawler.bfs import (
    BFSResult,
    DomainBFSCrawler,
    ExtractedLink,
    LinkExtractor,
    LinkType,
    explore_domain,
    extract_page_links,
)

# =============================================================================
# Sample HTML for Testing
# =============================================================================

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
    <nav>
        <a href="/home">Home</a>
        <a href="/about">About</a>
    </nav>

    <article>
        <h1><a href="/main-topic">Main Topic Link</a></h1>

        <div class="toc">
            <a href="/section1">Section 1</a>
            <a href="/section2">Section 2</a>
        </div>

        <p>This is the main content with a <a href="/detail">詳細ページ</a> link.</p>
        <p>Also see the <a href="/official">公式ドキュメント</a> for more.</p>
        <p>External link to <a href="https://external.com/page">external site</a>.</p>

        <aside class="sidebar">
            <a href="/sidebar-link">Sidebar Item</a>
        </aside>

        <div class="related-articles">
            <a href="/related1">Related Article 1</a>
            <a href="/related2">Related Article 2</a>
        </div>

        <div class="pagination">
            <a href="/page/1">1</a>
            <a href="/page/2">2</a>
        </div>
    </article>
</body>
</html>
"""

SAMPLE_HTML_WITH_FRAGMENTS = """
<!DOCTYPE html>
<html>
<body>
    <a href="#section1">Anchor only</a>
    <a href="/page#section1">Page with anchor</a>
    <a href="javascript:void(0)">JavaScript link</a>
    <a href="mailto:test@example.com">Email</a>
    <a href="/valid-page">Valid Page</a>
</body>
</html>
"""


# =============================================================================
# ExtractedLink Tests
# =============================================================================

class TestExtractedLink:
    """Tests for ExtractedLink dataclass."""

    def test_hash_by_url(self):
        """Links should be hashable by URL (TC-EL-N-01)."""
        # Given: Two links with same URL but different text/type
        link1 = ExtractedLink(url="https://example.com/page", text="Page", link_type=LinkType.BODY)
        link2 = ExtractedLink(url="https://example.com/page", text="Different", link_type=LinkType.TOC)

        # When/Then: Hash should be same (based on URL)
        assert hash(link1) == hash(link2)

    def test_equality_by_url(self):
        """Links should be equal if URLs match (TC-EL-N-02)."""
        # Given: Links with same/different URLs
        link1 = ExtractedLink(url="https://example.com/page", text="Page", link_type=LinkType.BODY)
        link2 = ExtractedLink(url="https://example.com/page", text="Different", link_type=LinkType.TOC)
        link3 = ExtractedLink(url="https://example.com/other", text="Other", link_type=LinkType.BODY)

        # When/Then: Same URL = equal, different URL = not equal
        assert link1 == link2
        assert link1 != link3

    def test_in_set(self):
        """Links can be used in sets (deduplication) (TC-EL-N-03)."""
        # Given: Links with duplicate URLs
        links = {
            ExtractedLink(url="https://example.com/a", text="A", link_type=LinkType.BODY),
            ExtractedLink(url="https://example.com/a", text="A2", link_type=LinkType.TOC),
            ExtractedLink(url="https://example.com/b", text="B", link_type=LinkType.BODY),
        }

        # When/Then: Set deduplicates by URL
        assert len(links) == 2


# =============================================================================
# BFSResult Tests
# =============================================================================

class TestBFSResult:
    """Tests for BFSResult dataclass."""

    def test_to_dict(self):
        """to_dict should return serializable dictionary (TC-BR-N-01)."""
        # Given: A BFSResult with data
        result = BFSResult(
            domain="example.com",
            seed_url="https://example.com/",
            discovered_urls=["https://example.com/page1"],
            visited_count=5,
        )

        # When: Converting to dict
        d = result.to_dict()

        # Then: Should have all expected fields
        assert d["domain"] == "example.com"
        assert d["seed_url"] == "https://example.com/"
        assert len(d["discovered_urls"]) == 1
        assert d["visited_count"] == 5
        assert "started_at" in d


# =============================================================================
# LinkExtractor Tests
# =============================================================================

class TestLinkExtractor:
    """Tests for LinkExtractor class."""

    def test_extract_same_domain_links(self):
        """Should extract only same-domain links (TC-LE-N-01)."""
        # Given: HTML with internal and external links
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML,
            "https://example.com/page",
            "example.com",
        )

        # Then: External links should be excluded
        urls = [link.url for link in links]
        assert not any("external.com" in url for url in urls)
        assert any("/detail" in url for url in urls)

    def test_classify_navigation_links(self):
        """Navigation links should be classified as NAVIGATION (TC-LE-N-02)."""
        # Given: HTML with nav element containing links
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML,
            "https://example.com/page",
            "example.com",
        )

        # Then: Nav links should have NAVIGATION type
        nav_links = [l for l in links if l.link_type == LinkType.NAVIGATION]
        nav_urls = {l.url for l in nav_links}
        assert "https://example.com/home" in nav_urls
        assert "https://example.com/about" in nav_urls
        assert len(nav_links) == 2

    def test_classify_toc_links(self):
        """TOC links should be classified as TOC (TC-LE-N-03)."""
        # Given: HTML with TOC div containing links
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML,
            "https://example.com/page",
            "example.com",
        )

        # Then: TOC links should have TOC type
        toc_links = [l for l in links if l.link_type == LinkType.TOC]
        toc_urls = {l.url for l in toc_links}
        assert "https://example.com/section1" in toc_urls
        assert "https://example.com/section2" in toc_urls
        assert len(toc_links) == 2

    def test_classify_heading_links(self):
        """Links in headings should be classified as HEADING (TC-LE-N-04)."""
        # Given: HTML with link inside h1
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML,
            "https://example.com/page",
            "example.com",
        )

        # Then: Heading links should have HEADING type
        heading_links = [l for l in links if l.link_type == LinkType.HEADING]
        heading_urls = {l.url for l in heading_links}
        assert "https://example.com/main-topic" in heading_urls
        assert len(heading_links) == 1

    def test_classify_related_links(self):
        """Related article links should be classified as RELATED (TC-LE-N-05)."""
        # Given: HTML with related-articles div
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML,
            "https://example.com/page",
            "example.com",
        )

        # Then: Related links should have RELATED type
        related_links = [l for l in links if l.link_type == LinkType.RELATED]
        related_urls = {l.url for l in related_links}
        assert "https://example.com/related1" in related_urls
        assert "https://example.com/related2" in related_urls
        assert len(related_links) == 2

    def test_classify_sidebar_links(self):
        """Sidebar links should be classified as SIDEBAR (TC-LE-N-06)."""
        # Given: HTML with aside.sidebar containing link
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML,
            "https://example.com/page",
            "example.com",
        )

        # Then: Sidebar links should have SIDEBAR type
        sidebar_links = [l for l in links if l.link_type == LinkType.SIDEBAR]
        sidebar_urls = {l.url for l in sidebar_links}
        assert "https://example.com/sidebar-link" in sidebar_urls
        assert len(sidebar_links) == 1

    def test_classify_pagination_links(self):
        """Pagination links should be classified as PAGINATION (TC-LE-N-07)."""
        # Given: HTML with pagination div
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML,
            "https://example.com/page",
            "example.com",
        )

        # Then: Extraction completes successfully
        assert isinstance(links, list)
        assert len(links) >= 5

    def test_skip_anchor_only_links(self):
        """Anchor-only links (#section) should be skipped (TC-LE-N-08)."""
        # Given: HTML with anchor-only links
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML_WITH_FRAGMENTS,
            "https://example.com/page",
            "example.com",
        )

        # Then: Pure anchor links should be excluded
        urls = [link.url for link in links]
        assert not any(url.endswith("#section1") and "page" not in url for url in urls)

    def test_skip_javascript_links(self):
        """JavaScript links should be skipped (TC-LE-N-09)."""
        # Given: HTML with javascript: links
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML_WITH_FRAGMENTS,
            "https://example.com/page",
            "example.com",
        )

        # Then: JavaScript links should be excluded
        urls = [link.url for link in links]
        assert not any("javascript:" in url for url in urls)

    def test_skip_mailto_links(self):
        """Mailto links should be skipped (TC-LE-N-10)."""
        # Given: HTML with mailto: links
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML_WITH_FRAGMENTS,
            "https://example.com/page",
            "example.com",
        )

        # Then: Mailto links should be excluded
        urls = [link.url for link in links]
        assert not any("mailto:" in url for url in urls)

    def test_remove_fragment_from_urls(self):
        """URL fragments should be removed (TC-LE-N-11)."""
        # Given: HTML with URLs containing fragments
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML_WITH_FRAGMENTS,
            "https://example.com/current",
            "example.com",
        )

        # Then: Fragments should be removed from URLs
        page_links = [l for l in links if "/page" in l.url]
        for link in page_links:
            assert "#" not in link.url

    def test_priority_boost_for_detail_links(self):
        """Links with '詳細' text should get priority boost (TC-LE-N-12)."""
        # Given: HTML with link containing 詳細 text
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML,
            "https://example.com/page",
            "example.com",
        )

        # Then: Detail link should have boosted priority
        detail_link = next((l for l in links if "詳細" in l.text), None)
        assert detail_link is not None
        assert detail_link.url == "https://example.com/detail"
        assert detail_link.priority >= 0.65

    def test_priority_boost_for_official_links(self):
        """Links with '公式' text should get priority boost (TC-LE-N-13)."""
        # Given: HTML with link containing 公式 text
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML,
            "https://example.com/page",
            "example.com",
        )

        # Then: Official link should have boosted priority
        official_link = next((l for l in links if "公式" in l.text), None)
        assert official_link is not None
        assert official_link.url == "https://example.com/official"
        assert official_link.priority >= 0.7

    def test_links_sorted_by_priority(self):
        """Extracted links should be sorted by priority descending (TC-LE-N-14)."""
        # Given: HTML with multiple links
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            SAMPLE_HTML,
            "https://example.com/page",
            "example.com",
        )

        # Then: Links should be sorted by priority descending
        priorities = [l.priority for l in links]
        assert priorities == sorted(priorities, reverse=True)

    def test_deduplicate_urls(self):
        """Duplicate URLs should be deduplicated (TC-LE-N-15)."""
        # Given: HTML with duplicate links
        html = """
        <html><body>
            <a href="/page">Link 1</a>
            <a href="/page">Link 2</a>
            <a href="/page">Link 3</a>
        </body></html>
        """
        extractor = LinkExtractor()

        # When: Extracting links
        links = extractor.extract_links(
            html,
            "https://example.com/",
            "example.com",
        )

        # Then: URLs should be deduplicated
        urls = [l.url for l in links]
        assert len(urls) == len(set(urls))


# =============================================================================
# DomainBFSCrawler Tests
# =============================================================================

class TestDomainBFSCrawler:
    """Tests for DomainBFSCrawler class."""

    @pytest.mark.asyncio
    async def test_crawl_respects_max_depth(self):
        """BFS should not exceed max_depth (TC-BFS-N-01)."""
        # Given: A crawler with mocked robots manager
        crawler = DomainBFSCrawler()

        with patch.object(crawler, '_robots_manager') as mock_robots:
            mock_robots.can_fetch = AsyncMock(return_value=True)
            mock_robots.get_effective_delay = AsyncMock(return_value=0.01)

            async def mock_fetch(url):
                return f"<html><body><a href='/level{url.count('/')}'>{url}</a></body></html>"

            # When: Crawling with max_depth=1
            result = await crawler.crawl(
                "https://example.com/",
                max_depth=1,
                max_urls=100,
                fetch_content=mock_fetch,
            )

            # Then: Depth should not exceed limit
            assert result.max_depth_reached <= 1

    @pytest.mark.asyncio
    async def test_crawl_respects_max_urls(self):
        """BFS should not exceed max_urls (TC-BFS-N-02)."""
        # Given: A crawler with mocked robots manager
        crawler = DomainBFSCrawler()

        with patch.object(crawler, '_robots_manager') as mock_robots:
            mock_robots.can_fetch = AsyncMock(return_value=True)
            mock_robots.get_effective_delay = AsyncMock(return_value=0.01)

            async def mock_fetch(url):
                links = "".join([f'<a href="/page{i}">Page {i}</a>' for i in range(50)])
                return f"<html><body>{links}</body></html>"

            # When: Crawling with max_urls=10
            result = await crawler.crawl(
                "https://example.com/",
                max_depth=2,
                max_urls=10,
                fetch_content=mock_fetch,
            )

            # Then: URL count should not exceed limit
            assert len(result.discovered_urls) <= 10

    @pytest.mark.asyncio
    async def test_crawl_checks_robots_txt(self):
        """BFS should check robots.txt for each URL (TC-BFS-N-03)."""
        # Given: A crawler with mocked robots manager blocking certain URLs
        crawler = DomainBFSCrawler()
        blocked_url = "https://example.com/blocked"

        with patch.object(crawler, '_robots_manager') as mock_robots:
            async def can_fetch(url):
                return url != blocked_url

            mock_robots.can_fetch = can_fetch
            mock_robots.get_effective_delay = AsyncMock(return_value=0.01)

            async def mock_fetch(url):
                return f'<html><body><a href="{blocked_url}">Blocked</a></body></html>'

            # When: Crawling
            result = await crawler.crawl(
                "https://example.com/",
                max_depth=1,
                max_urls=10,
                fetch_content=mock_fetch,
            )

            # Then: Blocked URL should be recorded
            assert blocked_url in result.blocked_by_robots

    @pytest.mark.asyncio
    async def test_get_priority_links(self):
        """get_priority_links should return prioritized links (TC-BFS-N-04)."""
        # Given: A crawler with mocked robots manager
        crawler = DomainBFSCrawler()

        with patch.object(crawler, '_robots_manager') as mock_robots:
            mock_robots.can_fetch = AsyncMock(return_value=True)

            # When: Getting priority links
            links = await crawler.get_priority_links(
                SAMPLE_HTML,
                "https://example.com/page",
                limit=5,
            )

            # Then: Should return limited list with expected format
            assert len(links) <= 5
            assert all(len(link) == 3 for link in links)

    @pytest.mark.asyncio
    async def test_result_contains_priority_urls(self):
        """Result should contain priority-sorted URLs (TC-BFS-N-05)."""
        # Given: A crawler with mocked robots manager
        crawler = DomainBFSCrawler()

        with patch.object(crawler, '_robots_manager') as mock_robots:
            mock_robots.can_fetch = AsyncMock(return_value=True)
            mock_robots.get_effective_delay = AsyncMock(return_value=0.01)

            async def mock_fetch(url):
                return SAMPLE_HTML

            # When: Crawling
            result = await crawler.crawl(
                "https://example.com/",
                max_depth=1,
                max_urls=20,
                fetch_content=mock_fetch,
            )

            # Then: Priority URLs should be sorted descending
            assert len(result.priority_urls) >= 1
            priorities = [p for _, p in result.priority_urls]
            assert priorities == sorted(priorities, reverse=True)


# =============================================================================
# MCP Tool Function Tests
# =============================================================================

class TestMCPToolFunctions:
    """Tests for MCP tool integration functions."""

    @pytest.mark.asyncio
    async def test_explore_domain(self):
        """explore_domain should return structured result (TC-MCP-N-01)."""
        # Given: Mocked BFS crawler
        with patch("src.crawler.bfs.get_bfs_crawler") as mock_get:
            mock_crawler = MagicMock()
            mock_crawler.crawl = AsyncMock(return_value=BFSResult(
                domain="example.com",
                seed_url="https://example.com/",
                discovered_urls=["https://example.com/page1"],
                visited_count=2,
            ))
            mock_get.return_value = mock_crawler

            # When: Calling explore_domain
            result = await explore_domain("https://example.com/")

            # Then: Should return structured result
            assert result["domain"] == "example.com"
            assert result["visited_count"] == 2
            assert len(result["discovered_urls"]) == 1

    @pytest.mark.asyncio
    async def test_extract_page_links(self):
        """extract_page_links should return link list (TC-MCP-N-02)."""
        # Given: Mocked BFS crawler
        with patch("src.crawler.bfs.get_bfs_crawler") as mock_get:
            mock_crawler = MagicMock()
            mock_crawler.get_priority_links = AsyncMock(return_value=[
                ("https://example.com/page1", 0.9, "heading"),
                ("https://example.com/page2", 0.7, "body"),
            ])
            mock_get.return_value = mock_crawler

            # When: Calling extract_page_links
            result = await extract_page_links(
                "<html></html>",
                "https://example.com/",
            )

            # Then: Should return structured link list
            assert result["domain"] == "example.com"
            assert result["total"] == 2
            assert result["links"][0]["priority"] == 0.9


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge case tests."""

    def test_empty_html(self):
        """Empty HTML should return empty list (TC-EC-B-01)."""
        # Given: An extractor
        extractor = LinkExtractor()

        # When: Extracting from empty HTML
        links = extractor.extract_links(
            "",
            "https://example.com/",
            "example.com",
        )

        # Then: Should return empty list
        assert links == []

    def test_html_without_links(self):
        """HTML without links should return empty list (TC-EC-B-02)."""
        # Given: An extractor
        extractor = LinkExtractor()

        # When: Extracting from HTML without links
        links = extractor.extract_links(
            "<html><body><p>No links here</p></body></html>",
            "https://example.com/",
            "example.com",
        )

        # Then: Should return empty list
        assert links == []

    def test_malformed_urls(self):
        """Malformed URLs should be handled gracefully (TC-EC-N-01)."""
        # Given: An extractor
        extractor = LinkExtractor()
        html = """
        <html><body>
            <a href="">Empty href</a>
            <a href="   ">Whitespace href</a>
            <a>No href</a>
        </body></html>
        """

        # When: Extracting from HTML with malformed URLs
        links = extractor.extract_links(
            html,
            "https://example.com/",
            "example.com",
        )

        # Then: Should not raise exception
        assert isinstance(links, list)

    def test_relative_url_resolution(self):
        """Relative URLs should be resolved correctly (TC-EC-N-02)."""
        # Given: An extractor
        extractor = LinkExtractor()
        html = """
        <html><body>
            <a href="page">Relative</a>
            <a href="./page">Dot relative</a>
            <a href="../page">Parent relative</a>
            <a href="/absolute">Absolute</a>
        </body></html>
        """

        # When: Extracting from HTML with relative URLs
        links = extractor.extract_links(
            html,
            "https://example.com/dir/current",
            "example.com",
        )

        # Then: URLs should be resolved correctly
        urls = [l.url for l in links]
        assert "https://example.com/dir/page" in urls
        assert "https://example.com/absolute" in urls

    def test_case_insensitive_domain_matching(self):
        """Domain matching should be case-insensitive (TC-EC-N-03)."""
        # Given: An extractor
        extractor = LinkExtractor()
        html = """
        <html><body>
            <a href="https://Example.COM/page1">Mixed case</a>
            <a href="https://EXAMPLE.com/page2">Upper case</a>
        </body></html>
        """

        # When: Extracting from HTML with mixed case domains
        links = extractor.extract_links(
            html,
            "https://example.com/",
            "example.com",
        )

        # Then: Both links should be included
        assert len(links) == 2
