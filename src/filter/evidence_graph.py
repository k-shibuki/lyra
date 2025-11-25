"""
Evidence graph for Lancet.
Manages relationships between claims, fragments, and sources.
Uses NetworkX for in-memory graph operations and SQLite for persistence.
"""

import json
import uuid
from enum import Enum
from typing import Any

import networkx as nx

from src.storage.database import get_database
from src.utils.logging import get_logger, CausalTrace

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
                
                evidence.append({
                    "node_type": node_type.value,
                    "obj_id": obj_id,
                    "relation": edge_data.get("relation"),
                    "confidence": edge_data.get("confidence"),
                    "nli_confidence": edge_data.get("nli_confidence"),
                    **{k: v for k, v in node_data.items() if k not in ("node_type", "obj_id")},
                })
        
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
                
                evidence.append({
                    "node_type": node_type.value,
                    "obj_id": obj_id,
                    "relation": edge_data.get("relation"),
                    "confidence": edge_data.get("confidence"),
                    "nli_confidence": edge_data.get("nli_confidence"),
                    **{k: v for k, v in node_data.items() if k not in ("node_type", "obj_id")},
                })
        
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
        
        result = {
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
        
        chain = []
        visited = set()
        current = start_node
        depth = 0
        
        while current and depth < max_depth:
            if current in visited:
                break
            visited.add(current)
            
            node_type_current, obj_id_current = self._parse_node_id(current)
            node_data = self._graph.nodes[current]
            
            chain.append({
                "depth": depth,
                "node_type": node_type_current.value,
                "obj_id": obj_id_current,
                **{k: v for k, v in node_data.items() if k not in ("node_type", "obj_id")},
            })
            
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
        support_confidences = [
            e.get("confidence", 0.5) for e in evidence["supports"]
        ]
        avg_support_confidence = (
            sum(support_confidences) / len(support_confidences)
            if support_confidences else 0.0
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
            confidence = avg_support_confidence * (supporting_count / (supporting_count + refuting_count * 2))
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
            n for n in self._graph.nodes()
            if self._graph.nodes[n].get("node_type") == NodeType.CLAIM.value
        ]
        
        # Check for mutual refutation
        for i, claim1 in enumerate(claim_nodes):
            for claim2 in claim_nodes[i + 1:]:
                # Check if claim1 refutes claim2 or vice versa
                edge1 = self._graph.edges.get((claim1, claim2), {})
                edge2 = self._graph.edges.get((claim2, claim1), {})
                
                if (edge1.get("relation") == RelationType.REFUTES.value or
                    edge2.get("relation") == RelationType.REFUTES.value):
                    
                    _, id1 = self._parse_node_id(claim1)
                    _, id2 = self._parse_node_id(claim2)
                    
                    contradictions.append({
                        "claim1_id": id1,
                        "claim2_id": id2,
                        "claim1_data": dict(self._graph.nodes[claim1]),
                        "claim2_data": dict(self._graph.nodes[claim2]),
                        "confidence": max(
                            edge1.get("confidence", 0),
                            edge2.get("confidence", 0),
                        ),
                    })
        
        return contradictions
    
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
        
        return {
            "total_nodes": self._graph.number_of_nodes(),
            "total_edges": self._graph.number_of_edges(),
            "node_counts": node_counts,
            "edge_counts": edge_counts,
        }
    
    async def save_to_db(self) -> None:
        """Persist graph edges to database."""
        db = await get_database()
        
        with CausalTrace() as trace:
            for source, target, data in self._graph.edges(data=True):
                source_type, source_id = self._parse_node_id(source)
                target_type, target_id = self._parse_node_id(target)
                
                await db.insert("edges", {
                    "id": data.get("edge_id", str(uuid.uuid4())),
                    "source_type": source_type.value,
                    "source_id": source_id,
                    "target_type": target_type.value,
                    "target_id": target_id,
                    "relation": data.get("relation"),
                    "confidence": data.get("confidence"),
                    "nli_label": data.get("nli_label"),
                    "nli_confidence": data.get("nli_confidence"),
                    "cause_id": trace.id,
                }, or_replace=True)
        
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
            edges.append({
                "source": source,
                "target": target,
                **data,
            })
        
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
    await db.insert("edges", {
        "id": edge_id,
        "source_type": NodeType.FRAGMENT.value,
        "source_id": fragment_id,
        "target_type": NodeType.CLAIM.value,
        "target_id": claim_id,
        "relation": relation,
        "confidence": confidence,
        "nli_label": nli_label,
        "nli_confidence": nli_confidence,
    }, or_replace=True)
    
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
) -> str:
    """Add citation relationship.
    
    Args:
        source_type: Source node type (fragment/claim).
        source_id: Source object ID.
        page_id: Page being cited.
        task_id: Task ID.
        
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
    )
    
    # Persist
    db = await get_database()
    await db.insert("edges", {
        "id": edge_id,
        "source_type": source_type,
        "source_id": source_id,
        "target_type": NodeType.PAGE.value,
        "target_id": page_id,
        "relation": RelationType.CITES.value,
        "confidence": 1.0,
    }, or_replace=True)
    
    return edge_id


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

