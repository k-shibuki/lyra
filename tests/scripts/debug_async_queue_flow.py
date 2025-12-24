#!/usr/bin/env python3
"""
Debug script for async search queue flow (Phase 3 verification).

This script validates the end-to-end async search queue workflow:
1. Create a task
2. Queue multiple searches via queue_searches
3. Monitor progress via get_status with wait (long polling)
4. Stop task with different modes (graceful/immediate)

Usage:
    ./.venv/bin/python tests/scripts/debug_async_queue_flow.py

This script uses an isolated database to avoid mutating data/lyra.db.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def main() -> None:
    """Run async queue flow verification."""
    from src.storage.isolation import isolated_database_path

    print("=" * 60)
    print("Phase 3: Async Search Queue Flow Verification")
    print("=" * 60)
    print()

    async with isolated_database_path() as db_path:
        print(f"Using isolated database: {db_path}")
        print()

        from src.storage.database import get_database

        db = await get_database()

        # Initialize schema
        await _initialize_schema(db)

        # Run verification steps
        await verify_queue_searches_flow(db)
        await verify_get_status_long_polling(db)
        await verify_stop_task_graceful(db)
        await verify_stop_task_immediate(db)

        print()
        print("=" * 60)
        print("✅ All Phase 3 verifications passed!")
        print("=" * 60)


async def _initialize_schema(db) -> None:
    """Initialize database schema."""
    await db.initialize_schema()
    print("✓ Schema initialized")


async def verify_queue_searches_flow(db) -> None:
    """Verify queue_searches tool flow."""
    print()
    print("--- Verify: queue_searches flow ---")

    from src.mcp.server import _handle_create_task, _handle_queue_searches

    # Create task
    task_result = await _handle_create_task({
        "query": "Test async queue flow",
    })
    task_id = task_result["task_id"]
    print(f"  Created task: {task_id}")

    # Queue searches
    queue_result = await _handle_queue_searches({
        "task_id": task_id,
        "queries": ["query 1", "query 2", "query 3"],
        "options": {"priority": "high"},
    })

    assert queue_result["ok"] is True
    assert queue_result["queued_count"] == 3
    assert len(queue_result["search_ids"]) == 3
    print(f"  Queued {queue_result['queued_count']} searches: {queue_result['search_ids']}")

    # Verify in database
    rows = await db.fetch_all(
        """
        SELECT id, state, priority FROM jobs
        WHERE task_id = ? AND kind = 'search_queue'
        ORDER BY id
        """,
        (task_id,),
    )
    assert len(rows) == 3
    for row in rows:
        assert row["state"] == "queued"
        assert row["priority"] == 10  # high priority
    print("  ✓ All jobs correctly queued with high priority (10)")


async def verify_get_status_long_polling(db) -> None:
    """Verify get_status with wait parameter (long polling)."""
    print()
    print("--- Verify: get_status long polling ---")

    from src.mcp.server import _handle_create_task, _handle_get_status, _handle_queue_searches

    # Create task with queued searches
    task_result = await _handle_create_task({
        "query": "Test long polling",
    })
    task_id = task_result["task_id"]

    await _handle_queue_searches({
        "task_id": task_id,
        "queries": ["polling test"],
    })

    # Test immediate return (wait=0)
    import time

    start = time.time()
    status = await _handle_get_status({
        "task_id": task_id,
        "wait": 0,
    })
    elapsed = time.time() - start

    assert status["ok"] is True
    assert "queue" in status
    assert status["queue"]["depth"] == 1
    assert elapsed < 0.5
    print(f"  wait=0 returned in {elapsed:.3f}s (< 0.5s)")

    # Test short wait with timeout (wait=1, no change expected)
    start = time.time()
    status = await _handle_get_status({
        "task_id": task_id,
        "wait": 1,
    })
    elapsed = time.time() - start

    # Should wait approximately 1 second then return
    assert 0.9 < elapsed < 1.5
    print(f"  wait=1 returned in {elapsed:.3f}s (~1s timeout)")
    print("  ✓ Long polling behaves correctly")


async def verify_stop_task_graceful(db) -> None:
    """Verify stop_task with mode=graceful."""
    print()
    print("--- Verify: stop_task mode=graceful ---")

    from src.mcp.server import _handle_create_task, _handle_queue_searches, _handle_stop_task

    # Create task with queued and "running" jobs
    task_result = await _handle_create_task({
        "query": "Test graceful stop",
    })
    task_id = task_result["task_id"]

    # Queue a job
    await _handle_queue_searches({
        "task_id": task_id,
        "queries": ["graceful test"],
    })

    # Manually set one job to running (simulating worker picked it up)
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "s_graceful_running",
            task_id,
            "search_queue",
            50,
            "network_client",
            "running",
            json.dumps({"query": "running job", "options": {}}),
            now,
            now,
        ),
    )

    # Stop with graceful mode
    stop_result = await _handle_stop_task({
        "task_id": task_id,
        "mode": "graceful",
    })

    assert stop_result["ok"] is True
    assert stop_result["mode"] == "graceful"
    print(f"  stop_task returned: mode={stop_result['mode']}")

    # Verify: queued job should be cancelled
    rows = await db.fetch_all(
        """
        SELECT id, state FROM jobs
        WHERE task_id = ? AND kind = 'search_queue'
        ORDER BY id
        """,
        (task_id,),
    )

    queued_cancelled = sum(1 for r in rows if r["state"] == "cancelled" and r["id"] != "s_graceful_running")
    running_preserved = sum(1 for r in rows if r["state"] == "running")

    assert queued_cancelled >= 1
    assert running_preserved == 1
    print(f"  Queued cancelled: {queued_cancelled}, Running preserved: {running_preserved}")
    print("  ✓ Graceful mode cancels queued but preserves running")


async def verify_stop_task_immediate(db) -> None:
    """Verify stop_task with mode=immediate."""
    print()
    print("--- Verify: stop_task mode=immediate ---")

    from src.mcp.server import _handle_create_task, _handle_queue_searches, _handle_stop_task

    # Create task with queued and "running" jobs
    task_result = await _handle_create_task({
        "query": "Test immediate stop",
    })
    task_id = task_result["task_id"]

    # Queue a job
    await _handle_queue_searches({
        "task_id": task_id,
        "queries": ["immediate test"],
    })

    # Manually set one job to running
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO jobs (id, task_id, kind, priority, slot, state, input_json, queued_at, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "s_immediate_running",
            task_id,
            "search_queue",
            50,
            "network_client",
            "running",
            json.dumps({"query": "running job", "options": {}}),
            now,
            now,
        ),
    )

    # Stop with immediate mode
    stop_result = await _handle_stop_task({
        "task_id": task_id,
        "mode": "immediate",
    })

    assert stop_result["ok"] is True
    assert stop_result["mode"] == "immediate"
    print(f"  stop_task returned: mode={stop_result['mode']}")

    # Verify: ALL jobs should be cancelled (including running)
    rows = await db.fetch_all(
        """
        SELECT id, state FROM jobs
        WHERE task_id = ? AND kind = 'search_queue'
        """,
        (task_id,),
    )

    all_cancelled = all(r["state"] == "cancelled" for r in rows)
    assert all_cancelled
    print(f"  All {len(rows)} jobs cancelled")
    print("  ✓ Immediate mode cancels ALL jobs including running")


if __name__ == "__main__":
    asyncio.run(main())

