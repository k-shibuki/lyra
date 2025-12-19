"""
OpenAlex API client.

Large-scale search API (priority=2).
"""

from __future__ import annotations

from src.search.apis.base import BaseAcademicClient
from src.utils.api_retry import ACADEMIC_API_POLICY, retry_api_call
from src.utils.logging import get_logger
from src.utils.schemas import AcademicSearchResult, Author, Paper

logger = get_logger(__name__)


class OpenAlexClient(BaseAcademicClient):
    """OpenAlex API client."""

    def __init__(self):
        """Initialize OpenAlex client."""
        # Load config
        try:
            from src.utils.config import get_academic_apis_config
            config = get_academic_apis_config()
            api_config = config.apis.get("openalex", {})
            base_url = api_config.base_url if api_config.base_url else "https://api.openalex.org"
            timeout = float(api_config.timeout_seconds) if api_config.timeout_seconds else 30.0
            headers = api_config.headers if api_config.headers else None
        except Exception:
            # Fallback to defaults if config loading fails
            base_url = "https://api.openalex.org"
            timeout = 30.0
            headers = None

        super().__init__("openalex", base_url=base_url, timeout=timeout, headers=headers)

    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Search for papers."""
        session = await self._get_session()

        async def _search():
            response = await session.get(
                f"{self.base_url}/works",
                params={
                    "search": query,
                    "per-page": limit,
                    "select": "id,title,abstract_inverted_index,publication_year,authorships,doi,cited_by_count,referenced_works_count,open_access,primary_location"
                }
            )
            response.raise_for_status()
            return response.json()

        try:
            data = await retry_api_call(_search, policy=ACADEMIC_API_POLICY)
            papers = [self._parse_paper(w) for w in data.get("results", [])]

            return AcademicSearchResult(
                papers=papers,
                total_count=data.get("meta", {}).get("count", 0),
                source_api="openalex"
            )
        except Exception as e:
            logger.error("OpenAlex search failed", query=query, error=str(e))
            return AcademicSearchResult(
                papers=[],
                total_count=0,
                source_api="openalex"
            )

    async def get_paper(self, paper_id: str) -> Paper | None:
        """Get paper metadata."""
        session = await self._get_session()

        async def _fetch():
            # paper_id is "W123456789" format or "https://openalex.org/W123456789"
            pid = paper_id
            if pid.startswith("https://"):
                pid = pid.split("/")[-1]
            response = await session.get(
                f"{self.base_url}/works/{pid}",
                params={"select": "id,title,abstract_inverted_index,publication_year,authorships,doi,cited_by_count,referenced_works_count,open_access,primary_location"}
            )
            response.raise_for_status()
            return response.json()

        try:
            data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
            return self._parse_paper(data)
        except Exception as e:
            logger.warning("Failed to get paper", paper_id=paper_id, error=str(e))
            return None

    async def get_references(self, paper_id: str) -> list[tuple[Paper, bool]]:
        """Get references (OpenAlex does not support detailed references)."""
        # OpenAlex API does not have a references endpoint
        # Detailed references retrieval is delegated to Semantic Scholar
        logger.debug("OpenAlex does not support detailed references", paper_id=paper_id)
        return []

    async def get_citations(self, paper_id: str) -> list[tuple[Paper, bool]]:
        """Get citations (OpenAlex does not support detailed citations)."""
        # OpenAlex API does not have a citations endpoint
        # Detailed citations retrieval is delegated to Semantic Scholar
        logger.debug("OpenAlex does not support detailed citations", paper_id=paper_id)
        return []

    def _parse_paper(self, data: dict) -> Paper:
        """Convert API response to Paper model."""
        abstract = self._reconstruct_abstract(data.get("abstract_inverted_index"))
        oa = data.get("open_access", {}) or {}
        location = data.get("primary_location", {}) or {}

        authors = []
        for authorship in data.get("authorships", []):
            author_data = authorship.get("author", {})
            authors.append(Author(
                name=author_data.get("display_name", ""),
                affiliation=None,  # OpenAlex does not provide detailed affiliation
                orcid=author_data.get("orcid")
            ))

        doi = data.get("doi", "")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")

        return Paper(
            id=f"openalex:{data['id'].split('/')[-1]}",
            title=data.get("title", ""),
            abstract=abstract,
            authors=authors,
            year=data.get("publication_year"),
            doi=doi if doi else None,
            venue=location.get("source", {}).get("display_name") if location.get("source") else None,
            citation_count=data.get("cited_by_count", 0),
            reference_count=data.get("referenced_works_count", 0),
            is_open_access=oa.get("is_oa", False),
            oa_url=oa.get("oa_url"),
            source_api="openalex"
        )

    def _reconstruct_abstract(self, inverted_index: dict | None) -> str | None:
        """Reconstruct plain text from OpenAlex inverted index format.
        
        Args:
            inverted_index: {"word": [position1, position2, ...]} format dict
            
        Returns:
            Reconstructed abstract text or None
        """
        if not inverted_index:
            return None

        words = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                words[pos] = word

        if not words:
            return None

        # Sort by position and join
        sorted_positions = sorted(words.keys())
        return " ".join(words[pos] for pos in sorted_positions)
