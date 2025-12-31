#!/usr/bin/env python3
"""
Debug script for E2E testing.
Executes a minimal search flow to trigger instrumentation logs.

Usage:
    timeout 120 uv run python scripts/debug_e2e_test.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.isolation import isolated_database_path


async def main() -> None:
    """Run minimal search flow for debugging."""
    print("=== E2E Debug Test ===")

    # Use isolated database to avoid lock conflicts
    async with isolated_database_path() as db_path:
        print(f"Using isolated DB: {db_path}")

        # Import after path setup
        from src.search.apis.openalex import OpenAlexClient
        from src.search.apis.semantic_scholar import SemanticScholarClient

        # Test 1: OpenAlex search (tests hypothesis A - Author.name validation)
        print("\n[1] Testing OpenAlex search...")
        oa_client = OpenAlexClient()
        try:
            result = await oa_client.search("DPP-4 inhibitors efficacy", limit=3)
            print(f"  OpenAlex: {len(result.papers)} papers found")
            for p in result.papers[:2]:
                print(f"    - {p.title[:50]}... (authors: {len(p.authors)})")
                for a in p.authors[:2]:
                    print(f"      Author: {a.name!r}")
        except Exception as e:
            print(f"  OpenAlex ERROR: {e}")
        finally:
            await oa_client.close()

        # Test 2: Semantic Scholar get_references (direct test, skip search to avoid rate limit)
        print("\n[2] Testing Semantic Scholar get_references directly...")
        s2_client = SemanticScholarClient()
        # Use a known paper_id to avoid search rate limit issues
        # This is a DPP-4 related paper from previous successful runs
        test_paper_id = "s2:e6494042a48765746108dccf83ded44554de2a61"
        try:
            print(f"  Testing get_references for: {test_paper_id}")

            # This should trigger hypothesis G logs (_parse_paper entry)
            refs = await s2_client.get_references(test_paper_id)
            print(f"  References: {len(refs)} papers")

            # Wait for rate limiter
            import asyncio
            await asyncio.sleep(3)

            # This should also trigger hypothesis G logs
            cits = await s2_client.get_citations(test_paper_id)
            print(f"  Citations: {len(cits)} papers")
        except Exception as e:
            print(f"  S2 ERROR: {e}")
        finally:
            await s2_client.close()

        print("\n=== Debug Test Complete ===")
        print("Check logs at: .cursor/debug.log")


if __name__ == "__main__":
    asyncio.run(main())

