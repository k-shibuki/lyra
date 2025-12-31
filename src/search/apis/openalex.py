"""
OpenAlex API client.

Large-scale search API (priority=2).
"""

import asyncio
import time
from typing import Any, cast

import httpx

from src.search.apis.base import BaseAcademicClient
from src.utils.api_retry import ACADEMIC_API_POLICY, retry_api_call
from src.utils.logging import get_logger
from src.utils.schemas import AcademicSearchResult, Author, Paper

logger = get_logger(__name__)

# H-C: Negative cache for 404 responses (TTL-based)
_404_cache: dict[str, float] = {}  # paper_id -> timestamp
_404_CACHE_TTL = 3600  # 1 hour


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
            data = await retry_api_call(
                _search, policy=ACADEMIC_API_POLICY, rate_limiter_provider=self.name
            )
            papers = [self._parse_paper(w) for w in data.get("results", [])]

            return AcademicSearchResult(
                papers=papers,
                total_count=(data.get("meta") or {}).get("count", 0),
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
        # H-B: Skip S2 paper IDs - OpenAlex cannot resolve Semantic Scholar IDs
        if paper_id.strip().startswith("s2:"):
            logger.debug("Skipping S2 paper ID (not queryable on OpenAlex)", paper_id=paper_id)
            return None

        # H-C: Check negative cache for known 404s
        if paper_id in _404_cache:
            cache_time = _404_cache[paper_id]
            if time.time() - cache_time < _404_CACHE_TTL:
                logger.debug("Skipping paper (cached 404)", paper_id=paper_id)
                return None
            else:
                # Cache expired, remove entry
                del _404_cache[paper_id]

        # Apply rate limiting (fix for hypothesis B)
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()
        await limiter.acquire(self.name)

        try:
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
                data = await retry_api_call(
                    _fetch, policy=ACADEMIC_API_POLICY, rate_limiter_provider=self.name
                )
                return self._parse_paper(data)
            except Exception as e:
                # H-C: Cache 404 responses to avoid repeated lookups
                is_404 = isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404
                if is_404:
                    _404_cache[paper_id] = time.time()
                    logger.debug("Cached 404 for paper", paper_id=paper_id)

                logger.warning("Failed to get paper", paper_id=paper_id, error=str(e))
                return None
        finally:
            limiter.release(self.name)

    async def get_references(self, paper_id: str) -> list[Paper]:
        """Get references via referenced_works field."""
        pid = self._normalize_work_id(paper_id)

        paper = await self.get_paper(pid)
        if paper is None:
            return []

        # Apply rate limiting for the referenced_works fetch
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()
        await limiter.acquire(self.name)

        try:
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
                data = await retry_api_call(
                    _fetch, policy=ACADEMIC_API_POLICY, rate_limiter_provider=self.name
                )
            except Exception as e:
                logger.debug(
                    "OpenAlex referenced_works fetch failed", paper_id=paper_id, error=str(e)
                )
                return []
        finally:
            limiter.release(self.name)

        refs = data.get("referenced_works") or []
        if not isinstance(refs, list):
            return []

        # Limit fan-out for performance
        refs = refs[:20]

        async def _get_one(ref: Any) -> Paper | None:
            if not isinstance(ref, str):
                return None
            try:
                return await self.get_paper(ref)  # Rate limited internally
            except Exception:
                return None

        papers = await asyncio.gather(*[_get_one(r) for r in refs], return_exceptions=False)
        return [p for p in papers if p and p.abstract]

    async def get_citations(self, paper_id: str) -> list[Paper]:
        """Get citing papers via filter=cites:{work_id}.

        Note: The cites filter requires an OpenAlex work ID (Wxxx).
        If a DOI URL is provided, we first resolve it to a work ID.
        """
        # DOI URL needs to be resolved to work ID first
        # because filter=cites:xxx requires OpenAlex work ID (Wxxx), not DOI
        if paper_id.startswith("https://doi.org/") or paper_id.startswith("doi:"):
            # Resolve DOI to work ID by fetching the paper first
            paper = await self.get_paper(paper_id)
            if paper is None:
                logger.debug("Cannot get citations: DOI not found in OpenAlex", paper_id=paper_id)
                return []
            # Extract work ID from paper.id (format: "openalex:Wxxx")
            paper_id = paper.id

        # Apply rate limiting
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()
        await limiter.acquire(self.name)

        try:
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
                data = await retry_api_call(
                    _search, policy=ACADEMIC_API_POLICY, rate_limiter_provider=self.name
                )
                papers = [self._parse_paper(w) for w in data.get("results", [])]
                return [p for p in papers if p and p.abstract]
            except Exception as e:
                logger.debug("OpenAlex citations fetch failed", paper_id=paper_id, error=str(e))
                return []
        finally:
            limiter.release(self.name)

    def _normalize_work_id(self, paper_id: str) -> str:
        """Normalize OpenAlex work identifiers for API usage.

        OpenAlex accepts:
        - Work ID: W1234567890
        - Full URL: https://openalex.org/W1234567890
        - DOI URL: https://doi.org/10.1234/xxx (kept as-is, OpenAlex resolves it)
        """
        pid = paper_id.strip()
        if pid.startswith("openalex:"):
            pid = pid.split("openalex:", 1)[1]
        # DOI URL should be kept as-is (OpenAlex can resolve it)
        elif pid.startswith("https://doi.org/"):
            pass  # Keep DOI URL as-is
        elif pid.startswith("https://openalex.org/"):
            pid = pid.split("/")[-1]  # Extract work ID
        return pid

    def _parse_paper(self, data: dict) -> Paper:
        """Convert API response to Paper model."""
        abstract = self._reconstruct_abstract(data.get("abstract_inverted_index"))
        oa = data.get("open_access", {}) or {}
        location = data.get("primary_location", {}) or {}

        authors = []
        for authorship in data.get("authorships", []):
            author_data = authorship.get("author") or {}
            # display_name can be null; use raw_author_name as fallback
            display_name = author_data.get("display_name")
            raw_author_name = authorship.get("raw_author_name")
            author_name = display_name or raw_author_name or ""
            authors.append(
                Author(
                    name=author_name,
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
            venue=(
                (location.get("source") or {}).get("display_name")
                if location.get("source")
                else None
            ),
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
