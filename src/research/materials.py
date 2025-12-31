"""
Report materials collection for Lyra.

Provides unified API for collecting report materials including claims,
fragments, and evidence graph.

See ADR-0003.
"""

from typing import Any

from src.storage.database import get_database
from src.utils.db_helpers import chunked
from src.utils.logging import LogContext, get_logger

logger = get_logger(__name__)


async def get_materials_action(
    task_id: str,
    include_graph: bool = False,
    include_citations: bool = False,
    format: str = "structured",
) -> dict[str, Any]:
    """
    Unified API for get_materials action.

    Collects report materials including claims, fragments, and optionally
    the evidence graph and citation network. MCP handler delegates to this
    function (see ADR-0003).

    Args:
        task_id: The task ID.
        include_graph: Whether to include evidence graph (default: False).
        include_citations: Whether to include citation network (default: False).
        format: Output format - "structured" or "narrative" (default: "structured").

    Returns:
        Materials dict (claims, fragments, optional graph, optional citation_network).
    """
    db = await get_database()

    with LogContext(task_id=task_id):
        logger.info(
            "Collecting report materials",
            include_graph=include_graph,
            include_citations=include_citations,
        )

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

        # Build citation network if requested
        citation_network = None
        if include_citations:
            citation_network = await _collect_citation_network(db, task_id)

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

        if citation_network:
            result["citation_network"] = citation_network

        return result


async def _collect_claims(db: Any, task_id: str) -> list[dict[str, Any]]:
    """Collect claims for a task.

    DB schema notes:
    - claims table has verification_notes (stores source_url) not source_url
    - fragments table has relevance_reason (stores source metadata) not source_url

    Includes Bayesian confidence metrics (uncertainty, controversy) and
    evidence details with time metadata for temporal judgments.
    """
    from src.filter.evidence_graph import EvidenceGraph

    claims = []

    # Load evidence graph for Bayesian confidence calculation
    graph = EvidenceGraph(task_id=task_id)
    try:
        await graph.load_from_db(task_id=task_id)
    except Exception as e:
        logger.debug("Failed to load evidence graph for claims", task_id=task_id, error=str(e))

    try:
        rows = await db.fetch_all(
            """
            SELECT c.id, c.claim_text, c.llm_claim_confidence, c.verification_notes,
                   c.source_fragment_ids,
                   c.claim_adoption_status, c.claim_rejection_reason,
                   COUNT(DISTINCT e.id) as evidence_count,
                   MAX(CASE WHEN e.relation = 'refutes' THEN 1 ELSE 0 END) as has_refutation
            FROM claims c
            LEFT JOIN edges e ON e.target_id = c.id AND e.target_type = 'claim'
            WHERE c.task_id = ?
            GROUP BY c.id
            ORDER BY c.llm_claim_confidence DESC
            """,
            (task_id,),
        )
        for row in rows:
            # Extract source_url from verification_notes (format: "source_url=...")
            verification_notes = row.get("verification_notes", "") or ""
            source_url = ""
            if "source_url=" in verification_notes:
                source_url = verification_notes.split("source_url=")[1].split(";")[0].strip()

            # Get sources from linked fragments
            sources = await db.fetch_all(
                """
                SELECT DISTINCT f.relevance_reason, f.heading_context
                FROM fragments f
                JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
                WHERE e.target_id = ? AND e.target_type = 'claim'
                """,
                (row["id"],),
            )

            # Parse relevance_reason to extract metadata
            parsed_sources = []
            for s in sources:
                reason = s.get("relevance_reason", "") or ""
                url = ""
                is_primary = False
                if "url=" in reason:
                    url = reason.split("url=")[1].split(";")[0].strip()
                if "primary_source=True" in reason:
                    is_primary = True

                # Derive domain + domain category (single-user refactor: domain_category only)
                domain = ""
                domain_category = None
                try:
                    from urllib.parse import urlparse

                    from src.utils.domain_policy import get_domain_category

                    parsed = urlparse(url or source_url)
                    domain = (parsed.netloc or "").lower()
                    domain_category = get_domain_category(domain).value if domain else None
                except Exception:
                    domain = ""
                    domain_category = None

                parsed_sources.append(
                    {
                        "url": url or source_url,
                        "title": s.get("heading_context", ""),
                        "domain": domain,
                        "domain_category": domain_category,
                        "is_primary": is_primary,
                    }
                )

            # If no sources from edges, use source_url from verification_notes
            if not parsed_sources and source_url:
                domain = ""
                domain_category = None
                try:
                    from urllib.parse import urlparse

                    from src.utils.domain_policy import get_domain_category

                    parsed = urlparse(source_url)
                    domain = (parsed.netloc or "").lower()
                    domain_category = get_domain_category(domain).value if domain else None
                except Exception:
                    domain = ""
                    domain_category = None

                parsed_sources = [
                    {
                        "url": source_url,
                        "title": "",
                        "domain": domain,
                        "domain_category": domain_category,
                        "is_primary": False,
                    }
                ]

            # Calculate Bayesian confidence metrics ( + 4b)
            confidence_info = graph.calculate_claim_confidence(row["id"])

            claims.append(
                {
                    "id": row["id"],
                    "text": row.get("claim_text", ""),
                    # Bayesian posterior (primary truth metric) - no fallback to LLM (different semantics)
                    "bayesian_claim_confidence": confidence_info.get(
                        "bayesian_claim_confidence", 0.5
                    ),
                    # LLM's self-reported extraction quality (not truth confidence)
                    "llm_claim_confidence": row.get("llm_claim_confidence", 0.5),
                    "uncertainty": confidence_info.get("uncertainty", 0.0),
                    "controversy": confidence_info.get("controversy", 0.0),
                    "evidence_count": row.get("evidence_count", 0),
                    "has_refutation": bool(row.get("has_refutation", 0)),
                    "sources": parsed_sources,
                    # Evidence details with time metadata (nli_edge_confidence in each item)
                    "evidence": confidence_info.get("evidence", []),
                    "evidence_years": confidence_info.get("evidence_years", {}),
                    # Adoption status for high-reasoning AI to filter
                    "claim_adoption_status": row.get("claim_adoption_status", "adopted"),
                    "claim_rejection_reason": row.get("claim_rejection_reason"),
                }
            )

    except Exception as e:
        logger.debug("Failed to collect claims", task_id=task_id, error=str(e))

    return claims


async def _collect_fragments(db: Any, task_id: str) -> list[dict[str, Any]]:
    """Collect fragments for a task.

    DB schema notes:
    - fragments table has text_content not text
    - fragments table has no task_id, need to join via claims
    - Source URL and is_primary stored in relevance_reason field
    """
    fragments = []

    try:
        # Get fragments linked to this task's claims via edges
        rows = await db.fetch_all(
            """
            SELECT DISTINCT f.id, f.text_content, f.heading_context, f.relevance_reason
            FROM fragments f
            JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
            JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
            WHERE c.task_id = ?
            ORDER BY f.created_at DESC
            LIMIT 100
            """,
            (task_id,),
        )

        for row in rows:
            # Parse relevance_reason to extract metadata
            reason = row.get("relevance_reason", "") or ""
            source_url = ""
            is_primary = False
            if "url=" in reason:
                source_url = reason.split("url=")[1].split(";")[0].strip()
            if "primary_source=True" in reason:
                is_primary = True

            fragments.append(
                {
                    "id": row["id"],
                    "text": (row.get("text_content", "") or "")[:500],  # Limit text length
                    "source_url": source_url,
                    "context": row.get("heading_context", ""),
                    "is_primary": is_primary,
                }
            )

    except Exception as e:
        logger.debug("Failed to collect fragments", task_id=task_id, error=str(e))

    return fragments


async def _build_evidence_graph(db: Any, task_id: str) -> dict[str, Any]:
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
                nodes.append(
                    {
                        "id": row["id"],
                        "type": "claim",
                        "label": row.get("label", "")[:50],
                    }
                )

            # Fragments don't have task_id, get via edges linked to claims
            fragment_rows = await db.fetch_all(
                """
                SELECT DISTINCT f.id, 'fragment' as type, f.heading_context as label
                FROM fragments f
                JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
                JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
                WHERE c.task_id = ?
                LIMIT 50
                """,
                (task_id,),
            )
            for row in fragment_rows:
                nodes.append(
                    {
                        "id": row["id"],
                        "type": "fragment",
                        "label": (row.get("label", "") or "")[:50],
                    }
                )

            # Get edges linked to this task's claims
            edge_rows = await db.fetch_all(
                """
                SELECT e.id, e.source_type, e.source_id, e.target_type, e.target_id,
                       e.relation, e.nli_edge_confidence
                FROM edges e
                WHERE e.target_id IN (SELECT id FROM claims WHERE task_id = ?)
                   OR e.source_id IN (SELECT id FROM claims WHERE task_id = ?)
                LIMIT 100
                """,
                (task_id, task_id),
            )
            for row in edge_rows:
                edges.append(
                    {
                        "source": row["source_id"],
                        "target": row["target_id"],
                        "relation": row.get("relation", "supports"),
                        "nli_edge_confidence": row.get("nli_edge_confidence", 0.5),
                    }
                )

        except Exception as e2:
            logger.debug("Fallback graph build failed", error=str(e2))

    return {"nodes": nodes, "edges": edges}


async def _collect_citation_network(db: Any, task_id: str) -> dict[str, Any]:
    """Collect citation network reachable from task's claims.

    Returns:
        Dict with source_pages, citations, and hub_pages.
    """
    # Get source pages linked to task's claims via fragments
    # Use json_valid to handle malformed paper_metadata gracefully
    source_pages = await db.fetch_all(
        """
        SELECT DISTINCT p.id, p.title, p.url, p.domain,
               CASE
                 WHEN p.paper_metadata IS NOT NULL AND json_valid(p.paper_metadata)
                 THEN json_extract(p.paper_metadata, '$.citation_count')
                 ELSE NULL
               END as citation_count,
               CASE
                 WHEN p.paper_metadata IS NOT NULL AND json_valid(p.paper_metadata)
                 THEN json_extract(p.paper_metadata, '$.year')
                 ELSE NULL
               END as year
        FROM pages p
        JOIN fragments f ON f.page_id = p.id
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id = ?
        """,
        (task_id,),
    )

    page_ids = [p["id"] for p in source_pages]

    # Get citation edges from source pages (chunked for scale)
    citations: list[dict[str, Any]] = []
    for chunk in chunked(page_ids):
        placeholders = ",".join(["?"] * len(chunk))
        citation_rows = await db.fetch_all(
            f"""
            SELECT
                e.id as edge_id,
                e.source_id as citing_page_id,
                e.target_id as cited_page_id,
                e.citation_source,
                p.title as cited_title
            FROM edges e
            JOIN pages p ON e.target_id = p.id
            WHERE e.relation = 'cites'
              AND e.source_type = 'page' AND e.target_type = 'page'
              AND e.source_id IN ({placeholders})
            """,
            tuple(chunk),
        )
        citations.extend(dict(row) for row in citation_rows)

    # Calculate hub pages (most cited within task scope, chunked for scale)
    # Aggregate counts across chunks, then take top 10
    hub_counts: dict[str, dict[str, Any]] = {}
    for chunk in chunked(page_ids):
        placeholders = ",".join(["?"] * len(chunk))
        hub_rows = await db.fetch_all(
            f"""
            SELECT
                e.target_id as page_id,
                p.title,
                COUNT(*) as cited_by_count
            FROM edges e
            JOIN pages p ON e.target_id = p.id
            WHERE e.relation = 'cites'
              AND e.source_type = 'page' AND e.target_type = 'page'
              AND e.source_id IN ({placeholders})
            GROUP BY e.target_id
            """,
            tuple(chunk),
        )
        for row in hub_rows:
            page_id = row["page_id"]
            if page_id in hub_counts:
                hub_counts[page_id]["cited_by_count"] += row["cited_by_count"]
            else:
                hub_counts[page_id] = {
                    "page_id": page_id,
                    "title": row["title"],
                    "cited_by_count": row["cited_by_count"],
                }

    # Sort by cited_by_count and take top 10
    hub_pages = sorted(hub_counts.values(), key=lambda x: x["cited_by_count"], reverse=True)[:10]

    return {
        "source_pages": [dict(p) for p in source_pages],
        "citations": citations,
        "hub_pages": hub_pages,
    }
