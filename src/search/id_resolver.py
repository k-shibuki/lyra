"""
ID resolver for converting between different paper identifier formats.

Converts PMID, arXiv ID, etc. to DOI using external APIs.
"""

from typing import Any, cast

import httpx

from src.utils.api_retry import ACADEMIC_API_POLICY, retry_api_call
from src.utils.logging import get_logger
from src.utils.schemas import PaperIdentifier

logger = get_logger(__name__)


class IDResolver:
    """Convert various paper IDs to DOI."""

    def __init__(self) -> None:
        """Initialize ID resolver."""
        self._session: httpx.AsyncClient | None = None

    async def _get_session(self) -> httpx.AsyncClient:
        """Get HTTP session (lazy initialization)."""
        if self._session is None:
            self._session = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Lyra/1.0 (research tool; mailto:lyra@example.com)"},
            )
        return self._session

    async def resolve_pmid_to_doi(self, pmid: str) -> str | None:
        """Get DOI from PMID (via Semantic Scholar API).

        Args:
            pmid: PubMed ID

        Returns:
            DOI string or None
        """
        try:
            session = await self._get_session()

            async def _fetch() -> dict[str, Any]:
                response = await session.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/PMID:{pmid}",
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
            logger.warning("Failed to resolve PMID to DOI", pmid=pmid, error=str(e))
            return None

    async def resolve_arxiv_to_doi(self, arxiv_id: str) -> str | None:
        """Get DOI from arXiv ID (via Semantic Scholar).

        Args:
            arxiv_id: arXiv ID (e.g., "2301.12345")

        Returns:
            DOI string or None
        """
        try:
            session = await self._get_session()

            async def _fetch() -> dict[str, Any]:
                response = await session.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}",
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
            logger.warning("Failed to resolve arXiv ID to DOI", arxiv_id=arxiv_id, error=str(e))
            return None

    async def resolve_crid_to_doi(self, crid: str) -> str | None:
        """Get DOI from CiNii CRID.

        Not implemented: Decision 6 defines S2 + OpenAlex as the two pillars.
        CiNii is out of scope.

        Args:
            crid: CiNii Research ID

        Returns:
            None (always)
        """
        logger.debug("CRID to DOI conversion not supported (Decision 6)", crid=crid)
        return None

    async def resolve_to_doi(self, identifier: "PaperIdentifier") -> str | None:
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

        # Convert from CRID to DOI (not implemented)
        if identifier.crid:
            return await self.resolve_crid_to_doi(identifier.crid)

        return None

    async def close(self) -> None:
        """Close the session."""
        if self._session:
            await self._session.aclose()
            self._session = None
