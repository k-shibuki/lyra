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
| TC-CDP-01 | CDP responds 200 | Equivalence - normal | _check_chrome_cdp_ready True | Success |
| TC-CDP-02 | CDP connection error | Equivalence - error | _check_chrome_cdp_ready False | Failure |
| TC-CDP-03 | CDP returns non-200 | Boundary - HTTP status | _check_chrome_cdp_ready False | Non-success |
| TC-AUTO-01 | CDP already ready | Equivalence - normal | No auto-start, return True | Fast path |
| TC-AUTO-02 | CDP not ready, auto-start succeeds | Equivalence - normal | Auto-start then search | Happy path |
| TC-AUTO-03 | CDP not ready, timeout | Equivalence - error | ChromeNotReadyError | Timeout |
| TC-AUTO-04 | chrome.sh not found | Boundary - missing script | _auto_start_chrome False | Edge case |
| TC-AUTO-05 | chrome.sh timeout | Boundary - script timeout | _auto_start_chrome False | 30s limit |
| TC-SEARCH-01 | Search with CDP ready | Equivalence - normal | Search proceeds | Integration |
| TC-SEARCH-02 | Search with auto-start success | Equivalence - normal | Auto-start then search | Integration |
| TC-SEARCH-03 | Search with auto-start failure | Equivalence - error | ChromeNotReadyError | Integration |
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
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_search

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
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_search

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
        from src.mcp.errors import TaskNotFoundError
        from src.mcp.server import _handle_search

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = None

        with patch("src.mcp.server._check_chrome_cdp_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with pytest.raises(TaskNotFoundError) as exc_info:
                    await _handle_search(
                        {
                            "task_id": "nonexistent_task",
                            "query": "test query",
                        }
                    )

        assert exc_info.value.details.get("task_id") == "nonexistent_task"

    @pytest.mark.asyncio
    async def test_empty_query_raises_error(self) -> None:
        """
        TC-A-06: Empty query string.

        // Given: Empty string as query
        // When: Calling search
        // Then: Raises InvalidParamsError
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_search

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_search(
                {
                    "task_id": "task_123",
                    "query": "",
                }
            )

        assert exc_info.value.details.get("param_name") == "query"

    @pytest.mark.asyncio
    async def test_whitespace_query_raises_error(self) -> None:
        """
        TC-A-07: Whitespace-only query.

        // Given: Whitespace-only string as query
        // When: Calling search
        // Then: Raises InvalidParamsError
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_search

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_search(
                {
                    "task_id": "task_123",
                    "query": "   \t\n  ",
                }
            )

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

        with patch("src.mcp.server._check_chrome_cdp_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch("src.research.pipeline.search_action", side_effect=capture_action):
                        result = await _handle_search(
                            {
                                "task_id": "task_abc123",
                                "query": "test",
                                "options": {"max_pages": 0},
                            }
                        )

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

        with patch("src.mcp.server._check_chrome_cdp_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch("src.research.pipeline.search_action", side_effect=capture_action):
                        result = await _handle_search(
                            {
                                "task_id": "task_abc123",
                                "query": "test",
                                "options": {"max_pages": 1},
                            }
                        )

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

        with patch("src.mcp.server._check_chrome_cdp_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=mock_search_result,
                    ):
                        result = await _handle_search(
                            {
                                "task_id": "task_abc123",
                                "query": long_query,
                            }
                        )

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

        with patch("src.mcp.server._check_chrome_cdp_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=mock_search_result,
                    ):
                        result = await _handle_search(
                            {
                                "task_id": "task_abc123",
                                "query": "test search query",
                            }
                        )

        assert result["ok"] is True
        assert result["search_id"] == "s_001"
        assert result["status"] == "satisfied"
        assert len(result["claims_found"]) == 1

    @pytest.mark.asyncio
    async def test_refutation_search_execution(self, mock_task: dict[str, Any]) -> None:
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

        with patch("src.mcp.server._check_chrome_cdp_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=refutation_result,
                    ):
                        result = await _handle_search(
                            {
                                "task_id": "task_abc123",
                                "query": "test claim",
                                "options": {"refute": True},
                            }
                        )

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

        with patch("src.mcp.server._check_chrome_cdp_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        side_effect=capture_search_action,
                    ):
                        await _handle_search(
                            {
                                "task_id": "task_abc123",
                                "query": "test query",
                                "options": {
                                    "max_pages": 20,
                                    "seek_primary": True,
                                },
                            }
                        )

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
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_stop_task

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
        from src.mcp.errors import TaskNotFoundError
        from src.mcp.server import _handle_stop_task

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
                    await _handle_stop_task(
                        {
                            "task_id": "task_abc123",
                            "reason": "budget_exhausted",
                        }
                    )

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
    """Tests for Chrome CDP check function."""

    @pytest.mark.asyncio
    async def test_check_chrome_cdp_ready_success(self) -> None:
        """
        TC-CDP-01: CDP responds 200.

        // Given: CDP endpoint responds with 200
        // When: Calling _check_chrome_cdp_ready
        // Then: Returns True
        """
        from unittest.mock import MagicMock

        from src.mcp.server import _check_chrome_cdp_ready

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
        TC-CDP-02: CDP connection error.

        // Given: CDP endpoint is not accessible
        // When: Calling _check_chrome_cdp_ready
        // Then: Returns False
        """
        from unittest.mock import MagicMock

        import aiohttp

        from src.mcp.server import _check_chrome_cdp_ready

        # Create mock session that raises error on get
        mock_session = MagicMock()
        mock_session.get.side_effect = aiohttp.ClientError("Connection refused")

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            result = await _check_chrome_cdp_ready()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_chrome_cdp_ready_non_200_status(self) -> None:
        """
        TC-CDP-03: CDP returns non-200 status code.

        // Given: CDP endpoint responds with non-200 status (e.g., 500)
        // When: Calling _check_chrome_cdp_ready
        // Then: Returns False
        """
        from unittest.mock import MagicMock

        from src.mcp.server import _check_chrome_cdp_ready

        # Create a mock response with non-200 status
        mock_response = MagicMock()
        mock_response.status = 500

        # Create mock session with proper async context manager support
        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            result = await _check_chrome_cdp_ready()

        assert result is False


class TestChromeAutoStart:
    """Tests for Chrome auto-start functionality (N.5.3)."""

    @pytest.mark.asyncio
    async def test_auto_start_chrome_success(self) -> None:
        """
        TC-AUTO-04 (partial): chrome.sh executes successfully.

        // Given: chrome.sh exists and executes successfully
        // When: Calling _auto_start_chrome
        // Then: Returns True
        """
        from unittest.mock import AsyncMock, MagicMock

        from src.mcp.server import _auto_start_chrome

        # Mock subprocess that returns success
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(
                b"READY\nHost: localhost:9222",
                b"",
            )
        )

        with patch("pathlib.Path.exists", return_value=True):
            with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)):
                result = await _auto_start_chrome()

        assert result is True

    @pytest.mark.asyncio
    async def test_auto_start_chrome_script_not_found(self) -> None:
        """
        TC-AUTO-04: chrome.sh not found.

        // Given: chrome.sh does not exist
        // When: Calling _auto_start_chrome
        // Then: Returns False
        """
        from src.mcp.server import _auto_start_chrome

        with patch("pathlib.Path.exists", return_value=False):
            result = await _auto_start_chrome()

        assert result is False

    @pytest.mark.asyncio
    async def test_auto_start_chrome_script_fails(self) -> None:
        """
        TC-AUTO-04 (variant): chrome.sh fails.

        // Given: chrome.sh exists but returns non-zero exit code
        // When: Calling _auto_start_chrome
        // Then: Returns False
        """
        from unittest.mock import AsyncMock, MagicMock

        from src.mcp.server import _auto_start_chrome

        # Mock subprocess that returns failure
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(
            return_value=(
                b"",
                b"ERROR: Chrome failed to start",
            )
        )

        with patch("pathlib.Path.exists", return_value=True):
            with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)):
                result = await _auto_start_chrome()

        assert result is False

    @pytest.mark.asyncio
    async def test_auto_start_chrome_timeout(self) -> None:
        """
        TC-AUTO-05: chrome.sh timeout.

        // Given: chrome.sh runs longer than 30 seconds
        // When: Calling _auto_start_chrome
        // Then: Returns False (timeout handled)
        """
        from unittest.mock import AsyncMock, MagicMock

        from src.mcp.server import _auto_start_chrome

        # Mock subprocess that times out
        mock_process = MagicMock()
        mock_process.communicate = AsyncMock(side_effect=TimeoutError())
        mock_process.wait = AsyncMock()  # process.wait() is awaited in timeout handler

        with patch("pathlib.Path.exists", return_value=True):
            with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)):
                result = await _auto_start_chrome()

        assert result is False


class TestEnsureChromeReady:
    """Tests for _ensure_chrome_ready (auto-start integration)."""

    @pytest.mark.asyncio
    async def test_ensure_chrome_ready_already_connected(self) -> None:
        """
        TC-AUTO-01: CDP already ready.

        // Given: CDP is already connected
        // When: Calling _ensure_chrome_ready
        // Then: Returns True immediately without auto-start
        """
        from src.mcp.server import _ensure_chrome_ready

        with patch(
            "src.mcp.server._check_chrome_cdp_ready", new=AsyncMock(return_value=True)
        ) as mock_check:
            with patch("src.mcp.server._auto_start_chrome") as mock_auto_start:
                result = await _ensure_chrome_ready()

        assert result is True
        mock_check.assert_called_once()
        mock_auto_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_chrome_ready_auto_start_success(self) -> None:
        """
        TC-AUTO-02: CDP not ready, auto-start succeeds.

        // Given: CDP not connected initially, but connects after auto-start
        // When: Calling _ensure_chrome_ready
        // Then: Auto-starts Chrome and returns True
        """
        from src.mcp.server import _ensure_chrome_ready

        call_count = 0

        async def cdp_check_side_effect():
            nonlocal call_count
            call_count += 1
            # First call: not ready, subsequent calls: ready
            return call_count > 1

        with patch("src.mcp.server._check_chrome_cdp_ready", side_effect=cdp_check_side_effect):
            with patch("src.mcp.server._auto_start_chrome", new=AsyncMock(return_value=True)):
                result = await _ensure_chrome_ready(timeout=2.0, poll_interval=0.1)

        assert result is True

    @pytest.mark.asyncio
    async def test_ensure_chrome_ready_timeout(self) -> None:
        """
        TC-AUTO-03: CDP not ready, timeout.

        // Given: CDP never connects (auto-start fails or Chrome doesn't respond)
        // When: Calling _ensure_chrome_ready with short timeout
        // Then: Raises ChromeNotReadyError after timeout
        """
        from src.mcp.errors import ChromeNotReadyError
        from src.mcp.server import _ensure_chrome_ready

        with patch("src.mcp.server._check_chrome_cdp_ready", new=AsyncMock(return_value=False)):
            with patch("src.mcp.server._auto_start_chrome", new=AsyncMock(return_value=False)):
                with pytest.raises(ChromeNotReadyError) as exc_info:
                    await _ensure_chrome_ready(timeout=0.5, poll_interval=0.1)

        error_dict = exc_info.value.to_dict()
        assert error_dict["error_code"] == "CHROME_NOT_READY"
        assert "start" in error_dict["error"]
        # Note: details may not be present if not in Podman environment
        if "details" in error_dict:
            assert error_dict["details"]["auto_start_attempted"] is True


class TestSearchWithAutoStart:
    """Integration tests for search with Chrome auto-start."""

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
    async def test_search_with_cdp_ready(
        self, mock_task: dict[str, Any], mock_search_result: dict[str, Any]
    ) -> None:
        """
        TC-SEARCH-01: Search with CDP ready.

        // Given: Chrome CDP is already connected
        // When: Calling _handle_search
        // Then: Search proceeds without auto-start
        """
        from src.mcp.server import _handle_search

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()

        with patch("src.mcp.server._ensure_chrome_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=mock_search_result,
                    ):
                        result = await _handle_search(
                            {
                                "task_id": "task_abc123",
                                "query": "test query",
                            }
                        )

        assert result["ok"] is True
        assert result["search_id"] == "s_001"

    @pytest.mark.asyncio
    async def test_search_with_auto_start_success(
        self, mock_task: dict[str, Any], mock_search_result: dict[str, Any]
    ) -> None:
        """
        TC-SEARCH-02: Search with auto-start success.

        // Given: Chrome CDP not connected, but auto-start succeeds
        // When: Calling _handle_search
        // Then: Auto-starts Chrome then proceeds with search
        """
        from src.mcp.server import _handle_search

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()

        ensure_called = False

        async def mock_ensure():
            nonlocal ensure_called
            ensure_called = True
            return True

        with patch("src.mcp.server._ensure_chrome_ready", side_effect=mock_ensure):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=mock_search_result,
                    ):
                        result = await _handle_search(
                            {
                                "task_id": "task_abc123",
                                "query": "test query",
                            }
                        )

        assert ensure_called is True
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_search_with_auto_start_failure(self) -> None:
        """
        TC-SEARCH-03: Search with auto-start failure.

        // Given: Chrome CDP not connected and auto-start fails
        // When: Calling _handle_search
        // Then: Raises ChromeNotReadyError
        """
        from src.mcp.errors import ChromeNotReadyError
        from src.mcp.server import _handle_search

        with patch("src.mcp.server._ensure_chrome_ready", side_effect=ChromeNotReadyError()):
            with pytest.raises(ChromeNotReadyError) as exc_info:
                await _handle_search(
                    {
                        "task_id": "task_123",
                        "query": "test query",
                    }
                )

        error_dict = exc_info.value.to_dict()
        assert error_dict["error_code"] == "CHROME_NOT_READY"


class TestSearchErrorHandling:
    """Tests for search error code handling.

    ## Test Perspectives Table (Error Handling)

    | Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
    |---------|---------------------|---------------------------------------|-----------------|-------|
    | TC-ERR-01 | Search returns PARSER_NOT_AVAILABLE | Equivalence - error | ParserNotAvailableError raised | Engine has no parser |
    | TC-ERR-02 | Search returns SERP_SEARCH_FAILED | Equivalence - error | SerpSearchFailedError raised | SERP search fails |
    | TC-ERR-03 | Search returns ALL_FETCHES_FAILED | Equivalence - error | AllFetchesFailedError raised | All fetches timeout |
    | TC-ERR-04 | Search returns unknown error code | Boundary - unknown | PipelineError raised | Fallback error |
    | TC-ERR-05 | ParserNotAvailable details | Equivalence - detail | Contains engine and available_engines | Error details |
    | TC-ERR-06 | AllFetchesFailed details | Equivalence - detail | Contains total_urls and auth_blocked | Error details |
    """

    @pytest.fixture
    def mock_task(self) -> dict[str, Any]:
        """Mock task database record."""
        return {"id": "task_err_test", "status": "running"}

    @pytest.mark.asyncio
    async def test_parser_not_available_error(self, mock_task: dict[str, Any]) -> None:
        """
        TC-ERR-01: Search returns PARSER_NOT_AVAILABLE error code.

        // Given: Search pipeline returns result with error_code=PARSER_NOT_AVAILABLE
        // When: _handle_search processes the result
        // Then: Raises ParserNotAvailableError with proper details
        """
        from src.mcp.errors import ParserNotAvailableError
        from src.mcp.server import _handle_search

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()

        error_result = {
            "ok": False,
            "search_id": "s_err001",
            "status": "failed",
            "error_code": "PARSER_NOT_AVAILABLE",
            "error_details": {
                "engine": "wikipedia",
                "available_engines": ["duckduckgo", "mojeek", "brave"],
            },
        }

        with patch("src.mcp.server._ensure_chrome_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=error_result,
                    ):
                        with pytest.raises(ParserNotAvailableError) as exc_info:
                            await _handle_search(
                                {
                                    "task_id": "task_err_test",
                                    "query": "test query",
                                }
                            )

        error_dict = exc_info.value.to_dict()
        assert error_dict["error_code"] == "PARSER_NOT_AVAILABLE"
        assert error_dict["details"]["engine"] == "wikipedia"
        assert "duckduckgo" in error_dict["details"]["available_engines"]

    @pytest.mark.asyncio
    async def test_serp_search_failed_error(self, mock_task: dict[str, Any]) -> None:
        """
        TC-ERR-02: Search returns SERP_SEARCH_FAILED error code.

        // Given: Search pipeline returns result with error_code=SERP_SEARCH_FAILED
        // When: _handle_search processes the result
        // Then: Raises SerpSearchFailedError
        """
        from src.mcp.errors import SerpSearchFailedError
        from src.mcp.server import _handle_search

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()

        error_result = {
            "ok": False,
            "search_id": "s_err002",
            "status": "failed",
            "error_code": "SERP_SEARCH_FAILED",
            "error_details": {
                "query": "test query",
                "provider_error": "Network timeout",
            },
        }

        with patch("src.mcp.server._ensure_chrome_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=error_result,
                    ):
                        with pytest.raises(SerpSearchFailedError) as exc_info:
                            await _handle_search(
                                {
                                    "task_id": "task_err_test",
                                    "query": "test query",
                                }
                            )

        error_dict = exc_info.value.to_dict()
        assert error_dict["error_code"] == "SERP_SEARCH_FAILED"

    @pytest.mark.asyncio
    async def test_all_fetches_failed_error(self, mock_task: dict[str, Any]) -> None:
        """
        TC-ERR-03: Search returns ALL_FETCHES_FAILED error code.

        // Given: Search pipeline returns result with error_code=ALL_FETCHES_FAILED
        // When: _handle_search processes the result
        // Then: Raises AllFetchesFailedError with proper details
        """
        from src.mcp.errors import AllFetchesFailedError
        from src.mcp.server import _handle_search

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()

        error_result = {
            "ok": False,
            "search_id": "s_err003",
            "status": "failed",
            "error_code": "ALL_FETCHES_FAILED",
            "error_details": {
                "total_urls": 5,
                "auth_blocked_count": 2,
            },
        }

        with patch("src.mcp.server._ensure_chrome_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=error_result,
                    ):
                        with pytest.raises(AllFetchesFailedError) as exc_info:
                            await _handle_search(
                                {
                                    "task_id": "task_err_test",
                                    "query": "test query",
                                }
                            )

        error_dict = exc_info.value.to_dict()
        assert error_dict["error_code"] == "ALL_FETCHES_FAILED"
        assert error_dict["details"]["total_urls"] == 5
        assert error_dict["details"]["auth_blocked_count"] == 2

    @pytest.mark.asyncio
    async def test_unknown_error_code_fallback(self, mock_task: dict[str, Any]) -> None:
        """
        TC-ERR-04: Search returns unknown error code.

        // Given: Search pipeline returns result with unknown error_code
        // When: _handle_search processes the result
        // Then: Raises PipelineError as fallback
        """
        from src.mcp.errors import PipelineError
        from src.mcp.server import _handle_search

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()

        error_result = {
            "ok": False,
            "search_id": "s_err004",
            "status": "failed",
            "error_code": "UNKNOWN_ERROR",
            "error_details": {},
        }

        with patch("src.mcp.server._ensure_chrome_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=error_result,
                    ):
                        with pytest.raises(PipelineError) as exc_info:
                            await _handle_search(
                                {
                                    "task_id": "task_err_test",
                                    "query": "test query",
                                }
                            )

        error_dict = exc_info.value.to_dict()
        assert error_dict["error_code"] == "PIPELINE_ERROR"
        assert "UNKNOWN_ERROR" in error_dict["error"]

    @pytest.mark.asyncio
    async def test_successful_search_no_error(self, mock_task: dict[str, Any]) -> None:
        """
        TC-ERR-05: Successful search returns no error.

        // Given: Search pipeline returns successful result (no error_code)
        // When: _handle_search processes the result
        // Then: Returns result without raising exception
        """
        from src.mcp.server import _handle_search

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task
        mock_state = AsyncMock()

        success_result = {
            "ok": True,
            "search_id": "s_success",
            "status": "satisfied",
            "pages_fetched": 5,
            "claims_found": [{"id": "c_001", "text": "Test claim"}],
        }

        with patch("src.mcp.server._ensure_chrome_ready", new=AsyncMock(return_value=True)):
            with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
                with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                    with patch(
                        "src.research.pipeline.search_action",
                        return_value=success_result,
                    ):
                        result = await _handle_search(
                            {
                                "task_id": "task_err_test",
                                "query": "test query",
                            }
                        )

        assert result["ok"] is True
        assert result["search_id"] == "s_success"
        assert "error_code" not in result


class TestSearchResultErrorCodes:
    """Tests for SearchResult error code propagation.

    ## Test Perspectives Table (Result Error Codes)

    | Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
    |---------|---------------------|---------------------------------------|-----------------|-------|
    | TC-RES-01 | SearchResult with error_code | Equivalence - normal | to_dict includes error_code | Propagation |
    | TC-RES-02 | SearchResult without error_code | Equivalence - normal | to_dict has ok=True | No error |
    | TC-RES-03 | SearchResult with errors list only | Boundary - legacy | ok=False but no error_code | Backward compat |
    """

    def test_executor_search_result_with_error_code(self) -> None:
        """
        TC-RES-01: SearchResult with error_code set.

        // Given: SearchResult has error_code and error_details
        // When: to_dict() is called
        // Then: Dictionary includes error_code and error_details, ok=False
        """
        from src.research.executor import SearchResult

        result = SearchResult(
            search_id="s_test",
            status="failed",
            error_code="PARSER_NOT_AVAILABLE",
            error_details={"engine": "wikipedia"},
        )

        result_dict = result.to_dict()

        assert result_dict["ok"] is False
        assert result_dict["error_code"] == "PARSER_NOT_AVAILABLE"
        assert result_dict["error_details"]["engine"] == "wikipedia"

    def test_executor_search_result_without_error(self) -> None:
        """
        TC-RES-02: SearchResult without error_code.

        // Given: SearchResult has no error_code and no errors
        // When: to_dict() is called
        // Then: Dictionary has ok=True, no error_code
        """
        from src.research.executor import SearchResult

        result = SearchResult(
            search_id="s_test",
            status="satisfied",
            pages_fetched=5,
        )

        result_dict = result.to_dict()

        assert result_dict["ok"] is True
        assert "error_code" not in result_dict
        assert "error_details" not in result_dict

    def test_executor_search_result_with_errors_list_only(self) -> None:
        """
        TC-RES-03: SearchResult with errors list but no error_code.

        // Given: SearchResult has errors list but no error_code
        // When: to_dict() is called
        // Then: Dictionary has ok=False, errors present, no error_code
        """
        from src.research.executor import SearchResult

        result = SearchResult(
            search_id="s_test",
            status="partial",
            errors=["Some error occurred"],
        )

        result_dict = result.to_dict()

        assert result_dict["ok"] is False
        assert "Some error occurred" in result_dict["errors"]
        assert "error_code" not in result_dict

    def test_pipeline_search_result_with_error_code(self) -> None:
        """
        TC-RES-04: Pipeline SearchResult with error_code set.

        // Given: Pipeline SearchResult has error_code and error_details
        // When: to_dict() is called
        // Then: Dictionary includes error_code and error_details
        """
        from src.research.pipeline import SearchResult

        result = SearchResult(
            search_id="s_pipe_test",
            query="test query",
            status="failed",
            error_code="ALL_FETCHES_FAILED",
            error_details={"total_urls": 3},
        )

        result_dict = result.to_dict()

        assert result_dict["ok"] is False
        assert result_dict["error_code"] == "ALL_FETCHES_FAILED"
        assert result_dict["error_details"]["total_urls"] == 3


class TestSearchApiExceptions:
    """Tests for search_api.py exception raising.

    ## Test Perspectives Table (Search API Exceptions)

    | Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
    |---------|---------------------|---------------------------------------|-----------------|-------|
    | TC-API-01 | Provider returns parser error | Equivalence - error | ParserNotAvailableSearchError | Exception type |
    | TC-API-02 | Provider returns generic error | Equivalence - error | SerpSearchError | Exception type |
    | TC-API-03 | SearchError has correct attributes | Equivalence - detail | error_type, engine, details | Attributes |
    """

    def test_parser_not_available_search_error(self) -> None:
        """
        TC-API-01: ParserNotAvailableSearchError attributes.

        // Given: Creating ParserNotAvailableSearchError
        // When: Accessing attributes
        // Then: Has correct error_type, engine, and available_engines
        """
        from src.search.search_api import ParserNotAvailableSearchError

        error = ParserNotAvailableSearchError(
            engine="wikipedia",
            available_engines=["duckduckgo", "mojeek"],
        )

        assert error.error_type == "parser_not_available"
        assert error.engine == "wikipedia"
        assert error.available_engines == ["duckduckgo", "mojeek"]
        assert "wikipedia" in str(error)

    def test_serp_search_error_attributes(self) -> None:
        """
        TC-API-02: SerpSearchError attributes.

        // Given: Creating SerpSearchError
        // When: Accessing attributes
        // Then: Has correct error_type, query, and provider_error
        """
        from src.search.search_api import SerpSearchError

        error = SerpSearchError(
            message="Search failed",
            query="test query",
            provider_error="Connection timeout",
        )

        assert error.error_type == "serp_search_failed"
        assert error.query == "test query"
        assert error.provider_error == "Connection timeout"

    def test_base_search_error(self) -> None:
        """
        TC-API-03: Base SearchError attributes.

        // Given: Creating base SearchError
        // When: Accessing attributes
        // Then: Has correct message, error_type, and details
        """
        from src.search.search_api import SearchError

        error = SearchError(
            message="Test error",
            error_type="test_error",
            query="some query",
            engine="test_engine",
            details={"key": "value"},
        )

        assert error.message == "Test error"
        assert error.error_type == "test_error"
        assert error.query == "some query"
        assert error.engine == "test_engine"
        assert error.details["key"] == "value"


class TestMCPErrorClasses:
    """Tests for new MCP error classes.

    ## Test Perspectives Table (MCP Error Classes)

    | Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
    |---------|---------------------|---------------------------------------|-----------------|-------|
    | TC-MCP-01 | ParserNotAvailableError | Equivalence - normal | Correct code and details | Error class |
    | TC-MCP-02 | SerpSearchFailedError | Equivalence - normal | Correct code and details | Error class |
    | TC-MCP-03 | AllFetchesFailedError | Equivalence - normal | Correct code and details | Error class |
    | TC-MCP-04 | Error codes in enum | Boundary - enum | All new codes defined | Enum completeness |
    """

    def test_parser_not_available_error(self) -> None:
        """
        TC-MCP-01: ParserNotAvailableError structure.

        // Given: Creating ParserNotAvailableError
        // When: Converting to dict
        // Then: Has correct error_code, message, and details
        """
        from src.mcp.errors import ParserNotAvailableError

        error = ParserNotAvailableError(
            engine="arxiv",
            available_engines=["duckduckgo", "brave"],
        )

        error_dict = error.to_dict()

        assert error_dict["ok"] is False
        assert error_dict["error_code"] == "PARSER_NOT_AVAILABLE"
        assert "arxiv" in error_dict["error"]
        assert error_dict["details"]["engine"] == "arxiv"
        assert "duckduckgo" in error_dict["details"]["available_engines"]

    def test_serp_search_failed_error(self) -> None:
        """
        TC-MCP-02: SerpSearchFailedError structure.

        // Given: Creating SerpSearchFailedError
        // When: Converting to dict
        // Then: Has correct error_code, message, and details
        """
        from src.mcp.errors import SerpSearchFailedError

        error = SerpSearchFailedError(
            message="SERP search failed: timeout",
            query="test query",
            attempted_engines=["duckduckgo", "mojeek"],
            error_details="Connection timeout",
        )

        error_dict = error.to_dict()

        assert error_dict["ok"] is False
        assert error_dict["error_code"] == "SERP_SEARCH_FAILED"
        assert "timeout" in error_dict["error"]
        assert error_dict["details"]["query"] == "test query"
        assert "duckduckgo" in error_dict["details"]["attempted_engines"]

    def test_all_fetches_failed_error(self) -> None:
        """
        TC-MCP-03: AllFetchesFailedError structure.

        // Given: Creating AllFetchesFailedError
        // When: Converting to dict
        // Then: Has correct error_code, message, and details
        """
        from src.mcp.errors import AllFetchesFailedError

        error = AllFetchesFailedError(
            total_urls=10,
            timeout_count=5,
            auth_blocked_count=3,
            error_count=2,
        )

        error_dict = error.to_dict()

        assert error_dict["ok"] is False
        assert error_dict["error_code"] == "ALL_FETCHES_FAILED"
        assert "10" in error_dict["error"]
        assert error_dict["details"]["total_urls"] == 10
        assert error_dict["details"]["timeout_count"] == 5
        assert error_dict["details"]["auth_blocked_count"] == 3

    def test_error_codes_defined_in_enum(self) -> None:
        """
        TC-MCP-04: All new error codes defined in MCPErrorCode enum.

        // Given: MCPErrorCode enum
        // When: Checking for new error codes
        // Then: All new codes are defined
        """
        from src.mcp.errors import MCPErrorCode

        # Verify new error codes exist
        assert hasattr(MCPErrorCode, "PARSER_NOT_AVAILABLE")
        assert hasattr(MCPErrorCode, "SERP_SEARCH_FAILED")
        assert hasattr(MCPErrorCode, "ALL_FETCHES_FAILED")

        # Verify values
        assert MCPErrorCode.PARSER_NOT_AVAILABLE.value == "PARSER_NOT_AVAILABLE"
        assert MCPErrorCode.SERP_SEARCH_FAILED.value == "SERP_SEARCH_FAILED"
        assert MCPErrorCode.ALL_FETCHES_FAILED.value == "ALL_FETCHES_FAILED"
