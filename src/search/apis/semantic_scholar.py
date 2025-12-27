"""
Semantic Scholar API client.

Primary API for citation graphs (priority=1).
"""

from typing import Any, cast

from src.search.apis.base import BaseAcademicClient
from src.utils.api_retry import ACADEMIC_API_POLICY, retry_api_call
from src.utils.logging import get_logger
from src.utils.schemas import AcademicSearchResult, Author, Paper

logger = get_logger(__name__)


class SemanticScholarClient(BaseAcademicClient):
    """Semantic Scholar API client."""

    FIELDS = "paperId,title,abstract,year,authors,citationCount,referenceCount,isOpenAccess,openAccessPdf,venue,externalIds"

    def __init__(self) -> None:
        """Initialize Semantic Scholar client."""
        # Load config
        try:
            from src.utils.config import get_academic_apis_config

            config = get_academic_apis_config()
            api_config = config.get_api_config("semantic_scholar")
            base_url = api_config.base_url
            timeout = float(api_config.timeout_seconds)
            headers = api_config.headers
        except Exception:
            # Fallback to defaults if config loading fails
            base_url = "https://api.semanticscholar.org/graph/v1"
            timeout = 30.0
            headers = None

        super().__init__("semantic_scholar", base_url=base_url, timeout=timeout, headers=headers)

    async def _search_impl(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Search for papers (internal implementation).

        Rate limiting is handled by the base class search() method.
        """
        session = await self._get_session()

        async def _search() -> dict[str, Any]:
            response = await session.get(
                f"{self.base_url}/paper/search",
                params={"query": query, "limit": limit, "fields": self.FIELDS},
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

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
                source_api="semantic_scholar",
            )
        except Exception as e:
            logger.error("Semantic Scholar search failed", query=query, error=str(e))
            return AcademicSearchResult(
                papers=[], total_count=0, next_cursor=None, source_api="semantic_scholar"
            )

    async def get_paper(self, paper_id: str) -> Paper | None:
        """Get paper metadata."""
        # Apply rate limiting (fix for hypothesis B)
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()
        await limiter.acquire(self.name)

        try:
            session = await self._get_session()

            # Normalize paper ID for API
            normalized_id = self._normalize_paper_id(paper_id)

            async def _fetch() -> dict[str, Any]:
                response = await session.get(
                    f"{self.base_url}/paper/{normalized_id}", params={"fields": self.FIELDS}
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())

            try:
                data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
                return self._parse_paper(data)
            except Exception as e:
                logger.warning("Failed to get paper", paper_id=paper_id, error=str(e))
                return None
        finally:
            limiter.release(self.name)

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

    async def get_references(self, paper_id: str) -> list[Paper]:
        """Get references (papers cited by this paper)."""
        # Apply rate limiting
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()
        await limiter.acquire(self.name)

        try:
            session = await self._get_session()

            # Normalize paper ID for API
            normalized_id = self._normalize_paper_id(paper_id)

            async def _fetch() -> dict[str, Any]:
                response = await session.get(
                    f"{self.base_url}/paper/{normalized_id}/references",
                    params={"fields": self.FIELDS},
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())

            try:
                data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
                results = []
                # Fix for DEBUG_E2E_02 H-C: handle None data or data["data"]
                refs_list = (data.get("data") if data else None) or []
                for ref in refs_list:
                    if ref is None:
                        continue
                    cited_paper = ref.get("citedPaper")
                    if cited_paper:
                        try:
                            paper = self._parse_paper(cited_paper)
                            results.append(paper)
                        except (ValueError, Exception) as parse_err:
                            # Skip malformed papers (e.g., paperId=None)
                            logger.debug("Skipping malformed reference", error=str(parse_err))
                            continue
                return results
            except Exception as e:
                logger.warning("Failed to get references", paper_id=paper_id, error=str(e))
                return []
        finally:
            limiter.release(self.name)

    async def get_citations(self, paper_id: str) -> list[Paper]:
        """Get citations (papers that cite this paper)."""
        # Apply rate limiting
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()
        await limiter.acquire(self.name)

        try:
            session = await self._get_session()

            # Normalize paper ID for API
            normalized_id = self._normalize_paper_id(paper_id)

            async def _fetch() -> dict[str, Any]:
                response = await session.get(
                    f"{self.base_url}/paper/{normalized_id}/citations",
                    params={"fields": self.FIELDS},
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())

            try:
                data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
                results = []
                # Fix for DEBUG_E2E_02 H-C: handle None data or data["data"]
                cits_list = (data.get("data") if data else None) or []
                for cit in cits_list:
                    # Fix for hypothesis F: skip None entries
                    if cit is None:
                        continue
                    citing_paper = cit.get("citingPaper")
                    if citing_paper:
                        try:
                            paper = self._parse_paper(citing_paper)
                            results.append(paper)
                        except (ValueError, Exception) as parse_err:
                            # Skip malformed papers (e.g., paperId=None)
                            logger.debug("Skipping malformed citation", error=str(parse_err))
                            continue
                return results
            except Exception as e:
                logger.warning("Failed to get citations", paper_id=paper_id, error=str(e))
                return []
        finally:
            limiter.release(self.name)

    def _parse_paper(self, data: dict) -> Paper:
        """Convert API response to Paper model."""
        # Handle None values (dict.get returns None if key exists but value is None)
        external_ids = data.get("externalIds") or {}
        oa_pdf = data.get("openAccessPdf") or {}

        authors = []
        for author_data in data.get("authors", []):
            authors.append(
                Author(
                    name=author_data.get("name", ""),
                    affiliation=None,  # Semantic Scholar API does not provide affiliation
                    orcid=None,
                )
            )

        # Use 'or default' pattern for fields that may have None values
        # data.get("key", default) returns None if key exists but value is None
        paper_id = data.get("paperId")
        if not paper_id:
            # Skip papers without paperId (malformed entries from API)
            raise ValueError(f"Paper has no paperId: {data.get('title', 'Unknown')[:50]}")

        return Paper(
            id=f"s2:{paper_id}",
            title=data.get("title") or "",
            abstract=data.get("abstract"),
            authors=authors,
            year=data.get("year"),
            published_date=None,  # Semantic Scholar does not provide date
            doi=external_ids.get("DOI"),
            arxiv_id=external_ids.get("ArXiv"),
            venue=data.get("venue"),
            citation_count=data.get("citationCount") or 0,
            reference_count=data.get("referenceCount") or 0,
            is_open_access=data.get("isOpenAccess") or False,
            oa_url=oa_pdf.get("url") if oa_pdf else None,
            pdf_url=oa_pdf.get("url") if oa_pdf else None,  # Same as OA URL
            source_api="semantic_scholar",
        )
