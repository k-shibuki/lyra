"""
Search pipeline for Lyra.

Unified pipeline that combines search execution with optional refutation mode.
Replaces execute_subquery and execute_refutation MCPtools with a single `search` interface.

See ADR-0002, ADR-0003.
"""

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from src.research.executor import PRIMARY_SOURCE_DOMAINS, REFUTATION_SUFFIXES, SearchExecutor
from src.research.state import ExplorationState
from src.storage.database import get_database

if TYPE_CHECKING:
    from src.storage.database import Database
from src.utils.logging import LogContext, get_logger
from src.utils.schemas import Paper

logger = get_logger(__name__)


@dataclass
class SearchResult:
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
class SearchOptions:
    """Options for search execution."""

    engines: list[str] | None = None  # Use None for Lyra-selected engines
    # NOTE: AcademicSearchProvider expects `options.limit` (see src/search/academic_provider.py).
    # This dataclass is passed through that interface via duck-typing.
    limit: int = 10  # Max results per Academic API query
    budget_pages: int | None = None
    # SERP pagination:
    # This is distinct from budget_pages (crawl budget). It controls how many SERP pages
    # BrowserSearchProvider.search() will fetch per query.
    serp_max_pages: int = 1
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
        options: SearchOptions | None = None,
    ) -> SearchResult:
        """
        Execute a search designed by Cursor AI.

        Applies ADR-0002 pipeline timeout for safe stop on Cursor AI idle.

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
        timeout_seconds = settings.task_limits.cursor_idle_timeout_seconds

        with LogContext(task_id=self.task_id, search_id=search_id):
            logger.info(
                "Executing search",
                query=query[:100],
                refute=options.refute,
                timeout=timeout_seconds,
            )

            result = SearchResult(
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
        options: SearchOptions,
        result: SearchResult,
    ) -> SearchResult:
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
        options: SearchOptions,
        result: SearchResult,
    ) -> SearchResult:
        """Execute normal search mode.

        Always runs unified dual-source search (Academic API + Browser SERP) per ADR-0016.
        Results are deduplicated via CanonicalPaperIndex, citation graph is processed once.
        """
        # Always use unified dual-source search (no is_academic branching)
        return await self._execute_unified_search(search_id, query, options, result)

    async def _execute_fetch_extract(
        self,
        search_id: str,
        query: str,
        options: SearchOptions,
        result: SearchResult,
    ) -> SearchResult:
        """Execute fetch and extract via SearchExecutor.

        Runs SearchExecutor to fetch pages and extract content/claims.
        Does NOT perform SERP search or citation graph processing
        (those are handled in _execute_unified_search to avoid duplication).

        Args:
            search_id: Search ID
            query: Search query
            options: Search options
            result: SearchResult to update

        Returns:
            Updated SearchResult with fetch/extract stats
        """
        # ADR-0014 Phase 3: pass worker_id for context isolation
        executor = SearchExecutor(self.task_id, self.state, worker_id=options.worker_id)
        budget_pages = options.budget_pages

        exec_result = await executor.execute(
            query=query,
            priority="high" if options.seek_primary else "medium",
            budget_pages=budget_pages,
            engines=options.engines,
            serp_max_pages=options.serp_max_pages,
            search_job_id=options.search_job_id,  # ADR-0007
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
        options: SearchOptions,
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
        from src.search.provider import SearchResult as ProviderSearchResult

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

                # Convert dict to SearchResult
                serp_result = ProviderSearchResult(
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

    async def _process_citation_graph(
        self,
        search_id: str,
        query: str,
        index: Any,
        options: SearchOptions,
        result: SearchResult,
    ) -> None:
        """Process citation graph for papers with abstracts.

        Args:
            search_id: Search ID
            query: Search query
            index: CanonicalPaperIndex with papers
            options: Search options
            result: SearchResult to update
        """
        from src.filter.evidence_graph import (
            NodeType,
            add_academic_page_with_citations,
            get_evidence_graph,
        )
        from src.search.academic_provider import AcademicSearchProvider
        from src.utils.config import get_settings

        academic_provider = AcademicSearchProvider()
        paper_to_page_map: dict[str, str] = {}

        try:
            unique_entries = index.get_all_entries()

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

                        # Track mapping for citation graph (only if page_id is valid)
                        if page_id is not None:
                            paper_to_page_map[entry.paper.id] = page_id

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

            # Citation graph integration
            papers_with_abstracts = [
                entry.paper
                for entry in unique_entries
                if entry.paper and entry.paper.abstract and entry.paper.id in paper_to_page_map
            ]

            settings = get_settings()
            top_n = settings.search.citation_graph_top_n_papers
            depth = settings.search.citation_graph_depth
            direction = settings.search.citation_graph_direction

            papers_with_abstracts = papers_with_abstracts[:top_n]

            for paper in papers_with_abstracts:
                try:
                    # Get citation graph
                    related_papers, citations = await academic_provider.get_citation_graph(
                        paper_id=paper.id,
                        depth=depth,
                        direction=direction,
                    )

                    # Relevance filtering + auto-persist top citations
                    try:
                        from src.search.citation_filter import filter_relevant_citations

                        filtered = await filter_relevant_citations(
                            query=query,
                            source_paper=paper,
                            candidate_papers=related_papers,
                        )
                    except Exception as e:
                        logger.debug(
                            "Citation relevance filtering failed; skipping persist",
                            paper_id=paper.id,
                            error=str(e),
                        )
                        filtered = []

                    # Persist relevant citation papers (Abstract Only)
                    for scored in filtered:
                        rp = scored.paper
                        if rp.id in paper_to_page_map:
                            continue
                        if not rp.abstract:
                            continue
                        try:
                            (
                                cited_page_id,
                                cited_fragment_id,
                            ) = await self._persist_abstract_as_fragment(
                                paper=rp,
                                task_id=self.task_id,
                                search_id=search_id,
                                worker_id=options.worker_id,
                            )
                            # Only add to map if we got a valid page_id
                            if cited_page_id:
                                paper_to_page_map[rp.id] = cited_page_id
                                graph = await get_evidence_graph(self.task_id)
                                graph.add_node(NodeType.PAGE, cited_page_id)

                                # FIX: Update ExplorationState metrics for citation papers
                                if cited_fragment_id is not None:
                                    result.pages_fetched += 1
                                    result.useful_fragments += 1

                                    # Extract domain from paper URL
                                    rp_url = rp.oa_url or (
                                        f"https://doi.org/{rp.doi}" if rp.doi else ""
                                    )
                                    rp_domain = self._extract_domain(rp_url)

                                    is_independent = rp_domain not in self._seen_domains
                                    if is_independent:
                                        self._seen_domains.add(rp_domain)

                                    # Record page fetch in ExplorationState
                                    self.state.record_page_fetch(
                                        search_id=search_id,
                                        domain=rp_domain,
                                        is_primary_source=True,
                                        is_independent=is_independent,
                                    )

                                    # Record fragment in ExplorationState
                                    import hashlib

                                    rp_hash = hashlib.sha256(
                                        rp.abstract[:500].encode()
                                    ).hexdigest()[:16]
                                    rp_novel = rp_hash not in self._seen_fragment_hashes
                                    if rp_novel:
                                        self._seen_fragment_hashes.add(rp_hash)

                                    self.state.record_fragment(
                                        search_id=search_id,
                                        fragment_hash=rp_hash,
                                        is_useful=True,
                                        is_novel=rp_novel,
                                    )

                        except Exception as e:
                            logger.debug(
                                "Failed to persist citation paper",
                                paper_id=rp.id,
                                error=str(e),
                            )

                    # Look up page_id from mapping
                    mapped_page_id = paper_to_page_map.get(paper.id)

                    if mapped_page_id and citations:
                        # Build paper_metadata
                        paper_metadata = {
                            "paper_id": paper.id,
                            "doi": paper.doi,
                            "arxiv_id": paper.arxiv_id,
                            "authors": [
                                {"name": a.name, "affiliation": a.affiliation, "orcid": a.orcid}
                                for a in paper.authors
                            ],
                            "year": paper.year,
                            "venue": paper.venue,
                            "citation_count": paper.citation_count,
                            "reference_count": paper.reference_count,
                            "is_open_access": paper.is_open_access,
                            "oa_url": paper.oa_url,
                            "pdf_url": paper.pdf_url,
                            "source_api": paper.source_api,
                        }

                        await add_academic_page_with_citations(
                            page_id=mapped_page_id,
                            paper_metadata=paper_metadata,
                            citations=citations,
                            task_id=self.task_id,
                            paper_to_page_map=paper_to_page_map,
                        )

                        logger.debug(
                            "Added citation graph",
                            paper_id=paper.id,
                            page_id=mapped_page_id,
                            citation_count=len(citations),
                        )

                except Exception as e:
                    logger.warning("Failed to get citation graph", paper_id=paper.id, error=str(e))

        finally:
            await academic_provider.close()

    async def _execute_unified_search(
        self,
        search_id: str,
        query: str,
        options: SearchOptions,
        result: SearchResult,
    ) -> SearchResult:
        """Execute unified dual-source search (Browser SERP + Academic API).

        Always runs both sources in parallel per ADR-0016:
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
        from src.search.provider import SearchResult as ProviderSearchResult
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
                engines=options.engines,
                serp_max_pages=options.serp_max_pages,
                worker_id=options.worker_id,
            )

            academic_task = academic_provider.search(query, cast(Any, options))

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

                # Convert dict to SearchResult
                serp_result = ProviderSearchResult(
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

            # -6: Process unique entries and citation graph (using common method)
            await self._process_citation_graph(
                search_id=search_id,
                query=query,
                index=index,
                options=options,
                result=result,
            )

            # For entries that need fetch (no abstract available), use SearchExecutor
            # This includes: SERP-only entries, and entries with paper but no abstract
            entries_needing_fetch = [e for e in unique_entries if e.needs_fetch]
            if entries_needing_fetch:
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

            return result
        finally:
            # Cleanup: Close HTTP sessions to prevent resource leaks
            await resolver.close()
            await academic_provider.close()

    async def _persist_abstract_as_fragment(
        self,
        paper: "Paper",
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
        import json

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

        # Prepare paper_metadata JSON
        paper_metadata = {
            "doi": paper.doi,
            "arxiv_id": paper.arxiv_id,
            "authors": [
                {"name": a.name, "affiliation": a.affiliation, "orcid": a.orcid}
                for a in paper.authors
            ],
            "year": paper.year,
            "venue": paper.venue,
            "citation_count": paper.citation_count,
            "reference_count": paper.reference_count,
            "is_open_access": paper.is_open_access,
            "oa_url": paper.oa_url,
            "pdf_url": paper.pdf_url,
            "source_api": paper.source_api,
        }

        # Generate page ID
        page_id = f"page_{uuid.uuid4().hex[:8]}"

        try:
            # Insert into pages table (use or_ignore for safety)
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
                    "paper_metadata": json.dumps(paper_metadata),
                    "fetched_at": time.time(),
                },
                auto_id=False,
                or_ignore=True,
            )

            # Insert abstract as fragment
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
        paper: "Paper",
        task_id: str,
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

                    # Persist claim to DB
                    try:
                        insert_result = await db.insert(
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

                    # Create edge from fragment to claim (NLI evaluation)
                    try:
                        from src.filter.nli import nli_judge

                        # nli_judge returns list[dict] directly (not wrapped in {"ok": ..., "results": ...})
                        nli_results = await nli_judge(
                            pairs=[
                                {
                                    "pair_id": f"{fragment_id}_{claim_id}",
                                    "premise": paper.abstract[:1000],
                                    "hypothesis": claim_text,
                                }
                            ]
                        )

                        if nli_results and len(nli_results) > 0:
                            nli_item = nli_results[0]
                            stance = nli_item.get("stance", "neutral")
                            nli_confidence = nli_item.get("nli_edge_confidence", 0.5)

                            # Sanitize stance (nli_judge returns "supports"/"refutes"/"neutral")
                            if stance not in ("supports", "refutes", "neutral"):
                                relation = "neutral"
                            else:
                                relation = stance

                            edge_id = f"e_{uuid.uuid4().hex[:8]}"
                            await db.insert(
                                "edges",
                                {
                                    "id": edge_id,
                                    "source_type": "fragment",
                                    "source_id": fragment_id,
                                    "target_type": "claim",
                                    "target_id": claim_id,
                                    "relation": relation,
                                    "nli_label": stance,
                                    "nli_edge_confidence": nli_confidence,
                                },
                                auto_id=False,
                                or_ignore=True,
                            )
                    except Exception as e:
                        logger.debug(
                            "NLI evaluation failed for abstract claim",
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
                    "hypothesis": claim_text,
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
    # Convert options dict to SearchOptions
    search_options = SearchOptions()
    if options:
        if "max_pages" in options:
            # Legacy key is rejected (see ADR-0003: MCP contract stability via explicit schema).
            raise ValueError("options.max_pages is no longer supported; use options.budget_pages")
        search_options.engines = options.get("engines")
        search_options.budget_pages = options.get("budget_pages")
        search_options.serp_max_pages = int(options.get("serp_max_pages", 1))
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
    reason: str = "completed",
    mode: str = "graceful",
) -> dict[str, Any]:
    """
    Unified API for stop_task action.

    Finalizes exploration and returns summary. MCP handler delegates to this
    function (see ADR-0003, ADR-0010).

    Args:
        task_id: The task ID.
        state: The exploration state manager.
        reason: Stop reason ("completed", "budget_exhausted", "user_cancelled").
        mode: Stop mode ("graceful" or "immediate"). Controls how running
              search queue jobs are handled. The MCP handler cancels jobs
              in DB before calling this function.

    Returns:
        Finalization result dict (summary, metrics, final status).
    """
    with LogContext(task_id=task_id):
        logger.info("Stopping task", reason=reason, mode=mode)

        # Finalize exploration
        finalize_result = await state.finalize()

        # Save final state
        await state.save_state()

        # Map to ADR-0003 schema
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
