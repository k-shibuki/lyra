"""
Tests for src/filter/evidence_graph.py
"""

import pytest

from src.filter.evidence_graph import (
    EvidenceGraph,
    NodeType,
    RelationType,
    add_claim_evidence,
    add_citation,
    get_claim_assessment,
)


class TestNodeType:
    """Tests for NodeType enum."""

    def test_node_types_exist(self):
        """Test all node types are defined."""
        assert NodeType.CLAIM.value == "claim"
        assert NodeType.FRAGMENT.value == "fragment"
        assert NodeType.PAGE.value == "page"


class TestRelationType:
    """Tests for RelationType enum."""

    def test_relation_types_exist(self):
        """Test all relation types are defined."""
        assert RelationType.SUPPORTS.value == "supports"
        assert RelationType.REFUTES.value == "refutes"
        assert RelationType.CITES.value == "cites"
        assert RelationType.NEUTRAL.value == "neutral"


class TestEvidenceGraph:
    """Tests for EvidenceGraph class."""

    def test_init(self):
        """Test graph initialization."""
        graph = EvidenceGraph(task_id="test-task")
        
        assert graph.task_id == "test-task"
        assert graph._graph.number_of_nodes() == 0
        assert graph._graph.number_of_edges() == 0

    def test_make_node_id(self):
        """Test node ID generation."""
        graph = EvidenceGraph()
        
        node_id = graph._make_node_id(NodeType.CLAIM, "abc123")
        assert node_id == "claim:abc123"
        
        node_id = graph._make_node_id(NodeType.FRAGMENT, "xyz789")
        assert node_id == "fragment:xyz789"

    def test_parse_node_id(self):
        """Test node ID parsing."""
        graph = EvidenceGraph()
        
        node_type, obj_id = graph._parse_node_id("claim:abc123")
        assert node_type == NodeType.CLAIM
        assert obj_id == "abc123"
        
        node_type, obj_id = graph._parse_node_id("page:http://example.com")
        assert node_type == NodeType.PAGE
        assert obj_id == "http://example.com"

    def test_add_node(self):
        """Test adding nodes."""
        graph = EvidenceGraph()
        
        node_id = graph.add_node(
            NodeType.CLAIM,
            "claim-1",
            text="Test claim",
            confidence=0.9,
        )
        
        assert node_id == "claim:claim-1"
        assert graph._graph.number_of_nodes() == 1
        
        node_data = graph._graph.nodes[node_id]
        assert node_data["node_type"] == "claim"
        assert node_data["obj_id"] == "claim-1"
        assert node_data["text"] == "Test claim"
        assert node_data["confidence"] == 0.9

    def test_add_edge_creates_nodes_if_missing(self):
        """Test adding edge creates nodes if they don't exist."""
        graph = EvidenceGraph()
        
        edge_id = graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.8,
        )
        
        assert edge_id is not None
        assert graph._graph.number_of_nodes() == 2
        assert graph._graph.number_of_edges() == 1

    def test_add_edge_with_nli_data(self):
        """Test adding edge with NLI data."""
        graph = EvidenceGraph()
        
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
        evidence = populated_graph.get_supporting_evidence("claim-1")
        
        assert len(evidence) == 2
        assert all(e["relation"] == "supports" for e in evidence)
        
        obj_ids = {e["obj_id"] for e in evidence}
        assert obj_ids == {"frag-1", "frag-2"}

    def test_get_refuting_evidence(self, populated_graph):
        """Test getting refuting evidence."""
        evidence = populated_graph.get_refuting_evidence("claim-1")
        
        assert len(evidence) == 1
        assert evidence[0]["obj_id"] == "frag-3"
        assert evidence[0]["relation"] == "refutes"

    def test_get_all_evidence(self, populated_graph):
        """Test getting all categorized evidence."""
        evidence = populated_graph.get_all_evidence("claim-1")
        
        assert len(evidence["supports"]) == 2
        assert len(evidence["refutes"]) == 1
        assert len(evidence["neutral"]) == 1

    def test_get_evidence_for_unknown_claim(self):
        """Test getting evidence for non-existent claim."""
        graph = EvidenceGraph()
        
        evidence = graph.get_supporting_evidence("unknown")
        assert evidence == []
        
        evidence = graph.get_all_evidence("unknown")
        assert evidence == {"supports": [], "refutes": [], "neutral": []}


class TestClaimConfidence:
    """Tests for claim confidence calculation."""

    def test_calculate_confidence_no_evidence(self):
        """Test confidence with no evidence."""
        graph = EvidenceGraph()
        graph.add_node(NodeType.CLAIM, "claim-1")
        
        result = graph.calculate_claim_confidence("claim-1")
        
        assert result["confidence"] == 0.0
        assert result["verdict"] == "unverified"
        assert result["supporting_count"] == 0

    def test_calculate_confidence_well_supported(self):
        """Test confidence with multiple supporting evidence."""
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
        
        result = graph.calculate_claim_confidence("claim-1")
        
        assert result["supporting_count"] == 3
        assert result["verdict"] == "well_supported"
        assert result["confidence"] > 0.8

    def test_calculate_confidence_contested(self):
        """Test confidence with conflicting evidence."""
        graph = EvidenceGraph()
        
        # 2 supporting
        for i in range(2):
            graph.add_edge(
                source_type=NodeType.FRAGMENT,
                source_id=f"support-{i}",
                target_type=NodeType.CLAIM,
                target_id="claim-1",
                relation=RelationType.SUPPORTS,
                confidence=0.9,
            )
        
        # 1 refuting
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="refute-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.REFUTES,
            confidence=0.8,
        )
        
        result = graph.calculate_claim_confidence("claim-1")
        
        assert result["supporting_count"] == 2
        assert result["refuting_count"] == 1
        assert result["verdict"] == "contested"


class TestCitationChain:
    """Tests for citation chain tracing."""

    def test_citation_chain(self):
        """Test tracing citation chain."""
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
        
        assert len(chain) >= 1
        assert chain[0]["node_type"] == "fragment"
        assert chain[0]["obj_id"] == "frag-1"

    def test_citation_chain_empty(self):
        """Test citation chain for unknown node."""
        graph = EvidenceGraph()
        
        chain = graph.get_citation_chain(NodeType.FRAGMENT, "unknown")
        
        assert chain == []


class TestContradictionDetection:
    """Tests for contradiction detection."""

    def test_find_contradictions(self):
        """Test finding contradicting claims."""
        graph = EvidenceGraph()
        
        # Add two claims
        graph.add_node(NodeType.CLAIM, "claim-1", text="A is true")
        graph.add_node(NodeType.CLAIM, "claim-2", text="A is false")
        
        # Mark as contradicting
        graph.add_edge(
            source_type=NodeType.CLAIM,
            source_id="claim-1",
            target_type=NodeType.CLAIM,
            target_id="claim-2",
            relation=RelationType.REFUTES,
            confidence=0.9,
        )
        
        contradictions = graph.find_contradictions()
        
        assert len(contradictions) == 1
        assert {contradictions[0]["claim1_id"], contradictions[0]["claim2_id"]} == {"claim-1", "claim-2"}

    def test_find_contradictions_none(self):
        """Test finding no contradictions."""
        graph = EvidenceGraph()
        
        graph.add_node(NodeType.CLAIM, "claim-1")
        graph.add_node(NodeType.CLAIM, "claim-2")
        
        contradictions = graph.find_contradictions()
        
        assert contradictions == []


class TestGraphStats:
    """Tests for graph statistics."""

    def test_get_stats_empty(self):
        """Test stats for empty graph."""
        graph = EvidenceGraph()
        
        stats = graph.get_stats()
        
        assert stats["total_nodes"] == 0
        assert stats["total_edges"] == 0

    def test_get_stats_populated(self):
        """Test stats for populated graph."""
        graph = EvidenceGraph()
        
        graph.add_node(NodeType.CLAIM, "c1")
        graph.add_node(NodeType.CLAIM, "c2")
        graph.add_node(NodeType.FRAGMENT, "f1")
        graph.add_node(NodeType.PAGE, "p1")
        
        graph.add_edge(
            NodeType.FRAGMENT, "f1",
            NodeType.CLAIM, "c1",
            RelationType.SUPPORTS,
        )
        graph.add_edge(
            NodeType.FRAGMENT, "f1",
            NodeType.PAGE, "p1",
            RelationType.CITES,
        )
        
        stats = graph.get_stats()
        
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
        graph = EvidenceGraph()
        
        graph.add_node(NodeType.CLAIM, "c1", text="Test")
        graph.add_edge(
            NodeType.FRAGMENT, "f1",
            NodeType.CLAIM, "c1",
            RelationType.SUPPORTS,
            confidence=0.9,
        )
        
        data = graph.to_dict()
        
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
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE, "page-2",
            NodeType.PAGE, "page-3",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE, "page-3",
            NodeType.PAGE, "page-1",
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
        graph = EvidenceGraph()
        
        # Linear chain: page-1 -> page-2 -> page-3
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE, "page-2",
            NodeType.PAGE, "page-3",
            RelationType.CITES,
        )
        
        loops = graph.detect_citation_loops()
        
        assert len(loops) == 0

    def test_detect_citation_loops_ignores_non_citation_edges(self):
        """Test that loop detection only considers citation edges."""
        graph = EvidenceGraph()
        
        # Create a loop with supports relation (should be ignored)
        graph.add_edge(
            NodeType.FRAGMENT, "frag-1",
            NodeType.CLAIM, "claim-1",
            RelationType.SUPPORTS,
        )
        graph.add_edge(
            NodeType.CLAIM, "claim-1",
            NodeType.FRAGMENT, "frag-1",
            RelationType.SUPPORTS,
        )
        
        loops = graph.detect_citation_loops()
        
        assert len(loops) == 0


class TestRoundTripDetection:
    """Tests for round-trip citation detection."""

    def test_detect_round_trip(self):
        """Test detecting round-trip citations (A cites B, B cites A)."""
        graph = EvidenceGraph()
        
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE, "page-2",
            NodeType.PAGE, "page-1",
            RelationType.CITES,
        )
        
        round_trips = graph.detect_round_trips()
        
        assert len(round_trips) == 1
        assert round_trips[0]["type"] == "round_trip"
        assert round_trips[0]["severity"] == "high"

    def test_detect_no_round_trips(self):
        """Test when there are no round-trips."""
        graph = EvidenceGraph()
        
        # One-way citation
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        
        round_trips = graph.detect_round_trips()
        
        assert len(round_trips) == 0


class TestSelfReferenceDetection:
    """Tests for self-reference detection."""

    def test_detect_direct_self_reference(self):
        """Test detecting direct self-loop."""
        graph = EvidenceGraph()
        
        # A node citing itself
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-1",
            RelationType.CITES,
        )
        
        self_refs = graph.detect_self_references()
        
        assert len(self_refs) == 1
        assert self_refs[0]["type"] == "direct_self_reference"
        assert self_refs[0]["severity"] == "critical"

    def test_detect_same_domain_citation(self):
        """Test detecting same-domain citations."""
        graph = EvidenceGraph()
        
        # Add pages with domain info
        graph.add_node(NodeType.PAGE, "page-1", domain="example.com")
        graph.add_node(NodeType.PAGE, "page-2", domain="example.com")
        
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        
        self_refs = graph.detect_self_references()
        
        assert len(self_refs) == 1
        assert self_refs[0]["type"] == "same_domain_citation"
        assert self_refs[0]["domain"] == "example.com"

    def test_no_self_references(self):
        """Test when there are no self-references."""
        graph = EvidenceGraph()
        
        graph.add_node(NodeType.PAGE, "page-1", domain="example.com")
        graph.add_node(NodeType.PAGE, "page-2", domain="other.com")
        
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        
        self_refs = graph.detect_self_references()
        
        assert len(self_refs) == 0


class TestCitationPenalties:
    """Tests for citation penalty calculation."""

    def test_calculate_penalties_with_loop(self):
        """Test penalty calculation for nodes in loops."""
        graph = EvidenceGraph()
        
        # Create a loop
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE, "page-2",
            NodeType.PAGE, "page-1",
            RelationType.CITES,
        )
        
        penalties = graph.calculate_citation_penalties()
        
        # Nodes in round-trip should have penalties
        assert penalties["page:page-1"] < 1.0
        assert penalties["page:page-2"] < 1.0

    def test_calculate_penalties_no_issues(self):
        """Test penalty calculation with clean citations."""
        graph = EvidenceGraph()
        
        # Linear chain
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        
        penalties = graph.calculate_citation_penalties()
        
        # No penalties for clean graph
        assert penalties["page:page-1"] == 1.0
        assert penalties["page:page-2"] == 1.0


class TestCitationIntegrityReport:
    """Tests for citation integrity report."""

    def test_integrity_report_clean_graph(self):
        """Test integrity report for clean graph."""
        graph = EvidenceGraph()
        
        # Clean linear chain
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        
        report = graph.get_citation_integrity_report()
        
        assert report["integrity_score"] == 1.0
        assert report["loop_count"] == 0
        assert report["round_trip_count"] == 0
        assert report["self_reference_count"] == 0

    def test_integrity_report_problematic_graph(self):
        """Test integrity report for graph with issues."""
        graph = EvidenceGraph()
        
        # Add a round-trip
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        graph.add_edge(
            NodeType.PAGE, "page-2",
            NodeType.PAGE, "page-1",
            RelationType.CITES,
        )
        
        report = graph.get_citation_integrity_report()
        
        assert report["integrity_score"] < 1.0
        assert report["round_trip_count"] == 1
        assert report["problematic_node_count"] == 2

    def test_integrity_report_empty_graph(self):
        """Test integrity report for empty graph."""
        graph = EvidenceGraph()
        
        report = graph.get_citation_integrity_report()
        
        assert report["integrity_score"] == 1.0
        assert report["total_citation_edges"] == 0


class TestPrimarySourceRatio:
    """Tests for primary source ratio calculation."""

    def test_primary_source_ratio_all_primary(self):
        """Test ratio when all sources are primary."""
        graph = EvidenceGraph()
        
        # Pages that don't cite other pages (primary)
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        
        # Fragment cites pages (doesn't affect page->page ratio)
        graph.add_edge(
            NodeType.FRAGMENT, "frag-1",
            NodeType.PAGE, "page-1",
            RelationType.CITES,
        )
        
        ratio = graph.get_primary_source_ratio()
        
        assert ratio["primary_count"] == 2
        assert ratio["secondary_count"] == 0
        assert ratio["primary_ratio"] == 1.0
        assert ratio["meets_threshold"] is True

    def test_primary_source_ratio_mixed(self):
        """Test ratio with mixed primary/secondary sources."""
        graph = EvidenceGraph()
        
        # page-1 is secondary (cites page-2)
        graph.add_node(NodeType.PAGE, "page-1")
        graph.add_node(NodeType.PAGE, "page-2")
        graph.add_node(NodeType.PAGE, "page-3")
        
        graph.add_edge(
            NodeType.PAGE, "page-1",
            NodeType.PAGE, "page-2",
            RelationType.CITES,
        )
        
        ratio = graph.get_primary_source_ratio()
        
        assert ratio["primary_count"] == 2  # page-2 and page-3
        assert ratio["secondary_count"] == 1  # page-1
        assert ratio["total_pages"] == 3

    def test_primary_source_ratio_empty(self):
        """Test ratio for empty graph."""
        graph = EvidenceGraph()
        
        ratio = graph.get_primary_source_ratio()
        
        assert ratio["primary_ratio"] == 0.0
        assert ratio["meets_threshold"] is False


class TestLoopSeverity:
    """Tests for loop severity calculation."""

    def test_severity_calculation(self):
        """Test loop severity based on length."""
        graph = EvidenceGraph()
        
        assert graph._calculate_loop_severity(2) == "critical"
        assert graph._calculate_loop_severity(3) == "high"
        assert graph._calculate_loop_severity(5) == "medium"
        assert graph._calculate_loop_severity(10) == "low"


class TestDatabaseIntegration:
    """Tests for database persistence."""

    @pytest.mark.asyncio
    async def test_save_and_load(self, test_database):
        """Test saving and loading graph from database."""
        from src.filter import evidence_graph
        from unittest.mock import patch
        
        # Create and populate graph
        graph = EvidenceGraph(task_id="test-task")
        
        graph.add_edge(
            source_type=NodeType.FRAGMENT,
            source_id="frag-1",
            target_type=NodeType.CLAIM,
            target_id="claim-1",
            relation=RelationType.SUPPORTS,
            confidence=0.9,
        )
        
        # Save to database
        with patch.object(evidence_graph, "get_database", return_value=test_database):
            await graph.save_to_db()
        
        # Verify in database
        edges = await test_database.fetch_all("SELECT * FROM edges")
        assert len(edges) == 1
        assert edges[0]["source_type"] == "fragment"
        assert edges[0]["target_type"] == "claim"
        assert edges[0]["relation"] == "supports"

    @pytest.mark.asyncio
    async def test_add_claim_evidence_persists(self, test_database):
        """Test add_claim_evidence persists to database."""
        from src.filter import evidence_graph
        from unittest.mock import patch, AsyncMock
        
        # Mock get_evidence_graph to return a fresh graph
        mock_graph = EvidenceGraph(task_id="test")
        
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
        
        assert edge_id is not None
        
        # Verify in database
        edges = await test_database.fetch_all("SELECT * FROM edges")
        assert len(edges) == 1
        assert edges[0]["confidence"] == 0.85

