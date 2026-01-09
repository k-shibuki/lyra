"""
Tests for ID resolver (PMID/arXiv ID to DOI conversion).

Tests identifier resolution functionality using Semantic Scholar API.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-ID-N-01 | Valid PMID (exists in S2) | Equivalence – normal | DOI returned | - |
| TC-ID-N-02 | Valid PMID (no DOI in S2) | Equivalence – normal | None returned | - |
| TC-ID-B-01 | Empty PMID string "" | Boundary – empty | None returned | - |
| TC-ID-B-02 | None PMID | Boundary – NULL | None returned (handled gracefully) | Runtime handles gracefully, returns None |
| TC-ID-A-01 | S2 API 404 error | Abnormal – API error | None returned, exception handled | - |
| TC-ID-A-02 | S2 API timeout | Abnormal – timeout | None returned, retry policy applied | - |
| TC-ID-A-03 | Invalid JSON response | Abnormal – invalid response | None returned, exception handled | - |
| TC-ID-A-04 | Network error | Abnormal – network | None returned, exception handled | - |
| TC-ID-ARX-01 | Valid arXiv ID (exists in S2) | Equivalence – normal | DOI returned | - |
| TC-ID-ARX-02 | Valid arXiv ID (no DOI in S2) | Equivalence – normal | None returned | - |
| TC-ID-ARX-A-01 | S2 API 404 for arXiv | Abnormal – API error | None returned | - |
| TC-ID-KEY-01 | API key 401 error | Abnormal – invalid key | Fallback to anonymous, retry | - |
| TC-ID-KEY-02 | API key 403 error | Abnormal – forbidden | Fallback to anonymous, retry | - |
| TC-ID-RES-01 | resolve_to_doi with DOI | Normal – pass-through | DOI returned directly | - |
| TC-ID-RES-02 | resolve_to_doi with PMID | Normal – delegate | PMID resolved | - |
| TC-ID-RES-03 | resolve_to_doi with arXiv | Normal – delegate | arXiv resolved | - |
| TC-ID-RES-04 | resolve_to_doi with nothing | Boundary – empty | None returned | - |
| TC-ID-PMC-01 | Valid PMCID (idconv returns pmid+doi) | Equivalence – normal | dict returned with pmid/doi | - |
| TC-ID-PMC-B-01 | Empty PMCID string "" | Boundary – empty | None returned | - |
| TC-ID-PMC-A-01 | idconv API error | Abnormal – API error | None returned | - |
| TC-ID-CL-01 | close() method | Resource cleanup | Session closed | - |
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.search.id_resolver import IDResolver

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def id_resolver() -> IDResolver:
    """Create IDResolver instance."""
    return IDResolver()


# =============================================================================
# Tests
# =============================================================================


class TestResolvePMIDToDOI:
    """Test resolve_pmid_to_doi() method."""

    @pytest.mark.asyncio
    async def test_resolve_pmid_to_doi_success(self, id_resolver: IDResolver) -> None:
        """TC-ID-N-01: Valid PMID (exists in S2) returns DOI."""
        # Given: Valid PMID that exists in Semantic Scholar
        pmid = "12345678"
        mock_response = {
            "externalIds": {
                "DOI": "10.1234/test.doi",
                "ArXiv": None,
                "PubMed": "12345678",
            }
        }

        # When: Resolving PMID to DOI
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.json = MagicMock(return_value=mock_response)
        mock_response_obj.raise_for_status = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_pmid_to_doi(pmid)

        # Then: DOI should be returned
        assert doi == "10.1234/test.doi"
        mock_session.get.assert_called_once()
        call_args = mock_session.get.call_args
        assert "PMID:12345678" in str(call_args)

    @pytest.mark.asyncio
    async def test_resolve_pmid_to_doi_no_doi_in_s2(self, id_resolver: IDResolver) -> None:
        """TC-ID-N-02: Valid PMID (no DOI in S2) returns None."""
        # Given: Valid PMID that exists in S2 but has no DOI
        pmid = "12345678"
        mock_response = {
            "externalIds": {
                "ArXiv": None,
                "PubMed": "12345678",
            }
        }

        # When: Resolving PMID to DOI
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.json = MagicMock(return_value=mock_response)
        mock_response_obj.raise_for_status = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_pmid_to_doi(pmid)

        # Then: None should be returned
        assert doi is None

    @pytest.mark.asyncio
    async def test_resolve_pmid_to_doi_empty_string(self, id_resolver: IDResolver) -> None:
        """TC-ID-B-01: Empty PMID string returns None."""
        # Given: Empty PMID string
        pmid = ""

        # When: Resolving empty PMID to DOI
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.json = MagicMock(return_value={})
        mock_response_obj.raise_for_status = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_pmid_to_doi(pmid)

        # Then: None should be returned (API call made but no DOI found)
        assert doi is None

    @pytest.mark.asyncio
    async def test_resolve_pmid_to_doi_none_returns_none(self, id_resolver: IDResolver) -> None:
        """TC-ID-B-02: None PMID returns None (handled gracefully)."""
        # Given: None as PMID (type error at type checking, but runtime handles gracefully)
        pmid: str | None = None

        # When: Resolving None PMID to DOI (with mock to avoid actual API call)
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "400 Bad Request", request=MagicMock(), response=MagicMock()
            )
        )

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_pmid_to_doi(pmid)  # type: ignore[arg-type]

        # Then: None should be returned (exception handled gracefully)
        assert doi is None

    @pytest.mark.asyncio
    async def test_resolve_pmid_to_doi_api_404(self, id_resolver: IDResolver) -> None:
        """TC-ID-A-01: S2 API 404 error handled gracefully."""
        # Given: PMID that returns 404 from S2 API
        pmid = "99999999"

        # When: Resolving PMID to DOI and API returns 404
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=MagicMock()
            )
        )
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_pmid_to_doi(pmid)

        # Then: None should be returned, exception handled gracefully
        assert doi is None

    @pytest.mark.asyncio
    async def test_resolve_pmid_to_doi_api_timeout(self, id_resolver: IDResolver) -> None:
        """TC-ID-A-02: S2 API timeout handled gracefully."""
        # Given: S2 API timeout
        pmid = "12345678"

        # When: Resolving PMID to DOI and API times out
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_pmid_to_doi(pmid)

        # Then: None should be returned, exception handled gracefully
        assert doi is None

    @pytest.mark.asyncio
    async def test_resolve_pmid_to_doi_invalid_json(self, id_resolver: IDResolver) -> None:
        """TC-ID-A-03: Invalid JSON response handled gracefully."""
        # Given: S2 API returns invalid JSON
        pmid = "12345678"

        # When: Resolving PMID to DOI and API returns invalid JSON
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.json = MagicMock(side_effect=ValueError("Invalid JSON"))
        mock_response_obj.raise_for_status = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_pmid_to_doi(pmid)

        # Then: None should be returned, exception handled gracefully
        assert doi is None

    @pytest.mark.asyncio
    async def test_resolve_pmid_to_doi_network_error(self, id_resolver: IDResolver) -> None:
        """TC-ID-A-04: Network error handled gracefully."""
        # Given: Network error
        pmid = "12345678"

        # When: Resolving PMID to DOI and network error occurs
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(side_effect=httpx.NetworkError("Network error"))

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_pmid_to_doi(pmid)

        # Then: None should be returned, exception handled gracefully
        assert doi is None


class TestResolveArxivToDOI:
    """Test resolve_arxiv_to_doi() method."""

    @pytest.mark.asyncio
    async def test_resolve_arxiv_to_doi_success(self, id_resolver: IDResolver) -> None:
        """TC-ID-ARX-01: Valid arXiv ID (exists in S2) returns DOI."""
        # Given: Valid arXiv ID that exists in Semantic Scholar
        arxiv_id = "2301.12345"
        mock_response = {
            "externalIds": {
                "DOI": "10.1234/arxiv.doi",
                "ArXiv": "2301.12345",
            }
        }

        # When: Resolving arXiv ID to DOI
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.json = MagicMock(return_value=mock_response)
        mock_response_obj.raise_for_status = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_arxiv_to_doi(arxiv_id)

        # Then: DOI should be returned
        assert doi == "10.1234/arxiv.doi"
        mock_session.get.assert_called_once()
        call_args = mock_session.get.call_args
        assert "arXiv:2301.12345" in str(call_args)

    @pytest.mark.asyncio
    async def test_resolve_arxiv_to_doi_no_doi_in_s2(self, id_resolver: IDResolver) -> None:
        """TC-ID-ARX-02: Valid arXiv ID (no DOI in S2) returns None."""
        # Given: Valid arXiv ID that exists in S2 but has no DOI
        arxiv_id = "2301.99999"
        mock_response = {
            "externalIds": {
                "ArXiv": "2301.99999",
            }
        }

        # When: Resolving arXiv ID to DOI
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.json = MagicMock(return_value=mock_response)
        mock_response_obj.raise_for_status = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_arxiv_to_doi(arxiv_id)

        # Then: None should be returned
        assert doi is None


class TestResolvePMCID:
    """Test resolve_pmcid() method (NCBI idconv)."""

    @pytest.mark.asyncio
    async def test_resolve_pmcid_success(self, id_resolver: IDResolver) -> None:
        """TC-ID-PMC-01: Valid PMCID returns PMID/DOI dict.

        // Given: PMCID and idconv API returns record
        // When: Calling resolve_pmcid()
        // Then: pmid/doi are returned
        """
        # Given: PMCID
        pmcid = "PMC5768864"
        mock_response = {
            "status": "ok",
            "records": [{"doi": "10.1038/s41598-017-19055-6", "pmcid": pmcid, "pmid": 29335646}],
        }

        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.json = MagicMock(return_value=mock_response)
        mock_response_obj.raise_for_status = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            resolved = await id_resolver.resolve_pmcid(pmcid)

        # Then
        assert resolved is not None
        assert resolved["pmcid"] == pmcid
        assert resolved["pmid"] == "29335646"
        assert resolved["doi"] == "10.1038/s41598-017-19055-6"

    @pytest.mark.asyncio
    async def test_resolve_pmcid_empty(self, id_resolver: IDResolver) -> None:
        """TC-ID-PMC-B-01: Empty PMCID returns None.

        // Given: Empty PMCID
        // When: Calling resolve_pmcid()
        // Then: None returned
        """
        # Given
        pmcid = ""

        # When
        resolved = await id_resolver.resolve_pmcid(pmcid)

        # Then
        assert resolved is None

    @pytest.mark.asyncio
    async def test_resolve_pmcid_api_error(self, id_resolver: IDResolver) -> None:
        """TC-ID-PMC-A-01: API error returns None.

        // Given: idconv API raises HTTPStatusError
        // When: Calling resolve_pmcid()
        // Then: None returned
        """
        # Given
        pmcid = "PMC99999999"
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "500 Server Error", request=MagicMock(), response=MagicMock()
            )
        )
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            resolved = await id_resolver.resolve_pmcid(pmcid)

        # Then
        assert resolved is None

    @pytest.mark.asyncio
    async def test_resolve_arxiv_to_doi_api_404(self, id_resolver: IDResolver) -> None:
        """TC-ID-ARX-A-01: S2 API 404 for arXiv ID handled gracefully."""
        # Given: arXiv ID that returns 404 from S2 API
        arxiv_id = "9999.99999"

        # When: Resolving arXiv ID to DOI and API returns 404
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=MagicMock()
            )
        )
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_arxiv_to_doi(arxiv_id)

        # Then: None should be returned, exception handled gracefully
        assert doi is None


class TestAPIKeyFallback:
    """Test API key fallback behavior."""

    @pytest.mark.asyncio
    async def test_api_key_401_fallback_to_anonymous(self) -> None:
        """TC-ID-KEY-01: 401 error triggers fallback to anonymous access."""
        # Given: IDResolver with API key configured
        resolver = IDResolver()
        resolver.api_key = "test_api_key"
        resolver._original_api_key = "test_api_key"

        mock_response_401 = MagicMock()
        mock_response_401.status_code = 401
        mock_response_401.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "401 Unauthorized",
                request=MagicMock(),
                response=mock_response_401,
            )
        )

        mock_response_success = MagicMock()
        mock_response_success.json = MagicMock(
            return_value={"externalIds": {"DOI": "10.1234/fallback"}}
        )
        mock_response_success.raise_for_status = MagicMock()

        # First call fails with 401, second call succeeds (anonymous)
        call_count = 0

        async def mock_get(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response_401
            return mock_response_success

        # When: Resolving PMID to DOI with API key error
        mock_session = AsyncMock()
        mock_session.get = mock_get
        mock_session.aclose = AsyncMock()

        with patch.object(resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await resolver.resolve_pmid_to_doi("12345678")

        # Then: Should fallback to anonymous and return DOI
        assert doi == "10.1234/fallback"
        assert resolver.api_key is None  # API key disabled

    @pytest.mark.asyncio
    async def test_api_key_403_fallback_to_anonymous(self) -> None:
        """TC-ID-KEY-02: 403 error triggers fallback to anonymous access."""
        # Given: IDResolver with API key configured
        resolver = IDResolver()
        resolver.api_key = "test_api_key"
        resolver._original_api_key = "test_api_key"

        mock_response_403 = MagicMock()
        mock_response_403.status_code = 403
        mock_response_403.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "403 Forbidden",
                request=MagicMock(),
                response=mock_response_403,
            )
        )

        mock_response_success = MagicMock()
        mock_response_success.json = MagicMock(
            return_value={"externalIds": {"DOI": "10.1234/forbidden"}}
        )
        mock_response_success.raise_for_status = MagicMock()

        call_count = 0

        async def mock_get(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response_403
            return mock_response_success

        # When: Resolving arXiv ID to DOI with API key error
        mock_session = AsyncMock()
        mock_session.get = mock_get
        mock_session.aclose = AsyncMock()

        with patch.object(resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await resolver.resolve_arxiv_to_doi("2301.12345")

        # Then: Should fallback to anonymous and return DOI
        assert doi == "10.1234/forbidden"
        assert resolver.api_key is None  # API key disabled

    def test_is_invalid_api_key_error_401(self) -> None:
        """TC-ID-KEY-01b: 401 status code is identified as invalid key."""
        # Given: IDResolver
        resolver = IDResolver()

        mock_response = MagicMock()
        mock_response.status_code = 401
        error = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=mock_response
        )

        # When/Then: Should identify as invalid API key
        assert resolver._is_invalid_api_key_error(error) is True

    def test_is_invalid_api_key_error_403(self) -> None:
        """TC-ID-KEY-02b: 403 status code is identified as invalid key."""
        # Given: IDResolver
        resolver = IDResolver()

        mock_response = MagicMock()
        mock_response.status_code = 403
        error = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=mock_response)

        # When/Then: Should identify as invalid API key
        assert resolver._is_invalid_api_key_error(error) is True

    def test_is_invalid_api_key_error_other_codes(self) -> None:
        """TC-ID-KEY-03b: Other status codes are not invalid key errors."""
        # Given: IDResolver
        resolver = IDResolver()

        for status_code in [400, 404, 429, 500, 502, 503]:
            mock_response = MagicMock()
            mock_response.status_code = status_code
            error = httpx.HTTPStatusError(
                f"{status_code} Error", request=MagicMock(), response=mock_response
            )

            # When/Then: Should not identify as invalid API key
            assert resolver._is_invalid_api_key_error(error) is False

    def test_is_invalid_api_key_error_non_http_error(self) -> None:
        """TC-ID-KEY-03c: Non-HTTP errors are not invalid key errors."""
        # Given: IDResolver
        resolver = IDResolver()

        # When/Then: Non-HTTP exceptions should return False
        assert resolver._is_invalid_api_key_error(ValueError("test")) is False
        assert resolver._is_invalid_api_key_error(httpx.TimeoutException("timeout")) is False


class TestResolveToDOI:
    """Test resolve_to_doi() method."""

    @pytest.mark.asyncio
    async def test_resolve_to_doi_with_existing_doi(self, id_resolver: IDResolver) -> None:
        """TC-ID-RES-01: PaperIdentifier with DOI returns it directly."""
        # Given: PaperIdentifier with DOI
        from src.utils.schemas import PaperIdentifier

        identifier = PaperIdentifier(
            doi="10.1234/existing.doi", pmid=None, pmcid=None, arxiv_id=None, url=None
        )

        # When: Resolving to DOI
        doi = await id_resolver.resolve_to_doi(identifier)

        # Then: Should return existing DOI directly
        assert doi == "10.1234/existing.doi"

    @pytest.mark.asyncio
    async def test_resolve_to_doi_with_pmid(self, id_resolver: IDResolver) -> None:
        """TC-ID-RES-02: PaperIdentifier with PMID resolves via PMID."""
        # Given: PaperIdentifier with PMID only
        from src.utils.schemas import PaperIdentifier

        identifier = PaperIdentifier(doi=None, pmid="12345678", pmcid=None, arxiv_id=None, url=None)

        mock_response = {"externalIds": {"DOI": "10.1234/from.pmid"}}

        # When: Resolving to DOI
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.json = MagicMock(return_value=mock_response)
        mock_response_obj.raise_for_status = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_to_doi(identifier)

        # Then: Should resolve via PMID
        assert doi == "10.1234/from.pmid"

    @pytest.mark.asyncio
    async def test_resolve_to_doi_with_arxiv(self, id_resolver: IDResolver) -> None:
        """TC-ID-RES-03: PaperIdentifier with arXiv ID resolves via arXiv."""
        # Given: PaperIdentifier with arXiv ID only
        from src.utils.schemas import PaperIdentifier

        identifier = PaperIdentifier(
            doi=None, pmid=None, pmcid=None, arxiv_id="2301.12345", url=None
        )

        mock_response = {"externalIds": {"DOI": "10.1234/from.arxiv"}}

        # When: Resolving to DOI
        mock_session = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.json = MagicMock(return_value=mock_response)
        mock_response_obj.raise_for_status = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_response_obj)

        with patch.object(id_resolver, "_get_session", AsyncMock(return_value=mock_session)):
            doi = await id_resolver.resolve_to_doi(identifier)

        # Then: Should resolve via arXiv
        assert doi == "10.1234/from.arxiv"

    @pytest.mark.asyncio
    async def test_resolve_to_doi_with_nothing(self, id_resolver: IDResolver) -> None:
        """TC-ID-RES-04: PaperIdentifier with no identifiers returns None."""
        # Given: PaperIdentifier with no identifiers
        from src.utils.schemas import PaperIdentifier

        identifier = PaperIdentifier(doi=None, pmid=None, pmcid=None, arxiv_id=None, url=None)

        # When: Resolving to DOI
        doi = await id_resolver.resolve_to_doi(identifier)

        # Then: Should return None
        assert doi is None

    @pytest.mark.asyncio
    async def test_resolve_to_doi_priority_order(self, id_resolver: IDResolver) -> None:
        """TC-ID-RES-01b: DOI takes priority over PMID and arXiv."""
        # Given: PaperIdentifier with all identifiers
        from src.utils.schemas import PaperIdentifier

        identifier = PaperIdentifier(
            doi="10.1234/direct.doi",
            pmid="12345678",
            pmcid=None,
            arxiv_id="2301.12345",
            url=None,
        )

        # When: Resolving to DOI
        doi = await id_resolver.resolve_to_doi(identifier)

        # Then: Should return DOI directly (no API call needed)
        assert doi == "10.1234/direct.doi"


class TestCloseSession:
    """Test close() method."""

    @pytest.mark.asyncio
    async def test_close_session(self) -> None:
        """TC-ID-CL-01: close() method closes the session."""
        # Given: IDResolver with active session
        resolver = IDResolver()
        mock_session = AsyncMock()
        mock_session.aclose = AsyncMock()
        resolver._session = mock_session

        # When: Closing resolver
        await resolver.close()

        # Then: Session should be closed
        mock_session.aclose.assert_called_once()
        assert resolver._session is None

    @pytest.mark.asyncio
    async def test_close_no_session(self) -> None:
        """TC-ID-CL-01b: close() with no session does nothing."""
        # Given: IDResolver with no session
        resolver = IDResolver()
        assert resolver._session is None

        # When: Closing resolver (should not raise)
        await resolver.close()

        # Then: No error, session still None
        assert resolver._session is None
