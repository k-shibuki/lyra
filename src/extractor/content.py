"""
Content extraction for Lancet.
Extracts text, metadata, and structure from HTML and PDF documents.

OCR Support (§5.1.1):
- PaddleOCR (GPU-capable): Primary OCR engine for scanned PDFs/images
- Tesseract: Lightweight fallback when PaddleOCR unavailable
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.storage.database import get_database
from src.utils.logging import get_logger

logger = get_logger(__name__)

# OCR availability flags (lazy initialization)
_paddleocr_available: bool | None = None
_tesseract_available: bool | None = None
_paddleocr_instance = None


def _check_paddleocr_available() -> bool:
    """Check if PaddleOCR is available."""
    global _paddleocr_available
    if _paddleocr_available is None:
        try:
            import paddleocr  # noqa: F401

            _paddleocr_available = True
            logger.debug("PaddleOCR is available")
        except ImportError:
            _paddleocr_available = False
            logger.debug("PaddleOCR is not available")
    return _paddleocr_available


def _check_tesseract_available() -> bool:
    """Check if Tesseract is available."""
    global _tesseract_available
    if _tesseract_available is None:
        try:
            import pytesseract

            # Verify tesseract binary is installed
            pytesseract.get_tesseract_version()
            _tesseract_available = True
            logger.debug("Tesseract is available")
        except Exception:
            _tesseract_available = False
            logger.debug("Tesseract is not available")
    return _tesseract_available


def _get_paddleocr_instance() -> Any:
    """Get or create PaddleOCR instance (singleton for efficiency)."""
    global _paddleocr_instance
    if _paddleocr_instance is None and _check_paddleocr_available():
        from paddleocr import PaddleOCR

        # Enable GPU if available, support Japanese and English
        _paddleocr_instance = PaddleOCR(
            use_angle_cls=True,
            lang="japan",  # Supports Japanese + English
            use_gpu=True,  # Will fallback to CPU if GPU unavailable
            show_log=False,
        )
        logger.info("PaddleOCR instance created")
    return _paddleocr_instance


async def extract_content(
    input_path: str | None = None,
    html: str | None = None,
    content_type: str = "auto",
    page_id: str | None = None,
) -> dict[str, Any]:
    """Extract content from HTML or PDF.

    Args:
        input_path: Path to HTML or PDF file.
        html: Raw HTML content.
        content_type: Content type (html, pdf, auto).
        page_id: Associated page ID in database.

    Returns:
        Extraction result dictionary.
    """
    if input_path is None and html is None:
        return {
            "ok": False,
            "error": "Either input_path or html must be provided",
        }

    # Determine content type
    if content_type == "auto":
        if input_path:
            path = Path(input_path)
            if path.suffix.lower() == ".pdf":
                content_type = "pdf"
            else:
                content_type = "html"
        else:
            content_type = "html"

    # Extract based on type
    if content_type == "pdf":
        return await _extract_pdf(input_path)
    else:
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

        # Extract main content
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            include_links=True,
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

        # Extract metadata
        metadata = trafilatura.extract_metadata(html)

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


async def _extract_pdf(
    input_path: str,
    ocr_threshold: int = 100,
    force_ocr: bool = False,
) -> dict[str, Any]:
    """Extract content from PDF with OCR support.

    OCR is applied when:
    - force_ocr is True, or
    - Extracted text per page is below ocr_threshold characters (scanned PDF detection)

    Args:
        input_path: Path to PDF file.
        ocr_threshold: Minimum chars per page before OCR is triggered (default: 100).
        force_ocr: Force OCR even if text is extractable.

    Returns:
        Extraction result.
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(input_path)

        text_parts = []
        headings = []
        tables = []
        ocr_used = False
        ocr_pages = []

        for page_num, page in enumerate(doc):
            # Extract text using standard method
            text = page.get_text("text")

            # Check if OCR is needed for this page
            text_length = len(text.strip())
            needs_ocr = force_ocr or (text_length < ocr_threshold)

            if needs_ocr:
                # Try OCR for this page
                ocr_text = await _ocr_pdf_page(page, page_num)
                if ocr_text and len(ocr_text.strip()) > text_length:
                    text = ocr_text
                    ocr_used = True
                    ocr_pages.append(page_num + 1)
                    logger.debug(
                        "OCR applied to page",
                        page=page_num + 1,
                        original_length=text_length,
                        ocr_length=len(ocr_text),
                    )

            text_parts.append(text)

            # Try to extract structure (only from non-OCR pages)
            if not needs_ocr:
                blocks = page.get_text("dict")["blocks"]
                for block in blocks:
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                # Detect headings by font size
                                if span["size"] > 14:
                                    headings.append(
                                        {
                                            "level": 1 if span["size"] > 18 else 2,
                                            "text": span["text"].strip(),
                                            "page": page_num + 1,
                                        }
                                    )

        # Extract PDF metadata
        metadata = doc.metadata
        title = metadata.get("title") if metadata else None

        doc.close()

        full_text = "\n\n".join(text_parts)

        logger.info(
            "PDF extraction complete",
            input_path=input_path,
            page_count=len(text_parts),
            text_length=len(full_text),
            ocr_used=ocr_used,
            ocr_pages=ocr_pages if ocr_pages else None,
        )

        return {
            "ok": True,
            "text": full_text,
            "title": title,
            "language": None,
            "headings": headings,
            "tables": tables,
            "meta": {
                "page_count": len(text_parts),
                "ocr_used": ocr_used,
                "ocr_pages": ocr_pages if ocr_pages else None,
            },
        }

    except Exception as e:
        logger.error("PDF extraction error", error=str(e), input_path=input_path)
        return {
            "ok": False,
            "error": str(e),
        }


async def _ocr_pdf_page(page: Any, page_num: int) -> str | None:
    """Apply OCR to a PDF page.

    Tries PaddleOCR first (GPU-capable), falls back to Tesseract.

    Args:
        page: PyMuPDF page object.
        page_num: Page number (0-indexed) for logging.

    Returns:
        OCR extracted text or None if OCR failed.
    """
    try:
        # Render page to image (300 DPI for good OCR quality)
        mat = page.get_pixmap(matrix=page.matrix * 2)  # 2x scale for better quality
        img_data = mat.tobytes("png")

        # Try PaddleOCR first
        if _check_paddleocr_available():
            text = await _ocr_with_paddleocr(img_data)
            if text:
                return text

        # Fallback to Tesseract
        if _check_tesseract_available():
            text = await _ocr_with_tesseract(img_data)
            if text:
                return text

        logger.warning(
            "No OCR engine available",
            page=page_num + 1,
        )
        return None

    except Exception as e:
        logger.error(
            "OCR failed for page",
            page=page_num + 1,
            error=str(e),
        )
        return None


async def _ocr_with_paddleocr(img_data: bytes) -> str | None:
    """Perform OCR using PaddleOCR.

    Args:
        img_data: PNG image data.

    Returns:
        Extracted text or None.
    """
    try:
        import io

        import numpy as np
        from PIL import Image

        # Convert bytes to numpy array
        img = Image.open(io.BytesIO(img_data))
        img_array = np.array(img)

        # Get PaddleOCR instance
        ocr = _get_paddleocr_instance()
        if ocr is None:
            return None

        # Perform OCR
        result = ocr.ocr(img_array, cls=True)

        if not result or not result[0]:
            return None

        # Extract text from result
        # Result format: [[[box], (text, confidence)], ...]
        lines = []
        for line in result[0]:
            if line and len(line) >= 2:
                text, confidence = line[1]
                if confidence > 0.5:  # Filter low confidence results
                    lines.append(text)

        return "\n".join(lines) if lines else None

    except Exception as e:
        logger.debug("PaddleOCR failed", error=str(e))
        return None


async def _ocr_with_tesseract(img_data: bytes) -> str | None:
    """Perform OCR using Tesseract (fallback).

    Args:
        img_data: PNG image data.

    Returns:
        Extracted text or None.
    """
    try:
        import io

        import pytesseract
        from PIL import Image

        # Convert bytes to PIL Image
        img = Image.open(io.BytesIO(img_data))

        # Perform OCR with Japanese + English support
        text = pytesseract.image_to_string(
            img,
            lang="jpn+eng",  # Japanese + English
            config="--oem 3 --psm 3",  # LSTM engine, auto page segmentation
        )

        return text.strip() if text else None

    except Exception as e:
        logger.debug("Tesseract OCR failed", error=str(e))
        return None


async def ocr_image(
    image_path: str | None = None,
    image_data: bytes | None = None,
) -> dict[str, Any]:
    """Extract text from an image using OCR.

    Standalone function for image OCR (not embedded in PDF).

    Args:
        image_path: Path to image file.
        image_data: Raw image bytes.

    Returns:
        OCR result dictionary.
    """
    if image_path is None and image_data is None:
        return {"ok": False, "error": "Either image_path or image_data must be provided"}

    try:
        # Load image data
        if image_data is None and image_path:
            image_data = Path(image_path).read_bytes()

        # Try PaddleOCR first
        if _check_paddleocr_available():
            text = await _ocr_with_paddleocr(image_data)
            if text:
                return {
                    "ok": True,
                    "text": text,
                    "engine": "paddleocr",
                }

        # Fallback to Tesseract
        if _check_tesseract_available():
            text = await _ocr_with_tesseract(image_data)
            if text:
                return {
                    "ok": True,
                    "text": text,
                    "engine": "tesseract",
                }

        return {
            "ok": False,
            "error": "No OCR engine available",
        }

    except Exception as e:
        logger.error("Image OCR error", error=str(e))
        return {
            "ok": False,
            "error": str(e),
        }


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

    return paragraph_idx - last_heading_pos
