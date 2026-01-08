"""
Search pipeline for Lyra.

Unified pipeline that combines search execution with optional refutation mode.
Replaces execute_subquery and execute_refutation MCPtools with a single `search` interface.

See ADR-0002, ADR-0003.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.research.executor import PRIMARY_SOURCE_DOMAINS, REFUTATION_SUFFIXES, SearchExecutor
from src.research.state import ExplorationState
from src.storage.database import get_database

if TYPE_CHECKING:
    from src.storage.database import Database
from src.utils.logging import LogContext, get_logger
from src.utils.schemas import Paper

logger = get_logger(__name__)


@dataclass
class SearchPipelineResult:
    """Result of a search pipeline execution.

    Conforms to ADR-0003 search response schema.
    """

    search_id: str
    query: str
    status: str = "running"  # satisfied|partial|exhausted|running|failed|timeout
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

    # Timeout flag (ADR-0002)
    is_partial: bool = False  # True if result is partial due to timeout

    # Auth tracking
    auth_blocked_urls: int = 0
    auth_queued_count: int = 0

    # Error tracking for MCP
    error_code: str | None = None  # MCP error code if failed
    error_details: dict[str, Any] = field(default_factory=dict)  # Additional error info

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary conforming to ADR-0003 schema."""
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

        # Include partial flag for timeout (ADR-0002)
        if self.is_partial:
            result["is_partial"] = True

        return result


@dataclass
class PipelineSearchOptions:
    """Options for search execution."""

    # SERP engines (duckduckgo, mojeek, google, brave, ecosia, startpage, bing)
    # Use None for Lyra-selected engines
    serp_engines: list[str] | None = None
    # Academic APIs (semantic_scholar, openalex). Use None for default (both).
    academic_apis: list[str] | None = None
    # NOTE: AcademicSearchProvider expects `options.limit` (see src/search/academic_provider.py).
    limit: int = 10  # Max results per Academic API query
    budget_pages: int | None = None
    # SERP pagination:
    # This is distinct from budget_pages (crawl budget). It controls how many SERP pages
    # BrowserSearchProvider.search() will fetch per query.
    serp_max_pages: int = 2
    seek_primary: bool = False  # Prioritize primary sources
    refute: bool = False  # Enable refutation mode
    # ADR-0007: CAPTCHA queue integration
    task_id: str | None = None  # Task ID for CAPTCHA queue association
    search_job_id: str | None = None  # Search job ID for auto-requeue on resolve
    # ADR-0014 Phase 3: Worker context isolation
    worker_id: int = 0  # Worker ID for isolated browser context


class SearchPipeline:
    """
    Unified search pipeline for Lyra.

    Executes Cursor AI-designed queries through the search/fetch/extract pipeline.
    Supports both normal search and refutation mode.

    Responsibilities (ADR-0002, ADR-0003):
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
        self._db: Database | None = None
        self._seen_fragment_hashes: set[str] = set()
        self._seen_domains: set[str] = set()

    async def _ensure_db(self) -> None:
        """Ensure database connection."""
        if self._db is None:
            self._db = await get_database()

    async def execute(
        self,
        query: str,
        options: PipelineSearchOptions | None = None,
    ) -> SearchPipelineResult:
        """
        Execute a search designed by Cursor AI.

        Applies ADR-0002 pipeline timeout for safe stop on Cursor AI idle.

        Args:
            query: The search query (designed by Cursor AI).
            options: Search options.

        Returns:
            SearchPipelineResult with execution results.
        """
        if options is None:
            options = PipelineSearchOptions()

        await self._ensure_db()

        # Generate search ID
        search_id = f"s_{uuid.uuid4().hex[:8]}"

        # FIX: Register search in ExplorationState for metrics tracking
        # This ensures record_page_fetch and record_fragment can find the search
        self.state.register_search(
            search_id=search_id,
            text=query,
            priority="high" if options.seek_primary else "medium",
            budget_pages=options.budget_pages,
        )
        self.state.start_search(search_id)

        # Get timeout from config (ADR-0002)
        from src.utils.config import get_settings

        settings = get_settings()
        timeout_seconds = settings.task_limits.search_timeout_seconds

        with LogContext(task_id=self.task_id, search_id=search_id):
            logger.info(
                "Executing search",
                query=query[:100],
                refute=options.refute,
                timeout=timeout_seconds,
            )

            result = SearchPipelineResult(
                search_id=search_id,
                query=query,
                is_refutation=options.refute,
            )

            try:
                # Wrap execution with timeout (ADR-0002)
                result = await asyncio.wait_for(
                    self._execute_impl(search_id, query, options, result),
                    timeout=float(timeout_seconds),
                )
            except TimeoutError:
                # Pipeline timeout - return partial result
                logger.warning(
                    "Pipeline timeout - safe stop",
                    search_id=search_id,
                    query=query[:50],
                    timeout=timeout_seconds,
                )
                result.status = "timeout"
                result.is_partial = True
                result.errors.append(
                    f"Pipeline timeout after {timeout_seconds}s (ADR-0002 safe stop)"
                )

                # Try to get partial budget info
                try:
                    overall_status = await self.state.get_status()
                    result.budget_remaining = {
                        "pages": overall_status["budget"]["budget_pages_limit"]
                        - overall_status["budget"]["budget_pages_used"],
                        "percent": int(
                            (
                                1
                                - overall_status["budget"]["budget_pages_used"]
                                / overall_status["budget"]["budget_pages_limit"]
                            )
                            * 100
                        ),
                    }
                except Exception:
                    pass  # Ignore errors when getting partial info
            except Exception as e:
                logger.error("Search execution failed", error=str(e), exc_info=True)
                result.status = "failed"
                result.errors.append(str(e))

            return result

    async def _execute_impl(
        self,
        search_id: str,
        query: str,
        options: PipelineSearchOptions,
        result: SearchPipelineResult,
    ) -> SearchPipelineResult:
        """
        Internal implementation of search execution.

        Separated from execute for timeout wrapping (ADR-0002).
        """
        if options.refute:
            # Refutation mode: use mechanical suffix patterns
            result = await self._execute_refutation_search(search_id, query, options, result)
        else:
            # Normal search mode
            result = await self._execute_normal_search(search_id, query, options, result)

        # Calculate remaining budget
        overall_status = await self.state.get_status()
        result.budget_remaining = {
            "pages": overall_status["budget"]["budget_pages_limit"]
            - overall_status["budget"]["budget_pages_used"],
            "percent": int(
                (
                    1
                    - overall_status["budget"]["budget_pages_used"]
                    / overall_status["budget"]["budget_pages_limit"]
                )
                * 100
            ),
        }

        return result

    async def _execute_normal_search(
        self,
        search_id: str,
        query: str,
        options: PipelineSearchOptions,
        result: SearchPipelineResult,
    ) -> SearchPipelineResult:
        """Execute normal search mode.

        Always runs unified dual-source search (Academic API + Browser SERP) per ADR-0015.
        Results are deduplicated via CanonicalPaperIndex, citation graph is processed once.
        """
        # Always use unified dual-source search (no is_academic branching)
        return await self._execute_unified_search(search_id, query, options, result)

    async def _execute_fetch_extract(
        self,
        search_id: str,
        query: str,
        options: PipelineSearchOptions,
        result: SearchPipelineResult,
    ) -> SearchPipelineResult:
        """Execute fetch and extract via SearchExecutor.

        Runs SearchExecutor to fetch pages and extract content/claims.
        Does NOT perform SERP search or citation graph processing
        (those are handled in _execute_unified_search to avoid duplication).

        Args:
            search_id: Search ID
            query: Search query
            options: Search options
            result: SearchPipelineResult to update

        Returns:
            Updated SearchPipelineResult with fetch/extract stats
        """
        # ADR-0014 Phase 3: pass worker_id for context isolation
        executor = SearchExecutor(self.task_id, self.state, worker_id=options.worker_id)
        budget_pages = options.budget_pages

        exec_result = await executor.execute(
            query=query,
            priority="high" if options.seek_primary else "medium",
            budget_pages=budget_pages,
            serp_engines=options.serp_engines,
            serp_max_pages=options.serp_max_pages,
            search_job_id=options.search_job_id,  # ADR-0007
        )

        # Map executor result to SearchPipelineResult
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
            result.claims_found.append(
                {
                    "id": f"c_{uuid.uuid4().hex[:8]}",
                    "text": claim.get("claim", claim.get("snippet", ""))[:200],
                    "confidence": claim.get("confidence", 0.5),
                    "source_url": claim.get("source_url", ""),
                    "is_primary_source": self._is_primary_source(claim.get("source_url", "")),
                }
            )

        if exec_result.errors:
            result.errors.extend(exec_result.errors)

        return result

    async def _process_serp_with_identifiers(
        self,
        search_id: str,
        query: str,
        serp_items: list[dict[str, Any]],
        options: PipelineSearchOptions,
    ) -> tuple[Any, list[Any]]:
        """Process SERP items to extract identifiers and complement with academic API.

        Args:
            search_id: Search ID
            query: Search query
            serp_items: SERP search results
            options: Search options

        Returns:
            Tuple of (CanonicalPaperIndex, list of Paper objects found)
        """
        from src.search.academic_provider import AcademicSearchProvider
        from src.search.canonical_index import CanonicalPaperIndex
        from src.search.id_resolver import IDResolver
        from src.search.identifier_extractor import IdentifierExtractor
        from src.search.provider import SERPResult

        index = CanonicalPaperIndex()
        extractor = IdentifierExtractor()
        resolver = IDResolver()
        academic_provider = AcademicSearchProvider()

        papers_found: list[Any] = []

        try:
            # Extract identifiers from SERP items
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
                            identifier.doi = await resolver.resolve_arxiv_to_doi(
                                identifier.arxiv_id
                            )
                    except Exception as e:
                        logger.debug("DOI resolution failed", url=url, error=str(e))

                # Convert dict to SERPResult
                serp_result = SERPResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("snippet", ""),
                    engine=item.get("engine", "unknown"),
                    rank=item.get("rank", 0),
                    date=item.get("date"),
                )

                index.register_serp_result(serp_result, identifier)
                serp_count += 1

            # Complement with academic API if identifiers found
            unique_entries = index.get_all_entries()
            identifiers_found = False

            for entry in unique_entries:
                if entry.paper:
                    # Already has Paper object from API
                    papers_found.append(entry.paper)
                    identifiers_found = True
                    continue

                # Check if identifier exists
                entry_identifier: Any = None
                if entry.serp_results:
                    url = entry.serp_results[0].url
                    entry_identifier = extractor.extract(url)

                if entry_identifier and (
                    entry_identifier.doi or entry_identifier.pmid or entry_identifier.arxiv_id
                ):
                    identifiers_found = True
                    try:
                        # Try to get paper metadata from academic API
                        paper_id = None
                        if entry_identifier.doi:
                            paper_id = f"DOI:{entry_identifier.doi}"
                        elif entry_identifier.pmid:
                            paper_id = f"PMID:{entry_identifier.pmid}"
                        elif entry_identifier.arxiv_id:
                            paper_id = f"ArXiv:{entry_identifier.arxiv_id}"

                        if paper_id:
                            # Try to get paper from academic API clients
                            paper = None
                            for api_name in ["semantic_scholar", "openalex"]:
                                try:
                                    client = await academic_provider._get_client(api_name)
                                    paper = await client.get_paper(paper_id)
                                    if paper:
                                        break
                                except Exception:
                                    continue

                            if paper and paper.abstract:
                                # Register paper in index
                                index.register_paper(paper, source_api=paper.source_api)
                                papers_found.append(paper)
                                logger.debug(
                                    "Complemented SERP result with academic API",
                                    url=url,
                                    paper_id=paper.id,
                                )
                    except Exception as e:
                        logger.debug(
                            "Failed to complement with academic API",
                            url=url,
                            error=str(e),
                        )

            if identifiers_found or serp_count > 0:
                logger.info(
                    "Processed SERP with identifiers",
                    query=query[:100],
                    serp_count=serp_count,
                    papers_found=len(papers_found),
                )

            return index, papers_found
        finally:
            await resolver.close()
            await academic_provider.close()

    async def _persist_academic_abstracts_and_enqueue_citation_graph(
        self,
        search_id: str,
        query: str,
        index: Any,
        options: PipelineSearchOptions,
        result: SearchPipelineResult,
    ) -> None:
        """Persist academic papers (Abstract Only) and enqueue citation graph job.

        Per ADR-0015: Citation graph processing is deferred to a separate job.
        This method only persists papers with abstracts synchronously.

        Args:
            search_id: Search ID
            query: Search query
            index: CanonicalPaperIndex with papers
            options: Search options
            result: SearchPipelineResult to update
        """
        from src.filter.evidence_graph import (
            NodeType,
            get_evidence_graph,
        )

        unique_entries = index.get_all_entries()
        paper_ids_with_page: list[str] = []

        # : Process unique entries (Abstract Only strategy)
        pages_created = 0
        fragments_created = 0

        for entry in unique_entries:
            if entry.paper and entry.paper.abstract:
                # OA URL is already provided by S2/OpenAlex APIs
                # No additional resolution needed

                # Abstract Only: Skip fetch, persist abstract directly
                try:
                    page_id, fragment_id = await self._persist_abstract_as_fragment(
                        paper=entry.paper,
                        task_id=self.task_id,
                        search_id=search_id,
                        worker_id=options.worker_id,
                    )
                    # Skip counting if already processed (fragment_id is None)
                    if fragment_id is not None:
                        pages_created += 1
                        fragments_created += 1

                        # FIX: Update ExplorationState metrics for academic papers
                        # Extract domain from paper URL
                        paper_url = entry.paper.oa_url or (
                            f"https://doi.org/{entry.paper.doi}" if entry.paper.doi else ""
                        )
                        paper_domain = self._extract_domain(paper_url)

                        # Academic papers are always primary sources
                        is_primary = True
                        is_independent = paper_domain not in self._seen_domains
                        if is_independent:
                            self._seen_domains.add(paper_domain)

                        # Record page fetch in ExplorationState
                        self.state.record_page_fetch(
                            search_id=search_id,
                            domain=paper_domain,
                            is_primary_source=is_primary,
                            is_independent=is_independent,
                        )

                        # Record fragment in ExplorationState
                        import hashlib

                        fragment_hash = hashlib.sha256(
                            entry.paper.abstract[:500].encode()
                        ).hexdigest()[:16]
                        is_novel = fragment_hash not in self._seen_fragment_hashes
                        if is_novel:
                            self._seen_fragment_hashes.add(fragment_hash)

                        self.state.record_fragment(
                            search_id=search_id,
                            fragment_hash=fragment_hash,
                            is_useful=True,  # Abstracts from academic APIs are always useful
                            is_novel=is_novel,
                        )

                    # Track paper_id for citation graph job (only if page_id is valid)
                    if page_id is not None:
                        paper_ids_with_page.append(entry.paper.id)

                        # Add to evidence graph
                        graph = await get_evidence_graph(self.task_id)
                        graph.add_node(NodeType.PAGE, page_id)

                except Exception as e:
                    logger.warning(
                        "Failed to persist abstract", error=str(e), paper_id=entry.paper.id
                    )

        # Update result stats
        result.pages_fetched += pages_created
        result.useful_fragments += fragments_created

        # Enqueue citation graph job (deferred processing per ADR-0015)
        if paper_ids_with_page:
            try:
                from src.research.citation_graph import enqueue_citation_graph_job

                await enqueue_citation_graph_job(
                    task_id=self.task_id,
                    search_id=search_id,
                    query=query,
                    paper_ids=paper_ids_with_page,
                )
                logger.info(
                    "Enqueued citation graph job",
                    task_id=self.task_id,
                    search_id=search_id,
                    paper_count=len(paper_ids_with_page),
                )
            except Exception as e:
                logger.warning(
                    "Failed to enqueue citation graph job",
                    error=str(e),
                    task_id=self.task_id,
                )

    async def _execute_unified_search(
        self,
        search_id: str,
        query: str,
        options: PipelineSearchOptions,
        result: SearchPipelineResult,
    ) -> SearchPipelineResult:
        """Execute unified dual-source search (Browser SERP + Academic API).

        Always runs both sources in parallel per ADR-0015:
        - Browser SERP for web results
        - Academic API (S2 + OpenAlex) for structured paper data

        Results are deduplicated via CanonicalPaperIndex.
        Citation graph processing happens once (Abstract Only strategy).
        Entries needing fetch (no abstract) go through SearchExecutor.
        """
        from src.search.academic_provider import AcademicSearchProvider
        from src.search.canonical_index import CanonicalPaperIndex
        from src.search.id_resolver import IDResolver
        from src.search.identifier_extractor import IdentifierExtractor
        from src.search.provider import SERPResult
        from src.search.search_api import search_serp

        logger.info("Executing unified dual-source search", query=query[:100])

        # Initialize components
        index = CanonicalPaperIndex()
        extractor = IdentifierExtractor()
        resolver = IDResolver()
        academic_provider = AcademicSearchProvider()

        try:
            # : Parallel search
            # ADR-0014 Phase 3: pass worker_id for context isolation
            browser_task = search_serp(
                query=query,
                # NOTE: This is a SERP result count, not a page budget.
                limit=20,
                task_id=self.task_id,
                engines=options.serp_engines,  # SERP engines only
                serp_max_pages=options.serp_max_pages,
                worker_id=options.worker_id,
            )

            # Build separate options for academic provider (no SERP engines mixing)
            from src.search.provider import SearchProviderOptions

            academic_options = SearchProviderOptions(
                engines=options.academic_apis,  # Academic APIs only
                limit=options.limit,
            )
            academic_task = academic_provider.search(query, academic_options)

            # Execute in parallel
            try:
                serp_items, academic_response = await asyncio.gather(
                    browser_task, academic_task, return_exceptions=True
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

            # : Register Academic API results first (structured, high priority)
            # Get Paper objects from AcademicSearchProvider's internal CanonicalPaperIndex
            academic_count = 0

            if academic_response and academic_response.ok:
                # Get the internal index from academic_provider to access Paper objects
                academic_index = academic_provider.get_last_index()

                if academic_index:
                    # Transfer Paper objects from academic_index to our unified index
                    for entry in academic_index.get_all_entries():
                        if entry.paper:
                            # Register Paper directly in our unified index
                            index.register_paper(entry.paper, source_api=entry.paper.source_api)
                            academic_count += 1
                else:
                    # Fallback: register SearchResults (without Paper objects)
                    for search_result in academic_response.results:
                        identifier = extractor.extract(search_result.url)
                        index.register_serp_result(search_result, identifier)
                        academic_count += 1

            # : Process browser SERP results with identifier extraction
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
                            identifier.doi = await resolver.resolve_arxiv_to_doi(
                                identifier.arxiv_id
                            )
                    except Exception as e:
                        logger.debug("DOI resolution failed", url=url, error=str(e))

                # Convert dict to SERPResult
                serp_result = SERPResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("snippet", ""),
                    engine=item.get("engine", "unknown"),
                    rank=item.get("rank", 0),
                    date=item.get("date"),
                )

                index.register_serp_result(serp_result, identifier)
                serp_count += 1

                # Complement with academic API if identifier found
                if identifier and (identifier.doi or identifier.pmid or identifier.arxiv_id):
                    try:
                        paper_id = None
                        if identifier.doi:
                            paper_id = f"DOI:{identifier.doi}"
                        elif identifier.pmid:
                            paper_id = f"PMID:{identifier.pmid}"
                        elif identifier.arxiv_id:
                            paper_id = f"ArXiv:{identifier.arxiv_id}"

                        if paper_id:
                            # Try to get paper from academic API clients
                            paper = None
                            for api_name in ["semantic_scholar", "openalex"]:
                                try:
                                    client = await academic_provider._get_client(api_name)
                                    paper = await client.get_paper(paper_id)
                                    if paper:
                                        break
                                except Exception:
                                    continue

                            if paper and paper.abstract:
                                index.register_paper(paper, source_api=paper.source_api)
                                logger.debug(
                                    "Complemented SERP result with academic API",
                                    url=url,
                                    paper_id=paper.id,
                                )
                    except Exception as e:
                        logger.debug(
                            "Failed to complement with academic API",
                            url=url,
                            error=str(e),
                        )

            # : Get deduplication stats
            stats = index.get_stats()
            unique_entries = index.get_all_entries()

            serp_count = len(serp_items)

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

            # -6a: EARLY CITATION GRAPH ENQUEUE (BUG-001b fix)
            # Enqueue citation graph job BEFORE web fetch to ensure it's created
            # even if timeout occurs during web fetch. This fixes BUG-001b.
            early_paper_ids = [
                e.paper.id for e in unique_entries if e.paper and e.paper.abstract and e.paper.id
            ]
            if early_paper_ids:
                try:
                    from src.research.citation_graph import enqueue_citation_graph_job

                    await enqueue_citation_graph_job(
                        task_id=self.task_id,
                        search_id=search_id,
                        query=query,
                        paper_ids=early_paper_ids,
                    )
                    logger.info(
                        "Early enqueue citation graph job (before web fetch)",
                        task_id=self.task_id,
                        search_id=search_id,
                        paper_count=len(early_paper_ids),
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to early enqueue citation graph job",
                        error=str(e),
                        task_id=self.task_id,
                    )

            # -6b: WEB FETCH (ADR-0015 update)
            # Process entries that need fetch (no abstract available)
            # SERP-only entries (FDA.gov, Wikipedia, etc.) are fetched here
            entries_needing_fetch = [e for e in unique_entries if e.needs_fetch]
            if entries_needing_fetch:
                logger.info(
                    "Web fetch first: processing SERP-only entries",
                    count=len(entries_needing_fetch),
                    query=query[:100],
                )
                # Save current stats before calling _execute_fetch_extract (it modifies result in-place)
                pages_before = result.pages_fetched
                fragments_before = result.useful_fragments

                # Run fetch/extract for the original query
                # (no query expansion needed - SERP + Academic API already ran)
                fetch_result = await self._execute_fetch_extract(search_id, query, options, result)

                # Accumulate stats: add fetch results to existing counts
                # (fetch_result is the same object as result, so fetch_result.pages_fetched
                # contains the new value that overwrote pages_before)
                result.pages_fetched = pages_before + fetch_result.pages_fetched
                result.useful_fragments = fragments_before + fetch_result.useful_fragments

            # -7: Process academic papers and enqueue citation graph job
            # This runs AFTER web fetch to ensure SERP-only entries are prioritized
            await self._persist_academic_abstracts_and_enqueue_citation_graph(
                search_id=search_id,
                query=query,
                index=index,
                options=options,
                result=result,
            )

            return result
        finally:
            # Cleanup: Close HTTP sessions to prevent resource leaks
            await resolver.close()
            await academic_provider.close()

    async def _persist_abstract_as_fragment(
        self,
        paper: Paper,
        task_id: str,
        search_id: str,
        worker_id: int = 0,
    ) -> tuple[str | None, str | None]:
        """Persist abstract as fragment (Abstract Only strategy).

        Saves academic paper metadata to pages table and abstract to fragments table,
        skipping fetch/extract for papers with abstracts from academic APIs.

        Uses resource deduplication to prevent duplicate processing across workers.

        Args:
            paper: Paper object with abstract
            task_id: Task ID
            search_id: Search ID
            worker_id: Worker ID for resource claiming

        Returns:
            (page_id, fragment_id) tuple, or (existing_page_id, None) if already processed
        """

        db = await get_database()

        # Build reference URL (OA URL or DOI URL)
        reference_url = paper.oa_url or (f"https://doi.org/{paper.doi}" if paper.doi else "")
        if not reference_url:
            # Fallback to paper ID-based URL
            reference_url = f"https://paper/{paper.id}"

        # Determine identifier for deduplication (DOI preferred, then URL)
        if paper.doi:
            identifier_type = "doi"
            identifier_value = paper.doi.lower().strip()
        else:
            identifier_type = "url"
            identifier_value = reference_url

        # Claim resource (prevents duplicate processing across workers)
        is_new, existing_page_id = await db.claim_resource(
            identifier_type=identifier_type,
            identifier_value=identifier_value,
            task_id=task_id,
            worker_id=worker_id,
        )

        if not is_new:
            # Already processed by another worker
            # Retrieve existing fragment_id for edge creation (ADR-0005: pages/fragments are global)
            existing_fragment_id = None
            if existing_page_id:
                fragment_row = await db.fetch_one(
                    "SELECT id FROM fragments WHERE page_id = ? AND fragment_type = 'abstract' LIMIT 1",
                    (existing_page_id,),
                )
                if fragment_row:
                    existing_fragment_id = fragment_row.get("id")

            logger.debug(
                "Paper already processed (returning existing)",
                doi=paper.doi,
                existing_page_id=existing_page_id,
                existing_fragment_id=existing_fragment_id,
            )
            return existing_page_id, existing_fragment_id

        # Compute canonical_id for deduplication and normalized storage
        from src.search.canonical_index import CanonicalPaperIndex

        index = CanonicalPaperIndex()
        canonical_id = index.register_paper(paper, paper.source_api)

        # Persist to normalized works tables (works, work_authors, work_identifiers)
        from src.storage.works import persist_work

        await persist_work(db, paper, canonical_id)

        # Generate page ID
        page_id = f"page_{uuid.uuid4().hex[:8]}"

        try:
            # Insert into pages table with canonical_id reference
            await db.insert(
                "pages",
                {
                    "id": page_id,
                    "url": reference_url,
                    "final_url": reference_url,
                    "domain": self._extract_domain(reference_url),
                    "page_type": "academic_paper",
                    "fetch_method": "academic_api",
                    "title": paper.title,
                    "canonical_id": canonical_id,
                    "fetched_at": time.time(),
                },
                auto_id=False,
                or_ignore=True,
            )

            # Check if page was actually inserted (URL UNIQUE constraint may have caused ignore)
            # If not, fetch existing page_id to avoid FK constraint violation
            existing_page = await db.fetch_one(
                "SELECT id FROM pages WHERE url = ?",
                (reference_url,),
            )
            if existing_page and existing_page["id"] != page_id:
                # URL already existed, use existing page_id
                page_id = existing_page["id"]
                logger.debug(
                    "Using existing page for URL",
                    url=reference_url[:100],
                    page_id=page_id,
                )

            # Insert abstract as fragment (using resolved page_id)
            fragment_id = f"frag_{uuid.uuid4().hex[:8]}"
            await db.insert(
                "fragments",
                {
                    "id": fragment_id,
                    "page_id": page_id,
                    "fragment_type": "abstract",
                    "text_content": paper.abstract or "",
                    "heading_context": "Abstract",
                    "position": 0,
                    "created_at": time.time(),
                },
                auto_id=False,
                or_ignore=True,
            )

            # Register in task_pages for Citation Chasing scope (Academic API)
            task_page_id = f"tp_{uuid.uuid4().hex[:8]}"
            await db.execute(
                """
                INSERT OR IGNORE INTO task_pages (id, task_id, page_id, reason, depth)
                VALUES (?, ?, ?, 'academic_api', 0)
                """,
                (task_page_id, task_id, page_id),
            )

            # Persist fragment embedding for semantic search (vector_search)
            if paper.abstract and paper.abstract.strip():
                try:
                    from src.ml_client import get_ml_client
                    from src.storage.vector_store import persist_embedding
                    from src.utils.config import get_settings

                    settings = get_settings()
                    model_id = settings.embedding.model_name
                    ml_client = get_ml_client()
                    emb = (await ml_client.embed([paper.abstract]))[0]
                    await persist_embedding("fragment", fragment_id, emb, model_id=model_id)
                except Exception as e:
                    # Log as warning so failures are observable
                    # Fragment is still in DB; vector_search will report ok=false when 0 embeddings
                    logger.warning(
                        "Embedding generation failed for abstract fragment",
                        fragment_id=fragment_id,
                        error=str(e),
                    )

            # Mark resource as completed
            await db.complete_resource(
                identifier_type=identifier_type,
                identifier_value=identifier_value,
                page_id=page_id,
            )

            # Extract claims from abstract using LLM (if in scope)
            await self._extract_claims_from_abstract(
                paper=paper,
                task_id=task_id,
                search_id=search_id,
                fragment_id=fragment_id,
                reference_url=reference_url,
            )

            logger.info(
                "Persisted abstract as fragment",
                page_id=page_id,
                fragment_id=fragment_id,
                paper_title=paper.title[:60],
                has_abstract=bool(paper.abstract),
            )

            return page_id, fragment_id

        except Exception as e:
            # Mark resource as failed
            await db.fail_resource(
                identifier_type=identifier_type,
                identifier_value=identifier_value,
                error_message=str(e),
            )
            raise

    async def _extract_claims_from_abstract(
        self,
        paper: Paper,
        task_id: str,
        search_id: str,
        fragment_id: str,
        reference_url: str,
    ) -> list[dict[str, Any]]:
        """Extract claims from academic paper abstract using LLM.

        Academic papers are always considered authoritative (tier 1), so
        LLM extraction is performed regardless of claims_extraction_scope setting.

        Args:
            paper: Paper object with abstract
            task_id: Task ID
            fragment_id: Fragment ID for the abstract
            reference_url: URL of the paper

        Returns:
            List of extracted claims
        """
        if not paper.abstract:
            return []

        db = await get_database()

        try:
            from src.filter.llm import llm_extract

            # Prepare passage for LLM extraction
            passage = {
                "id": fragment_id,
                "text": paper.abstract[:4000],  # Limit for LLM
                "source_url": reference_url,
            }

            # Extract claims using LLM
            result = await llm_extract(
                passages=[passage],
                task="extract_claims",
                context=f"Academic paper: {paper.title}",
            )
            if not result.get("ok") or not result.get("claims"):
                logger.debug(
                    "No claims extracted from abstract",
                    paper_title=paper.title[:60],
                )
                return []
            extracted_claims = []
            for claim in result["claims"]:
                if isinstance(claim, dict) and claim.get("claim"):
                    claim_id = f"c_{uuid.uuid4().hex[:8]}"
                    claim_text = claim.get("claim", "")[:500]
                    llm_confidence = claim.get("confidence", 0.5)

                    # Persist claim to DB (provenance tracked via origin edge, not JSON column)
                    try:
                        await db.insert(
                            "claims",
                            {
                                "id": claim_id,
                                "task_id": task_id,
                                "claim_text": claim_text,
                                "claim_type": claim.get("type", "fact"),
                                "llm_claim_confidence": llm_confidence,
                                "verification_notes": f"source_url={reference_url}",
                            },
                            auto_id=False,
                            or_ignore=True,
                        )
                    except Exception:
                        raise

                    # Create origin edge (provenance: which fragment this claim was extracted from)
                    # Per ADR-0005, origin edges track provenance; supports/refutes are for cross-source verification.
                    try:
                        origin_edge_id = f"e_{uuid.uuid4().hex[:8]}"
                        await db.insert(
                            "edges",
                            {
                                "id": origin_edge_id,
                                "source_type": "fragment",
                                "source_id": fragment_id,
                                "target_type": "claim",
                                "target_id": claim_id,
                                "relation": "origin",
                            },
                            auto_id=False,
                            or_ignore=True,
                        )
                    except Exception as e:
                        logger.debug(
                            "Failed to create origin edge",
                            claim_id=claim_id,
                            fragment_id=fragment_id,
                            error=str(e),
                        )

                    # Keep ExplorationState counters in sync with DB (db_only still uses DB for get_status,
                    # but stop_task.finalize() uses state counters for its summary).
                    try:
                        self.state.record_claim(search_id)
                    except Exception as e:
                        logger.debug(
                            "Failed to record claim in ExplorationState",
                            task_id=task_id,
                            search_id=search_id,
                            claim_id=claim_id,
                            error=str(e),
                        )

                    # Persist claim embedding for semantic search (vector_search)
                    if claim_text.strip():
                        try:
                            from src.ml_client import get_ml_client
                            from src.storage.vector_store import persist_embedding
                            from src.utils.config import get_settings

                            settings = get_settings()
                            model_id = settings.embedding.model_name
                            ml_client = get_ml_client()
                            emb = (await ml_client.embed([claim_text]))[0]
                            await persist_embedding("claim", claim_id, emb, model_id=model_id)
                        except Exception as e:
                            # Log as debug (claim extraction is more frequent)
                            # Claim is still in DB; vector_search will report ok=false when 0 embeddings
                            logger.debug(
                                "Embedding generation failed for claim",
                                claim_id=claim_id,
                                error=str(e),
                            )

                    extracted_claims.append(
                        {
                            "id": claim_id,
                            "claim": claim_text,
                            "confidence": llm_confidence,
                            "source_url": reference_url,
                        }
                    )

            logger.info(
                "Extracted claims from abstract",
                paper_title=paper.title[:60],
                claim_count=len(extracted_claims),
            )
            return extracted_claims

        except Exception as e:
            logger.debug(
                "Failed to extract claims from abstract",
                paper_title=paper.title[:60],
                error=str(e),
            )
            return []

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL.

        Args:
            url: URL string

        Returns:
            Domain string
        """
        match = re.search(r"https?://([^/]+)", url)
        return match.group(1) if match else "unknown"

    async def _create_citation_placeholder(
        self,
        paper: Paper,
        task_id: str,
    ) -> str | None:
        """Create placeholder page for cited paper (no abstract/fragment).

        Creates a minimal page record for citation graph edges without
        counting toward page budget. If abstract is later fetched,
        the page_id is preserved (page_id stability).

        Args:
            paper: Paper object (may or may not have abstract)
            task_id: Task ID

        Returns:
            page_id if created/existing, None if failed
        """
        db = await get_database()

        # Build reference URL (OA URL or DOI URL)
        reference_url = paper.oa_url or (f"https://doi.org/{paper.doi}" if paper.doi else "")
        if not reference_url:
            # Fallback to paper ID-based URL
            reference_url = f"https://paper/{paper.id}"

        try:
            # Check if page already exists by URL
            existing = await db.fetch_one("SELECT id FROM pages WHERE url = ?", (reference_url,))
            if existing and existing.get("id"):
                page_id_existing = str(existing["id"])
                logger.debug(
                    "Citation placeholder: page already exists",
                    url=reference_url[:80],
                    page_id=page_id_existing,
                )
                return page_id_existing

            # Compute canonical_id for normalized storage
            from src.search.canonical_index import CanonicalPaperIndex

            index = CanonicalPaperIndex()
            canonical_id = index.register_paper(paper, paper.source_api)

            # Persist to normalized works tables
            from src.storage.works import persist_work

            await persist_work(db, paper, canonical_id)

            # Generate page ID
            page_id = f"page_{uuid.uuid4().hex[:8]}"

            # Insert placeholder page with canonical_id reference
            await db.insert(
                "pages",
                {
                    "id": page_id,
                    "url": reference_url,
                    "final_url": reference_url,
                    "domain": self._extract_domain(reference_url),
                    "page_type": "citation_placeholder",
                    "fetch_method": "citation_graph",
                    "title": paper.title,
                    "canonical_id": canonical_id,
                    "fetched_at": time.time(),
                },
                auto_id=False,
                or_ignore=True,
            )

            # Check if page was actually inserted (URL UNIQUE constraint may have caused ignore)
            # If not, fetch existing page_id to return the correct ID
            existing_page = await db.fetch_one(
                "SELECT id FROM pages WHERE url = ?",
                (reference_url,),
            )
            if existing_page:
                page_id = existing_page["id"]

            logger.debug(
                "Created citation placeholder",
                page_id=page_id,
                doi=paper.doi,
                title=paper.title[:60] if paper.title else None,
            )

            return page_id

        except Exception as e:
            logger.warning(
                "Failed to create citation placeholder",
                doi=paper.doi,
                error=str(e),
            )
            return None

    async def _execute_refutation_search(
        self,
        search_id: str,
        query: str,
        options: PipelineSearchOptions,
        result: SearchPipelineResult,
    ) -> SearchPipelineResult:
        """Execute refutation search mode.

        Applies mechanical suffix patterns and uses NLI for refutation detection.
        """
        from src.crawler.fetcher import fetch_url
        from src.extractor.content import extract_content
        from src.filter.nli import nli_judge
        from src.search import search_serp

        logger.info("Executing refutation search", query=query[:100])

        # Generate refutation queries using mechanical patterns only
        refutation_queries = self._generate_refutation_queries(query)

        all_refutations = []
        pages_fetched = 0
        useful_fragments = 0

        budget = options.budget_pages or 15

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
                        # Fetch (ADR-0014 Phase 3: pass worker_id for context isolation)
                        fetch_result = await fetch_url(
                            url=url,
                            context={"referer": "refutation_search"},
                            task_id=self.task_id,
                            worker_id=options.worker_id,
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
                            result.claims_found.append(
                                {
                                    "id": f"c_{uuid.uuid4().hex[:8]}",
                                    "text": refutation["refuting_passage"][:200],
                                    "nli_edge_confidence": refutation["nli_edge_confidence"],
                                    "source_url": url,
                                    "is_primary_source": self._is_primary_source(url),
                                    "is_refutation": True,
                                }
                            )

                    except Exception as e:
                        logger.debug("Refutation fetch failed", url=url[:50], error=str(e))

            except Exception as e:
                logger.debug("Refutation search failed", query=rq[:50], error=str(e))

        result.pages_fetched = pages_fetched
        result.useful_fragments = useful_fragments
        result.harvest_rate = useful_fragments / max(1, pages_fetched)
        result.refutations_found = len(all_refutations)

        # Determine status
        if all_refutations:
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
        Does NOT use LLM to generate hypotheses (ADR-0002).

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
        source_url: str | None,
        source_title: str,
        nli_judge: Any,
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
            pairs = [
                {
                    "pair_id": "refutation_check",
                    "premise": passage,
                    "nli_hypothesis": claim_text,
                }
            ]

            results = await nli_judge(pairs=pairs)

            if results and len(results) > 0:
                stance = results[0].get("stance", "neutral")
                nli_edge_confidence = results[0].get("nli_edge_confidence", 0)

                if stance == "refutes" and nli_edge_confidence > 0.6:
                    return {
                        "claim_text": claim_text[:100],
                        "refuting_passage": passage[:200],
                        "source_url": source_url,
                        "source_title": source_title,
                        "nli_edge_confidence": nli_edge_confidence,
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

            return any(primary in domain for primary in PRIMARY_SOURCE_DOMAINS)
        except Exception as e:
            logger.debug("Primary source check failed", url=url[:100], error=str(e))
            return False


async def search_action(
    task_id: str,
    query: str,
    state: ExplorationState,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Unified API for search action.

    Entry point for the search MCP tool. MCP handler delegates to this function
    (see ADR-0003 for the thin-wrapper architecture).

    Args:
        task_id: The task ID.
        query: Search query designed by Cursor AI.
        state: The exploration state manager.
        options: Optional search options dict.

    Returns:
        Search result dict (pages found, claims extracted, metrics).
    """
    # Convert options dict to PipelineSearchOptions
    search_options = PipelineSearchOptions()
    if options:
        search_options.serp_engines = options.get("serp_engines")
        search_options.academic_apis = options.get("academic_apis")
        search_options.budget_pages = options.get("budget_pages")
        search_options.serp_max_pages = int(options.get("serp_max_pages", 2))
        search_options.seek_primary = options.get("seek_primary", False)
        search_options.refute = options.get("refute", False)
        # ADR-0007: Pass job identifiers for CAPTCHA queue integration
        search_options.task_id = options.get("task_id")
        search_options.search_job_id = options.get("search_job_id")
        # ADR-0014 Phase 3: Pass worker_id for context isolation
        search_options.worker_id = options.get("worker_id", 0)

    pipeline = SearchPipeline(task_id, state)
    result = await pipeline.execute(query, search_options)

    return result.to_dict()


async def stop_task_action(
    task_id: str,
    state: ExplorationState,
    reason: str = "session_completed",
    mode: str = "graceful",
) -> dict[str, Any]:
    """
    Unified API for stop_task action.

    Finalizes exploration session and returns summary. MCP handler delegates to this
    function (see ADR-0003, ADR-0010).

    Args:
        task_id: The task ID.
        state: The exploration state manager.
        reason: Stop reason:
            - "session_completed" (default): Session ends, task is paused and resumable.
            - "budget_exhausted": Budget depleted, task is paused and resumable.
            - "user_cancelled": User explicitly cancelled, task is paused.
        mode: Stop mode ("graceful" or "immediate"). Controls how running
              search queue jobs are handled. The MCP handler cancels jobs
              in DB before calling this function.

    Returns:
        Finalization result dict with:
        - final_status: "paused" (resumable) or "cancelled" (user explicit stop)
        - summary: Search completion metrics
        - is_resumable: Always True (task can be resumed with more searches)
    """
    with LogContext(task_id=task_id):
        logger.info("Stopping task session", reason=reason, mode=mode)

        # Finalize exploration session (pass reason to determine final_status)
        finalize_result = await state.finalize(reason=reason)

        # Save final state (status = paused)
        await state.save_state()

        # Map to ADR-0003 schema
        # Use safe .get() access to handle potential missing keys
        summary = finalize_result.get("summary", {})
        evidence_graph_summary = finalize_result.get("evidence_graph_summary", {})

        return {
            "ok": True,
            "task_id": task_id,
            "final_status": finalize_result.get("final_status", "paused"),
            "reason": reason,
            "summary": {
                "total_searches": len(state._searches),
                "satisfied_searches": summary.get("satisfied_searches", 0),
                "total_claims": summary.get("total_claims", 0),
                "primary_source_ratio": evidence_graph_summary.get("primary_source_ratio", 0.0),
            },
            "is_resumable": finalize_result.get("is_resumable", True),
            "message": f"Task paused. Resume with queue_targets(task_id='{task_id}', targets=[...]).",
        }


async def _reprocess_existing_page_for_claims(
    db: Database,
    task_id: str,
    page_id: str,
    html_path: str,
    url: str,
    domain: str,
    depth: int,
    run_citation_detector: bool,
) -> dict[str, Any]:
    """
    Reprocess an already-fetched page to extract claims for a new task.

    This is called when a page exists in DB with html_path but has no
    claims extracted for the current task (task未Claim condition).

    Args:
        db: Database instance
        task_id: Task ID to extract claims for
        page_id: Existing page ID
        html_path: Path to cached HTML
        url: Page URL
        domain: Page domain
        depth: Citation chain depth
        run_citation_detector: Whether to run citation detector

    Returns:
        Ingestion result dict
    """
    from pathlib import Path
    from urllib.parse import urlparse

    from src.extractor.content import extract_content

    fragments_extracted = 0
    claims_extracted = 0
    citations_detected = 0

    try:
        extract_result = await extract_content(
            input_path=html_path,
        )

        if extract_result.get("ok", False):
            text = extract_result.get("text", "")
            title = extract_result.get("title", "")

            if text:
                # Check if fragment already exists for this page
                existing_fragment = await db.fetch_one(
                    "SELECT id FROM fragments WHERE page_id = ? LIMIT 1",
                    (page_id,),
                )

                if existing_fragment:
                    fragment_id = (
                        existing_fragment["id"]
                        if isinstance(existing_fragment, dict)
                        else existing_fragment[0]
                    )
                else:
                    # Create new fragment
                    fragment_id = f"f_{uuid.uuid4().hex[:8]}"
                    await db.insert(
                        "fragments",
                        {
                            "id": fragment_id,
                            "page_id": page_id,
                            "text_content": text[:2000],
                            "fragment_type": "paragraph",
                            "heading_context": title[:200] if title else None,
                        },
                        or_ignore=True,
                    )
                fragments_extracted = 1

                # Extract claims using LLM for THIS task
                from src.filter.llm import llm_extract

                try:
                    passages = [{"id": fragment_id, "text": text[:4000]}]
                    llm_result = await llm_extract(
                        passages=passages,
                        task="extract_claims",
                    )
                    claims = llm_result.get("claims", [])

                    for claim_data in claims:
                        claim_id = f"c_{uuid.uuid4().hex[:8]}"
                        claim_text = (
                            claim_data.get("claim", "")
                            if isinstance(claim_data, dict)
                            else str(claim_data)
                        )
                        confidence = (
                            claim_data.get("confidence", 0.5)
                            if isinstance(claim_data, dict)
                            else 0.5
                        )

                        await db.insert(
                            "claims",
                            {
                                "id": claim_id,
                                "task_id": task_id,
                                "claim_text": claim_text[:1000],
                                "llm_claim_confidence": confidence,
                            },
                            or_ignore=True,
                        )

                        # Create origin edge from fragment to claim
                        from src.filter.evidence_graph import add_claim_evidence

                        await add_claim_evidence(
                            claim_id=claim_id,
                            fragment_id=fragment_id,
                            relation="origin",
                            nli_label=None,
                            nli_edge_confidence=confidence,
                            task_id=task_id,
                        )

                        claims_extracted += 1

                except Exception as e:
                    logger.warning(
                        "LLM claim extraction failed during reprocess",
                        url=url[:80],
                        error=str(e),
                    )

                # Run citation detector if enabled
                if run_citation_detector:
                    try:
                        from src.extractor.citation_detector import CitationDetector
                        from src.utils.config import get_settings as _get_settings

                        citation_settings = _get_settings()
                        wc = citation_settings.search.web_citation_detection

                        if wc.enabled:
                            html_content = Path(html_path).read_text(
                                encoding="utf-8", errors="ignore"
                            )

                            max_candidates = int(wc.max_candidates_per_page)
                            if max_candidates <= 0:
                                max_candidates = 10_000

                            detector = CitationDetector(max_candidates=max_candidates)
                            detected = await detector.detect_citations(
                                html=html_content,
                                base_url=url,
                                source_domain=domain,
                            )

                            citations = [d for d in detected if d.is_citation]
                            if wc.max_edges_per_page > 0:
                                citations = citations[: int(wc.max_edges_per_page)]

                            for c in citations:
                                target_url = c.url
                                target_domain = (
                                    urlparse(target_url).netloc or ""
                                ).lower() or "unknown"

                                # Create placeholder page for citation target
                                existing = await db.fetch_one(
                                    "SELECT id FROM pages WHERE url = ?",
                                    (target_url,),
                                )
                                if existing:
                                    target_page_id = (
                                        existing["id"]
                                        if isinstance(existing, dict)
                                        else existing[0]
                                    )
                                else:
                                    target_page_id = f"page_{uuid.uuid4().hex[:8]}"
                                    await db.insert(
                                        "pages",
                                        {
                                            "id": target_page_id,
                                            "url": target_url,
                                            "domain": target_domain,
                                        },
                                        auto_id=False,
                                        or_ignore=True,
                                    )

                                # Create citation edge (page→page via 'cites' relation)
                                from src.storage.database import get_database as _get_db

                                _db = await _get_db()
                                edge_id = f"cites_{uuid.uuid4().hex[:8]}"
                                await _db.insert(
                                    "edges",
                                    {
                                        "id": edge_id,
                                        "source_type": "page",
                                        "source_id": page_id,
                                        "target_type": "page",
                                        "target_id": target_page_id,
                                        "relation": "cites",
                                        "citation_context": (
                                            c.link_text[:500] if c.link_text else None
                                        ),
                                        "citation_source": "extraction",
                                    },
                                    or_ignore=True,
                                )
                                citations_detected += 1

                    except Exception as e:
                        logger.warning(
                            "Citation detection failed during reprocess",
                            url=url[:80],
                            error=str(e),
                        )

    except Exception as e:
        logger.warning(
            "Content extraction failed during reprocess",
            url=url[:80],
            error=str(e),
        )

    logger.info(
        "URL reprocessed for claims",
        url=url[:100],
        page_id=page_id,
        fragments=fragments_extracted,
        claims=claims_extracted,
        citations=citations_detected,
    )

    return {
        "ok": True,
        "url": url,
        "page_id": str(page_id),
        "pages_fetched": 0,  # No new fetch
        "fragments_extracted": fragments_extracted,
        "claims_extracted": claims_extracted,
        "citations_detected": citations_detected,
        "status": "reprocessed",
        "message": "Existing page reprocessed for this task",
    }


async def ingest_url_action(
    task_id: str,
    url: str,
    state: ExplorationState,
    depth: int = 0,
    reason: str = "manual",
    context: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Unified API for URL ingestion action (citation chasing).

    Entry point for direct URL processing. Fetches a URL, extracts content,
    generates claims, and optionally runs citation detection.

    This is the URL counterpart to search_action - it processes a single URL
    through the full pipeline without going through SERP search.

    Args:
        task_id: The task ID.
        url: URL to fetch and process.
        state: The exploration state manager.
        depth: Citation chain depth (0 = direct/manual, 1+ = chased from another page).
        reason: Why this URL is being ingested:
            - "citation_chase": Discovered as citation from another page.
            - "manual": Manually specified by user/AI.
        context: Optional context dict:
            - referer: Referring page URL.
            - citation_context: Text context where citation was found.
        policy: Optional fetch policy overrides:
            - skip_if_exists: Skip if page already has html_path (default: True).
            - run_citation_detector: Run citation detector (default: True for depth < max_depth).
        options: Optional options dict:
            - task_id: Task ID (for CAPTCHA queue).
            - target_job_id: Target job ID (for auto-requeue on resolve).
            - worker_id: Worker ID (for context isolation).

    Returns:
        Ingestion result dict with:
        - ok: True if successful
        - url: The URL processed
        - page_id: Page ID in DB
        - pages_fetched: Number of pages fetched (0 or 1)
        - fragments_extracted: Number of fragments extracted
        - claims_extracted: Number of claims extracted
        - citations_detected: Number of citations detected
        - status: "completed" | "skipped" | "failed"
    """
    from pathlib import Path
    from urllib.parse import urlparse

    from src.crawler.fetcher import fetch_url
    from src.extractor.content import extract_content
    from src.storage.database import get_database

    with LogContext(task_id=task_id):
        logger.info(
            "Ingesting URL",
            url=url[:100],
            depth=depth,
            reason=reason,
        )

        # Skip PDF URLs - browser fetch cannot extract text from PDFs
        # PDFs are handled via Academic API (abstract-only) per design
        url_lower = url.lower()
        if url_lower.endswith(".pdf") or "/pdf/" in url_lower:
            logger.info(
                "Skipping PDF URL (abstract-only design)",
                url=url[:100],
            )
            return {
                "ok": False,
                "url": url,
                "reason": "pdf_not_supported",
                "message": "PDF URLs cannot be processed via browser fetch. Use Academic API for abstract.",
                "status": "skipped",
                "pages_fetched": 0,
                "fragments_extracted": 0,
                "claims_extracted": 0,
                "citations_detected": 0,
            }

        context = context or {}
        policy = policy or {}
        options = options or {}

        # Extract options
        worker_id = options.get("worker_id", 0)
        # target_job_id reserved for future CAPTCHA requeue support

        # Policy defaults
        skip_if_exists = policy.get("skip_if_exists", True)
        max_depth = policy.get("max_citation_depth", 2)  # Default max depth for citation chasing
        run_citation_detector = policy.get("run_citation_detector", depth < max_depth)

        db = await get_database()

        # Parse URL to get domain
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
        except Exception:
            domain = "unknown"

        # Check if page already exists with content
        existing_page = await db.fetch_one(
            "SELECT id, html_path FROM pages WHERE url = ?",
            (url,),
        )

        if existing_page:
            page_id = existing_page["id"] if isinstance(existing_page, dict) else existing_page[0]
            html_path = (
                existing_page["html_path"] if isinstance(existing_page, dict) else existing_page[1]
            )

            if html_path and skip_if_exists:
                # Check if claims have been extracted for THIS task (task未Claim check)
                existing_origin = await db.fetch_one(
                    """
                    SELECT 1 FROM fragments f
                    JOIN edges e ON e.source_type = 'fragment' AND e.source_id = f.id
                                 AND e.relation = 'origin'
                    JOIN claims c ON e.target_type = 'claim' AND e.target_id = c.id
                                 AND c.task_id = ?
                    WHERE f.page_id = ?
                    LIMIT 1
                    """,
                    (task_id, page_id),
                )

                if existing_origin:
                    logger.info(
                        "URL already processed with claims for this task, skipping",
                        url=url[:100],
                        page_id=page_id,
                    )
                    return {
                        "ok": True,
                        "url": url,
                        "page_id": str(page_id),
                        "pages_fetched": 0,
                        "fragments_extracted": 0,
                        "claims_extracted": 0,
                        "citations_detected": 0,
                        "status": "skipped",
                        "message": "Page already exists with claims for this task",
                    }
                else:
                    # Page exists but no claims for this task - reprocess without fetching
                    logger.info(
                        "URL fetched but no claims for this task, reprocessing",
                        url=url[:100],
                        page_id=page_id,
                    )
                    # Register in task_pages
                    source_page_id = context.get("source_page_id") if context else None
                    task_page_id = f"tp_{uuid.uuid4().hex[:8]}"
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO task_pages (id, task_id, page_id, reason, depth, source_page_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (task_page_id, task_id, page_id, reason, depth, source_page_id),
                    )

                    # Jump directly to claim extraction (skip fetch)
                    return await _reprocess_existing_page_for_claims(
                        db=db,
                        task_id=task_id,
                        page_id=page_id,
                        html_path=html_path,
                        url=url,
                        domain=domain,
                        depth=depth,
                        run_citation_detector=run_citation_detector,
                    )
        else:
            page_id = None

        # Fetch URL
        try:
            fetch_result = await fetch_url(
                url=url,
                task_id=task_id,
                worker_id=worker_id,
            )
        except Exception as e:
            logger.error(
                "URL fetch failed",
                url=url[:100],
                error=str(e),
            )
            return {
                "ok": False,
                "url": url,
                "page_id": str(page_id) if page_id else None,
                "pages_fetched": 0,
                "fragments_extracted": 0,
                "claims_extracted": 0,
                "citations_detected": 0,
                "status": "failed",
                "error": str(e),
            }

        # Check if fetch was successful
        if not fetch_result.get("ok", False):
            error_msg = fetch_result.get("error", "Unknown fetch error")
            # Check for CAPTCHA queue
            if fetch_result.get("captcha_queued"):
                return {
                    "ok": True,
                    "url": url,
                    "page_id": (
                        str(fetch_result.get("page_id")) if fetch_result.get("page_id") else None
                    ),
                    "pages_fetched": 0,
                    "fragments_extracted": 0,
                    "claims_extracted": 0,
                    "citations_detected": 0,
                    "status": "awaiting_auth",
                    "captcha_queued": True,
                    "queue_id": fetch_result.get("queue_id"),
                    "message": "CAPTCHA detected, queued for resolution",
                }
            return {
                "ok": False,
                "url": url,
                "page_id": (
                    str(fetch_result.get("page_id")) if fetch_result.get("page_id") else None
                ),
                "pages_fetched": 0,
                "fragments_extracted": 0,
                "claims_extracted": 0,
                "citations_detected": 0,
                "status": "failed",
                "error": error_msg,
            }

        page_id = fetch_result.get("page_id")
        html_path = fetch_result.get("html_path")

        # Register in task_pages for Citation Chasing scope
        source_page_id = context.get("source_page_id") if context else None
        task_page_id = f"tp_{uuid.uuid4().hex[:8]}"
        await db.execute(
            """
            INSERT OR IGNORE INTO task_pages (id, task_id, page_id, reason, depth, source_page_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_page_id, task_id, page_id, reason, depth, source_page_id),
        )

        # Also register in resource_index for deduplication
        await db.execute(
            """
            INSERT OR IGNORE INTO resource_index (task_id, identifier_type, identifier_value, page_id, status)
            VALUES (?, 'url', ?, ?, 'completed')
            """,
            (task_id, url, page_id),
        )

        # Extract content
        fragments_extracted = 0
        claims_extracted = 0
        citations_detected = 0

        if html_path:
            try:
                extract_result = await extract_content(
                    input_path=html_path,
                )

                if extract_result.get("ok", False):
                    text = extract_result.get("text", "")
                    title = extract_result.get("title", "")

                    if text:
                        # Save fragment
                        fragment_id = f"f_{uuid.uuid4().hex[:8]}"
                        await db.insert(
                            "fragments",
                            {
                                "id": fragment_id,
                                "page_id": page_id,
                                "text_content": text[:2000],
                                "fragment_type": "paragraph",
                                "heading_context": title[:200] if title else None,
                            },
                            or_ignore=True,
                        )
                        fragments_extracted = 1

                        # Extract claims using LLM
                        from src.filter.llm import llm_extract

                        try:
                            passages = [{"id": fragment_id, "text": text[:4000]}]
                            llm_result = await llm_extract(
                                passages=passages,
                                task="extract_claims",
                            )
                            claims = llm_result.get("claims", [])

                            for claim_data in claims:
                                claim_id = f"c_{uuid.uuid4().hex[:8]}"
                                claim_text = (
                                    claim_data.get("claim", "")
                                    if isinstance(claim_data, dict)
                                    else str(claim_data)
                                )
                                confidence = (
                                    claim_data.get("confidence", 0.5)
                                    if isinstance(claim_data, dict)
                                    else 0.5
                                )

                                await db.insert(
                                    "claims",
                                    {
                                        "id": claim_id,
                                        "task_id": task_id,
                                        "claim_text": claim_text[:1000],
                                        "llm_claim_confidence": confidence,
                                    },
                                    or_ignore=True,
                                )

                                # Create origin edge from fragment to claim
                                from src.filter.evidence_graph import add_claim_evidence

                                await add_claim_evidence(
                                    claim_id=claim_id,
                                    fragment_id=fragment_id,
                                    relation="origin",
                                    nli_label=None,
                                    nli_edge_confidence=confidence,
                                    task_id=task_id,
                                )

                                claims_extracted += 1

                        except Exception as e:
                            logger.warning(
                                "LLM claim extraction failed",
                                url=url[:80],
                                error=str(e),
                            )

                        # Run citation detector if enabled
                        if run_citation_detector and html_path:
                            try:
                                from src.extractor.citation_detector import CitationDetector
                                from src.filter.evidence_graph import add_citation
                                from src.utils.config import get_settings as _get_settings

                                citation_settings = _get_settings()
                                wc = citation_settings.search.web_citation_detection

                                if wc.enabled:
                                    html_content = Path(html_path).read_text(
                                        encoding="utf-8", errors="ignore"
                                    )

                                    max_candidates = int(wc.max_candidates_per_page)
                                    if max_candidates <= 0:
                                        max_candidates = 10_000

                                    detector = CitationDetector(max_candidates=max_candidates)
                                    detected = await detector.detect_citations(
                                        html=html_content,
                                        base_url=url,
                                        source_domain=domain,
                                    )

                                    citations = [d for d in detected if d.is_citation]
                                    if wc.max_edges_per_page > 0:
                                        citations = citations[: int(wc.max_edges_per_page)]

                                    for c in citations:
                                        target_url = c.url
                                        target_domain = (
                                            urlparse(target_url).netloc or ""
                                        ).lower() or "unknown"

                                        # Check/create target page
                                        is_new, existing_page_id = await db.claim_resource(
                                            identifier_type="url",
                                            identifier_value=target_url,
                                            task_id=task_id,
                                            worker_id=worker_id,
                                        )

                                        if not is_new and existing_page_id:
                                            target_page_id = existing_page_id
                                        elif not is_new:
                                            existing = await db.fetch_one(
                                                "SELECT id FROM pages WHERE url = ?",
                                                (target_url,),
                                            )
                                            if existing and existing.get("id"):
                                                target_page_id = str(existing["id"])
                                            else:
                                                continue
                                        else:
                                            if not wc.create_placeholder_pages:
                                                continue
                                            inserted_id = await db.insert(
                                                "pages",
                                                {
                                                    "url": target_url,
                                                    "domain": target_domain,
                                                },
                                                or_ignore=True,
                                            )
                                            if not inserted_id:
                                                continue
                                            target_page_id = str(inserted_id)

                                            await db.complete_resource(
                                                identifier_type="url",
                                                identifier_value=target_url,
                                                page_id=target_page_id,
                                            )

                                        await add_citation(
                                            source_type="page",
                                            source_id=str(page_id),
                                            page_id=target_page_id,
                                            task_id=task_id,
                                            citation_source="extraction",
                                            citation_context=(c.context or "")[:500],
                                        )
                                        citations_detected += 1

                                    logger.debug(
                                        "Citation detection completed",
                                        url=url[:80],
                                        citations_total=len(detected),
                                        citations_added=citations_detected,
                                    )

                            except Exception as e:
                                logger.warning(
                                    "Citation detection failed",
                                    url=url[:80],
                                    error=str(e),
                                )

            except Exception as e:
                logger.warning(
                    "Content extraction failed",
                    url=url[:80],
                    error=str(e),
                )

        logger.info(
            "URL ingestion completed",
            url=url[:100],
            page_id=page_id,
            fragments=fragments_extracted,
            claims=claims_extracted,
            citations=citations_detected,
        )

        return {
            "ok": True,
            "url": url,
            "page_id": str(page_id) if page_id else None,
            "pages_fetched": 1,
            "fragments_extracted": fragments_extracted,
            "claims_extracted": claims_extracted,
            "citations_detected": citations_detected,
            "status": "completed",
        }


async def ingest_doi_action(
    task_id: str,
    doi: str,
    state: ExplorationState,
    reason: str = "manual",
    context: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Unified API for DOI ingestion action (Academic API fast path).

    Entry point for direct DOI processing. Attempts to fetch paper metadata
    from Academic APIs (Semantic Scholar, OpenAlex) and persist abstract
    without full web fetch.

    This is the DOI counterpart to ingest_url_action - it prioritizes
    Academic API metadata over web scraping for faster, more reliable
    ingestion of academic papers.

    Args:
        task_id: The task ID.
        doi: DOI to fetch (e.g., "10.1234/example").
        state: The exploration state manager.
        reason: Why this DOI is being ingested:
            - "citation_chase": Discovered as citation from another page.
            - "manual": Manually specified by user/AI.
        context: Optional context dict:
            - source_page_id: Page that cited this DOI.
            - citation_context: Text context where citation was found.
        options: Optional options dict:
            - task_id: Task ID (for CAPTCHA queue).
            - target_job_id: Target job ID (for auto-requeue on resolve).
            - worker_id: Worker ID (for context isolation).

    Returns:
        Ingestion result dict with:
        - ok: True if successful
        - doi: The DOI processed
        - page_id: Page ID in DB
        - pages_fetched: Number of pages fetched (0 or 1)
        - fragments_extracted: Number of fragments extracted
        - claims_extracted: Number of claims extracted
        - status: "completed" | "skipped" | "failed" | "fallback_url"
        - source: "academic_api" | "url_fallback"
    """
    from src.storage.database import get_database

    with LogContext(task_id=task_id):
        logger.info(
            "Ingesting DOI via Academic API",
            doi=doi,
            reason=reason,
        )

        context = context or {}
        options = options or {}

        worker_id = options.get("worker_id", 0)
        db = await get_database()

        # Normalize DOI
        doi = doi.strip().lower()

        # Check if already processed (via resource_index with doi type)
        is_new, existing_page_id = await db.claim_resource(
            identifier_type="doi",
            identifier_value=doi,
            task_id=task_id,
            worker_id=worker_id,
        )

        if not is_new and existing_page_id:
            # Already processed - check if claims exist for this task
            existing_origin = await db.fetch_one(
                """
                SELECT 1 FROM fragments f
                JOIN edges e ON e.source_type = 'fragment' AND e.source_id = f.id
                             AND e.relation = 'origin'
                JOIN claims c ON e.target_type = 'claim' AND e.target_id = c.id
                             AND c.task_id = ?
                WHERE f.page_id = ?
                LIMIT 1
                """,
                (task_id, existing_page_id),
            )

            if existing_origin:
                logger.info(
                    "DOI already processed with claims for this task, skipping",
                    doi=doi,
                    page_id=existing_page_id,
                )
                return {
                    "ok": True,
                    "doi": doi,
                    "page_id": str(existing_page_id),
                    "pages_fetched": 0,
                    "fragments_extracted": 0,
                    "claims_extracted": 0,
                    "status": "skipped",
                    "source": "academic_api",
                    "message": "DOI already processed with claims for this task",
                }
            else:
                # Page exists but no claims for this task - need to re-extract claims
                logger.info(
                    "DOI page exists but no claims for this task, re-extracting",
                    doi=doi,
                    page_id=existing_page_id,
                )
                # Continue to claim extraction below

        # Try Academic API first
        try:
            from src.search.academic_provider import AcademicSearchProvider

            provider = AcademicSearchProvider()
            try:
                paper = await provider.get_paper_by_doi(doi)
            finally:
                await provider.close()

            if paper and paper.abstract:
                # Success - persist abstract as fragment
                pipeline = SearchPipeline(task_id, state)
                page_id, fragment_id = await pipeline._persist_abstract_as_fragment(
                    paper=paper,
                    task_id=task_id,
                    search_id=f"doi_{doi[:20]}",
                    worker_id=worker_id,
                )

                if page_id:
                    # Register in task_pages
                    source_page_id = context.get("source_page_id")
                    task_page_id = f"tp_{uuid.uuid4().hex[:8]}"
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO task_pages (id, task_id, page_id, reason, depth, source_page_id)
                        VALUES (?, ?, ?, ?, 0, ?)
                        """,
                        (task_page_id, task_id, page_id, reason, source_page_id),
                    )

                    # Claims are extracted in _persist_abstract_as_fragment via _extract_claims_from_abstract
                    # Count them
                    claims_count = await db.fetch_one(
                        """
                        SELECT COUNT(*) as cnt FROM claims c
                        JOIN edges e ON e.target_type = 'claim' AND e.target_id = c.id
                                     AND e.relation = 'origin'
                        JOIN fragments f ON e.source_type = 'fragment' AND e.source_id = f.id
                        WHERE f.page_id = ? AND c.task_id = ?
                        """,
                        (page_id, task_id),
                    )
                    claims_extracted = claims_count.get("cnt", 0) if claims_count else 0

                    logger.info(
                        "DOI ingestion completed via Academic API",
                        doi=doi,
                        page_id=page_id,
                        claims=claims_extracted,
                    )

                    return {
                        "ok": True,
                        "doi": doi,
                        "page_id": str(page_id),
                        "pages_fetched": 1 if fragment_id else 0,
                        "fragments_extracted": 1 if fragment_id else 0,
                        "claims_extracted": claims_extracted,
                        "status": "completed",
                        "source": "academic_api",
                    }

        except Exception as e:
            logger.warning(
                "Academic API lookup failed for DOI, falling back to URL",
                doi=doi,
                error=str(e),
            )

        # Fallback: Try URL-based fetch via doi.org
        doi_url = f"https://doi.org/{doi}"
        logger.info(
            "Falling back to URL fetch for DOI",
            doi=doi,
            url=doi_url,
        )

        # Use ingest_url_action for fallback
        url_result = await ingest_url_action(
            task_id=task_id,
            url=doi_url,
            state=state,
            depth=0,
            reason=reason,
            context=context,
            policy={"skip_if_exists": False},  # Force re-fetch since Academic API failed
            options=options,
        )

        # Adjust response to indicate fallback
        return {
            "ok": url_result.get("ok", False),
            "doi": doi,
            "page_id": url_result.get("page_id"),
            "pages_fetched": url_result.get("pages_fetched", 0),
            "fragments_extracted": url_result.get("fragments_extracted", 0),
            "claims_extracted": url_result.get("claims_extracted", 0),
            "status": "fallback_url" if url_result.get("ok") else "failed",
            "source": "url_fallback",
            "error": url_result.get("error"),
        }
