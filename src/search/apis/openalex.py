"""
OpenAlex API client.

Large-scale search API (priority=2).
"""

import asyncio
from typing import Any, cast

from src.search.apis.base import BaseAcademicClient
from src.utils.api_retry import ACADEMIC_API_POLICY, retry_api_call
from src.utils.logging import get_logger
from src.utils.schemas import AcademicSearchResult, Author, Paper

logger = get_logger(__name__)


class OpenAlexClient(BaseAcademicClient):
    """OpenAlex API client."""

    def __init__(self) -> None:
        """Initialize OpenAlex client."""
        # Load config
        try:
            from src.utils.config import get_academic_apis_config

            config = get_academic_apis_config()
            api_config = config.get_api_config("openalex")
            base_url = api_config.base_url
            timeout = float(api_config.timeout_seconds)
            headers = api_config.headers
        except Exception:
            # Fallback to defaults if config loading fails
            base_url = "https://api.openalex.org"
            timeout = 30.0
            headers = None

        super().__init__("openalex", base_url=base_url, timeout=timeout, headers=headers)

    async def _search_impl(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Search for papers (internal implementation).

        Rate limiting is handled by the base class search() method.
        """
        session = await self._get_session()

        async def _search() -> dict[str, Any]:
            response = await session.get(
                f"{self.base_url}/works",
                params={
                    "search": query,
                    "per-page": limit,
                    "select": "id,title,abstract_inverted_index,publication_year,authorships,doi,cited_by_count,referenced_works_count,open_access,primary_location",
                },
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

        try:
            data = await retry_api_call(_search, policy=ACADEMIC_API_POLICY)
            papers = [self._parse_paper(w) for w in data.get("results", [])]

            return AcademicSearchResult(
                papers=papers,
                total_count=data.get("meta", {}).get("count", 0),
                next_cursor=None,  # OpenAlex uses meta.next_cursor
                source_api="openalex",
            )
        except Exception as e:
            logger.error("OpenAlex search failed", query=query, error=str(e))
            return AcademicSearchResult(
                papers=[], total_count=0, next_cursor=None, source_api="openalex"
            )

    async def get_paper(self, paper_id: str) -> Paper | None:
        """Get paper metadata."""
        session = await self._get_session()

        pid = self._normalize_work_id(paper_id)

        async def _fetch() -> dict[str, Any]:
            response = await session.get(
                f"{self.base_url}/works/{pid}",
                params={
                    "select": "id,title,abstract_inverted_index,publication_year,authorships,doi,cited_by_count,referenced_works_count,referenced_works,open_access,primary_location"
                },
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

        try:
            data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
            return self._parse_paper(data)
        except Exception as e:
            logger.warning("Failed to get paper", paper_id=paper_id, error=str(e))
            return None

    async def get_references(self, paper_id: str) -> list[Paper]:
        """Get references via referenced_works field."""
        pid = self._normalize_work_id(paper_id)

        paper = await self.get_paper(pid)
        if paper is None:
            return []

        # Fetch full work JSON to obtain referenced_works list (IDs/URLs)
        session = await self._get_session()

        async def _fetch() -> dict[str, Any]:
            response = await session.get(
                f"{self.base_url}/works/{pid}",
                params={"select": "id,referenced_works"},
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

        try:
            data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
        except Exception as e:
            logger.debug("OpenAlex referenced_works fetch failed", paper_id=paper_id, error=str(e))
            return []

        refs = data.get("referenced_works") or []
        if not isinstance(refs, list):
            return []

        # Limit fan-out for performance
        refs = refs[:20]

        async def _get_one(ref: Any) -> Paper | None:
            if not isinstance(ref, str):
                return None
            try:
                return await self.get_paper(ref)
            except Exception:
                return None

        papers = await asyncio.gather(*[_get_one(r) for r in refs], return_exceptions=False)
        return [p for p in papers if p and p.abstract]

    async def get_citations(self, paper_id: str) -> list[Paper]:
        """Get citing papers via filter=cites:{work_id}."""
        pid = self._normalize_work_id(paper_id)
        session = await self._get_session()

        async def _search() -> dict[str, Any]:
            response = await session.get(
                f"{self.base_url}/works",
                params={
                    "filter": f"cites:{pid}",
                    "per-page": 20,
                    "select": "id,title,abstract_inverted_index,publication_year,authorships,doi,cited_by_count,referenced_works_count,open_access,primary_location",
                },
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

        try:
            data = await retry_api_call(_search, policy=ACADEMIC_API_POLICY)
            papers = [self._parse_paper(w) for w in data.get("results", [])]
            return [p for p in papers if p and p.abstract]
        except Exception as e:
            logger.debug("OpenAlex citations fetch failed", paper_id=paper_id, error=str(e))
            return []

    def _normalize_work_id(self, paper_id: str) -> str:
        """Normalize OpenAlex work identifiers for API usage."""
        pid = paper_id.strip()
        if pid.startswith("openalex:"):
            pid = pid.split("openalex:", 1)[1]
        if pid.startswith("https://"):
            pid = pid.split("/")[-1]
        return pid

    def _parse_paper(self, data: dict) -> Paper:
        """Convert API response to Paper model."""
        abstract = self._reconstruct_abstract(data.get("abstract_inverted_index"))
        oa = data.get("open_access", {}) or {}
        location = data.get("primary_location", {}) or {}

        authors = []
        for authorship in data.get("authorships", []):
            author_data = authorship.get("author", {})
            authors.append(
                Author(
                    name=author_data.get("display_name", ""),
                    affiliation=None,  # OpenAlex does not provide detailed affiliation
                    orcid=author_data.get("orcid"),
                )
            )

        doi = data.get("doi", "")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")

        return Paper(
            id=f"openalex:{data['id'].split('/')[-1]}",
            title=data.get("title", ""),
            abstract=abstract,
            authors=authors,
            year=data.get("publication_year"),
            published_date=None,  # OpenAlex does not provide date
            doi=doi if doi else None,
            arxiv_id=None,  # OpenAlex does not provide arXiv ID
            venue=location.get("source", {}).get("display_name")
            if location.get("source")
            else None,
            citation_count=data.get("cited_by_count", 0),
            reference_count=data.get("referenced_works_count", 0),
            is_open_access=oa.get("is_oa", False),
            oa_url=oa.get("oa_url"),
            pdf_url=oa.get("oa_url"),  # Same as OA URL
            source_api="openalex",
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
