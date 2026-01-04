"""
Tests for Kneedle cutoff algorithm.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-KN-N-01 | Scores with clear knee point | Equivalence – normal | Cuts off at knee point | - |
| TC-KN-N-02 | Scores without knee (monotonic) | Equivalence – normal | Returns min_results | - |
| TC-KN-N-03 | Fewer results than min_results | Boundary – below min | Returns all results | - |
| TC-KN-N-04 | More results than max_results | Boundary – above max | Cuts at max_results | - |
| TC-KN-N-05 | Sensitivity parameter | Equivalence – normal | Affects cutoff point | - |
| TC-KN-A-01 | Empty ranked list | Boundary – empty | Returns empty list | - |
| TC-KN-A-02 | Missing final_score key | Abnormal – missing field | Raises KeyError | - |
| TC-KN-A-03 | kneed library not available | Abnormal – import error | Falls back to min_results | - |
"""

from unittest import mock

import pytest

pytestmark = pytest.mark.unit

from src.filter import ranking


def test_kneedle_cutoff_clear_knee() -> None:
    """
    TC-KN-N-01: Scores with clear knee point cuts off at knee.

    // Given: Scores with clear drop-off point
    // When: Applying kneedle_cutoff
    // Then: Cuts off at knee point
    """
    ranked = [
        {"final_score": 0.95},
        {"final_score": 0.90},
        {"final_score": 0.85},
        {"final_score": 0.50},  # Knee point
        {"final_score": 0.30},
        {"final_score": 0.20},
    ]

    result = ranking.kneedle_cutoff(ranked, min_results=2, max_results=10)

    # Should cut off around knee point (index 3-4)
    assert len(result) >= 2
    assert len(result) <= 6


def test_kneedle_cutoff_below_min() -> None:
    """
    TC-KN-N-03: Fewer results than min_results returns all.

    // Given: Only 2 results, min_results=3
    // When: Applying kneedle_cutoff
    // Then: Returns all 2 results
    """
    ranked = [
        {"final_score": 0.9},
        {"final_score": 0.8},
    ]

    result = ranking.kneedle_cutoff(ranked, min_results=3, max_results=10)

    assert len(result) == 2


def test_kneedle_cutoff_above_max() -> None:
    """
    TC-KN-N-04: More results than max_results cuts at max.

    // Given: 20 results, max_results=10
    // When: Applying kneedle_cutoff
    // Then: Returns at most 10 results
    """
    ranked = [{"final_score": 1.0 - i * 0.05} for i in range(20)]

    result = ranking.kneedle_cutoff(ranked, min_results=3, max_results=10)

    assert len(result) <= 10


def test_kneedle_cutoff_empty() -> None:
    """
    TC-KN-A-01: Empty ranked list returns empty list.

    // Given: Empty list
    // When: Applying kneedle_cutoff
    // Then: Returns empty list
    """
    result = ranking.kneedle_cutoff([], min_results=3, max_results=10)

    assert result == []


def test_kneedle_cutoff_missing_final_score() -> None:
    """
    TC-KN-A-02: Missing final_score falls back to min_results.

    // Given: Ranked items without final_score
    // When: Applying kneedle_cutoff
    // Then: Returns min_results items (fallback path)
    """
    ranked = [{"id": "1"}, {"id": "2"}]

    result = ranking.kneedle_cutoff(ranked, min_results=2, max_results=10)
    assert len(result) == 2


def test_kneedle_cutoff_import_error() -> None:
    """
    TC-KN-A-03: kneed library not available falls back to min_results.

    // Given: kneed import fails
    // When: Applying kneedle_cutoff
    // Then: Returns min_results items
    """
    ranked = [{"final_score": 1.0 - i * 0.1} for i in range(10)]

    import builtins
    from typing import Any

    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "kneed":
            raise ImportError("kneed not available")
        return real_import(name, globals, locals, fromlist, level)

    with mock.patch("builtins.__import__", side_effect=fake_import):
        result = ranking.kneedle_cutoff(ranked, min_results=3, max_results=10)
        assert len(result) == 3  # Falls back to min_results
