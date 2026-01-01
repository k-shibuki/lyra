"""Tests for ADR-0007 CAPTCHA Intervention Integration.

This module tests the integration between CAPTCHA detection in BrowserSearchProvider,
InterventionQueue, and the resolve_auth auto-requeue functionality.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scheduler.jobs import JobState

if TYPE_CHECKING:
    from src.storage.database import Database


class TestInterventionQueueEnqueue:
    """Tests for InterventionQueue.enqueue() with search_job_id."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_enqueue_with_search_job_id(self, mock_db: MagicMock) -> None:
        """Test enqueue includes search_job_id in DB insert.

        Given: A valid task_id, url, domain, auth_type, and search_job_id
        When: enqueue() is called
        Then: DB insert includes search_job_id
        """
        # Given
        from src.utils.intervention_queue import InterventionQueue

        queue = InterventionQueue()
        queue._db = mock_db

        # When
        with patch("src.utils.batch_notification._get_batch_notification_manager") as mock_batch:
            mock_batch.return_value.on_captcha_queued = AsyncMock()
            queue_id = await queue.enqueue(
                task_id="task_123",
                url="https://duckduckgo.com/",
                domain="duckduckgo",
                auth_type="captcha",
                search_job_id="job_456",
            )

        # Then
        assert queue_id.startswith("iq_")
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "search_job_id" in sql
        assert "job_456" in params

    @pytest.mark.asyncio
    async def test_enqueue_without_search_job_id(self, mock_db: MagicMock) -> None:
        """Test enqueue works without search_job_id.

        Given: A valid task_id, url, domain, auth_type, but no search_job_id
        When: enqueue() is called
        Then: DB insert has None for search_job_id
        """
        # Given
        from src.utils.intervention_queue import InterventionQueue

        queue = InterventionQueue()
        queue._db = mock_db

        # When
        with patch("src.utils.batch_notification._get_batch_notification_manager") as mock_batch:
            mock_batch.return_value.on_captcha_queued = AsyncMock()
            queue_id = await queue.enqueue(
                task_id="task_123",
                url="https://duckduckgo.com/",
                domain="duckduckgo",
                auth_type="captcha",
            )

        # Then
        assert queue_id.startswith("iq_")
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        # Last param should be None (search_job_id)
        assert params[-1] is None

    @pytest.mark.asyncio
    async def test_enqueue_triggers_batch_notification(self, mock_db: MagicMock) -> None:
        """Test enqueue triggers batch notification manager.

        Given: InterventionQueue with mock batch notification manager
        When: enqueue() is called
        Then: BatchNotificationManager.on_captcha_queued() is called
        """
        # Given
        from src.utils.intervention_queue import InterventionQueue

        queue = InterventionQueue()
        queue._db = mock_db

        # When
        with patch("src.utils.batch_notification._get_batch_notification_manager") as mock_batch:
            mock_on_captcha = AsyncMock()
            mock_batch.return_value.on_captcha_queued = mock_on_captcha
            await queue.enqueue(
                task_id="task_123",
                url="https://duckduckgo.com/",
                domain="duckduckgo",
                auth_type="captcha",
            )

        # Then
        mock_on_captcha.assert_called_once()
        call_args = mock_on_captcha.call_args[0]
        assert call_args[1] == "duckduckgo"  # domain


class TestBatchNotificationManager:
    """Tests for BatchNotificationManager."""

    @pytest.mark.asyncio
    async def test_on_captcha_queued_starts_timer(self) -> None:
        """Test on_captcha_queued starts notification timer.

        Given: A fresh BatchNotificationManager
        When: on_captcha_queued() is called
        Then: Timer is started (first_pending_time is set)
        """
        # Given
        from src.utils.batch_notification import BatchNotificationManager

        manager = BatchNotificationManager()
        assert manager._first_pending_time is None

        # When (mock sleep to avoid actual delay)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await manager.on_captcha_queued("iq_123", "duckduckgo")

        # Then
        assert manager._first_pending_time is not None
        assert manager._notification_timer is not None

    @pytest.mark.asyncio
    async def test_on_search_queue_empty_triggers_notification(self) -> None:
        """Test on_search_queue_empty triggers batch notification.

        Given: BatchNotificationManager with pending items
        When: on_search_queue_empty() is called
        Then: Notification is sent (send_toast is called)
        """
        # Given
        from src.utils.batch_notification import BatchNotificationManager

        manager = BatchNotificationManager()
        manager._first_pending_time = datetime.now(UTC)
        manager._notified = False

        # When: Mock get_pending to return items so notification is sent
        mock_item = {"domain": "duckduckgo", "auth_type": "captcha"}
        with patch("src.utils.intervention_queue.get_intervention_queue") as mock_queue:
            mock_queue.return_value.get_pending = AsyncMock(return_value=[mock_item])
            with patch("src.utils.intervention_manager._get_manager") as mock_mgr:
                mock_send_toast = AsyncMock()
                mock_mgr.return_value.send_toast = mock_send_toast
                await manager.on_search_queue_empty()

        # Then: Verify send_toast was called (notification was sent)
        # Note: _notified is reset to False by _reset() after notification
        mock_send_toast.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_duplicate_notifications(self) -> None:
        """Test that notifications are not sent twice.

        Given: BatchNotificationManager that already notified
        When: on_search_queue_empty() is called again
        Then: No additional notification is sent
        """
        # Given
        from src.utils.batch_notification import BatchNotificationManager

        manager = BatchNotificationManager()
        manager._first_pending_time = datetime.now(UTC)
        manager._notified = True  # Already notified

        # When
        with patch("src.utils.intervention_manager._get_manager") as mock_mgr:
            mock_send = AsyncMock()
            mock_mgr.return_value.send_toast = mock_send
            await manager.on_search_queue_empty()

        # Then
        mock_send.assert_not_called()


class TestSearchResponseCaptchaFields:
    """Tests for SearchResponse captcha_queued and queue_id fields."""

    def test_search_response_defaults(self) -> None:
        """Test SearchResponse has correct defaults for captcha fields.

        Given: A SearchResponse with minimal fields
        When: Created without captcha fields
        Then: captcha_queued=False and queue_id=None
        """
        # Given/When
        from src.search.provider import SearchResponse

        response = SearchResponse(
            results=[],
            query="test",
            provider="test_provider",
        )

        # Then
        assert response.captcha_queued is False
        assert response.queue_id is None

    def test_search_response_with_captcha_queued(self) -> None:
        """Test SearchResponse with captcha_queued=True.

        Given: A SearchResponse with captcha_queued=True
        When: to_dict() is called
        Then: captcha_queued and queue_id are included in dict
        """
        # Given
        from src.search.provider import SearchResponse

        response = SearchResponse(
            results=[],
            query="test",
            provider="test_provider",
            captcha_queued=True,
            queue_id="iq_123",
        )

        # When
        result_dict = response.to_dict()

        # Then
        assert result_dict["captcha_queued"] is True
        assert result_dict["queue_id"] == "iq_123"

    def test_search_response_to_dict_omits_captcha_if_not_queued(self) -> None:
        """Test to_dict() omits captcha fields if not queued.

        Given: A SearchResponse with captcha_queued=False
        When: to_dict() is called
        Then: captcha_queued is not in dict
        """
        # Given
        from src.search.provider import SearchResponse

        response = SearchResponse(
            results=[],
            query="test",
            provider="test_provider",
            captcha_queued=False,
        )

        # When
        result_dict = response.to_dict()

        # Then
        assert "captcha_queued" not in result_dict


class TestSearchProviderOptionsJobIdFields:
    """Tests for SearchProviderOptions task_id and search_job_id fields."""

    def test_search_options_with_job_ids(self) -> None:
        """Test SearchProviderOptions accepts task_id and search_job_id.

        Given: SearchProviderOptions with task_id and search_job_id
        When: Created
        Then: Fields are set correctly
        """
        # Given/When
        from src.search.provider import SearchProviderOptions

        options = SearchProviderOptions(
            task_id="task_123",
            search_job_id="job_456",
        )

        # Then
        assert options.task_id == "task_123"
        assert options.search_job_id == "job_456"

    def test_search_options_defaults_to_none(self) -> None:
        """Test SearchProviderOptions defaults job IDs to None.

        Given: SearchProviderOptions without job IDs
        When: Created
        Then: task_id and search_job_id are None
        """
        # Given/When
        from src.search.provider import SearchProviderOptions

        options = SearchProviderOptions()

        # Then
        assert options.task_id is None
        assert options.search_job_id is None


class TestJobStateAwaitingAuth:
    """Tests for JobState.AWAITING_AUTH."""

    def test_awaiting_auth_state_exists(self) -> None:
        """Test AWAITING_AUTH state is defined.

        Given: JobState enum
        When: Accessing AWAITING_AUTH
        Then: Value is 'awaiting_auth'
        """
        # Given/When/Then
        assert JobState.AWAITING_AUTH.value == "awaiting_auth"

    def test_awaiting_auth_is_string_enum(self) -> None:
        """Test AWAITING_AUTH is a valid string enum.

        Given: JobState.AWAITING_AUTH
        When: Compared as string
        Then: Equals 'awaiting_auth'
        """
        # Given/When/Then
        assert JobState.AWAITING_AUTH == "awaiting_auth"


class TestRequeueAwaitingAuthJobs:
    """Tests for _requeue_awaiting_auth_jobs helper."""

    @pytest.mark.asyncio
    async def test_requeue_awaiting_auth_jobs_success(self, test_database: Database) -> None:
        """Test requeuing awaiting_auth jobs after auth resolution.

        Given: Jobs in awaiting_auth state linked to intervention queue
        When: _requeue_awaiting_auth_jobs() is called
        Then: Jobs are updated to queued state
        """
        # Given
        db = test_database
        task_id = "task_test"

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status, created_at) VALUES (?, ?, ?, ?)",
            (task_id, "test query", "running", datetime.now(UTC).isoformat()),
        )

        # Create job in awaiting_auth state (including required slot column)
        job_id = "job_123"
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, state, slot, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                task_id,
                "search_queue",
                "awaiting_auth",
                0,
                "{}",
                datetime.now(UTC).isoformat(),
            ),
        )

        # Create completed intervention queue item
        await db.execute(
            """
            INSERT INTO intervention_queue (id, task_id, url, domain, auth_type, status, search_job_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("iq_123", task_id, "https://test.com", "duckduckgo", "captcha", "completed", job_id),
        )

        # When
        from src.mcp.tools.auth import requeue_awaiting_auth_jobs as _requeue_awaiting_auth_jobs

        with patch("src.storage.database.get_database", return_value=db):
            count = await _requeue_awaiting_auth_jobs("duckduckgo")

        # Then
        assert count == 1
        row = await db.fetch_one("SELECT state FROM jobs WHERE id = ?", (job_id,))
        assert row is not None
        assert row["state"] == "queued"

    @pytest.mark.asyncio
    async def test_requeue_no_matching_jobs(self, test_database: Database) -> None:
        """Test requeue returns 0 when no matching jobs.

        Given: No jobs in awaiting_auth state
        When: _requeue_awaiting_auth_jobs() is called
        Then: Returns 0
        """
        # Given
        db = test_database

        # When
        from src.mcp.tools.auth import requeue_awaiting_auth_jobs as _requeue_awaiting_auth_jobs

        with patch("src.storage.database.get_database", return_value=db):
            count = await _requeue_awaiting_auth_jobs("unknown_domain")

        # Then
        assert count == 0


class TestResetCircuitBreaker:
    """Tests for _reset_circuit_breaker_for_engine helper."""

    @pytest.mark.asyncio
    async def test_reset_circuit_breaker_success(self) -> None:
        """Test circuit breaker is reset after auth resolution.

        Given: A circuit breaker for an engine
        When: _reset_circuit_breaker_for_engine() is called
        Then: force_close() is called on the breaker
        """
        # Given
        mock_breaker = MagicMock()
        mock_manager = MagicMock()
        mock_manager.get_breaker = AsyncMock(return_value=mock_breaker)

        # When
        from src.mcp.tools.auth import (
            reset_circuit_breaker_for_engine as _reset_circuit_breaker_for_engine,
        )

        # Patch at the use site (inside the function)
        with patch(
            "src.mcp.tools.auth.get_circuit_breaker_manager",
            new_callable=AsyncMock,
            return_value=mock_manager,
        ):
            await _reset_circuit_breaker_for_engine("duckduckgo")

        # Then
        mock_breaker.force_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_circuit_breaker_handles_error(self) -> None:
        """Test circuit breaker reset handles errors gracefully.

        Given: get_circuit_breaker_manager raises exception
        When: _reset_circuit_breaker_for_engine() is called
        Then: No exception is raised (logs warning)
        """
        # Given/When
        from src.mcp.tools.auth import (
            reset_circuit_breaker_for_engine as _reset_circuit_breaker_for_engine,
        )

        with patch(
            "src.search.circuit_breaker.get_circuit_breaker_manager",
            side_effect=Exception("Test error"),
        ):
            # Should not raise
            await _reset_circuit_breaker_for_engine("duckduckgo")

        # Then (no exception means success)


class TestGetPendingAuthInfo:
    """Tests for _get_pending_auth_info helper."""

    @pytest.mark.asyncio
    async def test_get_pending_auth_info_with_data(self, test_database: Database) -> None:
        """Test getting pending auth info with existing data.

        Given: Jobs in awaiting_auth state and pending intervention items
        When: _get_pending_auth_info() is called
        Then: Returns correct counts and domain info
        """
        # Given
        db = test_database
        task_id = "task_test"

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status, created_at) VALUES (?, ?, ?, ?)",
            (task_id, "test query", "running", datetime.now(UTC).isoformat()),
        )

        # Create job in awaiting_auth state (including required slot column)
        await db.execute(
            """
            INSERT INTO jobs (id, task_id, kind, state, slot, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job_1",
                task_id,
                "search_queue",
                "awaiting_auth",
                0,
                "{}",
                datetime.now(UTC).isoformat(),
            ),
        )

        # Create pending intervention queue items
        await db.execute(
            """
            INSERT INTO intervention_queue (id, task_id, url, domain, auth_type, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("iq_1", task_id, "https://test.com", "duckduckgo", "captcha", "pending"),
        )
        await db.execute(
            """
            INSERT INTO intervention_queue (id, task_id, url, domain, auth_type, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("iq_2", task_id, "https://test2.com", "duckduckgo", "turnstile", "pending"),
        )

        # When
        from src.mcp.helpers import get_pending_auth_info as _get_pending_auth_info

        result = await _get_pending_auth_info(db, task_id)

        # Then
        assert result["awaiting_auth_jobs"] == 1
        assert result["pending_captchas"] == 2
        assert len(result["domains"]) == 1
        assert result["domains"][0]["domain"] == "duckduckgo"
        assert result["domains"][0]["count"] == 2

    @pytest.mark.asyncio
    async def test_get_pending_auth_info_empty(self, test_database: Database) -> None:
        """Test getting pending auth info with no data.

        Given: No awaiting_auth jobs or pending intervention items
        When: _get_pending_auth_info() is called
        Then: Returns zeros
        """
        # Given
        db = test_database
        task_id = "task_empty"

        # When
        from src.mcp.helpers import get_pending_auth_info as _get_pending_auth_info

        result = await _get_pending_auth_info(db, task_id)

        # Then
        assert result["awaiting_auth_jobs"] == 0
        assert result["pending_captchas"] == 0
        assert result["domains"] == []
