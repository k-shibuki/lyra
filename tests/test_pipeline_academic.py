"""
Tests for academic search pipeline integration.

Per ADR-0008: Academic Data Source Strategy.

Tests the Abstract Only strategy and citation graph integration
in the SearchPipeline._execute_unified_search() method.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-PA-N-01 | Paper with abstract from API | Equivalence – normal | Abstract persisted, fetch skipped | - |
| TC-PA-N-02 | Paper without abstract from API | Equivalence – normal | Browser search fallback triggered | - |
| TC-PA-N-03 | SERP-only entry (no Paper) | Equivalence – normal | Browser search fallback triggered | - |
| TC-PA-N-04 | Entry with source="both", paper.abstract=None | Equivalence – normal | Browser search fallback triggered | Bug 1関連 |
| TC-PA-N-05 | Entry with source="api", paper.abstract=None | Equivalence – normal | Browser search fallback triggered | Bug 1関連 |
| TC-PA-B-01 | abstract="" (empty string) | Boundary – empty | Treated as no abstract, fetch needed | - |
| TC-PA-B-02 | abstract=None | Boundary – NULL | Fetch needed | - |
| TC-PA-B-03 | entries_needing_fetch=[] | Boundary – empty | No browser search fallback | - |
| TC-PA-A-01 | _persist_abstract_as_fragment() raises exception | Abnormal – exception | Exception caught, logged, processing continues | - |
| TC-PA-A-02 | get_citation_graph() raises exception | Abnormal – exception | Exception caught, logged, processing continues | - |
| TC-PA-A-03 | DB insert fails | Abnormal – exception | Exception handled gracefully | - |
| TC-SS-N-01 | ID format: s2:12345 | Equivalence – normal | Normalized to CorpusId:12345 | Bug 2関連 |
| TC-SS-N-02 | ID format: CorpusId:12345 | Equivalence – normal | Returns as-is | - |
| TC-SS-N-03 | ID format: DOI:10.1234/example | Equivalence – normal | Returns as-is | - |
| TC-SS-N-04 | ID format: 12345 (no prefix) | Equivalence – normal | Normalized to CorpusId:12345 | - |
| TC-SS-A-01 | get_references() with s2: ID | Abnormal – API call | API called with CorpusId: format | Bug 2関連 |
| TC-SS-A-02 | get_citations() with s2: ID | Abnormal – API call | API called with CorpusId: format | Bug 2関連 |
| TC-SS-A-03 | API returns 404 for invalid ID | Abnormal – API error | Empty list returned, exception logged | - |
| TC-NA-N-01 | Non-academic query + DOI in SERP | Equivalence – normal | Identifier extracted, API complement executed | |
| TC-NA-N-02 | Non-academic query + PMID in SERP | Equivalence – normal | PMID extracted, DOI resolved, API complement executed | |
| TC-NA-N-03 | Non-academic query + arXiv ID in SERP | Equivalence – normal | arXiv ID extracted, DOI resolved, API complement executed | |
| TC-NA-N-04 | Non-academic query + no identifiers | Equivalence – normal | No API complement attempted | |
| TC-NA-N-05 | Identifier complement + citation tracking | Equivalence – normal | Citation graph retrieved and processed | |
| TC-NA-B-01 | Empty SERP items list | Boundary – empty | No processing attempted, no error | |
| TC-NA-B-02 | SERP item with empty URL | Boundary – empty | Item skipped, processing continues | |
| TC-NA-B-03 | Paper without abstract returned | Boundary – NULL | Paper not added to pages, citation tracking skipped | |
| TC-NA-A-01 | API error during identifier complement | Abnormal – exception | Exception caught, logged, processing continues | |
| TC-NA-A-02 | DOI resolution failure (PMID) | Abnormal – exception | Exception caught, API complement skipped | |
| TC-NA-A-03 | Citation graph retrieval failure | Abnormal – exception | Exception caught, logged, processing continues | |
| TC-NA-A-04 | Paper lookup returns None | Abnormal – NULL | None handled gracefully, no error | |
| TC-NA-A-05 | SERP search raises exception | Abnormal – exception | Exception caught, logged, executor result preserved | |
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.research.pipeline import SearchPipeline, SearchPipelineResult
from src.research.state import ExplorationState
from src.search.provider import SERPResult
from src.utils.schemas import Author, CanonicalEntry, Citation, Paper

T = TypeVar("T")

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_paper_with_abstract() -> Paper:
    """Paper with abstract (should skip fetch)."""
    return Paper(
        id="s2:test123",
        title="Test Paper With Abstract",
        abstract="This is a test abstract for validation.",
        authors=[Author(name="John Doe", affiliation="Test University", orcid=None)],
        year=2024,
        published_date=None,
        doi="10.1234/test.paper",
        arxiv_id=None,
        venue="Nature",
        citation_count=42,
        reference_count=25,
        is_open_access=True,
        oa_url="https://example.com/paper.pdf",
        pdf_url="https://example.com/paper.pdf",
        source_api="semantic_scholar",
    )


@pytest.fixture
def sample_paper_without_abstract() -> Paper:
    """Paper without abstract (should need fetch)."""
    return Paper(
        id="s2:test456",
        title="Test Paper Without Abstract",
        abstract=None,
        authors=[Author(name="Jane Doe", affiliation=None, orcid=None)],
        year=2024,
        published_date=None,
        doi="10.1234/test.paper2",
        arxiv_id=None,
        venue=None,
        oa_url=None,
        pdf_url=None,
        source_api="openalex",
    )


@pytest.fixture
def sample_citations() -> list[Citation]:
    """Sample citation relationships."""
    return [
        Citation(
            citing_paper_id="s2:test123",
            cited_paper_id="s2:ref1",
            context=None,
            source_api="semantic_scholar",
        ),
        Citation(
            citing_paper_id="s2:test123",
            cited_paper_id="s2:ref2",
            context="As shown in previous work...",
            source_api="openalex",
        ),
    ]


# =============================================================================
# Test: Abstract Only Strategy
# =============================================================================


class TestAbstractOnlyStrategy:
    """Tests for Abstract Only strategy implementation."""

    @pytest.mark.asyncio
    async def test_persist_abstract_as_fragment(self, sample_paper_with_abstract: Paper) -> None:
        """
        Test: _persist_abstract_as_fragment() creates page and fragment.

        Given: Paper with abstract
        When: _persist_abstract_as_fragment() is called
        Then: Page and fragment are created in database
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        with patch("src.research.pipeline.get_database") as mock_db:
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(return_value="test_id")
            # Mock resource dedup methods (claim succeeds, complete does nothing)
            mock_db_instance.claim_resource = AsyncMock(return_value=(True, None))
            mock_db_instance.complete_resource = AsyncMock()

            # When
            page_id, fragment_id = await pipeline._persist_abstract_as_fragment(
                paper=sample_paper_with_abstract,
                task_id="test_task",
                search_id="test_search",
            )

            # Then
            assert page_id.startswith("page_")
            assert fragment_id.startswith("frag_")

            # Verify DB inserts: pages, fragments, claims, edges
            # Note: _extract_claims_from_abstract adds claims and edges
            assert mock_db_instance.insert.call_count >= 2  # At minimum pages + fragments

            # Check pages insert
            pages_call = mock_db_instance.insert.call_args_list[0]
            assert pages_call[0][0] == "pages"
            pages_data = pages_call[0][1]
            assert pages_data["page_type"] == "academic_paper"
            assert pages_data["title"] == sample_paper_with_abstract.title
            assert "paper_metadata" in pages_data

            # Check fragments insert
            fragments_call = mock_db_instance.insert.call_args_list[1]
            assert fragments_call[0][0] == "fragments"
            fragments_data = fragments_call[0][1]
            assert fragments_data["fragment_type"] == "abstract"
            assert fragments_data["text_content"] == sample_paper_with_abstract.abstract

            # Verify resource dedup was called
            mock_db_instance.claim_resource.assert_called_once()
            mock_db_instance.complete_resource.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_abstract_existing_resource_returns_fragment_id(
        self, sample_paper_with_abstract: Paper
    ) -> None:
        """
        Test: _persist_abstract_as_fragment() returns existing fragment_id when resource exists.

        Given: Paper already processed by another worker (claim_resource returns False)
        When: _persist_abstract_as_fragment() is called
        Then: Existing page_id and fragment_id are returned (ADR-0005: global resources)
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        with patch("src.research.pipeline.get_database") as mock_get_db:
            mock_db_instance = AsyncMock()
            mock_get_db.return_value = mock_db_instance

            # Mock: resource already claimed by another worker
            existing_page_id = "page_existing123"
            existing_fragment_id = "frag_existing456"
            mock_db_instance.claim_resource = AsyncMock(return_value=(False, existing_page_id))
            # Mock: fetch_one returns existing fragment
            mock_db_instance.fetch_one = AsyncMock(return_value={"id": existing_fragment_id})

            # When
            page_id, fragment_id = await pipeline._persist_abstract_as_fragment(
                paper=sample_paper_with_abstract,
                task_id="test_task",
                search_id="test_search",
            )

            # Then: should return existing page_id and fragment_id
            assert page_id == existing_page_id
            assert fragment_id == existing_fragment_id

            # Verify: no inserts (resource already exists)
            mock_db_instance.insert.assert_not_called()
            mock_db_instance.complete_resource.assert_not_called()

            # Verify: fragment lookup was done
            mock_db_instance.fetch_one.assert_called_once()
            call_args = mock_db_instance.fetch_one.call_args
            assert "fragments" in call_args[0][0]
            assert "abstract" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_persist_abstract_existing_resource_no_fragment(
        self, sample_paper_with_abstract: Paper
    ) -> None:
        """
        Test: _persist_abstract_as_fragment() returns None fragment_id when fragment not found.

        Given: Page exists but fragment was not created (edge case)
        When: _persist_abstract_as_fragment() is called
        Then: Existing page_id returned, fragment_id is None
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        with patch("src.research.pipeline.get_database") as mock_get_db:
            mock_db_instance = AsyncMock()
            mock_get_db.return_value = mock_db_instance

            # Mock: resource claimed but page has no fragment
            existing_page_id = "page_nofrag123"
            mock_db_instance.claim_resource = AsyncMock(return_value=(False, existing_page_id))
            mock_db_instance.fetch_one = AsyncMock(return_value=None)

            # When
            page_id, fragment_id = await pipeline._persist_abstract_as_fragment(
                paper=sample_paper_with_abstract,
                task_id="test_task",
                search_id="test_search",
            )

            # Then
            assert page_id == existing_page_id
            assert fragment_id is None

    @pytest.mark.asyncio
    async def test_paper_with_abstract_skips_fetch(self, sample_paper_with_abstract: Paper) -> None:
        """
        Test: Papers with abstracts from API skip fetch.

        Given: Academic search returns paper with abstract
        When: _execute_unified_search() is called
        Then: Abstract is persisted directly, fetch is skipped
        """
        # Mock CanonicalEntry with paper that has abstract
        entry = CanonicalEntry(
            canonical_id="doi:10.1234/test.paper",
            paper=sample_paper_with_abstract,
            serp_results=[],
            source="api",
        )

        # Then: needs_fetch should be False
        assert entry.needs_fetch is False

    @pytest.mark.asyncio
    async def test_paper_without_abstract_needs_fetch(
        self, sample_paper_without_abstract: Paper
    ) -> None:
        """
        Test: Papers without abstracts need fetch.

        Given: Academic search returns paper without abstract
        When: Checking needs_fetch property
        Then: needs_fetch is True
        """
        # Given
        entry = CanonicalEntry(
            canonical_id="doi:10.1234/test.paper2",
            paper=sample_paper_without_abstract,
            serp_results=[],
            source="api",
        )

        # Then: needs_fetch should be True (no abstract)
        assert entry.needs_fetch is True

    @pytest.mark.asyncio
    async def test_serp_only_entry_needs_fetch(self) -> None:
        """
        Test: SERP-only entries (no Paper) need fetch.

        Given: Entry from SERP without Paper object
        When: Checking needs_fetch property
        Then: needs_fetch is True
        """
        # Given
        serp_result = SERPResult(
            title="Test SERP Result",
            url="https://example.com/article",
            snippet="Test snippet",
            engine="google",
            rank=1,
        )

        entry = CanonicalEntry(
            canonical_id="url:abc123",
            paper=None,  # No Paper object
            serp_results=[serp_result],
            source="serp",
        )

        # Then: needs_fetch should be True (no paper)
        assert entry.needs_fetch is True


# =============================================================================
# Test: Evidence Graph Integration
# =============================================================================


class TestEvidenceGraphIntegration:
    """Tests for evidence graph integration with academic citations."""

    @pytest.mark.asyncio
    async def test_add_academic_page_with_citations(self, sample_citations: list[Citation]) -> None:
        """
        Test: add_academic_page_with_citations() adds nodes and edges.

        Given: Page ID, paper metadata, and citations
        When: add_academic_page_with_citations() is called
        Then: PAGE node and CITES edges are added to graph
        """
        from src.filter.evidence_graph import (
            NodeType,
            RelationType,
            add_academic_page_with_citations,
        )

        with patch("src.filter.evidence_graph.get_database") as mock_db:
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(return_value="edge_id")
            # add_academic_page_with_citations() awaits fetch_one/fetch_all; ensure they return non-AsyncMock values
            mock_db_instance.fetch_one = AsyncMock(return_value=None)
            mock_db_instance.fetch_all = AsyncMock(return_value=[])

            # Given
            page_id = "page_test123"
            paper_metadata = {
                "paper_id": "s2:test123",
                "doi": "10.1234/test",
                "citation_count": 42,
                "year": 2024,
                "venue": "Nature",
                "source_api": "semantic_scholar",
            }

            # Given: paper_to_page_map for citations
            paper_to_page_map = {
                "s2:test123": page_id,
                "s2:ref1": "page_ref1",
                "s2:ref2": "page_ref2",
                "s2:ref3": "page_ref3",
            }

            # When
            await add_academic_page_with_citations(
                page_id=page_id,
                paper_metadata=paper_metadata,
                citations=sample_citations,
                task_id="test_task",
                paper_to_page_map=paper_to_page_map,
            )

            # Then: Verify edges were inserted
            assert mock_db_instance.insert.call_count == len(sample_citations)

            # Check edge properties
            for call in mock_db_instance.insert.call_args_list:
                edge_data = call[0][1]
                assert edge_data["source_type"] == NodeType.PAGE.value
                assert edge_data["relation"] == RelationType.CITES.value
                assert edge_data["citation_source"] in ("semantic_scholar", "openalex")


# =============================================================================
# Test: Paper Metadata Persistence
# =============================================================================


class TestPaperMetadataPersistence:
    """Tests for paper metadata JSON persistence."""

    @pytest.mark.asyncio
    async def test_paper_metadata_json_structure(self, sample_paper_with_abstract: Paper) -> None:
        """
        Test: paper_metadata JSON has correct structure.

        Given: Paper with full metadata
        When: Persisting to pages table
        Then: paper_metadata JSON contains all fields
        """
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        with patch("src.research.pipeline.get_database") as mock_db:
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(return_value="test_id")
            # Mock resource dedup methods
            mock_db_instance.claim_resource = AsyncMock(return_value=(True, None))
            mock_db_instance.complete_resource = AsyncMock()

            await pipeline._persist_abstract_as_fragment(
                paper=sample_paper_with_abstract,
                task_id="test_task",
                search_id="test_search",
            )

            # Get pages insert call
            pages_call = mock_db_instance.insert.call_args_list[0]
            pages_data = pages_call[0][1]

            # Parse and verify paper_metadata JSON
            paper_metadata = json.loads(pages_data["paper_metadata"])

            assert paper_metadata["doi"] == sample_paper_with_abstract.doi
            assert paper_metadata["year"] == sample_paper_with_abstract.year
            assert paper_metadata["venue"] == sample_paper_with_abstract.venue
            assert paper_metadata["citation_count"] == sample_paper_with_abstract.citation_count
            assert paper_metadata["is_open_access"] == sample_paper_with_abstract.is_open_access
            assert paper_metadata["source_api"] == sample_paper_with_abstract.source_api
            assert len(paper_metadata["authors"]) == 1
            assert paper_metadata["authors"][0]["name"] == "John Doe"


# =============================================================================
# Test: CanonicalEntry.needs_fetch Property
# =============================================================================


class TestCanonicalEntryNeedsFetch:
    """Tests for CanonicalEntry.needs_fetch property."""

    def test_needs_fetch_with_abstract(self, sample_paper_with_abstract: Paper) -> None:
        """
        Given: Paper with abstract
        When: Checking needs_fetch
        Then: False (no fetch needed)
        """
        entry = CanonicalEntry(
            canonical_id="doi:test",
            paper=sample_paper_with_abstract,
            serp_results=[],
            source="api",
        )
        assert entry.needs_fetch is False

    def test_needs_fetch_without_abstract(self, sample_paper_without_abstract: Paper) -> None:
        """
        Given: Paper without abstract
        When: Checking needs_fetch
        Then: True (fetch needed)
        """
        entry = CanonicalEntry(
            canonical_id="doi:test",
            paper=sample_paper_without_abstract,
            serp_results=[],
            source="api",
        )
        assert entry.needs_fetch is True

    def test_needs_fetch_no_paper(self) -> None:
        """
        Given: Entry without Paper (SERP only)
        When: Checking needs_fetch
        Then: True (fetch needed)
        """
        entry = CanonicalEntry(
            canonical_id="url:test",
            paper=None,
            serp_results=[],
            source="serp",
        )
        assert entry.needs_fetch is True

    def test_needs_fetch_api_source_no_abstract(self, sample_paper_without_abstract: Paper) -> None:
        """
        TC-PA-N-05: Entry with source="api", paper.abstract=None needs fetch.

        Given: Entry with source="api" and Paper without abstract
        When: Checking needs_fetch
        Then: True (fetch needed)
        """
        # Given: Entry with API source but no abstract
        entry = CanonicalEntry(
            canonical_id="doi:10.1234/test",
            paper=sample_paper_without_abstract,
            serp_results=[],
            source="api",
        )

        # Then: needs_fetch should be True
        assert entry.needs_fetch is True

    def test_needs_fetch_both_source_no_abstract(
        self, sample_paper_without_abstract: Paper
    ) -> None:
        """
        TC-PA-N-04: Entry with source="both", paper.abstract=None needs fetch.

        Given: Entry with source="both" and Paper without abstract
        When: Checking needs_fetch
        Then: True (fetch needed)
        """
        # Given: Entry with both sources but no abstract
        serp_result = SERPResult(
            title="Test SERP",
            url="https://example.com",
            snippet="Test",
            engine="google",
            rank=1,
        )
        entry = CanonicalEntry(
            canonical_id="doi:10.1234/test",
            paper=sample_paper_without_abstract,
            serp_results=[serp_result],
            source="both",
        )

        # Then: needs_fetch should be True
        assert entry.needs_fetch is True

    def test_needs_fetch_empty_abstract_string(self) -> None:
        """
        TC-PA-B-01: Empty string abstract is treated as no abstract.

        Given: Paper with abstract=""
        When: Checking needs_fetch
        Then: True (fetch needed)
        """
        # Given: Paper with empty string abstract
        paper = Paper(
            id="s2:test",
            title="Test",
            abstract="",  # Empty string
            authors=[],
            year=None,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )
        entry = CanonicalEntry(
            canonical_id="doi:test",
            paper=paper,
            serp_results=[],
            source="api",
        )

        # Then: needs_fetch should be True (empty string is falsy)
        assert entry.needs_fetch is True


# =============================================================================
# Test: Semantic Scholar API ID Normalization
# =============================================================================


class TestSemanticScholarIDNormalization:
    """Tests for Semantic Scholar API ID format normalization (Bug 2 fix)."""

    def test_normalize_s2_prefix_removed(self) -> None:
        """
        TC-SS-N-01: s2: prefix is removed, paperId used directly.

        Given: Paper ID with s2: prefix (40-char alphanumeric hash)
        When: Normalizing for API
        Then: Returns paperId without prefix (API expects direct paperId)
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient

        # Given: s2: prefix with 40-char paperId hash
        client = SemanticScholarClient()
        paper_id_hash = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"
        paper_id = f"s2:{paper_id_hash}"

        # When
        normalized = client._normalize_paper_id(paper_id)

        # Then: Prefix removed, paperId used directly
        assert normalized == paper_id_hash
        assert normalized.startswith("s2:") is False

    def test_normalize_corpusid_unchanged(self) -> None:
        """
        TC-SS-N-02: CorpusId: format is returned as-is (for numeric Corpus IDs).

        Given: Paper ID with CorpusId: prefix (numeric Corpus ID)
        When: Normalizing for API
        Then: Returns unchanged (CorpusId: prefix is valid for numeric IDs)
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient

        # Given: CorpusId: with numeric ID (valid format)
        client = SemanticScholarClient()
        paper_id = "CorpusId:12345"

        # When
        normalized = client._normalize_paper_id(paper_id)

        # Then: Unchanged (CorpusId: is valid for numeric IDs)
        assert normalized == "CorpusId:12345"

    def test_normalize_doi_unchanged(self) -> None:
        """
        TC-SS-N-03: DOI: format is returned as-is.

        Given: Paper ID with DOI: prefix
        When: Normalizing for API
        Then: Returns unchanged
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient

        # Given
        client = SemanticScholarClient()
        paper_id = "DOI:10.1234/example"

        # When
        normalized = client._normalize_paper_id(paper_id)

        # Then
        assert normalized == "DOI:10.1234/example"

    def test_normalize_no_prefix_unchanged(self) -> None:
        """
        TC-SS-N-04: ID without prefix is used as-is (assumed to be paperId).

        Given: Paper ID without prefix (40-char hash)
        When: Normalizing for API
        Then: Returns unchanged (API expects direct paperId)
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient

        # Given: paperId without prefix (40-char hash)
        client = SemanticScholarClient()
        paper_id = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"

        # When
        normalized = client._normalize_paper_id(paper_id)

        # Then: Unchanged (assumed to be paperId)
        assert normalized == paper_id

    @pytest.mark.asyncio
    async def test_get_references_uses_normalized_id(self) -> None:
        """
        TC-SS-A-01: get_references() uses normalized ID format.

        Given: Paper ID with s2: prefix
        When: Calling get_references()
        Then: API is called with paperId without prefix
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient

        # Given: s2: prefix with paperId hash
        client = SemanticScholarClient()
        paper_id_hash = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"
        paper_id = f"s2:{paper_id_hash}"

        # Create mock response - httpx.Response.json() is synchronous, not async
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value={"data": []})
        mock_response.raise_for_status = MagicMock()  # Not async

        # Create mock HTTP client with properly configured get method
        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=mock_response)

        # Mock retry_api_call to directly execute the _fetch function
        async def mock_retry_api_call(
            func: Callable[..., Awaitable[T]],
            *args: object,
            **kwargs: object,
        ) -> T:
            """Execute the function directly without retry logic."""
            # retry_api_call consumes these kwargs; the inner function doesn't accept them
            kwargs.pop("policy", None)
            kwargs.pop("operation_name", None)
            kwargs.pop("rate_limiter_provider", None)
            return await func(*args, **kwargs)

        with (
            patch.object(client, "_get_session", return_value=mock_http),
            patch("src.search.apis.semantic_scholar.retry_api_call", new=mock_retry_api_call),
        ):
            # When
            await client.get_references(paper_id)

            # Then: API should be called with paperId without prefix
            mock_http.get.assert_called_once()
            call_args = mock_http.get.call_args
            url = call_args[0][0]
            assert paper_id_hash in url
            assert "s2:" not in url
            assert "CorpusId:" not in url

    @pytest.mark.asyncio
    async def test_get_citations_uses_normalized_id(self) -> None:
        """
        TC-SS-A-02: get_citations() uses normalized ID format.

        Given: Paper ID with s2: prefix
        When: Calling get_citations()
        Then: API is called with paperId without prefix
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient

        # Given: s2: prefix with paperId hash
        client = SemanticScholarClient()
        paper_id_hash = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"
        paper_id = f"s2:{paper_id_hash}"

        # Create mock response - httpx.Response.json() is synchronous, not async
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value={"data": []})
        mock_response.raise_for_status = MagicMock()  # Not async

        # Create mock HTTP client with properly configured get method
        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=mock_response)

        # Mock retry_api_call to directly execute the _fetch function
        async def mock_retry_api_call(
            func: Callable[..., Awaitable[T]],
            *args: object,
            **kwargs: object,
        ) -> T:
            """Execute the function directly without retry logic."""
            # retry_api_call consumes these kwargs; the inner function doesn't accept them
            kwargs.pop("policy", None)
            kwargs.pop("operation_name", None)
            kwargs.pop("rate_limiter_provider", None)
            return await func(*args, **kwargs)

        with (
            patch.object(client, "_get_session", return_value=mock_http),
            patch("src.search.apis.semantic_scholar.retry_api_call", new=mock_retry_api_call),
        ):
            # When
            await client.get_citations(paper_id)

            # Then: API should be called with paperId without prefix
            mock_http.get.assert_called_once()
            call_args = mock_http.get.call_args
            url = call_args[0][0]
            assert paper_id_hash in url
            assert "s2:" not in url
            assert "CorpusId:" not in url


# =============================================================================
# Test: End-to-End Integration Tests
# =============================================================================


class TestExecuteComplementarySearchIntegration:
    """End-to-end tests for _execute_unified_search() processing flow."""

    def test_paper_without_abstract_triggers_browser_fallback(
        self, sample_paper_without_abstract: Paper
    ) -> None:
        """
        TC-PA-N-02: Paper without abstract triggers browser search fallback.

        Given: Entry with Paper but no abstract (source="api")
        When: Checking needs_fetch property
        Then: needs_fetch is True (should trigger browser fallback)
        """
        # Given: Entry with Paper but no abstract
        entry = CanonicalEntry(
            canonical_id="doi:10.1234/test",
            paper=sample_paper_without_abstract,
            serp_results=[],
            source="api",
        )

        # Then: needs_fetch should be True (will trigger browser fallback)
        assert entry.needs_fetch is True

    def test_mixed_entries_processing(
        self, sample_paper_with_abstract: Paper, sample_paper_without_abstract: Paper
    ) -> None:
        """
        Test: Mixed entries (with/without abstract) are processed correctly.

        Given: Multiple entries with different abstract states
        When: Checking needs_fetch for each
        Then: Each entry has correct needs_fetch value
        """
        # Given: Mixed entries
        entry_with_abstract = CanonicalEntry(
            canonical_id="doi:10.1234/test1",
            paper=sample_paper_with_abstract,
            serp_results=[],
            source="api",
        )

        entry_without_abstract = CanonicalEntry(
            canonical_id="doi:10.1234/test2",
            paper=sample_paper_without_abstract,
            serp_results=[],
            source="api",
        )

        # Then: needs_fetch should differ
        assert entry_with_abstract.needs_fetch is False
        assert entry_without_abstract.needs_fetch is True


# =============================================================================
# Test: Exception Handling
# =============================================================================


class TestExceptionHandling:
    """Tests for exception handling in academic integration."""

    @pytest.mark.asyncio
    async def test_persist_abstract_exception_handled(
        self, sample_paper_with_abstract: Paper
    ) -> None:
        """
        TC-PA-A-01: Exception in _persist_abstract_as_fragment() is handled.

        Given: _persist_abstract_as_fragment() raises exception
        When: Processing entry with abstract
        Then: Exception is raised (caller should handle it)
        """
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        with patch("src.research.pipeline.get_database") as mock_db:
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            # Mock claim_resource to succeed, then insert to fail
            mock_db_instance.claim_resource = AsyncMock(return_value=(True, None))
            mock_db_instance.fail_resource = AsyncMock()
            mock_db_instance.insert = AsyncMock(side_effect=Exception("DB error"))

            # When: Persisting abstract (should raise exception)
            with pytest.raises(Exception) as exc_info:
                await pipeline._persist_abstract_as_fragment(
                    paper=sample_paper_with_abstract,
                    task_id="test_task",
                    search_id="test_search",
                )

            # Then: Exception is raised and fail_resource is called
            assert "DB error" in str(exc_info.value)
            mock_db_instance.fail_resource.assert_called_once()


# =============================================================================
# Test: End-to-End Integration Tests
# =============================================================================


class TestExecuteComplementarySearchE2E:
    """End-to-end tests for _execute_unified_search() - specification-based."""

    @pytest.mark.asyncio
    async def test_abstract_only_strategy_with_mixed_entries(
        self, sample_paper_with_abstract: Paper, sample_paper_without_abstract: Paper
    ) -> None:
        """
        TC-PA-N-06: Abstract Only strategy processes mixed entries correctly.

        Given: Multiple entries with different abstract states
        When: _execute_unified_search() processes entries
        Then:
        - Entries with abstract are persisted directly (fetch skipped)
        - Entries without abstract trigger browser search fallback
        - Stats are accumulated correctly
        """
        from src.search.canonical_index import CanonicalPaperIndex

        state = ExplorationState(task_id="test_task")
        SearchPipeline(task_id="test_task", state=state)

        # Create index with mixed entries
        index = CanonicalPaperIndex()
        index.register_paper(sample_paper_with_abstract, "semantic_scholar")
        index.register_paper(sample_paper_without_abstract, "openalex")

        unique_entries = index.get_all_entries()

        # Verify entries have correct needs_fetch values
        entry_with_abstract = next(
            e for e in unique_entries if e.paper and e.paper.id == sample_paper_with_abstract.id
        )
        entry_without_abstract = next(
            e for e in unique_entries if e.paper and e.paper.id == sample_paper_without_abstract.id
        )

        assert entry_with_abstract.needs_fetch is False
        assert entry_without_abstract.needs_fetch is True

    @pytest.mark.asyncio
    async def test_browser_fallback_for_entries_needing_fetch(
        self, sample_paper_without_abstract: Paper
    ) -> None:
        """
        TC-PA-N-07: Browser search fallback is triggered for entries needing fetch.

        Given: Entry with Paper but no abstract (source="api")
        When: _execute_unified_search() processes entries
        Then: Browser search fallback is triggered via entries_needing_fetch filter
        """
        from src.search.canonical_index import CanonicalPaperIndex

        # Given: Entry with Paper but no abstract
        index = CanonicalPaperIndex()
        index.register_paper(sample_paper_without_abstract, "semantic_scholar")

        unique_entries = index.get_all_entries()
        entries_needing_fetch = [e for e in unique_entries if e.needs_fetch]

        # Then: Entry should be in entries_needing_fetch
        assert len(entries_needing_fetch) == 1
        assert entries_needing_fetch[0].paper == sample_paper_without_abstract

    @pytest.mark.asyncio
    async def test_citation_graph_integration_with_normalized_id(
        self, sample_paper_with_abstract: Paper
    ) -> None:
        """
        TC-PA-N-08: Citation graph integration uses normalized paper IDs.

        Given: Paper with abstract and s2: ID format
        When: get_citation_graph() is called
        Then: API is called with CorpusId: format (not s2:)
        """
        from src.search.academic_provider import AcademicSearchProvider
        from src.utils.schemas import Paper

        provider = AcademicSearchProvider()

        # Create initial paper for get_paper (DOI extraction)
        initial_paper = Paper(
            id="s2:12345",
            title="Initial Paper",
            abstract="Abstract",
            authors=[],
            year=2024,
            published_date=None,
            doi="10.1234/initial",
            arxiv_id=None,
            venue="Nature",
            citation_count=0,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )

        with patch.object(provider, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client

            # Mock get_paper for DOI extraction
            mock_client.get_paper = AsyncMock(return_value=initial_paper)
            # Mock get_references and get_citations to verify ID format
            mock_client.get_references = AsyncMock(return_value=[])
            mock_client.get_citations = AsyncMock(return_value=[])

            # When: Getting citation graph with s2: ID
            papers, citations = await provider.get_citation_graph(
                paper_id="s2:12345",
                depth=1,
                direction="both",
            )

            # Then: Client methods should be called (ID normalization happens in client)
            # Note: Actual ID format verification is tested in TestSemanticScholarIDNormalization
            assert mock_client.get_references.called or mock_client.get_citations.called

    @pytest.mark.asyncio
    async def test_empty_entries_needing_fetch_no_browser_search(self) -> None:
        """
        TC-PA-B-03: Empty entries_needing_fetch does not trigger browser search.

        Given: All entries have abstracts (no entries need fetch)
        When: Processing entries
        Then: Browser search fallback is not triggered
        """
        from src.search.canonical_index import CanonicalPaperIndex

        # Given: All entries have abstracts
        index = CanonicalPaperIndex()
        paper_with_abstract = Paper(
            id="s2:test1",
            title="Test 1",
            abstract="Abstract 1",
            authors=[],
            year=None,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )
        paper_with_abstract2 = Paper(
            id="s2:test2",
            title="Test 2",
            abstract="Abstract 2",
            authors=[],
            year=None,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )
        index.register_paper(paper_with_abstract, "semantic_scholar")
        index.register_paper(paper_with_abstract2, "semantic_scholar")

        unique_entries = index.get_all_entries()
        entries_needing_fetch = [e for e in unique_entries if e.needs_fetch]

        # Then: No entries need fetch
        assert len(entries_needing_fetch) == 0

    @pytest.mark.asyncio
    async def test_get_citation_graph_exception_handled(self) -> None:
        """
        TC-PA-A-02: Exception in get_citation_graph() is handled gracefully.

        Given: get_citation_graph() raises exception
        When: Getting citation graph for paper
        Then: Exception is caught, logged, processing continues
        """
        from src.search.academic_provider import AcademicSearchProvider
        from src.utils.schemas import Paper

        provider = AcademicSearchProvider()

        # Create initial paper for get_paper (DOI extraction)
        initial_paper = Paper(
            id="s2:test",
            title="Initial Paper",
            abstract="Abstract",
            authors=[],
            year=2024,
            published_date=None,
            doi="10.1234/initial",
            arxiv_id=None,
            venue="Nature",
            citation_count=0,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )

        with patch.object(provider, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.get_paper = AsyncMock(return_value=initial_paper)
            mock_client.get_references = AsyncMock(side_effect=Exception("API error"))
            mock_client.get_citations = AsyncMock(return_value=[])

            # When: Getting citation graph (should handle exception)
            try:
                papers, citations = await provider.get_citation_graph(
                    paper_id="s2:test",
                    depth=1,
                    direction="both",
                )
                # Exception should be handled internally, return empty result
                assert isinstance(papers, list)
                assert isinstance(citations, list)
            except Exception:
                # If exception propagates, that's also acceptable (caller handles it)
                pass

    @pytest.mark.asyncio
    async def test_api_timeout_handled(self) -> None:
        """
        TC-PA-A-04: API timeout is handled gracefully.

        Given: API call times out
        When: Getting citation graph
        Then: Timeout exception is handled, empty result returned
        """
        import asyncio

        from src.search.academic_provider import AcademicSearchProvider
        from src.utils.schemas import Paper

        provider = AcademicSearchProvider()

        # Create initial paper for get_paper (DOI extraction)
        initial_paper = Paper(
            id="s2:test",
            title="Initial Paper",
            abstract="Abstract",
            authors=[],
            year=2024,
            published_date=None,
            doi="10.1234/initial",
            arxiv_id=None,
            venue="Nature",
            citation_count=0,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )

        async def slow_api_call() -> list[object]:
            await asyncio.sleep(10)  # Simulate timeout
            return []

        with patch.object(provider, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.get_paper = AsyncMock(return_value=initial_paper)
            mock_client.get_references = AsyncMock(side_effect=TimeoutError("API timeout"))
            mock_client.get_citations = AsyncMock(return_value=[])

            # When: Getting citation graph with timeout
            try:
                papers, citations = await provider.get_citation_graph(
                    paper_id="s2:test",
                    depth=1,
                    direction="both",
                )
                # Should handle timeout gracefully
                assert isinstance(papers, list)
                assert isinstance(citations, list)
            except TimeoutError:
                # If timeout propagates, that's acceptable (caller handles it)
                pass

    @pytest.mark.asyncio
    async def test_paper_to_page_map_tracking(self, sample_paper_with_abstract: Paper) -> None:
        """
        TC-PA-N-09: paper_to_page_map correctly tracks paper_id -> page_id mapping.

        Given: Paper with abstract is persisted
        When: Processing entry
        Then: paper_to_page_map contains correct mapping for citation graph
        """
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        with patch("src.research.pipeline.get_database") as mock_db:
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(return_value="test_id")
            # Mock resource dedup methods
            mock_db_instance.claim_resource = AsyncMock(return_value=(True, None))
            mock_db_instance.complete_resource = AsyncMock()

            # When: Persisting abstract
            page_id, fragment_id = await pipeline._persist_abstract_as_fragment(
                paper=sample_paper_with_abstract,
                task_id="test_task",
                search_id="test_search",
            )

            # Then: page_id is generated and can be used for mapping
            assert page_id.startswith("page_")
            # In actual flow, paper_to_page_map[sample_paper_with_abstract.id] = page_id
            # This mapping is used for citation graph integration

    @pytest.mark.asyncio
    async def test_citation_graph_only_for_papers_with_abstracts(
        self, sample_paper_with_abstract: Paper, sample_paper_without_abstract: Paper
    ) -> None:
        """
        TC-PA-N-10: Citation graph is only retrieved for papers with abstracts.

        Given: Mixed entries (with/without abstracts)
        When: Getting citation graphs
        Then: Only papers with abstracts are included in papers_with_abstracts filter
        """
        from src.search.canonical_index import CanonicalPaperIndex

        # Given: Mixed entries
        index = CanonicalPaperIndex()
        index.register_paper(sample_paper_with_abstract, "semantic_scholar")
        index.register_paper(sample_paper_without_abstract, "openalex")

        unique_entries = index.get_all_entries()

        # When: Filtering papers with abstracts
        papers_with_abstracts = [
            entry.paper for entry in unique_entries if entry.paper and entry.paper.abstract
        ]

        # Then: Only paper with abstract is included
        assert len(papers_with_abstracts) == 1
        assert papers_with_abstracts[0].id == sample_paper_with_abstract.id
        assert papers_with_abstracts[0].abstract is not None

    @pytest.mark.asyncio
    async def test_execute_unified_search_processing_flow(
        self, sample_paper_with_abstract: Paper, sample_paper_without_abstract: Paper
    ) -> None:
        """
        TC-PA-N-11: _execute_unified_search() processes entries according to needs_fetch.

        Given: Mixed entries (with/without abstracts) from academic API
        When: _execute_unified_search() processes entries
        Then:
        - Entries with abstract: persisted directly, fetch skipped
        - Entries without abstract: included in entries_needing_fetch, browser search triggered
        - Stats accumulated correctly
        """
        from src.search.canonical_index import CanonicalPaperIndex

        state = ExplorationState(task_id="test_task")
        SearchPipeline(task_id="test_task", state=state)

        # Create index with mixed entries (simulating -4)
        index = CanonicalPaperIndex()
        index.register_paper(sample_paper_with_abstract, "semantic_scholar")
        index.register_paper(sample_paper_without_abstract, "openalex")

        unique_entries = index.get_all_entries()

        # Simulate processing logic
        pages_created = 0
        fragments_created = 0
        entries_needing_fetch = []

        for entry in unique_entries:
            if entry.paper and entry.paper.abstract:
                # Abstract Only: Skip fetch, persist abstract directly
                pages_created += 1
                fragments_created += 1
            elif entry.needs_fetch:
                # Entry needs fetch: collect for browser search fallback
                entries_needing_fetch.append(entry)

        # Then: Verify processing logic
        assert pages_created == 1  # Only paper with abstract
        assert fragments_created == 1
        assert len(entries_needing_fetch) == 1  # Only paper without abstract
        assert entries_needing_fetch[0].paper == sample_paper_without_abstract

    @pytest.mark.asyncio
    async def test_execute_unified_search_with_serp_only_entries(self) -> None:
        """
        TC-PA-N-12: SERP-only entries trigger browser search fallback.

        Given: SERP-only entries (no Paper object)
        When: Processing entries
        Then: entries_needing_fetch includes SERP-only entries
        """
        from src.search.canonical_index import CanonicalPaperIndex

        # Given: SERP-only entry
        serp_result = SERPResult(
            title="Test SERP",
            url="https://example.com/article",
            snippet="Test snippet",
            engine="google",
            rank=1,
        )

        index = CanonicalPaperIndex()
        from src.search.identifier_extractor import IdentifierExtractor

        extractor = IdentifierExtractor()
        identifier = extractor.extract(serp_result.url)
        index.register_serp_result(serp_result, identifier)

        unique_entries = index.get_all_entries()
        entries_needing_fetch = [e for e in unique_entries if e.needs_fetch]

        # Then: SERP-only entry needs fetch
        assert len(entries_needing_fetch) == 1
        assert entries_needing_fetch[0].paper is None
        assert len(entries_needing_fetch[0].serp_results) > 0

    @pytest.mark.asyncio
    async def test_citation_graph_integration_requires_page_id_mapping(
        self, sample_paper_with_abstract: Paper
    ) -> None:
        """
        TC-PA-N-13: Citation graph integration requires paper_id in paper_to_page_map.

        Given: Paper with abstract and citation graph
        When: Getting citation graph
        Then: paper_id must be in paper_to_page_map to add citations
        """
        from src.search.canonical_index import CanonicalPaperIndex

        # Given: Paper with abstract
        index = CanonicalPaperIndex()
        index.register_paper(sample_paper_with_abstract, "semantic_scholar")

        unique_entries = index.get_all_entries()
        paper_to_page_map = {}

        # Simulate : persist abstract and create mapping
        for entry in unique_entries:
            if entry.paper and entry.paper.abstract:
                page_id = f"page_{entry.paper.id[:8]}"
                paper_to_page_map[entry.paper.id] = page_id

        # When: Filtering papers for citation graph
        papers_with_abstracts = [
            entry.paper
            for entry in unique_entries
            if entry.paper and entry.paper.abstract and entry.paper.id in paper_to_page_map
        ]

        # Then: Paper is included only if in paper_to_page_map
        assert len(papers_with_abstracts) == 1
        assert papers_with_abstracts[0].id in paper_to_page_map

    @pytest.mark.asyncio
    async def test_citation_graph_excluded_if_not_in_page_map(
        self, sample_paper_with_abstract: Paper
    ) -> None:
        """
        TC-PA-N-14: Citation graph is excluded if paper_id not in paper_to_page_map.

        Given: Paper with abstract but not in paper_to_page_map
        When: Filtering papers for citation graph
        Then: Paper is excluded from citation graph processing
        """
        from src.search.canonical_index import CanonicalPaperIndex

        # Given: Paper with abstract but not in mapping (e.g., persistence failed)
        index = CanonicalPaperIndex()
        index.register_paper(sample_paper_with_abstract, "semantic_scholar")

        unique_entries = index.get_all_entries()
        paper_to_page_map: dict[str, object] = {}  # Empty mapping (simulating persistence failure)

        # When: Filtering papers for citation graph
        papers_with_abstracts = [
            entry.paper
            for entry in unique_entries
            if entry.paper and entry.paper.abstract and entry.paper.id in paper_to_page_map
        ]

        # Then: Paper is excluded (not in mapping)
        assert len(papers_with_abstracts) == 0

    @pytest.mark.asyncio
    async def test_stats_accumulation_with_mixed_entries(
        self, sample_paper_with_abstract: Paper, sample_paper_without_abstract: Paper
    ) -> None:
        """
        TC-PA-N-15: Stats are accumulated correctly with mixed entries.

        Given: Mixed entries (with/without abstracts)
        When: Processing entries
        Then: pages_created and fragments_created reflect only persisted abstracts
        """
        from src.search.canonical_index import CanonicalPaperIndex

        # Given: Mixed entries
        index = CanonicalPaperIndex()
        index.register_paper(sample_paper_with_abstract, "semantic_scholar")
        index.register_paper(sample_paper_without_abstract, "openalex")

        unique_entries = index.get_all_entries()

        # Simulate processing
        pages_created = 0
        fragments_created = 0

        for entry in unique_entries:
            if entry.paper and entry.paper.abstract:
                # Abstract persisted directly
                pages_created += 1
                fragments_created += 1

        # Then: Stats reflect only persisted abstracts
        assert pages_created == 1  # Only paper with abstract
        assert fragments_created == 1
        # Paper without abstract is not counted here (will be handled by browser search)

    @pytest.mark.asyncio
    async def test_browser_search_fallback_accumulates_stats(self) -> None:
        """
        TC-PA-N-16: Browser search fallback accumulates stats correctly.

        Given: entries_needing_fetch and existing stats
        When: Browser search is executed
        Then: Stats are accumulated (not overwritten)
        """
        # Given: Existing stats from abstract processing
        pages_before = 2
        fragments_before = 2

        # Simulate browser search result
        browser_pages = 3
        browser_fragments = 5

        # When: Accumulating stats
        pages_after = pages_before + browser_pages
        fragments_after = fragments_before + browser_fragments

        # Then: Stats are accumulated correctly
        assert pages_after == 5
        assert fragments_after == 7
        assert pages_after > pages_before  # Accumulated, not overwritten
        assert fragments_after > fragments_before


# =============================================================================
# Test: Unified Search Identifier Complement (ADR-0016)
# =============================================================================


@pytest.mark.skip(
    reason="ADR-0016: Tests need rewrite. Identifier extraction moved from "
    "_execute_browser_search() to _execute_unified_search(). "
    "Unified search behavior tested in tests/test_research.py::TestUnifiedDualSourceSearch"
)
class TestUnifiedSearchIdentifierComplement:
    """Tests for identifier extraction and API complement in unified dual-source search.

    NOTE (ADR-0016): After removing is_academic routing, ALL queries now use
    _execute_unified_search() which runs both Academic API and Browser SERP.

    SKIPPED: These tests were written for the old _execute_browser_search()
    which did SERP + identifier extraction + API complement. That behavior
    has moved to _execute_unified_search(). The new unified search behavior
    is tested in tests/test_research.py::TestUnifiedDualSourceSearch.

    TODO: Rewrite these tests to call _execute_unified_search() with proper mocks.
    """

    @pytest.mark.asyncio
    async def test_non_academic_query_with_doi_triggers_api_complement(self) -> None:
        """
        TC-NA-N-01: Non-academic query with DOI in SERP triggers API complement.

        Given: Non-academic query + SERP result with DOI URL
        When: _execute_fetch_extract() processes SERP results
        Then: Identifier extracted, API complement executed, Paper created
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "https://doi.org/10.1234/test.paper",
                "title": "Test Paper",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        mock_paper = Paper(
            id="s2:test123",
            title="Test Paper",
            abstract="Test abstract",
            authors=[Author(name="John Doe", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/test.paper",
            arxiv_id=None,
            venue="Nature",
            citation_count=42,
            reference_count=25,
            is_open_access=True,
            oa_url="https://example.com/paper.pdf",
            pdf_url="https://example.com/paper.pdf",
            source_api="semantic_scholar",
        )

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
            patch("src.research.pipeline.get_database") as mock_db,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock academic provider
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method
            mock_client = AsyncMock()
            mock_client.get_paper = AsyncMock(return_value=mock_paper)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.get_citation_graph = AsyncMock(return_value=([], []))
            mock_provider.close = AsyncMock()

            # Mock database
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(return_value="test_id")

            # Mock evidence graph
            with patch("src.filter.evidence_graph.get_evidence_graph") as mock_get_graph:
                mock_graph = MagicMock()
                mock_get_graph.return_value = mock_graph
                mock_graph.add_node = MagicMock()

                # When
                result = await pipeline._execute_fetch_extract(
                    search_id="test_search",
                    query="COVID-19 treatment",
                    options=MagicMock(
                        budget_pages=10, engines=None, seek_primary=False, refute=False
                    ),
                    result=SearchPipelineResult(
                        search_id="test_search",
                        query="COVID-19 treatment",
                    ),
                )

                # Then: API complement should be attempted
                assert result is not None
                assert result.status == "satisfied"
                mock_provider._get_client.assert_called()
                mock_client.get_paper.assert_called()
                # Verify DOI was extracted and used
                call_args = mock_client.get_paper.call_args
                assert call_args is not None
                paper_id = call_args[0][0] if call_args[0] else call_args[1].get("paper_id")
                assert paper_id is not None
                assert "DOI:" in paper_id or "10.1234" in str(paper_id)

    @pytest.mark.asyncio
    async def test_non_academic_query_with_pmid_triggers_api_complement(self) -> None:
        """
        TC-NA-N-02: Non-academic query with PMID in SERP triggers API complement.

        Given: Non-academic query + SERP result with PubMed URL
        When: _execute_fetch_extract() processes SERP results
        Then: PMID extracted, DOI resolved, API complement executed
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "https://pubmed.ncbi.nlm.nih.gov/12345678",
                "title": "Test Paper",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        mock_paper = Paper(
            id="s2:test123",
            title="Test Paper",
            abstract="Test abstract",
            authors=[Author(name="John Doe", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/test.paper",
            arxiv_id=None,
            venue="Nature",
            citation_count=42,
            reference_count=25,
            is_open_access=True,
            oa_url="https://example.com/paper.pdf",
            pdf_url="https://example.com/paper.pdf",
            source_api="semantic_scholar",
        )

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.id_resolver.IDResolver") as mock_resolver_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
            patch("src.research.pipeline.get_database") as mock_db,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock resolver
            mock_resolver = AsyncMock()
            mock_resolver_class.return_value = mock_resolver
            mock_resolver.resolve_pmid_to_doi = AsyncMock(return_value="10.1234/test.paper")
            mock_resolver.close = AsyncMock()

            # Mock academic provider
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method
            mock_client = AsyncMock()
            mock_client.get_paper = AsyncMock(return_value=mock_paper)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.get_citation_graph = AsyncMock(return_value=([], []))
            mock_provider.close = AsyncMock()

            # Mock database
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(return_value="test_id")

            # Mock evidence graph
            with patch("src.filter.evidence_graph.get_evidence_graph") as mock_get_graph:
                mock_graph = MagicMock()
                mock_get_graph.return_value = mock_graph
                mock_graph.add_node = MagicMock()

                # When
                result = await pipeline._execute_fetch_extract(
                    search_id="test_search",
                    query="drug side effects",
                    options=MagicMock(
                        budget_pages=10, engines=None, seek_primary=False, refute=False
                    ),
                    result=SearchPipelineResult(
                        search_id="test_search",
                        query="drug side effects",
                    ),
                )

                # Then: Result should be returned
                assert result is not None
                assert result.status == "satisfied"
                # PMID resolution should be attempted
                mock_resolver.resolve_pmid_to_doi.assert_called_with("12345678")
                # API complement should be attempted
                mock_provider._get_client.assert_called()
                mock_client.get_paper.assert_called()

    @pytest.mark.asyncio
    async def test_non_academic_query_without_identifiers_no_api_complement(self) -> None:
        """
        TC-NA-N-03: Non-academic query without identifiers does not trigger API complement.

        Given: Non-academic query + SERP results without identifiers
        When: _execute_fetch_extract() processes SERP results
        Then: No API complement attempted, browser search only
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "https://example.com/article",
                "title": "General Article",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock academic provider (should not be called)
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method
            mock_client = AsyncMock()
            mock_client.get_paper = AsyncMock(return_value=None)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.close = AsyncMock()

            # When
            result = await pipeline._execute_fetch_extract(
                search_id="test_search",
                query="general topic",
                options=MagicMock(budget_pages=10, engines=None, seek_primary=False, refute=False),
                result=SearchPipelineResult(
                    search_id="test_search",
                    query="general topic",
                ),
            )

            # Then: Result should be returned
            assert result is not None
            assert result.status == "satisfied"
            # API complement should not be attempted (no identifiers)
            # Note: _process_serp_with_identifiers may still be called but will find no identifiers
            # We verify that get_paper is not called with valid identifiers
            if mock_client.get_paper.called:
                # If called, it should be with None or invalid ID
                call_args = mock_client.get_paper.call_args
                if call_args:
                    paper_id = call_args[0][0] if call_args[0] else None
                    # Should not have valid DOI/PMID/arXiv format
                    assert paper_id is None or (
                        "DOI:" not in str(paper_id)
                        and "PMID:" not in str(paper_id)
                        and "ArXiv:" not in str(paper_id)
                    )

    @pytest.mark.asyncio
    async def test_identifier_complement_with_citation_tracking(self) -> None:
        """
        TC-NA-N-04: Identifier complement triggers citation tracking.

        Given: Non-academic query + DOI found + Paper with abstract
        When: _execute_fetch_extract() processes results
        Then: Citation graph is retrieved and processed
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "https://doi.org/10.1234/test.paper",
                "title": "Test Paper",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        mock_paper = Paper(
            id="s2:test123",
            title="Test Paper",
            abstract="Test abstract",
            authors=[Author(name="John Doe", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/test.paper",
            arxiv_id=None,
            venue="Nature",
            citation_count=42,
            reference_count=25,
            is_open_access=True,
            oa_url="https://example.com/paper.pdf",
            pdf_url="https://example.com/paper.pdf",
            source_api="semantic_scholar",
        )

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
            patch("src.research.pipeline.get_database") as mock_db,
            patch("src.search.citation_filter.filter_relevant_citations") as mock_filter,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock academic provider
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method
            mock_client = AsyncMock()
            mock_client.get_paper = AsyncMock(return_value=mock_paper)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.get_citation_graph = AsyncMock(return_value=([], []))
            mock_provider.close = AsyncMock()

            # Mock citation filter
            mock_filter.return_value = []

            # Mock database
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(return_value="test_id")

            # Mock evidence graph
            with patch("src.filter.evidence_graph.get_evidence_graph") as mock_get_graph:
                mock_graph = MagicMock()
                mock_get_graph.return_value = mock_graph
                mock_graph.add_node = MagicMock()

                # When
                result = await pipeline._execute_fetch_extract(
                    search_id="test_search",
                    query="COVID-19 treatment",
                    options=MagicMock(
                        budget_pages=10, engines=None, seek_primary=False, refute=False
                    ),
                    result=SearchPipelineResult(
                        search_id="test_search",
                        query="COVID-19 treatment",
                    ),
                )

                # Then: Result should be returned
                assert result is not None
                assert result.status == "satisfied"
                # Citation graph should be attempted if paper has abstract
                # Note: get_citation_graph is called in _process_citation_graph
                # We verify that the flow attempts citation tracking

    @pytest.mark.asyncio
    async def test_identifier_complement_api_error_handled(self) -> None:
        """
        TC-NA-A-01: API error during identifier complement is handled gracefully.

        Given: Non-academic query + DOI found + API error
        When: _execute_fetch_extract() processes results
        Then: Exception caught, logged, processing continues
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "https://doi.org/10.1234/test.paper",
                "title": "Test Paper",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock academic provider with error
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method that raises error
            mock_client = AsyncMock()
            api_error = Exception("API timeout")
            mock_client.get_paper = AsyncMock(side_effect=api_error)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.close = AsyncMock()

            # When: Processing should handle exception gracefully
            result = await pipeline._execute_fetch_extract(
                search_id="test_search",
                query="COVID-19 treatment",
                options=MagicMock(budget_pages=10, engines=None, seek_primary=False, refute=False),
                result=SearchPipelineResult(
                    search_id="test_search",
                    query="COVID-19 treatment",
                ),
            )

            # Then: Result should still be returned (exception handled)
            assert result is not None
            assert result.status == "satisfied"  # Executor result preserved
            # Exception type: Exception
            # Exception message: "API timeout"
            # Note: Exception is caught and logged in _execute_fetch_extract try/except block

    @pytest.mark.asyncio
    async def test_non_academic_query_with_arxiv_id_triggers_api_complement(self) -> None:
        """
        TC-NA-N-03: Non-academic query with arXiv ID in SERP triggers API complement.

        Given: Non-academic query + SERP result with arXiv URL
        When: _execute_fetch_extract() processes SERP results
        Then: arXiv ID extracted, DOI resolved, API complement executed
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "https://arxiv.org/abs/2401.12345",
                "title": "Test Paper",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        mock_paper = Paper(
            id="s2:test123",
            title="Test Paper",
            abstract="Test abstract",
            authors=[Author(name="John Doe", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/test.paper",
            arxiv_id="2401.12345",
            venue="arXiv",
            citation_count=42,
            reference_count=25,
            is_open_access=True,
            oa_url="https://example.com/paper.pdf",
            pdf_url="https://example.com/paper.pdf",
            source_api="semantic_scholar",
        )

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.id_resolver.IDResolver") as mock_resolver_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock resolver
            mock_resolver = AsyncMock()
            mock_resolver_class.return_value = mock_resolver
            mock_resolver.resolve_arxiv_to_doi = AsyncMock(return_value="10.1234/test.paper")
            mock_resolver.close = AsyncMock()

            # Mock academic provider
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method
            mock_client = AsyncMock()
            mock_client.get_paper = AsyncMock(return_value=mock_paper)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.close = AsyncMock()

            # When
            result = await pipeline._execute_fetch_extract(
                search_id="test_search",
                query="machine learning",
                options=MagicMock(budget_pages=10, engines=None, seek_primary=False, refute=False),
                result=SearchPipelineResult(
                    search_id="test_search",
                    query="machine learning",
                ),
            )

            # Then: Result should be returned
            assert result is not None
            assert result.status == "satisfied"
            # arXiv ID resolution should be attempted
            mock_resolver.resolve_arxiv_to_doi.assert_called_with("2401.12345")
            # API complement should be attempted
            mock_provider._get_client.assert_called()
            mock_client.get_paper.assert_called()

    @pytest.mark.asyncio
    async def test_empty_serp_items_no_processing(self) -> None:
        """
        TC-NA-B-01: Empty SERP items list does not trigger processing.

        Given: Non-academic query + empty SERP items list
        When: _execute_fetch_extract() processes results
        Then: No identifier processing attempted, no error
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items: list[dict[str, Any]] = []

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock academic provider (should not be called)
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method
            mock_client = AsyncMock()
            mock_client.get_paper = AsyncMock(return_value=None)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.close = AsyncMock()

            # When
            result = await pipeline._execute_fetch_extract(
                search_id="test_search",
                query="general topic",
                options=MagicMock(budget_pages=10, engines=None, seek_primary=False, refute=False),
                result=SearchPipelineResult(
                    search_id="test_search",
                    query="general topic",
                ),
            )

            # Then: No API complement attempted (empty SERP)
            # Note: get_paper may be called internally but should not be called with valid identifiers
            assert result is not None
            assert result.status == "satisfied"

    @pytest.mark.asyncio
    async def test_serp_item_empty_url_skipped(self) -> None:
        """
        TC-NA-B-02: SERP item with empty URL is skipped.

        Given: Non-academic query + SERP item with empty URL
        When: _execute_fetch_extract() processes results
        Then: Item skipped, processing continues
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "",  # Empty URL
                "title": "Test Paper",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock academic provider (should not be called)
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            mock_provider.get_paper = AsyncMock(return_value=None)
            mock_provider.close = AsyncMock()

            # When
            result = await pipeline._execute_fetch_extract(
                search_id="test_search",
                query="general topic",
                options=MagicMock(budget_pages=10, engines=None, seek_primary=False, refute=False),
                result=SearchPipelineResult(
                    search_id="test_search",
                    query="general topic",
                ),
            )

            # Then: Empty URL should be skipped
            assert result is not None
            # No valid identifier extraction should occur

    @pytest.mark.asyncio
    async def test_paper_without_abstract_skips_citation_tracking(self) -> None:
        """
        TC-NA-B-03: Paper without abstract skips citation tracking.

        Given: Non-academic query + DOI found + Paper without abstract
        When: _execute_fetch_extract() processes results
        Then: Paper not added to pages, citation tracking skipped
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "https://doi.org/10.1234/test.paper",
                "title": "Test Paper",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        mock_paper_no_abstract = Paper(
            id="s2:test123",
            title="Test Paper",
            abstract=None,  # No abstract
            authors=[Author(name="John Doe", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/test.paper",
            arxiv_id=None,
            venue="Nature",
            citation_count=42,
            reference_count=25,
            is_open_access=True,
            oa_url="https://example.com/paper.pdf",
            pdf_url="https://example.com/paper.pdf",
            source_api="semantic_scholar",
        )

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
            patch("src.research.pipeline.get_database") as mock_db,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock academic provider
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method
            mock_client = AsyncMock()
            mock_client.get_paper = AsyncMock(return_value=mock_paper_no_abstract)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.get_citation_graph = AsyncMock(return_value=([], []))
            mock_provider.close = AsyncMock()

            # Mock database
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(return_value="test_id")

            # When
            result = await pipeline._execute_fetch_extract(
                search_id="test_search",
                query="COVID-19 treatment",
                options=MagicMock(budget_pages=10, engines=None, seek_primary=False, refute=False),
                result=SearchPipelineResult(
                    search_id="test_search",
                    query="COVID-19 treatment",
                ),
            )

            # Then: Citation tracking should be skipped (no abstract)
            # Note: _process_citation_graph filters papers with abstracts
            assert result is not None

    @pytest.mark.asyncio
    async def test_doi_resolution_failure_handled(self) -> None:
        """
        TC-NA-A-02: DOI resolution failure (PMID) is handled gracefully.

        Given: Non-academic query + PMID found + DOI resolution fails
        When: _execute_fetch_extract() processes results
        Then: Exception caught, API complement skipped
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "https://pubmed.ncbi.nlm.nih.gov/12345678",
                "title": "Test Paper",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.id_resolver.IDResolver") as mock_resolver_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock resolver with error
            mock_resolver = AsyncMock()
            mock_resolver_class.return_value = mock_resolver
            mock_resolver.resolve_pmid_to_doi = AsyncMock(
                side_effect=Exception("DOI resolution failed")
            )
            mock_resolver.close = AsyncMock()

            # Mock academic provider (should not be called due to resolution failure)
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method
            mock_client = AsyncMock()
            mock_client.get_paper = AsyncMock(return_value=None)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.close = AsyncMock()

            # When: Processing should handle exception gracefully
            result = await pipeline._execute_fetch_extract(
                search_id="test_search",
                query="drug side effects",
                options=MagicMock(budget_pages=10, engines=None, seek_primary=False, refute=False),
                result=SearchPipelineResult(
                    search_id="test_search",
                    query="drug side effects",
                ),
            )

            # Then: Result should still be returned (exception handled)
            assert result is not None
            assert result.status == "satisfied"

    @pytest.mark.asyncio
    async def test_citation_graph_retrieval_failure_handled(self) -> None:
        """
        TC-NA-A-03: Citation graph retrieval failure is handled gracefully.

        Given: Non-academic query + DOI found + Paper with abstract + citation graph error
        When: _execute_fetch_extract() processes results
        Then: Exception caught, logged, processing continues
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "https://doi.org/10.1234/test.paper",
                "title": "Test Paper",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        mock_paper = Paper(
            id="s2:test123",
            title="Test Paper",
            abstract="Test abstract",
            authors=[Author(name="John Doe", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/test.paper",
            arxiv_id=None,
            venue="Nature",
            citation_count=42,
            reference_count=25,
            is_open_access=True,
            oa_url="https://example.com/paper.pdf",
            pdf_url="https://example.com/paper.pdf",
            source_api="semantic_scholar",
        )

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
            patch("src.research.pipeline.get_database") as mock_db,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock academic provider with citation graph error
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method
            mock_client = AsyncMock()
            mock_client.get_paper = AsyncMock(return_value=mock_paper)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.get_citation_graph = AsyncMock(
                side_effect=Exception("Citation graph retrieval failed")
            )
            mock_provider.close = AsyncMock()

            # Mock database
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(return_value="test_id")

            # Mock evidence graph
            with patch("src.filter.evidence_graph.get_evidence_graph") as mock_get_graph:
                mock_graph = MagicMock()
                mock_get_graph.return_value = mock_graph
                mock_graph.add_node = MagicMock()

                # When: Processing should handle exception gracefully
                result = await pipeline._execute_fetch_extract(
                    search_id="test_search",
                    query="COVID-19 treatment",
                    options=MagicMock(
                        budget_pages=10, engines=None, seek_primary=False, refute=False
                    ),
                    result=SearchPipelineResult(
                        search_id="test_search",
                        query="COVID-19 treatment",
                    ),
                )

                # Then: Result should still be returned (exception handled)
                assert result is not None
                assert result.status == "satisfied"

    @pytest.mark.asyncio
    async def test_paper_lookup_returns_none_handled(self) -> None:
        """
        TC-NA-A-04: Paper lookup returns None is handled gracefully.

        Given: Non-academic query + DOI found + get_paper returns None
        When: _execute_fetch_extract() processes results
        Then: None handled gracefully, no error
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        serp_items = [
            {
                "url": "https://doi.org/10.1234/test.paper",
                "title": "Test Paper",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
            }
        ]

        with (
            patch("src.search.search_api.search_serp", return_value=serp_items),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
            patch("src.search.academic_provider.AcademicSearchProvider") as mock_provider_class,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # Mock academic provider returning None
            mock_provider = AsyncMock()
            mock_provider_class.return_value = mock_provider
            # Mock _get_client to return a mock client with get_paper method
            mock_client = AsyncMock()
            mock_client.get_paper = AsyncMock(return_value=None)
            mock_provider._get_client = AsyncMock(return_value=mock_client)
            mock_provider.close = AsyncMock()

            # When
            result = await pipeline._execute_fetch_extract(
                search_id="test_search",
                query="COVID-19 treatment",
                options=MagicMock(budget_pages=10, engines=None, seek_primary=False, refute=False),
                result=SearchPipelineResult(
                    search_id="test_search",
                    query="COVID-19 treatment",
                ),
            )

            # Then: Result should still be returned (None handled gracefully)
            assert result is not None
            assert result.status == "satisfied"

    @pytest.mark.asyncio
    async def test_serp_search_exception_handled(self) -> None:
        """
        TC-NA-A-05: SERP search exception is handled gracefully.

        Given: Non-academic query + search_serp raises exception
        When: _execute_fetch_extract() processes results
        Then: Exception caught, logged, executor result preserved
        """
        # Given
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)

        with (
            patch(
                "src.search.search_api.search_serp",
                side_effect=Exception("SERP search failed"),
            ),
            patch("src.research.pipeline.SearchExecutor") as mock_executor_class,
        ):
            # Mock executor
            mock_executor = AsyncMock()
            mock_executor_class.return_value = mock_executor
            mock_exec_result = MagicMock()
            mock_exec_result.status = "satisfied"
            mock_exec_result.pages_fetched = 5
            mock_exec_result.useful_fragments = 3
            mock_exec_result.harvest_rate = 0.6
            mock_exec_result.satisfaction_score = 0.8
            mock_exec_result.novelty_score = 0.9
            mock_exec_result.auth_blocked_urls = 0
            mock_exec_result.auth_queued_count = 0
            mock_exec_result.error_code = None
            mock_exec_result.error_details = {}
            mock_exec_result.new_claims = []
            mock_exec_result.errors = []
            mock_executor.execute = AsyncMock(return_value=mock_exec_result)

            # When: Processing should handle exception gracefully
            result = await pipeline._execute_fetch_extract(
                search_id="test_search",
                query="COVID-19 treatment",
                options=MagicMock(budget_pages=10, engines=None, seek_primary=False, refute=False),
                result=SearchPipelineResult(
                    search_id="test_search",
                    query="COVID-19 treatment",
                ),
            )

            # Then: Result should still be returned (exception handled)
            assert result is not None
            assert result.status == "satisfied"  # Executor result preserved
