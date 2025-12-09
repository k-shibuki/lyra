"""
Report materials collection for Lancet.

Provides unified API for collecting report materials including claims,
fragments, and evidence graph.

See requirements.md §3.2.1.
"""

from typing import Any

from src.storage.database import get_database
from src.utils.logging import get_logger, LogContext

logger = get_logger(__name__)


async def get_materials_action(
    task_id: str,
    include_graph: bool = False,
    format: str = "structured",
) -> dict[str, Any]:
    """
    Unified API for get_materials action (Phase M architecture).
    
    Collects report materials including claims, fragments, and optionally
    the evidence graph.
    
    Args:
        task_id: The task ID.
        include_graph: Whether to include evidence graph (default: False).
        format: Output format - "structured" or "narrative" (default: "structured").
        
    Returns:
        Materials conforming to §3.2.1 schema.
    """
    db = await get_database()
    
    with LogContext(task_id=task_id):
        logger.info("Collecting report materials", include_graph=include_graph)
        
        # Get task info
        task = await db.fetch_one(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        )
        
        if not task:
            return {
                "ok": False,
                "error": f"Task not found: {task_id}",
            }
        
        original_query = task.get("query", "")
        
        # Collect claims
        claims = await _collect_claims(db, task_id)
        
        # Collect fragments
        fragments = await _collect_fragments(db, task_id)
        
        # Build evidence graph if requested
        evidence_graph = None
        if include_graph:
            evidence_graph = await _build_evidence_graph(db, task_id)
        
        # Calculate summary
        verified_count = sum(1 for c in claims if c.get("evidence_count", 0) >= 2)
        refuted_count = sum(1 for c in claims if c.get("has_refutation", False))
        primary_count = sum(1 for f in fragments if f.get("is_primary", False))
        
        result: dict[str, Any] = {
            "ok": True,
            "task_id": task_id,
            "query": original_query,
            "claims": claims,
            "fragments": fragments,
            "summary": {
                "total_claims": len(claims),
                "verified_claims": verified_count,
                "refuted_claims": refuted_count,
                "primary_source_ratio": primary_count / max(1, len(fragments)),
            },
        }
        
        if evidence_graph:
            result["evidence_graph"] = evidence_graph
        
        return result


async def _collect_claims(db, task_id: str) -> list[dict[str, Any]]:
    """Collect claims for a task."""
    claims = []
    
    try:
        rows = await db.fetch_all(
            """
            SELECT c.id, c.claim_text, c.confidence_score, c.source_url,
                   COUNT(DISTINCT e.id) as evidence_count,
                   MAX(CASE WHEN e.relation = 'refutes' THEN 1 ELSE 0 END) as has_refutation
            FROM claims c
            LEFT JOIN edges e ON e.target_id = c.id AND e.target_type = 'claim'
            WHERE c.task_id = ?
            GROUP BY c.id
            ORDER BY c.confidence_score DESC
            """,
            (task_id,),
        )
        
        for row in rows:
            # Get sources for this claim
            sources = await db.fetch_all(
                """
                SELECT DISTINCT f.source_url, f.title, f.is_primary
                FROM fragments f
                JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
                WHERE e.target_id = ? AND e.target_type = 'claim'
                """,
                (row["id"],),
            )
            
            claims.append({
                "id": row["id"],
                "text": row.get("claim_text", ""),
                "confidence": row.get("confidence_score", 0.5),
                "evidence_count": row.get("evidence_count", 0),
                "has_refutation": bool(row.get("has_refutation", 0)),
                "sources": [
                    {
                        "url": s.get("source_url", ""),
                        "title": s.get("title", ""),
                        "is_primary": bool(s.get("is_primary", False)),
                    }
                    for s in sources
                ],
            })
    
    except Exception as e:
        logger.debug("Failed to collect claims", task_id=task_id, error=str(e))
    
    return claims


async def _collect_fragments(db, task_id: str) -> list[dict[str, Any]]:
    """Collect fragments for a task."""
    fragments = []
    
    try:
        rows = await db.fetch_all(
            """
            SELECT id, text, source_url, title, heading_context, is_primary
            FROM fragments
            WHERE task_id = ?
            ORDER BY created_at DESC
            LIMIT 100
            """,
            (task_id,),
        )
        
        for row in rows:
            fragments.append({
                "id": row["id"],
                "text": row.get("text", "")[:500],  # Limit text length
                "source_url": row.get("source_url", ""),
                "context": row.get("heading_context", row.get("title", "")),
                "is_primary": bool(row.get("is_primary", False)),
            })
    
    except Exception as e:
        logger.debug("Failed to collect fragments", task_id=task_id, error=str(e))
    
    return fragments


async def _build_evidence_graph(db, task_id: str) -> dict[str, Any]:
    """Build evidence graph for a task."""
    nodes = []
    edges = []
    
    try:
        # Load from evidence_graph module if available
        from src.filter.evidence_graph import EvidenceGraph
        
        graph = EvidenceGraph(task_id=task_id)
        await graph.load_from_db(task_id=task_id)
        
        # Convert to serializable format
        graph_data = graph.to_dict()
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])
    
    except Exception as e:
        logger.debug("Failed to build evidence graph", task_id=task_id, error=str(e))
        
        # Fallback: build simple graph from DB
        try:
            # Get nodes (claims + fragments)
            claim_rows = await db.fetch_all(
                "SELECT id, 'claim' as type, claim_text as label FROM claims WHERE task_id = ?",
                (task_id,),
            )
            for row in claim_rows:
                nodes.append({
                    "id": row["id"],
                    "type": "claim",
                    "label": row.get("label", "")[:50],
                })
            
            fragment_rows = await db.fetch_all(
                "SELECT id, 'fragment' as type, source_url as label FROM fragments WHERE task_id = ? LIMIT 50",
                (task_id,),
            )
            for row in fragment_rows:
                nodes.append({
                    "id": row["id"],
                    "type": "fragment",
                    "label": row.get("label", "")[:50],
                })
            
            # Get edges
            edge_rows = await db.fetch_all(
                """
                SELECT id, source_type, source_id, target_type, target_id, relation, confidence
                FROM edges
                WHERE source_id IN (SELECT id FROM claims WHERE task_id = ?)
                   OR source_id IN (SELECT id FROM fragments WHERE task_id = ?)
                   OR target_id IN (SELECT id FROM claims WHERE task_id = ?)
                LIMIT 100
                """,
                (task_id, task_id, task_id),
            )
            for row in edge_rows:
                edges.append({
                    "source": row["source_id"],
                    "target": row["target_id"],
                    "relation": row.get("relation", "supports"),
                    "confidence": row.get("confidence", 0.5),
                })
        
        except Exception as e2:
            logger.debug("Fallback graph build failed", error=str(e2))
    
    return {"nodes": nodes, "edges": edges}

