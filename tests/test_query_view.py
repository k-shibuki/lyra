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
