"""Tests for search and stop_task MCP tools.

Tests the search pipeline and task stopping per §3.2.1.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


class TestSearchValidation:
    """Tests for search parameter validation."""

    @pytest.mark.asyncio
    async def test_missing_task_id_raises_error(self) -> None:
        """
        TC-A-01: Missing task_id parameter.
        
        // Given: No task_id provided
        // When: Calling search with only query
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_search
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_search({"query": "test query"})
        
        assert exc_info.value.details.get("param_name") == "task_id"

    @pytest.mark.asyncio
    async def test_missing_query_raises_error(self) -> None:
        """
        TC-A-02: Missing query parameter.
        
        // Given: No query provided
        // When: Calling search with only task_id
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_search
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_search({"task_id": "task_123"})
        
        assert exc_info.value.details.get("param_name") == "query"

    @pytest.mark.asyncio
    async def test_nonexistent_task_raises_error(self) -> None:
        """
        TC-A-03: Non-existent task_id.
        
        // Given: task_id not in database
        // When: Calling search
        // Then: Raises TaskNotFoundError
        """
        from src.mcp.server import _handle_search
        from src.mcp.errors import TaskNotFoundError
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = None
        
        with patch("src.mcp.server.get_database", return_value=mock_db):
            with pytest.raises(TaskNotFoundError) as exc_info:
                await _handle_search({
                    "task_id": "nonexistent_task",
                    "query": "test query",
                })
        
        assert exc_info.value.details.get("task_id") == "nonexistent_task"


class TestSearchExecution:
    """Tests for search execution."""

    @pytest.fixture
    def mock_task(self) -> dict[str, Any]:
        """Create mock task data."""
        return {"id": "task_abc123"}

    @pytest.fixture
    def mock_search_result(self) -> dict[str, Any]:
        """Create mock search result."""
        return {
            "ok": True,
            "search_id": "s_001",
            "query": "test search query",
            "status": "satisfied",
            "pages_fetched": 15,
            "useful_fragments": 8,
            "harvest_rate": 0.53,
            "claims_found": [
                {
                    "id": "c_001",
                    "text": "Test claim",
                    "confidence": 0.85,
                    "source_url": "https://example.com",
                    "is_primary_source": True,
                }
            ],
            "satisfaction_score": 0.85,
            "novelty_score": 0.42,
            "budget_remaining": {"pages": 45, "percent": 37},
        }

    @pytest.mark.asyncio
    async def test_normal_search_execution(
        self, mock_task: dict[str, Any], mock_search_result: dict[str, Any]
    ) -> None:
        """
        TC-N-01: Normal search execution.
        
        // Given: Valid task and query
        // When: Calling search without refute option
        // Then: Executes normal search pipeline
        """
        from src.mcp.server import _handle_search
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        
        mock_state = AsyncMock()
        
        with patch("src.mcp.server.get_database", return_value=mock_db):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                with patch(
                    "src.research.pipeline.search_action",
                    return_value=mock_search_result,
                ):
                    result = await _handle_search({
                        "task_id": "task_abc123",
                        "query": "test search query",
                    })
        
        assert result["ok"] is True
        assert result["search_id"] == "s_001"
        assert result["status"] == "satisfied"
        assert len(result["claims_found"]) == 1

    @pytest.mark.asyncio
    async def test_refutation_search_execution(
        self, mock_task: dict[str, Any]
    ) -> None:
        """
        TC-N-02: Refutation search execution.
        
        // Given: Valid task and query with refute=true
        // When: Calling search
        // Then: Executes refutation search mode
        """
        from src.mcp.server import _handle_search
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        
        mock_state = AsyncMock()
        
        refutation_result = {
            "ok": True,
            "search_id": "s_002",
            "query": "test claim",
            "status": "satisfied",
            "pages_fetched": 10,
            "useful_fragments": 5,
            "harvest_rate": 0.5,
            "claims_found": [],
            "satisfaction_score": 0.7,
            "novelty_score": 0.5,
            "budget_remaining": {"pages": 35, "percent": 29},
            "is_refutation": True,
            "refutations_found": 2,
        }
        
        with patch("src.mcp.server.get_database", return_value=mock_db):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                with patch(
                    "src.research.pipeline.search_action",
                    return_value=refutation_result,
                ):
                    result = await _handle_search({
                        "task_id": "task_abc123",
                        "query": "test claim",
                        "options": {"refute": True},
                    })
        
        assert result["ok"] is True
        assert result.get("refutations_found") == 2

    @pytest.mark.asyncio
    async def test_search_with_options(self, mock_task: dict[str, Any]) -> None:
        """
        TC-N-03: Search with custom options.
        
        // Given: Search with max_pages and seek_primary options
        // When: Calling search
        // Then: Options passed to search_action
        """
        from src.mcp.server import _handle_search
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        
        mock_state = AsyncMock()
        
        captured_options = {}
        
        async def capture_search_action(task_id, query, state, options):
            captured_options.update(options or {})
            return {
                "ok": True,
                "search_id": "s_003",
                "query": query,
                "status": "partial",
                "pages_fetched": 5,
                "useful_fragments": 2,
                "harvest_rate": 0.4,
                "claims_found": [],
                "satisfaction_score": 0.3,
                "novelty_score": 0.8,
                "budget_remaining": {"pages": 50, "percent": 42},
            }
        
        with patch("src.mcp.server.get_database", return_value=mock_db):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                with patch(
                    "src.research.pipeline.search_action",
                    side_effect=capture_search_action,
                ):
                    await _handle_search({
                        "task_id": "task_abc123",
                        "query": "test query",
                        "options": {
                            "max_pages": 20,
                            "seek_primary": True,
                        },
                    })
        
        assert captured_options.get("max_pages") == 20
        assert captured_options.get("seek_primary") is True


class TestStopTaskValidation:
    """Tests for stop_task parameter validation."""

    @pytest.mark.asyncio
    async def test_missing_task_id_raises_error(self) -> None:
        """
        TC-A-04: Missing task_id for stop_task.
        
        // Given: No task_id provided
        // When: Calling stop_task
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_stop_task
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_stop_task({})
        
        assert exc_info.value.details.get("param_name") == "task_id"

    @pytest.mark.asyncio
    async def test_nonexistent_task_raises_error(self) -> None:
        """
        TC-A-05: Non-existent task_id for stop_task.
        
        // Given: task_id not in database
        // When: Calling stop_task
        // Then: Raises TaskNotFoundError
        """
        from src.mcp.server import _handle_stop_task
        from src.mcp.errors import TaskNotFoundError
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = None
        
        with patch("src.mcp.server.get_database", return_value=mock_db):
            with pytest.raises(TaskNotFoundError):
                await _handle_stop_task({"task_id": "nonexistent"})


class TestStopTaskExecution:
    """Tests for stop_task execution."""

    @pytest.fixture
    def mock_task(self) -> dict[str, Any]:
        """Create mock task data."""
        return {"id": "task_abc123"}

    @pytest.fixture
    def mock_stop_result(self) -> dict[str, Any]:
        """Create mock stop result."""
        return {
            "ok": True,
            "task_id": "task_abc123",
            "final_status": "completed",
            "summary": {
                "total_searches": 5,
                "satisfied_searches": 3,
                "total_claims": 12,
                "primary_source_ratio": 0.65,
            },
        }

    @pytest.mark.asyncio
    async def test_stop_task_default_reason(
        self, mock_task: dict[str, Any], mock_stop_result: dict[str, Any]
    ) -> None:
        """
        TC-N-04: Stop task with default reason.
        
        // Given: Valid task_id
        // When: Calling stop_task without reason
        // Then: Uses "completed" as default reason
        """
        from src.mcp.server import _handle_stop_task
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_db.execute = AsyncMock()
        
        mock_state = AsyncMock()
        
        captured_reason = None
        
        async def capture_stop_action(task_id, state, reason):
            nonlocal captured_reason
            captured_reason = reason
            return mock_stop_result
        
        with patch("src.mcp.server.get_database", return_value=mock_db):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                with patch(
                    "src.research.pipeline.stop_task_action",
                    side_effect=capture_stop_action,
                ):
                    result = await _handle_stop_task({"task_id": "task_abc123"})
        
        assert captured_reason == "completed"
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_stop_task_custom_reason(
        self, mock_task: dict[str, Any], mock_stop_result: dict[str, Any]
    ) -> None:
        """
        TC-N-05: Stop task with custom reason.
        
        // Given: Valid task_id with reason="budget_exhausted"
        // When: Calling stop_task
        // Then: Uses provided reason
        """
        from src.mcp.server import _handle_stop_task
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_db.execute = AsyncMock()
        
        mock_state = AsyncMock()
        
        captured_reason = None
        
        async def capture_stop_action(task_id, state, reason):
            nonlocal captured_reason
            captured_reason = reason
            return mock_stop_result
        
        with patch("src.mcp.server.get_database", return_value=mock_db):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                with patch(
                    "src.research.pipeline.stop_task_action",
                    side_effect=capture_stop_action,
                ):
                    await _handle_stop_task({
                        "task_id": "task_abc123",
                        "reason": "budget_exhausted",
                    })
        
        assert captured_reason == "budget_exhausted"

    @pytest.mark.asyncio
    async def test_stop_task_returns_summary(
        self, mock_task: dict[str, Any], mock_stop_result: dict[str, Any]
    ) -> None:
        """
        TC-N-06: Stop task returns summary.
        
        // Given: Completed task
        // When: Calling stop_task
        // Then: Returns summary with stats
        """
        from src.mcp.server import _handle_stop_task
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_db.execute = AsyncMock()
        
        mock_state = AsyncMock()
        
        with patch("src.mcp.server.get_database", return_value=mock_db):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                with patch(
                    "src.research.pipeline.stop_task_action",
                    return_value=mock_stop_result,
                ):
                    result = await _handle_stop_task({"task_id": "task_abc123"})
        
        assert result["ok"] is True
        assert result["final_status"] == "completed"
        assert "summary" in result
        assert result["summary"]["total_searches"] == 5
        assert result["summary"]["primary_source_ratio"] == 0.65


class TestSearchToolDefinition:
    """Tests for search tool definition."""

    def test_search_in_tools(self) -> None:
        """
        Test that search is defined in TOOLS.
        
        // Given: TOOLS list
        // When: Searching for search
        // Then: Found with correct schema
        """
        from src.mcp.server import TOOLS
        
        tool = next((t for t in TOOLS if t.name == "search"), None)
        
        assert tool is not None
        assert "task_id" in tool.inputSchema["properties"]
        assert "query" in tool.inputSchema["properties"]
        assert "options" in tool.inputSchema["properties"]
        assert set(tool.inputSchema["required"]) == {"task_id", "query"}

    def test_stop_task_in_tools(self) -> None:
        """
        Test that stop_task is defined in TOOLS.
        
        // Given: TOOLS list
        // When: Searching for stop_task
        // Then: Found with correct schema
        """
        from src.mcp.server import TOOLS
        
        tool = next((t for t in TOOLS if t.name == "stop_task"), None)
        
        assert tool is not None
        assert "task_id" in tool.inputSchema["properties"]
        assert "reason" in tool.inputSchema["properties"]
        assert tool.inputSchema["required"] == ["task_id"]

