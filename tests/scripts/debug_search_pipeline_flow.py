#!/usr/bin/env python3
"""
Debug script for Search Pipeline Flow (O.7 Problem 1).

This is a "straight-line" debug script per §debug-integration rule.
Verifies the search → fetch → extract → claims pipeline.

Per §3.2.1:
- search(task_id, query, options) executes full pipeline
- Returns claims_found, harvest_rate, satisfaction_score, novelty_score
- DB persistence of claims/fragments/edges

Usage:
    python tests/scripts/debug_search_pipeline_flow.py
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from typing import TypedDict

# Add project root to path
sys.path.insert(0, "/home/statuser/lyra")


async def main() -> int:
    """Run search pipeline verification."""
    print("=" * 70)
    print("Search Pipeline Flow Debug Script (O.7)")
    print("=" * 70)

    # =========================================================================
    # 0. Setup - Initialize DB and create test task
    # =========================================================================
    print("\n[0] Setup: Initializing database and creating test task...")

    from src.storage.database import get_database

    db = await get_database()

    task_id = f"task_debug_{uuid.uuid4().hex[:8]}"
    query = "test search query"

    await db.execute(
        """INSERT INTO tasks (id, query, status, created_at)
           VALUES (?, ?, ?, ?)""",
        (task_id, query, "created", datetime.now(UTC).isoformat()),
    )

    print(f"  - Created test task: {task_id}")
    print("[0] Setup: PASSED ✓")

    # =========================================================================
    # 1. Test SearchResult dataclass
    # =========================================================================
    print("\n[1] Testing SearchResult dataclass...")

    from src.research.pipeline import SearchResult

    result = SearchResult(
        search_id="s_test001",
        query="test query",
        status="running",
        pages_fetched=0,
        useful_fragments=0,
        harvest_rate=0.0,
        claims_found=[],
        satisfaction_score=0.0,
        novelty_score=1.0,
        budget_remaining={"pages": 120, "percent": 100},
    )

    result_dict = result.to_dict()
    print(f"  - search_id: {result_dict.get('search_id')}")
    print(f"  - status: {result_dict.get('status')}")
    print(f"  - ok: {result_dict.get('ok')}")

    assert result_dict.get("ok") is True
    assert result_dict.get("search_id") == "s_test001"
    assert "claims_found" in result_dict

    print("[1] SearchResult dataclass: PASSED ✓")

    # =========================================================================
    # 2. Test ExplorationState initialization
    # =========================================================================
    print("\n[2] Testing ExplorationState initialization...")

    from src.research.state import ExplorationState

    state = ExplorationState(task_id=task_id)
    await state.load_state()
    print(f"  - task_id: {state.task_id}")

    # Check if original_query attribute exists (it should NOT - this is a bug)
    has_original_query = hasattr(state, "original_query")
    print(f"  - has original_query attr: {has_original_query}")
    if not has_original_query:
        print("  ⚠ WARNING: ExplorationState lacks original_query attribute")
        print("  ⚠ But executor.py:475 uses self.state.original_query")
        print("  ⚠ This will cause AttributeError at runtime")

    status = await state.get_status()
    print(f"  - budget.pages_limit: {status['budget']['pages_limit']}")
    print(f"  - budget.pages_used: {status['budget']['pages_used']}")

    assert status["budget"]["pages_limit"] == 120
    assert status["budget"]["pages_used"] == 0

    print("[2] ExplorationState initialization: PASSED ✓")

    # =========================================================================
    # 3. Test SearchExecutor query expansion
    # =========================================================================
    print("\n[3] Testing SearchExecutor query expansion...")

    from src.research.executor import SearchExecutor

    executor = SearchExecutor(task_id=task_id, state=state)

    test_query = "FDA drug safety report"
    expanded = executor._expand_query(test_query)

    print(f"  - Original query: {test_query}")
    print(f"  - Expanded queries ({len(expanded)}):")
    for i, eq in enumerate(expanded):
        print(f"    {i + 1}. {eq}")

    assert len(expanded) >= 1
    assert test_query in expanded

    print("[3] SearchExecutor query expansion: PASSED ✓")

    # =========================================================================
    # 4. Test claims_found format transformation
    # =========================================================================
    print("\n[4] Testing claims_found format transformation...")

    from src.research.pipeline import SearchPipeline

    pipeline = SearchPipeline(task_id=task_id, state=state)

    # Simulate raw claims from executor
    class RawClaim(TypedDict, total=False):
        source_url: str
        title: str
        claim: str
        snippet: str
        confidence: float

    class TransformedClaim(TypedDict):
        id: str
        text: str
        confidence: float
        source_url: str
        is_primary_source: bool

    raw_claims: list[RawClaim] = [
        {
            "source_url": "https://www.fda.gov/safety/report",
            "title": "FDA Safety Report",
            "claim": "Drug X has been associated with adverse events.",
            "confidence": 0.85,
        },
        {
            "source_url": "https://example.com/article",
            "title": "News Article",
            "snippet": "Recent studies suggest potential risks.",
            # No 'claim' field - secondary source
        },
    ]

    transformed_claims: list[TransformedClaim] = []
    for claim in raw_claims:
        text = claim["claim"] if "claim" in claim else (claim["snippet"] if "snippet" in claim else "")
        source_url = claim["source_url"] if "source_url" in claim else ""
        confidence = claim["confidence"] if "confidence" in claim else 0.5
        transformed_claims.append(
            {
                "id": f"c_{uuid.uuid4().hex[:8]}",
                "text": text[:200],
                "confidence": confidence,
                "source_url": source_url,
                "is_primary_source": pipeline._is_primary_source(source_url),
            }
        )

    print(f"  - Raw claims count: {len(raw_claims)}")
    print(f"  - Transformed claims count: {len(transformed_claims)}")

    for i, tc in enumerate(transformed_claims):
        print(f"  - Claim {i + 1}:")
        print(f"      id: {tc['id']}")
        print(f"      text: {tc['text'][:50]}...")
        print(f"      confidence: {tc['confidence']}")
        print(f"      is_primary_source: {tc['is_primary_source']}")

    # FDA source should be primary
    assert transformed_claims[0]["is_primary_source"] is True
    # example.com should not be primary
    assert transformed_claims[1]["is_primary_source"] is False

    print("[4] claims_found format transformation: PASSED ✓")

    # =========================================================================
    # 5. Check DB schema for claims/fragments/edges tables
    # =========================================================================
    print("\n[5] Checking DB schema for claims/fragments/edges tables...")

    # Check claims table exists
    claims_schema = await db.fetch_one(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='claims'"
    )
    if claims_schema:
        print("  - claims table: EXISTS ✓")
    else:
        print("  - claims table: MISSING ✗")

    # Check fragments table exists
    fragments_schema = await db.fetch_one(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='fragments'"
    )
    if fragments_schema:
        print("  - fragments table: EXISTS ✓")
    else:
        print("  - fragments table: MISSING ✗")

    # Check edges table exists
    edges_schema = await db.fetch_one(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='edges'"
    )
    if edges_schema:
        print("  - edges table: EXISTS ✓")
    else:
        print("  - edges table: MISSING ✗")

    assert claims_schema is not None, "claims table should exist"
    assert fragments_schema is not None, "fragments table should exist"
    assert edges_schema is not None, "edges table should exist"

    print("[5] DB schema check: PASSED ✓")

    # =========================================================================
    # 6. Check DB persistence in executor (analysis)
    # =========================================================================
    print("\n[6] Analyzing DB persistence in SearchExecutor...")

    import inspect

    from src.research.executor import SearchExecutor

    # Check for _persist_claim and _persist_fragment helper methods
    has_persist_claim = hasattr(SearchExecutor, "_persist_claim")
    has_persist_fragment = hasattr(SearchExecutor, "_persist_fragment")

    print(f"  - _persist_claim method: {'EXISTS ✓' if has_persist_claim else 'MISSING ✗'}")
    print(f"  - _persist_fragment method: {'EXISTS ✓' if has_persist_fragment else 'MISSING ✗'}")

    # Check helper method sources
    if has_persist_claim:
        persist_claim_source = inspect.getsource(SearchExecutor._persist_claim)
        claims_insert = "INSERT" in persist_claim_source and "claims" in persist_claim_source
        edges_insert = "INSERT" in persist_claim_source and "edges" in persist_claim_source
        print(f"  - _persist_claim has claims INSERT: {'YES ✓' if claims_insert else 'NO ⚠'}")
        print(f"  - _persist_claim has edges INSERT: {'YES ✓' if edges_insert else 'NO ⚠'}")
    else:
        claims_insert = False
        edges_insert = False

    if has_persist_fragment:
        persist_fragment_source = inspect.getsource(SearchExecutor._persist_fragment)
        fragments_insert = (
            "INSERT" in persist_fragment_source and "fragments" in persist_fragment_source
        )
        print(
            f"  - _persist_fragment has fragments INSERT: {'YES ✓' if fragments_insert else 'NO ⚠'}"
        )
    else:
        fragments_insert = False

    # Check _fetch_and_extract calls the helper methods
    fetch_extract_source = inspect.getsource(SearchExecutor._fetch_and_extract)
    calls_persist_claim = "_persist_claim" in fetch_extract_source
    calls_persist_fragment = "_persist_fragment" in fetch_extract_source

    print(
        f"  - _fetch_and_extract calls _persist_claim: {'YES ✓' if calls_persist_claim else 'NO ⚠'}"
    )
    print(
        f"  - _fetch_and_extract calls _persist_fragment: {'YES ✓' if calls_persist_fragment else 'NO ⚠'}"
    )

    print("\n  *** Analysis Result ***")
    if (
        has_persist_claim
        and has_persist_fragment
        and calls_persist_claim
        and calls_persist_fragment
    ):
        print("  ✓ DB persistence methods exist and are called")
    else:
        print("  ⚠ WARNING: DB persistence may not be working")

    print("[6] DB persistence analysis: COMPLETED")

    # =========================================================================
    # 7. Test state.record_* methods
    # =========================================================================
    print("\n[7] Testing state.record_* methods...")

    search_id = "s_test_debug"
    state.register_search(
        search_id=search_id,
        text="debug search",
        priority="medium",
    )
    state.start_search(search_id)

    # Record page fetch
    state.record_page_fetch(
        search_id=search_id,
        domain="example.com",
        is_primary_source=False,
        is_independent=True,
    )

    # Record fragment
    state.record_fragment(
        search_id=search_id,
        fragment_hash="test_hash_123",
        is_useful=True,
        is_novel=True,
    )

    # Record claim
    state.record_claim(search_id=search_id)

    # Check state
    search_state = state.get_search(search_id)
    assert search_state is not None
    print(f"  - pages_fetched: {search_state.pages_fetched}")
    print(f"  - useful_fragments: {search_state.useful_fragments}")
    print(f"  - harvest_rate: {search_state.harvest_rate:.2f}")
    print(f"  - independent_sources: {search_state.independent_sources}")

    # Note: total_claims is tracked on ExplorationState, not SearchState
    overall_status = await state.get_status()
    total_claims = overall_status.get("metrics", {}).get("total_claims", 0)
    print(f"  - total_claims (from ExplorationState): {total_claims}")

    assert search_state.pages_fetched == 1
    assert search_state.useful_fragments == 1
    assert total_claims == 1

    print("[7] state.record_* methods: PASSED ✓")

    # =========================================================================
    # 8. Check if claims are written to DB by record_claim
    # =========================================================================
    print("\n[8] Checking if record_claim writes to DB...")

    # Query claims table for our task
    claims_in_db = await db.fetch_all(
        "SELECT * FROM claims WHERE task_id = ?",
        (task_id,),
    )

    print(f"  - Claims in DB for task {task_id}: {len(claims_in_db)}")

    if len(claims_in_db) == 0:
        print("  ⚠ WARNING: No claims found in DB")
        print("  ⚠ record_claim() only updates counter, not DB")
    else:
        print(f"  - First claim: {dict(claims_in_db[0]) if claims_in_db else 'N/A'}")

    print("[8] DB claims check: COMPLETED")

    # =========================================================================
    # 9. Test llm_extract availability
    # =========================================================================
    print("\n[9] Testing llm_extract availability...")

    try:
        from src.filter.llm import llm_extract

        print("  - llm_extract: IMPORTED ✓")

        # Check function signature
        sig = inspect.signature(llm_extract)
        print(f"  - Signature: llm_extract{sig}")

        # Check if it's async
        is_async = asyncio.iscoroutinefunction(llm_extract)
        print(f"  - Is async: {is_async}")

    except ImportError as e:
        print(f"  - llm_extract: IMPORT FAILED ✗ ({e})")

    print("[9] llm_extract availability: COMPLETED")

    # =========================================================================
    # 10. Summary and Recommendations
    # =========================================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    all_checks_passed = (
        has_persist_claim
        and has_persist_fragment
        and calls_persist_claim
        and calls_persist_fragment
        and claims_insert
        and fragments_insert
        and edges_insert
        and hasattr(state, "original_query")
    )

    if all_checks_passed:
        print("\n✓ All checks passed!")
        print("  - ExplorationState.original_query: EXISTS")
        print("  - _persist_claim method: EXISTS")
        print("  - _persist_fragment method: EXISTS")
        print("  - DB INSERT for claims: ENABLED")
        print("  - DB INSERT for fragments: ENABLED")
        print("  - DB INSERT for edges: ENABLED")
        print("\n📋 Note:")
        print("  - record_claim() is counter-only by design")
        print("  - DB persistence happens via _persist_claim() / _persist_fragment()")
        print("  - Test with actual pipeline execution to verify end-to-end")
    else:
        issues_found = []
        if not hasattr(state, "original_query"):
            issues_found.append("ExplorationState lacks original_query")
        if not has_persist_claim:
            issues_found.append("_persist_claim method missing")
        if not has_persist_fragment:
            issues_found.append("_persist_fragment method missing")
        if not claims_insert:
            issues_found.append("claims INSERT missing")
        if not fragments_insert:
            issues_found.append("fragments INSERT missing")
        if not edges_insert:
            issues_found.append("edges INSERT missing")

        print("\n⚠ Issues Found:")
        for i, issue in enumerate(issues_found):
            print(f"  {i + 1}. {issue}")

    # Cleanup
    print("\n[Cleanup] Removing test task...")
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    await db.execute("DELETE FROM claims WHERE task_id = ?", (task_id,))

    print("\n" + "=" * 70)
    print("Debug script completed.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
