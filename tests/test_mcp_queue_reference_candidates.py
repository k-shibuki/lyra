"""Tests for queue_reference_candidates MCP tool.

Test perspectives:
- TC-QRC-N-01: include_ids whitelists specific candidates
- TC-QRC-A-01: exclude_ids blacklists specific candidates
- TC-QRC-B-01: dry_run returns candidates without queueing
- TC-QRC-N-02: DOI extraction from URL creates kind='doi' target
- TC-QRC-N-03: Plain URL creates kind='url' target
- TC-QRC-A-02: Invalid task_id raises TaskNotFoundError
- TC-QRC-A-03: Both include_ids and exclude_ids raises InvalidParamsError
"""

from collections.abc import AsyncGenerator

import pytest

from src.mcp.errors import InvalidParamsError, TaskNotFoundError
from src.mcp.tools.reference_candidates import (
    _extract_doi_from_url,
    handle_queue_reference_candidates,
)
from src.storage.database import Database


class TestExtractDoiFromUrl:
    """Tests for DOI extraction helper."""

    def test_extract_doi_from_doi_org_url(self) -> None:
        """Extract DOI from doi.org URL."""
        # Given: doi.org URL
        url = "https://doi.org/10.1234/example.paper"

        # When: Extract DOI
        doi = _extract_doi_from_url(url)

        # Then: DOI extracted correctly
        assert doi == "10.1234/example.paper"

    def test_extract_doi_from_dx_doi_org_url(self) -> None:
        """Extract DOI from dx.doi.org URL."""
        # Given: dx.doi.org URL
        url = "https://dx.doi.org/10.5678/another.paper"

        # When: Extract DOI
        doi = _extract_doi_from_url(url)

        # Then: DOI extracted correctly
        assert doi == "10.5678/another.paper"

    def test_extract_doi_returns_none_for_non_doi_url(self) -> None:
        """Return None for URL without DOI."""
        # Given: Regular URL
        url = "https://example.com/some/paper"

        # When: Extract DOI
        doi = _extract_doi_from_url(url)

        # Then: None returned
        assert doi is None

    def test_extract_doi_strips_trailing_punctuation(self) -> None:
        """Strip trailing punctuation from extracted DOI."""
        # Given: DOI URL with trailing punctuation
        url = "https://doi.org/10.1234/example.),"

        # When: Extract DOI
        doi = _extract_doi_from_url(url)

        # Then: Trailing punctuation removed
        assert doi == "10.1234/example"


@pytest.fixture
async def setup_qrc_data(test_database: Database) -> AsyncGenerator[Database]:
    """Set up test data for queue_reference_candidates tests."""
    db = test_database

    # Create a task
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_qrc", "QRC test hypothesis", "exploring"),
    )

    # Create citing page
    await db.insert(
        "pages",
        {
            "id": "citing_qrc",
            "url": "https://example.com/citing",
            "domain": "example.com",
            "html_path": "/tmp/citing.html",
        },
        auto_id=False,
    )

    # Associate citing page with task
    await db.execute(
        "INSERT INTO task_pages (id, task_id, page_id, reason, depth) VALUES (?, ?, ?, ?, ?)",
        ("tp_qrc", "task_qrc", "citing_qrc", "serp", 0),
    )

    # Create candidate pages
    # Candidate 1: DOI URL
    await db.insert(
        "pages",
        {
            "id": "candidate_doi",
            "url": "https://doi.org/10.1234/test.paper",
            "domain": "doi.org",
        },
        auto_id=False,
    )

    # Candidate 2: Regular URL
    await db.insert(
        "pages",
        {
            "id": "candidate_url",
            "url": "https://pubmed.ncbi.nlm.nih.gov/12345",
            "domain": "pubmed.ncbi.nlm.nih.gov",
        },
        auto_id=False,
    )

    # Candidate 3: Another DOI URL
    await db.insert(
        "pages",
        {
            "id": "candidate_doi_2",
            "url": "https://dx.doi.org/10.5678/another.paper",
            "domain": "dx.doi.org",
        },
        auto_id=False,
    )

    # Create 'cites' edges
    edges = [
        ("edge_doi", "candidate_doi", "DOI reference"),
        ("edge_url", "candidate_url", "PubMed reference"),
        ("edge_doi_2", "candidate_doi_2", "Another DOI reference"),
    ]
    for edge_id, target_id, context in edges:
        await db.insert(
            "edges",
            {
                "id": edge_id,
                "source_type": "page",
                "source_id": "citing_qrc",
                "target_type": "page",
                "target_id": target_id,
                "relation": "cites",
                "citation_context": context,
            },
            auto_id=False,
        )

    yield db


@pytest.mark.asyncio
async def test_qrc_include_ids_whitelists(setup_qrc_data: Database) -> None:
    """TC-QRC-N-01: include_ids whitelists specific candidates."""
    # Given: Multiple candidates available
    # When: Queue with include_ids for one candidate
    result = await handle_queue_reference_candidates(
        {
            "task_id": "task_qrc",
            "include_ids": ["edge_doi"],
            "dry_run": True,
        }
    )

    # Then: Only the included candidate returned
    assert result["ok"] is True
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["citation_edge_id"] == "edge_doi"


@pytest.mark.asyncio
async def test_qrc_exclude_ids_blacklists(setup_qrc_data: Database) -> None:
    """TC-QRC-A-01: exclude_ids blacklists specific candidates."""
    # Given: Multiple candidates available
    # When: Queue with exclude_ids for one candidate
    result = await handle_queue_reference_candidates(
        {
            "task_id": "task_qrc",
            "exclude_ids": ["edge_doi"],
            "dry_run": True,
        }
    )

    # Then: The excluded candidate is not in results
    assert result["ok"] is True
    edge_ids = [c["citation_edge_id"] for c in result["candidates"]]
    assert "edge_doi" not in edge_ids
    assert "edge_url" in edge_ids
    assert "edge_doi_2" in edge_ids


@pytest.mark.asyncio
async def test_qrc_dry_run_no_queue(setup_qrc_data: Database) -> None:
    """TC-QRC-B-01: dry_run returns candidates without queueing."""
    # Given: Candidates available
    db = setup_qrc_data

    # When: Call with dry_run=True
    result = await handle_queue_reference_candidates(
        {
            "task_id": "task_qrc",
            "dry_run": True,
        }
    )

    # Then: Candidates returned but nothing queued
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["queued_count"] == 0
    assert len(result["candidates"]) > 0

    # Verify no jobs were created
    jobs = await db.fetch_all(
        "SELECT * FROM jobs WHERE task_id = ? AND kind = 'target_queue'",
        ("task_qrc",),
    )
    assert len(jobs) == 0


@pytest.mark.asyncio
async def test_qrc_doi_url_creates_doi_target(setup_qrc_data: Database) -> None:
    """TC-QRC-N-02: DOI URL creates kind='doi' target."""
    # Given: Candidate with DOI URL
    # When: Queue the DOI candidate
    result = await handle_queue_reference_candidates(
        {
            "task_id": "task_qrc",
            "include_ids": ["edge_doi"],
            "dry_run": True,
        }
    )

    # Then: Target is kind='doi'
    assert result["ok"] is True
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["kind"] == "doi"
    assert result["candidates"][0]["doi"] == "10.1234/test.paper"


@pytest.mark.asyncio
async def test_qrc_plain_url_creates_url_target(setup_qrc_data: Database) -> None:
    """TC-QRC-N-03: Plain URL creates kind='url' target."""
    # Given: Candidate with plain URL
    # When: Queue the URL candidate
    result = await handle_queue_reference_candidates(
        {
            "task_id": "task_qrc",
            "include_ids": ["edge_url"],
            "dry_run": True,
        }
    )

    # Then: Target is kind='url'
    assert result["ok"] is True
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["kind"] == "url"
    assert result["candidates"][0]["doi"] is None


@pytest.mark.asyncio
async def test_qrc_invalid_task_raises_error(test_database: Database) -> None:
    """TC-QRC-A-02: Invalid task_id raises TaskNotFoundError."""
    # Given: Non-existent task
    # When/Then: Raises TaskNotFoundError
    with pytest.raises(TaskNotFoundError):
        await handle_queue_reference_candidates(
            {
                "task_id": "nonexistent_task",
            }
        )


@pytest.mark.asyncio
async def test_qrc_both_include_exclude_raises_error(setup_qrc_data: Database) -> None:
    """TC-QRC-A-03: Both include_ids and exclude_ids raises InvalidParamsError."""
    # Given: Both include_ids and exclude_ids specified
    # When/Then: Raises InvalidParamsError
    with pytest.raises(InvalidParamsError) as exc_info:
        await handle_queue_reference_candidates(
            {
                "task_id": "task_qrc",
                "include_ids": ["edge_doi"],
                "exclude_ids": ["edge_url"],
            }
        )

    assert "include_ids" in str(exc_info.value) or "exclude_ids" in str(exc_info.value)


@pytest.mark.asyncio
async def test_qrc_actual_queue_creates_jobs(setup_qrc_data: Database) -> None:
    """Verify actual queueing creates jobs in database."""
    # Given: Candidates available
    db = setup_qrc_data

    # When: Queue without dry_run
    result = await handle_queue_reference_candidates(
        {
            "task_id": "task_qrc",
            "limit": 2,
            "dry_run": False,
        }
    )

    # Then: Jobs created in database
    assert result["ok"] is True
    assert result["queued_count"] > 0
    assert result["dry_run"] is False

    jobs = await db.fetch_all(
        "SELECT * FROM jobs WHERE task_id = ? AND kind = 'target_queue'",
        ("task_qrc",),
    )
    assert len(jobs) == result["queued_count"]


@pytest.mark.asyncio
async def test_qrc_respects_limit(setup_qrc_data: Database) -> None:
    """Verify limit parameter is respected."""
    # Given: Multiple candidates
    # When: Queue with limit=1
    result = await handle_queue_reference_candidates(
        {
            "task_id": "task_qrc",
            "limit": 1,
            "dry_run": True,
        }
    )

    # Then: Only 1 candidate returned
    assert len(result["candidates"]) == 1


@pytest.mark.asyncio
async def test_qrc_skips_duplicates(setup_qrc_data: Database) -> None:
    """Verify duplicate targets are skipped."""
    # Given: Queue same candidates twice
    await handle_queue_reference_candidates(
        {
            "task_id": "task_qrc",
            "include_ids": ["edge_doi"],
            "dry_run": False,
        }
    )

    # When: Queue again
    result = await handle_queue_reference_candidates(
        {
            "task_id": "task_qrc",
            "include_ids": ["edge_doi"],
            "dry_run": False,
        }
    )

    # Then: Duplicate is skipped
    assert result["ok"] is True
    assert result["queued_count"] == 0
    assert result["skipped_count"] == 1
