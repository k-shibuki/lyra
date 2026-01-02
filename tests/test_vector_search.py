"""
Tests for vector_search MCP tool.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-VS-N-01 | Valid query, target=claims | Equivalence – normal | Returns results with similarity scores | - |
| TC-VS-N-02 | Valid query, target=fragments | Equivalence – normal | Returns results with similarity scores | - |
| TC-VS-N-03 | Query with task_id filter | Equivalence – normal | Returns only task-scoped results | - |
| TC-VS-N-04 | top_k parameter | Equivalence – normal | Respects top_k limit | - |
| TC-VS-N-05 | min_similarity parameter | Equivalence – normal | Filters by similarity threshold | - |
| TC-VS-A-01 | Missing query parameter | Boundary – missing | Raises InvalidParamsError | - |
| TC-VS-A-02 | Empty query string | Boundary – empty | Raises InvalidParamsError | - |
| TC-VS-A-03 | Invalid target (not fragments/claims) | Boundary – invalid enum | Raises InvalidParamsError | - |
| TC-VS-A-04 | top_k > 50 | Boundary – max exceeded | Raises InvalidParamsError | - |
| TC-VS-A-05 | top_k < 1 | Boundary – min exceeded | Raises InvalidParamsError | - |
| TC-VS-A-06 | min_similarity > 1.0 | Boundary – max exceeded | Raises InvalidParamsError | - |
| TC-VS-A-07 | min_similarity < 0.0 | Boundary – min exceeded | Raises InvalidParamsError | - |
"""

import pytest

pytestmark = pytest.mark.unit

from unittest.mock import patch

from src.mcp.errors import InvalidParamsError
from src.mcp.tools import vector


@pytest.mark.asyncio
async def test_vector_search_valid_query_claims(test_database) -> None:
    """
    TC-VS-N-01: Valid query with target=claims returns results.

    // Given: Valid query and target=claims
    // When: Executing vector_search
    // Then: Returns results with similarity scores
    """
    # Mock ML client and vector_search
    with patch("src.mcp.tools.vector.vector_search") as mock_search:
        mock_search.return_value = [
            {"id": "claim_1", "similarity": 0.85, "text_preview": "Test claim"},
        ]

        result = await vector.handle_vector_search({"query": "test query", "target": "claims"})

        assert result["ok"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["similarity"] == 0.85
        assert "total_searched" in result


@pytest.mark.asyncio
async def test_vector_search_valid_query_fragments(test_database) -> None:
    """
    TC-VS-N-02: Valid query with target=fragments returns results.

    // Given: Valid query and target=fragments
    // When: Executing vector_search
    // Then: Returns results with similarity scores
    """
    with patch("src.mcp.tools.vector.vector_search") as mock_search:
        mock_search.return_value = [
            {"id": "frag_1", "similarity": 0.75, "text_preview": "Test fragment"},
        ]

        result = await vector.handle_vector_search({"query": "test query", "target": "fragments"})

        assert result["ok"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "frag_1"


@pytest.mark.asyncio
async def test_vector_search_with_task_id(test_database) -> None:
    """
    TC-VS-N-03: Query with task_id filter returns only task-scoped results.

    // Given: Query with task_id parameter
    // When: Executing vector_search
    // Then: Returns only results from specified task
    """
    with patch("src.mcp.tools.vector.vector_search") as mock_search:
        mock_search.return_value = [
            {"id": "claim_1", "similarity": 0.80, "text_preview": "Task claim"},
        ]

        result = await vector.handle_vector_search(
            {"query": "test", "target": "claims", "task_id": "task_123"}
        )

        assert result["ok"] is True
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args[1]
        assert call_kwargs["task_id"] == "task_123"


@pytest.mark.asyncio
async def test_vector_search_top_k(test_database) -> None:
    """
    TC-VS-N-04: top_k parameter respects limit.

    // Given: Query with top_k=5
    // When: Executing vector_search
    // Then: Returns at most 5 results
    """
    with patch("src.mcp.tools.vector.vector_search") as mock_search:
        mock_search.return_value = [
            {"id": f"claim_{i}", "similarity": 0.9 - i * 0.1, "text_preview": f"Claim {i}"}
            for i in range(3)
        ]

        result = await vector.handle_vector_search(
            {"query": "test", "target": "claims", "top_k": 5}
        )

        assert result["ok"] is True
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args[1]
        assert call_kwargs["top_k"] == 5


@pytest.mark.asyncio
async def test_vector_search_min_similarity(test_database) -> None:
    """
    TC-VS-N-05: min_similarity parameter filters results.

    // Given: Query with min_similarity=0.7
    // When: Executing vector_search
    // Then: Only returns results with similarity >= 0.7
    """
    with patch("src.mcp.tools.vector.vector_search") as mock_search:
        mock_search.return_value = [
            {"id": "claim_1", "similarity": 0.75, "text_preview": "High similarity"},
        ]

        result = await vector.handle_vector_search(
            {"query": "test", "target": "claims", "min_similarity": 0.7}
        )

        assert result["ok"] is True
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args[1]
        assert call_kwargs["min_similarity"] == 0.7


@pytest.mark.asyncio
async def test_vector_search_missing_query() -> None:
    """
    TC-VS-A-01: Missing query parameter raises InvalidParamsError.

    // Given: No query parameter
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search({"target": "claims"})

    assert "query is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_empty_query() -> None:
    """
    TC-VS-A-02: Empty query string raises InvalidParamsError.

    // Given: Empty query string
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search({"query": "", "target": "claims"})

    assert "query is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_invalid_target() -> None:
    """
    TC-VS-A-03: Invalid target raises InvalidParamsError.

    // Given: target not in ['fragments', 'claims']
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search({"query": "test", "target": "invalid"})

    assert "target must be 'fragments' or 'claims'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_top_k_too_high() -> None:
    """
    TC-VS-A-04: top_k > 50 raises InvalidParamsError.

    // Given: top_k=51
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search({"query": "test", "target": "claims", "top_k": 51})

    assert "top_k must be between 1 and 50" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_top_k_too_low() -> None:
    """
    TC-VS-A-05: top_k < 1 raises InvalidParamsError.

    // Given: top_k=0
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search({"query": "test", "target": "claims", "top_k": 0})

    assert "top_k must be between 1 and 50" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_min_similarity_too_high() -> None:
    """
    TC-VS-A-06: min_similarity > 1.0 raises InvalidParamsError.

    // Given: min_similarity=1.1
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search(
            {"query": "test", "target": "claims", "min_similarity": 1.1}
        )

    assert "min_similarity must be between 0.0 and 1.0" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_min_similarity_too_low() -> None:
    """
    TC-VS-A-07: min_similarity < 0.0 raises InvalidParamsError.

    // Given: min_similarity=-0.1
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search(
            {"query": "test", "target": "claims", "min_similarity": -0.1}
        )

    assert "min_similarity must be between 0.0 and 1.0" in str(exc_info.value)
