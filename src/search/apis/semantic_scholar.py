"""
Semantic Scholar API client.

Primary API for citation graphs (priority=1).
"""

from typing import Any, cast

import httpx

from src.search.apis.base import BaseAcademicClient
from src.utils.api_retry import (
    get_academic_api_policy,
    get_max_consecutive_429_for_provider,
    retry_api_call,
)
from src.utils.logging import get_logger
from src.utils.schemas import AcademicSearchResult, Author, Paper

logger = get_logger(__name__)


class SemanticScholarClient(BaseAcademicClient):
    """Semantic Scholar API client.

    Supports optional API key authentication via x-api-key header.
    Configure via LYRA_ACADEMIC_APIS__APIS__SEMANTIC_SCHOLAR__API_KEY in .env.

    If API key becomes invalid (expired after 60 days of non-use, revoked, etc.),
    the client automatically falls back to anonymous access (shared pool) with a warning.
    """

    FIELDS = "paperId,title,abstract,year,authors,citationCount,referenceCount,isOpenAccess,openAccessPdf,venue,externalIds"

    # HTTP status codes indicating invalid API key
    _INVALID_KEY_STATUS_CODES = {401, 403}

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

        # Track original API key for fallback logging
        self._original_api_key = self.api_key
        self._api_key_fallback_logged = False

        # Add x-api-key header if api_key is configured
        # This enables authenticated access with higher rate limits
        if self.api_key:
            self.default_headers["x-api-key"] = self.api_key
            logger.debug("Semantic Scholar API key configured")

    async def _handle_invalid_api_key(self) -> None:
        """Handle invalid API key by falling back to anonymous access.

        Logs a warning (once) and recreates the session without the API key.
        Also notifies the rate limiter to downgrade to anonymous profile.
        """
        if not self._api_key_fallback_logged and self._original_api_key:
            logger.warning(
                "Semantic Scholar API key is invalid (expired or revoked). "
                "Falling back to anonymous access (shared pool, 1000 req/s across all users). "
                "Re-apply for a new key at https://www.semanticscholar.org/product/api if needed.",
            )
            self._api_key_fallback_logged = True

        # Disable API key
        self.api_key = None
        self.default_headers.pop("x-api-key", None)

        # Notify rate limiter to downgrade to anonymous profile
        # This affects rate limits for the remainder of this process lifetime
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()
        limiter.downgrade_profile(self.name)

        # Recreate session without API key
        if self._session:
            await self._session.aclose()
            self._session = None

    def _is_invalid_api_key_error(self, e: Exception) -> bool:
        """Check if exception indicates an invalid API key."""
        import httpx

        if isinstance(e, httpx.HTTPStatusError):
            return e.response.status_code in self._INVALID_KEY_STATUS_CODES
        return False

    async def _search_impl(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Search for papers (internal implementation).

        Rate limiting is handled by the base class search() method.
        If API key is invalid (401/403), automatically falls back to anonymous access.
        """
        # Retry once if API key is invalid (fallback to anonymous)
        for attempt in range(2):
            session = await self._get_session()

            async def _search(s: httpx.AsyncClient = session) -> dict[str, Any]:
                response = await s.get(
                    f"{self.base_url}/paper/search",
                    params={"query": query, "limit": limit, "fields": self.FIELDS},
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())

            try:
                # Get profile-aware max_consecutive_429 for this provider
                max_429 = get_max_consecutive_429_for_provider(self.name)

                data = await retry_api_call(
                    _search,
                    policy=get_academic_api_policy(),
                    rate_limiter_provider=self.name,
                    max_consecutive_429=max_429,
                )
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
                # Check for invalid API key (401/403) - fallback to anonymous access
                if self._is_invalid_api_key_error(e) and attempt == 0 and self.api_key:
                    await self._handle_invalid_api_key()
                    continue  # Retry without API key

                # Log as warning (not error) for 429 early-fail (expected behavior for fallback)
                from src.utils.api_retry import APIRetryError

                if isinstance(e, APIRetryError) and e.last_status == 429:
                    logger.warning(
                        "Semantic Scholar rate limited, falling back to OpenAlex only",
                        query=query[:50],
                    )
                else:
                    logger.error("Semantic Scholar search failed", query=query, error=str(e))
                return AcademicSearchResult(
                    papers=[], total_count=0, next_cursor=None, source_api="semantic_scholar"
                )

        # Should not reach here
        return AcademicSearchResult(
            papers=[], total_count=0, next_cursor=None, source_api="semantic_scholar"
        )

    async def get_paper(self, paper_id: str) -> Paper | None:
        """Get paper metadata.

        If API key is invalid (401/403), automatically falls back to anonymous access.
        """
        # Apply rate limiting (fix for hypothesis B)
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()

        # Normalize paper ID for API (once, outside retry loop)
        normalized_id = self._normalize_paper_id(paper_id)

        # OpenAlex work IDs are not queryable on Semantic Scholar.
        # Short-circuit to avoid 404 noise and rate limiter waits.
        if (paper_id or "").strip().startswith("openalex:") or (paper_id or "").strip().startswith(
            "https://openalex.org/"
        ):
            logger.debug("Skipping OpenAlex work ID on Semantic Scholar", paper_id=paper_id[:200])
            return None

        try:
            from src.utils.agent_debug import agent_debug_run_id, agent_debug_session_id, agent_log

            agent_log(
                sessionId=agent_debug_session_id(),
                runId=agent_debug_run_id(),
                hypothesisId="H-PMID-03",
                location="src/search/apis/semantic_scholar.py:get_paper:entry",
                message="S2 get_paper (start)",
                data={
                    "paper_id": paper_id[:200],
                    "normalized_id": normalized_id[:200],
                    "has_api_key": bool(self.api_key),
                },
            )
        except Exception:
            pass

        # Retry once if API key is invalid (fallback to anonymous)
        for attempt in range(2):
            await limiter.acquire(self.name)

            try:
                session = await self._get_session()

                async def _fetch(s: httpx.AsyncClient = session) -> dict[str, Any]:
                    response = await s.get(
                        f"{self.base_url}/paper/{normalized_id}", params={"fields": self.FIELDS}
                    )
                    response.raise_for_status()
                    return cast(dict[str, Any], response.json())

                try:
                    data = await retry_api_call(
                        _fetch, policy=get_academic_api_policy(), rate_limiter_provider=self.name
                    )
                    paper = self._parse_paper(data)

                    try:
                        from src.utils.agent_debug import (
                            agent_debug_run_id,
                            agent_debug_session_id,
                            agent_log,
                        )

                        agent_log(
                            sessionId=agent_debug_session_id(),
                            runId=agent_debug_run_id(),
                            hypothesisId="H-PMID-03",
                            location="src/search/apis/semantic_scholar.py:get_paper:parsed",
                            message="S2 get_paper (parsed)",
                            data={
                                "paper_id": paper_id[:200],
                                "has_paper": bool(paper),
                                "has_abstract": bool(paper.abstract) if paper else False,
                                "year": getattr(paper, "year", None) if paper else None,
                                "authors_count": (
                                    len(paper.authors) if paper and paper.authors else 0
                                ),
                                "doi": (paper.doi or "")[:120] if paper else None,
                            },
                        )
                    except Exception:
                        pass

                    return paper
                except Exception as e:
                    # Check for invalid API key (401/403) - fallback to anonymous access
                    if self._is_invalid_api_key_error(e) and attempt == 0 and self.api_key:
                        await self._handle_invalid_api_key()
                        continue  # Retry without API key

                    logger.warning("Failed to get paper", paper_id=paper_id, error=str(e))

                    try:
                        from src.utils.agent_debug import (
                            agent_debug_run_id,
                            agent_debug_session_id,
                            agent_log,
                        )

                        agent_log(
                            sessionId=agent_debug_session_id(),
                            runId=agent_debug_run_id(),
                            hypothesisId="H-PMID-03",
                            location="src/search/apis/semantic_scholar.py:get_paper:exception",
                            message="S2 get_paper (exception)",
                            data={
                                "paper_id": paper_id[:200],
                                "error_type": type(e).__name__,
                                "error": str(e)[:300],
                            },
                        )
                    except Exception:
                        pass

                    return None
            finally:
                limiter.release(self.name)

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

    async def get_references(self, paper_id: str) -> list[Paper]:
        """Get references (papers cited by this paper).

        If API key is invalid (401/403), automatically falls back to anonymous access.
        """
        # Apply rate limiting
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()

        # Normalize paper ID for API (once, outside retry loop)
        normalized_id = self._normalize_paper_id(paper_id)

        # OpenAlex work IDs are not queryable on Semantic Scholar.
        if (paper_id or "").strip().startswith("openalex:") or (paper_id or "").strip().startswith(
            "https://openalex.org/"
        ):
            logger.debug(
                "Skipping OpenAlex work ID on Semantic Scholar (references)",
                paper_id=paper_id[:200],
            )
            return []

        # Retry once if API key is invalid (fallback to anonymous)
        for attempt in range(2):
            await limiter.acquire(self.name)

            try:
                session = await self._get_session()

                async def _fetch(s: httpx.AsyncClient = session) -> dict[str, Any]:
                    response = await s.get(
                        f"{self.base_url}/paper/{normalized_id}/references",
                        params={"fields": self.FIELDS},
                    )
                    response.raise_for_status()
                    return cast(dict[str, Any], response.json())

                try:
                    data = await retry_api_call(
                        _fetch, policy=get_academic_api_policy(), rate_limiter_provider=self.name
                    )
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
                    # Check for invalid API key (401/403) - fallback to anonymous access
                    if self._is_invalid_api_key_error(e) and attempt == 0 and self.api_key:
                        await self._handle_invalid_api_key()
                        continue  # Retry without API key

                    logger.warning("Failed to get references", paper_id=paper_id, error=str(e))
                    return []
            finally:
                limiter.release(self.name)

        return []

    async def get_citations(self, paper_id: str) -> list[Paper]:
        """Get citations (papers that cite this paper).

        If API key is invalid (401/403), automatically falls back to anonymous access.
        """
        # Apply rate limiting
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()

        # Normalize paper ID for API (once, outside retry loop)
        normalized_id = self._normalize_paper_id(paper_id)

        # OpenAlex work IDs are not queryable on Semantic Scholar.
        if (paper_id or "").strip().startswith("openalex:") or (paper_id or "").strip().startswith(
            "https://openalex.org/"
        ):
            logger.debug(
                "Skipping OpenAlex work ID on Semantic Scholar (citations)",
                paper_id=paper_id[:200],
            )
            return []

        # Retry once if API key is invalid (fallback to anonymous)
        for attempt in range(2):
            await limiter.acquire(self.name)

            try:
                session = await self._get_session()

                async def _fetch(s: httpx.AsyncClient = session) -> dict[str, Any]:
                    response = await s.get(
                        f"{self.base_url}/paper/{normalized_id}/citations",
                        params={"fields": self.FIELDS},
                    )
                    response.raise_for_status()
                    return cast(dict[str, Any], response.json())

                try:
                    data = await retry_api_call(
                        _fetch, policy=get_academic_api_policy(), rate_limiter_provider=self.name
                    )
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
                    # Check for invalid API key (401/403) - fallback to anonymous access
                    if self._is_invalid_api_key_error(e) and attempt == 0 and self.api_key:
                        await self._handle_invalid_api_key()
                        continue  # Retry without API key

                    logger.warning("Failed to get citations", paper_id=paper_id, error=str(e))
                    return []
            finally:
                limiter.release(self.name)

        return []

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
