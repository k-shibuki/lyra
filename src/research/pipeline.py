"""
Search pipeline for Lancet.

Unified pipeline that combines search execution with optional refutation mode.
Replaces execute_subquery and execute_refutation MCPtools with a single `search` interface.

See requirements.md §2.1, §3.2.1.
"""

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.research.state import ExplorationState, SubqueryStatus
from src.research.executor import SubqueryExecutor, PRIMARY_SOURCE_DOMAINS, REFUTATION_SUFFIXES
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
    status: str = "running"  # satisfied|partial|exhausted|running
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
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary conforming to §3.2.1 schema."""
        result: dict[str, Any] = {
            "ok": len(self.errors) == 0,
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
        # Use SubqueryExecutor for the core pipeline logic
        executor = SubqueryExecutor(self.task_id, self.state)
        
        # Convert options to executor parameters
        budget_pages = options.max_pages
        
        # Execute through executor
        sq_result = await executor.execute(
            subquery=query,
            priority="high" if options.seek_primary else "medium",
            budget_pages=budget_pages,
        )
        
        # Map executor result to SearchResult
        result.status = sq_result.status
        result.pages_fetched = sq_result.pages_fetched
        result.useful_fragments = sq_result.useful_fragments
        result.harvest_rate = sq_result.harvest_rate
        result.satisfaction_score = sq_result.satisfaction_score
        result.novelty_score = sq_result.novelty_score
        result.auth_blocked_urls = sq_result.auth_blocked_urls
        result.auth_queued_count = sq_result.auth_queued_count
        
        # Convert claims to §3.2.1 format
        for claim in sq_result.new_claims:
            result.claims_found.append({
                "id": f"c_{uuid.uuid4().hex[:8]}",
                "text": claim.get("claim", claim.get("snippet", ""))[:200],
                "confidence": claim.get("confidence", 0.5),
                "source_url": claim.get("source_url", ""),
                "is_primary_source": self._is_primary_source(claim.get("source_url", "")),
            })
        
        if sq_result.errors:
            result.errors.extend(sq_result.errors)
        
        return result
    
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
        return {
            "ok": True,
            "task_id": task_id,
            "final_status": finalize_result.get("final_status", reason),
            "summary": {
                "total_searches": len(state._subqueries),
                "satisfied_searches": finalize_result["summary"]["satisfied_subqueries"],
                "total_claims": finalize_result["summary"]["total_claims"],
                "primary_source_ratio": finalize_result["evidence_graph_summary"]["primary_source_ratio"],
            },
        }

