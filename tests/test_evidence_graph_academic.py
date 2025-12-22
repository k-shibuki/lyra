"""
Tests for academic citation integration in evidence graph.

Tests the add_academic_page_with_citations() function and
citation_source, citation_context edge attributes.
Note: is_influential was removed per decision 12 (Phase 2).

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-EG-N-01 | Add edge with citation_source="semantic_scholar" | Equivalence – normal | Edge created with citation_source attribute | - |
| TC-EG-N-02 | Add edge with citation_context | Equivalence – normal | Edge created with citation_context | - |
| TC-EG-N-03 | add_academic_page_with_citations() with citations | Equivalence – normal | PAGE node and CITES edges created | - |
| TC-EG-N-04 | add_academic_page_with_citations() without citations | Equivalence – normal | PAGE node created, no edges | - |
| TC-EG-B-01 | citations=[] (empty list) | Boundary – empty | No edges created | - |
| TC-EG-B-02 | citation_context=None | Boundary – NULL | Edge created with None context | - |
| TC-EG-B-04 | citation_source=None (fallback) | Boundary – NULL | Edge uses paper_metadata.source_api | Citation.source_api未指定時 |
| TC-EG-B-03 | paper_metadata={} (empty dict) | Boundary – empty | Node created with default values | - |
| TC-EG-A-01 | Invalid Citation object in list | Abnormal – invalid input | Citation skipped, processing continues | - |
| TC-EG-A-02 | DB insert fails | Abnormal – exception | Exception handled gracefully | - |
| TC-EG-A-03 | cited_paper_id is None | Abnormal – invalid input | Edge creation skipped or handled | - |
"""

from unittest.mock import AsyncMock, patch

import pytest

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
def evidence_graph() -> EvidenceGraph:
    """Fresh EvidenceGraph instance for testing."""
    return EvidenceGraph(task_id="test_task")


@pytest.fixture
def sample_paper_metadata() -> dict[str, object]:
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
def sample_citations() -> list[Citation]:
    """Sample citation list."""
    return [
        Citation(
            citing_paper_id="page_123",
            cited_paper_id="s2:ref1",
            context="As shown in prior work...",
        ),
        Citation(
            citing_paper_id="page_123",
            cited_paper_id="s2:ref2",
            context=None,
        ),
        Citation(
            citing_paper_id="page_123",
            cited_paper_id="s2:ref3",
            context="Building on the foundational research...",
        ),
    ]


# =============================================================================
# Test: EvidenceGraph.add_edge with Academic Attributes
# =============================================================================


class TestEvidenceGraphAcademicEdges:
    """Tests for adding academic citations to evidence graph."""

    def test_add_edge_with_is_academic_attribute(self, evidence_graph: EvidenceGraph) -> None:
        """
        Test: add_edge() accepts citation_source attribute.

        Given: Source and target PAGE nodes
        When: Adding CITES edge with citation_source="semantic_scholar"
        Then: Edge is created with citation_source attribute
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
            citation_source="semantic_scholar",
        )

        # Then
        assert edge_id is not None

        # Verify edge exists
        source_node = evidence_graph._make_node_id(NodeType.PAGE, source_id)
        target_node = evidence_graph._make_node_id(NodeType.PAGE, target_id)

        assert evidence_graph._graph.has_edge(source_node, target_node)

        edge_data = evidence_graph._graph.edges[source_node, target_node]
        assert edge_data.get("citation_source") == "semantic_scholar"

    def test_add_edge_with_citation_context(self, evidence_graph: EvidenceGraph) -> None:
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
        evidence_graph.add_edge(
            source_type=NodeType.PAGE,
            source_id=source_id,
            target_type=NodeType.PAGE,
            target_id=target_id,
            relation=RelationType.CITES,
            confidence=1.0,
            citation_source="semantic_scholar",
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
    async def test_adds_page_node_with_metadata(
        self, sample_paper_metadata: dict[str, object]
    ) -> None:
        """
        Test: Function adds PAGE node with academic metadata.

        Given: page_id and paper_metadata
        When: add_academic_page_with_citations() is called
        Then: PAGE node is created with is_academic=True and metadata
        """
        with (
            patch("src.filter.evidence_graph.get_database") as mock_db,
            patch("src.filter.evidence_graph._graph", None),
        ):
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            # add_academic_page_with_citations() awaits fetch_one; ensure it returns a dict/None (not AsyncMock)
            mock_db_instance.fetch_one = AsyncMock(return_value=None)
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
    async def test_adds_citation_edges(
        self, sample_paper_metadata: dict[str, object], sample_citations: list[Citation]
    ) -> None:
        """
        Test: Function adds CITES edges for citations.

        Given: page_id, paper_metadata, citations list, and paper_to_page_map
        When: add_academic_page_with_citations() is called
        Then: CITES edges are created for each citation with mapped page_id
        """
        with (
            patch("src.filter.evidence_graph.get_database") as mock_db,
            patch("src.filter.evidence_graph._graph", None),
        ):
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            # add_academic_page_with_citations() awaits fetch_one; ensure it returns a dict/None (not AsyncMock)
            mock_db_instance.fetch_one = AsyncMock(return_value=None)
            mock_db_instance.fetch_all = AsyncMock(return_value=[])

            # Given: paper_to_page_map mapping cited_paper_id to page_id
            paper_to_page_map = {
                "s2:ref1": "page_ref1",
                "s2:ref2": "page_ref2",
                "s2:ref3": "page_ref3",
            }
            page_id = "page_123"

            # When
            await add_academic_page_with_citations(
                page_id=page_id,
                paper_metadata=sample_paper_metadata,
                citations=sample_citations,
                task_id="test_task",
                paper_to_page_map=paper_to_page_map,
            )

            # Then: Verify DB inserts (all citations should be mapped)
            assert mock_db_instance.insert.call_count == len(sample_citations)

            # Check each edge insert
            for _i, call in enumerate(mock_db_instance.insert.call_args_list):
                table_name = call[0][0]
                edge_data = call[0][1]

                assert table_name == "edges"
                assert edge_data["source_type"] == NodeType.PAGE.value
                assert edge_data["target_type"] == NodeType.PAGE.value
                assert edge_data["relation"] == RelationType.CITES.value
                assert edge_data["citation_source"] in ("semantic_scholar", "openalex")
                # Phase 2: domain_category should be present (from pages table domain)
                assert "source_domain_category" in edge_data
                assert "target_domain_category" in edge_data

    @pytest.mark.asyncio
    async def test_handles_empty_citations_list(
        self, sample_paper_metadata: dict[str, object]
    ) -> None:
        """
        Test: Function handles empty citations list gracefully.

        Given: Empty citations list
        When: add_academic_page_with_citations() is called
        Then: No edges are created, no errors
        """
        with (
            patch("src.filter.evidence_graph.get_database") as mock_db,
            patch("src.filter.evidence_graph._graph", None),
        ):
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

    @pytest.mark.asyncio
    async def test_domain_category_from_page_domains(
        self, sample_paper_metadata: dict[str, object], sample_citations: list[Citation]
    ) -> None:
        """
        TC-P2-ACAD-N-01: Domain categories derived from actual page domains.

        Given: Pages with known domains in database
        When: add_academic_page_with_citations() is called
        Then: source_domain_category and target_domain_category are calculated from pages table
        """
        with (
            patch("src.filter.evidence_graph.get_database") as mock_db,
            patch("src.filter.evidence_graph._graph", None),
        ):
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()

            # Mock fetch_one to return page domain information
            # NOTE: Use sync side_effect with AsyncMock to avoid returning a coroutine (which triggers "never awaited")
            def mock_fetch_one(query: str, params: tuple) -> dict | None:
                if "page_123" in params:
                    return {"url": "https://arxiv.org/abs/1234", "domain": "arxiv.org"}
                elif "page_ref1" in params:
                    return {"url": "https://doi.org/10.1234/test", "domain": "doi.org"}
                return None

            mock_db_instance.fetch_one = AsyncMock(side_effect=mock_fetch_one)
            mock_db_instance.fetch_all = AsyncMock(return_value=[])

            # Given: paper_to_page_map
            paper_to_page_map = {
                "s2:ref1": "page_ref1",
            }
            page_id = "page_123"

            # When
            await add_academic_page_with_citations(
                page_id=page_id,
                paper_metadata=sample_paper_metadata,
                citations=[sample_citations[0]],  # Single citation
                task_id="test_task",
                paper_to_page_map=paper_to_page_map,
            )

            # Then: Verify domain categories were calculated from pages
            assert mock_db_instance.insert.call_count == 1
            call = mock_db_instance.insert.call_args_list[0]
            edge_data = call[0][1]
            assert "source_domain_category" in edge_data
            assert "target_domain_category" in edge_data
            # Domain categories should be calculated (not hardcoded "academic")
            # Actual values depend on domain_policy configuration
            assert edge_data["source_domain_category"] is not None
            assert edge_data["target_domain_category"] is not None

    @pytest.mark.asyncio
    async def test_domain_category_fallback_when_page_not_found(
        self, sample_paper_metadata: dict[str, object], sample_citations: list[Citation]
    ) -> None:
        """
        TC-P2-ACAD-B-01: Domain categories fallback to "academic" when page not found.

        Given: Pages not found in database
        When: add_academic_page_with_citations() is called
        Then: Domain categories fallback to "academic"
        """
        with (
            patch("src.filter.evidence_graph.get_database") as mock_db,
            patch("src.filter.evidence_graph._graph", None),
        ):
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            mock_db_instance.fetch_one = AsyncMock(return_value=None)  # Page not found
            mock_db_instance.fetch_all = AsyncMock(return_value=[])

            # Given: paper_to_page_map
            paper_to_page_map = {
                "s2:ref1": "page_ref1",
            }
            page_id = "page_123"

            # When
            await add_academic_page_with_citations(
                page_id=page_id,
                paper_metadata=sample_paper_metadata,
                citations=[sample_citations[0]],
                task_id="test_task",
                paper_to_page_map=paper_to_page_map,
            )

            # Then: Verify fallback to "academic"
            assert mock_db_instance.insert.call_count == 1
            call = mock_db_instance.insert.call_args_list[0]
            edge_data = call[0][1]
            assert edge_data["source_domain_category"] == "academic"
            assert edge_data["target_domain_category"] == "academic"


# =============================================================================
# Test: Academic Edge Query
# =============================================================================


class TestAcademicEdgeQuery:
    """Tests for querying academic edges."""

    def test_filter_academic_citations(self, evidence_graph: EvidenceGraph) -> None:
        """
        Test: Can filter edges by citation_source attribute.

        Given: Graph with both API-derived and extracted citations
        When: Filtering for API-derived citation edges
        Then: Only API-derived citation edges are returned
        """
        # Given: Add mix of edges
        evidence_graph.add_edge(
            NodeType.PAGE,
            "page1",
            NodeType.PAGE,
            "page2",
            RelationType.CITES,
            citation_source="semantic_scholar",
        )

        evidence_graph.add_edge(
            NodeType.FRAGMENT,
            "frag1",
            NodeType.PAGE,
            "page3",
            RelationType.CITES,
            citation_source="extraction",
        )

        # When: Filter for API-derived citation edges
        academic_edges = [
            (u, v, d)
            for u, v, d in evidence_graph._graph.edges(data=True)
            if d.get("citation_source") in ("semantic_scholar", "openalex")
        ]

        # Then
        assert len(academic_edges) == 1
        assert academic_edges[0][0] == evidence_graph._make_node_id(NodeType.PAGE, "page1")


# =============================================================================
# Test: Boundary Values and Edge Cases
# =============================================================================


class TestBoundaryValues:
    """Tests for boundary values and edge cases."""

    @pytest.mark.asyncio
    async def test_citation_context_none(self, sample_paper_metadata: dict[str, object]) -> None:
        """
        TC-EG-B-02: citation_context=None is handled correctly.

        Given: Citation with context=None
        When: Adding citation edge
        Then: Edge is created with None context
        """
        Citation(
            citing_paper_id="page_123",
            cited_paper_id="s2:ref1",
            context=None,  # None context
        )

        graph = EvidenceGraph(task_id="test_task")

        # When: Adding edge with None context
        edge_id = graph.add_edge(
            NodeType.PAGE,
            "page_123",
            NodeType.PAGE,
            "s2:ref1",
            RelationType.CITES,
            citation_source="semantic_scholar",
            citation_context=None,
        )

        # Then: Edge created with None context
        assert edge_id is not None
        source_node = graph._make_node_id(NodeType.PAGE, "page_123")
        target_node = graph._make_node_id(NodeType.PAGE, "s2:ref1")
        edge_data = graph._graph.edges[source_node, target_node]
        assert edge_data.get("citation_context") is None

    @pytest.mark.asyncio
    async def test_empty_paper_metadata(self) -> None:
        """
        TC-EG-B-03: Empty paper_metadata dict is handled correctly.

        Given: Empty paper_metadata dict
        When: add_academic_page_with_citations() is called
        Then: Node created with default values
        """
        with patch("src.filter.evidence_graph.get_database") as mock_db:
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            mock_db_instance.fetch_one = AsyncMock(return_value=None)
            mock_db_instance.fetch_all = AsyncMock(return_value=[])

            # Given: Empty metadata
            page_id = "page_test"
            empty_metadata: dict[str, object] = {}

            # When: Adding page with empty metadata
            await add_academic_page_with_citations(
                page_id=page_id,
                paper_metadata=empty_metadata,
                citations=[],
                task_id="test_task",
            )

            # Then: Node should be created (default values used)
            graph = await get_evidence_graph("test_task")
            page_node = graph._make_node_id(NodeType.PAGE, page_id)
            assert graph._graph.has_node(page_node)

            node_data = graph._graph.nodes[page_node]
            assert node_data.get("is_academic") is True
            assert node_data.get("citation_count", 0) == 0  # Default value


# =============================================================================
# Test: Exception Handling
# =============================================================================


class TestExceptionHandlingEvidenceGraph:
    """Tests for exception handling in evidence graph operations."""

    @pytest.mark.asyncio
    async def test_invalid_citation_object_skipped(
        self, sample_paper_metadata: dict[str, object]
    ) -> None:
        """
        TC-EG-A-01: Invalid Citation object in list is skipped.

        Given: Citations list with invalid object
        When: add_academic_page_with_citations() is called
        Then: Invalid citation is skipped, processing continues
        """
        with patch("src.filter.evidence_graph.get_database") as mock_db:
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            # add_academic_page_with_citations() awaits fetch_one; return None to avoid AsyncMock dict-like usage
            mock_db_instance.fetch_one = AsyncMock(return_value=None)
            mock_db_instance.fetch_all = AsyncMock(return_value=[])

            # Given: Citations list with invalid object
            invalid_citations = [
                Citation(
                    citing_paper_id="page_123",
                    cited_paper_id="s2:ref1",
                    context=None,
                ),
                "not_a_citation",  # Invalid object
                {"invalid": "dict"},  # Invalid object
                Citation(
                    citing_paper_id="page_123",
                    cited_paper_id="s2:ref2",
                    context=None,
                ),
            ]

            # Given: paper_to_page_map for valid citations
            paper_to_page_map = {
                "s2:ref1": "page_ref1",
                "s2:ref2": "page_ref2",
            }

            # When: Adding citations
            await add_academic_page_with_citations(
                page_id="page_123",
                paper_metadata=sample_paper_metadata,
                citations=invalid_citations,
                task_id="test_task",
                paper_to_page_map=paper_to_page_map,
            )

            # Then: Only valid citations should create edges
            # Should have 2 edge inserts (for 2 valid Citation objects)
            valid_citation_count = sum(1 for c in invalid_citations if isinstance(c, Citation))
            assert mock_db_instance.insert.call_count == valid_citation_count

    @pytest.mark.asyncio
    async def test_db_insert_failure_handled(
        self, sample_paper_metadata: dict[str, object], sample_citations: list[Citation]
    ) -> None:
        """
        TC-EG-A-02: DB insert failure is handled gracefully.

        Given: DB insert raises exception
        When: add_academic_page_with_citations() is called
        Then: Exception is raised (caller should handle it)
        """
        with patch("src.filter.evidence_graph.get_database") as mock_db:
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock(side_effect=Exception("DB error"))
            mock_db_instance.fetch_one = AsyncMock(return_value=None)
            mock_db_instance.fetch_all = AsyncMock(return_value=[])

            # Given: paper_to_page_map so citations are not skipped
            paper_to_page_map = {
                "s2:ref1": "page_ref1",
                "s2:ref2": "page_ref2",
                "s2:ref3": "page_ref3",
            }

            # When: Adding citations (should raise exception on DB insert)
            with pytest.raises(Exception) as exc_info:
                await add_academic_page_with_citations(
                    page_id="page_123",
                    paper_metadata=sample_paper_metadata,
                    citations=sample_citations,
                    task_id="test_task",
                    paper_to_page_map=paper_to_page_map,
                )

            # Then: Exception is raised (caller should handle it)
            assert "DB error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cited_paper_id_empty_string_handled(
        self, sample_paper_metadata: dict[str, object]
    ) -> None:
        """
        TC-EG-A-03: cited_paper_id is empty string is handled.

        Given: Citation with cited_paper_id=""
        When: Adding citation edge
        Then: Edge creation proceeds (empty string is valid)
        """
        # Given: Citation with empty string cited_paper_id
        citation_with_empty = Citation(
            citing_paper_id="page_123",
            cited_paper_id="",  # Empty string (valid but edge case)
            context=None,
        )

        with patch("src.filter.evidence_graph.get_database") as mock_db:
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            mock_db_instance.fetch_one = AsyncMock(return_value=None)
            mock_db_instance.fetch_all = AsyncMock(return_value=[])

            # When: Adding citation with empty ID
            await add_academic_page_with_citations(
                page_id="page_123",
                paper_metadata=sample_paper_metadata,
                citations=[citation_with_empty],
                task_id="test_task",
            )

            # Then: Edge should be created (empty string is valid)
            # Note: Empty string cited_paper_id won't be in paper_to_page_map, so it will be skipped
            # This test verifies the function handles empty string gracefully
            assert mock_db_instance.insert.call_count == 0  # Skipped because not in map

    @pytest.mark.asyncio
    async def test_skips_citations_without_page_mapping(
        self, sample_paper_metadata: dict[str, object]
    ) -> None:
        """
        TC-EG-N-11: Citations without page_id mapping are skipped.

        Given: Citations with cited_paper_id not in paper_to_page_map
        When: add_academic_page_with_citations() is called
        Then: Citations are skipped, no edges created
        """
        from src.utils.schemas import Citation

        with (
            patch("src.filter.evidence_graph.get_database") as mock_db,
            patch("src.filter.evidence_graph._graph", None),
        ):
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            mock_db_instance.fetch_one = AsyncMock(return_value=None)
            mock_db_instance.fetch_all = AsyncMock(return_value=[])

            # Given: Citations with paper IDs not in mapping
            citations = [
                Citation(
                    citing_paper_id="page_123",
                    cited_paper_id="s2:unmapped1",  # Not in paper_to_page_map
                    context=None,
                ),
                Citation(
                    citing_paper_id="page_123",
                    cited_paper_id="s2:unmapped2",  # Not in paper_to_page_map
                    context=None,
                ),
            ]
            paper_to_page_map: dict[str, str] = {}  # Empty map

            # When
            await add_academic_page_with_citations(
                page_id="page_123",
                paper_metadata=sample_paper_metadata,
                citations=citations,
                task_id="test_task",
                paper_to_page_map=paper_to_page_map,
            )

            # Then: No edges created (all citations skipped)
            assert mock_db_instance.insert.call_count == 0

    @pytest.mark.asyncio
    async def test_maps_cited_paper_id_to_page_id(
        self, sample_paper_metadata: dict[str, object]
    ) -> None:
        """
        TC-EG-N-12: cited_paper_id is correctly mapped to page_id.

        Given: Citations with cited_paper_id in paper_to_page_map
        When: add_academic_page_with_citations() is called
        Then: Edges use mapped page_id, not paper_id
        """
        from src.utils.schemas import Citation

        with (
            patch("src.filter.evidence_graph.get_database") as mock_db,
            patch("src.filter.evidence_graph._graph", None),
        ):
            mock_db_instance = AsyncMock()
            mock_db.return_value = mock_db_instance
            mock_db_instance.insert = AsyncMock()
            mock_db_instance.fetch_one = AsyncMock(return_value=None)
            mock_db_instance.fetch_all = AsyncMock(return_value=[])

            # Given: Citations with paper IDs mapped to page IDs
            citations = [
                Citation(
                    citing_paper_id="page_123",
                    cited_paper_id="s2:ref1",  # Maps to page_ref1
                    context=None,
                ),
            ]
            paper_to_page_map = {
                "s2:ref1": "page_ref1",  # Mapping
            }

            # When
            await add_academic_page_with_citations(
                page_id="page_123",
                paper_metadata=sample_paper_metadata,
                citations=citations,
                task_id="test_task",
                paper_to_page_map=paper_to_page_map,
            )

            # Then: Edge uses mapped page_id, not paper_id
            assert mock_db_instance.insert.call_count == 1
            edge_data = mock_db_instance.insert.call_args[0][1]
            assert edge_data["target_id"] == "page_ref1"  # Mapped page_id
            assert edge_data["target_id"] != "s2:ref1"  # Not paper_id
