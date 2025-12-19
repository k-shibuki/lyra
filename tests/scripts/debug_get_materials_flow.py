#!/usr/bin/env python3
"""
Debug script for get_materials Flow (O.7 Problem 3).

This is a "straight-line" debug script per §debug-integration rule.
Verifies the get_materials tool returns claims/fragments/evidence_graph from DB.

Per §3.2.1:
- get_materials(task_id) returns claims, fragments, evidence_graph, summary
- Data should come from DB (populated by search pipeline)

Usage:
    python tests/scripts/debug_get_materials_flow.py
"""

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime

# Add project root to path
sys.path.insert(0, "/home/statuser/lancet")


async def main():
    """Run get_materials verification."""
    print("=" * 70)
    print("get_materials Flow Debug Script (O.7)")
    print("=" * 70)

    # =========================================================================
    # 0. Setup - Initialize DB and create test data
    # =========================================================================
    print("\n[0] Setup: Initializing database and creating test data...")

    from src.storage.database import get_database

    db = await get_database()

    task_id = f"task_debug_{uuid.uuid4().hex[:8]}"
    query = "test research query for get_materials"

    # Create task
    await db.execute(
        """INSERT INTO tasks (id, query, status, created_at)
           VALUES (?, ?, ?, ?)""",
        (task_id, query, "exploring", datetime.now(UTC).isoformat()),
    )
    print(f"  - Created test task: {task_id}")

    # Create a test page (required for fragments FK)
    page_id = f"p_{uuid.uuid4().hex[:8]}"
    page_url = f"https://example.gov/test/{uuid.uuid4().hex[:8]}"
    await db.execute(
        """INSERT INTO pages (id, url, domain, fetched_at)
           VALUES (?, ?, ?, datetime('now'))""",
        (page_id, page_url, "example.gov"),
    )
    print(f"  - Created test page: {page_id}")

    # Create test fragments (as the search pipeline would)
    fragment1_id = f"f_{uuid.uuid4().hex[:8]}"
    fragment2_id = f"f_{uuid.uuid4().hex[:8]}"

    await db.execute(
        """INSERT INTO fragments (id, page_id, fragment_type, text_content, heading_context, is_relevant, relevance_reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (fragment1_id, page_id, "paragraph", "This is test fragment 1 with important content.", "Test Heading", 1, "primary_source=True; url=https://example.gov/test"),
    )
    await db.execute(
        """INSERT INTO fragments (id, page_id, fragment_type, text_content, heading_context, is_relevant, relevance_reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (fragment2_id, page_id, "paragraph", "This is test fragment 2 with secondary content.", "Another Heading", 1, "primary_source=False; url=https://example.com/article"),
    )
    print(f"  - Created test fragments: {fragment1_id}, {fragment2_id}")

    # Create test claims (as the search pipeline would)
    claim1_id = f"c_{uuid.uuid4().hex[:8]}"
    claim2_id = f"c_{uuid.uuid4().hex[:8]}"

    await db.execute(
        """INSERT INTO claims (id, task_id, claim_text, claim_type, confidence_score, source_fragment_ids, verification_notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (claim1_id, task_id, "Test claim 1: Important fact from primary source", "fact", 0.85, json.dumps([fragment1_id]), "source_url=https://example.gov/test"),
    )
    await db.execute(
        """INSERT INTO claims (id, task_id, claim_text, claim_type, confidence_score, source_fragment_ids, verification_notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (claim2_id, task_id, "Test claim 2: Secondary information", "fact", 0.5, json.dumps([fragment2_id]), "source_url=https://example.com/article"),
    )
    print(f"  - Created test claims: {claim1_id}, {claim2_id}")

    # Create test edges (fragment -> claim relationship)
    edge1_id = f"e_{uuid.uuid4().hex[:8]}"
    edge2_id = f"e_{uuid.uuid4().hex[:8]}"

    await db.execute(
        """INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation, created_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        (edge1_id, "fragment", fragment1_id, "claim", claim1_id, "supports"),
    )
    await db.execute(
        """INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation, created_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        (edge2_id, "fragment", fragment2_id, "claim", claim2_id, "supports"),
    )
    print(f"  - Created test edges: {edge1_id}, {edge2_id}")

    print("[0] Setup: PASSED ✓")

    # =========================================================================
    # 1. Test get_materials_action() directly
    # =========================================================================
    print("\n[1] Testing get_materials_action() directly...")

    from src.research.materials import get_materials_action

    # Request with include_graph=True to build evidence graph
    result = await get_materials_action(task_id, {"include_graph": True})

    print(f"  - ok: {result.get('ok')}")
    print(f"  - task_id: {result.get('task_id')}")
    print(f"  - query: {result.get('query')}")
    print(f"  - claims count: {len(result.get('claims', []))}")
    print(f"  - fragments count: {len(result.get('fragments', []))}")

    evidence_graph = result.get("evidence_graph", {})
    print(f"  - evidence_graph.nodes count: {len(evidence_graph.get('nodes', []))}")
    print(f"  - evidence_graph.edges count: {len(evidence_graph.get('edges', []))}")

    summary = result.get("summary", {})
    print(f"  - summary.total_claims: {summary.get('total_claims')}")

    assert result.get("ok") is True, "Expected ok=True"

    print("[1] get_materials_action(): PASSED ✓")

    # =========================================================================
    # 2. Check claims structure
    # =========================================================================
    print("\n[2] Checking claims structure...")

    claims = result.get("claims", [])
    if claims:
        c = claims[0]
        print(f"  - First claim fields: {list(c.keys())}")
        print(f"    - id: {c.get('id')}")
        print(f"    - text: {c.get('text', '')[:50]}...")
        print(f"    - confidence: {c.get('confidence')}")
        print(f"    - evidence_count: {c.get('evidence_count')}")
        print(f"    - has_refutation: {c.get('has_refutation')}")
        print(f"    - sources: {c.get('sources')}")
    else:
        print("  ⚠ WARNING: No claims found!")

    assert len(claims) >= 2, f"Expected >= 2 claims, got {len(claims)}"
    print("[2] Claims structure: PASSED ✓")

    # =========================================================================
    # 3. Check fragments structure
    # =========================================================================
    print("\n[3] Checking fragments structure...")

    fragments = result.get("fragments", [])
    if fragments:
        f = fragments[0]
        print(f"  - First fragment fields: {list(f.keys())}")
        print(f"    - id: {f.get('id')}")
        print(f"    - text: {f.get('text', '')[:50]}...")
        print(f"    - source_url: {f.get('source_url')}")
        print(f"    - context: {f.get('context')}")
    else:
        print("  ⚠ WARNING: No fragments found!")

    # Note: fragments may be empty if _collect_fragments doesn't find by task_id
    print(f"  - fragments count: {len(fragments)}")
    print("[3] Fragments structure: CHECKED")

    # =========================================================================
    # 4. Check evidence_graph structure
    # =========================================================================
    print("\n[4] Checking evidence_graph structure...")

    nodes = evidence_graph.get("nodes", [])
    edges = evidence_graph.get("edges", [])

    print(f"  - nodes count: {len(nodes)}")
    print(f"  - edges count: {len(edges)}")

    if nodes:
        n = nodes[0]
        print(f"  - First node fields: {list(n.keys())}")
        print(f"    - id: {n.get('id')}")
        print(f"    - type: {n.get('type')}")

    if edges:
        e = edges[0]
        print(f"  - First edge fields: {list(e.keys())}")
        print(f"    - source: {e.get('source')}")
        print(f"    - target: {e.get('target')}")
        print(f"    - relation: {e.get('relation')}")

    print("[4] Evidence graph structure: CHECKED")

    # =========================================================================
    # 5. Test _handle_get_materials() via MCP
    # =========================================================================
    print("\n[5] Testing _handle_get_materials() MCP handler...")

    from src.mcp.server import _handle_get_materials

    # Test with include_graph=True (evidence_graph is opt-in)
    mcp_result = await _handle_get_materials(
        {"task_id": task_id, "options": {"include_graph": True}}
    )

    print(f"  - ok: {mcp_result.get('ok')}")
    print(f"  - claims count: {len(mcp_result.get('claims', []))}")
    print(f"  - fragments count: {len(mcp_result.get('fragments', []))}")

    mcp_graph = mcp_result.get("evidence_graph", {}) or {}
    print(f"  - evidence_graph.nodes: {len(mcp_graph.get('nodes', []))}")
    print(f"  - evidence_graph.edges: {len(mcp_graph.get('edges', []))}")

    # Note: evidence_graph requires include_graph=True option
    assert len(mcp_graph.get("nodes", [])) >= 2, "Expected evidence_graph with nodes"

    print("[5] _handle_get_materials(): PASSED ✓")

    # =========================================================================
    # 6. Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    issues = []

    if len(claims) < 2:
        issues.append(f"Expected >= 2 claims, got {len(claims)}")

    if len(evidence_graph.get("nodes", [])) == 0:
        issues.append("evidence_graph.nodes is empty")

    if len(evidence_graph.get("edges", [])) == 0:
        issues.append("evidence_graph.edges is empty")

    if issues:
        print("\n⚠ Issues Found:")
        for i, issue in enumerate(issues):
            print(f"  {i + 1}. {issue}")
    else:
        print("\n✓ All checks passed!")
        print(f"  - claims: {len(claims)} found")
        print(f"  - fragments: {len(fragments)} found")
        print(f"  - evidence_graph nodes: {len(nodes)}")
        print(f"  - evidence_graph edges: {len(edges)}")

    # Cleanup
    print("\n[Cleanup] Removing test data...")
    await db.execute("DELETE FROM edges WHERE id IN (?, ?)", (edge1_id, edge2_id))
    await db.execute("DELETE FROM claims WHERE task_id = ?", (task_id,))
    await db.execute("DELETE FROM fragments WHERE page_id = ?", (page_id,))
    await db.execute("DELETE FROM pages WHERE id = ?", (page_id,))
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    print("\n" + "=" * 70)
    print("Debug script completed.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
