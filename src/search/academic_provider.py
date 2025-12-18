"""
Academic search provider integrating multiple academic APIs.

Provides unified interface for searching academic papers from:
- Semantic Scholar (priority=1, citation graphs)
- OpenAlex (priority=2, large-scale search)
- Crossref (priority=3, DOI resolution)
- arXiv (priority=4, preprints)
"""

import asyncio
from collections import deque
from typing import Optional

from src.search.provider import BaseSearchProvider, SearchResponse, SearchOptions, SearchResult
from src.search.apis.base import BaseAcademicClient
from src.search.apis.semantic_scholar import SemanticScholarClient
from src.search.apis.openalex import OpenAlexClient
from src.search.apis.crossref import CrossrefClient
from src.search.apis.arxiv import ArxivClient
from src.search.apis.unpaywall import UnpaywallClient
from src.search.canonical_index import CanonicalPaperIndex
from src.utils.schemas import Paper
from src.utils.logging import get_logger

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
    
    def __init__(self):
        """Initialize academic search provider."""
        super().__init__("academic")
        self._clients: dict[str, BaseAcademicClient] = {}
        self._default_apis = ["semantic_scholar", "openalex"]  # Default APIs to use
        self._last_index: Optional[CanonicalPaperIndex] = None  # Expose last search index
        self._unpaywall_enabled: Optional[bool] = None  # Cache for Unpaywall enabled status
    
    def get_last_index(self) -> Optional[CanonicalPaperIndex]:
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
        options: Optional[SearchOptions] = None,
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
        apis_to_use = sorted(
            apis_to_use,
            key=lambda api: self.API_PRIORITY.get(api, 999)
        )
        
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
        for api_name, result in zip(apis_to_use, results):
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
        """Get citation graph.
        
        Args:
            paper_id: Starting paper ID
            depth: Search depth (1=direct citations only, 2=citations of citations)
            direction: Search direction
            
        Returns:
            (papers, citations) tuple
        """
        # Prefer Semantic Scholar (best citation graph coverage)
        client = await self._get_client("semantic_scholar")

        papers: dict[str, Paper] = {}
        citations = []
        # Use deque for O(1) popleft() in BFS traversal
        to_explore: deque[tuple[str, int]] = deque([(paper_id, 0)])  # (paper_id, current_depth)
        explored = set()

        while to_explore:
            current_id, current_depth = to_explore.popleft()
            if current_id in explored or current_depth >= depth:
                continue
            explored.add(current_id)
            
            # Get references
            if direction in ("references", "both"):
                refs = await client.get_references(current_id)
                for ref_paper, is_influential in refs:
                    papers[ref_paper.id] = ref_paper
                    from src.utils.schemas import Citation
                    citations.append(Citation(
                        citing_paper_id=current_id,
                        cited_paper_id=ref_paper.id,
                        is_influential=is_influential
                    ))
                    if current_depth + 1 < depth:
                        to_explore.append((ref_paper.id, current_depth + 1))
            
            # Get citations
            if direction in ("citations", "both"):
                cits = await client.get_citations(current_id)
                for cit_paper, is_influential in cits:
                    papers[cit_paper.id] = cit_paper
                    from src.utils.schemas import Citation
                    citations.append(Citation(
                        citing_paper_id=cit_paper.id,
                        cited_paper_id=current_id,
                        is_influential=is_influential
                    ))
                    if current_depth + 1 < depth:
                        to_explore.append((cit_paper.id, current_depth + 1))
        
        return list(papers.values()), citations
    
    async def resolve_oa_url_for_paper(self, paper: Paper) -> Optional[str]:
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
            unpaywall_client = await self._get_client("unpaywall")
            # _get_client("unpaywall") always returns UnpaywallClient when enabled
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
    
    async def get_health(self):
        """Get health status."""
        from src.search.provider import HealthStatus, HealthState
        
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
