"""
Tests for report generation module.

Tests deep link generation and citation formatting per §3.4 and §9.2.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-AS-01 | Simple English heading | Equivalence – simple | Lowercase slug | - |
| TC-AS-02 | Heading with spaces | Equivalence – spaces | Hyphenated slug | - |
| TC-AS-03 | Japanese heading | Equivalence – Japanese | Romaji slug | - |
| TC-AS-04 | Mixed language heading | Equivalence – mixed | Combined slug | - |
| TC-AS-05 | Special characters | Equivalence – special | Sanitized slug | - |
| TC-AS-06 | Empty heading | Boundary – empty | Empty or default slug | - |
| TC-DL-01 | Generate deep link | Equivalence – link | URL with anchor | - |
| TC-DL-02 | Deep link with fragment | Equivalence – fragment | Fragment appended | - |
| TC-C-01 | Citation creation | Equivalence – citation | Citation with fields | - |
| TC-C-02 | Citation formatting | Equivalence – format | Formatted string | - |
| TC-C-03 | Citation serialization | Equivalence – to_dict | Dictionary output | - |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

from src.report.generator import (
    generate_anchor_slug,
    generate_deep_link,
    Citation,
)


class TestGenerateAnchorSlug:
    """Tests for generate_anchor_slug function."""

    def test_simple_english_heading(self):
        """Test basic English heading slug generation."""
        result = generate_anchor_slug("Introduction")
        assert result == "introduction"

    def test_heading_with_spaces(self):
        """Test heading with spaces becomes hyphenated."""
        result = generate_anchor_slug("Getting Started Guide")
        assert result == "getting-started-guide"

    def test_heading_with_special_characters(self):
        """Test special characters are removed."""
        result = generate_anchor_slug("What's New? (2024)")
        assert result == "whats-new-2024"

    def test_japanese_heading(self):
        """Test Japanese heading is preserved."""
        result = generate_anchor_slug("はじめに")
        assert result == "はじめに"

    def test_japanese_heading_with_spaces(self):
        """Test Japanese heading with spaces."""
        result = generate_anchor_slug("第1章 概要")
        assert result == "第1章-概要"

    def test_mixed_language_heading(self):
        """Test mixed Japanese/English heading."""
        result = generate_anchor_slug("API仕様 Overview")
        assert result == "api仕様-overview"

    def test_empty_heading(self):
        """Test empty heading returns empty string."""
        result = generate_anchor_slug("")
        assert result == ""

    def test_none_heading(self):
        """Test None heading returns empty string."""
        result = generate_anchor_slug(None)  # type: ignore
        assert result == ""

    def test_heading_with_multiple_spaces(self):
        """Test multiple spaces collapse to single hyphen."""
        result = generate_anchor_slug("Section   One")
        assert result == "section-one"

    def test_heading_with_underscores(self):
        """Test underscores become hyphens."""
        result = generate_anchor_slug("getting_started_guide")
        assert result == "getting-started-guide"

    def test_heading_unicode_normalization(self):
        """Test unicode normalization (NFKC)."""
        # Full-width characters should be normalized
        result = generate_anchor_slug("ＡＢＣ")
        assert result == "abc"

    def test_heading_with_numbers(self):
        """Test numbers are preserved."""
        result = generate_anchor_slug("Chapter 123")
        assert result == "chapter-123"


class TestGenerateDeepLink:
    """Tests for generate_deep_link function."""

    def test_basic_deep_link(self):
        """Test basic deep link generation."""
        result = generate_deep_link(
            "https://example.com/page",
            "Introduction"
        )
        assert result == "https://example.com/page#introduction"

    def test_deep_link_with_japanese_heading(self):
        """Test deep link with Japanese heading."""
        result = generate_deep_link(
            "https://example.com/doc",
            "はじめに"
        )
        assert result == "https://example.com/doc#はじめに"

    def test_deep_link_no_heading(self):
        """Test deep link without heading returns original URL."""
        result = generate_deep_link(
            "https://example.com/page",
            None
        )
        assert result == "https://example.com/page"

    def test_deep_link_empty_heading(self):
        """Test deep link with empty heading returns original URL."""
        result = generate_deep_link(
            "https://example.com/page",
            ""
        )
        assert result == "https://example.com/page"

    def test_deep_link_preserves_existing_fragment(self):
        """Test existing fragment is not overwritten."""
        result = generate_deep_link(
            "https://example.com/page#existing",
            "New Section"
        )
        assert result == "https://example.com/page#existing"

    def test_deep_link_with_query_params(self):
        """Test deep link preserves query parameters."""
        result = generate_deep_link(
            "https://example.com/page?q=test&lang=ja",
            "Results"
        )
        assert result == "https://example.com/page?q=test&lang=ja#results"

    def test_deep_link_with_path(self):
        """Test deep link with complex path."""
        result = generate_deep_link(
            "https://example.com/docs/api/v2/reference",
            "Authentication"
        )
        assert result == "https://example.com/docs/api/v2/reference#authentication"


class TestCitation:
    """Tests for Citation class."""

    def test_citation_creation(self):
        """Test basic citation creation."""
        citation = Citation(
            url="https://example.com/doc",
            title="Test Document",
        )
        assert citation.url == "https://example.com/doc"
        assert citation.title == "Test Document"

    def test_citation_deep_link(self):
        """Test citation deep_link property."""
        citation = Citation(
            url="https://example.com/doc",
            title="Test Document",
            heading_context="Introduction",
        )
        assert citation.deep_link == "https://example.com/doc#introduction"

    def test_citation_deep_link_no_heading(self):
        """Test citation deep_link without heading returns original URL."""
        citation = Citation(
            url="https://example.com/doc",
            title="Test Document",
        )
        assert citation.deep_link == "https://example.com/doc"

    def test_citation_is_primary_source_government(self):
        """Test government sources are primary."""
        citation = Citation(
            url="https://gov.example.com/report",
            title="Government Report",
            source_tag="government",
        )
        assert citation.is_primary_source is True

    def test_citation_is_primary_source_academic(self):
        """Test academic sources are primary."""
        citation = Citation(
            url="https://arxiv.org/paper",
            title="Research Paper",
            source_tag="academic",
        )
        assert citation.is_primary_source is True

    def test_citation_is_primary_source_blog(self):
        """Test blog sources are not primary."""
        citation = Citation(
            url="https://blog.example.com/post",
            title="Blog Post",
            source_tag="blog",
        )
        assert citation.is_primary_source is False

    def test_citation_is_primary_source_none(self):
        """Test no source_tag means not primary."""
        citation = Citation(
            url="https://example.com/page",
            title="Some Page",
        )
        assert citation.is_primary_source is False

    def test_citation_to_markdown_basic(self):
        """Test basic markdown output."""
        citation = Citation(
            url="https://example.com/doc",
            title="Test Document",
        )
        result = citation.to_markdown(1, include_excerpt=False)
        assert "1. [Test Document](https://example.com/doc)" in result

    def test_citation_to_markdown_with_heading(self):
        """Test markdown output includes section reference."""
        citation = Citation(
            url="https://example.com/doc",
            title="Test Document",
            heading_context="第1章 概要",
        )
        result = citation.to_markdown(1, include_excerpt=False)
        # Should include deep link
        assert "#第1章-概要" in result
        # Should include section label
        assert "セクション: 第1章 概要" in result

    def test_citation_to_markdown_with_source_tag(self):
        """Test markdown output includes source type."""
        citation = Citation(
            url="https://gov.example.com/report",
            title="Official Report",
            source_tag="government",
        )
        result = citation.to_markdown(1, include_excerpt=False)
        assert "政府・公的機関" in result

    def test_citation_to_markdown_with_excerpt(self):
        """Test markdown output includes excerpt when requested."""
        citation = Citation(
            url="https://example.com/doc",
            title="Test Document",
            excerpt="This is a test excerpt for the citation.",
        )
        result = citation.to_markdown(1, include_excerpt=True)
        assert "This is a test excerpt" in result

    def test_citation_to_markdown_truncates_long_excerpt(self):
        """Test long excerpts are truncated."""
        long_text = "a" * 200
        citation = Citation(
            url="https://example.com/doc",
            title="Test Document",
            excerpt=long_text,
        )
        result = citation.to_markdown(1, include_excerpt=True)
        assert "..." in result
        # Should be truncated to ~150 chars
        assert len([line for line in result.split("\n") if line.startswith("   >")][0]) < 200


class TestCitationSourcePriority:
    """Tests for source priority classification per §3.4."""

    @pytest.mark.parametrize("source_tag,expected", [
        ("government", True),
        ("academic", True),
        ("official", True),
        ("standard", True),
        ("registry", True),
        ("news", False),
        ("blog", False),
        ("forum", False),
        ("unknown", False),
        (None, False),
    ])
    def test_primary_source_classification(self, source_tag, expected):
        """Test all source types are classified correctly."""
        citation = Citation(
            url="https://example.com/page",
            title="Test",
            source_tag=source_tag,
        )
        assert citation.is_primary_source is expected, (
            f"Source tag '{source_tag}' should be primary={expected}"
        )







