"""
URL fetcher for Lyra.
Handles fetching URLs via HTTP client or browser with appropriate strategies.

Features:
- HTTP client with Chrome impersonation (curl_cffi)
- Browser automation with Playwright (CDP connection)
- Headless/headful automatic switching based on domain policy
- Human-like behavior simulation (mouse movement, scrolling, delays)
- Tor integration with Stem for circuit control
- ETag/If-Modified-Since conditional requests (304 cache)
"""

import asyncio
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from src.crawler.browser_fetcher import BrowserFetcher
from src.crawler.browser_provider import (
    BrowserMode,
    BrowserOptions,
    get_browser_registry,
)
from src.crawler.fetch_result import FetchResult
from src.crawler.http_fetcher import HTTPFetcher
from src.crawler.ipv6_manager import (
    AddressFamily,
    IPv6ConnectionResult,
    get_ipv6_manager,
)
from src.crawler.tor_controller import _can_use_tor, get_tor_controller
from src.crawler.undetected import (
    get_undetected_fetcher,
)
from src.crawler.wayback import (
    get_wayback_fallback,
)
from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.logging import CausalTrace, get_logger

if TYPE_CHECKING:
    from playwright.async_api import Page

    from src.storage.database import Database

logger = get_logger(__name__)

# =============================================================================
# Utility Functions
# =============================================================================

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
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{url_hash}.warc.gz"
    filepath = warc_dir / filename

    try:
        with open(filepath, "wb") as output:
            writer = WARCWriter(output, gzip=True)

            # Create WARC-Date in ISO format
            warc_date = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

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


async def _save_screenshot(page: "Page", url: str) -> Path | None:
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
# Worker ID -> BrowserFetcher mapping (ADR-0014 Phase 3: Worker Context Isolation)
_browser_fetchers: dict[int, BrowserFetcher] = {}


async def fetch_url(
    url: str,
    context: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    task_id: str | None = None,
    worker_id: int = 0,
) -> dict[str, Any]:
    """Fetch URL with automatic method selection, escalation, and cache support.

    Implements multi-stage fetch strategy:
    1. HTTP client (fastest, with 304 cache support)
    2. Browser headless (for JS-rendered pages)
    3. Browser headful (for challenge bypass)
    4. Tor circuit renewal on 403/429
    5. Wayback fallback (for persistent blocks)

    Supports conditional requests (If-None-Match/If-Modified-Since) for
    efficient re-validation and 304 Not Modified responses.

    Cumulative timeout (max_fetch_time) ensures the entire fetch operation
    completes within a reasonable time, preventing exploration stalls.

    Args:
        url: URL to fetch.
        context: Context information (referer, etc.).
        policy: Fetch policy override. Supported keys:
            - force_browser: Force browser fetching.
            - force_headful: Force headful mode.
            - use_tor: Use Tor proxy.
            - skip_cache: Skip cache lookup and conditional requests.
            - max_retries: Override max retries (default: 3).
            - allow_intervention: Allow manual intervention on challenge (default: True).
            - use_provider: Use BrowserProviderRegistry for browser fetching (default: False).
            - provider_name: Specific provider to use (e.g., "playwright", "undetected_chrome").
            - max_fetch_time: Override cumulative timeout (default: from config).
        task_id: Associated task ID.
        worker_id: Worker ID for isolated browser context (ADR-0014 Phase 3).

    Returns:
        Fetch result dictionary with additional 'from_cache' field.
    """
    context = context or {}
    policy = policy or {}
    settings = get_settings()

    # Get cumulative timeout from policy or config
    max_fetch_time = policy.get("max_fetch_time", settings.crawler.max_fetch_time)

    try:
        # Wrap entire fetch operation with cumulative timeout
        return await asyncio.wait_for(
            _fetch_url_impl(url, context, policy, task_id, worker_id),
            timeout=float(max_fetch_time),
        )
    except TimeoutError:
        logger.warning(
            "Fetch cumulative timeout exceeded",
            url=url[:80],
            max_fetch_time=max_fetch_time,
        )
        # Return timeout result
        return FetchResult(
            ok=False,
            url=url,
            reason="cumulative_timeout",
            method="timeout",
        ).to_dict()


async def _fetch_url_impl(
    url: str,
    context: dict[str, Any],
    policy: dict[str, Any],
    task_id: str | None,
    worker_id: int = 0,
) -> dict[str, Any]:
    """Internal implementation of fetch_url with multi-stage escalation.

    This function contains the actual fetch logic. It is wrapped by fetch_url
    with a cumulative timeout to prevent indefinite blocking.

    Args:
        url: URL to fetch.
        context: Context information.
        policy: Fetch policy override.
        task_id: Associated task ID.
        worker_id: Worker ID for isolated browser context (ADR-0014 Phase 3).
    """
    global _http_fetcher, _browser_fetchers

    db = await get_database()
    settings = get_settings()

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

        # Check domain daily budget (ADR-0006 - IP block prevention)
        from src.scheduler.domain_budget import get_domain_budget_manager

        budget_manager = get_domain_budget_manager()
        budget_check = budget_manager.can_request_to_domain(domain)

        if not budget_check.allowed:
            logger.warning(
                "Domain daily budget exceeded",
                domain=domain,
                reason=budget_check.reason,
                url=url[:80],
            )
            return FetchResult(
                ok=False,
                url=url,
                reason="domain_budget_exceeded",
            ).to_dict()

        # Record request for Tor daily limit tracking (Tor daily usage limit)
        # Must be after cooldown check to only count actual fetches
        from src.utils.metrics import get_metrics_collector

        collector = get_metrics_collector()
        collector.record_request(domain)

        # Determine fetch method
        force_browser = policy.get("force_browser", False)
        force_headful = policy.get("force_headful", False)
        use_tor = policy.get("use_tor", False)
        skip_cache = policy.get("skip_cache", False)
        policy.get("max_retries", settings.crawler.max_retries)
        use_provider = policy.get("use_provider", False)
        provider_name = policy.get("provider_name", None)

        # Initialize fetchers
        if _http_fetcher is None:
            _http_fetcher = HTTPFetcher()
        # Get worker-specific browser fetcher (ADR-0014 Phase 3)
        if worker_id not in _browser_fetchers:
            _browser_fetchers[worker_id] = BrowserFetcher(worker_id=worker_id)
            logger.info("Created BrowserFetcher for worker", worker_id=worker_id)
        _browser_fetcher = _browser_fetchers[worker_id]

        # Check cache for conditional request data
        cached_etag = None
        cached_last_modified = None
        cached_content_path = None
        cached_content_hash = None
        has_previous_browser_fetch = False

        if not skip_cache and not force_browser:
            cache_entry = await db.get_fetch_cache(url)
            if cache_entry:
                cached_etag = cache_entry.get("etag")
                cached_last_modified = cache_entry.get("last_modified")
                cached_content_path = cache_entry.get("content_path")
                cached_content_hash = cache_entry.get("content_hash")
                # Subsequent visits use HTTP client with 304 cache
                # If cache entry exists with ETag/Last-Modified, use HTTP client
                has_previous_browser_fetch = bool(cached_etag or cached_last_modified)

                logger.debug(
                    "Found cache entry for conditional request",
                    url=url[:80],
                    has_etag=bool(cached_etag),
                    has_last_modified=bool(cached_last_modified),
                    has_previous_browser_fetch=has_previous_browser_fetch,
                )

        result = None
        retry_count = 0
        escalation_path = []  # Track escalation for logging

        # =====================================================================
        # First visit uses browser, subsequent visits use HTTP client with 304 cache
        # =====================================================================
        # Stage 1: HTTP Client (with optional Tor) - only for subsequent visits
        # =====================================================================
        if not force_browser and has_previous_browser_fetch:
            result = await _http_fetcher.fetch(
                url,
                referer=context.get("referer"),
                use_tor=use_tor,
                cached_etag=cached_etag,
                cached_last_modified=cached_last_modified,
            )
            escalation_path.append(f"http_client(tor={use_tor})")

            # Record Tor usage when explicitly requested (Tor daily usage limit)
            if use_tor:
                from src.utils.metrics import get_metrics_collector

                collector = get_metrics_collector()
                collector.record_tor_usage(domain)

            # Handle 304 Not Modified - use cached content
            if result.ok and result.status == 304 and cached_content_path:
                logger.info(
                    "Using cached content (304 Not Modified)",
                    url=url[:80],
                    cached_path=cached_content_path,
                )
                result.html_path = cached_content_path
                result.content_hash = cached_content_hash

                # Update cache validation time
                await db.update_fetch_cache_validation(
                    url,
                    etag=result.etag,
                    last_modified=result.last_modified,
                )

            # Handle 403/429 - try Tor circuit renewal (with daily limit check)
            if not result.ok and result.status in (403, 429) and not use_tor:
                # Check Tor daily limit before escalating (Tor daily usage limit)
                if await _can_use_tor(domain):
                    logger.info("HTTP error, trying with Tor", url=url[:80], status=result.status)

                    tor_controller = await get_tor_controller()
                    if await tor_controller.renew_circuit(domain):
                        result = await _http_fetcher.fetch(
                            url,
                            referer=context.get("referer"),
                            use_tor=True,
                            cached_etag=cached_etag,
                            cached_last_modified=cached_last_modified,
                        )
                        escalation_path.append("http_client(tor=True)")
                        retry_count += 1

                        # Record Tor usage for daily limit tracking
                        from src.utils.metrics import get_metrics_collector

                        collector = get_metrics_collector()
                        collector.record_tor_usage(domain)
                else:
                    logger.info(
                        "Tor daily limit reached, skipping Tor escalation",
                        url=url[:80],
                        status=result.status,
                    )

            # If challenge detected or still failing, escalate to browser
            if not result.ok and result.reason == "challenge_detected":
                logger.info("Challenge detected, escalating to browser", url=url[:80])
                force_browser = True

        # =====================================================================
        # First visit uses browser route (when cache is not available)
        # =====================================================================
        # Stage 1b: Browser (first visit) - first access uses browser by default
        # =====================================================================
        if not force_browser and not has_previous_browser_fetch and (not result or not result.ok):
            # First access uses browser route (headless) even for static pages
            logger.debug(
                "First visit detected, using browser route",
                url=url[:80],
            )
            force_browser = True

        # =====================================================================
        # Stage 2: Browser via Provider (if use_provider=True)
        # =====================================================================
        if force_browser and use_provider:
            registry = get_browser_registry()

            browser_options = BrowserOptions(
                mode=BrowserMode.HEADFUL if force_headful else BrowserMode.HEADLESS,
                referer=context.get("referer"),
                simulate_human=True,
                take_screenshot=True,
            )

            if provider_name:
                # Use specific provider
                provider = registry.get(provider_name)
                if provider:
                    provider_result = await provider.navigate(url, browser_options)
                else:
                    logger.warning(f"Provider {provider_name} not found, using fallback")
                    provider_result = await registry.navigate_with_fallback(url, browser_options)
            else:
                # Use fallback strategy
                provider_result = await registry.navigate_with_fallback(url, browser_options)

            escalation_path.append(f"provider({provider_result.provider})")

            if provider_result.ok:
                # Convert ProviderPageResult to FetchResult
                result = FetchResult(
                    ok=True,
                    url=url,
                    status=provider_result.status,
                    html_path=provider_result.html_path,
                    screenshot_path=provider_result.screenshot_path,
                    content_hash=provider_result.content_hash,
                    method=f"provider_{provider_result.provider}",
                    from_cache=False,
                )
            else:
                result = FetchResult(
                    ok=False,
                    url=url,
                    status=provider_result.status,
                    reason=provider_result.error,
                    method=f"provider_{provider_result.provider}",
                    auth_type=provider_result.challenge_type,
                )

                if provider_result.challenge_detected:
                    # Update domain policy for future
                    await _update_domain_headful_ratio(db, domain, increase=True)

        # =====================================================================
        # Stage 2b: Browser Headless (auto mode selection)
        # =====================================================================
        elif force_browser and not force_headful:
            allow_intervention = policy.get("allow_intervention", True)
            result = await _browser_fetcher.fetch(
                url,
                referer=context.get("referer"),
                headful=None,  # Auto-detect based on domain policy
                task_id=task_id,
                allow_intervention=allow_intervention,
            )
            escalation_path.append(f"browser({result.method})")
            retry_count += 1

            # If headless failed with escalation hint, try headful
            if not result.ok and result.reason == "challenge_detected_escalate_headful":
                logger.info("Headless challenge, escalating to headful", url=url[:80])
                force_headful = True

        # =====================================================================
        # Stage 3: Browser Headful (for persistent challenges)
        # =====================================================================
        if force_headful and (not result or not result.ok):
            allow_intervention = policy.get("allow_intervention", True)
            result = await _browser_fetcher.fetch(
                url,
                referer=context.get("referer"),
                headful=True,
                task_id=task_id,
                allow_intervention=allow_intervention,
            )
            escalation_path.append("browser_headful")
            retry_count += 1

            # If headful still fails, update domain policy for future
            if not result.ok and "challenge" in (result.reason or ""):
                await _update_domain_headful_ratio(db, domain, increase=True)

        # =====================================================================
        # Stage 4: Undetected ChromeDriver (for Cloudflare advanced/Turnstile)
        # =====================================================================
        use_undetected = policy.get("use_undetected", False)

        # Auto-escalate to undetected-chromedriver if:
        # 1. Explicitly requested, OR
        # 2. Headful browser failed with persistent challenge
        if not use_undetected and result and not result.ok:
            if result.reason in (
                "challenge_detected",
                "challenge_detected_after_intervention",
                "intervention_timeout",
                "intervention_failed",
            ):
                # Check if domain has high persistent challenge rate
                domain_info = await db.fetch_one(
                    "SELECT captcha_rate, block_score FROM domains WHERE domain = ?",
                    (domain,),
                )
                if domain_info:
                    captcha_rate = domain_info.get("captcha_rate", 0.0)
                    block_score = domain_info.get("block_score", 0)
                    # Auto-escalate for domains with persistent issues
                    if captcha_rate > 0.5 or block_score > 5:
                        use_undetected = True
                        logger.info(
                            "Auto-escalating to undetected-chromedriver",
                            url=url[:80],
                            captcha_rate=captcha_rate,
                            block_score=block_score,
                        )

        if use_undetected and (not result or not result.ok):
            try:
                undetected_fetcher = get_undetected_fetcher()

                if undetected_fetcher.is_available():
                    uc_result = await undetected_fetcher.fetch(
                        url,
                        headless=False,  # Headful is more effective for bypass
                        wait_for_cloudflare=True,
                        cloudflare_timeout=45,  # Allow more time for challenge
                        take_screenshot=True,
                        simulate_human=True,
                    )
                    escalation_path.append("undetected_chromedriver")
                    retry_count += 1

                    if uc_result.ok:
                        # Convert UndetectedFetchResult to FetchResult
                        result = FetchResult(
                            ok=True,
                            url=url,
                            status=uc_result.status,
                            html_path=uc_result.html_path,
                            screenshot_path=uc_result.screenshot_path,
                            content_hash=uc_result.content_hash,
                            method="undetected_chromedriver",
                            from_cache=False,
                        )
                        logger.info(
                            "Undetected-chromedriver bypass success",
                            url=url[:80],
                        )
                    else:
                        logger.warning(
                            "Undetected-chromedriver bypass failed",
                            url=url[:80],
                            reason=uc_result.reason,
                        )
                else:
                    logger.debug(
                        "Undetected-chromedriver not available, skipping",
                        url=url[:80],
                    )
            except Exception as e:
                logger.error(
                    "Undetected-chromedriver error",
                    url=url[:80],
                    error=str(e),
                )

        # =====================================================================
        # Stage 5: Wayback Fallback (for persistent 403/CAPTCHA)
        # =====================================================================
        use_wayback_fallback = policy.get("use_wayback_fallback", True)

        # Auto-fallback to Wayback if:
        # 1. Fallback is enabled, AND
        # 2. All previous stages failed with 403/CAPTCHA/blocking
        if use_wayback_fallback and result and not result.ok:
            should_try_wayback = result.status in (403, 429, 451, 503) or result.reason in (
                "challenge_detected",
                "challenge_detected_after_intervention",
                "challenge_detected_escalate_headful",
                "intervention_timeout",
                "intervention_failed",
                "auth_required",
            )

            if should_try_wayback:
                logger.info(
                    "Attempting Wayback fallback",
                    url=url[:80],
                    reason=result.reason,
                    status=result.status,
                )

                try:
                    wayback_fallback = get_wayback_fallback()
                    fallback_result = await wayback_fallback.get_fallback_content(url)

                    if fallback_result.ok and fallback_result.html:
                        # Save archived content
                        archived_content = fallback_result.html.encode("utf-8")
                        content_hash = hashlib.sha256(archived_content).hexdigest()
                        html_path = await _save_content(url, archived_content, {})

                        # Create successful result from archive
                        result = FetchResult(
                            ok=True,
                            url=url,
                            status=200,  # Treat as successful
                            html_path=str(html_path) if html_path else None,
                            content_hash=content_hash,
                            method="wayback_fallback",
                            from_cache=False,
                            # Archive-specific fields
                            is_archived=True,
                            archive_date=(
                                fallback_result.snapshot.timestamp
                                if fallback_result.snapshot
                                else None
                            ),
                            archive_url=(
                                fallback_result.snapshot.wayback_url
                                if fallback_result.snapshot
                                else None
                            ),
                            freshness_penalty=fallback_result.freshness_penalty,
                        )
                        escalation_path.append("wayback_fallback")

                        logger.info(
                            "Wayback fallback successful",
                            url=url[:80],
                            archive_date=(
                                result.archive_date.isoformat() if result.archive_date else None
                            ),
                            freshness_penalty=result.freshness_penalty,
                        )

                        # Update domain's wayback success rate for future reference
                        await _update_domain_wayback_success(db, domain, success=True)
                    else:
                        logger.warning(
                            "Wayback fallback failed",
                            url=url[:80],
                            error=fallback_result.error,
                        )
                        await _update_domain_wayback_success(db, domain, success=False)

                except Exception as e:
                    logger.error(
                        "Wayback fallback error",
                        url=url[:80],
                        error=str(e),
                    )

        # =====================================================================
        # Update Metrics and Store Results
        # =====================================================================

        # Update domain metrics
        if result is not None:
            await db.update_domain_metrics(
                domain,
                success=result.ok,
                is_captcha=bool(result.reason and "challenge" in result.reason),
                is_http_error=bool(result.status and result.status >= 400),
            )

        # Update IPv6 metrics
        # Track connection result for IPv6 learning
        ipv6_manager = get_ipv6_manager()
        ip_family_used = AddressFamily.IPV4  # Default assumption

        # Determine IP family from result or connection info
        # Note: curl_cffi doesn't expose the actual IP family used,
        # so we track based on success/failure patterns for learning
        if result is not None:
            if result.ok:
                # Record as success for learning
                ipv6_result = IPv6ConnectionResult(
                    hostname=urlparse(url).hostname or domain,
                    success=True,
                    family_used=ip_family_used,
                    family_attempted=ip_family_used,
                    switched=False,
                    switch_success=False,
                    latency_ms=0,  # Not tracked at this level
                )
                await ipv6_manager.record_connection_result(domain, ipv6_result)
            elif result.reason and "timeout" in result.reason.lower():
                # Timeout might indicate IPv6 connectivity issue
                ipv6_result = IPv6ConnectionResult(
                    hostname=urlparse(url).hostname or domain,
                    success=False,
                    family_used=ip_family_used,
                    family_attempted=ip_family_used,
                    switched=False,
                    switch_success=False,
                    latency_ms=0,
                    error=result.reason,
                )
                await ipv6_manager.record_connection_result(domain, ipv6_result)

        # Store page record and update cache if successful
        if result is not None and result.ok:
            # Update pages table and capture page_id for fragment linking
            page_id = await db.insert(
                "pages",
                {
                    "url": url,
                    "final_url": result.final_url,
                    "domain": domain,
                    "fetch_method": result.method,
                    "http_status": result.status,
                    "content_hash": result.content_hash,
                    "html_path": result.html_path,
                    "warc_path": result.warc_path,
                    "screenshot_path": result.screenshot_path,
                    "etag": result.etag,
                    "last_modified": result.last_modified,
                    "headers_json": json.dumps(result.headers) if result.headers else None,
                    "cause_id": trace.id,
                },
                or_replace=True,
            )
            if result is not None:
                result.page_id = page_id

                # Update fetch cache for future conditional requests
                # Only cache if we have ETag or Last-Modified
                if (result.etag or result.last_modified) and not result.from_cache:
                    await db.set_fetch_cache(
                        url,
                        etag=result.etag,
                        last_modified=result.last_modified,
                        content_hash=result.content_hash,
                        content_path=result.html_path,
                    )
                    logger.debug(
                        "Updated fetch cache",
                        url=url[:80],
                        etag=result.etag[:20] if result.etag else None,
                        last_modified=result.last_modified,
                    )

        # Log event
        if result is not None:
            event_details = {
                "url": url,
                "ok": result.ok,
                "method": result.method,
                "status": result.status,
                "reason": result.reason,
                "from_cache": result.from_cache,
                "has_etag": bool(result.etag),
                "has_last_modified": bool(result.last_modified),
                "escalation_path": " -> ".join(escalation_path),
                "retry_count": retry_count,
                "ip_family": result.ip_family,
                "ip_switched": result.ip_switched,
            }

            # Add archive details if content is from Wayback
            if result.is_archived:
                event_details["is_archived"] = True
                event_details["archive_date"] = (
                    result.archive_date.isoformat() if result.archive_date else None
                )
                event_details["freshness_penalty"] = result.freshness_penalty

            await db.log_event(
                event_type="fetch",
                message=f"Fetched {url[:60]}",
                task_id=task_id,
                cause_id=trace.id,
                component="crawler",
                details=event_details,
            )

            # Record domain request for daily budget tracking (ADR-0006 - Domain daily budget)
            # Only record successful fetches with actual content (not 304)
            if result.ok and result.status != 304:
                budget_manager.record_domain_request(domain, is_page=True)

            return result.to_dict()

        # If result is None, return empty dict
        return {}


async def _update_domain_headful_ratio(db: "Database", domain: str, increase: bool = True) -> None:
    """Update domain's headful ratio based on fetch outcomes.

    Args:
        db: Database instance.
        domain: Domain name.
        increase: Whether to increase (True) or decrease (False) the ratio.
    """
    current = await db.fetch_one(
        "SELECT headful_ratio FROM domains WHERE domain = ?",
        (domain,),
    )

    if current is None:
        # Create domain record with elevated headful ratio
        await db.insert(
            "domains",
            {
                "domain": domain,
                "headful_ratio": 0.3 if increase else 0.1,
            },
            auto_id=False,
        )
    else:
        ratio = current.get("headful_ratio", 0.1)
        if increase:
            new_ratio = min(1.0, ratio * 1.5 + 0.1)  # Increase by 50% + 0.1
        else:
            new_ratio = max(0.05, ratio * 0.8)  # Decrease by 20%

        await db.update(
            "domains",
            {"headful_ratio": new_ratio},
            "domain = ?",
            (domain,),
        )

        logger.debug(
            "Updated domain headful ratio",
            domain=domain,
            old_ratio=ratio,
            new_ratio=new_ratio,
        )


async def _update_domain_wayback_success(db: "Database", domain: str, success: bool) -> None:
    """Update domain's Wayback fallback success rate.

    Track Wayback fallback success to inform future fallback decisions.

    Args:
        db: Database instance.
        domain: Domain name.
        success: Whether the Wayback fallback was successful.
    """
    current = await db.fetch_one(
        "SELECT wayback_success_count, wayback_failure_count FROM domains WHERE domain = ?",
        (domain,),
    )

    if current is None:
        # Create domain record with initial Wayback stats
        await db.insert(
            "domains",
            {
                "domain": domain,
                "wayback_success_count": 1 if success else 0,
                "wayback_failure_count": 0 if success else 1,
            },
            auto_id=False,
        )
    else:
        success_count = current.get("wayback_success_count", 0) or 0
        failure_count = current.get("wayback_failure_count", 0) or 0

        if success:
            success_count += 1
        else:
            failure_count += 1

        await db.update(
            "domains",
            {
                "wayback_success_count": success_count,
                "wayback_failure_count": failure_count,
            },
            "domain = ?",
            (domain,),
        )

        # Calculate success rate for logging
        total = success_count + failure_count
        success_rate = success_count / total if total > 0 else 0.0

        logger.debug(
            "Updated domain Wayback success rate",
            domain=domain,
            success_rate=success_rate,
            success_count=success_count,
            failure_count=failure_count,
        )
