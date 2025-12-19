"""
Tests for calibrate MCP tool (Phase M unified architecture).

Implements test perspectives for the calibrate tool per test-strategy.mdc.

Test Perspectives Table (Equivalence Partitioning / Boundary Value Analysis)
=============================================================================

| Case ID   | Input / Precondition                        | Perspective (Equivalence / Boundary) | Expected Result                           | Notes                    |
|-----------|---------------------------------------------|--------------------------------------|-------------------------------------------|--------------------------|
| TC-N-01   | action="add_sample" with valid data         | Equivalence – normal                 | Sample added, ok=True                     | -                        |
| TC-N-02   | action="get_stats"                          | Equivalence – normal                 | Stats returned, ok=True                   | No data required         |
| TC-N-03   | action="evaluate" with valid data           | Equivalence – normal                 | Evaluation saved, ok=True                 | -                        |
| TC-N-04   | action="get_evaluations"                    | Equivalence – normal                 | Evaluations returned, ok=True             | -                        |
| TC-N-05   | action="get_diagram_data" with valid source | Equivalence – normal                 | Diagram data returned                     | -                        |
| TC-A-01   | action=None                                 | Boundary – NULL                      | InvalidParamsError                        | MCP handler validates    |
| TC-A-02   | action="" (empty)                           | Boundary – empty                     | InvalidParamsError                        | -                        |
| TC-A-03   | action="invalid_action"                     | Equivalence – invalid                | ok=False, error=INVALID_PARAMS            | calibrate_action handles |
| TC-A-04   | add_sample: source=None                     | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-A-05   | add_sample: prediction=None                 | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-A-06   | add_sample: actual=None                     | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-A-07   | evaluate: source=None                       | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-A-08   | evaluate: predictions=None                  | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-A-09   | evaluate: labels=None                       | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-A-10   | get_diagram_data: source=None               | Boundary – NULL                      | ok=False, error=INVALID_PARAMS            | -                        |
| TC-B-01   | add_sample: prediction=0.0                  | Boundary – minimum                   | ok=True (valid probability)               | -                        |
| TC-B-02   | add_sample: prediction=1.0                  | Boundary – maximum                   | ok=True (valid probability)               | -                        |
| TC-B-03   | add_sample: actual=0                        | Boundary – minimum                   | ok=True (valid label)                     | -                        |
| TC-B-04   | add_sample: actual=1                        | Boundary – maximum                   | ok=True (valid label)                     | -                        |
| TC-B-05   | get_evaluations: limit=0                    | Boundary – zero                      | Empty list returned                       | -                        |
| TC-B-06   | evaluate: empty predictions/labels          | Boundary – empty                     | Handled gracefully                        | -                        |
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.mcp.errors import InvalidParamsError

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_calibration_sample_result() -> dict[str, Any]:
    """Mock result from add_calibration_sample."""
    return {
        "sample_added": True,
        "source": "llm_extract",
        "recalibrated": False,
        "pending_samples": 5,
        "threshold": 10,
    }


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


class TestCalibrateHandler:
    """Tests for _handle_calibrate MCP handler."""

    # =========================================================================
    # Normal Cases (TC-N-*)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_add_sample_valid(self, mock_calibration_sample_result: dict[str, Any]) -> None:
        """
        TC-N-01: action="add_sample" with valid data.

        // Given: Valid sample data (source, prediction, actual)
        // When: Calling calibrate with action="add_sample"
        // Then: Sample is added and ok=True returned
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.add_calibration_sample", new_callable=AsyncMock
        ) as mock_add:
            mock_add.return_value = mock_calibration_sample_result

            result = await _handle_calibrate(
                {
                    "action": "add_sample",
                    "data": {
                        "source": "llm_extract",
                        "prediction": 0.85,
                        "actual": 1,
                    },
                }
            )

        assert result["ok"] is True
        assert result["sample_added"] is True
        assert result["source"] == "llm_extract"
        mock_add.assert_called_once_with(
            source="llm_extract",
            predicted_prob=0.85,
            actual_label=1,
            logit=None,
        )

    @pytest.mark.asyncio
    async def test_add_sample_with_logit(
        self, mock_calibration_sample_result: dict[str, Any]
    ) -> None:
        """
        TC-N-01b: action="add_sample" with optional logit.

        // Given: Valid sample data including logit
        // When: Calling calibrate with action="add_sample" and logit
        // Then: Sample is added with logit passed
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.add_calibration_sample", new_callable=AsyncMock
        ) as mock_add:
            mock_add.return_value = mock_calibration_sample_result

            result = await _handle_calibrate(
                {
                    "action": "add_sample",
                    "data": {
                        "source": "llm_extract",
                        "prediction": 0.85,
                        "actual": 1,
                        "logit": 1.5,
                    },
                }
            )

        assert result["ok"] is True
        mock_add.assert_called_once_with(
            source="llm_extract",
            predicted_prob=0.85,
            actual_label=1,
            logit=1.5,
        )

    @pytest.mark.asyncio
    async def test_get_stats(self, mock_calibration_stats: dict[str, Any]) -> None:
        """
        TC-N-02: action="get_stats".

        // Given: Calibration system initialized
        // When: Calling calibrate with action="get_stats"
        // Then: Statistics returned with ok=True
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.get_calibration_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = mock_calibration_stats

            result = await _handle_calibrate(
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
        // When: Calling calibrate with action="get_stats" without data
        // Then: Statistics returned (data not required for get_stats)
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.get_calibration_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = mock_calibration_stats

            result = await _handle_calibrate(
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
        // When: Calling calibrate with action="evaluate"
        // Then: Evaluation saved and results returned
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.save_calibration_evaluation", new_callable=AsyncMock
        ) as mock_eval:
            mock_eval.return_value = mock_evaluation_result

            result = await _handle_calibrate(
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
        // When: Calling calibrate with action="get_evaluations"
        // Then: Evaluations list returned
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.get_calibration_evaluations", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_evaluations_result

            result = await _handle_calibrate(
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
        // When: Calling calibrate with action="get_evaluations" and since
        // Then: Filtered evaluations returned
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.get_calibration_evaluations", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_evaluations_result

            result = await _handle_calibrate(
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
        // When: Calling calibrate with action="get_diagram_data"
        // Then: Diagram data returned
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.get_reliability_diagram_data", new_callable=AsyncMock
        ) as mock_diag:
            mock_diag.return_value = mock_diagram_data

            result = await _handle_calibrate(
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
        // When: Calling calibrate with action="get_diagram_data" and evaluation_id
        // Then: Specific evaluation diagram data returned
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.get_reliability_diagram_data", new_callable=AsyncMock
        ) as mock_diag:
            mock_diag.return_value = mock_diagram_data

            result = await _handle_calibrate(
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
        // When: Calling calibrate without action
        // Then: InvalidParamsError raised
        """
        from src.mcp.server import _handle_calibrate

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_calibrate({})

        assert "action is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_action_empty(self) -> None:
        """
        TC-A-02: action="" (empty string).

        // Given: Empty action string
        // When: Calling calibrate with action=""
        // Then: InvalidParamsError raised
        """
        from src.mcp.server import _handle_calibrate

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_calibrate({"action": ""})

        assert "action is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_action_invalid(self) -> None:
        """
        TC-A-03: action="invalid_action".

        // Given: Invalid action name
        // When: Calling calibrate with unknown action
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibrate

        result = await _handle_calibrate(
            {
                "action": "invalid_action",
            }
        )

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "Unknown action" in result["message"]

    @pytest.mark.asyncio
    async def test_add_sample_source_none(self) -> None:
        """
        TC-A-04: add_sample: source=None.

        // Given: add_sample action without source
        // When: Calling calibrate
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibrate

        result = await _handle_calibrate(
            {
                "action": "add_sample",
                "data": {
                    "prediction": 0.85,
                    "actual": 1,
                },
            }
        )

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "source is required" in result["message"]

    @pytest.mark.asyncio
    async def test_add_sample_prediction_none(self) -> None:
        """
        TC-A-05: add_sample: prediction=None.

        // Given: add_sample action without prediction
        // When: Calling calibrate
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibrate

        result = await _handle_calibrate(
            {
                "action": "add_sample",
                "data": {
                    "source": "llm_extract",
                    "actual": 1,
                },
            }
        )

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "prediction is required" in result["message"]

    @pytest.mark.asyncio
    async def test_add_sample_actual_none(self) -> None:
        """
        TC-A-06: add_sample: actual=None.

        // Given: add_sample action without actual
        // When: Calling calibrate
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibrate

        result = await _handle_calibrate(
            {
                "action": "add_sample",
                "data": {
                    "source": "llm_extract",
                    "prediction": 0.85,
                },
            }
        )

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "actual is required" in result["message"]

    @pytest.mark.asyncio
    async def test_evaluate_source_none(self) -> None:
        """
        TC-A-07: evaluate: source=None.

        // Given: evaluate action without source
        // When: Calling calibrate
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibrate

        result = await _handle_calibrate(
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
        // When: Calling calibrate
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibrate

        result = await _handle_calibrate(
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
        // When: Calling calibrate
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibrate

        result = await _handle_calibrate(
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
        // When: Calling calibrate
        // Then: ok=False with error=INVALID_PARAMS
        """
        from src.mcp.server import _handle_calibrate

        result = await _handle_calibrate({"action": "get_diagram_data", "data": {}})

        assert result["ok"] is False
        assert result["error"] == "INVALID_PARAMS"
        assert "source is required" in result["message"]

    # =========================================================================
    # Boundary Cases (TC-B-*)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_add_sample_prediction_zero(
        self, mock_calibration_sample_result: dict[str, Any]
    ) -> None:
        """
        TC-B-01: add_sample: prediction=0.0 (minimum).

        // Given: Prediction at minimum value (0.0)
        // When: Calling calibrate with action="add_sample"
        // Then: Sample is added successfully
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.add_calibration_sample", new_callable=AsyncMock
        ) as mock_add:
            mock_add.return_value = mock_calibration_sample_result

            result = await _handle_calibrate(
                {
                    "action": "add_sample",
                    "data": {
                        "source": "llm_extract",
                        "prediction": 0.0,
                        "actual": 0,
                    },
                }
            )

        assert result["ok"] is True
        mock_add.assert_called_once_with(
            source="llm_extract",
            predicted_prob=0.0,
            actual_label=0,
            logit=None,
        )

    @pytest.mark.asyncio
    async def test_add_sample_prediction_one(
        self, mock_calibration_sample_result: dict[str, Any]
    ) -> None:
        """
        TC-B-02: add_sample: prediction=1.0 (maximum).

        // Given: Prediction at maximum value (1.0)
        // When: Calling calibrate with action="add_sample"
        // Then: Sample is added successfully
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.add_calibration_sample", new_callable=AsyncMock
        ) as mock_add:
            mock_add.return_value = mock_calibration_sample_result

            result = await _handle_calibrate(
                {
                    "action": "add_sample",
                    "data": {
                        "source": "llm_extract",
                        "prediction": 1.0,
                        "actual": 1,
                    },
                }
            )

        assert result["ok"] is True
        mock_add.assert_called_once_with(
            source="llm_extract",
            predicted_prob=1.0,
            actual_label=1,
            logit=None,
        )

    @pytest.mark.asyncio
    async def test_add_sample_actual_zero(
        self, mock_calibration_sample_result: dict[str, Any]
    ) -> None:
        """
        TC-B-03: add_sample: actual=0 (minimum label).

        // Given: Actual label at minimum (0)
        // When: Calling calibrate with action="add_sample"
        // Then: Sample is added successfully
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.add_calibration_sample", new_callable=AsyncMock
        ) as mock_add:
            mock_add.return_value = mock_calibration_sample_result

            result = await _handle_calibrate(
                {
                    "action": "add_sample",
                    "data": {
                        "source": "llm_extract",
                        "prediction": 0.2,
                        "actual": 0,
                    },
                }
            )

        assert result["ok"] is True
        mock_add.assert_called_once_with(
            source="llm_extract",
            predicted_prob=0.2,
            actual_label=0,
            logit=None,
        )

    @pytest.mark.asyncio
    async def test_add_sample_actual_one(
        self, mock_calibration_sample_result: dict[str, Any]
    ) -> None:
        """
        TC-B-04: add_sample: actual=1 (maximum label).

        // Given: Actual label at maximum (1)
        // When: Calling calibrate with action="add_sample"
        // Then: Sample is added successfully
        """
        from src.mcp.server import _handle_calibrate

        with patch(
            "src.utils.calibration.add_calibration_sample", new_callable=AsyncMock
        ) as mock_add:
            mock_add.return_value = mock_calibration_sample_result

            result = await _handle_calibrate(
                {
                    "action": "add_sample",
                    "data": {
                        "source": "llm_extract",
                        "prediction": 0.9,
                        "actual": 1,
                    },
                }
            )

        assert result["ok"] is True
        mock_add.assert_called_once_with(
            source="llm_extract",
            predicted_prob=0.9,
            actual_label=1,
            logit=None,
        )

    @pytest.mark.asyncio
    async def test_get_evaluations_limit_zero(self) -> None:
        """
        TC-B-05: get_evaluations: limit=0.

        // Given: limit set to zero
        // When: Calling calibrate with action="get_evaluations"
        // Then: Empty list returned
        """
        from src.mcp.server import _handle_calibrate

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

            result = await _handle_calibrate(
                {
                    "action": "get_evaluations",
                    "data": {
                        "limit": 0,
                    },
                }
            )

        assert result["ok"] is True
        assert result["evaluations"] == []


class TestCalibrateActionDirectly:
    """Tests for calibrate_action function directly (unit tests)."""

    @pytest.mark.asyncio
    async def test_calibrate_action_exception_handling(self) -> None:
        """
        TC-E-01: Exception during action execution.

        // Given: Internal function raises exception
        // When: Calling calibrate_action
        // Then: ok=False with error=INTERNAL_ERROR
        """
        from src.utils.calibration import calibrate_action

        with patch(
            "src.utils.calibration.get_calibration_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.side_effect = RuntimeError("Database connection failed")

            result = await calibrate_action("get_stats", {})

        assert result["ok"] is False
        assert result["error"] == "INTERNAL_ERROR"
        assert "Database connection failed" in result["message"]

    @pytest.mark.asyncio
    async def test_calibrate_action_data_none(self) -> None:
        """
        TC-E-02: data=None passed to calibrate_action.

        // Given: data is None
        // When: Calling calibrate_action
        // Then: Handled gracefully (uses empty dict)
        """
        from src.utils.calibration import calibrate_action

        with patch(
            "src.utils.calibration.get_calibration_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = {"current_params": {}, "history": {}}

            result = await calibrate_action("get_stats", None)

        assert result["ok"] is True

        with patch(
            "src.utils.calibration.get_calibration_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = {"current_params": {}, "history": {}}

            result = await calibrate_action("get_stats", None)

        assert result["ok"] is True
