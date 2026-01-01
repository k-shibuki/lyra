"""
Startpage Search Result Parser.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from src.search.parsers.base import BaseSearchParser, ParsedResult


class StartpageParser(BaseSearchParser):
    """Parser for Startpage search results (Google-based, privacy-focused)."""

    def __init__(self) -> None:
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
