#!/usr/bin/env python3
"""
Debug script for metrics calculation testing.
Tests the full search pipeline with ExplorationState to verify metrics are calculated correctly.

Usage:
    timeout 180 uv run python scripts/debug_metrics_test.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.isolation import isolated_database_path


async def main() -> None:
    """Run full pipeline flow for metrics debugging."""
    print("=== Metrics Debug Test ===")
    print("Testing: harvest_rate, primary_source tracking, fragment counting\n")

    # Use isolated database to avoid lock conflicts
    async with isolated_database_path() as db_path:
        print(f"Using isolated DB: {db_path}")

        # Import after path setup (DB path is set by context manager)
        import uuid

        from src.research.pipeline import SearchOptions, SearchPipeline
        from src.research.state import ExplorationState

        # Create task
        task_id = f"test_{uuid.uuid4().hex[:8]}"
        query_text = "DPP-4 inhibitors efficacy test"
        print(f"\n[1] Creating task: {task_id}")

        # Create task record in database first (required for foreign key constraints)
        from src.storage.database import get_database
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

        # Initialize ExplorationState
        state = ExplorationState(task_id=task_id)
        state.original_query = query_text

        # Define search query
        search_query = "DPP-4 inhibitors meta-analysis HbA1c"
        print(f"\n[2] Will execute search: {search_query}")
        print("    (Pipeline will auto-register the search in ExplorationState)")

        # Create pipeline and execute
        print("\n[3] Executing search pipeline...")
        pipeline = SearchPipeline(task_id=task_id, state=state)

        options = SearchOptions(
            budget_pages=10,
            engines=None,  # Use defaults (academic APIs + browser)
            seek_primary=True,
            search_job_id=None,
            worker_id=0,
        )

        try:
            result = await pipeline.execute(query=search_query, options=options)
            print("\n[4] Pipeline execution completed:")
            print(f"    Status: {result.status}")
            print(f"    Pages fetched: {result.pages_fetched}")
            print(f"    Useful fragments: {result.useful_fragments}")
            print(f"    Harvest rate: {result.harvest_rate:.2f}")
            print(f"    Satisfaction score: {result.satisfaction_score:.2f}")
            print(f"    Auth blocked URLs: {result.auth_blocked_urls}")
        except Exception as e:
            print(f"    Pipeline ERROR: {e}")
            import traceback
            traceback.print_exc()

        # Get status from ExplorationState
        print("\n[5] Getting ExplorationState status...")
        try:
            status = await state.get_status()
            metrics = status.get("metrics", {})
            searches = status.get("searches", [])

            print("\n    Task-level metrics:")
            print(f"      total_pages: {metrics.get('total_pages', 0)}")
            print(f"      total_fragments: {metrics.get('total_fragments', 0)}")
            print(f"      total_claims: {metrics.get('total_claims', 0)}")
            print(f"      satisfied_count: {metrics.get('satisfied_count', 0)}")

            print("\n    Search-level metrics:")
            for s in searches:
                print(f"      Search {s.get('id', 'unknown')[:20]}:")
                print(f"        pages_fetched: {s.get('pages_fetched', 0)}")
                print(f"        useful_fragments: {s.get('useful_fragments', 0)}")
                print(f"        harvest_rate: {s.get('harvest_rate', 0.0):.2f}")
                print(f"        has_primary_source: {s.get('has_primary_source', False)}")
                print(f"        satisfaction_score: {s.get('satisfaction_score', 0.0):.2f}")

        except Exception as e:
            print(f"    Status ERROR: {e}")
            import traceback
            traceback.print_exc()

        # Check DB for persisted data
        print("\n[6] Checking persisted data in DB...")
        try:
            from src.storage.database import get_database
            db = await get_database()

            # Count pages
            pages = await db.fetch_all("SELECT COUNT(*) as cnt FROM pages")
            page_count = pages[0]["cnt"] if pages else 0

            # Count fragments
            fragments = await db.fetch_all("SELECT COUNT(*) as cnt FROM fragments")
            fragment_count = fragments[0]["cnt"] if fragments else 0

            # Count claims
            claims = await db.fetch_all("SELECT COUNT(*) as cnt FROM claims")
            claim_count = claims[0]["cnt"] if claims else 0

            print(f"    DB pages: {page_count}")
            print(f"    DB fragments: {fragment_count}")
            print(f"    DB claims: {claim_count}")

            # Sample fragments
            if fragment_count > 0:
                sample_frags = await db.fetch_all(
                    "SELECT id, fragment_type, LENGTH(text_content) as text_len FROM fragments LIMIT 3"
                )
                print("\n    Sample fragments:")
                for frag in sample_frags:
                    print(f"      {frag['id']}: type={frag['fragment_type']}, len={frag['text_len']}")

        except Exception as e:
            print(f"    DB check ERROR: {e}")

        print("\n=== Metrics Debug Test Complete ===")
        print("Check instrumentation logs at: .cursor/debug.log")


if __name__ == "__main__":
    asyncio.run(main())

