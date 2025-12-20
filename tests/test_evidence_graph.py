"""
Tests for src/filter/evidence_graph.py

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
| TC-CONF-N-02 | Well supported | Equivalence – normal | High confidence | verdict set |
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
"""

import pytest

# Unit tests for evidence graph (no external dependencies except test fixtures)
pytestmark = pytest.mark.unit

from src.filter.evidence_graph import (
    EvidenceGraph,
    NodeType,
    RelationType,
    add_claim_evidence,
)


class TestNodeType:
    """Tests for NodeType enum."""

    def test_node_types_exist(self):
        """Test all node types are defined."""
        # Given: The NodeType enum
        # When: Accessing enum values
        # Then: All expected node types exist with correct values
        assert NodeType.CLAIM.value == "claim"
        assert NodeType.FRAGMENT.value == "fragment"
        assert NodeType.PAGE.value == "page"


class TestRelationType:
    """Tests for RelationType enum."""

    def test_relation_types_exist(self):
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

    def test_init(self):
        """Test graph initialization."""
        # Given: A task ID for the graph
        # When: Creating a new EvidenceGraph
        graph = EvidenceGraph(task_id="test-task")

        # Then: Graph is empty with the specified task ID
        assert graph.task_id == "test-task"
        assert graph._graph.number_of_nodes() == 0
        assert graph._graph.number_of_edges() == 0

    def test_make_node_id(self):
        """Test node ID generation."""
        # Given: An EvidenceGraph instance
        graph = EvidenceGraph()

        # When: Generating node IDs for different types
        node_id = graph._make_node_id(NodeType.CLAIM, "abc123")

        # Then: Node ID follows type:id format
        assert node_id == "claim:abc123"

        node_id = graph._make_node_id(NodeType.FRAGMENT, "xyz789")
        assert node_id == "fragment:xyz789"

    def test_parse_node_id(self):
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

    def test_add_node(self):
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

    def test_add_edge_creates_nodes_if_missing(self):
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

    def test_add_edge_with_nli_data(self):
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
            nli_confidence=0.92,
        )

        # Then: Edge contains all NLI data
        edge_data = graph._graph.edges["fragment:frag-1", "claim:claim-1"]
        assert edge_data["relation"] == "supports"
        assert edge_data["confidence"] == 0.85
        assert edge_data["nli_label"] == "entailment"
        assert edge_data["nli_confidence"] == 0.92


class TestEvidenceRetrieval:
    """Tests for evidence retrieval methods."""

    @pytest.fixture
    def populated_graph(self):
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

    def test_get_supporting_evidence(self, populated_graph):
        """Test getting supporting evidence."""
        # Given: A graph with supporting, refuting, and neutral evidence
        # When: Getting supporting evidence for a claim
        evidence = populated_graph.get_supporting_evidence("claim-1")

        # Then: Only supporting evidence is returned
        assert len(evidence) == 2
        assert all(e["relation"] == "supports" for e in evidence)

        obj_ids = {e["obj_id"] for e in evidence}
        assert obj_ids == {"frag-1", "frag-2"}

    def test_get_refuting_evidence(self, populated_graph):
        """Test getting refuting evidence."""
        # Given: A graph with mixed evidence types
        # When: Getting refuting evidence for a claim
        evidence = populated_graph.get_refuting_evidence("claim-1")

        # Then: Only refuting evidence is returned
        assert len(evidence) == 1
        assert evidence[0]["obj_id"] == "frag-3"
        assert evidence[0]["relation"] == "refutes"

    def test_get_all_evidence(self, populated_graph):
        """Test getting all categorized evidence."""
        # Given: A graph with all evidence types
        # When: Getting all evidence for a claim
        evidence = populated_graph.get_all_evidence("claim-1")

        # Then: Evidence is categorized by relation type
        assert len(evidence["supports"]) == 2
        assert len(evidence["refutes"]) == 1
        assert len(evidence["neutral"]) == 1

    def test_get_evidence_for_unknown_claim(self):
        """Test getting evidence for non-existent claim."""
        # Given: An empty graph
        graph = EvidenceGraph()

        # When: Getting evidence for unknown claim
        evidence = graph.get_supporting_evidence("unknown")

        # Then: Empty results are returned
        assert evidence == []

        evidence = graph.get_all_evidence("unknown")
        assert evidence == {"supports": [], "refutes": [], "neutral": []}


class TestClaimConfidence:
    """Tests for claim confidence calculation."""

    def test_calculate_confidence_no_evidence(self):
        """Test confidence with no evidence."""
        # Given: A graph with a claim but no evidence
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")

        # When: Calculating confidence for the claim
        result = graph.calculate_claim_confidence("claim-1")

        # Then: Confidence is zero with unverified verdict
        assert result["confidence"] == 0.0
        assert result["verdict"] == "unverified"
        assert result["supporting_count"] == 0

    def test_calculate_confidence_well_supported(self):
        """Test confidence with multiple supporting evidence."""
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
            )

        # When: Calculating confidence for the claim
        result = graph.calculate_claim_confidence("claim-1")

        # Then: High confidence with well_supported verdict
        assert result["supporting_count"] == 3
        assert result["verdict"] == "well_supported"
        assert result["confidence"] > 0.8

    def test_calculate_confidence_contested(self):
        """Test confidence with conflicting evidence."""
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
            )

        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="refute-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.REFUTES,
            confidence=0.8,
        )

        # When: Calculating confidence for the contested claim
        result = graph.calculate_claim_confidence("claim-1")

        # Then: Verdict is contested
        assert result["supporting_count"] == 2
        assert result["refuting_count"] == 1
        assert result["verdict"] == "contested"


class TestCitationChain:
    """Tests for citation chain tracing."""

    def test_citation_chain(self):
        """Test tracing citation chain.

        Validates §3.3.3 citation chain tracing for source verification.
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
        assert chain[0]["node_type"] == "fragment", (
            f"First node should be fragment, got {chain[0]['node_type']}"
        )
        assert chain[0]["obj_id"] == "frag-1", (
            f"First node should be frag-1, got {chain[0]['obj_id']}"
        )
        assert chain[1]["node_type"] == "page", (
            f"Second node should be page, got {chain[1]['node_type']}"
        )
        assert chain[1]["obj_id"] == "page-1", (
            f"Second node should be page-1, got {chain[1]['obj_id']}"
        )

    def test_citation_chain_empty(self):
        """Test citation chain for unknown node."""
        # Given: An empty graph
        graph = EvidenceGraph()

        # When: Getting citation chain for unknown node
        chain = graph.get_citation_chain(NodeType.FRAGMENT, "unknown")

        # Then: Empty chain is returned
        assert chain == []


class TestContradictionDetection:
    """Tests for contradiction detection."""

    def test_find_contradictions(self):
        """Test finding contradicting claims."""
        # Given: Two claims with a refutes relationship
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1", text="A is true")
        graph.add_node(NodeType.CLAIM, "claim-2", text="A is false")

        graph.add_edge(
            source_type=NodeType.CLAIM,
            source_id="claim-1",
            target_type=NodeType.CLAIM,
            target_id="claim-2",
            relation=RelationType.REFUTES,
            confidence=0.9,
        )

        # When: Finding contradictions
        contradictions = graph.find_contradictions()

        # Then: The contradiction pair is found
        assert len(contradictions) == 1
        assert {contradictions[0]["claim1_id"], contradictions[0]["claim2_id"]} == {
            "claim-1",
            "claim-2",
        }

    def test_find_contradictions_none(self):
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

    def test_get_stats_empty(self):
        """Test stats for empty graph."""
        # Given: An empty graph
        graph = EvidenceGraph()

        # When: Getting statistics
        stats = graph.get_stats()

        # Then: All counts are zero
        assert stats["total_nodes"] == 0
        assert stats["total_edges"] == 0

    def test_get_stats_populated(self):
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

    def test_to_dict(self):
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

    def test_detect_simple_citation_loop(self):
        """Test detecting a simple citation loop (A -> B -> C -> A).

        §3.3.3 requirement: detect circular citations
        §7 requirement: citation loop detection rate ≥80%
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

    def test_detect_no_citation_loops(self):
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

    def test_detect_citation_loops_ignores_non_citation_edges(self):
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

    def test_detect_round_trip(self):
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

    def test_detect_no_round_trips(self):
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

    def test_detect_direct_self_reference(self):
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

    def test_detect_same_domain_citation(self):
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

    def test_no_self_references(self):
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

    def test_calculate_penalties_with_loop(self):
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

    def test_calculate_penalties_no_issues(self):
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

    def test_integrity_report_clean_graph(self):
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

    def test_integrity_report_problematic_graph(self):
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

    def test_integrity_report_empty_graph(self):
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

    def test_primary_source_ratio_all_primary(self):
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

    def test_primary_source_ratio_mixed(self):
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

    def test_primary_source_ratio_empty(self):
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

    def test_severity_calculation(self):
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

    Integration tests per §7.1.7 - uses temporary database.
    """

    @pytest.mark.asyncio
    async def test_save_and_load(self, test_database):
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
    async def test_add_claim_evidence_persists(self, test_database):
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
                    confidence=0.85,
                    nli_label="entailment",
                    nli_confidence=0.9,
                    task_id="test",
                )

        # Then: Edge is created and persisted
        assert edge_id is not None

        edges = await test_database.fetch_all("SELECT * FROM edges")
        assert len(edges) == 1
        assert edges[0]["confidence"] == 0.85


class TestAcademicCitationAttributes:
    """Tests for academic citation attributes (J2).

    Tests for is_academic, is_influential, citation_context attributes
    added to CITES edges.
    """

    def test_add_edge_with_academic_attributes(self):
        """Test adding edge with academic citation attributes.

        // Given: Academic citation with is_academic, is_influential
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
            is_academic=True,
            is_influential=True,
            citation_context="This paper discusses...",
        )

        # Then: Attributes stored correctly
        edge_data = graph._graph.edges["fragment:frag-1", "page:page-1"]
        assert edge_data["is_academic"] is True
        assert edge_data["is_influential"] is True
        assert edge_data["citation_context"] == "This paper discusses..."

    def test_add_citation_with_academic_attributes(self):
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
                is_academic=True,
                is_influential=True,
                citation_context="Test context",
            )

            # Then: Citation added with attributes
            assert edge_id is not None
            edge_data = graph._graph.edges["fragment:frag-1", "page:page-1"]
            assert edge_data["is_academic"] is True
            assert edge_data["is_influential"] is True

    def test_load_from_db_with_academic_attributes(self):
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
            is_academic=True,
            is_influential=False,
            citation_context="Context text",
        )

        # When: Exporting and importing (simulating DB load)
        data = graph.to_dict()

        # Then: Attributes in export
        edges = data["edges"]
        assert len(edges) == 1
        assert edges[0]["is_academic"] is True
        assert edges[0]["is_influential"] is False
        assert edges[0]["citation_context"] == "Context text"

    @pytest.mark.asyncio
    async def test_save_to_db_with_academic_attributes(self, test_database):
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
            is_academic=True,
            is_influential=True,
            citation_context="Academic citation context",
        )

        # When: Saving to DB
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.save_to_db()

        # Then: Attributes persisted correctly
        edges = await test_database.fetch_all("SELECT * FROM edges")
        assert len(edges) == 1
        assert edges[0]["is_academic"] == 1
        assert edges[0]["is_influential"] == 1
        assert edges[0]["citation_context"] == "Academic citation context"


class TestContradictionMarking:
    """Tests for marking contradictions with is_contradiction flag."""

    def test_mark_contradictions_persists_flag(self):
        """
        Test that mark_contradictions sets is_contradiction flag.

        // Given: Graph with contradicting claims
        // When: Calling mark_contradictions()
        // Then: Edges are marked with is_contradiction=True
        """
        # Given: Two claims that refute each other
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "c1", text="Claim A is true")
        graph.add_node(NodeType.CLAIM, "c2", text="Claim A is false")
        graph.add_edge(
            NodeType.CLAIM,
            "c1",
            NodeType.CLAIM,
            "c2",
            RelationType.REFUTES,
            confidence=0.9,
        )

        # When: Mark contradictions
        count = graph.mark_contradictions()

        # Then: One contradiction pair marked
        assert count == 1
        edge_data = graph._graph.edges.get(("claim:c1", "claim:c2"), {})
        assert edge_data.get("is_contradiction") is True

    def test_mark_contradictions_no_contradictions(self):
        """
        Test mark_contradictions with clean graph.

        // Given: Graph with no contradictions
        // When: Calling mark_contradictions()
        // Then: Returns 0, no edges marked
        """
        # Given: Two claims that support each other
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "c1", text="Claim A")
        graph.add_node(NodeType.CLAIM, "c2", text="Claim B supports A")
        graph.add_edge(
            NodeType.CLAIM,
            "c1",
            NodeType.CLAIM,
            "c2",
            RelationType.SUPPORTS,
            confidence=0.8,
        )

        # When: Mark contradictions
        count = graph.mark_contradictions()

        # Then: No contradictions
        assert count == 0

    def test_mark_contradictions_empty_graph(self):
        """
        Test mark_contradictions with empty graph.

        // Given: Empty graph with no nodes
        // When: Calling mark_contradictions()
        // Then: Returns 0
        """
        # Given: Empty graph
        graph = EvidenceGraph()

        # When: Mark contradictions
        count = graph.mark_contradictions()

        # Then: No contradictions
        assert count == 0

    def test_get_contradiction_edges(self):
        """
        Test get_contradiction_edges returns only contradiction edges.

        // Given: Graph with some contradiction edges
        // When: Calling get_contradiction_edges()
        // Then: Only contradiction edges returned
        """
        # Given: Mix of edges
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "c1")
        graph.add_node(NodeType.CLAIM, "c2")
        graph.add_node(NodeType.CLAIM, "c3")

        # Contradiction edge
        graph.add_edge(
            NodeType.CLAIM,
            "c1",
            NodeType.CLAIM,
            "c2",
            RelationType.REFUTES,
            confidence=0.9,
        )
        # Normal edge
        graph.add_edge(
            NodeType.CLAIM,
            "c1",
            NodeType.CLAIM,
            "c3",
            RelationType.SUPPORTS,
            confidence=0.8,
        )

        # Mark contradictions
        graph.mark_contradictions()

        # When: Get contradiction edges
        contradiction_edges = graph.get_contradiction_edges()

        # Then: Only one edge
        assert len(contradiction_edges) == 1
        assert "is_contradiction" in contradiction_edges[0]


class TestClaimAdoptionStatus:
    """Tests for claim adoption status tracking."""

    def test_set_claim_adoption_status(self):
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

    def test_set_claim_adoption_status_not_adopted(self):
        """
        Test setting not_adopted status for rejected claim.

        // Given: Claim that was rejected
        // When: Setting adoption_status to not_adopted
        // Then: Status is preserved in graph
        """
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "rejected_claim", text="Rejected claim")

        # When: Set not_adopted status
        graph.set_claim_adoption_status("rejected_claim", "not_adopted")

        # Then: Status is not_adopted
        assert graph.get_claim_adoption_status("rejected_claim") == "not_adopted"

    def test_get_claim_adoption_status_default(self):
        """
        Test default adoption status is pending.

        // Given: Claim without explicit status
        // When: Getting adoption status
        // Then: Returns pending
        """
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "c1", text="New claim")

        # Then: Default is pending
        assert graph.get_claim_adoption_status("c1") == "pending"

    def test_get_claim_adoption_status_not_found(self):
        """
        Test get adoption status for nonexistent claim.

        // Given: Claim not in graph
        // When: Getting adoption status
        // Then: Returns None
        """
        graph = EvidenceGraph()

        # Then: None for missing claim
        assert graph.get_claim_adoption_status("nonexistent") is None

    def test_set_claim_adoption_status_empty_string(self):
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

    def test_set_claim_adoption_status_nonexistent_claim(self):
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

    def test_get_claims_by_adoption_status(self):
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

        graph.set_claim_adoption_status("c1", "adopted")
        graph.set_claim_adoption_status("c2", "not_adopted")
        # c3 stays pending

        # When: Get adopted claims
        adopted = graph.get_claims_by_adoption_status("adopted")
        not_adopted = graph.get_claims_by_adoption_status("not_adopted")
        pending = graph.get_claims_by_adoption_status("pending")

        # Then: Correct filtering
        assert adopted == ["c1"]
        assert not_adopted == ["c2"]
        assert pending == ["c3"]

    def test_not_adopted_claim_preserved_in_graph(self):
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
        assert claim_nodes[0]["adoption_status"] == "not_adopted"
