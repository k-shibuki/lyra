"""
Unpaywall API client.

Open Access URL resolution (priority=5).
"""

import os

from src.search.apis.base import BaseAcademicClient
from src.utils.api_retry import ACADEMIC_API_POLICY, retry_api_call
from src.utils.logging import get_logger
from src.utils.schemas import AcademicSearchResult, Paper

logger = get_logger(__name__)


class UnpaywallClient(BaseAcademicClient):
    """Unpaywall API client for OA URL resolution."""

    def __init__(self):
        """Initialize Unpaywall client."""
        # Load config
        try:
            from src.utils.config import get_academic_apis_config
            config = get_academic_apis_config()
            api_config = config.apis.get("unpaywall", {})
            base_url = api_config.base_url if api_config.base_url else "https://api.unpaywall.org/v2"
            timeout = float(api_config.timeout_seconds) if api_config.timeout_seconds else 30.0
            headers = api_config.headers if api_config.headers else None

            # Email is required for Unpaywall API
            self.email = api_config.email if api_config.email else None
            if not self.email:
                # Try environment variable
                self.email = os.environ.get("LANCET_ACADEMIC_APIS__APIS__UNPAYWALL__EMAIL", "lancet@example.com")
        except Exception as e:
            logger.warning("Failed to load Unpaywall config", error=str(e))
            # Fallback to defaults if config loading fails
            base_url = "https://api.unpaywall.org/v2"
            timeout = 30.0
            headers = None
            self.email = os.environ.get("LANCET_ACADEMIC_APIS__APIS__UNPAYWALL__EMAIL", "lancet@example.com")

        super().__init__("unpaywall", base_url=base_url, timeout=timeout, headers=headers)

    async def resolve_oa_url(self, doi: str) -> str | None:
        """Resolve Open Access URL from DOI.
        
        Args:
            doi: DOI string (with or without https://doi.org/ prefix)
            
        Returns:
            OA URL if available, None otherwise
        """
        if not doi:
            return None

        # Normalize DOI (remove https://doi.org/ prefix if present)
        normalized_doi = doi.replace("https://doi.org/", "").strip()
        if not normalized_doi:
            return None

        session = await self._get_session()

        async def _fetch():
            response = await session.get(
                f"{self.base_url}/{normalized_doi}",
                params={"email": self.email}
            )
            response.raise_for_status()
            return response.json()

        try:
            data = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)

            # Check if OA is available
            is_oa = data.get("is_oa", False)
            if not is_oa:
                return None

            # Get best OA URL (prefer PDF, fallback to landing page)
            best_oa_location = data.get("best_oa_location")
            if best_oa_location:
                oa_url = best_oa_location.get("url_for_pdf") or best_oa_location.get("url_for_landing_page")
                if oa_url:
                    return oa_url

            # Fallback: check all OA locations
            oa_locations = data.get("oa_locations", [])
            for location in oa_locations:
                url = location.get("url_for_pdf") or location.get("url_for_landing_page")
                if url:
                    return url

            return None
        except Exception as e:
            logger.debug("Failed to resolve OA URL from Unpaywall", doi=doi, error=str(e))
            return None

    # Unpaywall API does not support search, references, or citations
    # These methods are required by BaseAcademicClient but return empty results

    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Search is not supported by Unpaywall API."""
        logger.debug("Unpaywall does not support search", query=query)
        return AcademicSearchResult(
            papers=[],
            total_count=0,
            source_api="unpaywall"
        )

    async def get_paper(self, paper_id: str) -> Paper | None:
        """Get paper is not supported by Unpaywall API.
        
        Use resolve_oa_url() instead for DOI-based OA URL resolution.
        """
        logger.debug("Unpaywall does not support get_paper", paper_id=paper_id)
        return None

    async def get_references(self, paper_id: str) -> list[tuple[Paper, bool]]:
        """References are not supported by Unpaywall API."""
        logger.debug("Unpaywall does not support references", paper_id=paper_id)
        return []

    async def get_citations(self, paper_id: str) -> list[tuple[Paper, bool]]:
        """Citations are not supported by Unpaywall API."""
        logger.debug("Unpaywall does not support citations", paper_id=paper_id)
        return []
