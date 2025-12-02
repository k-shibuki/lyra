"""
Tests for calibrate_rollback MCP tool.

Implements test perspectives for the new calibrate_rollback tool per test-strategy.mdc.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from src.mcp.errors import (
    InvalidParamsError,
    CalibrationError,
)


class TestCalibrateRollbackHandler:
    """Tests for _handle_calibrate_rollback MCP handler."""

    @pytest.fixture
    def mock_calibrator(self) -> MagicMock:
        """Create mock calibrator with default behavior."""
        calibrator = MagicMock()
        
        # Default: has calibration params
        mock_params = MagicMock()
        mock_params.version = 3
        mock_params.brier_after = 0.15
        mock_params.method = "temperature"
        calibrator.get_params.return_value = mock_params
        
        # Default: rollback succeeds
        rollback_params = MagicMock()
        rollback_params.version = 2
        rollback_params.brier_after = 0.12
        rollback_params.method = "temperature"
        calibrator.rollback.return_value = rollback_params
        calibrator.rollback_to_version.return_value = rollback_params
        
        return calibrator

    @pytest.mark.asyncio
    async def test_rollback_to_previous_version(self, mock_calibrator: MagicMock) -> None:
        """
        TC-N-01: Valid source with history.
        
        // Given: Source with calibration history
        // When: Calling calibrate_rollback without version
        // Then: Rollback to previous version succeeds
        """
        from src.mcp.server import _handle_calibrate_rollback
        
        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            result = await _handle_calibrate_rollback({
                "source": "llm_extract",
            })
        
        assert result["ok"] is True
        assert result["source"] == "llm_extract"
        assert result["rolled_back_to"] == 2
        assert result["previous_version"] == 3
        mock_calibrator.rollback.assert_called_once_with("llm_extract", "Manual rollback by Cursor AI")

    @pytest.mark.asyncio
    async def test_rollback_to_specific_version(self, mock_calibrator: MagicMock) -> None:
        """
        TC-N-02: Valid source with specific version.
        
        // Given: Source with multiple versions
        // When: Calling calibrate_rollback with version=1
        // Then: Rollback to version 1 succeeds
        """
        from src.mcp.server import _handle_calibrate_rollback
        
        rollback_params = MagicMock()
        rollback_params.version = 1
        rollback_params.brier_after = 0.10
        rollback_params.method = "platt"
        mock_calibrator.rollback_to_version.return_value = rollback_params
        
        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            result = await _handle_calibrate_rollback({
                "source": "llm_extract",
                "version": 1,
            })
        
        assert result["ok"] is True
        assert result["rolled_back_to"] == 1
        mock_calibrator.rollback_to_version.assert_called_once_with(
            "llm_extract", 1, "Manual rollback by Cursor AI"
        )

    @pytest.mark.asyncio
    async def test_rollback_with_reason(self, mock_calibrator: MagicMock) -> None:
        """
        TC-N-03: Valid source with reason.
        
        // Given: Source with calibration
        // When: Calling calibrate_rollback with reason
        // Then: Reason included in response and passed to rollback
        """
        from src.mcp.server import _handle_calibrate_rollback
        
        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            result = await _handle_calibrate_rollback({
                "source": "nli_judge",
                "reason": "Brier score degradation detected",
            })
        
        assert result["ok"] is True
        assert result["reason"] == "Brier score degradation detected"
        mock_calibrator.rollback.assert_called_once_with(
            "nli_judge", "Brier score degradation detected"
        )

    @pytest.mark.asyncio
    async def test_missing_source_parameter(self) -> None:
        """
        TC-A-01: Missing source parameter.
        
        // Given: No source in arguments
        // When: Calling calibrate_rollback
        // Then: InvalidParamsError raised
        """
        from src.mcp.server import _handle_calibrate_rollback
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_calibrate_rollback({})
        
        assert exc_info.value.code.value == "INVALID_PARAMS"
        assert "source is required" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_empty_source_string(self) -> None:
        """
        TC-A-02: Empty source string.
        
        // Given: source=""
        // When: Calling calibrate_rollback
        // Then: InvalidParamsError raised
        """
        from src.mcp.server import _handle_calibrate_rollback
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_calibrate_rollback({"source": ""})
        
        assert exc_info.value.code.value == "INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_source_with_no_calibration(self, mock_calibrator: MagicMock) -> None:
        """
        TC-A-03: Source with no calibration.
        
        // Given: Source never calibrated
        // When: Calling calibrate_rollback
        // Then: CalibrationError raised
        """
        from src.mcp.server import _handle_calibrate_rollback
        
        mock_calibrator.get_params.return_value = None
        
        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            with pytest.raises(CalibrationError) as exc_info:
                await _handle_calibrate_rollback({"source": "unknown_source"})
        
        assert exc_info.value.code.value == "CALIBRATION_ERROR"
        assert "unknown_source" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_source_with_only_one_version(self, mock_calibrator: MagicMock) -> None:
        """
        TC-A-04: Source with only one version.
        
        // Given: Source with single calibration version
        // When: Calling calibrate_rollback
        // Then: CalibrationError raised (no previous)
        """
        from src.mcp.server import _handle_calibrate_rollback
        
        mock_calibrator.rollback.return_value = None
        
        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            with pytest.raises(CalibrationError) as exc_info:
                await _handle_calibrate_rollback({"source": "llm_extract"})
        
        assert exc_info.value.code.value == "CALIBRATION_ERROR"
        assert "no previous version" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_nonexistent_target_version(self, mock_calibrator: MagicMock) -> None:
        """
        TC-A-05: Non-existent target version.
        
        // Given: Target version not in history
        // When: Calling calibrate_rollback with invalid version
        // Then: CalibrationError raised
        """
        from src.mcp.server import _handle_calibrate_rollback
        
        mock_calibrator.rollback_to_version.return_value = None
        
        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            with pytest.raises(CalibrationError) as exc_info:
                await _handle_calibrate_rollback({
                    "source": "llm_extract",
                    "version": 999,
                })
        
        assert exc_info.value.code.value == "CALIBRATION_ERROR"

    @pytest.mark.asyncio
    async def test_response_includes_brier_and_method(self, mock_calibrator: MagicMock) -> None:
        """
        Test that response includes brier_after and method fields.
        
        // Given: Successful rollback
        // When: Checking response
        // Then: brier_after and method are included
        """
        from src.mcp.server import _handle_calibrate_rollback
        
        with patch("src.utils.calibration.get_calibrator", return_value=mock_calibrator):
            result = await _handle_calibrate_rollback({
                "source": "llm_extract",
            })
        
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
        
        // Given: Handler that raises MCPError
        // When: Calling via call_tool
        // Then: Returns structured error response
        """
        from src.mcp.server import call_tool
        import json
        
        # This should raise InvalidParamsError
        result = await call_tool("calibrate_rollback", {})
        
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
        from src.mcp.server import call_tool
        import json
        
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
        Test that calibrate_rollback is defined in TOOLS.
        
        // Given: TOOLS list
        // When: Searching for calibrate_rollback
        // Then: Found with correct schema
        """
        from src.mcp.server import TOOLS
        
        tool = next((t for t in TOOLS if t.name == "calibrate_rollback"), None)
        
        assert tool is not None
        assert "source" in tool.inputSchema["properties"]
        assert "version" in tool.inputSchema["properties"]
        assert "reason" in tool.inputSchema["properties"]
        assert tool.inputSchema["required"] == ["source"]
