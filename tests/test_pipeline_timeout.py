"""
Tests for SearchPipeline timeout handling (§2.1.5).

Tests verify that the pipeline times out gracefully and returns partial results.

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective | Expected Result |
|---------|---------------------|-------------|-----------------|
| PT-N-01 | exec_time < timeout | Equivalence – normal | status=satisfied |
| PT-A-01 | exec_time > timeout | Equivalence – abnormal | status=timeout |
| PT-A-02 | Exception during exec | Equivalence – error | status=failed |
| PT-B-01 | timeout=0.1s, exec=0.05s | Boundary – under | normal complete |
| PT-B-02 | timeout=0.1s, exec=0.2s | Boundary – over | timeout |
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestPipelineTimeout:
    """Tests for SearchPipeline timeout handling."""

    @pytest.fixture
    def mock_state(self):
        """Create a mock ExplorationState."""
        state = MagicMock()
        state.task_id = "test_task"
        state.original_query = "test query"
        state.record_activity = MagicMock()
        state.get_status = AsyncMock(
            return_value={
                "budget": {"pages_limit": 120, "pages_used": 10},
            }
        )
        state.register_search = MagicMock(return_value=MagicMock(id="s_test"))
        state.start_search = MagicMock()
        state.get_search = MagicMock(return_value=MagicMock(status="running"))
        state.record_page_fetch = MagicMock()
        state.record_fragment = MagicMock()
        state.record_claim = MagicMock()
        return state

    @pytest.fixture
    def mock_db(self):
        """Create a mock database."""
        db = AsyncMock()
        db.fetch_one = AsyncMock(return_value=None)
        db.fetch_all = AsyncMock(return_value=[])
        db.execute = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_execute_respects_timeout_setting(self, mock_state, mock_db):
        """
        PT-A-01: Test that execute times out when execution exceeds timeout.

        // Given: Pipeline with 0.1s timeout, execution takes 10s
        // When: execute() is called
        // Then: Returns timeout status with is_partial=True
        """
        from src.research.pipeline import SearchOptions, SearchPipeline

        pipeline = SearchPipeline("test_task", mock_state)

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10)
            return args[3]

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch.object(pipeline, "_execute_impl", side_effect=slow_execute),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(cursor_idle_timeout_seconds=0.1)),
            ),
        ):
            result = await pipeline.execute("test query", SearchOptions())

            assert result.status == "timeout"
            assert result.is_partial is True
            assert "Pipeline timeout" in result.errors[0]
            assert "0.1" in result.errors[0] or "safe stop" in result.errors[0]

    @pytest.mark.asyncio
    async def test_execute_returns_partial_result_on_timeout(self, mock_state, mock_db):
        """
        PT-A-01: Test that partial results are returned on timeout.

        // Given: Pipeline with short timeout
        // When: execute() times out
        // Then: Returns partial result with valid structure
        """
        from src.research.pipeline import SearchPipeline

        pipeline = SearchPipeline("test_task", mock_state)

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10)
            return args[3]

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch.object(pipeline, "_execute_impl", side_effect=slow_execute),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(cursor_idle_timeout_seconds=0.1)),
            ),
        ):
            result = await pipeline.execute("test query")

            assert result.search_id.startswith("s_")
            assert result.query == "test query"
            assert result.is_partial is True

    @pytest.mark.asyncio
    async def test_execute_includes_budget_on_timeout(self, mock_state, mock_db):
        """
        PT-A-01: Test that budget info is included even on timeout.

        // Given: Pipeline with budget info available
        // When: execute() times out
        // Then: budget_remaining is populated
        """
        from src.research.pipeline import SearchOptions, SearchPipeline

        pipeline = SearchPipeline("test_task", mock_state)

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10)
            return args[3]

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch.object(pipeline, "_execute_impl", side_effect=slow_execute),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(cursor_idle_timeout_seconds=0.1)),
            ),
        ):
            result = await pipeline.execute("test query", SearchOptions())

            assert "pages" in result.budget_remaining
            assert result.budget_remaining["pages"] == 110

    @pytest.mark.asyncio
    async def test_execute_completes_within_timeout(self, mock_state, mock_db):
        """
        PT-N-01: Test that fast execution completes normally.

        // Given: Pipeline with 10s timeout, execution takes <1s
        // When: execute() is called
        // Then: Returns satisfied status, is_partial=False
        """
        from src.research.pipeline import SearchOptions, SearchPipeline

        pipeline = SearchPipeline("test_task", mock_state)

        async def fast_execute(*args, **kwargs):
            result = args[3]
            result.status = "satisfied"
            result.pages_fetched = 5
            return result

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch.object(pipeline, "_execute_impl", side_effect=fast_execute),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(cursor_idle_timeout_seconds=10)),
            ),
        ):
            result = await pipeline.execute("test query", SearchOptions())

            assert result.status == "satisfied"
            assert result.is_partial is False
            assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_execute_logs_timeout_warning(self, mock_state, mock_db):
        """
        PT-A-01: Test that timeout is logged as warning.

        // Given: Pipeline that will timeout
        // When: execute() times out
        // Then: Warning is logged with timeout keyword
        """
        from src.research.pipeline import SearchOptions, SearchPipeline

        pipeline = SearchPipeline("test_task", mock_state)

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10)
            return args[3]

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch.object(pipeline, "_execute_impl", side_effect=slow_execute),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(cursor_idle_timeout_seconds=0.1)),
            ),
            patch("src.research.pipeline.logger") as mock_logger,
        ):
            await pipeline.execute("test query", SearchOptions())

            mock_logger.warning.assert_called()
            call_args = mock_logger.warning.call_args
            assert "timeout" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_execute_handles_exception_during_execution(self, mock_state, mock_db) -> None:
        """
        PT-A-02: Test that exceptions during execution are handled.

        // Given: Pipeline that raises exception during execution
        // When: execute() is called
        // Then: Returns failed status with error message
        """
        from src.research.pipeline import SearchOptions, SearchPipeline

        pipeline = SearchPipeline("test_task", mock_state)

        async def failing_execute(*args, **kwargs):
            raise RuntimeError("Simulated failure")

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch.object(pipeline, "_execute_impl", side_effect=failing_execute),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(cursor_idle_timeout_seconds=10)),
            ),
        ):
            result = await pipeline.execute("test query", SearchOptions())

            assert result.status == "failed"
            assert len(result.errors) > 0
            assert "Simulated failure" in result.errors[0]

    @pytest.mark.asyncio
    async def test_execute_boundary_just_under_timeout(self, mock_state, mock_db):
        """
        PT-B-01: Test execution just under timeout completes normally.

        // Given: Pipeline with 0.2s timeout, execution takes 0.05s
        // When: execute() is called
        // Then: Completes normally without timeout
        """
        from src.research.pipeline import SearchOptions, SearchPipeline

        pipeline = SearchPipeline("test_task", mock_state)

        async def fast_execute(*args, **kwargs):
            await asyncio.sleep(0.05)
            result = args[3]
            result.status = "satisfied"
            return result

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch.object(pipeline, "_execute_impl", side_effect=fast_execute),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(cursor_idle_timeout_seconds=0.2)),
            ),
        ):
            result = await pipeline.execute("test query", SearchOptions())

            assert result.status == "satisfied"
            assert result.is_partial is False

    @pytest.mark.asyncio
    async def test_execute_boundary_just_over_timeout(self, mock_state, mock_db):
        """
        PT-B-02: Test execution just over timeout triggers timeout.

        // Given: Pipeline with 0.1s timeout, execution takes 0.2s
        // When: execute() is called
        // Then: Times out
        """
        from src.research.pipeline import SearchOptions, SearchPipeline

        pipeline = SearchPipeline("test_task", mock_state)

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(0.2)
            return args[3]

        with (
            patch.object(pipeline, "_ensure_db", new_callable=AsyncMock),
            patch.object(pipeline, "_execute_impl", side_effect=slow_execute),
            patch(
                "src.utils.config.get_settings",
                return_value=MagicMock(task_limits=MagicMock(cursor_idle_timeout_seconds=0.1)),
            ),
        ):
            result = await pipeline.execute("test query", SearchOptions())

            assert result.status == "timeout"
            assert result.is_partial is True
