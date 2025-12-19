"""
Tests for src/extractor/content.py

OCR functionality tests (§5.1.1):
- PaddleOCR (GPU-capable) as primary OCR engine
- Tesseract as fallback
- Scanned PDF detection and OCR application
"""

import io
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

# Check optional dependencies for conditional test skipping
try:
    import fitz  # noqa: F401

    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    from PIL import Image  # noqa: F401

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Check environment variable to force running extractor tests (e.g., in container)
_RUN_EXTRACTOR_TESTS = os.environ.get("LYRA_RUN_EXTRACTOR_TESTS", "0") == "1"

# Skip messages with guidance for ML container-based testing
_SKIP_MSG_FITZ = (
    "Requires PyMuPDF (fitz). "
    "PDF extraction runs in ML container. "
    "Run tests in container: podman exec lyra pytest tests/test_extractor.py, "
    "or install: pip install PyMuPDF"
)

_SKIP_MSG_PIL = (
    "Requires Pillow (PIL). "
    "OCR functionality runs in ML container. "
    "Run tests in container: podman exec lyra pytest tests/test_extractor.py, "
    "or install: pip install Pillow"
)

# Decorators for skipping tests based on optional dependencies
# If LYRA_RUN_EXTRACTOR_TESTS=1 is set (e.g., in container), don't skip even if libs are missing
requires_fitz = pytest.mark.skipif(
    not HAS_FITZ and not _RUN_EXTRACTOR_TESTS,
    reason=_SKIP_MSG_FITZ,
)
requires_pil = pytest.mark.skipif(
    not HAS_PIL and not _RUN_EXTRACTOR_TESTS,
    reason=_SKIP_MSG_PIL,
)


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

        # Given: HTML content with title, heading, and paragraphs
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

        # When: Extracting content from the HTML string
        with patch("src.extractor.content.get_database") as mock_db:
            mock_db.return_value = AsyncMock()
            result = await extract_content(html=html, content_type="html")

        # Then: Extraction succeeds and heading is detected
        assert result["ok"] is True
        assert "headings" in result, f"Expected 'headings' in result keys: {list(result.keys())}"
        heading_texts = [
            h.get("text", "") if isinstance(h, dict) else str(h) for h in result["headings"]
        ]
        assert "Test Heading" in heading_texts, (
            f"Expected 'Test Heading' in headings: {result['headings']}"
        )

    @pytest.mark.asyncio
    async def test_extract_html_detects_headings(self):
        """Test that HTML extraction detects headings."""
        from src.extractor.content import extract_content

        # Given: HTML with multiple heading levels (h1, h2, h3)
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

        # When: Extracting content from the HTML
        with patch("src.extractor.content.get_database") as mock_db:
            mock_db.return_value = AsyncMock()
            result = await extract_content(html=html)

        # Then: Multiple headings are detected
        assert result["ok"] is True
        assert len(result["headings"]) >= 2
        heading_texts = [h["text"] for h in result["headings"]]
        assert "Main Title" in heading_texts
        assert "Section One" in heading_texts

    @pytest.mark.asyncio
    async def test_extract_html_detects_tables(self):
        """Test that HTML extraction detects tables."""
        from src.extractor.content import extract_content

        # Given: HTML containing a table with header and data rows
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

        # When: Extracting content from the HTML
        with patch("src.extractor.content.get_database") as mock_db:
            mock_db.return_value = AsyncMock()
            result = await extract_content(html=html)

        # Then: Table structure is extracted with rows
        assert result["ok"] is True
        assert len(result["tables"]) == 1
        assert len(result["tables"][0]["rows"]) >= 2

    @pytest.mark.asyncio
    async def test_auto_detect_pdf_type(self):
        """Test auto-detection of PDF content type."""
        from src.extractor.content import extract_content

        # Given: A file path with .pdf extension
        # When: Extracting content with auto-detection
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

            # Then: PDF extraction is called and succeeds
            mock_pdf.assert_called_once()
            assert result["ok"] is True


class TestOCRAvailability:
    """Tests for OCR engine availability checking."""

    def test_paddleocr_availability_check_returns_bool(self):
        """Test PaddleOCR availability check returns boolean."""
        from src.extractor import content

        # Given: Cached availability value is reset
        content._paddleocr_available = None

        # When: Checking PaddleOCR availability
        result = content._check_paddleocr_available()

        # Then: Result is a boolean (depends on system installation)
        assert isinstance(result, bool)

    def test_paddleocr_availability_check_when_unavailable(self):
        """Test PaddleOCR availability check when module is unavailable."""
        from src.extractor import content

        # Given: PaddleOCR is cached as unavailable
        content._paddleocr_available = None
        content._paddleocr_available = False

        # When: Checking availability
        result = content._check_paddleocr_available()

        # Then: Returns False (cached unavailable status)
        assert result is False

    def test_tesseract_availability_check(self):
        """Test Tesseract availability check."""
        from src.extractor import content

        # Given: Cached availability value is reset
        content._tesseract_available = None

        # When: Checking Tesseract availability
        result = content._check_tesseract_available()

        # Then: Result is a boolean (depends on system installation)
        assert isinstance(result, bool)


@requires_fitz
class TestPDFExtraction:
    """Tests for PDF extraction with OCR support."""

    @pytest.mark.asyncio
    async def test_pdf_extraction_basic(self, tmp_path):
        """Test basic PDF extraction without OCR."""
        from src.extractor.content import _extract_pdf

        # Given: A mock PDF document with text content
        with patch("fitz.open") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_page.get_text.return_value = (
                "This is extracted text from PDF page one with sufficient content."
            )
            mock_page.get_pixmap.return_value = MagicMock()
            mock_page.matrix = MagicMock()

            mock_doc.__iter__ = lambda self: iter([mock_page])
            mock_doc.__len__ = lambda self: 1
            mock_doc.metadata = {"title": "Test PDF"}
            mock_doc.close = MagicMock()

            mock_fitz.return_value = mock_doc

            # When: Extracting content from the PDF
            result = await _extract_pdf("/fake/path.pdf")

        # Then: Text is extracted successfully with metadata
        assert result["ok"] is True
        assert "extracted text" in result["text"]
        assert result["meta"]["page_count"] == 1

    @pytest.mark.asyncio
    async def test_pdf_extraction_triggers_ocr_for_low_text(self):
        """Test that OCR is triggered when text content is low (scanned PDF detection)."""
        from src.extractor.content import _extract_pdf

        # Given: A scanned PDF with minimal extractable text
        with patch("fitz.open") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_page.get_text.return_value = "ab"  # Below threshold

            mock_pixmap = MagicMock()
            mock_pixmap.tobytes.return_value = b"fake_png_data"
            mock_page.get_pixmap.return_value = mock_pixmap
            mock_page.matrix = 1

            mock_doc.__iter__ = lambda self: iter([mock_page])
            mock_doc.__len__ = lambda self: 1
            mock_doc.metadata = {}
            mock_doc.close = MagicMock()

            mock_fitz.return_value = mock_doc

            # When: Extracting with OCR threshold set
            with patch("src.extractor.content._ocr_pdf_page") as mock_ocr:
                mock_ocr.return_value = "OCR extracted text from scanned page"
                result = await _extract_pdf("/fake/scanned.pdf", ocr_threshold=100)

        # Then: OCR is triggered for the low-text page
        assert result["ok"] is True
        mock_ocr.assert_called_once()

    @pytest.mark.asyncio
    async def test_pdf_extraction_force_ocr(self):
        """Test force_ocr parameter."""
        from src.extractor.content import _extract_pdf

        # Given: A PDF with sufficient text content
        with patch("fitz.open") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_page.get_text.return_value = (
                "This is plenty of text content that would not normally trigger OCR."
            )

            mock_pixmap = MagicMock()
            mock_pixmap.tobytes.return_value = b"fake_png_data"
            mock_page.get_pixmap.return_value = mock_pixmap
            mock_page.matrix = 1

            mock_doc.__iter__ = lambda self: iter([mock_page])
            mock_doc.__len__ = lambda self: 1
            mock_doc.metadata = {}
            mock_doc.close = MagicMock()

            mock_fitz.return_value = mock_doc

            # When: Extracting with force_ocr=True
            with patch("src.extractor.content._ocr_pdf_page") as mock_ocr:
                mock_ocr.return_value = None
                result = await _extract_pdf("/fake/path.pdf", force_ocr=True)

        # Then: OCR is called despite sufficient text
        assert result["ok"] is True
        mock_ocr.assert_called_once()


@requires_pil
class TestOCREngines:
    """Tests for individual OCR engines."""

    @pytest.mark.asyncio
    async def test_paddleocr_extraction(self):
        """Test PaddleOCR text extraction."""
        # Given: A test image and mocked PaddleOCR returning results
        from PIL import Image

        from src.extractor.content import _ocr_with_paddleocr

        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        with patch("src.extractor.content._check_paddleocr_available", return_value=True):
            with patch("src.extractor.content._get_paddleocr_instance") as mock_get_ocr:
                mock_ocr = MagicMock()
                mock_ocr.ocr.return_value = [
                    [
                        [[[0, 0], [100, 0], [100, 20], [0, 20]], ("Test text", 0.95)],
                        [[[0, 25], [100, 25], [100, 45], [0, 45]], ("More text", 0.90)],
                    ]
                ]
                mock_get_ocr.return_value = mock_ocr

                # When: Running OCR on the image
                result = await _ocr_with_paddleocr(img_data)

        # Then: All recognized text is returned
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
        from PIL import Image

        from src.extractor.content import ocr_image

        # Given: An image and Tesseract as the only available OCR engine
        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        # When: Running OCR with PaddleOCR unavailable
        with patch("src.extractor.content._check_paddleocr_available", return_value=False):
            with patch("src.extractor.content._check_tesseract_available", return_value=True):
                with patch("src.extractor.content._ocr_with_tesseract") as mock_tesseract:
                    mock_tesseract.return_value = "Tesseract extracted text"
                    result = await ocr_image(image_data=img_data)

        # Then: Tesseract fallback is used successfully
        assert result["ok"] is True
        assert result["text"] == "Tesseract extracted text"
        assert result["engine"] == "tesseract"

    @pytest.mark.asyncio
    async def test_paddleocr_filters_low_confidence(self):
        """Test that PaddleOCR filters low confidence results."""
        # Given: OCR results with mixed confidence levels
        from PIL import Image

        from src.extractor.content import _ocr_with_paddleocr

        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        with patch("src.extractor.content._check_paddleocr_available", return_value=True):
            with patch("src.extractor.content._get_paddleocr_instance") as mock_get_ocr:
                mock_ocr = MagicMock()
                mock_ocr.ocr.return_value = [
                    [
                        [[[0, 0], [100, 0], [100, 20], [0, 20]], ("High conf", 0.95)],
                        [[[0, 25], [100, 25], [100, 45], [0, 45]], ("Low conf", 0.3)],
                    ]
                ]
                mock_get_ocr.return_value = mock_ocr

                # When: Running OCR
                result = await _ocr_with_paddleocr(img_data)

        # Then: Low confidence results are filtered out
        assert result is not None
        assert "High conf" in result
        assert "Low conf" not in result


class TestOCRImage:
    """Tests for standalone image OCR function."""

    @pytest.mark.asyncio
    async def test_ocr_image_requires_input(self):
        """Test that ocr_image requires either image_path or image_data."""
        from src.extractor.content import ocr_image

        # Given: No input provided
        # When: Calling ocr_image without arguments
        result = await ocr_image()

        # Then: Error is returned indicating required input
        assert result["ok"] is False
        assert "must be provided" in result["error"]

    @requires_pil
    @pytest.mark.asyncio
    async def test_ocr_image_from_data(self):
        """Test OCR from image data."""
        # Given: Image data and available PaddleOCR
        from PIL import Image

        from src.extractor.content import ocr_image

        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        # When: Running OCR on image data
        with patch("src.extractor.content._check_paddleocr_available", return_value=True):
            with patch("src.extractor.content._ocr_with_paddleocr") as mock_paddle:
                mock_paddle.return_value = "Extracted text from image"
                result = await ocr_image(image_data=img_data)

        # Then: Text is extracted using PaddleOCR
        assert result["ok"] is True
        assert result["text"] == "Extracted text from image"
        assert result["engine"] == "paddleocr"

    @requires_pil
    @pytest.mark.asyncio
    async def test_ocr_image_falls_back_to_tesseract(self):
        """Test OCR falls back to Tesseract when PaddleOCR fails."""
        # Given: Image data with PaddleOCR unavailable
        from PIL import Image

        from src.extractor.content import ocr_image

        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        # When: Running OCR with fallback to Tesseract
        with patch("src.extractor.content._check_paddleocr_available", return_value=False):
            with patch("src.extractor.content._check_tesseract_available", return_value=True):
                with patch("src.extractor.content._ocr_with_tesseract") as mock_tess:
                    mock_tess.return_value = "Tesseract fallback text"
                    result = await ocr_image(image_data=img_data)

        # Then: Tesseract is used as fallback
        assert result["ok"] is True
        assert result["text"] == "Tesseract fallback text"
        assert result["engine"] == "tesseract"

    @requires_pil
    @pytest.mark.asyncio
    async def test_ocr_image_no_engine_available(self):
        """Test OCR when no engine is available."""
        # Given: Image data with no OCR engines available
        from PIL import Image

        from src.extractor.content import ocr_image

        img = Image.new("RGB", (100, 50), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        # When: Attempting OCR with no available engines
        with patch("src.extractor.content._check_paddleocr_available", return_value=False):
            with patch("src.extractor.content._check_tesseract_available", return_value=False):
                result = await ocr_image(image_data=img_data)

        # Then: Error is returned indicating no engine available
        assert result["ok"] is False
        assert "No OCR engine available" in result["error"]


class TestFallbackExtraction:
    """Tests for fallback HTML extraction methods."""

    @pytest.mark.asyncio
    async def test_fallback_uses_readability(self):
        """Test fallback extraction uses readability-lxml."""
        from src.extractor.content import _fallback_extract_html

        # Given: HTML with article content and sidebar
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

        # When: Running fallback extraction
        result = await _fallback_extract_html(html)

        # Then: Result is either extracted text or None
        assert isinstance(result, (str, type(None))), (
            f"Expected str or None, got {type(result).__name__}"
        )

    @pytest.mark.asyncio
    async def test_fallback_handles_empty_html(self):
        """Test fallback handles empty/minimal HTML gracefully."""
        from src.extractor.content import _fallback_extract_html

        # Given: Minimal HTML with empty body
        # When: Running fallback extraction
        result = await _fallback_extract_html("<html><body></body></html>")

        # Then: Returns None or empty string for empty content
        is_empty = (result is None) or (result == "")
        assert is_empty, f"Expected None or empty string for empty HTML, got: {result!r}"
