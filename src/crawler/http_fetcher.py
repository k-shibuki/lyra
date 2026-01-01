"""HTTP client fetcher for URL fetcher."""

import asyncio
import hashlib
import random
import time
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from src.crawler.challenge_detector import _is_challenge_page
from src.crawler.dns_policy import get_dns_policy_manager
from src.crawler.fetch_result import FetchResult
from src.crawler.http3_policy import (
    HTTP3RequestResult,
    ProtocolVersion,
    get_http3_policy_manager,
)
from src.crawler.sec_fetch import (
    NavigationContext,
    SecFetchDest,
    generate_sec_fetch_headers,
)
from src.utils.config import get_settings
from src.utils.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class RateLimiter:
    """Per-domain rate limiter.

    Uses DomainPolicyManager for per-domain QPS configuration.
    """

    def __init__(self) -> None:
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._domain_last_request: dict[str, float] = {}
        self._settings = get_settings()

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.lower()

    async def acquire(self, url: str) -> None:
        """Acquire rate limit slot for a domain.

        Uses DomainPolicyManager to get per-domain QPS limits.

        Args:
            url: URL to fetch.
        """
        from src.utils.domain_policy import get_domain_policy_manager

        domain = self._get_domain(url)

        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()

        async with self._domain_locks[domain]:
            last_request = self._domain_last_request.get(domain, 0)

            # Get domain-specific QPS from DomainPolicyManager
            policy_manager = get_domain_policy_manager()
            domain_policy = policy_manager.get_policy(domain)
            min_interval = domain_policy.min_request_interval

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
    """HTTP client fetcher using curl_cffi.

    Features:
    - Chrome impersonation for fingerprint consistency
    - IPv6-first with automatic IPv4 fallback (Happy Eyeballs-style)
    - Per-domain IPv6 success rate learning
    - Conditional requests (ETag/If-Modified-Since) for 304 cache
    """

    def __init__(self) -> None:
        self._rate_limiter = RateLimiter()
        self._settings = get_settings()
        from src.crawler.ipv6_manager import get_ipv6_manager

        self._ipv6_manager = get_ipv6_manager()

    async def fetch(
        self,
        url: str,
        *,
        referer: str | None = None,
        headers: dict[str, str] | None = None,
        use_tor: bool = False,
        cached_etag: str | None = None,
        cached_last_modified: str | None = None,
    ) -> FetchResult:
        """Fetch URL using HTTP client with conditional request support.

        Implements sec-fetch-* header requirements:
        - Sec-Fetch-Site: Relationship between initiator and target
        - Sec-Fetch-Mode: Request mode (navigate for document fetch)
        - Sec-Fetch-Dest: Request destination (document for pages)
        - Sec-Fetch-User: ?1 for user-initiated navigation

        Args:
            url: URL to fetch.
            referer: Referer header.
            headers: Additional headers.
            use_tor: Whether to use Tor.
            cached_etag: ETag from cache for conditional request.
            cached_last_modified: Last-Modified from cache for conditional request.

        Returns:
            FetchResult instance.
        """
        await self._rate_limiter.acquire(url)

        try:
            from curl_cffi import requests as curl_requests

            # Prepare base headers
            req_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            }

            # Generate Sec-Fetch-* headers
            nav_context = NavigationContext(
                target_url=url,
                referer_url=referer,
                is_user_initiated=True,
                destination=SecFetchDest.DOCUMENT,
            )
            sec_fetch_headers = generate_sec_fetch_headers(nav_context)
            req_headers.update(sec_fetch_headers.to_dict())

            if referer:
                req_headers["Referer"] = referer

            # Add conditional request headers for 304 support
            # URL-specific cached values take precedence over session-level values
            # to ensure correct ETag/Last-Modified for each URL
            if cached_etag:
                req_headers["If-None-Match"] = cached_etag
            if cached_last_modified:
                req_headers["If-Modified-Since"] = cached_last_modified

            # Apply session transfer headers
            # Exclude conditional headers if URL-specific values are already set
            # to prevent session-level ETag/Last-Modified from overwriting URL-specific values
            try:
                from src.crawler.session_transfer import get_transfer_headers

                include_conditional = not (cached_etag or cached_last_modified)
                transfer_result = get_transfer_headers(url, include_conditional=include_conditional)

                if transfer_result.ok and transfer_result.headers:
                    req_headers.update(transfer_result.headers)
                    logger.debug(
                        "Applied session transfer headers",
                        url=url[:80],
                        session_id=transfer_result.session_id,
                        header_count=len(transfer_result.headers),
                    )
            except Exception as e:
                logger.debug(
                    "Session transfer header application failed (non-critical)",
                    url=url[:80],
                    error=str(e),
                )

            if headers:
                req_headers.update(headers)

            # Configure proxy if using Tor
            # Use DNS policy manager to ensure DNS is resolved through Tor (socks5h://)
            # when using Tor route, preventing DNS leaks
            dns_manager = get_dns_policy_manager()
            proxies = dns_manager.get_proxy_dict(use_tor)

            # Execute request with Chrome impersonation
            response = curl_requests.get(
                url,
                headers=req_headers,
                proxies=cast(Any, proxies),
                impersonate="chrome",
                timeout=self._settings.crawler.request_timeout,
                allow_redirects=True,
            )

            # Extract response headers
            resp_headers = dict(response.headers)

            # Extract ETag and Last-Modified from response
            resp_etag = resp_headers.get("etag") or resp_headers.get("ETag")
            resp_last_modified = resp_headers.get("last-modified") or resp_headers.get(
                "Last-Modified"
            )

            # Handle 304 Not Modified response
            if response.status_code == 304:
                logger.info(
                    "HTTP 304 Not Modified - using cached content",
                    url=url[:80],
                )
                return FetchResult(
                    ok=True,
                    url=url,
                    status=304,
                    headers=resp_headers,
                    method="http_client",
                    from_cache=True,
                    etag=resp_etag or cached_etag,
                    last_modified=resp_last_modified or cached_last_modified,
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

            # Save content - import from fetcher to avoid circular dependency
            from src.crawler.fetcher import _save_content, _save_warc

            content_hash = hashlib.sha256(response.content).hexdigest()
            html_path = await _save_content(url, response.content, response.headers)

            # Save WARC archive
            warc_path = await _save_warc(
                url,
                response.content,
                response.status_code,
                resp_headers,
                request_headers=req_headers,
            )

            # Record HTTP client request for HTTP/3 policy tracking
            # HTTP client uses HTTP/2 by default, not HTTP/3
            domain = urlparse(url).netloc.lower()
            http3_manager = get_http3_policy_manager()
            await http3_manager.record_request(
                HTTP3RequestResult(
                    domain=domain,
                    url=url,
                    route="http_client",
                    success=True,
                    protocol=ProtocolVersion.HTTP_2,  # curl_cffi uses HTTP/2
                    status_code=response.status_code,
                )
            )

            logger.info(
                "HTTP fetch success",
                url=url[:80],
                status=response.status_code,
                content_length=len(response.content),
                has_etag=bool(resp_etag),
                has_last_modified=bool(resp_last_modified),
            )

            return FetchResult(
                ok=True,
                url=url,
                final_url=str(response.url),  # Track final URL after redirects
                status=response.status_code,
                headers=resp_headers,
                html_path=str(html_path) if html_path else None,
                warc_path=str(warc_path) if warc_path else None,
                content_hash=content_hash,
                method="http_client",
                from_cache=False,
                etag=resp_etag,
                last_modified=resp_last_modified,
            )

        except Exception as e:
            logger.error("HTTP fetch error", url=url, error=str(e))

            # Record failed HTTP client request for HTTP/3 policy tracking
            domain = urlparse(url).netloc.lower()
            http3_manager = get_http3_policy_manager()
            await http3_manager.record_request(
                HTTP3RequestResult(
                    domain=domain,
                    url=url,
                    route="http_client",
                    success=False,
                    protocol=ProtocolVersion.UNKNOWN,
                    error=str(e),
                )
            )

            return FetchResult(
                ok=False,
                url=url,
                reason=str(e),
                method="http_client",
            )

