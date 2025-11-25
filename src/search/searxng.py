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


class QueryExpander:
    """Query expansion using SudachiPy for Japanese text analysis."""
    
    def __init__(self):
        """Initialize query expander."""
        self._tokenizer = None
        self._tokenize_mode = None
        self._synonym_dict: dict[str, list[str]] = {}
        self._initialized = False
    
    def _ensure_initialized(self) -> bool:
        """Ensure SudachiPy is initialized."""
        if self._initialized:
            return self._tokenizer is not None
        
        self._initialized = True
        try:
            from sudachipy import dictionary, tokenizer
            
            self._tokenizer = dictionary.Dictionary().create()
            self._tokenize_mode = tokenizer.Tokenizer.SplitMode.A
            
            # Initialize basic synonym dictionary
            self._init_synonym_dict()
            
            logger.debug("SudachiPy initialized for query expansion")
            return True
        except ImportError:
            logger.warning("SudachiPy not available for query expansion")
            return False
    
    def _init_synonym_dict(self) -> None:
        """Initialize built-in synonym dictionary for common terms."""
        # Common synonym mappings (Japanese)
        self._synonym_dict = {
            # General terms
            "問題": ["課題", "イシュー", "トラブル"],
            "方法": ["やり方", "手法", "手段", "アプローチ"],
            "理由": ["原因", "要因", "わけ"],
            "結果": ["成果", "結論", "アウトプット"],
            "目的": ["目標", "ゴール", "狙い"],
            "利点": ["メリット", "長所", "強み"],
            "欠点": ["デメリット", "短所", "弱み"],
            "影響": ["インパクト", "効果", "作用"],
            "比較": ["対比", "比べる", "違い"],
            "分析": ["解析", "アナリシス", "調査"],
            # Tech terms
            "AI": ["人工知能", "エーアイ", "機械知能"],
            "人工知能": ["AI", "エーアイ", "機械知能"],
            "機械学習": ["マシンラーニング", "ML"],
            "深層学習": ["ディープラーニング", "DL"],
            "データ": ["情報", "データセット"],
            "セキュリティ": ["安全性", "セキュリティー"],
            "プログラミング": ["コーディング", "開発"],
            "アルゴリズム": ["算法", "手順"],
            "システム": ["仕組み", "体制"],
            "ネットワーク": ["通信網", "回線網"],
            # Business terms
            "企業": ["会社", "事業者", "法人"],
            "市場": ["マーケット", "市況"],
            "戦略": ["ストラテジー", "方針"],
            "顧客": ["お客様", "クライアント", "ユーザー"],
            "製品": ["プロダクト", "商品"],
            "サービス": ["サービス提供", "提供物"],
        }
    
    def tokenize(self, text: str) -> list[dict[str, Any]]:
        """Tokenize text and extract token information.
        
        Args:
            text: Input text.
            
        Returns:
            List of token info dicts.
        """
        if not self._ensure_initialized():
            # Fallback: simple space-based tokenization
            return [{"surface": w, "normalized": w, "pos": "unknown"} 
                    for w in text.split()]
        
        tokens = []
        for m in self._tokenizer.tokenize(text, self._tokenize_mode):
            tokens.append({
                "surface": m.surface(),
                "normalized": m.normalized_form(),
                "reading": m.reading_form(),
                "pos": m.part_of_speech()[0] if m.part_of_speech() else "unknown",
                "pos_detail": m.part_of_speech(),
            })
        return tokens
    
    def get_synonyms(self, word: str) -> list[str]:
        """Get synonyms for a word.
        
        Args:
            word: Input word.
            
        Returns:
            List of synonym words.
        """
        synonyms = set()
        
        # Check direct mapping
        if word in self._synonym_dict:
            synonyms.update(self._synonym_dict[word])
        
        # Check reverse mapping (if word is a synonym of another)
        for base, syns in self._synonym_dict.items():
            if word in syns:
                synonyms.add(base)
                synonyms.update(s for s in syns if s != word)
        
        return list(synonyms)
    
    def expand_with_normalized_forms(self, query: str) -> list[str]:
        """Expand query using normalized forms.
        
        Args:
            query: Original query.
            
        Returns:
            List of expanded queries with normalized forms.
        """
        expanded = [query]
        
        tokens = self.tokenize(query)
        
        # Find tokens where surface differs from normalized form
        variations = []
        for token in tokens:
            surface = token["surface"]
            normalized = token["normalized"]
            
            if surface != normalized and normalized:
                # Create variation by replacing surface with normalized
                variations.append((surface, normalized))
        
        # Generate variations
        for surface, normalized in variations:
            variant = query.replace(surface, normalized, 1)
            if variant != query and variant not in expanded:
                expanded.append(variant)
        
        return expanded
    
    def expand_with_synonyms(self, query: str, max_expansions: int = 3) -> list[str]:
        """Expand query using synonyms.
        
        Args:
            query: Original query.
            max_expansions: Maximum number of synonym expansions.
            
        Returns:
            List of expanded queries.
        """
        expanded = [query]
        
        tokens = self.tokenize(query)
        
        # Find content words (nouns, verbs, adjectives) with synonyms
        expansion_candidates = []
        
        for token in tokens:
            surface = token["surface"]
            pos = token["pos"]
            
            # Only expand content words
            if pos in ["名詞", "動詞", "形容詞"]:
                synonyms = self.get_synonyms(surface)
                if synonyms:
                    expansion_candidates.append((surface, synonyms))
        
        # Generate variations (limit to avoid explosion)
        for surface, synonyms in expansion_candidates[:max_expansions]:
            for syn in synonyms[:2]:  # Limit synonyms per word
                variant = query.replace(surface, syn, 1)
                if variant != query and variant not in expanded:
                    expanded.append(variant)
        
        return expanded[:max_expansions + 1]  # Limit total expansions
    
    def generate_variants(
        self,
        query: str,
        include_normalized: bool = True,
        include_synonyms: bool = True,
        max_results: int = 5,
    ) -> list[str]:
        """Generate query variants using multiple strategies.
        
        Args:
            query: Original query.
            include_normalized: Include normalized form variants.
            include_synonyms: Include synonym variants.
            max_results: Maximum number of results.
            
        Returns:
            List of query variants (including original).
        """
        variants = [query]
        
        if include_normalized:
            normalized = self.expand_with_normalized_forms(query)
            for v in normalized:
                if v not in variants:
                    variants.append(v)
        
        if include_synonyms:
            synonyms = self.expand_with_synonyms(query)
            for v in synonyms:
                if v not in variants:
                    variants.append(v)
        
        return variants[:max_results]


# Global query expander instance
_query_expander: QueryExpander | None = None


def _get_query_expander() -> QueryExpander:
    """Get or create the global query expander."""
    global _query_expander
    if _query_expander is None:
        _query_expander = QueryExpander()
    return _query_expander


async def expand_query(
    base_query: str,
    expansion_type: str = "all",
    language: str = "ja",
    max_results: int = 5,
) -> list[str]:
    """Expand a query with related terms.
    
    Uses SudachiPy for Japanese text analysis to generate query variations
    through synonym expansion and normalized form conversion.
    
    Args:
        base_query: Original query.
        expansion_type: Type of expansion:
            - "synonyms": Synonym-based expansion only
            - "normalized": Normalized form expansion only
            - "all": Both synonym and normalized expansion
        language: Query language (currently supports "ja").
        max_results: Maximum number of expanded queries.
        
    Returns:
        List of expanded queries (including original).
    """
    if not base_query.strip():
        return [base_query]
    
    expander = _get_query_expander()
    
    include_normalized = expansion_type in ["all", "normalized"]
    include_synonyms = expansion_type in ["all", "synonyms"]
    
    # For non-Japanese, return original only (expansion not supported)
    if language != "ja":
        logger.debug("Query expansion not supported for language", language=language)
        return [base_query]
    
    variants = expander.generate_variants(
        base_query,
        include_normalized=include_normalized,
        include_synonyms=include_synonyms,
        max_results=max_results,
    )
    
    logger.debug(
        "Query expanded",
        original=base_query,
        variant_count=len(variants),
        variants=variants[:3],  # Log first 3 for brevity
    )
    
    return variants


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

