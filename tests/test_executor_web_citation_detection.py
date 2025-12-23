"""
Tests for b web citation detection integration in SearchExecutor.

Goal: prove new settings (search.web_citation_detection.*) are wired and affect behavior.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-EX-WCD-N-01 | enabled, primary-only, useful text, placeholder ON | Equivalence – normal | CitationDetector called and add_citation called | wiring: max_candidates_per_page, create_placeholder_pages |
| TC-EX-WCD-N-02 | create_placeholder_pages=false and target missing | Equivalence – normal | add_citation not called | prevents DB growth |
| TC-EX-WCD-B-01 | max_candidates_per_page=0 | Boundary – 0 | CitationDetector constructed with 10000 | “no limit” |
| TC-EX-WCD-B-02 | max_edges_per_page=1 | Boundary – max | only 1 add_citation call | caps edges |
| TC-EX-WCD-A-01 | enabled=false | Abnormal – disabled | CitationDetector not called | global off |
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.research.executor import SearchExecutor, SearchResult
from src.research.state import ExplorationState
from src.utils.config import Settings


@dataclass(frozen=True)
class _FakeDetected:
    url: str
    link_text: str = ""
    context: str = ""
    link_type: str = "body"
    is_citation: bool = True
    raw_response: str = "YES"


class _FakeDetector:
    def __init__(self, *, max_candidates: int = 15) -> None:
        self.max_candidates = max_candidates

    async def detect_citations(
        self, *, html: str, base_url: str, source_domain: str
    ) -> list[_FakeDetected]:
        # Return 2 citations deterministically
        return [
            _FakeDetected(url="https://example.org/a", context="出典：A"),
            _FakeDetected(url="https://example.org/b", context="参考：B"),
        ]


def _make_executor() -> SearchExecutor:
    state = ExplorationState(task_id="test_task")
    return SearchExecutor(task_id="test_task", state=state)


def _settings_with_web_citation(**overrides: Any) -> Settings:
    base = Settings()
    # pydantic models are mutable by default in v2; update nested config
    wc = base.search.web_citation_detection
    for k, v in overrides.items():
        setattr(wc, k, v)
    return base


@pytest.mark.asyncio
async def test_executor_web_citation_detection_happy_path() -> None:
    # Given
    ex = _make_executor()
    settings = _settings_with_web_citation(
        enabled=True,
        run_on_primary_sources_only=True,
        require_useful_text=True,
        min_text_chars=10,
        max_candidates_per_page=7,
        max_edges_per_page=0,
        max_pages_per_task=0,
        create_placeholder_pages=True,
    )

    serp_item = {"url": "https://gov.example.com/page", "engine": "duckduckgo", "title": "t"}

    fetch_result = {"ok": True, "html_path": "/tmp/x.html", "page_id": "page_src"}
    extract_result = {"text": "x" * 1000, "title": "T"}

    mock_db_instance = AsyncMock()
    # target pages do not exist -> placeholder insert happens
    mock_db_instance.fetch_one = AsyncMock(return_value=None)
    mock_db_instance.insert = AsyncMock(return_value="page_target")
    mock_db_instance.execute = AsyncMock()

    with (
        patch("src.research.executor.get_settings", return_value=settings),
        patch("src.crawler.fetcher.fetch_url", AsyncMock(return_value=fetch_result)),
        patch("src.extractor.content.extract_content", AsyncMock(return_value=extract_result)),
        patch.object(Path, "read_text", return_value="<html></html>"),
        patch("src.extractor.citation_detector.CitationDetector", _FakeDetector),
        patch("src.research.executor.get_database", AsyncMock(return_value=mock_db_instance)),
        # : SearchExecutor._persist_claim now runs NLI by default.
        # Mock it here to avoid model load / remote calls (this test focuses on citation detection wiring).
        patch(
            "src.filter.nli.nli_judge",
            AsyncMock(return_value=[{"stance": "neutral", "confidence": 0.0}]),
        ),
        # _persist_claim persists edge via evidence_graph; mock to avoid touching global graph/DB internals.
        patch("src.filter.evidence_graph.add_claim_evidence", AsyncMock()),
        patch("src.filter.evidence_graph.add_citation", AsyncMock()) as add_citation,
        patch("src.filter.llm.llm_extract", AsyncMock(return_value={"ok": False})),
    ):
        # When
        result = SearchResult(search_id="s1", status="running")
        await ex._fetch_and_extract(search_id="s1", serp_item=serp_item, result=result)

        # Then: detector max_candidates is wired from settings
        # (validated by ensuring our FakeDetector was constructed; add_citation called twice)
        assert add_citation.await_count == 2
        for call in add_citation.await_args_list:
            kwargs = call.kwargs
            assert kwargs["citation_source"] == "extraction"
            assert kwargs["citation_context"]


@pytest.mark.asyncio
async def test_executor_web_citation_detection_no_placeholder_skips_missing_targets() -> None:
    # Given
    ex = _make_executor()
    settings = _settings_with_web_citation(
        enabled=True,
        run_on_primary_sources_only=True,
        require_useful_text=True,
        min_text_chars=10,
        max_candidates_per_page=10,
        max_edges_per_page=0,
        max_pages_per_task=0,
        create_placeholder_pages=False,
    )

    serp_item = {"url": "https://gov.example.com/page", "engine": "duckduckgo", "title": "t"}
    fetch_result = {"ok": True, "html_path": "/tmp/x.html", "page_id": "page_src"}
    extract_result = {"text": "x" * 1000, "title": "T"}

    mock_db_instance = AsyncMock()
    mock_db_instance.fetch_one = AsyncMock(return_value=None)
    mock_db_instance.insert = AsyncMock(return_value="page_target")
    mock_db_instance.execute = AsyncMock()

    with (
        patch("src.research.executor.get_settings", return_value=settings),
        patch("src.crawler.fetcher.fetch_url", AsyncMock(return_value=fetch_result)),
        patch("src.extractor.content.extract_content", AsyncMock(return_value=extract_result)),
        patch.object(Path, "read_text", return_value="<html></html>"),
        patch("src.extractor.citation_detector.CitationDetector", _FakeDetector),
        patch("src.research.executor.get_database", AsyncMock(return_value=mock_db_instance)),
        patch(
            "src.filter.nli.nli_judge",
            AsyncMock(return_value=[{"stance": "neutral", "confidence": 0.0}]),
        ),
        patch("src.filter.evidence_graph.add_claim_evidence", AsyncMock()),
        patch("src.filter.evidence_graph.add_citation", AsyncMock()) as add_citation,
        patch("src.filter.llm.llm_extract", AsyncMock(return_value={"ok": False})),
    ):
        # When
        result = SearchResult(search_id="s1", status="running")
        await ex._fetch_and_extract(search_id="s1", serp_item=serp_item, result=result)

        # Then: no placeholder -> no edges if target pages are missing
        assert add_citation.await_count == 0


@pytest.mark.asyncio
async def test_executor_web_citation_detection_max_candidates_zero_is_unlimited() -> None:
    # Given
    ex = _make_executor()
    settings = _settings_with_web_citation(
        enabled=True,
        run_on_primary_sources_only=True,
        require_useful_text=True,
        min_text_chars=10,
        max_candidates_per_page=0,  # boundary: no limit
        max_edges_per_page=0,
        max_pages_per_task=0,
        create_placeholder_pages=False,
    )

    serp_item = {"url": "https://gov.example.com/page", "engine": "duckduckgo", "title": "t"}
    fetch_result = {"ok": True, "html_path": "/tmp/x.html", "page_id": "page_src"}
    extract_result = {"text": "x" * 1000, "title": "T"}

    created: dict[str, int] = {}

    class _CapturingDetector(_FakeDetector):
        def __init__(self, *, max_candidates: int = 15) -> None:
            created["max_candidates"] = max_candidates
            super().__init__(max_candidates=max_candidates)

    mock_db_instance = AsyncMock()
    mock_db_instance.fetch_one = AsyncMock(return_value=None)
    mock_db_instance.insert = AsyncMock(return_value="page_target")
    mock_db_instance.execute = AsyncMock()

    with (
        patch("src.research.executor.get_settings", return_value=settings),
        patch("src.crawler.fetcher.fetch_url", AsyncMock(return_value=fetch_result)),
        patch("src.extractor.content.extract_content", AsyncMock(return_value=extract_result)),
        patch.object(Path, "read_text", return_value="<html></html>"),
        patch("src.extractor.citation_detector.CitationDetector", _CapturingDetector),
        patch("src.research.executor.get_database", AsyncMock(return_value=mock_db_instance)),
        patch(
            "src.filter.nli.nli_judge",
            AsyncMock(return_value=[{"stance": "neutral", "confidence": 0.0}]),
        ),
        patch("src.filter.evidence_graph.add_claim_evidence", AsyncMock()),
        patch("src.filter.evidence_graph.add_citation", AsyncMock()),
        patch("src.filter.llm.llm_extract", AsyncMock(return_value={"ok": False})),
    ):
        # When
        result = SearchResult(search_id="s1", status="running")
        await ex._fetch_and_extract(search_id="s1", serp_item=serp_item, result=result)

        # Then
        assert created["max_candidates"] == 10_000


@pytest.mark.asyncio
async def test_executor_web_citation_detection_caps_edges_per_page() -> None:
    # Given
    ex = _make_executor()
    settings = _settings_with_web_citation(
        enabled=True,
        run_on_primary_sources_only=True,
        require_useful_text=True,
        min_text_chars=10,
        max_candidates_per_page=10,
        max_edges_per_page=1,  # cap
        max_pages_per_task=0,
        create_placeholder_pages=True,
    )

    serp_item = {"url": "https://gov.example.com/page", "engine": "duckduckgo", "title": "t"}
    fetch_result = {"ok": True, "html_path": "/tmp/x.html", "page_id": "page_src"}
    extract_result = {"text": "x" * 1000, "title": "T"}

    mock_db_instance = AsyncMock()
    mock_db_instance.fetch_one = AsyncMock(return_value=None)
    mock_db_instance.insert = AsyncMock(return_value="page_target")
    mock_db_instance.execute = AsyncMock()

    with (
        patch("src.research.executor.get_settings", return_value=settings),
        patch("src.crawler.fetcher.fetch_url", AsyncMock(return_value=fetch_result)),
        patch("src.extractor.content.extract_content", AsyncMock(return_value=extract_result)),
        patch.object(Path, "read_text", return_value="<html></html>"),
        patch("src.extractor.citation_detector.CitationDetector", _FakeDetector),
        patch("src.research.executor.get_database", AsyncMock(return_value=mock_db_instance)),
        patch(
            "src.filter.nli.nli_judge",
            AsyncMock(return_value=[{"stance": "neutral", "confidence": 0.0}]),
        ),
        patch("src.filter.evidence_graph.add_claim_evidence", AsyncMock()),
        patch("src.filter.evidence_graph.add_citation", AsyncMock()) as add_citation,
        patch("src.filter.llm.llm_extract", AsyncMock(return_value={"ok": False})),
    ):
        # When
        result = SearchResult(search_id="s1", status="running")
        await ex._fetch_and_extract(search_id="s1", serp_item=serp_item, result=result)

        # Then
        assert add_citation.await_count == 1


@pytest.mark.asyncio
async def test_executor_web_citation_detection_disabled() -> None:
    # Given
    ex = _make_executor()
    settings = _settings_with_web_citation(enabled=False)

    serp_item = {"url": "https://gov.example.com/page", "engine": "duckduckgo", "title": "t"}
    fetch_result = {"ok": True, "html_path": "/tmp/x.html", "page_id": "page_src"}
    extract_result = {"text": "x" * 1000, "title": "T"}

    mock_db_instance = AsyncMock()
    mock_db_instance.fetch_one = AsyncMock(return_value=None)
    mock_db_instance.insert = AsyncMock(return_value="page_target")
    mock_db_instance.execute = AsyncMock()

    with (
        patch("src.research.executor.get_settings", return_value=settings),
        patch("src.crawler.fetcher.fetch_url", AsyncMock(return_value=fetch_result)),
        patch("src.extractor.content.extract_content", AsyncMock(return_value=extract_result)),
        patch.object(Path, "read_text", return_value="<html></html>"),
        patch("src.extractor.citation_detector.CitationDetector", _FakeDetector),
        patch("src.research.executor.get_database", AsyncMock(return_value=mock_db_instance)),
        patch(
            "src.filter.nli.nli_judge",
            AsyncMock(return_value=[{"stance": "neutral", "confidence": 0.0}]),
        ),
        patch("src.filter.evidence_graph.add_claim_evidence", AsyncMock()),
        patch("src.filter.evidence_graph.add_citation", AsyncMock()) as add_citation,
        patch("src.filter.llm.llm_extract", AsyncMock(return_value={"ok": False})),
    ):
        # When
        result = SearchResult(search_id="s1", status="running")
        await ex._fetch_and_extract(search_id="s1", serp_item=serp_item, result=result)

        # Then
        assert add_citation.await_count == 0
