"""
Deep link generation utilities for Lyra.

Provides URL anchor generation for precise source linking.
"""

import re
import unicodedata
from urllib.parse import urlparse, urlunparse


def generate_anchor_slug(heading: str) -> str:
    """Generate URL anchor slug from heading text.

    Uses GitHub-style slug generation:
    - Lowercase
    - Replace spaces with hyphens
    - Remove special characters
    - Handle Japanese text (keep as-is, replace spaces)

    Args:
        heading: Heading text.

    Returns:
        URL-safe anchor slug.
    """
    if not heading:
        return ""

    # Normalize unicode
    text = unicodedata.normalize("NFKC", heading)

    # Lowercase
    text = text.lower()

    # Replace spaces and underscores with hyphens
    text = re.sub(r"[\s_]+", "-", text)

    # Remove characters that aren't alphanumeric, hyphens, or Japanese/CJK
    # Keep: a-z, 0-9, -, Japanese hiragana/katakana/kanji
    text = re.sub(r"[^\w\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff-]", "", text)

    # Remove leading/trailing hyphens
    text = text.strip("-")

    # Collapse multiple hyphens
    text = re.sub(r"-+", "-", text)

    return text


def generate_deep_link(url: str, heading_context: str | None) -> str:
    """Generate a deep link URL with anchor.

    Args:
        url: Base URL.
        heading_context: Heading context for anchor.

    Returns:
        URL with anchor fragment if heading is available.
    """
    if not heading_context:
        return url

    anchor = generate_anchor_slug(heading_context)
    if not anchor:
        return url

    # Parse URL and add fragment
    parsed = urlparse(url)

    # Don't override existing fragment
    if parsed.fragment:
        return url

    # Add anchor fragment
    new_url = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            anchor,
        )
    )

    return new_url
