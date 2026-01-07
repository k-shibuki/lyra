"""
HTML normalization utilities for Lyra.

Provides lightweight preprocessing for HTML before content extraction
or link analysis. Designed to work with both trafilatura and BeautifulSoup.
"""

import re
from urllib.parse import urljoin, urlparse

from src.utils.logging import get_logger

logger = get_logger(__name__)


def normalize_html(html: str) -> str:
    """Normalize HTML for extraction.

    Performs minimal preprocessing to reduce noise without altering
    meaningful content structure:
    - Removes script, style, noscript tags and their contents
    - Collapses excessive whitespace
    - Preserves overall document structure for downstream parsers

    Args:
        html: Raw HTML string.

    Returns:
        Normalized HTML string.
    """
    if not html:
        return html

    # Remove script tags and contents
    html = re.sub(
        r"<script[^>]*>.*?</script>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove style tags and contents
    html = re.sub(
        r"<style[^>]*>.*?</style>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove noscript tags and contents
    html = re.sub(
        r"<noscript[^>]*>.*?</noscript>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove HTML comments (but not conditional comments for IE compatibility)
    html = re.sub(
        r"<!--(?!\[if).*?-->",
        "",
        html,
        flags=re.DOTALL,
    )

    # Collapse multiple whitespace (but preserve single newlines for structure)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n\s*\n+", "\n\n", html)

    return html.strip()


def get_effective_base_url(html: str, fallback_url: str) -> str:
    """Get effective base URL for resolving relative links.

    Checks for <base href="..."> tag in HTML and uses it if valid.
    Falls back to the provided URL if no valid base tag is found.

    Args:
        html: HTML string to search for base tag.
        fallback_url: URL to use if no base tag is found.

    Returns:
        Effective base URL for relative link resolution.
    """
    if not html:
        return fallback_url

    # Look for <base href="..."> tag
    # Handles both single and double quotes, and potential whitespace
    base_pattern = re.compile(
        r'<base\s+[^>]*href\s*=\s*["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    match = base_pattern.search(html)

    if match:
        base_href = match.group(1).strip()

        # Validate that it's a usable URL
        if base_href:
            parsed = urlparse(base_href)

            # If it's a relative URL, resolve against fallback
            if not parsed.scheme:
                base_href = urljoin(fallback_url, base_href)

            # Validate the resolved URL has a scheme
            parsed = urlparse(base_href)
            if parsed.scheme in ("http", "https"):
                logger.debug(
                    "Using base href for URL resolution",
                    base_href=base_href[:80],
                    fallback_url=fallback_url[:80],
                )
                return base_href

    return fallback_url
