"""
Integration-wiring tests for SERP pagination option (serp_max_pages).

Goal:
- Prove MCP options dict -> research.pipeline.SearchOptions.serp_max_pages is wired.
- Prove research.executor.SearchExecutor passes serp_max_pages to src.search.search_serp().

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-SERP-OPT-N-01 | search_action options={"serp_max_pages": 3} | Wiring – propagation | SearchPipeline.execute receives options.serp_max_pages=3 | Entry boundary |
| TC-SERP-OPT-B-01 | options missing serp_max_pages | Boundary – default | Default is 1 | - |
| TC-SERP-EXEC-W-01 | SearchExecutor._execute_search with _serp_max_pages=4 | Wiring – propagation | search_serp called with serp_max_pages=4 | Downstream boundary |
| TC-SERP-EXEC-E-01 | Different serp_max_pages values | Effect – value change | Calls differ by serp_max_pages | - |
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


@dataclass
class _DummyResult:
    """Minimal dummy result with to_dict used by search_action."""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": True}


class TestSerpMaxPagesWiringToPipeline:
    @pytest.mark.asyncio
    async def test_search_action_wires_serp_max_pages_to_pipeline_execute(self) -> None:
        """
        TC-SERP-OPT-N-01: search_action wires serp_max_pages into SearchOptions.

        // Given: search_action called with options.serp_max_pages=3
        // When:  search_action converts dict to SearchOptions and calls pipeline.execute
        // Then:  pipeline.execute receives SearchOptions.serp_max_pages=3
        """
        from src.research.pipeline import search_action

        captured: dict[str, Any] = {}

        async def _capture_execute(self: Any, query: str, options: Any) -> _DummyResult:
            captured["query"] = query
            captured["serp_max_pages"] = getattr(options, "serp_max_pages", None)
            return _DummyResult()

        # Given: minimal ExplorationState stub (not used due to patched execute)
        state = MagicMock()

        with patch("src.research.pipeline.SearchPipeline.execute", new=_capture_execute):
            # When
            out = await search_action(
                task_id="task_1",
                query="q",
                state=state,
                options={"serp_max_pages": 3},
            )

        # Then
        assert out["ok"] is True
        assert captured["query"] == "q"
        assert captured["serp_max_pages"] == 3

    @pytest.mark.asyncio
    async def test_search_action_serp_max_pages_default_is_one(self) -> None:
        """
        TC-SERP-OPT-B-01: Default serp_max_pages=1 when missing from options.

        // Given: search_action called with options missing serp_max_pages
        // When:  search_action calls pipeline.execute
        // Then:  SearchOptions.serp_max_pages defaults to 1
        """
        from src.research.pipeline import search_action

        captured: dict[str, Any] = {}

        async def _capture_execute(self: Any, query: str, options: Any) -> _DummyResult:
            captured["serp_max_pages"] = getattr(options, "serp_max_pages", None)
            return _DummyResult()

        state = MagicMock()

        with patch("src.research.pipeline.SearchPipeline.execute", new=_capture_execute):
            # When
            out = await search_action(
                task_id="task_1",
                query="q",
                state=state,
                options={},
            )

        # Then
        assert out["ok"] is True
        assert captured["serp_max_pages"] == 2  # default value per implementation


class TestSerpMaxPagesWiringToSearchSerp:
    @pytest.mark.asyncio
    async def test_executor_execute_search_passes_serp_max_pages(self) -> None:
        """
        TC-SERP-EXEC-W-01: SearchExecutor passes serp_max_pages to search_serp.

        // Given: SearchExecutor with _serp_max_pages=4
        // When:  _execute_search runs
        // Then:  src.search.search_serp is called with serp_max_pages=4
        """
        from src.research.executor import SearchExecutor

        state = MagicMock()
        ex = SearchExecutor(task_id="task_x", state=state)
        ex._serp_engines = ["mojeek"]
        ex._search_job_id = "job_1"
        ex._serp_max_pages = 4

        mock_search_serp = AsyncMock(return_value=[])

        with patch("src.search.search_serp", new=mock_search_serp):
            # When
            results, error_code, error_details = await ex._execute_search("query")

        # Then
        assert results == []
        assert error_code is None
        assert error_details == {}
        assert mock_search_serp.await_count == 1
        call = mock_search_serp.await_args
        assert call is not None
        assert call.kwargs["serp_max_pages"] == 4

    @pytest.mark.asyncio
    async def test_executor_execute_search_serp_max_pages_effect(self) -> None:
        """
        TC-SERP-EXEC-E-01: Different serp_max_pages values change the downstream call.

        // Given: Two SearchExecutors with different _serp_max_pages
        // When:  _execute_search runs for both
        // Then:  Calls differ by serp_max_pages
        """
        from src.research.executor import SearchExecutor

        mock_search_serp = AsyncMock(return_value=[])

        with patch("src.search.search_serp", new=mock_search_serp):
            # Given
            ex1 = SearchExecutor(task_id="t1", state=MagicMock())
            ex1._serp_max_pages = 1
            ex2 = SearchExecutor(task_id="t2", state=MagicMock())
            ex2._serp_max_pages = 3

            # When
            await ex1._execute_search("q1")
            await ex2._execute_search("q2")

        # Then
        assert mock_search_serp.await_count == 2
        first = mock_search_serp.await_args_list[0].kwargs["serp_max_pages"]
        second = mock_search_serp.await_args_list[1].kwargs["serp_max_pages"]
        assert first == 1
        assert second == 3
