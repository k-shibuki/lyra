"""Tests for v_reference_candidates view.

Test perspectives:
- TC-VREF-N-01: candidate without origin edge → view shows it
- TC-VREF-N-02: candidate with origin edge → view excludes it
- TC-VREF-B-01: candidate with html_path but no origin → view shows it ("strong requirement")
- TC-VREF-A-01: candidate already in task_pages → view excludes it
"""

from collections.abc import AsyncGenerator

import pytest

from src.storage.database import Database
from src.storage.view_manager import ViewManager


@pytest.fixture
async def setup_reference_candidates_data(
    test_database: Database,
) -> AsyncGenerator[Database]:
    """Set up test data for v_reference_candidates tests."""
    db = test_database

    # Create a task
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_1", "Test hypothesis", "exploring"),
    )

    # Create citing pages (pages associated with task via task_pages)
    await db.insert(
        "pages",
        {
            "id": "citing_page_1",
            "url": "https://example.com/citing",
            "domain": "example.com",
            "html_path": "/tmp/citing.html",
        },
        auto_id=False,
    )

    # Associate citing page with task
    await db.execute(
        "INSERT INTO task_pages (id, task_id, page_id, reason, depth) VALUES (?, ?, ?, ?, ?)",
        ("tp_1", "task_1", "citing_page_1", "serp", 0),
    )

    # Create candidate pages (pages cited by citing_page_1)
    # Candidate 1: No html_path, no origin edge (should appear)
    await db.insert(
        "pages",
        {
            "id": "candidate_page_1",
            "url": "https://cited.com/paper1",
            "domain": "cited.com",
        },
        auto_id=False,
    )

    # Candidate 2: With html_path but no origin edge (should appear - "strong requirement")
    await db.insert(
        "pages",
        {
            "id": "candidate_page_2",
            "url": "https://cited.com/paper2",
            "domain": "cited.com",
            "html_path": "/tmp/paper2.html",
        },
        auto_id=False,
    )

    # Candidate 3: With origin edge for this task (should NOT appear)
    await db.insert(
        "pages",
        {
            "id": "candidate_page_3",
            "url": "https://cited.com/paper3",
            "domain": "cited.com",
            "html_path": "/tmp/paper3.html",
        },
        auto_id=False,
    )

    # Create fragment for candidate 3
    await db.insert(
        "fragments",
        {
            "id": "frag_3",
            "page_id": "candidate_page_3",
            "text_content": "Test fragment",
            "fragment_type": "paragraph",
        },
        auto_id=False,
    )

    # Create claim for task_1 from candidate 3
    await db.insert(
        "claims",
        {
            "id": "claim_3",
            "task_id": "task_1",
            "claim_text": "Test claim",
        },
        auto_id=False,
    )

    # Create origin edge (fragment -> claim) for candidate 3
    await db.insert(
        "edges",
        {
            "id": "edge_origin_3",
            "source_type": "fragment",
            "source_id": "frag_3",
            "target_type": "claim",
            "target_id": "claim_3",
            "relation": "origin",
        },
        auto_id=False,
    )

    # Candidate 4: Already in task_pages (should NOT appear)
    await db.insert(
        "pages",
        {
            "id": "candidate_page_4",
            "url": "https://cited.com/paper4",
            "domain": "cited.com",
        },
        auto_id=False,
    )
    await db.execute(
        "INSERT INTO task_pages (id, task_id, page_id, reason, depth) VALUES (?, ?, ?, ?, ?)",
        ("tp_4", "task_1", "candidate_page_4", "citation_chase", 1),
    )

    # Create 'cites' edges from citing_page_1 to all candidates
    for i, candidate_id in enumerate(
        ["candidate_page_1", "candidate_page_2", "candidate_page_3", "candidate_page_4"], start=1
    ):
        await db.insert(
            "edges",
            {
                "id": f"cites_edge_{i}",
                "source_type": "page",
                "source_id": "citing_page_1",
                "target_type": "page",
                "target_id": candidate_id,
                "relation": "cites",
                "citation_context": f"See reference {i}",
            },
            auto_id=False,
        )

    yield db


@pytest.mark.asyncio
async def test_vref_candidate_without_origin_appears(
    setup_reference_candidates_data: Database,
) -> None:
    """TC-VREF-N-01: Candidate without origin edge should appear in view."""
    # Given: candidate_page_1 has no html_path and no origin edge
    db = setup_reference_candidates_data

    # When: Query v_reference_candidates view
    view_manager = ViewManager()
    sql = view_manager.render("v_reference_candidates", task_id="task_1")
    rows = await db.fetch_all(sql)

    # Then: candidate_page_1 should appear
    candidate_ids = [r["candidate_page_id"] for r in rows]
    assert "candidate_page_1" in candidate_ids


@pytest.mark.asyncio
async def test_vref_candidate_with_origin_excluded(
    setup_reference_candidates_data: Database,
) -> None:
    """TC-VREF-N-02: Candidate with origin edge should be excluded from view."""
    # Given: candidate_page_3 has origin edge for task_1
    db = setup_reference_candidates_data

    # When: Query v_reference_candidates view
    view_manager = ViewManager()
    sql = view_manager.render("v_reference_candidates", task_id="task_1")
    rows = await db.fetch_all(sql)

    # Then: candidate_page_3 should NOT appear
    candidate_ids = [r["candidate_page_id"] for r in rows]
    assert "candidate_page_3" not in candidate_ids


@pytest.mark.asyncio
async def test_vref_candidate_with_html_but_no_origin_appears(
    setup_reference_candidates_data: Database,
) -> None:
    """TC-VREF-B-01: Candidate with html_path but no origin should appear ("strong requirement")."""
    # Given: candidate_page_2 has html_path but no origin edge
    db = setup_reference_candidates_data

    # When: Query v_reference_candidates view
    view_manager = ViewManager()
    sql = view_manager.render("v_reference_candidates", task_id="task_1")
    rows = await db.fetch_all(sql)

    # Then: candidate_page_2 should appear (with html_path visible)
    candidate_ids = [r["candidate_page_id"] for r in rows]
    assert "candidate_page_2" in candidate_ids

    # Verify html_path is included in result
    candidate_2 = next(r for r in rows if r["candidate_page_id"] == "candidate_page_2")
    assert candidate_2["candidate_html_path"] == "/tmp/paper2.html"


@pytest.mark.asyncio
async def test_vref_candidate_in_task_pages_excluded(
    setup_reference_candidates_data: Database,
) -> None:
    """TC-VREF-A-01: Candidate already in task_pages should be excluded."""
    # Given: candidate_page_4 is already in task_pages for task_1
    db = setup_reference_candidates_data

    # When: Query v_reference_candidates view
    view_manager = ViewManager()
    sql = view_manager.render("v_reference_candidates", task_id="task_1")
    rows = await db.fetch_all(sql)

    # Then: candidate_page_4 should NOT appear
    candidate_ids = [r["candidate_page_id"] for r in rows]
    assert "candidate_page_4" not in candidate_ids


@pytest.mark.asyncio
async def test_vref_citation_edge_id_present(setup_reference_candidates_data: Database) -> None:
    """Verify citation_edge_id column is present for include/exclude."""
    # Given: View has candidates
    db = setup_reference_candidates_data

    # When: Query v_reference_candidates view
    view_manager = ViewManager()
    sql = view_manager.render("v_reference_candidates", task_id="task_1")
    rows = await db.fetch_all(sql)

    # Then: Each row should have citation_edge_id
    assert len(rows) > 0
    for row in rows:
        assert "citation_edge_id" in row
        assert row["citation_edge_id"] is not None
        assert row["citation_edge_id"].startswith("cites_edge_")


@pytest.mark.asyncio
async def test_vref_requires_task_id() -> None:
    """Verify view returns error without task_id."""
    # Given: No task_id
    view_manager = ViewManager()

    # When: Render view without task_id
    sql = view_manager.render("v_reference_candidates")

    # Then: SQL should contain error message
    assert "ERROR" in sql


@pytest.mark.asyncio
async def test_vref_empty_when_no_citations(test_database: Database) -> None:
    """Verify view returns empty when no citations exist."""
    db = test_database

    # Given: Task exists but no citations
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_empty", "Empty hypothesis", "exploring"),
    )

    # When: Query v_reference_candidates view
    view_manager = ViewManager()
    sql = view_manager.render("v_reference_candidates", task_id="task_empty")
    rows = await db.fetch_all(sql)

    # Then: No rows returned
    assert len(rows) == 0
