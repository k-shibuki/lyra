"""
MCP Error Code definitions for Lancet.

Implements §3.2.1 error code schema for consistent error handling across all MCP tools.
Each error code has a specific meaning and recommended action for Cursor AI.

Error codes follow the pattern:
- INVALID_*: Input validation errors (client-side fix needed)
- *_NOT_FOUND: Resource not found errors
- *_EXHAUSTED: Resource limits reached
- *_REQUIRED: Blocking conditions requiring action
- *_BLOCKED: Service unavailable states
- *_ERROR: Processing/internal errors
"""

from enum import Enum
from typing import Any


class MCPErrorCode(str, Enum):
    """
    MCP Error codes per §3.2.1.

    Each code indicates a specific error condition with recommended Cursor AI action.
    """

    # Input validation errors
    INVALID_PARAMS = "INVALID_PARAMS"
    """Input parameters are invalid or malformed.
    Action: Check parameters and re-call with corrected values."""

    # Resource not found
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    """Specified task_id does not exist.
    Action: Create a new task with create_task, or verify task_id."""

    # Resource limits
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    """Task budget (pages or time) has been exhausted.
    Action: Call stop_task to end, or request budget increase from user."""

    # Blocking conditions
    AUTH_REQUIRED = "AUTH_REQUIRED"
    """Authentication is required to proceed.
    Action: Call get_auth_queue to see pending auth, notify user."""

    ALL_ENGINES_BLOCKED = "ALL_ENGINES_BLOCKED"
    """All search engines are in cooldown state.
    Action: Wait and retry later, or end the task."""

    # Processing errors
    PIPELINE_ERROR = "PIPELINE_ERROR"
    """Error occurred in internal pipeline processing.
    Action: Check error_id in logs, consider retry with different parameters."""

    CALIBRATION_ERROR = "CALIBRATION_ERROR"
    """Error in calibration processing.
    Action: Check details, consider rollback if degradation detected."""

    # Timeout
    TIMEOUT = "TIMEOUT"
    """Operation timed out.
    Action: Retry with smaller scope or longer timeout."""

    # Infrastructure errors
    CHROME_NOT_READY = "CHROME_NOT_READY"
    """Chrome CDP is not connected (auto-start failed).
    Action: Check ./scripts/chrome.sh diagnose"""

    # Internal errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    """Unexpected internal error.
    Action: Check error_id in logs, report to operator if persistent."""


class MCPError(Exception):
    """
    Base exception for MCP tool errors.

    Provides structured error responses for MCP protocol.
    """

    def __init__(
        self,
        code: MCPErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        error_id: str | None = None,
    ):
        """
        Initialize MCP error.

        Args:
            code: Error code from MCPErrorCode enum.
            message: Human-readable error message.
            details: Optional additional error details.
            error_id: Optional unique error ID for log correlation.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.error_id = error_id

    def to_dict(self) -> dict[str, Any]:
        """
        Convert error to MCP response format.

        Returns:
            Dictionary suitable for MCP error response.
        """
        result: dict[str, Any] = {
            "ok": False,
            "error_code": self.code.value,
            "error": self.message,
        }

        if self.error_id:
            result["error_id"] = self.error_id

        if self.details:
            result["details"] = self.details

        return result


class InvalidParamsError(MCPError):
    """Raised when input parameters are invalid."""

    def __init__(
        self,
        message: str,
        *,
        param_name: str | None = None,
        expected: str | None = None,
        received: Any = None,
    ):
        details = {}
        if param_name:
            details["param_name"] = param_name
        if expected:
            details["expected"] = expected
        if received is not None:
            details["received"] = str(received)

        super().__init__(
            MCPErrorCode.INVALID_PARAMS,
            message,
            details=details if details else None,
        )


class TaskNotFoundError(MCPError):
    """Raised when specified task_id does not exist."""

    def __init__(self, task_id: str):
        super().__init__(
            MCPErrorCode.TASK_NOT_FOUND,
            f"Task not found: {task_id}",
            details={"task_id": task_id},
        )


class BudgetExhaustedError(MCPError):
    """Raised when task budget is exhausted."""

    def __init__(
        self,
        task_id: str,
        *,
        budget_type: str = "pages",
        limit: int | None = None,
        used: int | None = None,
    ):
        details: dict[str, Any] = {"task_id": task_id, "budget_type": budget_type}
        if limit is not None:
            details["limit"] = limit
        if used is not None:
            details["used"] = used

        super().__init__(
            MCPErrorCode.BUDGET_EXHAUSTED,
            f"Budget exhausted for task {task_id}: {budget_type}",
            details=details,
        )


class AuthRequiredError(MCPError):
    """Raised when authentication is required to proceed."""

    def __init__(
        self,
        task_id: str,
        *,
        pending_count: int = 0,
        domains: list[str] | None = None,
    ):
        details: dict[str, Any] = {"task_id": task_id, "pending_count": pending_count}
        if domains:
            details["domains"] = domains

        super().__init__(
            MCPErrorCode.AUTH_REQUIRED,
            f"Authentication required for task {task_id}: {pending_count} pending",
            details=details,
        )


class AllEnginesBlockedError(MCPError):
    """Raised when all search engines are in cooldown."""

    def __init__(
        self,
        *,
        engines: list[str] | None = None,
        earliest_retry: str | None = None,
    ):
        details: dict[str, Any] = {}
        if engines:
            details["blocked_engines"] = engines
        if earliest_retry:
            details["earliest_retry"] = earliest_retry

        super().__init__(
            MCPErrorCode.ALL_ENGINES_BLOCKED,
            "All search engines are currently blocked (cooldown)",
            details=details if details else None,
        )


class PipelineError(MCPError):
    """Raised when pipeline processing fails."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        error_id: str | None = None,
    ):
        details = {}
        if stage:
            details["stage"] = stage

        super().__init__(
            MCPErrorCode.PIPELINE_ERROR,
            message,
            details=details if details else None,
            error_id=error_id,
        )


class CalibrationError(MCPError):
    """Raised when calibration processing fails."""

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        reason: str | None = None,
    ):
        details = {}
        if source:
            details["source"] = source
        if reason:
            details["reason"] = reason

        super().__init__(
            MCPErrorCode.CALIBRATION_ERROR,
            message,
            details=details if details else None,
        )


class TimeoutError(MCPError):
    """Raised when operation times out."""

    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: float | None = None,
        operation: str | None = None,
    ):
        details = {}
        if timeout_seconds is not None:
            details["timeout_seconds"] = timeout_seconds
        if operation:
            details["operation"] = operation

        super().__init__(
            MCPErrorCode.TIMEOUT,
            message,
            details=details if details else None,
        )


class InternalError(MCPError):
    """Raised for unexpected internal errors."""

    def __init__(
        self,
        message: str = "An unexpected internal error occurred",
        *,
        error_id: str | None = None,
    ):
        super().__init__(
            MCPErrorCode.INTERNAL_ERROR,
            message,
            error_id=error_id,
        )


class ChromeNotReadyError(MCPError):
    """Raised when Chrome CDP connection is not available after auto-start attempt.
    
    This error indicates that Chrome auto-start was attempted but failed.
    Chrome with remote debugging is required for browser-based search operations.
    """

    def __init__(
        self,
        message: str = "Chrome CDP is not connected. Auto-start failed. Check: ./scripts/chrome.sh start",
        *,
        auto_start_attempted: bool = True,
        is_podman: bool = False,
    ):
        # Only include details if is_podman=True (per test expectations)
        details: dict[str, Any] | None = None
        if is_podman:
            details = {
                "auto_start_attempted": auto_start_attempted,
                "hint": "WSL2 + Podman: Verify Chrome is installed, socat is running, and WSL2 mirrored networking is enabled",
            }
        
        super().__init__(
            MCPErrorCode.CHROME_NOT_READY,
            message,
            details=details,
        )


def generate_error_id() -> str:
    """
    Generate unique error ID for log correlation.

    Returns:
        Unique error ID string.
    """
    import uuid

    return f"err_{uuid.uuid4().hex[:12]}"


def create_error_response(
    code: MCPErrorCode,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    error_id: str | None = None,
) -> dict[str, Any]:
    """
    Create standardized MCP error response.

    Utility function for handlers that prefer dict responses over exceptions.

    Args:
        code: Error code from MCPErrorCode enum.
        message: Human-readable error message.
        details: Optional additional details.
        error_id: Optional error ID for log correlation.

    Returns:
        Dictionary suitable for MCP error response.
    """
    return MCPError(code, message, details=details, error_id=error_id).to_dict()

