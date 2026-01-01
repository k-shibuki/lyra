"""Materials handler for MCP tools.

Handles get_materials operation.
"""

from typing import Any

from src.mcp.errors import InvalidParamsError, TaskNotFoundError
from src.research.materials import get_materials_action
from src.storage.database import get_database
from src.utils.logging import LogContext, ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)


async def handle_get_materials(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_materials tool call.

    Implements ADR-0003: Returns report materials for Cursor AI.
    Does NOT generate report - composition is Cursor AI's responsibility.
    """
    task_id = args.get("task_id")
    options = args.get("options", {})

    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )

    with LogContext(task_id=task_id):
        # Verify task exists
        db = await get_database()
        task = await db.fetch_one(
            "SELECT id FROM tasks WHERE id = ?",
            (task_id,),
        )

        if task is None:
            raise TaskNotFoundError(task_id)

        # Get materials through unified API
        result = await get_materials_action(
            task_id=task_id,
            include_graph=options.get("include_graph", False),
            include_citations=options.get("include_citations", False),
            format=options.get("format", "structured"),
        )
        return result
