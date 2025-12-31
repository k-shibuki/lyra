#!/usr/bin/env python3
"""
Debug script for DEBUG_E2E_02: Multi-worker environment issues.

This script tests the cancellation mechanism and NoneType defenses
without requiring the MCP server.

Usage:
    timeout 120 uv run python scripts/debug_e2e_02.py

Key hypotheses tested:
- H-C: NoneType defense in get_references/get_citations
- H-E: Cancellation mechanism in _process_citation_graph
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.isolation import isolated_database_path
from src.utils.logging import get_logger

logger = get_logger(__name__)

DEBUG_LOG_PATH = Path("/home/statuser/lyra/.cursor/debug.log")


def log_debug(location: str, message: str, data: dict, hypothesis_id: str = ""):
    """Write debug log entry."""
    with open(DEBUG_LOG_PATH, "a") as f:
        f.write(json.dumps({
            "location": location,
            "message": message,
            "data": data,
            "timestamp": time.time() * 1000,
            "sessionId": "debug-e2e-02",
            "hypothesisId": hypothesis_id,
        }) + "\n")


async def test_nonetype_defense():
    """Test H-C: NoneType defense in Semantic Scholar client."""
    log_debug(
        "debug_e2e_02.py:test_nonetype_defense",
        "Testing NoneType defense",
        {"test": "H-C"},
        "H-C"
    )

    from src.search.apis.semantic_scholar import SemanticScholarClient

    client = SemanticScholarClient()

    try:
        # Test with a paper ID that might return None data
        # This tests the defensive coding we added
        refs = await client.get_references("s2:nonexistent_paper_id_12345")
        log_debug(
            "debug_e2e_02.py:test_nonetype_defense",
            "get_references returned",
            {"refs_count": len(refs), "refs_type": type(refs).__name__},
            "H-C"
        )

        cits = await client.get_citations("s2:nonexistent_paper_id_12345")
        log_debug(
            "debug_e2e_02.py:test_nonetype_defense",
            "get_citations returned",
            {"cits_count": len(cits), "cits_type": type(cits).__name__},
            "H-C"
        )

        print(f"✅ H-C: NoneType defense works - refs={len(refs)}, cits={len(cits)}")
        return True

    except Exception as e:
        log_debug(
            "debug_e2e_02.py:test_nonetype_defense",
            "Exception occurred",
            {"error": str(e), "error_type": type(e).__name__},
            "H-C"
        )
        print(f"❌ H-C: NoneType defense failed - {type(e).__name__}: {e}")
        return False
    finally:
        await client.close()


async def test_cancellation_mechanism():
    """Test H-E: Cancellation mechanism in SearchPipeline."""
    log_debug(
        "debug_e2e_02.py:test_cancellation_mechanism",
        "Testing cancellation mechanism",
        {"test": "H-E"},
        "H-E"
    )

    async with isolated_database_path() as db_path:
        from src.storage.database import close_database, get_database

        # Initialize database
        db = await get_database()

        # Create a test task
        task_id = f"test_cancel_{int(time.time())}"
        await db.execute(
            """
            INSERT INTO tasks (id, query, status, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (task_id, "Test cancellation mechanism", "exploring"),
        )

        log_debug(
            "debug_e2e_02.py:test_cancellation_mechanism",
            "Created test task",
            {"task_id": task_id},
            "H-E"
        )

        # Create ExplorationState
        from src.research.state import ExplorationState, TaskStatus

        state = ExplorationState(task_id=task_id)

        # Set task status to COMPLETED (simulating stop_task)
        state.set_task_status(TaskStatus.COMPLETED)

        log_debug(
            "debug_e2e_02.py:test_cancellation_mechanism",
            "Set task status to COMPLETED",
            {"task_id": task_id, "status": str(state._task_status)},
            "H-E"
        )

        # Check if the status check in _process_citation_graph would work
        status_check_passed = state._task_status.value in ("completed", "failed")

        log_debug(
            "debug_e2e_02.py:test_cancellation_mechanism",
            "Status check result",
            {"would_exit_early": status_check_passed, "status_value": state._task_status.value},
            "H-E"
        )

        if status_check_passed:
            print(f"✅ H-E: Cancellation status check works - status={state._task_status.value}")
        else:
            print(f"❌ H-E: Cancellation status check failed - status={state._task_status.value}")

        await close_database()
        return status_check_passed


async def test_rate_limiter_sharing():
    """Test H-A: Rate limiter is shared between calls."""
    log_debug(
        "debug_e2e_02.py:test_rate_limiter_sharing",
        "Testing rate limiter sharing",
        {"test": "H-A"},
        "H-A"
    )

    from src.search.apis.rate_limiter import get_academic_rate_limiter

    # Get rate limiter twice - should be the same instance
    limiter1 = get_academic_rate_limiter()
    limiter2 = get_academic_rate_limiter()

    is_same = limiter1 is limiter2

    log_debug(
        "debug_e2e_02.py:test_rate_limiter_sharing",
        "Rate limiter singleton check",
        {"is_same_instance": is_same, "id1": id(limiter1), "id2": id(limiter2)},
        "H-A"
    )

    if is_same:
        print(f"✅ H-A: Rate limiter is a singleton (id={id(limiter1)})")
    else:
        print("❌ H-A: Rate limiter is NOT a singleton")

    return is_same


async def main():
    """Run all debug tests."""
    print("=" * 60)
    print("DEBUG_E2E_02: Multi-worker environment issues")
    print("=" * 60)
    print()

    # Clear debug log
    DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DEBUG_LOG_PATH.exists():
        DEBUG_LOG_PATH.write_text("")

    log_debug(
        "debug_e2e_02.py:main",
        "Starting debug tests",
        {"tests": ["H-A", "H-C", "H-E"]},
        "ALL"
    )

    results = {}

    # Test H-A: Rate limiter sharing
    print("\n[H-A] Testing rate limiter sharing...")
    results["H-A"] = await test_rate_limiter_sharing()

    # Test H-C: NoneType defense
    print("\n[H-C] Testing NoneType defense...")
    results["H-C"] = await test_nonetype_defense()

    # Test H-E: Cancellation mechanism
    print("\n[H-E] Testing cancellation mechanism...")
    results["H-E"] = await test_cancellation_mechanism()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for hypothesis, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {hypothesis}: {status}")

    all_passed = all(results.values())

    log_debug(
        "debug_e2e_02.py:main",
        "Debug tests completed",
        {"results": results, "all_passed": all_passed},
        "ALL"
    )

    print()
    print(f"Debug log written to: {DEBUG_LOG_PATH}")
    print()

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)





