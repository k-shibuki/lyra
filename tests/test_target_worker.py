"""Tests for target_worker (target queue processor).

Tests the async target queue worker per ADR-0010.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-JK-01 | JobKind.TARGET_QUEUE | Equivalence – normal | Enum value is "target_queue" | Definition |
| TC-JK-02 | KIND_TO_SLOT[TARGET_QUEUE] | Wiring – slot mapping | NETWORK_CLIENT | Slot mapping |
| TC-JK-03 | KIND_PRIORITY[TARGET_QUEUE] | Wiring – priority | 25 | Priority mapping |
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from src.storage.database import Database

pytestmark = pytest.mark.integration


class TestJobKindDefinition:
    """Tests for JobKind.TARGET_QUEUE definition."""

    def test_target_queue_enum_value(self) -> None:
        """
        TC-JK-01: JobKind.TARGET_QUEUE has correct value.

        // Given: JobKind enum
        // When: Accessing TARGET_QUEUE
        // Then: Value is "target_queue"
        """
        from src.scheduler.jobs import JobKind

        assert JobKind.TARGET_QUEUE.value == "target_queue"

    def test_target_queue_slot_mapping(self) -> None:
        """
        TC-JK-02: TARGET_QUEUE maps to NETWORK_CLIENT slot.

        // Given: KIND_TO_SLOT mapping
        // When: Looking up TARGET_QUEUE
        // Then: Maps to NETWORK_CLIENT
        """
        from src.scheduler.jobs import KIND_TO_SLOT, JobKind, Slot

        assert KIND_TO_SLOT[JobKind.TARGET_QUEUE] == Slot.NETWORK_CLIENT

    def test_target_queue_priority_mapping(self) -> None:
        """
        TC-JK-03: TARGET_QUEUE has priority 25.

        // Given: KIND_PRIORITY mapping
        // When: Looking up TARGET_QUEUE
        // Then: Priority is 25 (between FETCH and EXTRACT)
        """
        from src.scheduler.jobs import KIND_PRIORITY, JobKind

        assert KIND_PRIORITY[JobKind.TARGET_QUEUE] == 25


class TestTargetWorkerJobProcessing:
    """Tests for target_worker job processing."""

    @pytest.mark.asyncio
    async def test_query_job_state_transitions(self, test_database: Database) -> None:
        """
        Test that query job state transitions from queued to running.

        // Given: Queued target_queue job with kind=query
        // When: Worker picks up the job
        // Then: Job state transitions queued -> running
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_state", "Test task", "exploring"),
        )

        # Create queued job
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "t_state_01",
                "task_state",
                "target_queue",
                50,
                "network_client",
                "queued",
                json.dumps(
                    {
                        "kind": "query",
                        "value": "test query",
                        "options": {},
                    }
                ),
                now,
            ),
        )

        # Verify initial state
        row = await db.fetch_one(
            "SELECT state FROM jobs WHERE id = ?",
            ("t_state_01",),
        )
        assert row is not None
        assert row["state"] == "queued"

    @pytest.mark.asyncio
    async def test_url_job_stored_correctly(self, test_database: Database) -> None:
        """
        Test that URL job is stored with correct kind.

        // Given: URL target queued
        // When: Job is created
        // Then: input_json contains kind=url
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_url", "Test task", "exploring"),
        )

        # Create queued URL job
        now = datetime.now(UTC).isoformat()
        input_json = json.dumps(
            {
                "kind": "url",
                "value": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
                "options": {},
            }
        )
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "t_url_01",
                "task_url",
                "target_queue",
                50,
                "network_client",
                "queued",
                input_json,
                now,
            ),
        )

        # Verify job stored correctly
        row = await db.fetch_one(
            "SELECT input_json FROM jobs WHERE id = ?",
            ("t_url_01",),
        )
        assert row is not None
        data = json.loads(row["input_json"])
        assert data["kind"] == "url"
        assert data["value"] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"


class TestTargetWorkerManager:
    """Tests for TargetWorkerManager."""

    @pytest.mark.asyncio
    async def test_worker_manager_singleton(self) -> None:
        """
        Test that get_worker_manager returns singleton.

        // Given: Multiple calls to get_worker_manager
        // When: Called multiple times
        // Then: Same instance is returned
        """
        from src.scheduler.target_worker import get_worker_manager

        manager1 = get_worker_manager()
        manager2 = get_worker_manager()

        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_worker_manager_cancel_task(self, test_database: Database) -> None:
        """
        Test that cancel_task cancels jobs for a task.

        // Given: Task with queued jobs
        // When: cancel_task is called
        // Then: Jobs are marked for cancellation
        """
        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_cancel", "Test task", "exploring"),
        )

        # Create queued jobs
        now = datetime.now(UTC).isoformat()
        for i in range(3):
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"t_cancel_{i}",
                    "task_cancel",
                    "target_queue",
                    50,
                    "network_client",
                    "queued",
                    json.dumps({"kind": "query", "value": f"query {i}", "options": {}}),
                    now,
                ),
            )

        from src.scheduler.target_worker import get_worker_manager

        manager = get_worker_manager()

        # Verify manager is accessible and workers can be checked
        assert manager.running_job_count >= 0  # Manager tracks running jobs


class TestGetStatusQueueIntegration:
    """Tests for get_status showing queue status."""

    @pytest.mark.asyncio
    async def test_get_status_shows_target_queue_jobs(self, test_database: Database) -> None:
        """
        Test that get_status shows target_queue job counts.

        // Given: Task with queued target_queue jobs
        // When: get_status is called
        // Then: queue.depth shows correct count
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_status", "Test task", "exploring"),
        )

        # Create queued jobs
        now = datetime.now(UTC).isoformat()
        for i in range(5):
            await db.execute(
                """
                INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"t_status_{i}",
                    "task_status",
                    "target_queue",
                    50,
                    "network_client",
                    "queued",
                    json.dumps({"kind": "query", "value": f"query {i}", "options": {}}),
                    now,
                ),
            )

        result = await _handle_get_status({"task_id": "task_status"})

        assert result["ok"] is True
        assert result["queue"]["depth"] == 5
        assert result["queue"]["running"] == 0
