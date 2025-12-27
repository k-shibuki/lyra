#!/usr/bin/env python3
"""
Debug script to verify SERP cache hit query insertion fix.

Tests directly on the production database to verify cache hit behavior.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["LYRA_ENV"] = "development"


async def main():
    """Test SERP cache hit query insertion."""
    from src.storage.database import get_database

    db = await get_database()

    # Create a unique test task
    import uuid
    task_id = f"task_cachetest_{uuid.uuid4().hex[:8]}"
    test_query = "DPP-4 inhibitors efficacy meta-analysis"  # Same as previous E2E

    print(f"Task ID: {task_id}")
    print(f"Test Query: {test_query}")

    # Create test task
    await db.execute(
        """
        INSERT INTO tasks (id, query, status, created_at)
        VALUES (?, ?, 'active', datetime('now'))
        """,
        (task_id, f"Cache hit test: {test_query}"),
    )
    print(f"✓ Created test task: {task_id}")

    # Generate cache key using the same algorithm as search_api
    import hashlib
    def _normalize_query(q: str) -> str:
        return " ".join(q.lower().split())
    
    def _get_cache_key(query: str, engines: list[str] | None, time_range: str, serp_max_pages: int = 1) -> str:
        key_parts = [
            _normalize_query(query),
            ",".join(sorted(engines)) if engines else "default",
            time_range or "all",
            f"serp_max_pages={serp_max_pages}",
        ]
        key_str = "|".join(key_parts)
        return hashlib.sha256(key_str.encode()).hexdigest()[:32]
    
    expected_cache_key = _get_cache_key(test_query, ["mojeek"], "all", 1)
    print(f"Expected cache key: {expected_cache_key}")
    
    # Check if cache exists for this query
    cached = await db.fetch_one(
        """
        SELECT cache_key, query_normalized, hit_count, expires_at 
        FROM cache_serp 
        WHERE cache_key = ?
        """,
        (expected_cache_key,),
    )

    if cached:
        print(f"\n✓ Found existing cache entry:")
        print(f"   cache_key: {cached['cache_key'][:50]}...")
        print(f"   hit_count: {cached['hit_count']}")
        print(f"   expires_at: {cached['expires_at']}")
    else:
        print(f"\n⚠️ No cache entry found for query pattern: {cache_key_pattern}")
        print("   Creating a cache entry manually...")
        
        # Get any existing serp results to use as cache
        existing_serp = await db.fetch_all(
            """
            SELECT si.* FROM serp_items si
            JOIN queries q ON si.query_id = q.id
            WHERE q.query_text LIKE ?
            LIMIT 5
            """,
            (f"%{test_query[:30]}%",),
        )
        
        if existing_serp:
            fake_results = [
                {
                    "engine": row["engine"],
                    "rank": row["rank"],
                    "url": row["url"],
                    "title": row["title"],
                    "snippet": row["snippet"],
                    "source_tag": row["source_tag"],
                    "page_number": row.get("page_number", 1),
                }
                for row in existing_serp
            ]
        else:
            fake_results = [
                {
                    "engine": "mojeek",
                    "rank": 1,
                    "url": "https://example.com/dpp4",
                    "title": "DPP-4 Inhibitors Meta-Analysis",
                    "snippet": "A systematic review...",
                    "source_tag": "serp_web",
                    "page_number": 1,
                }
            ]
        
        # Use same cache key algorithm
        await db.execute(
            """
            INSERT OR REPLACE INTO cache_serp (cache_key, query_normalized, engines_json, result_json, expires_at, hit_count)
            VALUES (?, ?, ?, ?, datetime('now', '+1 hour'), 0)
            """,
            (expected_cache_key, _normalize_query(test_query), '["mojeek"]', json.dumps(fake_results)),
        )
        print(f"   ✓ Created cache entry with key: {expected_cache_key}")

    # Count queries before
    row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM queries WHERE task_id = ?", (task_id,)
    )
    queries_before = row["cnt"] if row else 0
    print(f"\n📊 Queries for task before search: {queries_before}")

    # Clear debug log
    debug_log_path = Path("/home/statuser/lyra/.cursor/debug.log")
    if debug_log_path.exists():
        debug_log_path.write_text("")

    # Execute search - should hit cache and still insert query record
    print("\n🔍 Executing search (expecting cache hit)...")
    from src.search.search_api import search_serp

    try:
        results = await search_serp(
            query=test_query,
            engines=["mojeek"],
            limit=5,
            task_id=task_id,
            use_cache=True,
        )
        print(f"   ✓ Search completed: {len(results)} results")
    except Exception as e:
        print(f"   ✗ Search failed: {e}")
        results = []

    # Count queries after
    row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM queries WHERE task_id = ?", (task_id,)
    )
    queries_after = row["cnt"] if row else 0
    print(f"\n📊 Queries for task after search: {queries_after}")

    # Check serp_items
    row = await db.fetch_one(
        """
        SELECT COUNT(*) as cnt FROM serp_items 
        WHERE query_id IN (SELECT id FROM queries WHERE task_id = ?)
        """,
        (task_id,),
    )
    serp_items_count = row["cnt"] if row else 0
    print(f"📊 SERP items for task: {serp_items_count}")

    # Check debug log for cache hit instrumentation
    print("\n📋 Debug log analysis:")
    if debug_log_path.exists():
        content = debug_log_path.read_text()
        if content.strip():
            for line in content.strip().split("\n"):
                try:
                    log_entry = json.loads(line)
                    if "cache_hit" in log_entry.get("location", ""):
                        print(f"   ✓ Cache hit log: {log_entry.get('message')}")
                        print(f"     data: {log_entry.get('data')}")
                except json.JSONDecodeError:
                    pass
        else:
            print("   (empty)")
    else:
        print("   (file not found)")

    # Summary
    print("\n" + "=" * 60)
    print("VERIFICATION RESULT")
    print("=" * 60)
    
    if queries_after > queries_before:
        print(f"✅ SUCCESS: Query record inserted!")
        print(f"   Queries: {queries_before} → {queries_after}")
        print(f"   SERP items: {serp_items_count}")
    else:
        print(f"❌ FAILED: No query record inserted on cache hit")
        print(f"   Queries: {queries_before} → {queries_after}")
        
        # Check if cache was actually hit
        row = await db.fetch_one(
            "SELECT hit_count FROM cache_serp WHERE cache_key = ?",
            (expected_cache_key,),
        )
        if row:
            print(f"   Cache hit_count: {row['hit_count']}")
        else:
            print("   ⚠️ Cache key mismatch - cache not found")

    # Cleanup test task
    print("\n🧹 Cleaning up test task...")
    await db.execute("DELETE FROM serp_items WHERE query_id IN (SELECT id FROM queries WHERE task_id = ?)", (task_id,))
    await db.execute("DELETE FROM queries WHERE task_id = ?", (task_id,))
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    print("   ✓ Test task cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
