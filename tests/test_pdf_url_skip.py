"""Tests for PDF URL skip logic in ingest_url_action.

Design: PDF URLs cannot be processed via browser fetch (page.content() returns
only <embed> tag). Per abstract-only design, PDFs should be handled via Academic API.

Test perspectives:
| Case ID | Input / Precondition | Perspective | Expected Result |
|---------|----------------------|-------------|-----------------|
| TC-PDF-A-01 | URL ending with `.pdf` | Equivalence – abnormal | skip, reason=pdf_not_supported |
| TC-PDF-A-02 | URL containing `/pdf/` | Equivalence – abnormal | skip, reason=pdf_not_supported |
| TC-PDF-B-01 | URL ending with `.PDF` | Boundary – case | skip (case-insensitive) |
| TC-PDF-B-02 | URL NOT ending with `.pdf` and NOT containing `/pdf/` | Boundary – path | not skipped (reason != pdf_not_supported) |
"""

from unittest.mock import MagicMock

import pytest

from src.research.pipeline import ingest_url_action
from src.storage.database import Database


@pytest.fixture
async def setup_pdf_test_data(test_database: Database) -> Database:
    """Set up minimal test data for PDF skip tests."""
    db = test_database

    # Create a task
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_pdf_test", "Test PDF skip", "exploring"),
    )

    return db


class TestPdfUrlSkip:
    """Test suite for PDF URL skip logic.

    These tests verify that PDF URLs are skipped early (before fetch_url is called).
    Since the skip happens before any external calls, no mocking is needed for skip tests.
    """

    @pytest.mark.asyncio
    async def test_pdf_extension_url_skipped(self, setup_pdf_test_data: Database) -> None:
        """
        TC-PDF-A-01: URL ending with .pdf should be skipped.

        // Given: A URL ending with .pdf
        // When: ingest_url_action is called
        // Then: Returns immediately with reason=pdf_not_supported, no fetch executed
        """
        # Given
        url = "https://example.com/paper/document.pdf"
        mock_state = MagicMock()
        mock_state.task_id = "task_pdf_test"
        mock_state.db = setup_pdf_test_data

        # When: PDF skip happens before fetch_url, so no mocking needed
        result = await ingest_url_action(
            task_id="task_pdf_test",
            url=url,
            state=mock_state,
        )

        # Then: Skipped with proper response
        assert result["ok"] is False
        assert result["reason"] == "pdf_not_supported"
        assert result["status"] == "skipped"
        assert result["pages_fetched"] == 0
        assert "PDF URLs cannot be processed" in result["message"]

    @pytest.mark.asyncio
    async def test_pdf_path_url_skipped(self, setup_pdf_test_data: Database) -> None:
        """
        TC-PDF-A-02: URL containing /pdf/ path should be skipped.

        // Given: A URL containing /pdf/ in the path
        // When: ingest_url_action is called
        // Then: Returns immediately with reason=pdf_not_supported
        """
        # Given
        url = "https://journals.example.com/content/pdf/article123"
        mock_state = MagicMock()
        mock_state.task_id = "task_pdf_test"
        mock_state.db = setup_pdf_test_data

        # When
        result = await ingest_url_action(
            task_id="task_pdf_test",
            url=url,
            state=mock_state,
        )

        # Then: Skipped
        assert result["ok"] is False
        assert result["reason"] == "pdf_not_supported"
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_pdf_extension_case_insensitive(self, setup_pdf_test_data: Database) -> None:
        """
        TC-PDF-B-01: URL ending with .PDF (uppercase) should also be skipped.

        // Given: A URL ending with .PDF (uppercase)
        // When: ingest_url_action is called
        // Then: Returns immediately with reason=pdf_not_supported (case-insensitive)
        """
        # Given
        url = "https://example.com/paper/DOCUMENT.PDF"
        mock_state = MagicMock()
        mock_state.task_id = "task_pdf_test"
        mock_state.db = setup_pdf_test_data

        # When
        result = await ingest_url_action(
            task_id="task_pdf_test",
            url=url,
            state=mock_state,
        )

        # Then: Skipped (case-insensitive)
        assert result["ok"] is False
        assert result["reason"] == "pdf_not_supported"

    @pytest.mark.asyncio
    async def test_pdf_in_path_but_not_pdf_pattern_not_skipped(
        self, setup_pdf_test_data: Database
    ) -> None:
        """
        TC-PDF-B-02: URL NOT ending with .pdf and NOT containing /pdf/ should NOT be skipped.

        // Given: A URL like /something.pdf.html or /api/getpdf (no /pdf/ segment)
        // When: ingest_url_action is called
        // Then: reason != pdf_not_supported (proceeds to fetch, which may fail for other reasons)

        Note: This test only verifies the PDF skip logic doesn't trigger falsely.
        The URL will likely fail at fetch stage since it's not a real URL.
        """
        # Given: URL contains "pdf" but NOT as /pdf/ path segment or .pdf extension
        url = "https://example.com/api/getpdf?id=123"  # No /pdf/ segment, no .pdf extension
        mock_state = MagicMock()
        mock_state.task_id = "task_pdf_test"
        mock_state.db = setup_pdf_test_data

        # When: This will proceed past PDF check and attempt fetch (which will fail)
        result = await ingest_url_action(
            task_id="task_pdf_test",
            url=url,
            state=mock_state,
        )

        # Then: NOT skipped for PDF reason (may fail for other reasons like fetch error)
        assert result.get("reason") != "pdf_not_supported"
        # The URL may fail for other reasons (e.g., fetch error), but not pdf_not_supported

    @pytest.mark.asyncio
    async def test_mixed_case_pdf_path_skipped(self, setup_pdf_test_data: Database) -> None:
        """
        TC-PDF-B-03: URL containing /PDF/ (uppercase) in path should also be skipped.

        // Given: A URL containing /PDF/ in the path (uppercase)
        // When: ingest_url_action is called
        // Then: Returns with reason=pdf_not_supported (case-insensitive)
        """
        # Given
        url = "https://journals.example.com/content/PDF/article123"
        mock_state = MagicMock()
        mock_state.task_id = "task_pdf_test"
        mock_state.db = setup_pdf_test_data

        # When
        result = await ingest_url_action(
            task_id="task_pdf_test",
            url=url,
            state=mock_state,
        )

        # Then: Skipped (case-insensitive path check)
        assert result["ok"] is False
        assert result["reason"] == "pdf_not_supported"
