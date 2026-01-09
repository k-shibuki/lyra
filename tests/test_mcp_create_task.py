"""Tests for create_task MCP tool.

Tests create_task handler behavior per ADR-0003 and ADR-0017 (hypothesis-first).

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
|| TC-CT-N-01 | Valid hypothesis, max_pages provided | Equivalence – normal | ok=True, budget.max_pages returned | - |
|| TC-CT-N-02 | Valid hypothesis, default budget | Equivalence – normal | ok=True, max_pages=settings.task_limits.max_budget_pages_per_task, max_seconds=3600 | Defaults |
|| TC-CT-N-03 | Valid hypothesis, config omitted | Equivalence – normal | ok=True, default budget applied | - |
|| TC-CT-A-01 | Empty hypothesis string | Boundary – empty | Task created (empty allowed) | - |
|| TC-CT-A-02 | hypothesis missing | Boundary – NULL | KeyError | ADR-0017: hypothesis is required |
|| TC-CT-B-01 | max_pages=0 | Boundary – zero | ok=True, max_pages=0 | Zero allowed |
|| TC-CT-B-02 | max_pages=-1 | Boundary – negative | InvalidParamsError | - |
|| TC-CT-B-03 | max_seconds=0 | Boundary – zero | ok=True, max_seconds=0 | Zero allowed |
|| TC-CT-B-04 | max_seconds=-1 | Boundary – negative | ok=True, max_seconds=0 | Clamped |
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

if TYPE_CHECKING:
    from src.storage.database import Database

pytestmark = pytest.mark.integration


class TestCreateTaskValidation:
    """Tests for create_task validation (breaking changes)."""

    @pytest.mark.asyncio
    async def test_create_task_happy_path(self, test_database: Database) -> None:
        """
        TC-CT-N-01: create_task returns max_pages in response.

        // Given: Valid hypothesis and budget config (ADR-0017)
        // When: _handle_create_task is called
        // Then: ok=True and budget includes max_pages
        """
        from src.mcp.tools.task import handle_create_task as _handle_create_task

        db = test_database

        with patch("src.storage.database.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "hypothesis": "DPP-4 inhibitors improve HbA1c",
                    "config": {"budget": {"max_pages": 10, "max_seconds": 60}},
                }
            )

        assert result["ok"] is True
        assert "task_id" in result
        assert result["hypothesis"] == "DPP-4 inhibitors improve HbA1c"
        assert result["budget"]["max_pages"] == 10
        assert result["budget"]["max_seconds"] == 60

    @pytest.mark.asyncio
    async def test_create_task_default_budget(self, test_database: Database) -> None:
        """
        TC-CT-N-02: create_task uses default budget when not specified.

        // Given: Valid hypothesis without budget config (ADR-0017)
        // When: _handle_create_task is called
        // Then: ok=True and budget uses defaults (max_pages=settings upper bound, max_seconds=3600)
        """
        from src.mcp.tools.task import handle_create_task as _handle_create_task

        db = test_database

        with patch("src.storage.database.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "hypothesis": "test hypothesis",
                    "config": {},
                }
            )

        assert result["ok"] is True
        assert result["budget"]["max_pages"] == 200
        assert result["budget"]["max_seconds"] == 3600

    @pytest.mark.asyncio
    async def test_create_task_config_omitted(self, test_database: Database) -> None:
        """
        TC-CT-N-03: create_task works when config is omitted.

        // Given: Valid hypothesis without config (ADR-0017)
        // When: _handle_create_task is called
        // Then: ok=True and default budget applied
        """
        from src.mcp.tools.task import handle_create_task as _handle_create_task

        db = test_database

        with patch("src.storage.database.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "hypothesis": "test hypothesis",
                }
            )

        assert result["ok"] is True
        assert result["budget"]["max_pages"] == 200
        assert result["budget"]["max_seconds"] == 3600

    @pytest.mark.asyncio
    async def test_create_task_empty_hypothesis(self, test_database: Database) -> None:
        """
        TC-CT-A-01: create_task allows empty hypothesis string.

        // Given: Empty hypothesis string (ADR-0017)
        // When: _handle_create_task is called
        // Then: Task is created (empty string is allowed, validation elsewhere)
        """
        from src.mcp.tools.task import handle_create_task as _handle_create_task

        db = test_database

        with patch("src.storage.database.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "hypothesis": "",
                }
            )

        # Empty hypothesis is allowed (validation happens elsewhere)
        assert result["ok"] is True
        assert result["hypothesis"] == ""

    @pytest.mark.asyncio
    async def test_create_task_missing_hypothesis(self, test_database: Database) -> None:
        """
        TC-CT-A-02: create_task raises error when hypothesis is missing.

        // Given: hypothesis parameter missing (ADR-0017)
        // When: _handle_create_task is called
        // Then: KeyError raised
        """
        from src.mcp.tools.task import handle_create_task as _handle_create_task

        db = test_database

        with patch("src.storage.database.get_database", new=AsyncMock(return_value=db)):
            with pytest.raises(KeyError):
                await _handle_create_task({})

    @pytest.mark.asyncio
    async def test_create_task_budget_pages_zero(self, test_database: Database) -> None:
        """
        TC-CT-B-01: create_task accepts max_pages=0.

        // Given: max_pages=0
        // When: _handle_create_task is called
        // Then: ok=True, max_pages=0
        """
        from src.mcp.tools.task import handle_create_task as _handle_create_task

        db = test_database

        with patch("src.storage.database.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "hypothesis": "test hypothesis",
                    "config": {"budget": {"max_pages": 0}},
                }
            )

        assert result["ok"] is True
        assert result["budget"]["max_pages"] == 0

    @pytest.mark.asyncio
    async def test_create_task_budget_pages_negative(self, test_database: Database) -> None:
        """
        TC-CT-B-02: create_task rejects negative max_pages.

        // Given: max_pages=-1 (ADR-0017)
        // When: _handle_create_task is called
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.task import handle_create_task as _handle_create_task

        db = test_database

        with patch("src.storage.database.get_database", new=AsyncMock(return_value=db)):
            with pytest.raises(InvalidParamsError) as e:
                await _handle_create_task(
                    {
                        "hypothesis": "test hypothesis",
                        "config": {"budget": {"max_pages": -1}},
                    }
                )

        assert "budget.max_pages must be >= 0" in str(e.value)

    @pytest.mark.asyncio
    async def test_create_task_max_seconds_zero(self, test_database: Database) -> None:
        """
        TC-CT-B-03: create_task accepts max_seconds=0.

        // Given: max_seconds=0 (ADR-0017)
        // When: _handle_create_task is called
        // Then: ok=True, max_seconds=0
        """
        from src.mcp.tools.task import handle_create_task as _handle_create_task

        db = test_database

        with patch("src.storage.database.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "hypothesis": "test hypothesis",
                    "config": {"budget": {"max_seconds": 0}},
                }
            )

        assert result["ok"] is True
        assert result["budget"]["max_seconds"] == 0

    @pytest.mark.asyncio
    async def test_create_task_max_seconds_negative(self, test_database: Database) -> None:
        """
        TC-CT-B-04: create_task clamps negative max_seconds to 0.

        // Given: max_seconds=-1 (ADR-0017)
        // When: _handle_create_task is called
        // Then: ok=True, max_seconds=0
        """
        from src.mcp.tools.task import handle_create_task as _handle_create_task

        db = test_database

        with patch("src.storage.database.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "hypothesis": "test hypothesis",
                    "config": {"budget": {"max_seconds": -1}},
                }
            )

        assert result["ok"] is True
        assert result["budget"]["max_seconds"] == 0
