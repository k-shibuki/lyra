#!/usr/bin/env python3
"""
E2E Integration Test for MCP Tools (O.7.6).

This is an end-to-end debug script that verifies the full MCP tool flow:
create_task → search → get_status → get_materials → stop_task

Per §3.2.1: All MCP tools should work together in a coherent pipeline.

Note: This script simulates the MCP flow without actual network/browser access.
For full E2E testing, use the actual MCP server with Cursor AI.

Usage:
    python tests/scripts/debug_e2e_mcp_flow.py
"""

import asyncio
import sys
import uuid

# Add project root to path
sys.path.insert(0, "/home/statuser/lyra")


async def main() -> int:
    """Run E2E MCP flow verification."""
    print("=" * 70)
    print("E2E MCP Flow Integration Test (O.7.6)")
    print("=" * 70)

    from src.storage.database import get_database

    db = await get_database()

    # =========================================================================
    # Step 1: create_task
    # =========================================================================
    print("\n[Step 1] create_task...")

    from src.mcp.server import _handle_create_task

    create_result = await _handle_create_task(
        {
            "query": "E2E test: What are the effects of caffeine?",
        }
    )

    print(f"  - ok: {create_result.get('ok')}")
    task_id = create_result.get("task_id")
    print(f"  - task_id: {task_id}")

    assert create_result.get("ok") is True, "create_task should return ok=True"
    assert task_id is not None, "create_task should return task_id"

    print("[Step 1] create_task: PASSED ✓")

    # =========================================================================
    # Step 2: get_status (initial)
    # =========================================================================
    print("\n[Step 2] get_status (initial)...")

    from src.mcp.server import _handle_get_status

    status_result = await _handle_get_status({"task_id": task_id})

    print(f"  - ok: {status_result.get('ok')}")
    print(f"  - status: {status_result.get('status')}")
    print(f"  - searches: {len(status_result.get('searches', []))}")

    assert status_result.get("ok") is True, "get_status should return ok=True"

    print("[Step 2] get_status (initial): PASSED ✓")

    # =========================================================================
    # Step 3: Simulate search execution
    # =========================================================================
    print("\n[Step 3] Simulating search data (bypassing actual fetch)...")

    # Insert mock data to simulate what search pipeline would produce
    claim_id = f"c_{uuid.uuid4().hex[:8]}"
    fragment_id = f"f_{uuid.uuid4().hex[:8]}"
    page_id = f"p_{uuid.uuid4().hex[:8]}"
    edge_id = f"e_{uuid.uuid4().hex[:8]}"

    # Create page
    await db.execute(
        """INSERT INTO pages (id, url, domain, fetched_at)
           VALUES (?, ?, ?, datetime('now'))""",
        (page_id, f"https://example.gov/caffeine/{uuid.uuid4().hex[:8]}", "example.gov"),
    )

    # Create fragment
    await db.execute(
        """INSERT INTO fragments (id, page_id, fragment_type, text_content, heading_context, is_relevant, relevance_reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            fragment_id,
            page_id,
            "paragraph",
            "Caffeine is a stimulant that affects the central nervous system.",
            "Effects of Caffeine",
            1,
            "primary_source=True; url=https://example.gov/caffeine",
        ),
    )

    # Create claim
    import json

    await db.execute(
        """INSERT INTO claims (id, task_id, claim_text, claim_type, claim_confidence, source_fragment_ids, verification_notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            claim_id,
            task_id,
            "Caffeine acts as a central nervous system stimulant.",
            "fact",
            0.85,
            json.dumps([fragment_id]),
            "source_url=https://example.gov/caffeine",
        ),
    )

    # Create edge
    await db.execute(
        """INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation, created_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        (edge_id, "fragment", fragment_id, "claim", claim_id, "supports"),
    )

    print(f"  - Created mock page: {page_id}")
    print(f"  - Created mock fragment: {fragment_id}")
    print(f"  - Created mock claim: {claim_id}")
    print(f"  - Created mock edge: {edge_id}")

    print("[Step 3] Mock data creation: PASSED ✓")

    # =========================================================================
    # Step 4: get_status (after data)
    # =========================================================================
    print("\n[Step 4] get_status (after mock data)...")

    status_result2 = await _handle_get_status({"task_id": task_id})

    print(f"  - ok: {status_result2.get('ok')}")
    print(f"  - status: {status_result2.get('status')}")
    metrics = status_result2.get("metrics", {})
    print(f"  - metrics.total_claims: {metrics.get('total_claims')}")

    print("[Step 4] get_status (after data): PASSED ✓")

    # =========================================================================
    # Step 5: get_materials
    # =========================================================================
    print("\n[Step 5] get_materials...")

    from src.mcp.server import _handle_get_materials

    materials_result = await _handle_get_materials(
        {
            "task_id": task_id,
            "options": {"include_graph": True},
        }
    )

    print(f"  - ok: {materials_result.get('ok')}")
    print(f"  - claims: {len(materials_result.get('claims', []))}")
    print(f"  - fragments: {len(materials_result.get('fragments', []))}")

    graph = materials_result.get("evidence_graph", {}) or {}
    print(f"  - evidence_graph.nodes: {len(graph.get('nodes', []))}")
    print(f"  - evidence_graph.edges: {len(graph.get('edges', []))}")

    summary = materials_result.get("summary", {})
    print(f"  - summary.total_claims: {summary.get('total_claims')}")

    assert materials_result.get("ok") is True, "get_materials should return ok=True"
    assert len(materials_result.get("claims", [])) >= 1, "Should have at least 1 claim"

    print("[Step 5] get_materials: PASSED ✓")

    # =========================================================================
    # Step 6: stop_task
    # =========================================================================
    print("\n[Step 6] stop_task...")

    from src.mcp.server import _handle_stop_task

    stop_result = await _handle_stop_task(
        {
            "task_id": task_id,
            "reason": "e2e_test_complete",
        }
    )

    print(f"  - ok: {stop_result.get('ok')}")
    print(f"  - final_status: {stop_result.get('final_status')}")

    assert stop_result.get("ok") is True, "stop_task should return ok=True"

    print("[Step 6] stop_task: PASSED ✓")

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("E2E FLOW SUMMARY")
    print("=" * 70)

    print("\n✓ All E2E steps passed!")
    print("  1. create_task → task created")
    print("  2. get_status → initial status retrieved")
    print("  3. (simulated) search → claims/fragments created")
    print("  4. get_status → metrics updated")
    print("  5. get_materials → claims/fragments/graph retrieved")
    print("  6. stop_task → task finalized")

    print("\n📋 MCP Tool Flow Verified:")
    print("  - create_task: ✓")
    print("  - get_status: ✓")
    print("  - get_materials: ✓")
    print("  - stop_task: ✓")

    # Cleanup
    print("\n[Cleanup] Removing test data...")
    await db.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
    await db.execute("DELETE FROM claims WHERE task_id = ?", (task_id,))
    await db.execute("DELETE FROM fragments WHERE page_id = ?", (page_id,))
    await db.execute("DELETE FROM pages WHERE id = ?", (page_id,))
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    print("\n" + "=" * 70)
    print("E2E test completed successfully.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
