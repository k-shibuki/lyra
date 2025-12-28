#!/usr/bin/env python3
"""
Debug script for citation graph cross-API query.

Tests:
1. S2 paper ID → DOI extraction → OpenAlex cross-query
2. OpenAlex paper ID → DOI extraction → S2 cross-query
3. DOI-based query to both APIs

Usage:
    timeout 120 uv run python scripts/debug_citation_graph.py
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


async def main() -> None:
    """Run citation graph cross-API tests."""
    print("=" * 60)
    print("Citation Graph Cross-API Query Test")
    print("=" * 60)

    # Clear debug log
    clear_debug_log()

    # Import after path setup
    from src.search.academic_provider import AcademicSearchProvider

    provider = AcademicSearchProvider()

    # Test 1: S2 paper with DOI
    print("\n[1] Testing S2 paper → citation graph (with DOI cross-query)...")

    # Use a well-known paper that has DOI
    s2_paper_id = "s2:204e3073870fae3d05bcbc2f6a8e263d9b72e776"  # "Attention Is All You Need"

    try:
        papers, citations = await provider.get_citation_graph(
            paper_id=s2_paper_id,
            depth=1,
            direction="references"
        )
        print(f"    Papers found: {len(papers)}")
        print(f"    Citations found: {len(citations)}")

        # Check if we got papers from both APIs
        s2_papers = [p for p in papers if p.id.startswith("s2:")]
        oa_papers = [p for p in papers if p.id.startswith("openalex:")]
        print(f"    S2 papers: {len(s2_papers)}")
        print(f"    OpenAlex papers: {len(oa_papers)}")

        # Check DOIs
        papers_with_doi = [p for p in papers if p.doi]
        print(f"    Papers with DOI: {len(papers_with_doi)}")

        if papers_with_doi:
            print(f"    Sample DOI: {papers_with_doi[0].doi}")

    except Exception as e:
        print(f"    Error: {e}")

    # Test 2: OpenAlex paper ID
    print("\n[2] Testing OpenAlex paper → citation graph...")

    oa_paper_id = "openalex:W2741809807"  # "The state of OA"

    try:
        papers2, citations2 = await provider.get_citation_graph(
            paper_id=oa_paper_id,
            depth=1,
            direction="citations"
        )
        print(f"    Papers found: {len(papers2)}")
        print(f"    Citations found: {len(citations2)}")

        s2_papers2 = [p for p in papers2 if p.id.startswith("s2:")]
        oa_papers2 = [p for p in papers2 if p.id.startswith("openalex:")]
        print(f"    S2 papers: {len(s2_papers2)}")
        print(f"    OpenAlex papers: {len(oa_papers2)}")

    except Exception as e:
        print(f"    Error: {e}")

    # Cleanup
    await provider.close()

    # Analyze debug log
    print("\n" + "=" * 60)
    print("Debug Log Analysis")
    print("=" * 60)

    entries = read_debug_log()
    print(f"Total entries: {len(entries)}")

    # Group by location
    by_location: dict[str, int] = {}
    for e in entries:
        loc = e.get("location", "unknown")
        by_location[loc] = by_location.get(loc, 0) + 1

    print("\nEntries by location:")
    for loc, count in sorted(by_location.items()):
        print(f"  {loc}: {count}")

    # Check for 404 errors
    error_entries = [e for e in entries if "error" in str(e.get("data", {})).lower() or "404" in str(e.get("data", {}))]
    if error_entries:
        print(f"\nError entries: {len(error_entries)}")
        for e in error_entries[:5]:
            print(f"  {e.get('location')}: {e.get('message')}")

    # Check H-J (get_citations with DOI)
    h_j_entries = [e for e in entries if e.get("hypothesisId") == "H-J"]
    print(f"\nH-J (get_citations) entries: {len(h_j_entries)}")
    for e in h_j_entries[:3]:
        print(f"  {e.get('data')}")

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
