"""
robots.txt and sitemap.xml parser for Lyra.

Implements:
- robots.txt parsing and compliance checking (ADR-0006)
- sitemap.xml parsing and priority URL extraction
- Crawl-delay respect and rate limiting integration
- Caching with TTL for efficiency

References:
- https://www.rfc-editor.org/rfc/rfc9309.html (Robots Exclusion Protocol)
- https://www.sitemaps.org/protocol.html (Sitemap Protocol)
"""

import asyncio
import gzip
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlparse

from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RobotsRule:
    """Parsed robots.txt rules for a domain."""

    domain: str
    allowed_paths: list[str] = field(default_factory=list)
    disallowed_paths: list[str] = field(default_factory=list)
    crawl_delay: float | None = None
    sitemap_urls: list[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw_content: str | None = None

    def is_expired(self, ttl_hours: int = 24) -> bool:
        """Check if robots.txt cache is expired."""
        expiry = self.fetched_at + timedelta(hours=ttl_hours)
        return datetime.now(UTC) > expiry


@dataclass
class SitemapEntry:
    """Single entry from a sitemap."""

    loc: str  # URL
    lastmod: datetime | None = None
    changefreq: str | None = None  # always, hourly, daily, weekly, monthly, yearly, never
    priority: float = 0.5

    def score(self) -> float:
        """Calculate priority score for URL selection.

        Higher score = higher priority for crawling.
        """
        score = self.priority

        # Boost recent content
        if self.lastmod:
            days_old = (datetime.now(UTC) - self.lastmod).days
            if days_old < 7:
                score += 0.2
            elif days_old < 30:
                score += 0.1

        # Boost frequently changing content
        freq_boost = {
            "always": 0.3,
            "hourly": 0.25,
            "daily": 0.2,
            "weekly": 0.1,
            "monthly": 0.05,
        }
        if self.changefreq:
            score += freq_boost.get(self.changefreq.lower(), 0)

        return min(1.0, score)


@dataclass
class SitemapResult:
    """Parsed sitemap with entries."""

    domain: str
    entries: list[SitemapEntry] = field(default_factory=list)
    index_urls: list[str] = field(default_factory=list)  # Nested sitemap URLs
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    total_urls: int = 0

    def get_priority_urls(
        self,
        limit: int = 50,
        min_score: float = 0.5,
    ) -> list[tuple[str, float]]:
        """Get high-priority URLs for crawling.

        Args:
            limit: Maximum number of URLs to return.
            min_score: Minimum score threshold.

        Returns:
            List of (url, score) tuples, sorted by score descending.
        """
        scored = [
            (entry.loc, entry.score()) for entry in self.entries if entry.score() >= min_score
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]


# =============================================================================
# Robots.txt Parser
# =============================================================================


class RobotsChecker:
    """Check URL compliance with robots.txt rules.

    Features:
    - Async fetching with caching
    - Crawl-delay extraction and enforcement
    - Sitemap URL discovery
    - Graceful degradation on parse errors
    """

    DEFAULT_USER_AGENT = "*"
    LYRA_USER_AGENT = "Lyra"  # Our crawler's user agent

    def __init__(self) -> None:
        self._settings = get_settings()
        self._cache: dict[str, RobotsRule] = {}
        self._lock = asyncio.Lock()

    async def can_fetch(
        self,
        url: str,
        user_agent: str | None = None,
    ) -> bool:
        """Check if URL can be fetched according to robots.txt.

        Args:
            url: URL to check.
            user_agent: User agent to check for (default: Lyra or *).

        Returns:
            True if URL is allowed, False otherwise.
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path or "/"

        # Get or fetch robots.txt
        rules = await self._get_robots_rules(domain)

        if rules is None:
            # No robots.txt or fetch failed - assume allowed
            return True

        # Check disallowed paths
        for disallowed in rules.disallowed_paths:
            if self._path_matches(path, disallowed):
                # Check if specifically allowed
                for allowed in rules.allowed_paths:
                    if self._path_matches(path, allowed):
                        if len(allowed) > len(disallowed):
                            return True
                return False

        return True

    async def get_crawl_delay(self, domain: str) -> float | None:
        """Get crawl-delay for domain from robots.txt.

        Args:
            domain: Domain name.

        Returns:
            Crawl delay in seconds, or None if not specified.
        """
        rules = await self._get_robots_rules(domain)
        if rules and rules.crawl_delay:
            return rules.crawl_delay
        return None

    async def get_sitemaps(self, domain: str) -> list[str]:
        """Get sitemap URLs from robots.txt.

        Args:
            domain: Domain name.

        Returns:
            List of sitemap URLs declared in robots.txt.
        """
        rules = await self._get_robots_rules(domain)
        if rules:
            return rules.sitemap_urls
        return []

    async def _get_robots_rules(self, domain: str) -> RobotsRule | None:
        """Get robots.txt rules for domain, fetching if needed.

        Args:
            domain: Domain name.

        Returns:
            RobotsRule object or None if unavailable.
        """
        async with self._lock:
            # Check cache
            if domain in self._cache:
                cached = self._cache[domain]
                if not cached.is_expired():
                    return cached

            # Fetch fresh copy
            rules = await self._fetch_robots_txt(domain)

            if rules:
                self._cache[domain] = rules

            return rules

    async def _fetch_robots_txt(self, domain: str) -> RobotsRule | None:
        """Fetch and parse robots.txt for domain.

        Args:
            domain: Domain name.

        Returns:
            RobotsRule object or None on failure.
        """
        robots_url = f"https://{domain}/robots.txt"

        try:
            from curl_cffi import requests as curl_requests

            response = curl_requests.get(
                robots_url,
                timeout=10,
                impersonate="chrome",
                headers={
                    "Accept": "text/plain, text/html, */*",
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                },
            )

            if response.status_code == 404:
                # No robots.txt - return empty rules (allow all)
                logger.debug("No robots.txt found", domain=domain)
                return RobotsRule(
                    domain=domain,
                    allowed_paths=["*"],
                    disallowed_paths=[],
                )

            if response.status_code != 200:
                logger.warning(
                    "robots.txt fetch failed",
                    domain=domain,
                    status=response.status_code,
                )
                return None

            content = response.text
            rules = self._parse_robots_txt(domain, content)

            logger.info(
                "Fetched robots.txt",
                domain=domain,
                disallowed_count=len(rules.disallowed_paths),
                sitemap_count=len(rules.sitemap_urls),
                crawl_delay=rules.crawl_delay,
            )

            return rules

        except Exception as e:
            logger.error("robots.txt fetch error", domain=domain, error=str(e))
            return None

    def _parse_robots_txt(self, domain: str, content: str) -> RobotsRule:
        """Parse robots.txt content.

        Extracts rules for our user agent (Lyra) or *.

        Args:
            domain: Domain name.
            content: robots.txt content.

        Returns:
            Parsed RobotsRule object.
        """
        rules = RobotsRule(domain=domain, raw_content=content)

        applies_to_us = False

        for line in content.split("\n"):
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Handle continuation
            if ":" not in line:
                continue

            directive, _, value = line.partition(":")
            directive = directive.strip().lower()
            value = value.strip()

            # Remove inline comments (RFC 9309 allows # comments anywhere)
            if "#" in value:
                value = value.split("#", 1)[0].strip()

            if directive == "user-agent":
                # New user-agent block
                if value.lower() in ("*", self.LYRA_USER_AGENT.lower()):
                    applies_to_us = True
                else:
                    applies_to_us = False

            elif directive == "disallow" and applies_to_us:
                if value:
                    rules.disallowed_paths.append(value)

            elif directive == "allow" and applies_to_us:
                if value:
                    rules.allowed_paths.append(value)

            elif directive == "crawl-delay" and applies_to_us:
                try:
                    rules.crawl_delay = float(value)
                except ValueError:
                    pass

            elif directive == "sitemap":
                # Sitemap directives are not user-agent specific
                if value:
                    rules.sitemap_urls.append(value)

        return rules

    @staticmethod
    def _path_matches(path: str, pattern: str) -> bool:
        """Check if path matches robots.txt pattern.

        Supports:
        - * wildcard (any characters)
        - $ end anchor

        Args:
            path: URL path to check.
            pattern: robots.txt pattern.

        Returns:
            True if path matches pattern.
        """
        # Empty pattern matches nothing
        if not pattern:
            return False

        # Convert robots.txt pattern to regex
        regex_pattern = "^"
        i = 0

        while i < len(pattern):
            c = pattern[i]
            if c == "*":
                regex_pattern += ".*"
            elif c == "$" and i == len(pattern) - 1:
                regex_pattern += "$"
            else:
                regex_pattern += re.escape(c)
            i += 1

        try:
            return bool(re.match(regex_pattern, path))
        except re.error:
            # Invalid pattern - assume no match
            return False

    def clear_cache(self) -> None:
        """Clear robots.txt cache."""
        self._cache.clear()


# =============================================================================
# Sitemap Parser
# =============================================================================


class SitemapParser:
    """Parse sitemap.xml and sitemap index files.

    Features:
    - Handles sitemap index files (recursive parsing)
    - Supports gzipped sitemaps
    - Extracts priority, lastmod, changefreq
    - URL scoring for crawl prioritization
    """

    # Sitemap XML namespaces
    SITEMAP_NS = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    }

    MAX_URLS_PER_SITEMAP = 1000  # Limit to prevent memory issues
    MAX_DEPTH = 3  # Maximum sitemap index nesting depth

    def __init__(self) -> None:
        self._settings = get_settings()
        self._cache: dict[str, SitemapResult] = {}

    async def parse(
        self,
        sitemap_url: str,
        depth: int = 0,
    ) -> SitemapResult:
        """Parse sitemap from URL.

        Handles both regular sitemaps and sitemap index files.

        Args:
            sitemap_url: URL of sitemap.
            depth: Current nesting depth (for index files).

        Returns:
            SitemapResult with extracted entries.
        """
        parsed = urlparse(sitemap_url)
        domain = parsed.netloc.lower()

        # Check cache
        cache_key = f"{domain}:{sitemap_url}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            age = datetime.now(UTC) - cached.fetched_at
            if age.total_seconds() / 3600 < 24:  # Less than 24 hours
                return cached

        result = SitemapResult(domain=domain)

        try:
            content = await self._fetch_sitemap(sitemap_url)

            if content is None:
                return result

            # Parse XML
            root = ET.fromstring(content)

            # Determine sitemap type
            root_tag = root.tag.lower()

            if "sitemapindex" in root_tag:
                # Sitemap index - extract nested sitemap URLs
                result.index_urls = self._extract_sitemap_urls(root)

                # Recursively parse nested sitemaps (with depth limit)
                if depth < self.MAX_DEPTH:
                    for nested_url in result.index_urls[:10]:  # Limit nested parsing
                        nested_result = await self.parse(nested_url, depth + 1)
                        result.entries.extend(nested_result.entries)
            else:
                # Regular sitemap - extract URLs
                result.entries = self._extract_url_entries(root)

            result.total_urls = len(result.entries)

            # Cache result
            self._cache[cache_key] = result

            logger.info(
                "Parsed sitemap",
                url=sitemap_url[:80],
                entries=len(result.entries),
                index_urls=len(result.index_urls),
            )

            return result

        except ET.ParseError as e:
            logger.warning("Sitemap XML parse error", url=sitemap_url[:80], error=str(e))
            return result
        except Exception as e:
            logger.error("Sitemap parse error", url=sitemap_url[:80], error=str(e))
            return result

    async def discover_sitemaps(self, domain: str) -> list[str]:
        """Discover sitemap URLs for domain.

        Checks:
        1. robots.txt Sitemap directives
        2. Standard /sitemap.xml location
        3. Common sitemap patterns

        Args:
            domain: Domain name.

        Returns:
            List of discovered sitemap URLs.
        """
        sitemaps = []

        # Check robots.txt
        robots_checker = RobotsChecker()
        robot_sitemaps = await robots_checker.get_sitemaps(domain)
        sitemaps.extend(robot_sitemaps)

        # Check standard locations
        standard_locations = [
            f"https://{domain}/sitemap.xml",
            f"https://{domain}/sitemap_index.xml",
            f"https://{domain}/sitemaps.xml",
        ]

        for url in standard_locations:
            if url not in sitemaps:
                # Quick HEAD check
                if await self._sitemap_exists(url):
                    sitemaps.append(url)

        logger.info(
            "Discovered sitemaps",
            domain=domain,
            count=len(sitemaps),
        )

        return sitemaps

    async def get_priority_urls(
        self,
        domain: str,
        limit: int = 50,
        min_score: float = 0.5,
    ) -> list[tuple[str, float]]:
        """Get high-priority URLs from domain's sitemaps.

        Args:
            domain: Domain name.
            limit: Maximum URLs to return.
            min_score: Minimum priority score.

        Returns:
            List of (url, score) tuples.
        """
        all_entries: list[SitemapEntry] = []

        # Discover and parse sitemaps
        sitemap_urls = await self.discover_sitemaps(domain)

        for sitemap_url in sitemap_urls[:5]:  # Limit sitemap processing
            result = await self.parse(sitemap_url)
            all_entries.extend(result.entries)

        # Deduplicate and score
        seen_urls: set[str] = set()
        scored: list[tuple[str, float]] = []

        for entry in all_entries:
            if entry.loc not in seen_urls:
                seen_urls.add(entry.loc)
                score = entry.score()
                if score >= min_score:
                    scored.append((entry.loc, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def _fetch_sitemap(self, url: str) -> str | None:
        """Fetch sitemap content.

        Handles gzipped sitemaps automatically.

        Args:
            url: Sitemap URL.

        Returns:
            Sitemap content as string, or None on failure.
        """
        try:
            from curl_cffi import requests as curl_requests

            response = curl_requests.get(
                url,
                timeout=15,
                impersonate="chrome",
                headers={
                    "Accept": "application/xml, text/xml, */*",
                    "Accept-Encoding": "gzip, deflate",
                },
            )

            if response.status_code != 200:
                logger.debug(
                    "Sitemap fetch failed",
                    url=url[:80],
                    status=response.status_code,
                )
                return None

            content = response.content

            # Check for gzip
            if url.endswith(".gz") or content[:2] == b"\x1f\x8b":
                try:
                    content = gzip.decompress(content)
                except gzip.BadGzipFile:
                    pass  # Not actually gzipped

            return cast(str, content.decode("utf-8", errors="replace"))

        except Exception as e:
            logger.debug("Sitemap fetch error", url=url[:80], error=str(e))
            return None

    async def _sitemap_exists(self, url: str) -> bool:
        """Check if sitemap exists via HEAD request.

        Args:
            url: Sitemap URL.

        Returns:
            True if sitemap exists.
        """
        try:
            from curl_cffi import requests as curl_requests

            response = curl_requests.head(
                url,
                timeout=5,
                impersonate="chrome",
            )

            return cast(bool, response.status_code == 200)

        except Exception as e:
            logger.debug("Sitemap HEAD request failed", url=url, error=str(e))
            return False

    def _extract_sitemap_urls(self, root: ET.Element) -> list[str]:
        """Extract sitemap URLs from sitemap index.

        Args:
            root: XML root element.

        Returns:
            List of sitemap URLs.
        """
        urls = []

        # Try with namespace
        for sitemap in root.findall(".//sm:sitemap", self.SITEMAP_NS):
            loc = sitemap.find("sm:loc", self.SITEMAP_NS)
            if loc is not None and loc.text:
                urls.append(loc.text.strip())

        # Try without namespace
        if not urls:
            for sitemap in root.findall(".//sitemap"):
                loc = sitemap.find("loc")
                if loc is not None and loc.text:
                    urls.append(loc.text.strip())

        return urls[: self.MAX_URLS_PER_SITEMAP]

    def _extract_url_entries(self, root: ET.Element) -> list[SitemapEntry]:
        """Extract URL entries from sitemap.

        Args:
            root: XML root element.

        Returns:
            List of SitemapEntry objects.
        """
        entries = []

        # Try with namespace
        url_elements = root.findall(".//sm:url", self.SITEMAP_NS)

        # Try without namespace if none found
        if not url_elements:
            url_elements = root.findall(".//url")

        for url_elem in url_elements[: self.MAX_URLS_PER_SITEMAP]:
            entry = self._parse_url_element(url_elem)
            if entry:
                entries.append(entry)

        return entries

    def _parse_url_element(self, url_elem: ET.Element) -> SitemapEntry | None:
        """Parse single URL element from sitemap.

        Args:
            url_elem: XML url element.

        Returns:
            SitemapEntry or None if invalid.
        """
        # Try with namespace first
        loc = url_elem.find("sm:loc", self.SITEMAP_NS)
        if loc is None:
            loc = url_elem.find("loc")

        if loc is None or not loc.text:
            return None

        entry = SitemapEntry(loc=loc.text.strip())

        # Extract optional fields
        lastmod = url_elem.find("sm:lastmod", self.SITEMAP_NS)
        if lastmod is None:
            lastmod = url_elem.find("lastmod")
        if lastmod is not None and lastmod.text:
            entry.lastmod = self._parse_datetime(lastmod.text.strip())

        changefreq = url_elem.find("sm:changefreq", self.SITEMAP_NS)
        if changefreq is None:
            changefreq = url_elem.find("changefreq")
        if changefreq is not None and changefreq.text:
            entry.changefreq = changefreq.text.strip()

        priority = url_elem.find("sm:priority", self.SITEMAP_NS)
        if priority is None:
            priority = url_elem.find("priority")
        if priority is not None and priority.text:
            try:
                entry.priority = float(priority.text.strip())
            except ValueError:
                pass

        return entry

    @staticmethod
    def _parse_datetime(date_str: str) -> datetime | None:
        """Parse datetime from sitemap lastmod.

        Supports various ISO 8601 formats.

        Args:
            date_str: Date string.

        Returns:
            Parsed datetime or None.
        """
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
            except ValueError:
                continue

        return None

    def clear_cache(self) -> None:
        """Clear sitemap cache."""
        self._cache.clear()


# =============================================================================
# Integration with Fetcher
# =============================================================================


class RobotsManager:
    """Manages robots.txt and sitemap integration with crawler.

    Provides unified interface for:
    - URL compliance checking
    - Crawl delay enforcement
    - Priority URL discovery from sitemaps
    """

    def __init__(self) -> None:
        self._robots_checker = RobotsChecker()
        self._sitemap_parser = SitemapParser()
        self._settings = get_settings()

    async def can_fetch(self, url: str) -> bool:
        """Check if URL can be fetched (robots.txt compliance).

        Args:
            url: URL to check.

        Returns:
            True if allowed.
        """
        return await self._robots_checker.can_fetch(url)

    async def get_effective_delay(self, domain: str) -> float:
        """Get effective crawl delay for domain.

        Returns the maximum of:
        - robots.txt Crawl-delay
        - Domain policy QPS
        - Global minimum delay

        Args:
            domain: Domain name.

        Returns:
            Delay in seconds.
        """
        # Get robots.txt crawl-delay
        robots_delay = await self._robots_checker.get_crawl_delay(domain)

        # Get domain policy QPS
        db = await get_database()
        domain_info = await db.fetch_one(
            "SELECT qps_limit FROM domains WHERE domain = ?",
            (domain,),
        )

        policy_delay = 1.0 / self._settings.crawler.domain_qps  # Default
        if domain_info and domain_info.get("qps_limit"):
            policy_delay = 1.0 / domain_info["qps_limit"]

        # Global minimum
        min_delay = self._settings.crawler.delay_min

        # Return maximum
        delays = [min_delay, policy_delay]
        if robots_delay:
            delays.append(robots_delay)

        return max(delays)

    async def get_priority_urls(
        self,
        domain: str,
        limit: int = 50,
    ) -> list[tuple[str, float]]:
        """Get priority URLs from sitemap for crawling.

        Args:
            domain: Domain name.
            limit: Maximum URLs to return.

        Returns:
            List of (url, score) tuples.
        """
        return await self._sitemap_parser.get_priority_urls(domain, limit)

    async def discover_content(
        self,
        domain: str,
        keywords: list[str] | None = None,
    ) -> list[str]:
        """Discover relevant URLs from sitemap.

        Filters sitemap URLs by keywords if provided.

        Args:
            domain: Domain name.
            keywords: Optional keywords to filter URLs.

        Returns:
            List of relevant URLs.
        """
        urls = await self.get_priority_urls(domain, limit=100)

        if not keywords:
            return [url for url, _ in urls]

        # Filter by keywords
        filtered = []
        keywords_lower = [k.lower() for k in keywords]

        for url, _score in urls:
            url_lower = url.lower()
            if any(kw in url_lower for kw in keywords_lower):
                filtered.append(url)

        return filtered

    async def get_robots_info(self, domain: str) -> dict[str, Any]:
        """Get robots.txt information for domain.

        Args:
            domain: Domain name.

        Returns:
            Dictionary with robots.txt info.
        """
        rules = await self._robots_checker._get_robots_rules(domain)

        if rules is None:
            return {
                "domain": domain,
                "found": False,
            }

        return {
            "domain": domain,
            "found": True,
            "crawl_delay": rules.crawl_delay,
            "sitemap_urls": rules.sitemap_urls,
            "disallowed_count": len(rules.disallowed_paths),
            "fetched_at": rules.fetched_at.isoformat(),
        }

    def clear_cache(self) -> None:
        """Clear all caches."""
        self._robots_checker.clear_cache()
        self._sitemap_parser.clear_cache()


# =============================================================================
# Global Instance
# =============================================================================

_robots_manager: RobotsManager | None = None


def get_robots_manager() -> RobotsManager:
    """Get or create global RobotsManager instance.

    Returns:
        RobotsManager instance.
    """
    global _robots_manager
    if _robots_manager is None:
        _robots_manager = RobotsManager()
    return _robots_manager


# =============================================================================
# MCP Tool Integration
# =============================================================================


async def check_robots_compliance(url: str) -> dict[str, Any]:
    """Check URL compliance with robots.txt (for MCP tool use).

    Args:
        url: URL to check.

    Returns:
        Compliance check result.
    """
    manager = get_robots_manager()

    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    can_fetch = await manager.can_fetch(url)
    delay = await manager.get_effective_delay(domain)
    robots_info = await manager.get_robots_info(domain)

    return {
        "url": url,
        "domain": domain,
        "allowed": can_fetch,
        "effective_delay": delay,
        "robots_info": robots_info,
    }


async def get_sitemap_urls(
    domain: str,
    limit: int = 50,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Get URLs from domain sitemap (for MCP tool use).

    Args:
        domain: Domain name.
        limit: Maximum URLs.
        keywords: Optional filter keywords.

    Returns:
        Sitemap extraction result.
    """
    manager = get_robots_manager()

    priority_urls = await manager.get_priority_urls(domain, limit)

    # Filter by keywords if provided
    if keywords:
        keywords_lower = [k.lower() for k in keywords]
        priority_urls = [
            (url, score)
            for url, score in priority_urls
            if any(kw in url.lower() for kw in keywords_lower)
        ]

    return {
        "domain": domain,
        "urls": [{"url": url, "score": score} for url, score in priority_urls],
        "total": len(priority_urls),
    }
