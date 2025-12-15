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
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

from src.search.circuit_breaker import check_engine_available, record_engine_result
from src.search.engine_config import get_engine_config_manager
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
from src.search.search_api import transform_query_for_engine
from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.crawler.fetcher import HumanBehavior

logger = get_logger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class CDPConnectionError(Exception):
    """
    Raised when CDP connection to Chrome fails.
    
    This indicates Chrome is not running with remote debugging enabled.
    Per spec (§4.3.3), headless fallback is not supported.
    """
    pass


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
        self._last_search_times: dict[str, float] = {}  # Per-engine tracking
        
        # Session management
        self._sessions: dict[str, BrowserSearchSession] = {}
        
        # CDP connection state
        self._cdp_connected = False
        
        # Health metrics
        self._success_count = 0
        self._failure_count = 0
        self._captcha_count = 0
        self._total_latency = 0.0
        self._last_error: str | None = None
        
        # Human behavior simulation
        self._human_behavior = HumanBehavior()
    
    async def _ensure_browser(self) -> None:
        """
        Ensure browser is initialized via CDP connection.
        
        Per spec (§3.2, §4.3.3), CDP connection to real Chrome profile is required.
        Headless fallback is not supported as it violates the "real profile consistency" principle.
        
        Raises:
            CDPConnectionError: If CDP connection fails (Chrome not running or not accessible).
        """
        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright
                
                self._playwright = await async_playwright().start()
                
                # CDP connection to Chrome (required, no fallback)
                chrome_host = getattr(self._settings.browser, "chrome_host", "localhost")
                chrome_port = getattr(self._settings.browser, "chrome_port", 9222)
                cdp_url = f"http://{chrome_host}:{chrome_port}"
                
                try:
                    self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                    self._cdp_connected = True
                    logger.info("Connected to Chrome via CDP", url=cdp_url)
                except Exception as e:
                    # CDP connection failed - do NOT fall back to headless
                    # Per spec: "real profile consistency" is required
                    self._cdp_connected = False
                    await self._playwright.stop()
                    self._playwright = None
                    
                    raise CDPConnectionError(
                        f"CDP connection failed: {e}. "
                        f"Start Chrome with: ./scripts/chrome.sh start"
                    ) from e
                
                # Reuse existing context if available (preserves profile cookies per §3.6.1)
                existing_contexts = self._browser.contexts
                if existing_contexts:
                    self._context = existing_contexts[0]
                    logger.info(
                        "Reusing existing browser context for cookie preservation",
                        context_count=len(existing_contexts),
                    )
                else:
                    # Create new context only if no existing context
                    self._context = await self._browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        locale="ja-JP",
                        timezone_id="Asia/Tokyo",
                        user_agent=self._get_user_agent(),
                    )
                    logger.info("Created new browser context")
                
                # Block unnecessary resources
                await self._context.route(
                    "**/*.{png,jpg,jpeg,gif,svg,webp,mp4,webm,mp3,woff,woff2}",
                    lambda route: route.abort(),
                )
                
                # Perform profile health audit on browser session initialization
                # Only audit when new context is created (not when reusing existing context)
                if not existing_contexts:
                    await self._perform_health_audit()
                
            except CDPConnectionError:
                raise
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
    
    async def _perform_health_audit(self) -> None:
        """Perform profile health audit on browser session initialization.
        
        Per high-frequency check requirement: Execute audit at browser session
        initialization to detect drift in UA, fonts, language, timezone, canvas, audio.
        """
        try:
            from src.crawler.profile_audit import perform_health_check, AuditStatus
            
            # Create temporary page for audit (minimal impact on performance)
            page = await self._context.new_page()
            try:
                await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
                
                # Perform health check with auto-repair enabled
                audit_result = await perform_health_check(
                    page,
                    force=False,
                    auto_repair=True,
                )
                
                if audit_result.status == AuditStatus.DRIFT:
                    logger.warning(
                        "Profile drift detected and repaired",
                        drifts=[d.attribute for d in audit_result.drifts],
                        repair_status=audit_result.repair_status.value,
                    )
                elif audit_result.status == AuditStatus.FAIL:
                    logger.warning(
                        "Profile health audit failed",
                        error=audit_result.error,
                    )
                else:
                    logger.debug(
                        "Profile health check passed",
                        status=audit_result.status.value,
                    )
            finally:
                await page.close()
        except Exception as e:
            # Non-blocking: Log error but continue with normal flow
            logger.warning(
                "Profile health audit error (non-blocking)",
                error=str(e),
            )
    
    async def _get_page(self) -> Any:
        """Get or create a browser page."""
        await self._ensure_browser()
        
        if self._page is None or self._page.is_closed():
            self._page = await self._context.new_page()
        
        return self._page
    
    async def _rate_limit(self, engine: str | None = None) -> None:
        """Apply rate limiting between searches (per-engine QPS).
        
        Per spec §3.1: "Engine-specific rate control (concurrency=1, strict QPS)"
        Per spec §4.3: "Engine QPS≤0.25, concurrency=1"
        
        Args:
            engine: Engine name for per-engine rate limiting.
                   If None, uses default interval for backward compatibility.
        """
        # Get engine-specific interval from config
        min_interval = self._min_interval  # Default fallback
        
        if engine:
            engine_config = get_engine_config_manager().get_engine(engine)
            if engine_config:
                min_interval = engine_config.min_interval
        
        async with self._rate_limiter:
            # Track per-engine last search time
            engine_key = engine or "default"
            last_time = self._last_search_times.get(engine_key, 0.0)
            
            elapsed = time.time() - last_time
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            
            self._last_search_times[engine_key] = time.time()
            # Also update shared time for backward compatibility
            self._last_search_time = time.time()
    
    def _detect_category(self, query: str) -> str:
        """Detect query category based on keywords.
        
        Simple keyword-based category detection. Categories:
        - academic: research papers, academic sources
        - news: current events, news articles
        - government: government sources, official documents
        - technical: technical documentation, code, APIs
        - general: default category
        
        Args:
            query: Search query text.
            
        Returns:
            Category name: "general", "academic", "news", "government", or "technical".
        """
        query_lower = query.lower()
        
        # Academic keywords
        academic_keywords = [
            "論文", "research", "study", "studies", "arxiv", "pubmed",
            "scholar", "academic", "journal", "publication", "paper",
            "dissertation", "thesis", "peer-reviewed", "peer reviewed",
        ]
        if any(keyword in query_lower for keyword in academic_keywords):
            return "academic"
        
        # News keywords
        news_keywords = [
            "ニュース", "news", "最新", "today", "recent", "breaking",
            "headline", "article", "report", "報道", "速報",
        ]
        if any(keyword in query_lower for keyword in news_keywords):
            return "news"
        
        # Government keywords
        government_keywords = [
            "政府", "government", "官公庁", ".gov", "official", "ministry",
            "department", "agency", "regulation", "law", "legal",
            "policy", "legislation", "法令", "条例",
        ]
        if any(keyword in query_lower for keyword in government_keywords):
            return "government"
        
        # Technical keywords
        technical_keywords = [
            "技術", "technical", "api", "code", "github", "documentation",
            "tutorial", "guide", "reference", "implementation", "algorithm",
            "programming", "software", "開発", "実装",
        ]
        if any(keyword in query_lower for keyword in technical_keywords):
            return "technical"
        
        # Default to general
        return "general"
    
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
        
        start_time = time.time()
        
        # Category detection
        category = self._detect_category(query)
        
        # Engine selection with weighted selection and circuit breaker
        config_manager = get_engine_config_manager()
        
        if options.engines:
            # Use specified engines
            candidate_engines = options.engines
        else:
            # Get engines for category
            candidate_engines_configs = config_manager.get_engines_for_category(category)
            if not candidate_engines_configs:
                # Fall back to default engines if no engines for category
                candidate_engines_configs = config_manager.get_available_engines()
            candidate_engines = [cfg.name for cfg in candidate_engines_configs]
        
        # Filter by circuit breaker and availability
        available_engines: list[tuple[str, float]] = []
        for engine_name in candidate_engines:
            try:
                if await check_engine_available(engine_name):
                    engine_config = config_manager.get_engine(engine_name)
                    if engine_config and engine_config.is_available:
                        available_engines.append((engine_name, engine_config.weight))
            except Exception as e:
                # Log error but continue with next engine
                logger.warning(
                    "Failed to check engine availability",
                    engine=engine_name,
                    error=str(e),
                )
                continue
        
        # Check if any engines are available
        if not available_engines:
            logger.warning(
                "No available engines",
                category=category,
                candidate_engines=candidate_engines,
            )
            return SearchResponse(
                results=[],
                query=query,
                provider=self.name,
                error="No available engines",
                elapsed_ms=(time.time() - start_time) * 1000,
                connection_mode="cdp" if self._cdp_connected else None,
            )
        
        # Weighted selection (sort by weight descending)
        available_engines.sort(key=lambda x: x[1], reverse=True)
        engine = available_engines[0][0]
        
        logger.debug(
            "Engine selected",
            engine=engine,
            category=category,
            weight=available_engines[0][1],
            available_count=len(available_engines),
        )
        
        try:
            await self._rate_limit(engine)
            
            # Get parser for engine
            parser = get_parser(engine)
            if parser is None:
                return SearchResponse(
                    results=[],
                    query=query,
                    provider=self.name,
                    error=f"No parser available for engine: {engine}",
                    elapsed_ms=(time.time() - start_time) * 1000,
                    connection_mode="cdp" if self._cdp_connected else None,
                )
            
            # Normalize query operators for the selected engine (§3.1.4)
            normalized_query = transform_query_for_engine(query, engine)
            
            # Log if query was transformed
            if normalized_query != query:
                logger.debug(
                    "Query operators normalized",
                    original=query[:50] if query else "",
                    normalized=normalized_query[:50] if normalized_query else "",
                    engine=engine,
                )
            
            # Build search URL
            search_url = parser.build_search_url(
                query=normalized_query,
                time_range=options.time_range,
            )
            
            logger.debug(
                "Browser search",
                engine=engine,
                query=normalized_query[:50] if normalized_query else "",
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
            
            # Apply human-like behavior to search results page
            try:
                # Apply inertial scrolling (reading simulation)
                await self._human_behavior.simulate_reading(page, len(html.encode("utf-8")))
                
                # Apply mouse trajectory to search result links
                try:
                    # Find search result links
                    result_links = await page.query_selector_all("a[href*='http'], a[href*='https']")
                    if result_links:
                        # Select random link from first 5 results
                        target_link = random.choice(result_links[:5])
                        # Get link selector
                        link_selector = await target_link.evaluate("""
                            (el) => {
                                if (el.id) return `#${el.id}`;
                                if (el.className) {
                                    const classes = el.className.split(' ').filter(c => c).join('.');
                                    if (classes) return `a.${classes}`;
                                }
                                return 'a';
                            }
                        """)
                        if link_selector:
                            await self._human_behavior.move_mouse_to_element(page, link_selector)
                except Exception as e:
                    logger.debug("Mouse movement skipped in search", error=str(e))
            except Exception as e:
                logger.debug("Human behavior simulation skipped", error=str(e))
            
            # Parse results
            parse_result = parser.parse(html, query)
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Handle CAPTCHA
            if parse_result.is_captcha:
                self._captcha_count += 1
                self._record_session_captcha(engine)
                
                # Record engine health (CAPTCHA)
                try:
                    await record_engine_result(
                        engine=engine,
                        success=False,
                        latency_ms=elapsed_ms,
                        is_captcha=True,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to record engine result",
                        engine=engine,
                        error=str(e),
                    )
                
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
                        connection_mode="cdp",
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
                
                # Record engine health (failure)
                try:
                    await record_engine_result(
                        engine=engine,
                        success=False,
                        latency_ms=elapsed_ms,
                        is_captcha=parse_result.is_captcha,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to record engine result",
                        engine=engine,
                        error=str(e),
                    )
                
                return SearchResponse(
                    results=[],
                    query=query,
                    provider=self.name,
                    error=error_msg,
                    elapsed_ms=elapsed_ms,
                    connection_mode="cdp",
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
            
            # Record engine health (success)
            try:
                await record_engine_result(
                    engine=engine,
                    success=True,
                    latency_ms=elapsed_ms,
                )
            except Exception as e:
                logger.warning(
                    "Failed to record engine result",
                    engine=engine,
                    error=str(e),
                )
            
            return SearchResponse(
                results=results,
                query=query,
                provider=self.name,
                total_count=len(parse_result.results),
                elapsed_ms=elapsed_ms,
                connection_mode="cdp",
            )
            
        except CDPConnectionError as e:
            # CDP connection failed - Chrome not running with remote debugging
            self._failure_count += 1
            self._last_error = str(e)
            elapsed_ms = (time.time() - start_time) * 1000
            
            logger.error(
                "CDP connection failed",
                error=str(e),
            )
            
            return SearchResponse(
                results=[],
                query=query,
                provider=self.name,
                error=str(e),
                elapsed_ms=elapsed_ms,
                connection_mode=None,
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
                connection_mode="cdp" if self._cdp_connected else None,
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
                connection_mode="cdp" if self._cdp_connected else None,
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

