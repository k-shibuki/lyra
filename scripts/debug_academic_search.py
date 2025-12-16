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
from src.search.identifier_extractor import IdentifierExtractor
from src.search.id_resolver import IDResolver
from src.search.provider import SearchOptions
from src.utils.logging import get_logger

logger = get_logger(__name__)


class AcademicSearchDebugger:
    """Debugger for academic search with deduplication metrics."""
    
    def __init__(self):
        self.provider = AcademicSearchProvider()
        self.extractor = IdentifierExtractor()
        self.resolver = IDResolver()
    
    async def run_search(self, query: str, limit: int = 20) -> dict:
        """Run academic search and return detailed metrics.
        
        Args:
            query: Search query
            limit: Maximum results per API
            
        Returns:
            Metrics dictionary
        """
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print(f"{'='*60}\n")
        
        # Execute search
        options = SearchOptions(limit=limit)
        response = await self.provider.search(query, options)
        
        # Collect metrics
        metrics = {
            "query": query,
            "total_results": len(response.results),
            "provider": response.provider,
            "error": response.error if hasattr(response, 'error') else None,
        }
        
        # Analyze results
        source_counts = {}
        doi_count = 0
        abstract_count = 0
        open_access_count = 0
        
        for result in response.results:
            # Count by source
            source = getattr(result, 'engine', 'unknown')
            source_counts[source] = source_counts.get(source, 0) + 1
            
            # Check for DOI in URL
            if result.url and 'doi.org' in result.url:
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
        print(f"\nSource Distribution:")
        for source, count in source_counts.items():
            print(f"  {source}: {count}")
        
        # Print top 5 results
        print(f"\nTop 5 Results:")
        for i, result in enumerate(response.results[:5]):
            print(f"  {i+1}. {result.title[:60]}...")
            print(f"     URL: {result.url[:60]}..." if result.url else "     URL: N/A")
            print()
        
        return metrics
    
    async def test_identifier_extraction(self) -> dict:
        """Test identifier extraction from various URLs.
        
        Returns:
            Test results
        """
        print(f"\n{'='*60}")
        print("Identifier Extraction Tests")
        print(f"{'='*60}\n")
        
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
        print(f"\n{'='*60}")
        print("Canonical Index Deduplication Tests")
        print(f"{'='*60}\n")
        
        from src.utils.schemas import Paper, Author, PaperIdentifier
        from src.search.provider import SearchResult
        
        index = CanonicalPaperIndex()
        
        # Test 1: Register paper with DOI
        paper1 = Paper(
            id="test:1",
            title="Test Paper 1",
            doi="10.1234/test1",
            authors=[Author(name="John Doe")],
            year=2024,
            source_api="semantic_scholar",
        )
        id1 = index.register_paper(paper1, source_api="semantic_scholar")
        print(f"  1. Registered paper with DOI: {id1}")
        
        # Test 2: Register same paper again (should deduplicate)
        paper2 = Paper(
            id="test:2",
            title="Test Paper 1 (duplicate)",
            doi="10.1234/test1",
            authors=[Author(name="John Doe")],
            year=2024,
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
        identifier = PaperIdentifier(doi="10.1234/test1")
        id3 = index.register_serp_result(serp1, identifier)
        serp_link_success = id1 == id3
        print(f"  3. SERP result linked to existing: {'✓' if serp_link_success else '✗'}")
        
        # Get stats
        stats = index.get_stats()
        print(f"\nFinal Stats:")
        print(f"  Total unique: {stats['total']}")
        print(f"  API only: {stats['api_only']}")
        print(f"  SERP only: {stats['serp_only']}")
        print(f"  Both: {stats['both']}")
        
        return {
            "dedup_success": dedup_success,
            "serp_link_success": serp_link_success,
            "stats": stats,
        }
    
    async def run_all_tests(self) -> dict:
        """Run all diagnostic tests.
        
        Returns:
            All test results
        """
        results = {}
        
        # Test identifier extraction
        results["identifier_extraction"] = await self.test_identifier_extraction()
        
        # Test canonical index
        results["canonical_index"] = await self.test_canonical_index()
        
        # Test actual search
        test_queries = [
            "transformer attention mechanism",
            "CRISPR gene editing",
        ]
        
        results["search_tests"] = []
        for query in test_queries:
            try:
                metrics = await self.run_search(query, limit=10)
                results["search_tests"].append(metrics)
            except Exception as e:
                print(f"\n  ✗ Search failed for '{query}': {e}")
                results["search_tests"].append({"query": query, "error": str(e)})
        
        # Summary
        print(f"\n{'='*60}")
        print("Summary")
        print(f"{'='*60}\n")
        
        id_tests = results["identifier_extraction"]
        print(f"Identifier Extraction: {id_tests['passed']}/{id_tests['total']} passed")
        
        ci_tests = results["canonical_index"]
        print(f"Canonical Index: dedup={'✓' if ci_tests['dedup_success'] else '✗'}, "
              f"serp_link={'✓' if ci_tests['serp_link_success'] else '✗'}")
        
        for search_result in results["search_tests"]:
            if "error" in search_result and search_result["error"]:
                print(f"Search '{search_result['query'][:30]}...': ✗ Error")
            else:
                print(f"Search '{search_result['query'][:30]}...': "
                      f"{search_result.get('total_results', 0)} results")
        
        return results
    
    async def close(self):
        """Cleanup resources."""
        await self.provider.close()
        await self.resolver.close()


async def main():
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
            return
        
        if args.json:
            print(json.dumps(results, indent=2, default=str))
    finally:
        await debugger.close()


if __name__ == "__main__":
    asyncio.run(main())

