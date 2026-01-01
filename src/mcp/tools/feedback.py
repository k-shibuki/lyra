"""Feedback handler for MCP tools.

Handles feedback operation.
"""

from typing import Any

from src.mcp.errors import InvalidParamsError
from src.mcp.feedback_handler import handle_feedback_action
from src.utils.logging import ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)


async def handle_feedback(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle feedback tool call.

    Implements ADR-0012: Human-in-the-loop feedback for domain/claim/edge management.
    Provides 6 actions across 3 levels:
    - Domain: domain_block, domain_unblock, domain_clear_override
    - Claim: claim_reject, claim_restore
    - Edge: edge_correct
    """
    action = args.get("action")

    if not action:
        raise InvalidParamsError(
            "action is required",
            param_name="action",
            expected="one of: domain_block, domain_unblock, domain_clear_override, claim_reject, claim_restore, edge_correct",
        )

    # Delegate to feedback handler
    return await handle_feedback_action(action, args)
