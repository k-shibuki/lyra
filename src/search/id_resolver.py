"""
ID resolver for converting between different paper identifier formats.

Converts PMID, arXiv ID, etc. to DOI using external APIs.
"""

import httpx
from typing import Optional

from src.utils.logging import get_logger
from src.utils.api_retry import retry_api_call, ACADEMIC_API_POLICY

logger = get_logger(__name__)


class IDResolver:
    """Convert various paper IDs to DOI."""

    def __init__(self):
        """Initialize ID resolver."""
        self._session: Optional[httpx.AsyncClient] = None

    async def _get_session(self) -> httpx.AsyncClient:
        """Get HTTP session (lazy initialization)."""
        if self._session is None:
            self._session = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Lancet/1.0 (research tool; mailto:lancet@example.com)"}
            )
        return self._session

    async def resolve_pmid_to_doi(self, pmid: str) -> Optional[str]:
        """Get DOI from PMID (via Crossref API).

        Args:
            pmid: PubMed ID

        Returns:
            DOI string or None
        """
        try:
            session = await self._get_session()

            async def _fetch():
                response = await session.get(
                    "https://api.crossref.org/works",
                    params={"filter": f"pmid:{pmid}", "rows": 1}
                )
                response.raise_for_status()
                return response.json()

            data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
            items = data.get("message", {}).get("items", [])

            if items and "DOI" in items[0]:
                doi = items[0]["DOI"]
                logger.debug("Resolved PMID to DOI", pmid=pmid, doi=doi)
                return doi

            logger.debug("No DOI found for PMID", pmid=pmid)
            return None

        except Exception as e:
            logger.warning("Failed to resolve PMID to DOI", pmid=pmid, error=str(e))
            return None

    async def resolve_arxiv_to_doi(self, arxiv_id: str) -> Optional[str]:
        """Get DOI from arXiv ID (via Semantic Scholar).

        Args:
            arxiv_id: arXiv ID (e.g., "2301.12345")

        Returns:
            DOI string or None
        """
        try:
            session = await self._get_session()

            async def _fetch():
                response = await session.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}",
                    params={"fields": "externalIds"}
                )
                response.raise_for_status()
                return response.json()

            data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
            external_ids = data.get("externalIds", {})
            doi = external_ids.get("DOI")

            if doi:
                logger.debug("Resolved arXiv ID to DOI", arxiv_id=arxiv_id, doi=doi)
                return doi

            logger.debug("No DOI found for arXiv ID", arxiv_id=arxiv_id)
            return None

        except Exception as e:
            logger.warning("Failed to resolve arXiv ID to DOI", arxiv_id=arxiv_id, error=str(e))
            return None

    async def resolve_crid_to_doi(self, crid: str) -> Optional[str]:
        """Get DOI from CiNii CRID (via CiNii API).

        Note: CiNii API may not return DOI directly, future extension planned.

        Args:
            crid: CiNii Research ID

        Returns:
            DOI string or None
        """
        # TODO: Implement CiNii API (not supported yet)
        logger.debug("CRID to DOI conversion not yet implemented", crid=crid)
        return None

    async def resolve_to_doi(self, identifier: "PaperIdentifier") -> Optional[str]:
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
