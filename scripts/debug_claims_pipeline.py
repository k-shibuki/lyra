#!/usr/bin/env python3
"""Debug script to test claims extraction pipeline in isolation.

This script tests the data pipeline from LLM extraction to DB persistence
without going through the full MCP server flow.
"""
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

LOG_PATH = "/home/statuser/lyra/.cursor/debug.log"


def log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    """Write NDJSON log entry."""
    entry = {
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": time.time() * 1000,
        "sessionId": "debug-script",
        "runId": "pipeline-test-v3",
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


async def test_full_pipeline_with_db():
    """Test the complete pipeline including DB persistence."""
    from src.filter.llm import llm_extract
    from src.filter.nli import nli_judge
    from src.storage.database import get_database

    log("H-PIPELINE", "test_full:entry", "Testing full pipeline with DB", {})

    # Test data
    test_task_id = f"test_task_{uuid.uuid4().hex[:8]}"
    test_fragment_id = f"test_frag_{uuid.uuid4().hex[:8]}"
    test_text = """Climate change poses a significant threat to coral reef ecosystems worldwide. 
    Rising ocean temperatures have caused mass bleaching events, with the Great Barrier Reef 
    experiencing severe bleaching in 2016 and 2017. Ocean acidification, resulting from 
    increased CO2 absorption, reduces the ability of corals to build calcium carbonate 
    skeletons. Studies indicate that coral cover has declined by 50% since the 1950s."""

    # Step 1: Create test task
    db = await get_database()
    await db.insert(
        "tasks",
        {"id": test_task_id, "query": "Test query", "status": "active"},
        auto_id=False,
        or_ignore=True,
    )
    log("H-PIPELINE", "test_full:task_created", "Test task created", {"task_id": test_task_id})

    # Step 2: LLM extraction
    test_passage = {
        "id": test_fragment_id,
        "text": test_text,
        "source_url": "https://example.com/coral-study",
    }

    result = await llm_extract(
        passages=[test_passage],
        task="extract_claims",
        context="Climate change impacts on coral reefs",
    )

    log(
        "H-PIPELINE",
        "test_full:llm_extract",
        "LLM extraction result",
        {
            "ok": result.get("ok"),
            "claims_count": len(result.get("claims", [])),
            "first_claim_keys": list(result.get("claims", [{}])[0].keys()) if result.get("claims") else None,
        },
    )

    if not result.get("ok") or not result.get("claims"):
        log("H-PIPELINE", "test_full:no_claims", "No claims extracted", {})
        return {"success": False, "reason": "no_claims"}

    # Step 3: Process each claim
    claims_saved = 0
    edges_saved = 0

    for claim in result["claims"]:
        if not isinstance(claim, dict) or not claim.get("claim"):
            log("H-PIPELINE", "test_full:skip_claim", "Skipping invalid claim", {"claim": claim})
            continue

        claim_id = f"c_{uuid.uuid4().hex[:8]}"
        claim_text = claim.get("claim", "")[:500]
        llm_confidence = claim.get("confidence", 0.5)

        # Step 3a: Save claim to DB
        try:
            await db.insert(
                "claims",
                {
                    "id": claim_id,
                    "task_id": test_task_id,
                    "claim_text": claim_text,
                    "claim_type": claim.get("type", "fact"),
                    "llm_claim_confidence": llm_confidence,
                    "verification_notes": "source_url=https://example.com/coral-study",
                },
                auto_id=False,
                or_ignore=True,
            )
            claims_saved += 1
            log(
                "H-PIPELINE",
                "test_full:claim_saved",
                "Claim saved to DB",
                {"claim_id": claim_id, "claim_text_preview": claim_text[:50]},
            )
        except Exception as e:
            log("H-PIPELINE", "test_full:claim_save_error", "Failed to save claim", {"error": str(e)})
            continue

        # Step 3b: NLI evaluation
        try:
            nli_results = await nli_judge(
                pairs=[
                    {
                        "pair_id": f"{test_fragment_id}_{claim_id}",
                        "premise": test_text[:1000],
                        "hypothesis": claim_text,
                    }
                ]
            )

            log(
                "H-PIPELINE",
                "test_full:nli_result",
                "NLI evaluation result",
                {
                    "result_type": type(nli_results).__name__,
                    "result_count": len(nli_results) if isinstance(nli_results, list) else None,
                    "first_result": nli_results[0] if nli_results else None,
                },
            )

            if nli_results and len(nli_results) > 0:
                nli_item = nli_results[0]
                stance = nli_item.get("stance", "neutral")
                nli_confidence = nli_item.get("nli_edge_confidence", 0.5)

                # Map stance to relation
                relation = {
                    "supports": "supports",
                    "refutes": "refutes",
                }.get(stance, "neutral")

                # Save edge
                edge_id = f"e_{uuid.uuid4().hex[:8]}"
                await db.insert(
                    "edges",
                    {
                        "id": edge_id,
                        "source_type": "fragment",
                        "source_id": test_fragment_id,
                        "target_type": "claim",
                        "target_id": claim_id,
                        "relation": relation,
                        "nli_label": stance,
                        "nli_edge_confidence": nli_confidence,
                    },
                    auto_id=False,
                    or_ignore=True,
                )
                edges_saved += 1
                log(
                    "H-PIPELINE",
                    "test_full:edge_saved",
                    "Edge saved to DB",
                    {"edge_id": edge_id, "relation": relation, "nli_confidence": nli_confidence},
                )

        except Exception as e:
            log("H-PIPELINE", "test_full:nli_error", "NLI evaluation failed", {"error": str(e), "type": type(e).__name__})

    # Step 4: Verify DB state
    saved_claims = await db.fetch_all(
        "SELECT * FROM claims WHERE task_id = ?", (test_task_id,)
    )
    log(
        "H-PIPELINE",
        "test_full:verify_claims",
        "Verify saved claims",
        {"count": len(saved_claims), "claims": [dict(c) for c in saved_claims[:3]]},
    )

    # Cleanup test data
    await db.execute("DELETE FROM edges WHERE source_id = ?", (test_fragment_id,))
    await db.execute("DELETE FROM claims WHERE task_id = ?", (test_task_id,))
    await db.execute("DELETE FROM tasks WHERE id = ?", (test_task_id,))

    return {
        "success": True,
        "claims_saved": claims_saved,
        "edges_saved": edges_saved,
        "verified_count": len(saved_claims),
    }


async def main():
    """Run all pipeline tests."""
    print("=== Claims Pipeline Debug Script v3 (Full Pipeline) ===")
    print(f"Log output: {LOG_PATH}")

    log("START", "main:entry", "Starting pipeline debug v3", {"timestamp": time.time()})

    # Test full pipeline with DB
    print("\n[1/1] Testing full pipeline with DB persistence...")
    result = await test_full_pipeline_with_db()

    log("END", "main:exit", "Pipeline debug v3 complete", {"result": result, "timestamp": time.time()})

    if result.get("success"):
        print(f"\n✅ SUCCESS: {result['claims_saved']} claims saved, {result['edges_saved']} edges saved")
    else:
        print(f"\n❌ FAILED: {result.get('reason', 'unknown')}")

    print(f"\n=== Debug complete. Check logs at: {LOG_PATH} ===")


if __name__ == "__main__":
    asyncio.run(main())
