#!/usr/bin/env python3
"""
Debug script for MCP metrics issue.

Simulates MCP server behavior to test:
1. _get_exploration_state caching with asyncio.Lock
2. Multiple concurrent calls to verify no race condition
3. Metrics calculation from ExplorationState

Usage:
    timeout 180 uv run python scripts/debug_mcp_metrics.py
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

DEBUG_LOG_PATH = Path(__file__).parent.parent / ".cursor" / "debug.log"


def clear_debug_log() -> None:
    """Clear the debug log file."""
    DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_LOG_PATH.write_text("")
    print(f"Cleared debug log: {DEBUG_LOG_PATH}")


def read_debug_log() -> list[dict]:
    """Read and parse debug log entries."""
    if not DEBUG_LOG_PATH.exists():
        return []

    entries = []
    for line in DEBUG_LOG_PATH.read_text().strip().split("\n"):
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


async def simulate_mcp_get_exploration_state(task_id: str) -> object:
    """
    Simulate MCP server's _get_exploration_state with locking.

    This tests the race condition fix (H-F).
    """
    from src.research.state import ExplorationState

    # Simulate the cache and lock from server.py
    if not hasattr(simulate_mcp_get_exploration_state, "_cache"):
        simulate_mcp_get_exploration_state._cache = {}
        simulate_mcp_get_exploration_state._locks = {}
        simulate_mcp_get_exploration_state._global_lock = asyncio.Lock()

    cache = simulate_mcp_get_exploration_state._cache
    locks = simulate_mcp_get_exploration_state._locks
    global_lock = simulate_mcp_get_exploration_state._global_lock

    # Get or create per-task lock
    async with global_lock:
        if task_id not in locks:
            locks[task_id] = asyncio.Lock()
        lock = locks[task_id]

    # Use per-task lock to prevent race condition
    async with lock:
        if task_id not in cache:
            print(f"    Creating new ExplorationState for {task_id}")
            state = ExplorationState(task_id)
            await state.load_state()
            cache[task_id] = state
        else:
            print(f"    Returning cached ExplorationState for {task_id}")

    return cache[task_id]


async def main() -> None:
    """Run MCP metrics debug test."""
    print("=" * 60)
    print("MCP Metrics Debug Test")
    print("=" * 60)

    # Clear debug log
    clear_debug_log()

    # Use isolated database
    from src.storage.isolation import isolated_database_path

    async with isolated_database_path() as db_path:
        print(f"\n[1] Using isolated DB: {db_path}")

        import uuid

        from src.research.pipeline import SearchOptions, SearchPipeline
        from src.storage.database import get_database

        # Create task
        task_id = f"mcp_test_{uuid.uuid4().hex[:8]}"
        query_text = "aspirin cardiovascular prevention"
        print(f"[2] Creating task: {task_id}")

        db = await get_database()
        await db.insert(
            "tasks",
            {"id": task_id, "query": query_text, "status": "running"},
            auto_id=False,
        )

        # Test 1: Concurrent access to ExplorationState
        print("\n[3] Testing concurrent ExplorationState access (H-F fix)...")

        async def get_state_and_check(call_id: int) -> tuple[int, object]:
            state = await simulate_mcp_get_exploration_state(task_id)
            return (call_id, id(state))

        # Launch 5 concurrent calls
        results = await asyncio.gather(*[
            get_state_and_check(i) for i in range(5)
        ])

        state_ids = [r[1] for r in results]
        unique_ids = set(state_ids)

        print("    Concurrent calls: 5")
        print(f"    Unique state IDs: {len(unique_ids)}")
        print(f"    All same instance: {len(unique_ids) == 1}")

        if len(unique_ids) > 1:
            print("    ERROR: Race condition detected! Multiple instances created.")
        else:
            print("    SUCCESS: All calls returned same instance.")

        # Test 2: Execute search and verify metrics
        print("\n[4] Executing search pipeline...")
        state = await simulate_mcp_get_exploration_state(task_id)
        state.original_query = query_text

        pipeline = SearchPipeline(task_id=task_id, state=state)
        options = SearchOptions(
            budget_pages=5,
            engines=None,
            seek_primary=True,
            search_job_id=None,
            worker_id=0,
        )

        try:
            result = await pipeline.execute(
                query="aspirin primary prevention efficacy",
                options=options,
            )
            print(f"    Pipeline completed: {result.status}")
            print(f"    Pages fetched: {result.pages_fetched}")
            print(f"    Useful fragments: {result.useful_fragments}")
        except Exception as e:
            print(f"    Pipeline ERROR: {e}")

        # Test 3: Get metrics from same state instance
        print("\n[5] Getting metrics from ExplorationState...")
        state_after = await simulate_mcp_get_exploration_state(task_id)

        print(f"    State ID before pipeline: {id(state)}")
        print(f"    State ID after get_status: {id(state_after)}")
        print(f"    Same instance: {id(state) == id(state_after)}")

        status = await state_after.get_status()
        metrics = status.get("metrics", {})

        print("\n    Metrics from get_status():")
        print(f"      total_pages: {metrics.get('total_pages', 0)}")
        print(f"      total_fragments: {metrics.get('total_fragments', 0)}")
        print(f"      total_claims: {metrics.get('total_claims', 0)}")
        print(f"      budget_pages_used: {metrics.get('budget_pages_used', 0)}")

        # Verify metrics are non-zero
        if metrics.get("total_fragments", 0) == 0:
            print("\n    WARNING: Metrics are 0!")
            print("    Possible causes:")
            print("      1. Pipeline didn't find any results")
            print("      2. record_fragment not being called")
            print("      3. State instance mismatch")
        else:
            print("\n    SUCCESS: Metrics are populated correctly!")

        # Check debug logs
        print("\n[6] Checking debug logs...")
        entries = read_debug_log()
        print(f"    Total entries: {len(entries)}")

        if entries:
            # Group by location
            by_location: dict[str, int] = {}
            for e in entries:
                loc = e.get("location", "unknown")
                by_location[loc] = by_location.get(loc, 0) + 1

            print("\n    Entries by location:")
            for loc, count in sorted(by_location.items()):
                print(f"      {loc}: {count}")

    print("\n" + "=" * 60)
    print("MCP Metrics Debug Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

