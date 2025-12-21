"""
Tests for ExplorationState activity tracking (§2.1.5).

Tests verify that activity timestamps are recorded and idle time is calculated correctly.

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective | Expected Result |
|---------|---------------------|-------------|-----------------|
| AT-N-01 | Initial state | Equivalence – normal | _last_activity_at > 0 |
| AT-N-02 | record_activity() | Equivalence – normal | timestamp updated |
| AT-N-03 | get_idle_seconds() | Equivalence – normal | returns elapsed time |
| AT-B-01 | idle = 0 (immediate) | Boundary – min | idle_seconds ≈ 0 |
| AT-B-02 | idle = timeout - 1 | Boundary – just under | no warning |
| AT-B-03 | idle = timeout | Boundary – exact | warning added |
| AT-B-04 | idle = timeout + 1 | Boundary – just over | warning added |
"""

import time
from unittest.mock import AsyncMock, patch

import pytest


class TestActivityTracking:
    """Tests for ExplorationState activity tracking."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create a mock database."""
        db = AsyncMock()
        db.fetch_one = AsyncMock(
            return_value={"id": "test_task", "status": "created", "query": "test"}
        )
        db.fetch_all = AsyncMock(return_value=[])
        db.execute = AsyncMock()
        return db

    def test_initial_activity_timestamp(self) -> None:
        """
        AT-N-01: Test that activity timestamp is set on initialization.

        // Given: New ExplorationState
        // When: State is created
        // Then: _last_activity_at is set to current time
        """
        with patch("src.research.state.get_database", new_callable=AsyncMock):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")

            assert hasattr(state, "_last_activity_at")
            assert state._last_activity_at > 0
            assert time.time() - state._last_activity_at < 1

    def test_record_activity_updates_timestamp(self) -> None:
        """
        AT-N-02: Test that record_activity updates the timestamp.

        // Given: ExplorationState with initial timestamp
        // When: record_activity() is called after delay
        // Then: Timestamp is updated to newer value
        """
        with patch("src.research.state.get_database", new_callable=AsyncMock):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")

            initial_time = state._last_activity_at
            time.sleep(0.01)
            state.record_activity()

            assert state._last_activity_at > initial_time

    def test_get_idle_seconds_returns_elapsed_time(self) -> None:
        """
        AT-N-03: Test that get_idle_seconds returns correct elapsed time.

        // Given: ExplorationState with activity recorded
        // When: get_idle_seconds() called after 50ms
        // Then: Returns approximately 0.05 seconds
        """
        with patch("src.research.state.get_database", new_callable=AsyncMock):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")

            state.record_activity()
            time.sleep(0.05)
            idle = state.get_idle_seconds()

            assert idle >= 0.05
            assert idle < 1

    def test_get_idle_seconds_boundary_zero(self) -> None:
        """
        AT-B-01: Test idle_seconds is approximately 0 immediately after activity.

        // Given: ExplorationState
        // When: get_idle_seconds() called immediately after record_activity()
        // Then: Returns value close to 0
        """
        with patch("src.research.state.get_database", new_callable=AsyncMock):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")
            state.record_activity()
            idle = state.get_idle_seconds()

            assert idle >= 0
            assert idle < 0.01  # Less than 10ms

    def test_get_idle_seconds_resets_after_record_activity(self) -> None:
        """
        AT-N-02: Test that idle seconds reset after recording activity.

        // Given: ExplorationState with accumulated idle time
        // When: record_activity() is called
        // Then: get_idle_seconds() returns much smaller value
        """
        with patch("src.research.state.get_database", new_callable=AsyncMock):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")

            time.sleep(0.1)
            idle_before = state.get_idle_seconds()
            assert idle_before >= 0.1

            state.record_activity()
            idle_after = state.get_idle_seconds()
            assert idle_after < idle_before
            assert idle_after < 0.05

    @pytest.mark.asyncio
    async def test_get_status_includes_idle_seconds(self, mock_db: AsyncMock) -> None:
        """
        AT-N-03: Test that get_status includes idle_seconds field.

        // Given: ExplorationState with activity tracking
        // When: get_status() is called
        // Then: Response includes idle_seconds as integer
        """
        with patch("src.research.state.get_database", return_value=mock_db):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")
            await state._ensure_db()

            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.task_limits.cursor_idle_timeout_seconds = 300

                status = await state.get_status()

                assert "idle_seconds" in status
                assert isinstance(status["idle_seconds"], int)
                assert status["idle_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_get_status_boundary_just_under_timeout_no_warning(
        self, mock_db: AsyncMock
    ) -> None:
        """
        AT-B-02: Test no warning when idle time is just under timeout.

        // Given: ExplorationState with idle_seconds = timeout - 1
        // When: get_status() is called
        // Then: No idle warning in warnings list
        """
        with patch("src.research.state.get_database", return_value=mock_db):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")
            await state._ensure_db()

            timeout = 60
            state._last_activity_at = time.time() - (timeout - 1)

            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.task_limits.cursor_idle_timeout_seconds = timeout

                status = await state.get_status()

                idle_warnings = [w for w in status["warnings"] if "idle" in w.lower()]
                assert len(idle_warnings) == 0

    @pytest.mark.asyncio
    async def test_get_status_boundary_exact_timeout_warning(self, mock_db: AsyncMock) -> None:
        """
        AT-B-03: Test warning when idle time equals timeout exactly.

        // Given: ExplorationState with idle_seconds = timeout
        // When: get_status() is called
        // Then: Idle warning is present
        """
        with patch("src.research.state.get_database", return_value=mock_db):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")
            await state._ensure_db()

            timeout = 60
            state._last_activity_at = time.time() - timeout

            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.task_limits.cursor_idle_timeout_seconds = timeout

                status = await state.get_status()

                idle_warnings = [w for w in status["warnings"] if "idle" in w.lower()]
                assert len(idle_warnings) > 0

    @pytest.mark.asyncio
    async def test_get_status_boundary_over_timeout_warning(self, mock_db: AsyncMock) -> None:
        """
        AT-B-04: Test warning when idle time exceeds timeout.

        // Given: ExplorationState with idle_seconds = timeout + 100
        // When: get_status() is called
        // Then: Idle warning includes timeout value
        """
        with patch("src.research.state.get_database", return_value=mock_db):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")
            await state._ensure_db()

            timeout = 60
            state._last_activity_at = time.time() - (timeout + 100)

            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.task_limits.cursor_idle_timeout_seconds = timeout

                status = await state.get_status()

                assert len(status["warnings"]) > 0
                idle_warning = [w for w in status["warnings"] if "idle" in w.lower()]
                assert len(idle_warning) > 0
                assert str(timeout) in idle_warning[0]

    @pytest.mark.asyncio
    async def test_get_status_no_warning_when_active(self, mock_db: AsyncMock) -> None:
        """
        AT-B-01: Test that no idle warning when activity is recent.

        // Given: ExplorationState with recent activity
        // When: get_status() is called
        // Then: No idle warnings
        """
        with patch("src.research.state.get_database", return_value=mock_db):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")
            await state._ensure_db()

            state.record_activity()

            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.task_limits.cursor_idle_timeout_seconds = 60

                status = await state.get_status()

                idle_warnings = [w for w in status["warnings"] if "idle" in w.lower()]
                assert len(idle_warnings) == 0

    def test_multiple_record_activity_calls(self) -> None:
        """
        AT-N-02: Test that multiple record_activity calls work correctly.

        // Given: ExplorationState
        // When: record_activity() called multiple times with delays
        // Then: Each timestamp >= previous timestamp
        """
        with patch("src.research.state.get_database", new_callable=AsyncMock):
            from src.research.state import ExplorationState

            state = ExplorationState("test_task")

            timestamps = []
            for _ in range(5):
                state.record_activity()
                timestamps.append(state._last_activity_at)
                time.sleep(0.01)

            for i in range(1, len(timestamps)):
                assert timestamps[i] >= timestamps[i - 1]
