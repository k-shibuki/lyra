"""
Tests for Chain-of-Density compression module.

Per .1: Test Code Quality Standards
- Avoid prohibited patterns (conditional assertions, vague assertions, etc.)
- Cover specific assertions and boundary conditions
- Test with production settings

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-CI-01 | Complete fragment data | Equivalence – normal | CitationInfo with all fields populated | - |
| TC-CI-02 | Fragment without heading | Equivalence – missing heading | deep_link is URL only, is_primary=False | - |
| TC-CI-03 | Fragment with empty text | Boundary – empty content | excerpt is empty string | - |
| TC-CI-04 | Primary source tags | Equivalence – source detection | is_primary=True for government/academic | - |
| TC-CI-05 | Secondary source tags | Equivalence – source detection | is_primary=False for news/blog | - |
| TC-CI-06 | Long text for excerpt | Boundary – truncation | Excerpt ≤203 chars with "..." | - |
| TC-CI-07 | Text with sentence boundaries | Equivalence – sentence boundary | Preserves sentence boundary | - |
| TC-CI-08 | CitationInfo serialization | Equivalence – serialization | to_dict contains all fields | - |
| TC-DC-01 | DenseClaim with complete citation | Equivalence – validation | is_valid=True, missing=[] | - |
| TC-DC-02 | DenseClaim without citations | Boundary – missing | is_valid=False, "citations" in missing | - |
| TC-DC-03 | DenseClaim with incomplete citation | Abnormal – incomplete | is_valid=False, specific fields missing | - |
| TC-DC-04 | DenseClaim serialization | Equivalence – serialization | to_dict contains all fields | - |
| TC-CODC-01 | Build citation mapping | Equivalence – mapping | Claims mapped to fragments by URL | - |
| TC-CODC-02 | Create dense claims | Equivalence – creation | DenseClaim objects with citations | - |
| TC-CODC-03 | Validate claims | Equivalence – validation | Returns valid/invalid counts and issues | - |
| TC-CODC-04 | Calculate primary ratio | Equivalence – calculation | Ratio between 0.0 and 1.0 | - |
| TC-CODC-05 | Count words Japanese | Equivalence – word count | Reasonable count for Japanese text | - |
| TC-CODC-06 | Count words English | Equivalence – word count | Accurate count (9 words) | - |
| TC-CODC-07 | Count words mixed | Equivalence – word count | Reasonable count for mixed text | - |
| TC-CODC-08 | Rule-based compress | Equivalence – compression | DenseSummary with text and score | - |
| TC-CODC-09 | Extract entities | Equivalence – extraction | Extracts year patterns etc. | - |
| TC-CODC-10 | Compress empty input | Boundary – empty | ok=False with error | - |
| TC-CODC-11 | Full compression | Equivalence – end-to-end | ok=True with all sections | - |
| TC-INT-01 | Convenience function | Integration – function | Complete result structure | - |
| TC-INT-02 | Mandatory fields | Integration – enforcement | deep_link, discovered_at, excerpt populated | - |
| TC-INT-03 | Validation reports | Integration – reporting | Reports missing fields correctly | - |
| TC-EC-01 | Single claim | Boundary – single | Handles gracefully | - |
| TC-EC-02 | Unmatched claims | Abnormal – no match | Processes with validation issues | - |
| TC-EC-03 | Unicode content | Equivalence – Unicode | Preserves characters | - |
| TC-EC-04 | Very long excerpt | Boundary – long text | Truncated properly | - |
| TC-DS-01 | DenseSummary serialization | Equivalence – serialization | to_dict contains all fields | - |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

from src.report.chain_of_density import (
    ChainOfDensityCompressor,
    CitationInfo,
    DenseClaim,
    DenseSummary,
    compress_with_chain_of_density,
)

# ============================================================
# Test Fixtures
# ============================================================


@pytest.fixture
def sample_fragment() -> dict[str, object]:
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
def sample_fragments() -> list[dict[str, object]]:
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
def sample_claims() -> list[dict[str, object]]:
    """Create sample claims for testing."""
    return [
        {
            "id": "claim_001",
            "claim_text": "日本の経済成長率は2024年に2.5%を記録した",
            "claim_confidence": 0.85,
            "claim_type": "fact",
            "source_url": "https://example.gov.jp/report/2024",
            "supporting_fragment_ids": ["frag_001", "frag_002"],
            "refutation_status": "not_found",
        },
        {
            "id": "claim_002",
            "claim_text": "輸出の増加が成長の主要因である",
            "claim_confidence": 0.72,
            "claim_type": "fact",
            "source_url": "https://example.gov.jp/report/2024",
            "supporting_fragment_ids": ["frag_001"],
            "refutation_status": "pending",
        },
    ]


# ============================================================
# CitationInfo Tests
# ============================================================


class TestCitationInfo:
    """Tests for CitationInfo class."""

    def test_from_fragment_with_complete_data(self, sample_fragment: dict[str, object]) -> None:
        """Test creating CitationInfo from a complete fragment.

        Verifies that all required fields are populated:
        - deep_link
        - discovered_at
        - excerpt
        """
        # Given: Complete fragment with all fields
        # When: Creating CitationInfo
        citation = CitationInfo.from_fragment(sample_fragment)

        # Then: All fields are correctly populated
        assert citation.url == "https://example.gov.jp/report/2024"
        assert citation.deep_link == "https://example.gov.jp/report/2024#第1章-概要"
        assert citation.title == "政府報告書2024年版"
        assert citation.heading_context == "第1章 概要"
        assert citation.discovered_at == "2024-01-15T10:30:00Z"
        assert citation.source_tag == "government"
        assert citation.is_primary is True
        assert (
            "経済成長率" in citation.excerpt
        ), f"Expected '経済成長率' in excerpt: {citation.excerpt}"

    def test_from_fragment_without_heading(self) -> None:
        """Test creating CitationInfo when heading_context is None."""
        # Given: Fragment without heading_context
        fragment = {
            "id": "frag_no_heading",
            "url": "https://example.com/page",
            "page_title": "Test Page",
            "heading_context": None,
            "text_content": "Some content here.",
            "created_at": "2024-01-01T00:00:00Z",
            "source_tag": "news",
        }

        # When: Creating CitationInfo
        citation = CitationInfo.from_fragment(fragment)

        # Then: Deep link is URL only, is_primary is False
        assert citation.deep_link == "https://example.com/page"
        assert citation.heading_context is None
        assert citation.is_primary is False

    def test_from_fragment_with_empty_text(self) -> None:
        """Test creating CitationInfo with empty text content."""
        # Given: Fragment with empty text_content
        fragment = {
            "id": "frag_empty",
            "url": "https://example.com/empty",
            "page_title": "Empty Page",
            "heading_context": "Section",
            "text_content": "",
            "created_at": "2024-01-01T00:00:00Z",
            "source_tag": "blog",
        }

        # When: Creating CitationInfo
        citation = CitationInfo.from_fragment(fragment)

        # Then: Excerpt is empty
        assert citation.excerpt == ""
        assert citation.url == "https://example.com/empty"

    def test_primary_source_detection(self) -> None:
        """Test detection of primary sources.

        Per ADR-0005: Primary sources include government, academic, official,
        standard, registry.
        """
        # Given: Primary source tags
        primary_tags: list[str] = ["government", "academic", "official", "standard", "registry"]
        secondary_tags: list[str | None] = ["news", "blog", "forum", None]

        # When/Then: Primary tags result in is_primary=True
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

        # When/Then: Secondary tags result in is_primary=False
        secondary_tag: str | None
        for secondary_tag in secondary_tags:
            citation = CitationInfo(
                url="https://example.com",
                deep_link="https://example.com",
                title="Test",
                heading_context=None,
                excerpt="Test excerpt",
                discovered_at="2024-01-01T00:00:00Z",
                source_tag=secondary_tag,
            )
            assert citation.is_primary is False, f"Tag '{secondary_tag}' should not be primary"

    def test_excerpt_truncation(self) -> None:
        """Test that excerpts are properly truncated."""
        # Given: Text longer than max_length
        long_text = "A" * 500

        # When: Extracting excerpt with max_length=200
        excerpt = CitationInfo._extract_excerpt(long_text, max_length=200)

        # Then: Excerpt is truncated with ellipsis
        assert len(excerpt) <= 203  # 200 + "..."
        assert excerpt.endswith("...")

    def test_excerpt_sentence_boundary(self) -> None:
        """Test excerpt truncation at sentence boundary."""
        # Given: Text with sentence boundaries
        text = "First sentence. Second sentence is longer. Third sentence."

        # When: Extracting excerpt with max_length=50
        excerpt = CitationInfo._extract_excerpt(text, max_length=50)

        # Then: Preserves sentence boundary
        assert "First sentence." in excerpt

    def test_to_dict_serialization(self, sample_fragment: dict[str, object]) -> None:
        """Test that CitationInfo serializes correctly."""
        # Given: CitationInfo from fragment
        citation = CitationInfo.from_fragment(sample_fragment)

        # When: Serializing to dict
        data = citation.to_dict()

        # Then: All fields present
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

    def test_validation_with_complete_citations(self, sample_fragment: dict[str, object]) -> None:
        """Test validation passes with complete citation info."""
        # Given: DenseClaim with complete citation
        citation = CitationInfo.from_fragment(sample_fragment)
        claim = DenseClaim(
            claim_id="claim_001",
            text="Test claim text",
            confidence=0.85,
            citations=[citation],
        )

        # When: Validating the claim
        is_valid, missing = claim.validate()

        # Then: Validation passes
        assert is_valid is True
        assert missing == []

    def test_validation_fails_without_citations(self) -> None:
        """Test validation fails when citations are missing.

        All claims must have citations.
        """
        # Given: DenseClaim without citations
        claim = DenseClaim(
            claim_id="claim_no_cit",
            text="Claim without citations",
            confidence=0.5,
            citations=[],
        )

        # When: Validating the claim
        is_valid, missing = claim.validate()

        # Then: Validation fails with "citations" missing
        assert is_valid is False
        assert "citations" in missing

    def test_validation_fails_with_incomplete_citation(self) -> None:
        """Test validation fails when citation is incomplete."""
        # Given: DenseClaim with incomplete citation
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

        # When: Validating the claim
        is_valid, missing = claim.validate()

        # Then: Validation fails with specific fields missing
        assert is_valid is False
        assert "citation[0].url" in missing
        assert "citation[0].excerpt" in missing
        assert "citation[0].discovered_at" in missing

    def test_to_dict_includes_all_fields(self, sample_fragment: dict[str, object]) -> None:
        """Test that to_dict includes all required fields."""
        # Given: DenseClaim with all fields
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

        # When: Serializing to dict
        data = claim.to_dict()

        # Then: All fields present with correct values
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

    def test_build_citation_mapping(
        self, sample_claims: list[dict[str, object]], sample_fragments: list[dict[str, object]]
    ) -> None:
        """Test building citation mapping from claims to fragments."""
        # Given: Compressor and sample data
        compressor = ChainOfDensityCompressor(use_llm=False)

        # When: Building citation mapping
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)

        # Then: Claims mapped to fragments by URL
        assert "claim_001" in mapping
        citations_001 = mapping["claim_001"]
        assert len(citations_001) >= 1
        urls = [c.url for c in citations_001]
        assert "https://example.gov.jp/report/2024" in urls

    def test_create_dense_claims(
        self, sample_claims: list[dict[str, object]], sample_fragments: list[dict[str, object]]
    ) -> None:
        """Test creating DenseClaim objects with citations."""
        # Given: Compressor and citation mapping
        compressor = ChainOfDensityCompressor(use_llm=False)
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)

        # When: Creating dense claims
        dense_claims = compressor._create_dense_claims(sample_claims, mapping, sample_fragments)

        # Then: DenseClaim objects have citations
        assert len(dense_claims) == 2
        claim_001 = next(c for c in dense_claims if c.claim_id == "claim_001")
        assert len(claim_001.citations) >= 1
        assert claim_001.confidence == 0.85
        assert claim_001.text == "日本の経済成長率は2024年に2.5%を記録した"

    def test_validate_claims(
        self, sample_claims: list[dict[str, object]], sample_fragments: list[dict[str, object]]
    ) -> None:
        """Test validation of dense claims."""
        # Given: Dense claims
        compressor = ChainOfDensityCompressor(use_llm=False)
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)
        dense_claims = compressor._create_dense_claims(sample_claims, mapping, sample_fragments)

        # When: Validating claims
        validation = compressor._validate_claims(dense_claims)

        # Then: Returns validation stats
        assert "valid_count" in validation
        assert "invalid_count" in validation
        assert "issues" in validation
        assert validation["valid_count"] + validation["invalid_count"] == len(dense_claims)

    def test_calc_primary_ratio(
        self, sample_claims: list[dict[str, object]], sample_fragments: list[dict[str, object]]
    ) -> None:
        """Test calculation of primary source ratio."""
        # Given: Dense claims with primary sources
        compressor = ChainOfDensityCompressor(use_llm=False)
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)
        dense_claims = compressor._create_dense_claims(sample_claims, mapping, sample_fragments)

        # When: Calculating primary ratio
        ratio = compressor._calc_primary_ratio(dense_claims)

        # Then: Ratio is valid and > 0 (government source)
        assert 0.0 <= ratio <= 1.0
        assert ratio > 0

    def test_count_words_japanese(self) -> None:
        """Test word counting for Japanese text."""
        # Given: Japanese text
        compressor = ChainOfDensityCompressor(use_llm=False)
        japanese = "日本の経済成長率は2024年に2.5%を記録した"

        # When: Counting words
        count_jp = compressor._count_words(japanese)

        # Then: Reasonable word count
        assert count_jp > 0
        assert count_jp < len(japanese)

    def test_count_words_english(self) -> None:
        """Test word counting for English text."""
        # Given: English text with 9 words
        compressor = ChainOfDensityCompressor(use_llm=False)
        english = "The economic growth rate was 2.5 percent in 2024"

        # When: Counting words
        count_en = compressor._count_words(english)

        # Then: Accurate count
        assert count_en == 9

    def test_count_words_mixed(self) -> None:
        """Test word counting for mixed Japanese/English text."""
        # Given: Mixed text
        compressor = ChainOfDensityCompressor(use_llm=False)
        mixed = "GDP成長率は2.5%でした"

        # When: Counting words
        count = compressor._count_words(mixed)

        # Then: Non-zero count
        assert count > 0

    def test_rule_based_compress(
        self, sample_claims: list[dict[str, object]], sample_fragments: list[dict[str, object]]
    ) -> None:
        """Test rule-based compression without LLM."""
        # Given: Dense claims
        compressor = ChainOfDensityCompressor(use_llm=False)
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)
        dense_claims = compressor._create_dense_claims(sample_claims, mapping, sample_fragments)

        # When: Compressing with rule-based method
        summaries = compressor._rule_based_compress(dense_claims)

        # Then: Summary generated with valid metrics
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.iteration == 0
        assert summary.word_count > 0, f"Expected word_count > 0, got {summary.word_count}"
        assert len(summary.text) >= 10, f"Expected text >=10 chars, got: {summary.text}"
        assert summary.density_score >= 0

    def test_extract_all_entities(
        self, sample_claims: list[dict[str, object]], sample_fragments: list[dict[str, object]]
    ) -> None:
        """Test entity extraction from claims and fragments."""
        # Given: Dense claims
        compressor = ChainOfDensityCompressor(use_llm=False)
        mapping = compressor._build_citation_mapping(sample_claims, sample_fragments)
        dense_claims = compressor._create_dense_claims(sample_claims, mapping, sample_fragments)

        # When: Extracting entities
        entities = compressor._extract_all_entities(dense_claims, sample_fragments)

        # Then: Extracts year patterns
        assert len(entities) >= 1, f"Expected at least 1 entity, got {len(entities)}"
        has_year = any("2024" in str(e) for e in entities)
        assert has_year, f"Expected '2024' in entities: {entities}"

    @pytest.mark.asyncio
    async def test_compress_empty_input(self) -> None:
        """Test compression with empty input."""
        # Given: Compressor with empty input
        compressor = ChainOfDensityCompressor(use_llm=False)

        # When: Compressing empty claims/fragments
        result = await compressor.compress(
            claims=[],
            fragments=[],
            task_query="Test query",
        )

        # Then: Returns error
        assert result["ok"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_compress_rule_based(
        self, sample_claims: list[dict[str, object]], sample_fragments: list[dict[str, object]]
    ) -> None:
        """Test full compression pipeline with rule-based method."""
        # Given: Compressor with sample data
        compressor = ChainOfDensityCompressor(use_llm=False)

        # When: Compressing
        result = await compressor.compress(
            claims=sample_claims,
            fragments=sample_fragments,
            task_query="日本の経済成長率について",
        )

        # Then: Complete result with all sections
        assert result["ok"] is True
        assert "dense_claims" in result
        assert "summaries" in result
        assert "validation" in result
        assert "statistics" in result
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
        self, sample_claims: list[dict[str, object]], sample_fragments: list[dict[str, object]]
    ) -> None:
        """Test the convenience function."""
        # Given: Sample claims and fragments
        # When: Using convenience function
        result = await compress_with_chain_of_density(
            claims=sample_claims,
            fragments=sample_fragments,
            task_query="日本の経済成長率について",
            max_iterations=3,
            use_llm=False,
        )

        # Then: Complete result structure
        assert result["ok"] is True
        assert result["task_query"] == "日本の経済成長率について"
        assert len(result["dense_claims"]) == 2

    @pytest.mark.asyncio
    async def test_citation_mandatory_fields_enforced(self) -> None:
        """Test that all mandatory citation fields are enforced.

        Require deep links, discovery timestamps, and excerpts for all claims.
        """
        # Given: Claim with matching fragment
        claims = [
            {
                "id": "claim_test",
                "claim_text": "Test claim",
                "claim_confidence": 0.8,
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

        # When: Compressing
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Test",
            use_llm=False,
        )

        # Then: Mandatory fields are populated
        assert result["ok"] is True
        dense_claim = result["dense_claims"][0]
        citation = dense_claim["citations"][0]
        assert citation["deep_link"] != ""
        assert citation["discovered_at"] != ""
        assert citation["excerpt"] != ""

    @pytest.mark.asyncio
    async def test_validation_reports_missing_fields(self) -> None:
        """Test that validation properly reports missing fields."""
        # Given: Claim without matching fragment
        claims = [
            {
                "id": "orphan_claim",
                "claim_text": "Orphan claim with no source",
                "claim_confidence": 0.5,
            }
        ]
        fragments: list[dict[str, object]] = []  # No fragments

        # When: Compressing
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Test",
            use_llm=False,
        )

        # Then: Validation reports issues
        assert result["ok"] is True
        validation = result["validation"]
        assert "valid_count" in validation
        assert "invalid_count" in validation


# ============================================================
# Edge Case Tests
# ============================================================


class TestChainOfDensityEdgeCases:
    """Edge case tests for Chain-of-Density compression."""

    @pytest.mark.asyncio
    async def test_single_claim(self) -> None:
        """Test compression with a single claim."""
        # Given: Single claim and fragment
        claims = [
            {
                "id": "single_claim",
                "claim_text": "Single test claim",
                "claim_confidence": 0.9,
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

        # When: Compressing
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Single claim test",
            use_llm=False,
        )

        # Then: Handles gracefully
        assert result["ok"] is True
        assert result["statistics"]["total_claims"] == 1

    @pytest.mark.asyncio
    async def test_claims_without_matching_fragments(self) -> None:
        """Test handling of claims that don't match any fragment."""
        # Given: Claim with no matching fragment URL
        claims = [
            {
                "id": "unmatched_claim",
                "claim_text": "This claim has no matching fragment",
                "claim_confidence": 0.7,
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

        # When: Compressing
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Unmatched test",
            use_llm=False,
        )

        # Then: Processes with potential validation issues
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_unicode_content(self) -> None:
        """Test handling of various Unicode content."""
        # Given: Unicode content in claims and fragments
        claims = [
            {
                "id": "unicode_claim",
                "claim_text": "日本語、中文、한국어、emoji 🎉 test",
                "claim_confidence": 0.8,
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

        # When: Compressing
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Unicode test",
            use_llm=False,
        )

        # Then: Unicode preserved
        assert result["ok"] is True
        dense_claim = result["dense_claims"][0]
        assert "日本語" in dense_claim["text"]

    @pytest.mark.asyncio
    async def test_very_long_excerpt(self) -> None:
        """Test handling of very long text content."""
        # Given: Very long text (10000 chars)
        long_text = "A" * 10000
        claims = [
            {
                "id": "long_claim",
                "claim_text": "Claim about long content",
                "claim_confidence": 0.6,
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

        # When: Compressing
        result = await compress_with_chain_of_density(
            claims=claims,
            fragments=fragments,
            task_query="Long content test",
            use_llm=False,
        )

        # Then: Excerpt is truncated
        assert result["ok"] is True
        citation = result["dense_claims"][0]["citations"][0]
        assert len(citation["excerpt"]) <= 203


# ============================================================
# DenseSummary Tests
# ============================================================


class TestDenseSummary:
    """Tests for DenseSummary class."""

    def test_to_dict(self, sample_fragment: dict[str, object]) -> None:
        """Test DenseSummary serialization."""
        # Given: DenseSummary with claims
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

        # When: Serializing to dict
        data = summary.to_dict()

        # Then: All fields present with correct values
        assert data["iteration"] == 2
        assert data["text"] == "Summary text"
        assert data["entity_count"] == 5
        assert data["word_count"] == 10
        assert data["density_score"] == 0.5
        assert len(data["claims"]) == 1
