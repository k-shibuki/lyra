"""View query handler for MCP tools.

Handles query_view and list_views operations (predefined SQL template execution).
"""

from __future__ import annotations

import time
from typing import Any

from jinja2 import TemplateNotFound

from src.mcp.errors import InvalidParamsError
from src.mcp.tools.sql import validate_sql_text
from src.storage.database import get_database
from src.storage.view_manager import get_view_manager
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def handle_list_views(args: dict[str, Any]) -> dict[str, Any]:
    """Handle list_views tool call.

    Lists all available SQL view templates.

    Args:
        args: Tool arguments (unused, no parameters).

    Returns:
        Dict with 'ok', 'views' (list of view names with descriptions).
    """
    _ = args  # No parameters needed

    vm = get_view_manager()
    view_names = vm.list_views()

    # Build view metadata
    views = []
    for name in view_names:
        # Extract description from template comment if available
        description = _get_view_description(name)
        views.append({"name": name, "description": description})

    return {
        "ok": True,
        "views": views,
        "count": len(views),
    }


def _get_view_description(view_name: str) -> str:
    """Extract description from view template.

    Args:
        view_name: Template name.

    Returns:
        Description string or empty string if not found.
    """
    # Map of view names to descriptions
    descriptions = {
        "v_claim_evidence_summary": "Per-claim support/refute counts and controversy scores",
        "v_contradictions": "Claims with conflicting evidence (supports vs refutes)",
        "v_unsupported_claims": "Claims with no supporting evidence",
        "v_evidence_chain": "Full evidence chain from claims through fragments to sources",
        "v_hub_pages": "High-connectivity pages (citation hubs)",
        "v_citation_flow": "Citation relationships between pages",
        "v_bibliographic_coupling": "Bibliographic coupling: papers cited by the same papers (coupling strength = shared citers)",
        "v_citation_chains": "Citation chains showing A→B→C paths through literature",
        "v_orphan_sources": "Pages with no outgoing citations",
        "v_evidence_timeline": "Evidence organized by publication year",
        "v_claim_temporal_support": "How claim support changes over time",
        "v_emerging_consensus": "Claims gaining support in recent publications",
        "v_outdated_evidence": "Evidence from older sources that may need updating",
        "v_source_authority": "Page authority scores based on citations",
        "v_controversy_by_era": "How controversy evolved over time",
        "v_citation_age_gap": "Gap between citing and cited publication years",
        "v_evidence_freshness": "Recency of evidence supporting claims",
    }
    return descriptions.get(view_name, "")


async def handle_query_view(args: dict[str, Any]) -> dict[str, Any]:
    """Handle query_view tool call.

    Renders and executes a predefined SQL template.

    Args:
        args: Tool arguments with 'view_name', optional 'task_id', 'params', 'limit'.

    Returns:
        Query result dict with 'ok', 'rows', 'row_count', 'columns', etc.
    """
    view_name = args.get("view_name")
    task_id = args.get("task_id")
    params = args.get("params", {})
    limit = args.get("limit", 50)

    if not view_name:
        raise InvalidParamsError(
            "view_name is required",
            param_name="view_name",
            expected="non-empty string",
        )

    # Validate limit
    if limit < 1 or limit > 200:
        raise InvalidParamsError(
            "limit must be between 1 and 200",
            param_name="limit",
            expected="integer 1-200",
        )

    start_time = time.time()

    try:
        vm = get_view_manager()

        # Render template with parameters
        sql = vm.render(view_name, task_id=task_id, **params)

        # Validate the rendered SQL (read-only check)
        try:
            validate_sql_text(sql)
        except ValueError as e:
            logger.error(
                "View template rendered invalid SQL",
                view_name=view_name,
                error=str(e),
            )
            return {
                "ok": False,
                "rows": [],
                "row_count": 0,
                "columns": [],
                "truncated": False,
                "elapsed_ms": int((time.time() - start_time) * 1000),
                "error": f"Template rendered invalid SQL: {e}",
            }

        # Execute the query
        db = await get_database()
        sql_with_limit = f"{sql.rstrip(';')} LIMIT {limit + 1}"
        rows = await db.fetch_all(sql_with_limit)

        # Check if truncated
        rows_list = list(rows)
        truncated = len(rows_list) > limit
        if truncated:
            rows_list = rows_list[:limit]

        # Convert to dicts
        result_rows = [dict(row) for row in rows_list]

        # Extract columns from first row (if any)
        columns = list(result_rows[0].keys()) if result_rows else []

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "ok": True,
            "view_name": view_name,
            "rows": result_rows,
            "row_count": len(result_rows),
            "columns": columns,
            "truncated": truncated,
            "elapsed_ms": elapsed_ms,
        }

    except TemplateNotFound:
        logger.warning("View template not found", view_name=view_name)
        return {
            "ok": False,
            "rows": [],
            "row_count": 0,
            "columns": [],
            "truncated": False,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "error": f"View template not found: {view_name}",
        }
    except Exception as e:
        logger.error("Unexpected error in query_view", error=str(e), exc_info=True)
        return {
            "ok": False,
            "rows": [],
            "row_count": 0,
            "columns": [],
            "truncated": False,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "error": str(e),
        }
