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
"""

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
