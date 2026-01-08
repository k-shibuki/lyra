"""Tests for CausalTrace contextvars support and job cause_id propagation.

Tests the causal tracing feature added in BUG-001d fix.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-CT-01 | get_current_cause_id() outside context | Boundary – NULL | Returns None | No active trace |
| TC-CT-02 | get_current_cause_id() inside CausalTrace | Equivalence – normal | Returns trace.id | Active trace |
| TC-CT-03 | Nested CausalTrace contexts | Boundary – nested | Returns innermost trace.id | LIFO semantics |
| TC-CT-04 | After CausalTrace exits | Boundary – cleanup | Returns previous value | Context reset |
| TC-CT-05 | CausalTrace sets contextvars token | Equivalence – internal | _token is set on enter | Implementation |
| TC-CT-06 | CausalTrace resets token on exit | Equivalence – cleanup | Token reset on exit | Implementation |
| TC-W-01 | enqueue_verify_nli_job with context | Wiring – propagation | cause_id passed to submit | Inheritance |
| TC-W-02 | enqueue_verify_nli_job with explicit cause_id | Wiring – explicit | Explicit cause_id used | Override |
| TC-W-03 | enqueue_citation_graph_job with context | Wiring – propagation | cause_id passed to submit | Inheritance |
| TC-W-04 | handle_queue_targets creates trace | Wiring – creation | cause_id in submitted jobs | MCP handler |
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from src.storage.database import Database


class TestGetCurrentCauseId:
    """Tests for get_current_cause_id() function."""

    def test_outside_context_returns_none(self) -> None:
        """
        TC-CT-01: get_current_cause_id() outside context returns None.

        // Given: No CausalTrace context is active
        // When: get_current_cause_id() is called
        // Then: Returns None
        """
        from src.utils.logging import _current_cause_id, get_current_cause_id

        # Ensure clean state
        _current_cause_id.set(None)

        result = get_current_cause_id()

        assert result is None

    def test_inside_context_returns_trace_id(self) -> None:
        """
        TC-CT-02: get_current_cause_id() inside CausalTrace returns trace.id.

        // Given: A CausalTrace context is active
        // When: get_current_cause_id() is called inside the context
        // Then: Returns the trace's id
        """
        from src.utils.logging import CausalTrace, get_current_cause_id

        with CausalTrace() as trace:
            result = get_current_cause_id()
            assert result == trace.id

    def test_nested_contexts_returns_innermost(self) -> None:
        """
        TC-CT-03: Nested CausalTrace contexts return innermost trace.id.

        // Given: Nested CausalTrace contexts
        // When: get_current_cause_id() is called in innermost context
        // Then: Returns the innermost trace's id (LIFO semantics)
        """
        from src.utils.logging import CausalTrace, get_current_cause_id

        with CausalTrace() as outer:
            outer_id = get_current_cause_id()
            assert outer_id == outer.id

            with CausalTrace() as inner:
                inner_id = get_current_cause_id()
                assert inner_id == inner.id
                assert inner_id != outer_id

            # After inner exits, should return to outer
            restored_id = get_current_cause_id()
            assert restored_id == outer.id

    def test_after_context_exits_returns_previous(self) -> None:
        """
        TC-CT-04: After CausalTrace exits, returns previous value.

        // Given: A CausalTrace context that has exited
        // When: get_current_cause_id() is called after exit
        // Then: Returns None (previous value)
        """
        from src.utils.logging import CausalTrace, _current_cause_id, get_current_cause_id

        # Ensure clean state
        _current_cause_id.set(None)

        with CausalTrace():
            pass  # Context exits

        result = get_current_cause_id()
        assert result is None


class TestCausalTraceContextvars:
    """Tests for CausalTrace contextvars token handling."""

    def test_token_is_set_on_enter(self) -> None:
        """
        TC-CT-05: CausalTrace sets contextvars token on enter.

        // Given: A new CausalTrace
        // When: Entering the context
        // Then: _token is set (not None)
        """
        from src.utils.logging import CausalTrace

        trace = CausalTrace()
        assert trace._token is None

        trace.__enter__()
        assert trace._token is not None

        trace.__exit__(None, None, None)

    def test_token_reset_on_exit(self) -> None:
        """
        TC-CT-06: CausalTrace resets token on exit.

        // Given: A CausalTrace context that was entered
        // When: Exiting the context
        // Then: Token is reset and contextvars returns to previous value
        """
        from src.utils.logging import CausalTrace, _current_cause_id

        # Set a known initial value
        _current_cause_id.set(None)

        with CausalTrace() as trace:
            assert _current_cause_id.get() == trace.id

        # After exit, should be back to None
        assert _current_cause_id.get() is None


class TestEnqueueVerifyNliJobWiring:
    """Tests for cause_id propagation in enqueue_verify_nli_job."""

    @pytest.mark.asyncio
    async def test_inherits_cause_id_from_context(self, test_database: Database) -> None:
        """
        TC-W-01: enqueue_verify_nli_job inherits cause_id from context.

        // Given: A CausalTrace context is active
        // When: enqueue_verify_nli_job is called without explicit cause_id
        // Then: The context's cause_id is passed to scheduler.submit
        """
        from src.filter.cross_verification import enqueue_verify_nli_job
        from src.utils.logging import CausalTrace

        # Create a task first
        await test_database.insert(
            "tasks",
            {
                "id": "task_test_001",
                "hypothesis": "Test hypothesis",
                "status": "exploring",
            },
        )

        mock_scheduler = MagicMock()
        mock_scheduler.submit = AsyncMock(return_value={"accepted": True, "job_id": "vnli_test"})

        # Patch at the use site (where get_scheduler is called)
        with patch(
            "src.scheduler.jobs.get_scheduler",
            return_value=mock_scheduler,
        ):
            with CausalTrace() as trace:
                await enqueue_verify_nli_job(task_id="task_test_001")

            # Verify cause_id was passed to submit
            mock_scheduler.submit.assert_called_once()
            call_kwargs = mock_scheduler.submit.call_args.kwargs
            assert call_kwargs.get("cause_id") == trace.id

    @pytest.mark.asyncio
    async def test_explicit_cause_id_overrides_context(self, test_database: Database) -> None:
        """
        TC-W-02: enqueue_verify_nli_job with explicit cause_id overrides context.

        // Given: A CausalTrace context is active
        // When: enqueue_verify_nli_job is called with explicit cause_id
        // Then: The explicit cause_id is used, not the context's
        """
        from src.filter.cross_verification import enqueue_verify_nli_job
        from src.utils.logging import CausalTrace

        await test_database.insert(
            "tasks",
            {
                "id": "task_test_002",
                "hypothesis": "Test hypothesis",
                "status": "exploring",
            },
        )

        mock_scheduler = MagicMock()
        mock_scheduler.submit = AsyncMock(return_value={"accepted": True, "job_id": "vnli_test2"})

        explicit_cause_id = "explicit-cause-id-123"

        with patch(
            "src.scheduler.jobs.get_scheduler",
            return_value=mock_scheduler,
        ):
            with CausalTrace():
                await enqueue_verify_nli_job(task_id="task_test_002", cause_id=explicit_cause_id)

            call_kwargs = mock_scheduler.submit.call_args.kwargs
            assert call_kwargs.get("cause_id") == explicit_cause_id

    @pytest.mark.asyncio
    async def test_no_context_no_cause_id(self, test_database: Database) -> None:
        """
        TC-W-01b: enqueue_verify_nli_job without context passes None cause_id.

        // Given: No CausalTrace context is active
        // When: enqueue_verify_nli_job is called without explicit cause_id
        // Then: cause_id is None
        """
        from src.filter.cross_verification import enqueue_verify_nli_job
        from src.utils.logging import _current_cause_id

        # Ensure clean state
        _current_cause_id.set(None)

        await test_database.insert(
            "tasks",
            {
                "id": "task_test_003",
                "hypothesis": "Test hypothesis",
                "status": "exploring",
            },
        )

        mock_scheduler = MagicMock()
        mock_scheduler.submit = AsyncMock(return_value={"accepted": True, "job_id": "vnli_test3"})

        with patch(
            "src.scheduler.jobs.get_scheduler",
            return_value=mock_scheduler,
        ):
            await enqueue_verify_nli_job(task_id="task_test_003")

            call_kwargs = mock_scheduler.submit.call_args.kwargs
            assert call_kwargs.get("cause_id") is None


class TestEnqueueCitationGraphJobWiring:
    """Tests for cause_id propagation in enqueue_citation_graph_job."""

    @pytest.mark.asyncio
    async def test_inherits_cause_id_from_context(self, test_database: Database) -> None:
        """
        TC-W-03: enqueue_citation_graph_job inherits cause_id from context.

        // Given: A CausalTrace context is active
        // When: enqueue_citation_graph_job is called without explicit cause_id
        // Then: The context's cause_id is passed to scheduler.submit
        """
        from src.research.citation_graph import enqueue_citation_graph_job
        from src.utils.logging import CausalTrace

        await test_database.insert(
            "tasks",
            {
                "id": "task_cg_001",
                "hypothesis": "Test hypothesis",
                "status": "exploring",
            },
        )

        mock_scheduler = MagicMock()
        mock_scheduler.submit = AsyncMock(return_value={"accepted": True, "job_id": "cg_test"})

        with patch(
            "src.scheduler.jobs.get_scheduler",
            return_value=mock_scheduler,
        ):
            with CausalTrace() as trace:
                await enqueue_citation_graph_job(
                    task_id="task_cg_001",
                    search_id="s_test",
                    query="test query",
                    paper_ids=["paper_1", "paper_2"],
                )

            mock_scheduler.submit.assert_called_once()
            call_kwargs = mock_scheduler.submit.call_args.kwargs
            assert call_kwargs.get("cause_id") == trace.id

    @pytest.mark.asyncio
    async def test_empty_paper_ids_returns_none(self, test_database: Database) -> None:
        """
        TC-W-03b: enqueue_citation_graph_job with empty paper_ids returns None.

        // Given: Empty paper_ids list
        // When: enqueue_citation_graph_job is called
        // Then: Returns None without submitting job
        """
        from src.research.citation_graph import enqueue_citation_graph_job

        result = await enqueue_citation_graph_job(
            task_id="task_cg_002",
            search_id="s_test",
            query="test query",
            paper_ids=[],
        )

        assert result is None


class TestHandleQueueTargetsWiring:
    """Tests for cause_id creation in handle_queue_targets."""

    @pytest.mark.asyncio
    async def test_creates_trace_and_passes_cause_id(self, test_database: Database) -> None:
        """
        TC-W-04: handle_queue_targets creates trace and passes cause_id.

        // Given: A valid task and targets
        // When: handle_queue_targets is called
        // Then: A CausalTrace is created and cause_id is passed to all jobs
        """
        from src.mcp.tools.targets import handle_queue_targets

        # Create task
        await test_database.insert(
            "tasks",
            {
                "id": "task_qt_001",
                "hypothesis": "Test hypothesis",
                "status": "exploring",
            },
        )

        mock_scheduler = MagicMock()
        mock_scheduler.submit = AsyncMock(return_value={"accepted": True, "job_id": "tq_test"})

        with patch(
            "src.scheduler.jobs.get_scheduler",
            return_value=mock_scheduler,
        ):
            await handle_queue_targets(
                {
                    "task_id": "task_qt_001",
                    "targets": [
                        {"kind": "query", "query": "test query 1"},
                        {"kind": "query", "query": "test query 2"},
                    ],
                }
            )

            # Verify all calls have cause_id
            assert mock_scheduler.submit.call_count == 2

            # All calls should have the same cause_id (from the same trace)
            cause_ids = [
                call.kwargs.get("cause_id") for call in mock_scheduler.submit.call_args_list
            ]
            assert all(cause_id is not None for cause_id in cause_ids)
            assert cause_ids[0] == cause_ids[1]  # Same trace for all targets

    @pytest.mark.asyncio
    async def test_cause_id_is_valid_uuid(self, test_database: Database) -> None:
        """
        TC-W-04b: handle_queue_targets generates valid UUID for cause_id.

        // Given: A valid task and targets
        // When: handle_queue_targets is called
        // Then: cause_id is a valid UUID format
        """
        import uuid

        from src.mcp.tools.targets import handle_queue_targets

        await test_database.insert(
            "tasks",
            {
                "id": "task_qt_002",
                "hypothesis": "Test hypothesis",
                "status": "exploring",
            },
        )

        mock_scheduler = MagicMock()
        mock_scheduler.submit = AsyncMock(return_value={"accepted": True, "job_id": "tq_test2"})

        with patch(
            "src.scheduler.jobs.get_scheduler",
            return_value=mock_scheduler,
        ):
            await handle_queue_targets(
                {
                    "task_id": "task_qt_002",
                    "targets": [{"kind": "query", "query": "test query"}],
                }
            )

            cause_id = mock_scheduler.submit.call_args.kwargs.get("cause_id")
            # Validate UUID format
            parsed = uuid.UUID(cause_id)
            assert str(parsed) == cause_id
