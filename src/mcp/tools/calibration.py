"""Calibration handlers for MCP tools.

Handles calibration_metrics and calibration_rollback operations.
"""

from typing import Any

from src.mcp.errors import CalibrationError, InvalidParamsError
from src.utils.logging import ensure_logging_configured, get_logger
from src.utils.nli_calibration import calibration_metrics_action, get_calibrator

ensure_logging_configured()
logger = get_logger(__name__)


async def handle_calibration_metrics(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle calibration_metrics tool call.

    Implements calibration metrics operations (2 actions).
    Actions: get_stats, get_evaluations.

    Note: add_sample was removed. Use feedback(edge_correct) for ground-truth collection.
    Batch evaluation/visualization are handled by scripts (see ADR-0011).
    For rollback (destructive operation), use calibration_rollback tool.
    """
    action = args.get("action")
    data = args.get("data", {})

    if not action:
        raise InvalidParamsError(
            "action is required",
            param_name="action",
            expected="one of: get_stats, get_evaluations",
        )

    return await calibration_metrics_action(action, data)


async def handle_calibration_rollback(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle calibration_rollback tool call.

    Implements ADR-0003: Rollback calibration parameters (destructive operation).
    Separate tool to prevent accidental invocation.
    """
    source = args.get("source")
    version = args.get("version")
    reason = args.get("reason", "Manual rollback")

    if not source:
        raise InvalidParamsError(
            "source is required",
            param_name="source",
            expected="non-empty string (e.g., 'llm_extract', 'nli_judge')",
        )

    logger.info(
        "Calibration rollback requested",
        source=source,
        target_version=version,
        reason=reason,
    )

    # Get calibrator
    calibrator = get_calibrator()

    # Get current parameters for logging
    current_params = calibrator.get_params(source)
    previous_version = current_params.version if current_params else 0

    # Determine target version
    if version is not None:
        target_version = version
    else:
        # Default: roll back to previous version
        if previous_version <= 1:
            raise CalibrationError(
                f"Cannot rollback: no previous version for source '{source}'",
                source=source,
            )
        target_version = previous_version - 1

    # Perform rollback (synchronous method)
    try:
        rolled_back_params = calibrator.rollback_to_version(
            source=source,
            version=target_version,
            reason=reason,
        )
    except ValueError as e:
        raise CalibrationError(str(e), source=source) from e

    if rolled_back_params is None:
        raise CalibrationError(
            f"Rollback failed: version {target_version} not found for source '{source}'",
            source=source,
        )

    # Log the rollback
    logger.warning(
        "Calibration rolled back",
        source=source,
        from_version=previous_version,
        to_version=rolled_back_params.version,
        reason=reason,
    )

    return {
        "ok": True,
        "source": source,
        "rolled_back_to": rolled_back_params.version,
        "previous_version": previous_version,
        "reason": reason,
        "brier_after": rolled_back_params.brier_after,
        "method": rolled_back_params.method,
    }


