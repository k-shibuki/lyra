#!/usr/bin/env python3
"""
E2E debug script for J2 Academic API Integration.

Tests the complementary search with unified deduplication and reports metrics.

Usage:
    python scripts/debug_academic_search.py "transformer attention mechanism"
    python scripts/debug_academic_search.py --test-cases
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.search.academic_provider import AcademicSearchProvider
from src.search.canonical_index import CanonicalPaperIndex
from src.search.id_resolver import IDResolver
from src.search.identifier_extractor import IdentifierExtractor
from src.search.provider import SearchOptions
from src.utils.logging import get_logger

logger = get_logger(__name__)


class AcademicSearchDebugger:
    """Debugger for academic search with deduplication metrics."""

    def __init__(self) -> None:
        self.provider = AcademicSearchProvider()
        self.extractor = IdentifierExtractor()
        self.resolver = IDResolver()

    async def run_search(self, query: str, limit: int = 20) -> dict[str, object]:
        """Run academic search and return detailed metrics.

        Args:
            query: Search query
            limit: Maximum results per API

        Returns:
            Metrics dictionary
        """
        print(f"\n{'=' * 60}")
        print(f"Query: {query}")
        print(f"{'=' * 60}\n")

        # Execute search
        options = SearchOptions(limit=limit)
        response = await self.provider.search(query, options)

        # Collect metrics
        metrics = {
            "query": query,
            "total_results": len(response.results),
            "provider": response.provider,
            "error": response.error if hasattr(response, "error") else None,
        }

        # Analyze results
        source_counts: dict[str, int] = {}
        doi_count = 0
        abstract_count = 0

        for result in response.results:
            # Count by source
            source = getattr(result, "engine", "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1

            # Check for DOI in URL
            if result.url and "doi.org" in result.url:
                doi_count += 1

            # Check for abstract
            if result.snippet and len(result.snippet) > 100:
                abstract_count += 1

        metrics["source_distribution"] = source_counts
        metrics["doi_coverage"] = doi_count
        metrics["abstract_coverage"] = abstract_count

        # Print results summary
        print("Results Summary:")
        print(f"  Total unique results: {metrics['total_results']}")
        print(f"  DOI coverage: {doi_count}")
        print(f"  Abstract coverage: {abstract_count}")
        print("\nSource Distribution:")
        for source, count in source_counts.items():
            print(f"  {source}: {count}")

        # Print top 5 results
        print("\nTop 5 Results:")
        for i, result in enumerate(response.results[:5]):
            print(f"  {i + 1}. {result.title[:60]}...")
            print(f"     URL: {result.url[:60]}..." if result.url else "     URL: N/A")
            print()

        return metrics

    async def test_identifier_extraction(self) -> dict:
        """Test identifier extraction from various URLs.

        Returns:
            Test results
        """
        print(f"\n{'=' * 60}")
        print("Identifier Extraction Tests")
        print(f"{'=' * 60}\n")

        test_urls = [
            ("https://doi.org/10.1038/nature12373", "doi", "10.1038/nature12373"),
            ("https://pubmed.ncbi.nlm.nih.gov/12345678/", "pmid", "12345678"),
            ("https://arxiv.org/abs/2301.12345", "arxiv_id", "2301.12345"),
            ("https://cir.nii.ac.jp/crid/1234567890", "crid", "1234567890"),
            ("https://example.com/random-page", "url", None),
        ]

        results = []
        for url, expected_field, expected_value in test_urls:
            identifier = self.extractor.extract(url)
            actual_value = getattr(identifier, expected_field, None)

            passed = True
            if expected_field != "url":
                passed = actual_value == expected_value

            result = {
                "url": url,
                "expected_field": expected_field,
                "expected_value": expected_value,
                "actual_value": actual_value,
                "passed": passed,
            }
            results.append(result)

            status = "✓" if passed else "✗"
            print(f"  {status} {url[:50]}...")
            print(f"    {expected_field}: {actual_value}")

        passed_count = sum(1 for r in results if r["passed"])
        print(f"\nPassed: {passed_count}/{len(results)}")

        return {"tests": results, "passed": passed_count, "total": len(results)}

    async def test_canonical_index(self) -> dict:
        """Test canonical paper index deduplication.

        Returns:
            Test results
        """
        print(f"\n{'=' * 60}")
        print("Canonical Index Deduplication Tests")
        print(f"{'=' * 60}\n")

        from src.search.provider import SearchResult
        from src.utils.schemas import Author, Paper, PaperIdentifier

        index = CanonicalPaperIndex()

        # Test 1: Register paper with DOI
        paper1 = Paper(
            id="test:1",
            title="Test Paper 1",
            abstract=None,
            authors=[Author(name="John Doe", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/test1",
            arxiv_id=None,
            venue=None,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )
        id1 = index.register_paper(paper1, source_api="semantic_scholar")
        print(f"  1. Registered paper with DOI: {id1}")

        # Test 2: Register same paper again (should deduplicate)
        paper2 = Paper(
            id="test:2",
            title="Test Paper 1 (duplicate)",
            abstract=None,
            authors=[Author(name="John Doe", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/test1",
            arxiv_id=None,
            venue=None,
            oa_url=None,
            pdf_url=None,
            source_api="openalex",
        )
        id2 = index.register_paper(paper2, source_api="openalex")
        dedup_success = id1 == id2
        print(f"  2. Registered duplicate (same DOI): {id2}")
        print(f"     Deduplication: {'✓ Success' if dedup_success else '✗ Failed'}")

        # Test 3: Register SERP result matching existing paper
        serp1 = SearchResult(
            title="Test Paper 1",
            url="https://doi.org/10.1234/test1",
            snippet="Test snippet",
            engine="google",
            rank=1,
        )
        identifier = PaperIdentifier(
            doi="10.1234/test1", pmid=None, arxiv_id=None, crid=None, url=None
        )
        id3 = index.register_serp_result(serp1, identifier)
        serp_link_success = id1 == id3
        print(f"  3. SERP result linked to existing: {'✓' if serp_link_success else '✗'}")

        # Get stats
        stats = index.get_stats()
        print("\nFinal Stats:")
        print(f"  Total unique: {stats['total']}")
        print(f"  API only: {stats['api_only']}")
        print(f"  SERP only: {stats['serp_only']}")
        print(f"  Both: {stats['both']}")

        return {
            "dedup_success": dedup_success,
            "serp_link_success": serp_link_success,
            "stats": stats,
        }

    async def test_abstract_only_strategy(self) -> dict:
        """Test Abstract Only strategy.

        Verifies that papers with abstracts skip fetch and are stored directly.

        Returns:
            Test results
        """
        print(f"\n{'=' * 60}")
        print("Abstract Only Strategy Tests")
        print(f"{'=' * 60}\n")

        from src.search.canonical_index import CanonicalPaperIndex
        from src.utils.schemas import Author, Paper

        # Test 1: Paper with abstract (should skip fetch)
        paper_with_abstract = Paper(
            id="test:abstract_paper",
            title="Test Paper With Abstract",
            abstract="This is a test abstract for the Abstract Only strategy validation.",
            authors=[Author(name="Test Author", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/test_abstract",
            arxiv_id=None,
            venue=None,
            is_open_access=True,
            oa_url="https://example.com/paper.pdf",
            pdf_url=None,
            source_api="semantic_scholar",
        )

        # Test 2: Paper without abstract (should need fetch)
        paper_without_abstract = Paper(
            id="test:no_abstract_paper",
            title="Test Paper Without Abstract",
            abstract=None,
            authors=[Author(name="Test Author", affiliation=None, orcid=None)],
            year=2024,
            published_date=None,
            doi="10.1234/test_no_abstract",
            arxiv_id=None,
            venue=None,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )

        index = CanonicalPaperIndex()

        # Register papers
        id1 = index.register_paper(paper_with_abstract, "semantic_scholar")
        id2 = index.register_paper(paper_without_abstract, "semantic_scholar")

        entries = index.get_all_entries()

        results = {
            "paper_with_abstract": {
                "canonical_id": id1,
                "needs_fetch": False,  # Should skip fetch
                "passed": True,
            },
            "paper_without_abstract": {
                "canonical_id": id2,
                "needs_fetch": True,  # Should need fetch
                "passed": True,
            },
        }

        # Verify needs_fetch property
        for entry in entries:
            if entry.paper and entry.paper.id == "test:abstract_paper":
                needs_fetch = entry.needs_fetch
                results["paper_with_abstract"]["actual_needs_fetch"] = needs_fetch
                results["paper_with_abstract"]["passed"] = not needs_fetch
            elif entry.paper and entry.paper.id == "test:no_abstract_paper":
                needs_fetch = entry.needs_fetch
                results["paper_without_abstract"]["actual_needs_fetch"] = needs_fetch
                results["paper_without_abstract"]["passed"] = needs_fetch

        # Print results
        for name, res in results.items():
            status = "✓" if res["passed"] else "✗"
            print(f"  {status} {name}")
            print(f"    canonical_id: {res['canonical_id']}")
            print(f"    expected needs_fetch: {res['needs_fetch']}")
            print(f"    actual needs_fetch: {res.get('actual_needs_fetch', 'N/A')}")

        passed_count = sum(1 for r in results.values() if r["passed"])
        print(f"\nPassed: {passed_count}/{len(results)}")

        return {"tests": results, "passed": passed_count, "total": len(results)}

    async def test_citation_graph(self) -> dict:
        """Test citation graph retrieval.

        Returns:
            Test results
        """
        print(f"\n{'=' * 60}")
        print("Citation Graph Tests")
        print(f"{'=' * 60}\n")

        # Use a known paper ID from Semantic Scholar
        # "Attention Is All You Need" paper
        test_paper_id = "s2:204e3073870fae3d05bcbc2f6a8e263d9b72e776"

        try:
            related_papers, citations = await self.provider.get_citation_graph(
                paper_id=test_paper_id,
                depth=1,
                direction="references",
            )

            result = {
                "paper_id": test_paper_id,
                "related_papers_count": len(related_papers),
                "citations_count": len(citations),
                "passed": len(related_papers) > 0 or len(citations) > 0,
            }

            status = "✓" if result["passed"] else "✗"
            print(f"  {status} Citation graph for {test_paper_id[:30]}...")
            print(f"    Related papers: {len(related_papers)}")
            print(f"    Citations: {len(citations)}")

            if related_papers:
                print(f"    Sample related paper: {related_papers[0].title[:50]}...")

            return result

        except Exception as e:
            print(f"  ✗ Citation graph failed: {e}")
            return {"paper_id": test_paper_id, "error": str(e), "passed": False}

    async def run_all_tests(self) -> dict[str, object]:
        """Run all diagnostic tests.

        Returns:
            All test results
        """
        results: dict[str, object] = {}

        # Run core tests (keep local variables for type-safe summary)
        id_tests = await self.test_identifier_extraction()
        ci_tests = await self.test_canonical_index()
        ao_tests = await self.test_abstract_only_strategy()
        cg_test = await self.test_citation_graph()

        results["identifier_extraction"] = id_tests
        results["canonical_index"] = ci_tests
        results["abstract_only"] = ao_tests
        results["citation_graph"] = cg_test

        # Test actual search
        test_queries = [
            "transformer attention mechanism",
            "CRISPR gene editing",
        ]

        search_tests: list[dict[str, object]] = []
        for query in test_queries:
            try:
                metrics = await self.run_search(query, limit=10)
                search_tests.append(metrics)
            except Exception as e:
                print(f"\n  ✗ Search failed for '{query}': {e}")
                search_tests.append({"query": query, "error": str(e)})
        results["search_tests"] = search_tests

        # Summary
        print(f"\n{'=' * 60}")
        print("Summary")
        print(f"{'=' * 60}\n")

        def _as_int(value: object, default: int = 0) -> int:
            return value if isinstance(value, int) else default

        def _as_bool(value: object, default: bool = False) -> bool:
            return value if isinstance(value, bool) else default

        if isinstance(id_tests, dict):
            passed = _as_int(id_tests.get("passed"))
            total = _as_int(id_tests.get("total"))
            print(f"Identifier Extraction: {passed}/{total} passed")
        else:
            print("Identifier Extraction: (invalid result)")

        if isinstance(ci_tests, dict):
            dedup_success = _as_bool(ci_tests.get("dedup_success"))
            serp_link_success = _as_bool(ci_tests.get("serp_link_success"))
            print(
                f"Canonical Index: dedup={'✓' if dedup_success else '✗'}, "
                f"serp_link={'✓' if serp_link_success else '✗'}"
            )
        else:
            print("Canonical Index: (invalid result)")

        if isinstance(ao_tests, dict):
            passed = _as_int(ao_tests.get("passed"))
            total = _as_int(ao_tests.get("total"))
            print(f"Abstract Only: {passed}/{total} passed")
        else:
            print("Abstract Only: (invalid result)")

        if isinstance(cg_test, dict):
            passed = _as_bool(cg_test.get("passed"))
            print(f"Citation Graph: {'✓' if passed else '✗'}")
        else:
            print("Citation Graph: (invalid result)")

        for search_result in search_tests:
            query_obj = search_result.get("query")
            query = query_obj if isinstance(query_obj, str) else ""

            error_obj = search_result.get("error")
            error = error_obj if isinstance(error_obj, str) else ""

            if error:
                print(f"Search '{query[:30]}...': ✗ Error")
            else:
                total_obj = search_result.get("total_results")
                total = _as_int(total_obj)
                print(f"Search '{query[:30]}...': {total} results")

        return results

    async def close(self) -> None:
        """Cleanup resources."""
        await self.provider.close()
        await self.resolver.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Debug Academic Search Integration")
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--test-cases", action="store_true", help="Run all test cases")
    parser.add_argument("--limit", type=int, default=20, help="Max results per API")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    debugger = AcademicSearchDebugger()

    try:
        if args.test_cases:
            results = await debugger.run_all_tests()
        elif args.query:
            results = await debugger.run_search(args.query, args.limit)
        else:
            print("Usage: python scripts/debug_academic_search.py <query>")
            print("       python scripts/debug_academic_search.py --test-cases")
            return 0

        if args.json:
            print(json.dumps(results, indent=2, default=str))
        return 0
    finally:
        await debugger.close()


if __name__ == "__main__":
    asyncio.run(main())
