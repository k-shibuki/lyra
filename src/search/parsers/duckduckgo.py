"""
DuckDuckGo Search Result Parser.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from src.search.parsers.base import BaseSearchParser, ParsedResult


class DuckDuckGoParser(BaseSearchParser):
    """Parser for DuckDuckGo search results."""

    def __init__(self) -> None:
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
            title_elem = container.select_one(
                "h2 a, a[data-testid='result-title-a'], .result__title a"
            )

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
        snippet_elem = container.select_one("[data-testid='result-snippet'], .result__snippet")
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
