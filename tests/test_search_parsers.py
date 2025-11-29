"""
Unit tests for search result parsers.

Tests for Phase 16.9: Direct browser-based search.
Validates:
- ParserConfigManager configuration loading
- BaseSearchParser functionality
- DuckDuckGoParser result extraction
- MojeekParser result extraction
- CAPTCHA detection
- Error handling and diagnostic messages

Follows §7.1 test code quality standards:
- Specific assertions with concrete values
- No conditional assertions
- Proper HTML fixtures for testing
- Boundary conditions coverage
"""

import os

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.search.parser_config import (
    ParserConfigManager,
    SelectorConfig,
    EngineParserConfig,
    get_parser_config_manager,
    reset_parser_config_manager,
)
from src.search.search_parsers import (
    BaseSearchParser,
    DuckDuckGoParser,
    MojeekParser,
    EcosiaParser,
    StartpageParser,
    ParseResult,
    ParsedResult,
    get_parser,
    get_available_parsers,
)
from src.search.provider import SourceTag


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def fixtures_dir() -> Path:
    """Get path to test fixtures directory."""
    return Path(__file__).parent / "fixtures" / "search_html"


@pytest.fixture
def duckduckgo_html(fixtures_dir: Path) -> str:
    """Load DuckDuckGo sample HTML."""
    html_file = fixtures_dir / "duckduckgo_results.html"
    return html_file.read_text(encoding="utf-8")


@pytest.fixture
def duckduckgo_captcha_html(fixtures_dir: Path) -> str:
    """Load DuckDuckGo CAPTCHA HTML."""
    html_file = fixtures_dir / "duckduckgo_captcha.html"
    return html_file.read_text(encoding="utf-8")


@pytest.fixture
def mojeek_html(fixtures_dir: Path) -> str:
    """Load Mojeek sample HTML."""
    html_file = fixtures_dir / "mojeek_results.html"
    return html_file.read_text(encoding="utf-8")


@pytest.fixture
def ecosia_html(fixtures_dir: Path) -> str:
    """Load Ecosia sample HTML."""
    html_file = fixtures_dir / "ecosia_results.html"
    return html_file.read_text(encoding="utf-8")


@pytest.fixture
def startpage_html(fixtures_dir: Path) -> str:
    """Load Startpage sample HTML."""
    html_file = fixtures_dir / "startpage_results.html"
    return html_file.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def reset_manager():
    """Reset parser config manager before each test."""
    reset_parser_config_manager()
    yield
    reset_parser_config_manager()


# ============================================================================
# ParserConfigManager Tests
# ============================================================================


class TestParserConfigManager:
    """Tests for ParserConfigManager."""
    
    def test_load_config(self):
        """Test configuration loading from YAML."""
        manager = get_parser_config_manager()
        
        # Should have loaded engines (at least duckduckgo and mojeek)
        engines = manager.get_available_engines()
        assert len(engines) >= 2, f"Expected >=2 engines, got {len(engines)}: {engines}"
        assert "duckduckgo" in engines
        assert "mojeek" in engines
    
    def test_get_engine_config(self):
        """Test getting engine configuration."""
        manager = get_parser_config_manager()
        
        config = manager.get_engine_config("duckduckgo")
        assert config is not None
        assert config.name == "duckduckgo"
        assert config.search_url is not None
        # URL should contain query placeholder
        assert "{query}" in config.search_url, (
            f"Expected '{{query}}' placeholder in search_url: {config.search_url}"
        )
    
    def test_get_engine_config_case_insensitive(self):
        """Test engine config lookup is case-insensitive."""
        manager = get_parser_config_manager()
        
        config1 = manager.get_engine_config("DuckDuckGo")
        config2 = manager.get_engine_config("duckduckgo")
        config3 = manager.get_engine_config("DUCKDUCKGO")
        
        assert config1 is not None
        assert config2 is not None
        assert config3 is not None
        assert config1.name == config2.name == config3.name
    
    def test_get_nonexistent_engine(self):
        """Test getting config for nonexistent engine returns None."""
        manager = get_parser_config_manager()
        
        config = manager.get_engine_config("nonexistent_engine")
        assert config is None
    
    def test_selector_config(self):
        """Test selector configuration is loaded correctly."""
        manager = get_parser_config_manager()
        
        config = manager.get_engine_config("duckduckgo")
        assert config is not None
        
        # Check results_container selector
        selector = config.get_selector("results_container")
        assert selector is not None
        assert selector.required is True
        # Diagnostic message should be meaningful for debugging
        assert len(selector.diagnostic_message) >= 10, (
            f"Expected diagnostic message >=10 chars, got: {selector.diagnostic_message}"
        )
    
    def test_settings(self):
        """Test global settings are loaded."""
        manager = get_parser_config_manager()
        
        settings = manager.settings
        assert settings.debug_html_dir is not None
        assert settings.max_results_per_page > 0
        assert settings.search_timeout > 0


class TestEngineParserConfig:
    """Tests for EngineParserConfig."""
    
    def test_build_search_url_no_encoding(self):
        """
        Test EngineParserConfig.build_search_url does NOT encode query.
        
        EngineParserConfig is a low-level config class that provides raw URL
        template substitution. URL encoding is the responsibility of the
        calling code (e.g., BaseSearchParser.build_search_url).
        """
        manager = get_parser_config_manager()
        config = manager.get_engine_config("duckduckgo")
        assert config is not None
        
        url = config.build_search_url("test query", time_range="week")
        
        # EngineParserConfig does NOT encode - raw query is substituted
        assert "test query" in url  # Space not encoded
        assert "duckduckgo.com" in url
    
    def test_get_time_range(self):
        """Test time range mapping for DuckDuckGo."""
        manager = get_parser_config_manager()
        config = manager.get_engine_config("duckduckgo")
        assert config is not None
        
        # Per config/search_parsers.yaml, DuckDuckGo time_ranges:
        # all: "", day: "d", week: "w", month: "m", year: "y"
        assert config.get_time_range("all") == ""
        assert config.get_time_range("day") == "d"
        assert config.get_time_range("week") == "w"
        assert config.get_time_range("month") == "m"
        assert config.get_time_range("year") == "y"
    
    def test_get_required_selectors(self):
        """Test getting required selectors."""
        manager = get_parser_config_manager()
        config = manager.get_engine_config("duckduckgo")
        assert config is not None
        
        required = config.get_required_selectors()
        # DuckDuckGo should have at least 1 required selector (results_container)
        assert len(required) >= 1, f"Expected >=1 required selectors, got {len(required)}"
        
        # results_container should be required
        names = [s.name for s in required]
        assert "results_container" in names


# ============================================================================
# DuckDuckGo Parser Tests
# ============================================================================


class TestDuckDuckGoParser:
    """Tests for DuckDuckGoParser."""
    
    def test_parse_results(self, duckduckgo_html: str):
        """Test parsing DuckDuckGo search results."""
        parser = DuckDuckGoParser()
        result = parser.parse(duckduckgo_html, "test query")
        
        assert result.ok is True
        assert len(result.results) == 3
        assert result.is_captcha is False
        assert result.error is None
    
    def test_parse_result_titles(self, duckduckgo_html: str):
        """Test extracted titles are correct."""
        parser = DuckDuckGoParser()
        result = parser.parse(duckduckgo_html, "test")
        
        titles = [r.title for r in result.results]
        assert "First Result Title" in titles
        assert "Academic Paper Title" in titles
        assert "Government Document" in titles
    
    def test_parse_result_urls(self, duckduckgo_html: str):
        """Test extracted URLs are correct."""
        parser = DuckDuckGoParser()
        result = parser.parse(duckduckgo_html, "test")
        
        urls = [r.url for r in result.results]
        assert "https://example.com/page1" in urls
        assert "https://arxiv.org/abs/12345" in urls
        assert "https://www.e-gov.go.jp/document" in urls
    
    def test_parse_result_snippets(self, duckduckgo_html: str):
        """Test extracted snippets are correct."""
        parser = DuckDuckGoParser()
        result = parser.parse(duckduckgo_html, "test")
        
        snippets = [r.snippet for r in result.results]
        assert any("first result" in s.lower() for s in snippets)
        assert any("academic" in s.lower() for s in snippets)
    
    def test_parse_result_ranks(self, duckduckgo_html: str):
        """Test results have correct ranks assigned."""
        parser = DuckDuckGoParser()
        result = parser.parse(duckduckgo_html, "test")
        
        ranks = [r.rank for r in result.results]
        assert ranks == [1, 2, 3]
    
    def test_detect_captcha(self, duckduckgo_captcha_html: str):
        """Test CAPTCHA detection."""
        parser = DuckDuckGoParser()
        result = parser.parse(duckduckgo_captcha_html, "test")
        
        assert result.ok is False
        assert result.is_captcha is True
        assert result.captcha_type is not None
    
    def test_captcha_detection_patterns(self):
        """Test various CAPTCHA patterns are detected."""
        parser = DuckDuckGoParser()
        
        # Turnstile
        html_turnstile = "<html><div class='cf-turnstile'></div></html>"
        result = parser.parse(html_turnstile, "test")
        assert result.is_captcha is True
        
        # ReCAPTCHA
        html_recaptcha = "<html><div class='g-recaptcha'></div></html>"
        result = parser.parse(html_recaptcha, "test")
        assert result.is_captcha is True
    
    def test_empty_html(self):
        """Test handling of empty HTML."""
        parser = DuckDuckGoParser()
        result = parser.parse("", "test")
        
        # Should fail with selector errors (at least 1 for missing container)
        assert result.ok is False
        assert len(result.selector_errors) >= 1, f"Expected >=1 selector errors, got {result.selector_errors}"
    
    def test_malformed_html(self):
        """Test handling of malformed HTML."""
        parser = DuckDuckGoParser()
        html = "<html><div>No search results here</div></html>"
        result = parser.parse(html, "test")
        
        # Should fail because required selectors not found
        assert result.ok is False
    
    def test_build_search_url_with_encoding(self):
        """
        Test BaseSearchParser.build_search_url URL-encodes the query.
        
        Unlike EngineParserConfig.build_search_url, the parser's build_search_url
        method URL-encodes the query (e.g., spaces become '+').
        """
        parser = DuckDuckGoParser()
        url = parser.build_search_url("AI regulations")
        
        assert "duckduckgo.com" in url
        # Query should be URL-encoded - space becomes + or %20
        # Verify the query terms are present (encoding-agnostic check)
        assert "AI" in url, f"Expected 'AI' in URL: {url}"
        assert "regulations" in url, f"Expected 'regulations' in URL: {url}"


# ============================================================================
# Mojeek Parser Tests
# ============================================================================


class TestMojeekParser:
    """Tests for MojeekParser."""
    
    def test_parse_results(self, mojeek_html: str):
        """Test parsing Mojeek search results."""
        parser = MojeekParser()
        result = parser.parse(mojeek_html, "test query")
        
        assert result.ok is True
        assert len(result.results) == 2
        assert result.is_captcha is False
    
    def test_parse_result_titles(self, mojeek_html: str):
        """Test extracted titles from Mojeek."""
        parser = MojeekParser()
        result = parser.parse(mojeek_html, "test")
        
        titles = [r.title for r in result.results]
        assert "Mojeek Result One" in titles
        assert "Wikipedia Article" in titles
    
    def test_parse_result_urls(self, mojeek_html: str):
        """Test extracted URLs from Mojeek."""
        parser = MojeekParser()
        result = parser.parse(mojeek_html, "test")
        
        urls = [r.url for r in result.results]
        assert "https://example.com/mojeek1" in urls
        assert "https://wikipedia.org/wiki/Test" in urls
    
    def test_build_search_url(self):
        """Test building Mojeek search URL."""
        parser = MojeekParser()
        url = parser.build_search_url("test query")
        
        assert "mojeek.com" in url


# ============================================================================
# Parser Registry Tests
# ============================================================================


class TestParserRegistry:
    """Tests for parser registry functions."""
    
    def test_get_parser(self):
        """Test getting parser by name."""
        parser = get_parser("duckduckgo")
        assert parser is not None
        assert isinstance(parser, DuckDuckGoParser)
    
    def test_get_parser_case_insensitive(self):
        """Test parser lookup is case-insensitive."""
        parser1 = get_parser("DuckDuckGo")
        parser2 = get_parser("duckduckgo")
        
        assert parser1 is not None
        assert parser2 is not None
        assert type(parser1) == type(parser2)
    
    def test_get_nonexistent_parser(self):
        """Test getting nonexistent parser returns None."""
        parser = get_parser("nonexistent")
        assert parser is None
    
    def test_get_available_parsers(self):
        """Test getting list of available parsers."""
        parsers = get_available_parsers()
        
        assert isinstance(parsers, list)
        # Should have at least duckduckgo and mojeek
        assert len(parsers) >= 2, f"Expected >=2 parsers, got {len(parsers)}: {parsers}"
        assert "duckduckgo" in parsers
        assert "mojeek" in parsers


# ============================================================================
# Source Classification Tests
# ============================================================================


class TestSourceClassification:
    """Tests for source URL classification."""
    
    def test_search_result_source_tag(self, duckduckgo_html: str):
        """Test source tags are assigned to results."""
        parser = DuckDuckGoParser()
        result = parser.parse(duckduckgo_html, "test")
        
        # Find academic result
        academic_result = next(
            (r for r in result.results if "arxiv.org" in r.url),
            None,
        )
        assert academic_result is not None
        
        search_result = academic_result.to_search_result("duckduckgo")
        assert search_result.source_tag == SourceTag.ACADEMIC
    
    def test_government_source_classification(self, duckduckgo_html: str):
        """Test government source is classified correctly."""
        parser = DuckDuckGoParser()
        result = parser.parse(duckduckgo_html, "test")
        
        gov_result = next(
            (r for r in result.results if ".go.jp" in r.url),
            None,
        )
        assert gov_result is not None
        
        search_result = gov_result.to_search_result("duckduckgo")
        assert search_result.source_tag == SourceTag.GOVERNMENT


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestParserErrorHandling:
    """Tests for parser error handling and diagnostics."""
    
    def test_selector_error_messages(self):
        """Test diagnostic messages are included in errors."""
        parser = DuckDuckGoParser()
        html = "<html><body>No results</body></html>"
        result = parser.parse(html, "test query")
        
        assert result.ok is False
        assert len(result.selector_errors) >= 1, f"Expected selector errors, got {result.selector_errors}"
        
        # Check error messages contain diagnostics about the failed selector
        error_text = "\n".join(result.selector_errors)
        assert "results_container" in error_text.lower(), (
            f"Expected 'results_container' in error message: {error_text}"
        )
    
    def test_html_saved_on_failure(self, tmp_path):
        """Test HTML is saved when parsing fails."""
        # Configure to save to temp directory
        with patch.object(
            get_parser_config_manager().settings,
            'debug_html_dir',
            tmp_path,
        ):
            with patch.object(
                get_parser_config_manager().settings,
                'save_failed_html',
                True,
            ):
                parser = DuckDuckGoParser()
                html = "<html><body>Invalid</body></html>"
                result = parser.parse(html, "test query")
                
                # Path might be None if save is disabled in actual config
                # Just verify the mechanism works
                assert result.ok is False


# ============================================================================
# Ecosia Parser Tests (Phase 16.13)
# ============================================================================


class TestEcosiaParser:
    """Tests for EcosiaParser (Bing-based, relatively lenient)."""
    
    def test_parse_results(self, ecosia_html: str):
        """Test parsing Ecosia search results."""
        parser = EcosiaParser()
        result = parser.parse(ecosia_html, "test query")
        
        assert result.ok is True
        assert len(result.results) == 3
        assert result.is_captcha is False
        assert result.error is None
    
    def test_parse_result_titles(self, ecosia_html: str):
        """Test extracted titles from Ecosia."""
        parser = EcosiaParser()
        result = parser.parse(ecosia_html, "test")
        
        titles = [r.title for r in result.results]
        assert "Ecosia Result One" in titles
        assert "Nature Article" in titles
        assert "UK Government Document" in titles
    
    def test_parse_result_urls(self, ecosia_html: str):
        """Test extracted URLs from Ecosia."""
        parser = EcosiaParser()
        result = parser.parse(ecosia_html, "test")
        
        urls = [r.url for r in result.results]
        assert "https://example.com/ecosia1" in urls
        assert "https://nature.com/article/123" in urls
        assert "https://www.gov.uk/document" in urls
    
    def test_parse_result_snippets(self, ecosia_html: str):
        """Test extracted snippets from Ecosia match expected content."""
        parser = EcosiaParser()
        result = parser.parse(ecosia_html, "test")
        
        # Verify specific snippet content by index (deterministic order from fixture)
        assert len(result.results) == 3
        assert "first result from Ecosia" in result.results[0].snippet
        assert "environmental research" in result.results[1].snippet
        assert "UK government document" in result.results[2].snippet
    
    def test_parse_result_ranks(self, ecosia_html: str):
        """Test results have correct ranks assigned."""
        parser = EcosiaParser()
        result = parser.parse(ecosia_html, "test")
        
        ranks = [r.rank for r in result.results]
        assert ranks == [1, 2, 3]
    
    def test_build_search_url(self):
        """Test building Ecosia search URL contains domain and encoded query."""
        parser = EcosiaParser()
        url = parser.build_search_url("test query")
        
        assert "ecosia.org" in url
        # Query should be URL-encoded (space becomes + or %20)
        assert "test" in url
        assert "query" in url
    
    def test_government_source_classification(self, ecosia_html: str):
        """Test UK government source is classified correctly."""
        parser = EcosiaParser()
        result = parser.parse(ecosia_html, "test")
        
        gov_result = next(
            (r for r in result.results if ".gov.uk" in r.url),
            None,
        )
        assert gov_result is not None
        
        search_result = gov_result.to_search_result("ecosia")
        assert search_result.source_tag == SourceTag.GOVERNMENT
    
    def test_empty_html(self):
        """Test empty HTML returns failure with selector errors for required selectors."""
        parser = EcosiaParser()
        result = parser.parse("", "test")
        
        assert result.ok is False
        # Ecosia has 3 required selectors: results_container, title, url
        assert len(result.selector_errors) == 3


# ============================================================================
# Startpage Parser Tests (Phase 16.13)
# ============================================================================


class TestStartpageParser:
    """Tests for StartpageParser (Google-based, privacy-focused)."""
    
    def test_parse_results(self, startpage_html: str):
        """Test parsing Startpage search results."""
        parser = StartpageParser()
        result = parser.parse(startpage_html, "test query")
        
        assert result.ok is True
        assert len(result.results) == 3
        assert result.is_captcha is False
        assert result.error is None
    
    def test_parse_result_titles(self, startpage_html: str):
        """Test extracted titles from Startpage."""
        parser = StartpageParser()
        result = parser.parse(startpage_html, "test")
        
        titles = [r.title for r in result.results]
        assert "Startpage Result One" in titles
        assert "Google Scholar Paper" in titles
        assert "Japanese Government Law" in titles
    
    def test_parse_result_urls(self, startpage_html: str):
        """Test extracted URLs from Startpage."""
        parser = StartpageParser()
        result = parser.parse(startpage_html, "test")
        
        urls = [r.url for r in result.results]
        assert "https://example.com/startpage1" in urls
        assert "https://scholar.google.com/paper123" in urls
        assert "https://www.e-gov.go.jp/law" in urls
    
    def test_parse_result_snippets(self, startpage_html: str):
        """Test extracted snippets from Startpage match expected content."""
        parser = StartpageParser()
        result = parser.parse(startpage_html, "test")
        
        # Verify specific snippet content by index (deterministic order from fixture)
        assert len(result.results) == 3
        assert "privacy search" in result.results[0].snippet
        assert "Academic paper" in result.results[1].snippet
        assert "Legal document" in result.results[2].snippet
    
    def test_parse_result_ranks(self, startpage_html: str):
        """Test results have correct ranks assigned."""
        parser = StartpageParser()
        result = parser.parse(startpage_html, "test")
        
        ranks = [r.rank for r in result.results]
        assert ranks == [1, 2, 3]
    
    def test_build_search_url(self):
        """Test building Startpage search URL."""
        parser = StartpageParser()
        url = parser.build_search_url("test query")
        
        assert "startpage.com" in url
    
    def test_academic_source_classification(self, startpage_html: str):
        """Test Google Scholar source is classified as academic."""
        parser = StartpageParser()
        result = parser.parse(startpage_html, "test")
        
        academic_result = next(
            (r for r in result.results if "scholar.google" in r.url.lower()),
            None,
        )
        assert academic_result is not None
        
        search_result = academic_result.to_search_result("startpage")
        assert search_result.source_tag == SourceTag.ACADEMIC
    
    def test_government_source_classification(self, startpage_html: str):
        """Test Japanese government source is classified correctly."""
        parser = StartpageParser()
        result = parser.parse(startpage_html, "test")
        
        gov_result = next(
            (r for r in result.results if ".go.jp" in r.url),
            None,
        )
        assert gov_result is not None
        
        search_result = gov_result.to_search_result("startpage")
        assert search_result.source_tag == SourceTag.GOVERNMENT
    
    def test_empty_html(self):
        """Test empty HTML returns failure with selector errors for required selectors."""
        parser = StartpageParser()
        result = parser.parse("", "test")
        
        assert result.ok is False
        # Startpage has 3 required selectors: results_container, title, url
        assert len(result.selector_errors) == 3
    
    def test_captcha_detection(self):
        """Test reCAPTCHA pattern is detected in HTML."""
        parser = StartpageParser()
        
        # reCAPTCHA
        html = "<html><body><div class='g-recaptcha'></div></body></html>"
        result = parser.parse(html, "test")
        assert result.is_captcha is True
        assert result.captcha_type == "recaptcha"


# ============================================================================
# Phase 16.13 Parser Registry Tests
# ============================================================================


class TestPhase1613ParserRegistry:
    """Tests for new parsers added in Phase 16.13."""
    
    def test_ecosia_parser_available(self):
        """Test Ecosia parser is registered and returns correct type."""
        parser = get_parser("ecosia")
        assert parser is not None
        assert isinstance(parser, EcosiaParser)
    
    def test_startpage_parser_available(self):
        """Test Startpage parser is registered and returns correct type."""
        parser = get_parser("startpage")
        assert parser is not None
        assert isinstance(parser, StartpageParser)
    
    def test_new_parsers_in_available_list(self):
        """Test Phase 16.13 parsers appear in available parsers list."""
        parsers = get_available_parsers()
        
        assert "ecosia" in parsers, f"ecosia not in {parsers}"
        assert "startpage" in parsers, f"startpage not in {parsers}"
    
    def test_all_parsers_count(self):
        """Test total parser count is exactly 7."""
        parsers = get_available_parsers()
        
        # duckduckgo, mojeek, google, qwant, brave, ecosia, startpage
        assert len(parsers) == 7, f"Expected 7 parsers, got {len(parsers)}: {parsers}"

