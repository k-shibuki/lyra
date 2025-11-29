"""
Browser-based Search Provider for Lancet.

Implements direct browser-based search using Playwright
for improved resilience and session management.

Design Philosophy:
- Uses same browser profile as content fetching (consistent fingerprint)
- Supports CAPTCHA detection and InterventionManager integration
- Session cookies are preserved for subsequent searches
- Parsers are externalized for easy maintenance

References:
- §3.2 (Browser automation)
- §3.6.1 (Authentication queue)
- §4.3 (Stealth requirements)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

from src.search.parser_config import get_parser_config_manager
from src.search.provider import (
    BaseSearchProvider,
    HealthState,
    HealthStatus,
    SearchOptions,
    SearchResponse,
    SearchResult,
)
from src.search.search_parsers import (
    ParseResult,
    get_parser,
    get_available_parsers,
)
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class BrowserSearchSession:
    """Session data for browser-based search."""
    
    engine: str
    cookies: list[dict[str, Any]]
    last_used: float
    captcha_count: int = 0
    success_count: int = 0
    
    def is_fresh(self, max_age_seconds: float = 3600.0) -> bool:
        """Check if session is still fresh."""
        return (time.time() - self.last_used) < max_age_seconds
    
    def record_success(self) -> None:
        """Record successful search."""
        self.success_count += 1
        self.last_used = time.time()
    
    def record_captcha(self) -> None:
        """Record CAPTCHA encounter."""
        self.captcha_count += 1
        self.last_used = time.time()


# =============================================================================
# Browser Search Provider
# =============================================================================


class BrowserSearchProvider(BaseSearchProvider):
    """
    Browser-based search provider using Playwright.
    
    Executes searches directly in browser, maintaining consistent
    fingerprint and session across search and fetch stages.
    
    Features:
    - Direct browser search via Playwright
    - Cookie/fingerprint consistency
    - CAPTCHA detection and intervention queue integration
    - Session preservation across searches
    - Multiple search engine support (DuckDuckGo, Mojeek, etc.)
    
    Example:
        provider = BrowserSearchProvider()
        response = await provider.search("AI regulations", SearchOptions(language="ja"))
        if response.ok:
            for result in response.results:
                print(result.title, result.url)
        await provider.close()
    """
    
    DEFAULT_ENGINE = "duckduckgo"
    DEFAULT_TIMEOUT = 30
    MIN_INTERVAL = 2.0  # Minimum seconds between searches
    
    def __init__(
        self,
        default_engine: str | None = None,
        timeout: int | None = None,
        min_interval: float | None = None,
    ):
        """
        Initialize browser search provider.
        
        Args:
            default_engine: Default search engine to use.
            timeout: Search timeout in seconds.
            min_interval: Minimum interval between searches.
        """
        super().__init__("browser_search")
        
        self._settings = get_settings()
        self._default_engine = default_engine or self.DEFAULT_ENGINE
        self._timeout = timeout or self.DEFAULT_TIMEOUT
        self._min_interval = min_interval or self.MIN_INTERVAL
        
        # Browser state (lazy initialization)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        
        # Rate limiting
        self._rate_limiter = asyncio.Semaphore(1)
        self._last_search_time = 0.0
        
        # Session management
        self._sessions: dict[str, BrowserSearchSession] = {}
        
        # Health metrics
        self._success_count = 0
        self._failure_count = 0
        self._captcha_count = 0
        self._total_latency = 0.0
        self._last_error: str | None = None
    
    async def _ensure_browser(self) -> None:
        """Ensure browser is initialized."""
        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright
                
                self._playwright = await async_playwright().start()
                
                # Try CDP connection to Windows Chrome first
                chrome_host = getattr(self._settings.browser, "chrome_host", "localhost")
                chrome_port = getattr(self._settings.browser, "chrome_port", 9222)
                cdp_url = f"http://{chrome_host}:{chrome_port}"
                
                try:
                    self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                    logger.info("Connected to Chrome via CDP", url=cdp_url)
                except Exception as e:
                    logger.warning(
                        "CDP connection failed, launching browser",
                        error=str(e),
                    )
                    self._browser = await self._playwright.chromium.launch(
                        headless=True,
                    )
                
                # Create context with realistic settings
                self._context = await self._browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    locale="ja-JP",
                    timezone_id="Asia/Tokyo",
                    user_agent=self._get_user_agent(),
                )
                
                # Block unnecessary resources
                await self._context.route(
                    "**/*.{png,jpg,jpeg,gif,svg,webp,mp4,webm,mp3,woff,woff2}",
                    lambda route: route.abort(),
                )
                
            except Exception as e:
                logger.error("Failed to initialize browser", error=str(e))
                raise
    
    def _get_user_agent(self) -> str:
        """Get user agent string matching Windows Chrome."""
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    
    async def _get_page(self) -> Any:
        """Get or create a browser page."""
        await self._ensure_browser()
        
        if self._page is None or self._page.is_closed():
            self._page = await self._context.new_page()
        
        return self._page
    
    async def _rate_limit(self) -> None:
        """Apply rate limiting between searches."""
        async with self._rate_limiter:
            elapsed = time.time() - self._last_search_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_search_time = time.time()
    
    async def search(
        self,
        query: str,
        options: SearchOptions | None = None,
    ) -> SearchResponse:
        """
        Execute a search using browser.
        
        Args:
            query: Search query text.
            options: Search options.
            
        Returns:
            SearchResponse with results or error.
        """
        self._check_closed()
        
        if options is None:
            options = SearchOptions()
        
        # Determine engine to use
        engine = self._default_engine
        if options.engines:
            engine = options.engines[0]
        
        start_time = time.time()
        
        try:
            await self._rate_limit()
            
            # Get parser for engine
            parser = get_parser(engine)
            if parser is None:
                return SearchResponse(
                    results=[],
                    query=query,
                    provider=self.name,
                    error=f"No parser available for engine: {engine}",
                    elapsed_ms=(time.time() - start_time) * 1000,
                )
            
            # Build search URL
            search_url = parser.build_search_url(
                query=query,
                time_range=options.time_range,
            )
            
            logger.debug(
                "Browser search",
                engine=engine,
                query=query[:50],
                url=search_url[:100],
            )
            
            # Execute search
            page = await self._get_page()
            
            # Navigate to search page
            response = await page.goto(
                search_url,
                timeout=self._timeout * 1000,
                wait_until="domcontentloaded",
            )
            
            # Wait for content to load (with fallback for JS-heavy sites)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                # Some engines (e.g., Brave) have constant JS activity
                # Fall back to a short fixed wait
                await asyncio.sleep(2)
            
            # Get HTML content
            html = await page.content()
            
            # Parse results
            parse_result = parser.parse(html, query)
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Handle CAPTCHA
            if parse_result.is_captcha:
                self._captcha_count += 1
                self._record_session_captcha(engine)
                
                # Trigger intervention queue
                intervention_result = await self._request_intervention(
                    url=search_url,
                    engine=engine,
                    captcha_type=parse_result.captcha_type,
                    page=page,
                )
                
                if intervention_result:
                    # Retry after intervention
                    html = await page.content()
                    parse_result = parser.parse(html, query)
                else:
                    return SearchResponse(
                        results=[],
                        query=query,
                        provider=self.name,
                        error=f"CAPTCHA detected: {parse_result.captcha_type}",
                        elapsed_ms=elapsed_ms,
                    )
            
            # Handle parse failure
            if not parse_result.ok:
                self._failure_count += 1
                self._last_error = parse_result.error
                
                error_msg = parse_result.error or "Parse failed"
                if parse_result.selector_errors:
                    error_msg += f" ({len(parse_result.selector_errors)} selector errors)"
                if parse_result.html_saved_path:
                    error_msg += f" [HTML saved: {parse_result.html_saved_path}]"
                
                logger.error(
                    "Search parse failed",
                    engine=engine,
                    query=query[:50],
                    error=error_msg,
                )
                
                return SearchResponse(
                    results=[],
                    query=query,
                    provider=self.name,
                    error=error_msg,
                    elapsed_ms=elapsed_ms,
                )
            
            # Convert results
            results = [
                r.to_search_result(engine)
                for r in parse_result.results[:options.limit]
            ]
            
            # Save session cookies
            await self._save_session(engine, page)
            
            self._success_count += 1
            self._total_latency += elapsed_ms
            
            logger.info(
                "Browser search completed",
                engine=engine,
                query=query[:50],
                result_count=len(results),
                elapsed_ms=round(elapsed_ms, 1),
            )
            
            return SearchResponse(
                results=results,
                query=query,
                provider=self.name,
                total_count=len(parse_result.results),
                elapsed_ms=elapsed_ms,
            )
            
        except asyncio.TimeoutError:
            self._failure_count += 1
            self._last_error = "Timeout"
            elapsed_ms = (time.time() - start_time) * 1000
            
            logger.error("Browser search timeout", engine=engine, query=query[:50])
            
            return SearchResponse(
                results=[],
                query=query,
                provider=self.name,
                error="Timeout",
                elapsed_ms=elapsed_ms,
            )
            
        except Exception as e:
            self._failure_count += 1
            self._last_error = str(e)
            elapsed_ms = (time.time() - start_time) * 1000
            
            logger.error(
                "Browser search error",
                engine=engine,
                query=query[:50],
                error=str(e),
            )
            
            return SearchResponse(
                results=[],
                query=query,
                provider=self.name,
                error=str(e),
                elapsed_ms=elapsed_ms,
            )
    
    async def _request_intervention(
        self,
        url: str,
        engine: str,
        captcha_type: str | None,
        page: Any,
    ) -> bool:
        """
        Request manual intervention for CAPTCHA.
        
        Returns True if intervention succeeded.
        """
        try:
            from src.utils.notification import (
                InterventionType,
                InterventionStatus,
                get_intervention_manager,
            )
            
            intervention_manager = get_intervention_manager()
            
            # Map captcha type to intervention type
            type_map = {
                "recaptcha": InterventionType.CAPTCHA,
                "turnstile": InterventionType.TURNSTILE,
                "ddg_challenge": InterventionType.JS_CHALLENGE,
                "verification": InterventionType.CAPTCHA,
                "rate_limit": InterventionType.CLOUDFLARE,
                "blocked": InterventionType.CLOUDFLARE,
            }
            
            intervention_type = type_map.get(
                captcha_type or "",
                InterventionType.CAPTCHA,
            )
            
            # Request intervention
            result = await intervention_manager.request_intervention(
                intervention_type=intervention_type,
                url=url,
                domain=engine,
                message=f"CAPTCHA detected on {engine} search",
                page=page,
            )
            
            # Check if resolved
            return result.status == InterventionStatus.SUCCESS
            
        except ImportError:
            logger.warning("InterventionManager not available")
            return False
        except Exception as e:
            logger.error("Intervention request failed", error=str(e))
            return False
    
    async def _save_session(self, engine: str, page: Any) -> None:
        """Save session cookies for engine."""
        try:
            cookies = await self._context.cookies()
            
            self._sessions[engine] = BrowserSearchSession(
                engine=engine,
                cookies=[dict(c) for c in cookies],
                last_used=time.time(),
            )
            self._sessions[engine].record_success()
            
        except Exception as e:
            logger.debug("Failed to save session", error=str(e))
    
    def _record_session_captcha(self, engine: str) -> None:
        """Record CAPTCHA for engine session."""
        if engine in self._sessions:
            self._sessions[engine].record_captcha()
    
    def get_session(self, engine: str) -> BrowserSearchSession | None:
        """Get session for engine."""
        session = self._sessions.get(engine)
        if session and session.is_fresh():
            return session
        return None
    
    async def get_health(self) -> HealthStatus:
        """
        Get current health status.
        
        Returns:
            HealthStatus based on recent metrics.
        """
        if self._is_closed:
            return HealthStatus.unhealthy("Provider closed")
        
        total = self._success_count + self._failure_count
        
        if total == 0:
            return HealthStatus(
                state=HealthState.UNKNOWN,
                message="No searches made yet",
            )
        
        success_rate = self._success_count / total
        avg_latency = self._total_latency / total if total > 0 else 0
        
        # Factor in CAPTCHA rate
        captcha_rate = self._captcha_count / total if total > 0 else 0
        
        if success_rate >= 0.9 and captcha_rate < 0.1:
            return HealthStatus.healthy(latency_ms=avg_latency)
        elif success_rate >= 0.5:
            message = self._last_error
            if captcha_rate >= 0.2:
                message = f"High CAPTCHA rate: {captcha_rate:.0%}"
            return HealthStatus.degraded(
                success_rate=success_rate,
                message=message,
            )
        else:
            return HealthStatus.unhealthy(message=self._last_error)
    
    async def close(self) -> None:
        """Close browser and cleanup."""
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
            
            if self._context:
                await self._context.close()
            
            if self._browser:
                await self._browser.close()
            
            if self._playwright:
                await self._playwright.stop()
                
        except Exception as e:
            logger.warning("Error during browser cleanup", error=str(e))
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
        
        await super().close()
    
    def reset_metrics(self) -> None:
        """Reset health metrics. For testing purposes."""
        self._success_count = 0
        self._failure_count = 0
        self._captcha_count = 0
        self._total_latency = 0.0
        self._last_error = None
    
    def get_available_engines(self) -> list[str]:
        """Get list of available search engines."""
        return get_available_parsers()
    
    def get_stats(self) -> dict[str, Any]:
        """Get provider statistics."""
        total = self._success_count + self._failure_count
        return {
            "provider": self.name,
            "default_engine": self._default_engine,
            "available_engines": self.get_available_engines(),
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "captcha_count": self._captcha_count,
            "success_rate": self._success_count / total if total > 0 else 0,
            "captcha_rate": self._captcha_count / total if total > 0 else 0,
            "avg_latency_ms": self._total_latency / total if total > 0 else 0,
            "active_sessions": len(self._sessions),
            "last_error": self._last_error,
        }


# =============================================================================
# Factory Functions
# =============================================================================


_default_provider: BrowserSearchProvider | None = None


def get_browser_search_provider() -> BrowserSearchProvider:
    """
    Get or create the default BrowserSearchProvider instance.
    
    Returns:
        BrowserSearchProvider singleton instance.
    """
    global _default_provider
    if _default_provider is None:
        _default_provider = BrowserSearchProvider()
    return _default_provider


async def cleanup_browser_search_provider() -> None:
    """
    Close and cleanup the default BrowserSearchProvider.
    
    Used for testing cleanup and graceful shutdown.
    """
    global _default_provider
    if _default_provider is not None:
        await _default_provider.close()
        _default_provider = None


def reset_browser_search_provider() -> None:
    """
    Reset the default provider. For testing purposes only.
    """
    global _default_provider
    _default_provider = None

