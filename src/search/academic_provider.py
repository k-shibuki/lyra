"""
Academic search provider integrating multiple academic APIs.

Provides unified interface for searching academic papers from:
- Semantic Scholar (priority=1, citation graphs)
- OpenAlex (priority=2, large-scale search)
- Crossref (priority=3, DOI resolution)
- arXiv (priority=4, preprints)
"""

import asyncio
from typing import Any

from src.search.apis.arxiv import ArxivClient
from src.search.apis.base import BaseAcademicClient
from src.search.apis.crossref import CrossrefClient
from src.search.apis.openalex import OpenAlexClient
from src.search.apis.semantic_scholar import SemanticScholarClient
from src.search.apis.unpaywall import UnpaywallClient
from src.search.canonical_index import CanonicalPaperIndex
from src.search.provider import BaseSearchProvider, SearchOptions, SearchResponse
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
        "crossref": 3,
        "arxiv": 4,
        "unpaywall": 5,
    }

    def __init__(self) -> None:
        """Initialize academic search provider."""
        super().__init__("academic")
        self._clients: dict[str, BaseAcademicClient] = {}
        self._default_apis = ["semantic_scholar", "openalex"]  # Default APIs to use
        self._last_index: CanonicalPaperIndex | None = None  # Expose last search index
        self._unpaywall_enabled: bool | None = None  # Cache for Unpaywall enabled status

    def get_last_index(self) -> CanonicalPaperIndex | None:
        """Get the CanonicalPaperIndex from the last search.

        Returns the internal index containing Paper objects with full metadata.

        Returns:
            CanonicalPaperIndex or None if no search has been performed
        """
        return self._last_index

    def _is_unpaywall_enabled(self) -> bool:
        """Check if Unpaywall is enabled via configuration.

        Returns:
            True if Unpaywall is enabled, False otherwise (default: False)
        """
        if self._unpaywall_enabled is None:
            try:
                from src.utils.config import get_academic_apis_config

                config = get_academic_apis_config()
                unpaywall_config = config.apis.get("unpaywall")
                # Default to False if config not found (opt-in behavior)
                self._unpaywall_enabled = unpaywall_config.enabled if unpaywall_config else False
            except Exception as e:
                logger.debug("Failed to check Unpaywall enabled status", error=str(e))
                # Default to False on error (opt-in behavior)
                self._unpaywall_enabled = False
        return self._unpaywall_enabled

    async def _get_client(self, api_name: str) -> BaseAcademicClient:
        """Get client (lazy initialization)."""
        if api_name not in self._clients:
            if api_name == "semantic_scholar":
                self._clients[api_name] = SemanticScholarClient()
            elif api_name == "openalex":
                self._clients[api_name] = OpenAlexClient()
            elif api_name == "crossref":
                self._clients[api_name] = CrossrefClient()
            elif api_name == "arxiv":
                self._clients[api_name] = ArxivClient()
            elif api_name == "unpaywall":
                # Check if Unpaywall is enabled before initializing
                if not self._is_unpaywall_enabled():
                    raise ValueError("Unpaywall API is disabled")
                self._clients[api_name] = UnpaywallClient()
            else:
                raise ValueError(f"Unknown API: {api_name}")
        return self._clients[api_name]

    async def search(
        self,
        query: str,
        options: SearchOptions | None = None,
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
            options = SearchOptions()

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
                search_result = entry.paper.to_search_result()
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
        to_explore = [(paper_id, 0)]  # (paper_id, current_depth)
        explored = set()

        while to_explore:
            current_id, current_depth = to_explore.pop(0)
            if current_id in explored or current_depth >= depth:
                continue
            explored.add(current_id)

            # Get references from both APIs in parallel
            if direction in ("references", "both"):
                s2_refs_task = s2_client.get_references(current_id)
                oa_refs_task = oa_client.get_references(current_id)

                try:
                    results = await asyncio.gather(
                        s2_refs_task, oa_refs_task, return_exceptions=True
                    )
                    s2_refs_raw, oa_refs_raw = results
                except Exception as e:
                    logger.debug(
                        "Failed to get references in parallel", paper_id=current_id, error=str(e)
                    )
                    s2_refs_raw = []
                    oa_refs_raw = []

                # Handle exceptions
                if isinstance(s2_refs_raw, Exception):
                    logger.debug("S2 references failed", paper_id=current_id, error=str(s2_refs_raw))
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
                            )
                        )
                        citation_pairs.add(pair_key)
                    if current_depth + 1 < depth:
                        to_explore.append((ref_paper.id, current_depth + 1))

                for ref_paper in oa_refs:
                    index.register_paper(ref_paper, source_api="openalex")
                    pair_key = (current_id, ref_paper.id)
                    if pair_key not in citation_pairs:
                        citations.append(
                            Citation(
                                citing_paper_id=current_id,
                                cited_paper_id=ref_paper.id,
                                context=None,
                            )
                        )
                        citation_pairs.add(pair_key)
                    if current_depth + 1 < depth:
                        to_explore.append((ref_paper.id, current_depth + 1))

            # Get citations from both APIs in parallel
            if direction in ("citations", "both"):
                s2_cits_task = s2_client.get_citations(current_id)
                oa_cits_task = oa_client.get_citations(current_id)

                try:
                    results = await asyncio.gather(
                        s2_cits_task, oa_cits_task, return_exceptions=True
                    )
                    s2_cits_raw, oa_cits_raw = results
                except Exception as e:
                    logger.debug(
                        "Failed to get citations in parallel", paper_id=current_id, error=str(e)
                    )
                    s2_cits_raw = []
                    oa_cits_raw = []

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
                            )
                        )
                        citation_pairs.add(pair_key)
                    if current_depth + 1 < depth:
                        to_explore.append((cit_paper.id, current_depth + 1))

                for cit_paper in oa_cits:
                    index.register_paper(cit_paper, source_api="openalex")
                    pair_key = (cit_paper.id, current_id)
                    if pair_key not in citation_pairs:
                        citations.append(
                            Citation(
                                citing_paper_id=cit_paper.id,
                                cited_paper_id=current_id,
                                context=None,
                            )
                        )
                        citation_pairs.add(pair_key)
                    if current_depth + 1 < depth:
                        to_explore.append((cit_paper.id, current_depth + 1))

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

    async def resolve_oa_url_for_paper(self, paper: Paper) -> str | None:
        """Resolve OA URL for a paper using Unpaywall if not already available.

        Args:
            paper: Paper object

        Returns:
            OA URL if resolved, None otherwise
        """
        # If paper already has OA URL, return it
        if paper.oa_url:
            return paper.oa_url

        # If no DOI, cannot resolve
        if not paper.doi:
            return None

        # Check if Unpaywall is enabled before attempting resolution
        if not self._is_unpaywall_enabled():
            logger.debug("Unpaywall is disabled, skipping OA URL resolution", doi=paper.doi)
            return None

        # Try Unpaywall API
        try:
            from src.search.apis.unpaywall import UnpaywallClient

            unpaywall_client = await self._get_client("unpaywall")
            # _get_client("unpaywall") always returns UnpaywallClient when enabled
            if not isinstance(unpaywall_client, UnpaywallClient):
                return None
            oa_url = await unpaywall_client.resolve_oa_url(paper.doi)
            if oa_url:
                logger.debug("Resolved OA URL via Unpaywall", doi=paper.doi, oa_url=oa_url)
                return oa_url
        except ValueError as e:
            # Unpaywall is disabled
            logger.debug("Unpaywall is disabled", error=str(e))
            return None
        except Exception as e:
            logger.debug("Failed to resolve OA URL via Unpaywall", doi=paper.doi, error=str(e))

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
