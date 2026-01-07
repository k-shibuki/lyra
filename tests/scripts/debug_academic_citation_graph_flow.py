"""
Debug script: academic_citation_graph_flow

Validates the end-to-end integration contract:
- Academic ingestion persists pages.paper_metadata.paper_id (= Paper.id)
- citation_graph job can map paper_id -> page_id via JSON extraction

This script uses an isolated DB and does NOT touch data/lyra.db.

Run:
  ./.venv/bin/python tests/scripts/debug_academic_citation_graph_flow.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock, patch

from src.storage.database import get_database
from src.storage.isolation import isolated_database_path
from src.utils.schemas import Author, Paper


async def main() -> None:
    # Given: isolated DB
    async with isolated_database_path(filename="debug_academic_citation_graph_flow.db"):
        db = await get_database()

        # Given: a task exists
        task_id = "task_debug_paper_id"
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Debug paper_id contract", "exploring"),
        )

        # When: persist academic paper via pipeline helper
        #
        # This debug flow focuses on the *paper_id persistence + lookup contract*.
        # We intentionally stub out LLM/ML calls to avoid external dependencies and
        # to prevent unclosed aiohttp sessions in standalone runs.
        from src.research.pipeline import ExplorationState, SearchPipeline

        state = ExplorationState(task_id=task_id)
        pipeline = SearchPipeline(task_id=task_id, state=state)

        paper = Paper(
            id="s2:debugpaperid123",
            title="Debug Paper Title",
            abstract="This is a debug abstract.",
            authors=[Author(name="Alice", affiliation=None, orcid=None)],
            year=2020,
            published_date=date(2020, 1, 1),
            doi="10.0000/debug.doi",
            arxiv_id=None,
            venue="Debug Journal",
            citation_count=1,
            reference_count=1,
            is_open_access=True,
            oa_url="https://doi.org/10.0000/debug.doi",
            pdf_url="https://doi.org/10.0000/debug.doi",
            source_api="semantic_scholar",
        )

        class _DummyMLClient:
            async def embed(self, texts: list[str]) -> list[list[float]]:
                return [[0.0] * 1024 for _ in texts]

        with patch.object(
            SearchPipeline,
            "_extract_claims_from_abstract",
            new=AsyncMock(return_value=[]),
        ):
            with patch("src.ml_client.get_ml_client", return_value=_DummyMLClient()):
                with patch(
                    "src.storage.vector_store.persist_embedding",
                    new=AsyncMock(return_value=None),
                ):
                    page_id, _fragment_id = await pipeline._persist_abstract_as_fragment(
                        paper=paper,
                        task_id=task_id,
                        search_id="s_debug",
                        worker_id=0,
                    )
        assert page_id is not None

        # Then: paper_id is persisted in paper_metadata
        row = await db.fetch_one("SELECT paper_metadata FROM pages WHERE id = ?", (page_id,))
        assert row is not None
        pm = json.loads(row["paper_metadata"])
        assert pm["paper_id"] == paper.id

        # When: citation_graph attempts to map paper_id -> page_id
        mapped = await db.fetch_one(
            """
            SELECT id FROM pages
            WHERE paper_metadata IS NOT NULL
              AND json_valid(paper_metadata)
              AND json_extract(paper_metadata, '$.paper_id') = ?
            LIMIT 1
            """,
            (paper.id,),
        )
        assert mapped is not None
        assert mapped["id"] == page_id

        print("OK: paper_id contract verified", {"paper_id": paper.id, "page_id": page_id})


if __name__ == "__main__":
    asyncio.run(main())
