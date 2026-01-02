"""
Debug script: Evidence Graph exploration flow (query_sql + vector_search + views).

Run:
  ./.venv/bin/python tests/scripts/debug_evidence_graph_exploration_flow.py

This script uses an isolated DB so it will NOT touch data/lyra.db.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch


async def _main() -> None:
    from src.mcp.server import TOOLS, call_tool
    from src.storage.database import get_database
    from src.storage.isolation import isolated_database_path
    from src.storage.vector_store import persist_embedding
    from src.storage.view_manager import ViewManager
    from src.utils.config import get_settings

    tool_names = [t.name for t in TOOLS]
    assert "query_sql" in tool_names, f"query_sql missing from TOOLS: {tool_names}"
    assert "vector_search" in tool_names, f"vector_search missing from TOOLS: {tool_names}"

    settings = get_settings()
    model_id = settings.embedding.model_name

    async with isolated_database_path(filename="lyra_debug_evidence_graph.db"):
        db = await get_database()

        task_id = f"task_dbg_{uuid.uuid4().hex[:8]}"
        page_id = f"p_dbg_{uuid.uuid4().hex[:8]}"
        frag_id = f"f_dbg_{uuid.uuid4().hex[:8]}"
        claim_id = f"c_dbg_{uuid.uuid4().hex[:8]}"
        edge_id = f"e_dbg_{uuid.uuid4().hex[:8]}"

        # Minimal task + evidence rows
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            (task_id, "debug evidence graph exploration", "completed"),
        )
        await db.execute(
            "INSERT INTO pages (id, url, domain, paper_metadata) VALUES (?, ?, ?, ?)",
            (
                page_id,
                "https://example.org/paper",
                "example.org",
                json.dumps({"year": 2021}),
            ),
        )
        await db.execute(
            "INSERT INTO fragments (id, page_id, fragment_type, text_content, heading_context, is_relevant) VALUES (?, ?, ?, ?, ?, ?)",
            (
                frag_id,
                page_id,
                "paragraph",
                "Metformin reduces cardiovascular events.",
                "Results",
                1,
            ),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
            (claim_id, task_id, "Metformin reduces cardiovascular events.", 0.8),
        )
        await db.execute(
            "INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation, nli_edge_confidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (edge_id, "fragment", frag_id, "claim", claim_id, "supports", 0.9),
        )

        # Persist embeddings for claim + fragment (3-dim for debug)
        await persist_embedding("fragment", frag_id, [0.9, 0.1, 0.0], model_id=model_id)
        await persist_embedding("claim", claim_id, [0.9, 0.1, 0.0], model_id=model_id)

        # ------------------------------------------------------------
        # query_sql: view query + include_schema wiring
        # ------------------------------------------------------------
        q1 = await call_tool(
            "query_sql",
            {
                "sql": f"SELECT claim_id, support_count, refute_count FROM v_claim_evidence_summary WHERE task_id = '{task_id}'",
                "options": {"limit": 10, "include_schema": True},
            },
        )
        assert q1["ok"] is True, q1
        assert q1["row_count"] >= 1, q1
        assert "schema" in q1 and q1["schema"], q1
        table_names = {t["name"] for t in q1["schema"]["tables"]}
        assert "claims" in table_names, table_names
        assert "embeddings" in table_names, table_names

        # query_sql: security guard (PRAGMA forbidden)
        q2 = await call_tool("query_sql", {"sql": "PRAGMA table_info(claims)"})
        assert q2["ok"] is False and q2.get("error"), q2

        # query_sql: DoS-ish query should be interrupted by timeout/VM steps
        q3 = await call_tool(
            "query_sql",
            {
                "sql": "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM cnt WHERE x < 1000000) SELECT count(*) AS c FROM cnt",
                "options": {"timeout_ms": 100, "max_vm_steps": 20000, "limit": 1},
            },
        )
        assert q3["ok"] is False, q3

        # ------------------------------------------------------------
        # vector_search: task-scoped claims search
        # ------------------------------------------------------------
        with patch("src.storage.vector_store.get_ml_client") as mock_get_ml:
            mock_client = AsyncMock()
            mock_client.embed.return_value = [[0.9, 0.1, 0.0]]
            mock_get_ml.return_value = mock_client

            v1 = await call_tool(
                "vector_search",
                {
                    "query": "cardiovascular events",
                    "target": "claims",
                    "task_id": task_id,
                    "top_k": 5,
                },
            )
            assert v1["ok"] is True, v1
            assert v1["results"], v1
            assert v1["results"][0]["id"] == claim_id, v1

        # ------------------------------------------------------------
        # ViewManager: templates exist + can execute
        # ------------------------------------------------------------
        vm = ViewManager()
        views = vm.list_views()
        expected = {
            "v_claim_evidence_summary",
            "v_contradictions",
            "v_unsupported_claims",
            "v_evidence_chain",
            "v_hub_pages",
            "v_citation_flow",
            "v_citation_clusters",
            "v_orphan_sources",
            "v_evidence_timeline",
            "v_claim_temporal_support",
            "v_emerging_consensus",
            "v_outdated_evidence",
            "v_source_authority",
            "v_controversy_by_era",
            "v_citation_age_gap",
            "v_evidence_freshness",
        }
        missing = expected - set(views)
        assert not missing, f"Missing view templates: {sorted(missing)}"

        rows = await vm.query("v_claim_evidence_summary", task_id=task_id, limit=5)
        assert rows and rows[0]["claim_id"] == claim_id, rows


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
