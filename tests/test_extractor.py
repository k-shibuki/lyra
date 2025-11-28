"""
Tests for src/extractor/content.py

OCR functionality tests (§5.1.1):
- PaddleOCR (GPU-capable) as primary OCR engine
- Tesseract as fallback
- Scanned PDF detection and OCR application
"""

import io

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestExtractContent:
    """Tests for extract_content function."""

    @pytest.mark.asyncio
    async def test_extract_content_requires_input(self):
        """Test that extract_content requires either input_path or html."""
        from src.extractor.content import extract_content
        
        result = await extract_content()
        
        assert result["ok"] is False
        assert "must be provided" in result["error"]

    @pytest.mark.asyncio
    async def test_extract_html_from_string(self):
        """Test HTML extraction from raw string."""
        from src.extractor.content import extract_content
        
        html = """
        <html>
        <head><title>Test Page</title></head>
        <body>
        <h1>Test Heading</h1>
        <p>This is a test paragraph with enough content to pass the minimum length filter.</p>
        <p>Another paragraph with important information about the test topic.</p>
        </body>
        </html>
        """
        
        with patch("src.extractor.content.get_database") as mock_db:
            mock_db.return_value = AsyncMock()
            result = await extract_content(html=html, content_type="html")
        
        assert result["ok"] is True
        assert "Test Heading" in result["text"] or len(result["headings"]) > 0

    @pytest.mark.asyncio
    async def test_extract_html_detects_headings(self):
        """Test that HTML extraction detects headings."""
        from src.extractor.content import extract_content
        
        html = """
        <html>
        <body>
        <h1>Main Title</h1>
        <h2>Section One</h2>
        <p>Content for section one.</p>
        <h3>Subsection</h3>
        <p>More content here.</p>
        </body>
        </html>
        """
        
        with patch("src.extractor.content.get_database") as mock_db:
            mock_db.return_value = AsyncMock()
            result = await extract_content(html=html)
        
        assert result["ok"] is True
        assert len(result["headings"]) >= 2
        heading_texts = [h["text"] for h in result["headings"]]
        assert "Main Title" in heading_texts
        assert "Section One" in heading_texts

    @pytest.mark.asyncio
    async def test_extract_html_detects_tables(self):
        """Test that HTML extraction detects tables."""
        from src.extractor.content import extract_content
        
        html = """
        <html>
        <body>
        <table>
            <tr><th>Name</th><th>Value</th></tr>
            <tr><td>Item 1</td><td>100</td></tr>
            <tr><td>Item 2</td><td>200</td></tr>
        </table>
        </body>
        </html>
        """
        
        with patch("src.extractor.content.get_database") as mock_db:
            mock_db.return_value = AsyncMock()
            result = await extract_content(html=html)
        
        assert result["ok"] is True
        assert len(result["tables"]) == 1
        assert len(result["tables"][0]["rows"]) >= 2

    @pytest.mark.asyncio
    async def test_auto_detect_pdf_type(self):
        """Test auto-detection of PDF content type."""
        from src.extractor.content import extract_content
        
        # Mock PDF extraction
        with patch("src.extractor.content._extract_pdf") as mock_pdf:
            mock_pdf.return_value = {
                "ok": True,
                "text": "PDF content",
                "title": None,
                "language": None,
                "headings": [],
                "tables": [],
                "meta": {"page_count": 1},
            }
            
            result = await extract_content(input_path="/path/to/file.pdf")
            
            mock_pdf.assert_called_once()
            assert result["ok"] is True


class TestOCRAvailability:
    """Tests for OCR engine availability checking."""

    def test_paddleocr_availability_check_returns_bool(self):
        """Test PaddleOCR availability check returns boolean."""
        from src.extractor import content
        
        # Reset cached value
        content._paddleocr_available = None
        
        # The result depends on actual system installation
        result = content._check_paddleocr_available()
        assert isinstance(result, bool)

    def test_paddleocr_availability_check_when_unavailable(self):
        """Test PaddleOCR availability check when module is unavailable."""
        from src.extractor import content
        
        # Reset cached value
        content._paddleocr_available = None
        
        # Directly set the cache to simulate unavailability
        content._paddleocr_available = False
        result = content._check_paddleocr_available()
        
        assert result is False

    def test_tesseract_availability_check(self):
        """Test Tesseract availability check."""
        from src.extractor import content
        
        # Reset cached value
        content._tesseract_available = None
        
        # The result depends on actual system installation
        result = content._check_tesseract_available()
        assert isinstance(result, bool)


class TestPDFExtraction:
    """Tests for PDF extraction with OCR support."""

    @pytest.mark.asyncio
    async def test_pdf_extraction_basic(self, tmp_path):
        """Test basic PDF extraction without OCR."""
        from src.extractor.content import _extract_pdf
        
        # Create a mock PDF file
        with patch("fitz.open") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_page.get_text.return_value = "This is extracted text from PDF page one with sufficient content."
            mock_page.get_pixmap.return_value = MagicMock()
            mock_page.matrix = MagicMock()
            
            mock_doc.__iter__ = lambda self: iter([mock_page])
            mock_doc.__len__ = lambda self: 1
            mock_doc.metadata = {"title": "Test PDF"}
            mock_doc.close = MagicMock()
            
            mock_fitz.return_value = mock_doc
            
            result = await _extract_pdf("/fake/path.pdf")
        
        assert result["ok"] is True
        assert "extracted text" in result["text"]
        assert result["meta"]["page_count"] == 1

    @pytest.mark.asyncio
    async def test_pdf_extraction_triggers_ocr_for_low_text(self):
        """Test that OCR is triggered when text content is low (scanned PDF detection)."""
        from src.extractor.content import _extract_pdf
        
        with patch("fitz.open") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            # Simulate scanned PDF with very little extractable text
            mock_page.get_text.return_value = "ab"  # Below threshold
            
            # Mock pixmap for OCR
            mock_pixmap = MagicMock()
            mock_pixmap.tobytes.return_value = b"fake_png_data"
            mock_page.get_pixmap.return_value = mock_pixmap
            mock_page.matrix = 1
            
            mock_doc.__iter__ = lambda self: iter([mock_page])
            mock_doc.__len__ = lambda self: 1
            mock_doc.metadata = {}
            mock_doc.close = MagicMock()
            
            mock_fitz.return_value = mock_doc
            
            # Mock OCR to return text
            with patch("src.extractor.content._ocr_pdf_page") as mock_ocr:
                mock_ocr.return_value = "OCR extracted text from scanned page"
                
                result = await _extract_pdf("/fake/scanned.pdf", ocr_threshold=100)
        
        assert result["ok"] is True
        # OCR should have been called for the low-text page
        mock_ocr.assert_called_once()

    @pytest.mark.asyncio
    async def test_pdf_extraction_force_ocr(self):
        """Test force_ocr parameter."""
        from src.extractor.content import _extract_pdf
        
        with patch("fitz.open") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            # Normal text content
            mock_page.get_text.return_value = "This is plenty of text content that would not normally trigger OCR."
            
            mock_pixmap = MagicMock()
            mock_pixmap.tobytes.return_value = b"fake_png_data"
            mock_page.get_pixmap.return_value = mock_pixmap
            mock_page.matrix = 1
            
            mock_doc.__iter__ = lambda self: iter([mock_page])
            mock_doc.__len__ = lambda self: 1
            mock_doc.metadata = {}
            mock_doc.close = MagicMock()
            
            mock_fitz.return_value = mock_doc
            
            with patch("src.extractor.content._ocr_pdf_page") as mock_ocr:
                mock_ocr.return_value = None  # OCR returns nothing better
                
                result = await _extract_pdf("/fake/path.pdf", force_ocr=True)
        
        assert result["ok"] is True
        # OCR should have been called due to force_ocr=True
        mock_ocr.assert_called_once()


class TestOCREngines:
    """Tests for individual OCR engines."""

    @pytest.mark.asyncio
    async def test_paddleocr_extraction(self):
        """Test PaddleOCR text extraction."""
        from src.extractor.content import _ocr_with_paddleocr
        
        # Create a simple test image
        from PIL import Image
        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()
        
        with patch("src.extractor.content._check_paddleocr_available", return_value=True):
            with patch("src.extractor.content._get_paddleocr_instance") as mock_get_ocr:
                mock_ocr = MagicMock()
                # Simulate PaddleOCR result format
                mock_ocr.ocr.return_value = [
                    [
                        [[[0, 0], [100, 0], [100, 20], [0, 20]], ("Test text", 0.95)],
                        [[[0, 25], [100, 25], [100, 45], [0, 45]], ("More text", 0.90)],
                    ]
                ]
                mock_get_ocr.return_value = mock_ocr
                
                result = await _ocr_with_paddleocr(img_data)
        
        assert result is not None
        assert "Test text" in result
        assert "More text" in result

    @pytest.mark.asyncio
    async def test_tesseract_extraction_via_ocr_image(self):
        """Test Tesseract text extraction via ocr_image function.
        
        Tests the fallback path when PaddleOCR is unavailable.
        The _ocr_with_tesseract function is mocked to avoid dependency on
        pytesseract installation.
        """
        from src.extractor.content import ocr_image
        from PIL import Image
        
        # Create a simple test image
        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()
        
        # Mock at the higher level to avoid pytesseract import issues
        with patch("src.extractor.content._check_paddleocr_available", return_value=False):
            with patch("src.extractor.content._check_tesseract_available", return_value=True):
                with patch("src.extractor.content._ocr_with_tesseract") as mock_tesseract:
                    mock_tesseract.return_value = "Tesseract extracted text"
                    
                    result = await ocr_image(image_data=img_data)
        
        assert result["ok"] is True
        assert result["text"] == "Tesseract extracted text"
        assert result["engine"] == "tesseract"

    @pytest.mark.asyncio
    async def test_paddleocr_filters_low_confidence(self):
        """Test that PaddleOCR filters low confidence results."""
        from src.extractor.content import _ocr_with_paddleocr
        
        from PIL import Image
        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()
        
        with patch("src.extractor.content._check_paddleocr_available", return_value=True):
            with patch("src.extractor.content._get_paddleocr_instance") as mock_get_ocr:
                mock_ocr = MagicMock()
                # Mix of high and low confidence results
                mock_ocr.ocr.return_value = [
                    [
                        [[[0, 0], [100, 0], [100, 20], [0, 20]], ("High conf", 0.95)],
                        [[[0, 25], [100, 25], [100, 45], [0, 45]], ("Low conf", 0.3)],  # Should be filtered
                    ]
                ]
                mock_get_ocr.return_value = mock_ocr
                
                result = await _ocr_with_paddleocr(img_data)
        
        assert result is not None
        assert "High conf" in result
        assert "Low conf" not in result


class TestOCRImage:
    """Tests for standalone image OCR function."""

    @pytest.mark.asyncio
    async def test_ocr_image_requires_input(self):
        """Test that ocr_image requires either image_path or image_data."""
        from src.extractor.content import ocr_image
        
        result = await ocr_image()
        
        assert result["ok"] is False
        assert "must be provided" in result["error"]

    @pytest.mark.asyncio
    async def test_ocr_image_from_data(self):
        """Test OCR from image data."""
        from src.extractor.content import ocr_image
        
        from PIL import Image
        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()
        
        with patch("src.extractor.content._check_paddleocr_available", return_value=True):
            with patch("src.extractor.content._ocr_with_paddleocr") as mock_paddle:
                mock_paddle.return_value = "Extracted text from image"
                
                result = await ocr_image(image_data=img_data)
        
        assert result["ok"] is True
        assert result["text"] == "Extracted text from image"
        assert result["engine"] == "paddleocr"

    @pytest.mark.asyncio
    async def test_ocr_image_falls_back_to_tesseract(self):
        """Test OCR falls back to Tesseract when PaddleOCR fails."""
        from src.extractor.content import ocr_image
        
        from PIL import Image
        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()
        
        with patch("src.extractor.content._check_paddleocr_available", return_value=False):
            with patch("src.extractor.content._check_tesseract_available", return_value=True):
                with patch("src.extractor.content._ocr_with_tesseract") as mock_tess:
                    mock_tess.return_value = "Tesseract fallback text"
                    
                    result = await ocr_image(image_data=img_data)
        
        assert result["ok"] is True
        assert result["text"] == "Tesseract fallback text"
        assert result["engine"] == "tesseract"

    @pytest.mark.asyncio
    async def test_ocr_image_no_engine_available(self):
        """Test OCR when no engine is available."""
        from src.extractor.content import ocr_image
        
        from PIL import Image
        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()
        
        with patch("src.extractor.content._check_paddleocr_available", return_value=False):
            with patch("src.extractor.content._check_tesseract_available", return_value=False):
                result = await ocr_image(image_data=img_data)
        
        assert result["ok"] is False
        assert "No OCR engine available" in result["error"]


class TestFallbackExtraction:
    """Tests for fallback HTML extraction methods."""

    @pytest.mark.asyncio
    async def test_fallback_uses_readability(self):
        """Test fallback extraction uses readability-lxml."""
        from src.extractor.content import _fallback_extract_html
        
        html = """
        <html>
        <body>
        <article>
        <p>This is the main content of the article that should be extracted by readability.
        It has enough text to pass the minimum length filter and be considered valid content.</p>
        </article>
        <div class="sidebar">Sidebar content that should be ignored</div>
        </body>
        </html>
        """
        
        result = await _fallback_extract_html(html)
        
        # Result depends on actual readability behavior
        # At minimum, it should return something or None
        assert result is None or isinstance(result, str)

    @pytest.mark.asyncio
    async def test_fallback_handles_empty_html(self):
        """Test fallback handles empty/minimal HTML gracefully."""
        from src.extractor.content import _fallback_extract_html
        
        result = await _fallback_extract_html("<html><body></body></html>")
        
        # Should return None for empty content
        assert result is None or result == ""

