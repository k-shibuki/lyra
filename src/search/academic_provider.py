"""
Academic search provider integrating multiple academic APIs.

Provides unified interface for searching academic papers from:
- Semantic Scholar (priority=1, citation graphs)
- OpenAlex (priority=2, large-scale search)
"""

import asyncio
from typing import Any

from src.search.apis.base import BaseAcademicClient
from src.search.apis.openalex import OpenAlexClient
from src.search.apis.semantic_scholar import SemanticScholarClient
from src.search.canonical_index import CanonicalPaperIndex
from src.search.provider import BaseSearchProvider, SearchProviderOptions, SearchResponse
from src.utils.logging import get_logger
from src.utils.schemas import Paper

logger = get_logger(__name__)


class AcademicSearchProvider(BaseSearchProvider):
    """Academic API integration provider.

    Integrates multiple academic APIs into a unified interface for search and
    citation graph retrieval. Early deduplication ensures each unique paper
    is processed only once.
    """

    # API priority (lower number = higher priority)
    API_PRIORITY = {
        "semantic_scholar": 1,
        "openalex": 2,
    }

    def __init__(self) -> None:
        """Initialize academic search provider."""
        super().__init__("academic")
        self._clients: dict[str, BaseAcademicClient] = {}
        self._default_apis = ["semantic_scholar", "openalex"]  # Default APIs to use
        self._last_index: CanonicalPaperIndex | None = None  # Expose last search index

    def get_last_index(self) -> CanonicalPaperIndex | None:
        """Get the CanonicalPaperIndex from the last search.

        Returns the internal index containing Paper objects with full metadata.

        Returns:
            CanonicalPaperIndex or None if no search has been performed
        """
        return self._last_index

    async def _get_client(self, api_name: str) -> BaseAcademicClient:
        """Get client (lazy initialization)."""
        if api_name not in self._clients:
            if api_name == "semantic_scholar":
                self._clients[api_name] = SemanticScholarClient()
            elif api_name == "openalex":
                self._clients[api_name] = OpenAlexClient()
            else:
                raise ValueError(f"Unknown API: {api_name}")
        return self._clients[api_name]

    async def search(
        self,
        query: str,
        options: SearchProviderOptions | None = None,
    ) -> SearchResponse:
        """Search for academic papers.

        Calls multiple APIs in parallel, merges and deduplicates results.

        Args:
            query: Search query
            options: Search options

        Returns:
            SearchResponse with deduplicated results
        """
        if options is None:
            options = SearchProviderOptions()

        apis_to_use = options.engines if options.engines else self._default_apis

        # Sort by priority
        apis_to_use = sorted(apis_to_use, key=lambda api: self.API_PRIORITY.get(api, 999))

        # Parallel search
        tasks = []
        for api_name in apis_to_use:
            try:
                client = await self._get_client(api_name)
                limit = options.limit if options else 10
                tasks.append(client.search(query, limit=limit))
            except Exception as e:
                logger.warning("Failed to create search task", api=api_name, error=str(e))

        if not tasks:
            return SearchResponse(
                results=[],
                query=query,
                provider=self.name,
                error="No API clients available",
            )

        # Execute in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Early deduplication
        index = CanonicalPaperIndex()

        # Register in priority order (higher priority API registered first)
        for api_name, result in zip(apis_to_use, results, strict=False):
            if isinstance(result, Exception):
                logger.warning("API search failed", api=api_name, error=str(result))
                continue

            from src.utils.schemas import AcademicSearchResult

            if not isinstance(result, AcademicSearchResult):
                continue

            # Register each paper (duplicates are automatically skipped)
            for paper in result.papers:
                index.register_paper(paper, source_api=api_name)

        # Store index for external access (e.g., to get Paper objects)
        self._last_index = index

        # Get unique paper list
        unique_entries = index.get_all_entries()
        stats = index.get_stats()

        logger.info(
            "Academic API search completed",
            query=query[:100],
            apis_used=apis_to_use,
            total_raw=sum(
                len(r.papers) if isinstance(r, AcademicSearchResult) else 0
                for r in results
                if not isinstance(r, Exception)
            ),
            unique_count=stats["total"],
            dedup_stats=stats,
        )

        # Convert to SearchResponse format
        search_results = []
        for entry in unique_entries:
            if entry.paper:
                search_result = entry.paper.to_serp_result()
                search_results.append(search_result)

        return SearchResponse(
            results=search_results,
            query=query,
            provider=self.name,
            total_count=len(search_results),
        )

    async def get_citation_graph(
        self,
        paper_id: str,
        depth: int = 1,
        direction: str = "both",  # "references", "citations", "both"
    ) -> tuple[list[Paper], list]:
        """Get citation graph from S2 + OpenAlex (integrated).

        Fetches citations from both Semantic Scholar and OpenAlex in parallel,
        then deduplicates using CanonicalPaperIndex.

        Args:
            paper_id: Starting paper ID
            depth: Search depth (1=direct citations only, 2=citations of citations)
            direction: Search direction

        Returns:
            (papers, citations) tuple
        """
        import asyncio

        from src.utils.schemas import Citation

        # Get both clients
        s2_client = await self._get_client("semantic_scholar")
        oa_client = await self._get_client("openalex")

        # Use CanonicalPaperIndex for deduplication
        index = CanonicalPaperIndex()
        citations = []
        citation_pairs = set()  # Track citation pairs to avoid duplicates across APIs

        # Get DOI for the starting paper to enable cross-API queries
        initial_doi: str | None = None
        if paper_id.startswith("s2:"):
            # Try to get DOI from S2
            paper_obj = await s2_client.get_paper(paper_id)
            if paper_obj:
                initial_doi = paper_obj.doi
                index.register_paper(paper_obj, source_api="semantic_scholar")
        elif paper_id.startswith("openalex:"):
            # Try to get DOI from OpenAlex
            paper_obj = await oa_client.get_paper(paper_id)
            if paper_obj:
                initial_doi = paper_obj.doi
                index.register_paper(paper_obj, source_api="openalex")

        # (paper_id, current_depth, doi) - DOI enables cross-API queries
        to_explore: list[tuple[str, int, str | None]] = [(paper_id, 0, initial_doi)]
        explored = set()

        while to_explore:
            current_id, current_depth, current_doi = to_explore.pop(0)
            if current_id in explored or current_depth >= depth:
                continue
            explored.add(current_id)

            # Determine IDs for each API based on prefix and DOI availability
            # DOI is the universal identifier that both APIs can resolve
            s2_query_id: str | None = None
            oa_query_id: str | None = None

            if current_doi:
                # DOI available: both APIs can search using DOI
                s2_query_id = f"DOI:{current_doi}"  # S2 accepts DOI: prefix
                oa_query_id = f"https://doi.org/{current_doi}"  # OpenAlex accepts DOI URL
            elif (
                current_id.startswith("s2:")
                or current_id.startswith("DOI:")
                or current_id.startswith("ArXiv:")
                or current_id.startswith("PMID:")
            ):
                # S2-compatible ID only
                s2_query_id = current_id
            elif current_id.startswith("openalex:") or current_id.startswith(
                "https://openalex.org/"
            ):
                # OpenAlex-compatible ID only
                oa_query_id = current_id
            else:
                # Unknown format: try both with original ID
                s2_query_id = current_id
                oa_query_id = current_id

            # Get references from appropriate APIs
            if direction in ("references", "both"):
                s2_refs_raw: list[Paper] | BaseException = []
                oa_refs_raw: list[Paper] | BaseException = []

                tasks = []
                task_names = []
                if s2_query_id:
                    tasks.append(s2_client.get_references(s2_query_id))
                    task_names.append("s2")
                if oa_query_id:
                    tasks.append(oa_client.get_references(oa_query_id))
                    task_names.append("oa")

                if tasks:
                    try:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        for name, result in zip(task_names, results, strict=False):
                            if name == "s2":
                                s2_refs_raw = result
                            else:
                                oa_refs_raw = result
                    except Exception as e:
                        logger.debug("Failed to get references", paper_id=current_id, error=str(e))

                # Handle exceptions
                if isinstance(s2_refs_raw, Exception):
                    logger.debug(
                        "S2 references failed", paper_id=current_id, error=str(s2_refs_raw)
                    )
                    s2_refs: list[Paper] = []
                elif isinstance(s2_refs_raw, list):
                    s2_refs = s2_refs_raw
                else:
                    s2_refs = []
                if isinstance(oa_refs_raw, Exception):
                    logger.debug(
                        "OpenAlex references failed", paper_id=current_id, error=str(oa_refs_raw)
                    )
                    oa_refs: list[Paper] = []
                elif isinstance(oa_refs_raw, list):
                    oa_refs = oa_refs_raw
                else:
                    oa_refs = []

                # Register all references in index (deduplication happens automatically)
                for ref_paper in s2_refs:
                    index.register_paper(ref_paper, source_api="semantic_scholar")
                    pair_key = (current_id, ref_paper.id)
                    if pair_key not in citation_pairs:
                        citations.append(
                            Citation(
                                citing_paper_id=current_id,
                                cited_paper_id=ref_paper.id,
                                context=None,
                                source_api="semantic_scholar",
                            )
                        )
                        citation_pairs.add(pair_key)
                    if current_depth + 1 < depth:
                        # Include DOI for cross-API queries in next iteration
                        to_explore.append((ref_paper.id, current_depth + 1, ref_paper.doi))

                for ref_paper in oa_refs:
                    index.register_paper(ref_paper, source_api="openalex")
                    pair_key = (current_id, ref_paper.id)
                    if pair_key not in citation_pairs:
                        citations.append(
                            Citation(
                                citing_paper_id=current_id,
                                cited_paper_id=ref_paper.id,
                                context=None,
                                source_api="openalex",
                            )
                        )
                        citation_pairs.add(pair_key)
                    if current_depth + 1 < depth:
                        # Include DOI for cross-API queries in next iteration
                        to_explore.append((ref_paper.id, current_depth + 1, ref_paper.doi))

            # Get citations from appropriate APIs (based on ID format and DOI)
            if direction in ("citations", "both"):
                s2_cits_raw: list[Paper] | BaseException = []
                oa_cits_raw: list[Paper] | BaseException = []

                tasks = []
                task_names = []
                if s2_query_id:
                    tasks.append(s2_client.get_citations(s2_query_id))
                    task_names.append("s2")
                if oa_query_id:
                    tasks.append(oa_client.get_citations(oa_query_id))
                    task_names.append("oa")

                if tasks:
                    try:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        for name, result in zip(task_names, results, strict=False):
                            if name == "s2":
                                s2_cits_raw = result
                            else:
                                oa_cits_raw = result
                    except Exception as e:
                        logger.debug("Failed to get citations", paper_id=current_id, error=str(e))

                # Handle exceptions
                if isinstance(s2_cits_raw, Exception):
                    logger.debug("S2 citations failed", paper_id=current_id, error=str(s2_cits_raw))
                    s2_cits: list[Paper] = []
                elif isinstance(s2_cits_raw, list):
                    s2_cits = s2_cits_raw
                else:
                    s2_cits = []
                if isinstance(oa_cits_raw, Exception):
                    logger.debug(
                        "OpenAlex citations failed", paper_id=current_id, error=str(oa_cits_raw)
                    )
                    oa_cits: list[Paper] = []
                elif isinstance(oa_cits_raw, list):
                    oa_cits = oa_cits_raw
                else:
                    oa_cits = []

                # Register all citations in index (deduplication happens automatically)
                for cit_paper in s2_cits:
                    index.register_paper(cit_paper, source_api="semantic_scholar")
                    pair_key = (cit_paper.id, current_id)
                    if pair_key not in citation_pairs:
                        citations.append(
                            Citation(
                                citing_paper_id=cit_paper.id,
                                cited_paper_id=current_id,
                                context=None,
                                source_api="semantic_scholar",
                            )
                        )
                        citation_pairs.add(pair_key)
                    if current_depth + 1 < depth:
                        # Include DOI for cross-API queries in next iteration
                        to_explore.append((cit_paper.id, current_depth + 1, cit_paper.doi))

                for cit_paper in oa_cits:
                    index.register_paper(cit_paper, source_api="openalex")
                    pair_key = (cit_paper.id, current_id)
                    if pair_key not in citation_pairs:
                        citations.append(
                            Citation(
                                citing_paper_id=cit_paper.id,
                                cited_paper_id=current_id,
                                context=None,
                                source_api="openalex",
                            )
                        )
                        citation_pairs.add(pair_key)
                    if current_depth + 1 < depth:
                        # Include DOI for cross-API queries in next iteration
                        to_explore.append((cit_paper.id, current_depth + 1, cit_paper.doi))

        # Get unique papers from index
        unique_entries = index.get_all_entries()
        papers = [entry.paper for entry in unique_entries if entry.paper]

        logger.info(
            "Citation graph integrated",
            paper_id=paper_id,
            unique_papers=len(papers),
            total_citations=len(citations),
            s2_oa_integrated=True,
        )

        return papers, citations

    async def get_paper_by_doi(self, doi: str) -> Paper | None:
        """Get paper metadata by DOI.

        Tries Semantic Scholar first (higher priority), then OpenAlex.
        Returns the first successful result with abstract.

        Args:
            doi: DOI string (e.g., "10.1234/example")

        Returns:
            Paper object with metadata and abstract, or None if not found
        """
        # Normalize DOI
        doi = doi.strip().lower()

        # Try Semantic Scholar first (usually has better abstracts)
        try:
            s2_client = await self._get_client("semantic_scholar")
            paper = await s2_client.get_paper(f"DOI:{doi}")
            if paper and paper.abstract:
                logger.debug(
                    "Found paper via Semantic Scholar",
                    doi=doi,
                    has_abstract=True,
                )
                return paper
        except Exception as e:
            logger.debug("Semantic Scholar lookup failed", doi=doi, error=str(e))

        # Try OpenAlex
        try:
            oa_client = await self._get_client("openalex")
            paper = await oa_client.get_paper(f"https://doi.org/{doi}")
            if paper and paper.abstract:
                logger.debug(
                    "Found paper via OpenAlex",
                    doi=doi,
                    has_abstract=True,
                )
                return paper
        except Exception as e:
            logger.debug("OpenAlex lookup failed", doi=doi, error=str(e))

        logger.warning(
            "Paper not found in any Academic API",
            doi=doi,
        )
        return None

    async def get_health(self) -> Any:
        """Get health status."""
        from src.search.provider import HealthStatus

        # Simple health check: can client be initialized
        try:
            await self._get_client("semantic_scholar")
            return HealthStatus.healthy()
        except Exception as e:
            return HealthStatus.unhealthy(str(e))

    async def close(self) -> None:
        """Close all clients."""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
        await super().close()
