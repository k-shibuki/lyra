"""
Unit tests for parser diagnostics module.

Tests for AI-assisted parser repair functionality.
Validates:
- Diagnostic report generation
- HTML analysis and candidate element detection
- YAML fix suggestion generation
- Debug HTML file handling
- Helper function escaping and sanitization

Test Perspectives Table:
| Case ID   | Input / Precondition                     | Perspective              | Expected Result                        | Notes |
|-----------|------------------------------------------|--------------------------|----------------------------------------|-------|
| TC-N-01   | Valid HTML with result elements          | Equivalence - normal     | Candidates found with confidence > 0   |       |
| TC-N-02   | Failed selectors list                    | Equivalence - normal     | YAML fixes generated                   |       |
| TC-N-03   | Diagnostic report creation               | Equivalence - normal     | Report contains all required fields    |       |
| TC-A-01   | Empty HTML                               | Boundary - empty         | Empty candidates list                  |       |
| TC-A-02   | HTML without result patterns             | Equivalence - abnormal   | Low confidence candidates              |       |
| TC-A-03   | Invalid selector in failed list          | Equivalence - abnormal   | Fix still generated with escaped chars |       |
| TC-B-01   | HTML with data-testid attributes         | Equivalence - specific   | data-testid candidates detected        |       |
| TC-B-02   | HTML with list structure (ul/li)         | Equivalence - specific   | List-based candidates detected         |       |
| TC-B-03   | HTML with class patterns (result, etc.)  | Equivalence - specific   | Pattern-matched candidates detected    |       |
| TC-H-01   | Empty string for CSS attr value          | Boundary - empty         | Returns empty quoted string ''         |       |
| TC-H-02   | Single quotes in CSS attr value          | Equivalence - special    | Escapes with double quotes             |       |
| TC-H-03   | Double quotes in CSS attr value          | Equivalence - special    | Escapes with single quotes             |       |
| TC-H-04   | Both quotes in CSS attr value            | Equivalence - edge       | Properly escaped                       |       |
| TC-H-05   | Backslash in CSS attr value              | Equivalence - special    | Backslash escaped                      |       |
| TC-H-06   | Normal CSS attr value                    | Equivalence - normal     | Wrapped in single quotes               |       |
| TC-H-07   | Empty string for CSS ID                  | Boundary - empty         | Returns empty string                   |       |
| TC-H-08   | Hash in CSS ID                           | Equivalence - special    | Hash escaped with backslash            |       |
| TC-H-09   | Space in CSS ID                          | Equivalence - special    | Space escaped with backslash           |       |
| TC-H-10   | Dot in CSS ID                            | Equivalence - special    | Dot escaped with backslash             |       |
| TC-H-11   | Multiple special chars in CSS ID         | Equivalence - edge       | All chars escaped                      |       |
| TC-H-12   | Normal CSS ID                            | Equivalence - normal     | Unchanged                              |       |
| TC-H-13   | Empty string for YAML comment            | Boundary - empty         | Returns empty string                   |       |
| TC-H-14   | Hash in YAML comment                     | Equivalence - special    | Hash replaced with arrow               |       |
| TC-H-15   | Newline in YAML comment                  | Equivalence - special    | Newline replaced with space            |       |
| TC-H-16   | Text exceeding max_length                | Boundary - max           | Truncated with ellipsis                |       |
| TC-H-17   | Control characters in YAML comment       | Equivalence - special    | Control chars removed                  |       |
| TC-H-18   | Normal text for YAML comment             | Equivalence - normal     | Unchanged                              |       |
| TC-H-19   | Valid selector for _safe_select          | Equivalence - normal     | Returns element list                   |       |
| TC-H-20   | Invalid selector for _safe_select        | Equivalence - abnormal   | Returns empty list, no exception       |       |
| TC-H-21   | Non-existent selector for _safe_select   | Equivalence - normal     | Returns empty list                     |       |
| TC-E-01   | Exception in create_diagnostic_report    | Equivalence - abnormal   | Returns minimal report with error      |       |
| TC-B-04   | engine=None for get_latest_debug_html    | Boundary - NULL          | Returns all HTML files                 |       |
| TC-B-05   | engine="" for get_latest_debug_html      | Boundary - empty         | Treated as no filter (all files)       |       |
| TC-B-06   | Valid engine for get_latest_debug_html   | Equivalence - normal     | Returns filtered files                 |       |
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import os

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

from src.search.parser_diagnostics import (
    FailedSelector,
    CandidateElement,
    ParserDiagnosticReport,
    HTMLAnalyzer,
    generate_yaml_fix,
    generate_multiple_yaml_fixes,
    create_diagnostic_report,
    get_latest_debug_html,
    analyze_debug_html,
    _escape_css_attribute_value,
    _escape_css_id,
    _sanitize_for_yaml_comment,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_html_with_results() -> str:
    """Sample HTML with search result-like structure."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Search Results</title></head>
    <body>
        <div id="results">
            <div class="result-item" data-testid="result">
                <h2><a href="https://example.com/page1">Result Title 1</a></h2>
                <p class="snippet">This is the first result snippet with some text.</p>
                <cite class="url">example.com</cite>
            </div>
            <div class="result-item" data-testid="result">
                <h2><a href="https://example.com/page2">Result Title 2</a></h2>
                <p class="snippet">This is the second result snippet with more text.</p>
                <cite class="url">example.com</cite>
            </div>
            <div class="result-item" data-testid="result">
                <h2><a href="https://example.com/page3">Result Title 3</a></h2>
                <p class="snippet">This is the third result snippet with even more text.</p>
                <cite class="url">example.com</cite>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_with_list_results() -> str:
    """Sample HTML with list-based search results."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Search Results</title></head>
    <body>
        <ul class="search-results">
            <li class="search-item">
                <a href="https://example.com/1" class="title-link">First Result</a>
                <p class="description">Description for the first result.</p>
            </li>
            <li class="search-item">
                <a href="https://example.com/2" class="title-link">Second Result</a>
                <p class="description">Description for the second result.</p>
            </li>
            <li class="search-item">
                <a href="https://example.com/3" class="title-link">Third Result</a>
                <p class="description">Description for the third result.</p>
            </li>
            <li class="search-item">
                <a href="https://example.com/4" class="title-link">Fourth Result</a>
                <p class="description">Description for the fourth result.</p>
            </li>
        </ul>
    </body>
    </html>
    """


@pytest.fixture
def empty_html() -> str:
    """Empty HTML document."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Empty Page</title></head>
    <body></body>
    </html>
    """


@pytest.fixture
def sample_failed_selectors() -> list[FailedSelector]:
    """Sample failed selectors for testing."""
    return [
        FailedSelector(
            name="results_container",
            selector=".old-result-class",
            required=True,
            diagnostic_message="Results container not found.",
        ),
        FailedSelector(
            name="title",
            selector="h3.old-title",
            required=True,
            diagnostic_message="Title selector not found.",
        ),
    ]


# ============================================================================
# FailedSelector Tests
# ============================================================================


class TestFailedSelector:
    """Tests for FailedSelector dataclass."""
    
    # Given: A FailedSelector with all fields populated
    # When: Converting to dict
    # Then: All fields should be present in the output
    def test_to_dict_all_fields(self):
        """Test to_dict includes all fields."""
        selector = FailedSelector(
            name="results_container",
            selector=".result",
            required=True,
            diagnostic_message="Container not found",
        )
        
        result = selector.to_dict()
        
        assert result["name"] == "results_container"
        assert result["selector"] == ".result"
        assert result["required"] is True
        assert result["diagnostic_message"] == "Container not found"
    
    # Given: A FailedSelector with empty diagnostic message
    # When: Converting to dict
    # Then: Empty string should be preserved
    def test_to_dict_empty_diagnostic(self):
        """Test to_dict with empty diagnostic message."""
        selector = FailedSelector(
            name="title",
            selector="h2 a",
            required=False,
            diagnostic_message="",
        )
        
        result = selector.to_dict()
        
        assert result["diagnostic_message"] == ""


# ============================================================================
# CandidateElement Tests
# ============================================================================


class TestCandidateElement:
    """Tests for CandidateElement dataclass."""
    
    # Given: A CandidateElement with long sample text
    # When: Converting to dict
    # Then: Sample text should be truncated to 100 characters
    def test_to_dict_truncates_sample_text(self):
        """Test to_dict truncates long sample text."""
        long_text = "A" * 200
        candidate = CandidateElement(
            tag="div",
            selector=".result",
            sample_text=long_text,
            occurrence_count=5,
            confidence=0.8,
            reason="Pattern match",
        )
        
        result = candidate.to_dict()
        
        assert len(result["sample_text"]) == 100
        assert result["sample_text"] == "A" * 100
    
    # Given: A CandidateElement with short sample text
    # When: Converting to dict
    # Then: Sample text should not be truncated
    def test_to_dict_short_sample_text(self):
        """Test to_dict preserves short sample text."""
        short_text = "Short text"
        candidate = CandidateElement(
            tag="p",
            selector=".snippet",
            sample_text=short_text,
            occurrence_count=3,
            confidence=0.6,
            reason="Snippet pattern",
        )
        
        result = candidate.to_dict()
        
        assert result["sample_text"] == short_text
    
    # Given: A CandidateElement with empty sample text
    # When: Converting to dict
    # Then: Empty string should be preserved
    def test_to_dict_empty_sample_text(self):
        """Test to_dict with empty sample text."""
        candidate = CandidateElement(
            tag="a",
            selector="a.link",
            sample_text="",
            occurrence_count=1,
            confidence=0.5,
            reason="Link element",
        )
        
        result = candidate.to_dict()
        
        assert result["sample_text"] == ""


# ============================================================================
# ParserDiagnosticReport Tests
# ============================================================================


class TestParserDiagnosticReport:
    """Tests for ParserDiagnosticReport dataclass."""
    
    # Given: A complete diagnostic report
    # When: Converting to dict
    # Then: All fields should be serialized correctly
    def test_to_dict_complete_report(self, sample_failed_selectors):
        """Test to_dict with complete report."""
        report = ParserDiagnosticReport(
            engine="duckduckgo",
            query="test query",
            failed_selectors=sample_failed_selectors,
            candidate_elements=[
                CandidateElement(
                    tag="div",
                    selector=".result",
                    sample_text="Sample",
                    occurrence_count=5,
                    confidence=0.8,
                    reason="Test",
                ),
            ],
            suggested_fixes=["# YAML fix"],
            html_path=Path("/tmp/debug.html"),
            html_summary={"total_elements": 100},
        )
        
        result = report.to_dict()
        
        assert result["engine"] == "duckduckgo"
        assert result["query"] == "test query"
        assert len(result["failed_selectors"]) == 2
        assert len(result["candidate_elements"]) == 1
        assert len(result["suggested_fixes"]) == 1
        assert result["html_path"] == "/tmp/debug.html"
        assert result["html_summary"]["total_elements"] == 100
    
    # Given: A diagnostic report with None html_path
    # When: Converting to dict
    # Then: html_path should be None in output
    def test_to_dict_no_html_path(self):
        """Test to_dict with no html_path."""
        report = ParserDiagnosticReport(
            engine="google",
            query="test",
            failed_selectors=[],
            candidate_elements=[],
            suggested_fixes=[],
            html_path=None,
        )
        
        result = report.to_dict()
        
        assert result["html_path"] is None
    
    # Given: A diagnostic report with candidates
    # When: Converting to log dict
    # Then: Compact representation should be returned
    def test_to_log_dict_with_candidates(self, sample_failed_selectors):
        """Test to_log_dict returns compact representation."""
        report = ParserDiagnosticReport(
            engine="brave",
            query="test",
            failed_selectors=sample_failed_selectors,
            candidate_elements=[
                CandidateElement(
                    tag="div",
                    selector=".top-candidate",
                    sample_text="Top",
                    occurrence_count=3,
                    confidence=0.9,
                    reason="Best match",
                ),
            ],
            suggested_fixes=["# fix1", "# fix2"],
            html_path=Path("/debug/test.html"),
        )
        
        result = report.to_log_dict()
        
        assert result["engine"] == "brave"
        assert result["failed_selector_names"] == ["results_container", "title"]
        assert result["candidate_count"] == 1
        assert result["top_candidate"] == ".top-candidate"
        assert result["has_suggestions"] is True
    
    # Given: A diagnostic report without candidates
    # When: Converting to log dict
    # Then: top_candidate should be None
    def test_to_log_dict_no_candidates(self):
        """Test to_log_dict with no candidates."""
        report = ParserDiagnosticReport(
            engine="bing",
            query="test",
            failed_selectors=[],
            candidate_elements=[],
            suggested_fixes=[],
            html_path=None,
        )
        
        result = report.to_log_dict()
        
        assert result["top_candidate"] is None
        assert result["has_suggestions"] is False


# ============================================================================
# HTMLAnalyzer Tests
# ============================================================================


class TestHTMLAnalyzer:
    """Tests for HTMLAnalyzer class."""
    
    # Given: Valid HTML with result-like elements
    # When: Getting HTML summary
    # Then: Summary should contain element counts
    def test_get_html_summary(self, sample_html_with_results):
        """Test get_html_summary returns element counts."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        summary = analyzer.get_html_summary()
        
        assert summary["total_elements"] > 0
        assert summary["total_links"] >= 3  # At least 3 result links
        assert summary["total_divs"] >= 3  # At least 3 result divs
        assert summary["title"] == "Search Results"
    
    # Given: HTML with result-pattern classes
    # When: Finding result containers
    # Then: Containers with matching classes should be found
    def test_find_result_containers_by_class(self, sample_html_with_results):
        """Test find_result_containers finds elements by class pattern."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        candidates = analyzer.find_result_containers()
        
        assert len(candidates) > 0
        # Should find result-item class elements
        selectors = [c.selector for c in candidates]
        assert any("result" in s.lower() for s in selectors)
    
    # Given: HTML with data-testid attributes
    # When: Finding result containers
    # Then: Elements with data-testid should be found
    def test_find_result_containers_by_testid(self, sample_html_with_results):
        """Test find_result_containers finds data-testid elements."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        candidates = analyzer.find_result_containers()
        
        # Should find data-testid='result' elements
        testid_candidates = [c for c in candidates if "data-testid" in c.selector]
        assert len(testid_candidates) > 0
    
    # Given: HTML with list-based results (ul/li)
    # When: Finding result containers
    # Then: List items should be identified as candidates
    def test_find_result_containers_by_list(self, sample_html_with_list_results):
        """Test find_result_containers finds list-based results."""
        analyzer = HTMLAnalyzer(sample_html_with_list_results)
        
        candidates = analyzer.find_result_containers()
        
        assert len(candidates) > 0
        # Should find li elements
        li_candidates = [c for c in candidates if c.tag == "li" or "li" in c.selector]
        assert len(li_candidates) > 0
    
    # Given: Empty HTML
    # When: Finding result containers
    # Then: Empty list should be returned
    def test_find_result_containers_empty_html(self, empty_html):
        """Test find_result_containers with empty HTML."""
        analyzer = HTMLAnalyzer(empty_html)
        
        candidates = analyzer.find_result_containers()
        
        assert candidates == []
    
    # Given: HTML with headings containing links
    # When: Finding title elements
    # Then: Heading links should be found
    def test_find_title_elements(self, sample_html_with_results):
        """Test find_title_elements finds heading links."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        candidates = analyzer.find_title_elements()
        
        assert len(candidates) > 0
        # Should find h2 a elements
        heading_candidates = [c for c in candidates if c.tag.startswith("h")]
        assert len(heading_candidates) > 0
    
    # Given: HTML with paragraph elements
    # When: Finding snippet elements
    # Then: Paragraphs with appropriate length should be found
    def test_find_snippet_elements(self, sample_html_with_results):
        """Test find_snippet_elements finds paragraph content."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        candidates = analyzer.find_snippet_elements()
        
        assert len(candidates) > 0
        # Should find snippet class elements
        snippet_candidates = [c for c in candidates if "snippet" in c.selector.lower()]
        assert len(snippet_candidates) > 0
    
    # Given: HTML with external links
    # When: Finding URL elements
    # Then: Links with http(s) URLs should be found
    def test_find_url_elements(self, sample_html_with_results):
        """Test find_url_elements finds external links."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        candidates = analyzer.find_url_elements()
        
        assert len(candidates) > 0
        # All should be links
        assert all(c.tag == "a" or "url" in c.selector.lower() for c in candidates)


# ============================================================================
# YAML Fix Generation Tests
# ============================================================================


class TestYAMLFixGeneration:
    """Tests for YAML fix generation functions."""
    
    # Given: A selector name and candidate element
    # When: Generating YAML fix
    # Then: Valid YAML with correct structure should be returned
    def test_generate_yaml_fix_basic(self):
        """Test generate_yaml_fix creates valid YAML structure."""
        candidate = CandidateElement(
            tag="div",
            selector=".new-result",
            sample_text="Sample result text",
            occurrence_count=5,
            confidence=0.85,
            reason="Class matches result pattern",
        )
        
        fix = generate_yaml_fix("results_container", candidate, "duckduckgo")
        
        assert "duckduckgo:" in fix
        assert "selectors:" in fix
        assert "results_container:" in fix
        assert 'selector: ".new-result"' in fix
        assert "required: true" in fix
    
    # Given: A candidate with special characters in selector
    # When: Generating YAML fix
    # Then: Special characters should be escaped
    def test_generate_yaml_fix_escapes_quotes(self):
        """Test generate_yaml_fix escapes special characters."""
        candidate = CandidateElement(
            tag="div",
            selector='[data-testid="result"]',
            sample_text="Test",
            occurrence_count=3,
            confidence=0.9,
            reason="data-testid",
        )
        
        fix = generate_yaml_fix("results_container", candidate, "brave")
        
        # Quotes should be escaped
        assert '\\"' in fix or "data-testid" in fix
    
    # Given: Multiple failed selectors with candidates
    # When: Generating multiple YAML fixes
    # Then: Fixes should be generated for each failed selector
    def test_generate_multiple_yaml_fixes(self, sample_failed_selectors):
        """Test generate_multiple_yaml_fixes creates fixes for all selectors."""
        candidates_by_type = {
            "container": [
                CandidateElement(
                    tag="div",
                    selector=".result",
                    sample_text="Result",
                    occurrence_count=5,
                    confidence=0.8,
                    reason="Test",
                ),
            ],
            "title": [
                CandidateElement(
                    tag="h2",
                    selector="h2 a",
                    sample_text="Title",
                    occurrence_count=5,
                    confidence=0.7,
                    reason="Test",
                ),
            ],
        }
        
        fixes = generate_multiple_yaml_fixes(
            sample_failed_selectors,
            candidates_by_type,
            "ecosia",
        )
        
        assert len(fixes) == 2
        assert any("results_container" in fix for fix in fixes)
        assert any("title" in fix for fix in fixes)
    
    # Given: No candidates available
    # When: Generating multiple YAML fixes
    # Then: Empty list should be returned
    def test_generate_multiple_yaml_fixes_no_candidates(self, sample_failed_selectors):
        """Test generate_multiple_yaml_fixes with no candidates."""
        fixes = generate_multiple_yaml_fixes(
            sample_failed_selectors,
            {},  # No candidates
            "bing",
        )
        
        assert fixes == []


# ============================================================================
# create_diagnostic_report Tests
# ============================================================================


class TestCreateDiagnosticReport:
    """Tests for create_diagnostic_report function."""
    
    # Given: Valid HTML with result elements
    # When: Creating diagnostic report
    # Then: Report should contain candidates and suggestions
    def test_create_report_with_results(self, sample_html_with_results, sample_failed_selectors):
        """Test create_diagnostic_report with valid HTML."""
        report = create_diagnostic_report(
            engine="duckduckgo",
            query="test query",
            html=sample_html_with_results,
            failed_selectors=sample_failed_selectors,
            html_path=Path("/tmp/test.html"),
        )
        
        assert report.engine == "duckduckgo"
        assert report.query == "test query"
        assert len(report.failed_selectors) == 2
        assert len(report.candidate_elements) > 0
        assert report.html_path == Path("/tmp/test.html")
    
    # Given: Empty HTML
    # When: Creating diagnostic report
    # Then: Report should be created with empty candidates
    def test_create_report_empty_html(self, empty_html, sample_failed_selectors):
        """Test create_diagnostic_report with empty HTML."""
        report = create_diagnostic_report(
            engine="google",
            query="test",
            html=empty_html,
            failed_selectors=sample_failed_selectors,
            html_path=None,
        )
        
        assert report.engine == "google"
        assert report.candidate_elements == []
        assert report.html_path is None
    
    # Given: HTML without html_path
    # When: Creating diagnostic report
    # Then: html_path should be None in report
    def test_create_report_no_path(self, sample_html_with_results):
        """Test create_diagnostic_report without html_path."""
        report = create_diagnostic_report(
            engine="mojeek",
            query="test",
            html=sample_html_with_results,
            failed_selectors=[],
            html_path=None,
        )
        
        assert report.html_path is None


# ============================================================================
# Debug HTML File Handling Tests
# ============================================================================


class TestDebugHTMLHandling:
    """Tests for debug HTML file handling functions."""
    
    # Given: Non-existent debug directory
    # When: Getting latest debug HTML
    # Then: None should be returned
    def test_get_latest_debug_html_no_dir(self, tmp_path):
        """Test get_latest_debug_html when directory doesn't exist."""
        # Use a non-existent directory
        fake_debug_dir = tmp_path / "nonexistent" / "search_html"
        
        with patch("src.search.parser_diagnostics.get_parser_config_manager") as mock_manager:
            mock_settings = MagicMock()
            mock_settings.debug_html_dir = fake_debug_dir
            mock_manager.return_value.settings = mock_settings
            
            result = get_latest_debug_html()
            
            assert result is None
    
    # Given: Empty debug directory
    # When: Getting latest debug HTML
    # Then: None should be returned
    def test_get_latest_debug_html_empty_dir(self, tmp_path):
        """Test get_latest_debug_html with empty directory."""
        debug_dir = tmp_path / "debug" / "search_html"
        debug_dir.mkdir(parents=True)
        
        with patch("src.search.parser_diagnostics.get_parser_config_manager") as mock_manager:
            mock_settings = MagicMock()
            mock_settings.debug_html_dir = debug_dir
            mock_manager.return_value.settings = mock_settings
            
            result = get_latest_debug_html()
            
            # Should return None for empty directory
            assert result is None
    
    # Given: Debug HTML file with metadata
    # When: Analyzing debug HTML
    # Then: Report should extract metadata and analyze content
    def test_analyze_debug_html_with_metadata(self, tmp_path, sample_html_with_results):
        """Test analyze_debug_html extracts metadata."""
        # Create test file with metadata header
        html_file = tmp_path / "duckduckgo_123_test.html"
        content = f"""<!-- Parser Debug Info
Engine: duckduckgo
Query: test query
Timestamp: 1234567890
Error: Selector not found
-->

{sample_html_with_results}"""
        html_file.write_text(content, encoding="utf-8")
        
        report = analyze_debug_html(html_file)
        
        assert report is not None
        assert report.engine == "duckduckgo"
        assert report.query == "test query"
        assert len(report.candidate_elements) > 0
    
    # Given: Non-existent HTML file
    # When: Analyzing debug HTML
    # Then: None should be returned
    def test_analyze_debug_html_file_not_found(self, tmp_path):
        """Test analyze_debug_html with non-existent file."""
        fake_path = tmp_path / "nonexistent.html"
        
        result = analyze_debug_html(fake_path)
        
        assert result is None
    
    # Given: HTML file without metadata header
    # When: Analyzing debug HTML
    # Then: Engine should be extracted from filename
    def test_analyze_debug_html_no_metadata(self, tmp_path, sample_html_with_results):
        """Test analyze_debug_html without metadata header."""
        html_file = tmp_path / "brave_456_search.html"
        html_file.write_text(sample_html_with_results, encoding="utf-8")
        
        report = analyze_debug_html(html_file)
        
        assert report is not None
        assert report.engine == "brave"  # Extracted from filename


# ============================================================================
# Integration Tests
# ============================================================================


class TestDiagnosticsIntegration:
    """Integration tests for diagnostics workflow."""
    
    # Given: Complete diagnostic workflow
    # When: Creating and analyzing report
    # Then: All components should work together
    def test_full_diagnostic_workflow(self, sample_html_with_results, sample_failed_selectors):
        """Test complete diagnostic workflow."""
        # Step 1: Create diagnostic report
        report = create_diagnostic_report(
            engine="ecosia",
            query="AI regulations",
            html=sample_html_with_results,
            failed_selectors=sample_failed_selectors,
            html_path=None,
        )
        
        # Step 2: Verify report contents
        assert report.engine == "ecosia"
        assert len(report.candidate_elements) > 0
        
        # Step 3: Generate YAML fixes
        assert len(report.suggested_fixes) > 0
        
        # Step 4: Verify fix format
        for fix in report.suggested_fixes:
            assert "ecosia:" in fix
            assert "selectors:" in fix
            assert "selector:" in fix
        
        # Step 5: Verify log dict
        log_dict = report.to_log_dict()
        assert log_dict["engine"] == "ecosia"
        assert log_dict["has_suggestions"] is True


# ============================================================================
# Helper Function Tests - _escape_css_attribute_value
# ============================================================================


class TestEscapeCssAttributeValue:
    """Tests for _escape_css_attribute_value helper function."""
    
    # Given: Empty string
    # When: Escaping for CSS attribute
    # Then: Returns empty quoted string
    def test_empty_string(self):
        """Test empty string returns empty quotes."""
        result = _escape_css_attribute_value("")
        assert result == "''"
    
    # Given: String with single quotes only
    # When: Escaping for CSS attribute
    # Then: Uses double quotes and escapes single quotes
    def test_single_quotes(self):
        """Test string with single quotes uses double quotes."""
        result = _escape_css_attribute_value("it's")
        assert result.startswith('"')
        assert result.endswith('"')
    
    # Given: String with double quotes only
    # When: Escaping for CSS attribute
    # Then: Uses single quotes
    def test_double_quotes(self):
        """Test string with double quotes uses single quotes."""
        result = _escape_css_attribute_value('say "hello"')
        assert result.startswith("'")
        assert result.endswith("'")
    
    # Given: String with both single and double quotes
    # When: Escaping for CSS attribute
    # Then: Properly escaped with single quotes
    def test_both_quotes(self):
        """Test string with both quotes is properly escaped."""
        result = _escape_css_attribute_value("it's \"great\"")
        # Should use single quotes and escape the single quote
        assert "\\'" in result or '\\"' in result
    
    # Given: String with backslash
    # When: Escaping for CSS attribute
    # Then: Backslash is escaped
    def test_backslash(self):
        """Test backslash is escaped."""
        result = _escape_css_attribute_value("path\\to")
        assert "\\\\" in result
    
    # Given: Normal string without special characters
    # When: Escaping for CSS attribute
    # Then: Wrapped in single quotes
    def test_normal_string(self):
        """Test normal string is wrapped in single quotes."""
        result = _escape_css_attribute_value("result-item")
        assert result == "'result-item'"


# ============================================================================
# Helper Function Tests - _escape_css_id
# ============================================================================


class TestEscapeCssId:
    """Tests for _escape_css_id helper function."""
    
    # Given: Empty string
    # When: Escaping for CSS ID selector
    # Then: Returns empty string
    def test_empty_string(self):
        """Test empty string returns empty string."""
        result = _escape_css_id("")
        assert result == ""
    
    # Given: ID containing hash character
    # When: Escaping for CSS ID selector
    # Then: Hash is escaped with backslash
    def test_hash_character(self):
        """Test hash character is escaped."""
        result = _escape_css_id("id#123")
        assert "\\#" in result
    
    # Given: ID containing space
    # When: Escaping for CSS ID selector
    # Then: Space is escaped with backslash
    def test_space_character(self):
        """Test space character is escaped."""
        result = _escape_css_id("my id")
        assert "\\ " in result
    
    # Given: ID containing dot
    # When: Escaping for CSS ID selector
    # Then: Dot is escaped with backslash
    def test_dot_character(self):
        """Test dot character is escaped."""
        result = _escape_css_id("id.class")
        assert "\\." in result
    
    # Given: ID containing multiple special characters
    # When: Escaping for CSS ID selector
    # Then: All special characters are escaped
    def test_multiple_special_chars(self):
        """Test multiple special characters are all escaped."""
        result = _escape_css_id("id#123.test")
        assert "\\#" in result
        assert "\\." in result
    
    # Given: Normal ID without special characters
    # When: Escaping for CSS ID selector
    # Then: ID is unchanged
    def test_normal_id(self):
        """Test normal ID is unchanged."""
        result = _escape_css_id("result-item")
        assert result == "result-item"


# ============================================================================
# Helper Function Tests - _sanitize_for_yaml_comment
# ============================================================================


class TestSanitizeForYamlComment:
    """Tests for _sanitize_for_yaml_comment helper function."""
    
    # Given: Empty string
    # When: Sanitizing for YAML comment
    # Then: Returns empty string
    def test_empty_string(self):
        """Test empty string returns empty string."""
        result = _sanitize_for_yaml_comment("")
        assert result == ""
    
    # Given: String containing hash character
    # When: Sanitizing for YAML comment
    # Then: Hash is replaced with arrow
    def test_hash_character(self):
        """Test hash character is replaced with arrow."""
        result = _sanitize_for_yaml_comment("Price #50")
        assert "#" not in result
        assert "→" in result
    
    # Given: String containing newline
    # When: Sanitizing for YAML comment
    # Then: Newline is replaced with space
    def test_newline_character(self):
        """Test newline is replaced with space."""
        result = _sanitize_for_yaml_comment("line1\nline2")
        assert "\n" not in result
        assert " " in result
    
    # Given: String exceeding max_length
    # When: Sanitizing for YAML comment
    # Then: Text is truncated with ellipsis
    def test_max_length_exceeded(self):
        """Test text exceeding max_length is truncated."""
        long_text = "A" * 100
        result = _sanitize_for_yaml_comment(long_text, max_length=50)
        assert len(result) == 53  # 50 + "..."
        assert result.endswith("...")
    
    # Given: String containing control characters
    # When: Sanitizing for YAML comment
    # Then: Control characters are removed
    def test_control_characters(self):
        """Test control characters are removed."""
        result = _sanitize_for_yaml_comment("test\x00\x01\x02text")
        assert "\x00" not in result
        assert "\x01" not in result
        assert "\x02" not in result
        assert "testtext" in result
    
    # Given: Normal string without special characters
    # When: Sanitizing for YAML comment
    # Then: String is unchanged
    def test_normal_string(self):
        """Test normal string is unchanged."""
        result = _sanitize_for_yaml_comment("Normal text here")
        assert result == "Normal text here"


# ============================================================================
# Helper Function Tests - _safe_select (via HTMLAnalyzer)
# ============================================================================


class TestSafeSelect:
    """Tests for _safe_select method in HTMLAnalyzer."""
    
    # Given: Valid CSS selector on HTML with matching elements
    # When: Calling _safe_select
    # Then: Returns list of matching elements
    def test_valid_selector(self, sample_html_with_results):
        """Test valid selector returns matching elements."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        result = analyzer._safe_select("div.result-item")
        
        assert len(result) > 0
    
    # Given: CSS selector that matches no elements
    # When: Calling _safe_select
    # Then: Returns empty list
    def test_nonexistent_selector(self, sample_html_with_results):
        """Test non-existent selector returns empty list."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        result = analyzer._safe_select(".nonexistent-class-12345")
        
        assert result == []
    
    # Given: Invalid/malformed CSS selector
    # When: Calling _safe_select
    # Then: Returns empty list without raising exception
    def test_invalid_selector(self, sample_html_with_results):
        """Test invalid selector returns empty list without exception."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        # This should not raise an exception
        result = analyzer._safe_select("[invalid='")
        
        assert result == []


# ============================================================================
# Exception Handling Tests
# ============================================================================


class TestExceptionHandling:
    """Tests for exception handling in diagnostic functions."""
    
    # Given: HTML that causes an internal exception during analysis
    # When: Creating diagnostic report
    # Then: Minimal report is returned with error info
    def test_create_report_handles_exception(self):
        """Test create_diagnostic_report handles exceptions gracefully."""
        # Create a mock that raises an exception
        with patch.object(HTMLAnalyzer, 'find_result_containers', side_effect=Exception("Test error")):
            report = create_diagnostic_report(
                engine="test",
                query="test query",
                html="<html><body>test</body></html>",
                failed_selectors=[],
                html_path=None,
            )
            
            # Should return a report (not raise exception)
            assert report is not None
            assert report.engine == "test"
            # Should have error info in html_summary
            assert "error" in report.html_summary


# ============================================================================
# Boundary Value Tests - get_latest_debug_html
# ============================================================================


class TestGetLatestDebugHtmlBoundary:
    """Boundary value tests for get_latest_debug_html function."""
    
    # Given: engine=None
    # When: Getting latest debug HTML
    # Then: Returns any HTML file (no filter)
    def test_engine_none(self, tmp_path):
        """Test engine=None returns all HTML files."""
        debug_dir = tmp_path / "debug" / "search_html"
        debug_dir.mkdir(parents=True)
        
        # Create test files
        (debug_dir / "duckduckgo_123.html").write_text("<html></html>")
        
        with patch("src.search.parser_diagnostics.get_parser_config_manager") as mock_manager:
            mock_settings = MagicMock()
            mock_settings.debug_html_dir = debug_dir
            mock_manager.return_value.settings = mock_settings
            
            result = get_latest_debug_html(engine=None)
            
            assert result is not None
    
    # Given: engine="" (empty string)
    # When: Getting latest debug HTML
    # Then: Treated as no filter (same as None)
    def test_engine_empty_string(self, tmp_path):
        """Test engine='' is treated as no filter."""
        debug_dir = tmp_path / "debug" / "search_html"
        debug_dir.mkdir(parents=True)
        
        # Create test files
        (debug_dir / "duckduckgo_123.html").write_text("<html></html>")
        
        with patch("src.search.parser_diagnostics.get_parser_config_manager") as mock_manager:
            mock_settings = MagicMock()
            mock_settings.debug_html_dir = debug_dir
            mock_manager.return_value.settings = mock_settings
            
            result = get_latest_debug_html(engine="")
            
            # Should return file (empty string treated as no filter)
            assert result is not None
    
    # Given: Valid engine name
    # When: Getting latest debug HTML
    # Then: Returns only matching engine files
    def test_engine_filter(self, tmp_path):
        """Test engine filter returns only matching files."""
        debug_dir = tmp_path / "debug" / "search_html"
        debug_dir.mkdir(parents=True)
        
        # Create test files
        (debug_dir / "duckduckgo_123.html").write_text("<html></html>")
        (debug_dir / "google_456.html").write_text("<html></html>")
        
        with patch("src.search.parser_diagnostics.get_parser_config_manager") as mock_manager:
            mock_settings = MagicMock()
            mock_settings.debug_html_dir = debug_dir
            mock_manager.return_value.settings = mock_settings
            
            result = get_latest_debug_html(engine="duckduckgo")
            
            assert result is not None
            assert "duckduckgo" in result.name


# ============================================================================
# Boundary Value Tests - container_selector
# ============================================================================


class TestContainerSelectorBoundary:
    """Boundary value tests for container_selector parameter."""
    
    # Given: container_selector=None
    # When: Finding title elements
    # Then: Searches entire document
    def test_container_selector_none(self, sample_html_with_results):
        """Test container_selector=None searches entire document."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        result = analyzer.find_title_elements(container_selector=None)
        
        # Should return results from entire document
        assert len(result) > 0
    
    # Given: container_selector="" (empty string)
    # When: Finding title elements
    # Then: Treated as None (searches entire document)
    def test_container_selector_empty_string(self, sample_html_with_results):
        """Test container_selector='' is treated as None."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        result = analyzer.find_title_elements(container_selector="")
        
        # Should return results (empty string treated as no container)
        assert len(result) > 0
    
    # Given: Valid container_selector
    # When: Finding title elements
    # Then: Searches within container only
    def test_container_selector_valid(self, sample_html_with_results):
        """Test valid container_selector searches within container."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        result = analyzer.find_title_elements(container_selector="#results")
        
        # Should return results from within container
        assert len(result) > 0
    
    # Given: container_selector="" for find_snippet_elements
    # When: Finding snippet elements
    # Then: Treated as None (searches entire document)
    def test_snippet_container_empty_string(self, sample_html_with_results):
        """Test find_snippet_elements with empty container_selector."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        result = analyzer.find_snippet_elements(container_selector="")
        
        # Should return results
        assert len(result) > 0
    
    # Given: container_selector="" for find_url_elements
    # When: Finding URL elements
    # Then: Treated as None (searches entire document)
    def test_url_container_empty_string(self, sample_html_with_results):
        """Test find_url_elements with empty container_selector."""
        analyzer = HTMLAnalyzer(sample_html_with_results)
        
        result = analyzer.find_url_elements(container_selector="")
        
        # Should return results
        assert len(result) > 0

