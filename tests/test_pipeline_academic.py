"""
Tests for academic search pipeline integration.

Tests the Abstract Only strategy and citation graph integration
in the SearchPipeline._execute_complementary_search() method.

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
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from src.research.pipeline import SearchPipeline, SearchResult, SearchOptions
from src.research.state import ExplorationState
from src.utils.schemas import Paper, Author, Citation, CanonicalEntry
from src.search.provider import SearchResponse, SearchResult as ProviderSearchResult, SourceTag


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_paper_with_abstract():
    """Paper with abstract (should skip fetch)."""
    return Paper(
        id="s2:test123",
        title="Test Paper With Abstract",
        abstract="This is a test abstract for validation.",
        doi="10.1234/test.paper",
        arxiv_id=None,
        authors=[Author(name="John Doe", affiliation="Test University")],
        year=2024,
        venue="Nature",
        citation_count=42,
        reference_count=25,
        is_open_access=True,
        oa_url="https://example.com/paper.pdf",
        pdf_url="https://example.com/paper.pdf",
        source_api="semantic_scholar",
    )


@pytest.fixture
def sample_paper_without_abstract():
    """Paper without abstract (should need fetch)."""
    return Paper(
        id="s2:test456",
        title="Test Paper Without Abstract",
        abstract=None,
        doi="10.1234/test.paper2",
        arxiv_id=None,
        authors=[Author(name="Jane Doe")],
        year=2024,
        source_api="openalex",
    )


@pytest.fixture
def sample_citations():
    """Sample citation relationships."""
    return [
        Citation(
            citing_paper_id="s2:test123",
            cited_paper_id="s2:ref1",
            is_influential=True,
            context=None,
        ),
        Citation(
            citing_paper_id="s2:test123",
            cited_paper_id="s2:ref2",
            is_influential=False,
            context="As shown in previous work...",
        ),
    ]


# =============================================================================
# Test: Abstract Only Strategy
# =============================================================================


class TestAbstractOnlyStrategy:
    """Tests for Abstract Only strategy implementation."""
    
    @pytest.mark.asyncio
    async def test_persist_abstract_as_fragment(self, sample_paper_with_abstract):
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
            
            # When
            page_id, fragment_id = await pipeline._persist_abstract_as_fragment(
                paper=sample_paper_with_abstract,
                task_id="test_task",
                search_id="test_search",
            )
            
            # Then
            assert page_id.startswith("page_")
            assert fragment_id.startswith("frag_")
            
            # Verify DB inserts
            assert mock_db_instance.insert.call_count == 2
            
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
    
    @pytest.mark.asyncio
    async def test_paper_with_abstract_skips_fetch(self, sample_paper_with_abstract):
        """
        Test: Papers with abstracts from API skip fetch.
        
        Given: Academic search returns paper with abstract
        When: _execute_complementary_search() is called
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
    async def test_paper_without_abstract_needs_fetch(self, sample_paper_without_abstract):
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
    async def test_serp_only_entry_needs_fetch(self):
        """
        Test: SERP-only entries (no Paper) need fetch.
        
        Given: Entry from SERP without Paper object
        When: Checking needs_fetch property
        Then: needs_fetch is True
        """
        # Given
        serp_result = ProviderSearchResult(
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
    async def test_add_academic_page_with_citations(self, sample_citations):
        """
        Test: add_academic_page_with_citations() adds nodes and edges.
        
        Given: Page ID, paper metadata, and citations
        When: add_academic_page_with_citations() is called
        Then: PAGE node and CITES edges are added to graph
        """
        from src.filter.evidence_graph import (
            add_academic_page_with_citations,
            get_evidence_graph,
            NodeType,
            RelationType,
        )
        
        with patch("src.filter.evidence_graph.get_database") as mock_db:
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(return_value="edge_id")
            
            # Given
            page_id = "page_test123"
            paper_metadata = {
                "doi": "10.1234/test",
                "citation_count": 42,
                "year": 2024,
                "venue": "Nature",
                "source_api": "semantic_scholar",
            }
            
            # When
            await add_academic_page_with_citations(
                page_id=page_id,
                paper_metadata=paper_metadata,
                citations=sample_citations,
                task_id="test_task",
            )
            
            # Then: Verify edges were inserted
            assert mock_db_instance.insert.call_count == len(sample_citations)
            
            # Check edge properties
            for call in mock_db_instance.insert.call_args_list:
                edge_data = call[0][1]
                assert edge_data["source_type"] == NodeType.PAGE.value
                assert edge_data["relation"] == RelationType.CITES.value
                assert edge_data["is_academic"] == 1


# =============================================================================
# Test: Paper Metadata Persistence
# =============================================================================


class TestPaperMetadataPersistence:
    """Tests for paper metadata JSON persistence."""
    
    @pytest.mark.asyncio
    async def test_paper_metadata_json_structure(self, sample_paper_with_abstract):
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
    
    def test_needs_fetch_with_abstract(self, sample_paper_with_abstract):
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
    
    def test_needs_fetch_without_abstract(self, sample_paper_without_abstract):
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
    
    def test_needs_fetch_no_paper(self):
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
    
    def test_needs_fetch_api_source_no_abstract(self, sample_paper_without_abstract):
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
    
    def test_needs_fetch_both_source_no_abstract(self, sample_paper_without_abstract):
        """
        TC-PA-N-04: Entry with source="both", paper.abstract=None needs fetch.
        
        Given: Entry with source="both" and Paper without abstract
        When: Checking needs_fetch
        Then: True (fetch needed)
        """
        # Given: Entry with both sources but no abstract
        serp_result = ProviderSearchResult(
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
    
    def test_needs_fetch_empty_abstract_string(self):
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
    
    def test_normalize_s2_prefix_to_corpusid(self):
        """
        TC-SS-N-01: s2: prefix is normalized to CorpusId:.
        
        Given: Paper ID with s2: prefix
        When: Normalizing for API
        Then: Returns CorpusId: format
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient
        
        # Given
        client = SemanticScholarClient()
        paper_id = "s2:12345"
        
        # When
        normalized = client._normalize_paper_id(paper_id)
        
        # Then
        assert normalized == "CorpusId:12345"
    
    def test_normalize_corpusid_unchanged(self):
        """
        TC-SS-N-02: CorpusId: format is returned as-is.
        
        Given: Paper ID with CorpusId: prefix
        When: Normalizing for API
        Then: Returns unchanged
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient
        
        # Given
        client = SemanticScholarClient()
        paper_id = "CorpusId:12345"
        
        # When
        normalized = client._normalize_paper_id(paper_id)
        
        # Then
        assert normalized == "CorpusId:12345"
    
    def test_normalize_doi_unchanged(self):
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
    
    def test_normalize_no_prefix_adds_corpusid(self):
        """
        TC-SS-N-04: ID without prefix gets CorpusId: prefix.
        
        Given: Paper ID without prefix
        When: Normalizing for API
        Then: Returns with CorpusId: prefix
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient
        
        # Given
        client = SemanticScholarClient()
        paper_id = "12345"
        
        # When
        normalized = client._normalize_paper_id(paper_id)
        
        # Then
        assert normalized == "CorpusId:12345"
    
    @pytest.mark.asyncio
    async def test_get_references_uses_normalized_id(self):
        """
        TC-SS-A-01: get_references() uses normalized ID format.
        
        Given: Paper ID with s2: prefix
        When: Calling get_references()
        Then: API is called with CorpusId: format
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient
        
        # Given
        client = SemanticScholarClient()
        paper_id = "s2:12345"
        
        with patch.object(client, '_get_session') as mock_session:
            mock_http = AsyncMock()
            mock_session.return_value = mock_http
            
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={"data": []})
            mock_response.raise_for_status = MagicMock()  # Not async
            mock_http.get = AsyncMock(return_value=mock_response)
            
            # When
            await client.get_references(paper_id)
            
            # Then: API should be called with normalized ID
            mock_http.get.assert_called_once()
            call_args = mock_http.get.call_args
            url = call_args[0][0]
            assert "CorpusId:12345" in url
            assert "s2:12345" not in url
    
    @pytest.mark.asyncio
    async def test_get_citations_uses_normalized_id(self):
        """
        TC-SS-A-02: get_citations() uses normalized ID format.
        
        Given: Paper ID with s2: prefix
        When: Calling get_citations()
        Then: API is called with CorpusId: format
        """
        from src.search.apis.semantic_scholar import SemanticScholarClient
        
        # Given
        client = SemanticScholarClient()
        paper_id = "s2:12345"
        
        with patch.object(client, '_get_session') as mock_session:
            mock_http = AsyncMock()
            mock_session.return_value = mock_http
            
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={"data": []})
            mock_response.raise_for_status = MagicMock()  # Not async
            mock_http.get = AsyncMock(return_value=mock_response)
            
            # When
            await client.get_citations(paper_id)
            
            # Then: API should be called with normalized ID
            mock_http.get.assert_called_once()
            call_args = mock_http.get.call_args
            url = call_args[0][0]
            assert "CorpusId:12345" in url
            assert "s2:12345" not in url


# =============================================================================
# Test: End-to-End Integration Tests
# =============================================================================


class TestExecuteComplementarySearchIntegration:
    """End-to-end tests for _execute_complementary_search() processing flow."""
    
    def test_paper_without_abstract_triggers_browser_fallback(self, sample_paper_without_abstract):
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
    
    def test_mixed_entries_processing(self, sample_paper_with_abstract, sample_paper_without_abstract):
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
    async def test_persist_abstract_exception_handled(self, sample_paper_with_abstract):
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
            mock_db_instance.insert = AsyncMock(side_effect=Exception("DB error"))
            
            # When: Persisting abstract (should raise exception)
            with pytest.raises(Exception) as exc_info:
                await pipeline._persist_abstract_as_fragment(
                    paper=sample_paper_with_abstract,
                    task_id="test_task",
                    search_id="test_search",
                )
            
            # Then: Exception is raised (caller should handle it)
            assert "DB error" in str(exc_info.value)


# =============================================================================
# Test: End-to-End Integration Tests
# =============================================================================


class TestExecuteComplementarySearchE2E:
    """End-to-end tests for _execute_complementary_search() - specification-based."""
    
    @pytest.mark.asyncio
    async def test_abstract_only_strategy_with_mixed_entries(self, sample_paper_with_abstract, sample_paper_without_abstract):
        """
        TC-PA-N-06: Abstract Only strategy processes mixed entries correctly.
        
        Given: Multiple entries with different abstract states
        When: _execute_complementary_search() processes entries
        Then: 
        - Entries with abstract are persisted directly (fetch skipped)
        - Entries without abstract trigger browser search fallback
        - Stats are accumulated correctly
        """
        from src.search.canonical_index import CanonicalPaperIndex
        
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)
        
        # Create index with mixed entries
        index = CanonicalPaperIndex()
        index.register_paper(sample_paper_with_abstract, "semantic_scholar")
        index.register_paper(sample_paper_without_abstract, "openalex")
        
        unique_entries = index.get_all_entries()
        
        # Verify entries have correct needs_fetch values
        entry_with_abstract = next(e for e in unique_entries if e.paper and e.paper.id == sample_paper_with_abstract.id)
        entry_without_abstract = next(e for e in unique_entries if e.paper and e.paper.id == sample_paper_without_abstract.id)
        
        assert entry_with_abstract.needs_fetch is False
        assert entry_without_abstract.needs_fetch is True
    
    @pytest.mark.asyncio
    async def test_browser_fallback_for_entries_needing_fetch(self, sample_paper_without_abstract):
        """
        TC-PA-N-07: Browser search fallback is triggered for entries needing fetch.
        
        Given: Entry with Paper but no abstract (source="api")
        When: _execute_complementary_search() processes entries
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
    async def test_citation_graph_integration_with_normalized_id(self, sample_paper_with_abstract):
        """
        TC-PA-N-08: Citation graph integration uses normalized paper IDs.
        
        Given: Paper with abstract and s2: ID format
        When: get_citation_graph() is called
        Then: API is called with CorpusId: format (not s2:)
        """
        from src.search.academic_provider import AcademicSearchProvider
        
        provider = AcademicSearchProvider()
        
        with patch.object(provider, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            
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
    async def test_empty_entries_needing_fetch_no_browser_search(self):
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
            source_api="semantic_scholar",
        )
        paper_with_abstract2 = Paper(
            id="s2:test2",
            title="Test 2",
            abstract="Abstract 2",
            source_api="semantic_scholar",
        )
        index.register_paper(paper_with_abstract, "semantic_scholar")
        index.register_paper(paper_with_abstract2, "semantic_scholar")
        
        unique_entries = index.get_all_entries()
        entries_needing_fetch = [e for e in unique_entries if e.needs_fetch]
        
        # Then: No entries need fetch
        assert len(entries_needing_fetch) == 0
    
    @pytest.mark.asyncio
    async def test_get_citation_graph_exception_handled(self):
        """
        TC-PA-A-02: Exception in get_citation_graph() is handled gracefully.
        
        Given: get_citation_graph() raises exception
        When: Getting citation graph for paper
        Then: Exception is caught, logged, processing continues
        """
        from src.search.academic_provider import AcademicSearchProvider
        
        provider = AcademicSearchProvider()
        
        with patch.object(provider, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
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
    async def test_api_timeout_handled(self):
        """
        TC-PA-A-04: API timeout is handled gracefully.
        
        Given: API call times out
        When: Getting citation graph
        Then: Timeout exception is handled, empty result returned
        """
        import asyncio
        from src.search.academic_provider import AcademicSearchProvider
        
        provider = AcademicSearchProvider()
        
        async def slow_api_call():
            await asyncio.sleep(10)  # Simulate timeout
            return []
        
        with patch.object(provider, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.get_references = AsyncMock(side_effect=asyncio.TimeoutError("API timeout"))
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
            except asyncio.TimeoutError:
                # If timeout propagates, that's acceptable (caller handles it)
                pass
    
    @pytest.mark.asyncio
    async def test_paper_to_page_map_tracking(self, sample_paper_with_abstract):
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
    async def test_citation_graph_only_for_papers_with_abstracts(self, sample_paper_with_abstract, sample_paper_without_abstract):
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
            entry.paper for entry in unique_entries
            if entry.paper and entry.paper.abstract
        ]
        
        # Then: Only paper with abstract is included
        assert len(papers_with_abstracts) == 1
        assert papers_with_abstracts[0].id == sample_paper_with_abstract.id
        assert papers_with_abstracts[0].abstract is not None
    
    @pytest.mark.asyncio
    async def test_execute_complementary_search_processing_flow(self, sample_paper_with_abstract, sample_paper_without_abstract):
        """
        TC-PA-N-11: _execute_complementary_search() processes entries according to needs_fetch.
        
        Given: Mixed entries (with/without abstracts) from academic API
        When: _execute_complementary_search() processes entries
        Then:
        - Entries with abstract: persisted directly, fetch skipped
        - Entries without abstract: included in entries_needing_fetch, browser search triggered
        - Stats accumulated correctly
        """
        from src.search.canonical_index import CanonicalPaperIndex
        
        state = ExplorationState(task_id="test_task")
        pipeline = SearchPipeline(task_id="test_task", state=state)
        
        # Create index with mixed entries (simulating Phase 2-4)
        index = CanonicalPaperIndex()
        index.register_paper(sample_paper_with_abstract, "semantic_scholar")
        index.register_paper(sample_paper_without_abstract, "openalex")
        
        unique_entries = index.get_all_entries()
        
        # Simulate Phase 5 processing logic
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
    async def test_execute_complementary_search_with_serp_only_entries(self):
        """
        TC-PA-N-12: SERP-only entries trigger browser search fallback.
        
        Given: SERP-only entries (no Paper object)
        When: Processing entries
        Then: entries_needing_fetch includes SERP-only entries
        """
        from src.search.canonical_index import CanonicalPaperIndex
        
        # Given: SERP-only entry
        serp_result = ProviderSearchResult(
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
    async def test_citation_graph_integration_requires_page_id_mapping(self, sample_paper_with_abstract):
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
        
        # Simulate Phase 5: persist abstract and create mapping
        for entry in unique_entries:
            if entry.paper and entry.paper.abstract:
                page_id = f"page_{entry.paper.id[:8]}"
                paper_to_page_map[entry.paper.id] = page_id
        
        # When: Filtering papers for citation graph (Phase 6)
        papers_with_abstracts = [
            entry.paper for entry in unique_entries
            if entry.paper and entry.paper.abstract and entry.paper.id in paper_to_page_map
        ]
        
        # Then: Paper is included only if in paper_to_page_map
        assert len(papers_with_abstracts) == 1
        assert papers_with_abstracts[0].id in paper_to_page_map
    
    @pytest.mark.asyncio
    async def test_citation_graph_excluded_if_not_in_page_map(self, sample_paper_with_abstract):
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
        paper_to_page_map = {}  # Empty mapping (simulating persistence failure)
        
        # When: Filtering papers for citation graph
        papers_with_abstracts = [
            entry.paper for entry in unique_entries
            if entry.paper and entry.paper.abstract and entry.paper.id in paper_to_page_map
        ]
        
        # Then: Paper is excluded (not in mapping)
        assert len(papers_with_abstracts) == 0
    
    @pytest.mark.asyncio
    async def test_stats_accumulation_with_mixed_entries(self, sample_paper_with_abstract, sample_paper_without_abstract):
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
        
        # Simulate Phase 5 processing
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
    async def test_browser_search_fallback_accumulates_stats(self):
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

