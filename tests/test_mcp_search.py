"""Tests for search and stop_task MCP tools.

Tests the search pipeline and task stopping per §3.2.1.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-A-01 | Missing task_id | Equivalence – error | InvalidParamsError with param_name=task_id | Required param |
| TC-A-02 | Missing query | Equivalence – error | InvalidParamsError with param_name=query | Required param |
| TC-A-03 | Non-existent task_id | Equivalence – error | TaskNotFoundError with task_id | DB lookup failure |
| TC-A-04 | Missing task_id for stop_task | Equivalence – error | InvalidParamsError | Required param |
| TC-A-05 | Non-existent task for stop_task | Equivalence – error | TaskNotFoundError | DB lookup failure |
| TC-A-06 | Empty query string | Boundary – empty | InvalidParamsError | Empty string validation |
| TC-A-07 | Whitespace-only query | Boundary – whitespace | InvalidParamsError | Whitespace validation |
| TC-N-01 | Valid task + query | Equivalence – normal | Search executes, returns result | Normal search |
| TC-N-02 | Valid task + query + refute=true | Equivalence – normal | Refutation search executes | Refutation mode |
| TC-N-03 | Search with custom options | Equivalence – normal | Options passed to action | Custom options |
| TC-N-04 | stop_task without reason | Equivalence – normal | Default reason="completed" | Default value |
| TC-N-05 | stop_task with custom reason | Equivalence – normal | Custom reason passed | Custom value |
| TC-N-06 | stop_task returns summary | Equivalence – normal | Summary with stats | Return structure |
| TC-B-01 | max_pages=0 | Boundary – min | Accepts 0 (immediate return) | Zero boundary |
| TC-B-02 | max_pages=1 | Boundary – min+1 | Accepts 1 page | Minimal fetch |
| TC-A-08 | CDP not available | Equivalence - error | ChromeNotReadyError | N.5 pre-check |
| TC-A-09 | CDP not available (Podman) | Equivalence - error | ChromeNotReadyError with socat hint | N.5 Podman |
| TC-N-07 | CDP available | Equivalence - normal | Search proceeds normally | N.5 pre-check |
| TC-CDP-01 | CDP responds 200 | Equivalence - normal | _check_chrome_cdp_ready True | Success |
| TC-CDP-02 | CDP connection error | Equivalence - error | _check_chrome_cdp_ready False | Failure |
| TC-CDP-03 | .dockerenv exists | Boundary - podman | _is_podman_environment True | Docker |
| TC-CDP-04 | container=podman env | Boundary - podman | _is_podman_environment True | Env var |
| TC-CDP-05 | Native environment | Boundary - native | _is_podman_environment False | No container |
| TC-B-03 | Very long query (4000 chars) | Boundary – max | Accepts long query | §4.4.1 input limit |
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
        
        with patch("src.mcp.server._check_chrome_cdp_ready", return_value=True):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with pytest.raises(TaskNotFoundError) as exc_info:
                    await _handle_search({
                        "task_id": "nonexistent_task",
                        "query": "test query",
                    })
        
        assert exc_info.value.details.get("task_id") == "nonexistent_task"

    @pytest.mark.asyncio
    async def test_empty_query_raises_error(self) -> None:
        """
        TC-A-06: Empty query string.
        
        // Given: Empty string as query
        // When: Calling search
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_search
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_search({
                "task_id": "task_123",
                "query": "",
            })
        
        assert exc_info.value.details.get("param_name") == "query"

    @pytest.mark.asyncio
    async def test_whitespace_query_raises_error(self) -> None:
        """
        TC-A-07: Whitespace-only query.
        
        // Given: Whitespace-only string as query
        // When: Calling search
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_search
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_search({
                "task_id": "task_123",
                "query": "   \t\n  ",
            })
        
        assert exc_info.value.details.get("param_name") == "query"


class TestSearchBoundaryValues:
    """Tests for search boundary values."""

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
            "query": "test",
            "status": "partial",
            "pages_fetched": 0,
            "useful_fragments": 0,
            "harvest_rate": 0.0,
            "claims_found": [],
            "satisfaction_score": 0.0,
            "novelty_score": 0.0,
            "budget_remaining": {"pages": 100, "percent": 100},
        }

    @pytest.mark.asyncio
    async def test_max_pages_zero(
        self, mock_task: dict[str, Any], mock_search_result: dict[str, Any]
    ) -> None:
        """
        TC-B-01: max_pages=0 boundary.
        
        // Given: max_pages=0
        // When: Calling search
        // Then: Accepts and passes 0 to action (immediate return)
        """
        from src.mcp.server import _handle_search
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()
        
        captured_options = {}
        
        async def capture_action(task_id, query, state, options):
            captured_options.update(options or {})
            return mock_search_result
        
        with patch("src.mcp.server._check_chrome_cdp_ready", return_value=True):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch("src.research.pipeline.search_action", side_effect=capture_action):
                        result = await _handle_search({
                            "task_id": "task_abc123",
                            "query": "test",
                            "options": {"max_pages": 0},
                        })
        
        assert result["ok"] is True
        assert captured_options.get("max_pages") == 0

    @pytest.mark.asyncio
    async def test_max_pages_one(
        self, mock_task: dict[str, Any], mock_search_result: dict[str, Any]
    ) -> None:
        """
        TC-B-02: max_pages=1 boundary (minimum practical value).
        
        // Given: max_pages=1
        // When: Calling search
        // Then: Accepts minimal page count
        """
        from src.mcp.server import _handle_search
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()
        
        captured_options = {}
        
        async def capture_action(task_id, query, state, options):
            captured_options.update(options or {})
            return mock_search_result
        
        with patch("src.mcp.server._check_chrome_cdp_ready", return_value=True):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch("src.research.pipeline.search_action", side_effect=capture_action):
                        result = await _handle_search({
                            "task_id": "task_abc123",
                            "query": "test",
                            "options": {"max_pages": 1},
                        })
        
        assert result["ok"] is True
        assert captured_options.get("max_pages") == 1

    @pytest.mark.asyncio
    async def test_long_query_at_limit(
        self, mock_task: dict[str, Any], mock_search_result: dict[str, Any]
    ) -> None:
        """
        TC-B-03: Very long query at input limit (4000 chars per §4.4.1).
        
        // Given: Query of 4000 characters
        // When: Calling search
        // Then: Accepts the query
        """
        from src.mcp.server import _handle_search
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()
        
        long_query = "a" * 4000  # Max input length per §4.4.1
        
        with patch("src.mcp.server._check_chrome_cdp_ready", return_value=True):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=mock_search_result,
                    ):
                        result = await _handle_search({
                            "task_id": "task_abc123",
                            "query": long_query,
                        })
        
        assert result["ok"] is True


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
        
        with patch("src.mcp.server._check_chrome_cdp_ready", return_value=True):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
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
        
        with patch("src.mcp.server._check_chrome_cdp_ready", return_value=True):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
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
        
        with patch("src.mcp.server._check_chrome_cdp_ready", return_value=True):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
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
        
        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
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
        
        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
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
        
        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
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
        
        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
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


class TestChromeCDPCheck:
    """Tests for Chrome CDP pre-check (N.5 implementation)."""

    @pytest.mark.asyncio
    async def test_cdp_not_available_raises_error(self) -> None:
        """
        TC-A-08: CDP not available raises ChromeNotReadyError.
        
        // Given: Chrome CDP endpoint is not accessible
        // When: Calling _handle_search
        // Then: Raises ChromeNotReadyError before reaching pipeline
        """
        from src.mcp.server import _handle_search
        from src.mcp.errors import ChromeNotReadyError
        
        # Mock CDP check to return False (not available)
        with patch("src.mcp.server._check_chrome_cdp_ready", return_value=False):
            with patch("src.mcp.server._is_podman_environment", return_value=False):
                with pytest.raises(ChromeNotReadyError) as exc_info:
                    await _handle_search({
                        "task_id": "task_123",
                        "query": "test query",
                    })
        
        error_dict = exc_info.value.to_dict()
        assert error_dict["error_code"] == "CHROME_NOT_READY"
        assert "./scripts/chrome.sh start" in error_dict["error"]

    @pytest.mark.asyncio
    async def test_cdp_not_available_in_podman_includes_hint(self) -> None:
        """
        TC-A-09: CDP not available in Podman includes socat hint.
        
        // Given: CDP not available AND running in Podman environment
        // When: Calling _handle_search
        // Then: Raises ChromeNotReadyError with Podman/socat hint
        """
        from src.mcp.server import _handle_search
        from src.mcp.errors import ChromeNotReadyError
        
        # Mock CDP check to return False and Podman check to return True
        with patch("src.mcp.server._check_chrome_cdp_ready", return_value=False):
            with patch("src.mcp.server._is_podman_environment", return_value=True):
                with pytest.raises(ChromeNotReadyError) as exc_info:
                    await _handle_search({
                        "task_id": "task_123",
                        "query": "test query",
                    })
        
        error_dict = exc_info.value.to_dict()
        assert error_dict["error_code"] == "CHROME_NOT_READY"
        assert "details" in error_dict
        assert "hint" in error_dict["details"]
        assert "socat" in error_dict["details"]["hint"]
        assert "WSL2" in error_dict["details"]["hint"]

    @pytest.mark.asyncio
    async def test_cdp_available_proceeds_to_search(self) -> None:
        """
        TC-N-07: CDP available allows search to proceed.
        
        // Given: Chrome CDP endpoint is accessible
        // When: Calling _handle_search with valid params
        // Then: Search proceeds (no ChromeNotReadyError)
        """
        from src.mcp.server import _handle_search
        
        mock_task = {"id": "task_abc123"}
        mock_search_result = {
            "ok": True,
            "search_id": "s_001",
            "query": "test",
            "status": "partial",
            "pages_fetched": 0,
            "useful_fragments": 0,
            "harvest_rate": 0.0,
            "claims_found": [],
            "satisfaction_score": 0.0,
            "novelty_score": 0.0,
            "budget_remaining": {"pages": 100, "percent": 100},
        }
        
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()
        
        # Mock CDP check to return True (available)
        with patch("src.mcp.server._check_chrome_cdp_ready", return_value=True):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=mock_search_result,
                    ):
                        result = await _handle_search({
                            "task_id": "task_abc123",
                            "query": "test query",
                        })
        
        assert result["ok"] is True
        assert result["search_id"] == "s_001"

    @pytest.mark.asyncio
    async def test_check_chrome_cdp_ready_success(self) -> None:
        """
        Test _check_chrome_cdp_ready returns True when CDP responds.
        
        // Given: CDP endpoint responds with 200
        // When: Calling _check_chrome_cdp_ready
        // Then: Returns True
        """
        from src.mcp.server import _check_chrome_cdp_ready
        from unittest.mock import MagicMock
        
        # Create a mock response that works with async context manager
        mock_response = MagicMock()
        mock_response.status = 200
        
        # Create mock session with proper async context manager support
        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
        
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        
        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            result = await _check_chrome_cdp_ready()
        
        assert result is True

    @pytest.mark.asyncio
    async def test_check_chrome_cdp_ready_failure(self) -> None:
        """
        Test _check_chrome_cdp_ready returns False on connection error.
        
        // Given: CDP endpoint is not accessible
        // When: Calling _check_chrome_cdp_ready
        // Then: Returns False
        """
        from src.mcp.server import _check_chrome_cdp_ready
        from unittest.mock import MagicMock
        import aiohttp
        
        # Create mock session that raises error on get
        mock_session = MagicMock()
        mock_session.get.side_effect = aiohttp.ClientError("Connection refused")
        
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        
        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            result = await _check_chrome_cdp_ready()
        
        assert result is False

    def test_is_podman_environment_with_dockerenv(self) -> None:
        """
        Test _is_podman_environment detects .dockerenv.
        
        // Given: /.dockerenv exists
        // When: Calling _is_podman_environment
        // Then: Returns True
        """
        from src.mcp.server import _is_podman_environment
        import os
        
        with patch("os.path.exists", return_value=True):
            with patch.dict(os.environ, {}, clear=True):
                result = _is_podman_environment()
        
        assert result is True

    def test_is_podman_environment_with_container_env(self) -> None:
        """
        Test _is_podman_environment detects container env var.
        
        // Given: container=podman env var set
        // When: Calling _is_podman_environment
        // Then: Returns True
        """
        from src.mcp.server import _is_podman_environment
        import os
        
        with patch("os.path.exists", return_value=False):
            with patch.dict(os.environ, {"container": "podman"}):
                result = _is_podman_environment()
        
        assert result is True

    def test_is_podman_environment_native(self) -> None:
        """
        Test _is_podman_environment returns False in native env.
        
        // Given: No .dockerenv and no container env var
        // When: Calling _is_podman_environment
        // Then: Returns False
        """
        from src.mcp.server import _is_podman_environment
        import os
        
        with patch("os.path.exists", return_value=False):
            with patch.dict(os.environ, {}, clear=True):
                result = _is_podman_environment()
        
        assert result is False

