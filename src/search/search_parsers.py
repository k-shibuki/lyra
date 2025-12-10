"""
Search Result Parsers for Direct Browser Search.

Parses search engine result pages (SERPs) to extract structured results.

Design Philosophy:
- Selectors are loaded from config/search_parsers.yaml (not hardcoded)
- Required selectors fail loudly with diagnostic messages
- Failed HTML is saved for debugging
- AI-friendly error messages enable quick fixes
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from src.search.parser_config import (
    EngineParserConfig,
    SelectorConfig,
    get_parser_config_manager,
    save_debug_html,
)
from src.search.parser_diagnostics import (
    FailedSelector,
    ParserDiagnosticReport,
    create_diagnostic_report,
)
from src.search.provider import SearchResult, SourceTag
from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ParsedResult:
    """A single parsed search result."""
    
    title: str
    url: str
    snippet: str = ""
    date: str | None = None
    rank: int = 0
    raw_element: str | None = None  # For debugging
    
    def to_search_result(self, engine: str) -> SearchResult:
        """Convert to SearchResult for provider interface."""
        return SearchResult(
            title=self.title,
            url=self.url,
            snippet=self.snippet,
            date=self.date,
            engine=engine,
            rank=self.rank,
            source_tag=_classify_source(self.url),
        )


@dataclass
class ParseResult:
    """Result of parsing a search page."""
    
    ok: bool
    results: list[ParsedResult] = field(default_factory=list)
    error: str | None = None
    is_captcha: bool = False
    captcha_type: str | None = None
    selector_errors: list[str] = field(default_factory=list)
    html_saved_path: str | None = None
    diagnostic_report: ParserDiagnosticReport | None = None
    
    @classmethod
    def success(cls, results: list[ParsedResult]) -> "ParseResult":
        """Create successful parse result."""
        return cls(ok=True, results=results)
    
    @classmethod
    def failure(
        cls,
        error: str,
        selector_errors: list[str] | None = None,
        html_saved_path: str | None = None,
        diagnostic_report: ParserDiagnosticReport | None = None,
    ) -> "ParseResult":
        """Create failed parse result."""
        return cls(
            ok=False,
            error=error,
            selector_errors=selector_errors or [],
            html_saved_path=html_saved_path,
            diagnostic_report=diagnostic_report,
        )
    
    @classmethod
    def captcha(cls, captcha_type: str) -> "ParseResult":
        """Create CAPTCHA detection result."""
        return cls(
            ok=False,
            is_captcha=True,
            captcha_type=captcha_type,
            error=f"CAPTCHA detected: {captcha_type}",
        )


# =============================================================================
# Base Parser
# =============================================================================


class BaseSearchParser(ABC):
    """
    Base class for search result parsers.
    
    Provides common functionality for:
    - Loading configuration from search_parsers.yaml
    - Selector-based element finding with validation
    - CAPTCHA detection
    - Debug HTML saving
    - Error reporting with diagnostic messages
    
    Subclasses implement engine-specific result extraction.
    """
    
    def __init__(self, engine_name: str):
        """
        Initialize parser.
        
        Args:
            engine_name: Name of search engine (e.g., "duckduckgo").
        """
        self.engine_name = engine_name
        self._config: EngineParserConfig | None = None
    
    @property
    def config(self) -> EngineParserConfig:
        """Get parser configuration (lazy-loaded)."""
        if self._config is None:
            manager = get_parser_config_manager()
            config = manager.get_engine_config(self.engine_name)
            if config is None:
                raise ValueError(f"No parser configuration for engine: {self.engine_name}")
            self._config = config
        return self._config
    
    def reload_config(self) -> None:
        """Force reload of configuration."""
        self._config = None
    
    def get_selector(self, name: str) -> SelectorConfig | None:
        """Get selector configuration by name."""
        return self.config.get_selector(name)
    
    def find_elements(
        self,
        soup: BeautifulSoup,
        selector_name: str,
        parent: Tag | None = None,
    ) -> list[Tag]:
        """
        Find elements using configured selector.
        
        Args:
            soup: BeautifulSoup object.
            selector_name: Name of selector from config.
            parent: Parent element to search within.
            
        Returns:
            List of matching elements.
        """
        selector_config = self.get_selector(selector_name)
        if selector_config is None:
            logger.warning(f"Selector '{selector_name}' not configured for {self.engine_name}")
            return []
        
        search_context = parent if parent is not None else soup
        
        try:
            elements = search_context.select(selector_config.selector)
            return elements
        except Exception as e:
            logger.warning(
                f"Selector '{selector_name}' failed",
                selector=selector_config.selector,
                error=str(e),
            )
            return []
    
    def find_element(
        self,
        soup: BeautifulSoup,
        selector_name: str,
        parent: Tag | None = None,
    ) -> Tag | None:
        """
        Find single element using configured selector.
        
        Args:
            soup: BeautifulSoup object.
            selector_name: Name of selector from config.
            parent: Parent element to search within.
            
        Returns:
            First matching element or None.
        """
        elements = self.find_elements(soup, selector_name, parent)
        return elements[0] if elements else None
    
    def validate_required_selectors(
        self,
        soup: BeautifulSoup,
    ) -> tuple[bool, list[str]]:
        """
        Validate that all required selectors find elements.
        
        Args:
            soup: BeautifulSoup object.
            
        Returns:
            Tuple of (all_valid, list of error messages).
        """
        errors = []
        
        for selector_config in self.config.get_required_selectors():
            elements = self.find_elements(soup, selector_config.name)
            if not elements:
                error_msg = selector_config.get_error_message(self.engine_name)
                errors.append(error_msg)
                logger.error(
                    "Required selector not found",
                    engine=self.engine_name,
                    selector=selector_config.name,
                )
        
        return len(errors) == 0, errors
    
    def _collect_failed_selectors(self, soup: BeautifulSoup) -> list[FailedSelector]:
        """
        Collect detailed information about failed selectors.
        
        Args:
            soup: BeautifulSoup object.
            
        Returns:
            List of FailedSelector objects.
        """
        failed = []
        
        for selector_config in self.config.get_required_selectors():
            elements = self.find_elements(soup, selector_config.name)
            if not elements:
                failed.append(FailedSelector(
                    name=selector_config.name,
                    selector=selector_config.selector,
                    required=selector_config.required,
                    diagnostic_message=selector_config.diagnostic_message,
                ))
        
        return failed
    
    def detect_captcha(self, html: str) -> tuple[bool, str | None]:
        """
        Check if HTML contains CAPTCHA/challenge.
        
        Args:
            html: HTML content.
            
        Returns:
            Tuple of (is_captcha, captcha_type).
        """
        return self.config.detect_captcha(html)
    
    def build_search_url(
        self,
        query: str,
        time_range: str = "all",
        **kwargs,
    ) -> str:
        """
        Build search URL for this engine.
        
        Args:
            query: Search query (will be URL-encoded).
            time_range: Time range filter.
            **kwargs: Additional URL parameters.
            
        Returns:
            Complete search URL.
        """
        from urllib.parse import quote_plus
        
        encoded_query = quote_plus(query)
        return self.config.build_search_url(
            query=encoded_query,
            time_range=time_range,
            **kwargs,
        )
    
    def parse(self, html: str, query: str = "") -> ParseResult:
        """
        Parse search results from HTML.
        
        Args:
            html: HTML content of search results page.
            query: Original search query (for error reporting).
            
        Returns:
            ParseResult with extracted results or error information.
        """
        # Check for CAPTCHA first
        is_captcha, captcha_type = self.detect_captcha(html)
        if is_captcha:
            logger.warning(
                "CAPTCHA detected",
                engine=self.engine_name,
                captcha_type=captcha_type,
            )
            return ParseResult.captcha(captcha_type or "unknown")
        
        # Parse HTML
        soup = BeautifulSoup(html, "html.parser")
        
        # Validate required selectors
        valid, errors = self.validate_required_selectors(soup)
        if not valid:
            # Save HTML for debugging
            saved_path = save_debug_html(
                html=html,
                engine=self.engine_name,
                query=query,
                error="; ".join(errors),
            )
            
            # Create diagnostic report for AI-assisted repair
            failed_selectors = self._collect_failed_selectors(soup)
            diagnostic_report = create_diagnostic_report(
                engine=self.engine_name,
                query=query,
                html=html,
                failed_selectors=failed_selectors,
                html_path=saved_path,
            )
            
            # Log with structured diagnostic information
            logger.error(
                "Parser failure - AI repair suggested",
                engine=self.engine_name,
                query=query[:50] if query else "",
                failed_selectors=[s.name for s in failed_selectors],
                candidate_count=len(diagnostic_report.candidate_elements),
                html_path=str(saved_path) if saved_path else None,
                top_candidate=(
                    diagnostic_report.candidate_elements[0].selector
                    if diagnostic_report.candidate_elements else None
                ),
                has_suggestions=len(diagnostic_report.suggested_fixes) > 0,
            )
            
            return ParseResult.failure(
                error=f"Required selectors not found: {len(errors)} errors",
                selector_errors=errors,
                html_saved_path=str(saved_path) if saved_path else None,
                diagnostic_report=diagnostic_report,
            )
        
        # Extract results (engine-specific implementation)
        try:
            results = self._extract_results(soup)
            
            # Assign ranks
            for i, result in enumerate(results):
                result.rank = i + 1
            
            logger.info(
                "Parsed search results",
                engine=self.engine_name,
                result_count=len(results),
                query=query[:50] if query else "",
            )
            
            return ParseResult.success(results)
            
        except Exception as e:
            logger.error(
                "Result extraction failed",
                engine=self.engine_name,
                error=str(e),
            )
            
            # Save HTML for debugging
            saved_path = save_debug_html(
                html=html,
                engine=self.engine_name,
                query=query,
                error=str(e),
            )
            
            # Create diagnostic report for extraction failures too
            diagnostic_report = create_diagnostic_report(
                engine=self.engine_name,
                query=query,
                html=html,
                failed_selectors=[],  # No specific selector failed
                html_path=saved_path,
            )
            
            logger.error(
                "Parser failure - AI repair suggested",
                engine=self.engine_name,
                query=query[:50] if query else "",
                extraction_error=str(e),
                candidate_count=len(diagnostic_report.candidate_elements),
                html_path=str(saved_path) if saved_path else None,
            )
            
            return ParseResult.failure(
                error=f"Extraction failed: {e}",
                html_saved_path=str(saved_path) if saved_path else None,
                diagnostic_report=diagnostic_report,
            )
    
    @abstractmethod
    def _extract_results(self, soup: BeautifulSoup) -> list[ParsedResult]:
        """
        Extract search results from parsed HTML.
        
        Subclasses implement engine-specific extraction logic.
        
        Args:
            soup: BeautifulSoup object.
            
        Returns:
            List of ParsedResult objects.
        """
        pass
    
    def _extract_text(self, element: Tag | None, default: str = "") -> str:
        """Safely extract text from element."""
        if element is None:
            return default
        return element.get_text(strip=True) or default
    
    def _extract_href(self, element: Tag | None) -> str | None:
        """Safely extract href from element."""
        if element is None:
            return None
        
        # Try direct href
        href = element.get("href")
        if href:
            return str(href)
        
        # Try finding link child
        link = element.find("a")
        if link:
            return link.get("href")
        
        return None
    
    def _normalize_url(self, url: str | None, base_url: str = "") -> str | None:
        """Normalize and validate URL."""
        if not url:
            return None
        
        # Skip javascript: and other non-http URLs
        if url.startswith(("javascript:", "mailto:", "#")):
            return None
        
        # Handle relative URLs
        if not url.startswith(("http://", "https://")):
            if base_url:
                url = urljoin(base_url, url)
            else:
                return None
        
        # Skip search engine internal URLs
        parsed = urlparse(url)
        if self._is_internal_url(parsed.netloc):
            return None
        
        return url
    
    def _is_internal_url(self, netloc: str) -> bool:
        """Check if URL is internal to search engine (override in subclass)."""
        return False


# =============================================================================
# DuckDuckGo Parser
# =============================================================================


class DuckDuckGoParser(BaseSearchParser):
    """Parser for DuckDuckGo search results."""
    
    def __init__(self):
        super().__init__("duckduckgo")
    
    def _extract_results(self, soup: BeautifulSoup) -> list[ParsedResult]:
        """Extract results from DuckDuckGo SERP."""
        results = []
        
        # Try primary selector
        containers = self.find_elements(soup, "results_container")
        
        # Try alternative selector if primary fails
        if not containers:
            containers = self.find_elements(soup, "results_container_alt")
        
        for container in containers:
            result = self._extract_single_result(container)
            if result:
                results.append(result)
        
        return results
    
    def _extract_single_result(self, container: Tag) -> ParsedResult | None:
        """Extract a single result from container."""
        # Extract title and URL
        title_elem = self.find_element(BeautifulSoup(str(container), "html.parser"), "title")
        url_elem = self.find_element(BeautifulSoup(str(container), "html.parser"), "url")
        
        # Fallback: try direct search in container
        if title_elem is None:
            title_elem = container.select_one("h2 a, a[data-testid='result-title-a'], .result__title a")
        
        if url_elem is None:
            url_elem = container.select_one("a[data-testid='result-title-a'], h2 a")
        
        if title_elem is None or url_elem is None:
            return None
        
        title = self._extract_text(title_elem)
        url = self._extract_href(url_elem)
        
        if not title or not url:
            return None
        
        url = self._normalize_url(url, "https://duckduckgo.com")
        if not url:
            return None
        
        # Extract snippet
        snippet_elem = container.select_one(
            "[data-testid='result-snippet'], .result__snippet"
        )
        snippet = self._extract_text(snippet_elem)
        
        # Extract date (if available)
        date_elem = container.select_one(".result__timestamp, time")
        date = self._extract_text(date_elem) if date_elem else None
        
        return ParsedResult(
            title=title,
            url=url,
            snippet=snippet,
            date=date,
        )
    
    def _is_internal_url(self, netloc: str) -> bool:
        """Check if URL is internal to DuckDuckGo."""
        ddg_domains = ["duckduckgo.com", "duck.co", "spreadprivacy.com"]
        return any(ddg in netloc.lower() for ddg in ddg_domains)


# =============================================================================
# Mojeek Parser
# =============================================================================


class MojeekParser(BaseSearchParser):
    """Parser for Mojeek search results."""
    
    def __init__(self):
        super().__init__("mojeek")
    
    def _extract_results(self, soup: BeautifulSoup) -> list[ParsedResult]:
        """Extract results from Mojeek SERP."""
        results = []
        
        containers = self.find_elements(soup, "results_container")
        
        for container in containers:
            result = self._extract_single_result(container)
            if result:
                results.append(result)
        
        return results
    
    def _extract_single_result(self, container: Tag) -> ParsedResult | None:
        """Extract a single result from container."""
        # Extract title and URL
        title_elem = container.select_one("a.title, h2 a, .result-title a")
        
        if title_elem is None:
            return None
        
        title = self._extract_text(title_elem)
        url = self._extract_href(title_elem)
        
        if not title or not url:
            return None
        
        url = self._normalize_url(url, "https://www.mojeek.com")
        if not url:
            return None
        
        # Extract snippet
        snippet_elem = container.select_one(".s, .result-snippet, p.s")
        snippet = self._extract_text(snippet_elem)
        
        # Extract date
        date_elem = container.select_one(".date, time")
        date = self._extract_text(date_elem) if date_elem else None
        
        return ParsedResult(
            title=title,
            url=url,
            snippet=snippet,
            date=date,
        )
    
    def _is_internal_url(self, netloc: str) -> bool:
        """Check if URL is internal to Mojeek."""
        return "mojeek.com" in netloc.lower()


# =============================================================================
# Google Parser
# =============================================================================


class GoogleParser(BaseSearchParser):
    """Parser for Google search results (high block risk)."""
    
    def __init__(self):
        super().__init__("google")
    
    def _extract_results(self, soup: BeautifulSoup) -> list[ParsedResult]:
        """Extract results from Google SERP."""
        results = []
        
        containers = self.find_elements(soup, "results_container")
        
        for container in containers:
            result = self._extract_single_result(container)
            if result:
                results.append(result)
        
        return results
    
    def _extract_single_result(self, container: Tag) -> ParsedResult | None:
        """Extract a single result from container."""
        # Extract title
        title_elem = container.select_one("h3, .LC20lb")
        if title_elem is None:
            return None
        
        title = self._extract_text(title_elem)
        
        # Extract URL (find parent link or sibling)
        url_elem = container.select_one("a[href^='http'], a[data-ved]")
        if url_elem is None:
            # Try finding link around title
            parent = title_elem.parent
            if parent and parent.name == "a":
                url_elem = parent
            else:
                url_elem = container.find("a")
        
        if url_elem is None:
            return None
        
        url = self._extract_href(url_elem)
        if not url:
            return None
        
        # Handle Google redirect URLs
        url = self._clean_google_url(url)
        if not url:
            return None
        
        url = self._normalize_url(url, "https://www.google.com")
        if not url:
            return None
        
        # Extract snippet
        snippet_elem = container.select_one(".VwiC3b, .IsZvec, .aCOpRe span")
        snippet = self._extract_text(snippet_elem)
        
        # Extract date
        date_elem = container.select_one(".MUxGbd, span.LEwnzc")
        date = self._extract_text(date_elem) if date_elem else None
        
        return ParsedResult(
            title=title,
            url=url,
            snippet=snippet,
            date=date,
        )
    
    def _clean_google_url(self, url: str) -> str | None:
        """Clean Google redirect URL to get actual destination."""
        if "/url?" in url:
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            if "q" in params:
                return params["q"][0]
            if "url" in params:
                return params["url"][0]
        return url
    
    def _is_internal_url(self, netloc: str) -> bool:
        """Check if URL is internal to Google."""
        google_domains = [
            "google.com", "google.co.jp", "google.co.uk",
            "gstatic.com", "googleapis.com",
        ]
        return any(gd in netloc.lower() for gd in google_domains)


# =============================================================================
# Brave Parser
# =============================================================================


class BraveParser(BaseSearchParser):
    """Parser for Brave Search results."""
    
    def __init__(self):
        super().__init__("brave")
    
    def _extract_results(self, soup: BeautifulSoup) -> list[ParsedResult]:
        """Extract results from Brave Search SERP."""
        results = []
        
        containers = self.find_elements(soup, "results_container")
        
        for container in containers:
            result = self._extract_single_result(container)
            if result:
                results.append(result)
        
        return results
    
    def _extract_single_result(self, container: Tag) -> ParsedResult | None:
        """Extract a single result from container."""
        # Extract title
        title_elem = container.select_one(".title, .snippet-title")
        if title_elem is None:
            return None
        
        title = self._extract_text(title_elem)
        
        # Extract URL
        url_elem = container.select_one(".url, a[href^='http']")
        if url_elem is None:
            return None
        
        url = self._extract_href(url_elem)
        if not url:
            # Try getting text as URL
            url = self._extract_text(url_elem)
        
        if not url:
            return None
        
        url = self._normalize_url(url, "https://search.brave.com")
        if not url:
            return None
        
        # Extract snippet
        snippet_elem = container.select_one(".snippet-description, .desc")
        snippet = self._extract_text(snippet_elem)
        
        return ParsedResult(
            title=title,
            url=url,
            snippet=snippet,
        )
    
    def _is_internal_url(self, netloc: str) -> bool:
        """Check if URL is internal to Brave."""
        return "brave.com" in netloc.lower()


# =============================================================================
# Ecosia Parser
# =============================================================================


class EcosiaParser(BaseSearchParser):
    """Parser for Ecosia search results (Bing-based, relatively lenient)."""
    
    def __init__(self):
        super().__init__("ecosia")
    
    def _extract_results(self, soup: BeautifulSoup) -> list[ParsedResult]:
        """Extract results from Ecosia SERP."""
        results = []
        
        containers = self.find_elements(soup, "results_container")
        
        for container in containers:
            result = self._extract_single_result(container)
            if result:
                results.append(result)
        
        return results
    
    def _extract_single_result(self, container: Tag) -> ParsedResult | None:
        """Extract a single result from container."""
        # Extract title (updated for current Ecosia HTML structure)
        # Title is in .result__title or .result-title__heading
        title_elem = container.select_one(".result-title__heading, .result__title, h2 a")
        if title_elem is None:
            return None
        
        title = self._extract_text(title_elem)
        if not title:
            return None
        
        # Extract URL - the actual result link is inside .result__title or has data-test-id="result-link"
        url_elem = container.select_one("a[data-test-id='result-link'], .result__title a, a.result__link[href^='http']")
        if url_elem is None:
            # Try parent link
            if title_elem.name == "a":
                url_elem = title_elem
            else:
                url_elem = title_elem.find_parent("a")
        
        if url_elem is None:
            return None
        
        url = self._extract_href(url_elem)
        if not url:
            return None
        
        url = self._normalize_url(url, "https://www.ecosia.org")
        if not url:
            return None
        
        # Extract snippet (updated for current Ecosia HTML structure)
        snippet_elem = container.select_one(".result__description, .web-result__description, p")
        snippet = self._extract_text(snippet_elem)
        
        # Extract date
        date_elem = container.select_one(".result-date, time")
        date = self._extract_text(date_elem) if date_elem else None
        
        return ParsedResult(
            title=title,
            url=url,
            snippet=snippet,
            date=date,
        )
    
    def _is_internal_url(self, netloc: str) -> bool:
        """Check if URL is internal to Ecosia."""
        ecosia_domains = ["ecosia.org", "bing.com"]
        return any(ed in netloc.lower() for ed in ecosia_domains)


# =============================================================================
# Startpage Parser
# =============================================================================


class StartpageParser(BaseSearchParser):
    """Parser for Startpage search results (Google-based, privacy-focused)."""
    
    def __init__(self):
        super().__init__("startpage")
    
    def _extract_results(self, soup: BeautifulSoup) -> list[ParsedResult]:
        """Extract results from Startpage SERP."""
        results = []
        
        containers = self.find_elements(soup, "results_container")
        
        for container in containers:
            result = self._extract_single_result(container)
            if result:
                results.append(result)
        
        return results
    
    def _extract_single_result(self, container: Tag) -> ParsedResult | None:
        """Extract a single result from container."""
        # Extract title (updated for current Startpage HTML structure)
        # .wgl-title contains text, .result-title is the link element
        title_elem = container.select_one(".wgl-title, .result-title, h3")
        if title_elem is None:
            return None
        
        title = self._extract_text(title_elem)
        if not title:
            return None
        
        # Extract URL - .result-title is usually the link itself
        url_elem = container.select_one("a.result-title, a.result-link, a[href^='http']")
        if url_elem is None:
            # Try parent link or find link in container
            if title_elem.name == "a":
                url_elem = title_elem
            else:
                url_elem = title_elem.find_parent("a")
                if url_elem is None:
                    url_elem = container.select_one("a[href^='http']")
        
        if url_elem is None:
            return None
        
        url = self._extract_href(url_elem)
        if not url:
            return None
        
        # Startpage sometimes uses proxy URLs
        url = self._clean_startpage_url(url)
        
        url = self._normalize_url(url, "https://www.startpage.com")
        if not url:
            return None
        
        # Extract snippet (updated for current Startpage HTML structure)
        snippet_elem = container.select_one(".description, .w-gl__description, p.description")
        snippet = self._extract_text(snippet_elem)
        
        # Extract date
        date_elem = container.select_one(".w-gl__result-date, time, .result-date")
        date = self._extract_text(date_elem) if date_elem else None
        
        return ParsedResult(
            title=title,
            url=url,
            snippet=snippet,
            date=date,
        )
    
    def _clean_startpage_url(self, url: str) -> str:
        """Clean Startpage proxy URL to get actual destination."""
        from urllib.parse import parse_qs, urlparse
        
        # Startpage uses /do/proxy for anonymous viewing
        if "/do/proxy" in url or "/do/metasearch" in url:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            if "url" in params:
                return params["url"][0]
            if "u" in params:
                return params["u"][0]
        return url
    
    def _is_internal_url(self, netloc: str) -> bool:
        """Check if URL is internal to Startpage."""
        return "startpage.com" in netloc.lower()


# =============================================================================
# Bing Parser
# =============================================================================


class BingParser(BaseSearchParser):
    """Parser for Bing search results (high block risk)."""
    
    def __init__(self):
        super().__init__("bing")
    
    def _extract_results(self, soup: BeautifulSoup) -> list[ParsedResult]:
        """Extract results from Bing SERP."""
        results = []
        
        containers = self.find_elements(soup, "results_container")
        
        for container in containers:
            result = self._extract_single_result(container)
            if result:
                results.append(result)
        
        return results
    
    def _extract_single_result(self, container: Tag) -> ParsedResult | None:
        """Extract a single result from container."""
        # Extract title
        title_elem = container.select_one("h2 a, .b_title a")
        if title_elem is None:
            return None
        
        title = self._extract_text(title_elem)
        
        # Extract URL from the title link
        url = self._extract_href(title_elem)
        if not url:
            # Try cite element as fallback
            cite_elem = container.select_one("cite")
            if cite_elem:
                url = self._extract_text(cite_elem)
                # Add protocol if missing
                if url and not url.startswith(("http://", "https://")):
                    url = "https://" + url
        
        if not url:
            return None
        
        # Handle Bing redirect URLs
        url = self._clean_bing_url(url)
        if not url:
            return None
        
        url = self._normalize_url(url, "https://www.bing.com")
        if not url:
            return None
        
        # Extract snippet
        snippet_elem = container.select_one(".b_caption p, .b_lineclamp2, .b_paractl")
        snippet = self._extract_text(snippet_elem)
        
        # Extract date
        date_elem = container.select_one(".news_dt, span.sc_hl")
        date = self._extract_text(date_elem) if date_elem else None
        
        return ParsedResult(
            title=title,
            url=url,
            snippet=snippet,
            date=date,
        )
    
    def _clean_bing_url(self, url: str) -> str | None:
        """Clean Bing redirect URL to get actual destination."""
        import base64
        from urllib.parse import parse_qs, urlparse, unquote
        
        # Bing uses /ck/a for click tracking
        if "/ck/a" in url or "bing.com/ck" in url:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            if "u" in params:
                # Bing encodes the URL in 'u' parameter with base64
                encoded_url = params["u"][0]
                # Bing uses a1, a2, etc. prefixes before base64
                if encoded_url.startswith(("a1", "a2", "a3")):
                    try:
                        # Remove prefix and decode base64
                        b64_part = encoded_url[2:]
                        # Add padding if needed
                        padding = 4 - len(b64_part) % 4
                        if padding != 4:
                            b64_part += "=" * padding
                        decoded = base64.urlsafe_b64decode(b64_part).decode("utf-8")
                        return decoded
                    except Exception:
                        # If decode fails, return as-is
                        return encoded_url[2:]
                return encoded_url
        return url
    
    def _is_internal_url(self, netloc: str) -> bool:
        """Check if URL is internal to Bing."""
        bing_domains = [
            "bing.com", "msn.com", "microsoft.com",
            "live.com", "bing.net",
        ]
        return any(bd in netloc.lower() for bd in bing_domains)


# =============================================================================
# Parser Registry
# =============================================================================


_parser_registry: dict[str, type[BaseSearchParser]] = {
    "duckduckgo": DuckDuckGoParser,
    "mojeek": MojeekParser,
    "google": GoogleParser,
    "brave": BraveParser,
    "ecosia": EcosiaParser,
    "startpage": StartpageParser,
    "bing": BingParser,
}


def get_parser(engine_name: str) -> BaseSearchParser | None:
    """
    Get parser instance for an engine.
    
    Args:
        engine_name: Engine name (case-insensitive).
        
    Returns:
        Parser instance or None if not available.
    """
    name_lower = engine_name.lower()
    parser_class = _parser_registry.get(name_lower)
    
    if parser_class is None:
        logger.warning(f"No parser available for engine: {engine_name}")
        return None
    
    # Check if configuration exists
    manager = get_parser_config_manager()
    if not manager.is_engine_configured(name_lower):
        logger.warning(f"Engine {engine_name} not configured in search_parsers.yaml")
        return None
    
    return parser_class()


def get_available_parsers() -> list[str]:
    """Get list of available parser engine names."""
    manager = get_parser_config_manager()
    configured = set(manager.get_available_engines())
    registered = set(_parser_registry.keys())
    return sorted(configured & registered)


def register_parser(engine_name: str, parser_class: type[BaseSearchParser]) -> None:
    """
    Register a custom parser for an engine.
    
    Args:
        engine_name: Engine name.
        parser_class: Parser class (must inherit BaseSearchParser).
    """
    if not issubclass(parser_class, BaseSearchParser):
        raise TypeError("Parser must inherit from BaseSearchParser")
    
    _parser_registry[engine_name.lower()] = parser_class
    logger.info(f"Registered parser for engine: {engine_name}")


# =============================================================================
# Helper Functions
# =============================================================================


def _classify_source(url: str) -> SourceTag:
    """
    Classify source type based on URL.
    
    Reuses classification logic from search_api and converts to SourceTag enum.
    """
    # Import here to avoid circular dependency
    try:
        from src.search.search_api import _classify_source as classify_source
        tag_str = classify_source(url)
        # Convert string to SourceTag enum
        try:
            return SourceTag(tag_str)
        except ValueError:
            return SourceTag.UNKNOWN
    except ImportError:
        # Fallback classification
        url_lower = url.lower()
        
        if any(d in url_lower for d in ["arxiv.org", "pubmed", "scholar.google"]):
            return SourceTag.ACADEMIC
        if any(p in url_lower for p in [".gov", ".go.jp", ".gov.uk"]):
            return SourceTag.GOVERNMENT
        if "wikipedia.org" in url_lower:
            return SourceTag.KNOWLEDGE
        
        return SourceTag.UNKNOWN

