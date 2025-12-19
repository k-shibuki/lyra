"""
Secure logging utilities for Lyra.

Implements L8 (Log Security Policy) per §4.4.1:
- LLM input/output logging as summaries (hash, length, preview)
- Exception sanitization (no stack traces, internal paths)
- Security audit logging for detection events

This module prevents sensitive information from leaking through logs.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

# Maximum length for preview text in logs
MAX_PREVIEW_LENGTH = 100

# Maximum length for error messages in logs
MAX_ERROR_MESSAGE_LENGTH = 200

# Pattern for sensitive paths (same as response_sanitizer)
_SENSITIVE_PATH_PATTERN = re.compile(
    r"/home/[^/\s]+|"
    r"/root/|"
    r"/tmp/[^/\s]+|"
    r"/var/[^/\s]+|"
    r"C:\\\\Users\\\\[^\\\\]+|"
    r"\\\\src\\\\|"
    r'File "[^"]+"|'
    r"line \d+, in \w+",
    re.IGNORECASE,
)

# Pattern for stack trace fragments
_STACK_TRACE_PATTERN = re.compile(
    r"Traceback \(most recent call last\):|"
    r"^\s+File |"
    r"^\s+at \w+|"
    r"^\s+raise \w+",
    re.MULTILINE,
)

# Patterns that suggest LLM prompt content
_PROMPT_CONTENT_PATTERNS = [
    r"LYRA[\s_-]*[A-Za-z0-9_-]{4,}",  # Session tags
    r"システムインストラクション",
    r"ユーザープロンプト",
    r"このタグ.*内の記述",
]

_PROMPT_CONTENT_REGEX = re.compile("|".join(_PROMPT_CONTENT_PATTERNS), re.IGNORECASE)


# ============================================================================
# Enums
# ============================================================================


class SecurityEventType(Enum):
    """Types of security events for audit logging."""

    # Prompt injection related
    DANGEROUS_PATTERN_DETECTED = "dangerous_pattern_detected"
    PROMPT_LEAKAGE_DETECTED = "prompt_leakage_detected"
    TAG_PATTERN_REMOVED = "tag_pattern_removed"

    # Output validation related
    SUSPICIOUS_URL_DETECTED = "suspicious_url_detected"
    SUSPICIOUS_IP_DETECTED = "suspicious_ip_detected"
    OUTPUT_TRUNCATED = "output_truncated"

    # MCP response related
    UNKNOWN_FIELD_REMOVED = "unknown_field_removed"
    LLM_FIELD_SANITIZED = "llm_field_sanitized"
    ERROR_SANITIZED = "error_sanitized"

    # Network/access related
    EXTERNAL_ACCESS_BLOCKED = "external_access_blocked"


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class LLMIOSummary:
    """Summary of LLM input/output for safe logging."""

    content_hash: str  # SHA256 hash (first 16 chars)
    length: int
    preview: str  # First N chars with sensitive content masked
    had_sensitive_content: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for structured logging."""
        return {
            "hash": self.content_hash,
            "length": self.length,
            "preview": self.preview,
            "had_sensitive": self.had_sensitive_content,
        }


@dataclass
class SanitizedExceptionInfo:
    """Sanitized exception information for logging."""

    exception_type: str
    sanitized_message: str
    error_id: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for structured logging."""
        return {
            "type": self.exception_type,
            "message": self.sanitized_message,
            "error_id": self.error_id,
        }


# ============================================================================
# SecureLogger Class
# ============================================================================


class SecureLogger:
    """
    Secure logger that prevents sensitive information leakage.

    Provides methods for logging LLM I/O, exceptions, and other
    potentially sensitive information in a safe manner.

    Usage:
        secure_log = SecureLogger("my_module")

        # Log LLM input/output
        secure_log.log_llm_io(
            "llm_extract",
            input_text=user_content,
            output_text=llm_response,
        )

        # Log exception safely
        try:
            dangerous_operation()
        except Exception as e:
            secure_log.log_exception(e, context={"operation": "extract"})
    """

    def __init__(self, name: str | None = None):
        """
        Initialize secure logger.

        Args:
            name: Logger name (usually __name__).
        """
        self._logger = get_logger(name)
        self._name = name or "secure_logger"

    def log_llm_io(
        self,
        operation: str,
        input_text: str | None = None,
        output_text: str | None = None,
        level: str = "debug",
        **extra_context: Any,
    ) -> None:
        """
        Log LLM input/output as safe summaries.

        Per §4.4.1 L8: Never log full prompt text.
        Instead, log hash, length, and masked preview.

        Args:
            operation: Name of LLM operation (e.g., "llm_extract").
            input_text: Input text sent to LLM (optional).
            output_text: Output text from LLM (optional).
            level: Log level (debug, info, warning, error).
            **extra_context: Additional context to log.
        """
        log_data: dict[str, Any] = {
            "operation": operation,
        }

        if input_text is not None:
            input_summary = self._create_io_summary(input_text)
            log_data["input"] = input_summary.to_dict()

        if output_text is not None:
            output_summary = self._create_io_summary(output_text)
            log_data["output"] = output_summary.to_dict()

        log_data.update(extra_context)

        # Get appropriate log method
        log_method = getattr(self._logger, level, self._logger.debug)
        log_method("LLM I/O", **log_data)

    def log_exception(
        self,
        exception: Exception,
        context: dict[str, Any] | None = None,
        level: str = "error",
        include_internal_trace: bool = False,
    ) -> SanitizedExceptionInfo:
        """
        Log an exception with sanitized information.

        Per §4.4.1 L8: Sanitize exception messages before logging.
        Internal trace is logged separately at DEBUG level only if requested.

        Args:
            exception: Exception to log.
            context: Additional context dict.
            level: Log level for sanitized message.
            include_internal_trace: Whether to log full trace at DEBUG.

        Returns:
            SanitizedExceptionInfo for potential response use.
        """
        error_id = self._generate_error_id()
        sanitized = self._sanitize_exception(exception, error_id)

        log_data: dict[str, Any] = {
            "error_id": error_id,
            "exception_type": sanitized.exception_type,
            "sanitized_message": sanitized.sanitized_message,
        }

        if context:
            log_data["context"] = context

        # Log sanitized version at requested level
        log_method = getattr(self._logger, level, self._logger.error)
        log_method("Exception occurred", **log_data)

        # Optionally log full trace at DEBUG for internal debugging
        if include_internal_trace:
            self._logger.debug(
                "Internal exception trace",
                error_id=error_id,
                full_trace=traceback.format_exc(),
            )

        return sanitized

    def log_sensitive_operation(
        self,
        operation: str,
        details: dict[str, Any],
        level: str = "info",
    ) -> None:
        """
        Log a sensitive operation with sanitized details.

        Automatically masks any values that look like prompts or paths.

        Args:
            operation: Operation name.
            details: Details dict (values will be sanitized).
            level: Log level.
        """
        sanitized_details = self._sanitize_dict(details)

        log_method = getattr(self._logger, level, self._logger.info)
        log_method(
            "Sensitive operation",
            operation=operation,
            details=sanitized_details,
        )

    def _create_io_summary(self, text: str) -> LLMIOSummary:
        """Create a safe summary of LLM input/output text."""
        # Calculate hash
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

        # Create preview with sensitive content masked
        preview, had_sensitive = self._create_safe_preview(text)

        return LLMIOSummary(
            content_hash=content_hash,
            length=len(text),
            preview=preview,
            had_sensitive_content=had_sensitive,
        )

    def _create_safe_preview(
        self,
        text: str,
        max_length: int = MAX_PREVIEW_LENGTH,
    ) -> tuple[str, bool]:
        """
        Create a safe preview of text for logging.

        Args:
            text: Original text.
            max_length: Maximum preview length.

        Returns:
            Tuple of (preview, had_sensitive_content).
        """
        had_sensitive = False

        # Take first N characters
        preview = text[:max_length]

        # Mask prompt-like content
        if _PROMPT_CONTENT_REGEX.search(preview):
            preview = _PROMPT_CONTENT_REGEX.sub("[MASKED]", preview)
            had_sensitive = True

        # Mask paths
        if _SENSITIVE_PATH_PATTERN.search(preview):
            preview = _SENSITIVE_PATH_PATTERN.sub("[PATH]", preview)
            had_sensitive = True

        # Add ellipsis if truncated
        if len(text) > max_length:
            preview = preview.rstrip() + "..."

        return preview, had_sensitive

    def _sanitize_exception(
        self,
        exception: Exception,
        error_id: str,
    ) -> SanitizedExceptionInfo:
        """Sanitize exception for safe logging/response."""
        message = str(exception)

        # Remove paths
        sanitized = _SENSITIVE_PATH_PATTERN.sub("[PATH]", message)

        # Remove stack traces
        sanitized = _STACK_TRACE_PATTERN.sub("[TRACE]", sanitized)

        # Truncate if too long
        if len(sanitized) > MAX_ERROR_MESSAGE_LENGTH:
            sanitized = sanitized[:MAX_ERROR_MESSAGE_LENGTH] + "..."

        # If message is mostly redacted, use generic
        redaction_count = sanitized.count("[PATH]") + sanitized.count("[TRACE]")
        if redaction_count > 3:
            sanitized = "An internal error occurred"

        return SanitizedExceptionInfo(
            exception_type=type(exception).__name__,
            sanitized_message=sanitized,
            error_id=error_id,
        )

    def _sanitize_dict(self, d: dict[str, Any]) -> dict[str, Any]:
        """Sanitize all values in a dict."""
        result: dict[str, Any] = {}
        for key, value in d.items():
            if isinstance(value, str):
                # Mask sensitive patterns
                if _PROMPT_CONTENT_REGEX.search(value):
                    result[key] = "[MASKED:prompt_content]"
                elif _SENSITIVE_PATH_PATTERN.search(value):
                    result[key] = _SENSITIVE_PATH_PATTERN.sub("[PATH]", value)
                elif len(value) > MAX_ERROR_MESSAGE_LENGTH:
                    result[key] = value[:MAX_ERROR_MESSAGE_LENGTH] + "..."
                else:
                    result[key] = value
            elif isinstance(value, dict):
                result[key] = self._sanitize_dict(value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _generate_error_id() -> str:
        """Generate unique error ID for log correlation."""
        return f"err_{secrets.token_hex(8)}"


# ============================================================================
# AuditLogger Class
# ============================================================================


class AuditLogger:
    """
    Security audit logger for recording detection events.

    Per §4.4.1: Records security-relevant events for monitoring and review.

    Usage:
        audit = AuditLogger()
        audit.log_security_event(
            SecurityEventType.PROMPT_LEAKAGE_DETECTED,
            severity="high",
            details={"source": "llm_extract", "fragment_count": 2},
        )
    """

    def __init__(self) -> None:
        """Initialize audit logger."""
        self._logger = get_logger("security.audit")

    def log_security_event(
        self,
        event_type: SecurityEventType,
        severity: str = "medium",
        details: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> str:
        """
        Log a security event.

        Args:
            event_type: Type of security event.
            severity: Event severity (low, medium, high, critical).
            details: Additional details (will be sanitized).
            task_id: Associated task ID if applicable.

        Returns:
            Event ID for reference.
        """
        event_id = f"sec_{secrets.token_hex(8)}"

        log_data: dict[str, Any] = {
            "event_id": event_id,
            "event_type": event_type.value,
            "severity": severity,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if task_id:
            log_data["task_id"] = task_id

        if details:
            # Sanitize details before logging
            log_data["details"] = self._sanitize_audit_details(details)

        # Log at appropriate level based on severity
        if severity == "critical":
            self._logger.error("Security event", **log_data)
        elif severity == "high":
            self._logger.warning("Security event", **log_data)
        else:
            self._logger.info("Security event", **log_data)

        return event_id

    def log_prompt_leakage(
        self,
        source: str,
        fragment_count: int,
        task_id: str | None = None,
    ) -> str:
        """
        Log a prompt leakage detection event.

        Args:
            source: Source of leakage (e.g., "llm_extract", "mcp_response").
            fragment_count: Number of leaked fragments detected.
            task_id: Associated task ID.

        Returns:
            Event ID.
        """
        return self.log_security_event(
            SecurityEventType.PROMPT_LEAKAGE_DETECTED,
            severity="high",
            details={
                "source": source,
                "fragment_count": fragment_count,
            },
            task_id=task_id,
        )

    def log_dangerous_pattern(
        self,
        patterns: list[str],
        source: str,
        task_id: str | None = None,
    ) -> str:
        """
        Log dangerous pattern detection.

        Args:
            patterns: List of detected pattern names (not content).
            source: Source of input.
            task_id: Associated task ID.

        Returns:
            Event ID.
        """
        return self.log_security_event(
            SecurityEventType.DANGEROUS_PATTERN_DETECTED,
            severity="medium",
            details={
                "source": source,
                "pattern_count": len(patterns),
                # Don't log actual patterns to avoid log injection
            },
            task_id=task_id,
        )

    def _sanitize_audit_details(
        self,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """Sanitize audit details to prevent sensitive data in logs."""
        result: dict[str, Any] = {}

        for key, value in details.items():
            if isinstance(value, str):
                # Never log actual prompt/content fragments
                if len(value) > 50:
                    result[key] = f"[{len(value)} chars]"
                elif _PROMPT_CONTENT_REGEX.search(value):
                    result[key] = "[masked]"
                else:
                    result[key] = value
            elif isinstance(value, (int, float, bool)):
                result[key] = value
            elif isinstance(value, list):
                result[key] = f"[{len(value)} items]"
            elif isinstance(value, dict):
                result[key] = self._sanitize_audit_details(value)
            else:
                result[key] = str(type(value).__name__)

        return result


# ============================================================================
# Structlog Processor
# ============================================================================


def sanitize_log_processor(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Structlog processor that sanitizes sensitive content in logs.

    Per §4.4.1 L8: Automatically detect and mask prompt content in logs.

    Add to structlog processors:
        processors = [
            ...,
            sanitize_log_processor,
            ...,
        ]
    """
    # Fields to check for sensitive content
    sensitive_fields = {"prompt", "content", "text", "message", "input", "output"}

    for key, value in list(event_dict.items()):
        if key in sensitive_fields and isinstance(value, str):
            # Check for prompt-like content
            if _PROMPT_CONTENT_REGEX.search(value):
                # Replace with hash and length
                content_hash = hashlib.sha256(value.encode()).hexdigest()[:8]
                event_dict[key] = f"[SANITIZED:hash={content_hash},len={len(value)}]"
            elif len(value) > 500:
                # Truncate long values
                content_hash = hashlib.sha256(value.encode()).hexdigest()[:8]
                event_dict[key] = f"{value[:100]}...[hash={content_hash},len={len(value)}]"

    return event_dict


# ============================================================================
# Module-level Instances
# ============================================================================

_default_secure_logger: SecureLogger | None = None
_default_audit_logger: AuditLogger | None = None


def get_secure_logger(name: str | None = None) -> SecureLogger:
    """
    Get a SecureLogger instance.

    Args:
        name: Logger name.

    Returns:
        SecureLogger instance.
    """
    global _default_secure_logger

    if name:
        return SecureLogger(name)

    if _default_secure_logger is None:
        _default_secure_logger = SecureLogger()

    return _default_secure_logger


def get_audit_logger() -> AuditLogger:
    """
    Get the AuditLogger instance.

    Returns:
        AuditLogger singleton.
    """
    global _default_audit_logger

    if _default_audit_logger is None:
        _default_audit_logger = AuditLogger()

    return _default_audit_logger

    return _default_audit_logger
