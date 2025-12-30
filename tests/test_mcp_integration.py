"""Integration tests for MCP tool data flow.

Per ADR-0003: MCP over CLI / REST API.

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
| TC-L7-01 | get_materials via call_tool (L7) | Equivalence – normal | L7 output preserves Bayesian fields | Contract wiring |
| TC-L7-02 | L7 strips unknown claim fields | Equivalence – negative | Unknown fields removed, allowed remain | Allowlist guard |
"""

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from src.filter.evidence_graph import NodeType, RelationType

if TYPE_CHECKING:
    from src.storage.database import Database


@pytest.mark.integration
class TestGetStatusIntegration:
    """Integration tests for get_status with real database data."""

    @pytest.fixture
    async def setup_task_with_search_data(self, memory_database: "Database") -> dict[str, Any]:
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
                (
                    fragment_id,
                    page_id,
                    "paragraph",
                    f"Content {i}",
                    f"Heading {i}",
                    1,
                    f"url=https://example.com/page{i}",
                ),
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
        self, memory_database: "Database", setup_task_with_search_data: dict[str, Any]
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
        self, memory_database: "Database"
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
    async def setup_task_with_claims(self, memory_database: "Database") -> dict[str, Any]:
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
                (
                    frag_id,
                    page_id,
                    "paragraph",
                    f"Fragment content {i}",
                    f"Section {i}",
                    1,
                    f"primary_source={is_primary}; url=https://example.gov/doc",
                ),
            )

        # Create claims
        claim_ids = []
        for i in range(2):
            claim_id = f"c_{uuid.uuid4().hex[:8]}"
            claim_ids.append(claim_id)
            await db.execute(
                """INSERT INTO claims (id, task_id, claim_text, claim_type,
                   llm_claim_confidence, source_fragment_ids, verification_notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    claim_id,
                    task_id,
                    f"Claim {i} text",
                    "fact",
                    0.8 - i * 0.2,
                    json.dumps([frag_ids[i]]),
                    "source_url=https://example.gov/doc",
                ),
            )

        # Create edges (fragment -> claim)
        for frag_id, claim_id in zip(frag_ids, claim_ids, strict=False):
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
        self, memory_database: "Database", setup_task_with_claims: dict[str, Any]
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

        with patch(
            "src.research.materials.get_database", new=AsyncMock(return_value=memory_database)
        ):
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
    async def test_get_materials_empty_task(self, memory_database: "Database") -> None:
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
        self, memory_database: "Database", setup_task_with_claims: dict[str, Any]
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

        with patch(
            "src.research.materials.get_database", new=AsyncMock(return_value=memory_database)
        ):
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

    @pytest.mark.asyncio
    async def test_get_materials_includes_bayesian_confidence(
        self, memory_database: "Database", setup_task_with_claims: dict[str, Any]
    ) -> None:
        """
        TC-4.3-N-01: get_materials includes uncertainty and controversy .

        // Given: Task with claims and evidence edges (with nli_edge_confidence)
        // When: Calling get_materials_action
        // Then: Claims include uncertainty and controversy fields
        """
        from src.filter import evidence_graph as eg_module
        from src.filter.evidence_graph import EvidenceGraph
        from src.research.materials import get_materials_action

        data = setup_task_with_claims
        task_id = data["task_id"]
        claim_ids = data["claim_ids"]

        # Clear global EvidenceGraph cache
        eg_module._graph = None

        # Patch get_database at all usage points (module-level imports require patching at use site)
        with (
            patch(
                "src.filter.evidence_graph.get_database",
                new=AsyncMock(return_value=memory_database),
            ),
            patch(
                "src.research.materials.get_database", new=AsyncMock(return_value=memory_database)
            ),
        ):
            # Add edges with nli_edge_confidence to evidence graph
            graph = EvidenceGraph(task_id=task_id)
            await graph.load_from_db(task_id=task_id)

            # Add supporting edge with nli_edge_confidence (add_edge is synchronous)
            graph.add_edge(
                source_type=NodeType.FRAGMENT,
                source_id=data["frag_ids"][0],
                target_type=NodeType.CLAIM,
                target_id=claim_ids[0],
                relation=RelationType.SUPPORTS,
                nli_edge_confidence=0.9,
            )

            # Add refuting edge with nli_edge_confidence
            graph.add_edge(
                source_type=NodeType.FRAGMENT,
                source_id=data["frag_ids"][1],
                target_type=NodeType.CLAIM,
                target_id=claim_ids[0],
                relation=RelationType.REFUTES,
                nli_edge_confidence=0.8,
            )

            # Save edges to DB
            await graph.save_to_db()

            # Clear cache before get_materials to force reload from DB
            eg_module._graph = None

            # Now get_materials should see the edges
            result = await get_materials_action(task_id)

        assert result["ok"] is True
        assert len(result["claims"]) >= 1

        # Verify Bayesian confidence fields exist
        claim_with_evidence = None
        for claim in result["claims"]:
            if claim["id"] == claim_ids[0]:
                claim_with_evidence = claim
                break

        assert claim_with_evidence is not None

        # Wiring test: Bayesian confidence fields exist
        assert "uncertainty" in claim_with_evidence
        assert "controversy" in claim_with_evidence
        assert isinstance(claim_with_evidence["uncertainty"], (int, float))
        assert isinstance(claim_with_evidence["controversy"], (int, float))
        assert claim_with_evidence["uncertainty"] >= 0.0
        assert claim_with_evidence["controversy"] >= 0.0

        # Effect test: Claim with both SUPPORTS and REFUTES should have controversy > 0
        assert claim_with_evidence["controversy"] > 0.0, (
            f"Expected controversy > 0 for claim with both SUPPORTS and REFUTES edges, "
            f"got {claim_with_evidence['controversy']}"
        )

    @pytest.mark.asyncio
    async def test_get_materials_call_tool_preserves_bayesian_fields(
        self, memory_database: "Database", setup_task_with_claims: dict[str, Any]
    ) -> None:
        """
        TC-L7-01: get_materials via MCP call_tool preserves Bayesian fields after L7.

        // Given: Task with claims exists in DB (memory_database) and schema allowlists Bayesian fields
        // When:  Calling src.mcp.server.call_tool("get_materials", ...) (L7 sanitize applied)
        // Then:  Claims still include uncertainty/controversy/evidence/evidence_years
        """
        from src.filter import evidence_graph as eg_module
        from src.mcp.server import call_tool

        # Clear module-level EvidenceGraph cache for reproducibility
        eg_module._graph = None

        data = setup_task_with_claims
        task_id = data["task_id"]

        with (
            patch("src.mcp.server.get_database", new=AsyncMock(return_value=memory_database)),
            patch(
                "src.research.materials.get_database", new=AsyncMock(return_value=memory_database)
            ),
            patch(
                "src.filter.evidence_graph.get_database",
                new=AsyncMock(return_value=memory_database),
            ),
        ):
            content_list = await call_tool(
                "get_materials",
                {"task_id": task_id, "options": {"include_graph": False}},
            )

        assert len(content_list) == 1
        payload = json.loads(content_list[0].text)

        assert payload["ok"] is True
        assert payload["task_id"] == task_id
        assert isinstance(payload.get("claims"), list)
        assert len(payload["claims"]) >= 1

        claim = payload["claims"][0]
        # Wiring test: these fields must survive L7 allowlist filtering
        assert "uncertainty" in claim
        assert "controversy" in claim
        assert "evidence" in claim
        assert "evidence_years" in claim

        # Boundary assertions: evidence_years values can be null
        assert isinstance(claim["evidence"], list)
        assert isinstance(claim["evidence_years"], dict)
        assert "oldest" in claim["evidence_years"]
        assert "newest" in claim["evidence_years"]

    @pytest.mark.asyncio
    async def test_get_materials_l7_strips_unknown_claim_fields_but_keeps_allowed(self) -> None:
        """
        TC-L7-02: L7 allowlist strips unknown claim fields but keeps allowed ones.

        // Given: A get_materials-like response containing both allowed and unknown claim fields
        // When:  Sanitizing via ResponseSanitizer with tool schema "get_materials"
        // Then:  Unknown fields are removed, allowed Bayesian fields remain
        """
        from src.mcp.response_sanitizer import ResponseSanitizer

        raw = {
            "ok": True,
            "task_id": "task_dummy",
            "query": "dummy",
            "claims": [
                {
                    "id": "c_dummy",
                    "text": "dummy claim",
                    "confidence": 0.5,
                    "uncertainty": 0.1,
                    "controversy": 0.2,
                    "evidence_count": 0,
                    "has_refutation": False,
                    "sources": [],
                    "evidence": [],
                    "evidence_years": {"oldest": None, "newest": None},
                    "claim_adoption_status": "adopted",
                    "claim_rejection_reason": None,
                    "unknown_debug": "SHOULD_BE_STRIPPED",
                }
            ],
            "fragments": [],
            "summary": {
                "total_claims": 1,
                "verified_claims": 0,
                "refuted_claims": 0,
                "primary_source_ratio": 0.0,
            },
        }

        sanitized = ResponseSanitizer().sanitize_response(raw, "get_materials").sanitized_response
        assert sanitized["ok"] is True
        assert isinstance(sanitized.get("claims"), list)
        assert len(sanitized["claims"]) == 1

        claim = sanitized["claims"][0]
        assert "unknown_debug" not in claim
        assert "uncertainty" in claim
        assert "controversy" in claim
        assert "evidence" in claim
        assert "evidence_years" in claim

    @pytest.mark.asyncio
    async def test_get_materials_includes_claim_adoption_status_default(
        self, memory_database: "Database", setup_task_with_claims: dict[str, Any]
    ) -> None:
        """
        TC-N-01 / TC-W-01: get_materials includes claim_adoption_status with default value.

        // Given: Task with claims that have default adoption status (adopted)
        // When: Calling get_materials_action
        // Then: Claims include claim_adoption_status="adopted" and claim_rejection_reason=None
        """
        from src.research.materials import get_materials_action

        data = setup_task_with_claims
        task_id = data["task_id"]

        with patch(
            "src.research.materials.get_database", new=AsyncMock(return_value=memory_database)
        ):
            result = await get_materials_action(task_id)

        assert result["ok"] is True
        assert len(result["claims"]) >= 1

        # Wiring test: All claims have claim_adoption_status field
        for claim in result["claims"]:
            assert "claim_adoption_status" in claim, "claim_adoption_status field must be present"
            assert "claim_rejection_reason" in claim, "claim_rejection_reason field must be present"
            # Default value check
            assert claim["claim_adoption_status"] == "adopted"
            assert claim["claim_rejection_reason"] is None

    @pytest.mark.asyncio
    async def test_get_materials_not_adopted_claim_with_reason(
        self, memory_database: "Database"
    ) -> None:
        """
        TC-N-02 / TC-E-01: get_materials returns not_adopted claim with rejection reason.

        // Given: Task with a claim marked as not_adopted with rejection reason
        // When: Calling get_materials_action
        // Then: Claim has claim_adoption_status="not_adopted" and claim_rejection_reason set
        """
        from src.research.materials import get_materials_action

        db = memory_database
        task_id = f"task_reject_{uuid.uuid4().hex[:8]}"
        claim_id = f"c_{uuid.uuid4().hex[:8]}"
        rejection_reason = "Low confidence source"

        # Create task
        await db.execute(
            """INSERT INTO tasks (id, query, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, "rejection test query", "exploring", datetime.now(UTC).isoformat()),
        )

        # Create claim with not_adopted status and rejection reason
        await db.execute(
            """INSERT INTO claims (id, task_id, claim_text, claim_type,
               llm_claim_confidence, claim_adoption_status, claim_rejection_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                claim_id,
                task_id,
                "Rejected claim text",
                "fact",
                0.5,
                "not_adopted",
                rejection_reason,
            ),
        )

        with patch(
            "src.research.materials.get_database", new=AsyncMock(return_value=memory_database)
        ):
            result = await get_materials_action(task_id)

        assert result["ok"] is True
        assert len(result["claims"]) == 1

        claim = result["claims"][0]
        # Effect test: Status and reason are correctly propagated
        assert claim["claim_adoption_status"] == "not_adopted"
        assert claim["claim_rejection_reason"] == rejection_reason

    @pytest.mark.asyncio
    async def test_get_materials_claim_rejection_reason_null(
        self, memory_database: "Database"
    ) -> None:
        """
        TC-B-02: Claim with NULL rejection_reason returns None.

        // Given: Task with a claim that has claim_adoption_status but no rejection reason
        // When: Calling get_materials_action
        // Then: claim_rejection_reason is None (not missing)
        """
        from src.research.materials import get_materials_action

        db = memory_database
        task_id = f"task_null_{uuid.uuid4().hex[:8]}"
        claim_id = f"c_{uuid.uuid4().hex[:8]}"

        # Create task
        await db.execute(
            """INSERT INTO tasks (id, query, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, "null reason test query", "exploring", datetime.now(UTC).isoformat()),
        )

        # Create claim with adopted status and no rejection reason (NULL)
        await db.execute(
            """INSERT INTO claims (id, task_id, claim_text, claim_type,
               llm_claim_confidence, claim_adoption_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                claim_id,
                task_id,
                "Claim with null reason",
                "fact",
                0.8,
                "adopted",
            ),
        )

        with patch(
            "src.research.materials.get_database", new=AsyncMock(return_value=memory_database)
        ):
            result = await get_materials_action(task_id)

        assert result["ok"] is True
        assert len(result["claims"]) == 1

        claim = result["claims"][0]
        assert claim["claim_adoption_status"] == "adopted"
        # Boundary test: NULL in DB returns None (not omitted)
        assert "claim_rejection_reason" in claim
        assert claim["claim_rejection_reason"] is None

    @pytest.mark.asyncio
    async def test_get_materials_mixed_adoption_statuses(self, memory_database: "Database") -> None:
        """
        TC-E-01 variant: get_materials correctly returns mixed adoption statuses.

        // Given: Task with multiple claims having different adoption statuses
        // When: Calling get_materials_action
        // Then: Each claim reflects its individual adoption status
        """
        from src.research.materials import get_materials_action

        db = memory_database
        task_id = f"task_mixed_{uuid.uuid4().hex[:8]}"

        # Create task
        await db.execute(
            """INSERT INTO tasks (id, query, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, "mixed status test query", "exploring", datetime.now(UTC).isoformat()),
        )

        # Create claims with different statuses
        test_cases = [
            ("c_adopted", "adopted", None),
            ("c_not_adopted", "not_adopted", "Manual rejection by user"),
            ("c_pending", "pending", None),
        ]

        for claim_suffix, status, reason in test_cases:
            claim_id = f"{claim_suffix}_{uuid.uuid4().hex[:8]}"
            await db.execute(
                """INSERT INTO claims (id, task_id, claim_text, claim_type,
                   llm_claim_confidence, claim_adoption_status, claim_rejection_reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    claim_id,
                    task_id,
                    f"Claim with status {status}",
                    "fact",
                    0.7,
                    status,
                    reason,
                ),
            )

        with patch(
            "src.research.materials.get_database", new=AsyncMock(return_value=memory_database)
        ):
            result = await get_materials_action(task_id)

        assert result["ok"] is True
        assert len(result["claims"]) == 3

        # Verify each status is preserved
        statuses_found = {c["claim_adoption_status"] for c in result["claims"]}
        assert statuses_found == {"adopted", "not_adopted", "pending"}

        # Verify rejection reason is only set for not_adopted
        for claim in result["claims"]:
            if claim["claim_adoption_status"] == "not_adopted":
                assert claim["claim_rejection_reason"] == "Manual rejection by user"
            else:
                assert claim["claim_rejection_reason"] is None


@pytest.mark.integration
class TestMCPToolDataConsistency:
    """Tests for data consistency across MCP tools."""

    @pytest.fixture
    async def setup_full_exploration(self, memory_database: "Database") -> dict[str, Any]:
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
            (
                frag_id,
                page_id,
                "paragraph",
                "Key information from source",
                "Results",
                1,
                "primary_source=True; url=https://source.gov/data",
            ),
        )

        # Create claim
        claim_id = f"c_{uuid.uuid4().hex[:8]}"
        await db.execute(
            """INSERT INTO claims (id, task_id, claim_text, claim_type,
               llm_claim_confidence, source_fragment_ids, verification_notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                claim_id,
                task_id,
                "Verified claim from exploration",
                "fact",
                0.9,
                json.dumps([frag_id]),
                "source_url=https://source.gov/data",
            ),
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
        self, memory_database: "Database", setup_full_exploration: dict[str, Any]
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
        with patch(
            "src.research.materials.get_database", new=AsyncMock(return_value=memory_database)
        ):
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


@pytest.mark.integration
class TestDomainOverrideStartupRestore:
    """Tests for domain override restoration on server startup.

    Ensures domain-specific policies persist across server restarts.
    Test matrix for load_domain_overrides_from_db() on startup:

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-SR-01 | DB has domain_block rule | Equivalence - normal | _blocked_domains reflects rule | wiring |
    | TC-SR-02 | DB has domain_unblock rule | Equivalence - normal | _blocked_domains excludes domain | wiring |
    | TC-SR-03 | DB has multiple rules (block + unblock) | Equivalence - normal | Both applied correctly | compound |
    | TC-SR-04 | DB has no rules (empty) | Boundary - empty | _blocked_domains stays empty | boundary |
    | TC-SR-05 | DB has is_active=0 rule | Boundary - inactive | Inactive rules ignored | boundary |
    """

    @pytest.fixture(autouse=True)
    def reset_verifier_for_startup_tests(self) -> None:
        """Reset SourceVerifier before each test."""
        from src.filter.source_verification import reset_source_verifier

        reset_source_verifier()

    @pytest.mark.asyncio
    async def test_startup_restores_blocked_domain(self, memory_database: "Database") -> None:
        """
        TC-SR-01: Server startup restores blocked domain from DB.

        // Given: DB contains active domain_block rule
        // When: load_domain_overrides_from_db() is called
        // Then: Domain is in SourceVerifier._blocked_domains
        """
        from src.filter.source_verification import (
            get_source_verifier,
            load_domain_overrides_from_db,
        )

        db = memory_database
        domain = "blocked-on-startup.com"

        # Given: DB contains active domain_block rule
        await db.execute(
            """INSERT INTO domain_override_rules
               (domain_pattern, decision, reason, is_active, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (domain, "block", "Manual block from previous session", 1),
        )

        # When: load_domain_overrides_from_db() is called
        with patch(
            "src.storage.database.get_database",
            new=AsyncMock(return_value=memory_database),
        ):
            await load_domain_overrides_from_db()

        # Then: Domain is in SourceVerifier._blocked_domains
        verifier = get_source_verifier()
        assert (
            domain in verifier._blocked_domains
        ), f"Expected '{domain}' in _blocked_domains after startup restore"

    @pytest.mark.asyncio
    async def test_startup_restores_unblocked_domain(self, memory_database: "Database") -> None:
        """
        TC-SR-02: Server startup restores unblocked domain from DB.

        // Given: DB contains active domain_unblock rule
        // When: load_domain_overrides_from_db() is called
        // Then: Domain is removed from SourceVerifier._blocked_domains
        """
        from src.filter.source_verification import (
            get_source_verifier,
            load_domain_overrides_from_db,
        )

        db = memory_database
        domain = "unblocked-on-startup.com"
        verifier = get_source_verifier()

        # Pre-condition: Domain is initially blocked (e.g., from denylist)
        verifier._blocked_domains.add(domain)
        assert domain in verifier._blocked_domains

        # Given: DB contains active domain_unblock rule
        await db.execute(
            """INSERT INTO domain_override_rules
               (domain_pattern, decision, reason, is_active, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (domain, "unblock", "Manual unblock from previous session", 1),
        )

        # When: load_domain_overrides_from_db() is called
        with patch(
            "src.storage.database.get_database",
            new=AsyncMock(return_value=memory_database),
        ):
            await load_domain_overrides_from_db()

        # Then: Domain is removed from SourceVerifier._blocked_domains
        assert (
            domain not in verifier._blocked_domains
        ), f"Expected '{domain}' NOT in _blocked_domains after startup restore"

    @pytest.mark.asyncio
    async def test_startup_restores_multiple_rules(self, memory_database: "Database") -> None:
        """
        TC-SR-03: Server startup restores multiple domain rules (block + unblock).

        // Given: DB contains multiple active rules
        // When: load_domain_overrides_from_db() is called
        // Then: All rules are applied correctly
        """
        from src.filter.source_verification import (
            get_source_verifier,
            load_domain_overrides_from_db,
        )

        db = memory_database
        block_domain = "should-be-blocked.com"
        unblock_domain = "should-be-unblocked.com"
        verifier = get_source_verifier()

        # Pre-condition: unblock_domain is initially blocked
        verifier._blocked_domains.add(unblock_domain)

        # Given: DB contains multiple active rules
        await db.execute(
            """INSERT INTO domain_override_rules
               (domain_pattern, decision, reason, is_active, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (block_domain, "block", "Block rule", 1),
        )
        await db.execute(
            """INSERT INTO domain_override_rules
               (domain_pattern, decision, reason, is_active, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (unblock_domain, "unblock", "Unblock rule", 1),
        )

        # When: load_domain_overrides_from_db() is called
        with patch(
            "src.storage.database.get_database",
            new=AsyncMock(return_value=memory_database),
        ):
            await load_domain_overrides_from_db()

        # Then: All rules are applied correctly
        assert block_domain in verifier._blocked_domains
        assert unblock_domain not in verifier._blocked_domains

    @pytest.mark.asyncio
    async def test_startup_with_empty_rules(self, memory_database: "Database") -> None:
        """
        TC-SR-04: Server startup with no domain rules leaves _blocked_domains empty.

        // Given: DB contains no domain_override_rules
        // When: load_domain_overrides_from_db() is called
        // Then: _blocked_domains remains empty (no error)
        """
        from src.filter.source_verification import (
            get_source_verifier,
            load_domain_overrides_from_db,
        )

        verifier = get_source_verifier()

        # Given: DB contains no rules (memory_database is fresh)
        # When: load_domain_overrides_from_db() is called
        with patch(
            "src.storage.database.get_database",
            new=AsyncMock(return_value=memory_database),
        ):
            await load_domain_overrides_from_db()

        # Then: _blocked_domains remains empty (no error)
        assert len(verifier._blocked_domains) == 0

    @pytest.mark.asyncio
    async def test_startup_ignores_inactive_rules(self, memory_database: "Database") -> None:
        """
        TC-SR-05: Server startup ignores inactive (is_active=0) rules.

        // Given: DB contains inactive domain_block rule (is_active=0)
        // When: load_domain_overrides_from_db() is called
        // Then: Inactive rule is ignored, domain NOT in _blocked_domains
        """
        from src.filter.source_verification import (
            get_source_verifier,
            load_domain_overrides_from_db,
        )

        db = memory_database
        domain = "inactive-rule.com"

        # Given: DB contains inactive rule
        await db.execute(
            """INSERT INTO domain_override_rules
               (domain_pattern, decision, reason, is_active, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (domain, "block", "Inactive block rule", 0),  # is_active=0
        )

        # When: load_domain_overrides_from_db() is called
        with patch(
            "src.storage.database.get_database",
            new=AsyncMock(return_value=memory_database),
        ):
            await load_domain_overrides_from_db()

        # Then: Inactive rule is ignored
        verifier = get_source_verifier()
        assert (
            domain not in verifier._blocked_domains
        ), f"Expected '{domain}' NOT in _blocked_domains (inactive rule should be ignored)"
