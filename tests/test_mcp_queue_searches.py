"""Tests for queue_searches MCP tool.

Tests the async search queue tool per ADR-0010.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-Q-01 | Valid task_id, queries | Equivalence – normal | Searches queued, returns search_ids | Happy path |
| TC-Q-02 | Missing task_id | Boundary – NULL | InvalidParamsError | Validation |
| TC-Q-03 | Empty queries array | Boundary – empty | InvalidParamsError | Validation |
| TC-Q-04 | Non-existent task_id | Equivalence – error | TaskNotFoundError | Validation |
| TC-Q-05 | priority="high" | Equivalence – option | priority_value=10 in DB | Priority mapping |
| TC-Q-06 | priority="low" | Equivalence – option | priority_value=90 in DB | Priority mapping |
| TC-Q-07 | Multiple queries | Equivalence – normal | All queued with separate IDs | Batch |
| TC-QS-01 | get_status after queue | Equivalence – normal | queue.depth shows queued count | Integration |
| TC-QS-02 | get_status wait=0 | Boundary – minimum | Returns immediately | Long polling |
| TC-QS-03 | get_status wait=60 | Boundary – maximum | Waits up to 60s | Long polling |
| TC-QS-04 | get_status wait=-1 | Boundary – invalid | InvalidParamsError | Validation |
| TC-QS-05 | get_status wait=61 | Boundary – invalid | InvalidParamsError | Validation |
"""

import json
from datetime import UTC, datetime

import pytest


class TestQueueSearchesValidation:
    """Tests for queue_searches parameter validation."""

    @pytest.mark.asyncio
    async def test_missing_task_id(self, test_database) -> None:
        """
        TC-Q-02: Missing task_id raises InvalidParamsError.

        // Given: queue_searches called without task_id
        // When: Handler is invoked
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_queue_searches

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_queue_searches(
                {
                    "queries": ["test query"],
                }
            )

        assert "task_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_queries(self, test_database) -> None:
        """
        TC-Q-03: Empty queries array raises InvalidParamsError.

        // Given: queue_searches with empty queries
        // When: Handler is invoked
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_queue_searches

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_queue_searches(
                {
                    "task_id": "task_q03",
                    "queries": [],
                }
            )

        assert "queries" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_nonexistent_task(self, test_database) -> None:
        """
        TC-Q-04: Non-existent task_id raises TaskNotFoundError.

        // Given: queue_searches with non-existent task
        // When: Handler is invoked
        // Then: TaskNotFoundError is raised
        """
        from src.mcp.errors import TaskNotFoundError
        from src.mcp.server import _handle_queue_searches

        with pytest.raises(TaskNotFoundError) as exc_info:
            await _handle_queue_searches(
                {
                    "task_id": "nonexistent_task",
                    "queries": ["test query"],
                }
            )

        assert "nonexistent_task" in str(exc_info.value)


class TestQueueSearchesExecution:
    """Tests for queue_searches execution."""

    @pytest.mark.asyncio
    async def test_queue_single_query(self, test_database) -> None:
        """
        TC-Q-01: Queue single search query.

        // Given: Valid task
        // When: queue_searches with one query
        // Then: Returns ok=True, queued_count=1, search_ids
        """
        from src.mcp.server import _handle_queue_searches

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_q01", "Test task", "exploring"),
        )

        result = await _handle_queue_searches(
            {
                "task_id": "task_q01",
                "queries": ["test search query"],
            }
        )

        assert result["ok"] is True
        assert result["queued_count"] == 1
        assert len(result["search_ids"]) == 1
        assert result["search_ids"][0].startswith("s_")

        # Verify job in database
        row = await db.fetch_one(
            "SELECT * FROM jobs WHERE id = ?",
            (result["search_ids"][0],),
        )
        assert row is not None
        assert row["kind"] == "search_queue"
        assert row["state"] == "queued"
        assert row["priority"] == 50  # default medium

    @pytest.mark.asyncio
    async def test_queue_multiple_queries(self, test_database) -> None:
        """
        TC-Q-07: Queue multiple search queries.

        // Given: Valid task
        // When: queue_searches with multiple queries
        // Then: All queued with unique IDs
        """
        from src.mcp.server import _handle_queue_searches

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_q07", "Test task", "exploring"),
        )

        result = await _handle_queue_searches(
            {
                "task_id": "task_q07",
                "queries": ["query 1", "query 2", "query 3"],
            }
        )

        assert result["ok"] is True
        assert result["queued_count"] == 3
        assert len(result["search_ids"]) == 3
        assert len(set(result["search_ids"])) == 3  # All unique

    @pytest.mark.asyncio
    async def test_queue_with_high_priority(self, test_database) -> None:
        """
        TC-Q-05: Queue with priority="high" sets priority=10.

        // Given: Valid task
        // When: queue_searches with priority="high"
        // Then: Job has priority=10
        """
        from src.mcp.server import _handle_queue_searches

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_q05", "Test task", "exploring"),
        )

        result = await _handle_queue_searches(
            {
                "task_id": "task_q05",
                "queries": ["high priority query"],
                "options": {"priority": "high"},
            }
        )

        row = await db.fetch_one(
            "SELECT priority FROM jobs WHERE id = ?",
            (result["search_ids"][0],),
        )
        assert row["priority"] == 10

    @pytest.mark.asyncio
    async def test_queue_with_low_priority(self, test_database) -> None:
        """
        TC-Q-06: Queue with priority="low" sets priority=90.

        // Given: Valid task
        // When: queue_searches with priority="low"
        // Then: Job has priority=90
        """
        from src.mcp.server import _handle_queue_searches

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_q06", "Test task", "exploring"),
        )

        result = await _handle_queue_searches(
            {
                "task_id": "task_q06",
                "queries": ["low priority query"],
                "options": {"priority": "low"},
            }
        )

        row = await db.fetch_one(
            "SELECT priority FROM jobs WHERE id = ?",
            (result["search_ids"][0],),
        )
        assert row["priority"] == 90


class TestGetStatusWithWait:
    """Tests for get_status wait parameter (long polling)."""

    @pytest.mark.asyncio
    async def test_get_status_wait_validation_negative(self, test_database) -> None:
        """
        TC-QS-04: get_status with wait=-1 raises InvalidParamsError.

        // Given: Invalid wait value
        // When: get_status called
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_get_status

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_qs04", "Test task", "exploring"),
        )

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_get_status(
                {
                    "task_id": "task_qs04",
                    "wait": -1,
                }
            )

        assert "wait" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_status_wait_validation_too_large(self, test_database) -> None:
        """
        TC-QS-05: get_status with wait=61 raises InvalidParamsError.

        // Given: wait > 60
        // When: get_status called
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_get_status

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_qs05", "Test task", "exploring"),
        )

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_get_status(
                {
                    "task_id": "task_qs05",
                    "wait": 61,
                }
            )

        assert "wait" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_status_wait_zero_returns_immediately(self, test_database) -> None:
        """
        TC-QS-02: get_status with wait=0 returns immediately.

        // Given: Task exists
        // When: get_status with wait=0
        // Then: Returns immediately without waiting
        """
        from src.mcp.server import _handle_get_status

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_qs02", "Test task", "exploring"),
        )

        import time

        start = time.time()
        result = await _handle_get_status(
            {
                "task_id": "task_qs02",
                "wait": 0,
            }
        )
        elapsed = time.time() - start

        assert result["ok"] is True
        assert elapsed < 0.5  # Should be nearly instant


class TestGetStatusQueueField:
    """Tests for get_status queue field."""

    @pytest.mark.asyncio
    async def test_get_status_shows_queue_status(self, test_database) -> None:
        """
        TC-QS-01: get_status shows queued search count.

        // Given: Task with queued searches
        // When: get_status called
        // Then: queue.depth reflects queued count
        """
        from src.mcp.server import _handle_get_status

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_qs01", "Test task", "exploring"),
        )

        # Queue some searches
        now = datetime.now(UTC).isoformat()
        for i in range(3):
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"s_qs01_{i}",
                    "task_qs01",
                    "search_queue",
                    50,
                    "network_client",
                    "queued",
                    json.dumps({"query": f"query {i}", "options": {}}),
                    now,
                ),
            )

        result = await _handle_get_status(
            {
                "task_id": "task_qs01",
            }
        )

        assert result["ok"] is True
        assert "queue" in result
        assert result["queue"]["depth"] == 3
        assert result["queue"]["running"] == 0
        assert len(result["queue"]["items"]) == 3

    @pytest.mark.asyncio
    async def test_get_status_empty_queue(self, test_database) -> None:
        """
        Test get_status with no queued searches.

        // Given: Task with no queued searches
        // When: get_status called
        // Then: queue.depth is 0
        """
        from src.mcp.server import _handle_get_status

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            ("task_empty_q", "Test task", "exploring"),
        )

        result = await _handle_get_status(
            {
                "task_id": "task_empty_q",
            }
        )

        assert result["ok"] is True
        assert result["queue"]["depth"] == 0
        assert result["queue"]["running"] == 0
        assert result["queue"]["items"] == []


class TestQueueSearchesToolDefinition:
    """Tests for queue_searches tool definition."""

    def test_queue_searches_in_tools(self) -> None:
        """
        Test that queue_searches is defined in TOOLS list.

        // Given: TOOLS list
        // When: Looking for queue_searches
        // Then: Tool is found with correct schema
        """
        from src.mcp.server import TOOLS

        tool_names = [t.name for t in TOOLS]
        assert "queue_searches" in tool_names

        queue_tool = next(t for t in TOOLS if t.name == "queue_searches")
        assert "task_id" in queue_tool.inputSchema["properties"]
        assert "queries" in queue_tool.inputSchema["properties"]
        assert queue_tool.inputSchema["properties"]["queries"]["minItems"] == 1

    def test_get_status_has_wait_parameter(self) -> None:
        """
        Test that get_status has wait parameter in schema.

        // Given: TOOLS list
        // When: Looking at get_status schema
        // Then: wait parameter is defined
        """
        from src.mcp.server import TOOLS

        get_status_tool = next(t for t in TOOLS if t.name == "get_status")
        assert "wait" in get_status_tool.inputSchema["properties"]
        assert get_status_tool.inputSchema["properties"]["wait"]["maximum"] == 60
        assert get_status_tool.inputSchema["properties"]["wait"]["minimum"] == 0
