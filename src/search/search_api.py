"""
Search integration for Lancet.

Provides unified search interface through provider abstraction.
Uses BrowserSearchProvider by default.

Key functions:
- search_serp() - Execute search queries (uses provider system)
- expand_query() - Query expansion with synonyms
- generate_mirror_query() - Cross-language query generation
- QueryOperatorProcessor - Parse and transform search operators

BrowserSearchProvider handles all searches:
- Uses the user's browser profile (Cookie/fingerprint)
- Enables CAPTCHA resolution via manual intervention (§3.6.1)
- Maintains session consistency with fetch operations
"""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import yaml

from src.utils.config import get_settings
from src.utils.logging import get_logger, CausalTrace
from src.storage.database import get_database

logger = get_logger(__name__)


# ============================================================================
# Search Errors (for propagation to MCP layer)
# ============================================================================


class SearchError(Exception):
    """Base exception for search operations.
    
    Carries error details for proper MCP error response generation.
    """
    
    def __init__(
        self,
        message: str,
        *,
        error_type: str = "search_failed",
        query: str | None = None,
        engine: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.query = query
        self.engine = engine
        self.details = details or {}


class ParserNotAvailableSearchError(SearchError):
    """Raised when no parser is available for the selected engine."""
    
    def __init__(self, engine: str, available_engines: list[str] | None = None):
        super().__init__(
            f"No parser available for engine: {engine}",
            error_type="parser_not_available",
            engine=engine,
            details={"available_engines": available_engines} if available_engines else {},
        )
        self.available_engines = available_engines


class SerpSearchError(SearchError):
    """Raised when SERP search fails."""
    
    def __init__(
        self,
        message: str,
        query: str | None = None,
        engine: str | None = None,
        provider_error: str | None = None,
    ):
        super().__init__(
            message,
            error_type="serp_search_failed",
            query=query,
            engine=engine,
            details={"provider_error": provider_error} if provider_error else {},
        )
        self.provider_error = provider_error


# ============================================================================
# Query Operator Processing (§3.1.1, §3.1.4 in docs/requirements.md)
# ============================================================================


@dataclass
class ParsedOperator:
    """Parsed search operator."""
    operator_type: str  # site, filetype, intitle, exact, exclude, date_after, required
    value: str  # The value (e.g., domain for site:, type for filetype:)
    raw_text: str  # Original text in query


@dataclass
class ParsedQuery:
    """Query with parsed operators and base text."""
    base_query: str  # Query without operators
    operators: list[ParsedOperator] = field(default_factory=list)
    
    def has_operator(self, op_type: str) -> bool:
        """Check if query has a specific operator type."""
        return any(op.operator_type == op_type for op in self.operators)
    
    def get_operators(self, op_type: str) -> list[ParsedOperator]:
        """Get all operators of a specific type."""
        return [op for op in self.operators if op.operator_type == op_type]


class QueryOperatorProcessor:
    """
    Parse and transform search operators for different engines.
    
    Supports:
    - site:domain.com  - Restrict to specific domain
    - filetype:pdf     - Restrict to file type
    - intitle:text     - Search in title
    - "exact phrase"   - Exact phrase match
    - -term            - Exclude term
    - +term            - Required term
    - after:YYYY-MM-DD - Date filter
    
    Implements engine-specific mapping from config/engines.yaml (§3.1.4).
    Uses SearchEngineConfigManager for centralized configuration.
    """
    
    # Regex patterns for operator detection
    PATTERNS = {
        # site:domain.com
        "site": re.compile(r'\bsite:([^\s]+)', re.IGNORECASE),
        # filetype:pdf
        "filetype": re.compile(r'\bfiletype:(\w+)', re.IGNORECASE),
        # intitle:word or intitle:"phrase"
        "intitle": re.compile(r'\bintitle:(?:"([^"]+)"|([^\s]+))', re.IGNORECASE),
        # "exact phrase"
        "exact": re.compile(r'"([^"]+)"'),
        # -excluded (but not negative numbers like -123)
        "exclude": re.compile(r'(?<![:\w])-([a-zA-Z\u3040-\u9fff][^\s]*)', re.IGNORECASE),
        # +required
        "required": re.compile(r'(?<![:\w])\+([a-zA-Z\u3040-\u9fff][^\s]*)', re.IGNORECASE),
        # after:2024-01-01 or after:2024
        "date_after": re.compile(r'\bafter:(\d{4}(?:-\d{2}(?:-\d{2})?)?)', re.IGNORECASE),
    }
    
    def __init__(self, config_path: str | None = None):
        """Initialize with optional custom config path.
        
        Args:
            config_path: Optional path to engines.yaml. If None, uses
                         SearchEngineConfigManager singleton.
        """
        self._operator_mapping: dict[str, dict[str, str | None]] = {}
        self._config_manager = None
        self._load_config(config_path)
    
    def _load_config(self, config_path: str | None = None) -> None:
        """Load operator mapping from SearchEngineConfigManager or config file.
        
        Uses SearchEngineConfigManager by default for centralized config.
        Falls back to direct file loading for custom paths or testing.
        """
        # Try to use SearchEngineConfigManager
        try:
            from src.search.engine_config import get_engine_config_manager
            
            if config_path is None:
                self._config_manager = get_engine_config_manager()
                self._operator_mapping = self._config_manager.get_all_operator_mappings()
                logger.debug(
                    "Loaded operator mapping from SearchEngineConfigManager",
                    operators=list(self._operator_mapping.keys()),
                )
                return
        except ImportError:
            logger.debug("SearchEngineConfigManager not available, falling back to direct load")
        
        # Fallback: direct file loading (for custom paths or when manager not available)
        import os
        
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(base_dir, "config", "engines.yaml")
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            
            if config and "operator_mapping" in config:
                self._operator_mapping = config["operator_mapping"]
                logger.debug("Loaded operator mapping from file", operators=list(self._operator_mapping.keys()))
            else:
                logger.warning("No operator_mapping found in config, using defaults")
                self._init_default_mapping()
        except FileNotFoundError:
            logger.warning("Config file not found, using default operator mapping", path=config_path)
            self._init_default_mapping()
        except Exception as e:
            logger.error("Failed to load operator config", error=str(e))
            self._init_default_mapping()
    
    def _init_default_mapping(self) -> None:
        """Initialize default operator mapping."""
        self._operator_mapping = {
            "site": {
                "default": "site:{domain}",
                "google": "site:{domain}",
                "bing": "site:{domain}",
                "duckduckgo": "site:{domain}",
                "qwant": "site:{domain}",
            },
            "filetype": {
                "default": "filetype:{type}",
                "google": "filetype:{type}",
                "bing": "filetype:{type}",
                "duckduckgo": "filetype:{type}",
            },
            "intitle": {
                "default": "intitle:{text}",
                "google": "intitle:{text}",
                "bing": "intitle:{text}",
            },
            "exact": {
                "default": '"{text}"',
                "google": '"{text}"',
                "bing": '"{text}"',
                "duckduckgo": '"{text}"',
            },
            "exclude": {
                "default": "-{term}",
                "google": "-{term}",
                "bing": "-{term}",
            },
            "required": {
                "default": "+{term}",
                "google": "+{term}",
                "bing": "+{term}",
            },
            "date_after": {
                "default": None,  # Not all engines support
                "google": "after:{date}",
            },
        }
    
    def reload_config(self) -> None:
        """Reload operator mappings from SearchEngineConfigManager.
        
        Useful for hot-reload scenarios where config has changed.
        """
        if self._config_manager is not None:
            self._config_manager.reload()
            self._operator_mapping = self._config_manager.get_all_operator_mappings()
            logger.debug("Reloaded operator mapping", operators=list(self._operator_mapping.keys()))
    
    def parse(self, query: str) -> ParsedQuery:
        """
        Parse a query string and extract operators.
        
        Args:
            query: Raw query string with operators.
            
        Returns:
            ParsedQuery with base query and list of operators.
        """
        operators: list[ParsedOperator] = []
        remaining_query = query
        
        # Extract operators in specific order (more specific first)
        extraction_order = ["site", "filetype", "intitle", "date_after", "exact", "exclude", "required"]
        
        for op_type in extraction_order:
            pattern = self.PATTERNS.get(op_type)
            if not pattern:
                continue
            
            matches = list(pattern.finditer(remaining_query))
            for match in reversed(matches):  # Process from end to preserve indices
                raw_text = match.group(0)
                
                # Extract value based on operator type
                if op_type == "intitle":
                    # intitle has two capture groups (quoted and unquoted)
                    value = match.group(1) or match.group(2)
                else:
                    value = match.group(1)
                
                operators.append(ParsedOperator(
                    operator_type=op_type,
                    value=value,
                    raw_text=raw_text,
                ))
                
                # Remove from query
                remaining_query = remaining_query[:match.start()] + remaining_query[match.end():]
        
        # Clean up base query
        base_query = " ".join(remaining_query.split())
        
        return ParsedQuery(base_query=base_query, operators=operators)
    
    def transform_for_engine(
        self,
        parsed: ParsedQuery,
        engine: str,
    ) -> str:
        """
        Transform parsed query for a specific engine.
        
        Args:
            parsed: Parsed query with operators.
            engine: Target engine name.
            
        Returns:
            Query string formatted for the engine.
        """
        engine_lower = engine.lower()
        parts = [parsed.base_query] if parsed.base_query else []
        
        for op in parsed.operators:
            mapping = self._operator_mapping.get(op.operator_type, {})
            
            # Get engine-specific format or default
            template = mapping.get(engine_lower) or mapping.get("default")
            
            if template is None:
                # Engine doesn't support this operator, skip
                logger.debug(
                    "Operator not supported by engine",
                    operator=op.operator_type,
                    engine=engine,
                )
                continue
            
            # Format the operator
            try:
                if op.operator_type == "site":
                    formatted = template.format(domain=op.value)
                elif op.operator_type == "filetype":
                    formatted = template.format(type=op.value)
                elif op.operator_type in ("intitle", "exact"):
                    formatted = template.format(text=op.value)
                elif op.operator_type in ("exclude", "required"):
                    formatted = template.format(term=op.value)
                elif op.operator_type == "date_after":
                    formatted = template.format(date=op.value)
                else:
                    formatted = template.format(value=op.value)
                
                parts.append(formatted)
            except KeyError as e:
                logger.warning(
                    "Failed to format operator",
                    operator=op.operator_type,
                    template=template,
                    error=str(e),
                )
        
        return " ".join(parts)
    
    def process_query(
        self,
        query: str,
        engine: str | None = None,
    ) -> str:
        """
        Parse and transform query in one step.
        
        Args:
            query: Raw query with operators.
            engine: Target engine (None for default format).
            
        Returns:
            Processed query string.
        """
        parsed = self.parse(query)
        return self.transform_for_engine(parsed, engine or "default")
    
    def get_supported_operators(self, engine: str) -> list[str]:
        """Get list of operators supported by an engine."""
        engine_lower = engine.lower()
        supported = []
        
        for op_type, mapping in self._operator_mapping.items():
            if mapping.get(engine_lower) is not None or mapping.get("default") is not None:
                supported.append(op_type)
        
        return supported
    
    def build_query(
        self,
        base_query: str,
        site: str | None = None,
        filetype: str | None = None,
        intitle: str | None = None,
        exact_phrases: list[str] | None = None,
        exclude_terms: list[str] | None = None,
        required_terms: list[str] | None = None,
        date_after: str | None = None,
        engine: str | None = None,
    ) -> str:
        """
        Build a query with operators programmatically.
        
        Args:
            base_query: Base search terms.
            site: Domain restriction.
            filetype: File type restriction.
            intitle: Title search term.
            exact_phrases: List of exact phrases.
            exclude_terms: Terms to exclude.
            required_terms: Required terms.
            date_after: Date filter (YYYY-MM-DD or YYYY).
            engine: Target engine.
            
        Returns:
            Formatted query string.
        """
        operators = []
        
        if site:
            operators.append(ParsedOperator("site", site, f"site:{site}"))
        
        if filetype:
            operators.append(ParsedOperator("filetype", filetype, f"filetype:{filetype}"))
        
        if intitle:
            operators.append(ParsedOperator("intitle", intitle, f"intitle:{intitle}"))
        
        if exact_phrases:
            for phrase in exact_phrases:
                operators.append(ParsedOperator("exact", phrase, f'"{phrase}"'))
        
        if exclude_terms:
            for term in exclude_terms:
                operators.append(ParsedOperator("exclude", term, f"-{term}"))
        
        if required_terms:
            for term in required_terms:
                operators.append(ParsedOperator("required", term, f"+{term}"))
        
        if date_after:
            operators.append(ParsedOperator("date_after", date_after, f"after:{date_after}"))
        
        parsed = ParsedQuery(base_query=base_query, operators=operators)
        return self.transform_for_engine(parsed, engine or "default")


# Global operator processor instance
_operator_processor: QueryOperatorProcessor | None = None


def _get_operator_processor() -> QueryOperatorProcessor:
    """Get or create the global operator processor."""
    global _operator_processor
    if _operator_processor is None:
        _operator_processor = QueryOperatorProcessor()
    return _operator_processor


def parse_query_operators(query: str) -> ParsedQuery:
    """
    Parse operators from a query string.
    
    Args:
        query: Raw query with operators.
        
    Returns:
        ParsedQuery with base query and operators.
    """
    processor = _get_operator_processor()
    return processor.parse(query)


def transform_query_for_engine(query: str, engine: str) -> str:
    """
    Transform a query for a specific search engine.
    
    Args:
        query: Raw query with operators.
        engine: Target engine name.
        
    Returns:
        Query formatted for the engine.
    """
    processor = _get_operator_processor()
    return processor.process_query(query, engine)


def build_search_query(
    base_query: str,
    site: str | None = None,
    filetype: str | None = None,
    intitle: str | None = None,
    exact_phrases: list[str] | None = None,
    exclude_terms: list[str] | None = None,
    required_terms: list[str] | None = None,
    date_after: str | None = None,
    engine: str | None = None,
) -> str:
    """
    Build a search query with operators.
    
    Convenience function for programmatically building queries.
    
    Args:
        base_query: Base search terms.
        site: Domain restriction (e.g., "go.jp").
        filetype: File type (e.g., "pdf").
        intitle: Title search term.
        exact_phrases: List of exact phrases to match.
        exclude_terms: Terms to exclude.
        required_terms: Required terms.
        date_after: Date filter (YYYY-MM-DD or YYYY).
        engine: Target engine for formatting.
        
    Returns:
        Formatted query string.
        
    Example:
        >>> build_search_query(
        ...     "AI規制",
        ...     site="go.jp",
        ...     filetype="pdf",
        ...     exclude_terms=["draft"],
        ... )
        'AI規制 site:go.jp filetype:pdf -draft'
    """
    processor = _get_operator_processor()
    return processor.build_query(
        base_query=base_query,
        site=site,
        filetype=filetype,
        intitle=intitle,
        exact_phrases=exact_phrases,
        exclude_terms=exclude_terms,
        required_terms=required_terms,
        date_after=date_after,
        engine=engine,
    )


# ============================================================================
# Provider-based Search
# ============================================================================


async def _search_with_provider(
    query: str,
    engines: list[str] | None = None,
    limit: int = 10,
    time_range: str = "all",
) -> list[dict[str, Any]]:
    """
    Execute search using the provider abstraction layer.
    
    Uses BrowserSearchProvider for direct browser-based search.
    
    Args:
        query: Search query.
        engines: Engines to use.
        limit: Maximum results.
        time_range: Time filter.
        
    Returns:
        List of normalized result dicts.
    """
    from src.search.provider import SearchOptions, get_registry
    
    # Ensure provider is registered
    registry = get_registry()
    
    # Use BrowserSearchProvider
    if registry.get("browser_search") is None:
        from src.search.browser_search_provider import get_browser_search_provider
        provider = get_browser_search_provider()
        registry.register(provider, set_default=True)
    
    # Set as default if not already
    if registry.get_default() is None or registry.get_default().name != "browser_search":
        if registry.get("browser_search"):
            registry.set_default("browser_search")
    
    # Build options
    options = SearchOptions(
        engines=engines,
        time_range=time_range,
        limit=limit,
    )
    
    # Search via registry (with fallback support)
    response = await registry.search_with_fallback(query, options)
    
    if not response.ok:
        error_msg = response.error or "Unknown search error"
        logger.warning(
            "Search failed",
            query=query[:50],
            provider=response.provider,
            error=error_msg,
        )
        
        # Determine specific error type and raise appropriate exception
        if "No parser available" in error_msg:
            # Extract engine name from error message
            engine_match = error_msg.split("engine:")[-1].strip() if "engine:" in error_msg else None
            from src.search.search_parsers import get_available_parsers
            raise ParserNotAvailableSearchError(
                engine=engine_match or "unknown",
                available_engines=get_available_parsers(),
            )
        else:
            # Generic SERP search failure
            raise SerpSearchError(
                message=f"SERP search failed: {error_msg}",
                query=query[:100] if query else None,
                provider_error=error_msg,
            )
    
    # Convert to dict format for backward compatibility
    return [r.to_dict() for r in response.results]


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
    transform_operators: bool = True,
) -> list[dict[str, Any]]:
    """Execute search and return normalized SERP results.
    
    Uses provider abstraction (BrowserSearchProvider by default).
    
    Args:
        query: Search query (may contain operators like site:, filetype:, etc.).
        engines: List of engines to use.
        limit: Maximum results per engine.
        time_range: Time range filter.
        task_id: Associated task ID.
        use_cache: Whether to use cache.
        transform_operators: Whether to transform query operators for engines.
        
    Returns:
        List of normalized SERP result dicts.
        
    Raises:
        ParserNotAvailableSearchError: When selected engine has no parser.
        SerpSearchError: When SERP search fails for other reasons.
    """
    db = await get_database()
    
    # Parse query operators
    parsed_query = parse_query_operators(query) if transform_operators else None
    
    with CausalTrace() as trace:
        # Check cache (use original query for cache key to ensure consistency)
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
        
        # Transform query operators to engine-specific format
        # Uses default format which works across most search engines
        search_query = query
        if transform_operators and parsed_query and parsed_query.operators:
            processor = _get_operator_processor()
            search_query = processor.transform_for_engine(parsed_query, "default")
            
            # Log operator usage for analytics
            operator_types = [op.operator_type for op in parsed_query.operators]
            logger.debug(
                "Query operators transformed",
                original=query[:100],
                transformed=search_query[:100],
                operators=operator_types,
            )
        
        # Execute search via provider abstraction
        results = await _search_with_provider(
            query=search_query,
            engines=engines,
            limit=limit,
            time_range=time_range,
        )
        
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
        
        # Find content words (nouns, verbs, adjectives) with synonyms
        expansion_candidates = []
        
        # First, check if the query itself (or query words) has synonyms
        # This handles cases where the tokenizer splits compound words
        query_words = query.split()
        for word in query_words:
            word_stripped = word.strip()
            if word_stripped:
                synonyms = self.get_synonyms(word_stripped)
                if synonyms:
                    expansion_candidates.append((word_stripped, synonyms))
        
        # Also check tokenized forms for additional synonyms
        tokens = self.tokenize(query)
        for token in tokens:
            surface = token["surface"]
            pos = token["pos"]
            
            # Only expand content words
            if pos in ["名詞", "動詞", "形容詞", "unknown"]:
                synonyms = self.get_synonyms(surface)
                if synonyms and (surface, synonyms) not in expansion_candidates:
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
    """Generate a mirror query in another language using local LLM.
    
    Implements §3.1.1: Cross-language (JA↔EN) mirror query auto-generation.
    Uses Ollama for translation to maintain Zero OpEx requirement.
    
    Args:
        query: Original query.
        source_lang: Source language code (ja, en, de, fr, zh).
        target_lang: Target language code.
        
    Returns:
        Translated query or None if translation fails.
    """
    if not query.strip():
        return None
    
    # No translation needed for same language
    if source_lang == target_lang:
        return query
    
    # Check cache first
    cache_key = f"mirror:{source_lang}:{target_lang}:{query}"
    cached = _mirror_query_cache.get(cache_key)
    if cached is not None:
        logger.debug("Mirror query cache hit", query=query, target_lang=target_lang)
        return cached
    
    try:
        from src.filter.llm import _get_client
        
        client = _get_client()
        settings = get_settings()
        
        # Language names for prompt
        lang_names = {
            "ja": "日本語",
            "en": "English",
            "de": "Deutsch",
            "fr": "Français",
            "zh": "中文",
        }
        
        source_name = lang_names.get(source_lang, source_lang)
        target_name = lang_names.get(target_lang, target_lang)
        
        # Specialized prompt for search query translation
        # Emphasizes conciseness and keyword preservation
        prompt = f"""Translate the following search query from {source_name} to {target_name}.
Keep it concise and preserve search keywords. Output only the translated query, nothing else.

Query: {query}

Translation:"""
        
        response = await client.generate(
            prompt=prompt,
            model=settings.llm.model,
            temperature=0.1,  # Low temperature for consistent translation
            max_tokens=100,  # Search queries are short
        )
        
        # Clean up response
        translated = response.strip()
        
        # Remove quotes if present
        if translated.startswith('"') and translated.endswith('"'):
            translated = translated[1:-1]
        if translated.startswith("'") and translated.endswith("'"):
            translated = translated[1:-1]
        
        # Validate translation is not empty or same as original
        if not translated or translated == query:
            logger.warning(
                "Mirror query translation failed",
                query=query,
                response=response,
            )
            return None
        
        # Cache successful translation
        _mirror_query_cache[cache_key] = translated
        
        logger.debug(
            "Mirror query generated",
            original=query,
            translated=translated,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        
        return translated
        
    except Exception as e:
        logger.error(
            "Mirror query generation failed",
            query=query,
            error=str(e),
        )
        return None


# Cache for mirror query translations
_mirror_query_cache: dict[str, str] = {}


async def generate_mirror_queries(
    query: str,
    source_lang: str = "ja",
    target_langs: list[str] | None = None,
) -> dict[str, str]:
    """Generate mirror queries in multiple languages.
    
    Args:
        query: Original query.
        source_lang: Source language code.
        target_langs: Target language codes (default: ["en"] for ja, ["ja"] for others).
        
    Returns:
        Dict mapping language codes to translated queries.
    """
    if target_langs is None:
        # Default: Japanese queries get English mirror, others get Japanese
        target_langs = ["en"] if source_lang == "ja" else ["ja"]
    
    results = {source_lang: query}
    
    for target_lang in target_langs:
        if target_lang != source_lang:
            translated = await generate_mirror_query(query, source_lang, target_lang)
            if translated:
                results[target_lang] = translated
    
    return results

