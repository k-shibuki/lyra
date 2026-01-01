"""
Ecosia Search Result Parser.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from src.search.parsers.base import BaseSearchParser, ParsedResult


class EcosiaParser(BaseSearchParser):
    """Parser for Ecosia search results (Bing-based, relatively lenient)."""

    def __init__(self) -> None:
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
        url_elem = container.select_one(
            "a[data-test-id='result-link'], .result__title a, a.result__link[href^='http']"
        )
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
