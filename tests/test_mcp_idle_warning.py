"""
Tests for MCP handlers idle warning (ADR-0002).

Tests verify that MCP handlers record activity and get_status includes idle_seconds.

NOTE: Per ADR-0010, _handle_search tests removed.
      Use queue_searches + get_status(wait=N) instead.

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective | Expected Result |
|---------|---------------------|-------------|-----------------|
| MH-N-01 | valid task_id (stop_task) | Equivalence – normal | record_activity called |
| MH-N-02 | get_status | Equivalence – normal | idle_seconds in response |
| MH-A-01 | task_id = None | Boundary – null | InvalidParamsError |
| MH-A-02 | task_id = "" | Boundary – empty | InvalidParamsError |
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMCPIdleWarning:
    """Tests for MCP handlers idle warning functionality."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create a mock database."""
        db = AsyncMock()
        db.fetch_one = AsyncMock(
            return_value={"id": "test_task", "status": "created", "query": "test query"}
        )
        db.fetch_all = AsyncMock(return_value=[])
        # Mock cursor with rowcount attribute for UPDATE operations
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 0
        db.execute = AsyncMock(return_value=mock_cursor)
        return db

    @pytest.fixture
    def mock_state(self) -> MagicMock:
        """Create a mock ExplorationState with activity tracking."""
        state = MagicMock()
        state.task_id = "test_task"
        state.original_query = "test query"
        state.record_activity = MagicMock()
        state.get_idle_seconds = MagicMock(return_value=100)
        state.get_status = AsyncMock(
            return_value={
                "ok": True,
                "task_id": "test_task",
                "task_status": "exploring",
                "searches": [],
                "metrics": {
                    "satisfied_count": 0,
                    "partial_count": 0,
                    "pending_count": 0,
                    "exhausted_count": 0,
                    "total_pages": 0,
                    "total_fragments": 0,
                    "total_claims": 0,
                    "elapsed_seconds": 0,
                },
                "budget": {
                    "budget_pages_used": 0,
                    "budget_pages_limit": 120,
                    "time_used_seconds": 0,
                    "time_limit_seconds": 1200,
                },
                "ucb_scores": None,
                "authentication_queue": None,
                "warnings": [],
                "idle_seconds": 100,
            }
        )
        return state

    @pytest.mark.asyncio
    async def test_get_status_includes_idle_seconds(
        self, mock_db: AsyncMock, mock_state: MagicMock
    ) -> None:
        """
        MH-N-02: Test that get_status response includes idle_seconds field.

        // Given: Valid task with exploration state
        // When: _handle_get_status() is called
        // Then: Response includes idle_seconds, record_activity called
        """

        async def get_state(task_id: str) -> MagicMock:
            return mock_state

        with (
            patch("src.mcp.server.get_database", return_value=mock_db),
            patch("src.mcp.server._get_exploration_state", side_effect=get_state),
        ):
            from src.mcp.server import _handle_get_status

            result = await _handle_get_status({"task_id": "test_task"})

            assert "idle_seconds" in result
            assert result["idle_seconds"] == 100
            mock_state.record_activity.assert_called_once()

    # NOTE: Per ADR-0010, test_search_records_activity removed.
    # _handle_search was removed; use queue_searches + get_status(wait=N) instead.

    @pytest.mark.asyncio
    async def test_stop_task_records_activity(
        self, mock_db: AsyncMock, mock_state: MagicMock
    ) -> None:
        """
        MH-N-01: Test that stop_task handler records activity.

        // Given: Valid task to stop
        // When: _handle_stop_task() is called
        // Then: record_activity() is called on state
        """
        mock_stop_result: dict[str, object] = {
            "ok": True,
            "task_id": "test_task",
            "final_status": "completed",
            "summary": {
                "total_searches": 5,
                "satisfied_searches": 3,
                "total_claims": 10,
                "primary_source_ratio": 0.4,
            },
        }

        async def get_state(task_id: str) -> MagicMock:
            return mock_state

        with (
            patch("src.mcp.server.get_database", return_value=mock_db),
            patch("src.mcp.server._get_exploration_state", side_effect=get_state),
            patch(
                "src.research.pipeline.stop_task_action",
                new_callable=AsyncMock,
                return_value=mock_stop_result,
            ),
            patch("src.mcp.server._clear_exploration_state"),
        ):
            from src.mcp.server import _handle_stop_task

            await _handle_stop_task({"task_id": "test_task"})

            mock_state.record_activity.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_status_shows_idle_warning_when_exceeded(self, mock_db: AsyncMock) -> None:
        """
        MH-N-02: Test that get_status shows warning when idle time exceeds timeout.

        // Given: Task with idle time > timeout
        // When: _handle_get_status() is called
        // Then: warnings list contains idle warning
        """
        mock_state = MagicMock()
        mock_state.task_id = "test_task"
        mock_state.record_activity = MagicMock()
        mock_state.get_status = AsyncMock(
            return_value={
                "ok": True,
                "task_id": "test_task",
                "task_status": "exploring",
                "searches": [],
                "metrics": {
                    "satisfied_count": 0,
                    "partial_count": 0,
                    "pending_count": 0,
                    "exhausted_count": 0,
                    "total_pages": 0,
                    "total_fragments": 0,
                    "total_claims": 0,
                    "elapsed_seconds": 0,
                },
                "budget": {
                    "budget_pages_used": 0,
                    "budget_pages_limit": 120,
                    "time_used_seconds": 0,
                    "time_limit_seconds": 1200,
                },
                "ucb_scores": None,
                "authentication_queue": None,
                "warnings": [
                    "Task idle for 350 seconds (timeout: 60s). Consider resuming or stopping."
                ],
                "idle_seconds": 350,
            }
        )

        async def get_state(task_id: str) -> MagicMock:
            return mock_state

        with (
            patch("src.mcp.server.get_database", return_value=mock_db),
            patch("src.mcp.server._get_exploration_state", side_effect=get_state),
        ):
            from src.mcp.server import _handle_get_status

            result = await _handle_get_status({"task_id": "test_task"})

            assert "warnings" in result
            assert len(result["warnings"]) > 0
            assert any("idle" in w.lower() for w in result["warnings"])
            assert result["idle_seconds"] == 350

    @pytest.mark.asyncio
    async def test_get_status_task_id_none_raises_error(self, mock_db: AsyncMock) -> None:
        """
        MH-A-01: Test that task_id=None raises InvalidParamsError.

        // Given: task_id is None
        // When: _handle_get_status() is called
        // Then: InvalidParamsError is raised with appropriate message
        """
        from src.mcp.errors import InvalidParamsError

        with patch("src.mcp.server.get_database", return_value=mock_db):
            from src.mcp.server import _handle_get_status

            with pytest.raises(InvalidParamsError) as exc_info:
                await _handle_get_status({"task_id": None})

            assert "task_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_status_task_id_empty_raises_error(self, mock_db: AsyncMock) -> None:
        """
        MH-A-02: Test that task_id="" raises InvalidParamsError.

        // Given: task_id is empty string
        // When: _handle_get_status() is called
        // Then: InvalidParamsError is raised
        """
        from src.mcp.errors import InvalidParamsError

        with patch("src.mcp.server.get_database", return_value=mock_db):
            from src.mcp.server import _handle_get_status

            with pytest.raises(InvalidParamsError) as exc_info:
                await _handle_get_status({"task_id": ""})

            assert "task_id" in str(exc_info.value).lower()

    # NOTE: Per ADR-0010, test_search_query_none_raises_error, test_search_query_empty_raises_error,
    # and test_search_task_id_none_raises_error removed.
    # _handle_search was removed; use queue_searches + get_status(wait=N) instead.
