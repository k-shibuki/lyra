"""
Bing Search Result Parser.
"""

from __future__ import annotations

import base64
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from src.search.parsers.base import BaseSearchParser, ParsedResult
from src.utils.logging import get_logger

logger = get_logger(__name__)


class BingParser(BaseSearchParser):
    """Parser for Bing search results (high block risk)."""

    def __init__(self) -> None:
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
                    except Exception as e:
                        # If decode fails, return as-is
                        logger.debug(
                            "Base64 URL decode failed", encoded_url=encoded_url[:50], error=str(e)
                        )
                        return encoded_url[2:]
                return encoded_url
        return url

    def _is_internal_url(self, netloc: str) -> bool:
        """Check if URL is internal to Bing."""
        bing_domains = [
            "bing.com",
            "msn.com",
            "microsoft.com",
            "live.com",
            "bing.net",
        ]
        return any(bd in netloc.lower() for bd in bing_domains)
