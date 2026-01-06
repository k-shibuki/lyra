"""
ID resolver for converting between different paper identifier formats.

Converts PMID, arXiv ID to DOI using Semantic Scholar API.
Per ADR-0008: S2 + OpenAlex two-pillar strategy.
"""

from typing import Any, cast

import httpx

from src.utils.api_retry import ACADEMIC_API_POLICY, retry_api_call
from src.utils.logging import get_logger
from src.utils.schemas import PaperIdentifier

logger = get_logger(__name__)


class IDResolver:
    """Convert various paper IDs to DOI.

    Uses Semantic Scholar API for ID resolution.
    Supports API key authentication via LYRA_ACADEMIC_APIS__APIS__SEMANTIC_SCHOLAR__API_KEY.

    If API key becomes invalid (expired after 60 days of non-use, revoked, etc.),
    automatically falls back to anonymous access (shared pool) with a warning.
    """

    # HTTP status codes indicating invalid API key
    _INVALID_KEY_STATUS_CODES = {401, 403}

    def __init__(self) -> None:
        """Initialize ID resolver with Semantic Scholar config."""
        self._session: httpx.AsyncClient | None = None

        # Load Semantic Scholar config
        self.base_url = "https://api.semanticscholar.org/graph/v1"
        self.timeout = 30.0
        self.email: str | None = None
        self.api_key: str | None = None

        try:
            from src.utils.config import get_academic_apis_config

            config = get_academic_apis_config()
            api_config = config.get_api_config("semantic_scholar")
            self.base_url = api_config.base_url
            self.timeout = float(api_config.timeout_seconds)
            self.email = api_config.email
            self.api_key = api_config.api_key
        except Exception as e:
            logger.debug("Failed to load S2 config for IDResolver", error=str(e))

        # Track original API key for fallback logging
        self._original_api_key = self.api_key
        self._api_key_fallback_logged = False

    async def _get_session(self) -> httpx.AsyncClient:
        """Get HTTP session (lazy initialization)."""
        if self._session is None:
            # Build User-Agent with optional email identification
            if self.email:
                user_agent = f"Lyra/1.0 (research tool; mailto:{self.email})"
            else:
                user_agent = "Lyra/1.0 (research tool)"

            headers: dict[str, str] = {"User-Agent": user_agent}

            # Add x-api-key if configured
            if self.api_key:
                headers["x-api-key"] = self.api_key

            self._session = httpx.AsyncClient(
                timeout=self.timeout,
                headers=headers,
            )
        return self._session

    async def _handle_invalid_api_key(self) -> None:
        """Handle invalid API key by falling back to anonymous access.

        Logs a warning (once) and recreates the session without the API key.
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

        # Recreate session without API key
        if self._session:
            await self._session.aclose()
            self._session = None

    def _is_invalid_api_key_error(self, e: Exception) -> bool:
        """Check if exception indicates an invalid API key."""
        if isinstance(e, httpx.HTTPStatusError):
            return e.response.status_code in self._INVALID_KEY_STATUS_CODES
        return False

    async def resolve_pmid_to_doi(self, pmid: str) -> str | None:
        """Get DOI from PMID (via Semantic Scholar API).

        If API key is invalid (401/403), automatically falls back to anonymous access.

        Args:
            pmid: PubMed ID

        Returns:
            DOI string or None
        """
        # Retry once if API key is invalid (fallback to anonymous)
        for attempt in range(2):
            try:
                session = await self._get_session()

                async def _fetch(s: httpx.AsyncClient = session) -> dict[str, Any]:
                    response = await s.get(
                        f"{self.base_url}/paper/PMID:{pmid}",
                        params={"fields": "externalIds"},
                    )
                    response.raise_for_status()
                    return cast(dict[str, Any], response.json())

                data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
                external_ids = data.get("externalIds", {})
                doi = external_ids.get("DOI")

                if doi:
                    logger.debug("Resolved PMID to DOI", pmid=pmid, doi=doi)
                    return cast(str, doi)

                logger.debug("No DOI found for PMID", pmid=pmid)
                return None

            except Exception as e:
                # Check for invalid API key (401/403) - fallback to anonymous access
                if self._is_invalid_api_key_error(e) and attempt == 0 and self.api_key:
                    await self._handle_invalid_api_key()
                    continue  # Retry without API key

                logger.warning("Failed to resolve PMID to DOI", pmid=pmid, error=str(e))
                return None

        return None

    async def resolve_arxiv_to_doi(self, arxiv_id: str) -> str | None:
        """Get DOI from arXiv ID (via Semantic Scholar).

        If API key is invalid (401/403), automatically falls back to anonymous access.

        Args:
            arxiv_id: arXiv ID (e.g., "2301.12345")

        Returns:
            DOI string or None
        """
        # Retry once if API key is invalid (fallback to anonymous)
        for attempt in range(2):
            try:
                session = await self._get_session()

                async def _fetch(s: httpx.AsyncClient = session) -> dict[str, Any]:
                    response = await s.get(
                        f"{self.base_url}/paper/arXiv:{arxiv_id}",
                        params={"fields": "externalIds"},
                    )
                    response.raise_for_status()
                    return cast(dict[str, Any], response.json())

                data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
                external_ids = data.get("externalIds", {})
                doi = external_ids.get("DOI")

                if doi:
                    logger.debug("Resolved arXiv ID to DOI", arxiv_id=arxiv_id, doi=doi)
                    return cast(str, doi)

                logger.debug("No DOI found for arXiv ID", arxiv_id=arxiv_id)
                return None

            except Exception as e:
                # Check for invalid API key (401/403) - fallback to anonymous access
                if self._is_invalid_api_key_error(e) and attempt == 0 and self.api_key:
                    await self._handle_invalid_api_key()
                    continue  # Retry without API key

                logger.warning("Failed to resolve arXiv ID to DOI", arxiv_id=arxiv_id, error=str(e))
                return None

        return None

    async def resolve_to_doi(self, identifier: PaperIdentifier) -> str | None:
        """Resolve DOI from PaperIdentifier.

        Args:
            identifier: PaperIdentifier

        Returns:
            DOI string or None
        """
        # Return existing DOI if available
        if identifier.doi:
            return identifier.doi

        # Convert from PMID to DOI
        if identifier.pmid:
            return await self.resolve_pmid_to_doi(identifier.pmid)

        # Convert from arXiv ID to DOI
        if identifier.arxiv_id:
            return await self.resolve_arxiv_to_doi(identifier.arxiv_id)

        return None

    async def close(self) -> None:
        """Close the session."""
        if self._session:
            await self._session.aclose()
            self._session = None
