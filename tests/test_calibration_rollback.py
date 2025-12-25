"""
Tests for calibration_rollback MCP tool.

Per ADR-0011: LoRA Fine-tuning Strategy.

Implements test perspectives for calibration_rollback tool per test-strategy.mdc.
Renamed from calibrate_rollback.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.mcp.errors import (
    CalibrationError,
    InvalidParamsError,
)


class TestCalibrationRollbackHandler:
    """Tests for _handle_calibration_rollback MCP handler ."""

    @pytest.fixture
    def mock_calibrator(self) -> MagicMock:
        """Create mock calibrator with default behavior."""
        calibrator = MagicMock()

        # Default: has current params at version 3
        current_params = MagicMock()
        current_params.version = 3
        current_params.brier_after = 0.15
        current_params.method = "temperature"
        calibrator.get_params.return_value = current_params

        # Default: rollback_to_version succeeds
        rollback_params = MagicMock()
        rollback_params.version = 2
        rollback_params.brier_after = 0.12
        rollback_params.method = "temperature"
        calibrator.rollback_to_version.return_value = rollback_params

        return calibrator

    @pytest.mark.asyncio
    async def test_rollback_to_previous_version(self, mock_calibrator: MagicMock) -> None:
        """
        TC-N-01: Valid source with history.

        // Given: Source with calibration history
        // When: Calling calibration_rollback without version
        // Then: Rollback to previous version succeeds
        """
        from src.mcp.server import _handle_calibration_rollback

        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            result = await _handle_calibration_rollback(
                {
                    "source": "llm_extract",
                }
            )

        assert result["ok"] is True
        assert result["source"] == "llm_extract"
        assert result["rolled_back_to"] == 2
        assert result["previous_version"] == 3

        # Verify rollback_to_version was called with calculated target version
        mock_calibrator.rollback_to_version.assert_called_once_with(
            source="llm_extract",
            version=2,  # previous_version - 1
            reason="Manual rollback",
        )

    @pytest.mark.asyncio
    async def test_rollback_to_specific_version(self, mock_calibrator: MagicMock) -> None:
        """
        TC-N-02: Valid source with specific version.

        // Given: Source with multiple versions
        // When: Calling calibration_rollback with version=1
        // Then: Rollback to version 1 succeeds
        """
        from src.mcp.server import _handle_calibration_rollback

        # Override rollback result for version 1
        rollback_params = MagicMock()
        rollback_params.version = 1
        rollback_params.brier_after = 0.10
        rollback_params.method = "platt"
        mock_calibrator.rollback_to_version.return_value = rollback_params

        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            result = await _handle_calibration_rollback(
                {
                    "source": "llm_extract",
                    "version": 1,
                }
            )

        assert result["ok"] is True
        assert result["rolled_back_to"] == 1
        assert result["method"] == "platt"

        mock_calibrator.rollback_to_version.assert_called_once_with(
            source="llm_extract",
            version=1,
            reason="Manual rollback",
        )

    @pytest.mark.asyncio
    async def test_rollback_with_reason(self, mock_calibrator: MagicMock) -> None:
        """
        TC-N-03: Valid source with reason.

        // Given: Source with calibration
        // When: Calling calibration_rollback with reason
        // Then: Reason included in response and passed to rollback
        """
        from src.mcp.server import _handle_calibration_rollback

        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            result = await _handle_calibration_rollback(
                {
                    "source": "nli_judge",
                    "reason": "Brier score degradation detected",
                }
            )

        assert result["ok"] is True
        assert result["reason"] == "Brier score degradation detected"

        mock_calibrator.rollback_to_version.assert_called_once_with(
            source="nli_judge",
            version=2,  # previous_version (3) - 1
            reason="Brier score degradation detected",
        )

    @pytest.mark.asyncio
    async def test_missing_source_parameter(self) -> None:
        """
        TC-A-01: Missing source parameter.

        // Given: No source in arguments
        // When: Calling calibration_rollback
        // Then: InvalidParamsError raised
        """
        from src.mcp.server import _handle_calibration_rollback

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_calibration_rollback({})

        assert exc_info.value.code.value == "INVALID_PARAMS"
        assert "source is required" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_empty_source_string(self) -> None:
        """
        TC-A-02: Empty source string.

        // Given: source=""
        // When: Calling calibration_rollback
        // Then: InvalidParamsError raised
        """
        from src.mcp.server import _handle_calibration_rollback

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_calibration_rollback({"source": ""})

        assert exc_info.value.code.value == "INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_source_with_no_calibration(self, mock_calibrator: MagicMock) -> None:
        """
        TC-A-03: Source with no calibration history.

        // Given: Source never calibrated (get_params returns None)
        // When: Calling calibration_rollback
        // Then: CalibrationError raised
        """
        from src.mcp.server import _handle_calibration_rollback

        # No calibration history
        mock_calibrator.get_params.return_value = None

        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            with pytest.raises(CalibrationError) as exc_info:
                await _handle_calibration_rollback({"source": "unknown_source"})

        assert exc_info.value.code.value == "CALIBRATION_ERROR"
        assert "no previous version" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_source_with_only_one_version(self, mock_calibrator: MagicMock) -> None:
        """
        TC-A-04: Source with only one version.

        // Given: Source with single calibration version (version=1)
        // When: Calling calibration_rollback without version
        // Then: CalibrationError raised (no previous)
        """
        from src.mcp.server import _handle_calibration_rollback

        # Only version 1 exists
        current_params = MagicMock()
        current_params.version = 1
        mock_calibrator.get_params.return_value = current_params

        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            with pytest.raises(CalibrationError) as exc_info:
                await _handle_calibration_rollback({"source": "llm_extract"})

        assert exc_info.value.code.value == "CALIBRATION_ERROR"
        assert "no previous version" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_nonexistent_target_version(self, mock_calibrator: MagicMock) -> None:
        """
        TC-A-05: Non-existent target version.

        // Given: Target version not in history
        // When: Calling calibration_rollback with invalid version
        // Then: CalibrationError raised
        """
        from src.mcp.server import _handle_calibration_rollback

        # rollback_to_version raises ValueError for invalid version
        mock_calibrator.rollback_to_version.side_effect = ValueError("Version 999 not found")

        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            with pytest.raises(CalibrationError) as exc_info:
                await _handle_calibration_rollback(
                    {
                        "source": "llm_extract",
                        "version": 999,
                    }
                )

        assert exc_info.value.code.value == "CALIBRATION_ERROR"

    @pytest.mark.asyncio
    async def test_rollback_returns_none(self, mock_calibrator: MagicMock) -> None:
        """
        TC-A-06: Rollback returns None.

        // Given: rollback_to_version returns None
        // When: Calling calibration_rollback
        // Then: CalibrationError raised
        """
        from src.mcp.server import _handle_calibration_rollback

        mock_calibrator.rollback_to_version.return_value = None

        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            with pytest.raises(CalibrationError) as exc_info:
                await _handle_calibration_rollback(
                    {
                        "source": "llm_extract",
                        "version": 1,
                    }
                )

        assert exc_info.value.code.value == "CALIBRATION_ERROR"
        assert "not found" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_response_includes_brier_and_method(self, mock_calibrator: MagicMock) -> None:
        """
        Test that response includes brier_after and method fields.

        // Given: Successful rollback
        // When: Checking response
        // Then: brier_after and method are included
        """
        from src.mcp.server import _handle_calibration_rollback

        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            result = await _handle_calibration_rollback(
                {
                    "source": "llm_extract",
                }
            )

        assert "brier_after" in result
        assert "method" in result
        assert result["brier_after"] == 0.12
        assert result["method"] == "temperature"


class TestCallToolErrorHandling:
    """Tests for call_tool error handling with MCPError."""

    @pytest.mark.asyncio
    async def test_mcp_error_returns_structured_response(self) -> None:
        """
        Test that MCPError is converted to structured response.

        // Given: Handler that raises MCPError (missing source parameter)
        // When: Calling via call_tool
        // Then: Returns structured error response with INVALID_PARAMS
        """
        import json

        from src.mcp.server import call_tool

        # This should raise InvalidParamsError (source is required)
        result = await call_tool("calibration_rollback", {})

        assert len(result) == 1
        response = json.loads(result[0].text)

        assert response["ok"] is False
        assert response["error_code"] == "INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped_as_internal(self) -> None:
        """
        Test that unexpected errors are wrapped as INTERNAL_ERROR.

        // Given: Handler that raises unexpected exception
        // When: Calling via call_tool
        // Then: Returns INTERNAL_ERROR with error_id
        """
        import json

        from src.mcp.server import call_tool

        with patch("src.mcp.server._dispatch_tool", side_effect=RuntimeError("Unexpected")):
            result = await call_tool("some_tool", {})

        assert len(result) == 1
        response = json.loads(result[0].text)

        assert response["ok"] is False
        assert response["error_code"] == "INTERNAL_ERROR"
        assert "error_id" in response
        assert response["error_id"].startswith("err_")


class TestToolDefinition:
    """Tests for calibrate_rollback tool definition."""

    def test_calibrate_rollback_in_tools(self) -> None:
        """
        Test that calibration_rollback is defined in TOOLS .

        // Given: TOOLS list
        // When: Searching for calibration_rollback
        // Then: Found with correct schema
        """
        from src.mcp.server import TOOLS

        tool = next((t for t in TOOLS if t.name == "calibration_rollback"), None)

        assert tool is not None
        assert "source" in tool.inputSchema["properties"]
        assert "version" in tool.inputSchema["properties"]
        assert "reason" in tool.inputSchema["properties"]
        assert tool.inputSchema["required"] == ["source"]
