"""
Tests for MCP error code definitions.

Implements test perspectives for src/mcp/errors.py per test-strategy.mdc.

## Test Perspectives Table (ChromeNotReadyError - Phase O.3 Simplified)

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-N-14 | Default constructor | Equivalence - normal | CHROME_NOT_READY code, startup instructions | Default msg |
| TC-N-16 | Custom message | Equivalence - normal | Uses custom message | Override |
| TC-N-17 | Format check | Equivalence - normal | Format matches requirements.md §3.2.1 | Spec compliance |
| TC-B-02 | message="" (empty) | Boundary - empty | Empty string accepted | Edge case |
"""

import pytest

from src.mcp.errors import (
    MCPErrorCode,
    MCPError,
    InvalidParamsError,
    TaskNotFoundError,
    BudgetExhaustedError,
    AuthRequiredError,
    AllEnginesBlockedError,
    PipelineError,
    CalibrationError,
    TimeoutError,
    InternalError,
    ChromeNotReadyError,
    generate_error_id,
    create_error_response,
)


class TestMCPErrorCode:
    """Tests for MCPErrorCode enum."""

    def test_all_error_codes_defined(self) -> None:
        """
        Test that all 10 error codes from §3.2.1 are defined.
        
        // Given: MCPErrorCode enum
        // When: Checking all expected codes
        // Then: All 10 codes exist with correct values
        """
        expected_codes = [
            ("INVALID_PARAMS", "INVALID_PARAMS"),
            ("TASK_NOT_FOUND", "TASK_NOT_FOUND"),
            ("BUDGET_EXHAUSTED", "BUDGET_EXHAUSTED"),
            ("AUTH_REQUIRED", "AUTH_REQUIRED"),
            ("ALL_ENGINES_BLOCKED", "ALL_ENGINES_BLOCKED"),
            ("CHROME_NOT_READY", "CHROME_NOT_READY"),
            ("PIPELINE_ERROR", "PIPELINE_ERROR"),
            ("CALIBRATION_ERROR", "CALIBRATION_ERROR"),
            ("TIMEOUT", "TIMEOUT"),
            ("INTERNAL_ERROR", "INTERNAL_ERROR"),
        ]
        
        for name, value in expected_codes:
            code = MCPErrorCode[name]
            assert code.value == value

    def test_error_code_count(self) -> None:
        """
        Test that exactly 10 error codes are defined.
        
        // Given: MCPErrorCode enum
        // When: Counting all codes
        // Then: Count equals 10
        """
        assert len(MCPErrorCode) == 10


class TestMCPError:
    """Tests for MCPError base class."""

    def test_basic_error_creation(self) -> None:
        """
        TC-N-01: MCPError with valid code and message.
        
        // Given: Valid error code and message
        // When: Creating MCPError
        // Then: Error dict has ok=False, error_code, error
        """
        error = MCPError(MCPErrorCode.INVALID_PARAMS, "Invalid input")
        result = error.to_dict()
        
        assert result["ok"] is False
        assert result["error_code"] == "INVALID_PARAMS"
        assert result["error"] == "Invalid input"
        assert "error_id" not in result
        assert "details" not in result

    def test_error_with_details_and_error_id(self) -> None:
        """
        TC-N-02: MCPError with details and error_id.
        
        // Given: Error with all optional fields
        // When: Creating MCPError
        // Then: Dict includes details and error_id
        """
        error = MCPError(
            MCPErrorCode.PIPELINE_ERROR,
            "Processing failed",
            details={"stage": "extract"},
            error_id="err_12345",
        )
        result = error.to_dict()
        
        assert result["ok"] is False
        assert result["error_code"] == "PIPELINE_ERROR"
        assert result["error"] == "Processing failed"
        assert result["error_id"] == "err_12345"
        assert result["details"] == {"stage": "extract"}

    def test_error_with_none_details(self) -> None:
        """
        TC-A-01: MCPError with None details.
        
        // Given: Error with details=None
        // When: Converting to dict
        // Then: details key not included
        """
        error = MCPError(MCPErrorCode.TIMEOUT, "Timed out", details=None)
        result = error.to_dict()
        
        assert "details" not in result

    def test_error_with_empty_details(self) -> None:
        """
        TC-A-02: MCPError with empty details dict.
        
        // Given: Error with details={}
        // When: Converting to dict
        // Then: details key not included (empty is filtered)
        """
        error = MCPError(MCPErrorCode.TIMEOUT, "Timed out", details={})
        result = error.to_dict()
        
        # Empty details should not be included
        assert "details" not in result

    def test_error_is_exception(self) -> None:
        """
        Test MCPError is a proper Exception.
        
        // Given: MCPError instance
        // When: Raising as exception
        // Then: Can be caught as Exception
        """
        error = MCPError(MCPErrorCode.INTERNAL_ERROR, "Test error")
        
        with pytest.raises(MCPError) as exc_info:
            raise error
        
        assert exc_info.value.code == MCPErrorCode.INTERNAL_ERROR
        assert str(exc_info.value) == "Test error"


class TestInvalidParamsError:
    """Tests for InvalidParamsError."""

    def test_with_all_params(self) -> None:
        """
        TC-N-03: InvalidParamsError with param_name.
        
        // Given: Invalid parameter details
        // When: Creating InvalidParamsError
        // Then: Error has INVALID_PARAMS code with details
        """
        error = InvalidParamsError(
            "Value must be positive",
            param_name="count",
            expected="positive integer",
            received=-5,
        )
        result = error.to_dict()
        
        assert result["error_code"] == "INVALID_PARAMS"
        assert result["error"] == "Value must be positive"
        assert result["details"]["param_name"] == "count"
        assert result["details"]["expected"] == "positive integer"
        assert result["details"]["received"] == "-5"

    def test_with_minimal_params(self) -> None:
        """
        TC-A-03: InvalidParamsError without optional params.
        
        // Given: Only message
        // When: Creating InvalidParamsError
        // Then: No details included
        """
        error = InvalidParamsError("Invalid input")
        result = error.to_dict()
        
        assert result["error_code"] == "INVALID_PARAMS"
        assert "details" not in result


class TestTaskNotFoundError:
    """Tests for TaskNotFoundError."""

    def test_task_not_found(self) -> None:
        """
        TC-N-04: TaskNotFoundError with task_id.
        
        // Given: Task ID that doesn't exist
        // When: Creating TaskNotFoundError
        // Then: Error has TASK_NOT_FOUND code with task_id
        """
        error = TaskNotFoundError("task_abc123")
        result = error.to_dict()
        
        assert result["error_code"] == "TASK_NOT_FOUND"
        assert result["error"] == "Task not found: task_abc123"
        assert result["details"]["task_id"] == "task_abc123"


class TestBudgetExhaustedError:
    """Tests for BudgetExhaustedError."""

    def test_with_full_details(self) -> None:
        """
        TC-N-05: BudgetExhaustedError with full details.
        
        // Given: Budget exhaustion details
        // When: Creating BudgetExhaustedError
        // Then: Error includes limit and used counts
        """
        error = BudgetExhaustedError(
            "task_xyz",
            budget_type="pages",
            limit=100,
            used=100,
        )
        result = error.to_dict()
        
        assert result["error_code"] == "BUDGET_EXHAUSTED"
        assert result["details"]["task_id"] == "task_xyz"
        assert result["details"]["budget_type"] == "pages"
        assert result["details"]["limit"] == 100
        assert result["details"]["used"] == 100


class TestAuthRequiredError:
    """Tests for AuthRequiredError."""

    def test_with_domains(self) -> None:
        """
        TC-N-06: AuthRequiredError with domains list.
        
        // Given: Auth required with domain list
        // When: Creating AuthRequiredError
        // Then: Error includes domains in details
        """
        error = AuthRequiredError(
            "task_123",
            pending_count=3,
            domains=["example.com", "test.org"],
        )
        result = error.to_dict()
        
        assert result["error_code"] == "AUTH_REQUIRED"
        assert result["details"]["task_id"] == "task_123"
        assert result["details"]["pending_count"] == 3
        assert result["details"]["domains"] == ["example.com", "test.org"]


class TestAllEnginesBlockedError:
    """Tests for AllEnginesBlockedError."""

    def test_all_engines_blocked(self) -> None:
        """
        TC-N-07: AllEnginesBlockedError.
        
        // Given: All engines in cooldown
        // When: Creating AllEnginesBlockedError
        // Then: Error has ALL_ENGINES_BLOCKED code
        """
        error = AllEnginesBlockedError(
            engines=["google", "duckduckgo"],
            earliest_retry="2024-01-01T12:30:00Z",
        )
        result = error.to_dict()
        
        assert result["error_code"] == "ALL_ENGINES_BLOCKED"
        assert result["details"]["blocked_engines"] == ["google", "duckduckgo"]
        assert result["details"]["earliest_retry"] == "2024-01-01T12:30:00Z"


class TestPipelineError:
    """Tests for PipelineError."""

    def test_with_stage(self) -> None:
        """
        TC-N-08: PipelineError with stage.
        
        // Given: Pipeline error at specific stage
        // When: Creating PipelineError
        // Then: Error includes stage in details
        """
        error = PipelineError(
            "Extraction failed",
            stage="llm_extract",
            error_id="err_abc",
        )
        result = error.to_dict()
        
        assert result["error_code"] == "PIPELINE_ERROR"
        assert result["error"] == "Extraction failed"
        assert result["details"]["stage"] == "llm_extract"
        assert result["error_id"] == "err_abc"


class TestCalibrationError:
    """Tests for CalibrationError."""

    def test_with_source(self) -> None:
        """
        TC-N-09: CalibrationError with source.
        
        // Given: Calibration error for source
        // When: Creating CalibrationError
        // Then: Error includes source in details
        """
        error = CalibrationError(
            "No previous version",
            source="llm_extract",
            reason="no_previous_version",
        )
        result = error.to_dict()
        
        assert result["error_code"] == "CALIBRATION_ERROR"
        assert result["details"]["source"] == "llm_extract"
        assert result["details"]["reason"] == "no_previous_version"


class TestTimeoutError:
    """Tests for TimeoutError."""

    def test_with_operation(self) -> None:
        """
        TC-N-10: TimeoutError with operation.
        
        // Given: Timeout for specific operation
        // When: Creating TimeoutError
        // Then: Error includes operation details
        """
        error = TimeoutError(
            "Search timed out",
            timeout_seconds=30.0,
            operation="search_serp",
        )
        result = error.to_dict()
        
        assert result["error_code"] == "TIMEOUT"
        assert result["error"] == "Search timed out"
        assert result["details"]["timeout_seconds"] == 30.0
        assert result["details"]["operation"] == "search_serp"


class TestInternalError:
    """Tests for InternalError."""

    def test_with_error_id(self) -> None:
        """
        TC-N-11: InternalError with error_id.
        
        // Given: Internal error with correlation ID
        // When: Creating InternalError
        // Then: Error includes error_id
        """
        error = InternalError(
            "Database connection failed",
            error_id="err_xyz789",
        )
        result = error.to_dict()
        
        assert result["error_code"] == "INTERNAL_ERROR"
        assert result["error"] == "Database connection failed"
        assert result["error_id"] == "err_xyz789"

    def test_default_message(self) -> None:
        """
        Test InternalError default message.
        
        // Given: No message provided
        // When: Creating InternalError
        // Then: Uses default message
        """
        error = InternalError()
        result = error.to_dict()
        
        assert result["error"] == "An unexpected internal error occurred"


class TestChromeNotReadyError:
    """Tests for ChromeNotReadyError (N.5 implementation)."""

    def test_default_message(self) -> None:
        """
        TC-N-14: ChromeNotReadyError with default message.
        
        // Given: No parameters
        // When: Creating ChromeNotReadyError
        // Then: Error has CHROME_NOT_READY code with startup instructions
        """
        error = ChromeNotReadyError()
        result = error.to_dict()
        
        assert result["error_code"] == "CHROME_NOT_READY"
        assert "Chrome CDP is not connected" in result["error"]
        assert "./scripts/chrome.sh start" in result["error"]
        assert "details" not in result  # No details in simplified error

    def test_custom_message(self) -> None:
        """
        TC-N-16: ChromeNotReadyError with custom message.
        
        // Given: Custom message
        // When: Creating ChromeNotReadyError
        // Then: Uses custom message
        """
        custom_msg = "Custom CDP error message"
        error = ChromeNotReadyError(message=custom_msg)
        result = error.to_dict()
        
        assert result["error_code"] == "CHROME_NOT_READY"
        assert result["error"] == custom_msg

    def test_error_response_format_matches_spec(self) -> None:
        """
        TC-N-17: Error response format matches §3.2.1 spec.
        
        // Given: ChromeNotReadyError
        // When: Converting to dict
        // Then: Format matches requirements.md §3.2.1 CHROME_NOT_READY spec
        """
        error = ChromeNotReadyError()
        result = error.to_dict()
        
        # Required fields per §3.2.1
        assert result["ok"] is False
        assert result["error_code"] == "CHROME_NOT_READY"
        assert isinstance(result["error"], str)
        # No details in simplified hybrid architecture
        assert "details" not in result

    def test_empty_message(self) -> None:
        """
        TC-B-02: ChromeNotReadyError with empty message.
        
        // Given: Empty string message
        // When: Creating ChromeNotReadyError
        // Then: Error accepts empty message (edge case)
        """
        error = ChromeNotReadyError(message="")
        result = error.to_dict()
        
        assert result["error_code"] == "CHROME_NOT_READY"
        assert result["error"] == ""
        assert "details" not in result


class TestGenerateErrorId:
    """Tests for generate_error_id function."""

    def test_format(self) -> None:
        """
        TC-N-12: generate_error_id() returns proper format.
        
        // Given: Calling generate_error_id
        // When: Generating ID
        // Then: Returns "err_" prefixed unique ID
        """
        error_id = generate_error_id()
        
        assert error_id.startswith("err_")
        assert len(error_id) == 16  # "err_" + 12 hex chars

    def test_uniqueness(self) -> None:
        """
        Test generate_error_id produces unique IDs.
        
        // Given: Generating multiple IDs
        // When: Comparing them
        // Then: All IDs are unique
        """
        ids = [generate_error_id() for _ in range(100)]
        
        assert len(set(ids)) == 100


class TestCreateErrorResponse:
    """Tests for create_error_response utility."""

    def test_creates_same_as_mcp_error(self) -> None:
        """
        TC-N-13: create_error_response() utility.
        
        // Given: Error parameters
        // When: Using utility function
        // Then: Returns dict same as MCPError.to_dict()
        """
        result = create_error_response(
            MCPErrorCode.INVALID_PARAMS,
            "Test message",
            details={"key": "value"},
            error_id="err_test",
        )
        
        expected = MCPError(
            MCPErrorCode.INVALID_PARAMS,
            "Test message",
            details={"key": "value"},
            error_id="err_test",
        ).to_dict()
        
        assert result == expected

