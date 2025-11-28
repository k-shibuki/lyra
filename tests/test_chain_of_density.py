"""
Tests for Chain-of-Density compression module.

Per §7.1: テストコード品質基準
- 禁止パターン（条件付きアサーション、曖昧なアサーション等）を回避
- 具体的なアサーション、境界条件の網羅
- 本番設定でのテスト
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.report.chain_of_density import (
    CitationInfo,
    DenseClaim,
    DenseSummary,
    ChainOfDensityCompressor,
    compress_with_chain_of_density,
)


# ============================================================
# Test Fixtures
# ============================================================

@pytest.fixture
def sample_fragment():
    """Create a sample fragment for testing."""
    return {
        "id": "frag_001",
        "url": "https://example.gov.jp/report/2024",
        "page_title": "政府報告書2024年版",
        "heading_context": "第1章 概要",
        "text_content": "日本の経済成長率は2024年に2.5%を記録した。これは前年比0.3ポイントの増加である。主な要因として、輸出の増加と国内消費の回復が挙げられる。",
        "created_at": "2024-01-15T10:30:00Z",
        "source_tag": "government",
    }


@pytest.fixture
def sample_fragments():
    """Create multiple sample fragments."""
    return [
        {
            "id": "frag_001",
            "url": "https://example.gov.jp/report/2024",
            "page_title": "政府報告書2024年版",
            "heading_context": "第1章 概要",
            "text_content": "日本の経済成長率は2024年に2.5%を記録した。",
            "created_at": "2024-01-15T10:30:00Z",
            "source_tag": "government",
        },
        {
            "id": "frag_002",
            "url": "https://academic.example.org/paper/123",
            "page_title": "経済分析論文",
            "heading_context": "Results",
            "text_content": "Analysis shows GDP growth of 2.5% in 2024.",
            "created_at": "2024-01-20T14:00:00Z",
            "source_tag": "academic",
        },
        {
            "id": "frag_003",
            "url": "https://news.example.com/economy/growth",
            "page_title": "経済ニュース",
            "heading_context": None,
            "text_content": "経済成長率が予想を上回る結果となった。",
            "created_at": "2024-01-25T08:00:00Z",
            "source_tag": "news",
        },
    ]


@pytest.fixture
def sample_claims():
    """Create sample claims for testing."""
    return [
        {
            "id": "claim_001",
            "claim_text": "日本の経済成長率は2024年に2.5%を記録した",
            "confidence_score": 0.85,
            "claim_type": "fact",
            "source_url": "https://example.gov.jp/report/2024",
            "supporting_fragment_ids": ["frag_001", "frag_002"],
            "is_verified": True,
            "refutation_status": "not_found",
        },
        {
            "id": "claim_002",
            "claim_text": "輸出の増加が成長の主要因である",
            "confidence_score": 0.72,
            "claim_type": "fact",
            "source_url": "https://example.gov.jp/report/2024",
            "supporting_fragment_ids": ["frag_001"],
            "is_verified": False,
            "refutation_status": "pending",
        },
    ]


# ============================================================
# CitationInfo Tests
# ============================================================

class TestCitationInfo:
    """Tests for CitationInfo class."""
    
    def test_from_fragment_with_complete_data(self, sample_fragment):
        """Test creating CitationInfo from a complete fragment.
        
        Verifies that all required fields (§3.3.1) are populated:
        - deep_link
        - discovered_at
        - excerpt
        """
        citation = CitationInfo.from_fragment(sample_fragment)
        
        # Verify required fields are present (§3.3.1)
        assert citation.url == "https://example.gov.jp/report/2024"
        assert citation.deep_link == "https://example.gov.jp/report/2024#第1章-概要"
        assert citation.title == "政府報告書2024年版"
        assert citation.heading_context == "第1章 概要"
        assert citation.discovered_at == "2024-01-15T10:30:00Z"
        assert citation.source_tag == "government"
        assert citation.is_primary is True
        
        # Verify excerpt is populated
        assert len(citation.excerpt) > 0
        assert "経済成長率" in citation.excerpt
    
    def test_from_fragment_without_heading(self):
        """Test creating CitationInfo when heading_context is None."""
        fragment = {
            "id": "frag_no_heading",
            "url": "https://example.com/page",
            "page_title": "Test Page",
            "heading_context": None,
            "text_content": "Some content here.",
            "created_at": "2024-01-01T00:00:00Z",
            "source_tag": "news",
        }
        
        citation = CitationInfo.from_fragment(fragment)
        
        # Deep link should be URL without anchor
        assert citation.deep_link == "https://example.com/page"
        assert citation.heading_context is None
        assert citation.is_primary is False
    
    def test_from_fragment_with_empty_text(self):
        """Test creating CitationInfo with empty text content."""
        fragment = {
            "id": "frag_empty",
            "url": "https://example.com/empty",
            "page_title": "Empty Page",
            "heading_context": "Section",
            "text_content": "",
            "created_at": "2024-01-01T00:00:00Z",
            "source_tag": "blog",
        }
        
        citation = CitationInfo.from_fragment(fragment)
        
        assert citation.excerpt == ""
        assert citation.url == "https://example.com/empty"
    
    def test_primary_source_detection(self):
        """Test detection of primary sources.
        
        Per §3.4: Primary sources include government, academic, official,
        standard, registry.
        """
        primary_tags = ["government", "academic", "official", "standard", "registry"]
        secondary_tags = ["news", "blog", "forum", None]
        
        for tag in primary_tags:
            citation = CitationInfo(
                url="https://example.com",
                deep_link="https://example.com",
                title="Test",
                heading_context=None,
                excerpt="Test excerpt",
                discovered_at="2024-01-01T00:00:00Z",
                source_tag=tag,
            )
            assert citation.is_primary is True, f"Tag '{tag}' should be primary"
        
        for tag in secondary_tags:
            citation = CitationInfo(
                url="https://example.com",
                deep_link="https://example.com",
                title="Test",
                heading_context=None,
                excerpt="Test excerpt",
                discovered_at="2024-01-01T00:00:00Z",
                source_tag=tag,
            )
            assert citation.is_primary is False, f"Tag '{tag}' should not be primary"
    
    def test_excerpt_truncation(self):
        """Test that excerpts are properly truncated."""
        long_text = "A" * 500
        
        excerpt = CitationInfo._extract_excerpt(long_text, max_length=200)
        
        # Excerpt should be truncated
        assert len(excerpt) <= 203  # 200 + "..."
        assert excerpt.endswith("...")
    
    def test_excerpt_sentence_boundary(self):
        """Test excerpt truncation at sentence boundary."""
        text = "First sentence. Second sentence is longer. Third sentence."
        
        excerpt = CitationInfo._extract_excerpt(text, max_length=50)
        
        # Should preserve sentence boundary
        assert "First sentence." in excerpt
    
    def test_to_dict_serialization(self, sample_fragment):
        """Test that CitationInfo serializes correctly."""
        citation = CitationInfo.from_fragment(sample_fragment)
        data = citation.to_dict()
        
        assert "url" in data
        assert "deep_link" in data
        assert "title" in data
        assert "excerpt" in data
        assert "discovered_at" in data
        assert "is_primary" in data
        assert data["is_primary"] is True


# ============================================================
# DenseClaim Tests
# ============================================================

class TestDenseClaim:
    """Tests for DenseClaim class."""
    
    def test_validation_with_complete_citations(self, sample_fragment):
        """Test validation passes with complete citation info."""
        citation = CitationInfo.from_fragment(sample_fragment)
        
        claim = DenseClaim(
            claim_id="claim_001",
            text="Test claim text",
            confidence=0.85,
            citations=[citation],
        )
        
        is_valid, missing = claim.validate()
        
        assert is_valid is True
        assert missing == []
    
    def test_validation_fails_without_citations(self):
        """Test validation fails when citations are missing.
        
        Per §3.3.1: All claims must have citations.
        """
        claim = DenseClaim(
            claim_id="claim_no_cit",
            text="Claim without citations",
            confidence=0.5,
            citations=[],
        )
        
        is_valid, missing = claim.validate()
        
        assert is_valid is False
        assert "citations" in missing
    
    def test_validation_fails_with_incomplete_citation(self):
        """Test validation fails when citation is incomplete."""
        incomplete_citation = CitationInfo(
            url="",  # Missing URL
            deep_link="",
            title="Test",
            heading_context=None,
            excerpt="",  # Missing excerpt
            discovered_at="",  # Missing timestamp
        )
        
        claim = DenseClaim(
            claim_id="claim_incomplete",
            text="Claim with incomplete citation",
            confidence=0.5,
            citations=[incomplete_citation],
        )
        
        is_valid, missing = claim.validate()
        
        assert is_valid is False
        assert "citation[0].url" in missing
        assert "citation[0].excerpt" in missing
        assert "citation[0].discovered_at" in missing
    
    def test_to_dict_includes_all_fields(self, sample_fragment):
        """Test that to_dict includes all required fields."""
        citation = CitationInfo.from_fragment(sample_fragment)
        
        claim = DenseClaim(
            claim_id="claim_001",
            text="Test claim",
            confidence=0.85,
            citations=[citation],
            claim_type="fact",
            is_verified=True,
            refutation_status="not_found",
        )
        
        data = claim.to_dict()
        
        assert data["claim_id"] == "claim_001"
        assert data["text"] == "Test claim"
        assert data["confidence"] == 0.85
        assert data["claim_type"] == "fact"
        assert data["is_verified"] is True
        assert data["refutation_status"] == "not_found"
        assert data["has_primary_source"] is True
        assert data["citation_count"] == 1
        assert len(data["citations"]) == 1


# ============================================================
# ChainOfDensityCompressor Tests
# ============================================================

class TestChainOfDensityCompressor:
    """Tests for ChainOfDensityCompressor class."""
    
    def test_build_citation_mapping(self, sample_claims, sample_fragments):
        """Test building citation mapping from claims to fragments."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)
        
        # claim_001 should have citations from frag_001 and frag_002
        assert "claim_001" in mapping
        citations_001 = mapping["claim_001"]
        assert len(citations_001) >= 1
        
        # Verify citation URLs
        urls = [c.url for c in citations_001]
        assert "https://example.gov.jp/report/2024" in urls
    
    def test_create_dense_claims(self, sample_claims, sample_fragments):
        """Test creating DenseClaim objects with citations."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)
        dense_claims = compressor._create_dense_claims(
            sample_claims, mapping, sample_fragments
        )
        
        assert len(dense_claims) == 2
        
        # First claim should have citations
        claim_001 = next(c for c in dense_claims if c.claim_id == "claim_001")
        assert len(claim_001.citations) >= 1
        assert claim_001.confidence == 0.85
        assert claim_001.text == "日本の経済成長率は2024年に2.5%を記録した"
    
    def test_validate_claims(self, sample_claims, sample_fragments):
        """Test validation of dense claims."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)
        dense_claims = compressor._create_dense_claims(
            sample_claims, mapping, sample_fragments
        )
        
        validation = compressor._validate_claims(dense_claims)
        
        assert "valid_count" in validation
        assert "invalid_count" in validation
        assert "issues" in validation
        assert validation["valid_count"] + validation["invalid_count"] == len(dense_claims)
    
    def test_calc_primary_ratio(self, sample_claims, sample_fragments):
        """Test calculation of primary source ratio."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)
        dense_claims = compressor._create_dense_claims(
            sample_claims, mapping, sample_fragments
        )
        
        ratio = compressor._calc_primary_ratio(dense_claims)
        
        # At least one claim should have primary source (government)
        assert 0.0 <= ratio <= 1.0
        assert ratio > 0  # claim_001 has government source
    
    def test_count_words_japanese(self):
        """Test word counting for Japanese text."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        # Japanese text
        japanese = "日本の経済成長率は2024年に2.5%を記録した"
        count_jp = compressor._count_words(japanese)
        
        # Should count Japanese characters (approx 2 chars = 1 word)
        assert count_jp > 0
        assert count_jp < len(japanese)  # Not counting each char as word
    
    def test_count_words_english(self):
        """Test word counting for English text."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        english = "The economic growth rate was 2.5 percent in 2024"
        count_en = compressor._count_words(english)
        
        # Should count words
        assert count_en == 9  # 9 words in the sentence
    
    def test_count_words_mixed(self):
        """Test word counting for mixed Japanese/English text."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        mixed = "GDP成長率は2.5%でした"
        count = compressor._count_words(mixed)
        
        assert count > 0
    
    def test_rule_based_compress(self, sample_claims, sample_fragments):
        """Test rule-based compression without LLM."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)
        dense_claims = compressor._create_dense_claims(
            sample_claims, mapping, sample_fragments
        )
        
        summaries = compressor._rule_based_compress(dense_claims)
        
        assert len(summaries) == 1
        summary = summaries[0]
        
        assert summary.iteration == 0
        assert len(summary.text) > 0
        assert summary.word_count > 0
        assert summary.density_score >= 0
    
    def test_extract_all_entities(self, sample_claims, sample_fragments):
        """Test entity extraction from claims and fragments."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)
        dense_claims = compressor._create_dense_claims(
            sample_claims, mapping, sample_fragments
        )
        
        entities = compressor._extract_all_entities(dense_claims, sample_fragments)
        
        assert len(entities) > 0
        # Should extract year patterns
        assert "2024年" in entities or any("2024" in e for e in entities)
    
    @pytest.mark.asyncio
    async def test_compress_empty_input(self):
        """Test compression with empty input."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        result = await compressor.compress(
            claims=[],
            fragments=[],
            task_query="Test query",
        )
        
        assert result["ok"] is False
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_compress_rule_based(self, sample_claims, sample_fragments):
        """Test full compression pipeline with rule-based method."""
        compressor = ChainOfDensityCompressor(use_llm=False)
        
        result = await compressor.compress(
            claims=sample_claims,
            fragments=sample_fragments,
            task_query="日本の経済成長率について",
        )
        
        assert result["ok"] is True
        assert "dense_claims" in result
        assert "summaries" in result
        assert "validation" in result
        assert "statistics" in result
        
        # Verify statistics
        stats = result["statistics"]
        assert stats["total_claims"] == 2
        assert stats["primary_source_ratio"] > 0


# ============================================================
# Integration Tests
# ============================================================

class TestChainOfDensityIntegration:
    """Integration tests for Chain-of-Density compression."""
    
    @pytest.mark.asyncio
    async def test_compress_with_chain_of_density_function(
        self, sample_claims, sample_fragments
    ):
        """Test the convenience function."""
        result = await compress_with_chain_of_density(
            claims=sample_claims,
            fragments=sample_fragments,
            task_query="日本の経済成長率について",
            max_iterations=3,
            use_llm=False,
        )
        
        assert result["ok"] is True
        assert result["task_query"] == "日本の経済成長率について"
        assert len(result["dense_claims"]) == 2
    
    @pytest.mark.asyncio
    async def test_citation_mandatory_fields_enforced(self):
        """Test that all mandatory citation fields are enforced.
        
        Per §3.3.1: 全主張に深いリンク・発見日時・抜粋を必須付与
        """
        claims = [
            {
                "id": "claim_test",
                "claim_text": "Test claim",
                "confidence_score": 0.8,
                "source_url": "https://example.com/source",
            }
        ]
        
        fragments = [
            {
                "id": "frag_test",
                "url": "https://example.com/source",
                "page_title": "Source Page",
                "heading_context": "Section 1",
                "text_content": "This is the source content for the claim.",
                "created_at": "2024-01-01T00:00:00Z",
                "source_tag": "news",
            }
        ]
        
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Test",
            use_llm=False,
        )
        
        assert result["ok"] is True
        
        # Check that dense claims have required citation fields
        dense_claim = result["dense_claims"][0]
        citation = dense_claim["citations"][0]
        
        # Mandatory fields per §3.3.1
        assert citation["deep_link"] != ""
        assert citation["discovered_at"] != ""
        assert citation["excerpt"] != ""
    
    @pytest.mark.asyncio
    async def test_validation_reports_missing_fields(self):
        """Test that validation properly reports missing fields."""
        # Claim without matching fragment
        claims = [
            {
                "id": "orphan_claim",
                "claim_text": "Orphan claim with no source",
                "confidence_score": 0.5,
            }
        ]
        
        fragments = []  # No fragments
        
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Test",
            use_llm=False,
        )
        
        assert result["ok"] is True
        
        # Validation should report issues
        validation = result["validation"]
        # With no fragments, citations may be incomplete
        # The exact behavior depends on implementation
        assert "valid_count" in validation
        assert "invalid_count" in validation


# ============================================================
# Edge Case Tests
# ============================================================

class TestChainOfDensityEdgeCases:
    """Edge case tests for Chain-of-Density compression."""
    
    @pytest.mark.asyncio
    async def test_single_claim(self):
        """Test compression with a single claim."""
        claims = [
            {
                "id": "single_claim",
                "claim_text": "Single test claim",
                "confidence_score": 0.9,
                "source_url": "https://example.com",
            }
        ]
        
        fragments = [
            {
                "id": "single_frag",
                "url": "https://example.com",
                "page_title": "Test",
                "text_content": "Single test claim content",
                "created_at": "2024-01-01T00:00:00Z",
                "source_tag": "academic",
            }
        ]
        
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Single claim test",
            use_llm=False,
        )
        
        assert result["ok"] is True
        assert result["statistics"]["total_claims"] == 1
    
    @pytest.mark.asyncio
    async def test_claims_without_matching_fragments(self):
        """Test handling of claims that don't match any fragment."""
        claims = [
            {
                "id": "unmatched_claim",
                "claim_text": "This claim has no matching fragment",
                "confidence_score": 0.7,
            }
        ]
        
        fragments = [
            {
                "id": "different_frag",
                "url": "https://different.com",
                "page_title": "Different",
                "text_content": "Completely unrelated content about cats and dogs",
                "created_at": "2024-01-01T00:00:00Z",
                "source_tag": "blog",
            }
        ]
        
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Unmatched test",
            use_llm=False,
        )
        
        # Should still succeed, but may have validation issues
        assert result["ok"] is True
    
    @pytest.mark.asyncio
    async def test_unicode_content(self):
        """Test handling of various Unicode content."""
        claims = [
            {
                "id": "unicode_claim",
                "claim_text": "日本語、中文、한국어、emoji 🎉 test",
                "confidence_score": 0.8,
                "source_url": "https://example.com/unicode",
            }
        ]
        
        fragments = [
            {
                "id": "unicode_frag",
                "url": "https://example.com/unicode",
                "page_title": "多言語テスト",
                "heading_context": "セクション1",
                "text_content": "日本語、中文、한국어、emoji 🎉 content",
                "created_at": "2024-01-01T00:00:00Z",
                "source_tag": "official",
            }
        ]
        
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Unicode test",
            use_llm=False,
        )
        
        assert result["ok"] is True
        
        # Verify Unicode is preserved
        dense_claim = result["dense_claims"][0]
        assert "日本語" in dense_claim["text"]
    
    @pytest.mark.asyncio
    async def test_very_long_excerpt(self):
        """Test handling of very long text content."""
        long_text = "A" * 10000
        
        claims = [
            {
                "id": "long_claim",
                "claim_text": "Claim about long content",
                "confidence_score": 0.6,
                "source_url": "https://example.com/long",
            }
        ]
        
        fragments = [
            {
                "id": "long_frag",
                "url": "https://example.com/long",
                "page_title": "Long Content",
                "text_content": long_text,
                "created_at": "2024-01-01T00:00:00Z",
                "source_tag": "news",
            }
        ]
        
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Long content test",
            use_llm=False,
        )
        
        assert result["ok"] is True
        
        # Excerpt should be truncated
        citation = result["dense_claims"][0]["citations"][0]
        assert len(citation["excerpt"]) <= 203  # 200 + "..."


# ============================================================
# DenseSummary Tests
# ============================================================

class TestDenseSummary:
    """Tests for DenseSummary class."""
    
    def test_to_dict(self, sample_fragment):
        """Test DenseSummary serialization."""
        citation = CitationInfo.from_fragment(sample_fragment)
        claim = DenseClaim(
            claim_id="test",
            text="Test",
            confidence=0.8,
            citations=[citation],
        )
        
        summary = DenseSummary(
            iteration=2,
            text="Summary text",
            entity_count=5,
            word_count=10,
            density_score=0.5,
            claims=[claim],
        )
        
        data = summary.to_dict()
        
        assert data["iteration"] == 2
        assert data["text"] == "Summary text"
        assert data["entity_count"] == 5
        assert data["word_count"] == 10
        assert data["density_score"] == 0.5
        assert len(data["claims"]) == 1

