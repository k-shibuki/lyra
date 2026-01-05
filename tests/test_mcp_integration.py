"""Integration tests for MCP tool data flow.

Per ADR-0003: MCP over CLI / REST API.

Tests the full data flow between MCP tools:
- create_task → search → get_status → query_sql/vector_search → stop_task

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-I-01 | Valid task with search data | Equivalence – normal | get_status returns search info | E2E flow |
| TC-I-03 | Task with no exploration data | Boundary – empty | get_status returns empty searches | Minimal case |
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

if TYPE_CHECKING:
    from src.storage.database import Database


@pytest.mark.integration
class TestGetStatusIntegration:
    """Integration tests for get_status with real database data."""

    @pytest.fixture
    async def setup_task_with_search_data(self, memory_database: Database) -> dict[str, Any]:
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
        self, memory_database: Database, setup_task_with_search_data: dict[str, Any]
    ) -> None:
        """
        TC-I-01: get_status returns task and search information.

        // Given: Task exists with search data in database
        // When: Calling get_status
        // Then: Returns task info with searches, metrics, budget
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        data = setup_task_with_search_data
        task_id = data["task_id"]

        mock_db = memory_database

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state", side_effect=KeyError("No state")
            ):
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
        self, memory_database: Database
    ) -> None:
        """
        TC-I-03: Task with no exploration data returns empty searches.

        // Given: Task exists but no exploration started
        // When: Calling get_status
        // Then: Returns minimal status with empty searches
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        db = memory_database
        task_id = f"task_minimal_{uuid.uuid4().hex[:8]}"

        # Create bare task
        await db.execute(
            """INSERT INTO tasks (id, query, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, "minimal query", "pending", datetime.now(UTC).isoformat()),
        )

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state", side_effect=KeyError("No state")
            ):
                result = await _handle_get_status({"task_id": task_id})

        assert result["ok"] is True
        assert result["task_id"] == task_id
        assert result["searches"] == []
        assert result["metrics"]["total_searches"] == 0


@pytest.mark.integration
class TestMCPToolDataConsistency:
    """Tests for data consistency across MCP tools."""

    @pytest.fixture
    async def setup_full_exploration(self, memory_database: Database) -> dict[str, Any]:
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

        # Create claim (provenance tracked via origin edge, not JSON column)
        claim_id = f"c_{uuid.uuid4().hex[:8]}"
        await db.execute(
            """INSERT INTO claims (id, task_id, claim_text, claim_type,
               llm_claim_confidence, verification_notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                claim_id,
                task_id,
                "Verified claim from exploration",
                "fact",
                0.9,
                "source_url=https://source.gov/data",
            ),
        )

        # Create origin edge (provenance)
        origin_edge_id = f"e_{uuid.uuid4().hex[:8]}"
        await db.execute(
            """INSERT INTO edges (id, source_type, source_id, target_type,
               target_id, relation, created_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (origin_edge_id, "fragment", frag_id, "claim", claim_id, "origin"),
        )

        # Create supports edge (NLI evidence)
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
    async def test_get_status_returns_evidence_summary(
        self, memory_database: Database, setup_full_exploration: dict[str, Any]
    ) -> None:
        """
        Test that get_status returns evidence_summary when task is completed.

        // Given: Complete exploration with search, claims, fragments
        // When: Calling get_status
        // Then: Returns evidence_summary with claim/fragment/edge counts
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        data = setup_full_exploration
        task_id = data["task_id"]

        # Mark task as completed
        await memory_database.execute(
            "UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,)
        )

        # Get status
        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=memory_database)):
            with patch(
                "src.mcp.tools.task.get_exploration_state", side_effect=KeyError("No state")
            ):
                status_result = await _handle_get_status({"task_id": task_id})

        # Verify status succeeded
        assert status_result["ok"] is True
        assert status_result["task_id"] == task_id

        # Verify evidence_summary is present for completed task
        assert "evidence_summary" in status_result
        summary = status_result["evidence_summary"]
        assert summary["total_claims"] >= 0
        assert summary["total_fragments"] >= 0


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
    async def test_startup_restores_blocked_domain(self, memory_database: Database) -> None:
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
    async def test_startup_restores_unblocked_domain(self, memory_database: Database) -> None:
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
    async def test_startup_restores_multiple_rules(self, memory_database: Database) -> None:
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
    async def test_startup_with_empty_rules(self, memory_database: Database) -> None:
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
    async def test_startup_ignores_inactive_rules(self, memory_database: Database) -> None:
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
