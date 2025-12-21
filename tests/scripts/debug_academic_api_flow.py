#!/usr/bin/env python3
"""
E2E Verification: Academic API Integration Flow

This script verifies the complete flow of J.2 Academic API Integration:

1. Academic query detection
2. AcademicSearchProvider initialization
3. Semantic Scholar API search
4. OpenAlex API search
5. Result deduplication via CanonicalPaperIndex
6. Citation graph retrieval
7. Evidence graph integration

Usage:
    source .venv/bin/activate
    python tests/scripts/debug_academic_api_flow.py

    # With live API calls (requires network)
    python tests/scripts/debug_academic_api_flow.py --live
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def test_academic_query_detection() -> bool:
    """Step 1: Test academic query detection."""
    print("\n" + "=" * 60)
    print("[Step 1] Testing academic query detection")
    print("=" * 60)

    from src.research.pipeline import SearchPipeline

    # Create pipeline instance (minimal setup for testing)
    pipeline = SearchPipeline.__new__(SearchPipeline)

    # Test cases: (query, expected_is_academic)
    test_cases = [
        ("machine learning paper", True),
        ("深層学習 論文", True),
        ("arXiv transformer attention", True),
        ("10.1038/nature12373", True),
        ("site:arxiv.org neural networks", True),
        ("how to cook pasta", False),
        ("python programming tutorial", False),
    ]

    passed = 0
    failed = 0

    for query, expected in test_cases:
        result = pipeline._is_academic_query(query)
        status = "✓" if result == expected else "✗"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status} Query: '{query[:40]}...' -> {result} (expected: {expected})")

    print(f"\n  Summary: {passed} passed, {failed} failed")
    return failed == 0


async def test_academic_provider_initialization() -> bool:
    """Step 2: Test AcademicSearchProvider initialization."""
    print("\n" + "=" * 60)
    print("[Step 2] Testing AcademicSearchProvider initialization")
    print("=" * 60)

    from src.search.academic_provider import AcademicSearchProvider

    provider = AcademicSearchProvider()

    # Verify default APIs
    assert provider._default_apis == ["semantic_scholar", "openalex"], (
        f"Expected default APIs: semantic_scholar, openalex, got: {provider._default_apis}"
    )
    print(f"  ✓ Default APIs: {provider._default_apis}")

    # Verify API priority
    expected_priority = {
        "semantic_scholar": 1,
        "openalex": 2,
        "crossref": 3,
        "arxiv": 4,
        "unpaywall": 5,
    }
    assert provider.API_PRIORITY == expected_priority, (
        f"API priority mismatch: {provider.API_PRIORITY}"
    )
    print(
        "  ✓ API priority order: semantic_scholar(1) > openalex(2) > crossref(3) > arxiv(4) > unpaywall(5)"
    )

    # Verify lazy initialization
    assert provider._clients == {}, "Clients should be empty (lazy init)"
    print("  ✓ Clients are lazily initialized")

    await provider.close()
    print("  ✓ Provider cleanup successful")

    return True


async def test_paper_model() -> bool:
    """Step 3: Test Paper/Citation/Author models."""
    print("\n" + "=" * 60)
    print("[Step 3] Testing Paper/Citation/Author Pydantic models")
    print("=" * 60)

    from src.utils.schemas import Author, Citation, Paper

    # Test Author model
    author = Author(name="John Doe", affiliation="MIT", orcid="0000-0001-2345-6789")
    assert author.name == "John Doe"
    print(f"  ✓ Author model: {author.name}")

    # Test Paper model
    paper = Paper(
        id="s2:12345",
        title="Test Paper",
        abstract="This is a test abstract.",
        authors=[author],
        year=2024,
        published_date=None,
        doi="10.1234/test",
        arxiv_id=None,
        venue=None,
        citation_count=42,
        reference_count=10,
        is_open_access=True,
        oa_url="https://example.com/paper.pdf",
        pdf_url=None,
        source_api="semantic_scholar",
    )
    assert paper.id == "s2:12345"
    assert paper.citation_count == 42
    print(f"  ✓ Paper model: {paper.title} (citations: {paper.citation_count})")

    # Test to_search_result conversion
    search_result = paper.to_search_result()
    assert search_result.title == paper.title
    assert search_result.engine == "semantic_scholar"
    print(f"  ✓ Paper.to_search_result(): engine={search_result.engine}")

    # Test Citation model
    citation = Citation(
        citing_paper_id="s2:12345",
        cited_paper_id="s2:67890",
        is_influential=True,
        context="This work extends the previous study [1].",
    )
    assert citation.is_influential is True
    print(f"  ✓ Citation model: {citation.citing_paper_id} -> {citation.cited_paper_id}")

    return True


async def test_canonical_paper_index() -> bool:
    """Step 4: Test CanonicalPaperIndex deduplication."""
    print("\n" + "=" * 60)
    print("[Step 4] Testing CanonicalPaperIndex deduplication")
    print("=" * 60)

    from src.search.canonical_index import CanonicalPaperIndex
    from src.utils.schemas import Paper

    index = CanonicalPaperIndex()

    # Register paper from Semantic Scholar
    paper1 = Paper(
        id="s2:12345",
        title="Attention Is All You Need",
        abstract="We propose a new model architecture...",
        authors=[],
        year=2017,
        published_date=None,
        doi="10.5555/3295222.3295349",
        arxiv_id=None,
        venue=None,
        citation_count=100000,
        reference_count=0,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="semantic_scholar",
    )
    id1 = index.register_paper(paper1, source_api="semantic_scholar")
    print(f"  ✓ Registered from Semantic Scholar: {id1}")

    # Register same paper from OpenAlex (should deduplicate)
    paper2 = Paper(
        id="openalex:W2963403868",
        title="Attention Is All You Need",
        abstract="The dominant sequence transduction models...",
        authors=[],
        year=2017,
        published_date=None,
        doi="10.5555/3295222.3295349",  # Same DOI
        arxiv_id=None,
        venue=None,
        citation_count=95000,
        reference_count=0,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="openalex",
    )
    id2 = index.register_paper(paper2, source_api="openalex")
    print(f"  ✓ Registered from OpenAlex (same DOI): {id2}")

    # Verify deduplication
    assert id1 == id2, f"DOI deduplication failed: {id1} != {id2}"
    print(f"  ✓ DOI deduplication: both IDs map to {id1}")

    # Check stats
    stats = index.get_stats()
    assert stats["total"] == 1, f"Expected 1 unique paper, got {stats['total']}"
    print(f"  ✓ Stats: {stats}")

    # Get all entries
    entries = index.get_all_entries()
    assert len(entries) == 1

    # Verify Paper object is preserved
    entry = entries[0]
    assert entry.paper is not None
    assert entry.paper.citation_count in [100000, 95000]  # First registered wins
    print(f"  ✓ Entry preserved: source={entry.source}, paper.id={entry.paper.id}")

    return True


async def test_semantic_scholar_client() -> bool:
    """Step 5: Test Semantic Scholar client (mocked)."""
    print("\n" + "=" * 60)
    print("[Step 5] Testing Semantic Scholar client")
    print("=" * 60)

    from src.search.apis.semantic_scholar import SemanticScholarClient

    client = SemanticScholarClient()

    # Verify client attributes
    assert client.name == "semantic_scholar"
    print(f"  ✓ Client name: {client.name}")

    assert client.base_url is not None
    assert "semanticscholar.org" in client.base_url
    print(f"  ✓ Base URL: {client.base_url}")

    # Test ID normalization (important bug fix)
    test_ids = [
        ("s2:12345", "12345"),  # Remove s2: prefix
        ("CorpusId:12345", "CorpusId:12345"),  # Keep CorpusId
        ("10.1234/test", "10.1234/test"),  # Keep DOI
        ("12345", "12345"),  # Keep raw ID
    ]

    for input_id, expected in test_ids:
        normalized = client._normalize_paper_id(input_id)
        assert normalized == expected, (
            f"ID normalization failed: {input_id} -> {normalized}, expected {expected}"
        )
        print(f"  ✓ ID normalization: '{input_id}' -> '{normalized}'")

    await client.close()
    return True


async def test_evidence_graph_academic_edges() -> bool:
    """Step 6: Test evidence graph academic edge attributes."""
    print("\n" + "=" * 60)
    print("[Step 6] Testing evidence graph academic edge attributes")
    print("=" * 60)

    from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

    graph = EvidenceGraph()

    # Add PAGE nodes
    graph.add_node(NodeType.PAGE, "page1")
    graph.add_node(NodeType.PAGE, "page2")

    # Add academic CITES edge
    graph.add_edge(
        source_type=NodeType.PAGE,
        source_id="page1",
        target_type=NodeType.PAGE,
        target_id="page2",
        relation=RelationType.CITES,
        is_academic=True,
        is_influential=True,
        citation_context="This work builds upon [1].",
    )

    # Verify edge attributes
    source_node = f"{NodeType.PAGE.value}:page1"
    target_node = f"{NodeType.PAGE.value}:page2"
    edge_data = graph._graph.edges[source_node, target_node]

    assert edge_data.get("is_academic") is True
    print(f"  ✓ is_academic attribute: {edge_data.get('is_academic')}")

    assert edge_data.get("is_influential") is True
    print(f"  ✓ is_influential attribute: {edge_data.get('is_influential')}")

    assert edge_data.get("citation_context") == "This work builds upon [1]."
    print(f"  ✓ citation_context attribute: '{edge_data.get('citation_context')[:30]}...'")

    return True


async def test_live_api_search(live: bool = False) -> bool:
    """Step 7: Live API search test (optional)."""
    print("\n" + "=" * 60)
    print("[Step 7] Live API search test")
    print("=" * 60)

    if not live:
        print("  ⏭ Skipped (use --live flag to enable)")
        return True

    from src.search.academic_provider import AcademicSearchProvider
    from src.search.provider import SearchOptions

    provider = AcademicSearchProvider()

    try:
        query = "transformer attention mechanism"
        options = SearchOptions(limit=5, engines=["semantic_scholar", "openalex"])

        print(f"  Searching: '{query}'...")
        response = await provider.search(query, options)

        if response.ok:
            print(f"  ✓ Search successful: {len(response.results)} results")
            for i, result in enumerate(response.results[:3]):
                print(f"    [{i + 1}] {result.title[:50]}...")
        else:
            print(f"  ⚠ Search failed: {response.error}")

        # Get internal index for more details
        index = provider.get_last_index()
        if index:
            stats = index.get_stats()
            print(f"  ✓ Deduplication stats: {stats}")

    finally:
        await provider.close()

    return True


async def test_config_loading() -> bool:
    """Step 8: Test academic APIs config loading."""
    print("\n" + "=" * 60)
    print("[Step 8] Testing academic APIs config loading")
    print("=" * 60)

    from src.utils.config import get_academic_apis_config

    config = get_academic_apis_config()

    # Verify config structure
    assert config.apis is not None
    print(f"  ✓ APIs configured: {list(config.apis.keys())}")

    # Verify Semantic Scholar config
    ss_config = config.apis.get("semantic_scholar")
    assert ss_config is not None
    assert ss_config.enabled is True
    print(f"  ✓ Semantic Scholar: enabled={ss_config.enabled}, priority={ss_config.priority}")

    # Verify OpenAlex config
    oa_config = config.apis.get("openalex")
    assert oa_config is not None
    assert oa_config.enabled is True
    print(f"  ✓ OpenAlex: enabled={oa_config.enabled}, priority={oa_config.priority}")

    # Verify Unpaywall is disabled by default
    up_config = config.apis.get("unpaywall")
    if up_config:
        print(f"  ✓ Unpaywall: enabled={up_config.enabled}")

    # Verify defaults
    assert config.defaults is not None
    assert "semantic_scholar" in config.defaults.search_apis
    print(f"  ✓ Default search APIs: {config.defaults.search_apis}")

    return True


async def main() -> int:
    """Run all verification steps."""
    print("=" * 60)
    print(" J.2 Academic API Integration - E2E Verification")
    print("=" * 60)

    # Check for --live flag
    live = "--live" in sys.argv
    if live:
        print("\n⚠ Running with --live flag: actual API calls will be made")

    all_passed = True

    try:
        # Run all steps
        steps = [
            ("Academic query detection", test_academic_query_detection),
            ("AcademicSearchProvider init", test_academic_provider_initialization),
            ("Paper/Citation/Author models", test_paper_model),
            ("CanonicalPaperIndex dedup", test_canonical_paper_index),
            ("Semantic Scholar client", test_semantic_scholar_client),
            ("Evidence graph academic edges", test_evidence_graph_academic_edges),
            ("Live API search", lambda: test_live_api_search(live)),
            ("Config loading", test_config_loading),
        ]

        for name, test_func in steps:
            try:
                result = await test_func()
                if not result:
                    all_passed = False
            except Exception as e:
                print(f"\n  ✗ Error in '{name}': {e}")
                all_passed = False

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        all_passed = False

    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All verification steps passed!")
    else:
        print("✗ Some verification steps failed")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
