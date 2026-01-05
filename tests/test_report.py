"""
Tests for report link generation module.

Tests deep link generation per ADR-0005.

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
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

# E402: Intentionally import after pytestmark for test configuration
from src.report.links import (
    generate_anchor_slug,
    generate_deep_link,
)


class TestGenerateAnchorSlug:
    """Tests for generate_anchor_slug function."""

    def test_simple_english_heading(self) -> None:
        """Test basic English heading slug generation."""
        result = generate_anchor_slug("Introduction")
        assert result == "introduction"

    def test_heading_with_spaces(self) -> None:
        """Test heading with spaces becomes hyphenated."""
        result = generate_anchor_slug("Getting Started Guide")
        assert result == "getting-started-guide"

    def test_heading_with_special_characters(self) -> None:
        """Test special characters are removed."""
        result = generate_anchor_slug("What's New? (2024)")
        assert result == "whats-new-2024"

    def test_japanese_heading(self) -> None:
        """Test Japanese heading is preserved."""
        result = generate_anchor_slug("はじめに")
        assert result == "はじめに"

    def test_japanese_heading_with_spaces(self) -> None:
        """Test Japanese heading with spaces."""
        result = generate_anchor_slug("第1章 概要")
        assert result == "第1章-概要"

    def test_mixed_language_heading(self) -> None:
        """Test mixed Japanese/English heading."""
        result = generate_anchor_slug("API仕様 Overview")
        assert result == "api仕様-overview"

    def test_empty_heading(self) -> None:
        """Test empty heading returns empty string."""
        result = generate_anchor_slug("")
        assert result == ""

    def test_none_heading(self) -> None:
        """Test None heading returns empty string."""
        result = generate_anchor_slug(None)  # type: ignore
        assert result == ""

    def test_heading_with_multiple_spaces(self) -> None:
        """Test multiple spaces collapse to single hyphen."""
        result = generate_anchor_slug("Section   One")
        assert result == "section-one"

    def test_heading_with_underscores(self) -> None:
        """Test underscores become hyphens."""
        result = generate_anchor_slug("getting_started_guide")
        assert result == "getting-started-guide"

    def test_heading_unicode_normalization(self) -> None:
        """Test unicode normalization (NFKC)."""
        # Full-width characters should be normalized
        result = generate_anchor_slug("ＡＢＣ")
        assert result == "abc"

    def test_heading_with_numbers(self) -> None:
        """Test numbers are preserved."""
        result = generate_anchor_slug("Chapter 123")
        assert result == "chapter-123"


class TestGenerateDeepLink:
    """Tests for generate_deep_link function."""

    def test_basic_deep_link(self) -> None:
        """Test basic deep link generation."""
        result = generate_deep_link("https://example.com/page", "Introduction")
        assert result == "https://example.com/page#introduction"

    def test_deep_link_with_japanese_heading(self) -> None:
        """Test deep link with Japanese heading."""
        result = generate_deep_link("https://example.com/doc", "はじめに")
        assert result == "https://example.com/doc#はじめに"

    def test_deep_link_no_heading(self) -> None:
        """Test deep link without heading returns original URL."""
        result = generate_deep_link("https://example.com/page", None)
        assert result == "https://example.com/page"

    def test_deep_link_empty_heading(self) -> None:
        """Test deep link with empty heading returns original URL."""
        result = generate_deep_link("https://example.com/page", "")
        assert result == "https://example.com/page"

    def test_deep_link_preserves_existing_fragment(self) -> None:
        """Test existing fragment is not overwritten."""
        result = generate_deep_link("https://example.com/page#existing", "New Section")
        assert result == "https://example.com/page#existing"

    def test_deep_link_with_query_params(self) -> None:
        """Test deep link preserves query parameters."""
        result = generate_deep_link("https://example.com/page?q=test&lang=ja", "Results")
        assert result == "https://example.com/page?q=test&lang=ja#results"

    def test_deep_link_with_path(self) -> None:
        """Test deep link with complex path."""
        result = generate_deep_link("https://example.com/docs/api/v2/reference", "Authentication")
        assert result == "https://example.com/docs/api/v2/reference#authentication"
