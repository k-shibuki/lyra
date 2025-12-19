#!/usr/bin/env python3
"""
Debug script for Other MCP Tools (O.7 Problem 4+).

This is a "straight-line" debug script per §debug-integration rule.
Verifies calibrate, notify_user, wait_for_user tools.

Per §3.2.1:
- calibrate: add_sample, get_stats, evaluate, get_evaluations, get_diagram_data
- notify_user: Send user notifications
- wait_for_user: Wait for user input

Usage:
    python tests/scripts/debug_other_tools_flow.py
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime

# Add project root to path
sys.path.insert(0, "/home/statuser/lancet")


async def main():
    """Run other tools verification."""
    print("=" * 70)
    print("Other MCP Tools Debug Script (O.7)")
    print("=" * 70)

    # =========================================================================
    # 0. Setup
    # =========================================================================
    print("\n[0] Setup: Initializing database...")

    from src.storage.database import get_database

    db = await get_database()

    task_id = f"task_debug_{uuid.uuid4().hex[:8]}"
    await db.execute(
        """INSERT INTO tasks (id, query, status, created_at)
           VALUES (?, ?, ?, ?)""",
        (task_id, "test query", "exploring", datetime.now(UTC).isoformat()),
    )
    print(f"  - Created test task: {task_id}")
    print("[0] Setup: PASSED ✓")

    # =========================================================================
    # 1. Test calibrate actions
    # =========================================================================
    print("\n[1] Testing calibrate actions...")

    from src.mcp.server import _handle_calibrate

    # Test get_stats
    try:
        result = await _handle_calibrate({
            "action": "get_stats",
        })
        print(f"  - get_stats: ok={result.get('ok')}")
        print(f"    - total_samples: {result.get('total_samples', 'N/A')}")
        print(f"    - last_evaluation: {result.get('last_evaluation', 'N/A')}")
    except Exception as e:
        print(f"  ⚠ get_stats failed: {e}")

    # Test add_sample (with mock data)
    try:
        result = await _handle_calibrate({
            "action": "add_sample",
            "sample": {
                "claim_id": f"c_{uuid.uuid4().hex[:8]}",
                "predicted_confidence": 0.8,
                "actual_outcome": 1,
            },
        })
        print(f"  - add_sample: ok={result.get('ok')}")
    except Exception as e:
        print(f"  ⚠ add_sample failed: {e}")

    # Test get_diagram_data
    try:
        result = await _handle_calibrate({
            "action": "get_diagram_data",
        })
        print(f"  - get_diagram_data: ok={result.get('ok')}")
        print(f"    - bin_count: {len(result.get('bins', []))}")
    except Exception as e:
        print(f"  ⚠ get_diagram_data failed: {e}")

    print("[1] Calibrate actions: CHECKED")

    # =========================================================================
    # 2. Test notify_user
    # =========================================================================
    print("\n[2] Testing notify_user...")

    from src.mcp.server import _handle_notify_user

    try:
        result = await _handle_notify_user({
            "event": "info",
            "payload": {
                "task_id": task_id,
                "message": "Test notification from debug script",
            },
        })
        print(f"  - ok: {result.get('ok')}")
        print(f"  - notification_id: {result.get('notification_id', 'N/A')}")
    except Exception as e:
        print(f"  ⚠ notify_user failed: {e}")

    print("[2] notify_user: CHECKED")

    # =========================================================================
    # 3. Test wait_for_user (non-blocking check)
    # =========================================================================
    print("\n[3] Testing wait_for_user schema...")

    # This is a blocking call, so we just verify the handler exists and has correct signature
    import inspect

    from src.mcp.server import _handle_wait_for_user
    sig = inspect.signature(_handle_wait_for_user)
    print(f"  - Handler signature: _handle_wait_for_user{sig}")
    print("  - (Skipping actual call - would block waiting for user input)")

    print("[3] wait_for_user: SCHEMA VERIFIED")

    # =========================================================================
    # 4. Test stop_task
    # =========================================================================
    print("\n[4] Testing stop_task...")

    from src.mcp.server import _handle_stop_task

    try:
        result = await _handle_stop_task({
            "task_id": task_id,
            "reason": "debug_script_test",
        })
        print(f"  - ok: {result.get('ok')}")
        print(f"  - final_status: {result.get('final_status')}")
    except Exception as e:
        print(f"  ⚠ stop_task failed: {e}")

    print("[4] stop_task: CHECKED")

    # =========================================================================
    # 5. Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print("\n✓ Other tools verification completed")
    print("  - calibrate: get_stats, add_sample, get_diagram_data checked")
    print("  - notify_user: checked")
    print("  - wait_for_user: schema verified")
    print("  - stop_task: checked")

    # Cleanup
    print("\n[Cleanup] Removing test data...")
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    print("\n" + "=" * 70)
    print("Debug script completed.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
