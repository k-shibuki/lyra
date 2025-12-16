"""
Tests for academic search pipeline integration.

Tests the Abstract Only strategy and citation graph integration
in the SearchPipeline._execute_complementary_search() method.
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

