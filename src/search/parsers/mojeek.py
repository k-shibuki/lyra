"""
Mojeek Search Result Parser.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from src.search.parsers.base import BaseSearchParser, ParsedResult


class MojeekParser(BaseSearchParser):
    """Parser for Mojeek search results."""

    def __init__(self) -> None:
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
