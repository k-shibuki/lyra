"""
SearXNG search provider implementation.

Implements the SearchProvider interface for SearXNG, providing
a standardized way to execute searches through the local SearXNG instance.

Part of Phase 17.1.1: SearchProvider abstraction.
"""

import asyncio
import os
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp

from src.search.provider import (
    BaseSearchProvider,
    HealthState,
    HealthStatus,
    SearchOptions,
    SearchResponse,
    SearchResult,
    SourceTag,
)
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def classify_source(url: str) -> SourceTag:
    """
    Classify source type based on URL.
    
    Args:
        url: Source URL.
        
    Returns:
        SourceTag classification.
    """
    url_lower = url.lower()
    
    # Academic
    academic_domains = [
        "arxiv.org", "pubmed", "ncbi.nlm.nih.gov", "jstage.jst.go.jp",
        "cir.nii.ac.jp", "scholar.google", "researchgate.net",
        "academia.edu", "sciencedirect.com", "springer.com",
    ]
    if any(d in url_lower for d in academic_domains):
        return SourceTag.ACADEMIC
    
    # Government
    gov_patterns = [".gov", ".go.jp", ".gov.uk", ".gouv.fr", ".gov.au"]
    if any(p in url_lower for p in gov_patterns):
        return SourceTag.GOVERNMENT
    
    # Standards / Registry
    standards_domains = ["iso.org", "ietf.org", "w3.org", "iana.org", "ieee.org"]
    if any(d in url_lower for d in standards_domains):
        return SourceTag.STANDARDS
    
    # Wikipedia / Knowledge
    if "wikipedia.org" in url_lower or "wikidata.org" in url_lower:
        return SourceTag.KNOWLEDGE
    
    # News (major outlets)
    news_domains = [
        "reuters.com", "bbc.com", "nytimes.com", "theguardian.com",
        "nhk.or.jp", "asahi.com", "nikkei.com",
    ]
    if any(d in url_lower for d in news_domains):
        return SourceTag.NEWS
    
    # Tech / Documentation
    tech_domains = [
        "github.com", "gitlab.com", "stackoverflow.com", "docs.",
        "developer.", "documentation",
    ]
    if any(d in url_lower for d in tech_domains):
        return SourceTag.TECHNICAL
    
    # Blog indicators
    blog_patterns = ["blog", "medium.com", "note.com", "qiita.com", "zenn.dev"]
    if any(p in url_lower for p in blog_patterns):
        return SourceTag.BLOG
    
    return SourceTag.UNKNOWN


class SearXNGProvider(BaseSearchProvider):
    """
    SearXNG search provider.
    
    Implements the SearchProvider interface for the local SearXNG instance.
    Provides rate limiting, health monitoring, and standardized result format.
    Uses SearchEngineConfigManager for configuration (Phase 17.2.2).
    
    Example:
        provider = SearXNGProvider()
        response = await provider.search("AI regulations", SearchOptions(language="ja"))
        if response.ok:
            for result in response.results:
                print(result.title, result.url)
        await provider.close()
    """
    
    DEFAULT_BASE_URL = "http://localhost:8080"
    DEFAULT_TIMEOUT = 30
    
    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
        min_interval: float | None = None,
    ):
        """
        Initialize SearXNG provider.
        
        Uses SearchEngineConfigManager for default configuration (Phase 17.2.2).
        Falls back to DomainPolicyManager for min_interval if not specified.
        
        Args:
            base_url: SearXNG instance URL. Default: from config or SEARXNG_HOST env.
            timeout: Request timeout in seconds. Default: from config or 30.
            min_interval: Minimum interval between requests in seconds. Default from config.
        """
        super().__init__("searxng")
        
        # Try to get settings from SearchEngineConfigManager first (Phase 17.2.2)
        engine_manager = None
        try:
            from src.search.engine_config import get_engine_config_manager
            engine_manager = get_engine_config_manager()
        except ImportError:
            pass
        
        # Resolve base_url - Environment variable takes highest priority for container deployments
        if base_url is not None:
            self._base_url = base_url
        elif os.environ.get("SEARXNG_HOST"):
            # Environment variable overrides config file (for container/deployment flexibility)
            self._base_url = os.environ["SEARXNG_HOST"]
        elif engine_manager is not None:
            self._base_url = engine_manager.get_searxng_host()
        else:
            self._base_url = self.DEFAULT_BASE_URL
        
        # Resolve timeout
        if timeout is not None:
            self._timeout = timeout
        elif engine_manager is not None:
            self._timeout = engine_manager.get_searxng_timeout()
        else:
            self._timeout = self.DEFAULT_TIMEOUT
        
        # Resolve min_interval
        if min_interval is not None:
            self._min_interval = min_interval
        else:
            # Try DomainPolicyManager for backward compatibility
            from src.utils.domain_policy import get_domain_policy_manager
            policy_manager = get_domain_policy_manager()
            self._min_interval = policy_manager.get_search_engine_min_interval()
        
        self._session: aiohttp.ClientSession | None = None
        self._rate_limiter = asyncio.Semaphore(1)
        self._last_request_time = 0.0
        
        # Health metrics
        self._success_count = 0
        self._failure_count = 0
        self._total_latency = 0.0
        self._last_error: str | None = None
        
        # Store engine manager reference for later use
        self._engine_manager = engine_manager
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout)
            )
        return self._session
    
    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        async with self._rate_limiter:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_time = time.time()
    
    async def search(
        self,
        query: str,
        options: SearchOptions | None = None,
    ) -> SearchResponse:
        """
        Execute a search query against SearXNG.
        
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
        
        try:
            await self._rate_limit()
            
            session = await self._get_session()
            
            # Build request parameters
            params = {
                "q": query,
                "format": "json",
                "language": options.language,
                "pageno": options.page,
            }
            
            if options.engines:
                params["engines"] = ",".join(options.engines)
            
            if options.categories:
                params["categories"] = ",".join(options.categories)
            
            if options.time_range and options.time_range != "all":
                params["time_range"] = options.time_range
            
            url = f"{self._base_url}/search?{urlencode(params)}"
            
            logger.debug(
                "SearXNG request",
                url=url,
                query=query[:50],
                provider=self.name,
            )
            
            async with session.get(url) as response:
                elapsed_ms = (time.time() - start_time) * 1000
                
                if response.status != 200:
                    self._failure_count += 1
                    self._last_error = f"HTTP {response.status}"
                    
                    logger.error(
                        "SearXNG error",
                        status=response.status,
                        query=query[:50],
                        provider=self.name,
                    )
                    
                    return SearchResponse(
                        results=[],
                        query=query,
                        provider=self.name,
                        error=f"HTTP {response.status}",
                        elapsed_ms=elapsed_ms,
                    )
                
                data = await response.json()
                
                # Normalize results
                results = self._normalize_results(data, options.limit)
                
                self._success_count += 1
                self._total_latency += elapsed_ms
                
                logger.info(
                    "SearXNG search completed",
                    query=query[:50],
                    result_count=len(results),
                    elapsed_ms=round(elapsed_ms, 1),
                    provider=self.name,
                )
                
                return SearchResponse(
                    results=results,
                    query=query,
                    provider=self.name,
                    total_count=len(data.get("results", [])),
                    elapsed_ms=elapsed_ms,
                )
                
        except asyncio.TimeoutError:
            self._failure_count += 1
            self._last_error = "Timeout"
            elapsed_ms = (time.time() - start_time) * 1000
            
            logger.error("SearXNG timeout", query=query[:50], provider=self.name)
            
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
                "SearXNG error",
                query=query[:50],
                error=str(e),
                provider=self.name,
            )
            
            return SearchResponse(
                results=[],
                query=query,
                provider=self.name,
                error=str(e),
                elapsed_ms=elapsed_ms,
            )
    
    def _normalize_results(
        self,
        data: dict[str, Any],
        limit: int,
    ) -> list[SearchResult]:
        """
        Normalize SearXNG results to standard format.
        
        Args:
            data: Raw SearXNG response data.
            limit: Maximum results to return.
            
        Returns:
            List of normalized SearchResult objects.
        """
        results = []
        seen_urls: set[str] = set()
        
        for idx, item in enumerate(data.get("results", [])):
            url = item.get("url", "")
            
            # Skip duplicates
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            result = SearchResult(
                title=item.get("title", ""),
                url=url,
                snippet=item.get("content", ""),
                date=item.get("publishedDate"),
                engine=item.get("engine", "unknown"),
                rank=idx + 1,
                source_tag=classify_source(url),
                raw_data=item,
            )
            
            results.append(result)
            
            if len(results) >= limit:
                break
        
        return results
    
    async def get_health(self) -> HealthStatus:
        """
        Get current health status of SearXNG.
        
        Returns:
            HealthStatus based on recent metrics.
        """
        if self._is_closed:
            return HealthStatus.unhealthy("Provider closed")
        
        total = self._success_count + self._failure_count
        
        if total == 0:
            return HealthStatus(
                state=HealthState.UNKNOWN,
                message="No requests made yet",
            )
        
        success_rate = self._success_count / total
        avg_latency = self._total_latency / total if total > 0 else 0
        
        if success_rate >= 0.9:
            return HealthStatus.healthy(latency_ms=avg_latency)
        elif success_rate >= 0.5:
            return HealthStatus.degraded(
                success_rate=success_rate,
                message=self._last_error,
            )
        else:
            return HealthStatus.unhealthy(message=self._last_error)
    
    async def close(self) -> None:
        """Close HTTP session and cleanup."""
        if self._session and not self._session.closed:
            await self._session.close()
        
        await super().close()
    
    def reset_metrics(self) -> None:
        """Reset health metrics. For testing purposes."""
        self._success_count = 0
        self._failure_count = 0
        self._total_latency = 0.0
        self._last_error = None


# ============================================================================
# Factory and Convenience Functions
# ============================================================================


_default_provider: SearXNGProvider | None = None


def get_searxng_provider() -> SearXNGProvider:
    """
    Get or create the default SearXNG provider instance.
    
    Returns:
        SearXNGProvider singleton instance.
    """
    global _default_provider
    if _default_provider is None:
        _default_provider = SearXNGProvider()
    return _default_provider


async def cleanup_searxng_provider() -> None:
    """
    Close and cleanup the default SearXNG provider.
    
    Used for testing cleanup and graceful shutdown.
    """
    global _default_provider
    if _default_provider is not None:
        await _default_provider.close()
        _default_provider = None


def reset_searxng_provider() -> None:
    """
    Reset the default provider. For testing purposes only.
    """
    global _default_provider
    _default_provider = None

