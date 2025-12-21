"""
Tests for AcademicSearchProvider citation graph integration.

Tests S2/OpenAlex integration and API return type consistency.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|--------------------------------------|-----------------|-------|
| TC-CG-N-01 | S2 + OpenAlex both return papers | Equivalence – normal | Both papers integrated, citations created | - |
| TC-CG-N-02 | Same DOI from both APIs | Equivalence – normal | Deduplicated to single paper | - |
| TC-CG-N-03 | direction="references" only | Equivalence – normal | Only references fetched | - |
| TC-CG-N-04 | direction="citations" only | Equivalence – normal | Only citations fetched | - |
| TC-CG-N-05 | depth=2 (multi-level) | Equivalence – normal | Papers at depth 2 included | - |
| TC-CG-B-01 | depth=0 | Boundary – zero | Empty results (no exploration) | - |
| TC-CG-B-02 | Empty results from both APIs | Boundary – empty | Empty papers and citations lists | - |
| TC-CG-B-03 | One API returns empty list | Boundary – empty | Results from other API returned | - |
| TC-CG-A-01 | S2 API fails (exception) | Abnormal – exception | OpenAlex results still returned | - |
| TC-CG-A-02 | OpenAlex API fails (exception) | Abnormal – exception | S2 results still returned | - |
| TC-CG-A-03 | Both APIs fail | Abnormal – exception | Empty results, no exception raised | - |
| TC-CG-A-04 | asyncio.gather raises exception | Abnormal – exception | Handled gracefully, empty results | - |
| TC-API-N-01 | OpenAlex get_references() | Equivalence – normal | Returns list[Paper] | - |
| TC-API-N-02 | OpenAlex get_citations() | Equivalence – normal | Returns list[Paper] | - |
| TC-API-N-03 | arXiv get_references() | Equivalence – normal | Returns list[Paper] (empty) | - |
| TC-API-N-04 | Crossref get_references() | Equivalence – normal | Returns list[Paper] (empty) | - |
| TC-API-B-01 | OpenAlex get_references() with no abstract | Boundary – empty | Empty list (abstract required) | - |
| TC-API-B-02 | OpenAlex get_citations() with no abstract | Boundary – empty | Empty list (abstract required) | - |
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.search.academic_provider import AcademicSearchProvider
from src.utils.schemas import Author, Paper


@pytest.fixture
def sample_paper_s2() -> Paper:
    """Sample paper from Semantic Scholar."""
    return Paper(
        id="s2:test123",
        title="Test Paper S2",
        abstract="Abstract from S2",
        authors=[Author(name="John Doe", affiliation=None, orcid=None)],
        year=2024,
        published_date=None,
        doi="10.1234/test.s2",
        arxiv_id=None,
        venue="Nature",
        citation_count=10,
        reference_count=5,
        is_open_access=True,
        oa_url=None,
        pdf_url=None,
        source_api="semantic_scholar",
    )


@pytest.fixture
def sample_paper_openalex() -> Paper:
    """Sample paper from OpenAlex."""
    return Paper(
        id="openalex:W123456789",
        title="Test Paper OpenAlex",
        abstract="Abstract from OpenAlex",
        authors=[Author(name="Jane Smith", affiliation=None, orcid=None)],
        year=2024,
        published_date=None,
        doi="10.1234/test.oa",
        arxiv_id=None,
        venue="Science",
        citation_count=20,
        reference_count=8,
        is_open_access=True,
        oa_url=None,
        pdf_url=None,
        source_api="openalex",
    )


@pytest.fixture
def sample_reference_paper() -> Paper:
    """Sample reference paper (same DOI, different API)."""
    return Paper(
        id="openalex:W987654321",
        title="Reference Paper",
        abstract="Reference abstract",
        authors=[Author(name="Alice Brown", affiliation=None, orcid=None)],
        year=2023,
        published_date=None,
        doi="10.1234/reference",
        arxiv_id=None,
        venue="PLOS ONE",
        citation_count=5,
        reference_count=3,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="openalex",
    )


class TestCitationGraphIntegration:
    """Tests for S2/OpenAlex citation graph integration."""

    @pytest.mark.asyncio
    async def test_get_citation_graph_integrates_s2_and_openalex(
        self, sample_paper_s2: Paper, sample_paper_openalex: Paper
    ) -> None:
        """
        Test: get_citation_graph() fetches from both S2 and OpenAlex.

        Given: Paper ID that exists in both APIs
        When: get_citation_graph() is called
        Then: Results from both APIs are integrated
        """
        # Given
        provider = AcademicSearchProvider()

        # Mock clients
        s2_client = AsyncMock()
        s2_client.get_references = AsyncMock(return_value=[sample_paper_s2])
        s2_client.get_citations = AsyncMock(return_value=[])

        oa_client = AsyncMock()
        oa_client.get_references = AsyncMock(return_value=[sample_paper_openalex])
        oa_client.get_citations = AsyncMock(return_value=[])

        with patch.object(provider, "_get_client") as mock_get_client:

            async def client_factory(api_name: str) -> AsyncMock:
                if api_name == "semantic_scholar":
                    return s2_client
                elif api_name == "openalex":
                    return oa_client
                raise ValueError(f"Unknown API: {api_name}")

            mock_get_client.side_effect = client_factory

            # When
            papers, citations = await provider.get_citation_graph(
                paper_id="s2:test123",
                depth=1,
                direction="references",
            )

            # Then
            assert len(papers) == 2  # Both S2 and OpenAlex papers
            assert any(p.id == sample_paper_s2.id for p in papers)
            assert any(p.id == sample_paper_openalex.id for p in papers)
            assert len(citations) == 2  # One citation per paper

            # Verify both APIs were called
            s2_client.get_references.assert_called_once()
            oa_client.get_references.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_citation_graph_deduplicates_by_doi(
        self, sample_paper_s2: Paper, sample_reference_paper: Paper
    ) -> None:
        """
        Test: get_citation_graph() deduplicates papers with same DOI.

        Given: Same paper returned from both S2 and OpenAlex (same DOI)
        When: get_citation_graph() is called
        Then: Only one paper instance is returned
        """
        # Given: Same paper from different APIs (same DOI)
        paper_s2_dup = Paper(
            id="s2:duplicate",
            title="Duplicate Paper",
            abstract="Same paper from S2",
            authors=[Author(name="Author", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/reference",  # Same DOI as sample_reference_paper
            arxiv_id=None,
            venue="Journal",
            citation_count=5,
            reference_count=3,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )

        provider = AcademicSearchProvider()

        s2_client = AsyncMock()
        s2_client.get_references = AsyncMock(return_value=[paper_s2_dup])
        s2_client.get_citations = AsyncMock(return_value=[])

        oa_client = AsyncMock()
        oa_client.get_references = AsyncMock(return_value=[sample_reference_paper])
        oa_client.get_citations = AsyncMock(return_value=[])

        with patch.object(provider, "_get_client") as mock_get_client:

            async def client_factory(api_name: str) -> AsyncMock:
                if api_name == "semantic_scholar":
                    return s2_client
                elif api_name == "openalex":
                    return oa_client
                raise ValueError(f"Unknown API: {api_name}")

            mock_get_client.side_effect = client_factory

            # When
            papers, citations = await provider.get_citation_graph(
                paper_id="s2:test123",
                depth=1,
                direction="references",
            )

            # Then: Should deduplicate papers by DOI (only 1 unique paper)
            assert len(papers) == 1  # Deduplicated
            assert papers[0].doi == "10.1234/reference"
            # Citations are tracked by paper_id pairs, so both citations exist
            # (even though they refer to the same paper via DOI)
            # This is expected behavior: paper deduplication happens, but citation
            # pairs are tracked by paper_id, not DOI
            assert len(citations) == 2

    @pytest.mark.asyncio
    async def test_get_citation_graph_handles_api_failures(self, sample_paper_s2: Paper) -> None:
        """
        Test: get_citation_graph() handles API failures gracefully.

        Given: One API fails
        When: get_citation_graph() is called
        Then: Results from working API are still returned
        """
        # Given
        provider = AcademicSearchProvider()

        s2_client = AsyncMock()
        s2_client.get_references = AsyncMock(return_value=[sample_paper_s2])
        s2_client.get_citations = AsyncMock(return_value=[])

        oa_client = AsyncMock()
        oa_client.get_references = AsyncMock(side_effect=Exception("OpenAlex API error"))
        oa_client.get_citations = AsyncMock(return_value=[])

        with patch.object(provider, "_get_client") as mock_get_client:

            async def client_factory(api_name: str) -> AsyncMock:
                if api_name == "semantic_scholar":
                    return s2_client
                elif api_name == "openalex":
                    return oa_client
                raise ValueError(f"Unknown API: {api_name}")

            mock_get_client.side_effect = client_factory

            # When
            papers, citations = await provider.get_citation_graph(
                paper_id="s2:test123",
                depth=1,
                direction="references",
            )

            # Then: Should still return S2 results
            assert len(papers) == 1
            assert papers[0].id == sample_paper_s2.id

    @pytest.mark.asyncio
    async def test_get_citation_graph_direction_citations_only(
        self, sample_paper_s2: Paper, sample_paper_openalex: Paper
    ) -> None:
        """
        Test: get_citation_graph() with direction="citations" only.

        Given: direction="citations"
        When: get_citation_graph() is called
        Then: Only citations are fetched, not references
        """
        # Given
        provider = AcademicSearchProvider()

        s2_client = AsyncMock()
        s2_client.get_references = AsyncMock(return_value=[])
        s2_client.get_citations = AsyncMock(return_value=[sample_paper_s2])

        oa_client = AsyncMock()
        oa_client.get_references = AsyncMock(return_value=[])
        oa_client.get_citations = AsyncMock(return_value=[sample_paper_openalex])

        with patch.object(provider, "_get_client") as mock_get_client:

            async def client_factory(api_name: str) -> AsyncMock:
                if api_name == "semantic_scholar":
                    return s2_client
                elif api_name == "openalex":
                    return oa_client
                raise ValueError(f"Unknown API: {api_name}")

            mock_get_client.side_effect = client_factory

            # When
            papers, citations = await provider.get_citation_graph(
                paper_id="s2:test123",
                depth=1,
                direction="citations",
            )

            # Then
            assert len(papers) == 2
            s2_client.get_references.assert_not_called()
            oa_client.get_references.assert_not_called()
            s2_client.get_citations.assert_called_once()
            oa_client.get_citations.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_citation_graph_depth_zero(self) -> None:
        """
        Test: get_citation_graph() with depth=0 returns empty.

        Given: depth=0
        When: get_citation_graph() is called
        Then: Empty results (no exploration)
        """
        # Given
        provider = AcademicSearchProvider()

        s2_client = AsyncMock()
        oa_client = AsyncMock()

        with patch.object(provider, "_get_client") as mock_get_client:

            async def client_factory(api_name: str) -> AsyncMock:
                if api_name == "semantic_scholar":
                    return s2_client
                elif api_name == "openalex":
                    return oa_client
                raise ValueError(f"Unknown API: {api_name}")

            mock_get_client.side_effect = client_factory

            # When
            papers, citations = await provider.get_citation_graph(
                paper_id="s2:test123",
                depth=0,
                direction="both",
            )

            # Then: No exploration, empty results
            assert len(papers) == 0
            assert len(citations) == 0
            s2_client.get_references.assert_not_called()
            s2_client.get_citations.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_citation_graph_empty_results(self) -> None:
        """
        Test: get_citation_graph() handles empty API results.

        Given: Both APIs return empty lists
        When: get_citation_graph() is called
        Then: Empty papers and citations lists
        """
        # Given
        provider = AcademicSearchProvider()

        s2_client = AsyncMock()
        s2_client.get_references = AsyncMock(return_value=[])
        s2_client.get_citations = AsyncMock(return_value=[])

        oa_client = AsyncMock()
        oa_client.get_references = AsyncMock(return_value=[])
        oa_client.get_citations = AsyncMock(return_value=[])

        with patch.object(provider, "_get_client") as mock_get_client:

            async def client_factory(api_name: str) -> AsyncMock:
                if api_name == "semantic_scholar":
                    return s2_client
                elif api_name == "openalex":
                    return oa_client
                raise ValueError(f"Unknown API: {api_name}")

            mock_get_client.side_effect = client_factory

            # When
            papers, citations = await provider.get_citation_graph(
                paper_id="s2:test123",
                depth=1,
                direction="both",
            )

            # Then
            assert len(papers) == 0
            assert len(citations) == 0

    @pytest.mark.asyncio
    async def test_get_citation_graph_both_apis_fail(self) -> None:
        """
        Test: get_citation_graph() handles both APIs failing.

        Given: Both S2 and OpenAlex fail
        When: get_citation_graph() is called
        Then: Empty results, no exception raised
        """
        # Given
        provider = AcademicSearchProvider()

        s2_client = AsyncMock()
        s2_client.get_references = AsyncMock(side_effect=Exception("S2 API error"))
        s2_client.get_citations = AsyncMock(side_effect=Exception("S2 API error"))

        oa_client = AsyncMock()
        oa_client.get_references = AsyncMock(side_effect=Exception("OpenAlex API error"))
        oa_client.get_citations = AsyncMock(side_effect=Exception("OpenAlex API error"))

        with patch.object(provider, "_get_client") as mock_get_client:

            async def client_factory(api_name: str) -> AsyncMock:
                if api_name == "semantic_scholar":
                    return s2_client
                elif api_name == "openalex":
                    return oa_client
                raise ValueError(f"Unknown API: {api_name}")

            mock_get_client.side_effect = client_factory

            # When
            papers, citations = await provider.get_citation_graph(
                paper_id="s2:test123",
                depth=1,
                direction="both",
            )

            # Then: Should handle gracefully, return empty results
            assert len(papers) == 0
            assert len(citations) == 0

    @pytest.mark.asyncio
    async def test_get_citation_graph_depth_two(
        self, sample_paper_s2: Paper, sample_paper_openalex: Paper
    ) -> None:
        """
        Test: get_citation_graph() with depth=2 explores multiple levels.

        Given: depth=2
        When: get_citation_graph() is called
        Then: Papers at depth 2 are included
        """
        # Given
        provider = AcademicSearchProvider()

        depth_1_paper = Paper(
            id="s2:depth1",
            title="Depth 1 Paper",
            abstract="Abstract",
            authors=[],
            year=2024,
            published_date=None,
            doi="10.1234/depth1",
            arxiv_id=None,
            venue=None,
            citation_count=0,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )

        depth_2_paper = Paper(
            id="s2:depth2",
            title="Depth 2 Paper",
            abstract="Abstract",
            authors=[],
            year=2024,
            published_date=None,
            doi="10.1234/depth2",
            arxiv_id=None,
            venue=None,
            citation_count=0,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )

        s2_client = AsyncMock()
        # First call (depth 0 -> 1)
        s2_client.get_references = AsyncMock(
            side_effect=[
                [depth_1_paper],  # First call
                [depth_2_paper],  # Second call (depth 1 -> 2)
            ]
        )
        s2_client.get_citations = AsyncMock(return_value=[])

        oa_client = AsyncMock()
        oa_client.get_references = AsyncMock(return_value=[])
        oa_client.get_citations = AsyncMock(return_value=[])

        with patch.object(provider, "_get_client") as mock_get_client:

            async def client_factory(api_name: str) -> AsyncMock:
                if api_name == "semantic_scholar":
                    return s2_client
                elif api_name == "openalex":
                    return oa_client
                raise ValueError(f"Unknown API: {api_name}")

            mock_get_client.side_effect = client_factory

            # When
            papers, citations = await provider.get_citation_graph(
                paper_id="s2:test123",
                depth=2,
                direction="references",
            )

            # Then: Should include papers from depth 2
            assert len(papers) >= 2
            assert s2_client.get_references.call_count == 2  # Called for depth 0->1 and 1->2


class TestAPIReturnTypes:
    """Tests for API return type consistency (Decision 12)."""

    @pytest.mark.asyncio
    async def test_openalex_get_references_returns_list_paper(self) -> None:
        """
        Test: OpenAlex get_references() returns list[Paper] (not tuple).

        Given: OpenAlex client
        When: get_references() is called
        Then: Returns list[Paper]
        """
        from src.search.apis.openalex import OpenAlexClient

        client = OpenAlexClient()

        mock_paper = Paper(
            id="openalex:W123",
            title="Test",
            abstract="Abstract",
            authors=[],
            year=2024,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            citation_count=0,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="openalex",
        )

        with (
            patch.object(client, "get_paper", return_value=mock_paper),
            patch("src.search.apis.openalex.retry_api_call") as mock_retry,
        ):
            mock_retry.return_value = {
                "referenced_works": ["W123"],
            }

            # When
            result = await client.get_references("openalex:W123")

            # Then
            assert isinstance(result, list)
            assert all(isinstance(p, Paper) for p in result)
            assert not any(isinstance(p, tuple) for p in result)

    @pytest.mark.asyncio
    async def test_openalex_get_references_filters_no_abstract(self) -> None:
        """
        Test: OpenAlex get_references() filters papers without abstract.

        Given: Paper without abstract
        When: get_references() is called
        Then: Returns empty list (abstract required)
        """
        from src.search.apis.openalex import OpenAlexClient

        client = OpenAlexClient()

        with patch.object(client, "get_paper") as mock_get_paper:
            mock_paper_no_abstract = Paper(
                id="openalex:W123",
                title="Test",
                abstract=None,  # No abstract
                authors=[],
                year=2024,
                published_date=None,
                doi=None,
                arxiv_id=None,
                venue=None,
                citation_count=0,
                reference_count=0,
                is_open_access=False,
                oa_url=None,
                pdf_url=None,
                source_api="openalex",
            )
            mock_get_paper.return_value = mock_paper_no_abstract

            with patch("src.search.apis.openalex.retry_api_call") as mock_retry:
                mock_retry.return_value = {
                    "referenced_works": ["W123"],
                }

                # When
                result = await client.get_references("openalex:W123")

                # Then: Should filter out papers without abstract
                assert isinstance(result, list)
                assert len(result) == 0

    @pytest.mark.asyncio
    async def test_openalex_get_citations_returns_list_paper(self) -> None:
        """
        Test: OpenAlex get_citations() returns list[Paper] (not tuple).

        Given: OpenAlex client
        When: get_citations() is called
        Then: Returns list[Paper]
        """
        from src.search.apis.openalex import OpenAlexClient

        client = OpenAlexClient()

        # httpx.Response.json() is sync; use MagicMock to avoid creating an un-awaited coroutine
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "https://openalex.org/W123",
                    "title": "Test Paper",
                    "abstract_inverted_index": {"test": [0], "paper": [1]},
                    "publication_year": 2024,
                    "authorships": [],
                    "doi": None,
                    "cited_by_count": 0,
                    "referenced_works_count": 0,
                    "open_access": {},
                    "primary_location": {},
                }
            ],
        }
        mock_response.raise_for_status = lambda: None
        mock_session_instance = AsyncMock()
        mock_session_instance.get = AsyncMock(return_value=mock_response)

        async def mock_get_session() -> AsyncMock:
            return mock_session_instance

        with patch.object(client, "_get_session", side_effect=mock_get_session):
            # When
            result = await client.get_citations("openalex:W123")

            # Then
            assert isinstance(result, list)
            assert all(isinstance(p, Paper) for p in result)
            assert not any(isinstance(p, tuple) for p in result)

    @pytest.mark.asyncio
    async def test_openalex_get_citations_filters_no_abstract(self) -> None:
        """
        Test: OpenAlex get_citations() filters papers without abstract.

        Given: Papers without abstract in API response
        When: get_citations() is called
        Then: Returns empty list (abstract required)
        """
        from src.search.apis.openalex import OpenAlexClient

        client = OpenAlexClient()

        with patch.object(client, "_get_session") as mock_session:
            # httpx.Response.json() is sync; use MagicMock to avoid creating an un-awaited coroutine
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "title": "Test Paper",
                        "abstract_inverted_index": None,  # No abstract
                        "publication_year": 2024,
                        "authorships": [],
                        "doi": None,
                        "cited_by_count": 0,
                        "referenced_works_count": 0,
                        "open_access": {},
                        "primary_location": {},
                    }
                ],
            }
            mock_response.raise_for_status = lambda: None
            mock_session.return_value.get = AsyncMock(return_value=mock_response)

            # When
            result = await client.get_citations("openalex:W123")

            # Then: Should filter out papers without abstract
            assert isinstance(result, list)
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_arxiv_get_references_returns_list_paper(self) -> None:
        """
        Test: arXiv get_references() returns list[Paper] (not tuple).

        Given: arXiv client
        When: get_references() is called
        Then: Returns list[Paper]
        """
        from src.search.apis.arxiv import ArxivClient

        client = ArxivClient()

        # When
        result = await client.get_references("arxiv:1234.5678")

        # Then
        assert isinstance(result, list)
        assert all(isinstance(p, Paper) for p in result)
        assert not any(isinstance(p, tuple) for p in result)

    @pytest.mark.asyncio
    async def test_crossref_get_references_returns_list_paper(self) -> None:
        """
        Test: Crossref get_references() returns list[Paper] (not tuple).

        Given: Crossref client
        When: get_references() is called
        Then: Returns list[Paper]
        """
        from src.search.apis.crossref import CrossrefClient

        client = CrossrefClient()

        # When
        result = await client.get_references("10.1234/test")

        # Then
        assert isinstance(result, list)
        assert all(isinstance(p, Paper) for p in result)
        assert not any(isinstance(p, tuple) for p in result)
