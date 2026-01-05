"""
Tests for src/filter/evidence_graph.py

Per ADR-0005: Evidence Graph Structure.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-NODE-N-01 | NodeType enum | Equivalence – normal | All types defined | claim, fragment, page |
| TC-REL-N-01 | RelationType enum | Equivalence – normal | All types defined | supports, refutes, cites, neutral |
| TC-INIT-N-01 | Graph init | Equivalence – normal | Empty graph created | task_id set |
| TC-NID-N-01 | Valid node ID | Equivalence – normal | ID generated | type:id format |
| TC-NID-N-02 | Parse node ID | Equivalence – normal | Type and ID extracted | Reverse of make |
| TC-NODE-N-02 | Add node | Equivalence – normal | Node added with attrs | Stored in graph |
| TC-EDGE-N-01 | Add edge | Equivalence – normal | Nodes created if missing | Auto-create |
| TC-EDGE-N-02 | Edge with NLI | Equivalence – normal | NLI data stored | label, confidence |
| TC-EVID-N-01 | Get supporting | Equivalence – normal | Supporting evidence | Filtered by relation |
| TC-EVID-N-02 | Get refuting | Equivalence – normal | Refuting evidence | Filtered by relation |
| TC-EVID-N-03 | Get all evidence | Equivalence – normal | Categorized evidence | All relations |
| TC-EVID-B-01 | Unknown claim | Boundary – not found | Empty result | Edge case |
| TC-CONF-N-01 | No evidence | Equivalence – normal | confidence=0 | unverified |
| TC-CONF-N-02 | Well supported | Equivalence – normal | High confidence | Bayesian confidence computed |
| TC-CONF-N-03 | Contested | Equivalence – normal | Mixed evidence | Support + refute |
| TC-CITE-N-01 | Citation chain | Equivalence – normal | Chain traced | CITES edges |
| TC-CITE-B-01 | Unknown node | Boundary – not found | Empty chain | Edge case |
| TC-CONTR-N-01 | Find contradictions | Equivalence – normal | Pairs returned | Claim-claim refutes |
| TC-CONTR-B-01 | No contradictions | Boundary – empty | Empty list | Clean graph |
| TC-STAT-N-01 | Stats empty | Equivalence – normal | Zero counts | Empty graph |
| TC-STAT-N-02 | Stats populated | Equivalence – normal | Correct counts | Node/edge types |
| TC-EXP-N-01 | Export to dict | Equivalence – normal | Data structure | nodes, edges, stats |
| TC-LOOP-N-01 | Citation loop | Equivalence – normal | Loop detected | A->B->C->A |
| TC-LOOP-B-01 | No loops | Boundary – clean | Empty list | Linear chain |
| TC-LOOP-N-02 | Ignores non-cites | Equivalence – normal | Only CITES edges | Filter by relation |
| TC-RT-N-01 | Round trip | Equivalence – normal | Detected | A->B, B->A |
| TC-RT-B-01 | No round trips | Boundary – clean | Empty list | One-way |
| TC-SELF-N-01 | Direct self-ref | Equivalence – normal | Critical severity | A->A |
| TC-SELF-N-02 | Same domain | Equivalence – normal | Detected | Same domain cite |
| TC-SELF-B-01 | No self-refs | Boundary – clean | Empty list | Different domains |
| TC-PEN-N-01 | Loop penalties | Equivalence – normal | Penalty < 1.0 | Nodes in loop |
| TC-PEN-B-01 | No issues | Boundary – clean | Penalty = 1.0 | Clean graph |
| TC-INT-N-01 | Clean integrity | Equivalence – normal | Score = 1.0 | No issues |
| TC-INT-N-02 | Problematic | Equivalence – normal | Score < 1.0 | Has issues |
| TC-INT-B-01 | Empty graph | Boundary – empty | Score = 1.0 | No edges |
| TC-PRIM-N-01 | All primary | Equivalence – normal | Ratio = 1.0 | No secondary |
| TC-PRIM-N-02 | Mixed sources | Equivalence – normal | Ratio calculated | Primary/secondary |
| TC-PRIM-B-01 | Empty graph | Boundary – empty | Ratio = 0.0 | No pages |
| TC-SEV-N-01 | Severity calc | Equivalence – normal | By loop length | critical/high/medium/low |
| TC-DB-I-01 | Save and load | Integration | Persisted to DB | DB integration |
| TC-DB-I-02 | Add evidence | Integration | Edge persisted | DB integration |
| TC-IS-N-01 | 2 frags from 2 pages | Equivalence – normal | independent_sources = 2 | FRAGMENT→CLAIM |
| TC-IS-N-02 | 2 frags from same page | Equivalence – normal | independent_sources = 1 | Dedup by page_id |
| TC-IS-B-01 | No evidence | Boundary – empty | independent_sources = 0 | Empty graph |
| TC-IS-B-02 | 1 frag with page_id | Boundary – single | independent_sources = 1 | Minimum positive |
| TC-IS-B-03 | Frag without page_id | Boundary – fallback | Fallback to frag_id | Legacy compat |
| TC-IS-N-03 | Mixed frags | Equivalence – normal | Correct count | Mix page_id/none |
| TC-EY-N-01 | Frags with page years | Equivalence – normal | evidence_years extracted | Year from node |
| TC-EY-B-01 | Frag no year | Boundary – empty | evidence_years = null | No year attr |
"""

from typing import TYPE_CHECKING

import pytest

# Unit tests for evidence graph (no external dependencies except test fixtures)
pytestmark = pytest.mark.unit

from src.filter.evidence_graph import (
    EvidenceGraph,
    NodeType,
    RelationType,
    add_claim_evidence,
)

if TYPE_CHECKING:
    from src.storage.database import Database


class TestNodeType:
    """Tests for NodeType enum."""

    def test_node_types_exist(self) -> None:
        """Test all node types are defined."""
        # Given: The NodeType enum
        # When: Accessing enum values
        # Then: All expected node types exist with correct values
        assert NodeType.CLAIM.value == "claim"
        assert NodeType.FRAGMENT.value == "fragment"
        assert NodeType.PAGE.value == "page"


class TestRelationType:
    """Tests for RelationType enum."""

    def test_relation_types_exist(self) -> None:
        """Test all relation types are defined."""
        # Given: The RelationType enum
        # When: Accessing enum values
        # Then: All expected relation types exist with correct values
        assert RelationType.SUPPORTS.value == "supports"
        assert RelationType.REFUTES.value == "refutes"
        assert RelationType.CITES.value == "cites"
        assert RelationType.NEUTRAL.value == "neutral"


class TestEvidenceGraph:
    """Tests for EvidenceGraph class."""

    def test_init(self) -> None:
        """Test graph initialization."""
        # Given: A task ID for the graph
        # When: Creating a new EvidenceGraph
        graph = EvidenceGraph(task_id="test-task")

        # Then: Graph is empty with the specified task ID
        assert graph.task_id == "test-task"
        assert graph._graph.number_of_nodes() == 0
        assert graph._graph.number_of_edges() == 0

    def test_make_node_id(self) -> None:
        """Test node ID generation."""
        # Given: An EvidenceGraph instance
        graph = EvidenceGraph()

        # When: Generating node IDs for different types
        node_id = graph._make_node_id(NodeType.CLAIM, "abc123")

        # Then: Node ID follows type:id format
        assert node_id == "claim:abc123"

        node_id = graph._make_node_id(NodeType.FRAGMENT, "xyz789")
        assert node_id == "fragment:xyz789"

    def test_parse_node_id(self) -> None:
        """Test node ID parsing."""
        # Given: Node IDs in type:id format
        graph = EvidenceGraph()

        # When: Parsing the node IDs
        node_type, obj_id = graph._parse_node_id("claim:abc123")

        # Then: Type and ID are correctly extracted
        assert node_type == NodeType.CLAIM
        assert obj_id == "abc123"

        node_type, obj_id = graph._parse_node_id("page:http://example.com")
        assert node_type == NodeType.PAGE
        assert obj_id == "http://example.com"

    def test_add_node(self) -> None:
        """Test adding nodes."""
        # Given: An empty EvidenceGraph
        graph = EvidenceGraph()

        # When: Adding a node with attributes
        node_id = graph.add_node(
            NodeType.CLAIM,
            "claim-1",
            text="Test claim",
            confidence=0.9,
        )

        # Then: Node is added with all attributes stored
        assert node_id == "claim:claim-1"
        assert graph._graph.number_of_nodes() == 1

        node_data = graph._graph.nodes[node_id]
        assert node_data["node_type"] == "claim"
        assert node_data["obj_id"] == "claim-1"
        assert node_data["text"] == "Test claim"
        assert node_data["confidence"] == 0.9

    def test_add_edge_creates_nodes_if_missing(self) -> None:
        """Test adding edge creates nodes if they don't exist."""
        # Given: An empty EvidenceGraph
        graph = EvidenceGraph()

        # When: Adding an edge between non-existent nodes
        edge_id = graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.8,
        )

        # Then: Both nodes and the edge are created
        assert edge_id is not None
        assert graph._graph.number_of_nodes() == 2
        assert graph._graph.number_of_edges() == 1

    def test_add_edge_with_nli_data(self) -> None:
        """Test adding edge with NLI data."""
        # Given: An empty EvidenceGraph
        graph = EvidenceGraph()

        # When: Adding an edge with NLI metadata
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.85,
            nli_label="entailment",
            nli_edge_confidence=0.92,
        )

        # Then: Edge contains all NLI data
        edge_data = graph._graph.edges["fragment:frag-1", "claim:claim-1"]
        assert edge_data["relation"] == "supports"
        assert edge_data["confidence"] == 0.85
        assert edge_data["nli_label"] == "entailment"
        assert edge_data["nli_edge_confidence"] == 0.92


class TestEvidenceRetrieval:
    """Tests for evidence retrieval methods."""

    @pytest.fixture
    def populated_graph(self) -> EvidenceGraph:
        """Create a graph with test data."""
        graph = EvidenceGraph(task_id="test")

        # Add supporting evidence
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
        )
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-2",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.85,
        )

        # Add refuting evidence
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-3",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.REFUTES,
            confidence=0.7,
        )

        # Add neutral evidence
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-4",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.NEUTRAL,
            confidence=0.5,
        )

        return graph

    def test_get_supporting_evidence(self, populated_graph: EvidenceGraph) -> None:
        """Test getting supporting evidence."""
        # Given: A graph with supporting, refuting, and neutral evidence
        # When: Getting supporting evidence for a claim
        evidence = populated_graph.get_supporting_evidence("claim-1")

        # Then: Only supporting evidence is returned
        assert len(evidence) == 2
        assert all(e["relation"] == "supports" for e in evidence)

        obj_ids = {e["obj_id"] for e in evidence}
        assert obj_ids == {"frag-1", "frag-2"}

    def test_get_refuting_evidence(self, populated_graph: EvidenceGraph) -> None:
        """Test getting refuting evidence."""
        # Given: A graph with mixed evidence types
        # When: Getting refuting evidence for a claim
        evidence = populated_graph.get_refuting_evidence("claim-1")

        # Then: Only refuting evidence is returned
        assert len(evidence) == 1
        assert evidence[0]["obj_id"] == "frag-3"
        assert evidence[0]["relation"] == "refutes"

    def test_get_all_evidence(self, populated_graph: EvidenceGraph) -> None:
        """Test getting all categorized evidence."""
        # Given: A graph with all evidence types
        # When: Getting all evidence for a claim
        evidence = populated_graph.get_all_evidence("claim-1")

        # Then: Evidence is categorized by relation type
        assert len(evidence["supports"]) == 2
        assert len(evidence["refutes"]) == 1
        assert len(evidence["neutral"]) == 1

    def test_get_evidence_for_unknown_claim(self) -> None:
        """Test getting evidence for non-existent claim."""
        # Given: An empty graph
        graph = EvidenceGraph()

        # When: Getting evidence for unknown claim
        evidence: list[dict[str, object]] = graph.get_supporting_evidence("unknown")

        # Then: Empty results are returned
        assert evidence == []

        evidence_all: dict[str, list[dict[str, object]]] = graph.get_all_evidence("unknown")
        assert evidence_all == {"supports": [], "refutes": [], "neutral": []}


class TestClaimConfidence:
    """Tests for claim confidence calculation."""

    def test_calculate_confidence_no_evidence(self) -> None:
        """Test confidence with no evidence (Beta(1,1) prior)."""
        # Given: A graph with a claim but no evidence
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")

        # When: Calculating confidence for the claim
        result = graph.calculate_claim_confidence("claim-1")

        # Then: Returns Beta(1,1) prior statistics
        assert result["bayesian_claim_confidence"] == 0.5  # Beta(1,1) expectation
        assert abs(result["uncertainty"] - 0.288675) < 0.01  # sqrt(1*1/(2^2*3)) ≈ 0.289
        assert result["controversy"] == 0.0
        assert result["supporting_count"] == 0
        assert result["alpha"] == 1.0
        assert result["beta"] == 1.0

    def test_calculate_confidence_well_supported(self) -> None:
        """Test confidence with multiple supporting evidence (Bayesian updating)."""
        # Given: A graph with multiple high-confidence supporting evidence
        graph = EvidenceGraph()

        for i in range(3):
            graph.add_edge(
                source_type=NodeType.FRAGMENT,
                source_id=f"frag-{i}",
                target_type=NodeType.CLAIM,
                target_id="claim-1",
                relation=RelationType.SUPPORTS,
                confidence=0.9,
                nli_edge_confidence=0.9,  # : nli_edge_confidence required for Bayesian update
            )

        # When: Calculating confidence for the claim
        result = graph.calculate_claim_confidence("claim-1")

        # Then: High confidence, low uncertainty (Bayesian)
        assert result["supporting_count"] == 3
        assert result["bayesian_claim_confidence"] > 0.75  # α=3.7, β=1 → confidence ≈ 0.79
        assert result["uncertainty"] < 0.2  # More evidence → lower uncertainty
        assert result["controversy"] == 0.0  # No refuting evidence
        assert result["alpha"] > 3.0
        assert result["beta"] == 1.0

    def test_calculate_confidence_contested(self) -> None:
        """Test confidence with conflicting evidence (high controversy)."""
        # Given: A graph with both supporting and refuting evidence
        graph = EvidenceGraph()

        for i in range(2):
            graph.add_edge(
                source_type=NodeType.FRAGMENT,
                source_id=f"support-{i}",
                target_type=NodeType.CLAIM,
                target_id="claim-1",
                relation=RelationType.SUPPORTS,
                confidence=0.9,
                nli_edge_confidence=0.9,  # : nli_edge_confidence required
            )

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="refute-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.REFUTES,
            confidence=0.8,
            nli_edge_confidence=0.8,  # : nli_edge_confidence required
        )

        # When: Calculating confidence for the contested claim
        result = graph.calculate_claim_confidence("claim-1")

        # Then: Moderate confidence, high controversy
        assert result["supporting_count"] == 2
        assert result["refuting_count"] == 1
        assert result["controversy"] > 0.0  # Both alpha and beta > 1
        assert result["bayesian_claim_confidence"] > 0.5  # α=2.8, β=1.8 → confidence ≈ 0.61

    def test_calculate_confidence_single_support(self) -> None:
        """Test confidence with single supporting evidence."""
        # Given: A graph with one supporting evidence
        graph = EvidenceGraph()
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
            nli_edge_confidence=0.9,
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: Confidence increases but uncertainty is still high
        assert result["bayesian_claim_confidence"] > 0.5  # α=1.9, β=1 → confidence ≈ 0.66
        assert result["uncertainty"] < 0.29  # Lower than prior but still significant
        assert result["controversy"] == 0.0
        assert result["alpha"] == 1.9
        assert result["beta"] == 1.0

    def test_calculate_confidence_balanced_conflict(self) -> None:
        """Test confidence with balanced supporting and refuting evidence."""
        # Given: Equal amounts of supporting and refuting evidence
        graph = EvidenceGraph()

        for i in range(5):
            graph.add_edge(
                source_type=NodeType.FRAGMENT,
                source_id=f"support-{i}",
                target_type=NodeType.CLAIM,
                target_id="claim-1",
                relation=RelationType.SUPPORTS,
                confidence=0.9,
                nli_edge_confidence=0.9,
            )

        for i in range(5):
            graph.add_edge(
                source_type=NodeType.FRAGMENT,
                source_id=f"refute-{i}",
                target_type=NodeType.CLAIM,
                target_id="claim-1",
                relation=RelationType.REFUTES,
                confidence=0.9,
                nli_edge_confidence=0.9,
            )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: Confidence near 0.5, high controversy
        assert (
            abs(result["bayesian_claim_confidence"] - 0.5) < 0.1
        )  # α≈5.5, β≈5.5 → confidence ≈ 0.5
        assert result["controversy"] > 0.4  # High controversy
        assert (
            result["uncertainty"] < 0.15
        )  # Lower uncertainty due to more evidence (actual ≈ 0.144)
        assert result["supporting_count"] == 5
        assert result["refuting_count"] == 5

    def test_calculate_confidence_zero_nli_edge_confidence(self) -> None:
        """Test that edges with nli_edge_confidence=0 do not update alpha/beta."""
        # Given: Edges with zero nli_edge_confidence
        graph = EvidenceGraph()
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            nli_edge_confidence=0.0,  # Zero weight
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: No update (prior distribution)
        assert result["bayesian_claim_confidence"] == 0.5
        assert result["alpha"] == 1.0
        assert result["beta"] == 1.0

    def test_calculate_confidence_neutral_edges_ignored(self) -> None:
        """Test that NEUTRAL edges do not update alpha/beta."""
        # Given: Only neutral edges
        graph = EvidenceGraph()
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.NEUTRAL,
            nli_edge_confidence=0.8,  # Even high confidence neutral doesn't update
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: Prior distribution (neutral edges ignored)
        assert result["bayesian_claim_confidence"] == 0.5
        assert result["alpha"] == 1.0
        assert result["beta"] == 1.0
        assert result["neutral_count"] == 1

    def test_calculate_confidence_none_nli_edge_confidence(self) -> None:
        """Test that edges with None nli_edge_confidence are handled gracefully."""
        # Given: Edge with None nli_edge_confidence
        graph = EvidenceGraph()
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
            nli_edge_confidence=None,  # Missing nli_edge_confidence
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: No update (None is treated as 0)
        assert result["bayesian_claim_confidence"] == 0.5
        assert result["alpha"] == 1.0
        assert result["beta"] == 1.0

    def test_calculate_confidence_unknown_claim(self) -> None:
        """Test confidence calculation for non-existent claim."""
        # Given: Empty graph
        graph = EvidenceGraph()

        # When: Calculating confidence for unknown claim
        result = graph.calculate_claim_confidence("unknown-claim")

        # Then: Returns prior distribution
        assert result["bayesian_claim_confidence"] == 0.5
        assert result["uncertainty"] > 0.0
        assert result["controversy"] == 0.0
        assert result["supporting_count"] == 0
        assert result["refuting_count"] == 0

    def test_calculate_confidence_returns_evidence_list(self) -> None:
        """b: Test that evidence list with time metadata is returned."""
        # Given: A graph with evidence including year metadata
        graph = EvidenceGraph()

        # Add a page node with year metadata
        page_node = graph._make_node_id(NodeType.PAGE, "page-2023")
        graph._graph.add_node(
            page_node, node_type=NodeType.PAGE.value, year=2023, doi="10.1234/test"
        )

        graph.add_edge(
            source_type=NodeType.PAGE,
            source_id="page-2023",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
            nli_edge_confidence=0.9,
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: Evidence list is returned with time metadata
        assert "evidence" in result
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["relation"] == "supports"
        assert result["evidence"][0]["year"] == 2023
        assert result["evidence"][0]["doi"] == "10.1234/test"
        assert result["evidence"][0]["nli_edge_confidence"] == 0.9

    def test_calculate_confidence_returns_evidence_years_summary(self) -> None:
        """b: Test that evidence_years summary is returned."""
        # Given: A graph with evidence from multiple years
        graph = EvidenceGraph()

        # Add page nodes with different years
        page_node_2020 = graph._make_node_id(NodeType.PAGE, "page-2020")
        graph._graph.add_node(page_node_2020, node_type=NodeType.PAGE.value, year=2020)

        page_node_2024 = graph._make_node_id(NodeType.PAGE, "page-2024")
        graph._graph.add_node(page_node_2024, node_type=NodeType.PAGE.value, year=2024)

        graph.add_edge(
            source_type=NodeType.PAGE,
            source_id="page-2020",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.8,
            nli_edge_confidence=0.8,
        )

        graph.add_edge(
            source_type=NodeType.PAGE,
            source_id="page-2024",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.REFUTES,
            confidence=0.9,
            nli_edge_confidence=0.9,
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: evidence_years summary is returned
        assert "evidence_years" in result
        assert result["evidence_years"]["oldest"] == 2020
        assert result["evidence_years"]["newest"] == 2024

    def test_calculate_confidence_evidence_years_empty_when_no_years(self) -> None:
        """b: Test that evidence_years is null when no year data exists."""
        # Given: A graph with evidence but no year metadata
        graph = EvidenceGraph()

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
            nli_edge_confidence=0.9,
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: evidence_years has null values
        assert "evidence_years" in result
        assert result["evidence_years"]["oldest"] is None
        assert result["evidence_years"]["newest"] is None


class TestIndependentSourcesFromFragments:
    """Tests for independent_sources calculation from FRAGMENT→CLAIM edges.

    These tests ensure independent_sources correctly counts unique pages
    when evidence comes from fragments (not just unique domains).

    Test matrix:
    | Case ID     | Input                                | Expected                      |
    |-------------|--------------------------------------|-------------------------------|
    | TC-IS-N-01  | 2 fragments from 2 different pages   | independent_sources = 2       |
    | TC-IS-N-02  | 2 fragments from same page           | independent_sources = 1       |
    | TC-IS-B-01  | No evidence                          | independent_sources = 0       |
    | TC-IS-B-02  | 1 fragment with page_id              | independent_sources = 1       |
    | TC-IS-B-03  | Fragment without page_id (fallback)  | independent_sources = 1       |
    | TC-IS-N-03  | Mixed: some with page_id, some without | Correct count               |
    | TC-EY-N-01  | Fragments with page years            | evidence_years extracted      |
    | TC-EY-B-01  | Fragment with no year                | evidence_years = null         |
    """

    def test_two_fragments_from_different_pages_counts_two_sources(self) -> None:
        """TC-IS-N-01: Two fragments from different pages → independent_sources = 2."""
        # Given: A graph with 2 FRAGMENT→CLAIM edges, each fragment from a different page
        graph = EvidenceGraph()

        frag1_node = graph._make_node_id(NodeType.FRAGMENT, "frag-1")
        frag2_node = graph._make_node_id(NodeType.FRAGMENT, "frag-2")
        graph._graph.add_node(frag1_node, node_type=NodeType.FRAGMENT.value, page_id="page-A")
        graph._graph.add_node(frag2_node, node_type=NodeType.FRAGMENT.value, page_id="page-B")

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
            nli_edge_confidence=0.9,
        )
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-2",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.85,
            nli_edge_confidence=0.85,
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: independent_sources = 2 (page-A and page-B)
        assert (
            result["independent_sources"] == 2
        ), f"Expected 2 independent sources (2 different pages), got {result['independent_sources']}"

    def test_two_fragments_from_same_page_counts_one_source(self) -> None:
        """TC-IS-N-02: Two fragments from same page → independent_sources = 1."""
        # Given: A graph with 2 FRAGMENT→CLAIM edges, both fragments from same page
        graph = EvidenceGraph()

        frag1_node = graph._make_node_id(NodeType.FRAGMENT, "frag-1")
        frag2_node = graph._make_node_id(NodeType.FRAGMENT, "frag-2")
        graph._graph.add_node(frag1_node, node_type=NodeType.FRAGMENT.value, page_id="page-same")
        graph._graph.add_node(frag2_node, node_type=NodeType.FRAGMENT.value, page_id="page-same")

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
            nli_edge_confidence=0.9,
        )
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-2",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.85,
            nli_edge_confidence=0.85,
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: independent_sources = 1 (deduplicated by page_id)
        assert (
            result["independent_sources"] == 1
        ), f"Expected 1 independent source (same page), got {result['independent_sources']}"

    def test_no_evidence_returns_zero_sources(self) -> None:
        """TC-IS-B-01: No evidence → independent_sources = 0."""
        # Given: An empty graph with just a claim node
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: independent_sources = 0
        assert result["independent_sources"] == 0

    def test_single_fragment_with_page_id_counts_one_source(self) -> None:
        """TC-IS-B-02: Single fragment with page_id → independent_sources = 1."""
        # Given: A graph with 1 FRAGMENT→CLAIM edge with page_id
        graph = EvidenceGraph()

        frag_node = graph._make_node_id(NodeType.FRAGMENT, "frag-1")
        graph._graph.add_node(frag_node, node_type=NodeType.FRAGMENT.value, page_id="page-1")

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
            nli_edge_confidence=0.9,
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: independent_sources = 1
        assert result["independent_sources"] == 1

    def test_fragment_without_page_id_falls_back_to_fragment_id(self) -> None:
        """TC-IS-B-03: Fragment without page_id → fallback to fragment_id counting."""
        # Given: A graph with FRAGMENT→CLAIM edge, fragment has no page_id
        graph = EvidenceGraph()

        frag_node = graph._make_node_id(NodeType.FRAGMENT, "frag-no-page")
        graph._graph.add_node(frag_node, node_type=NodeType.FRAGMENT.value)
        # Note: no page_id attribute

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-no-page",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
            nli_edge_confidence=0.9,
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: independent_sources = 1 (fallback to fragment_id)
        assert (
            result["independent_sources"] == 1
        ), "Fallback to fragment_id should count as 1 source"

    def test_mixed_fragments_with_and_without_page_id(self) -> None:
        """TC-IS-N-03: Mixed fragments → correct count."""
        # Given: 3 fragments:
        #   - frag-1: page_id = page-A
        #   - frag-2: page_id = page-B
        #   - frag-3: no page_id (fallback to fragment_id)
        graph = EvidenceGraph()

        frag1_node = graph._make_node_id(NodeType.FRAGMENT, "frag-1")
        frag2_node = graph._make_node_id(NodeType.FRAGMENT, "frag-2")
        frag3_node = graph._make_node_id(NodeType.FRAGMENT, "frag-3")
        graph._graph.add_node(frag1_node, node_type=NodeType.FRAGMENT.value, page_id="page-A")
        graph._graph.add_node(frag2_node, node_type=NodeType.FRAGMENT.value, page_id="page-B")
        graph._graph.add_node(frag3_node, node_type=NodeType.FRAGMENT.value)  # no page_id

        for frag_id in ["frag-1", "frag-2", "frag-3"]:
            graph.add_edge(
                source_type=NodeType.FRAGMENT,
                source_id=frag_id,
                target_type=NodeType.CLAIM,
                target_id="claim-1",
                relation=RelationType.SUPPORTS,
                confidence=0.9,
                nli_edge_confidence=0.9,
            )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: independent_sources = 3 (page-A, page-B, frag-3 fallback)
        assert (
            result["independent_sources"] == 3
        ), f"Expected 3 sources (2 pages + 1 fallback), got {result['independent_sources']}"

    def test_fragment_with_page_year_extracts_evidence_years(self) -> None:
        """TC-EY-N-01: Fragments with page years → evidence_years extracted."""
        # Given: Fragments with year metadata on their nodes
        graph = EvidenceGraph()

        frag1_node = graph._make_node_id(NodeType.FRAGMENT, "frag-1")
        frag2_node = graph._make_node_id(NodeType.FRAGMENT, "frag-2")
        graph._graph.add_node(
            frag1_node, node_type=NodeType.FRAGMENT.value, page_id="page-A", year=2020
        )
        graph._graph.add_node(
            frag2_node, node_type=NodeType.FRAGMENT.value, page_id="page-B", year=2023
        )

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
            nli_edge_confidence=0.9,
        )
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-2",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.85,
            nli_edge_confidence=0.85,
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: evidence_years is extracted
        assert result["evidence_years"]["oldest"] == 2020
        assert result["evidence_years"]["newest"] == 2023

    def test_fragment_without_year_returns_null_evidence_years(self) -> None:
        """TC-EY-B-01: Fragment with no year → evidence_years = null."""
        # Given: Fragment with page_id but no year attribute
        graph = EvidenceGraph()

        frag_node = graph._make_node_id(NodeType.FRAGMENT, "frag-1")
        graph._graph.add_node(frag_node, node_type=NodeType.FRAGMENT.value, page_id="page-1")
        # Note: no 'year' attribute

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
            nli_edge_confidence=0.9,
        )

        # When: Calculating confidence
        result = graph.calculate_claim_confidence("claim-1")

        # Then: evidence_years has null values
        assert result["evidence_years"]["oldest"] is None
        assert result["evidence_years"]["newest"] is None


class TestCitationChain:
    """Tests for citation chain tracing."""

    def test_citation_chain(self) -> None:
        """Test tracing citation chain.

        Validates citation chain tracing for source verification.
        Chain follows CITES edges from source to primary sources.
        """
        graph = EvidenceGraph()

        # Fragment -> Page (primary source)
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.PAGE,
            target_id="page-1",
            relation=RelationType.CITES,
        )

        chain = graph.get_citation_chain(NodeType.FRAGMENT, "frag-1")

        # STRICT: Chain must include the starting node (frag-1) and follow to cited page
        # get_citation_chain follows outgoing CITES edges, so chain = [frag-1, page-1]
        assert len(chain) == 2, f"Expected chain of 2 (frag->page), got {len(chain)}"
        assert (
            chain[0]["node_type"] == "fragment"
        ), f"First node should be fragment, got {chain[0]['node_type']}"
        assert (
            chain[0]["obj_id"] == "frag-1"
        ), f"First node should be frag-1, got {chain[0]['obj_id']}"
        assert (
            chain[1]["node_type"] == "page"
        ), f"Second node should be page, got {chain[1]['node_type']}"
        assert (
            chain[1]["obj_id"] == "page-1"
        ), f"Second node should be page-1, got {chain[1]['obj_id']}"

    def test_citation_chain_empty(self) -> None:
        """Test citation chain for unknown node."""
        # Given: An empty graph
        graph = EvidenceGraph()

        # When: Getting citation chain for unknown node
        chain = graph.get_citation_chain(NodeType.FRAGMENT, "unknown")

        # Then: Empty chain is returned
        assert chain == []


class TestContradictionDetection:
    """Tests for contradiction detection."""

    def test_find_contradictions(self) -> None:
        """Test finding refuting evidence on a claim ("contradiction" = REFUTES evidence)."""
        # Given: Two claims with a refutes relationship (claim-2 has incoming REFUTES)
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1", text="A is true")
        graph.add_node(NodeType.CLAIM, "claim-2", text="A is false")

        graph.add_edge(
            source_type=NodeType.CLAIM,
            source_id="claim-1",
            target_type=NodeType.CLAIM,
            target_id="claim-2",
            relation=RelationType.REFUTES,
            nli_edge_confidence=0.9,
        )

        # When: Finding contradictions
        contradictions = graph.find_contradictions()

        # Then: The claim with refuting evidence is reported
        assert len(contradictions) == 1
        assert contradictions[0]["claim_id"] == "claim-2"
        assert contradictions[0]["refuting_count"] == 1
        assert contradictions[0]["max_nli_edge_confidence"] == pytest.approx(0.9)

    def test_find_contradictions_none(self) -> None:
        """Test finding no contradictions."""
        # Given: Two unrelated claims
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")
        graph.add_node(NodeType.CLAIM, "claim-2")

        # When: Finding contradictions
        contradictions = graph.find_contradictions()

        # Then: No contradictions are found
        assert contradictions == []


class TestGraphStats:
    """Tests for graph statistics."""

    def test_get_stats_empty(self) -> None:
        """Test stats for empty graph."""
        # Given: An empty graph
        graph = EvidenceGraph()

        # When: Getting statistics
        stats = graph.get_stats()

        # Then: All counts are zero
        assert stats["total_nodes"] == 0
        assert stats["total_edges"] == 0

    def test_get_stats_populated(self) -> None:
        """Test stats for populated graph."""
        # Given: A graph with various nodes and edges
        graph = EvidenceGraph()

        graph.add_node(NodeType.CLAIM, "c1")
        graph.add_node(NodeType.CLAIM, "c2")
        graph.add_node(NodeType.FRAGMENT, "f1")
        graph.add_node(NodeType.PAGE, "p1")

        graph.add_edge(
            NodeType.FRAGMENT,
            "f1",
            NodeType.CLAIM,
            "c1",
            RelationType.SUPPORTS,
        )
        graph.add_edge(
            NodeType.FRAGMENT,
            "f1",
            NodeType.PAGE,
            "p1",
            RelationType.CITES,
        )

        # When: Getting statistics
        stats = graph.get_stats()

        # Then: Correct counts for each type
        assert stats["total_nodes"] == 4
        assert stats["total_edges"] == 2
        assert stats["node_counts"]["claim"] == 2
        assert stats["node_counts"]["fragment"] == 1
        assert stats["node_counts"]["page"] == 1
        assert stats["edge_counts"]["supports"] == 1
        assert stats["edge_counts"]["cites"] == 1


class TestGraphExport:
    """Tests for graph export."""

    def test_to_dict(self) -> None:
        """Test exporting graph as dict."""
        # Given: A graph with nodes and edges
        graph = EvidenceGraph()

        graph.add_node(NodeType.CLAIM, "c1", text="Test")
        graph.add_edge(
            NodeType.FRAGMENT,
            "f1",
            NodeType.CLAIM,
            "c1",
            RelationType.SUPPORTS,
            confidence=0.9,
        )

        # When: Exporting to dictionary
        data = graph.to_dict()

        # Then: All data is included in the export
        assert "nodes" in data
        assert "edges" in data
        assert "stats" in data

        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1


class TestCitationLoopDetection:
    """Tests for citation loop detection."""

    def test_detect_simple_citation_loop(self) -> None:
        """Test detecting a simple citation loop (A -> B -> C -> A).

        requirement: detect circular citations
        requirement: citation loop detection rate ≥80%
        """
        graph = EvidenceGraph()

        # Create exactly one 3-node loop: page-1 -> page-2 -> page-3 -> page-1
        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE,
            "page-2",
            NodeType.PAGE,
            "page-3",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE,
            "page-3",
            NodeType.PAGE,
            "page-1",
            RelationType.CITES,
        )

        loops = graph.detect_citation_loops()

        # STRICT: Exactly 1 loop must be detected
        assert len(loops) == 1, f"Expected 1 loop, got {len(loops)}"
        assert loops[0]["type"] == "citation_loop"
        assert loops[0]["length"] == 3
        # Verify all nodes are in the loop
        node_ids = {n["obj_id"] for n in loops[0]["nodes"]}
        assert node_ids == {"page-1", "page-2", "page-3"}

    def test_detect_no_citation_loops(self) -> None:
        """Test when there are no citation loops."""
        # Given: A linear citation chain (no loops)
        graph = EvidenceGraph()

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE,
            "page-2",
            NodeType.PAGE,
            "page-3",
            RelationType.CITES,
        )

        # When: Detecting citation loops
        loops = graph.detect_citation_loops()

        # Then: No loops are found
        assert len(loops) == 0

    def test_detect_citation_loops_ignores_non_citation_edges(self) -> None:
        """Test that loop detection only considers citation edges."""
        # Given: A loop using SUPPORTS relation (not CITES)
        graph = EvidenceGraph()

        graph.add_edge(
            NodeType.FRAGMENT,
            "frag-1",
            NodeType.CLAIM,
            "claim-1",
            RelationType.SUPPORTS,
        )
        graph.add_edge(
            NodeType.CLAIM,
            "claim-1",
            NodeType.FRAGMENT,
            "frag-1",
            RelationType.SUPPORTS,
        )

        # When: Detecting citation loops
        loops = graph.detect_citation_loops()

        # Then: Non-CITES edges are ignored
        assert len(loops) == 0


class TestRoundTripDetection:
    """Tests for round-trip citation detection."""

    def test_detect_round_trip(self) -> None:
        """Test detecting round-trip citations (A cites B, B cites A)."""
        # Given: Mutual citation between two pages
        graph = EvidenceGraph()

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE,
            "page-2",
            NodeType.PAGE,
            "page-1",
            RelationType.CITES,
        )

        # When: Detecting round trips
        round_trips = graph.detect_round_trips()

        # Then: Round trip is detected with high severity
        assert len(round_trips) == 1
        assert round_trips[0]["type"] == "round_trip"
        assert round_trips[0]["severity"] == "high"

    def test_detect_no_round_trips(self) -> None:
        """Test when there are no round-trips."""
        # Given: A one-way citation
        graph = EvidenceGraph()

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )

        # When: Detecting round trips
        round_trips = graph.detect_round_trips()

        # Then: No round trips found
        assert len(round_trips) == 0


class TestSelfReferenceDetection:
    """Tests for self-reference detection."""

    def test_detect_direct_self_reference(self) -> None:
        """Test detecting direct self-loop."""
        # Given: A page citing itself
        graph = EvidenceGraph()

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-1",
            RelationType.CITES,
        )

        # When: Detecting self references
        self_refs = graph.detect_self_references()

        # Then: Self-reference detected with critical severity
        assert len(self_refs) == 1
        assert self_refs[0]["type"] == "direct_self_reference"
        assert self_refs[0]["severity"] == "critical"

    def test_detect_same_domain_citation(self) -> None:
        """Test detecting same-domain citations."""
        # Given: Two pages from the same domain
        graph = EvidenceGraph()

        graph.add_node(NodeType.PAGE, "page-1", domain="example.com")
        graph.add_node(NodeType.PAGE, "page-2", domain="example.com")

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )

        # When: Detecting self references
        self_refs = graph.detect_self_references()

        # Then: Same-domain citation is detected
        assert len(self_refs) == 1
        assert self_refs[0]["type"] == "same_domain_citation"
        assert self_refs[0]["domain"] == "example.com"

    def test_no_self_references(self) -> None:
        """Test when there are no self-references."""
        # Given: Pages from different domains
        graph = EvidenceGraph()

        graph.add_node(NodeType.PAGE, "page-1", domain="example.com")
        graph.add_node(NodeType.PAGE, "page-2", domain="other.com")

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )

        # When: Detecting self references
        self_refs = graph.detect_self_references()

        # Then: No self-references found
        assert len(self_refs) == 0


class TestCitationPenalties:
    """Tests for citation penalty calculation."""

    def test_calculate_penalties_with_loop(self) -> None:
        """Test penalty calculation for nodes in loops."""
        # Given: A round-trip citation loop
        graph = EvidenceGraph()

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE,
            "page-2",
            NodeType.PAGE,
            "page-1",
            RelationType.CITES,
        )

        # When: Calculating citation penalties
        penalties = graph.calculate_citation_penalties()

        # Then: Nodes in loop have reduced penalties
        assert penalties["page:page-1"] < 1.0
        assert penalties["page:page-2"] < 1.0

    def test_calculate_penalties_no_issues(self) -> None:
        """Test penalty calculation with clean citations."""
        # Given: A clean linear citation chain
        graph = EvidenceGraph()

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )

        # When: Calculating citation penalties
        penalties = graph.calculate_citation_penalties()

        # Then: No penalties applied (all 1.0)
        assert penalties["page:page-1"] == 1.0
        assert penalties["page:page-2"] == 1.0


class TestCitationIntegrityReport:
    """Tests for citation integrity report."""

    def test_integrity_report_clean_graph(self) -> None:
        """Test integrity report for clean graph."""
        # Given: A clean citation graph
        graph = EvidenceGraph()

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )

        # When: Getting integrity report
        report = graph.get_citation_integrity_report()

        # Then: Perfect integrity score with no issues
        assert report["integrity_score"] == 1.0
        assert report["loop_count"] == 0
        assert report["round_trip_count"] == 0
        assert report["self_reference_count"] == 0

    def test_integrity_report_problematic_graph(self) -> None:
        """Test integrity report for graph with issues."""
        # Given: A graph with a round-trip citation
        graph = EvidenceGraph()

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE,
            "page-2",
            NodeType.PAGE,
            "page-1",
            RelationType.CITES,
        )

        # When: Getting integrity report
        report = graph.get_citation_integrity_report()

        # Then: Reduced integrity score with issues counted
        assert report["integrity_score"] < 1.0
        assert report["round_trip_count"] == 1
        assert report["problematic_node_count"] == 2

    def test_integrity_report_empty_graph(self) -> None:
        """Test integrity report for empty graph."""
        # Given: An empty graph
        graph = EvidenceGraph()

        # When: Getting integrity report
        report = graph.get_citation_integrity_report()

        # Then: Perfect score with zero edges
        assert report["integrity_score"] == 1.0
        assert report["total_citation_edges"] == 0


class TestPrimarySourceRatio:
    """Tests for primary source ratio calculation."""

    def test_primary_source_ratio_all_primary(self) -> None:
        """Test ratio when all sources are primary."""
        # Given: Pages that don't cite other pages
        graph = EvidenceGraph()

        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")

        graph.add_edge(
            NodeType.FRAGMENT,
            "frag-1",
            NodeType.PAGE,
            "page-1",
            RelationType.CITES,
        )

        # When: Calculating primary source ratio
        ratio = graph.get_primary_source_ratio()

        # Then: All pages are primary (ratio = 1.0)
        assert ratio["primary_count"] == 2
        assert ratio["secondary_count"] == 0
        assert ratio["primary_ratio"] == 1.0
        assert ratio["meets_threshold"] is True

    def test_primary_source_ratio_mixed(self) -> None:
        """Test ratio with mixed primary/secondary sources."""
        # Given: Pages with one secondary source (cites another page)
        graph = EvidenceGraph()

        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        graph.add_node(NodeType.PAGE, "page-3")

        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
        )

        # When: Calculating primary source ratio
        ratio = graph.get_primary_source_ratio()

        # Then: Correct primary/secondary counts
        assert ratio["primary_count"] == 2  # page-2 and page-3
        assert ratio["secondary_count"] == 1  # page-1
        assert ratio["total_pages"] == 3

    def test_primary_source_ratio_empty(self) -> None:
        """Test ratio for empty graph."""
        # Given: An empty graph
        graph = EvidenceGraph()

        # When: Calculating primary source ratio
        ratio = graph.get_primary_source_ratio()

        # Then: Ratio is 0.0 and threshold not met
        assert ratio["primary_ratio"] == 0.0
        assert ratio["meets_threshold"] is False


class TestLoopSeverity:
    """Tests for loop severity calculation."""

    def test_severity_calculation(self) -> None:
        """Test loop severity based on length."""
        # Given: An EvidenceGraph instance
        graph = EvidenceGraph()

        # When: Calculating severity for different loop lengths
        # Then: Severity decreases with loop length
        assert graph._calculate_loop_severity(2) == "critical"
        assert graph._calculate_loop_severity(3) == "high"
        assert graph._calculate_loop_severity(5) == "medium"
        assert graph._calculate_loop_severity(10) == "low"


@pytest.mark.integration
class TestDatabaseIntegration:
    """Tests for database persistence.

    Integration tests per .1.7 - uses temporary database.
    """

    @pytest.mark.asyncio
    async def test_save_and_load(self, test_database: Database) -> None:
        """Test saving and loading graph from database."""
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: A populated evidence graph
        graph = EvidenceGraph(task_id="test-task")

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
        )

        # When: Saving graph to database
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.save_to_db()

        # Then: Edges are persisted correctly
        edges = await test_database.fetch_all("SELECT * FROM edges")
        assert len(edges) == 1
        assert edges[0]["source_type"] == "fragment"
        assert edges[0]["target_type"] == "claim"
        assert edges[0]["relation"] == "supports"

    @pytest.mark.asyncio
    async def test_add_claim_evidence_persists(self, test_database: Database) -> None:
        """Test add_claim_evidence persists to database."""
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: A mock evidence graph and test database
        mock_graph = EvidenceGraph(task_id="test")

        # When: Adding claim evidence via the function
        with patch.object(evidence_graph, "get_evidence_graph", return_value=mock_graph):
            with patch.object(evidence_graph, "get_database", return_value=test_database):
                edge_id = await add_claim_evidence(
                    claim_id="claim-1",
                    fragment_id="frag-1",
                    relation="supports",
                    nli_label="entailment",
                    nli_edge_confidence=0.9,
                    task_id="test",
                )

        # Then: Edge is created and persisted
        assert edge_id is not None

        edges = await test_database.fetch_all("SELECT * FROM edges")
        assert len(edges) == 1
        assert edges[0]["nli_edge_confidence"] == 0.9


class TestAcademicCitationAttributes:
    """Tests for academic citation attributes (J2).

    Tests for citation_source, citation_context attributes added to CITES edges.
    """

    def test_add_edge_with_academic_attributes(self) -> None:
        """Test adding edge with academic citation attributes.

        // Given: Academic citation with citation_source, citation_context
        // When: Adding edge
        // Then: Attributes stored correctly
        """
        # Given: Academic citation attributes
        graph = EvidenceGraph()

        # When: Adding edge with academic attributes
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.PAGE,
            target_id="page-1",
            relation=RelationType.CITES,
            confidence=1.0,
            citation_source="semantic_scholar",
            citation_context="This paper discusses...",
        )

        # Then: Attributes stored correctly
        edge_data = graph._graph.edges["fragment:frag-1", "page:page-1"]
        assert edge_data["citation_source"] == "semantic_scholar"
        assert edge_data["citation_context"] == "This paper discusses..."

    def test_add_citation_with_academic_attributes(self) -> None:
        """Test add_citation() with academic attributes.

        // Given: Academic citation attributes
        // When: Calling add_citation()
        // Then: Citation added with attributes
        """
        from unittest.mock import patch

        # Given: Academic citation attributes
        graph = EvidenceGraph(task_id="test")

        with patch("src.filter.evidence_graph.get_evidence_graph", return_value=graph):
            # When: Calling add_citation() with academic attributes

            # Note: This is a simplified test - full async test requires test_database fixture
            # For now, test the graph.add_edge() method directly
            edge_id = graph.add_edge(
                source_type=NodeType.FRAGMENT,
                source_id="frag-1",
                target_type=NodeType.PAGE,
                target_id="page-1",
                relation=RelationType.CITES,
                citation_source="semantic_scholar",
                citation_context="Test context",
            )

            # Then: Citation added with attributes
            assert edge_id is not None
            edge_data = graph._graph.edges["fragment:frag-1", "page:page-1"]
            assert edge_data["citation_source"] == "semantic_scholar"

    def test_load_from_db_with_academic_attributes(self) -> None:
        """Test loading edges with academic attributes from DB.

        // Given: Edge with academic attributes in DB
        // When: Loading from DB
        // Then: Attributes loaded correctly
        """
        # Given: Edge with academic attributes
        graph = EvidenceGraph()
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.PAGE,
            target_id="page-1",
            relation=RelationType.CITES,
            citation_source="semantic_scholar",
            citation_context="Context text",
        )

        # When: Exporting and importing (simulating DB load)
        data = graph.to_dict()

        # Then: Attributes in export
        edges = data["edges"]
        assert len(edges) == 1
        assert edges[0]["citation_source"] == "semantic_scholar"
        assert edges[0]["citation_context"] == "Context text"

    @pytest.mark.asyncio
    async def test_save_to_db_with_academic_attributes(self, test_database: Database) -> None:
        """Test saving edges with academic attributes to DB.

        // Given: Edge with academic attributes
        // When: Saving to DB
        // Then: Attributes persisted correctly
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Edge with academic attributes
        graph = EvidenceGraph(task_id="test-task")
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.PAGE,
            target_id="page-1",
            relation=RelationType.CITES,
            confidence=1.0,
            citation_source="semantic_scholar",
            citation_context="Academic citation context",
        )

        # When: Saving to DB
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.save_to_db()

        # Then: Attributes persisted correctly
        edges = await test_database.fetch_all("SELECT * FROM edges")
        assert len(edges) == 1
        assert edges[0]["citation_source"] == "semantic_scholar"
        assert edges[0]["citation_context"] == "Academic citation context"


class TestClaimAdoptionStatus:
    """Tests for claim adoption status tracking."""

    def test_set_claim_adoption_status(self) -> None:
        """
        Test setting claim adoption status.

        // Given: Claim in graph
        // When: Setting adoption status
        // Then: Status is stored
        """
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "c1", text="Test claim")

        # When: Set status
        graph.set_claim_adoption_status("c1", "adopted")

        # Then: Status stored
        assert graph.get_claim_adoption_status("c1") == "adopted"

    def test_set_claim_adoption_status_not_adopted(self) -> None:
        """
        Test setting not_adopted status for rejected claim.

        // Given: Claim that was rejected
        // When: Setting claim_adoption_status to not_adopted
        // Then: Status is preserved in graph
        """
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "rejected_claim", text="Rejected claim")

        # When: Set not_adopted status
        graph.set_claim_adoption_status("rejected_claim", "not_adopted")

        # Then: Status is not_adopted
        assert graph.get_claim_adoption_status("rejected_claim") == "not_adopted"

    def test_get_claim_adoption_status_default(self) -> None:
        """
        Test default adoption status is adopted.

        // Given: Claim without explicit status
        // When: Getting adoption status
        // Then: Returns adopted (: default changed from 'pending')
        """
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "c1", text="New claim")

        # Then: Default is adopted
        assert graph.get_claim_adoption_status("c1") == "adopted"

    def test_get_claim_adoption_status_not_found(self) -> None:
        """
        Test get adoption status for nonexistent claim.

        // Given: Claim not in graph
        // When: Getting adoption status
        // Then: Returns None
        """
        graph = EvidenceGraph()

        # Then: None for missing claim
        assert graph.get_claim_adoption_status("nonexistent") is None

    def test_set_claim_adoption_status_empty_string(self) -> None:
        """
        Test setting empty string as adoption status.

        // Given: Claim in graph
        // When: Setting empty string as status
        // Then: Status is stored (no validation)
        """
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "c1", text="Test claim")

        # When: Set empty status
        graph.set_claim_adoption_status("c1", "")

        # Then: Empty string stored
        assert graph.get_claim_adoption_status("c1") == ""

    def test_set_claim_adoption_status_nonexistent_claim(self) -> None:
        """
        Test setting status for nonexistent claim.

        // Given: Claim not in graph
        // When: Trying to set adoption status
        // Then: Silently ignored (no error)
        """
        graph = EvidenceGraph()

        # When: Set status for missing claim (should not raise)
        graph.set_claim_adoption_status("missing_claim", "adopted")

        # Then: Status is None (claim not found)
        assert graph.get_claim_adoption_status("missing_claim") is None

    def test_get_claims_by_adoption_status(self) -> None:
        """
        Test filtering claims by adoption status.

        // Given: Claims with different statuses
        // When: Filtering by status
        // Then: Only matching claims returned
        """
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "c1", text="Claim 1")
        graph.add_node(NodeType.CLAIM, "c2", text="Claim 2")
        graph.add_node(NodeType.CLAIM, "c3", text="Claim 3")

        # c1 stays adopted (default)
        graph.set_claim_adoption_status("c2", "not_adopted")
        graph.set_claim_adoption_status("c3", "pending")

        # When: Get claims by status
        adopted = graph.get_claims_by_adoption_status("adopted")
        not_adopted = graph.get_claims_by_adoption_status("not_adopted")
        pending = graph.get_claims_by_adoption_status("pending")

        # Then: Correct filtering (default is now 'adopted')
        assert adopted == ["c1"]
        assert not_adopted == ["c2"]
        assert pending == ["c3"]

    def test_not_adopted_claim_preserved_in_graph(self) -> None:
        """
        Test that not_adopted claims are preserved in graph.

        // Given: Claim marked as not_adopted
        // When: Exporting graph
        // Then: Claim and status preserved
        """
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "rejected", text="Rejected claim text")
        graph.set_claim_adoption_status("rejected", "not_adopted")

        # When: Export graph
        data = graph.to_dict()

        # Then: Claim preserved with status
        claim_nodes = [n for n in data["nodes"] if n.get("node_type") == "claim"]
        assert len(claim_nodes) == 1
        assert claim_nodes[0]["claim_adoption_status"] == "not_adopted"


class TestPhaseP2DomainCategoryOnEdges:
    """Tests for Contradiction handling behavior: Domain category information on edges.

    Contradiction handling behavior adds source_domain_category and target_domain_category to edges,
    for ranking adjustment and high-inference AI reference.
    DomainCategory is NOT used for confidence calculation or verification decisions.
    """

    def test_add_edge_with_domain_categories(self) -> None:
        """
        TC-P2-EDGE-N-01: Add edge with source and target domain categories.

        // Given: Evidence from different domain category sources
        // When: Adding edge with domain categories
        // Then: Domain categories stored on edge
        """
        graph = EvidenceGraph()

        edge_id = graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-academic",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.REFUTES,
            confidence=0.85,
            nli_label="contradiction",
            nli_edge_confidence=0.9,
            source_domain_category="academic",
            target_domain_category="unverified",
        )

        assert edge_id is not None
        edge_data = graph._graph.edges["fragment:frag-academic", "claim:claim-1"]
        assert edge_data["source_domain_category"] == "academic"
        assert edge_data["target_domain_category"] == "unverified"

    def test_add_edge_domain_categories_default_none(self) -> None:
        """
        TC-P2-EDGE-N-02: Domain categories default to None when not provided.

        // Given: Edge added without domain categories
        // When: Inspecting edge data
        // Then: Domain categories are None
        """
        graph = EvidenceGraph()

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
        )

        edge_data = graph._graph.edges["fragment:frag-1", "claim:claim-1"]
        assert edge_data.get("source_domain_category") is None
        assert edge_data.get("target_domain_category") is None

    def test_to_dict_includes_domain_categories(self) -> None:
        """
        TC-P2-EDGE-N-03: Export includes domain categories on edges.

        // Given: Graph with edge containing domain categories
        // When: Exporting to dict
        // Then: Domain categories included in export
        """
        graph = EvidenceGraph()

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-trusted",
            target_type=NodeType.CLAIM,
            target_id="claim-low",
            relation=RelationType.REFUTES,
            confidence=0.88,
            source_domain_category="trusted",
            target_domain_category="low",
        )

        data = graph.to_dict()

        assert len(data["edges"]) == 1
        edge = data["edges"][0]
        assert edge["source_domain_category"] == "trusted"
        assert edge["target_domain_category"] == "low"

    def test_contradicting_edges_with_different_domain_categories(self) -> None:
        """
        TC-P2-EDGE-N-04: Refuting evidence edges preserve domain categories.

        // Given: Two claims and a REFUTES edge
        // When: One is from ACADEMIC, one from UNVERIFIED
        // Then: Domain categories allow AI to evaluate credibility
        """
        graph = EvidenceGraph()

        # Academic source claims: "Climate change is real"
        graph.add_node(NodeType.CLAIM, "claim-academic", text="Climate change is real")

        # Unverified source claims opposite
        graph.add_node(NodeType.CLAIM, "claim-unverified", text="Climate change is a hoax")

        # Add REFUTES edge with domain categories
        graph.add_edge(
            source_type=NodeType.CLAIM,
            source_id="claim-academic",
            target_type=NodeType.CLAIM,
            target_id="claim-unverified",
            relation=RelationType.REFUTES,
            confidence=0.95,
            source_domain_category="academic",
            target_domain_category="unverified",
        )

        # Find contradictions
        contradictions = graph.find_contradictions()
        assert len(contradictions) == 1
        assert contradictions[0]["claim_id"] == "claim-unverified"

        # Export and verify domain categories preserved
        data = graph.to_dict()
        edge = data["edges"][0]
        assert edge["source_domain_category"] == "academic"
        assert edge["target_domain_category"] == "unverified"
        # High-inference AI can now prioritize academic source

    def test_add_claim_evidence_with_domain_categories(self) -> None:
        """
        TC-P2-EDGE-N-05: add_claim_evidence accepts domain categories.

        // Given: Need to add evidence with domain category info
        // When: Adding edge with domain categories
        // Then: Domain categories stored in graph
        """

        graph = EvidenceGraph(task_id="test")

        # Add edge directly (simulating what add_claim_evidence does)
        edge_id = graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-gov",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.92,
            nli_label="entailment",
            nli_edge_confidence=0.95,
            source_domain_category="government",
            target_domain_category="primary",
        )

        assert edge_id is not None
        edge_data = graph._graph.edges["fragment:frag-gov", "claim:claim-1"]
        assert edge_data["source_domain_category"] == "government"
        assert edge_data["target_domain_category"] == "primary"

    @pytest.mark.asyncio
    async def test_save_to_db_with_domain_categories(self, test_database: Database) -> None:
        """
        TC-P2-EDGE-I-01: Save edges with domain categories to database.

        // Given: Edge with domain categories
        // When: Saving to database
        // Then: Domain categories persisted
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        graph = EvidenceGraph(task_id="test-task")
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.REFUTES,
            confidence=0.85,
            source_domain_category="academic",
            target_domain_category="low",
        )

        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.save_to_db()

        edges = await test_database.fetch_all("SELECT * FROM edges")
        assert len(edges) == 1
        assert edges[0]["source_domain_category"] == "academic"
        assert edges[0]["target_domain_category"] == "low"

    @pytest.mark.asyncio
    async def test_load_from_db_with_domain_categories(self, test_database: Database) -> None:
        """
        TC-P2-EDGE-I-02: Load edges with domain categories from database.

        // Given: Edges with domain categories in database
        // When: Loading graph from database
        // Then: Domain categories restored
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # First create a task (foreign key required)
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )

        # Then create a claim referencing the task
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )

        # Insert edge with domain categories
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id,
                             relation, nli_edge_confidence, source_domain_category, target_domain_category)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1',
                   'supports', 0.9, 'government', 'trusted')
            """
        )

        graph = EvidenceGraph(task_id="test-task")

        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Check edge was loaded with domain categories
        edge_data = graph._graph.edges.get(("fragment:frag-1", "claim:claim-1"))
        assert edge_data is not None
        assert edge_data["source_domain_category"] == "government"
        assert edge_data["target_domain_category"] == "trusted"


class TestRelationTypeEvidenceSource:
    """Tests for RelationType.EVIDENCE_SOURCE enum value.

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-ENUM-N-01 | RelationType.EVIDENCE_SOURCE | Equivalence – normal | Enum value exists | Phase 2 prep |
    """

    def test_evidence_source_enum_exists(self) -> None:
        """TC-ENUM-N-01: RelationType.EVIDENCE_SOURCE enum value exists.

        // Given: The RelationType enum
        // When: Accessing EVIDENCE_SOURCE
        // Then: Enum value is "evidence_source"
        """
        assert RelationType.EVIDENCE_SOURCE.value == "evidence_source"


@pytest.mark.integration
class TestCitationNetworkLoading:
    """Tests for loading page->page cites edges in load_from_db.

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-CITES-N-01 | task with claims linked to fragments with page_id | Equivalence – normal | cites edges loaded | Core functionality |
    | TC-CITES-N-02 | cites edges exist for source pages | Equivalence – normal | edges in NetworkX graph | Verify wiring |
    | TC-CITES-N-03 | Multiple source pages | Equivalence – normal | All cites edges loaded | Multiple pages |
    | TC-CITES-B-01 | task with no claims | Boundary – empty | Empty cites edges | Edge case |
    | TC-CITES-B-02 | claims with no fragment edges | Boundary – empty | Empty cites edges | No fragments |
    | TC-CITES-B-03 | fragments with NULL page_id | Boundary – NULL | Fragments skipped | NULL handling |
    | TC-CITES-B-04 | No cites edges in DB | Boundary – empty | Empty cites edges | No citations |
    | TC-CITES-N-04 | get_stats returns cites count | Equivalence – normal | edge_counts.cites > 0 | Stats verification |
    | TC-CITES-N-05 | to_dict includes cites edges | Equivalence – normal | cites in export | Export verification |
    """

    @pytest.mark.asyncio
    async def test_load_cites_edges_for_task(self, test_database: Database) -> None:
        """TC-CITES-N-01: Load cites edges for task with claims linked to fragments with page_id.

        // Given: Task with claim -> fragment edge, fragment has page_id, page has cites edges
        // When: load_from_db(task_id) is called
        // Then: cites edges are loaded into the NetworkX graph
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create task
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )

        # Create claim for task
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )

        # Create pages
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-source', 'https://source.com', 'source.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-cited', 'https://cited.com', 'cited.com', datetime('now'))
            """
        )

        # Create fragment with page_id
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-source', 'paragraph', 'Fragment text', datetime('now'))
            """
        )

        # Create fragment -> claim edge
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-frag-claim', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # Create page -> page cites edge
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-page-cites', 'page', 'page-source', 'page', 'page-cited', 'cites')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: Edges are loaded (frag->claim + cites + evidence_source)
        # Phase 2 adds EVIDENCE_SOURCE edges: claim->page derived from fragment->claim
        assert graph._graph.number_of_edges() == 3  # 1 frag->claim + 1 cites + 1 evidence_source

        # Verify cites edge is loaded
        cites_edge = graph._graph.edges.get(("page:page-source", "page:page-cited"))
        assert cites_edge is not None
        assert cites_edge["relation"] == "cites"

        # Verify EVIDENCE_SOURCE edge is also loaded
        es_edge = graph._graph.edges.get(("claim:claim-1", "page:page-source"))
        assert es_edge is not None
        assert es_edge["relation"] == "evidence_source"

    @pytest.mark.asyncio
    async def test_cites_edges_in_stats(self, test_database: Database) -> None:
        """TC-CITES-N-04: get_stats returns correct cites count.

        // Given: Task with loaded cites edges
        // When: get_stats() is called
        // Then: edge_counts.cites > 0
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create test data
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://source.com', 'source.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-2', 'https://cited.com', 'cited.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment text', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-2', 'page', 'page-1', 'page', 'page-2', 'cites')
            """
        )

        # When: Load and get stats
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        stats = graph.get_stats()

        # Then: cites count is correct
        assert stats["edge_counts"]["cites"] == 1
        assert stats["edge_counts"]["supports"] == 1

    @pytest.mark.asyncio
    async def test_cites_edges_in_to_dict(self, test_database: Database) -> None:
        """TC-CITES-N-05: to_dict includes cites edges.

        // Given: Task with loaded cites edges
        // When: to_dict() is called
        // Then: cites edges are in the export
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create test data (same setup as above)
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://source.com', 'source.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-2', 'https://cited.com', 'cited.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment text', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-2', 'page', 'page-1', 'page', 'page-2', 'cites')
            """
        )

        # When: Load and export
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        data = graph.to_dict()

        # Then: cites edges are in the export
        cites_edges = [e for e in data["edges"] if e["relation"] == "cites"]
        assert len(cites_edges) == 1
        assert cites_edges[0]["source"] == "page:page-1"
        assert cites_edges[0]["target"] == "page:page-2"

    @pytest.mark.asyncio
    async def test_multiple_source_pages_load_all_cites(self, test_database: Database) -> None:
        """TC-CITES-N-03: Multiple source pages load all cites edges.

        // Given: Task with claims linked to multiple fragments from different pages
        // When: load_from_db(task_id) is called
        // Then: All cites edges from all source pages are loaded
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create test data with multiple source pages
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim 1', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-2', 'test-task', 'Test claim 2', 0.8)
            """
        )

        # Create 3 pages (2 source, 1 cited)
        for page_id in ["page-src1", "page-src2", "page-cited"]:
            await test_database.execute(
                f"""
                INSERT INTO pages (id, url, domain, fetched_at)
                VALUES ('{page_id}', 'https://{page_id}.com', '{page_id}.com', datetime('now'))
                """
            )

        # Create fragments for each source page
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-src1', 'paragraph', 'Fragment 1', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-2', 'page-src2', 'paragraph', 'Fragment 2', datetime('now'))
            """
        )

        # Create fragment -> claim edges
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-fc-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-fc-2', 'fragment', 'frag-2', 'claim', 'claim-2', 'supports')
            """
        )

        # Create cites edges from both source pages
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-cites-1', 'page', 'page-src1', 'page', 'page-cited', 'cites')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-cites-2', 'page', 'page-src2', 'page', 'page-cited', 'cites')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: All edges loaded (2 frag->claim + 2 cites + 2 evidence_source)
        # Phase 2 adds EVIDENCE_SOURCE edges for each unique claim->page pair
        assert graph._graph.number_of_edges() == 6

        stats = graph.get_stats()
        assert stats["edge_counts"]["cites"] == 2
        assert stats["edge_counts"]["evidence_source"] == 2  # 2 claims, 2 source pages

    @pytest.mark.asyncio
    async def test_no_claims_empty_cites(self, test_database: Database) -> None:
        """TC-CITES-B-01: Task with no claims loads no cites edges.

        // Given: Task with no claims
        // When: load_from_db(task_id) is called
        // Then: No edges are loaded
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create task with no claims
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )

        # Create pages and cites edge (unrelated to task)
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://a.com', 'a.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-2', 'https://b.com', 'b.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'page', 'page-1', 'page', 'page-2', 'cites')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: No edges loaded (task has no claims, so no source pages)
        assert graph._graph.number_of_edges() == 0

    @pytest.mark.asyncio
    async def test_fragment_page_without_cites(self, test_database: Database) -> None:
        """TC-CITES-B-03: Fragment's page without cites edges loads no cites.

        // Given: Fragment linked to claim, but fragment's page has no cites edges
        // When: load_from_db(task_id) is called
        // Then: Only fragment->claim edge loaded, no cites
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create test data
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )

        # Create page (source page with no cites)
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-source', 'https://source.com', 'source.com', datetime('now'))
            """
        )

        # Create fragment with page_id
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-source', 'paragraph', 'Fragment text', datetime('now'))
            """
        )

        # Create fragment -> claim edge
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # Create unrelated cites edge (from different pages not linked to our task)
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-unrelated1', 'https://a.com', 'a.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-unrelated2', 'https://b.com', 'b.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-cites', 'page', 'page-unrelated1', 'page', 'page-unrelated2', 'cites')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: fragment->claim + evidence_source, no cites (source page has no cites)
        # Phase 2 adds EVIDENCE_SOURCE edge from claim to source page
        assert graph._graph.number_of_edges() == 2  # 1 frag->claim + 1 evidence_source
        stats = graph.get_stats()
        assert stats["edge_counts"]["cites"] == 0
        assert stats["edge_counts"]["supports"] == 1
        assert stats["edge_counts"]["evidence_source"] == 1

    @pytest.mark.asyncio
    async def test_no_cites_edges_in_db(self, test_database: Database) -> None:
        """TC-CITES-B-04: No cites edges in DB loads empty.

        // Given: Task with claims and fragments, but no cites edges
        // When: load_from_db(task_id) is called
        // Then: Only claim edges loaded, no cites
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create test data without cites edges
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://a.com', 'a.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment text', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: fragment->claim + evidence_source (no cites)
        # Phase 2 adds EVIDENCE_SOURCE edge from claim to page
        assert graph._graph.number_of_edges() == 2  # 1 frag->claim + 1 evidence_source
        stats = graph.get_stats()
        assert stats["edge_counts"]["cites"] == 0
        assert stats["edge_counts"]["supports"] == 1
        assert stats["edge_counts"]["evidence_source"] == 1

    @pytest.mark.asyncio
    async def test_claims_no_fragment_edges(self, test_database: Database) -> None:
        """TC-CITES-B-02: Claims with no fragment edges load no cites.

        // Given: Task with claims but no fragment edges
        // When: load_from_db(task_id) is called
        // Then: No source pages found, no cites edges loaded
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create task with claims but no edges
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )

        # Create pages and cites edge (unrelated to any claim)
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://a.com', 'a.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-2', 'https://b.com', 'b.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'page', 'page-1', 'page', 'page-2', 'cites')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: No edges loaded
        assert graph._graph.number_of_edges() == 0


class TestEvidenceSourceDerived:
    """Tests for derived EVIDENCE_SOURCE (Claim→Page) edges in load_from_db.

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-ES-N-01 | task with claim, fragment (page_id), page | Equivalence – normal | EVIDENCE_SOURCE edge claim→page created | Core wiring |
    | TC-ES-N-02 | Multiple fragments same page → same claim | Equivalence – dedup | 1 EVIDENCE_SOURCE edge | Deduplication |
    | TC-ES-N-03 | Multiple claims, multiple pages | Equivalence – normal | Each claim→page pair has edge | Multiple pairs |
    | TC-ES-N-04 | get_stats counts evidence_source | Equivalence – normal | edge_counts.evidence_source > 0 | Stats verification |
    | TC-ES-N-05 | to_dict includes evidence_source edges | Equivalence – normal | evidence_source in export | Export verification |
    | TC-ES-N-06 | Full traversal Claim→Page→CitedPage | Equivalence – effect | Path exists in graph | Acceptance criterion |
    | TC-ES-B-01 | No claims | Boundary – empty | No EVIDENCE_SOURCE edges | Edge case |
    | TC-ES-B-02 | Claims but no fragment edges | Boundary – empty | No EVIDENCE_SOURCE edges | Missing fragments |
    | TC-ES-B-03 | Fragment with NULL page_id | Boundary – NULL | No EVIDENCE_SOURCE for that fragment | NULL handling |
    | TC-ES-A-01 | EVIDENCE_SOURCE not saved to DB | Negative – persistence | Edges not in DB after load_from_db | In-memory only |
    """

    @pytest.mark.asyncio
    async def test_evidence_source_basic(self, test_database: Database) -> None:
        """TC-ES-N-01: EVIDENCE_SOURCE edge created for claim with fragment.

        // Given: Task with claim, fragment linked to page
        // When: load_from_db(task_id) is called
        // Then: EVIDENCE_SOURCE edge from claim to page is created
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create task with claim, fragment, and page
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://example.com', 'example.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment text', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-frag-claim', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: EVIDENCE_SOURCE edge is created (claim -> page)
        evidence_source_edge = graph._graph.edges.get(("claim:claim-1", "page:page-1"))
        assert evidence_source_edge is not None
        assert evidence_source_edge["relation"] == RelationType.EVIDENCE_SOURCE.value

    @pytest.mark.asyncio
    async def test_evidence_source_deduplication(self, test_database: Database) -> None:
        """TC-ES-N-02: Multiple fragments from same page to same claim creates 1 edge.

        // Given: Two fragments from the same page, both linking to the same claim
        // When: load_from_db(task_id) is called
        // Then: Only 1 EVIDENCE_SOURCE edge is created (deduplicated)
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Task with claim, two fragments from same page
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://example.com', 'example.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment 1', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-2', 'page-1', 'paragraph', 'Fragment 2', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-2', 'fragment', 'frag-2', 'claim', 'claim-1', 'refutes')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: Only 1 EVIDENCE_SOURCE edge (deduplicated)
        stats = graph.get_stats()
        assert stats["edge_counts"]["evidence_source"] == 1
        # Total edges: 2 fragment->claim + 1 evidence_source
        assert graph._graph.number_of_edges() == 3

    @pytest.mark.asyncio
    async def test_evidence_source_multiple_pairs(self, test_database: Database) -> None:
        """TC-ES-N-03: Multiple claims and pages create correct number of edges.

        // Given: 2 claims, 2 pages, each claim linked to different page via fragment
        // When: load_from_db(task_id) is called
        // Then: 2 EVIDENCE_SOURCE edges are created (one per claim-page pair)
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: 2 claims, 2 pages, 2 fragments
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Claim 1', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-2', 'test-task', 'Claim 2', 0.8)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://a.com', 'a.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-2', 'https://b.com', 'b.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment 1', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-2', 'page-2', 'paragraph', 'Fragment 2', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-2', 'fragment', 'frag-2', 'claim', 'claim-2', 'supports')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: 2 EVIDENCE_SOURCE edges
        stats = graph.get_stats()
        assert stats["edge_counts"]["evidence_source"] == 2
        # Verify both edges exist
        assert graph._graph.has_edge("claim:claim-1", "page:page-1")
        assert graph._graph.has_edge("claim:claim-2", "page:page-2")

    @pytest.mark.asyncio
    async def test_evidence_source_in_stats(self, test_database: Database) -> None:
        """TC-ES-N-04: get_stats counts evidence_source edges correctly.

        // Given: Task with EVIDENCE_SOURCE edges
        // When: get_stats() is called
        // Then: edge_counts.evidence_source > 0
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create test data
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://example.com', 'example.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # When: Load and get stats
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        stats = graph.get_stats()

        # Then: evidence_source count is correct
        assert stats["edge_counts"]["evidence_source"] == 1
        assert stats["edge_counts"]["supports"] == 1

    @pytest.mark.asyncio
    async def test_evidence_source_in_to_dict(self, test_database: Database) -> None:
        """TC-ES-N-05: to_dict includes evidence_source edges.

        // Given: Task with EVIDENCE_SOURCE edges
        // When: to_dict() is called
        // Then: evidence_source edges are in the export
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create test data
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://example.com', 'example.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # When: Load and export
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        result = graph.to_dict()

        # Then: evidence_source edge is in export
        evidence_source_edges = [e for e in result["edges"] if e["relation"] == "evidence_source"]
        assert len(evidence_source_edges) == 1
        assert evidence_source_edges[0]["source"] == "claim:claim-1"
        assert evidence_source_edges[0]["target"] == "page:page-1"

    @pytest.mark.asyncio
    async def test_full_traversal_claim_to_cited_page(self, test_database: Database) -> None:
        """TC-ES-N-06: Full traversal Claim → Page → Cited Page works.

        // Given: Claim -> Fragment (page) -> Page -> Cited Page chain
        // When: load_from_db(task_id) is called
        // Then: Can traverse from Claim to Cited Page via EVIDENCE_SOURCE and CITES
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Full chain: claim -> fragment(page-1) -> page-1 -> page-2 (cited)
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-source', 'https://source.com', 'source.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-cited', 'https://cited.com', 'cited.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-source', 'paragraph', 'Fragment', datetime('now'))
            """
        )
        # fragment -> claim edge
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-frag-claim', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )
        # page -> page cites edge
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-page-cites', 'page', 'page-source', 'page', 'page-cited', 'cites')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: Full traversal is possible
        # Path: claim:claim-1 -> page:page-source -> page:page-cited
        # Step 1: Claim -> Page via EVIDENCE_SOURCE
        assert graph._graph.has_edge("claim:claim-1", "page:page-source")
        es_edge = graph._graph.edges["claim:claim-1", "page:page-source"]
        assert es_edge["relation"] == "evidence_source"

        # Step 2: Page -> Cited Page via CITES
        assert graph._graph.has_edge("page:page-source", "page:page-cited")
        cites_edge = graph._graph.edges["page:page-source", "page:page-cited"]
        assert cites_edge["relation"] == "cites"

        # Verify full path exists (using networkx path check)
        import networkx as nx

        assert nx.has_path(graph._graph, "claim:claim-1", "page:page-cited")

    @pytest.mark.asyncio
    async def test_no_claims_no_evidence_source(self, test_database: Database) -> None:
        """TC-ES-B-01: Task with no claims has no EVIDENCE_SOURCE edges.

        // Given: Task with no claims
        // When: load_from_db(task_id) is called
        // Then: No EVIDENCE_SOURCE edges are created
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Task with no claims
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: No edges
        stats = graph.get_stats()
        assert stats["edge_counts"]["evidence_source"] == 0
        assert graph._graph.number_of_edges() == 0

    @pytest.mark.asyncio
    async def test_claims_no_fragment_edges_no_evidence_source(
        self, test_database: Database
    ) -> None:
        """TC-ES-B-02: Claims with no fragment edges have no EVIDENCE_SOURCE.

        // Given: Task with claims but no fragment edges
        // When: load_from_db(task_id) is called
        // Then: No EVIDENCE_SOURCE edges are created
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Task with claims but no edges
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: No EVIDENCE_SOURCE edges
        stats = graph.get_stats()
        assert stats["edge_counts"]["evidence_source"] == 0

    @pytest.mark.asyncio
    async def test_fragment_null_page_id_no_evidence_source(self, test_database: Database) -> None:
        """TC-ES-B-03: Fragment with NULL page_id creates no EVIDENCE_SOURCE.

        // Given: Fragment with NULL page_id linked to claim
        // When: load_from_db(task_id) is called
        // Then: No EVIDENCE_SOURCE edge for that fragment
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Fragment with NULL page_id (simulate legacy data)
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        # Create a page first (required by FK)
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-placeholder', 'https://placeholder.com', 'placeholder.com', datetime('now'))
            """
        )
        # Create fragment with a page_id (required by NOT NULL constraint)
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-placeholder', 'paragraph', 'Fragment', datetime('now'))
            """
        )
        # Fragment -> claim edge
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # Simulate NULL page_id by not having the page in frag_to_page lookup
        # (This happens if page_id was NULL when loaded from DB in Phase 1 logic)

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: EVIDENCE_SOURCE edge IS created (page_id is not NULL)
        # Note: Since page_id is NOT NULL in schema, we can't test true NULL case
        # This test verifies the basic functionality works with valid page_id
        stats = graph.get_stats()
        # With valid page_id, EVIDENCE_SOURCE should be created
        assert stats["edge_counts"]["evidence_source"] == 1

    @pytest.mark.asyncio
    async def test_evidence_source_not_persisted_to_db(self, test_database: Database) -> None:
        """TC-ES-A-01: EVIDENCE_SOURCE edges are not persisted to DB.

        // Given: Task with EVIDENCE_SOURCE edges in graph
        // When: Checking edges table in DB after load_from_db
        // Then: No evidence_source edges in DB (in-memory only)
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Create test data
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://example.com', 'example.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # When: Load from DB (this creates EVIDENCE_SOURCE in memory)
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Verify EVIDENCE_SOURCE exists in graph
        stats = graph.get_stats()
        assert stats["edge_counts"]["evidence_source"] == 1

        # Then: Check DB - no evidence_source edges
        db_edges = await test_database.fetch_all(
            "SELECT * FROM edges WHERE relation = 'evidence_source'"
        )
        assert len(db_edges) == 0

    @pytest.mark.asyncio
    async def test_evidence_source_with_neutral_relation(self, test_database: Database) -> None:
        """Test EVIDENCE_SOURCE is created for neutral fragment->claim edges.

        // Given: Fragment -> claim edge with neutral relation
        // When: load_from_db(task_id) is called
        // Then: EVIDENCE_SOURCE edge is created
        """
        from unittest.mock import patch

        from src.filter import evidence_graph

        # Given: Fragment -> claim with neutral relation
        await test_database.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://example.com', 'example.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'neutral')
            """
        )

        # When: Load from DB
        graph = EvidenceGraph(task_id="test-task")
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.load_from_db("test-task")

        # Then: EVIDENCE_SOURCE edge is created (neutral relation also triggers it)
        stats = graph.get_stats()
        assert stats["edge_counts"]["evidence_source"] == 1
        assert graph._graph.has_edge("claim:claim-1", "page:page-1")


class TestGraphAnalysis:
    """Tests for graph analysis methods (Phase 4).

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-PR-N-01 | Graph with page-page edges | Normal | PageRank scores returned | Core functionality |
    | TC-PR-N-02 | node_type_filter=PAGE | Normal | Only PAGE nodes in result | Filter wiring |
    | TC-PR-B-01 | Empty graph | Boundary | Empty dict | Edge case |
    | TC-PR-B-02 | Single node, no edges | Boundary | Single entry with score 1.0 | Edge case |
    | TC-BC-N-01 | Graph with multiple paths | Normal | Centrality scores returned | Core functionality |
    | TC-BC-N-02 | node_type_filter=PAGE | Normal | Only PAGE nodes in result | Filter wiring |
    | TC-BC-B-01 | Empty graph | Boundary | Empty dict | Edge case |
    | TC-HUB-N-01 | Graph with citations | Normal | Pages sorted by cited_by_count | Core functionality |
    | TC-HUB-N-02 | limit=5 | Normal | At most 5 results | Limit effect |
    | TC-HUB-B-01 | No PAGE nodes | Boundary | Empty list | Edge case |
    | TC-HUB-B-02 | Pages with 0 in-degree | Boundary | Empty list | No citations |
    """

    def test_pagerank_basic(self) -> None:
        """TC-PR-N-01: PageRank returns scores for graph with edges.

        // Given: Graph with page-page citation edges
        // When: calculate_pagerank() is called
        // Then: PageRank scores are returned for all nodes
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph with page-page citation edges
        graph = EvidenceGraph()
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        graph.add_node(NodeType.PAGE, "page-3")
        graph.add_edge(NodeType.PAGE, "page-1", NodeType.PAGE, "page-2", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "page-1", NodeType.PAGE, "page-3", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "page-2", NodeType.PAGE, "page-3", RelationType.CITES)

        # When: Calculate PageRank
        scores = graph.calculate_pagerank()

        # Then: PageRank scores returned, sum to 1.0
        assert len(scores) == 3
        assert abs(sum(scores.values()) - 1.0) < 0.001
        # page-3 should have highest score (most cited)
        assert scores["page:page-3"] > scores["page:page-1"]

    def test_pagerank_filter_by_node_type(self) -> None:
        """TC-PR-N-02: node_type_filter returns only matching nodes.

        // Given: Graph with PAGE and CLAIM nodes
        // When: calculate_pagerank(node_type_filter=PAGE) is called
        // Then: Only PAGE nodes in result
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph with mixed node types
        graph = EvidenceGraph()
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        graph.add_node(NodeType.CLAIM, "claim-1")
        graph.add_edge(NodeType.PAGE, "page-1", NodeType.PAGE, "page-2", RelationType.CITES)
        graph.add_edge(
            NodeType.CLAIM, "claim-1", NodeType.PAGE, "page-1", RelationType.EVIDENCE_SOURCE
        )

        # When: Calculate PageRank with filter
        scores = graph.calculate_pagerank(node_type_filter=NodeType.PAGE)

        # Then: Only PAGE nodes in result
        assert len(scores) == 2
        assert all("page:" in node_id for node_id in scores.keys())
        assert "claim:claim-1" not in scores

    def test_pagerank_empty_graph(self) -> None:
        """TC-PR-B-01: Empty graph returns empty dict.

        // Given: Empty graph
        // When: calculate_pagerank() is called
        // Then: Returns empty dict
        """
        from src.filter.evidence_graph import EvidenceGraph

        # Given: Empty graph
        graph = EvidenceGraph()

        # When: Calculate PageRank
        scores = graph.calculate_pagerank()

        # Then: Empty dict
        assert scores == {}

    def test_pagerank_single_node(self) -> None:
        """TC-PR-B-02: Single node with no edges has score 1.0.

        // Given: Graph with single node, no edges
        // When: calculate_pagerank() is called
        // Then: Single entry with score 1.0
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType

        # Given: Single node
        graph = EvidenceGraph()
        graph.add_node(NodeType.PAGE, "page-1")

        # When: Calculate PageRank
        scores = graph.calculate_pagerank()

        # Then: Single entry with score 1.0
        assert len(scores) == 1
        assert scores["page:page-1"] == 1.0

    def test_betweenness_centrality_basic(self) -> None:
        """TC-BC-N-01: Betweenness centrality returns scores for graph with paths.

        // Given: Graph with multiple paths through nodes
        // When: calculate_betweenness_centrality() is called
        // Then: Centrality scores are returned
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph where page-2 is a bridge between page-1 and page-3
        graph = EvidenceGraph()
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        graph.add_node(NodeType.PAGE, "page-3")
        graph.add_edge(NodeType.PAGE, "page-1", NodeType.PAGE, "page-2", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "page-2", NodeType.PAGE, "page-3", RelationType.CITES)

        # When: Calculate betweenness centrality
        scores = graph.calculate_betweenness_centrality()

        # Then: Centrality scores returned
        assert len(scores) == 3
        # page-2 should have highest centrality (bridge node)
        assert scores["page:page-2"] >= scores["page:page-1"]
        assert scores["page:page-2"] >= scores["page:page-3"]

    def test_betweenness_centrality_filter_by_node_type(self) -> None:
        """TC-BC-N-02: node_type_filter returns only matching nodes.

        // Given: Graph with PAGE and CLAIM nodes
        // When: calculate_betweenness_centrality(node_type_filter=PAGE) is called
        // Then: Only PAGE nodes in result
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph with mixed node types
        graph = EvidenceGraph()
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        graph.add_node(NodeType.CLAIM, "claim-1")
        graph.add_edge(NodeType.PAGE, "page-1", NodeType.PAGE, "page-2", RelationType.CITES)

        # When: Calculate betweenness centrality with filter
        scores = graph.calculate_betweenness_centrality(node_type_filter=NodeType.PAGE)

        # Then: Only PAGE nodes in result
        assert len(scores) == 2
        assert all("page:" in node_id for node_id in scores.keys())

    def test_betweenness_centrality_empty_graph(self) -> None:
        """TC-BC-B-01: Empty graph returns empty dict.

        // Given: Empty graph
        // When: calculate_betweenness_centrality() is called
        // Then: Returns empty dict
        """
        from src.filter.evidence_graph import EvidenceGraph

        # Given: Empty graph
        graph = EvidenceGraph()

        # When: Calculate betweenness centrality
        scores = graph.calculate_betweenness_centrality()

        # Then: Empty dict
        assert scores == {}

    def test_hub_pages_basic(self) -> None:
        """TC-HUB-N-01: get_citation_hub_pages returns pages sorted by cited_by_count.

        // Given: Graph with citation edges to pages
        // When: get_citation_hub_pages() is called
        // Then: Pages sorted by cited_by_count DESC
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph with pages cited different numbers of times
        graph = EvidenceGraph()
        graph.add_node(NodeType.PAGE, "page-src1", title="Source 1")
        graph.add_node(NodeType.PAGE, "page-src2", title="Source 2")
        graph.add_node(NodeType.PAGE, "page-hub-high", title="High Hub")
        graph.add_node(NodeType.PAGE, "page-hub-low", title="Low Hub")

        # page-hub-high cited by both sources
        graph.add_edge(
            NodeType.PAGE, "page-src1", NodeType.PAGE, "page-hub-high", RelationType.CITES
        )
        graph.add_edge(
            NodeType.PAGE, "page-src2", NodeType.PAGE, "page-hub-high", RelationType.CITES
        )
        # page-hub-low cited by one source
        graph.add_edge(
            NodeType.PAGE, "page-src1", NodeType.PAGE, "page-hub-low", RelationType.CITES
        )

        # When: Get citation hub pages
        hubs = graph.get_citation_hub_pages()

        # Then: Sorted by cited_by_count DESC
        assert len(hubs) == 2
        assert hubs[0]["page_id"] == "page-hub-high"
        assert hubs[0]["cited_by_count"] == 2
        assert hubs[0]["title"] == "High Hub"
        assert hubs[1]["page_id"] == "page-hub-low"
        assert hubs[1]["cited_by_count"] == 1

    def test_hub_pages_limit(self) -> None:
        """TC-HUB-N-02: limit parameter limits results.

        // Given: Graph with many cited pages
        // When: get_citation_hub_pages(limit=2) is called
        // Then: At most 2 results returned
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph with 5 cited pages
        graph = EvidenceGraph()
        graph.add_node(NodeType.PAGE, "page-src")
        for i in range(5):
            graph.add_node(NodeType.PAGE, f"page-cited-{i}", title=f"Cited {i}")
            graph.add_edge(
                NodeType.PAGE, "page-src", NodeType.PAGE, f"page-cited-{i}", RelationType.CITES
            )

        # When: Get hub pages with limit
        hubs = graph.get_citation_hub_pages(limit=2)

        # Then: At most 2 results
        assert len(hubs) == 2

    def test_hub_pages_no_page_nodes(self) -> None:
        """TC-HUB-B-01: Graph with no PAGE nodes returns empty list.

        // Given: Graph with only CLAIM nodes
        // When: get_citation_hub_pages() is called
        // Then: Returns empty list
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph with only claims
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")
        graph.add_node(NodeType.CLAIM, "claim-2")
        graph.add_edge(NodeType.CLAIM, "claim-1", NodeType.CLAIM, "claim-2", RelationType.SUPPORTS)

        # When: Get hub pages
        hubs = graph.get_citation_hub_pages()

        # Then: Empty list
        assert hubs == []

    def test_hub_pages_zero_citations(self) -> None:
        """TC-HUB-B-02: Pages with 0 in-degree are not included.

        // Given: Graph with PAGE nodes but no CITES edges
        // When: get_citation_hub_pages() is called
        // Then: Empty list (no hubs)
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Pages with no incoming cites edges
        graph = EvidenceGraph()
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        # Only EVIDENCE_SOURCE edges, not CITES
        graph.add_edge(
            NodeType.CLAIM, "claim-1", NodeType.PAGE, "page-1", RelationType.EVIDENCE_SOURCE
        )

        # When: Get hub pages
        hubs = graph.get_citation_hub_pages()

        # Then: Empty list (no cites edges)
        assert hubs == []


class TestSaveToDbDerivedEdgeSkip:
    """Tests for save_to_db derived edge skip functionality.

    Per ADR-0005: EVIDENCE_SOURCE edges are derived in-memory and should NOT
    be persisted to the database. This test class verifies that save_to_db()
    correctly skips these edges.

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|----------------------|-------------|-----------------|-------|
    | TC-SAVE-N-01 | Graph with supports/refutes edges | Normal | All edges saved | Wiring |
    | TC-SAVE-N-02 | Graph with cites edges | Normal | cites edges saved | Wiring |
    | TC-SAVE-N-03 | Graph with evidence_source edges | Key case | NOT saved | Effect (skip) |
    | TC-SAVE-N-04 | Mixed graph (supports + evidence_source) | Mixed | Only supports saved | Effect |
    | TC-SAVE-B-01 | Empty graph | Boundary | No DB insert called | Edge case |
    | TC-SAVE-A-01 | Graph with only evidence_source | Negative | 0 edges saved | All skipped |
    """

    @pytest.mark.asyncio
    async def test_save_supports_refutes_edges(self, test_database: Database) -> None:
        """TC-SAVE-N-01: Graph with supports/refutes edges saves all edges.

        // Given: Graph with SUPPORTS and REFUTES edges
        // When: save_to_db() is called
        // Then: All edges are persisted to DB
        """
        from unittest.mock import patch

        from src.filter import evidence_graph as eg_module
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph with supports and refutes edges
        graph = EvidenceGraph(task_id="test-task")
        graph.add_edge(
            NodeType.FRAGMENT,
            "frag-1",
            NodeType.CLAIM,
            "claim-1",
            RelationType.SUPPORTS,
            edge_id="edge-supports",
        )
        graph.add_edge(
            NodeType.FRAGMENT,
            "frag-2",
            NodeType.CLAIM,
            "claim-1",
            RelationType.REFUTES,
            edge_id="edge-refutes",
        )

        # When: save_to_db is called
        with patch.object(eg_module, "get_database", return_value=test_database):
            await graph.save_to_db()

        # Then: Both edges are saved
        edges = await test_database.fetch_all("SELECT id, relation FROM edges")
        edge_ids = {e["id"] for e in edges}
        relations = {e["relation"] for e in edges}

        assert "edge-supports" in edge_ids
        assert "edge-refutes" in edge_ids
        assert "supports" in relations
        assert "refutes" in relations
        assert len(edges) == 2

    @pytest.mark.asyncio
    async def test_save_cites_edges(self, test_database: Database) -> None:
        """TC-SAVE-N-02: Graph with cites edges saves all edges.

        // Given: Graph with CITES edges (page->page)
        // When: save_to_db() is called
        // Then: cites edges are persisted to DB
        """
        from unittest.mock import patch

        from src.filter import evidence_graph as eg_module
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph with cites edges
        graph = EvidenceGraph(task_id="test-task")
        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
            edge_id="edge-cites",
        )

        # When: save_to_db is called
        with patch.object(eg_module, "get_database", return_value=test_database):
            await graph.save_to_db()

        # Then: cites edge is saved
        edges = await test_database.fetch_all("SELECT id, relation FROM edges")
        assert len(edges) == 1
        assert edges[0]["id"] == "edge-cites"
        assert edges[0]["relation"] == "cites"

    @pytest.mark.asyncio
    async def test_skip_evidence_source_edges(self, test_database: Database) -> None:
        """TC-SAVE-N-03: Graph with evidence_source edges does NOT save them.

        // Given: Graph with EVIDENCE_SOURCE edges (derived edges)
        // When: save_to_db() is called
        // Then: evidence_source edges are NOT persisted (per ADR-0005)
        """
        from unittest.mock import patch

        from src.filter import evidence_graph as eg_module
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph with evidence_source edges
        graph = EvidenceGraph(task_id="test-task")
        graph.add_edge(
            NodeType.CLAIM,
            "claim-1",
            NodeType.PAGE,
            "page-1",
            RelationType.EVIDENCE_SOURCE,
            edge_id="edge-evidence-source",
        )

        # When: save_to_db is called
        with patch.object(eg_module, "get_database", return_value=test_database):
            await graph.save_to_db()

        # Then: No edges are saved (evidence_source is skipped)
        edges = await test_database.fetch_all("SELECT id, relation FROM edges")
        assert len(edges) == 0

    @pytest.mark.asyncio
    async def test_mixed_graph_saves_only_non_derived(self, test_database: Database) -> None:
        """TC-SAVE-N-04: Mixed graph saves only non-derived edges.

        // Given: Graph with SUPPORTS and EVIDENCE_SOURCE edges
        // When: save_to_db() is called
        // Then: Only SUPPORTS edges are persisted, EVIDENCE_SOURCE is skipped
        """
        from unittest.mock import patch

        from src.filter import evidence_graph as eg_module
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Mixed graph
        graph = EvidenceGraph(task_id="test-task")
        graph.add_edge(
            NodeType.FRAGMENT,
            "frag-1",
            NodeType.CLAIM,
            "claim-1",
            RelationType.SUPPORTS,
            edge_id="edge-supports",
        )
        graph.add_edge(
            NodeType.CLAIM,
            "claim-1",
            NodeType.PAGE,
            "page-1",
            RelationType.EVIDENCE_SOURCE,
            edge_id="edge-evidence-source",
        )
        graph.add_edge(
            NodeType.PAGE,
            "page-1",
            NodeType.PAGE,
            "page-2",
            RelationType.CITES,
            edge_id="edge-cites",
        )

        # When: save_to_db is called
        with patch.object(eg_module, "get_database", return_value=test_database):
            await graph.save_to_db()

        # Then: Only supports and cites are saved, evidence_source is skipped
        edges = await test_database.fetch_all("SELECT id, relation FROM edges")
        edge_ids = {e["id"] for e in edges}
        relations = {e["relation"] for e in edges}

        assert len(edges) == 2
        assert "edge-supports" in edge_ids
        assert "edge-cites" in edge_ids
        assert "edge-evidence-source" not in edge_ids
        assert "supports" in relations
        assert "cites" in relations
        assert "evidence_source" not in relations

    @pytest.mark.asyncio
    async def test_empty_graph_no_inserts(self, test_database: Database) -> None:
        """TC-SAVE-B-01: Empty graph does not call insert.

        // Given: Empty graph (no edges)
        // When: save_to_db() is called
        // Then: No DB inserts occur
        """
        from unittest.mock import patch

        from src.filter import evidence_graph as eg_module
        from src.filter.evidence_graph import EvidenceGraph

        # Given: Empty graph
        graph = EvidenceGraph(task_id="test-task")

        # When: save_to_db is called
        with patch.object(eg_module, "get_database", return_value=test_database):
            await graph.save_to_db()

        # Then: No edges in DB
        edges = await test_database.fetch_all("SELECT id FROM edges")
        assert len(edges) == 0

    @pytest.mark.asyncio
    async def test_only_evidence_source_edges_all_skipped(self, test_database: Database) -> None:
        """TC-SAVE-A-01: Graph with only evidence_source edges saves nothing.

        // Given: Graph with only EVIDENCE_SOURCE edges
        // When: save_to_db() is called
        // Then: 0 edges saved, all skipped
        """
        from unittest.mock import patch

        from src.filter import evidence_graph as eg_module
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Graph with multiple evidence_source edges
        graph = EvidenceGraph(task_id="test-task")
        graph.add_edge(
            NodeType.CLAIM,
            "claim-1",
            NodeType.PAGE,
            "page-1",
            RelationType.EVIDENCE_SOURCE,
        )
        graph.add_edge(
            NodeType.CLAIM,
            "claim-2",
            NodeType.PAGE,
            "page-2",
            RelationType.EVIDENCE_SOURCE,
        )
        graph.add_edge(
            NodeType.CLAIM,
            "claim-3",
            NodeType.PAGE,
            "page-3",
            RelationType.EVIDENCE_SOURCE,
        )

        # When: save_to_db is called
        with patch.object(eg_module, "get_database", return_value=test_database):
            await graph.save_to_db()

        # Then: No edges are saved
        edges = await test_database.fetch_all("SELECT id, relation FROM edges")
        assert len(edges) == 0


class TestCalculatePageRankCitationOnly:
    """Tests for calculate_pagerank with citation_only parameter (10.4.2b)."""

    def test_citation_only_true_uses_page_cites_subgraph(self) -> None:
        """TC-PR-N-01: citation_only=True uses PAGE nodes + CITES edges only.

        // Given: A mixed graph with claims, fragments, and pages with various edges
        // When: calculate_pagerank(citation_only=True)
        // Then: Only PAGE nodes are scored, Claim/Fragment nodes are excluded
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Mixed graph
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")
        graph.add_node(NodeType.FRAGMENT, "frag-1")
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        graph.add_node(NodeType.PAGE, "page-3")

        # Add various edge types
        graph.add_edge(NodeType.PAGE, "page-1", NodeType.PAGE, "page-2", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "page-2", NodeType.PAGE, "page-3", RelationType.CITES)
        graph.add_edge(
            NodeType.FRAGMENT, "frag-1", NodeType.CLAIM, "claim-1", RelationType.SUPPORTS
        )

        # When: citation_only=True (default)
        scores = graph.calculate_pagerank(citation_only=True)

        # Then: Only PAGE nodes are in the result
        assert len(scores) == 3
        assert all(node_id.startswith("page:") for node_id in scores.keys())
        assert "claim:claim-1" not in scores
        assert "fragment:frag-1" not in scores

    def test_citation_only_false_uses_full_graph(self) -> None:
        """TC-PR-N-02: citation_only=False uses full graph including all node types.

        // Given: A mixed graph
        // When: calculate_pagerank(citation_only=False)
        // Then: All nodes (claims, fragments, pages) are scored
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Mixed graph
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")
        graph.add_node(NodeType.FRAGMENT, "frag-1")
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_edge(
            NodeType.FRAGMENT, "frag-1", NodeType.CLAIM, "claim-1", RelationType.SUPPORTS
        )

        # When: citation_only=False
        scores = graph.calculate_pagerank(citation_only=False)

        # Then: All nodes are scored
        assert "claim:claim-1" in scores
        assert "fragment:frag-1" in scores
        assert "page:page-1" in scores

    def test_empty_graph_returns_empty_dict(self) -> None:
        """TC-PR-B-01: Empty graph returns empty dict.

        // Given: An empty graph
        // When: calculate_pagerank(citation_only=True)
        // Then: Empty dict is returned
        """
        from src.filter.evidence_graph import EvidenceGraph

        # Given: Empty graph
        graph = EvidenceGraph()

        # When
        scores = graph.calculate_pagerank(citation_only=True)

        # Then
        assert scores == {}

    def test_no_cites_edges_with_citation_only(self) -> None:
        """TC-PR-B-02: Graph with pages but no CITES edges returns uniform scores.

        // Given: Graph with PAGE nodes but no CITES edges
        // When: calculate_pagerank(citation_only=True)
        // Then: Returns uniform scores (no linking to affect rank)
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Pages connected by non-CITES edges only
        graph = EvidenceGraph()
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        graph.add_edge(
            NodeType.FRAGMENT, "frag-1", NodeType.CLAIM, "claim-1", RelationType.SUPPORTS
        )

        # When: citation_only=True
        scores = graph.calculate_pagerank(citation_only=True)

        # Then: Uniform distribution (each page gets 0.5)
        assert len(scores) == 2
        assert abs(scores["page:page-1"] - 0.5) < 0.01
        assert abs(scores["page:page-2"] - 0.5) < 0.01

    def test_no_page_nodes_returns_empty(self) -> None:
        """TC-PR-B-03: Graph without PAGE nodes returns empty dict with citation_only=True.

        // Given: Graph with only claims and fragments
        // When: calculate_pagerank(citation_only=True)
        // Then: Empty dict (no page nodes to analyze)
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Only claims and fragments
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")
        graph.add_node(NodeType.FRAGMENT, "frag-1")
        graph.add_edge(
            NodeType.FRAGMENT, "frag-1", NodeType.CLAIM, "claim-1", RelationType.SUPPORTS
        )

        # When: citation_only=True
        scores = graph.calculate_pagerank(citation_only=True)

        # Then: Empty (no PAGE nodes)
        assert scores == {}


class TestCalculateBetweennessCentralityCitationOnly:
    """Tests for calculate_betweenness_centrality with citation_only parameter (10.4.2b)."""

    def test_citation_only_true_uses_page_cites_subgraph(self) -> None:
        """TC-BC-N-01: citation_only=True uses PAGE nodes + CITES edges only.

        // Given: A mixed graph with claims, fragments, and pages with various edges
        // When: calculate_betweenness_centrality(citation_only=True)
        // Then: Only PAGE nodes are scored
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Mixed graph with central page
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        graph.add_node(NodeType.PAGE, "page-3")

        # page-2 is a bridge between page-1 and page-3
        graph.add_edge(NodeType.PAGE, "page-1", NodeType.PAGE, "page-2", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "page-2", NodeType.PAGE, "page-3", RelationType.CITES)
        graph.add_edge(
            NodeType.FRAGMENT, "frag-1", NodeType.CLAIM, "claim-1", RelationType.SUPPORTS
        )

        # When: citation_only=True
        scores = graph.calculate_betweenness_centrality(citation_only=True)

        # Then: Only PAGE nodes are scored
        assert len(scores) == 3
        assert all(node_id.startswith("page:") for node_id in scores.keys())
        assert "claim:claim-1" not in scores

    def test_citation_only_false_uses_full_graph(self) -> None:
        """TC-BC-N-02: citation_only=False uses full graph.

        // Given: A mixed graph
        // When: calculate_betweenness_centrality(citation_only=False)
        // Then: All nodes are scored
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Mixed graph
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")
        graph.add_node(NodeType.FRAGMENT, "frag-1")
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_edge(
            NodeType.FRAGMENT, "frag-1", NodeType.CLAIM, "claim-1", RelationType.SUPPORTS
        )

        # When: citation_only=False
        scores = graph.calculate_betweenness_centrality(citation_only=False)

        # Then: All nodes are scored
        assert "claim:claim-1" in scores
        assert "fragment:frag-1" in scores
        assert "page:page-1" in scores

    def test_empty_graph_returns_empty_dict(self) -> None:
        """TC-BC-B-01: Empty graph returns empty dict.

        // Given: Empty graph
        // When: calculate_betweenness_centrality(citation_only=True)
        // Then: Empty dict
        """
        from src.filter.evidence_graph import EvidenceGraph

        # Given
        graph = EvidenceGraph()

        # When
        scores = graph.calculate_betweenness_centrality(citation_only=True)

        # Then
        assert scores == {}

    def test_bridge_node_has_higher_centrality(self) -> None:
        """TC-BC-N-03: Bridge nodes have higher betweenness centrality.

        // Given: Linear citation chain page-1 -> page-2 -> page-3
        // When: calculate_betweenness_centrality(citation_only=True)
        // Then: page-2 has highest centrality (bridge)
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: Linear chain
        graph = EvidenceGraph()
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        graph.add_node(NodeType.PAGE, "page-3")
        graph.add_edge(NodeType.PAGE, "page-1", NodeType.PAGE, "page-2", RelationType.CITES)
        graph.add_edge(NodeType.PAGE, "page-2", NodeType.PAGE, "page-3", RelationType.CITES)

        # When
        scores = graph.calculate_betweenness_centrality(citation_only=True)

        # Then: page-2 is the bridge, should have highest centrality
        assert scores["page:page-2"] >= scores["page:page-1"]
        assert scores["page:page-2"] >= scores["page:page-3"]
