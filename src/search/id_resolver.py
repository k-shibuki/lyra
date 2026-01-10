"""
ID resolver for converting between different paper identifier formats.

Converts PMID, arXiv ID to DOI using Semantic Scholar API.
Per ADR-0008: S2 + OpenAlex two-pillar strategy.
"""

from typing import Any, cast

import httpx

from src.utils.api_retry import get_academic_api_policy, retry_api_call
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

        # Notify rate limiter to downgrade to anonymous profile
        # This affects rate limits for the remainder of this process lifetime
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()
        limiter.downgrade_profile("semantic_scholar")

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

        try:
            from src.utils.agent_debug import agent_debug_run_id, agent_debug_session_id, agent_log

            agent_log(
                sessionId=agent_debug_session_id(),
                runId=agent_debug_run_id(),
                hypothesisId="H-PMID-02",
                location="src/search/id_resolver.py:resolve_pmid_to_doi:entry",
                message="Resolve PMID -> DOI (start)",
                data={
                    "pmid": pmid,
                    "base_url": self.base_url,
                    "has_api_key": bool(self.api_key),
                },
            )
        except Exception:
            pass

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

                data = await retry_api_call(_fetch, policy=get_academic_api_policy())
                external_ids = data.get("externalIds", {})
                doi = external_ids.get("DOI")

                if doi:
                    logger.debug("Resolved PMID to DOI", pmid=pmid, doi=doi)

                    try:
                        from src.utils.agent_debug import (
                            agent_debug_run_id,
                            agent_debug_session_id,
                            agent_log,
                        )

                        agent_log(
                            sessionId=agent_debug_session_id(),
                            runId=agent_debug_run_id(),
                            hypothesisId="H-PMID-02",
                            location="src/search/id_resolver.py:resolve_pmid_to_doi:success",
                            message="Resolved PMID -> DOI",
                            data={"pmid": pmid, "doi": str(doi)[:120]},
                        )
                    except Exception:
                        pass

                    return cast(str, doi)

                logger.debug("No DOI found for PMID", pmid=pmid)

                try:
                    from src.utils.agent_debug import (
                        agent_debug_run_id,
                        agent_debug_session_id,
                        agent_log,
                    )

                    agent_log(
                        sessionId=agent_debug_session_id(),
                        runId=agent_debug_run_id(),
                        hypothesisId="H-PMID-02",
                        location="src/search/id_resolver.py:resolve_pmid_to_doi:no_doi",
                        message="No DOI found for PMID",
                        data={"pmid": pmid},
                    )
                except Exception:
                    pass

                return None

            except Exception as e:
                # Check for invalid API key (401/403) - fallback to anonymous access
                if self._is_invalid_api_key_error(e) and attempt == 0 and self.api_key:
                    await self._handle_invalid_api_key()
                    continue  # Retry without API key

                logger.warning("Failed to resolve PMID to DOI", pmid=pmid, error=str(e))

                try:
                    from src.utils.agent_debug import (
                        agent_debug_run_id,
                        agent_debug_session_id,
                        agent_log,
                    )

                    agent_log(
                        sessionId=agent_debug_session_id(),
                        runId=agent_debug_run_id(),
                        hypothesisId="H-PMID-02",
                        location="src/search/id_resolver.py:resolve_pmid_to_doi:exception",
                        message="Exception while resolving PMID -> DOI",
                        data={"pmid": pmid, "error_type": type(e).__name__, "error": str(e)[:300]},
                    )
                except Exception:
                    pass

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

                data = await retry_api_call(_fetch, policy=get_academic_api_policy())
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

    async def resolve_pmcid(self, pmcid: str) -> dict[str, Any] | None:
        """Resolve PMCID to PMID/DOI via NCBI PMC idconv API.

        This is used for PMC URLs (pmc.ncbi.nlm.nih.gov/articles/PMCxxxxxxx/),
        where PMCID must be converted to PMID and/or DOI for downstream academic APIs.

        Returns:
            {"pmid": "...", "doi": "...", "pmcid": "PMC..."} or None
        """
        pmcid = (pmcid or "").strip()
        if not pmcid:
            return None

        try:
            from src.utils.agent_debug import agent_debug_run_id, agent_debug_session_id, agent_log

            agent_log(
                sessionId=agent_debug_session_id(),
                runId=agent_debug_run_id(),
                hypothesisId="H-PMID-12",
                location="src/search/id_resolver.py:resolve_pmcid:entry",
                message="Resolve PMCID -> PMID/DOI (start)",
                data={"pmcid": pmcid},
            )
        except Exception:
            pass

        # Load NCBI config from academic_apis.yaml
        ncbi_base_url = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1"
        ncbi_api_key: str | None = None
        email: str | None = None

        try:
            from src.utils.config import get_academic_apis_config

            apis = get_academic_apis_config()
            try:
                ncbi_config = apis.get_api_config("ncbi")
                ncbi_base_url = ncbi_config.base_url
                ncbi_api_key = ncbi_config.api_key
                email = ncbi_config.email
            except Exception:
                pass
            # Fallback: use OpenAlex/S2 email if NCBI email not configured
            if not email:
                try:
                    email = (
                        apis.get_api_config("openalex").email
                        or apis.get_api_config("semantic_scholar").email
                    )
                except Exception:
                    pass
        except Exception:
            pass

        url = f"{ncbi_base_url}/articles/"

        params: dict[str, Any] = {"ids": pmcid, "format": "json", "tool": "lyra"}
        if email:
            params["email"] = str(email)
        if ncbi_api_key:
            params["api_key"] = ncbi_api_key

        # Apply rate limiting for NCBI API
        from src.search.apis.rate_limiter import get_academic_rate_limiter

        limiter = get_academic_rate_limiter()
        await limiter.acquire("ncbi")

        try:

            async def _fetch() -> dict[str, Any]:
                session = await self._get_session()
                resp = await session.get(url, params=params)
                resp.raise_for_status()
                return cast(dict[str, Any], resp.json())

            data = await retry_api_call(_fetch, policy=get_academic_api_policy())
            limiter.report_success("ncbi")
            records = data.get("records") or []
            if not isinstance(records, list) or not records:
                return None
            rec = records[0] if isinstance(records[0], dict) else None
            if not rec:
                return None

            resolved = {
                "pmcid": str(rec.get("pmcid") or pmcid),
                "pmid": str(rec.get("pmid")) if rec.get("pmid") is not None else None,
                "doi": str(rec.get("doi")) if rec.get("doi") else None,
            }

            try:
                from src.utils.agent_debug import (
                    agent_debug_run_id,
                    agent_debug_session_id,
                    agent_log,
                )

                agent_log(
                    sessionId=agent_debug_session_id(),
                    runId=agent_debug_run_id(),
                    hypothesisId="H-PMID-12",
                    location="src/search/id_resolver.py:resolve_pmcid:success",
                    message="Resolved PMCID -> PMID/DOI",
                    data=resolved,
                )
            except Exception:
                pass

            return resolved
        except Exception as e:
            try:
                from src.utils.agent_debug import (
                    agent_debug_run_id,
                    agent_debug_session_id,
                    agent_log,
                )

                agent_log(
                    sessionId=agent_debug_session_id(),
                    runId=agent_debug_run_id(),
                    hypothesisId="H-PMID-12",
                    location="src/search/id_resolver.py:resolve_pmcid:exception",
                    message="Exception while resolving PMCID -> PMID/DOI",
                    data={"pmcid": pmcid, "error_type": type(e).__name__, "error": str(e)[:300]},
                )
            except Exception:
                pass

            return None
        finally:
            limiter.release("ncbi")

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
