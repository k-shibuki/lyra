"""Tests for queue_targets MCP tool.

Tests the async target queue tool per ADR-0010.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-Q-01 | Valid task_id, targets (queries) | Equivalence – normal | Targets queued, returns target_ids | Happy path |
| TC-Q-02 | Missing task_id | Boundary – NULL | InvalidParamsError | Validation |
| TC-Q-03 | Empty targets array | Boundary – empty | InvalidParamsError | Validation |
| TC-Q-04 | Non-existent task_id | Equivalence – error | TaskNotFoundError | Validation |
| TC-Q-05 | priority="high" | Equivalence – option | priority_value=10 in DB | Priority mapping |
| TC-Q-06 | priority="low" | Equivalence – option | priority_value=90 in DB | Priority mapping |
| TC-Q-07 | Multiple targets (queries) | Equivalence – normal | All queued with separate IDs | Batch |
| TC-Q-08 | budget_pages=5 | Wiring – option propagation | budget_pages in input_json | Propagation |
| TC-Q-09 | serp_engines=["duckduckgo"] | Wiring – option propagation | serp_engines in input_json | Propagation |
| TC-Q-10 | budget_pages + serp_engines | Effect – options preserved | Both in input_json, priority excluded | Full options |
| TC-QS-01 | get_status after queue | Equivalence – normal | queue.depth shows queued count | Integration |
| TC-QS-02 | get_status wait=0 | Boundary – minimum | Returns immediately | Long polling |
| TC-Q-11 | queue_targets on paused task | Equivalence – resume | Task resumed, status=exploring | Resumption |
| TC-Q-12 | queue_targets on failed task | Boundary – rejected | InvalidParamsError | Failed rejection |
| TC-Q-13 | queue_targets response has task_resumed | Equivalence – flag | task_resumed=True for paused | Response field |
| TC-Q-14 | serp_engines with unknown engine | Abnormal – invalid enum | InvalidParamsError | SERP validation |
| TC-Q-15 | academic_apis with unknown API | Abnormal – invalid enum | InvalidParamsError | Academic validation |
| TC-Q-16 | serp_engines=[] (empty) | Boundary – empty | InvalidParamsError | Empty array rejected |
| TC-Q-17 | academic_apis=[] (empty) | Boundary – empty | InvalidParamsError | Empty array rejected |
| TC-Q-18 | academic_apis=["semantic_scholar"] | Equivalence – normal | Stored in input_json | Valid academic API |
| TC-URL-01 | targets with URL | Equivalence – URL target | kind='url' job created | URL routing |
| TC-URL-02 | Mixed query + URL targets | Equivalence – mixed | Both query and url jobs created | Mixed batch |
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from src.storage.database import Database

pytestmark = pytest.mark.integration


class TestQueueTargetsValidation:
    """Tests for queue_targets parameter validation."""

    @pytest.mark.asyncio
    async def test_missing_task_id(self, test_database: Database) -> None:
        """
        TC-Q-02: Missing task_id raises InvalidParamsError.

        // Given: queue_targets called without task_id
        // When: Handler is invoked
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_queue_targets(
                {
                    "targets": [{"kind": "query", "query": "test query"}],
                }
            )

        assert "task_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_targets(self, test_database: Database) -> None:
        """
        TC-Q-03: Empty targets array raises InvalidParamsError.

        // Given: queue_targets with empty targets
        // When: Handler is invoked
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_queue_targets(
                {
                    "task_id": "task_q03",
                    "targets": [],
                }
            )

        assert "targets" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_nonexistent_task(self, test_database: Database) -> None:
        """
        TC-Q-04: Non-existent task_id raises TaskNotFoundError.

        // Given: queue_targets with non-existent task
        // When: Handler is invoked
        // Then: TaskNotFoundError is raised
        """
        from src.mcp.errors import TaskNotFoundError
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        with pytest.raises(TaskNotFoundError) as exc_info:
            await _handle_queue_targets(
                {
                    "task_id": "nonexistent_task",
                    "targets": [{"kind": "query", "query": "test query"}],
                }
            )

        assert "nonexistent_task" in str(exc_info.value)


class TestQueueTargetsExecution:
    """Tests for queue_targets execution."""

    @pytest.mark.asyncio
    async def test_queue_single_query(self, test_database: Database) -> None:
        """
        TC-Q-01: Queue single search query target.

        // Given: Valid task
        // When: queue_targets with one query target
        // Then: Returns ok=True, queued_count=1, target_ids
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q01", "Test task", "exploring"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_q01",
                "targets": [{"kind": "query", "query": "test search query"}],
            }
        )

        assert result["ok"] is True
        assert result["queued_count"] == 1
        assert len(result["target_ids"]) == 1
        assert result["target_ids"][0].startswith("tq_")

        # Verify job in database
        row = await db.fetch_one(
            "SELECT * FROM jobs WHERE id = ?",
            (result["target_ids"][0],),
        )
        assert row is not None
        assert row["kind"] == "target_queue"
        # Job may be 'queued' or 'running' (scheduler picks up immediately)
        assert row["state"] in ("queued", "running", "completed", "failed")
        assert row["priority"] == 50  # default medium

        # Verify input_json contains query kind
        input_data = json.loads(row["input_json"])
        assert input_data["target"]["kind"] == "query"
        assert input_data["target"]["query"] == "test search query"

    @pytest.mark.asyncio
    async def test_queue_url_target(self, test_database: Database) -> None:
        """
        TC-URL-01: Queue URL target creates kind='url' job.

        // Given: Valid task
        // When: queue_targets with URL target
        // Then: Job created with kind='url' in input_json
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_url01", "Test task", "exploring"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_url01",
                "targets": [{"kind": "url", "url": "https://example.com/paper.pdf"}],
            }
        )

        assert result["ok"] is True
        assert result["queued_count"] == 1

        # Verify job in database
        row = await db.fetch_one(
            "SELECT * FROM jobs WHERE id = ?",
            (result["target_ids"][0],),
        )
        assert row is not None
        assert row["kind"] == "target_queue"

        # Verify input_json contains url kind
        input_data = json.loads(row["input_json"])
        assert input_data["target"]["kind"] == "url"
        assert input_data["target"]["url"] == "https://example.com/paper.pdf"

    @pytest.mark.asyncio
    async def test_queue_mixed_targets(self, test_database: Database) -> None:
        """
        TC-URL-02: Queue mixed query and URL targets.

        // Given: Valid task
        // When: queue_targets with both query and URL targets
        // Then: Both jobs created with appropriate kinds
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_mixed", "Test task", "exploring"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_mixed",
                "targets": [
                    {"kind": "query", "query": "meta-analysis diabetes"},
                    {"kind": "url", "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/"},
                    {"kind": "query", "query": "systematic review insulin"},
                ],
            }
        )

        assert result["ok"] is True
        assert result["queued_count"] == 3
        assert len(result["target_ids"]) == 3

        # Verify first target (query)
        row1 = await db.fetch_one(
            "SELECT input_json FROM jobs WHERE id = ?",
            (result["target_ids"][0],),
        )
        assert row1 is not None
        input1 = json.loads(row1["input_json"])
        assert input1["target"]["kind"] == "query"
        assert input1["target"]["query"] == "meta-analysis diabetes"

        # Verify second target (URL)
        row2 = await db.fetch_one(
            "SELECT input_json FROM jobs WHERE id = ?",
            (result["target_ids"][1],),
        )
        assert row2 is not None
        input2 = json.loads(row2["input_json"])
        assert input2["target"]["kind"] == "url"
        assert input2["target"]["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"

        # Verify third target (query)
        row3 = await db.fetch_one(
            "SELECT input_json FROM jobs WHERE id = ?",
            (result["target_ids"][2],),
        )
        assert row3 is not None
        input3 = json.loads(row3["input_json"])
        assert input3["target"]["kind"] == "query"
        assert input3["target"]["query"] == "systematic review insulin"

    @pytest.mark.asyncio
    async def test_queue_multiple_queries(self, test_database: Database) -> None:
        """
        TC-Q-07: Queue multiple search query targets.

        // Given: Valid task
        // When: queue_targets with multiple queries
        // Then: All queued with unique IDs
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q07", "Test task", "exploring"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_q07",
                "targets": [
                    {"kind": "query", "query": "query 1"},
                    {"kind": "query", "query": "query 2"},
                    {"kind": "query", "query": "query 3"},
                ],
            }
        )

        assert result["ok"] is True
        assert result["queued_count"] == 3
        assert len(result["target_ids"]) == 3
        assert len(set(result["target_ids"])) == 3  # All unique

    @pytest.mark.asyncio
    async def test_queue_with_high_priority(self, test_database: Database) -> None:
        """
        TC-Q-05: Queue with priority="high" sets priority=10.

        // Given: Valid task
        // When: queue_targets with priority="high"
        // Then: Job has priority=10
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q05", "Test task", "exploring"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_q05",
                "targets": [{"kind": "query", "query": "high priority query"}],
                "options": {"priority": "high"},
            }
        )

        row = await db.fetch_one(
            "SELECT priority FROM jobs WHERE id = ?",
            (result["target_ids"][0],),
        )
        assert row is not None
        assert row["priority"] == 10

    @pytest.mark.asyncio
    async def test_queue_with_low_priority(self, test_database: Database) -> None:
        """
        TC-Q-06: Queue with priority="low" sets priority=90.

        // Given: Valid task
        // When: queue_targets with priority="low"
        // Then: Job has priority=90
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q06", "Test task", "exploring"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_q06",
                "targets": [{"kind": "query", "query": "low priority query"}],
                "options": {"priority": "low"},
            }
        )

        row = await db.fetch_one(
            "SELECT priority FROM jobs WHERE id = ?",
            (result["target_ids"][0],),
        )
        assert row is not None
        assert row["priority"] == 90


class TestQueueTargetsOptionsPropagation:
    """Wiring/Effect tests for queue_targets options propagation.

    Per test rules: New parameters must have wiring tests that verify
    propagation to downstream components.
    """

    @pytest.mark.asyncio
    async def test_budget_pages_stored_in_input_json(self, test_database: Database) -> None:
        """
        TC-Q-08: options.budget_pages is stored in jobs.input_json.

        // Given: Valid task
        // When: queue_targets with options.budget_pages=5
        // Then: input_json contains {"options": {"budget_pages": 5}}
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q08", "Test task", "exploring"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_q08",
                "targets": [{"kind": "query", "query": "budget test query"}],
                "options": {"budget_pages": 5},
            }
        )

        row = await db.fetch_one(
            "SELECT input_json FROM jobs WHERE id = ?",
            (result["target_ids"][0],),
        )
        assert row is not None

        input_data = json.loads(row["input_json"])
        assert "options" in input_data
        assert input_data["options"].get("budget_pages") == 5

    @pytest.mark.asyncio
    async def test_serp_engines_stored_in_input_json(self, test_database: Database) -> None:
        """
        TC-Q-09: options.serp_engines is stored in jobs.input_json.

        // Given: Valid task
        // When: queue_targets with options.serp_engines=["duckduckgo"]
        // Then: input_json contains {"options": {"serp_engines": ["duckduckgo"]}}
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q09", "Test task", "exploring"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_q09",
                "targets": [{"kind": "query", "query": "engine test query"}],
                "options": {"serp_engines": ["duckduckgo"]},
            }
        )

        row = await db.fetch_one(
            "SELECT input_json FROM jobs WHERE id = ?",
            (result["target_ids"][0],),
        )
        assert row is not None

        input_data = json.loads(row["input_json"])
        assert "options" in input_data
        assert input_data["options"].get("serp_engines") == ["duckduckgo"]


class TestGetStatusQueueField:
    """Tests for get_status queue field."""

    @pytest.mark.asyncio
    async def test_get_status_shows_queue_status(self, test_database: Database) -> None:
        """
        TC-QS-01: get_status shows queued target count.

        // Given: Task with queued targets
        // When: get_status called
        // Then: queue.depth reflects queued count
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_qs01", "Test task", "exploring"),
        )

        # Queue some targets
        now = datetime.now(UTC).isoformat()
        for i in range(3):
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"t_qs01_{i}",
                    "task_qs01",
                    "target_queue",
                    50,
                    "network_client",
                    "queued",
                    json.dumps({"kind": "query", "value": f"query {i}", "options": {}}),
                    now,
                ),
            )

        # Use detail="full" to get queue_items
        result = await _handle_get_status(
            {
                "task_id": "task_qs01",
                "detail": "full",
            }
        )

        assert result["ok"] is True
        # Summary mode has progress.queue, full mode has queue_items
        assert result["progress"]["queue"]["depth"] == 3
        assert result["progress"]["queue"]["running"] == 0
        assert len(result["queue_items"]) == 3

    @pytest.mark.asyncio
    async def test_get_status_wait_zero_returns_immediately(self, test_database: Database) -> None:
        """
        TC-QS-02: get_status with wait=0 returns immediately.

        // Given: Task exists
        // When: get_status with wait=0
        // Then: Returns immediately without waiting
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
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


class TestQueueTargetsToolDefinition:
    """Tests for queue_targets tool definition."""

    def test_queue_targets_in_tools(self) -> None:
        """
        Test that queue_targets is defined in TOOLS list.

        // Given: TOOLS list
        // When: Looking for queue_targets
        // Then: Tool is found with correct schema
        """
        from src.mcp.server import TOOLS

        tool_names = [t.name for t in TOOLS]
        assert "queue_targets" in tool_names

        queue_tool = next(t for t in TOOLS if t.name == "queue_targets")
        assert "task_id" in queue_tool.inputSchema["properties"]
        assert "targets" in queue_tool.inputSchema["properties"]
        assert queue_tool.inputSchema["properties"]["targets"]["minItems"] == 1


class TestQueueTargetsPausedTaskResumption:
    """Tests for queue_targets on paused tasks (resumption flow)."""

    @pytest.mark.asyncio
    async def test_queue_targets_on_paused_task(self, test_database: Database) -> None:
        """
        TC-Q-11: queue_targets on paused task resumes it.

        // Given: Task in 'paused' status
        // When: queue_targets is called
        // Then: Targets queued, task status becomes 'exploring'
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        # Create paused task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q11", "Test task", "paused"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_q11",
                "targets": [{"kind": "query", "query": "resume query"}],
            }
        )

        # Verify targets queued
        assert result["ok"] is True
        assert result["queued_count"] == 1

        # Verify task status updated to exploring
        task = await db.fetch_one(
            "SELECT status FROM tasks WHERE id = ?",
            ("task_q11",),
        )
        assert task is not None
        assert task["status"] == "exploring"

    @pytest.mark.asyncio
    async def test_queue_targets_on_failed_task_rejected(self, test_database: Database) -> None:
        """
        TC-Q-12: queue_targets on failed task is rejected.

        // Given: Task in 'failed' status
        // When: queue_targets is called
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        # Create failed task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q12", "Test task", "failed"),
        )

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_queue_targets(
                {
                    "task_id": "task_q12",
                    "targets": [{"kind": "query", "query": "attempt query"}],
                }
            )

        assert "failed task" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_queue_targets_response_has_task_resumed_flag(
        self, test_database: Database
    ) -> None:
        """
        TC-Q-13: queue_targets response includes task_resumed flag.

        // Given: Paused task
        // When: queue_targets is called
        // Then: Response has task_resumed=True
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        # Create paused task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q13", "Test task", "paused"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_q13",
                "targets": [{"kind": "query", "query": "resume query"}],
            }
        )

        assert result["ok"] is True
        assert result.get("task_resumed") is True


class TestQueueTargetsEngineApiValidation:
    """Tests for serp_engines and academic_apis validation.

    Per plan: Unknown values must be rejected with InvalidParamsError.
    """

    @pytest.mark.asyncio
    async def test_unknown_serp_engine_rejected(self, test_database: Database) -> None:
        """
        TC-Q-14: serp_engines with unknown engine raises InvalidParamsError.

        // Given: Valid task
        // When: queue_targets with options.serp_engines=["scholar"]
        // Then: InvalidParamsError is raised with type and message
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q14", "Test task", "exploring"),
        )

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_queue_targets(
                {
                    "task_id": "task_q14",
                    "targets": [{"kind": "query", "query": "test query"}],
                    "options": {"serp_engines": ["scholar"]},  # 'scholar' is not a SERP engine
                }
            )

        # Verify exception type and message
        error = exc_info.value
        assert "scholar" in str(error)
        assert "serp engine" in str(error).lower()
        assert error.details is not None
        assert error.details.get("param_name") == "options.serp_engines"

    @pytest.mark.asyncio
    async def test_unknown_academic_api_rejected(self, test_database: Database) -> None:
        """
        TC-Q-15: academic_apis with unknown API raises InvalidParamsError.

        // Given: Valid task
        // When: queue_targets with options.academic_apis=["google"]
        // Then: InvalidParamsError is raised with type and message
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q15", "Test task", "exploring"),
        )

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_queue_targets(
                {
                    "task_id": "task_q15",
                    "targets": [{"kind": "query", "query": "test query"}],
                    "options": {"academic_apis": ["google"]},  # 'google' is not an academic API
                }
            )

        # Verify exception type and message
        error = exc_info.value
        assert "google" in str(error)
        assert "academic api" in str(error).lower()
        assert error.details is not None
        assert error.details.get("param_name") == "options.academic_apis"

    @pytest.mark.asyncio
    async def test_empty_serp_engines_rejected(self, test_database: Database) -> None:
        """
        TC-Q-16: serp_engines=[] raises InvalidParamsError.

        // Given: Valid task
        // When: queue_targets with options.serp_engines=[]
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q16", "Test task", "exploring"),
        )

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_queue_targets(
                {
                    "task_id": "task_q16",
                    "targets": [{"kind": "query", "query": "test query"}],
                    "options": {"serp_engines": []},  # Empty array
                }
            )

        error = exc_info.value
        assert "empty" in str(error).lower()
        assert error.details is not None
        assert error.details.get("param_name") == "options.serp_engines"

    @pytest.mark.asyncio
    async def test_empty_academic_apis_rejected(self, test_database: Database) -> None:
        """
        TC-Q-17: academic_apis=[] raises InvalidParamsError.

        // Given: Valid task
        // When: queue_targets with options.academic_apis=[]
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q17", "Test task", "exploring"),
        )

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_queue_targets(
                {
                    "task_id": "task_q17",
                    "targets": [{"kind": "query", "query": "test query"}],
                    "options": {"academic_apis": []},  # Empty array
                }
            )

        error = exc_info.value
        assert "empty" in str(error).lower()
        assert error.details is not None
        assert error.details.get("param_name") == "options.academic_apis"

    @pytest.mark.asyncio
    async def test_valid_academic_apis_stored(self, test_database: Database) -> None:
        """
        TC-Q-18: valid academic_apis are stored in input_json.

        // Given: Valid task
        // When: queue_targets with options.academic_apis=["semantic_scholar"]
        // Then: academic_apis stored in input_json
        """
        from src.mcp.tools.targets import handle_queue_targets as _handle_queue_targets

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_q18", "Test task", "exploring"),
        )

        result = await _handle_queue_targets(
            {
                "task_id": "task_q18",
                "targets": [{"kind": "query", "query": "test query"}],
                "options": {"academic_apis": ["semantic_scholar"]},
            }
        )

        assert result["ok"] is True
        assert result["queued_count"] == 1

        row = await db.fetch_one(
            "SELECT input_json FROM jobs WHERE id = ?",
            (result["target_ids"][0],),
        )
        assert row is not None

        input_data = json.loads(row["input_json"])
        assert input_data["options"].get("academic_apis") == ["semantic_scholar"]
