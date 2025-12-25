"""
Tests for b web citation detection policy (settings-driven gating).

This module focuses on the pure decision logic in SearchExecutor to avoid I/O.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-WCD-N-01 | enabled=True, primary=True, useful=True, budget_pages=0 | Equivalence – normal | returns True | Default behavior (unlimited pages) |
| TC-WCD-N-02 | enabled=True, primary=False, primary_only=True | Equivalence – normal | returns False | Enforces primary-only |
| TC-WCD-N-03 | enabled=True, useful=False, require_useful=True | Equivalence – normal | returns False | Enforces usefulness gate |
| TC-WCD-B-01 | budget_pages=1, processed=0 | Boundary – min/0 | returns True | First page allowed |
| TC-WCD-B-02 | budget_pages=1, processed=1 | Boundary – max | returns False | Budget exhausted |
| TC-WCD-A-01 | enabled=False | Abnormal – disabled | returns False | Global off switch |
"""

from __future__ import annotations

from src.research.executor import SearchExecutor
from src.research.state import ExplorationState


def _make_executor() -> SearchExecutor:
    state = ExplorationState(task_id="test_task")
    return SearchExecutor(task_id="test_task", state=state)


def test_wcd_allows_default_case() -> None:
    # Given
    ex = _make_executor()

    # When
    ok = ex._should_run_web_citation_detection(
        enabled=True,
        budget_pages_per_task=0,
        run_on_primary_sources_only=True,
        require_useful_text=True,
        is_primary=True,
        is_useful=True,
    )

    # Then
    assert ok is True


def test_wcd_blocks_non_primary_when_primary_only() -> None:
    # Given
    ex = _make_executor()

    # When
    ok = ex._should_run_web_citation_detection(
        enabled=True,
        budget_pages_per_task=0,
        run_on_primary_sources_only=True,
        require_useful_text=False,
        is_primary=False,
        is_useful=True,
    )

    # Then
    assert ok is False


def test_wcd_blocks_non_useful_when_required() -> None:
    # Given
    ex = _make_executor()

    # When
    ok = ex._should_run_web_citation_detection(
        enabled=True,
        budget_pages_per_task=0,
        run_on_primary_sources_only=False,
        require_useful_text=True,
        is_primary=True,
        is_useful=False,
    )

    # Then
    assert ok is False


def test_wcd_budget_allows_first_page() -> None:
    # Given
    ex = _make_executor()
    ex._web_citation_pages_processed = 0

    # When
    ok = ex._should_run_web_citation_detection(
        enabled=True,
        budget_pages_per_task=1,
        run_on_primary_sources_only=False,
        require_useful_text=False,
        is_primary=False,
        is_useful=False,
    )

    # Then
    assert ok is True


def test_wcd_budget_blocks_after_exhausted() -> None:
    # Given
    ex = _make_executor()
    ex._web_citation_pages_processed = 1

    # When
    ok = ex._should_run_web_citation_detection(
        enabled=True,
        budget_pages_per_task=1,
        run_on_primary_sources_only=False,
        require_useful_text=False,
        is_primary=True,
        is_useful=True,
    )

    # Then
    assert ok is False


def test_wcd_disabled_returns_false() -> None:
    # Given
    ex = _make_executor()

    # When
    ok = ex._should_run_web_citation_detection(
        enabled=False,
        budget_pages_per_task=0,
        run_on_primary_sources_only=False,
        require_useful_text=False,
        is_primary=True,
        is_useful=True,
    )

    # Then
    assert ok is False
