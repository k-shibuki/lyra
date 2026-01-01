"""
Google Search Result Parser.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from src.search.parsers.base import BaseSearchParser, ParsedResult


class GoogleParser(BaseSearchParser):
    """Parser for Google search results (high block risk)."""

    def __init__(self) -> None:
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
            "google.com",
            "google.co.jp",
            "google.co.uk",
            "gstatic.com",
            "googleapis.com",
        ]
        return any(gd in netloc.lower() for gd in google_domains)
