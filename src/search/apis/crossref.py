"""
Crossref API client.

DOI resolution and metadata normalization (priority=3).
"""

from typing import Optional

import httpx

from src.search.apis.base import BaseAcademicClient
from src.utils.schemas import Paper, Author, AcademicSearchResult
from src.utils.api_retry import retry_api_call, ACADEMIC_API_POLICY
from src.utils.logging import get_logger

logger = get_logger(__name__)


class CrossrefClient(BaseAcademicClient):
    """Crossref API client."""
    
    def __init__(self):
        """Initialize Crossref client."""
        # Load config
        try:
            from src.utils.config import get_academic_apis_config
            config = get_academic_apis_config()
            api_config = config.apis.get("crossref", {})
            base_url = api_config.base_url if api_config.base_url else "https://api.crossref.org"
            timeout = float(api_config.timeout_seconds) if api_config.timeout_seconds else 30.0
            headers = api_config.headers if api_config.headers else None
        except Exception as e:
            # Fallback to defaults if config loading fails
            logger.debug("Failed to load Crossref config, using defaults", error=str(e))
            base_url = "https://api.crossref.org"
            timeout = 30.0
            headers = None
        
        super().__init__("crossref", base_url=base_url, timeout=timeout, headers=headers)
    
    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Search for papers."""
        session = await self._get_session()
        
        async def _search():
            response = await session.get(
                f"{self.base_url}/works",
                params={"query": query, "rows": limit}
            )
            response.raise_for_status()
            return response.json()
        
        try:
            data = await retry_api_call(_search, policy=ACADEMIC_API_POLICY)
            items = data.get("message", {}).get("items", [])
            papers = [self._parse_paper(item) for item in items]
            
            return AcademicSearchResult(
                papers=papers,
                total_count=data.get("message", {}).get("total-results", 0),
                source_api="crossref"
            )
        except Exception as e:
            logger.error("Crossref search failed", query=query, error=str(e))
            return AcademicSearchResult(
                papers=[],
                total_count=0,
                source_api="crossref"
            )
    
    async def get_paper(self, paper_id: str) -> Optional[Paper]:
        """Get paper metadata by DOI."""
        return await self.get_paper_by_doi(paper_id)
    
    async def get_paper_by_doi(self, doi: str) -> Optional[Paper]:
        """Get paper metadata from DOI."""
        session = await self._get_session()
        
        async def _fetch():
            response = await session.get(f"{self.base_url}/works/{doi}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        
        try:
            data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
            if not data:
                return None
            return self._parse_paper(data.get("message", {}))
        except Exception as e:
            logger.warning("Failed to get paper by DOI", doi=doi, error=str(e))
            return None
    
    async def get_references(self, paper_id: str) -> list[tuple[Paper, bool]]:
        """Get references (Crossref does not support detailed references)."""
        # Crossref API has a references endpoint but detailed retrieval is complex
        # Simple implementation: only referenced_works_count is available via get_paper
        logger.debug("Crossref references not fully implemented", paper_id=paper_id)
        return []
    
    async def get_citations(self, paper_id: str) -> list[tuple[Paper, bool]]:
        """Get citations (Crossref does not support citations)."""
        # Crossref API does not have citation information
        logger.debug("Crossref does not support citations", paper_id=paper_id)
        return []
    
    def _parse_paper(self, data: dict) -> Paper:
        """Convert API response to Paper model."""
        authors = []
        for author_data in data.get("author", []):
            given = author_data.get("given", "")
            family = author_data.get("family", "")
            name = f"{given} {family}".strip() if given or family else ""
            if name:
                authors.append(Author(
                    name=name,
                    affiliation=None,
                    orcid=author_data.get("ORCID")
                ))
        
        doi = data.get("DOI", "")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")
        
        # Extract year from publication date
        year = None
        published = data.get("published-print") or data.get("published-online") or data.get("published")
        if published and "date-parts" in published:
            date_parts = published["date-parts"][0]
            if date_parts:
                year = date_parts[0]
        
        # Fallback: if year not found, try published-print directly
        if not year and data.get("published-print"):
            date_parts = data.get("published-print", {}).get("date-parts", [[None]])
            if date_parts and date_parts[0]:
                year = date_parts[0][0]
        
        return Paper(
            id=f"crossref:{doi}" if doi else f"crossref:{data.get('URL', '').split('/')[-1]}",
            title=data.get("title", [""])[0] if isinstance(data.get("title"), list) else data.get("title", ""),
            abstract=None,  # Crossref API often does not have abstract
            authors=authors,
            year=year,
            doi=doi if doi else None,
            venue=data.get("container-title", [""])[0] if isinstance(data.get("container-title"), list) else data.get("container-title"),
            citation_count=0,  # Crossref API does not have citation count
            reference_count=len(data.get("reference", [])) if data.get("reference") else 0,
            is_open_access=False,  # Crossref API does not have OA info
            oa_url=None,
            source_api="crossref"
        )
