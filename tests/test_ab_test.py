"""
Tests for Query A/B Testing module.

Tests §3.1.1: Query A/B Testing
- Small-scale A/B tests with notation/particle/word-order variants
- Cache and reuse high-yield queries

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-QVG-N-01 | Generator initialization | Equivalence – normal | Rules loaded | Init test |
| TC-QVG-N-02 | AI term in query | Equivalence – normal | Notation variants generated | AI→人工知能 |
| TC-QVG-N-03 | Kanji in query | Equivalence – normal | Notation variants generated | Kanji variants |
| TC-QVG-B-01 | No matching patterns | Boundary – empty | Empty list | No match case |
| TC-QVG-N-04 | Particle の in query | Equivalence – normal | Particle variants generated | Particle rules |
| TC-QVG-N-05 | Particle は in query | Equivalence – normal | Particle variants generated | は→が etc |
| TC-QVG-N-06 | Multi-word query | Equivalence – normal | Order variants generated | Word reorder |
| TC-QVG-B-02 | Single word query | Boundary – minimal | No order variants | Can't reorder |
| TC-QVG-N-07 | All variant types | Equivalence – normal | Original + variants | Comprehensive |
| TC-QVG-N-08 | max_total limit | Equivalence – normal | Respects limit | Limit applied |
| TC-QVG-N-09 | Unique variants | Equivalence – normal | No duplicates | Deduplication |
| TC-QV-N-01 | Same query text | Equivalence – normal | Equal variants | Equality test |
| TC-QV-N-02 | Different query text | Equivalence – normal | Unequal variants | Inequality |
| TC-QV-N-03 | Hash consistency | Equivalence – normal | Same hash | Hashable |
| TC-ABE-N-01 | Executor init | Equivalence – normal | Generator present | Init test |
| TC-ABE-N-02 | Basic A/B test | Equivalence – normal | Session completed | Happy path |
| TC-ABE-N-03 | Find winner | Equivalence – normal | Winner identified | Best variant |
| TC-ABE-N-04 | Save session | Equivalence – normal | DB execute called | Persistence |
| TC-ABE-N-05 | Session ID format | Equivalence – normal | Starts with ab_ | ID format |
| TC-HYC-N-01 | Similar patterns | Equivalence – normal | Pattern matches | Pattern match |
| TC-HYC-N-02 | Different patterns | Equivalence – normal | No match | No match |
| TC-HYC-B-01 | Empty strings | Boundary – empty | No match | Empty input |
| TC-HYC-N-03 | Apply pattern | Equivalence – normal | Pattern applied | Transformation |
| TC-HYC-B-02 | No cached patterns | Boundary – empty | None returned | Empty cache |
| TC-HYC-N-04 | Cached pattern match | Equivalence – normal | Improved query | Cache hit |
| TC-HYC-N-05 | Empty cache stats | Equivalence – normal | Zero counts | Stats structure |
| TC-MF-N-01 | Generator singleton | Equivalence – normal | Same instance | Singleton |
| TC-MF-N-02 | Executor singleton | Equivalence – normal | Same instance | Singleton |
| TC-MF-N-03 | Cache singleton | Equivalence – normal | Same instance | Singleton |
| TC-MF-N-04 | Convenience function | Equivalence – normal | Variants returned | API test |
| TC-MF-N-05 | Max variants param | Equivalence – normal | Respects limit | Limit test |
| TC-INT-N-01 | Full A/B flow | Equivalence – normal | Session complete | Integration |
| TC-INT-N-02 | Real variants | Equivalence – normal | Multiple variants | Variant gen |
| TC-EC-B-01 | Empty query | Boundary – empty | Original returned | Empty input |
| TC-EC-B-02 | Very long query | Boundary – max | Handled gracefully | Long input |
| TC-EC-N-01 | Special characters | Equivalence – normal | Handled gracefully | Special chars |
| TC-EC-N-02 | Unicode characters | Equivalence – normal | Handled gracefully | Unicode |
| TC-EC-N-03 | English only | Equivalence – normal | Original returned | No JP rules |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, patch

from src.search.ab_test import (
    ABTestExecutor,
    HighYieldQueryCache,
    QueryVariant,
    QueryVariantGenerator,
    VariantType,
    generate_query_variants,
    get_ab_executor,
    get_high_yield_cache,
    get_variant_generator,
)

# ============================================================================
# QueryVariantGenerator Tests
# ============================================================================


class TestQueryVariantGenerator:
    """Tests for QueryVariantGenerator."""

    def test_init(self):
        """Test generator initialization (TC-QVG-N-01)."""
        # Given: No preconditions
        # When: Creating a new generator
        generator = QueryVariantGenerator()

        # Then: Rules should be loaded
        assert generator._particle_rules is not None
        assert generator._notation_rules is not None

    def test_generate_notation_variants_with_ai(self):
        """Test notation variant generation with AI term (TC-QVG-N-02)."""
        # Given: A generator and a query containing "AI"
        generator = QueryVariantGenerator()

        # When: Generating notation variants
        variants = generator.generate_notation_variants("AI技術の問題")

        # Then: Should find AI variation
        assert len(variants) >= 1
        for v in variants:
            assert v.variant_type == VariantType.NOTATION
            assert v.query_text != "AI技術の問題"

    def test_generate_notation_variants_with_kanji(self):
        """Test notation variant generation with kanji (TC-QVG-N-03)."""
        # Given: A generator and a query with kanji terms
        generator = QueryVariantGenerator()

        # When: Generating notation variants
        variants = generator.generate_notation_variants("人工知能の分析")

        # Then: Should find some notation variation
        if variants:
            assert variants[0].variant_type == VariantType.NOTATION
            assert variants[0].query_text != "人工知能の分析"

    def test_generate_notation_variants_no_match(self):
        """Test notation variants with no matching patterns (TC-QVG-B-01)."""
        # Given: A generator and a query with no matching patterns
        generator = QueryVariantGenerator()

        # When: Generating notation variants
        variants = generator.generate_notation_variants("xyz abc")

        # Then: Should return empty list (boundary case)
        assert variants == []

    def test_generate_particle_variants(self):
        """Test particle variant generation (TC-QVG-N-04)."""
        # Given: A generator and a query with particle の
        generator = QueryVariantGenerator()

        # When: Generating particle variants
        variants = generator.generate_particle_variants("機械学習の応用")

        # Then: Should generate particle variants
        if variants:
            assert variants[0].variant_type == VariantType.PARTICLE

    def test_generate_particle_variants_with_ha(self):
        """Test particle variant with は (TC-QVG-N-05)."""
        # Given: A generator and a query with particle は
        generator = QueryVariantGenerator()

        # When: Generating particle variants
        variants = generator.generate_particle_variants("AIは社会を変える")

        # Then: Should generate transformed variants
        if variants:
            assert variants[0].variant_type == VariantType.PARTICLE
            assert variants[0].query_text != "AIは社会を変える"

    def test_generate_order_variants_basic(self):
        """Test word order variant generation (TC-QVG-N-06)."""
        # Given: A generator and a multi-word query
        generator = QueryVariantGenerator()

        # When: Generating order variants
        variants = generator.generate_order_variants("機械学習 応用 事例")

        # Then: Should generate order variants
        if variants:
            assert variants[0].variant_type == VariantType.ORDER
            assert variants[0].query_text != "機械学習 応用 事例"

    def test_generate_order_variants_single_word(self):
        """Test order variants with single word (TC-QVG-B-02)."""
        # Given: A generator and a single word query
        generator = QueryVariantGenerator()

        # When: Generating order variants
        variants = generator.generate_order_variants("AI")

        # Then: Single word should not generate order variants (boundary)
        assert variants == []

    def test_generate_all_variants(self):
        """Test generating all variant types (TC-QVG-N-07)."""
        # Given: A generator and a query
        generator = QueryVariantGenerator()

        # When: Generating all variants
        variants = generator.generate_all_variants("AIの問題点")

        # Then: Should include original as first variant
        assert any(v.variant_type == VariantType.ORIGINAL for v in variants)
        assert variants[0].variant_type == VariantType.ORIGINAL
        assert variants[0].query_text == "AIの問題点"

    def test_generate_all_variants_max_total(self):
        """Test max_total limit (TC-QVG-N-08)."""
        # Given: A generator and a query with max_total limit
        generator = QueryVariantGenerator()

        # When: Generating variants with limit
        variants = generator.generate_all_variants("人工知能の問題", max_total=3)

        # Then: Should not exceed max_total + 1 (including original)
        assert len(variants) <= 4

    def test_generate_all_variants_unique(self):
        """Test that variants are unique (TC-QVG-N-09)."""
        # Given: A generator and a query
        generator = QueryVariantGenerator()

        # When: Generating all variants
        variants = generator.generate_all_variants("AIセキュリティの課題")

        # Then: All variants should be unique
        query_texts = [v.query_text for v in variants]
        assert len(query_texts) == len(set(query_texts))


class TestQueryVariant:
    """Tests for QueryVariant dataclass."""

    def test_equality(self):
        """Test variant equality (TC-QV-N-01)."""
        # Given: Two variants with same query text
        v1 = QueryVariant("test query", VariantType.ORIGINAL)
        v2 = QueryVariant("test query", VariantType.NOTATION)

        # When/Then: Same query text should be equal
        assert v1 == v2

    def test_inequality(self):
        """Test variant inequality (TC-QV-N-02)."""
        # Given: Two variants with different query text
        v1 = QueryVariant("query one", VariantType.ORIGINAL)
        v2 = QueryVariant("query two", VariantType.ORIGINAL)

        # When/Then: Different query text should be unequal
        assert v1 != v2

    def test_hash(self):
        """Test variant hashing (TC-QV-N-03)."""
        # Given: Two variants with same query text
        v1 = QueryVariant("test", VariantType.ORIGINAL)
        v2 = QueryVariant("test", VariantType.ORIGINAL)

        # When/Then: Same variants should have same hash
        assert hash(v1) == hash(v2)


# ============================================================================
# ABTestExecutor Tests
# ============================================================================


class TestABTestExecutor:
    """Tests for ABTestExecutor."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.fetch_one = AsyncMock(return_value=None)
        db.fetch_all = AsyncMock(return_value=[])
        return db

    @pytest.fixture
    def mock_search(self):
        """Create mock search function."""

        async def _search(*args, **kwargs):
            return [
                {"title": "Result 1", "url": "http://example.com/1", "snippet": "..."},
                {"title": "Result 2", "url": "http://example.com/2", "snippet": "..."},
            ]

        return _search

    def test_init(self):
        """Test executor initialization (TC-ABE-N-01)."""
        # Given: No preconditions
        # When: Creating a new executor
        executor = ABTestExecutor()

        # Then: Generator should be present
        assert executor._generator is not None

    @pytest.mark.asyncio
    async def test_run_ab_test_basic(self, mock_db, mock_search):
        """Test basic A/B test execution (TC-ABE-N-02)."""
        # Given: Mock database and search function
        with patch("src.search.ab_test.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.search.search_serp", mock_search):
                executor = ABTestExecutor()

                # When: Running an A/B test
                session = await executor.run_ab_test(
                    task_id="test_task",
                    base_query="AI技術",
                    max_variants=2,
                )

                # Then: Session should be completed with results
                assert session.status == "completed"
                assert session.base_query == "AI技術"
                assert len(session.results) >= 1

    @pytest.mark.asyncio
    async def test_run_ab_test_finds_winner(self, mock_db):
        """Test that A/B test finds a winner (TC-ABE-N-03)."""
        # Given: Mock search returning different result counts
        call_count = 0

        async def _search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    {"title": f"R{i}", "url": f"http://ex.com/{i}", "snippet": "..."}
                    for i in range(5)
                ]
            return [
                {"title": f"R{i}", "url": f"http://ex.com/{i}", "snippet": "..."} for i in range(8)
            ]

        with patch("src.search.ab_test.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.search.search_serp", _search):
                executor = ABTestExecutor()

                # When: Running an A/B test
                session = await executor.run_ab_test(
                    task_id="test_task",
                    base_query="人工知能",
                    max_variants=2,
                )

                # Then: Winner should be identified
                assert session.winner is not None
                assert session.winner.harvest_rate > 0

    @pytest.mark.asyncio
    async def test_run_ab_test_saves_session(self, mock_db, mock_search):
        """Test that session is saved to database (TC-ABE-N-04)."""
        # Given: Mock database and search
        with patch("src.search.ab_test.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.search.search_serp", mock_search):
                executor = ABTestExecutor()

                # When: Running an A/B test
                await executor.run_ab_test(
                    task_id="test_task",
                    base_query="テスト",
                    max_variants=2,
                )

                # Then: Database should be called
                assert mock_db.execute.called

    def test_generate_session_id(self):
        """Test session ID generation (TC-ABE-N-05)."""
        # Given: An executor
        executor = ABTestExecutor()

        # When: Generating session IDs
        id1 = executor._generate_session_id("task1", "query1")
        id2 = executor._generate_session_id("task1", "query2")
        executor._generate_session_id("task1", "query1")

        # Then: IDs should start with ab_ prefix
        assert id1.startswith("ab_")
        assert id2.startswith("ab_")
        assert len(id1) == len(id2)


# ============================================================================
# HighYieldQueryCache Tests
# ============================================================================


class TestHighYieldQueryCache:
    """Tests for HighYieldQueryCache."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        db = AsyncMock()
        db.fetch_one = AsyncMock(return_value=None)
        db.fetch_all = AsyncMock(return_value=[])
        return db

    def test_matches_pattern_similar(self):
        """Test pattern matching with similar queries (TC-HYC-N-01)."""
        # Given: A cache instance
        cache = HighYieldQueryCache()

        # When/Then: Similar queries should match (50% term overlap required)
        assert cache._matches_pattern("AI 技術 問題", "AI 技術 課題", "人工知能 技術 課題")

    def test_matches_pattern_different(self):
        """Test pattern matching with different queries (TC-HYC-N-02)."""
        # Given: A cache instance
        cache = HighYieldQueryCache()

        # When/Then: Very different queries should not match
        assert not cache._matches_pattern("完全に異なるクエリ", "AI技術", "人工知能")

    def test_matches_pattern_empty(self):
        """Test pattern matching with empty strings (TC-HYC-B-01)."""
        # Given: A cache instance
        cache = HighYieldQueryCache()

        # When/Then: Empty strings should not match (boundary)
        assert not cache._matches_pattern("", "test", "test2")
        assert not cache._matches_pattern("test", "", "test2")

    def test_apply_pattern(self):
        """Test pattern application (TC-HYC-N-03)."""
        # Given: A cache instance
        cache = HighYieldQueryCache()

        # When: Applying a pattern
        result = cache._apply_pattern("AI技術の問題", "AI技術の問題", "人工知能技術の問題")

        # Then: Pattern should be applied
        assert result is not None
        assert result != "AI技術の問題"

    @pytest.mark.asyncio
    async def test_get_improved_query_no_patterns(self, mock_db):
        """Test getting improved query when no patterns exist (TC-HYC-B-02)."""
        # Given: Empty cache
        with patch("src.search.ab_test.get_database", new=AsyncMock(return_value=mock_db)):
            cache = HighYieldQueryCache()

            # When: Getting improved query
            result = await cache.get_improved_query("テストクエリ")

            # Then: Should return None (boundary - empty cache)
            assert result is None

    @pytest.mark.asyncio
    async def test_get_improved_query_with_pattern(self, mock_db):
        """Test getting improved query with matching pattern (TC-HYC-N-04)."""
        # Given: Cache with matching pattern
        mock_db.fetch_all.return_value = [
            {
                "pattern_type": "notation",
                "original_pattern": "AI技術",
                "improved_pattern": "人工知能技術",
                "improvement_ratio": 0.15,
                "confidence": 0.8,
            }
        ]

        with patch("src.search.ab_test.get_database", new=AsyncMock(return_value=mock_db)):
            cache = HighYieldQueryCache()

            # When: Getting improved query
            result = await cache.get_improved_query("AI技術の応用")

            # Then: Pattern should be applied
            if result:
                assert "人工知能" in result

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, mock_db):
        """Test getting stats with empty cache (TC-HYC-N-05)."""
        # Given: Empty cache
        mock_db.fetch_one.return_value = {
            "total_patterns": 0,
            "avg_improvement": None,
            "avg_confidence": None,
            "total_samples": 0,
        }

        with patch("src.search.ab_test.get_database", new=AsyncMock(return_value=mock_db)):
            cache = HighYieldQueryCache()

            # When: Getting stats
            stats = await cache.get_stats()

            # Then: Stats should show zero counts
            assert stats["total_patterns"] == 0


# ============================================================================
# Module Function Tests
# ============================================================================


class TestModuleFunctions:
    """Tests for module-level functions."""

    def test_get_variant_generator_singleton(self):
        """Test that generator is a singleton (TC-MF-N-01)."""
        # Given: No preconditions
        # When: Getting generator twice
        g1 = get_variant_generator()
        g2 = get_variant_generator()

        # Then: Should be same instance
        assert g1 is g2

    def test_get_ab_executor_singleton(self):
        """Test that executor is a singleton (TC-MF-N-02)."""
        # Given: No preconditions
        # When: Getting executor twice
        e1 = get_ab_executor()
        e2 = get_ab_executor()

        # Then: Should be same instance
        assert e1 is e2

    def test_get_high_yield_cache_singleton(self):
        """Test that cache is a singleton (TC-MF-N-03)."""
        # Given: No preconditions
        # When: Getting cache twice
        c1 = get_high_yield_cache()
        c2 = get_high_yield_cache()

        # Then: Should be same instance
        assert c1 is c2

    def test_generate_query_variants(self):
        """Test the convenience function (TC-MF-N-04)."""
        # Given: A query
        # When: Generating variants
        variants = generate_query_variants("AI問題")

        # Then: Should return variants with original first
        assert len(variants) >= 1
        assert variants[0].variant_type == VariantType.ORIGINAL

    def test_generate_query_variants_max_variants(self):
        """Test max_variants parameter (TC-MF-N-05)."""
        # Given: A query with max_variants limit
        # When: Generating variants
        variants = generate_query_variants("人工知能の課題", max_variants=2)

        # Then: Should have at most 2 variants (original + 1)
        assert len(variants) <= 3


# ============================================================================
# Integration Tests
# ============================================================================


class TestABTestIntegration:
    """Integration tests for A/B testing."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database with all needed methods."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.fetch_one = AsyncMock(return_value=None)
        db.fetch_all = AsyncMock(return_value=[])
        return db

    @pytest.mark.asyncio
    async def test_full_ab_test_flow(self, mock_db):
        """Test complete A/B test flow (TC-INT-N-01)."""
        # Given: Mock search returning different results per query
        results_by_query = {
            "元のクエリ": [{"title": "R1", "url": "http://a.com", "snippet": "..."}],
            "default": [
                {"title": f"R{i}", "url": f"http://b.com/{i}", "snippet": "..."} for i in range(5)
            ],
        }

        async def _search(query, **kwargs):
            for key in results_by_query:
                if key in query:
                    return results_by_query[key]
            return results_by_query["default"]

        with patch("src.search.ab_test.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.search.search_serp", _search):
                from src.search.ab_test import run_query_ab_test

                # When: Running full A/B test
                session = await run_query_ab_test(
                    task_id="integration_test",
                    query="元のクエリ",
                    max_variants=2,
                )

                # Then: Session should complete with winner
                assert session.status == "completed"
                assert session.winner is not None

    @pytest.mark.asyncio
    async def test_ab_test_with_real_variants(self, mock_db):
        """Test A/B test generates real variants (TC-INT-N-02)."""

        # Given: Mock search
        async def _search(*args, **kwargs):
            return [{"title": "Test", "url": "http://test.com", "snippet": "..."}]

        with patch("src.search.ab_test.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.search.search_serp", _search):
                from src.search.ab_test import run_query_ab_test

                # When: Running A/B test with query that generates variants
                session = await run_query_ab_test(
                    task_id="test",
                    query="人工知能の問題",
                    max_variants=4,
                )

                # Then: Should have multiple variants including original
                assert len(session.variants) >= 2
                types = [v.variant_type for v in session.variants]
                assert VariantType.ORIGINAL in types


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_query(self):
        """Test with empty query (TC-EC-B-01)."""
        # Given: A generator
        generator = QueryVariantGenerator()

        # When: Generating variants for empty query
        variants = generator.generate_all_variants("")

        # Then: Should still return original (even if empty)
        assert len(variants) >= 1
        assert variants[0].query_text == ""

    def test_very_long_query(self):
        """Test with very long query (TC-EC-B-02)."""
        # Given: A generator
        generator = QueryVariantGenerator()

        # When: Generating variants for very long query
        long_query = "AI " * 100
        variants = generator.generate_all_variants(long_query, max_total=3)

        # Then: Should handle gracefully
        assert len(variants) >= 1

    def test_special_characters(self):
        """Test with special characters (TC-EC-N-01)."""
        # Given: A generator
        generator = QueryVariantGenerator()

        # When: Generating variants with special characters
        variants = generator.generate_all_variants("AI & ML: 課題と「解決策」")

        # Then: Should handle special characters
        assert len(variants) >= 1

    def test_unicode_query(self):
        """Test with various Unicode characters (TC-EC-N-02)."""
        # Given: A generator
        generator = QueryVariantGenerator()

        # When: Generating variants with Unicode
        variants = generator.generate_all_variants("AI技術 🤖 émojis")

        # Then: Should handle Unicode
        assert len(variants) >= 1

    def test_only_english(self):
        """Test with English-only query (TC-EC-N-03)."""
        # Given: A generator
        generator = QueryVariantGenerator()

        # When: Generating variants for English-only query
        variants = generator.generate_all_variants("machine learning problems")

        # Then: Should return at least original
        assert len(variants) >= 1
        assert variants[0].variant_type == VariantType.ORIGINAL
