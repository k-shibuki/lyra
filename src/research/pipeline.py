"""
Search pipeline for Lyra.

Unified pipeline that combines search execution with optional refutation mode.
Replaces execute_subquery and execute_refutation MCPtools with a single `search` interface.

See docs/REQUIREMENTS.md §2.1, §3.2.1.
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

    Conforms to §3.2.1 search response schema.
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

    # Timeout flag (§2.1.5)
    is_partial: bool = False  # True if result is partial due to timeout

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

        # Include partial flag for timeout (§2.1.5)
        if self.is_partial:
            result["is_partial"] = True

        return result


@dataclass
class SearchOptions:
    """Options for search execution."""

    engines: list[str] | None = None  # Use None for Lyra-selected engines
    max_pages: int | None = None
    seek_primary: bool = False  # Prioritize primary sources
    refute: bool = False  # Enable refutation mode


class SearchPipeline:
    """
    Unified search pipeline for Lyra.

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

        Applies §2.1.5 pipeline timeout for safe stop on Cursor AI idle.

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

        # Get timeout from config (§2.1.5)
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
                # Wrap execution with timeout (§2.1.5)
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
                    f"Pipeline timeout after {timeout_seconds}s (§2.1.5 safe stop)"
                )

                # Try to get partial budget info
                try:
                    overall_status = await self.state.get_status()
                    result.budget_remaining = {
                        "pages": overall_status["budget"]["pages_limit"]
                        - overall_status["budget"]["pages_used"],
                        "percent": int(
                            (
                                1
                                - overall_status["budget"]["pages_used"]
                                / overall_status["budget"]["pages_limit"]
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

        Separated from execute() for timeout wrapping (§2.1.5).
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
            "pages": overall_status["budget"]["pages_limit"]
            - overall_status["budget"]["pages_used"],
            "percent": int(
                (
                    1
                    - overall_status["budget"]["pages_used"]
                    / overall_status["budget"]["pages_limit"]
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
        """Execute normal search mode."""
        # Check if academic query
        is_academic = self._is_academic_query(query)

        if is_academic:
            # Complementary search: Browser + Academic API
            return await self._execute_complementary_search(search_id, query, options, result)
        else:
            # Standard browser search only
            return await self._execute_browser_search(search_id, query, options, result)

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
        from src.search.id_resolver import IDResolver
        from src.search.identifier_extractor import IdentifierExtractor
        from src.search.provider import SearchResult as ProviderSearchResult
        from src.search.search_api import search_serp

        logger.info("Executing complementary search", query=query[:100])

        # Initialize components
        index = CanonicalPaperIndex()
        extractor = IdentifierExtractor()
        resolver = IDResolver()
        academic_provider = AcademicSearchProvider()

        try:
            # Phase 1: Parallel search
            browser_task = search_serp(
                query=query,
                limit=options.max_pages or 20,
                task_id=self.task_id,
                engines=options.engines,
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

            # Phase 2: Register Academic API results first (structured, high priority)
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

            # Phase 5: Process unique entries (Abstract Only strategy)
            # - Skip fetch for entries with abstracts from API
            # - Fetch and extract for SERP-only entries

            from src.filter.evidence_graph import (
                NodeType,
                add_academic_page_with_citations,
                get_evidence_graph,
            )

            pages_created = 0
            fragments_created = 0
            paper_to_page_map: dict[str, str] = {}  # paper_id -> page_id mapping for citation graph

            for entry in unique_entries:
                if entry.paper and entry.paper.abstract:
                    # Try to resolve OA URL via Unpaywall if not available
                    if not entry.paper.oa_url and entry.paper.doi:
                        try:
                            resolved_oa_url = await academic_provider.resolve_oa_url_for_paper(
                                entry.paper
                            )
                            if resolved_oa_url:
                                # Update paper object with resolved OA URL
                                entry.paper.oa_url = resolved_oa_url
                                entry.paper.is_open_access = True
                        except Exception as e:
                            logger.debug(
                                "Failed to resolve OA URL via Unpaywall",
                                doi=entry.paper.doi,
                                error=str(e),
                            )

                    # Abstract Only: Skip fetch, persist abstract directly
                    try:
                        page_id, fragment_id = await self._persist_abstract_as_fragment(
                            paper=entry.paper,
                            task_id=self.task_id,
                            search_id=search_id,
                        )
                        pages_created += 1
                        fragments_created += 1

                        # Track mapping for citation graph
                        paper_to_page_map[entry.paper.id] = page_id

                        # Add to evidence graph
                        graph = await get_evidence_graph(self.task_id)
                        graph.add_node(NodeType.PAGE, page_id)

                    except Exception as e:
                        logger.warning(
                            "Failed to persist abstract", error=str(e), paper_id=entry.paper.id
                        )
                elif entry.needs_fetch:
                    # Entry needs fetch: either no paper or paper without abstract
                    # Collect URLs for browser search fallback
                    pass  # Will be handled by browser search fallback below

            # Update result stats
            result.pages_fetched += pages_created
            result.useful_fragments += fragments_created

            # Phase 6: Citation graph integration
            # Get citation graphs for top N papers with abstracts

            papers_with_abstracts = [
                entry.paper
                for entry in unique_entries
                if entry.paper and entry.paper.abstract and entry.paper.id in paper_to_page_map
            ]

            from src.utils.config import get_settings

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

                    # Phase 3: Relevance filtering + auto-persist top citations
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

                    # Persist relevant citation papers (Abstract Only) so edges are not skipped
                    for scored in filtered:
                        rp = scored.paper
                        if rp.id in paper_to_page_map:
                            continue
                        if not rp.abstract:
                            continue
                        try:
                            cited_page_id, _cited_fragment_id = await self._persist_abstract_as_fragment(
                                paper=rp,
                                task_id=self.task_id,
                                search_id=search_id,
                            )
                            paper_to_page_map[rp.id] = cited_page_id
                            graph = await get_evidence_graph(self.task_id)
                            graph.add_node(NodeType.PAGE, cited_page_id)
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

            # For entries that need fetch (no abstract available), fall back to browser search
            # This includes: SERP-only entries, and entries with paper but no abstract
            entries_needing_fetch = [e for e in unique_entries if e.needs_fetch]
            if entries_needing_fetch:
                # Use browser search for SERP-only entries
                # Save current stats before calling _execute_browser_search (it modifies result in-place)
                pages_before = result.pages_fetched
                fragments_before = result.useful_fragments

                expanded_queries = self._expand_academic_query(query)
                browser_result = await self._execute_browser_search(
                    search_id, expanded_queries[0], options, result
                )

                # Accumulate stats: add browser search results to existing counts
                # (browser_result is the same object as result, so browser_result.pages_fetched
                # contains the new value that overwrote pages_before)
                result.pages_fetched = pages_before + browser_result.pages_fetched
                result.useful_fragments = fragments_before + browser_result.useful_fragments

            return result
        finally:
            # Cleanup: Close HTTP sessions to prevent resource leaks
            await resolver.close()
            await academic_provider.close()

    def _is_academic_query(self, query: str) -> bool:
        """Determine if query is academic.

        Args:
            query: Search query

        Returns:
            True if academic query
        """
        query_lower = query.lower()

        # Keyword detection
        academic_keywords = [
            "論文",
            "paper",
            "研究",
            "study",
            "学術",
            "journal",
            "arxiv",
            "pubmed",
            "doi:",
            "citation",
            "引用",
            "preprint",
            "peer-review",
            "査読",
            "publication",
        ]
        if any(kw in query_lower for kw in academic_keywords):
            return True

        # Site specification detection
        academic_sites = [
            "arxiv.org",
            "pubmed",
            "scholar.google",
            "jstage",
            "doi.org",
            "semanticscholar.org",
            "crossref.org",
        ]
        if any(f"site:{site}" in query_lower for site in academic_sites):
            return True

        # DOI format detection
        if re.search(r"10\.\d{4,}/", query):
            return True

        return False

    def _expand_academic_query(self, query: str) -> list[str]:
        """Expand academic query into multiple site-specific queries.

        Args:
            query: Original query

        Returns:
            List of expanded queries
        """
        queries = [query]  # Original query

        # Remove site: operator
        base_query = re.sub(r"\bsite:\S+", "", query).strip()

        # Add academic site specifications (top 2 sites only)
        academic_sites = [
            "arxiv.org",
            "pubmed.ncbi.nlm.nih.gov",
        ]

        for site in academic_sites[:2]:
            queries.append(f"{base_query} site:{site}")

        return queries

    async def _persist_abstract_as_fragment(
        self,
        paper: "Paper",
        task_id: str,
        search_id: str,
    ) -> tuple[str, str]:
        """Persist abstract as fragment (Abstract Only strategy).

        Saves academic paper metadata to pages table and abstract to fragments table,
        skipping fetch/extract for papers with abstracts from academic APIs.

        Args:
            paper: Paper object with abstract
            task_id: Task ID
            search_id: Search ID

        Returns:
            (page_id, fragment_id) tuple
        """
        import json

        db = await get_database()

        # Build reference URL (OA URL or DOI URL)
        reference_url = paper.oa_url or (f"https://doi.org/{paper.doi}" if paper.doi else "")
        if not reference_url:
            # Fallback to paper ID-based URL
            reference_url = f"https://paper/{paper.id}"

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

        # Insert into pages table
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
        )

        logger.info(
            "Persisted abstract as fragment",
            page_id=page_id,
            fragment_id=fragment_id,
            paper_title=paper.title[:60],
            has_abstract=bool(paper.abstract),
        )

        return page_id, fragment_id

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL.

        Args:
            url: URL string

        Returns:
            Domain string
        """
        import re

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
                            result.claims_found.append(
                                {
                                    "id": f"c_{uuid.uuid4().hex[:8]}",
                                    "text": refutation["refuting_passage"][:200],
                                    "confidence": refutation["nli_confidence"],
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
