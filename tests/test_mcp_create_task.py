"""Tests for create_task MCP tool.

Tests create_task handler behavior per ADR-0003.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-CT-N-01 | Valid query, budget_pages provided | Equivalence – normal | ok=True, budget.budget_pages returned | - |
"""

import pytest


class TestCreateTaskValidation:
    """Tests for create_task validation (breaking changes)."""

    @pytest.mark.asyncio
    async def test_create_task_happy_path(self, test_database) -> None:
        """
        TC-CT-N-01: create_task returns budget_pages in response.

        // Given: Valid query and budget config
        // When: _handle_create_task is called
        // Then: ok=True and budget includes budget_pages
        """
        from unittest.mock import AsyncMock, patch

        from src.mcp.server import _handle_create_task

        db = test_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "query": "test query",
                    "config": {"budget": {"budget_pages": 10, "max_seconds": 60}},
                }
            )

        assert result["ok"] is True
        assert "task_id" in result
        assert result["budget"]["budget_pages"] == 10
        assert result["budget"]["max_seconds"] == 60


