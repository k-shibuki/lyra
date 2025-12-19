"""
Structured logging configuration for Lancet.
Uses structlog for JSON-formatted logs with causal tracing.
"""

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from structlog.types import Processor

from src.utils.config import get_project_root, get_settings


def _add_timestamp(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add ISO timestamp to log event."""
    event_dict["timestamp"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return event_dict


def _add_log_level(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add log level to event dict."""
    event_dict["level"] = method_name.upper()
    return event_dict


def _filter_health_check(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Filter out noisy health check logs."""
    if event_dict.get("event", "").startswith("health_check"):
        if method_name == "debug":
            raise structlog.DropEvent
    return event_dict


def configure_logging(
    log_level: str | None = None,
    log_file: str | Path | None = None,
    json_format: bool = True,
) -> None:
    """Configure structured logging.

    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR). Uses settings if None.
        log_file: Path to log file. Uses settings if None.
        json_format: Whether to use JSON format (True) or console format (False).
    """
    settings = get_settings()

    if log_level is None:
        log_level = settings.general.log_level

    if log_file is None:
        log_dir = get_project_root() / settings.general.logs_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"lancet_{datetime.now().strftime('%Y%m%d')}.log"

    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure stdlib logging
    logging.basicConfig(
        format="%(message)s",
        level=numeric_level,
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    # Define processors
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        _add_timestamp,
        _add_log_level,
        _filter_health_check,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_format:
        # JSON format for file logging and production
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
    else:
        # Console format for development
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a logger instance.

    Args:
        name: Logger name (usually __name__).

    Returns:
        Configured logger instance.
    """
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """Bind context variables to all subsequent log calls.

    Useful for adding task_id, job_id, cause_id to all logs
    within a context.

    Args:
        **kwargs: Context variables to bind.
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    """Unbind context variables.

    Args:
        *keys: Context variable keys to unbind.
    """
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """Clear all bound context variables."""
    structlog.contextvars.clear_contextvars()


class LogContext:
    """Context manager for scoped logging context.

    Example:
        with LogContext(task_id="123", job_id="456"):
            logger.info("Processing task")
            # All logs within this block will have task_id and job_id
    """

    def __init__(self, **kwargs: Any):
        """Initialize with context variables.

        Args:
            **kwargs: Context variables to bind.
        """
        self.context = kwargs
        self._token = None

    def __enter__(self) -> "LogContext":
        """Enter context and bind variables."""
        bind_context(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context and unbind variables."""
        unbind_context(*self.context.keys())


class CausalTrace:
    """Helper for managing causal trace IDs.

    Ensures all operations within a trace share the same cause_id,
    enabling reconstruction of decision chains.
    """

    def __init__(self, cause_id: str | None = None):
        """Initialize causal trace.

        Args:
            cause_id: Parent cause ID. If None, this is a root cause.
        """
        import uuid
        self.trace_id = str(uuid.uuid4())
        self.parent_id = cause_id

    def __enter__(self) -> "CausalTrace":
        """Enter trace context."""
        bind_context(
            cause_id=self.trace_id,
            parent_cause_id=self.parent_id,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit trace context."""
        unbind_context("cause_id", "parent_cause_id")

    @property
    def id(self) -> str:
        """Get the trace ID."""
        return self.trace_id


# Initialize logging on module import
_logging_configured = False


def ensure_logging_configured() -> None:
    """Ensure logging is configured (call once at startup)."""
    global _logging_configured
    if not _logging_configured:
        configure_logging()
        _logging_configured = True

