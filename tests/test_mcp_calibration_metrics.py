"""
Tests for calibration_metrics MCP tool.

Per ADR-0003: MCP over CLI / REST API.

Renamed from calibrate. add_sample action was removed.
Use feedback(edge_correct) for ground-truth collection.

Phase 6: evaluate and get_diagram_data actions were removed.
Use scripts for batch evaluation and visualization (S_LORA.md).

Test Perspectives Table (Equivalence Partitioning / Boundary Value Analysis)
=============================================================================

| Case ID   | Input / Precondition                        | Perspective (Equivalence / Boundary) | Expected Result                           | Notes                    |
|-----------|---------------------------------------------|--------------------------------------|-------------------------------------------|--------------------------|
| TC-N-01   | action="get_stats"                          | Equivalence – normal                 | Stats returned, ok=True                   | No data required         |
| TC-N-02   | action="get_evaluations"                    | Equivalence – normal                 | Evaluations returned, ok=True             | -                        |
| TC-A-01   | action=None                                 | Boundary – NULL                      | InvalidParamsError                        | MCP handler validates    |
| TC-A-02   | action="" (empty)                           | Boundary – empty                     | InvalidParamsError                        | -                        |
| TC-A-03   | action="invalid_action"                     | Equivalence – invalid                | ok=False, error=INVALID_PARAMS            | covers unknown actions   |
| TC-B-01   | get_evaluations: limit=0                    | Boundary – zero                      | Empty list returned                       | -                        |

Note: Removed action tests (TC-A-04~06) intentionally omitted - covered by TC-A-03.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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


# =============================================================================
# Test Classes
# =============================================================================


class TestCalibrationMetricsHandler:
    """Tests for _handle_calibration_metrics MCP handler."""

    # =========================================================================
    # Normal Cases (TC-N-*)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_stats(self, mock_calibration_stats: dict[str, Any]) -> None:
        """
        TC-N-01: action="get_stats".

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
        assert result["action"] == "get_stats"
        assert "current_params" in result
        assert "history" in result
        mock_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_stats_no_data(self, mock_calibration_stats: dict[str, Any]) -> None:
        """
        TC-N-01b: action="get_stats" with no data field.

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
    async def test_get_evaluations_valid(self) -> None:
        """
        TC-N-02: action="get_evaluations".

        // Given: Evaluation history exists in database
        // When: Calling calibration_metrics with action="get_evaluations"
        // Then: Evaluations list returned with ok=True
        """
        from src.mcp.server import _handle_calibration_metrics

        # Mock database cursor and connection
        mock_cursor = MagicMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.fetchone = AsyncMock(return_value=(0,))

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("src.storage.database.get_database", new_callable=AsyncMock) as mock_get_db:
            mock_get_db.return_value = mock_db

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
        assert result["action"] == "get_evaluations"
        assert "evaluations" in result
        assert "total_count" in result
        assert result["filter_source"] == "llm_extract"

    @pytest.mark.asyncio
    async def test_get_evaluations_with_since(self) -> None:
        """
        TC-N-02b: action="get_evaluations" with since filter.

        // Given: Evaluation history exists
        // When: Calling calibration_metrics with action="get_evaluations" and since
        // Then: Filtered evaluations returned
        """
        from src.mcp.server import _handle_calibration_metrics

        # Mock database cursor and connection
        mock_cursor = MagicMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.fetchone = AsyncMock(return_value=(0,))

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("src.storage.database.get_database", new_callable=AsyncMock) as mock_get_db:
            mock_get_db.return_value = mock_db

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
        assert result["filter_since"] == "2024-01-01T00:00:00Z"

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

    # NOTE: Tests for removed actions (evaluate, get_diagram_data, add_sample) are
    # intentionally omitted as they are not essential - they only verify that calling
    # a non-existent action returns an error, which is already covered by test_action_invalid.

    # =========================================================================
    # Boundary Cases (TC-B-*)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_evaluations_limit_zero(self) -> None:
        """
        TC-B-01: get_evaluations: limit=0.

        // Given: limit set to zero
        // When: Calling calibration_metrics with action="get_evaluations"
        // Then: Empty list returned
        """
        from src.mcp.server import _handle_calibration_metrics

        # Mock database cursor and connection
        mock_cursor = MagicMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.fetchone = AsyncMock(return_value=(0,))

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("src.storage.database.get_database", new_callable=AsyncMock) as mock_get_db:
            mock_get_db.return_value = mock_db

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

    @pytest.mark.asyncio
    async def test_get_evaluations_returns_action_field(self) -> None:
        """
        TC-N-02c: get_evaluations includes action field in response.

        // Given: Valid get_evaluations request
        // When: Calling calibration_metrics_action
        // Then: Response includes action="get_evaluations"
        """
        from src.utils.calibration import calibration_metrics_action

        # Mock database cursor and connection
        mock_cursor = MagicMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.fetchone = AsyncMock(return_value=(0,))

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("src.storage.database.get_database", new_callable=AsyncMock) as mock_get_db:
            mock_get_db.return_value = mock_db

            result = await calibration_metrics_action(
                "get_evaluations", {"source": "test", "limit": 10}
            )

        assert result["ok"] is True
        assert result["action"] == "get_evaluations"
