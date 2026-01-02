"""
Debug script: executor -> DB persistence wiring (fragments/claims/edges/embeddings).

Purpose:
- Validate the "settings + executor persistence + ML client + DB" path works end-to-end
  without touching data/lyra.db.

Run:
  ./.venv/bin/python tests/scripts/debug_executor_embedding_flow.py
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch


async def _main() -> None:
    from src.storage.database import get_database
    from src.storage.isolation import isolated_database_path
    from src.utils.config import get_settings

    settings = get_settings()
    model_id = settings.embedding.model_name

    async with isolated_database_path(filename="lyra_debug_executor_embed.db"):
        db = await get_database()

        task_id = f"task_dbg_{uuid.uuid4().hex[:8]}"
        page_id = f"p_dbg_{uuid.uuid4().hex[:8]}"
        frag_id = f"f_dbg_{uuid.uuid4().hex[:8]}"
        claim_id = f"c_dbg_{uuid.uuid4().hex[:8]}"

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            (task_id, "debug executor embedding", "running"),
        )
        await db.execute(
            "INSERT INTO pages (id, url, domain, paper_metadata) VALUES (?, ?, ?, ?)",
            (
                page_id,
                "https://example.org/paper",
                "example.org",
                json.dumps({"year": 2022}),
            ),
        )

        # Create an executor instance without running its full init.
        from src.research.executor import SearchExecutor

        ex = SearchExecutor.__new__(SearchExecutor)  # type: ignore[call-arg]
        ex.task_id = task_id

        # Patch ML + NLI so this script is deterministic and offline.
        with patch("src.ml_client.get_ml_client") as mock_get_ml:
            mock_client = AsyncMock()
            mock_client.embed.return_value = [[0.9, 0.1, 0.0]]
            mock_client.nli.return_value = [{"pair_id": "p1", "label": "supports", "confidence": 0.9}]
            mock_get_ml.return_value = mock_client

            async def fake_nli_judge(pairs):
                return [
                    {
                        "pair_id": pairs[0]["pair_id"],
                        "stance": "supports",
                        "nli_edge_confidence": 0.9,
                    }
                ]

            with patch("src.filter.nli.nli_judge", side_effect=fake_nli_judge):
                with patch("src.utils.domain_policy.get_domain_category", return_value="trusted"):
                    # 1) persist fragment (should create fragment row + embedding row)
                    await ex._persist_fragment(
                        fragment_id=frag_id,
                        page_id=page_id,
                        text="Metformin reduces cardiovascular events.",
                        source_url="https://example.org/paper",
                        title="Example Paper",
                        heading_context="Results",
                        is_primary=True,
                    )

                    frag_row = await db.fetch_one(
                        "SELECT id FROM fragments WHERE id = ?", (frag_id,)
                    )
                    assert frag_row is not None, "fragment not persisted"

                    frag_emb = await db.fetch_one(
                        "SELECT model_id, dimension FROM embeddings WHERE target_type='fragment' AND target_id=?",
                        (frag_id,),
                    )
                    assert frag_emb is not None, "fragment embedding not persisted"
                    assert frag_emb["model_id"] == model_id

                    # 2) persist claim (should create claim row + embedding row + edge row)
                    await ex._persist_claim(
                        claim_id=claim_id,
                        claim_text="Metformin reduces cardiovascular events.",
                        llm_claim_confidence=0.8,
                        source_url="https://example.org/paper",
                        source_fragment_id=frag_id,
                    )

                    claim_row = await db.fetch_one(
                        "SELECT id, task_id FROM claims WHERE id = ?", (claim_id,)
                    )
                    assert claim_row is not None and claim_row["task_id"] == task_id

                    claim_emb = await db.fetch_one(
                        "SELECT model_id, dimension FROM embeddings WHERE target_type='claim' AND target_id=?",
                        (claim_id,),
                    )
                    assert claim_emb is not None, "claim embedding not persisted"
                    assert claim_emb["model_id"] == model_id

                    edge_row = await db.fetch_one(
                        "SELECT relation, nli_edge_confidence FROM edges WHERE source_id=? AND target_id=?",
                        (frag_id, claim_id),
                    )
                    assert edge_row is not None, "evidence edge not persisted"
                    assert edge_row["relation"] in ("supports", "refutes", "neutral")
                    assert edge_row["nli_edge_confidence"] is not None


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()


