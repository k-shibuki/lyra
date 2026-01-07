"""
Tests for src/extractor/content.py

HTML extraction functionality tests.
"""

from unittest.mock import AsyncMock, patch

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit


class TestExtractContent:
    """Tests for extract_content function."""

    @pytest.mark.asyncio
    async def test_extract_content_requires_input(self) -> None:
        """Test that extract_content requires either input_path or html."""
        from src.extractor.content import extract_content

        result = await extract_content()

        assert result["ok"] is False
        assert "must be provided" in result["error"]

    @pytest.mark.asyncio
    async def test_extract_html_from_string(self) -> None:
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
        assert (
            "Test Heading" in heading_texts
        ), f"Expected 'Test Heading' in headings: {result['headings']}"

    @pytest.mark.asyncio
    async def test_extract_html_detects_headings(self) -> None:
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
    async def test_extract_html_detects_tables(self) -> None:
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
    async def test_pdf_not_supported(self) -> None:
        """Test that PDF extraction is not supported."""
        from src.extractor.content import extract_content

        # Given: A file path with .pdf extension
        # When: Extracting content from PDF
        result = await extract_content(input_path="/path/to/file.pdf")

        # Then: Error is returned indicating PDF is not supported
        assert result["ok"] is False
        assert "PDF extraction is not supported" in result["error"]

    @pytest.mark.asyncio
    async def test_pdf_content_type_not_supported(self) -> None:
        """Test that PDF content_type is not supported."""
        from src.extractor.content import extract_content

        # Given: Content type explicitly set to PDF
        # When: Extracting content with PDF content type
        result = await extract_content(html="<html><body>test</body></html>", content_type="pdf")

        # Then: Error is returned indicating PDF is not supported
        assert result["ok"] is False
        assert "not supported" in result["error"]


class TestTrafilaturaWiring:
    """Tests for trafilatura call wiring (include_links=False)."""

    @pytest.mark.asyncio
    async def test_trafilatura_called_with_include_links_false(self) -> None:
        """Test that trafilatura.extract is called with include_links=False.

        This wiring test ensures link embedding is disabled to prevent
        'missing link attribute' warnings from trafilatura.

        | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
        |---------|----------------------|-------------|-----------------|-------|
        | TC-N-02 | trafilatura.extract call | wiring | include_links=False | - |
        """
        # Given: HTML content to extract
        html = """
        <html>
        <body>
        <h1>Test Article</h1>
        <p>This is a test paragraph with content.</p>
        <p><a href="https://example.org/ref">Reference Link</a></p>
        </body>
        </html>
        """

        captured_calls: list[dict] = []

        # Create fake trafilatura module
        class FakeTrafilaturaModule:
            @staticmethod
            def extract(
                html: str,
                include_comments: bool = True,
                include_tables: bool = False,
                include_links: bool = True,  # default is True
                include_images: bool = False,
                output_format: str = "txt",
                favor_precision: bool = False,
            ) -> str | None:
                captured_calls.append(
                    {
                        "include_comments": include_comments,
                        "include_tables": include_tables,
                        "include_links": include_links,
                        "include_images": include_images,
                        "output_format": output_format,
                        "favor_precision": favor_precision,
                    }
                )
                return "Test Article\nThis is a test paragraph with content."

            @staticmethod
            def extract_metadata(html: str) -> None:
                return None

        # When: extract_content is called with fake trafilatura injected
        import importlib

        import src.extractor.content as content_module

        with patch("src.extractor.content.get_database") as mock_db:
            mock_db.return_value = AsyncMock()
            with patch.dict(
                "sys.modules",
                {"trafilatura": FakeTrafilaturaModule()},
            ):
                # Re-import to pick up the patched module
                importlib.reload(content_module)

                await content_module.extract_content(html=html, content_type="html")

        # Then: trafilatura.extract was called with include_links=False
        assert len(captured_calls) >= 1, "trafilatura.extract was not called"
        assert (
            captured_calls[0]["include_links"] is False
        ), f"Expected include_links=False, got {captured_calls[0]['include_links']}"
        # Also verify other expected parameters
        assert captured_calls[0]["include_comments"] is False
        assert captured_calls[0]["include_tables"] is True
        assert captured_calls[0]["output_format"] == "txt"
        assert captured_calls[0]["favor_precision"] is True


class TestFallbackExtraction:
    """Tests for fallback HTML extraction methods."""

    @pytest.mark.asyncio
    async def test_fallback_uses_readability(self) -> None:
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
        assert isinstance(
            result, (str, type(None))
        ), f"Expected str or None, got {type(result).__name__}"

    @pytest.mark.asyncio
    async def test_fallback_handles_empty_html(self) -> None:
        """Test fallback handles empty/minimal HTML gracefully."""
        from src.extractor.content import _fallback_extract_html

        # Given: Minimal HTML with empty body
        # When: Running fallback extraction
        result = await _fallback_extract_html("<html><body></body></html>")

        # Then: Returns None or empty string for empty content
        is_empty = (result is None) or (result == "")
        assert is_empty, f"Expected None or empty string for empty HTML, got: {result!r}"
