#!/usr/bin/env python3
"""Debug script for ADR-0007 CAPTCHA Intervention Requeue Flow.

This script validates the complete integration of:
1. CAPTCHA detection → InterventionQueue registration
2. SearchWorker → awaiting_auth state transition
3. resolve_auth → auto-requeue and circuit breaker reset

Usage:
    ./.venv/bin/python tests/scripts/debug_adr0007_captcha_requeue.py

This script uses an isolated database.
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def main() -> None:
    """Run ADR-0007 CAPTCHA requeue flow verification."""
    print("=" * 60)
    print("ADR-0007 CAPTCHA Intervention Requeue Flow Verification")
    print("=" * 60)

    from src.storage.isolation import isolated_database_path

    async with isolated_database_path() as db_path:
        print(f"\n[Setup] Using isolated database: {db_path}")

        # Initialize database
        from src.storage.database import get_database

        db = await get_database()
        await db.initialize_schema()

        await verify_job_state_awaiting_auth()
        await verify_search_options_propagation()
        await verify_intervention_queue_with_job_id()
        await verify_batch_notification_manager()
        await verify_requeue_on_resolve_auth()
        await verify_get_pending_auth_info()

        print("\n" + "=" * 60)
        print("✓ All verifications passed!")
        print("=" * 60)


async def verify_job_state_awaiting_auth() -> None:
    """Verify JobState.AWAITING_AUTH is available."""
    print("\n--- Verify: JobState.AWAITING_AUTH ---")

    from src.scheduler.jobs import JobState

    assert hasattr(JobState, "AWAITING_AUTH"), "JobState.AWAITING_AUTH should exist"
    assert JobState.AWAITING_AUTH.value == "awaiting_auth"
    print("  ✓ JobState.AWAITING_AUTH exists with value 'awaiting_auth'")


async def verify_search_options_propagation() -> None:
    """Verify SearchOptions has task_id and search_job_id fields."""
    print("\n--- Verify: SearchOptions Job ID Fields ---")

    from src.search.provider import SearchOptions

    options = SearchOptions(
        task_id="test_task",
        search_job_id="test_job",
    )

    assert options.task_id == "test_task", "task_id should be set"
    assert options.search_job_id == "test_job", "search_job_id should be set"
    print("  ✓ SearchOptions accepts task_id and search_job_id")

    # Verify defaults
    default_options = SearchOptions()
    assert default_options.task_id is None
    assert default_options.search_job_id is None
    print("  ✓ SearchOptions defaults to None for job IDs")


async def verify_intervention_queue_with_job_id() -> None:
    """Verify InterventionQueue.enqueue() accepts search_job_id."""
    print("\n--- Verify: InterventionQueue with search_job_id ---")

    from src.utils.notification import InterventionQueue

    queue = InterventionQueue()
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    queue._db = mock_db

    # Mock batch notification manager
    with patch("src.utils.notification._get_batch_notification_manager") as mock_batch:
        mock_batch.return_value.on_captcha_queued = AsyncMock()

        queue_id = await queue.enqueue(
            task_id="task_123",
            url="https://duckduckgo.com/",
            domain="duckduckgo",
            auth_type="captcha",
            search_job_id="job_456",
        )

    assert queue_id.startswith("iq_"), f"Queue ID should start with iq_, got {queue_id}"
    print(f"  ✓ Queue item created: {queue_id}")

    # Verify DB call includes search_job_id
    call_args = mock_db.execute.call_args
    sql = call_args[0][0]
    params = call_args[0][1]
    assert "search_job_id" in sql, "SQL should include search_job_id"
    assert "job_456" in params, "Params should include job_456"
    print("  ✓ DB insert includes search_job_id")


async def verify_batch_notification_manager() -> None:
    """Verify BatchNotificationManager works correctly."""
    print("\n--- Verify: BatchNotificationManager ---")

    from src.utils.notification import BatchNotificationManager

    manager = BatchNotificationManager()

    # Verify initial state
    assert manager._first_pending_time is None
    assert manager._notified is False
    print("  ✓ Initial state: no pending items, not notified")

    # Verify timer starts on first CAPTCHA
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await manager.on_captcha_queued("iq_123", "duckduckgo")

    assert manager._first_pending_time is not None
    assert manager._notification_timer is not None
    print("  ✓ Timer started after on_captcha_queued()")

    # Clean up
    if manager._notification_timer:
        manager._notification_timer.cancel()


async def verify_requeue_on_resolve_auth() -> None:
    """Verify resolve_auth requeues awaiting_auth jobs."""
    print("\n--- Verify: Requeue on resolve_auth ---")

    from src.storage.database import get_database

    db = await get_database()
    task_id = "task_test_requeue"

    # Setup: Create task
    await db.execute(
        "INSERT INTO tasks (id, query, status, created_at) VALUES (?, ?, ?, ?)",
        (task_id, "test query", "running", datetime.now(UTC).isoformat()),
    )

    # Setup: Create job in awaiting_auth state
    job_id = "job_test_requeue"
    await db.execute(
        """
        INSERT INTO jobs (id, task_id, kind, state, slot, input_json, queued_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, task_id, "search_queue", "awaiting_auth", 0, "{}", datetime.now(UTC).isoformat()),
    )

    # Setup: Create completed intervention queue item
    await db.execute(
        """
        INSERT INTO intervention_queue (id, task_id, url, domain, auth_type, status, search_job_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "iq_test_requeue",
            task_id,
            "https://test.com",
            "duckduckgo",
            "captcha",
            "completed",
            job_id,
        ),
    )

    print(f"  Setup: Job {job_id} in awaiting_auth state")

    # Execute: Call _requeue_awaiting_auth_jobs
    from src.mcp.server import _requeue_awaiting_auth_jobs

    count = await _requeue_awaiting_auth_jobs("duckduckgo")

    # Verify
    assert count == 1, f"Expected 1 job requeued, got {count}"
    row = await db.fetch_one("SELECT state FROM jobs WHERE id = ?", (job_id,))
    assert row is not None
    assert row["state"] == "queued", f"Expected state=queued, got {row['state']}"
    print(f"  ✓ Job {job_id} requeued (state=queued)")


async def verify_get_pending_auth_info() -> None:
    """Verify get_status returns pending_auth info."""
    print("\n--- Verify: get_status pending_auth info ---")

    from src.storage.database import get_database

    db = await get_database()
    task_id = "task_test_pending"

    # Setup: Create task
    await db.execute(
        "INSERT INTO tasks (id, query, status, created_at) VALUES (?, ?, ?, ?)",
        (task_id, "test query", "running", datetime.now(UTC).isoformat()),
    )

    # Setup: Create job in awaiting_auth state
    await db.execute(
        """
        INSERT INTO jobs (id, task_id, kind, state, slot, input_json, queued_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "job_pending",
            task_id,
            "search_queue",
            "awaiting_auth",
            0,
            "{}",
            datetime.now(UTC).isoformat(),
        ),
    )

    # Setup: Create pending intervention queue items
    await db.execute(
        """
        INSERT INTO intervention_queue (id, task_id, url, domain, auth_type, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("iq_pending_1", task_id, "https://test.com", "duckduckgo", "captcha", "pending"),
    )
    await db.execute(
        """
        INSERT INTO intervention_queue (id, task_id, url, domain, auth_type, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("iq_pending_2", task_id, "https://test2.com", "google", "turnstile", "pending"),
    )

    # Execute
    from src.mcp.server import _get_pending_auth_info

    result = await _get_pending_auth_info(db, task_id)

    # Verify
    assert result["awaiting_auth_jobs"] == 1, (
        f"Expected 1 awaiting job, got {result['awaiting_auth_jobs']}"
    )
    assert result["pending_captchas"] == 2, (
        f"Expected 2 pending captchas, got {result['pending_captchas']}"
    )
    assert len(result["domains"]) == 2, f"Expected 2 domains, got {len(result['domains'])}"
    print(f"  ✓ pending_auth info: {result}")


if __name__ == "__main__":
    asyncio.run(main())
