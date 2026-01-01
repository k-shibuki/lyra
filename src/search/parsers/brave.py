"""
Brave Search Result Parser.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from src.search.parsers.base import BaseSearchParser, ParsedResult


class BraveParser(BaseSearchParser):
    """Parser for Brave Search results."""

    def __init__(self) -> None:
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
