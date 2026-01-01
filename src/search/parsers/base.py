"""
Base Search Parser Classes and Utilities.

Provides common functionality for search result parsers:
- BaseSearchParser abstract base class
- ParsedResult and ParseResult data classes
- Helper methods for element extraction and URL normalization
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
from src.search.provider import SERPResult
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

    def to_search_result(self, engine: str, serp_page: int = 1) -> SERPResult:
        """Convert to SERPResult for provider interface.

        Args:
            engine: Search engine name.
            serp_page: SERP page number (1-indexed) for audit/reproducibility.

        Returns:
            SERPResult with page_number set.
        """
        # Import here to avoid circular dependency
        from src.search.parsers.registry import _classify_source

        return SERPResult(
            title=self.title,
            url=self.url,
            snippet=self.snippet,
            date=self.date,
            engine=engine,
            rank=self.rank,
            source_tag=_classify_source(self.url),
            page_number=serp_page,
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
    def success(cls, results: list[ParsedResult]) -> ParseResult:
        """Create successful parse result."""
        return cls(ok=True, results=results)

    @classmethod
    def failure(
        cls,
        error: str,
        selector_errors: list[str] | None = None,
        html_saved_path: str | None = None,
        diagnostic_report: ParserDiagnosticReport | None = None,
    ) -> ParseResult:
        """Create failed parse result."""
        return cls(
            ok=False,
            error=error,
            selector_errors=selector_errors or [],
            html_saved_path=html_saved_path,
            diagnostic_report=diagnostic_report,
        )

    @classmethod
    def captcha(cls, captcha_type: str) -> ParseResult:
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
                failed.append(
                    FailedSelector(
                        name=selector_config.name,
                        selector=selector_config.selector,
                        required=selector_config.required,
                        diagnostic_message=selector_config.diagnostic_message,
                    )
                )

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
        serp_page: int = 1,
        **kwargs: str,
    ) -> str:
        """
        Build search URL for this engine.

        Args:
            query: Search query (will be URL-encoded).
            time_range: Time range filter.
            serp_page: SERP page number (1-indexed).
            **kwargs: Additional URL parameters.

        Returns:
            Complete search URL.
        """
        from urllib.parse import quote_plus

        encoded_query = quote_plus(query)
        return self.config.build_search_url(
            query=encoded_query,
            time_range=time_range,
            serp_page=serp_page,
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
                    if diagnostic_report.candidate_elements
                    else None
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
            href_value = link.get("href")
            if isinstance(href_value, str):
                return href_value
            return None

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
