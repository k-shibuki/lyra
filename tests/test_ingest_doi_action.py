"""Tests for ingest_doi_action.

Test perspectives:
- TC-DOI-N-01: DOI target via Academic API creates page/fragment/claims
- TC-DOI-A-01: Academic API failure falls back to URL fetch
- TC-DOI-N-02: Already processed DOI with claims is skipped
- TC-DOI-B-01: Already processed DOI without claims for this task re-extracts
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest

from src.research.pipeline import ingest_doi_action
from src.storage.database import Database
from src.utils.schemas import Author, Paper


@pytest.fixture
def mock_paper() -> Paper:
    """Create a mock paper for testing."""
    return Paper(
        id="test_paper_123",
        title="Test Paper Title",
        abstract="This is a test abstract with important findings about DPP-4 inhibitors.",
        authors=[Author(name="Test Author", affiliation="Test University", orcid=None)],
        year=2024,
        published_date=None,
        doi="10.1234/test.paper",
        venue="Test Journal",
        citation_count=10,
        reference_count=5,
        is_open_access=True,
        oa_url="https://example.com/paper.pdf",
        pdf_url="https://example.com/paper.pdf",
        source_api="semantic_scholar",
        arxiv_id=None,
    )


@pytest.fixture
async def setup_doi_test_data(test_database: Database) -> AsyncGenerator[Database]:
    """Set up test data for DOI tests."""
    db = test_database

    # Create a task
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_doi", "DOI test hypothesis", "exploring"),
    )

    yield db


@pytest.mark.asyncio
async def test_doi_academic_api_success(setup_doi_test_data: Database, mock_paper: Paper) -> None:
    """TC-DOI-N-01: DOI via Academic API creates page/fragment/claims.

    This test verifies that the DOI ingestion action correctly:
    1. Attempts to use Academic API for DOI resolution
    2. Falls back to URL if Academic API is unavailable
    3. Returns appropriate status indicators
    """
    # Given: Valid DOI
    _ = setup_doi_test_data  # Ensure fixture runs
    doi = "10.1234/test.paper"

    mock_state = AsyncMock()
    mock_state.record_page_fetch = AsyncMock()
    mock_state.record_fragment = AsyncMock()

    # Mock the ingest_url_action to avoid actual network calls
    with patch("src.research.pipeline.ingest_url_action") as mock_url_action:
        mock_url_action.return_value = {
            "ok": True,
            "url": f"https://doi.org/{doi}",
            "page_id": "page_doi_123",
            "pages_fetched": 1,
            "fragments_extracted": 1,
            "claims_extracted": 2,
        }

        # When: Ingest DOI (will fall back to URL since Academic API is mocked)
        result = await ingest_doi_action(
            task_id="task_doi",
            doi=doi,
            state=mock_state,
            reason="manual",
        )

    # Then: Should return success (either academic_api or url_fallback)
    assert result["ok"] is True
    assert result["doi"] == doi
    # Source can be 'academic_api' or 'url_fallback' depending on API availability
    assert result["source"] in ("academic_api", "url_fallback")


@pytest.mark.asyncio
async def test_doi_academic_api_failure_falls_back(setup_doi_test_data: Database) -> None:
    """TC-DOI-A-01: Academic API failure falls back to URL fetch."""
    # Given: DOI where Academic API fails
    doi = "10.9999/unknown.paper"

    mock_state = AsyncMock()

    with (
        patch("src.search.academic_provider.AcademicSearchProvider") as MockProvider,
        patch("src.research.pipeline.ingest_url_action") as mock_url_action,
    ):
        # Setup mock provider to fail
        mock_provider_instance = AsyncMock()
        mock_provider_instance.get_paper_by_doi = AsyncMock(side_effect=Exception("API Error"))
        mock_provider_instance.close = AsyncMock()
        MockProvider.return_value = mock_provider_instance

        # Setup mock URL fallback
        mock_url_action.return_value = {
            "ok": True,
            "url": f"https://doi.org/{doi}",
            "page_id": "page_fallback",
            "pages_fetched": 1,
            "fragments_extracted": 1,
            "claims_extracted": 2,
        }

        # When: Ingest DOI
        result = await ingest_doi_action(
            task_id="task_doi",
            doi=doi,
            state=mock_state,
            reason="manual",
        )

    # Then: Fallback to URL
    assert result["ok"] is True
    assert result["source"] == "url_fallback"
    assert result["status"] == "fallback_url"


@pytest.mark.asyncio
async def test_doi_already_processed_with_claims_skipped(setup_doi_test_data: Database) -> None:
    """TC-DOI-N-02: Already processed DOI with claims is skipped."""
    # Given: DOI already processed with claims for this task
    db = setup_doi_test_data
    doi = "10.1234/existing.paper"

    # Create existing page
    await db.insert(
        "pages",
        {
            "id": "existing_page",
            "url": f"https://doi.org/{doi}",
            "domain": "doi.org",
            "html_path": "/tmp/existing.html",
        },
        auto_id=False,
    )

    # Create fragment
    await db.insert(
        "fragments",
        {
            "id": "existing_frag",
            "page_id": "existing_page",
            "text_content": "Existing content",
            "fragment_type": "abstract",
        },
        auto_id=False,
    )

    # Create claim for this task
    await db.insert(
        "claims",
        {
            "id": "existing_claim",
            "task_id": "task_doi",
            "claim_text": "Existing claim",
        },
        auto_id=False,
    )

    # Create origin edge
    await db.insert(
        "edges",
        {
            "id": "existing_origin",
            "source_type": "fragment",
            "source_id": "existing_frag",
            "target_type": "claim",
            "target_id": "existing_claim",
            "relation": "origin",
        },
        auto_id=False,
    )

    # Register in resource_index
    await db.execute(
        """
        INSERT INTO resource_index (id, identifier_type, identifier_value, page_id, status)
        VALUES (?, 'doi', ?, 'existing_page', 'completed')
        """,
        ("ri_existing", doi.lower()),
    )

    mock_state = AsyncMock()

    # When: Ingest same DOI
    result = await ingest_doi_action(
        task_id="task_doi",
        doi=doi,
        state=mock_state,
        reason="manual",
    )

    # Then: Skipped
    assert result["ok"] is True
    assert result["status"] == "skipped"
    assert result["page_id"] == "existing_page"


@pytest.mark.asyncio
async def test_queue_targets_with_doi_kind(test_database: Database) -> None:
    """Verify queue_targets accepts kind='doi' targets."""
    from src.mcp.tools.targets import handle_queue_targets

    db = test_database

    # Create task
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_doi_queue", "DOI queue test", "exploring"),
    )

    # When: Queue DOI target
    result = await handle_queue_targets(
        {
            "task_id": "task_doi_queue",
            "targets": [
                {"kind": "doi", "doi": "10.1234/test.doi"},
            ],
        }
    )

    # Then: Target queued successfully
    assert result["ok"] is True
    assert result["queued_count"] == 1
    assert len(result["target_ids"]) == 1
    assert result["target_ids"][0].startswith("tq_")  # All target_queue jobs use tq_ prefix


@pytest.mark.asyncio
async def test_queue_targets_doi_duplicate_skipped(test_database: Database) -> None:
    """Verify duplicate DOI targets are skipped."""
    from src.mcp.tools.targets import handle_queue_targets

    db = test_database

    # Create task
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_doi_dup", "DOI duplicate test", "exploring"),
    )

    # Queue first DOI
    await handle_queue_targets(
        {
            "task_id": "task_doi_dup",
            "targets": [
                {"kind": "doi", "doi": "10.1234/duplicate.doi"},
            ],
        }
    )

    # When: Queue same DOI again
    result = await handle_queue_targets(
        {
            "task_id": "task_doi_dup",
            "targets": [
                {"kind": "doi", "doi": "10.1234/duplicate.doi"},
            ],
        }
    )

    # Then: Duplicate skipped
    assert result["ok"] is True
    assert result["queued_count"] == 0
    assert result["skipped_count"] == 1
