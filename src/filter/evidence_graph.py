"""
Evidence graph for Lyra.
Manages relationships between claims, fragments, and sources.
Uses NetworkX for in-memory graph operations and SQLite for persistence.
"""

import uuid
from enum import Enum
from typing import Any

import networkx as nx

from src.storage.database import get_database
from src.utils.logging import CausalTrace, get_logger

logger = get_logger(__name__)


class NodeType(str, Enum):
    """Types of nodes in the evidence graph."""

    CLAIM = "claim"
    FRAGMENT = "fragment"
    PAGE = "page"


class RelationType(str, Enum):
    """Types of relationships between nodes."""

    SUPPORTS = "supports"
    REFUTES = "refutes"
    CITES = "cites"
    NEUTRAL = "neutral"


class EvidenceGraph:
    """Evidence graph for tracking claim-evidence relationships.

    Uses a directed graph where:
    - Nodes represent claims, fragments, or pages
    - Edges represent relationships (supports, refutes, cites, neutral)

    The graph is backed by SQLite for persistence.
    """

    def __init__(self, task_id: str | None = None):
        """Initialize evidence graph.

        Args:
            task_id: Associated task ID for scoping.
        """
        self.task_id = task_id
        self._graph = nx.DiGraph()

    def _make_node_id(self, node_type: NodeType, obj_id: str) -> str:
        """Create composite node ID.

        Args:
            node_type: Type of node.
            obj_id: Object ID.

        Returns:
            Composite node ID.
        """
        return f"{node_type.value}:{obj_id}"

    def _parse_node_id(self, node_id: str) -> tuple[NodeType, str]:
        """Parse composite node ID.

        Args:
            node_id: Composite node ID.

        Returns:
            Tuple of (NodeType, object_id).
        """
        node_type_str, obj_id = node_id.split(":", 1)
        return NodeType(node_type_str), obj_id

    def add_node(
        self,
        node_type: NodeType,
        obj_id: str,
        **attributes: Any,
    ) -> str:
        """Add a node to the graph.

        Args:
            node_type: Type of node (claim, fragment, page).
            obj_id: Object ID.
            **attributes: Additional node attributes.

        Returns:
            Node ID.
        """
        node_id = self._make_node_id(node_type, obj_id)

        self._graph.add_node(
            node_id,
            node_type=node_type.value,
            obj_id=obj_id,
            **attributes,
        )

        return node_id

    def add_edge(
        self,
        source_type: NodeType,
        source_id: str,
        target_type: NodeType,
        target_id: str,
        relation: RelationType,
        confidence: float | None = None,
        nli_label: str | None = None,
        nli_confidence: float | None = None,
        **attributes: Any,
    ) -> str:
        """Add an edge (relationship) to the graph.

        Args:
            source_type: Type of source node.
            source_id: Source object ID.
            target_type: Type of target node.
            target_id: Target object ID.
            relation: Relationship type.
            confidence: Overall confidence score.
            nli_label: NLI model label.
            nli_confidence: NLI model confidence.
            **attributes: Additional edge attributes.

        Returns:
            Edge ID.
        """
        source_node = self._make_node_id(source_type, source_id)
        target_node = self._make_node_id(target_type, target_id)

        # Ensure nodes exist
        if source_node not in self._graph:
            self.add_node(source_type, source_id)
        if target_node not in self._graph:
            self.add_node(target_type, target_id)

        edge_id = str(uuid.uuid4())

        self._graph.add_edge(
            source_node,
            target_node,
            edge_id=edge_id,
            relation=relation.value,
            confidence=confidence,
            nli_label=nli_label,
            nli_confidence=nli_confidence,
            **attributes,
        )

        return edge_id

    def get_supporting_evidence(
        self,
        claim_id: str,
    ) -> list[dict[str, Any]]:
        """Get all evidence supporting a claim.

        Args:
            claim_id: Claim object ID.

        Returns:
            List of supporting evidence dicts.
        """
        claim_node = self._make_node_id(NodeType.CLAIM, claim_id)

        if claim_node not in self._graph:
            return []

        evidence = []

        # Get incoming edges with 'supports' relation
        for predecessor in self._graph.predecessors(claim_node):
            edge_data = self._graph.edges[predecessor, claim_node]

            if edge_data.get("relation") == RelationType.SUPPORTS.value:
                node_type, obj_id = self._parse_node_id(predecessor)
                node_data = self._graph.nodes[predecessor]

                evidence.append(
                    {
                        "node_type": node_type.value,
                        "obj_id": obj_id,
                        "relation": edge_data.get("relation"),
                        "confidence": edge_data.get("confidence"),
                        "nli_confidence": edge_data.get("nli_confidence"),
                        **{k: v for k, v in node_data.items() if k not in ("node_type", "obj_id")},
                    }
                )

        return evidence

    def get_refuting_evidence(
        self,
        claim_id: str,
    ) -> list[dict[str, Any]]:
        """Get all evidence refuting a claim.

        Args:
            claim_id: Claim object ID.

        Returns:
            List of refuting evidence dicts.
        """
        claim_node = self._make_node_id(NodeType.CLAIM, claim_id)

        if claim_node not in self._graph:
            return []

        evidence = []

        for predecessor in self._graph.predecessors(claim_node):
            edge_data = self._graph.edges[predecessor, claim_node]

            if edge_data.get("relation") == RelationType.REFUTES.value:
                node_type, obj_id = self._parse_node_id(predecessor)
                node_data = self._graph.nodes[predecessor]

                evidence.append(
                    {
                        "node_type": node_type.value,
                        "obj_id": obj_id,
                        "relation": edge_data.get("relation"),
                        "confidence": edge_data.get("confidence"),
                        "nli_confidence": edge_data.get("nli_confidence"),
                        **{k: v for k, v in node_data.items() if k not in ("node_type", "obj_id")},
                    }
                )

        return evidence

    def get_all_evidence(
        self,
        claim_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """Get all evidence for a claim, categorized by relation.

        Args:
            claim_id: Claim object ID.

        Returns:
            Dict with 'supports', 'refutes', 'neutral' lists.
        """
        claim_node = self._make_node_id(NodeType.CLAIM, claim_id)

        result: dict[str, list[dict[str, Any]]] = {
            "supports": [],
            "refutes": [],
            "neutral": [],
        }

        if claim_node not in self._graph:
            return result

        for predecessor in self._graph.predecessors(claim_node):
            edge_data = self._graph.edges[predecessor, claim_node]
            relation = edge_data.get("relation", "neutral")

            node_type, obj_id = self._parse_node_id(predecessor)
            node_data = self._graph.nodes[predecessor]

            evidence = {
                "node_type": node_type.value,
                "obj_id": obj_id,
                "relation": relation,
                "confidence": edge_data.get("confidence"),
                "nli_confidence": edge_data.get("nli_confidence"),
                **{k: v for k, v in node_data.items() if k not in ("node_type", "obj_id")},
            }

            if relation in result:
                result[relation].append(evidence)

        return result

    def get_citation_chain(
        self,
        node_type: NodeType,
        obj_id: str,
        max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        """Trace citation chain from a node to primary sources.

        Args:
            node_type: Starting node type.
            obj_id: Starting object ID.
            max_depth: Maximum chain depth.

        Returns:
            List of nodes in citation chain.
        """
        start_node = self._make_node_id(node_type, obj_id)

        if start_node not in self._graph:
            return []

        chain: list[dict[str, Any]] = []
        visited: set[str] = set()
        current: str | None = start_node
        depth = 0

        while current and depth < max_depth:
            if current in visited:
                break
            visited.add(current)

            node_type_current, obj_id_current = self._parse_node_id(current)
            node_data = self._graph.nodes[current]

            chain.append(
                {
                    "depth": depth,
                    "node_type": node_type_current.value,
                    "obj_id": obj_id_current,
                    **{k: v for k, v in node_data.items() if k not in ("node_type", "obj_id")},
                }
            )

            # Find next citation
            next_node = None
            for successor in self._graph.successors(current):
                edge_data = self._graph.edges[current, successor]
                if edge_data.get("relation") == RelationType.CITES.value:
                    next_node = successor
                    break

            current = next_node
            depth += 1

        return chain

    def calculate_claim_confidence(
        self,
        claim_id: str,
    ) -> dict[str, Any]:
        """Calculate overall confidence for a claim based on evidence.

        Args:
            claim_id: Claim object ID.

        Returns:
            Confidence assessment dict.
        """
        evidence = self.get_all_evidence(claim_id)

        supporting_count = len(evidence["supports"])
        refuting_count = len(evidence["refutes"])
        neutral_count = len(evidence["neutral"])
        total_count = supporting_count + refuting_count + neutral_count

        if total_count == 0:
            return {
                "confidence": 0.0,
                "supporting_count": 0,
                "refuting_count": 0,
                "neutral_count": 0,
                "verdict": "unverified",
                "independent_sources": 0,
            }

        # Calculate average confidence from supporting evidence
        support_confidences = [e.get("confidence", 0.5) for e in evidence["supports"]]
        avg_support_confidence = (
            sum(support_confidences) / len(support_confidences) if support_confidences else 0.0
        )

        # Count unique sources (pages)
        unique_sources = set()
        for category in evidence.values():
            for e in category:
                if e.get("node_type") == NodeType.PAGE.value:
                    unique_sources.add(e.get("obj_id"))
                # Also count fragments' parent pages if available

        # Calculate overall confidence
        if refuting_count > 0:
            # Presence of refutation lowers confidence
            confidence = avg_support_confidence * (
                supporting_count / (supporting_count + refuting_count * 2)
            )
            verdict = "contested" if supporting_count > refuting_count else "likely_false"
        elif supporting_count >= 3:
            confidence = min(avg_support_confidence * 1.1, 1.0)
            verdict = "well_supported"
        elif supporting_count >= 1:
            confidence = avg_support_confidence
            verdict = "supported"
        else:
            confidence = 0.3
            verdict = "unverified"

        return {
            "confidence": round(confidence, 3),
            "supporting_count": supporting_count,
            "refuting_count": refuting_count,
            "neutral_count": neutral_count,
            "verdict": verdict,
            "independent_sources": len(unique_sources),
        }

    def find_contradictions(self) -> list[dict[str, Any]]:
        """Find contradicting claims in the graph.

        Returns:
            List of contradiction pairs.
        """
        contradictions = []

        # Get all claim nodes
        claim_nodes = [
            n
            for n in self._graph.nodes()
            if self._graph.nodes[n].get("node_type") == NodeType.CLAIM.value
        ]

        # Check for mutual refutation
        for i, claim1 in enumerate(claim_nodes):
            for claim2 in claim_nodes[i + 1 :]:
                # Check if claim1 refutes claim2 or vice versa
                edge1 = self._graph.edges.get((claim1, claim2), {})
                edge2 = self._graph.edges.get((claim2, claim1), {})

                if (
                    edge1.get("relation") == RelationType.REFUTES.value
                    or edge2.get("relation") == RelationType.REFUTES.value
                ):
                    _, id1 = self._parse_node_id(claim1)
                    _, id2 = self._parse_node_id(claim2)

                    contradictions.append(
                        {
                            "claim1_id": id1,
                            "claim2_id": id2,
                            "claim1_data": dict(self._graph.nodes[claim1]),
                            "claim2_data": dict(self._graph.nodes[claim2]),
                            "confidence": max(
                                edge1.get("confidence", 0),
                                edge2.get("confidence", 0),
                            ),
                        }
                    )

        return contradictions

    def mark_contradictions(self) -> int:
        """Mark detected contradictions with is_contradiction flag.

        Detects contradicting edges and marks them with is_contradiction=True
        for persistence and later querying.

        Returns:
            Number of contradiction pairs marked.
        """
        contradictions = self.find_contradictions()

        for c in contradictions:
            claim1_node = self._make_node_id(NodeType.CLAIM, c["claim1_id"])
            claim2_node = self._make_node_id(NodeType.CLAIM, c["claim2_id"])

            # Mark edges in both directions if they exist
            if (claim1_node, claim2_node) in self._graph.edges:
                self._graph.edges[claim1_node, claim2_node]["is_contradiction"] = True
            if (claim2_node, claim1_node) in self._graph.edges:
                self._graph.edges[claim2_node, claim1_node]["is_contradiction"] = True

        return len(contradictions)

    def set_claim_adoption_status(self, claim_id: str, status: str) -> None:
        """Set adoption status for a claim.

        Args:
            claim_id: Claim object ID.
            status: Adoption status ('pending', 'adopted', 'not_adopted').
        """
        node_id = self._make_node_id(NodeType.CLAIM, claim_id)
        if node_id in self._graph:
            self._graph.nodes[node_id]["adoption_status"] = status
            logger.debug(
                "Claim adoption status updated",
                claim_id=claim_id,
                adoption_status=status,
            )
        else:
            logger.warning(
                "Cannot set adoption status: claim not found",
                claim_id=claim_id,
            )

    def get_claim_adoption_status(self, claim_id: str) -> str | None:
        """Get adoption status for a claim.

        Args:
            claim_id: Claim object ID.

        Returns:
            Adoption status or None if claim not found.
        """
        node_id = self._make_node_id(NodeType.CLAIM, claim_id)
        if node_id in self._graph:
            return self._graph.nodes[node_id].get("adoption_status", "pending")
        return None

    def get_claims_by_adoption_status(self, status: str) -> list[str]:
        """Get all claim IDs with a specific adoption status.

        Args:
            status: Adoption status to filter by.

        Returns:
            List of claim IDs.
        """
        result = []
        for node_id in self._graph.nodes():
            node_data = self._graph.nodes[node_id]
            if node_data.get("node_type") == NodeType.CLAIM.value:
                if node_data.get("adoption_status", "pending") == status:
                    _, obj_id = self._parse_node_id(node_id)
                    result.append(obj_id)
        return result

    def get_contradiction_edges(self) -> list[dict[str, Any]]:
        """Get all edges marked as contradictions.

        Returns:
            List of contradiction edge data.
        """
        result = []
        for source, target, data in self._graph.edges(data=True):
            if data.get("is_contradiction"):
                result.append({
                    "source": source,
                    "target": target,
                    **data,
                })
        return result

    def detect_citation_loops(self) -> list[dict[str, Any]]:
        """Detect citation loops (cycles) in the graph.

        Citation loops occur when sources cite each other in a circular pattern,
        e.g., A cites B, B cites C, C cites A.

        Returns:
            List of detected loops with metadata.
        """
        loops: list[dict[str, Any]] = []

        # Build subgraph with only citation edges
        citation_edges = [
            (u, v)
            for u, v, d in self._graph.edges(data=True)
            if d.get("relation") == RelationType.CITES.value
        ]

        if not citation_edges:
            return loops

        citation_graph = nx.DiGraph()
        citation_graph.add_edges_from(citation_edges)

        # Find all simple cycles
        try:
            cycles = list(nx.simple_cycles(citation_graph))
        except Exception as e:
            logger.warning("Error detecting cycles", error=str(e))
            return loops

        for cycle in cycles:
            # Parse node information
            cycle_info = []
            for node_id in cycle:
                if node_id in self._graph.nodes:
                    node_type, obj_id = self._parse_node_id(node_id)
                    cycle_info.append(
                        {
                            "node_id": node_id,
                            "node_type": node_type.value,
                            "obj_id": obj_id,
                        }
                    )

            if cycle_info:
                loops.append(
                    {
                        "type": "citation_loop",
                        "length": len(cycle),
                        "nodes": cycle_info,
                        "severity": self._calculate_loop_severity(len(cycle)),
                    }
                )

        return loops

    def detect_round_trips(self) -> list[dict[str, Any]]:
        """Detect round-trip citations (A cites B, B cites A).

        Round-trips are a special case of citation loops with length 2,
        indicating mutual citation which may be problematic for credibility.

        Returns:
            List of round-trip pairs.
        """
        round_trips = []

        # Check for bidirectional citation edges
        checked_pairs = set()

        for u, v, data in self._graph.edges(data=True):
            if data.get("relation") != RelationType.CITES.value:
                continue

            # Create canonical pair ID to avoid duplicates
            pair_id = tuple(sorted([u, v]))
            if pair_id in checked_pairs:
                continue
            checked_pairs.add(pair_id)

            # Check if reverse edge exists
            if self._graph.has_edge(v, u):
                reverse_data = self._graph.edges[v, u]
                if reverse_data.get("relation") == RelationType.CITES.value:
                    # Found round-trip
                    type_u, id_u = self._parse_node_id(u)
                    type_v, id_v = self._parse_node_id(v)

                    round_trips.append(
                        {
                            "type": "round_trip",
                            "node_a": {
                                "node_id": u,
                                "node_type": type_u.value,
                                "obj_id": id_u,
                            },
                            "node_b": {
                                "node_id": v,
                                "node_type": type_v.value,
                                "obj_id": id_v,
                            },
                            "severity": "high",  # Round-trips are always high severity
                        }
                    )

        return round_trips

    def detect_self_references(self) -> list[dict[str, Any]]:
        """Detect self-references (node citing itself or same-domain citations).

        Self-references include:
        - Direct self-loops (A cites A)
        - Same-domain citations (detected by domain attribute if available)

        Returns:
            List of self-reference issues.
        """
        self_refs = []

        for u, v, data in self._graph.edges(data=True):
            if data.get("relation") != RelationType.CITES.value:
                continue

            # Check for direct self-loop
            if u == v:
                node_type, obj_id = self._parse_node_id(u)
                self_refs.append(
                    {
                        "type": "direct_self_reference",
                        "node_id": u,
                        "node_type": node_type.value,
                        "obj_id": obj_id,
                        "severity": "critical",
                    }
                )
                continue

            # Check for same-domain citation (if domain info available)
            u_data = self._graph.nodes.get(u, {})
            v_data = self._graph.nodes.get(v, {})

            u_domain = u_data.get("domain")
            v_domain = v_data.get("domain")

            if u_domain and v_domain and u_domain == v_domain:
                type_u, id_u = self._parse_node_id(u)
                type_v, id_v = self._parse_node_id(v)

                self_refs.append(
                    {
                        "type": "same_domain_citation",
                        "source": {
                            "node_id": u,
                            "node_type": type_u.value,
                            "obj_id": id_u,
                        },
                        "target": {
                            "node_id": v,
                            "node_type": type_v.value,
                            "obj_id": id_v,
                        },
                        "domain": u_domain,
                        "severity": "medium",
                    }
                )

        return self_refs

    def _calculate_loop_severity(self, loop_length: int) -> str:
        """Calculate severity of a citation loop based on length.

        Args:
            loop_length: Number of nodes in the loop.

        Returns:
            Severity level (critical/high/medium/low).
        """
        if loop_length <= 2:
            return "critical"
        elif loop_length <= 3:
            return "high"
        elif loop_length <= 5:
            return "medium"
        else:
            return "low"

    def calculate_citation_penalties(self) -> dict[str, float]:
        """Calculate citation-based penalties for nodes.

        Nodes involved in loops, round-trips, or self-references
        receive penalty scores that reduce their credibility weight.

        Returns:
            Dict mapping node_id to penalty score (0.0 to 1.0, where 1.0 = no penalty).
        """
        penalties: dict[str, float] = {}

        # Initialize all nodes with no penalty
        for node in self._graph.nodes():
            penalties[node] = 1.0

        # Apply penalties for citation loops
        loops = self.detect_citation_loops()
        for loop in loops:
            severity = loop["severity"]
            penalty_factor = {
                "critical": 0.2,
                "high": 0.4,
                "medium": 0.6,
                "low": 0.8,
            }.get(severity, 0.8)

            for node_info in loop["nodes"]:
                node_id = node_info["node_id"]
                # Multiply penalties (cumulative for multiple issues)
                penalties[node_id] *= penalty_factor

        # Apply penalties for round-trips
        round_trips = self.detect_round_trips()
        for rt in round_trips:
            # Round-trips get 0.3 penalty multiplier
            penalties[rt["node_a"]["node_id"]] *= 0.3
            penalties[rt["node_b"]["node_id"]] *= 0.3

        # Apply penalties for self-references
        self_refs = self.detect_self_references()
        for sr in self_refs:
            severity = sr["severity"]
            penalty_factor = {
                "critical": 0.1,  # Direct self-ref is very bad
                "high": 0.3,
                "medium": 0.5,
                "low": 0.7,
            }.get(severity, 0.7)

            if sr["type"] == "direct_self_reference":
                penalties[sr["node_id"]] *= penalty_factor
            else:
                penalties[sr["source"]["node_id"]] *= penalty_factor
                penalties[sr["target"]["node_id"]] *= penalty_factor * 1.2  # Target less penalized

        # Clamp to [0.0, 1.0]
        for node_id in penalties:
            penalties[node_id] = max(0.0, min(1.0, penalties[node_id]))

        return penalties

    def get_citation_integrity_report(self) -> dict[str, Any]:
        """Generate comprehensive citation integrity report.

        Returns:
            Report dict with loops, round-trips, self-refs, and metrics.
        """
        loops = self.detect_citation_loops()
        round_trips = self.detect_round_trips()
        self_refs = self.detect_self_references()
        penalties = self.calculate_citation_penalties()

        # Calculate metrics
        total_citation_edges = sum(
            1
            for _, _, d in self._graph.edges(data=True)
            if d.get("relation") == RelationType.CITES.value
        )

        # Count problematic citations
        problematic_nodes = set()
        for loop in loops:
            for node in loop["nodes"]:
                problematic_nodes.add(node["node_id"])
        for rt in round_trips:
            problematic_nodes.add(rt["node_a"]["node_id"])
            problematic_nodes.add(rt["node_b"]["node_id"])
        for sr in self_refs:
            if sr["type"] == "direct_self_reference":
                problematic_nodes.add(sr["node_id"])
            else:
                problematic_nodes.add(sr["source"]["node_id"])

        # Calculate integrity score
        if total_citation_edges > 0:
            clean_ratio = 1.0 - (len(problematic_nodes) / max(len(penalties), 1))
            integrity_score = max(0.0, min(1.0, clean_ratio))
        else:
            integrity_score = 1.0  # No citations = no issues

        # Nodes with significant penalties
        penalized_nodes = [
            {"node_id": k, "penalty_factor": v} for k, v in penalties.items() if v < 0.9
        ]

        return {
            "integrity_score": round(integrity_score, 3),
            "total_citation_edges": total_citation_edges,
            "loop_count": len(loops),
            "round_trip_count": len(round_trips),
            "self_reference_count": len(self_refs),
            "problematic_node_count": len(problematic_nodes),
            "loops": loops,
            "round_trips": round_trips,
            "self_references": self_refs,
            "penalized_nodes": sorted(penalized_nodes, key=lambda x: x["penalty_factor"]),
        }

    def get_primary_source_ratio(self) -> dict[str, Any]:
        """Calculate the ratio of primary vs secondary source citations.

        Primary sources are pages with depth 0 in citation chains.
        Secondary sources cite other sources.

        Returns:
            Ratio information dict.
        """
        page_nodes = [
            n
            for n in self._graph.nodes()
            if self._graph.nodes[n].get("node_type") == NodeType.PAGE.value
        ]

        primary_count = 0
        secondary_count = 0

        for page_node in page_nodes:
            # Check if this page cites other pages
            has_outgoing_citation = False
            for _, target, data in self._graph.out_edges(page_node, data=True):
                if data.get("relation") == RelationType.CITES.value:
                    target_type = self._graph.nodes[target].get("node_type")
                    if target_type == NodeType.PAGE.value:
                        has_outgoing_citation = True
                        break

            if has_outgoing_citation:
                secondary_count += 1
            else:
                primary_count += 1

        total = primary_count + secondary_count
        primary_ratio = primary_count / total if total > 0 else 0.0

        return {
            "primary_count": primary_count,
            "secondary_count": secondary_count,
            "total_pages": total,
            "primary_ratio": round(primary_ratio, 3),
            "meets_threshold": primary_ratio >= 0.6,  # §7 requirement
        }

    def get_stats(self) -> dict[str, Any]:
        """Get graph statistics.

        Returns:
            Statistics dict.
        """
        node_counts = {
            NodeType.CLAIM.value: 0,
            NodeType.FRAGMENT.value: 0,
            NodeType.PAGE.value: 0,
        }

        for node in self._graph.nodes():
            node_type = self._graph.nodes[node].get("node_type")
            if node_type in node_counts:
                node_counts[node_type] += 1

        edge_counts = {
            RelationType.SUPPORTS.value: 0,
            RelationType.REFUTES.value: 0,
            RelationType.CITES.value: 0,
            RelationType.NEUTRAL.value: 0,
        }

        for _, _, data in self._graph.edges(data=True):
            relation = data.get("relation")
            if relation in edge_counts:
                edge_counts[relation] += 1

        # Include citation integrity metrics
        integrity = self.get_citation_integrity_report()

        return {
            "total_nodes": self._graph.number_of_nodes(),
            "total_edges": self._graph.number_of_edges(),
            "node_counts": node_counts,
            "edge_counts": edge_counts,
            "citation_integrity_score": integrity["integrity_score"],
            "citation_loop_count": integrity["loop_count"],
            "round_trip_count": integrity["round_trip_count"],
        }

    async def save_to_db(self) -> None:
        """Persist graph edges to database."""
        db = await get_database()

        with CausalTrace() as trace:
            for source, target, data in self._graph.edges(data=True):
                source_type, source_id = self._parse_node_id(source)
                target_type, target_id = self._parse_node_id(target)

                await db.insert(
                    "edges",
                    {
                        "id": data.get("edge_id", str(uuid.uuid4())),
                        "source_type": source_type.value,
                        "source_id": source_id,
                        "target_type": target_type.value,
                        "target_id": target_id,
                        "relation": data.get("relation"),
                        "confidence": data.get("confidence"),
                        "nli_label": data.get("nli_label"),
                        "nli_confidence": data.get("nli_confidence"),
                        "is_academic": 1 if data.get("is_academic") else 0,
                        "is_influential": 1 if data.get("is_influential") else 0,
                        "citation_context": data.get("citation_context"),
                        "cause_id": trace.id,
                    },
                    or_replace=True,
                )

        logger.info(
            "Evidence graph saved",
            edge_count=self._graph.number_of_edges(),
            task_id=self.task_id,
        )

    async def load_from_db(self, task_id: str | None = None) -> None:
        """Load graph edges from database.

        Args:
            task_id: Optional task ID to filter by.
        """
        db = await get_database()

        # Load edges
        if task_id:
            # Filter by task via claims
            edges = await db.fetch_all(
                """
                SELECT e.* FROM edges e
                WHERE e.source_type = 'claim' AND e.source_id IN (
                    SELECT id FROM claims WHERE task_id = ?
                )
                OR e.target_type = 'claim' AND e.target_id IN (
                    SELECT id FROM claims WHERE task_id = ?
                )
                """,
                (task_id, task_id),
            )
        else:
            edges = await db.fetch_all("SELECT * FROM edges")

        # Rebuild graph
        self._graph.clear()

        for edge in edges:
            source_type = NodeType(edge["source_type"])
            target_type = NodeType(edge["target_type"])

            self.add_edge(
                source_type=source_type,
                source_id=edge["source_id"],
                target_type=target_type,
                target_id=edge["target_id"],
                relation=RelationType(edge["relation"]),
                confidence=edge.get("confidence"),
                nli_label=edge.get("nli_label"),
                nli_confidence=edge.get("nli_confidence"),
            )

        logger.info(
            "Evidence graph loaded",
            edge_count=len(edges),
            task_id=task_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Export graph as dict.

        Returns:
            Graph data as dict.
        """
        nodes = []
        for node_id in self._graph.nodes():
            node_data = dict(self._graph.nodes[node_id])
            node_data["id"] = node_id
            nodes.append(node_data)

        edges = []
        for source, target, data in self._graph.edges(data=True):
            edges.append(
                {
                    "source": source,
                    "target": target,
                    **data,
                }
            )

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": self.get_stats(),
        }


# Global graph instance
_graph: EvidenceGraph | None = None


async def get_evidence_graph(task_id: str | None = None) -> EvidenceGraph:
    """Get or create evidence graph for a task.

    Args:
        task_id: Task ID.

    Returns:
        EvidenceGraph instance.
    """
    global _graph

    if _graph is None or _graph.task_id != task_id:
        _graph = EvidenceGraph(task_id=task_id)
        if task_id:
            await _graph.load_from_db(task_id)

    return _graph


async def add_claim_evidence(
    claim_id: str,
    fragment_id: str,
    relation: str,
    confidence: float,
    nli_label: str | None = None,
    nli_confidence: float | None = None,
    task_id: str | None = None,
) -> str:
    """Add evidence relationship for a claim.

    Args:
        claim_id: Claim ID.
        fragment_id: Fragment ID providing evidence.
        relation: Relationship type (supports/refutes/neutral).
        confidence: Confidence score.
        nli_label: NLI model label.
        nli_confidence: NLI model confidence.
        task_id: Task ID.

    Returns:
        Edge ID.
    """
    graph = await get_evidence_graph(task_id)

    edge_id = graph.add_edge(
        source_type=NodeType.FRAGMENT,
        source_id=fragment_id,
        target_type=NodeType.CLAIM,
        target_id=claim_id,
        relation=RelationType(relation),
        confidence=confidence,
        nli_label=nli_label,
        nli_confidence=nli_confidence,
    )

    # Persist immediately
    db = await get_database()
    await db.insert(
        "edges",
        {
            "id": edge_id,
            "source_type": NodeType.FRAGMENT.value,
            "source_id": fragment_id,
            "target_type": NodeType.CLAIM.value,
            "target_id": claim_id,
            "relation": relation,
            "confidence": confidence,
            "nli_label": nli_label,
            "nli_confidence": nli_confidence,
        },
        or_replace=True,
    )

    logger.debug(
        "Claim evidence added",
        claim_id=claim_id,
        fragment_id=fragment_id,
        relation=relation,
    )

    return edge_id


async def add_citation(
    source_type: str,
    source_id: str,
    page_id: str,
    task_id: str | None = None,
    is_academic: bool = False,
    is_influential: bool = False,
    citation_context: str | None = None,
) -> str:
    """Add citation relationship.

    Args:
        source_type: Source node type (fragment/claim).
        source_id: Source object ID.
        page_id: Page being cited.
        task_id: Task ID.
        is_academic: Whether this is an academic citation.
        is_influential: Whether this is an influential citation (Semantic Scholar).
        citation_context: Citation context text.

    Returns:
        Edge ID.
    """
    graph = await get_evidence_graph(task_id)

    edge_id = graph.add_edge(
        source_type=NodeType(source_type),
        source_id=source_id,
        target_type=NodeType.PAGE,
        target_id=page_id,
        relation=RelationType.CITES,
        confidence=1.0,
        is_academic=is_academic,
        is_influential=is_influential,
        citation_context=citation_context,
    )

    # Persist
    db = await get_database()
    await db.insert(
        "edges",
        {
            "id": edge_id,
            "source_type": source_type,
            "source_id": source_id,
            "target_type": NodeType.PAGE.value,
            "target_id": page_id,
            "relation": RelationType.CITES.value,
            "confidence": 1.0,
            "is_academic": 1 if is_academic else 0,
            "is_influential": 1 if is_influential else 0,
            "citation_context": citation_context,
        },
        or_replace=True,
    )

    return edge_id


async def add_academic_page_with_citations(
    page_id: str,
    paper_metadata: dict,
    citations: list,
    task_id: str | None = None,
    paper_to_page_map: dict[str, str] | None = None,
) -> None:
    """Add academic paper and its citations to evidence graph.

    Adds PAGE node with academic metadata and CITES edges for citation relationships.

    Args:
        page_id: Page ID (from pages table)
        paper_metadata: Paper metadata dict (from paper_metadata JSON column)
        citations: List of Citation objects
        task_id: Task ID
        paper_to_page_map: Mapping from paper_id to page_id for cited papers.
                          If None, citations with paper IDs that don't map to pages
                          will be skipped.
    """
    from src.utils.schemas import Citation

    graph = await get_evidence_graph(task_id)
    db = await get_database()

    # Ensure PAGE node exists
    page_node = graph._make_node_id(NodeType.PAGE, page_id)
    if not graph._graph.has_node(page_node):
        graph.add_node(NodeType.PAGE, page_id)

    # Add academic metadata to node
    graph._graph.nodes[page_node].update(
        {
            "is_academic": True,
            "doi": paper_metadata.get("doi"),
            "citation_count": paper_metadata.get("citation_count", 0),
            "year": paper_metadata.get("year"),
            "venue": paper_metadata.get("venue"),
            "source_api": paper_metadata.get("source_api"),
        }
    )

    # Add citation edges
    if paper_to_page_map is None:
        paper_to_page_map = {}

    edges_created = 0
    edges_skipped = 0

    for citation in citations:
        if not isinstance(citation, Citation):
            continue

        # Map cited_paper_id (paper ID) to cited_page_id (page ID)
        cited_paper_id = citation.cited_paper_id
        cited_page_id = paper_to_page_map.get(cited_paper_id)

        # Skip citations where the cited paper doesn't have a corresponding page
        # (e.g., papers that weren't persisted because they had no abstract)
        if not cited_page_id:
            logger.debug(
                "Skipping citation: cited paper not in pages table",
                cited_paper_id=cited_paper_id,
                page_id=page_id,
            )
            edges_skipped += 1
            continue

        # Ensure cited PAGE node exists
        cited_node = graph._make_node_id(NodeType.PAGE, cited_page_id)
        if not graph._graph.has_node(cited_node):
            graph.add_node(NodeType.PAGE, cited_page_id)

        # Add CITES edge with academic attributes
        edge_id = graph.add_edge(
            source_type=NodeType.PAGE,
            source_id=page_id,
            target_type=NodeType.PAGE,
            target_id=cited_page_id,
            relation=RelationType.CITES,
            confidence=1.0,
            is_academic=True,
            is_influential=citation.is_influential,
            citation_context=citation.context,
        )

        # Persist edge to database
        await db.insert(
            "edges",
            {
                "id": edge_id,
                "source_type": NodeType.PAGE.value,
                "source_id": page_id,
                "target_type": NodeType.PAGE.value,
                "target_id": cited_page_id,
                "relation": RelationType.CITES.value,
                "confidence": 1.0,
                "is_academic": 1,
                "is_influential": 1 if citation.is_influential else 0,
                "citation_context": citation.context,
            },
            or_replace=True,
        )

        edges_created += 1

    logger.debug(
        "Added academic page with citations",
        page_id=page_id,
        edges_created=edges_created,
        edges_skipped=edges_skipped,
        citation_count=len(citations),
    )


async def get_claim_assessment(
    claim_id: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Get comprehensive assessment for a claim.

    Args:
        claim_id: Claim ID.
        task_id: Task ID.

    Returns:
        Assessment dict with evidence and confidence.
    """
    graph = await get_evidence_graph(task_id)

    evidence = graph.get_all_evidence(claim_id)
    confidence = graph.calculate_claim_confidence(claim_id)

    return {
        "claim_id": claim_id,
        "evidence": evidence,
        **confidence,
    }
