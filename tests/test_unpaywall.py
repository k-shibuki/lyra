"""
Tests for Unpaywall API client and integration.

Tests OA URL resolution functionality.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-UP-N-01 | Valid DOI with OA available (PDF URL) | Equivalence – normal | OA URL (PDF) returned | - |
| TC-UP-N-02 | Valid DOI with OA available (landing page only) | Equivalence – normal | OA URL (landing page) returned | - |
| TC-UP-N-03 | Paper with existing OA URL | Equivalence – normal | Existing OA URL returned, Unpaywall not called | - |
| TC-UP-N-04 | DOI with https://doi.org/ prefix | Equivalence – normal | DOI normalized, OA URL returned | - |
| TC-UP-B-01 | Empty DOI string "" | Boundary – empty | None returned | - |
| TC-UP-B-02 | None DOI | Boundary – NULL | None returned | - |
| TC-UP-B-03 | DOI with only whitespace | Boundary – empty | None returned | - |
| TC-UP-B-04 | Very long DOI (>200 chars) | Boundary – maximum | OA URL returned or API error | - |
| TC-UP-A-01 | DOI not found (404) | Abnormal – API error | None returned, exception handled | - |
| TC-UP-A-02 | Rate limit exceeded (429) | Abnormal – API error | None returned, retry policy applied | - |
| TC-UP-A-03 | Server error (500) | Abnormal – API error | None returned, exception handled | - |
| TC-UP-A-04 | Network timeout | Abnormal – timeout | None returned, retry policy applied | - |
| TC-UP-A-05 | Invalid JSON response | Abnormal – invalid response | None returned, exception handled | - |
| TC-UP-A-06 | Paper not OA (is_oa=False) | Abnormal – no OA | None returned | - |
| TC-UP-A-07 | Paper OA but no location URLs | Abnormal – missing data | None returned | - |
| TC-UP-A-08 | Paper without DOI | Abnormal – missing input | None returned, Unpaywall not called | - |
| TC-UP-I-01 | resolve_oa_url_for_paper with existing OA URL | Integration | Existing URL returned | - |
| TC-UP-I-02 | resolve_oa_url_for_paper with DOI, OA resolved | Integration | Resolved OA URL returned | - |
| TC-UP-I-03 | resolve_oa_url_for_paper API failure | Integration | None returned, no exception | - |
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional

from src.search.apis.unpaywall import UnpaywallClient
from src.search.academic_provider import AcademicSearchProvider
from src.utils.schemas import Paper, Author


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_paper_with_doi():
    """Paper with DOI but no OA URL."""
    return Paper(
        id="test:123",
        title="Test Paper",
        abstract="Test abstract",
        authors=[Author(name="John Doe")],
        year=2024,
        doi="10.1234/test",
        oa_url=None,
        is_open_access=False,
        source_api="semantic_scholar",
    )


@pytest.fixture
def sample_paper_without_doi():
    """Paper without DOI."""
    return Paper(
        id="test:456",
        title="Test Paper 2",
        abstract="Test abstract 2",
        authors=[Author(name="Jane Doe")],
        year=2024,
        doi=None,
        oa_url=None,
        is_open_access=False,
        source_api="semantic_scholar",
    )


@pytest.fixture
def sample_paper_with_oa_url():
    """Paper with existing OA URL."""
    return Paper(
        id="test:789",
        title="Test Paper 3",
        abstract="Test abstract 3",
        authors=[Author(name="Bob Smith")],
        year=2024,
        doi="10.1234/test3",
        oa_url="https://example.com/paper.pdf",
        is_open_access=True,
        source_api="semantic_scholar",
    )


# =============================================================================
# Tests
# =============================================================================


class TestUnpaywallClient:
    """Test Unpaywall API client."""
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_success_pdf(self):
        """TC-UP-N-01: Valid DOI with OA available (PDF URL)."""
        # Given: Unpaywall client and valid DOI with OA PDF
        client = UnpaywallClient()
        mock_response = {
            "is_oa": True,
            "best_oa_location": {
                "url_for_pdf": "https://example.com/paper.pdf",
                "url_for_landing_page": "https://example.com/paper"
            }
        }
        
        # When: Resolving OA URL
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_session.get = AsyncMock(return_value=mock_response_obj)
            mock_get_session.return_value = mock_session
            
            oa_url = await client.resolve_oa_url("10.1234/test")
        
        # Then: PDF URL should be returned (preferred over landing page)
        assert oa_url == "https://example.com/paper.pdf"
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_success_landing_page(self):
        """TC-UP-N-02: Valid DOI with OA available (landing page only)."""
        # Given: Unpaywall client and valid DOI with OA landing page only
        client = UnpaywallClient()
        mock_response = {
            "is_oa": True,
            "best_oa_location": {
                "url_for_landing_page": "https://example.com/paper"
            }
        }
        
        # When: Resolving OA URL
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_session.get = AsyncMock(return_value=mock_response_obj)
            mock_get_session.return_value = mock_session
            
            oa_url = await client.resolve_oa_url("10.1234/test")
        
        # Then: Landing page URL should be returned
        assert oa_url == "https://example.com/paper"
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_not_oa(self):
        """TC-UP-A-06: Paper not OA (is_oa=False)."""
        # Given: Unpaywall client and DOI for non-OA paper
        client = UnpaywallClient()
        mock_response = {"is_oa": False}
        
        # When: Resolving OA URL
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_session.get = AsyncMock(return_value=mock_response_obj)
            mock_get_session.return_value = mock_session
            
            oa_url = await client.resolve_oa_url("10.1234/test")
        
        # Then: None should be returned
        assert oa_url is None
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_no_doi_empty_string(self):
        """TC-UP-B-01: Empty DOI string."""
        # Given: Unpaywall client and empty DOI string
        client = UnpaywallClient()
        
        # When: Resolving OA URL with empty string
        oa_url = await client.resolve_oa_url("")
        
        # Then: None should be returned
        assert oa_url is None
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_no_doi_none(self):
        """TC-UP-B-02: None DOI."""
        # Given: Unpaywall client and None DOI
        client = UnpaywallClient()
        
        # When: Resolving OA URL with None
        oa_url = await client.resolve_oa_url(None)
        
        # Then: None should be returned
        assert oa_url is None
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_normalize_doi(self):
        """TC-UP-N-04: DOI with https://doi.org/ prefix."""
        # Given: Unpaywall client and DOI with https://doi.org/ prefix
        client = UnpaywallClient()
        mock_response = {
            "is_oa": True,
            "best_oa_location": {
                "url_for_pdf": "https://example.com/paper.pdf"
            }
        }
        
        # When: Resolving OA URL with prefixed DOI
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_session.get = AsyncMock(return_value=mock_response_obj)
            mock_get_session.return_value = mock_session
            
            oa_url = await client.resolve_oa_url("https://doi.org/10.1234/test")
        
        # Then: DOI should be normalized and OA URL returned
        assert oa_url == "https://example.com/paper.pdf"
        # Verify DOI was normalized (without prefix) in API call
        call_args = mock_session.get.call_args
        assert "10.1234/test" in str(call_args)
        assert "https://doi.org" not in str(call_args)
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_api_error_404(self):
        """TC-UP-A-01: DOI not found (404)."""
        # Given: Unpaywall client and DOI that returns 404
        client = UnpaywallClient()
        
        # When: Resolving OA URL and API returns 404
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.raise_for_status.side_effect = Exception("404 Not Found")
            mock_session.get = AsyncMock(return_value=mock_response_obj)
            mock_get_session.return_value = mock_session
            
            oa_url = await client.resolve_oa_url("10.1234/nonexistent")
        
        # Then: None should be returned, exception handled gracefully
        assert oa_url is None
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_no_location_urls(self):
        """TC-UP-A-07: Paper OA but no location URLs."""
        # Given: Unpaywall client and OA paper but no location URLs
        client = UnpaywallClient()
        mock_response = {
            "is_oa": True,
            "best_oa_location": {},
            "oa_locations": []
        }
        
        # When: Resolving OA URL
        with patch.object(client, "_get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_session.get = AsyncMock(return_value=mock_response_obj)
            mock_get_session.return_value = mock_session
            
            oa_url = await client.resolve_oa_url("10.1234/test")
        
        # Then: None should be returned
        assert oa_url is None
    
    @pytest.mark.asyncio
    async def test_search_not_supported(self):
        """Test that search is not supported (Unpaywall spec)."""
        # Given: Unpaywall client
        client = UnpaywallClient()
        
        # When: Calling search (not supported by Unpaywall API)
        result = await client.search("test query")
        
        # Then: Should return empty result (spec: Unpaywall does not support search)
        assert result.papers == []
        assert result.total_count == 0
        assert result.source_api == "unpaywall"
    
    @pytest.mark.asyncio
    async def test_get_paper_not_supported(self):
        """Test that get_paper is not supported (Unpaywall spec)."""
        # Given: Unpaywall client
        client = UnpaywallClient()
        
        # When: Calling get_paper (not supported by Unpaywall API)
        paper = await client.get_paper("test_id")
        
        # Then: Should return None (spec: Unpaywall does not support get_paper)
        assert paper is None


class TestAcademicSearchProviderIntegration:
    """Test Unpaywall integration in AcademicSearchProvider."""
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_for_paper_with_existing_oa_url(self, sample_paper_with_oa_url):
        """TC-UP-N-03: Paper with existing OA URL."""
        # Given: Paper with existing OA URL
        provider = AcademicSearchProvider()
        
        # When: Resolving OA URL
        oa_url = await provider.resolve_oa_url_for_paper(sample_paper_with_oa_url)
        
        # Then: Existing OA URL should be returned (Unpaywall not called)
        assert oa_url == "https://example.com/paper.pdf"
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_for_paper_without_doi(self, sample_paper_without_doi):
        """TC-UP-A-08: Paper without DOI."""
        # Given: Paper without DOI
        provider = AcademicSearchProvider()
        
        # When: Resolving OA URL
        oa_url = await provider.resolve_oa_url_for_paper(sample_paper_without_doi)
        
        # Then: None should be returned (Unpaywall requires DOI)
        assert oa_url is None
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_for_paper_success(self, sample_paper_with_doi):
        """TC-UP-I-02: resolve_oa_url_for_paper with DOI, OA resolved."""
        # Given: Paper with DOI but no OA URL
        provider = AcademicSearchProvider()
        
        # When: Resolving OA URL via Unpaywall
        with patch.object(provider, "_is_unpaywall_enabled", return_value=True), \
             patch.object(provider, "_get_client") as mock_get_client:
            mock_unpaywall_client = AsyncMock(spec=UnpaywallClient)
            mock_unpaywall_client.resolve_oa_url = AsyncMock(return_value="https://example.com/resolved.pdf")
            mock_get_client.return_value = mock_unpaywall_client
            
            oa_url = await provider.resolve_oa_url_for_paper(sample_paper_with_doi)
        
        # Then: Resolved OA URL should be returned
        assert oa_url == "https://example.com/resolved.pdf"
        mock_unpaywall_client.resolve_oa_url.assert_called_once_with("10.1234/test")
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_for_paper_api_failure(self, sample_paper_with_doi):
        """TC-UP-I-03: resolve_oa_url_for_paper API failure."""
        # Given: Paper with DOI and Unpaywall API failure
        provider = AcademicSearchProvider()
        
        # When: Resolving OA URL and API returns None
        with patch.object(provider, "_is_unpaywall_enabled", return_value=True), \
             patch.object(provider, "_get_client") as mock_get_client:
            mock_unpaywall_client = AsyncMock(spec=UnpaywallClient)
            mock_unpaywall_client.resolve_oa_url = AsyncMock(return_value=None)
            mock_get_client.return_value = mock_unpaywall_client
            
            oa_url = await provider.resolve_oa_url_for_paper(sample_paper_with_doi)
        
        # Then: None should be returned, no exception raised
        assert oa_url is None
    
    @pytest.mark.asyncio
    async def test_resolve_oa_url_for_paper_exception_handling(self, sample_paper_with_doi):
        """Test exception handling during OA URL resolution."""
        # Given: Paper with DOI and client initialization failure
        provider = AcademicSearchProvider()
        
        # When: Resolving OA URL and exception occurs
        with patch.object(provider, "_is_unpaywall_enabled", return_value=True), \
             patch.object(provider, "_get_client") as mock_get_client:
            mock_get_client.side_effect = Exception("Client initialization failed")
            
            # Then: Should not raise exception, return None
            oa_url = await provider.resolve_oa_url_for_paper(sample_paper_with_doi)
            assert oa_url is None
