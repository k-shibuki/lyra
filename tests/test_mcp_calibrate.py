"""
Tests for calibration_metrics MCP tool.

Per ADR-0003: MCP over CLI / REST API.

Renamed from calibrate. add_sample action was removed.
Use feedback(edge_correct) for ground-truth collection.

Test Perspectives Table (Equivalence Partitioning / Boundary Value Analysis)
=============================================================================

| Case ID   | Input / Precondition                        | Perspective (Equivalence / Boundary) | Expected Result                           | Notes                    |
|-----------|---------------------------------------------|--------------------------------------|-------------------------------------------|--------------------------|
| TC-N-02   | action="get_stats"                          | Equivalence – normal                 | Stats returned, ok=True                   | No data required         |
| TC-N-03   | action="evaluate" with valid data           | Equivalence – normal                 | Evaluation saved, ok=True                 | -                        |
| TC-N-04   | action="get_evaluations"                    | Equivalence – normal                 | Evaluations returned, ok=True             | -                        |
| TC-N-05   | action="get_diagram_data" with valid source | Equivalence – normal                 | Diagram data returned                     | -                        |
| TC-A-01   | action=None                                 | Boundary – NULL                      | InvalidParamsError                        | MCP handler validates    |
| TC-A-02   | action="" (empty)                           | Boundary – empty                     | InvalidParamsError                        | -                        |
| TC-A-03   | action="invalid_action"                     | Equivalence – invalid                | ok=False, error=INVALID_PARAMS            | calibration_metrics handles |
| TC-A-07   | evaluate: source=None                       | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-A-08   | evaluate: predictions=None                  | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-A-09   | evaluate: labels=None                       | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-A-10   | get_diagram_data: source=None               | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-B-05   | get_evaluations: limit=0                    | Boundary – zero                      | Empty list returned                       | -                        |
| TC-CM-08 | action="add_sample" | Abnormal – removed action | ok=False, Unknown action | BREAKING: |
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.mcp.errors import InvalidParamsError

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_calibration_stats() -> dict[str, Any]:
    """Mock result from get_calibration_stats."""
    return {
        "current_params": {
            "llm_extract": {
                "version": 3,
                "method": "temperature",
                "brier_after": 0.12,
                "samples_used": 150,
            }
        },
        "history": {
            "sources": {
                "llm_extract": {
                    "history_size": 3,
                    "latest_version": 3,
                    "latest_brier": 0.12,
                }
            },
            "total_rollbacks": 1,
            "max_history_per_source": 10,
        },
        "recalibration_threshold": 10,
        "degradation_threshold": 0.05,
    }


@pytest.fixture
def mock_evaluation_result() -> dict[str, Any]:
    """Mock result from save_calibration_evaluation."""
    return {
        "ok": True,
        "evaluation_id": "eval_abc123",
        "source": "llm_extract",
        "brier_score": 0.15,
        "brier_score_calibrated": 0.12,
        "improvement_ratio": 0.20,
        "expected_calibration_error": 0.08,
        "samples_evaluated": 100,
        "bins": [],
        "calibration_version": 3,
        "evaluated_at": "2024-01-15T10:00:00+00:00",
        "created_at": "2024-01-15T10:00:00+00:00",
    }


@pytest.fixture
def mock_evaluations_result() -> dict[str, Any]:
    """Mock result from get_calibration_evaluations."""
    return {
        "ok": True,
        "evaluations": [
            {
                "evaluation_id": "eval_abc123",
                "source": "llm_extract",
                "brier_score": 0.15,
                "brier_score_calibrated": 0.12,
                "improvement_ratio": 0.20,
                "expected_calibration_error": 0.08,
                "samples_evaluated": 100,
            }
        ],
        "total_count": 1,
        "filter_source": "llm_extract",
        "filter_since": None,
        "returned_count": 1,
    }


@pytest.fixture
def mock_diagram_data() -> dict[str, Any]:
    """Mock result from get_reliability_diagram_data."""
    return {
        "ok": True,
        "source": "llm_extract",
        "evaluation_id": "eval_abc123",
        "n_bins": 10,
        "bins": [
            {
                "bin_lower": 0.0,
                "bin_upper": 0.1,
                "count": 5,
                "accuracy": 0.0,
                "confidence": 0.05,
                "gap": 0.05,
            },
            {
                "bin_lower": 0.1,
                "bin_upper": 0.2,
                "count": 10,
                "accuracy": 0.1,
                "confidence": 0.15,
                "gap": 0.05,
            },
        ],
        "overall_ece": 0.08,
        "brier_score": 0.15,
        "brier_score_calibrated": 0.12,
        "evaluated_at": "2024-01-15T10:00:00+00:00",
    }


# =============================================================================
# Test Classes
# =============================================================================


class TestCalibrationMetricsHandler:
    """Tests for _handle_calibration_metrics MCP handler ."""

    # =========================================================================
    # Normal Cases (TC-N-*)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_stats(self, mock_calibration_stats: dict[str, Any]) -> None:
        """
        TC-N-02: action="get_stats".

        // Given: Calibration system initialized
        // When: Calling calibration_metrics with action="get_stats"
        // Then: Statistics returned with ok=True
        """
        from src.mcp.server import _handle_calibration_metrics

        with patch(
            "src.utils.calibration.get_calibration_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = mock_calibration_stats

            result = await _handle_calibration_metrics(
                {
                    "action": "get_stats",
                }
            )

        assert result["ok"] is True
        assert "current_params" in result
        assert "history" in result
        mock_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_stats_no_data(self, mock_calibration_stats: dict[str, Any]) -> None:
        """
        TC-N-02b: action="get_stats" with no data field.

        // Given: Calibration system initialized
        // When: Calling calibration_metrics with action="get_stats" without data
        // Then: Statistics returned (data not required for get_stats)
        """
        from src.mcp.server import _handle_calibration_metrics

        with patch(
            "src.utils.calibration.get_calibration_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = mock_calibration_stats

            result = await _handle_calibration_metrics(
                {
                    "action": "get_stats",
                    # No "data" field
                }
            )

        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_evaluate_valid(self, mock_evaluation_result: dict[str, Any]) -> None:
        """
        TC-N-03: action="evaluate" with valid data.

        // Given: Valid predictions and labels arrays
        // When: Calling calibration_metrics with action="evaluate"
        // Then: Evaluation saved and results returned
        """
        from src.mcp.server import _handle_calibration_metrics

        with patch(
            "src.utils.calibration.save_calibration_evaluation", new_callable=AsyncMock
        ) as mock_eval:
            mock_eval.return_value = mock_evaluation_result

            result = await _handle_calibration_metrics(
                {
                    "action": "evaluate",
                    "data": {
                        "source": "llm_extract",
                        "predictions": [0.8, 0.6, 0.9],
                        "labels": [1, 0, 1],
                    },
                }
            )

        assert result["ok"] is True
        assert "evaluation_id" in result
        mock_eval.assert_called_once_with(
            source="llm_extract",
            predictions=[0.8, 0.6, 0.9],
            labels=[1, 0, 1],
        )

    @pytest.mark.asyncio
    async def test_get_evaluations_valid(self, mock_evaluations_result: dict[str, Any]) -> None:
        """
        TC-N-04: action="get_evaluations".

        // Given: Evaluation history exists
        // When: Calling calibration_metrics with action="get_evaluations"
        // Then: Evaluations list returned
        """
        from src.mcp.server import _handle_calibration_metrics

        with patch(
            "src.utils.calibration.get_calibration_evaluations", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_evaluations_result

            result = await _handle_calibration_metrics(
                {
                    "action": "get_evaluations",
                    "data": {
                        "source": "llm_extract",
                        "limit": 10,
                    },
                }
            )

        assert result["ok"] is True
        assert "evaluations" in result
        mock_get.assert_called_once_with(
            source="llm_extract",
            limit=10,
            since=None,
        )

    @pytest.mark.asyncio
    async def test_get_evaluations_with_since(
        self, mock_evaluations_result: dict[str, Any]
    ) -> None:
        """
        TC-N-04b: action="get_evaluations" with since filter.

        // Given: Evaluation history exists
        // When: Calling calibration_metrics with action="get_evaluations" and since
        // Then: Filtered evaluations returned
        """
        from src.mcp.server import _handle_calibration_metrics

        with patch(
            "src.utils.calibration.get_calibration_evaluations", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_evaluations_result

            result = await _handle_calibration_metrics(
                {
                    "action": "get_evaluations",
                    "data": {
                        "source": "llm_extract",
                        "since": "2024-01-01T00:00:00Z",
                    },
                }
            )

        assert result["ok"] is True
        mock_get.assert_called_once_with(
            source="llm_extract",
            limit=50,  # Default
            since="2024-01-01T00:00:00Z",
        )

    @pytest.mark.asyncio
    async def test_get_diagram_data_valid(self, mock_diagram_data: dict[str, Any]) -> None:
        """
        TC-N-05: action="get_diagram_data" with valid source.

        // Given: Evaluation exists for source
        // When: Calling calibration_metrics with action="get_diagram_data"
        // Then: Diagram data returned
        """
        from src.mcp.server import _handle_calibration_metrics

        with patch(
            "src.utils.calibration.get_reliability_diagram_data", new_callable=AsyncMock
        ) as mock_diag:
            mock_diag.return_value = mock_diagram_data

            result = await _handle_calibration_metrics(
                {
                    "action": "get_diagram_data",
                    "data": {
                        "source": "llm_extract",
                    },
                }
            )

        assert result["ok"] is True
        assert "bins" in result
        mock_diag.assert_called_once_with(
            source="llm_extract",
            evaluation_id=None,
        )

    @pytest.mark.asyncio
    async def test_get_diagram_data_with_evaluation_id(
        self, mock_diagram_data: dict[str, Any]
    ) -> None:
        """
        TC-N-05b: action="get_diagram_data" with evaluation_id.

        // Given: Specific evaluation exists
        // When: Calling calibration_metrics with action="get_diagram_data" and evaluation_id
        // Then: Specific evaluation diagram data returned
        """
        from src.mcp.server import _handle_calibration_metrics

        with patch(
            "src.utils.calibration.get_reliability_diagram_data", new_callable=AsyncMock
        ) as mock_diag:
            mock_diag.return_value = mock_diagram_data

            result = await _handle_calibration_metrics(
                {
                    "action": "get_diagram_data",
                    "data": {
                        "source": "llm_extract",
                        "evaluation_id": "eval_abc123",
                    },
                }
            )

        assert result["ok"] is True
        mock_diag.assert_called_once_with(
            source="llm_extract",
            evaluation_id="eval_abc123",
        )

    # =========================================================================
    # Abnormal Cases (TC-A-*)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_action_none(self) -> None:
        """
        TC-A-01: action=None.

        // Given: No action specified
        // When: Calling calibration_metrics without action
        // Then: InvalidParamsError raised
        """
        from src.mcp.server import _handle_calibration_metrics

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_calibration_metrics({})

        assert "action is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_action_empty(self) -> None:
        """
        TC-A-02: action="" (empty string).

        // Given: Empty action string
        // When: Calling calibration_metrics with action=""
        // Then: InvalidParamsError raised
        """
        from src.mcp.server import _handle_calibration_metrics

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_calibration_metrics({"action": ""})

        assert "action is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_action_invalid(self) -> None:
        """
        TC-A-03: action="invalid_action".

        // Given: Invalid action name
        // When: Calling calibration_metrics with unknown action
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibration_metrics

        result = await _handle_calibration_metrics(
            {
                "action": "invalid_action",
            }
        )

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "Unknown action" in result["message"]

    @pytest.mark.asyncio
    async def test_add_sample_removed(self) -> None:
        """
        TC-CM-08: add_sample action was removed.

        // Given: Trying to use the removed add_sample action
        // When: Calling calibration_metrics with action="add_sample"
        // Then: ok=False with error=INVALID_PARAMS, "Unknown action"
        """
        from src.mcp.server import _handle_calibration_metrics

        result = await _handle_calibration_metrics(
            {
                "action": "add_sample",
                "data": {
                    "source": "llm_extract",
                    "prediction": 0.85,
                    "actual": 1,
                },
            }
        )

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "Unknown action" in result["message"]
        assert "add_sample" in result["message"]

    @pytest.mark.asyncio
    async def test_evaluate_source_none(self) -> None:
        """
        TC-A-07: evaluate: source=None.

        // Given: evaluate action without source
        // When: Calling calibration_metrics
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibration_metrics

        result = await _handle_calibration_metrics(
            {
                "action": "evaluate",
                "data": {
                    "predictions": [0.8, 0.6],
                    "labels": [1, 0],
                },
            }
        )

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "source is required" in result["message"]

    @pytest.mark.asyncio
    async def test_evaluate_predictions_none(self) -> None:
        """
        TC-A-08: evaluate: predictions=None.

        // Given: evaluate action without predictions
        // When: Calling calibration_metrics
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibration_metrics

        result = await _handle_calibration_metrics(
            {
                "action": "evaluate",
                "data": {
                    "source": "llm_extract",
                    "labels": [1, 0],
                },
            }
        )

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "predictions is required" in result["message"]

    @pytest.mark.asyncio
    async def test_evaluate_labels_none(self) -> None:
        """
        TC-A-09: evaluate: labels=None.

        // Given: evaluate action without labels
        // When: Calling calibration_metrics
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibration_metrics

        result = await _handle_calibration_metrics(
            {
                "action": "evaluate",
                "data": {
                    "source": "llm_extract",
                    "predictions": [0.8, 0.6],
                },
            }
        )

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "labels is required" in result["message"]

    @pytest.mark.asyncio
    async def test_get_diagram_data_source_none(self) -> None:
        """
        TC-A-10: get_diagram_data: source=None.

        // Given: get_diagram_data action without source
        // When: Calling calibration_metrics
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibration_metrics

        result = await _handle_calibration_metrics({"action": "get_diagram_data", "data": {}})

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "source is required" in result["message"]

    # =========================================================================
    # Boundary Cases (TC-B-*)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_evaluations_limit_zero(self) -> None:
        """
        TC-B-05: get_evaluations: limit=0.

        // Given: limit set to zero
        // When: Calling calibration_metrics with action="get_evaluations"
        // Then: Empty list returned
        """
        from src.mcp.server import _handle_calibration_metrics

        empty_result = {
            "ok": True,
            "evaluations": [],
            "total_count": 0,
            "filter_source": None,
            "filter_since": None,
            "returned_count": 0,
        }

        with patch(
            "src.utils.calibration.get_calibration_evaluations", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = empty_result

            result = await _handle_calibration_metrics(
                {
                    "action": "get_evaluations",
                    "data": {
                        "limit": 0,
                    },
                }
            )

        assert result["ok"] is True
        assert result["evaluations"] == []


class TestCalibrationMetricsActionDirectly:
    """Tests for calibration_metrics_action function directly (unit tests)."""

    @pytest.mark.asyncio
    async def test_calibration_metrics_action_exception_handling(self) -> None:
        """
        TC-E-01: Exception during action execution.

        // Given: Internal function raises exception
        // When: Calling calibration_metrics_action
        // Then: ok=False with error=INTERNAL_ERROR
        """
        from src.utils.calibration import calibration_metrics_action

        with patch(
            "src.utils.calibration.get_calibration_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.side_effect = RuntimeError("Database connection failed")

            result = await calibration_metrics_action("get_stats", {})

        assert result["ok"] is False
        assert result["error"] == "INTERNAL_ERROR"
        assert "Database connection failed" in result["message"]

    @pytest.mark.asyncio
    async def test_calibration_metrics_action_data_none(self) -> None:
        """
        TC-E-02: data=None passed to calibration_metrics_action.

        // Given: data is None
        // When: Calling calibration_metrics_action
        // Then: Handled gracefully (uses empty dict)
        """
        from src.utils.calibration import calibration_metrics_action

        with patch(
            "src.utils.calibration.get_calibration_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = {"current_params": {}, "history": {}}

            result = await calibration_metrics_action("get_stats", None)

        assert result["ok"] is True
