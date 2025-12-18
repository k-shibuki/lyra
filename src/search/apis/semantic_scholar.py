"""
Semantic Scholar API client.

Primary API for citation graphs (priority=1).
"""

from typing import Optional

import httpx

from src.search.apis.base import BaseAcademicClient
from src.utils.schemas import Paper, Author, AcademicSearchResult
from src.utils.api_retry import retry_api_call, ACADEMIC_API_POLICY
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SemanticScholarClient(BaseAcademicClient):
    """Semantic Scholar API client."""
    
    FIELDS = "paperId,title,abstract,year,authors,citationCount,referenceCount,isOpenAccess,openAccessPdf,venue,externalIds"
    
    def __init__(self):
        """Initialize Semantic Scholar client."""
        # Load config
        try:
            from src.utils.config import get_academic_apis_config
            config = get_academic_apis_config()
            api_config = config.apis.get("semantic_scholar", {})
            base_url = api_config.base_url if api_config.base_url else "https://api.semanticscholar.org/graph/v1"
            timeout = float(api_config.timeout_seconds) if api_config.timeout_seconds else 30.0
            headers = api_config.headers if api_config.headers else None
        except Exception as e:
            # Fallback to defaults if config loading fails
            logger.debug("Config loading failed, using defaults", api="semantic_scholar", error=str(e))
            base_url = "https://api.semanticscholar.org/graph/v1"
            timeout = 30.0
            headers = None
        
        super().__init__("semantic_scholar", base_url=base_url, timeout=timeout, headers=headers)
    
    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Search for papers."""
        session = await self._get_session()
        
        async def _search():
            response = await session.get(
                f"{self.base_url}/paper/search",
                params={"query": query, "limit": limit, "fields": self.FIELDS}
            )
            response.raise_for_status()
            return response.json()
        
        try:
            data = await retry_api_call(_search, policy=ACADEMIC_API_POLICY)
            papers = [self._parse_paper(p) for p in data.get("data", [])]
            
            next_cursor = data.get("next")
            # Semantic Scholar API returns 'next' as int offset, convert to string
            if next_cursor is not None:
                next_cursor = str(next_cursor)
            
            return AcademicSearchResult(
                papers=papers,
                total_count=data.get("total", 0),
                next_cursor=next_cursor,
                source_api="semantic_scholar"
            )
        except Exception as e:
            logger.error("Semantic Scholar search failed", query=query, error=str(e))
            return AcademicSearchResult(
                papers=[],
                total_count=0,
                source_api="semantic_scholar"
            )
    
    async def get_paper(self, paper_id: str) -> Optional[Paper]:
        """Get paper metadata."""
        session = await self._get_session()
        
        # Normalize paper ID for API
        normalized_id = self._normalize_paper_id(paper_id)
        
        async def _fetch():
            response = await session.get(
                f"{self.base_url}/paper/{normalized_id}",
                params={"fields": self.FIELDS}
            )
            response.raise_for_status()
            return response.json()
        
        try:
            data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
            return self._parse_paper(data)
        except Exception as e:
            logger.warning("Failed to get paper", paper_id=paper_id, error=str(e))
            return None
    
    def _normalize_paper_id(self, paper_id: str) -> str:
        """Normalize paper ID for Semantic Scholar API.
        
        Converts internal ID format (e.g., 's2:204e3073...') to API format.
        Semantic Scholar API paperId values are 40-character alphanumeric hashes
        that should be used directly without any prefix. CorpusId: prefix is only
        for numeric Corpus IDs.
        
        Args:
            paper_id: Paper ID in various formats
            
        Returns:
            Normalized paper ID for API
        """
        # Handle s2: prefix (internal format) -> remove prefix, use paperId directly
        if paper_id.startswith("s2:"):
            # Extract paperId (40-char alphanumeric hash) and use directly
            paper_id_without_prefix = paper_id[3:]  # Remove "s2:" prefix
            return paper_id_without_prefix
        
        # Already in correct format (DOI:, ArXiv:, PMID:)
        # These prefixes are recognized by the API
        if ":" in paper_id:
            return paper_id
        
        # If no prefix, assume it's already a paperId (40-char hash) and use directly
        return paper_id
    
    async def get_references(self, paper_id: str) -> list[tuple[Paper, bool]]:
        """Get references (papers cited by this paper) with influential citation flag."""
        session = await self._get_session()
        
        # Normalize paper ID for API
        normalized_id = self._normalize_paper_id(paper_id)
        
        async def _fetch():
            response = await session.get(
                f"{self.base_url}/paper/{normalized_id}/references",
                params={"fields": self.FIELDS + ",isInfluential"}
            )
            response.raise_for_status()
            return response.json()
        
        try:
            data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
            results = []
            for ref in data.get("data", []):
                if ref.get("citedPaper"):
                    paper = self._parse_paper(ref["citedPaper"])
                    is_influential = ref.get("isInfluential", False)
                    results.append((paper, is_influential))
            return results
        except Exception as e:
            logger.warning("Failed to get references", paper_id=paper_id, error=str(e))
            return []
    
    async def get_citations(self, paper_id: str) -> list[tuple[Paper, bool]]:
        """Get citations (papers that cite this paper)."""
        session = await self._get_session()
        
        # Normalize paper ID for API
        normalized_id = self._normalize_paper_id(paper_id)
        
        async def _fetch():
            response = await session.get(
                f"{self.base_url}/paper/{normalized_id}/citations",
                params={"fields": self.FIELDS + ",isInfluential"}
            )
            response.raise_for_status()
            return response.json()
        
        try:
            data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
            results = []
            for cit in data.get("data", []):
                if cit.get("citingPaper"):
                    paper = self._parse_paper(cit["citingPaper"])
                    is_influential = cit.get("isInfluential", False)
                    results.append((paper, is_influential))
            return results
        except Exception as e:
            logger.warning("Failed to get citations", paper_id=paper_id, error=str(e))
            return []
    
    def _parse_paper(self, data: dict) -> Paper:
        """Convert API response to Paper model."""
        external_ids = data.get("externalIds", {})
        oa_pdf = data.get("openAccessPdf", {})
        
        authors = []
        for author_data in data.get("authors", []):
            authors.append(Author(
                name=author_data.get("name", ""),
                affiliation=None,  # Semantic Scholar API does not provide affiliation
                orcid=None
            ))
        
        return Paper(
            id=f"s2:{data['paperId']}",
            title=data.get("title", ""),
            abstract=data.get("abstract"),
            authors=authors,
            year=data.get("year"),
            doi=external_ids.get("DOI"),
            arxiv_id=external_ids.get("ArXiv"),
            venue=data.get("venue"),
            citation_count=data.get("citationCount", 0),
            reference_count=data.get("referenceCount", 0),
            is_open_access=data.get("isOpenAccess", False),
            oa_url=oa_pdf.get("url") if oa_pdf else None,
            source_api="semantic_scholar"
        )
