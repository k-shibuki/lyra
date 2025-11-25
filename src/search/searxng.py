"""
SearXNG integration for Lancet.
Handles search queries through the local SearXNG instance.
"""

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, quote_plus

import aiohttp

from src.utils.config import get_settings
from src.utils.logging import get_logger, CausalTrace
from src.storage.database import get_database

logger = get_logger(__name__)


class SearXNGClient:
    """Client for interacting with SearXNG."""
    
    def __init__(self):
        """Initialize SearXNG client."""
        import os
        self.settings = get_settings()
        # Use environment variable or default
        self.base_url = os.environ.get("SEARXNG_HOST", "http://localhost:8080")
        self._session: aiohttp.ClientSession | None = None
        self._rate_limiter = asyncio.Semaphore(1)
        self._last_request_time = 0.0
        self._min_interval = 4.0  # QPS = 0.25
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session
    
    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _rate_limit(self) -> None:
        """Apply rate limiting."""
        async with self._rate_limiter:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_time = time.time()
    
    async def search(
        self,
        query: str,
        engines: list[str] | None = None,
        categories: list[str] | None = None,
        language: str = "ja",
        time_range: str | None = None,
        pageno: int = 1,
    ) -> dict[str, Any]:
        """Execute a search query.
        
        Args:
            query: Search query text.
            engines: List of engines to use.
            categories: List of categories.
            language: Search language.
            time_range: Time range filter (day, week, month, year).
            pageno: Page number.
            
        Returns:
            Search results dictionary.
        """
        await self._rate_limit()
        
        session = await self._get_session()
        
        params = {
            "q": query,
            "format": "json",
            "language": language,
            "pageno": pageno,
        }
        
        if engines:
            params["engines"] = ",".join(engines)
        
        if categories:
            params["categories"] = ",".join(categories)
        
        if time_range and time_range != "all":
            params["time_range"] = time_range
        
        url = f"{self.base_url}/search?{urlencode(params)}"
        
        logger.debug("SearXNG request", url=url, query=query)
        
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(
                        "SearXNG error",
                        status=response.status,
                        query=query,
                    )
                    return {"results": [], "error": f"HTTP {response.status}"}
                
                data = await response.json()
                
                logger.info(
                    "SearXNG search completed",
                    query=query[:50],
                    result_count=len(data.get("results", [])),
                )
                
                return data
                
        except asyncio.TimeoutError:
            logger.error("SearXNG timeout", query=query)
            return {"results": [], "error": "Timeout"}
        except Exception as e:
            logger.error("SearXNG error", query=query, error=str(e))
            return {"results": [], "error": str(e)}


# Global client instance
_client: SearXNGClient | None = None


def _get_client() -> SearXNGClient:
    """Get or create the global SearXNG client."""
    global _client
    if _client is None:
        _client = SearXNGClient()
    return _client


def _normalize_query(query: str) -> str:
    """Normalize query for caching.
    
    Args:
        query: Search query.
        
    Returns:
        Normalized query string.
    """
    # Lowercase, strip whitespace, normalize spaces
    return " ".join(query.lower().split())


def _get_cache_key(query: str, engines: list[str] | None, time_range: str) -> str:
    """Generate cache key for SERP results.
    
    Args:
        query: Normalized query.
        engines: Engine list.
        time_range: Time range.
        
    Returns:
        Cache key hash.
    """
    key_parts = [
        _normalize_query(query),
        ",".join(sorted(engines)) if engines else "default",
        time_range or "all",
    ]
    key_str = "|".join(key_parts)
    return hashlib.sha256(key_str.encode()).hexdigest()[:32]


async def search_serp(
    query: str,
    engines: list[str] | None = None,
    limit: int = 10,
    time_range: str = "all",
    task_id: str | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Execute search and return normalized SERP results.
    
    Args:
        query: Search query.
        engines: List of engines to use.
        limit: Maximum results per engine.
        time_range: Time range filter.
        task_id: Associated task ID.
        use_cache: Whether to use cache.
        
    Returns:
        List of normalized SERP result dicts.
    """
    db = await get_database()
    
    with CausalTrace() as trace:
        # Check cache
        cache_key = _get_cache_key(query, engines, time_range)
        
        if use_cache:
            cached = await db.fetch_one(
                """
                SELECT result_json FROM cache_serp 
                WHERE cache_key = ? AND expires_at > ?
                """,
                (cache_key, datetime.now(timezone.utc).isoformat()),
            )
            
            if cached:
                logger.info("SERP cache hit", query=query[:50], cache_key=cache_key)
                await db.execute(
                    "UPDATE cache_serp SET hit_count = hit_count + 1 WHERE cache_key = ?",
                    (cache_key,),
                )
                return json.loads(cached["result_json"])
        
        # Execute search
        client = _get_client()
        raw_results = await client.search(
            query=query,
            engines=engines,
            time_range=time_range if time_range != "all" else None,
        )
        
        # Normalize results
        results = []
        seen_urls = set()
        
        for idx, item in enumerate(raw_results.get("results", [])):
            url = item.get("url", "")
            
            # Skip duplicates
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            # Normalize to standard schema
            result = {
                "title": item.get("title", ""),
                "url": url,
                "snippet": item.get("content", ""),
                "date": item.get("publishedDate"),
                "engine": item.get("engine", "unknown"),
                "rank": idx + 1,
                "source_tag": _classify_source(url),
            }
            
            results.append(result)
            
            if len(results) >= limit:
                break
        
        # Store in database
        if task_id:
            query_id = await db.insert("queries", {
                "task_id": task_id,
                "query_text": query,
                "query_type": "initial",
                "engines_used": json.dumps(engines) if engines else None,
                "result_count": len(results),
                "cause_id": trace.id,
            })
            
            # Store SERP items
            for result in results:
                await db.insert("serp_items", {
                    "query_id": query_id,
                    "engine": result["engine"],
                    "rank": result["rank"],
                    "url": result["url"],
                    "title": result["title"],
                    "snippet": result["snippet"],
                    "published_date": result.get("date"),
                    "source_tag": result["source_tag"],
                    "cause_id": trace.id,
                })
        
        # Cache results
        if use_cache and results:
            settings = get_settings()
            expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.storage.serp_cache_ttl)
            
            await db.insert("cache_serp", {
                "cache_key": cache_key,
                "query_normalized": _normalize_query(query),
                "engines_json": json.dumps(engines) if engines else "[]",
                "time_range": time_range,
                "result_json": json.dumps(results, ensure_ascii=False),
                "expires_at": expires_at.isoformat(),
            }, or_replace=True, auto_id=False)
        
        logger.info(
            "SERP search completed",
            query=query[:50],
            result_count=len(results),
            task_id=task_id,
            cause_id=trace.id,
        )
        
        return results


def _classify_source(url: str) -> str:
    """Classify source type based on URL.
    
    Args:
        url: Source URL.
        
    Returns:
        Source tag (academic, government, news, blog, etc.).
    """
    url_lower = url.lower()
    
    # Academic
    academic_domains = [
        "arxiv.org", "pubmed", "ncbi.nlm.nih.gov", "jstage.jst.go.jp",
        "cir.nii.ac.jp", "scholar.google", "researchgate.net",
        "academia.edu", "sciencedirect.com", "springer.com",
    ]
    if any(d in url_lower for d in academic_domains):
        return "academic"
    
    # Government
    gov_patterns = [".gov", ".go.jp", ".gov.uk", ".gouv.fr", ".gov.au"]
    if any(p in url_lower for p in gov_patterns):
        return "government"
    
    # Standards / Registry
    standards_domains = ["iso.org", "ietf.org", "w3.org", "iana.org", "ieee.org"]
    if any(d in url_lower for d in standards_domains):
        return "standards"
    
    # Wikipedia / Knowledge
    if "wikipedia.org" in url_lower or "wikidata.org" in url_lower:
        return "knowledge"
    
    # News (major outlets)
    news_domains = [
        "reuters.com", "bbc.com", "nytimes.com", "theguardian.com",
        "nhk.or.jp", "asahi.com", "nikkei.com",
    ]
    if any(d in url_lower for d in news_domains):
        return "news"
    
    # Tech / Documentation
    tech_domains = [
        "github.com", "gitlab.com", "stackoverflow.com", "docs.",
        "developer.", "documentation",
    ]
    if any(d in url_lower for d in tech_domains):
        return "technical"
    
    # Blog indicators
    blog_patterns = ["blog", "medium.com", "note.com", "qiita.com", "zenn.dev"]
    if any(p in url_lower for p in blog_patterns):
        return "blog"
    
    return "unknown"


async def expand_query(
    base_query: str,
    expansion_type: str = "synonyms",
    language: str = "ja",
) -> list[str]:
    """Expand a query with related terms.
    
    Args:
        base_query: Original query.
        expansion_type: Type of expansion (synonyms, hyponyms, related).
        language: Query language.
        
    Returns:
        List of expanded queries.
    """
    # TODO: Implement SudachiPy-based expansion
    # For now, return just the base query
    expanded = [base_query]
    
    # Add simple variations
    if language == "ja":
        # Japanese-specific expansions would go here
        pass
    
    return expanded


async def generate_mirror_query(
    query: str,
    source_lang: str = "ja",
    target_lang: str = "en",
) -> str | None:
    """Generate a mirror query in another language.
    
    Args:
        query: Original query.
        source_lang: Source language.
        target_lang: Target language.
        
    Returns:
        Translated query or None if translation fails.
    """
    # TODO: Implement local LLM-based translation
    # For now, return None
    return None

