"""
Site-internal search UI automation for Lancet.

Implements automated interaction with site-internal search forms (§3.1.5):
- Allowlist-based domain management for stable internal search UIs
- Automatic form detection and interaction
- Result extraction and link prioritization
- Fallback to site: operator search on failure
- Success/harvest rate learning for domain policy

References:
- §3.1.5: Site Internal Search UI Automation (allowlist operation)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import yaml

from src.crawler.bfs import LinkExtractor
from src.storage.database import get_database
from src.utils.config import get_project_root, get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SearchTemplate:
    """Template for site-internal search UI."""

    domain: str
    search_input: str  # CSS selector for search input
    search_button: str | None = None  # CSS selector for submit button (None = Enter)
    results_selector: str | None = None  # CSS selector for result items
    link_selector: str | None = None  # CSS selector for links within results
    wait_for: str | None = None  # CSS selector to wait for after search

    @classmethod
    def from_dict(cls, domain: str, data: dict) -> "SearchTemplate":
        """Create from dictionary."""
        return cls(
            domain=data.get("domain", domain),
            search_input=data.get("search_input", "input[type='search'], input[type='text']"),
            search_button=data.get("search_button"),
            results_selector=data.get("results_selector"),
            link_selector=data.get("link_selector", "a"),
            wait_for=data.get("wait_for"),
        )


@dataclass
class SiteSearchResult:
    """Result of site-internal search."""

    domain: str
    query: str
    success: bool
    result_urls: list[str] = field(default_factory=list)
    result_count: int = 0
    method: str = "site_search"  # site_search or fallback
    error: str | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "query": self.query,
            "success": self.success,
            "result_urls": self.result_urls,
            "result_count": self.result_count,
            "method": self.method,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class DomainSearchStats:
    """Statistics for site search on a domain."""

    domain: str
    total_attempts: int = 0
    successful_attempts: int = 0
    total_results: int = 0
    consecutive_failures: int = 0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    skip_until: datetime | None = None

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_attempts == 0:
            return 0.0
        return self.successful_attempts / self.total_attempts

    @property
    def harvest_rate(self) -> float:
        """Calculate average results per successful search."""
        if self.successful_attempts == 0:
            return 0.0
        return self.total_results / self.successful_attempts

    def is_skipped(self) -> bool:
        """Check if domain is temporarily skipped."""
        if self.skip_until is None:
            return False
        return datetime.now(UTC) < self.skip_until

    def record_success(self, result_count: int) -> None:
        """Record successful search."""
        self.total_attempts += 1
        self.successful_attempts += 1
        self.total_results += result_count
        self.consecutive_failures = 0
        self.last_success_at = datetime.now(UTC)

    def record_failure(self) -> None:
        """Record failed search."""
        self.total_attempts += 1
        self.consecutive_failures += 1
        self.last_failure_at = datetime.now(UTC)

        # Skip domain after 2 consecutive failures (§3.1.5)
        if self.consecutive_failures >= 2:
            # Skip for rest of day
            now = datetime.now(UTC)
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            self.skip_until = tomorrow
            logger.warning(
                "Domain site search skipped due to consecutive failures",
                domain=self.domain,
                failures=self.consecutive_failures,
                skip_until=self.skip_until.isoformat(),
            )


# =============================================================================
# Site Search Manager
# =============================================================================

class SiteSearchManager:
    """Manages site-internal search operations.

    Features:
    - Allowlist management from config
    - Template-based form interaction
    - Fallback to site: operator search
    - Success/harvest rate tracking
    - Automatic skip on consecutive failures
    - DomainPolicyManager integration for QPS settings
    """

    def __init__(self):
        from src.utils.domain_policy import get_domain_policy_manager

        self._settings = get_settings()
        self._templates: dict[str, SearchTemplate] = {}
        self._stats: dict[str, DomainSearchStats] = {}
        self._last_search: dict[str, float] = {}  # domain -> timestamp
        self._lock = asyncio.Lock()
        self._link_extractor = LinkExtractor()

        # Get QPS settings from DomainPolicyManager
        policy_manager = get_domain_policy_manager()
        self._site_search_qps = policy_manager.get_site_search_qps()
        self._min_interval = policy_manager.get_site_search_min_interval()

        # Load templates from config
        self._load_templates()

    @property
    def site_search_qps(self) -> float:
        """Get site search QPS from config."""
        return self._site_search_qps

    @property
    def min_interval(self) -> float:
        """Get minimum interval between site searches."""
        return self._min_interval

    def _load_templates(self) -> None:
        """Load search templates from config file."""
        config_path = get_project_root() / "config" / "domains.yaml"

        if not config_path.exists():
            logger.warning("domains.yaml not found", path=str(config_path))
            return

        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)

            templates = config.get("internal_search_templates", {})

            for name, data in templates.items():
                domain = data.get("domain", name)
                self._templates[domain] = SearchTemplate.from_dict(domain, data)
                logger.debug("Loaded search template", domain=domain)

            logger.info(
                "Loaded site search templates",
                count=len(self._templates),
            )

        except Exception as e:
            logger.error("Failed to load search templates", error=str(e))

    def is_allowlisted(self, domain: str) -> bool:
        """Check if domain has allowlisted internal search.

        Args:
            domain: Domain name.

        Returns:
            True if domain has a search template.
        """
        return domain in self._templates

    def get_template(self, domain: str) -> SearchTemplate | None:
        """Get search template for domain.

        Args:
            domain: Domain name.

        Returns:
            SearchTemplate or None.
        """
        return self._templates.get(domain)

    def get_stats(self, domain: str) -> DomainSearchStats:
        """Get or create stats for domain.

        Args:
            domain: Domain name.

        Returns:
            DomainSearchStats instance.
        """
        if domain not in self._stats:
            self._stats[domain] = DomainSearchStats(domain=domain)
        return self._stats[domain]

    async def can_search(self, domain: str) -> bool:
        """Check if site search is available for domain.

        Considers allowlist, skip status, and rate limiting.

        Args:
            domain: Domain name.

        Returns:
            True if search can proceed.
        """
        # Check allowlist
        if not self.is_allowlisted(domain):
            return False

        # Check skip status
        stats = self.get_stats(domain)
        if stats.is_skipped():
            logger.debug(
                "Domain site search skipped",
                domain=domain,
                skip_until=stats.skip_until.isoformat() if stats.skip_until else None,
            )
            return False

        return True

    async def search(
        self,
        domain: str,
        query: str,
        browser_context=None,
        fallback_to_site: bool = True,
    ) -> SiteSearchResult:
        """Execute site-internal search.

        Args:
            domain: Target domain.
            query: Search query.
            browser_context: Playwright browser context (optional).
            fallback_to_site: Fall back to site: operator on failure.

        Returns:
            SiteSearchResult with found URLs.
        """
        start_time = asyncio.get_running_loop().time()
        result = SiteSearchResult(domain=domain, query=query, success=False)

        # Check if search is available
        if not await self.can_search(domain):
            if fallback_to_site:
                return await self._fallback_search(domain, query)
            result.error = "site_search_not_available"
            return result

        # Rate limiting
        await self._wait_for_rate_limit(domain)

        template = self.get_template(domain)
        stats = self.get_stats(domain)

        try:
            if browser_context:
                # Browser-based search
                result = await self._browser_search(
                    domain, query, template, browser_context,
                )
            else:
                # HTTP-based search (if possible)
                result = await self._http_search(domain, query, template)

            # Update stats
            if result.success:
                stats.record_success(result.result_count)
                await self._update_domain_policy(domain, stats)
            else:
                stats.record_failure()
                await self._update_domain_policy(domain, stats)

                # Fallback if enabled
                if fallback_to_site and not result.success:
                    fallback_result = await self._fallback_search(domain, query)
                    if fallback_result.success:
                        return fallback_result

        except Exception as e:
            logger.error(
                "Site search error",
                domain=domain,
                query=query[:50],
                error=str(e),
            )
            stats.record_failure()
            result.error = str(e)

            if fallback_to_site:
                return await self._fallback_search(domain, query)

        result.duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)
        return result

    async def _wait_for_rate_limit(self, domain: str) -> None:
        """Wait for rate limit if needed."""
        async with self._lock:
            last = self._last_search.get(domain, 0)
            elapsed = asyncio.get_running_loop().time() - last
            wait_time = max(0, self._min_interval - elapsed)

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            self._last_search[domain] = asyncio.get_running_loop().time()

    async def _browser_search(
        self,
        domain: str,
        query: str,
        template: SearchTemplate,
        context,
    ) -> SiteSearchResult:
        """Execute search using browser automation.

        Args:
            domain: Target domain.
            query: Search query.
            template: Search template.
            context: Playwright browser context.

        Returns:
            SiteSearchResult.
        """
        result = SiteSearchResult(domain=domain, query=query, success=False, method="site_search")

        page = await context.new_page()

        try:
            # Navigate to domain
            search_url = f"https://{domain}/"
            await page.goto(search_url, timeout=30000)

            # Find and fill search input
            search_input = await page.wait_for_selector(
                template.search_input,
                timeout=10000,
            )

            if not search_input:
                result.error = "search_input_not_found"
                return result

            await search_input.fill(query)

            # Submit search
            if template.search_button:
                submit_btn = await page.query_selector(template.search_button)
                if submit_btn:
                    await submit_btn.click()
                else:
                    await search_input.press("Enter")
            else:
                await search_input.press("Enter")

            # Wait for results
            if template.wait_for:
                await page.wait_for_selector(template.wait_for, timeout=15000)
            else:
                await page.wait_for_load_state("networkidle", timeout=15000)

            # Extract results
            html = await page.content()
            urls = self._extract_result_urls(html, domain, template)

            result.success = True
            result.result_urls = urls
            result.result_count = len(urls)

            logger.info(
                "Site search completed",
                domain=domain,
                query=query[:50],
                results=len(urls),
            )

        except Exception as e:
            logger.warning(
                "Browser search failed",
                domain=domain,
                error=str(e),
            )
            result.error = str(e)

            # Check for CAPTCHA/login wall
            if await self._detect_challenge(page):
                result.error = "challenge_detected"

        finally:
            await page.close()

        return result

    async def _http_search(
        self,
        domain: str,
        query: str,
        template: SearchTemplate,
    ) -> SiteSearchResult:
        """Execute search using HTTP requests (limited support).

        Most sites require JavaScript, so this is often a fallback.

        Args:
            domain: Target domain.
            query: Search query.
            template: Search template.

        Returns:
            SiteSearchResult.
        """
        result = SiteSearchResult(domain=domain, query=query, success=False, method="site_search")

        # Try common search URL patterns
        search_patterns = [
            f"https://{domain}/search?q={quote_plus(query)}",
            f"https://{domain}/search?query={quote_plus(query)}",
            f"https://{domain}/?s={quote_plus(query)}",
        ]

        try:
            from curl_cffi import requests as curl_requests

            for search_url in search_patterns:
                response = curl_requests.get(
                    search_url,
                    timeout=15,
                    impersonate="chrome",
                    headers={
                        "Accept": "text/html",
                        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                    },
                )

                if response.status_code == 200:
                    urls = self._extract_result_urls(
                        response.text, domain, template,
                    )

                    if urls:
                        result.success = True
                        result.result_urls = urls
                        result.result_count = len(urls)
                        return result

            result.error = "no_results_found"

        except Exception as e:
            result.error = str(e)

        return result

    async def _fallback_search(
        self,
        domain: str,
        query: str,
    ) -> SiteSearchResult:
        """Fallback to site: operator search via search engines.

        Args:
            domain: Target domain.
            query: Search query.

        Returns:
            SiteSearchResult with fallback results.
        """
        result = SiteSearchResult(
            domain=domain,
            query=query,
            success=False,
            method="fallback",
        )

        try:
            # Import search module for site: query
            from src.search.client import search_serp

            site_query = f"site:{domain} {query}"

            serp_results = await search_serp(
                query=site_query,
                engines=["duckduckgo", "qwant"],
                limit=20,
            )

            if serp_results.get("ok"):
                urls = [
                    item["url"]
                    for item in serp_results.get("results", [])
                    if domain in item.get("url", "")
                ]

                result.success = len(urls) > 0
                result.result_urls = urls
                result.result_count = len(urls)

                logger.info(
                    "Fallback search completed",
                    domain=domain,
                    query=query[:50],
                    results=len(urls),
                )

        except Exception as e:
            logger.warning("Fallback search failed", domain=domain, error=str(e))
            result.error = str(e)

        return result

    def _extract_result_urls(
        self,
        html: str,
        domain: str,
        template: SearchTemplate,
    ) -> list[str]:
        """Extract result URLs from search results page.

        Args:
            html: Search results HTML.
            domain: Target domain.
            template: Search template.

        Returns:
            List of result URLs.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        urls = []
        seen = set()

        # Find result containers if specified
        if template.results_selector:
            containers = soup.select(template.results_selector)
        else:
            containers = [soup]

        # Extract links from containers
        link_selector = template.link_selector or "a"

        for container in containers:
            for link in container.select(link_selector):
                href = link.get("href")
                if not href:
                    continue

                # Resolve relative URLs
                absolute_url = urljoin(f"https://{domain}/", href)

                # Filter to same domain
                parsed = urlparse(absolute_url)
                if parsed.netloc.lower() != domain.lower():
                    continue

                # Skip duplicates
                if absolute_url in seen:
                    continue
                seen.add(absolute_url)

                # Skip common non-content URLs
                if any(x in absolute_url.lower() for x in [
                    "/search", "/login", "/register", "/tag/", "/category/"
                ]):
                    continue

                urls.append(absolute_url)

        return urls[:50]  # Limit results

    async def _detect_challenge(self, page) -> bool:
        """Detect CAPTCHA or login wall.

        Args:
            page: Playwright page.

        Returns:
            True if challenge detected.
        """
        try:
            content = await page.content()
            content_lower = content.lower()

            challenge_indicators = [
                "captcha", "recaptcha", "hcaptcha", "turnstile",
                "login", "sign in", "ログイン",
            ]

            return any(ind in content_lower for ind in challenge_indicators)

        except Exception as e:
            logger.debug("Challenge page detection failed", error=str(e))
            return False

    async def _update_domain_policy(
        self,
        domain: str,
        stats: DomainSearchStats,
    ) -> None:
        """Update domain policy with search statistics.

        Args:
            domain: Domain name.
            stats: Current statistics.
        """
        try:
            db = await get_database()

            # Update or insert domain record
            await db.execute("""
                INSERT INTO domains (domain, internal_search_success_rate, internal_search_harvest_rate)
                VALUES (?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    internal_search_success_rate = excluded.internal_search_success_rate,
                    internal_search_harvest_rate = excluded.internal_search_harvest_rate
            """, (domain, stats.success_rate, stats.harvest_rate))

        except Exception as e:
            logger.debug(
                "Failed to update domain policy",
                domain=domain,
                error=str(e),
            )


# =============================================================================
# Global Instance
# =============================================================================

_site_search_manager: SiteSearchManager | None = None


def get_site_search_manager() -> SiteSearchManager:
    """Get or create global SiteSearchManager instance.

    Returns:
        SiteSearchManager instance.
    """
    global _site_search_manager
    if _site_search_manager is None:
        _site_search_manager = SiteSearchManager()
    return _site_search_manager


# =============================================================================
# MCP Tool Integration
# =============================================================================

async def site_search(
    domain: str,
    query: str,
    use_browser: bool = False,
    fallback: bool = True,
) -> dict[str, Any]:
    """Execute site-internal search (for MCP tool use).

    Args:
        domain: Target domain.
        query: Search query.
        use_browser: Use browser automation.
        fallback: Fall back to site: operator on failure.

    Returns:
        Search result dictionary.
    """
    manager = get_site_search_manager()

    # Note: Browser-based site search requires a Playwright context to be passed
    # from the caller. This MCP tool entry point doesn't have direct access to
    # the browser context, so we always use HTTP-based search with site: fallback.
    if use_browser:
        logger.warning(
            "Browser-based site search requested but no context available, "
            "falling back to HTTP-based search",
            domain=domain,
        )

    result = await manager.search(
        domain,
        query,
        browser_context=None,  # Browser context must be passed by caller with browser access
        fallback_to_site=fallback,
    )

    return result.to_dict()


async def get_site_search_stats(domain: str) -> dict[str, Any]:
    """Get site search statistics for domain (for MCP tool use).

    Args:
        domain: Domain name.

    Returns:
        Statistics dictionary.
    """
    manager = get_site_search_manager()

    is_allowlisted = manager.is_allowlisted(domain)
    stats = manager.get_stats(domain) if is_allowlisted else None
    template = manager.get_template(domain)

    return {
        "domain": domain,
        "is_allowlisted": is_allowlisted,
        "has_template": template is not None,
        "template": {
            "search_input": template.search_input,
            "search_button": template.search_button,
            "results_selector": template.results_selector,
        } if template else None,
        "stats": {
            "total_attempts": stats.total_attempts,
            "successful_attempts": stats.successful_attempts,
            "success_rate": stats.success_rate,
            "harvest_rate": stats.harvest_rate,
            "consecutive_failures": stats.consecutive_failures,
            "is_skipped": stats.is_skipped(),
            "skip_until": stats.skip_until.isoformat() if stats.skip_until else None,
        } if stats else None,
    }


async def list_allowlisted_domains() -> dict[str, Any]:
    """List all allowlisted domains for site search (for MCP tool use).

    Returns:
        Dictionary with domain list.
    """
    manager = get_site_search_manager()

    domains = []
    for domain, _template in manager._templates.items():
        stats = manager.get_stats(domain)
        domains.append({
            "domain": domain,
            "success_rate": stats.success_rate,
            "harvest_rate": stats.harvest_rate,
            "is_skipped": stats.is_skipped(),
        })

    return {
        "domains": domains,
        "total": len(domains),
    }

