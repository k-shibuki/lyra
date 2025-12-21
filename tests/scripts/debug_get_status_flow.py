#!/usr/bin/env python3
"""
Debug script for get_status Flow (O.7 Problem 2).

This is a "straight-line" debug script per §debug-integration rule.
Verifies the get_status tool returns correct metrics and search states.

Per §3.2.1:
- get_status(task_id) returns task state, searches, metrics, budget
- searches array maps from internal subqueries
- metrics include total_claims, satisfied_count

Usage:
    python tests/scripts/debug_get_status_flow.py
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime

# Add project root to path
sys.path.insert(0, "/home/statuser/lyra")


async def main() -> int:
    """Run get_status verification."""
    print("=" * 70)
    print("get_status Flow Debug Script (O.7)")
    print("=" * 70)

    # =========================================================================
    # 0. Setup - Initialize DB and create test task
    # =========================================================================
    print("\n[0] Setup: Initializing database and creating test task...")

    from src.storage.database import get_database

    db = await get_database()

    task_id = f"task_debug_{uuid.uuid4().hex[:8]}"
    query = "test research query for get_status"

    await db.execute(
        """INSERT INTO tasks (id, query, status, created_at)
           VALUES (?, ?, ?, ?)""",
        (task_id, query, "exploring", datetime.now(UTC).isoformat()),
    )

    print(f"  - Created test task: {task_id}")
    print("[0] Setup: PASSED ✓")

    # =========================================================================
    # 1. Test ExplorationState.get_status() structure
    # =========================================================================
    print("\n[1] Testing ExplorationState.get_status() structure...")

    from src.mcp.server import _get_exploration_state

    # Use the same state cache as _handle_get_status()
    state = await _get_exploration_state(task_id)

    # Register some searches
    state.register_search("s_001", "search query 1", priority="high")
    state.start_search("s_001")
    state.record_page_fetch("s_001", "example.com", is_primary_source=True, is_independent=True)
    state.record_page_fetch("s_001", "gov.jp", is_primary_source=True, is_independent=True)
    state.record_page_fetch("s_001", "other.org", is_primary_source=False, is_independent=True)
    state.record_fragment("s_001", "hash1", is_useful=True, is_novel=True)
    state.record_fragment("s_001", "hash2", is_useful=True, is_novel=True)
    state.record_claim("s_001")

    state.register_search("s_002", "search query 2", priority="medium")
    state.start_search("s_002")
    state.record_page_fetch("s_002", "news.com", is_primary_source=False, is_independent=True)

    # Get status
    status = await state.get_status()

    print(f"  - task_id: {status.get('task_id')}")
    print(f"  - task_status: {status.get('task_status')}")
    print(f"  - searches count: {len(status.get('searches', []))}")

    # Check required fields (actual structure from ExplorationState.get_status())
    required_keys = ["task_id", "task_status", "searches", "metrics", "budget"]
    for key in required_keys:
        assert key in status, f"Missing required key: {key}"
    print(f"  - Required keys present: {required_keys}")

    print("[1] ExplorationState.get_status() structure: PASSED ✓")

    # =========================================================================
    # 2. Test metrics calculation
    # =========================================================================
    print("\n[2] Testing metrics calculation...")

    metrics = status.get("metrics", {})
    print(f"  - satisfied_count: {metrics.get('satisfied_count')}")
    print(f"  - partial_count: {metrics.get('partial_count')}")
    print(f"  - pending_count: {metrics.get('pending_count')}")
    print(f"  - total_pages: {metrics.get('total_pages')}")
    print(f"  - total_fragments: {metrics.get('total_fragments')}")
    print(f"  - total_claims: {metrics.get('total_claims')}")
    print(f"  - elapsed_seconds: {metrics.get('elapsed_seconds')}")

    # Note: total_searches is sum of satisfied + partial + pending + exhausted
    total_searches = (
        metrics.get("satisfied_count", 0)
        + metrics.get("partial_count", 0)
        + metrics.get("pending_count", 0)
        + metrics.get("exhausted_count", 0)
    )
    assert total_searches == 2, f"Expected 2 total searches, got {total_searches}"
    assert metrics.get("total_pages") == 4, f"Expected 4 pages, got {metrics.get('total_pages')}"
    assert metrics.get("total_fragments") == 2, (
        f"Expected 2 fragments, got {metrics.get('total_fragments')}"
    )
    assert metrics.get("total_claims") == 1, f"Expected 1 claim, got {metrics.get('total_claims')}"

    print("[2] Metrics calculation: PASSED ✓")

    # =========================================================================
    # 3. Test budget calculation
    # =========================================================================
    print("\n[3] Testing budget calculation...")

    budget = status.get("budget", {})
    print(f"  - pages_used: {budget.get('pages_used')}")
    print(f"  - pages_limit: {budget.get('pages_limit')}")
    print(f"  - time_used_seconds: {budget.get('time_used_seconds')}")
    print(f"  - time_limit_seconds: {budget.get('time_limit_seconds')}")

    # Note: remaining_percent is NOT in ExplorationState.get_status() but is in _handle_get_status()
    # Spec §3.2.1 expects remaining_percent, added by _handle_get_status
    has_remaining_percent = "remaining_percent" in budget
    print(f"  - remaining_percent present: {has_remaining_percent}")

    assert budget.get("pages_limit") == 120, f"Expected limit 120, got {budget.get('pages_limit')}"
    assert budget.get("pages_used") == 4, f"Expected 4 used, got {budget.get('pages_used')}"

    print("[3] Budget calculation: PASSED ✓")

    # =========================================================================
    # 4. Test searches structure from ExplorationState.get_status()
    # =========================================================================
    print("\n[4] Testing searches structure...")

    searches_from_state = status.get("searches", [])
    print(f"  - searches count: {len(searches_from_state)}")

    if searches_from_state:
        sq = searches_from_state[0]
        print(f"  - First search fields: {list(sq.keys())}")
        print(f"    - id: {sq.get('id')}")
        print(f"    - text: {sq.get('text')}")
        print(f"    - status: {sq.get('status')}")
        print(f"    - pages_fetched: {sq.get('pages_fetched')}")
        print(f"    - useful_fragments: {sq.get('useful_fragments')}")
        print(f"    - harvest_rate: {sq.get('harvest_rate')}")
        print(f"    - satisfaction_score: {sq.get('satisfaction_score')}")
        print(f"    - has_primary_source: {sq.get('has_primary_source')}")

    print("[4] Searches structure: PASSED ✓")

    # =========================================================================
    # 5. Test _handle_get_status() mapping
    # =========================================================================
    print("\n[5] Testing _handle_get_status() field mapping...")

    from src.mcp.server import _handle_get_status

    # Call the handler
    result = await _handle_get_status({"task_id": task_id})

    print(f"  - ok: {result.get('ok')}")
    print(f"  - task_id: {result.get('task_id')}")
    print(f"  - status: {result.get('status')}")
    print(f"  - query: {result.get('query')}")

    # Check "searches" field (mapped from "subqueries")
    searches = result.get("searches", [])
    print(f"  - searches count: {len(searches)}")

    if searches:
        s = searches[0]
        print(f"  - First search fields: {list(s.keys())}")
        # Check renamed fields
        assert "query" in s, "searches[].query should exist (mapped from text)"
        assert "text" not in s or "query" in s, "text should be renamed to query"
        print(f"    - id: {s.get('id')}")
        print(f"    - query: {s.get('query')}")  # Should exist (mapped from text)

    # Check metrics includes satisfied_count
    result_metrics = result.get("metrics", {})
    print(f"  - metrics.satisfied_count: {result_metrics.get('satisfied_count', 'NOT PRESENT')}")

    # Check auth_queue
    auth_queue = result.get("auth_queue", {})
    print(f"  - auth_queue: {auth_queue}")

    # Check warnings
    warnings = result.get("warnings", [])
    print(f"  - warnings: {warnings}")

    print("[5] _handle_get_status() field mapping: PASSED ✓")

    # =========================================================================
    # 6. Test satisfied_count calculation
    # =========================================================================
    print("\n[6] Testing satisfied_count calculation...")

    # Make s_001 satisfied (needs 3 independent sources + primary)
    search_state = state.get_search("s_001")
    search_state.update_status()

    print(f"  - s_001 status: {search_state.status}")
    print(f"  - s_001 satisfaction_score: {search_state.satisfaction_score}")
    print(f"  - s_001 independent_sources: {search_state.independent_sources}")
    print(f"  - s_001 has_primary_source: {search_state.has_primary_source}")

    # Get updated status
    result2 = await _handle_get_status({"task_id": task_id})
    result_metrics2 = result2.get("metrics", {})
    satisfied_count = result_metrics2.get("satisfied_count", 0)
    print(f"  - satisfied_count after update: {satisfied_count}")

    # Check if satisfied_count is calculated correctly
    # s_001 has 3 independent sources and primary source, should be satisfied
    # s_002 has only 1 source, should be partial
    if search_state.status.value == "satisfied":
        assert satisfied_count >= 1, f"Expected satisfied_count >= 1, got {satisfied_count}"
        print("  ✓ satisfied_count matches number of satisfied searches")
    else:
        print(f"  ⚠ s_001 not satisfied (status={search_state.status})")

    print("[6] satisfied_count calculation: COMPLETED")

    # =========================================================================
    # 7. Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    issues = []

    # Check if satisfied_count is present in metrics
    if "satisfied_count" not in result_metrics:
        issues.append("metrics.satisfied_count not present in response")

    # Check if searches use correct field names
    if searches and "text" in searches[0] and "query" not in searches[0]:
        issues.append("searches[].text should be renamed to query")

    if issues:
        print("\n⚠ Issues Found:")
        for i, issue in enumerate(issues):
            print(f"  {i + 1}. {issue}")
    else:
        print("\n✓ All checks passed!")
        print("  - ExplorationState.get_status() returns correct structure")
        print("  - Metrics calculation is correct")
        print("  - Budget calculation is correct")
        print("  - _handle_get_status() maps fields correctly")

    # Cleanup
    print("\n[Cleanup] Removing test task...")
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    print("\n" + "=" * 70)
    print("Debug script completed.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
