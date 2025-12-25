"""
MCP Server implementation for Lyra.
Provides tools for research operations that can be called by Cursor/LLM.

Provides 10 MCP tools per ADR-0010 async architecture:
- Removed: search (replaced by queue_searches), notify_user, wait_for_user
- Added: queue_searches (ADR-0010)
- Modified: get_status (long polling with wait parameter)
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mcp.server import Server
from src.mcp.response_meta import attach_meta, create_minimal_meta
from src.storage.database import close_database, get_database
from src.utils.logging import LogContext, ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)

# Create MCP server instance
app = Server("lyra")


# ============================================================
# Tool Definitions (10 tools per ADR-0010 async architecture)
# ============================================================

TOOLS = [
    # ============================================================
    # 1. Task Management (2 tools)
    # ============================================================
    Tool(
        name="create_task",
        description="Create a new research task. Returns task_id for subsequent operations.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Research question or topic"},
                "config": {
                    "type": "object",
                    "description": "Optional configuration",
                    "properties": {
                        "budget": {
                            "type": "object",
                            "properties": {
                                "budget_pages": {"type": "integer", "default": 120},
                                "max_seconds": {"type": "integer", "default": 1200},
                            },
                        },
                        "priority_domains": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Domains to prioritize",
                        },
                        "language": {
                            "type": "string",
                            "description": "Primary language (ja, en, etc.)",
                        },
                    },
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_status",
        description="Get unified task and exploration status. Returns task info, search states (including queued), metrics, budget, and auth queue. Supports wait (long polling). Per ADR-0003, ADR-0010.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to get status for"},
                "wait": {
                    "type": "integer",
                    "description": "Max seconds to wait for progress before returning (long polling). Default: 0 (immediate).",
                    "default": 0,
                    "minimum": 0,
                    "maximum": 60,
                },
            },
            "required": ["task_id"],
        },
    ),
    # ============================================================
    # 2. Research Execution (2 tools)
    # ============================================================
    Tool(
        name="queue_searches",
        description="Queue multiple search queries for background execution. Returns immediately. Use get_status(wait=N) to monitor progress. Per ADR-0010: Async search queue.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Search queries to execute in background",
                    "minItems": 1,
                },
                "options": {
                    "type": "object",
                    "description": "Optional search options applied to all queries",
                    "properties": {
                        "engines": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific engines to use (optional)",
                        },
                        "budget_pages": {
                            "type": "integer",
                            "description": "Page fetch budget per search (max pages to fetch)",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "default": "medium",
                            "description": "Scheduling priority. high=10, medium=50, low=90.",
                        },
                    },
                },
            },
            "required": ["task_id", "queries"],
        },
    ),
    # NOTE: search tool removed (ADR-0010: async search queue).
    # Use queue_searches + get_status(wait=N) instead.
    Tool(
        name="stop_task",
        description="Stop/finalize a research task. Returns summary with completion stats. Mode controls how running searches are handled (ADR-0010).",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to stop"},
                "reason": {
                    "type": "string",
                    "description": "Stop reason",
                    "enum": ["completed", "budget_exhausted", "user_cancelled"],
                    "default": "completed",
                },
                "mode": {
                    "type": "string",
                    "description": "Stop mode: graceful (wait for running searches) or immediate (cancel all)",
                    "enum": ["graceful", "immediate"],
                    "default": "graceful",
                },
            },
            "required": ["task_id"],
        },
    ),
    # ============================================================
    # 3. Materials (1 tool)
    # ============================================================
    Tool(
        name="get_materials",
        description="Get report materials (claims, fragments, evidence graph) for Cursor AI to compose a report. Does NOT generate report - Cursor AI handles composition/writing (ADR-0002).",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "options": {
                    "type": "object",
                    "properties": {
                        "include_graph": {
                            "type": "boolean",
                            "description": "Include evidence graph",
                            "default": False,
                        },
                        "format": {
                            "type": "string",
                            "enum": ["structured", "narrative"],
                            "default": "structured",
                        },
                    },
                },
            },
            "required": ["task_id"],
        },
    ),
    # ============================================================
    # 4. Calibration (2 tools)
    # ============================================================
    Tool(
        name="calibration_metrics",
        description="Calibration metrics operations. Actions: get_stats, evaluate, get_evaluations, get_diagram_data. For ground-truth collection, use feedback(edge_correct). For rollback, use calibration_rollback.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "get_stats",
                        "evaluate",
                        "get_evaluations",
                        "get_diagram_data",
                    ],
                    "description": "Action to perform",
                },
                "data": {
                    "type": "object",
                    "description": "Action-specific data. evaluate: {source, predictions, labels}. get_evaluations: {source?, limit?, since?}. get_diagram_data: {source, evaluation_id?}. get_stats: no data required.",
                },
            },
            "required": ["action"],
        },
    ),
    Tool(
        name="calibration_rollback",
        description="Rollback calibration parameters to a previous version (destructive operation). Per ADR-0003: Separate tool because rollback is destructive and irreversible.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source model identifier"},
                "version": {
                    "type": "integer",
                    "description": "Target version (omit for previous version)",
                },
                "reason": {"type": "string", "description": "Reason for rollback (audit log)"},
            },
            "required": ["source"],
        },
    ),
    # ============================================================
    # 5. Authentication Queue (2 tools)
    # ============================================================
    Tool(
        name="get_auth_queue",
        description="Get pending authentication queue. Per ADR-0003: Supports grouping by domain/type and priority filtering.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID (optional, omit for all tasks)",
                },
                "group_by": {
                    "type": "string",
                    "enum": ["none", "domain", "type"],
                    "description": "Grouping mode",
                    "default": "none",
                },
                "priority_filter": {
                    "type": "string",
                    "enum": ["high", "medium", "low", "all"],
                    "description": "Filter by priority",
                    "default": "all",
                },
            },
        },
    ),
    Tool(
        name="resolve_auth",
        description="Report authentication completion or skip. Per ADR-0003: Supports single item or domain-batch operations.",
        inputSchema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["item", "domain"],
                    "description": "Resolution target type",
                    "default": "item",
                },
                "queue_id": {"type": "string", "description": "Queue item ID (when target=item)"},
                "domain": {
                    "type": "string",
                    "description": "Domain to resolve (when target=domain)",
                },
                "action": {
                    "type": "string",
                    "enum": ["complete", "skip"],
                    "description": "Resolution action",
                },
                "success": {
                    "type": "boolean",
                    "description": "Whether auth succeeded (for complete action)",
                    "default": True,
                },
            },
            "required": ["action"],
        },
    ),
    # ============================================================
    # 6. Feedback (1 tool - ADR-0012)
    # ============================================================
    # NOTE: notify_user and wait_for_user removed (ADR-0010: async search queue).
    # Use get_status(wait=N) for long polling instead.
    Tool(
        name="feedback",
        description="Human-in-the-loop feedback for domain/claim/edge management. Provides 6 actions across 3 levels (Domain, Claim, Edge).",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "domain_block",
                        "domain_unblock",
                        "domain_clear_override",
                        "claim_reject",
                        "claim_restore",
                        "edge_correct",
                    ],
                    "description": "Action to perform",
                },
                "domain_pattern": {
                    "type": "string",
                    "description": "For domain_* actions. Glob pattern (e.g., 'example.com', '*.example.com')",
                },
                "claim_id": {
                    "type": "string",
                    "description": "For claim_reject/claim_restore",
                },
                "edge_id": {
                    "type": "string",
                    "description": "For edge_correct",
                },
                "correct_relation": {
                    "type": "string",
                    "enum": ["supports", "refutes", "neutral"],
                    "description": "For edge_correct: the correct NLI relation",
                },
                "reason": {
                    "type": "string",
                    "description": "Required for domain_block, domain_unblock, domain_clear_override, claim_reject. Optional for edge_correct.",
                },
            },
            "required": ["action"],
        },
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        List of text content responses.

    Note:
        All responses pass through L7 sanitization (ADR-0005)
        before being returned to Cursor AI.
    """
    from src.mcp.errors import MCPError, generate_error_id
    from src.mcp.response_sanitizer import sanitize_error, sanitize_response

    logger.info("Tool called", tool=name, arguments=arguments)

    try:
        result = await _dispatch_tool(name, arguments)

        # L7: Sanitize response before returning to Cursor AI
        sanitized_result = sanitize_response(result, name)

        return [
            TextContent(
                type="text", text=json.dumps(sanitized_result, ensure_ascii=False, indent=2)
            )
        ]
    except MCPError as e:
        # Structured MCP error with error code
        logger.warning(
            "Tool MCP error",
            tool=name,
            error_code=e.code.value,
            error=e.message,
        )
        # L7: Error responses also go through sanitization
        error_dict = e.to_dict()
        sanitized_error = sanitize_response(error_dict, "error")
        return [
            TextContent(type="text", text=json.dumps(sanitized_error, ensure_ascii=False, indent=2))
        ]
    except Exception as e:
        # Unexpected error - wrap in INTERNAL_ERROR with L7 sanitization
        error_id = generate_error_id()
        logger.error(
            "Tool internal error",
            tool=name,
            error=str(e),
            error_id=error_id,
            exc_info=True,
        )
        # L7: Use sanitize_error for unexpected exceptions
        error_result = sanitize_error(e, error_id)
        return [
            TextContent(type="text", text=json.dumps(error_result, ensure_ascii=False, indent=2))
        ]


async def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch tool call to appropriate handler.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result.
    """
    handlers = {
        # Task Management
        "create_task": _handle_create_task,
        "get_status": _handle_get_status,
        # Research Execution (search removed per ADR-0010, use queue_searches)
        "queue_searches": _handle_queue_searches,
        "stop_task": _handle_stop_task,
        # Materials
        "get_materials": _handle_get_materials,
        # Calibration (ADR-0012: renamed from calibrate/calibrate_rollback)
        "calibration_metrics": _handle_calibration_metrics,
        "calibration_rollback": _handle_calibration_rollback,
        # Authentication Queue
        "get_auth_queue": _handle_get_auth_queue,
        "resolve_auth": _handle_resolve_auth,
        # Feedback (notify_user, wait_for_user removed per ADR-0010)
        "feedback": _handle_feedback,
    }

    handler = handlers.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")

    return await handler(arguments)


# ============================================================
# Exploration State Management
# ============================================================

# Cache of exploration states per task
_exploration_states: dict[str, Any] = {}


async def _get_exploration_state(task_id: str) -> Any:
    """Get or create exploration state for a task."""
    from src.research.state import ExplorationState

    if task_id not in _exploration_states:
        state = ExplorationState(task_id)
        await state.load_state()
        _exploration_states[task_id] = state

    return _exploration_states[task_id]


def _clear_exploration_state(task_id: str) -> None:
    """Clear exploration state from cache."""
    if task_id in _exploration_states:
        del _exploration_states[task_id]


# ============================================================
# Task Management Handlers
# ============================================================


async def _get_search_queue_status(db: Any, task_id: str) -> dict[str, Any]:
    """Get search queue status for a task.

    Returns queue depth, running count, and item details.
    Per ADR-0010: Search queue status in get_status response.

    Args:
        db: Database connection.
        task_id: Task ID.

    Returns:
        Queue status dict with depth, running, and items.
    """
    try:
        cursor = await db.execute(
            """
            SELECT id, input_json, state, priority, queued_at, started_at, finished_at
            FROM jobs
            WHERE task_id = ? AND kind = 'search_queue'
            ORDER BY priority ASC, queued_at ASC
            """,
            (task_id,),
        )
        rows = await cursor.fetchall()

        items = []
        queued_count = 0
        running_count = 0

        for row in rows:
            if isinstance(row, dict):
                item_id = row["id"]
                input_json = row["input_json"]
                state = row["state"]
                priority = row["priority"]
                queued_at = row["queued_at"]
                started_at = row["started_at"]
                finished_at = row["finished_at"]
            else:
                item_id = row[0]
                input_json = row[1]
                state = row[2]
                priority = row[3]
                queued_at = row[4]
                started_at = row[5]
                finished_at = row[6]

            # Parse input to get query
            query = ""
            if input_json:
                try:
                    input_data = json.loads(input_json)
                    query = input_data.get("query", "")
                except json.JSONDecodeError:
                    pass

            # Count by state
            if state == "queued":
                queued_count += 1
            elif state == "running":
                running_count += 1

            items.append(
                {
                    "id": item_id,
                    "query": query,
                    "status": state,
                    "priority": priority,
                    "created_at": queued_at,
                    "started_at": started_at,
                    "completed_at": finished_at,
                }
            )

        return {
            "depth": queued_count,
            "running": running_count,
            "items": items,
        }
    except Exception as e:
        logger.warning("Failed to get search queue status", error=str(e))
        return {
            "depth": 0,
            "running": 0,
            "items": [],
        }


async def _get_domain_overrides() -> list[dict[str, Any]]:
    """Get active domain override rules from DB.

    Returns list of override rules for get_status response .
    Per ADR-0012: expose domain_overrides for auditability.
    """
    try:
        db = await get_database()
        cursor = await db.execute(
            """
            SELECT id, domain_pattern, decision, reason, updated_at
            FROM domain_override_rules
            WHERE is_active = 1
            ORDER BY updated_at DESC
            """
        )
        rows = await cursor.fetchall()

        overrides = []
        for row in rows:
            if isinstance(row, dict):
                overrides.append(
                    {
                        "rule_id": row["id"],
                        "domain_pattern": row["domain_pattern"],
                        "decision": row["decision"],
                        "reason": row["reason"] or "",
                        "updated_at": row["updated_at"] or "",
                    }
                )
            else:
                overrides.append(
                    {
                        "rule_id": row[0],
                        "domain_pattern": row[1],
                        "decision": row[2],
                        "reason": row[3] or "",
                        "updated_at": row[4] or "",
                    }
                )
        return overrides
    except Exception as e:
        logger.warning("Failed to get domain overrides", error=str(e))
        return []


async def _handle_create_task(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle create_task tool call.

    Creates a new research task and returns task_id.
    Per ADR-0003: Returns task_id, query, created_at, budget.
    """
    import uuid
    from datetime import datetime

    query = args["query"]
    config = args.get("config", {})

    # Generate task ID
    task_id = f"task_{uuid.uuid4().hex[:8]}"

    # Extract budget config
    budget_config = config.get("budget", {})
    if "max_pages" in budget_config:
        # Legacy key is rejected (explicit schema; see ADR-0003).
        from src.mcp.errors import InvalidParamsError

        raise InvalidParamsError(
            "budget.max_pages is no longer supported; use budget.budget_pages",
            param_name="config.budget.budget_pages",
            expected="integer",
        )
    budget_pages = budget_config.get("budget_pages", 120)
    max_seconds = budget_config.get("max_seconds", 1200)

    with LogContext(task_id=task_id):
        logger.info("Creating task", query=query[:100])

        # Store task in database
        db = await get_database()

        created_at = datetime.now(UTC).isoformat()

        await db.execute(
            """
            INSERT INTO tasks (id, query, status, config_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, query, "created", json.dumps(config), created_at),
        )

        response = {
            "ok": True,
            "task_id": task_id,
            "query": query,
            "created_at": created_at,
            "budget": {
                "budget_pages": budget_pages,
                "max_seconds": max_seconds,
            },
        }
        return attach_meta(response, create_minimal_meta())


async def _handle_get_status(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_status tool call.

    Implements ADR-0003: Unified task and exploration status.
    Implements ADR-0010: Long polling with wait parameter.

    Returns task info, search states, queue status, metrics, budget, auth queue.

    Note: Returns data only, no recommendations. Cursor AI decides next actions.
    """
    from src.mcp.errors import InvalidParamsError, TaskNotFoundError

    task_id = args.get("task_id")
    wait = args.get("wait", 0)

    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )

    # Validate wait parameter
    if wait < 0 or wait > 60:
        raise InvalidParamsError(
            "wait must be between 0 and 60",
            param_name="wait",
            expected="integer 0-60",
        )

    with LogContext(task_id=task_id):
        # Get exploration state first for long polling
        state = None
        try:
            state = await _get_exploration_state(task_id)
            # Record activity for ADR-0002 idle timeout tracking
            state.record_activity()
        except Exception as e:
            logger.debug(
                "No exploration state available",
                task_id=task_id,
                error=str(e),
            )

        # Long polling: wait for status change (ADR-0010)
        if wait > 0 and state is not None:
            logger.debug(f"Long polling wait={wait}s", task_id=task_id)
            await state.wait_for_change(timeout=float(wait))

        # Get task info from DB
        db = await get_database()
        task = await db.fetch_one(
            "SELECT id, query, status, created_at FROM tasks WHERE id = ?",
            (task_id,),
        )

        if task is None:
            raise TaskNotFoundError(task_id)

        # Map DB status to spec status
        db_status = task["status"] if isinstance(task, dict) else task[2]
        task_query = task["query"] if isinstance(task, dict) else task[1]

        # Get exploration state status
        exploration_status = None
        if state is not None:
            try:
                exploration_status = await state.get_status()
            except Exception as e:
                logger.debug(
                    "Failed to get exploration status",
                    task_id=task_id,
                    error=str(e),
                )

        # Build unified response per ADR-0003
        if exploration_status:
            # Convert searches to ADR-0003 format (text -> query field name mapping)
            searches = []
            for sq in exploration_status.get("searches", []):
                searches.append(
                    {
                        "id": sq.get("id"),
                        "query": sq.get("text"),
                        "status": sq.get("status"),
                        "pages_fetched": sq.get("pages_fetched", 0),
                        "useful_fragments": sq.get("useful_fragments", 0),
                        "harvest_rate": sq.get("harvest_rate", 0.0),
                        "satisfaction_score": sq.get("satisfaction_score", 0.0),
                        "has_primary_source": sq.get("has_primary_source", False),
                    }
                )

            # Map task_status to status field
            status_map = {
                "exploring": "exploring",
                "created": "exploring",
                "awaiting_decision": "paused",
                "paused": "paused",  # Direct mapping for paused status
                "finalizing": "exploring",
                "completed": "completed",
                "failed": "failed",
            }
            status = status_map.get(exploration_status.get("task_status", db_status), "exploring")

            metrics = exploration_status.get("metrics", {})
            budget = exploration_status.get("budget", {})

            # Calculate remaining percent
            budget_pages_used = budget.get("budget_pages_used", 0)
            budget_pages_limit = budget.get("budget_pages_limit", 120)
            remaining_percent = int((1 - budget_pages_used / max(1, budget_pages_limit)) * 100)

            # Get blocked domains info for transparency
            from src.filter.source_verification import get_source_verifier

            verifier = get_source_verifier()
            blocked_domains = verifier.get_blocked_domains_info()

            # Get domain overrides from DB
            domain_overrides = await _get_domain_overrides()

            # Get search queue status (ADR-0010)
            queue_info = await _get_search_queue_status(db, task_id)

            response = {
                "ok": True,
                "task_id": task_id,
                "status": status,
                "query": task_query,
                "searches": searches,
                "queue": queue_info,  # ADR-0010: Search queue status
                "metrics": {
                    "total_searches": len(searches),
                    "satisfied_count": metrics.get("satisfied_count", 0),
                    "total_pages": metrics.get("total_pages", 0),
                    "total_fragments": metrics.get("total_fragments", 0),
                    "total_claims": metrics.get("total_claims", 0),
                    "elapsed_seconds": metrics.get("elapsed_seconds", 0),
                },
                "budget": {
                    "budget_pages_used": budget_pages_used,
                    "budget_pages_limit": budget_pages_limit,
                    "time_used_seconds": budget.get("time_used_seconds", 0),
                    "time_limit_seconds": budget.get("time_limit_seconds", 1200),
                    "remaining_percent": remaining_percent,
                },
                "auth_queue": exploration_status.get("authentication_queue"),
                "warnings": exploration_status.get("warnings", []),
                "idle_seconds": exploration_status.get("idle_seconds", 0),  # ADR-0002
                "blocked_domains": blocked_domains,  # Added for transparency
                "domain_overrides": domain_overrides,  #
            }
            return attach_meta(response, create_minimal_meta())
        else:
            # No exploration state - return minimal info
            # Get blocked domains info for transparency
            from src.filter.source_verification import get_source_verifier

            verifier = get_source_verifier()
            blocked_domains = verifier.get_blocked_domains_info()

            # Get domain overrides from DB
            domain_overrides = await _get_domain_overrides()

            # Get search queue status (ADR-0010)
            queue_info = await _get_search_queue_status(db, task_id)

            response = {
                "ok": True,
                "task_id": task_id,
                "status": db_status or "created",
                "query": task_query,
                "searches": [],
                "queue": queue_info,  # ADR-0010: Search queue status
                "metrics": {
                    "total_searches": 0,
                    "satisfied_count": 0,
                    "total_pages": 0,
                    "total_fragments": 0,
                    "total_claims": 0,
                    "elapsed_seconds": 0,
                },
                "budget": {
                    "budget_pages_used": 0,
                    "budget_pages_limit": 120,
                    "time_used_seconds": 0,
                    "time_limit_seconds": 1200,
                    "remaining_percent": 100,
                },
                "auth_queue": None,
                "warnings": [],
                "idle_seconds": 0,  # ADR-0002 (no exploration state)
                "blocked_domains": blocked_domains,  # Added for transparency
                "domain_overrides": domain_overrides,  #
            }
            return attach_meta(response, create_minimal_meta())


# ============================================================
# Research Execution Handlers
# ============================================================


async def _handle_queue_searches(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle queue_searches tool call.

    Queues multiple search queries for background execution.
    Returns immediately with queued count and search IDs.

    Per ADR-0010: Async search queue architecture.

    Args:
        task_id: Task ID
        queries: List of search queries
        options: Optional search options (applied to all queries)

    Returns:
        {ok: true, queued_count: N, search_ids: [...]}
    """
    import uuid

    from src.mcp.errors import InvalidParamsError, TaskNotFoundError

    task_id = args.get("task_id")
    queries = args.get("queries", [])
    options = args.get("options", {})

    # Validation
    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )

    if not queries or len(queries) == 0:
        raise InvalidParamsError(
            "queries must not be empty",
            param_name="queries",
            expected="non-empty array of strings",
        )

    if "max_pages" in options:
        raise InvalidParamsError(
            "options.max_pages is no longer supported; use options.budget_pages",
            param_name="options.budget_pages",
            expected="integer",
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

        # Determine priority value from string
        priority_str = options.get("priority", "medium")
        priority_map = {"high": 10, "medium": 50, "low": 90}
        priority_value = priority_map.get(priority_str, 50)

        # Queue each search
        search_ids = []
        now = datetime.now(UTC).isoformat()

        for query in queries:
            search_id = f"s_{uuid.uuid4().hex[:12]}"

            # Prepare input JSON
            input_data = {
                "query": query,
                "options": {k: v for k, v in options.items() if k != "priority"},
            }

            # Insert into jobs table (kind='search_queue')
            await db.execute(
                """
                INSERT INTO jobs
                    (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    search_id,
                    task_id,
                    "search_queue",
                    priority_value,
                    "network_client",
                    "queued",
                    json.dumps(input_data, ensure_ascii=False),
                    now,
                ),
            )
            search_ids.append(search_id)

        logger.info(
            "Searches queued",
            task_id=task_id,
            count=len(search_ids),
            priority=priority_str,
        )

        return {
            "ok": True,
            "queued_count": len(search_ids),
            "search_ids": search_ids,
            "message": f"{len(search_ids)} searches queued. Use get_status(wait=N) to monitor progress.",
        }


async def _check_chrome_cdp_ready() -> bool:
    """
    Check if Chrome CDP is available.

    Performs a lightweight HTTP check to the CDP endpoint without
    initializing full Playwright.

    Returns:
        True if CDP is available, False otherwise.
    """
    import aiohttp

    from src.utils.config import get_settings

    settings = get_settings()
    chrome_host = settings.browser.chrome_host
    chrome_port = settings.browser.chrome_port
    cdp_url = f"http://{chrome_host}:{chrome_port}/json/version"

    try:
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(cdp_url) as response:
                return response.status == 200
    except Exception as e:
        logger.debug("Chrome health check failed", cdp_url=cdp_url, error=str(e))
        return False


# NOTE: _handle_search removed (ADR-0010: async search queue).
# Use queue_searches + get_status(wait=N) instead.
# search_action is still used internally by SearchQueueWorker.


async def _handle_stop_task(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle stop_task tool call.

    Implements ADR-0003: Finalizes task and returns summary.
    Implements ADR-0010: Stop modes (graceful/immediate).

    Mode semantics:
    - graceful: Cancel queued jobs, wait for running jobs to complete.
    - immediate: Cancel all queued and running jobs immediately.
    """
    from src.mcp.errors import InvalidParamsError, TaskNotFoundError
    from src.research.pipeline import stop_task_action

    task_id = args.get("task_id")
    reason = args.get("reason", "completed")
    mode = args.get("mode", "graceful")

    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )

    if mode not in ("graceful", "immediate"):
        raise InvalidParamsError(
            "mode must be 'graceful' or 'immediate'",
            param_name="mode",
            expected="'graceful' or 'immediate'",
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

        # Get exploration state
        state = await _get_exploration_state(task_id)

        # Record activity for ADR-0002 idle timeout tracking
        state.record_activity()

        # Handle search queue jobs based on mode (ADR-0010)
        await _cancel_search_queue_jobs(task_id, mode, db)

        # Execute stop through unified API
        result = await stop_task_action(
            task_id=task_id,
            state=state,
            reason=reason,
            mode=mode,
        )

        # Clear cached state
        _clear_exploration_state(task_id)

        # Update task status in DB
        await db.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (result.get("final_status", "completed"), task_id),
        )

        # Include mode in response for transparency
        result["mode"] = mode

        return result


async def _cancel_search_queue_jobs(
    task_id: str,
    mode: str,
    db: Any,
) -> dict[str, int]:
    """
    Cancel search queue jobs for a task based on stop mode.

    Args:
        task_id: The task ID.
        mode: Stop mode ('graceful' or 'immediate').
        db: Database connection.

    Returns:
        Dict with counts of cancelled jobs by previous state.

    Mode semantics (ADR-0010):
    - graceful: Only cancel 'queued' jobs. Running jobs complete normally.
    - immediate: Cancel both 'queued' and 'running' jobs, including in-flight
                 search_action executions via asyncio.Task.cancel().
    """
    from datetime import UTC, datetime

    from src.scheduler.search_worker import get_worker_manager

    now = datetime.now(UTC).isoformat()
    counts = {"queued_cancelled": 0, "running_cancelled": 0, "tasks_cancelled": 0}

    # Always cancel queued jobs (DB state only)
    cursor = await db.execute(
        """
        UPDATE jobs
        SET state = 'cancelled', finished_at = ?
        WHERE task_id = ? AND kind = 'search_queue' AND state = 'queued'
        """,
        (now, task_id),
    )
    counts["queued_cancelled"] = getattr(cursor, "rowcount", 0)

    if mode == "immediate":
        # Cancel running jobs: both DB state and actual asyncio.Task
        # Step 1: Cancel running worker tasks (this triggers CancelledError)
        manager = get_worker_manager()
        tasks_cancelled = await manager.cancel_jobs_for_task(task_id)
        counts["tasks_cancelled"] = tasks_cancelled

        # Step 2: Update DB state for any running jobs that weren't tracked
        # (defensive: handles edge cases where job wasn't registered)
        cursor = await db.execute(
            """
            UPDATE jobs
            SET state = 'cancelled', finished_at = ?
            WHERE task_id = ? AND kind = 'search_queue' AND state = 'running'
            """,
            (now, task_id),
        )
        counts["running_cancelled"] = getattr(cursor, "rowcount", 0)

    logger.info(
        "Search queue jobs cancelled",
        task_id=task_id,
        mode=mode,
        queued_cancelled=counts["queued_cancelled"],
        running_cancelled=counts["running_cancelled"],
        tasks_cancelled=counts.get("tasks_cancelled", 0),
    )

    return counts


# ============================================================
# Materials Handler
# ============================================================


async def _handle_get_materials(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_materials tool call.

    Implements ADR-0003: Returns report materials for Cursor AI.
    Does NOT generate report - composition is Cursor AI's responsibility.
    """
    from src.mcp.errors import InvalidParamsError, TaskNotFoundError
    from src.research.materials import get_materials_action

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
            format=options.get("format", "structured"),
        )

        return result


# ============================================================
# Calibration Handlers (ADR-0003)
# ============================================================


async def _handle_calibration_metrics(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle calibration_metrics tool call.

    Implements calibration metrics operations (4 actions).
    Actions: get_stats, evaluate, get_evaluations, get_diagram_data.

    Note: add_sample was removed. Use feedback(edge_correct) for ground-truth collection.
    For rollback (destructive operation), use calibration_rollback tool.
    """
    from src.mcp.errors import InvalidParamsError
    from src.utils.calibration import calibration_metrics_action

    action = args.get("action")
    data = args.get("data", {})

    if not action:
        raise InvalidParamsError(
            "action is required",
            param_name="action",
            expected="one of: get_stats, evaluate, get_evaluations, get_diagram_data",
        )

    return await calibration_metrics_action(action, data)


async def _handle_calibration_rollback(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle calibration_rollback tool call.

    Implements ADR-0003: Rollback calibration parameters (destructive operation).
    Separate tool to prevent accidental invocation.
    """
    from src.mcp.errors import (
        CalibrationError,
        InvalidParamsError,
    )
    from src.utils.calibration import get_calibrator

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


# ============================================================
# Authentication Queue Handlers (ADR-0003, ADR-0007)
# ============================================================


async def _handle_get_auth_queue(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_auth_queue tool call.

    Implements ADR-0003: Get pending authentication queue.
    Supports grouping by domain/type and priority filtering.
    """
    from src.utils.notification import get_intervention_queue

    task_id = args.get("task_id")
    group_by = args.get("group_by", "none")
    priority_filter = args.get("priority_filter", "all")

    queue = get_intervention_queue()

    # Get pending items using existing get_pending method
    items = await queue.get_pending(
        task_id=task_id,
        priority=priority_filter if priority_filter != "all" else None,
    )

    # Group if requested
    if group_by == "domain":
        grouped: dict[str, list] = {}
        for item in items:
            domain = item.get("domain", "unknown")
            if domain not in grouped:
                grouped[domain] = []
            grouped[domain].append(item)

        return {
            "ok": True,
            "group_by": "domain",
            "groups": grouped,
            "total_count": len(items),
        }

    elif group_by == "type":
        grouped = {}
        for item in items:
            auth_type = item.get("auth_type", "unknown")
            if auth_type not in grouped:
                grouped[auth_type] = []
            grouped[auth_type].append(item)

        return {
            "ok": True,
            "group_by": "type",
            "groups": grouped,
            "total_count": len(items),
        }

    else:  # no grouping
        return {
            "ok": True,
            "group_by": "none",
            "items": items,
            "total_count": len(items),
        }


async def _capture_auth_session_cookies(domain: str) -> dict | None:
    """Capture cookies from browser for authentication session storage.

    Per ADR-0007: Capture session data after authentication completion
    so subsequent requests can reuse the authenticated session.

    This function connects to the existing Chrome browser via CDP and
    retrieves cookies from all existing contexts, filtering for the target domain.

    Args:
        domain: Domain to capture cookies for.

    Returns:
        Session data dict with cookies, or None if capture failed.
    """
    from datetime import datetime

    try:
        # Connect to existing Chrome browser via CDP
        from playwright.async_api import async_playwright

        from src.utils.config import get_settings

        settings = get_settings()
        chrome_host = getattr(settings.browser, "chrome_host", "localhost")
        chrome_port = getattr(settings.browser, "chrome_port", 9222)
        cdp_url = f"http://{chrome_host}:{chrome_port}"

        playwright = await async_playwright().start()

        try:
            # Connect to existing Chrome instance
            browser = await playwright.chromium.connect_over_cdp(cdp_url)

            # Get all existing contexts (these contain cookies from user's browser session)
            existing_contexts = browser.contexts

            if not existing_contexts:
                logger.debug(
                    "No browser contexts found, skipping cookie capture",
                    domain=domain,
                )
                await playwright.stop()
                return None

            # Collect cookies from all contexts
            all_cookies = []
            for context in existing_contexts:
                try:
                    context_cookies = await context.cookies()
                    all_cookies.extend(context_cookies)
                except Exception as e:
                    logger.debug(
                        "Failed to get cookies from context",
                        error=str(e),
                    )
                    continue

            # Filter cookies that match the domain
            # Per HTTP cookie spec: cookies set for subdomain should not be sent to parent domain
            # Only parent domain cookies can be sent to subdomains
            from src.crawler.session_transfer import CookieData

            domain_cookies = []
            for cookie in all_cookies:
                cookie_data = CookieData.from_playwright_cookie(dict(cookie))
                # Use CookieData.matches_domain() which correctly implements HTTP cookie domain matching
                # - Exact match: cookie.domain == target_domain
                # - Parent -> subdomain: cookie.domain="example.com" matches "sub.example.com"
                # - Subdomain -> parent: NOT allowed (correctly rejected)
                if cookie_data.matches_domain(domain):
                    domain_cookies.append(dict(cookie))

            await playwright.stop()

            if not domain_cookies:
                logger.debug(
                    "No cookies found for domain",
                    domain=domain,
                )
                return None

            session_data = {
                "cookies": domain_cookies,
                "captured_at": datetime.now(UTC).isoformat(),
                "domain": domain,
            }

            logger.info(
                "Captured authentication session cookies",
                domain=domain,
                cookie_count=len(domain_cookies),
                contexts_checked=len(existing_contexts),
            )

            return session_data

        except Exception:
            await playwright.stop()
            raise

    except Exception as e:
        logger.warning(
            "Failed to capture authentication session cookies",
            domain=domain,
            error=str(e),
        )
        return None


async def _handle_resolve_auth(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle resolve_auth tool call.

    Implements ADR-0003: Report authentication completion or skip.
    Per ADR-0007: Captures session cookies on completion for reuse.
    Supports single item or domain-batch operations.
    """
    from src.mcp.errors import InvalidParamsError
    from src.utils.notification import get_intervention_queue

    target = args.get("target", "item")
    action = args.get("action")
    success = args.get("success", True)

    if not action:
        raise InvalidParamsError(
            "action is required",
            param_name="action",
            expected="one of: complete, skip",
        )

    valid_actions = {"complete", "skip"}
    if action not in valid_actions:
        raise InvalidParamsError(
            f"Invalid action: {action}",
            param_name="action",
            expected="one of: complete, skip",
        )

    valid_targets = {"item", "domain"}
    if target not in valid_targets:
        raise InvalidParamsError(
            f"Invalid target: {target}",
            param_name="target",
            expected="one of: item, domain",
        )

    queue = get_intervention_queue()

    if target == "item":
        queue_id = args.get("queue_id")
        if not queue_id:
            raise InvalidParamsError(
                "queue_id is required when target=item",
                param_name="queue_id",
                expected="non-empty string",
            )

        if action == "complete":
            # Get domain from queue item for cookie capture
            item = await queue.get_item(queue_id)
            session_data = None
            if item and success:
                domain = item.get("domain")
                if domain:
                    session_data = await _capture_auth_session_cookies(domain)

            result = await queue.complete(queue_id, success=success, session_data=session_data)
        else:  # skip
            result = await queue.skip(queue_ids=[queue_id])

        return {
            "ok": True,
            "target": "item",
            "queue_id": queue_id,
            "action": action,
            "success": success if action == "complete" else None,
        }

    elif target == "domain":
        domain = args.get("domain")
        if not domain:
            raise InvalidParamsError(
                "domain is required when target=domain",
                param_name="domain",
                expected="non-empty string",
            )

        if action == "complete":
            # Capture cookies for the domain
            session_data = None
            if success:
                session_data = await _capture_auth_session_cookies(domain)

            result = await queue.complete_domain(domain, success=success, session_data=session_data)
            count = result.get("resolved_count", 0)
        else:  # skip
            result = await queue.skip(domain=domain)
            count = result.get("skipped", 0)

        return {
            "ok": True,
            "target": "domain",
            "domain": domain,
            "action": action,
            "resolved_count": count,
        }

    else:
        raise InvalidParamsError(
            f"Invalid target: {target}",
            param_name="target",
            expected="one of: item, domain",
        )


# ============================================================
# NOTE: Notification Handlers removed (ADR-0010: async search queue)
# _handle_notify_user and _handle_wait_for_user were removed.
# Use get_status(wait=N) for long polling instead.
# ============================================================


# ============================================================
# Feedback Handler
# ============================================================


async def _handle_feedback(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle feedback tool call.

    Implements ADR-0012: Human-in-the-loop feedback for domain/claim/edge management.
    Provides 6 actions across 3 levels:
    - Domain: domain_block, domain_unblock, domain_clear_override
    - Claim: claim_reject, claim_restore
    - Edge: edge_correct
    """
    from src.mcp.errors import InvalidParamsError
    from src.mcp.feedback_handler import handle_feedback_action

    action = args.get("action")

    if not action:
        raise InvalidParamsError(
            "action is required",
            param_name="action",
            expected="one of: domain_block, domain_unblock, domain_clear_override, claim_reject, claim_restore, edge_correct",
        )

    # Delegate to feedback handler
    return await handle_feedback_action(action, args)


# ============================================================
# Server Entry Point
# ============================================================


async def run_server() -> None:
    """Run the MCP server."""
    logger.info("Starting Lyra MCP server (10 tools)")

    # Initialize database
    await get_database()

    # Restore domain overrides from DB (ISSUE-001 fix)
    from src.filter.source_verification import load_domain_overrides_from_db

    await load_domain_overrides_from_db()

    # Start search queue workers (ADR-0010)
    from src.scheduler.search_worker import get_worker_manager

    worker_manager = get_worker_manager()
    await worker_manager.start()

    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )
    finally:
        # Stop search queue workers
        await worker_manager.stop()
        await close_database()
        logger.info("Lyra MCP server stopped")


def main() -> None:
    """Main entry point."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
