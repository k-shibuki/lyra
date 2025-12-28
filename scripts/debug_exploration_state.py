#!/usr/bin/env python3
"""
Debug script for ExplorationState and metrics verification.

Tests that:
1. ExplorationState instances are correctly cached and shared
2. record_fragment/record_claim are called during pipeline execution
3. get_status returns correct metrics

Usage:
    timeout 180 uv run python scripts/debug_exploration_state.py
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


def analyze_logs(entries: list[dict]) -> dict:
    """Analyze debug log entries by hypothesis ID."""
    by_hypothesis: dict[str, list[dict]] = {}

    for entry in entries:
        h_id = entry.get("hypothesisId", "unknown")
        if h_id not in by_hypothesis:
            by_hypothesis[h_id] = []
        by_hypothesis[h_id].append(entry)

    return by_hypothesis


async def main() -> None:
    """Run ExplorationState debug test."""
    print("=" * 60)
    print("ExplorationState Debug Test")
    print("=" * 60)

    # Clear debug log
    clear_debug_log()

    # Use isolated database to avoid lock conflicts
    from src.storage.isolation import isolated_database_path

    async with isolated_database_path() as db_path:
        print(f"\n[1] Using isolated DB: {db_path}")

        # Import after path setup
        import uuid

        from src.research.pipeline import SearchOptions, SearchPipeline
        from src.research.state import ExplorationState
        from src.storage.database import get_database

        # Create task
        task_id = f"debug_{uuid.uuid4().hex[:8]}"
        query_text = "statin cardiovascular prevention test"
        print(f"[2] Creating task: {task_id}")

        # Create task record in database
        db = await get_database()
        await db.insert(
            "tasks",
            {
                "id": task_id,
                "query": query_text,
                "status": "running",
            },
            auto_id=False,
        )
        print("    Task record created in DB")

        # Create ExplorationState
        print("\n[3] Creating ExplorationState...")
        state = ExplorationState(task_id=task_id)
        state.original_query = query_text
        state_id = id(state)
        print(f"    State ID: {state_id}")

        # Execute search
        print("\n[4] Executing search pipeline...")
        pipeline = SearchPipeline(task_id=task_id, state=state)

        options = SearchOptions(
            budget_pages=5,  # Small budget for quick test
            engines=None,
            seek_primary=True,
            search_job_id=None,
            worker_id=0,
        )

        try:
            result = await pipeline.execute(
                query="statin therapy efficacy meta-analysis",
                options=options,
            )
            print("\n[5] Pipeline result:")
            print(f"    Status: {result.status}")
            print(f"    Pages fetched: {result.pages_fetched}")
            print(f"    Useful fragments: {result.useful_fragments}")
            print(f"    Harvest rate: {result.harvest_rate:.2f}")
        except Exception as e:
            print(f"    Pipeline ERROR: {e}")
            import traceback
            traceback.print_exc()

        # Check state metrics
        print("\n[6] Checking ExplorationState metrics...")
        try:
            status = await state.get_status()
            metrics = status.get("metrics", {})
            searches = status.get("searches", [])

            print(f"    State ID after pipeline: {id(state)}")
            print(f"    Same instance: {id(state) == state_id}")
            print("\n    Metrics:")
            print(f"      total_pages: {metrics.get('total_pages', 0)}")
            print(f"      total_fragments: {metrics.get('total_fragments', 0)}")
            print(f"      total_claims: {metrics.get('total_claims', 0)}")
            print(f"      budget_pages_used: {metrics.get('budget_pages_used', 0)}")

            print(f"\n    Searches ({len(searches)}):")
            for s in searches:
                print(f"      - {s.get('id', 'unknown')[:20]}:")
                print(f"        pages_fetched: {s.get('pages_fetched', 0)}")
                print(f"        useful_fragments: {s.get('useful_fragments', 0)}")

        except Exception as e:
            print(f"    Status ERROR: {e}")
            import traceback
            traceback.print_exc()

        # Verify DB persistence
        print("\n[7] Verifying DB persistence...")
        try:
            # Count pages
            pages = await db.fetch_all(
                """
                SELECT COUNT(*) as cnt FROM pages p
                JOIN serp_items si ON p.serp_item_id = si.id
                JOIN queries q ON si.query_id = q.id
                WHERE q.task_id = ?
                """,
                [task_id],
            )
            page_count = pages[0]["cnt"] if pages else 0

            # Count fragments
            fragments = await db.fetch_all(
                """
                SELECT COUNT(*) as cnt FROM fragments f
                JOIN pages p ON f.page_id = p.id
                JOIN serp_items si ON p.serp_item_id = si.id
                JOIN queries q ON si.query_id = q.id
                WHERE q.task_id = ?
                """,
                [task_id],
            )
            fragment_count = fragments[0]["cnt"] if fragments else 0

            print(f"    DB pages for task: {page_count}")
            print(f"    DB fragments for task: {fragment_count}")

        except Exception as e:
            print(f"    DB verification ERROR: {e}")

        # Analyze debug logs
        print("\n[8] Analyzing debug logs...")
        entries = read_debug_log()
        print(f"    Total log entries: {len(entries)}")

        if entries:
            by_hypothesis = analyze_logs(entries)
            print("\n    Entries by hypothesis:")
            for h_id, h_entries in sorted(by_hypothesis.items()):
                print(f"      {h_id}: {len(h_entries)} entries")
                # Show first entry for each hypothesis
                if h_entries:
                    first = h_entries[0]
                    print(f"        First: {first.get('message', 'N/A')}")
                    if "data" in first:
                        print(f"        Data: {json.dumps(first['data'], default=str)[:100]}")
        else:
            print("    No debug log entries found!")
            print("    This means instrumentation is not being executed.")
            print("    Ensure MCP server is restarted to load new code.")

    print("\n" + "=" * 60)
    print("Debug Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

