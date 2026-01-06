"""
Tests for query_view and list_views MCP tools.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-QV-N-01 | Valid view_name with task_id | Equivalence – normal | Returns rows successfully | - |
| TC-QV-N-02 | list_views call | Equivalence – normal | Returns all available views | - |
| TC-QV-N-03 | View with limit option | Equivalence – normal | Respects limit, sets truncated flag | - |
| TC-QV-A-01 | Missing view_name | Boundary – missing | Raises InvalidParamsError | - |
| TC-QV-A-02 | Non-existent view_name | Abnormal – not found | Returns ok=False with error | - |
| TC-QV-A-03 | limit > 200 | Boundary – max exceeded | Raises InvalidParamsError | - |
| TC-QV-A-04 | limit < 1 | Boundary – min exceeded | Raises InvalidParamsError | - |
| TC-SI-N-01 | Page with origin edges only | Equivalence – normal | claims_generated > 0, impact_score calculated | v_source_impact |
| TC-SI-N-02 | Page with origin + supports edges | Equivalence – normal | Both claims_generated and claims_supported populated | v_source_impact |
| TC-SI-N-03 | Multiple pages, different scores | Equivalence – normal | Ordered by impact_score DESC | v_source_impact |
| TC-SI-N-04 | list_views includes v_source_impact | Equivalence – normal | v_source_impact in view list | v_source_impact |
"""

import pytest

from src.storage.database import Database

pytestmark = pytest.mark.unit

from src.mcp.errors import InvalidParamsError
from src.mcp.tools import view


@pytest.mark.asyncio
async def test_query_view_valid_call(test_database: Database) -> None:
    """
    TC-QV-N-01: Valid view_name with task_id returns rows successfully.

    // Given: Valid view_name and task_id with data
    // When: Calling query_view
    // Then: Returns rows with ok=True
    """
    # Setup: Insert test data
    db = test_database
    task_id = "test_task_qv"
    claim_id = "claim_qv_001"

    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        (task_id, "test query", "completed"),
    )
    await db.execute(
        "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
        (claim_id, task_id, "Test claim text", 0.8),
    )

    result = await view.handle_query_view(
        {
            "view_name": "v_claim_evidence_summary",
            "task_id": task_id,
        }
    )

    assert result["ok"] is True
    assert result["view_name"] == "v_claim_evidence_summary"
    assert result["row_count"] >= 1
    assert "columns" in result
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_list_views() -> None:
    """
    TC-QV-N-02: list_views returns all available views.

    // Given: Views directory with templates
    // When: Calling list_views
    // Then: Returns list of view names with descriptions
    """
    result = await view.handle_list_views({})

    assert result["ok"] is True
    assert result["count"] > 0
    assert len(result["views"]) == result["count"]

    # Check expected views exist
    view_names = [v["name"] for v in result["views"]]
    expected_views = [
        "v_claim_evidence_summary",
        "v_contradictions",
        "v_unsupported_claims",
        "v_evidence_chain",
    ]
    for expected in expected_views:
        assert expected in view_names, f"Missing expected view: {expected}"

    # Check all views have descriptions
    for v in result["views"]:
        assert "name" in v
        assert "description" in v


@pytest.mark.asyncio
async def test_query_view_with_limit(test_database: Database) -> None:
    """
    TC-QV-N-03: View with limit option respects limit.

    // Given: Multiple claims in database
    // When: Calling query_view with limit
    // Then: Returns limited rows and sets truncated=True if applicable
    """
    db = test_database
    task_id = "test_task_limit"

    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        (task_id, "test query", "completed"),
    )

    # Insert multiple claims
    for i in range(5):
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
            (f"claim_limit_{i}", task_id, f"Claim {i}", 0.8),
        )

    result = await view.handle_query_view(
        {
            "view_name": "v_claim_evidence_summary",
            "task_id": task_id,
            "limit": 3,
        }
    )

    assert result["ok"] is True
    assert result["row_count"] == 3
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_query_view_missing_view_name() -> None:
    """
    TC-QV-A-01: Missing view_name raises InvalidParamsError.

    // Given: No view_name parameter
    // When: Calling query_view
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await view.handle_query_view({})

    assert "view_name is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_view_nonexistent_view() -> None:
    """
    TC-QV-A-02: Non-existent view_name returns ok=False.

    // Given: Invalid view_name
    // When: Calling query_view
    // Then: Returns ok=False with error message
    """
    result = await view.handle_query_view(
        {
            "view_name": "v_nonexistent_view",
        }
    )

    assert result["ok"] is False
    assert "error" in result
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_query_view_limit_too_high() -> None:
    """
    TC-QV-A-03: limit > 200 raises InvalidParamsError.

    // Given: limit option > 200
    // When: Calling query_view
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await view.handle_query_view(
            {
                "view_name": "v_claim_evidence_summary",
                "limit": 201,
            }
        )

    assert "limit must be between 1 and 200" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_view_limit_too_low() -> None:
    """
    TC-QV-A-04: limit < 1 raises InvalidParamsError.

    // Given: limit option < 1
    // When: Calling query_view
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await view.handle_query_view(
            {
                "view_name": "v_claim_evidence_summary",
                "limit": 0,
            }
        )

    assert "limit must be between 1 and 200" in str(exc_info.value)


# ============================================================================
# v_source_impact tests
# ============================================================================


@pytest.mark.asyncio
async def test_source_impact_origin_edges_only(test_database: Database) -> None:
    """
    TC-SI-N-01: Page with origin edges only has claims_generated > 0 and impact_score calculated.

    // Given: A page with claims extracted from it (origin edges)
    // When: Querying v_source_impact
    // Then: claims_generated > 0, claims_supported = 0, impact_score calculated
    """
    db = test_database
    task_id = "test_task_si_01"
    page_id = "page_si_01"
    fragment_id = "frag_si_01"
    claim_id = "claim_si_01"

    # Setup: task, page, fragment, claim, origin edge
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        (task_id, "source impact test", "completed"),
    )
    await db.execute(
        "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
        (page_id, "https://example.com/paper1", "example.com"),
    )
    await db.execute(
        "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
        (fragment_id, page_id, "paragraph", "Test fragment content"),
    )
    await db.execute(
        "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
        (claim_id, task_id, "Test claim from paper", 0.85),
    )
    # Origin edge: fragment -> claim
    await db.execute(
        """INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("edge_origin_01", "fragment", fragment_id, "claim", claim_id, "origin"),
    )

    result = await view.handle_query_view(
        {"view_name": "v_source_impact", "task_id": task_id}
    )

    assert result["ok"] is True
    assert result["row_count"] == 1

    row = result["rows"][0]
    assert row["claims_generated"] == 1
    assert row["claims_supported"] == 0
    assert row["impact_score"] > 0
    # impact_score = claims_generated + (avg_confidence * claims_generated * 0.5) + (claims_supported * 0.3)
    # = 1 + (0.85 * 1 * 0.5) + (0 * 0.3) = 1.425
    assert row["impact_score"] == pytest.approx(1.43, rel=0.1)


@pytest.mark.asyncio
async def test_source_impact_both_origin_and_supports(test_database: Database) -> None:
    """
    TC-SI-N-02: Page with both origin and supports edges has both metrics populated.

    // Given: A page with claims extracted (origin) and also supporting other claims (supports)
    // When: Querying v_source_impact
    // Then: Both claims_generated and claims_supported are populated
    """
    db = test_database
    task_id = "test_task_si_02"
    page_id = "page_si_02"
    fragment_id = "frag_si_02"
    claim_id_1 = "claim_si_02_a"
    claim_id_2 = "claim_si_02_b"

    # Setup: task, page, fragment, claims
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        (task_id, "source impact test 2", "completed"),
    )
    await db.execute(
        "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
        (page_id, "https://example.com/paper2", "example.com"),
    )
    await db.execute(
        "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
        (fragment_id, page_id, "paragraph", "Test fragment content 2"),
    )
    # Claim generated from this page
    await db.execute(
        "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
        (claim_id_1, task_id, "Claim generated from paper", 0.9),
    )
    # Another claim (could be from elsewhere)
    await db.execute(
        "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
        (claim_id_2, task_id, "Another claim to be supported", 0.8),
    )

    # Origin edge: fragment -> claim_1
    await db.execute(
        """INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("edge_origin_02", "fragment", fragment_id, "claim", claim_id_1, "origin"),
    )
    # Supports edge: fragment -> claim_2
    await db.execute(
        """INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("edge_supports_02", "fragment", fragment_id, "claim", claim_id_2, "supports"),
    )

    result = await view.handle_query_view(
        {"view_name": "v_source_impact", "task_id": task_id}
    )

    assert result["ok"] is True
    assert result["row_count"] == 1

    row = result["rows"][0]
    assert row["claims_generated"] == 1
    assert row["claims_supported"] == 1
    assert row["impact_score"] > 0
    # impact_score = 1 + (0.9 * 1 * 0.5) + (1 * 0.3) = 1 + 0.45 + 0.3 = 1.75
    assert row["impact_score"] == pytest.approx(1.75, rel=0.1)


@pytest.mark.asyncio
async def test_source_impact_multiple_pages_ordered(test_database: Database) -> None:
    """
    TC-SI-N-03: Multiple pages with different scores are ordered by impact_score DESC.

    // Given: Multiple pages with different claim generation counts
    // When: Querying v_source_impact
    // Then: Results ordered by impact_score DESC
    """
    db = test_database
    task_id = "test_task_si_03"

    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        (task_id, "source impact ordering test", "completed"),
    )

    # Page A: 1 claim
    await db.execute(
        "INSERT INTO pages (id, url, domain, title) VALUES (?, ?, ?, ?)",
        ("page_a", "https://example.com/a", "example.com", "Paper A"),
    )
    await db.execute(
        "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
        ("frag_a", "page_a", "paragraph", "Fragment A"),
    )
    await db.execute(
        "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
        ("claim_a", task_id, "Claim A", 0.8),
    )
    await db.execute(
        """INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("edge_a", "fragment", "frag_a", "claim", "claim_a", "origin"),
    )

    # Page B: 3 claims (higher impact)
    await db.execute(
        "INSERT INTO pages (id, url, domain, title) VALUES (?, ?, ?, ?)",
        ("page_b", "https://example.com/b", "example.com", "Paper B"),
    )
    await db.execute(
        "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
        ("frag_b", "page_b", "paragraph", "Fragment B"),
    )
    for i in range(3):
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
            (f"claim_b_{i}", task_id, f"Claim B{i}", 0.9),
        )
        await db.execute(
            """INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f"edge_b_{i}", "fragment", "frag_b", "claim", f"claim_b_{i}", "origin"),
        )

    result = await view.handle_query_view(
        {"view_name": "v_source_impact", "task_id": task_id}
    )

    assert result["ok"] is True
    assert result["row_count"] == 2

    # Should be ordered by impact_score DESC (Page B first)
    assert result["rows"][0]["title"] == "Paper B"
    assert result["rows"][1]["title"] == "Paper A"
    assert result["rows"][0]["impact_score"] > result["rows"][1]["impact_score"]


@pytest.mark.asyncio
async def test_list_views_includes_source_impact() -> None:
    """
    TC-SI-N-04: list_views includes v_source_impact.

    // Given: Views directory with v_source_impact template
    // When: Calling list_views
    // Then: v_source_impact is in the list
    """
    result = await view.handle_list_views({})

    assert result["ok"] is True
    view_names = [v["name"] for v in result["views"]]
    assert "v_source_impact" in view_names, "v_source_impact should be in view list"
