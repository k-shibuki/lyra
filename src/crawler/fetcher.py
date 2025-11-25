"""
URL fetcher for Lancet.
Handles fetching URLs via HTTP client or browser with appropriate strategies.
"""

import asyncio
import gzip
import hashlib
import io
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from warcio.warcwriter import WARCWriter
from warcio.statusandheaders import StatusAndHeaders

from src.utils.config import get_settings
from src.utils.logging import get_logger, CausalTrace
from src.storage.database import get_database

logger = get_logger(__name__)


class FetchResult:
    """Result of a fetch operation."""
    
    def __init__(
        self,
        ok: bool,
        url: str,
        *,
        status: int | None = None,
        headers: dict[str, str] | None = None,
        html_path: str | None = None,
        pdf_path: str | None = None,
        warc_path: str | None = None,
        screenshot_path: str | None = None,
        content_hash: str | None = None,
        reason: str | None = None,
        method: str = "http_client",
    ):
        self.ok = ok
        self.url = url
        self.status = status
        self.headers = headers or {}
        self.html_path = html_path
        self.pdf_path = pdf_path
        self.warc_path = warc_path
        self.screenshot_path = screenshot_path
        self.content_hash = content_hash
        self.reason = reason
        self.method = method
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ok": self.ok,
            "url": self.url,
            "status": self.status,
            "headers": self.headers,
            "html_path": self.html_path,
            "pdf_path": self.pdf_path,
            "warc_path": self.warc_path,
            "screenshot_path": self.screenshot_path,
            "content_hash": self.content_hash,
            "reason": self.reason,
            "method": self.method,
        }


class RateLimiter:
    """Per-domain rate limiter."""
    
    def __init__(self):
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._domain_last_request: dict[str, float] = {}
        self._settings = get_settings()
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.lower()
    
    async def acquire(self, url: str) -> None:
        """Acquire rate limit slot for a domain.
        
        Args:
            url: URL to fetch.
        """
        domain = self._get_domain(url)
        
        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()
        
        async with self._domain_locks[domain]:
            last_request = self._domain_last_request.get(domain, 0)
            min_interval = 1.0 / self._settings.crawler.domain_qps
            
            # Add jitter
            delay_min = self._settings.crawler.delay_min
            delay_max = self._settings.crawler.delay_max
            jitter = random.uniform(delay_min, delay_max)
            
            elapsed = time.time() - last_request
            wait_time = max(0, min_interval + jitter - elapsed)
            
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            self._domain_last_request[domain] = time.time()


class HTTPFetcher:
    """HTTP client fetcher using curl_cffi."""
    
    def __init__(self):
        self._rate_limiter = RateLimiter()
        self._settings = get_settings()
    
    async def fetch(
        self,
        url: str,
        *,
        referer: str | None = None,
        headers: dict[str, str] | None = None,
        use_tor: bool = False,
    ) -> FetchResult:
        """Fetch URL using HTTP client.
        
        Args:
            url: URL to fetch.
            referer: Referer header.
            headers: Additional headers.
            use_tor: Whether to use Tor.
            
        Returns:
            FetchResult instance.
        """
        await self._rate_limiter.acquire(url)
        
        try:
            from curl_cffi import requests as curl_requests
            
            # Prepare headers
            req_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            }
            
            if referer:
                req_headers["Referer"] = referer
            
            if headers:
                req_headers.update(headers)
            
            # Configure proxy if using Tor
            proxies = None
            if use_tor:
                tor_settings = self._settings.tor
                proxy_url = f"socks5://{tor_settings.socks_host}:{tor_settings.socks_port}"
                proxies = {"http": proxy_url, "https": proxy_url}
            
            # Execute request with Chrome impersonation
            response = curl_requests.get(
                url,
                headers=req_headers,
                proxies=proxies,
                impersonate="chrome",
                timeout=self._settings.crawler.request_timeout,
                allow_redirects=True,
            )
            
            # Check for Cloudflare/JS challenge
            if _is_challenge_page(response.text, response.headers):
                logger.info("Challenge detected", url=url)
                return FetchResult(
                    ok=False,
                    url=url,
                    status=response.status_code,
                    reason="challenge_detected",
                    method="http_client",
                )
            
            # Save content
            content_hash = hashlib.sha256(response.content).hexdigest()
            html_path = await _save_content(url, response.content, response.headers)
            
            # Extract response headers
            resp_headers = dict(response.headers)
            
            # Save WARC archive
            warc_path = await _save_warc(
                url,
                response.content,
                response.status_code,
                resp_headers,
                request_headers=req_headers,
            )
            
            logger.info(
                "HTTP fetch success",
                url=url[:80],
                status=response.status_code,
                content_length=len(response.content),
            )
            
            return FetchResult(
                ok=True,
                url=url,
                status=response.status_code,
                headers=resp_headers,
                html_path=str(html_path) if html_path else None,
                warc_path=str(warc_path) if warc_path else None,
                content_hash=content_hash,
                method="http_client",
            )
            
        except Exception as e:
            logger.error("HTTP fetch error", url=url, error=str(e))
            return FetchResult(
                ok=False,
                url=url,
                reason=str(e),
                method="http_client",
            )


class BrowserFetcher:
    """Browser-based fetcher using Playwright."""
    
    def __init__(self):
        self._rate_limiter = RateLimiter()
        self._settings = get_settings()
        self._browser = None
        self._context = None
    
    async def _ensure_browser(self) -> None:
        """Ensure browser connection is established."""
        if self._browser is not None:
            return
        
        from playwright.async_api import async_playwright
        
        self._playwright = await async_playwright().start()
        
        # Connect to Chrome via CDP
        browser_settings = self._settings.browser
        cdp_url = f"http://{browser_settings.chrome_host}:{browser_settings.chrome_port}"
        
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
            logger.info("Connected to Chrome via CDP", url=cdp_url)
        except Exception as e:
            logger.warning("CDP connection failed, launching local browser", error=str(e))
            self._browser = await self._playwright.chromium.launch(
                headless=browser_settings.default_headless
            )
        
        # Create context
        self._context = await self._browser.new_context(
            viewport={
                "width": browser_settings.viewport_width,
                "height": browser_settings.viewport_height,
            },
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        
        # Setup route for blocking
        if browser_settings.block_ads or browser_settings.block_trackers:
            await self._setup_blocking()
    
    async def _setup_blocking(self) -> None:
        """Setup resource blocking rules."""
        block_patterns = [
            # Ads
            "*googlesyndication.com*",
            "*doubleclick.net*",
            "*googleadservices.com*",
            # Trackers
            "*google-analytics.com*",
            "*googletagmanager.com*",
            "*facebook.com/tr*",
        ]
        
        async def block_route(route):
            await route.abort()
        
        for pattern in block_patterns:
            await self._context.route(pattern, block_route)
    
    async def fetch(
        self,
        url: str,
        *,
        referer: str | None = None,
        headful: bool = False,
        take_screenshot: bool = True,
    ) -> FetchResult:
        """Fetch URL using browser.
        
        Args:
            url: URL to fetch.
            referer: Referer header.
            headful: Whether to use headful mode.
            take_screenshot: Whether to capture screenshot.
            
        Returns:
            FetchResult instance.
        """
        await self._rate_limiter.acquire(url)
        await self._ensure_browser()
        
        page = None
        try:
            page = await self._context.new_page()
            
            # Set referer if provided
            if referer:
                await page.set_extra_http_headers({"Referer": referer})
            
            # Navigate
            response = await page.goto(
                url,
                timeout=self._settings.crawler.page_load_timeout * 1000,
                wait_until="domcontentloaded",
            )
            
            if response is None:
                return FetchResult(
                    ok=False,
                    url=url,
                    reason="no_response",
                    method="browser",
                )
            
            # Wait a bit for dynamic content
            await page.wait_for_timeout(1000)
            
            # Get content
            content = await page.content()
            content_bytes = content.encode("utf-8")
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            
            # Check for challenge
            if _is_challenge_page(content, {}):
                logger.info("Browser challenge detected", url=url)
                return FetchResult(
                    ok=False,
                    url=url,
                    status=response.status,
                    reason="challenge_detected",
                    method="browser",
                )
            
            # Save content
            html_path = await _save_content(url, content_bytes, {})
            
            # Save WARC archive
            resp_headers = dict(response.headers)
            warc_path = await _save_warc(
                url,
                content_bytes,
                response.status,
                resp_headers,
            )
            
            # Take screenshot
            screenshot_path = None
            if take_screenshot:
                screenshot_path = await _save_screenshot(page, url)
            
            logger.info(
                "Browser fetch success",
                url=url[:80],
                status=response.status,
                content_length=len(content_bytes),
            )
            
            return FetchResult(
                ok=True,
                url=url,
                status=response.status,
                headers=resp_headers,
                html_path=str(html_path) if html_path else None,
                warc_path=str(warc_path) if warc_path else None,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
                content_hash=content_hash,
                method="browser_headless" if not headful else "browser_headful",
            )
            
        except Exception as e:
            logger.error("Browser fetch error", url=url, error=str(e))
            return FetchResult(
                ok=False,
                url=url,
                reason=str(e),
                method="browser",
            )
        finally:
            if page:
                await page.close()
    
    async def close(self) -> None:
        """Close browser connection."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_playwright"):
            await self._playwright.stop()


def _is_challenge_page(content: str, headers: dict) -> bool:
    """Check if page is a challenge/captcha page.
    
    Args:
        content: Page content.
        headers: Response headers.
        
    Returns:
        True if challenge detected.
    """
    content_lower = content.lower()
    
    # Cloudflare indicators
    cloudflare_indicators = [
        "cf-browser-verification",
        "cloudflare ray id",
        "please wait while we verify",
        "checking your browser",
        "just a moment",
        "_cf_chl_opt",
    ]
    
    if any(ind in content_lower for ind in cloudflare_indicators):
        return True
    
    # CAPTCHA indicators
    captcha_indicators = [
        "recaptcha",
        "hcaptcha",
        "captcha-container",
        "g-recaptcha",
        "h-captcha",
    ]
    
    if any(ind in content_lower for ind in captcha_indicators):
        return True
    
    # Server header check
    server = headers.get("server", "").lower()
    if "cloudflare" in server:
        # Check for challenge response
        cf_ray = headers.get("cf-ray")
        if cf_ray and len(content) < 10000:  # Challenge pages are usually small
            return True
    
    return False


async def _save_content(url: str, content: bytes, headers: dict) -> Path | None:
    """Save fetched content to file.
    
    Args:
        url: Source URL.
        content: Content bytes.
        headers: Response headers.
        
    Returns:
        Path to saved file.
    """
    settings = get_settings()
    cache_dir = Path(settings.storage.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename from URL hash
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Determine extension
    content_type = headers.get("content-type", "").lower()
    if "pdf" in content_type:
        ext = ".pdf"
    else:
        ext = ".html"
    
    filename = f"{timestamp}_{url_hash}{ext}"
    filepath = cache_dir / filename
    
    filepath.write_bytes(content)
    
    return filepath


async def _save_warc(
    url: str,
    content: bytes,
    status_code: int,
    response_headers: dict[str, str],
    *,
    request_headers: dict[str, str] | None = None,
    method: str = "GET",
) -> Path | None:
    """Save HTTP response as WARC file.
    
    Creates a WARC file containing the request and response records.
    
    Args:
        url: Request URL.
        content: Response body bytes.
        status_code: HTTP status code.
        response_headers: Response headers.
        request_headers: Request headers (optional).
        method: HTTP method (default: GET).
        
    Returns:
        Path to saved WARC file.
    """
    settings = get_settings()
    warc_dir = Path(settings.storage.warc_dir)
    warc_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename from URL hash and timestamp
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{url_hash}.warc.gz"
    filepath = warc_dir / filename
    
    try:
        with open(filepath, "wb") as output:
            writer = WARCWriter(output, gzip=True)
            
            # Create WARC-Date in ISO format
            warc_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            # Write request record (if headers provided)
            if request_headers:
                req_headers_list = list(request_headers.items())
                req_http_headers = StatusAndHeaders(
                    f"{method} {urlparse(url).path or '/'} HTTP/1.1",
                    req_headers_list,
                    is_http_request=True,
                )
                request_record = writer.create_warc_record(
                    url,
                    "request",
                    http_headers=req_http_headers,
                    warc_headers_dict={"WARC-Date": warc_date},
                )
                writer.write_record(request_record)
            
            # Build response status line
            status_text = _get_http_status_text(status_code)
            status_line = f"HTTP/1.1 {status_code} {status_text}"
            
            # Build response headers list
            resp_headers_list = list(response_headers.items())
            resp_http_headers = StatusAndHeaders(status_line, resp_headers_list)
            
            # Write response record
            response_record = writer.create_warc_record(
                url,
                "response",
                payload=io.BytesIO(content),
                http_headers=resp_http_headers,
                warc_headers_dict={"WARC-Date": warc_date},
            )
            writer.write_record(response_record)
        
        logger.debug("WARC saved", url=url[:60], path=str(filepath))
        return filepath
        
    except Exception as e:
        logger.error("WARC save failed", url=url[:60], error=str(e))
        return None


def _get_http_status_text(status_code: int) -> str:
    """Get HTTP status text for status code.
    
    Args:
        status_code: HTTP status code.
        
    Returns:
        Status text (e.g., "OK", "Not Found").
    """
    status_texts = {
        200: "OK",
        201: "Created",
        204: "No Content",
        301: "Moved Permanently",
        302: "Found",
        303: "See Other",
        304: "Not Modified",
        307: "Temporary Redirect",
        308: "Permanent Redirect",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        408: "Request Timeout",
        429: "Too Many Requests",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
    }
    return status_texts.get(status_code, "Unknown")


async def _save_screenshot(page, url: str) -> Path | None:
    """Save page screenshot.
    
    Args:
        page: Playwright page.
        url: Source URL.
        
    Returns:
        Path to screenshot file.
    """
    settings = get_settings()
    screenshots_dir = Path(settings.storage.screenshots_dir)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    filename = f"{timestamp}_{url_hash}.png"
    filepath = screenshots_dir / filename
    
    await page.screenshot(path=str(filepath), full_page=False)
    
    return filepath


# Global fetcher instances
_http_fetcher: HTTPFetcher | None = None
_browser_fetcher: BrowserFetcher | None = None


async def fetch_url(
    url: str,
    context: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Fetch URL with automatic method selection.
    
    Args:
        url: URL to fetch.
        context: Context information (referer, etc.).
        policy: Fetch policy override.
        task_id: Associated task ID.
        
    Returns:
        Fetch result dictionary.
    """
    global _http_fetcher, _browser_fetcher
    
    context = context or {}
    policy = policy or {}
    
    db = await get_database()
    
    with CausalTrace() as trace:
        # Check domain cooldown
        domain = urlparse(url).netloc.lower()
        if await db.is_domain_cooled_down(domain):
            logger.info("Domain in cooldown", domain=domain, url=url[:80])
            return FetchResult(
                ok=False,
                url=url,
                reason="domain_cooldown",
            ).to_dict()
        
        # Determine fetch method
        force_browser = policy.get("force_browser", False)
        force_headful = policy.get("force_headful", False)
        use_tor = policy.get("use_tor", False)
        
        # Initialize fetchers
        if _http_fetcher is None:
            _http_fetcher = HTTPFetcher()
        if _browser_fetcher is None:
            _browser_fetcher = BrowserFetcher()
        
        # Try HTTP client first unless browser forced
        result = None
        
        if not force_browser:
            result = await _http_fetcher.fetch(
                url,
                referer=context.get("referer"),
                use_tor=use_tor,
            )
            
            # If challenge detected, try browser
            if not result.ok and result.reason == "challenge_detected":
                logger.info("Escalating to browser", url=url[:80])
                force_browser = True
        
        if force_browser or (result and not result.ok):
            result = await _browser_fetcher.fetch(
                url,
                referer=context.get("referer"),
                headful=force_headful,
            )
        
        # Update domain metrics
        await db.update_domain_metrics(
            domain,
            success=result.ok,
            is_captcha=result.reason == "challenge_detected",
            is_http_error=result.status and result.status >= 400,
        )
        
        # Store page record if successful
        if result.ok:
            await db.insert("pages", {
                "url": url,
                "final_url": url,  # TODO: Track redirects
                "domain": domain,
                "fetch_method": result.method,
                "http_status": result.status,
                "content_hash": result.content_hash,
                "html_path": result.html_path,
                "warc_path": result.warc_path,
                "screenshot_path": result.screenshot_path,
                "headers_json": json.dumps(result.headers) if result.headers else None,
                "cause_id": trace.id,
            }, or_replace=True)
        
        # Log event
        await db.log_event(
            event_type="fetch",
            message=f"Fetched {url[:60]}",
            task_id=task_id,
            cause_id=trace.id,
            component="crawler",
            details={
                "url": url,
                "ok": result.ok,
                "method": result.method,
                "status": result.status,
                "reason": result.reason,
            },
        )
        
        return result.to_dict()


# Need to import json for the db.insert call
import json

