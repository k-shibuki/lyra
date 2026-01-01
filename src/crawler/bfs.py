"""
Domain-internal BFS crawler for Lyra.

Implements breadth-first search within a single domain (ADR-0006):
- Maximum depth of 2 from seed URL
- Link prioritization based on heading/TOC/related article structure
- robots.txt compliance
- Rate limiting and domain policy respect

References:
- ADR-0006: Crawling Strategy - Domain internal exploration
"""

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from bs4 import Tag

from src.crawler.robots import get_robots_manager
from src.utils.config import get_settings
from src.utils.logging import CausalTrace, get_logger

logger = get_logger(__name__)


# =============================================================================
# Enums and Data Classes
# =============================================================================


class LinkType(Enum):
    """Type of link based on context."""

    NAVIGATION = "navigation"  # Header/footer navigation
    TOC = "toc"  # Table of contents
    HEADING = "heading"  # Links within headings
    RELATED = "related"  # Related articles section
    BODY = "body"  # General body content
    SIDEBAR = "sidebar"  # Sidebar links
    PAGINATION = "pagination"  # Pagination links
    UNKNOWN = "unknown"


@dataclass
class ExtractedLink:
    """Link extracted from a page with context."""

    url: str
    text: str
    link_type: LinkType
    priority: float = 0.5
    depth: int = 0
    source_url: str = ""
    context: str = ""  # Surrounding text

    def __hash__(self) -> int:
        return hash(self.url)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ExtractedLink):
            return self.url == other.url
        return False


@dataclass
class BFSResult:
    """Result of BFS crawl within a domain."""

    domain: str
    seed_url: str
    discovered_urls: list[str] = field(default_factory=list)
    priority_urls: list[tuple[str, float]] = field(default_factory=list)
    visited_count: int = 0
    max_depth_reached: int = 0
    blocked_by_robots: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "seed_url": self.seed_url,
            "discovered_urls": self.discovered_urls,
            "priority_urls": self.priority_urls,
            "visited_count": self.visited_count,
            "max_depth_reached": self.max_depth_reached,
            "blocked_by_robots": self.blocked_by_robots,
            "errors": self.errors,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# =============================================================================
# Link Extractor
# =============================================================================


class LinkExtractor:
    """Extract and classify links from HTML content.

    Identifies link types based on:
    - Container element (nav, aside, main, article)
    - CSS classes/IDs (toc, related, pagination)
    - Link text patterns
    - Position in document
    """

    # CSS selectors for different link types
    NAV_SELECTORS = [
        "nav",
        "header nav",
        "footer nav",
        "[role='navigation']",
        ".navigation",
        ".nav",
    ]

    TOC_SELECTORS = [
        ".toc",
        ".table-of-contents",
        "#toc",
        "[class*='toc']",
        "[id*='toc']",
        ".contents",
        "#contents",
    ]

    RELATED_SELECTORS = [
        ".related",
        ".related-articles",
        ".related-posts",
        "[class*='related']",
        ".see-also",
        ".also-read",
        ".recommended",
        ".suggestions",
    ]

    SIDEBAR_SELECTORS = [
        "aside",
        ".sidebar",
        "#sidebar",
        "[role='complementary']",
    ]

    PAGINATION_SELECTORS = [
        ".pagination",
        ".pager",
        ".page-numbers",
        "[class*='pagination']",
        "nav.pagination",
    ]

    # Patterns to identify low-value links
    SKIP_PATTERNS = [
        r"^#",  # Anchor only
        r"^javascript:",  # JavaScript links
        r"^mailto:",  # Email links
        r"^tel:",  # Phone links
        r"\.(jpg|jpeg|png|gif|svg|pdf|zip|exe|mp3|mp4|avi)$",  # Media files
        r"/tag/",
        r"/tags/",  # Tag pages
        r"/category/",
        r"/categories/",  # Category pages
        r"/author/",
        r"/authors/",  # Author pages
        r"/page/\d+",  # Pagination
        r"/feed/",
        r"/rss",  # RSS feeds
        r"/search",  # Search pages
        r"/login",
        r"/register",  # Auth pages
        r"/cart",
        r"/checkout",  # E-commerce
    ]

    def __init__(self) -> None:
        self._settings = get_settings()
        self._skip_patterns = [re.compile(p, re.I) for p in self.SKIP_PATTERNS]

    def extract_links(
        self,
        html: str,
        base_url: str,
        target_domain: str,
        *,
        same_domain_only: bool = True,
        allow_pdf: bool = False,
    ) -> list[ExtractedLink]:
        """Extract links from HTML content.

        Args:
            html: HTML content.
            base_url: Base URL for resolving relative links.
            target_domain: Target domain to filter same-domain links.
            same_domain_only: If True, only return links within target_domain (crawler use).
            allow_pdf: If True, do not skip .pdf links (useful for citation detection).

        Returns:
            List of ExtractedLink objects.
        """
        soup = BeautifulSoup(html, "html.parser")
        links: list[ExtractedLink] = []
        seen_urls: set[str] = set()

        # Find all anchor tags
        for anchor in soup.find_all("a", href=True):
            href_attr = anchor.get("href", "")
            # Ensure href is a string (could be AttributeValueList in rare cases)
            href = str(href_attr).strip() if href_attr else ""

            if not href:
                continue

            # Skip unwanted patterns
            if self._should_skip(href, allow_pdf=allow_pdf):
                continue

            # Resolve relative URL
            absolute_url = urljoin(base_url, href)

            # Remove fragment
            absolute_url, _ = urldefrag(absolute_url)

            # Check same domain
            parsed = urlparse(absolute_url)
            if same_domain_only and parsed.netloc.lower() != target_domain.lower():
                continue

            # Skip duplicates
            if absolute_url in seen_urls:
                continue
            seen_urls.add(absolute_url)

            # Classify link
            link_type = self._classify_link(anchor, soup)
            priority = self._calculate_priority(anchor, link_type)

            # Get link text and context
            text = anchor.get_text(strip=True)[:200]
            context = self._get_context(anchor)

            links.append(
                ExtractedLink(
                    url=absolute_url,
                    text=text,
                    link_type=link_type,
                    priority=priority,
                    source_url=base_url,
                    context=context,
                )
            )

        # Sort by priority
        links.sort(key=lambda x: x.priority, reverse=True)

        return links

    def _should_skip(self, href: str, *, allow_pdf: bool = False) -> bool:
        """Check if link should be skipped."""
        is_pdf = bool(re.search(r"\.pdf(?:$|[?#])", href, re.I))
        for pattern in self._skip_patterns:
            # Allow PDF links when explicitly enabled (citation detection use-case).
            if allow_pdf and is_pdf and "pdf" in pattern.pattern and "jpg" in pattern.pattern:
                continue
            if pattern.search(href):
                return True
        return False

    def _classify_link(self, anchor: Tag, soup: BeautifulSoup) -> LinkType:
        """Classify link type based on context.

        Args:
            anchor: BeautifulSoup anchor element.
            soup: Full BeautifulSoup document.

        Returns:
            LinkType enum value.
        """
        # Check if link is within specific containers
        for parent in anchor.parents:
            if parent.name is None:
                continue

            parent_str = str(parent.get("class", "")) + str(parent.get("id", ""))
            parent_str = parent_str.lower()

            # Navigation
            if parent.name == "nav" or "nav" in parent_str:
                return LinkType.NAVIGATION

            # TOC
            if "toc" in parent_str or "content" in parent_str:
                return LinkType.TOC

            # Related
            if "related" in parent_str or "see-also" in parent_str:
                return LinkType.RELATED

            # Sidebar
            if parent.name == "aside" or "sidebar" in parent_str:
                return LinkType.SIDEBAR

            # Pagination
            if "pagination" in parent_str or "pager" in parent_str:
                return LinkType.PAGINATION

            # Heading
            if parent.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                return LinkType.HEADING

        # Default to body
        return LinkType.BODY

    def _calculate_priority(self, anchor: Tag, link_type: LinkType) -> float:
        """Calculate link priority score.

        Args:
            anchor: BeautifulSoup anchor element.
            link_type: Classified link type.

        Returns:
            Priority score (0.0 - 1.0).
        """
        # Base priority by type (per ADR-0006)
        type_priority = {
            LinkType.HEADING: 0.9,  # High value - linked from headings
            LinkType.TOC: 0.85,  # Table of contents - structured
            LinkType.RELATED: 0.8,  # Related articles - editorial choice
            LinkType.BODY: 0.6,  # General body links
            LinkType.SIDEBAR: 0.4,  # Sidebar - often secondary
            LinkType.NAVIGATION: 0.3,  # Navigation - structural
            LinkType.PAGINATION: 0.2,  # Pagination - low priority
            LinkType.UNKNOWN: 0.5,
        }

        priority = type_priority.get(link_type, 0.5)

        # Boost based on link text
        text = anchor.get_text(strip=True).lower()

        # High-value text patterns
        if any(kw in text for kw in ["詳細", "detail", "more", "続き", "全文"]):
            priority += 0.1

        # Document/resource links
        if any(kw in text for kw in ["資料", "document", "report", "paper"]):
            priority += 0.1

        # Official/primary source indicators
        if any(kw in text for kw in ["公式", "official", "原文", "source"]):
            priority += 0.15

        return min(1.0, priority)

    def _get_context(self, anchor: Tag, chars: int = 100) -> str:
        """Get surrounding text context for link.

        Args:
            anchor: BeautifulSoup anchor element.
            chars: Characters of context to extract.

        Returns:
            Context string.
        """
        # Get parent paragraph or container
        parent = anchor.find_parent(["p", "li", "div", "article"])

        if parent:
            text = parent.get_text(strip=True)
            return text[:chars] if len(text) > chars else text

        return ""


# =============================================================================
# BFS Crawler
# =============================================================================


class DomainBFSCrawler:
    """Breadth-first search crawler within a single domain.

    Implements ADR-0006 requirements:
    - Maximum depth of 2 from seed URL
    - Heading/TOC/related article link prioritization
    - robots.txt compliance
    - Rate limiting
    """

    DEFAULT_MAX_DEPTH = 2
    DEFAULT_MAX_URLS = 50

    def __init__(self) -> None:
        self._settings = get_settings()
        self._link_extractor = LinkExtractor()
        self._robots_manager = get_robots_manager()

    async def crawl(
        self,
        seed_url: str,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_urls: int = DEFAULT_MAX_URLS,
        fetch_content: Callable[[str], Any] | None = None,
        task_id: str | None = None,
    ) -> BFSResult:
        """Perform BFS crawl from seed URL within domain.

        Args:
            seed_url: Starting URL for crawl.
            max_depth: Maximum depth (default: 2).
            max_urls: Maximum URLs to discover.
            fetch_content: Async function to fetch URL content.
            task_id: Associated task ID for logging.

        Returns:
            BFSResult with discovered URLs.
        """
        parsed = urlparse(seed_url)
        domain = parsed.netloc.lower()

        result = BFSResult(
            domain=domain,
            seed_url=seed_url,
        )

        # Queue: (url, depth)
        queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        await queue.put((seed_url, 0))

        visited: set[str] = set()
        discovered: list[ExtractedLink] = []

        with CausalTrace():
            logger.info(
                "Starting domain BFS",
                domain=domain,
                seed_url=seed_url[:80],
                max_depth=max_depth,
                max_urls=max_urls,
            )

            while not queue.empty() and len(discovered) < max_urls:
                url, depth = await queue.get()

                # Skip if already visited
                if url in visited:
                    continue

                visited.add(url)
                result.visited_count += 1

                # Check depth limit
                if depth > max_depth:
                    continue

                result.max_depth_reached = max(result.max_depth_reached, depth)

                # Check robots.txt
                if not await self._robots_manager.can_fetch(url):
                    result.blocked_by_robots.append(url)
                    logger.debug("URL blocked by robots.txt", url=url[:80])
                    continue

                # Fetch content
                html = await self._fetch_html(url, fetch_content)

                if html is None:
                    result.errors.append(f"Failed to fetch: {url}")
                    continue

                # Extract links
                links = self._link_extractor.extract_links(html, url, domain)

                # Process links
                for link in links:
                    if link.url not in visited and len(discovered) < max_urls:
                        link.depth = depth + 1
                        discovered.append(link)

                        # Add to queue if within depth limit
                        if depth + 1 <= max_depth:
                            await queue.put((link.url, depth + 1))

                # Respect rate limiting
                delay = await self._robots_manager.get_effective_delay(domain)
                await asyncio.sleep(delay)

            # Build results
            result.discovered_urls = [link.url for link in discovered]
            result.priority_urls = [
                (link.url, link.priority)
                for link in sorted(discovered, key=lambda x: x.priority, reverse=True)
            ]
            result.completed_at = datetime.now(UTC)

            logger.info(
                "Domain BFS completed",
                domain=domain,
                visited=result.visited_count,
                discovered=len(result.discovered_urls),
                max_depth=result.max_depth_reached,
                blocked=len(result.blocked_by_robots),
            )

            return result

    async def _fetch_html(
        self,
        url: str,
        fetch_content: Callable[[str], Any] | None,
    ) -> str | None:
        """Fetch HTML content from URL.

        Args:
            url: URL to fetch.
            fetch_content: Custom fetch function, or use default.

        Returns:
            HTML content or None.
        """
        try:
            if fetch_content:
                result = await fetch_content(url)
                if isinstance(result, str):
                    return result
                if isinstance(result, dict) and result.get("ok"):
                    # Read from file path
                    html_path = result.get("html_path")
                    if html_path:
                        from pathlib import Path

                        return Path(html_path).read_text(errors="replace")
                return None

            # Default: simple HTTP fetch
            from curl_cffi import requests as curl_requests

            response = curl_requests.get(
                url,
                timeout=15,
                impersonate="chrome",
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                },
            )

            if response.status_code == 200:
                return cast(str, response.text)

            return None

        except Exception as e:
            logger.debug("HTML fetch error", url=url[:80], error=str(e))
            return None

    async def get_priority_links(
        self,
        html: str,
        base_url: str,
        limit: int = 20,
    ) -> list[tuple[str, float, str]]:
        """Get high-priority links from a single page.

        Useful for targeted link extraction without full BFS.

        Args:
            html: HTML content.
            base_url: Base URL for resolving.
            limit: Maximum links to return.

        Returns:
            List of (url, priority, link_type) tuples.
        """
        parsed = urlparse(base_url)
        domain = parsed.netloc.lower()

        links = self._link_extractor.extract_links(html, base_url, domain)

        # Filter by robots.txt
        allowed_links = []
        for link in links[: limit * 2]:  # Check more than needed
            if await self._robots_manager.can_fetch(link.url):
                allowed_links.append(link)
            if len(allowed_links) >= limit:
                break

        return [(link.url, link.priority, link.link_type.value) for link in allowed_links[:limit]]


# =============================================================================
# Global Instance
# =============================================================================

_bfs_crawler: DomainBFSCrawler | None = None


def get_bfs_crawler() -> DomainBFSCrawler:
    """Get or create global BFS crawler instance.

    Returns:
        DomainBFSCrawler instance.
    """
    global _bfs_crawler
    if _bfs_crawler is None:
        _bfs_crawler = DomainBFSCrawler()
    return _bfs_crawler


# =============================================================================
# MCP Tool Integration
# =============================================================================


async def explore_domain(
    seed_url: str,
    max_depth: int = 2,
    max_urls: int = 50,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Explore domain via BFS from seed URL (for MCP tool use).

    Args:
        seed_url: Starting URL.
        max_depth: Maximum crawl depth.
        max_urls: Maximum URLs to discover.
        task_id: Associated task ID.

    Returns:
        BFS exploration result.
    """
    crawler = get_bfs_crawler()
    result = await crawler.crawl(
        seed_url,
        max_depth=max_depth,
        max_urls=max_urls,
        task_id=task_id,
    )
    return result.to_dict()


async def extract_page_links(
    html: str,
    base_url: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Extract priority links from a page (for MCP tool use).

    Args:
        html: HTML content.
        base_url: Page URL.
        limit: Maximum links.

    Returns:
        Extracted links with priorities.
    """
    crawler = get_bfs_crawler()
    links = await crawler.get_priority_links(html, base_url, limit)

    parsed = urlparse(base_url)

    return {
        "domain": parsed.netloc.lower(),
        "base_url": base_url,
        "links": [
            {"url": url, "priority": priority, "type": link_type}
            for url, priority, link_type in links
        ],
        "total": len(links),
    }
