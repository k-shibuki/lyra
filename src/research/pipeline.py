"""
Search pipeline for Lancet.

Unified pipeline that combines search execution with optional refutation mode.
Replaces execute_subquery and execute_refutation MCPtools with a single `search` interface.

See docs/requirements.md §2.1, §3.2.1.
"""

import asyncio
import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.research.state import ExplorationState, SearchStatus
from src.research.executor import SearchExecutor, PRIMARY_SOURCE_DOMAINS, REFUTATION_SUFFIXES
from src.storage.database import get_database
from src.utils.logging import get_logger, LogContext

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """Result of a search pipeline execution.
    
    Conforms to §3.2.1 search response schema.
    """
    
    search_id: str
    query: str
    status: str = "running"  # satisfied|partial|exhausted|running|failed
    pages_fetched: int = 0
    useful_fragments: int = 0
    harvest_rate: float = 0.0
    claims_found: list[dict[str, Any]] = field(default_factory=list)
    satisfaction_score: float = 0.0
    novelty_score: float = 1.0
    budget_remaining: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    
    # Refutation mode results
    is_refutation: bool = False
    refutations_found: int = 0
    
    # Auth tracking
    auth_blocked_urls: int = 0
    auth_queued_count: int = 0
    
    # Error tracking for MCP
    error_code: str | None = None  # MCP error code if failed
    error_details: dict[str, Any] = field(default_factory=dict)  # Additional error info
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary conforming to §3.2.1 schema."""
        # Determine ok based on error_code presence (error_code takes precedence)
        is_ok = self.error_code is None and len(self.errors) == 0
        
        result: dict[str, Any] = {
            "ok": is_ok,
            "search_id": self.search_id,
            "query": self.query,
            "status": self.status,
            "pages_fetched": self.pages_fetched,
            "useful_fragments": self.useful_fragments,
            "harvest_rate": self.harvest_rate,
            "claims_found": self.claims_found,
            "satisfaction_score": self.satisfaction_score,
            "novelty_score": self.novelty_score,
            "budget_remaining": self.budget_remaining,
        }
        
        # Include error information if present
        if self.error_code:
            result["error_code"] = self.error_code
        if self.error_details:
            result["error_details"] = self.error_details
        if self.errors:
            result["errors"] = self.errors
        
        if self.is_refutation:
            result["refutations_found"] = self.refutations_found
        
        if self.auth_blocked_urls > 0 or self.auth_queued_count > 0:
            result["auth_blocked_urls"] = self.auth_blocked_urls
            result["auth_queued_count"] = self.auth_queued_count
        
        return result


@dataclass
class SearchOptions:
    """Options for search execution."""
    
    engines: list[str] | None = None  # Use None for Lancet-selected engines
    max_pages: int | None = None
    seek_primary: bool = False  # Prioritize primary sources
    refute: bool = False  # Enable refutation mode


class SearchPipeline:
    """
    Unified search pipeline for Lancet.
    
    Executes Cursor AI-designed queries through the search/fetch/extract pipeline.
    Supports both normal search and refutation mode.
    
    Responsibilities (§2.1.3, §3.2.1):
    - Execute search → fetch → extract → evaluate pipeline
    - Apply mechanical query expansions
    - Calculate metrics (harvest rate, novelty, satisfaction)
    - In refutation mode, apply mechanical suffix patterns and NLI detection
    
    Does NOT:
    - Design queries (Cursor AI's responsibility)
    - Make strategic decisions about what to search next
    """
    
    def __init__(self, task_id: str, state: ExplorationState):
        """Initialize search pipeline.
        
        Args:
            task_id: The task ID.
            state: The exploration state manager.
        """
        self.task_id = task_id
        self.state = state
        self._db = None
        self._seen_fragment_hashes: set[str] = set()
        self._seen_domains: set[str] = set()
    
    async def _ensure_db(self) -> None:
        """Ensure database connection."""
        if self._db is None:
            self._db = await get_database()
    
    async def execute(
        self,
        query: str,
        options: SearchOptions | None = None,
    ) -> SearchResult:
        """
        Execute a search designed by Cursor AI.
        
        Args:
            query: The search query (designed by Cursor AI).
            options: Search options.
            
        Returns:
            SearchResult with execution results.
        """
        if options is None:
            options = SearchOptions()
        
        await self._ensure_db()
        
        # Generate search ID
        search_id = f"s_{uuid.uuid4().hex[:8]}"
        
        with LogContext(task_id=self.task_id, search_id=search_id):
            logger.info(
                "Executing search",
                query=query[:100],
                refute=options.refute,
            )
            
            result = SearchResult(
                search_id=search_id,
                query=query,
                is_refutation=options.refute,
            )
            
            try:
                if options.refute:
                    # Refutation mode: use mechanical suffix patterns
                    result = await self._execute_refutation_search(
                        search_id, query, options, result
                    )
                else:
                    # Normal search mode
                    result = await self._execute_normal_search(
                        search_id, query, options, result
                    )
                
                # Calculate remaining budget
                overall_status = await self.state.get_status()
                result.budget_remaining = {
                    "pages": overall_status["budget"]["pages_limit"] - overall_status["budget"]["pages_used"],
                    "percent": int(
                        (1 - overall_status["budget"]["pages_used"] / overall_status["budget"]["pages_limit"]) * 100
                    ),
                }
                
            except Exception as e:
                logger.error("Search execution failed", error=str(e), exc_info=True)
                result.status = "failed"
                result.errors.append(str(e))
            
            return result
    
    async def _execute_normal_search(
        self,
        search_id: str,
        query: str,
        options: SearchOptions,
        result: SearchResult,
    ) -> SearchResult:
        """Execute normal search mode."""
        # Check if academic query
        is_academic = self._is_academic_query(query)
        
        if is_academic:
            # Complementary search: Browser + Academic API
            return await self._execute_complementary_search(
                search_id, query, options, result
            )
        else:
            # Standard browser search only
            return await self._execute_browser_search(
                search_id, query, options, result
            )
    
    async def _execute_browser_search(
        self,
        search_id: str,
        query: str,
        options: SearchOptions,
        result: SearchResult,
    ) -> SearchResult:
        """Execute browser search only."""
        executor = SearchExecutor(self.task_id, self.state)
        budget_pages = options.max_pages

        exec_result = await executor.execute(
            query=query,
            priority="high" if options.seek_primary else "medium",
            budget_pages=budget_pages,
            engines=options.engines,
        )
        
        # Map executor result to SearchResult
        result.status = exec_result.status
        result.pages_fetched = exec_result.pages_fetched
        result.useful_fragments = exec_result.useful_fragments
        result.harvest_rate = exec_result.harvest_rate
        result.satisfaction_score = exec_result.satisfaction_score
        result.novelty_score = exec_result.novelty_score
        result.auth_blocked_urls = exec_result.auth_blocked_urls
        result.auth_queued_count = exec_result.auth_queued_count
        
        if exec_result.error_code:
            result.error_code = exec_result.error_code
            result.error_details = exec_result.error_details
        
        for claim in exec_result.new_claims:
            result.claims_found.append({
                "id": f"c_{uuid.uuid4().hex[:8]}",
                "text": claim.get("claim", claim.get("snippet", ""))[:200],
                "confidence": claim.get("confidence", 0.5),
                "source_url": claim.get("source_url", ""),
                "is_primary_source": self._is_primary_source(claim.get("source_url", "")),
            })
        
        if exec_result.errors:
            result.errors.extend(exec_result.errors)
        
        return result
    
    async def _execute_complementary_search(
        self,
        search_id: str,
        query: str,
        options: SearchOptions,
        result: SearchResult,
    ) -> SearchResult:
        """Execute complementary search (Browser + Academic API).
        
        Performs unified deduplication across both sources.
        """
        from src.search.academic_provider import AcademicSearchProvider
        from src.search.canonical_index import CanonicalPaperIndex
        from src.search.identifier_extractor import IdentifierExtractor
        from src.search.id_resolver import IDResolver
        from src.search.search_api import search_serp
        from src.search.provider import SearchResult as ProviderSearchResult
        
        logger.info("Executing complementary search", query=query[:100])
        
        # Initialize components
        index = CanonicalPaperIndex()
        extractor = IdentifierExtractor()
        resolver = IDResolver()
        
        # Phase 1: Parallel search
        browser_task = search_serp(
            query=query,
            limit=options.max_pages or 20,
            task_id=self.task_id,
            engines=options.engines,
        )
        
        academic_provider = AcademicSearchProvider()
        academic_task = academic_provider.search(query, options)
        
        # Execute in parallel
        try:
            serp_items, academic_response = await asyncio.gather(
                browser_task,
                academic_task,
                return_exceptions=True
            )
        except Exception as e:
            logger.error("Parallel search failed", error=str(e))
            serp_items = []
            academic_response = None
        
        if isinstance(serp_items, Exception):
            logger.warning("Browser search failed", error=str(serp_items))
            serp_items = []
        if isinstance(academic_response, Exception):
            logger.warning("Academic API search failed", error=str(academic_response))
            academic_response = None
        
        # Phase 2: Register Academic API results first (structured, high priority)
        academic_count = 0
        if academic_response and academic_response.ok:
            for search_result in academic_response.results:
                # SearchResultから識別子を抽出
                identifier = extractor.extract(search_result.url)
                
                # DOIが既にある場合はそのまま使用
                if not identifier.doi and search_result.url:
                    # URLからDOIを再抽出
                    identifier = extractor.extract(search_result.url)
                
                canonical_id = index.register_serp_result(search_result, identifier)
                academic_count += 1
        
        # Phase 3: Process browser SERP results with identifier extraction
        serp_count = 0
        for item in serp_items:
            if not isinstance(item, dict):
                continue
            
            url = item.get("url", "")
            if not url:
                continue
            
            identifier = extractor.extract(url)
            
            # Resolve DOI if needed
            if identifier.needs_meta_extraction and not identifier.doi:
                try:
                    if identifier.pmid:
                        identifier.doi = await resolver.resolve_pmid_to_doi(identifier.pmid)
                    elif identifier.arxiv_id:
                        identifier.doi = await resolver.resolve_arxiv_to_doi(identifier.arxiv_id)
                except Exception as e:
                    logger.debug("DOI resolution failed", url=url, error=str(e))
            
            # Convert dict to SearchResult
            serp_result = ProviderSearchResult(
                title=item.get("title", ""),
                url=url,
                snippet=item.get("snippet", ""),
                engine=item.get("engine", "unknown"),
                rank=item.get("rank", 0),
                date=item.get("date"),
            )
            
            canonical_id = index.register_serp_result(serp_result, identifier)
            serp_count += 1
        
        # Phase 4: Get deduplication stats
        stats = index.get_stats()
        unique_entries = index.get_all_entries()
        
        logger.info(
            "Complementary search deduplication",
            query=query[:100],
            browser_count=serp_count,
            academic_count=academic_count,
            unique_count=stats["total"],
            overlap_count=stats["both"],
            api_only=stats["api_only"],
            serp_only=stats["serp_only"],
        )
        
        # Phase 5: Process unique entries through SearchExecutor
        # For now, use browser search executor with merged unique URLs
        # Full implementation would:
        # - Skip fetch for entries with abstracts from API
        # - Fetch and extract for SERP-only entries
        
        # Simplified: Use browser search with expanded queries
        expanded_queries = self._expand_academic_query(query)
        return await self._execute_browser_search(search_id, expanded_queries[0], options, result)
    
    def _is_academic_query(self, query: str) -> bool:
        """学術クエリかどうかを判定.
        
        Args:
            query: 検索クエリ
            
        Returns:
            True if academic query
        """
        query_lower = query.lower()
        
        # キーワード判定
        academic_keywords = [
            "論文", "paper", "研究", "study", "学術", "journal",
            "arxiv", "pubmed", "doi:", "citation", "引用",
            "preprint", "peer-review", "査読", "publication",
        ]
        if any(kw in query_lower for kw in academic_keywords):
            return True
        
        # サイト指定判定
        academic_sites = [
            "arxiv.org", "pubmed", "scholar.google", "jstage",
            "doi.org", "semanticscholar.org", "crossref.org",
        ]
        if any(f"site:{site}" in query_lower for site in academic_sites):
            return True
        
        # DOI形式判定
        if re.search(r"10\.\d{4,}/", query):
            return True
        
        return False
    
    def _expand_academic_query(self, query: str) -> list[str]:
        """学術クエリを複数のサイト指定クエリに展開.
        
        Args:
            query: 元のクエリ
            
        Returns:
            展開されたクエリのリスト
        """
        queries = [query]  # 元のクエリ
        
        # site:演算子を除去
        base_query = re.sub(r'\bsite:\S+', '', query).strip()
        
        # 学術サイト指定を追加（上位2サイトのみ）
        academic_sites = [
            "arxiv.org",
            "pubmed.ncbi.nlm.nih.gov",
        ]
        
        for site in academic_sites[:2]:
            queries.append(f"{base_query} site:{site}")
        
        return queries
    
    async def _execute_refutation_search(
        self,
        search_id: str,
        query: str,
        options: SearchOptions,
        result: SearchResult,
    ) -> SearchResult:
        """Execute refutation search mode.
        
        Applies mechanical suffix patterns and uses NLI for refutation detection.
        """
        from src.search import search_serp
        from src.crawler.fetcher import fetch_url
        from src.extractor.content import extract_content
        from src.filter.nli import nli_judge
        
        logger.info("Executing refutation search", query=query[:100])
        
        # Generate refutation queries using mechanical patterns only
        refutation_queries = self._generate_refutation_queries(query)
        
        all_refutations = []
        pages_fetched = 0
        useful_fragments = 0
        
        budget = options.max_pages or 15
        
        for rq in refutation_queries:
            # Check budget
            within_budget, _ = self.state.check_budget()
            if not within_budget or pages_fetched >= budget:
                break
            
            try:
                # Search
                serp_results = await search_serp(
                    query=rq,
                    limit=5,
                    task_id=self.task_id,
                )
                
                for item in serp_results[:3]:
                    if pages_fetched >= budget:
                        break
                    
                    url = item.get("url", "")
                    if not url:
                        continue
                    
                    try:
                        # Fetch
                        fetch_result = await fetch_url(
                            url=url,
                            context={"referer": "refutation_search"},
                            task_id=self.task_id,
                        )
                        
                        pages_fetched += 1
                        
                        if not fetch_result.get("ok"):
                            if fetch_result.get("auth_queued"):
                                result.auth_blocked_urls += 1
                                result.auth_queued_count += 1
                            continue
                        
                        # Extract
                        html_path = fetch_result.get("html_path")
                        if not html_path:
                            continue
                        
                        extract_result = await extract_content(
                            input_path=html_path,
                            content_type="html",
                        )
                        
                        text = extract_result.get("text", "")
                        if not text:
                            continue
                        
                        useful_fragments += 1
                        
                        # Check for refutation using NLI
                        passage = text[:500]
                        refutation = await self._detect_refutation_nli(
                            query, passage, url, item.get("title", ""), nli_judge
                        )
                        
                        if refutation:
                            all_refutations.append(refutation)
                            result.claims_found.append({
                                "id": f"c_{uuid.uuid4().hex[:8]}",
                                "text": refutation["refuting_passage"][:200],
                                "confidence": refutation["nli_confidence"],
                                "source_url": url,
                                "is_primary_source": self._is_primary_source(url),
                                "is_refutation": True,
                            })
                    
                    except Exception as e:
                        logger.debug("Refutation fetch failed", url=url[:50], error=str(e))
            
            except Exception as e:
                logger.debug("Refutation search failed", query=rq[:50], error=str(e))
        
        result.pages_fetched = pages_fetched
        result.useful_fragments = useful_fragments
        result.harvest_rate = useful_fragments / max(1, pages_fetched)
        result.refutations_found = len(all_refutations)
        
        # Determine status
        if len(all_refutations) > 0:
            result.status = "satisfied"
            result.satisfaction_score = min(1.0, len(all_refutations) / 3)
        elif pages_fetched >= budget:
            result.status = "exhausted"
        else:
            result.status = "partial"
        
        return result
    
    def _generate_refutation_queries(self, text: str) -> list[str]:
        """
        Generate refutation queries using mechanical patterns only.
        
        Applies predefined suffixes to the text.
        Does NOT use LLM to generate hypotheses (§2.1.4).
        
        Args:
            text: The claim or query text.
            
        Returns:
            List of refutation queries.
        """
        key_terms = text[:100]  # Use first 100 chars as key
        
        refutation_queries = []
        for suffix in REFUTATION_SUFFIXES[:5]:  # Limit to avoid too many queries
            refutation_queries.append(f"{key_terms} {suffix}")
        
        return refutation_queries
    
    async def _detect_refutation_nli(
        self,
        claim_text: str,
        passage: str,
        source_url: str,
        source_title: str,
        nli_judge,
    ) -> dict[str, Any] | None:
        """
        Detect if a passage refutes a claim using NLI.
        
        Args:
            claim_text: The claim text.
            passage: The passage to check.
            source_url: URL of the source.
            source_title: Title of the source.
            nli_judge: NLI judge function.
            
        Returns:
            Refutation details if detected, None otherwise.
        """
        try:
            pairs = [{
                "pair_id": "refutation_check",
                "premise": passage,
                "hypothesis": claim_text,
            }]
            
            results = await nli_judge(pairs=pairs)
            
            if results and len(results) > 0:
                stance = results[0].get("stance", "neutral")
                confidence = results[0].get("confidence", 0)
                
                if stance == "refutes" and confidence > 0.6:
                    return {
                        "claim_text": claim_text[:100],
                        "refuting_passage": passage[:200],
                        "source_url": source_url,
                        "source_title": source_title,
                        "nli_confidence": confidence,
                    }
        
        except Exception as e:
            logger.debug("NLI detection failed", error=str(e))
        
        return None
    
    def _is_primary_source(self, url: str) -> bool:
        """Check if URL is from a primary source domain."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            return any(
                primary in domain
                for primary in PRIMARY_SOURCE_DOMAINS
            )
        except Exception:
            return False


async def search_action(
    task_id: str,
    query: str,
    state: ExplorationState,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Unified API for search action (Phase M architecture).
    
    This function serves as the action-based entry point for the search MCP tool,
    following the unified architecture pattern where MCP handlers are thin wrappers.
    
    Args:
        task_id: The task ID.
        query: Search query designed by Cursor AI.
        state: The exploration state manager.
        options: Optional search options dict.
        
    Returns:
        Search result conforming to §3.2.1 schema.
    """
    # Convert options dict to SearchOptions
    search_options = SearchOptions()
    if options:
        search_options.engines = options.get("engines")
        search_options.max_pages = options.get("max_pages")
        search_options.seek_primary = options.get("seek_primary", False)
        search_options.refute = options.get("refute", False)
    
    pipeline = SearchPipeline(task_id, state)
    result = await pipeline.execute(query, search_options)
    
    return result.to_dict()


async def stop_task_action(
    task_id: str,
    state: ExplorationState,
    reason: str = "completed",
) -> dict[str, Any]:
    """
    Unified API for stop_task action (Phase M architecture).
    
    Finalizes exploration and returns summary.
    
    Args:
        task_id: The task ID.
        state: The exploration state manager.
        reason: Stop reason ("completed", "budget_exhausted", "user_cancelled").
        
    Returns:
        Finalization result conforming to §3.2.1 schema.
    """
    with LogContext(task_id=task_id):
        logger.info("Stopping task", reason=reason)
        
        # Finalize exploration
        finalize_result = await state.finalize()
        
        # Save final state
        await state.save_state()
        
        # Map to §3.2.1 schema
        # Use safe .get() access to handle potential missing keys
        summary = finalize_result.get("summary", {})
        evidence_graph_summary = finalize_result.get("evidence_graph_summary", {})
        
        return {
            "ok": True,
            "task_id": task_id,
            "final_status": finalize_result.get("final_status", reason),
            "summary": {
                "total_searches": len(state._searches),
                "satisfied_searches": summary.get("satisfied_searches", 0),
                "total_claims": summary.get("total_claims", 0),
                "primary_source_ratio": evidence_graph_summary.get("primary_source_ratio", 0.0),
            },
        }
