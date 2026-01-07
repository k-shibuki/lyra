"""Tests for URL reprocessing (task未Claim condition).

Test perspectives:
- TC-URL-N-01: URL with html_path but no origin for this task → reprocess without fetch
- TC-URL-B-01: URL with origin for this task → skip (no double extraction)
- TC-URL-N-02: Reprocess creates claims for the new task
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest

from src.research.pipeline import ingest_url_action
from src.storage.database import Database


@pytest.fixture
async def setup_reprocess_data(test_database: Database) -> AsyncGenerator[Database]:
    """Set up test data for URL reprocess tests."""
    db = test_database

    # Create tasks
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_old", "Old task", "completed"),
    )
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_new", "New task", "exploring"),
    )

    # Create a page that was processed for task_old but not task_new
    await db.insert(
        "pages",
        {
            "id": "page_reprocess",
            "url": "https://example.com/reprocess",
            "domain": "example.com",
            "html_path": "/tmp/reprocess.html",
        },
        auto_id=False,
    )

    # Create fragment for the page
    await db.insert(
        "fragments",
        {
            "id": "frag_reprocess",
            "page_id": "page_reprocess",
            "text_content": "Test content about DPP-4 inhibitors efficacy.",
            "fragment_type": "paragraph",
        },
        auto_id=False,
    )

    # Create claim for task_old (NOT task_new)
    await db.insert(
        "claims",
        {
            "id": "claim_old",
            "task_id": "task_old",
            "claim_text": "Old task claim",
        },
        auto_id=False,
    )

    # Create origin edge for task_old
    await db.insert(
        "edges",
        {
            "id": "edge_origin_old",
            "source_type": "fragment",
            "source_id": "frag_reprocess",
            "target_type": "claim",
            "target_id": "claim_old",
            "relation": "origin",
        },
        auto_id=False,
    )

    yield db


@pytest.mark.asyncio
async def test_url_reprocess_when_no_claims_for_task(setup_reprocess_data: Database) -> None:
    """TC-URL-N-01: URL with html_path but no origin for this task triggers reprocess."""
    # Given: Page processed for task_old but not task_new
    _ = setup_reprocess_data  # Ensure fixture runs

    mock_state = AsyncMock()

    with (
        patch("src.extractor.content.extract_content") as mock_extract,
        patch("src.filter.llm.llm_extract") as mock_llm,
    ):
        mock_extract.return_value = {
            "ok": True,
            "text": "Test content about DPP-4 inhibitors efficacy.",
            "title": "Test Title",
        }
        mock_llm.return_value = {
            "claims": [
                {"claim": "DPP-4 inhibitors are effective", "confidence": 0.8},
            ],
        }

        # When: Ingest URL for task_new (skip_if_exists=True default)
        result = await ingest_url_action(
            task_id="task_new",
            url="https://example.com/reprocess",
            state=mock_state,
            reason="manual",
        )

    # Then: Page reprocessed (not fetched again)
    assert result["ok"] is True
    assert result["status"] == "reprocessed"
    assert result["pages_fetched"] == 0  # No new fetch
    assert result["page_id"] == "page_reprocess"


@pytest.mark.asyncio
async def test_url_skip_when_has_origin_for_task(test_database: Database) -> None:
    """TC-URL-B-01: URL with origin for this task is skipped."""
    db = test_database

    # Create task
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_skip", "Skip test", "exploring"),
    )

    # Create page
    await db.insert(
        "pages",
        {
            "id": "page_skip",
            "url": "https://example.com/skip",
            "domain": "example.com",
            "html_path": "/tmp/skip.html",
        },
        auto_id=False,
    )

    # Create fragment
    await db.insert(
        "fragments",
        {
            "id": "frag_skip",
            "page_id": "page_skip",
            "text_content": "Skip content",
            "fragment_type": "paragraph",
        },
        auto_id=False,
    )

    # Create claim for THIS task
    await db.insert(
        "claims",
        {
            "id": "claim_skip",
            "task_id": "task_skip",
            "claim_text": "Skip claim",
        },
        auto_id=False,
    )

    # Create origin edge
    await db.insert(
        "edges",
        {
            "id": "edge_origin_skip",
            "source_type": "fragment",
            "source_id": "frag_skip",
            "target_type": "claim",
            "target_id": "claim_skip",
            "relation": "origin",
        },
        auto_id=False,
    )

    mock_state = AsyncMock()

    # When: Ingest URL that already has claims for this task
    result = await ingest_url_action(
        task_id="task_skip",
        url="https://example.com/skip",
        state=mock_state,
        reason="manual",
    )

    # Then: Skipped
    assert result["ok"] is True
    assert result["status"] == "skipped"
    assert "already exists with claims" in result["message"]


@pytest.mark.asyncio
async def test_reprocess_creates_task_pages_entry(setup_reprocess_data: Database) -> None:
    """Verify reprocess creates task_pages entry."""
    db = setup_reprocess_data

    mock_state = AsyncMock()

    with (
        patch("src.extractor.content.extract_content") as mock_extract,
        patch("src.filter.llm.llm_extract") as mock_llm,
    ):
        mock_extract.return_value = {
            "ok": True,
            "text": "Test content",
            "title": "Test",
        }
        mock_llm.return_value = {"claims": []}

        # When: Reprocess
        await ingest_url_action(
            task_id="task_new",
            url="https://example.com/reprocess",
            state=mock_state,
            reason="citation_chase",
        )

    # Then: task_pages entry created
    tp = await db.fetch_one(
        "SELECT * FROM task_pages WHERE task_id = ? AND page_id = ?",
        ("task_new", "page_reprocess"),
    )
    assert tp is not None
    assert tp["reason"] == "citation_chase"


@pytest.mark.asyncio
async def test_reprocess_claims_associated_with_new_task(setup_reprocess_data: Database) -> None:
    """TC-URL-N-02: Reprocessed claims are associated with the new task."""
    db = setup_reprocess_data

    mock_state = AsyncMock()

    with (
        patch("src.extractor.content.extract_content") as mock_extract,
        patch("src.filter.llm.llm_extract") as mock_llm,
        patch("src.filter.evidence_graph.add_claim_evidence") as mock_add_evidence,
    ):
        mock_extract.return_value = {
            "ok": True,
            "text": "Test content about findings",
            "title": "Test Title",
        }
        mock_llm.return_value = {
            "claims": [
                {"claim": "Finding 1", "confidence": 0.9},
                {"claim": "Finding 2", "confidence": 0.8},
            ],
        }
        mock_add_evidence.return_value = None

        # When: Reprocess for new task
        result = await ingest_url_action(
            task_id="task_new",
            url="https://example.com/reprocess",
            state=mock_state,
            reason="manual",
        )

    # Then: Claims created for new task
    assert result["ok"] is True
    assert result["claims_extracted"] == 2

    # Verify claims are for task_new
    claims = await db.fetch_all(
        "SELECT * FROM claims WHERE task_id = ?",
        ("task_new",),
    )
    assert len(claims) >= 2


@pytest.mark.asyncio
async def test_force_fetch_ignores_skip_if_exists(test_database: Database) -> None:
    """Verify skip_if_exists=False forces fetch even with existing content."""
    db = test_database

    # Create task
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_force", "Force test", "exploring"),
    )

    # Create existing page with content
    await db.insert(
        "pages",
        {
            "id": "page_force",
            "url": "https://example.com/force",
            "domain": "example.com",
            "html_path": "/tmp/force.html",
        },
        auto_id=False,
    )

    # Create fragment and claim for this task (normally would skip)
    await db.insert(
        "fragments",
        {
            "id": "frag_force",
            "page_id": "page_force",
            "text_content": "Force content",
            "fragment_type": "paragraph",
        },
        auto_id=False,
    )
    await db.insert(
        "claims",
        {
            "id": "claim_force",
            "task_id": "task_force",
            "claim_text": "Force claim",
        },
        auto_id=False,
    )
    await db.insert(
        "edges",
        {
            "id": "edge_force",
            "source_type": "fragment",
            "source_id": "frag_force",
            "target_type": "claim",
            "target_id": "claim_force",
            "relation": "origin",
        },
        auto_id=False,
    )

    mock_state = AsyncMock()

    with patch("src.crawler.fetcher.fetch_url") as mock_fetch:
        mock_fetch.return_value = {
            "ok": True,
            "page_id": "page_force",
            "html_path": "/tmp/force_new.html",
        }

        # When: Ingest with skip_if_exists=False
        await ingest_url_action(
            task_id="task_force",
            url="https://example.com/force",
            state=mock_state,
            policy={"skip_if_exists": False},
        )

    # Then: Fetch was called (not skipped)
    mock_fetch.assert_called_once()
