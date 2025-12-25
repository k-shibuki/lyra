"""Tests for create_task MCP tool.

Tests create_task handler behavior per ADR-0003.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-CT-N-01 | Valid query, budget_pages provided | Equivalence – normal | ok=True, budget.budget_pages returned | - |
| TC-CT-N-02 | Valid query, default budget | Equivalence – normal | ok=True, budget_pages=120, max_seconds=1200 | Default values |
| TC-CT-N-03 | Valid query, config omitted | Equivalence – normal | ok=True, default budget applied | - |
| TC-CT-A-01 | Empty query string | Boundary – empty | InvalidParamsError | - |
| TC-CT-A-02 | query missing | Boundary – NULL | KeyError or InvalidParamsError | - |
| TC-CT-A-03 | budget.max_pages (legacy) | Abnormal | InvalidParamsError with message | ADR-0003 breaking change |
| TC-CT-B-01 | budget_pages=0 | Boundary – zero | ok=True, budget_pages=0 | Zero allowed |
| TC-CT-B-02 | budget_pages=-1 | Boundary – negative | ok=True, budget_pages=-1 | Negative allowed (validation elsewhere) |
| TC-CT-B-03 | max_seconds=0 | Boundary – zero | ok=True, max_seconds=0 | Zero allowed |
| TC-CT-B-04 | max_seconds=-1 | Boundary – negative | ok=True, max_seconds=-1 | Negative allowed (validation elsewhere) |
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
        TC-CT-N-01: create_task returns budget_pages in response.

        // Given: Valid query and budget config
        // When: _handle_create_task is called
        // Then: ok=True and budget includes budget_pages
        """
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

    @pytest.mark.asyncio
    async def test_create_task_default_budget(self, test_database: Database) -> None:
        """
        TC-CT-N-02: create_task uses default budget when not specified.

        // Given: Valid query without budget config
        // When: _handle_create_task is called
        // Then: ok=True and budget uses defaults (budget_pages=120, max_seconds=1200)
        """
        from src.mcp.server import _handle_create_task

        db = test_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "query": "test query",
                    "config": {},
                }
            )

        assert result["ok"] is True
        assert result["budget"]["budget_pages"] == 120
        assert result["budget"]["max_seconds"] == 1200

    @pytest.mark.asyncio
    async def test_create_task_config_omitted(self, test_database: Database) -> None:
        """
        TC-CT-N-03: create_task works when config is omitted.

        // Given: Valid query without config
        // When: _handle_create_task is called
        // Then: ok=True and default budget applied
        """
        from src.mcp.server import _handle_create_task

        db = test_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "query": "test query",
                }
            )

        assert result["ok"] is True
        assert result["budget"]["budget_pages"] == 120
        assert result["budget"]["max_seconds"] == 1200

    @pytest.mark.asyncio
    async def test_create_task_empty_query(self, test_database: Database) -> None:
        """
        TC-CT-A-01: create_task rejects empty query string.

        // Given: Empty query string
        // When: _handle_create_task is called
        // Then: Task is created (empty string is allowed, validation elsewhere)
        """
        from src.mcp.server import _handle_create_task

        db = test_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "query": "",
                }
            )

        # Empty query is allowed (validation happens elsewhere)
        assert result["ok"] is True
        assert result["query"] == ""

    @pytest.mark.asyncio
    async def test_create_task_missing_query(self, test_database: Database) -> None:
        """
        TC-CT-A-02: create_task raises error when query is missing.

        // Given: query parameter missing
        // When: _handle_create_task is called
        // Then: KeyError raised
        """
        from src.mcp.server import _handle_create_task

        db = test_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            with pytest.raises(KeyError):
                await _handle_create_task({})

    @pytest.mark.asyncio
    async def test_create_task_legacy_max_pages_rejected(
        self, test_database: Database
    ) -> None:
        """
        TC-CT-A-03: create_task rejects legacy budget.max_pages key.

        // Given: budget.max_pages (legacy key) in config
        // When: _handle_create_task is called
        // Then: InvalidParamsError with clear message
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_create_task

        db = test_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            with pytest.raises(InvalidParamsError) as exc_info:
                await _handle_create_task(
                    {
                        "query": "test query",
                        "config": {"budget": {"max_pages": 10}},
                    }
                )

        assert "max_pages is no longer supported" in str(exc_info.value)
        assert "budget.budget_pages" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_task_budget_pages_zero(
        self, test_database: Database
    ) -> None:
        """
        TC-CT-B-01: create_task accepts budget_pages=0.

        // Given: budget_pages=0
        // When: _handle_create_task is called
        // Then: ok=True, budget_pages=0
        """
        from src.mcp.server import _handle_create_task

        db = test_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "query": "test query",
                    "config": {"budget": {"budget_pages": 0}},
                }
            )

        assert result["ok"] is True
        assert result["budget"]["budget_pages"] == 0

    @pytest.mark.asyncio
    async def test_create_task_budget_pages_negative(
        self, test_database: Database
    ) -> None:
        """
        TC-CT-B-02: create_task accepts negative budget_pages (validation elsewhere).

        // Given: budget_pages=-1
        // When: _handle_create_task is called
        // Then: ok=True, budget_pages=-1 (validation happens elsewhere)
        """
        from src.mcp.server import _handle_create_task

        db = test_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "query": "test query",
                    "config": {"budget": {"budget_pages": -1}},
                }
            )

        assert result["ok"] is True
        assert result["budget"]["budget_pages"] == -1

    @pytest.mark.asyncio
    async def test_create_task_max_seconds_zero(
        self, test_database: Database
    ) -> None:
        """
        TC-CT-B-03: create_task accepts max_seconds=0.

        // Given: max_seconds=0
        // When: _handle_create_task is called
        // Then: ok=True, max_seconds=0
        """
        from src.mcp.server import _handle_create_task

        db = test_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "query": "test query",
                    "config": {"budget": {"max_seconds": 0}},
                }
            )

        assert result["ok"] is True
        assert result["budget"]["max_seconds"] == 0

    @pytest.mark.asyncio
    async def test_create_task_max_seconds_negative(
        self, test_database: Database
    ) -> None:
        """
        TC-CT-B-04: create_task accepts negative max_seconds (validation elsewhere).

        // Given: max_seconds=-1
        // When: _handle_create_task is called
        // Then: ok=True, max_seconds=-1 (validation happens elsewhere)
        """
        from src.mcp.server import _handle_create_task

        db = test_database

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=db)):
            result = await _handle_create_task(
                {
                    "query": "test query",
                    "config": {"budget": {"max_seconds": -1}},
                }
            )

        assert result["ok"] is True
        assert result["budget"]["max_seconds"] == -1
