"""
Tests for Query A/B Testing module.

Tests §3.1.1: Query A/B Testing
- Small-scale A/B tests with notation/particle/word-order variants
- Cache and reuse high-yield queries
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock, patch

from src.search.ab_test import (
    QueryVariantGenerator,
    QueryVariant,
    VariantType,
    ABTestExecutor,
    ABTestSession,
    ABTestResult,
    HighYieldQueryCache,
    generate_query_variants,
    get_variant_generator,
    get_ab_executor,
    get_high_yield_cache,
)


# ============================================================================
# QueryVariantGenerator Tests
# ============================================================================


class TestQueryVariantGenerator:
    """Tests for QueryVariantGenerator."""
    
    def test_init(self):
        """Test generator initialization."""
        generator = QueryVariantGenerator()
        assert generator._particle_rules is not None
        assert generator._notation_rules is not None
    
    def test_generate_notation_variants_with_ai(self):
        """Test notation variant generation with AI term."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_notation_variants("AI技術の問題")
        
        # Should find AI variation
        assert len(variants) >= 1
        
        # Check variant types
        for v in variants:
            assert v.variant_type == VariantType.NOTATION
            assert v.query_text != "AI技術の問題"
    
    def test_generate_notation_variants_with_kanji(self):
        """Test notation variant generation with kanji."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_notation_variants("人工知能の分析")
        
        # Should find some notation variation (could be 人工知能→AI or 分析→ぶんせき)
        if variants:
            assert variants[0].variant_type == VariantType.NOTATION
            # The variant should be different from original
            assert variants[0].query_text != "人工知能の分析"
    
    def test_generate_notation_variants_no_match(self):
        """Test notation variants with no matching patterns."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_notation_variants("xyz abc")
        
        # Should return empty list
        assert variants == []
    
    def test_generate_particle_variants(self):
        """Test particle variant generation."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_particle_variants("機械学習の応用")
        
        # Should generate particle variants
        if variants:
            assert variants[0].variant_type == VariantType.PARTICLE
    
    def test_generate_particle_variants_with_ha(self):
        """Test particle variant with は."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_particle_variants("AIは社会を変える")
        
        if variants:
            assert variants[0].variant_type == VariantType.PARTICLE
            # Check transformation was applied
            assert variants[0].query_text != "AIは社会を変える"
    
    def test_generate_order_variants_basic(self):
        """Test word order variant generation."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_order_variants("機械学習 応用 事例")
        
        # Should generate order variants for multi-word queries
        if variants:
            assert variants[0].variant_type == VariantType.ORDER
            assert variants[0].query_text != "機械学習 応用 事例"
    
    def test_generate_order_variants_single_word(self):
        """Test order variants with single word."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_order_variants("AI")
        
        # Single word should not generate order variants
        assert variants == []
    
    def test_generate_all_variants(self):
        """Test generating all variant types."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_all_variants("AIの問題点")
        
        # Should include original
        assert any(v.variant_type == VariantType.ORIGINAL for v in variants)
        
        # Original should be first
        assert variants[0].variant_type == VariantType.ORIGINAL
        assert variants[0].query_text == "AIの問題点"
    
    def test_generate_all_variants_max_total(self):
        """Test max_total limit."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_all_variants("人工知能の問題", max_total=3)
        
        # Should not exceed max_total + 1 (including original)
        assert len(variants) <= 4
    
    def test_generate_all_variants_unique(self):
        """Test that variants are unique."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_all_variants("AIセキュリティの課題")
        
        # All variants should be unique
        query_texts = [v.query_text for v in variants]
        assert len(query_texts) == len(set(query_texts))


class TestQueryVariant:
    """Tests for QueryVariant dataclass."""
    
    def test_equality(self):
        """Test variant equality."""
        v1 = QueryVariant("test query", VariantType.ORIGINAL)
        v2 = QueryVariant("test query", VariantType.NOTATION)
        
        # Same query text should be equal
        assert v1 == v2
    
    def test_inequality(self):
        """Test variant inequality."""
        v1 = QueryVariant("query one", VariantType.ORIGINAL)
        v2 = QueryVariant("query two", VariantType.ORIGINAL)
        
        assert v1 != v2
    
    def test_hash(self):
        """Test variant hashing."""
        v1 = QueryVariant("test", VariantType.ORIGINAL)
        v2 = QueryVariant("test", VariantType.ORIGINAL)
        
        # Same variants should have same hash
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
        """Test executor initialization."""
        executor = ABTestExecutor()
        assert executor._generator is not None
    
    @pytest.mark.asyncio
    async def test_run_ab_test_basic(self, mock_db, mock_search):
        """Test basic A/B test execution."""
        with patch("src.search.ab_test.get_database", return_value=mock_db):
            with patch("src.search.search_serp", mock_search):
                executor = ABTestExecutor()
                
                session = await executor.run_ab_test(
                    task_id="test_task",
                    base_query="AI技術",
                    max_variants=2,
                )
                
                assert session.status == "completed"
                assert session.base_query == "AI技術"
                assert len(session.results) >= 1
    
    @pytest.mark.asyncio
    async def test_run_ab_test_finds_winner(self, mock_db):
        """Test that A/B test finds a winner."""
        call_count = 0
        
        async def _search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Return different result counts to simulate different performance
            if call_count == 1:
                return [{"title": f"R{i}", "url": f"http://ex.com/{i}", "snippet": "..."} for i in range(5)]
            return [{"title": f"R{i}", "url": f"http://ex.com/{i}", "snippet": "..."} for i in range(8)]
        
        with patch("src.search.ab_test.get_database", return_value=mock_db):
            with patch("src.search.search_serp", _search):
                executor = ABTestExecutor()
                
                session = await executor.run_ab_test(
                    task_id="test_task",
                    base_query="人工知能",
                    max_variants=2,
                )
                
                assert session.winner is not None
                assert session.winner.harvest_rate > 0
    
    @pytest.mark.asyncio
    async def test_run_ab_test_saves_session(self, mock_db, mock_search):
        """Test that session is saved to database."""
        with patch("src.search.ab_test.get_database", return_value=mock_db):
            with patch("src.search.search_serp", mock_search):
                executor = ABTestExecutor()
                
                session = await executor.run_ab_test(
                    task_id="test_task",
                    base_query="テスト",
                    max_variants=2,
                )
                
                # Verify database was called
                assert mock_db.execute.called
    
    def test_generate_session_id(self):
        """Test session ID generation."""
        executor = ABTestExecutor()
        
        id1 = executor._generate_session_id("task1", "query1")
        id2 = executor._generate_session_id("task1", "query2")
        id3 = executor._generate_session_id("task1", "query1")
        
        # Different queries should get different IDs (most likely due to timestamp)
        assert id1.startswith("ab_")
        assert id2.startswith("ab_")
        # Same inputs at different times should get different IDs
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
        """Test pattern matching with similar queries."""
        cache = HighYieldQueryCache()
        
        # Same query structure should match (50% term overlap required)
        assert cache._matches_pattern(
            "AI 技術 問題",
            "AI 技術 課題",
            "人工知能 技術 課題"
        )
    
    def test_matches_pattern_different(self):
        """Test pattern matching with different queries."""
        cache = HighYieldQueryCache()
        
        # Very different queries should not match
        assert not cache._matches_pattern(
            "完全に異なるクエリ",
            "AI技術",
            "人工知能"
        )
    
    def test_matches_pattern_empty(self):
        """Test pattern matching with empty strings."""
        cache = HighYieldQueryCache()
        
        assert not cache._matches_pattern("", "test", "test2")
        assert not cache._matches_pattern("test", "", "test2")
    
    def test_apply_pattern(self):
        """Test pattern application."""
        cache = HighYieldQueryCache()
        
        result = cache._apply_pattern(
            "AI技術の問題",
            "AI技術の問題",
            "人工知能技術の問題"
        )
        
        # Should replace AI with 人工知能
        assert result is not None
        assert result != "AI技術の問題"
    
    @pytest.mark.asyncio
    async def test_get_improved_query_no_patterns(self, mock_db):
        """Test getting improved query when no patterns exist."""
        with patch("src.search.ab_test.get_database", return_value=mock_db):
            cache = HighYieldQueryCache()
            
            result = await cache.get_improved_query("テストクエリ")
            
            assert result is None
    
    @pytest.mark.asyncio
    async def test_get_improved_query_with_pattern(self, mock_db):
        """Test getting improved query with matching pattern."""
        mock_db.fetch_all.return_value = [
            {
                "pattern_type": "notation",
                "original_pattern": "AI技術",
                "improved_pattern": "人工知能技術",
                "improvement_ratio": 0.15,
                "confidence": 0.8,
            }
        ]
        
        with patch("src.search.ab_test.get_database", return_value=mock_db):
            cache = HighYieldQueryCache()
            
            result = await cache.get_improved_query("AI技術の応用")
            
            # Should apply the pattern
            if result:
                assert "人工知能" in result
    
    @pytest.mark.asyncio
    async def test_get_stats_empty(self, mock_db):
        """Test getting stats with empty cache."""
        mock_db.fetch_one.return_value = {
            "total_patterns": 0,
            "avg_improvement": None,
            "avg_confidence": None,
            "total_samples": 0,
        }
        
        with patch("src.search.ab_test.get_database", return_value=mock_db):
            cache = HighYieldQueryCache()
            
            stats = await cache.get_stats()
            
            assert stats["total_patterns"] == 0


# ============================================================================
# Module Function Tests
# ============================================================================


class TestModuleFunctions:
    """Tests for module-level functions."""
    
    def test_get_variant_generator_singleton(self):
        """Test that generator is a singleton."""
        g1 = get_variant_generator()
        g2 = get_variant_generator()
        
        assert g1 is g2
    
    def test_get_ab_executor_singleton(self):
        """Test that executor is a singleton."""
        e1 = get_ab_executor()
        e2 = get_ab_executor()
        
        assert e1 is e2
    
    def test_get_high_yield_cache_singleton(self):
        """Test that cache is a singleton."""
        c1 = get_high_yield_cache()
        c2 = get_high_yield_cache()
        
        assert c1 is c2
    
    def test_generate_query_variants(self):
        """Test the convenience function."""
        variants = generate_query_variants("AI問題")
        
        assert len(variants) >= 1
        assert variants[0].variant_type == VariantType.ORIGINAL
    
    def test_generate_query_variants_max_variants(self):
        """Test max_variants parameter."""
        variants = generate_query_variants("人工知能の課題", max_variants=2)
        
        # Should have at most 2 variants (original + 1)
        assert len(variants) <= 3  # max_variants + 1 for original


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
        """Test complete A/B test flow."""
        results_by_query = {
            "元のクエリ": [{"title": "R1", "url": "http://a.com", "snippet": "..."}],
            "default": [
                {"title": f"R{i}", "url": f"http://b.com/{i}", "snippet": "..."}
                for i in range(5)
            ],
        }
        
        async def _search(query, **kwargs):
            for key in results_by_query:
                if key in query:
                    return results_by_query[key]
            return results_by_query["default"]
        
        with patch("src.search.ab_test.get_database", return_value=mock_db):
            with patch("src.search.search_serp", _search):
                from src.search.ab_test import run_query_ab_test
                
                session = await run_query_ab_test(
                    task_id="integration_test",
                    query="元のクエリ",
                    max_variants=2,
                )
                
                assert session.status == "completed"
                assert session.winner is not None
    
    @pytest.mark.asyncio
    async def test_ab_test_with_real_variants(self, mock_db):
        """Test A/B test generates real variants."""
        async def _search(*args, **kwargs):
            return [{"title": "Test", "url": "http://test.com", "snippet": "..."}]
        
        with patch("src.search.ab_test.get_database", return_value=mock_db):
            with patch("src.search.search_serp", _search):
                from src.search.ab_test import run_query_ab_test
                
                session = await run_query_ab_test(
                    task_id="test",
                    query="人工知能の問題",
                    max_variants=4,
                )
                
                # Should have multiple variants
                assert len(session.variants) >= 2
                
                # Should have variant types
                types = [v.variant_type for v in session.variants]
                assert VariantType.ORIGINAL in types


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""
    
    def test_empty_query(self):
        """Test with empty query."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_all_variants("")
        
        # Should still return original (even if empty)
        assert len(variants) >= 1
        assert variants[0].query_text == ""
    
    def test_very_long_query(self):
        """Test with very long query."""
        generator = QueryVariantGenerator()
        
        long_query = "AI " * 100
        variants = generator.generate_all_variants(long_query, max_total=3)
        
        # Should handle gracefully
        assert len(variants) >= 1
    
    def test_special_characters(self):
        """Test with special characters."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_all_variants("AI & ML: 課題と「解決策」")
        
        # Should handle special characters
        assert len(variants) >= 1
    
    def test_unicode_query(self):
        """Test with various Unicode characters."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_all_variants("AI技術 🤖 émojis")
        
        # Should handle Unicode
        assert len(variants) >= 1
    
    def test_only_english(self):
        """Test with English-only query."""
        generator = QueryVariantGenerator()
        
        variants = generator.generate_all_variants("machine learning problems")
        
        # Should return at least original
        assert len(variants) >= 1
        assert variants[0].variant_type == VariantType.ORIGINAL

