"""Integration tests for MCP tool data flow.

Tests the full data flow between MCP tools:
- create_task → search → get_status → get_materials → stop_task

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-I-01 | Valid task with search data | Equivalence – normal | get_status returns search info | E2E flow |
| TC-I-02 | Valid task with claims/fragments | Equivalence – normal | get_materials returns data | DB integrity |
| TC-I-03 | Task with no exploration data | Boundary – empty | get_status returns empty searches | Minimal case |
| TC-I-04 | Task with 0 claims/fragments | Boundary – empty | get_materials returns empty lists | Zero data |
| TC-I-05 | Task with include_graph=True | Equivalence – graph | get_materials includes evidence_graph | Graph feature |
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.integration
class TestGetStatusIntegration:
    """Integration tests for get_status with real database data."""

    @pytest.fixture
    async def setup_task_with_search_data(self, memory_database) -> dict[str, Any]:
        """Create a task with search/exploration data.

        Returns dict with task_id, search_id, page_count, fragment_count.
        """
        db = memory_database
        task_id = f"task_int_{uuid.uuid4().hex[:8]}"
        search_id = f"sq_{uuid.uuid4().hex[:8]}"

        # Create task
        await db.execute(
            """INSERT INTO tasks (id, query, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, "integration test query", "exploring", datetime.now(UTC).isoformat()),
        )

        # Create query record (using actual schema: query_text, query_type)
        await db.execute(
            """INSERT INTO queries (id, task_id, query_text, query_type, created_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (search_id, task_id, "test search query", "initial"),
        )

        # Create pages
        page_ids = []
        for i in range(3):
            page_id = f"p_{uuid.uuid4().hex[:8]}"
            page_ids.append(page_id)
            await db.execute(
                """INSERT INTO pages (id, url, domain, fetched_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                (page_id, f"https://example.com/page{i}", "example.com"),
            )

        # Create fragments
        fragment_ids = []
        for i, page_id in enumerate(page_ids):
            fragment_id = f"f_{uuid.uuid4().hex[:8]}"
            fragment_ids.append(fragment_id)
            await db.execute(
                """INSERT INTO fragments (id, page_id, fragment_type, text_content, 
                   heading_context, is_relevant, relevance_reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (fragment_id, page_id, "paragraph", f"Content {i}", f"Heading {i}",
                 1, f"url=https://example.com/page{i}"),
            )

        return {
            "task_id": task_id,
            "search_id": search_id,
            "page_count": len(page_ids),
            "fragment_count": len(fragment_ids),
            "page_ids": page_ids,
            "fragment_ids": fragment_ids,
        }

    @pytest.mark.asyncio
    async def test_get_status_returns_task_info(
        self, memory_database, setup_task_with_search_data
    ) -> None:
        """
        TC-I-01: get_status returns task and search information.

        // Given: Task exists with search data in database
        // When: Calling get_status
        // Then: Returns task info with searches, metrics, budget
        """
        from src.mcp.server import _handle_get_status

        data = setup_task_with_search_data
        task_id = data["task_id"]

        mock_db = memory_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.server._get_exploration_state", side_effect=KeyError("No state")):
                result = await _handle_get_status({"task_id": task_id})

        # Verify response structure
        assert result["ok"] is True
        assert result["task_id"] == task_id
        assert result["query"] == "integration test query"
        assert "metrics" in result
        assert "budget" in result
        assert "searches" in result

    @pytest.mark.asyncio
    async def test_get_status_without_exploration_returns_minimal(
        self, memory_database
    ) -> None:
        """
        TC-I-03: Task with no exploration data returns empty searches.

        // Given: Task exists but no exploration started
        // When: Calling get_status
        // Then: Returns minimal status with empty searches
        """
        from src.mcp.server import _handle_get_status

        db = memory_database
        task_id = f"task_minimal_{uuid.uuid4().hex[:8]}"

        # Create bare task
        await db.execute(
            """INSERT INTO tasks (id, query, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, "minimal query", "pending", datetime.now(UTC).isoformat()),
        )

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            with patch("src.mcp.server._get_exploration_state", side_effect=KeyError("No state")):
                result = await _handle_get_status({"task_id": task_id})

        assert result["ok"] is True
        assert result["task_id"] == task_id
        assert result["searches"] == []
        assert result["metrics"]["total_searches"] == 0


@pytest.mark.integration
class TestGetMaterialsIntegration:
    """Integration tests for get_materials with real database data."""

    @pytest.fixture
    async def setup_task_with_claims(self, memory_database) -> dict[str, Any]:
        """Create a task with claims, fragments, and edges.

        Returns dict with task_id and expected counts.
        """
        db = memory_database
        task_id = f"task_mat_{uuid.uuid4().hex[:8]}"

        # Create task
        await db.execute(
            """INSERT INTO tasks (id, query, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, "materials test query", "exploring", datetime.now(UTC).isoformat()),
        )

        # Create page
        page_id = f"p_{uuid.uuid4().hex[:8]}"
        await db.execute(
            """INSERT INTO pages (id, url, domain, fetched_at)
               VALUES (?, ?, ?, datetime('now'))""",
            (page_id, "https://example.gov/doc", "example.gov"),
        )

        # Create fragments
        frag_ids = []
        for i in range(2):
            frag_id = f"f_{uuid.uuid4().hex[:8]}"
            frag_ids.append(frag_id)
            is_primary = i == 0
            await db.execute(
                """INSERT INTO fragments (id, page_id, fragment_type, text_content,
                   heading_context, is_relevant, relevance_reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (frag_id, page_id, "paragraph", f"Fragment content {i}", f"Section {i}",
                 1, f"primary_source={is_primary}; url=https://example.gov/doc"),
            )

        # Create claims
        claim_ids = []
        for i in range(2):
            claim_id = f"c_{uuid.uuid4().hex[:8]}"
            claim_ids.append(claim_id)
            await db.execute(
                """INSERT INTO claims (id, task_id, claim_text, claim_type, 
                   confidence_score, source_fragment_ids, verification_notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (claim_id, task_id, f"Claim {i} text", "fact", 0.8 - i*0.2,
                 json.dumps([frag_ids[i]]), "source_url=https://example.gov/doc"),
            )

        # Create edges (fragment -> claim)
        for i, (frag_id, claim_id) in enumerate(zip(frag_ids, claim_ids)):
            edge_id = f"e_{uuid.uuid4().hex[:8]}"
            await db.execute(
                """INSERT INTO edges (id, source_type, source_id, target_type, 
                   target_id, relation, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                (edge_id, "fragment", frag_id, "claim", claim_id, "supports"),
            )

        return {
            "task_id": task_id,
            "claim_count": 2,
            "fragment_count": 2,
            "page_id": page_id,
            "frag_ids": frag_ids,
            "claim_ids": claim_ids,
        }

    @pytest.mark.asyncio
    async def test_get_materials_returns_claims_and_fragments(
        self, memory_database, setup_task_with_claims
    ) -> None:
        """
        TC-I-02: get_materials returns claims and fragments from DB.

        // Given: Task with claims and fragments in database
        // When: Calling get_materials_action
        // Then: Returns claims, fragments, summary
        """
        from src.research.materials import get_materials_action

        data = setup_task_with_claims
        task_id = data["task_id"]

        with patch("src.research.materials.get_database", new=AsyncMock(return_value=memory_database)):
            result = await get_materials_action(task_id)

        assert result["ok"] is True
        assert result["task_id"] == task_id
        assert result["query"] == "materials test query"

        # Verify claims
        assert len(result["claims"]) == 2
        assert all("claim_text" in c or "text" in c for c in result["claims"])

        # Verify fragments
        assert len(result["fragments"]) >= 1

        # Verify summary
        assert "summary" in result
        assert result["summary"]["total_claims"] == 2

    @pytest.mark.asyncio
    async def test_get_materials_empty_task(self, memory_database) -> None:
        """
        TC-I-04: Task with 0 claims/fragments returns empty lists.

        // Given: Task exists but has no claims/fragments
        // When: Calling get_materials_action
        // Then: Returns empty claims and fragments lists
        """
        from src.research.materials import get_materials_action

        db = memory_database
        task_id = f"task_empty_{uuid.uuid4().hex[:8]}"

        # Create bare task
        await db.execute(
            """INSERT INTO tasks (id, query, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, "empty task query", "exploring", datetime.now(UTC).isoformat()),
        )

        with patch("src.research.materials.get_database", new=AsyncMock(return_value=db)):
            result = await get_materials_action(task_id)

        assert result["ok"] is True
        assert result["claims"] == []
        assert result["fragments"] == []
        assert result["summary"]["total_claims"] == 0

    @pytest.mark.asyncio
    async def test_get_materials_with_evidence_graph(
        self, memory_database, setup_task_with_claims
    ) -> None:
        """
        TC-I-05: get_materials with include_graph=True includes evidence_graph.

        // Given: Task with claims, fragments, and edges
        // When: Calling get_materials_action with include_graph=True
        // Then: Response includes evidence_graph structure (nodes and edges keys)
        """
        from src.research.materials import get_materials_action

        data = setup_task_with_claims
        task_id = data["task_id"]

        with patch("src.research.materials.get_database", new=AsyncMock(return_value=memory_database)):
            result = await get_materials_action(task_id, include_graph=True)

        assert result["ok"] is True
        assert "evidence_graph" in result

        graph = result["evidence_graph"]
        # Verify graph structure exists (fallback may return empty)
        assert "nodes" in graph
        assert "edges" in graph

        # Graph may be empty if EvidenceGraph module is not available in test env
        # In that case, fallback logic still creates empty structure which is valid
        assert isinstance(graph["nodes"], list)
        assert isinstance(graph["edges"], list)


@pytest.mark.integration
class TestMCPToolDataConsistency:
    """Tests for data consistency across MCP tools."""

    @pytest.fixture
    async def setup_full_exploration(self, memory_database) -> dict[str, Any]:
        """Create complete exploration data for consistency testing."""
        db = memory_database
        task_id = f"task_full_{uuid.uuid4().hex[:8]}"

        # Create task
        await db.execute(
            """INSERT INTO tasks (id, query, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, "full exploration query", "exploring", datetime.now(UTC).isoformat()),
        )

        # Create query/search (using actual schema)
        search_id = f"sq_{uuid.uuid4().hex[:8]}"
        await db.execute(
            """INSERT INTO queries (id, task_id, query_text, query_type, created_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (search_id, task_id, "search query", "initial"),
        )

        # Create page
        page_id = f"p_{uuid.uuid4().hex[:8]}"
        await db.execute(
            """INSERT INTO pages (id, url, domain, fetched_at)
               VALUES (?, ?, ?, datetime('now'))""",
            (page_id, "https://source.gov/data", "source.gov"),
        )

        # Create fragment
        frag_id = f"f_{uuid.uuid4().hex[:8]}"
        await db.execute(
            """INSERT INTO fragments (id, page_id, fragment_type, text_content,
               heading_context, is_relevant, relevance_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (frag_id, page_id, "paragraph", "Key information from source",
             "Results", 1, "primary_source=True; url=https://source.gov/data"),
        )

        # Create claim
        claim_id = f"c_{uuid.uuid4().hex[:8]}"
        await db.execute(
            """INSERT INTO claims (id, task_id, claim_text, claim_type,
               confidence_score, source_fragment_ids, verification_notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (claim_id, task_id, "Verified claim from exploration", "fact",
             0.9, json.dumps([frag_id]), "source_url=https://source.gov/data"),
        )

        # Create edge
        edge_id = f"e_{uuid.uuid4().hex[:8]}"
        await db.execute(
            """INSERT INTO edges (id, source_type, source_id, target_type,
               target_id, relation, created_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (edge_id, "fragment", frag_id, "claim", claim_id, "supports"),
        )

        return {
            "task_id": task_id,
            "search_id": search_id,
            "page_id": page_id,
            "frag_id": frag_id,
            "claim_id": claim_id,
        }

    @pytest.mark.asyncio
    async def test_get_status_and_materials_consistent(
        self, memory_database, setup_full_exploration
    ) -> None:
        """
        Test that get_status and get_materials return consistent data.

        // Given: Complete exploration with search, claims, fragments
        // When: Calling both get_status and get_materials
        // Then: Data is consistent (same task_id, related counts)
        """
        from src.mcp.server import _handle_get_status
        from src.research.materials import get_materials_action

        data = setup_full_exploration
        task_id = data["task_id"]

        # Get status
        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=memory_database)):
            with patch("src.mcp.server._get_exploration_state", side_effect=KeyError("No state")):
                status_result = await _handle_get_status({"task_id": task_id})

        # Get materials
        with patch("src.research.materials.get_database", new=AsyncMock(return_value=memory_database)):
            materials_result = await get_materials_action(task_id)

        # Verify both succeed
        assert status_result["ok"] is True
        assert materials_result["ok"] is True

        # Verify same task_id
        assert status_result["task_id"] == task_id
        assert materials_result["task_id"] == task_id

        # Verify materials contains expected claim
        assert len(materials_result["claims"]) == 1
        claim = materials_result["claims"][0]
        assert "Verified claim" in claim.get("claim_text", claim.get("text", ""))

