"""
Debug script: E2E verification for 2026-01-02 changes.

Validates the following changes work end-to-end:
1. query_sql (renamed from query_graph)
2. query_view + list_views (new tools)
3. vector_search with zero embeddings → ok=false
4. stop_task mode=full

Run:
  ./.venv/bin/python tests/scripts/debug_e2e_changes_flow.py

This script uses an isolated DB so it will NOT touch data/lyra.db.
"""

from __future__ import annotations

import asyncio
import json
import struct
import uuid
from unittest.mock import AsyncMock, patch


async def _main() -> None:
    print("=" * 60)
    print("E2E Flow Verification: 2026-01-02 Changes")
    print("=" * 60)

    from src.mcp.server import TOOLS, call_tool
    from src.storage.database import get_database
    from src.storage.isolation import isolated_database_path

    # Verify tools exist
    tool_names = [t.name for t in TOOLS]
    print("\n[1] Verifying tool registration...")
    assert "query_sql" in tool_names, f"query_sql missing from TOOLS: {tool_names}"
    assert "query_view" in tool_names, f"query_view missing from TOOLS: {tool_names}"
    assert "list_views" in tool_names, f"list_views missing from TOOLS: {tool_names}"
    assert "vector_search" in tool_names, f"vector_search missing from TOOLS: {tool_names}"
    assert "stop_task" in tool_names, f"stop_task missing from TOOLS: {tool_names}"
    assert "query_graph" not in tool_names, "query_graph should NOT be in TOOLS"
    print("   ✓ All expected tools registered")
    print("   ✓ query_graph correctly removed")

    # Verify stop_task has mode=full
    stop_task_tool = next(t for t in TOOLS if t.name == "stop_task")
    mode_enum = stop_task_tool.inputSchema["properties"]["mode"]["enum"]
    assert "full" in mode_enum, f"mode=full missing from stop_task: {mode_enum}"
    print("   ✓ stop_task has mode=full")

    async with isolated_database_path(filename="lyra_debug_e2e_changes.db"):
        db = await get_database()
        task_id = f"task_e2e_{uuid.uuid4().hex[:8]}"
        page_id = f"p_e2e_{uuid.uuid4().hex[:8]}"
        frag_id = f"f_e2e_{uuid.uuid4().hex[:8]}"
        claim_id = f"c_e2e_{uuid.uuid4().hex[:8]}"

        # Setup test data
        print("\n[2] Setting up test data in isolated DB...")
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            (task_id, "E2E test query", "exploring"),
        )
        await db.execute(
            "INSERT INTO pages (id, url, domain, paper_metadata) VALUES (?, ?, ?, ?)",
            (page_id, "https://example.org/paper", "example.org", json.dumps({"year": 2024})),
        )
        await db.execute(
            "INSERT INTO fragments (id, page_id, fragment_type, text_content, heading_context, is_relevant) VALUES (?, ?, ?, ?, ?, ?)",
            (frag_id, page_id, "paragraph", "Metformin reduces HbA1c levels.", "Results", 1),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
            (claim_id, task_id, "Metformin reduces HbA1c levels effectively.", 0.85),
        )
        print(f"   ✓ Created task: {task_id}")
        print("   ✓ Created page, fragment, claim")

        # ------------------------------------------------------------
        # Test 1: query_sql (renamed from query_graph)
        # ------------------------------------------------------------
        print("\n[3] Testing query_sql tool...")
        q1 = await call_tool(
            "query_sql",
            {
                "sql": f"SELECT id, claim_text FROM claims WHERE task_id = '{task_id}'",
                "options": {"limit": 10},
            },
        )
        assert q1["ok"] is True, f"query_sql failed: {q1}"
        assert q1["row_count"] == 1, f"Expected 1 row, got {q1['row_count']}"
        assert q1["rows"][0]["id"] == claim_id
        print(f"   ✓ query_sql returned {q1['row_count']} row(s)")

        # Test include_schema option
        q2 = await call_tool(
            "query_sql",
            {"sql": "SELECT 1", "options": {"include_schema": True}},
        )
        assert q2["ok"] is True
        assert "schema" in q2 and q2["schema"]
        table_names = {t["name"] for t in q2["schema"]["tables"]}
        assert "claims" in table_names
        assert "embeddings" in table_names
        print("   ✓ query_sql include_schema works")

        # Test security guard
        q3 = await call_tool("query_sql", {"sql": "PRAGMA table_info(claims)"})
        assert q3["ok"] is False and q3.get("error")
        print("   ✓ query_sql security guard blocks PRAGMA")

        # ------------------------------------------------------------
        # Test 2: list_views
        # ------------------------------------------------------------
        print("\n[4] Testing list_views tool...")
        lv = await call_tool("list_views", {})
        assert lv["ok"] is True
        assert lv["count"] > 0
        view_names = [v["name"] for v in lv["views"]]
        expected_views = [
            "v_claim_evidence_summary",
            "v_contradictions",
            "v_unsupported_claims",
        ]
        for ev in expected_views:
            assert ev in view_names, f"Missing view: {ev}"
        print(f"   ✓ list_views returned {lv['count']} views")

        # ------------------------------------------------------------
        # Test 3: query_view
        # ------------------------------------------------------------
        print("\n[5] Testing query_view tool...")
        qv = await call_tool(
            "query_view",
            {"view_name": "v_claim_evidence_summary", "task_id": task_id, "limit": 10},
        )
        assert qv["ok"] is True, f"query_view failed: {qv}"
        assert qv["view_name"] == "v_claim_evidence_summary"
        print(f"   ✓ query_view returned {qv['row_count']} row(s)")

        # Test non-existent view
        qv_bad = await call_tool(
            "query_view",
            {"view_name": "v_nonexistent", "task_id": task_id},
        )
        assert qv_bad["ok"] is False
        assert "not found" in qv_bad.get("error", "").lower()
        print("   ✓ query_view correctly handles non-existent view")

        # ------------------------------------------------------------
        # Test 4: vector_search with zero embeddings → ok=false
        # ------------------------------------------------------------
        print("\n[6] Testing vector_search with zero embeddings...")
        with patch("src.storage.vector_store.get_ml_client") as mock_get_ml:
            mock_client = AsyncMock()
            mock_client.embed.return_value = [[0.5, 0.5, 0.5]]
            mock_get_ml.return_value = mock_client

            # No embeddings in DB → should return ok=false
            vs = await call_tool(
                "vector_search",
                {"query": "HbA1c levels", "target": "claims", "task_id": task_id},
            )
            assert vs["ok"] is False, f"Expected ok=false for zero embeddings: {vs}"
            assert "no embeddings found" in vs.get("error", "").lower()
            assert vs["total_searched"] == 0
            print("   ✓ vector_search returns ok=false for zero embeddings")

        # Now add embeddings and verify search works
        print("\n[7] Testing vector_search with embeddings...")
        dummy_embedding = struct.pack("<3f", 0.5, 0.5, 0.5)
        await db.execute(
            "INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension) VALUES (?, ?, ?, ?, ?, ?)",
            (f"claim:{claim_id}:test", "claim", claim_id, "BAAI/bge-m3", dummy_embedding, 3),
        )

        with patch("src.storage.vector_store.get_ml_client") as mock_get_ml:
            mock_client = AsyncMock()
            mock_client.embed.return_value = [[0.5, 0.5, 0.5]]
            mock_get_ml.return_value = mock_client

            vs2 = await call_tool(
                "vector_search",
                {"query": "HbA1c levels", "target": "claims", "task_id": task_id},
            )
            assert vs2["ok"] is True, f"Expected ok=true with embeddings: {vs2}"
            assert vs2["total_searched"] == 1
            assert len(vs2["results"]) == 1
            assert vs2["results"][0]["id"] == claim_id
            print(f"   ✓ vector_search found {len(vs2['results'])} result(s)")

        # ------------------------------------------------------------
        # Test 5: stop_task mode=full
        # ------------------------------------------------------------
        print("\n[8] Testing stop_task mode=full...")

        # Add some jobs
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        for i, state in enumerate(["queued", "running"]):
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"job_e2e_{i}",
                    task_id,
                    "search_queue",
                    50,
                    "network_client",
                    state,
                    json.dumps({"query": f"query {i}"}),
                    now,
                ),
            )

        st = await call_tool(
            "stop_task",
            {"task_id": task_id, "mode": "full", "reason": "completed"},
        )
        assert st["ok"] is True, f"stop_task failed: {st}"
        assert st["mode"] == "full"
        print("   ✓ stop_task mode=full completed")

        # Verify jobs are cancelled
        rows = await db.fetch_all(
            "SELECT state FROM jobs WHERE task_id = ? AND kind = 'search_queue'",
            (task_id,),
        )
        for row in rows:
            assert row["state"] == "cancelled", f"Job not cancelled: {row}"
        print(f"   ✓ All {len(rows)} jobs cancelled")

        # Verify task status updated
        task_row = await db.fetch_one(
            "SELECT status FROM tasks WHERE id = ?",
            (task_id,),
        )
        assert task_row["status"] == "completed", f"Task status not updated: {task_row}"
        print("   ✓ Task status updated to 'completed'")

    print("\n" + "=" * 60)
    print("✓ All E2E flow verifications passed!")
    print("=" * 60)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
