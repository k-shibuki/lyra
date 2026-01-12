"""
Tests for Lyra Report Validator.

Tests the validation logic for LLM-enhanced reports against evidence pack constraints.

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|---------------------|-------------|-----------------|-------|
| TC-V-01 | URL in citation_index | Normal - valid URL | No violation | - |
| TC-V-02 | URL not in citation_index | Abnormal - hallucinated URL | Violation recorded | - |
| TC-V-03 | Footnote with page_id | Normal - valid trace | No violation | - |
| TC-V-04 | Footnote without page_id | Abnormal - missing trace | Violation recorded | - |
| TC-V-05 | Number in evidence_chains | Normal - valid number | No violation (or warning) | - |
| TC-V-06 | Number not in evidence | Abnormal - fabricated number | Warning recorded | - |
| TC-V-07 | Empty report | Boundary - empty | Pass (no content to validate) | - |
| TC-V-08 | Empty citation_index | Boundary - empty | Any URL is violation | - |
| TC-V-09 | DOI URL format | Normal - DOI allowed | No violation | DOI URLs always valid |
"""

from typing import Any

from src.report.validator import (
    extract_footnotes,
    extract_numbers_from_report,
    extract_urls_from_report,
    validate_footnote_traces,
    validate_urls,
)

# =============================================================================
# TC-URL: URL Extraction Tests
# =============================================================================


class TestExtractUrlsFromReport:
    """Tests for URL extraction from report content."""

    def test_extract_https_url(self) -> None:
        """TC-URL-01: Extract HTTPS URLs from content.

        Given: Content with HTTPS URLs
        When: extract_urls_from_report is called
        Then: URLs should be extracted
        """
        # Given
        content = "See reference at https://example.com/paper.html for details."

        # When
        urls = extract_urls_from_report(content)

        # Then
        assert "https://example.com/paper.html" in urls

    def test_extract_http_url(self) -> None:
        """TC-URL-02: Extract HTTP URLs from content.

        Given: Content with HTTP URLs
        When: extract_urls_from_report is called
        Then: URLs should be extracted
        """
        # Given
        content = "Legacy source: http://old-site.org/page"

        # When
        urls = extract_urls_from_report(content)

        # Then
        assert "http://old-site.org/page" in urls

    def test_extract_doi_reference(self) -> None:
        """TC-URL-03: Extract DOI references.

        Given: Content with DOI references
        When: extract_urls_from_report is called
        Then: DOI should be extracted
        """
        # Given
        content = "Published paper DOI:10.1234/example.2023.001"

        # When
        urls = extract_urls_from_report(content)

        # Then
        assert any("10.1234" in url for url in urls)

    def test_extract_multiple_urls(self) -> None:
        """TC-URL-04: Extract multiple URLs from content.

        Given: Content with multiple URLs
        When: extract_urls_from_report is called
        Then: All URLs should be extracted
        """
        # Given
        content = """
        Source 1: https://example.com/a
        Source 2: https://example.org/b
        DOI:10.5678/test
        """

        # When
        urls = extract_urls_from_report(content)

        # Then
        assert len(urls) >= 3

    def test_empty_content(self) -> None:
        """TC-URL-05: Empty content returns empty set.

        Given: Empty content
        When: extract_urls_from_report is called
        Then: Empty set should be returned
        """
        # Given
        content = ""

        # When
        urls = extract_urls_from_report(content)

        # Then
        assert urls == set()

    def test_url_with_trailing_punctuation_cleaned(self) -> None:
        """TC-URL-06: Trailing punctuation is removed from URLs.

        Given: URL followed by punctuation
        When: extract_urls_from_report is called
        Then: URL should not include trailing punctuation
        """
        # Given
        content = "See https://example.com/page."

        # When
        urls = extract_urls_from_report(content)

        # Then
        extracted = list(urls)[0] if urls else ""
        assert not extracted.endswith(".")


# =============================================================================
# TC-FN: Footnote Extraction Tests
# =============================================================================


class TestExtractFootnotes:
    """Tests for footnote extraction from report content."""

    def test_extract_footnote_with_page_id(self) -> None:
        """TC-FN-01: Extract footnote with page_id.

        Given: Footnote with Lyra trace IDs
        When: extract_footnotes is called
        Then: Footnote should have has_trace_ids=True
        """
        # Given
        content = "[^1]: Smith et al., 2023. Title. page_id=p_abc123."

        # When
        footnotes = extract_footnotes(content)

        # Then
        assert len(footnotes) == 1
        assert footnotes[0]["number"] == 1
        assert footnotes[0]["page_id"] == "p_abc123"
        assert footnotes[0]["has_trace_ids"] is True

    def test_extract_footnote_without_page_id(self) -> None:
        """TC-FN-02: Extract footnote without page_id.

        Given: Footnote without Lyra trace IDs
        When: extract_footnotes is called
        Then: Footnote should have has_trace_ids=False
        """
        # Given
        content = "[^2]: Unknown source, no trace."

        # When
        footnotes = extract_footnotes(content)

        # Then
        assert len(footnotes) == 1
        assert footnotes[0]["page_id"] is None
        assert footnotes[0]["has_trace_ids"] is False

    def test_extract_multiple_footnotes(self) -> None:
        """TC-FN-03: Extract multiple footnotes.

        Given: Content with multiple footnotes
        When: extract_footnotes is called
        Then: All footnotes should be extracted
        """
        # Given
        content = """
[^1]: First source. page_id=p_001.

[^2]: Second source. page_id=p_002.

[^3]: Third source without trace.
        """

        # When
        footnotes = extract_footnotes(content)

        # Then
        assert len(footnotes) == 3
        assert footnotes[0]["number"] == 1
        assert footnotes[1]["number"] == 2
        assert footnotes[2]["number"] == 3

    def test_extract_footnote_with_fragment_id(self) -> None:
        """TC-FN-04: Extract footnote with fragment_id.

        Given: Footnote with fragment_id
        When: extract_footnotes is called
        Then: fragment_id should be extracted
        """
        # Given
        content = "[^5]: Source. page_id=p_x, fragment_id=f_y."

        # When
        footnotes = extract_footnotes(content)

        # Then
        assert footnotes[0]["fragment_id"] == "f_y"

    def test_empty_content_no_footnotes(self) -> None:
        """TC-FN-05: Empty content returns empty list.

        Given: Empty content
        When: extract_footnotes is called
        Then: Empty list should be returned
        """
        # Given
        content = ""

        # When
        footnotes = extract_footnotes(content)

        # Then
        assert footnotes == []


# =============================================================================
# TC-NUM: Number Extraction Tests
# =============================================================================


class TestExtractNumbersFromReport:
    """Tests for number extraction from report content."""

    def test_extract_percentage(self) -> None:
        """TC-NUM-01: Extract percentage values.

        Given: Content with percentage
        When: extract_numbers_from_report is called
        Then: Percentage should be extracted
        """
        # Given
        content = "HbA1c reduced by 0.7%"

        # When
        numbers = extract_numbers_from_report(content)

        # Then
        assert any("0.7" in n["value"] for n in numbers)

    def test_extract_range(self) -> None:
        """TC-NUM-02: Extract range values.

        Given: Content with range
        When: extract_numbers_from_report is called
        Then: Range should be extracted
        """
        # Given
        content = "Effect size: 0.5 to 0.8"

        # When
        numbers = extract_numbers_from_report(content)

        # Then
        assert len(numbers) > 0

    def test_extract_sample_size(self) -> None:
        """TC-NUM-03: Extract sample size (n=X).

        Given: Content with sample size
        When: extract_numbers_from_report is called
        Then: Sample size should be extracted
        """
        # Given
        content = "Study included n=500 patients"

        # When
        numbers = extract_numbers_from_report(content)

        # Then
        assert any("500" in n["value"] for n in numbers)

    def test_extract_ci(self) -> None:
        """TC-NUM-04: Extract confidence interval.

        Given: Content with CI
        When: extract_numbers_from_report is called
        Then: CI should be extracted
        """
        # Given
        content = "95% CI [0.45, 0.62]"

        # When
        numbers = extract_numbers_from_report(content)

        # Then
        assert len(numbers) > 0

    def test_empty_content_no_numbers(self) -> None:
        """TC-NUM-05: Empty content returns empty list.

        Given: Empty content
        When: extract_numbers_from_report is called
        Then: Empty list should be returned
        """
        # Given
        content = ""

        # When
        numbers = extract_numbers_from_report(content)

        # Then
        assert numbers == []


# =============================================================================
# TC-VAL: Validation Function Tests
# =============================================================================


class TestValidateUrls:
    """Tests for URL validation against citation_index."""

    def test_valid_url_no_violation(self) -> None:
        """TC-VAL-01: URL in citation_index passes validation.

        Given: URL that exists in citation_index
        When: validate_urls is called
        Then: No violations should be returned
        """
        # Given
        report_urls = {"https://example.com/paper"}
        citation_index = {"https://example.com/paper": {"page_id": "p_1", "domain": "example.com"}}

        # When
        violations = validate_urls(report_urls, citation_index)

        # Then
        assert len(violations) == 0

    def test_hallucinated_url_violation(self) -> None:
        """TC-VAL-02: URL not in citation_index is violation.

        Given: URL that doesn't exist in citation_index
        When: validate_urls is called
        Then: Violation should be returned
        """
        # Given
        report_urls = {"https://fake.com/invented"}
        citation_index: dict[str, Any] = {}

        # When
        violations = validate_urls(report_urls, citation_index)

        # Then
        assert len(violations) == 1
        assert violations[0]["url"] == "https://fake.com/invented"

    def test_doi_url_always_valid(self) -> None:
        """TC-VAL-03: DOI URLs are always valid.

        Given: DOI URL not explicitly in citation_index
        When: validate_urls is called
        Then: No violation (DOIs are allowed)
        """
        # Given
        report_urls = {"DOI:10.1234/test"}
        citation_index: dict[str, Any] = {}

        # When
        violations = validate_urls(report_urls, citation_index)

        # Then
        assert len(violations) == 0

    def test_partial_url_match(self) -> None:
        """TC-VAL-04: Partial URL match is allowed.

        Given: URL that is a prefix of one in citation_index
        When: validate_urls is called
        Then: Should be considered valid
        """
        # Given
        report_urls = {"https://example.com/paper"}
        citation_index = {"https://example.com/paper/full": {"page_id": "p_1"}}

        # When
        violations = validate_urls(report_urls, citation_index)

        # Then
        # Partial match should be allowed
        assert len(violations) == 0


class TestValidateFootnoteTraces:
    """Tests for footnote trace ID validation."""

    def test_footnote_with_trace_passes(self) -> None:
        """TC-VAL-05: Footnote with page_id passes validation.

        Given: Footnote with has_trace_ids=True
        When: validate_footnote_traces is called
        Then: No violations should be returned
        """
        # Given
        footnotes = [{"number": 1, "content": "...", "page_id": "p_1", "has_trace_ids": True}]

        # When
        violations = validate_footnote_traces(footnotes)

        # Then
        assert len(violations) == 0

    def test_footnote_without_trace_violation(self) -> None:
        """TC-VAL-06: Footnote without page_id is violation.

        Given: Footnote with has_trace_ids=False
        When: validate_footnote_traces is called
        Then: Violation should be returned
        """
        # Given
        footnotes = [
            {"number": 3, "content": "No trace here", "page_id": None, "has_trace_ids": False}
        ]

        # When
        violations = validate_footnote_traces(footnotes)

        # Then
        assert len(violations) == 1
        assert violations[0]["footnote_number"] == 3

    def test_mixed_footnotes(self) -> None:
        """TC-VAL-07: Mixed footnotes only report violations.

        Given: Some footnotes with traces, some without
        When: validate_footnote_traces is called
        Then: Only footnotes without traces should be violations
        """
        # Given
        footnotes = [
            {"number": 1, "content": "Good", "page_id": "p_1", "has_trace_ids": True},
            {"number": 2, "content": "Bad", "page_id": None, "has_trace_ids": False},
            {"number": 3, "content": "Good", "page_id": "p_2", "has_trace_ids": True},
        ]

        # When
        violations = validate_footnote_traces(footnotes)

        # Then
        assert len(violations) == 1
        assert violations[0]["footnote_number"] == 2

    def test_empty_footnotes_passes(self) -> None:
        """TC-VAL-08: Empty footnote list passes validation.

        Given: Empty footnote list
        When: validate_footnote_traces is called
        Then: No violations should be returned
        """
        # Given
        footnotes: list[dict] = []

        # When
        violations = validate_footnote_traces(footnotes)

        # Then
        assert len(violations) == 0
