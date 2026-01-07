"""
Content extraction for Lyra.
Extracts text, metadata, and structure from HTML documents.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.extractor.html_normalizer import normalize_html
from src.storage.database import get_database
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def extract_content(
    input_path: str | None = None,
    html: str | None = None,
    content_type: str = "html",
    page_id: str | None = None,
) -> dict[str, Any]:
    """Extract content from HTML.

    Args:
        input_path: Path to HTML file.
        html: Raw HTML content.
        content_type: Content type (html only). PDF is not supported.
        page_id: Associated page ID in database.

    Returns:
        Extraction result dictionary.
    """
    if input_path is None and html is None:
        return {
            "ok": False,
            "error": "Either input_path or html must be provided",
        }

    # Check for PDF files (not supported)
    if input_path:
        path = Path(input_path)
        if path.suffix.lower() == ".pdf":
            return {
                "ok": False,
                "error": "PDF extraction is not supported. Only HTML extraction is available.",
            }

    # Only HTML extraction is supported
    if content_type not in ("html", "auto"):
        return {
            "ok": False,
            "error": f"Content type '{content_type}' is not supported. Only HTML extraction is available.",
        }

    return await _extract_html(input_path, html, page_id)


async def _extract_html(
    input_path: str | None,
    html: str | None,
    page_id: str | None,
) -> dict[str, Any]:
    """Extract content from HTML.

    Args:
        input_path: Path to HTML file.
        html: Raw HTML content.
        page_id: Associated page ID.

    Returns:
        Extraction result.
    """
    try:
        import trafilatura

        # Load content
        if html is None and input_path:
            html = Path(input_path).read_text(encoding="utf-8", errors="ignore")

        if html is None:
            return {"ok": False, "error": "No content to extract"}

        # Normalize HTML before extraction (removes script/style/noscript noise)
        normalized_html = normalize_html(html)

        # Extract main content
        # Note: include_links=False to avoid trafilatura's link embedding warnings
        # ("missing link attribute"). Citation links are extracted separately via
        # CitationDetector which uses LinkExtractor on raw HTML.
        extracted = trafilatura.extract(
            normalized_html,
            include_comments=False,
            include_tables=True,
            include_links=False,
            include_images=False,
            output_format="txt",
            favor_precision=True,
        )

        if extracted is None:
            # Fallback to other extractors
            extracted = await _fallback_extract_html(html)

        if extracted is None:
            return {
                "ok": False,
                "error": "Could not extract content",
            }

        # Extract metadata (use normalized HTML for consistency)
        metadata = trafilatura.extract_metadata(normalized_html)

        title = None
        language = None

        if metadata:
            title = metadata.title
            language = metadata.language

        # Extract headings
        headings = _extract_headings(html)

        # Extract tables
        tables = _extract_tables(html)

        # Store fragments in database
        fragments = []
        db = await get_database()

        # Split text into paragraphs
        paragraphs = _split_into_paragraphs(extracted)

        for idx, para in enumerate(paragraphs):
            if len(para.strip()) < 20:  # Skip very short paragraphs
                continue

            text_hash = hashlib.sha256(para.encode()).hexdigest()[:32]
            heading_hierarchy = _build_heading_hierarchy(headings, idx)
            element_index = _calculate_element_index(idx, headings)

            fragment = {
                "text": para,
                "type": "paragraph",
                "position": idx,
                "heading_context": _find_heading_context(idx, headings, paragraphs),
                "heading_hierarchy": heading_hierarchy,
                "element_index": element_index,
                "text_hash": text_hash,
            }
            fragments.append(fragment)

            # Store in database if we have a page_id
            if page_id:
                await db.insert(
                    "fragments",
                    {
                        "page_id": page_id,
                        "fragment_type": "paragraph",
                        "position": idx,
                        "text_content": para,
                        "heading_context": fragment["heading_context"],
                        "heading_hierarchy": json.dumps(heading_hierarchy, ensure_ascii=False),
                        "element_index": element_index,
                        "text_hash": text_hash,
                    },
                )

        logger.info(
            "HTML extraction complete",
            input_path=input_path,
            text_length=len(extracted),
            fragment_count=len(fragments),
        )

        return {
            "ok": True,
            "text": extracted,
            "title": title,
            "language": language,
            "headings": headings,
            "tables": tables,
            "fragments": fragments,
            "meta": {
                "author": metadata.author if metadata else None,
                "date": metadata.date if metadata else None,
                "sitename": metadata.sitename if metadata else None,
            },
        }

    except Exception as e:
        logger.error("HTML extraction error", error=str(e), input_path=input_path)
        return {
            "ok": False,
            "error": str(e),
        }


async def _fallback_extract_html(html: str) -> str | None:
    """Fallback extraction using alternative methods.

    Args:
        html: HTML content.

    Returns:
        Extracted text or None.
    """
    # Try readability-lxml
    try:
        from readability import Document

        doc = Document(html)
        summary = doc.summary()

        # Strip HTML tags from summary
        from html import unescape

        text = re.sub(r"<[^>]+>", " ", summary)
        text = unescape(text)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) > 100:
            return text
    except Exception as e:
        logger.debug("trafilatura extraction failed", error=str(e))

    # Try jusText
    try:
        import justext

        paragraphs = justext.justext(html.encode("utf-8"), justext.get_stoplist("Japanese"))
        text_parts = [p.text for p in paragraphs if not p.is_boilerplate]
        if text_parts:
            return "\n\n".join(text_parts)
    except Exception as e:
        logger.debug("justext extraction failed", error=str(e))

    return None


def _extract_headings(html: str) -> list[dict[str, Any]]:
    """Extract headings from HTML with position information.

    Args:
        html: HTML content.

    Returns:
        List of heading dictionaries with level, text, and position.
    """
    headings = []

    # Simple regex extraction for headings
    heading_pattern = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)

    # Also track paragraph positions to correlate with headings
    paragraph_pattern = re.compile(r"<p[^>]*>.*?</p>", re.IGNORECASE | re.DOTALL)

    # Find all paragraph positions
    para_positions = [m.start() for m in paragraph_pattern.finditer(html)]

    for match in heading_pattern.finditer(html):
        level = int(match.group(1))
        text = re.sub(r"<[^>]+>", "", match.group(2)).strip()

        if text:
            # Calculate position as "number of paragraphs before this heading"
            heading_char_pos = match.start()
            position = sum(1 for p in para_positions if p < heading_char_pos)

            headings.append(
                {
                    "level": level,
                    "text": text,
                    "position": position,
                }
            )

    return headings


def _extract_tables(html: str) -> list[dict[str, Any]]:
    """Extract tables from HTML.

    Args:
        html: HTML content.

    Returns:
        List of table dictionaries.
    """
    tables = []

    # Simple table detection
    table_pattern = re.compile(r"<table[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)

    for idx, match in enumerate(table_pattern.finditer(html)):
        table_html = match.group(1)

        # Extract rows
        rows = []
        row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
        cell_pattern = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.IGNORECASE | re.DOTALL)

        for row_match in row_pattern.finditer(table_html):
            cells = []
            for cell_match in cell_pattern.finditer(row_match.group(1)):
                cell_text = re.sub(r"<[^>]+>", "", cell_match.group(1)).strip()
                cells.append(cell_text)
            if cells:
                rows.append(cells)

        if rows:
            tables.append(
                {
                    "index": idx,
                    "rows": rows,
                }
            )

    return tables


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs.

    Args:
        text: Full text content.

    Returns:
        List of paragraph strings.
    """
    # Split by double newlines
    paragraphs = re.split(r"\n\s*\n", text)

    # Clean up each paragraph
    cleaned = []
    for para in paragraphs:
        para = re.sub(r"\s+", " ", para).strip()
        if para:
            cleaned.append(para)

    return cleaned


def _build_heading_hierarchy(
    headings: list[dict],
    paragraph_idx: int,
) -> list[dict]:
    """Build heading hierarchy for a paragraph position.

    Constructs a list of headings from h1 to the most specific level
    that applies to the given paragraph position.

    Args:
        headings: List of heading dicts with 'level', 'text', 'position'.
        paragraph_idx: Index of the paragraph.

    Returns:
        List of heading dicts representing the hierarchy.
        Example: [{"level": 1, "text": "Title"}, {"level": 2, "text": "Section"}]
    """
    if not headings:
        return []

    # Find all headings that appear before this paragraph
    applicable_headings = [h for h in headings if h.get("position", 0) <= paragraph_idx]

    if not applicable_headings:
        return []

    # Build hierarchy: keep the most recent heading at each level
    hierarchy = {}
    for h in applicable_headings:
        level = h.get("level", 1)
        hierarchy[level] = h
        # Clear deeper levels when a higher-level heading appears
        for deeper in list(hierarchy.keys()):
            if deeper > level:
                del hierarchy[deeper]

    # Sort by level and return
    return [
        {"level": level, "text": hierarchy[level].get("text", "")}
        for level in sorted(hierarchy.keys())
    ]


def _find_heading_context(
    paragraph_idx: int,
    headings: list[dict],
    paragraphs: list[str],
) -> str | None:
    """Find the most recent heading for a paragraph.

    Args:
        paragraph_idx: Index of the paragraph.
        headings: List of headings.
        paragraphs: List of paragraphs.

    Returns:
        Heading text or None (the deepest/most specific heading).
    """
    hierarchy = _build_heading_hierarchy(headings, paragraph_idx)
    if hierarchy:
        # Return the deepest (most specific) heading
        return hierarchy[-1].get("text")
    return None


def _calculate_element_index(
    paragraph_idx: int,
    headings: list[dict],
) -> int:
    """Calculate element index within the current heading section.

    Args:
        paragraph_idx: Index of the paragraph in the document.
        headings: List of headings with positions.

    Returns:
        Index within the current section (0-based).
    """
    if not headings:
        return paragraph_idx

    # Find the most recent heading before this paragraph
    last_heading_pos = 0
    for h in headings:
        pos = h.get("position", 0)
        if pos <= paragraph_idx:
            last_heading_pos = pos
        else:
            break

    return paragraph_idx - last_heading_pos
