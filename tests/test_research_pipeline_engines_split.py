"""Tests for pipeline serp_engines/academic_apis split.

Verifies that SERP engines and Academic APIs are correctly separated
in the search pipeline per the Unknown API fix.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-P-01 | serp_engines=["google"], academic_apis=["semantic_scholar"] | Equivalence – normal | SERP gets google, Academic gets semantic_scholar | Wiring |
| TC-P-02 | serp_engines=None, academic_apis=None | Equivalence – default | Both use defaults | Default behavior |
| TC-P-03 | serp_engines set, academic_apis=None | Effect – split | Academic defaults to both APIs | Partial spec |
| TC-P-04 | serp_engines=None, academic_apis set | Effect – split | SERP uses auto-selection | Partial spec |
| TC-P-05 | search_action converts options correctly | Wiring | PipelineSearchOptions has serp_engines/academic_apis | Conversion |
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from src.storage.database import Database

pytestmark = pytest.mark.integration


class TestPipelineEnginesSplit:
    """Tests for pipeline serp_engines/academic_apis separation.

    Per plan: Verify that SERP engines and academic APIs don't mix.
    """

    @pytest.mark.asyncio
    async def test_serp_engines_passed_to_search_serp(self, test_database: Database) -> None:
        """
        TC-P-01a: serp_engines are passed to search_serp, not to academic provider.

        // Given: PipelineSearchOptions with serp_engines=["duckduckgo"]
        // When: _execute_unified_search is called
        // Then: search_serp receives engines=["duckduckgo"]
        """
        from src.research.pipeline import PipelineSearchOptions, SearchPipeline
        from src.research.state import ExplorationState

        db = test_database

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_p01a", "Test hypothesis", "exploring"),
        )

        state = ExplorationState(task_id="task_p01a")
        pipeline = SearchPipeline(task_id="task_p01a", state=state)

        captured_serp_engines: list[list[str] | None] = []
        captured_academic_options: list[Any] = []

        # Mock search_serp to capture engines argument
        async def mock_search_serp(
            query: str,
            limit: int = 10,
            task_id: str | None = None,
            engines: list[str] | None = None,
            serp_max_pages: int = 1,
            worker_id: int = 0,
            **kwargs: Any,
        ) -> list[dict[str, Any]]:
            captured_serp_engines.append(engines)
            return []

        # Mock academic provider to capture options
        class MockAcademicProvider:
            def __init__(self) -> None:
                pass

            def get_last_index(self) -> None:
                return None

            async def search(self, query: str, options: Any) -> Any:
                captured_academic_options.append(options)
                return MagicMock(ok=True, results=[])

            async def close(self) -> None:
                pass

        options = PipelineSearchOptions(
            serp_engines=["duckduckgo"],
            academic_apis=["semantic_scholar"],
        )

        with (
            patch("src.search.search_api.search_serp", side_effect=mock_search_serp),
            patch(
                "src.search.academic_provider.AcademicSearchProvider",
                return_value=MockAcademicProvider(),
            ),
            patch("src.search.id_resolver.IDResolver") as mock_resolver,
        ):
            mock_resolver.return_value.close = AsyncMock()
            # Execute just the search part (skip full execution)
            await pipeline.execute(query="test query", options=options)

        # Verify SERP received serp_engines
        assert len(captured_serp_engines) >= 1
        assert captured_serp_engines[0] == ["duckduckgo"]

        # Verify academic provider received academic_apis via SearchProviderOptions
        assert len(captured_academic_options) >= 1
        academic_options = captured_academic_options[0]
        assert hasattr(academic_options, "engines")
        assert academic_options.engines == ["semantic_scholar"]

    @pytest.mark.asyncio
    async def test_academic_apis_not_mixed_with_serp_engines(self, test_database: Database) -> None:
        """
        TC-P-01b: Academic provider does not receive SERP engine names.

        // Given: PipelineSearchOptions with serp_engines=["google"], academic_apis=["openalex"]
        // When: _execute_unified_search is called
        // Then: Academic provider receives only ["openalex"], not ["google"]
        """
        from src.research.pipeline import PipelineSearchOptions, SearchPipeline
        from src.research.state import ExplorationState

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_p01b", "Test hypothesis", "exploring"),
        )

        state = ExplorationState(task_id="task_p01b")
        pipeline = SearchPipeline(task_id="task_p01b", state=state)

        captured_academic_engines: list[list[str] | None] = []

        # Mock academic provider to capture engines
        class MockAcademicProvider:
            def __init__(self) -> None:
                pass

            def get_last_index(self) -> None:
                return None

            async def search(self, query: str, options: Any) -> Any:
                captured_academic_engines.append(getattr(options, "engines", None))
                return MagicMock(ok=True, results=[])

            async def close(self) -> None:
                pass

        options = PipelineSearchOptions(
            serp_engines=["google"],  # This should NOT go to academic
            academic_apis=["openalex"],  # Only this should go to academic
        )

        async def mock_search_serp(**kwargs: Any) -> list[dict[str, Any]]:
            return []

        with (
            patch("src.search.search_api.search_serp", side_effect=mock_search_serp),
            patch(
                "src.search.academic_provider.AcademicSearchProvider",
                return_value=MockAcademicProvider(),
            ),
            patch("src.search.id_resolver.IDResolver") as mock_resolver,
        ):
            mock_resolver.return_value.close = AsyncMock()
            await pipeline.execute(query="test query", options=options)

        # Verify academic provider received only academic_apis, not serp_engines
        assert len(captured_academic_engines) >= 1
        assert captured_academic_engines[0] == ["openalex"]
        assert "google" not in (captured_academic_engines[0] or [])

    @pytest.mark.asyncio
    async def test_default_apis_when_none_specified(self, test_database: Database) -> None:
        """
        TC-P-02: Default behavior when neither serp_engines nor academic_apis specified.

        // Given: PipelineSearchOptions with serp_engines=None, academic_apis=None
        // When: _execute_unified_search is called
        // Then: Both use auto-selection/defaults
        """
        from src.research.pipeline import PipelineSearchOptions, SearchPipeline
        from src.research.state import ExplorationState

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_p02", "Test hypothesis", "exploring"),
        )

        state = ExplorationState(task_id="task_p02")
        pipeline = SearchPipeline(task_id="task_p02", state=state)

        captured_serp_engines: list[list[str] | None] = []
        captured_academic_engines: list[list[str] | None] = []

        async def mock_search_serp(
            engines: list[str] | None = None, **kwargs: Any
        ) -> list[dict[str, Any]]:
            captured_serp_engines.append(engines)
            return []

        class MockAcademicProvider:
            def __init__(self) -> None:
                pass

            def get_last_index(self) -> None:
                return None

            async def search(self, query: str, options: Any) -> Any:
                captured_academic_engines.append(getattr(options, "engines", None))
                return MagicMock(ok=True, results=[])

            async def close(self) -> None:
                pass

        # Both None - should use defaults
        options = PipelineSearchOptions()

        with (
            patch("src.search.search_api.search_serp", side_effect=mock_search_serp),
            patch(
                "src.search.academic_provider.AcademicSearchProvider",
                return_value=MockAcademicProvider(),
            ),
            patch("src.search.id_resolver.IDResolver") as mock_resolver,
        ):
            mock_resolver.return_value.close = AsyncMock()
            await pipeline.execute(query="test query", options=options)

        # SERP should get None (auto-selection)
        assert captured_serp_engines[0] is None

        # Academic should get None (provider uses its own defaults)
        assert captured_academic_engines[0] is None


class TestSearchActionOptionsConversion:
    """Tests for search_action options dict to PipelineSearchOptions conversion."""

    @pytest.mark.asyncio
    async def test_search_action_converts_serp_engines(self, test_database: Database) -> None:
        """
        TC-P-05a: search_action correctly converts options.serp_engines.

        // Given: options dict with serp_engines
        // When: search_action is called
        // Then: PipelineSearchOptions.serp_engines is set correctly
        """
        from unittest.mock import patch

        from src.research.pipeline import search_action
        from src.research.state import ExplorationState

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_p05a", "Test hypothesis", "exploring"),
        )

        state = ExplorationState(task_id="task_p05a")

        captured_options: list[Any] = []

        # Capture the options passed to SearchPipeline.execute
        class MockPipeline:
            def __init__(self, task_id: str, state: ExplorationState) -> None:
                pass

            async def execute(self, query: str, options: Any) -> Any:
                captured_options.append(options)
                return MagicMock(to_dict=lambda: {"ok": True})

        with patch("src.research.pipeline.SearchPipeline", MockPipeline):
            await search_action(
                task_id="task_p05a",
                query="test query",
                state=state,
                options={
                    "serp_engines": ["mojeek"],
                    "academic_apis": ["openalex"],
                    "budget_pages": 5,
                },
            )

        assert len(captured_options) == 1
        opts = captured_options[0]
        assert opts.serp_engines == ["mojeek"]
        assert opts.academic_apis == ["openalex"]
        assert opts.budget_pages == 5

    @pytest.mark.asyncio
    async def test_search_action_handles_missing_options(self, test_database: Database) -> None:
        """
        TC-P-05b: search_action handles missing serp_engines/academic_apis gracefully.

        // Given: options dict without serp_engines/academic_apis
        // When: search_action is called
        // Then: PipelineSearchOptions has None for both fields
        """
        from unittest.mock import patch

        from src.research.pipeline import search_action
        from src.research.state import ExplorationState

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_p05b", "Test hypothesis", "exploring"),
        )

        state = ExplorationState(task_id="task_p05b")

        captured_options: list[Any] = []

        class MockPipeline:
            def __init__(self, task_id: str, state: ExplorationState) -> None:
                pass

            async def execute(self, query: str, options: Any) -> Any:
                captured_options.append(options)
                return MagicMock(to_dict=lambda: {"ok": True})

        with patch("src.research.pipeline.SearchPipeline", MockPipeline):
            await search_action(
                task_id="task_p05b",
                query="test query",
                state=state,
                options={"budget_pages": 10},  # No serp_engines or academic_apis
            )

        assert len(captured_options) == 1
        opts = captured_options[0]
        assert opts.serp_engines is None
        assert opts.academic_apis is None
        assert opts.budget_pages == 10


class TestExecutorSerpEnginesParameter:
    """Tests for SearchExecutor.execute() serp_engines parameter."""

    @pytest.mark.asyncio
    async def test_executor_passes_serp_engines_to_search_serp(
        self, test_database: Database
    ) -> None:
        """
        Verify SearchExecutor passes serp_engines to search_serp.

        // Given: SearchExecutor with serp_engines=["bing"]
        // When: execute() is called
        // Then: search_serp receives engines=["bing"]
        """
        from src.research.executor import SearchExecutor
        from src.research.state import ExplorationState

        db = test_database

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_exec", "Test hypothesis", "exploring"),
        )

        state = ExplorationState(task_id="task_exec")
        executor = SearchExecutor(task_id="task_exec", state=state)

        captured_engines: list[list[str] | None] = []

        async def mock_search_serp(
            query: str,
            limit: int = 10,
            task_id: str | None = None,
            engines: list[str] | None = None,
            **kwargs: Any,
        ) -> list[dict[str, Any]]:
            captured_engines.append(engines)
            return []

        with patch("src.search.search_serp", side_effect=mock_search_serp):
            await executor.execute(
                query="test query",
                serp_engines=["bing"],
            )

        # Verify search_serp received the serp_engines
        assert len(captured_engines) >= 1
        assert captured_engines[0] == ["bing"]
