"""
Content extraction for Lancet.
Extracts text, metadata, and structure from HTML and PDF documents.
"""

import hashlib
import re
from pathlib import Path
from typing import Any

from src.utils.logging import get_logger
from src.storage.database import get_database

logger = get_logger(__name__)


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
            
            fragment = {
                "text": para,
                "type": "paragraph",
                "position": idx,
                "heading_context": _find_heading_context(idx, headings, paragraphs),
                "text_hash": text_hash,
            }
            fragments.append(fragment)
            
            # Store in database if we have a page_id
            if page_id:
                await db.insert("fragments", {
                    "page_id": page_id,
                    "fragment_type": "paragraph",
                    "position": idx,
                    "text_content": para,
                    "heading_context": fragment["heading_context"],
                    "text_hash": text_hash,
                })
        
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
    except Exception:
        pass
    
    # Try jusText
    try:
        import justext
        paragraphs = justext.justext(html.encode("utf-8"), justext.get_stoplist("Japanese"))
        text_parts = [p.text for p in paragraphs if not p.is_boilerplate]
        if text_parts:
            return "\n\n".join(text_parts)
    except Exception:
        pass
    
    return None


async def _extract_pdf(input_path: str) -> dict[str, Any]:
    """Extract content from PDF.
    
    Args:
        input_path: Path to PDF file.
        
    Returns:
        Extraction result.
    """
    try:
        import fitz  # PyMuPDF
        
        doc = fitz.open(input_path)
        
        text_parts = []
        headings = []
        tables = []
        
        for page_num, page in enumerate(doc):
            # Extract text
            text = page.get_text("text")
            text_parts.append(text)
            
            # Try to extract structure
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            # Detect headings by font size
                            if span["size"] > 14:
                                headings.append({
                                    "level": 1 if span["size"] > 18 else 2,
                                    "text": span["text"].strip(),
                                    "page": page_num + 1,
                                })
        
        doc.close()
        
        full_text = "\n\n".join(text_parts)
        
        logger.info(
            "PDF extraction complete",
            input_path=input_path,
            page_count=len(text_parts),
            text_length=len(full_text),
        )
        
        return {
            "ok": True,
            "text": full_text,
            "title": None,  # TODO: Extract from metadata
            "language": None,
            "headings": headings,
            "tables": tables,
            "meta": {
                "page_count": len(text_parts),
            },
        }
        
    except Exception as e:
        logger.error("PDF extraction error", error=str(e), input_path=input_path)
        return {
            "ok": False,
            "error": str(e),
        }


def _extract_headings(html: str) -> list[dict[str, Any]]:
    """Extract headings from HTML.
    
    Args:
        html: HTML content.
        
    Returns:
        List of heading dictionaries.
    """
    headings = []
    
    # Simple regex extraction for headings
    heading_pattern = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
    
    for match in heading_pattern.finditer(html):
        level = int(match.group(1))
        text = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        
        if text:
            headings.append({
                "level": level,
                "text": text,
            })
    
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
            tables.append({
                "index": idx,
                "rows": rows,
            })
    
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
        Heading text or None.
    """
    # This is a simplified implementation
    # In practice, we'd need to track heading positions in the original text
    if headings and len(headings) > 0:
        # Return the first heading as context (simplified)
        idx = min(paragraph_idx // 3, len(headings) - 1)
        return headings[idx]["text"]
    return None

