"""
Tests for academic citation integration in evidence graph.

Tests the add_academic_page_with_citations() function and
is_academic/is_influential edge attributes.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.filter.evidence_graph import (
    EvidenceGraph,
    NodeType,
    RelationType,
    add_academic_page_with_citations,
    get_evidence_graph,
)
from src.utils.schemas import Citation


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def evidence_graph():
    """Fresh EvidenceGraph instance for testing."""
    return EvidenceGraph(task_id="test_task")


@pytest.fixture
def sample_paper_metadata():
    """Sample paper metadata dict."""
    return {
        "doi": "10.1234/test.paper",
        "arxiv_id": None,
        "authors": [
            {"name": "John Doe", "affiliation": "Test University", "orcid": None},
        ],
        "year": 2024,
        "venue": "Nature",
        "citation_count": 42,
        "reference_count": 25,
        "is_open_access": True,
        "oa_url": "https://example.com/paper.pdf",
        "pdf_url": "https://example.com/paper.pdf",
        "source_api": "semantic_scholar",
    }


@pytest.fixture
def sample_citations():
    """Sample citation list."""
    return [
        Citation(
            citing_paper_id="page_123",
            cited_paper_id="s2:ref1",
            is_influential=True,
            context="As shown in prior work...",
        ),
        Citation(
            citing_paper_id="page_123",
            cited_paper_id="s2:ref2",
            is_influential=False,
            context=None,
        ),
        Citation(
            citing_paper_id="page_123",
            cited_paper_id="s2:ref3",
            is_influential=True,
            context="Building on the foundational research...",
        ),
    ]


# =============================================================================
# Test: EvidenceGraph.add_edge with Academic Attributes
# =============================================================================


class TestEvidenceGraphAcademicEdges:
    """Tests for adding academic citations to evidence graph."""
    
    def test_add_edge_with_is_academic_attribute(self, evidence_graph):
        """
        Test: add_edge() accepts is_academic attribute.
        
        Given: Source and target PAGE nodes
        When: Adding CITES edge with is_academic=True
        Then: Edge is created with is_academic attribute
        """
        # Given
        source_id = "page_source"
        target_id = "page_target"
        
        # When
        edge_id = evidence_graph.add_edge(
            source_type=NodeType.PAGE,
            source_id=source_id,
            target_type=NodeType.PAGE,
            target_id=target_id,
            relation=RelationType.CITES,
            confidence=1.0,
            is_academic=True,
        )
        
        # Then
        assert edge_id is not None
        
        # Verify edge exists
        source_node = evidence_graph._make_node_id(NodeType.PAGE, source_id)
        target_node = evidence_graph._make_node_id(NodeType.PAGE, target_id)
        
        assert evidence_graph._graph.has_edge(source_node, target_node)
        
        edge_data = evidence_graph._graph.edges[source_node, target_node]
        assert edge_data.get("is_academic") is True
    
    def test_add_edge_with_is_influential_attribute(self, evidence_graph):
        """
        Test: add_edge() accepts is_influential attribute.
        
        Given: Source and target PAGE nodes
        When: Adding CITES edge with is_influential=True
        Then: Edge is created with is_influential attribute
        """
        # Given
        source_id = "page_source"
        target_id = "page_target"
        
        # When
        edge_id = evidence_graph.add_edge(
            source_type=NodeType.PAGE,
            source_id=source_id,
            target_type=NodeType.PAGE,
            target_id=target_id,
            relation=RelationType.CITES,
            confidence=1.0,
            is_academic=True,
            is_influential=True,
        )
        
        # Then
        source_node = evidence_graph._make_node_id(NodeType.PAGE, source_id)
        target_node = evidence_graph._make_node_id(NodeType.PAGE, target_id)
        
        edge_data = evidence_graph._graph.edges[source_node, target_node]
        assert edge_data.get("is_influential") is True
    
    def test_add_edge_with_citation_context(self, evidence_graph):
        """
        Test: add_edge() accepts citation_context attribute.
        
        Given: Source and target PAGE nodes
        When: Adding CITES edge with citation_context
        Then: Edge is created with citation_context attribute
        """
        # Given
        source_id = "page_source"
        target_id = "page_target"
        context = "As demonstrated in previous work..."
        
        # When
        edge_id = evidence_graph.add_edge(
            source_type=NodeType.PAGE,
            source_id=source_id,
            target_type=NodeType.PAGE,
            target_id=target_id,
            relation=RelationType.CITES,
            confidence=1.0,
            is_academic=True,
            citation_context=context,
        )
        
        # Then
        source_node = evidence_graph._make_node_id(NodeType.PAGE, source_id)
        target_node = evidence_graph._make_node_id(NodeType.PAGE, target_id)
        
        edge_data = evidence_graph._graph.edges[source_node, target_node]
        assert edge_data.get("citation_context") == context


# =============================================================================
# Test: add_academic_page_with_citations()
# =============================================================================


class TestAddAcademicPageWithCitations:
    """Tests for add_academic_page_with_citations() function."""
    
    @pytest.mark.asyncio
    async def test_adds_page_node_with_metadata(self, sample_paper_metadata):
        """
        Test: Function adds PAGE node with academic metadata.
        
        Given: page_id and paper_metadata
        When: add_academic_page_with_citations() is called
        Then: PAGE node is created with is_academic=True and metadata
        """
        with patch("src.filter.evidence_graph.get_database") as mock_db, \
             patch("src.filter.evidence_graph._graph", None):
            
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            mock_db_instance.fetch_all = AsyncMock(return_value=[])
            
            # Given
            page_id = "page_test123"
            
            # When
            await add_academic_page_with_citations(
                page_id=page_id,
                paper_metadata=sample_paper_metadata,
                citations=[],  # No citations
                task_id="test_task",
            )
            
            # Then: Verify graph was updated
            graph = await get_evidence_graph("test_task")
            page_node = graph._make_node_id(NodeType.PAGE, page_id)
            
            assert graph._graph.has_node(page_node)
            node_data = graph._graph.nodes[page_node]
            assert node_data.get("is_academic") is True
            assert node_data.get("doi") == sample_paper_metadata["doi"]
            assert node_data.get("citation_count") == sample_paper_metadata["citation_count"]
    
    @pytest.mark.asyncio
    async def test_adds_citation_edges(self, sample_paper_metadata, sample_citations):
        """
        Test: Function adds CITES edges for citations.
        
        Given: page_id, paper_metadata, and citations list
        When: add_academic_page_with_citations() is called
        Then: CITES edges are created for each citation
        """
        with patch("src.filter.evidence_graph.get_database") as mock_db, \
             patch("src.filter.evidence_graph._graph", None):
            
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            mock_db_instance.fetch_all = AsyncMock(return_value=[])
            
            # Given
            page_id = "page_123"
            
            # When
            await add_academic_page_with_citations(
                page_id=page_id,
                paper_metadata=sample_paper_metadata,
                citations=sample_citations,
                task_id="test_task",
            )
            
            # Then: Verify DB inserts
            assert mock_db_instance.insert.call_count == len(sample_citations)
            
            # Check each edge insert
            for i, call in enumerate(mock_db_instance.insert.call_args_list):
                table_name = call[0][0]
                edge_data = call[0][1]
                
                assert table_name == "edges"
                assert edge_data["source_type"] == NodeType.PAGE.value
                assert edge_data["target_type"] == NodeType.PAGE.value
                assert edge_data["relation"] == RelationType.CITES.value
                assert edge_data["is_academic"] == 1
    
    @pytest.mark.asyncio
    async def test_preserves_is_influential_flag(self, sample_paper_metadata, sample_citations):
        """
        Test: Function preserves is_influential from Citation objects.
        
        Given: Citations with varying is_influential values
        When: add_academic_page_with_citations() is called
        Then: is_influential is correctly set on edges
        """
        with patch("src.filter.evidence_graph.get_database") as mock_db, \
             patch("src.filter.evidence_graph._graph", None):
            
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            mock_db_instance.fetch_all = AsyncMock(return_value=[])
            
            # Given
            page_id = "page_123"
            
            # When
            await add_academic_page_with_citations(
                page_id=page_id,
                paper_metadata=sample_paper_metadata,
                citations=sample_citations,
                task_id="test_task",
            )
            
            # Then: Verify is_influential matches original citations
            calls = mock_db_instance.insert.call_args_list
            
            for i, citation in enumerate(sample_citations):
                edge_data = calls[i][0][1]
                expected = 1 if citation.is_influential else 0
                assert edge_data["is_influential"] == expected
    
    @pytest.mark.asyncio
    async def test_handles_empty_citations_list(self, sample_paper_metadata):
        """
        Test: Function handles empty citations list gracefully.
        
        Given: Empty citations list
        When: add_academic_page_with_citations() is called
        Then: No edges are created, no errors
        """
        with patch("src.filter.evidence_graph.get_database") as mock_db, \
             patch("src.filter.evidence_graph._graph", None):
            
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            mock_db_instance.fetch_all = AsyncMock(return_value=[])
            
            # Given
            page_id = "page_123"
            
            # When
            await add_academic_page_with_citations(
                page_id=page_id,
                paper_metadata=sample_paper_metadata,
                citations=[],  # Empty list
                task_id="test_task",
            )
            
            # Then: No edge inserts
            assert mock_db_instance.insert.call_count == 0


# =============================================================================
# Test: Academic Edge Query
# =============================================================================


class TestAcademicEdgeQuery:
    """Tests for querying academic edges."""
    
    def test_filter_academic_citations(self, evidence_graph):
        """
        Test: Can filter edges by is_academic attribute.
        
        Given: Graph with both academic and non-academic edges
        When: Filtering for academic edges
        Then: Only academic edges are returned
        """
        # Given: Add mix of edges
        evidence_graph.add_edge(
            NodeType.PAGE, "page1",
            NodeType.PAGE, "page2",
            RelationType.CITES,
            is_academic=True,
        )
        
        evidence_graph.add_edge(
            NodeType.FRAGMENT, "frag1",
            NodeType.PAGE, "page3",
            RelationType.CITES,
            is_academic=False,
        )
        
        # When: Filter for academic edges
        academic_edges = [
            (u, v, d) for u, v, d in evidence_graph._graph.edges(data=True)
            if d.get("is_academic") is True
        ]
        
        # Then
        assert len(academic_edges) == 1
        assert academic_edges[0][0] == evidence_graph._make_node_id(NodeType.PAGE, "page1")
    
    def test_filter_influential_citations(self, evidence_graph):
        """
        Test: Can filter edges by is_influential attribute.
        
        Given: Graph with influential and non-influential edges
        When: Filtering for influential edges
        Then: Only influential edges are returned
        """
        # Given: Add mix of edges
        evidence_graph.add_edge(
            NodeType.PAGE, "page1",
            NodeType.PAGE, "ref1",
            RelationType.CITES,
            is_academic=True,
            is_influential=True,
        )
        
        evidence_graph.add_edge(
            NodeType.PAGE, "page1",
            NodeType.PAGE, "ref2",
            RelationType.CITES,
            is_academic=True,
            is_influential=False,
        )
        
        # When: Filter for influential edges
        influential_edges = [
            (u, v, d) for u, v, d in evidence_graph._graph.edges(data=True)
            if d.get("is_influential") is True
        ]
        
        # Then
        assert len(influential_edges) == 1

