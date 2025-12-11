"""
MCP Server implementation for Lancet.
Provides tools for research operations that can be called by Cursor/LLM.

Phase M: Refactored to 11 tools per requirements.md §3.2.1.
"""

import asyncio
import json
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from src.utils.logging import get_logger, ensure_logging_configured, LogContext
from src.storage.database import get_database, close_database
from src.mcp.response_meta import create_minimal_meta, attach_meta

ensure_logging_configured()
logger = get_logger(__name__)

# Create MCP server instance
app = Server("lancet")


# ============================================================
# Tool Definitions (Phase M - §3.2.1: 11 Tools)
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
                "query": {
                    "type": "string",
                    "description": "Research question or topic"
                },
                "config": {
                    "type": "object",
                    "description": "Optional configuration",
                    "properties": {
                        "budget": {
                            "type": "object",
                            "properties": {
                                "max_pages": {"type": "integer", "default": 120},
                                "max_seconds": {"type": "integer", "default": 1200}
                            }
                        },
                        "priority_domains": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Domains to prioritize"
                        },
                        "language": {
                            "type": "string",
                            "description": "Primary language (ja, en, etc.)"
                        }
                    }
                }
            },
            "required": ["query"]
        }
    ),
    Tool(
        name="get_status",
        description="Get unified task and exploration status. Returns task info, search states, metrics, budget, and auth queue. Cursor AI uses this to decide next actions. Per §3.2.1: No recommendations - data only.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to get status for"
                }
            },
            "required": ["task_id"]
        }
    ),
    # ============================================================
    # 2. Research Execution (2 tools)
    # ============================================================
    Tool(
        name="search",
        description="Execute a search query designed by Cursor AI. Runs the full search→fetch→extract→evaluate pipeline. Use refute:true for refutation mode.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID"
                },
                "query": {
                    "type": "string",
                    "description": "Search query (designed by Cursor AI)"
                },
                "options": {
                    "type": "object",
                    "description": "Search options",
                    "properties": {
                        "engines": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific engines to use (optional)"
                        },
                        "max_pages": {
                            "type": "integer",
                            "description": "Maximum pages for this search"
                        },
                        "seek_primary": {
                            "type": "boolean",
                            "description": "Prioritize primary sources",
                            "default": False
                        },
                        "refute": {
                            "type": "boolean",
                            "description": "Enable refutation mode (applies mechanical suffix patterns)",
                            "default": False
                        }
                    }
                }
            },
            "required": ["task_id", "query"]
        }
    ),
    Tool(
        name="stop_task",
        description="Stop/finalize a research task. Returns summary with completion stats.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to stop"
                },
                "reason": {
                    "type": "string",
                    "description": "Stop reason",
                    "enum": ["completed", "budget_exhausted", "user_cancelled"],
                    "default": "completed"
                }
            },
            "required": ["task_id"]
        }
    ),
    # ============================================================
    # 3. Materials (1 tool)
    # ============================================================
    Tool(
        name="get_materials",
        description="Get report materials (claims, fragments, evidence graph) for Cursor AI to compose a report. Does NOT generate report - Cursor AI handles composition/writing (§2.1).",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID"
                },
                "options": {
                    "type": "object",
                    "properties": {
                        "include_graph": {
                            "type": "boolean",
                            "description": "Include evidence graph",
                            "default": False
                        },
                        "format": {
                            "type": "string",
                            "enum": ["structured", "narrative"],
                            "default": "structured"
                        }
                    }
                }
            },
            "required": ["task_id"]
        }
    ),
    # ============================================================
    # 4. Calibration (2 tools)
    # ============================================================
    Tool(
        name="calibrate",
        description="Unified calibration operations (daily operations). Actions: add_sample, get_stats, evaluate, get_evaluations, get_diagram_data. For rollback (destructive), use calibrate_rollback.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add_sample", "get_stats", "evaluate", "get_evaluations", "get_diagram_data"],
                    "description": "Action to perform"
                },
                "data": {
                    "type": "object",
                    "description": "Action-specific data. add_sample: {source, prediction, actual, logit?}. evaluate: {source, predictions, labels}. get_evaluations: {source?, limit?, since?}. get_diagram_data: {source, evaluation_id?}. get_stats: no data required."
                }
            },
            "required": ["action"]
        }
    ),
    Tool(
        name="calibrate_rollback",
        description="Rollback calibration parameters to a previous version (destructive operation). Per §3.2.1: Separate tool because rollback is destructive and irreversible.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source model identifier"
                },
                "version": {
                    "type": "integer",
                    "description": "Target version (omit for previous version)"
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for rollback (audit log)"
                }
            },
            "required": ["source"]
        }
    ),
    # ============================================================
    # 5. Authentication Queue (2 tools)
    # ============================================================
    Tool(
        name="get_auth_queue",
        description="Get pending authentication queue. Per §3.2.1: Supports grouping by domain/type and priority filtering.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID (optional, omit for all tasks)"
                },
                "group_by": {
                    "type": "string",
                    "enum": ["none", "domain", "type"],
                    "description": "Grouping mode",
                    "default": "none"
                },
                "priority_filter": {
                    "type": "string",
                    "enum": ["high", "medium", "low", "all"],
                    "description": "Filter by priority",
                    "default": "all"
                }
            }
        }
    ),
    Tool(
        name="resolve_auth",
        description="Report authentication completion or skip. Per §3.2.1: Supports single item or domain-batch operations.",
        inputSchema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["item", "domain"],
                    "description": "Resolution target type",
                    "default": "item"
                },
                "queue_id": {
                    "type": "string",
                    "description": "Queue item ID (when target=item)"
                },
                "domain": {
                    "type": "string",
                    "description": "Domain to resolve (when target=domain)"
                },
                "action": {
                    "type": "string",
                    "enum": ["complete", "skip"],
                    "description": "Resolution action"
                },
                "success": {
                    "type": "boolean",
                    "description": "Whether auth succeeded (for complete action)",
                    "default": True
                }
            },
            "required": ["action"]
        }
    ),
    # ============================================================
    # 6. Notification (2 tools)
    # ============================================================
    Tool(
        name="notify_user",
        description="Send notification to user. Per §3.2.1: Event types for auth, progress, and errors.",
        inputSchema={
            "type": "object",
            "properties": {
                "event": {
                    "type": "string",
                    "enum": ["auth_required", "task_progress", "task_complete", "error", "info"],
                    "description": "Notification event type"
                },
                "payload": {
                    "type": "object",
                    "description": "Event-specific payload",
                    "properties": {
                        "url": {"type": "string"},
                        "domain": {"type": "string"},
                        "message": {"type": "string"},
                        "task_id": {"type": "string"},
                        "progress_percent": {"type": "number"}
                    }
                }
            },
            "required": ["event", "payload"]
        }
    ),
    Tool(
        name="wait_for_user",
        description="Wait for user input/acknowledgment. Per §3.2.1: Blocks until user responds or timeout.",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Message to show user"
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 300)",
                    "default": 300
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional choices for user"
                }
            },
            "required": ["prompt"]
        }
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
        All responses pass through L7 sanitization (§4.4.1)
        before being returned to Cursor AI.
    """
    from src.mcp.errors import MCPError, generate_error_id
    from src.mcp.response_sanitizer import sanitize_response, sanitize_error
    
    logger.info("Tool called", tool=name, arguments=arguments)
    
    try:
        result = await _dispatch_tool(name, arguments)
        
        # L7: Sanitize response before returning to Cursor AI
        sanitized_result = sanitize_response(result, name)
        
        return [TextContent(type="text", text=json.dumps(sanitized_result, ensure_ascii=False, indent=2))]
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
        return [TextContent(type="text", text=json.dumps(sanitized_error, ensure_ascii=False, indent=2))]
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
        return [TextContent(type="text", text=json.dumps(error_result, ensure_ascii=False, indent=2))]


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
        # Research Execution
        "search": _handle_search,
        "stop_task": _handle_stop_task,
        # Materials
        "get_materials": _handle_get_materials,
        # Calibration
        "calibrate": _handle_calibrate,
        "calibrate_rollback": _handle_calibrate_rollback,
        # Authentication Queue
        "get_auth_queue": _handle_get_auth_queue,
        "resolve_auth": _handle_resolve_auth,
        # Notification
        "notify_user": _handle_notify_user,
        "wait_for_user": _handle_wait_for_user,
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


async def _get_exploration_state(task_id: str):
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

async def _handle_create_task(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle create_task tool call.
    
    Creates a new research task and returns task_id.
    Per §3.2.1: Returns task_id, query, created_at, budget.
    """
    import uuid
    from datetime import datetime, timezone
    
    query = args["query"]
    config = args.get("config", {})
    
    # Generate task ID
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    
    # Extract budget config
    budget_config = config.get("budget", {})
    max_pages = budget_config.get("max_pages", 120)
    max_seconds = budget_config.get("max_seconds", 1200)
    
    with LogContext(task_id=task_id):
        logger.info("Creating task", query=query[:100])
        
        # Store task in database
        db = await get_database()
        
        created_at = datetime.now(timezone.utc).isoformat()
        
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
                "max_pages": max_pages,
                "max_seconds": max_seconds,
            },
        }
        return attach_meta(response, create_minimal_meta())


async def _handle_get_status(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_status tool call.
    
    Implements §3.2.1: Unified task and exploration status.
    Returns task info, search states, metrics, budget, auth queue.
    
    Note: Returns data only, no recommendations. Cursor AI decides next actions.
    """
    from src.mcp.errors import TaskNotFoundError, InvalidParamsError
    
    task_id = args.get("task_id")
    
    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )
    
    with LogContext(task_id=task_id):
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
        
        # Get exploration state if exists
        exploration_status = None
        try:
            state = await _get_exploration_state(task_id)
            exploration_status = await state.get_status()
        except Exception as e:
            logger.debug(
                "No exploration state available",
                task_id=task_id,
                error=str(e),
            )
        
        # Build unified response per §3.2.1
        if exploration_status:
            # Convert subqueries to searches (field name mapping)
            searches = []
            for sq in exploration_status.get("subqueries", []):
                searches.append({
                    "id": sq.get("id"),
                    "query": sq.get("text"),
                    "status": sq.get("status"),
                    "pages_fetched": sq.get("pages_fetched", 0),
                    "useful_fragments": sq.get("useful_fragments", 0),
                    "harvest_rate": sq.get("harvest_rate", 0.0),
                    "satisfaction_score": sq.get("satisfaction_score", 0.0),
                    "has_primary_source": sq.get("has_primary_source", False),
                })
            
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
            status = status_map.get(
                exploration_status.get("task_status", db_status),
                "exploring"
            )
            
            metrics = exploration_status.get("metrics", {})
            budget = exploration_status.get("budget", {})
            
            # Calculate remaining percent
            pages_used = budget.get("pages_used", 0)
            pages_limit = budget.get("pages_limit", 120)
            remaining_percent = int((1 - pages_used / max(1, pages_limit)) * 100)
            
            response = {
                "ok": True,
                "task_id": task_id,
                "status": status,
                "query": task_query,
                "searches": searches,
                "metrics": {
                    "total_searches": len(searches),
                    "satisfied_count": metrics.get("satisfied_count", 0),
                    "total_pages": metrics.get("total_pages", 0),
                    "total_fragments": metrics.get("total_fragments", 0),
                    "total_claims": metrics.get("total_claims", 0),
                    "elapsed_seconds": metrics.get("elapsed_seconds", 0),
                },
                "budget": {
                    "pages_used": pages_used,
                    "pages_limit": pages_limit,
                    "time_used_seconds": budget.get("time_used_seconds", 0),
                    "time_limit_seconds": budget.get("time_limit_seconds", 1200),
                    "remaining_percent": remaining_percent,
                },
                "auth_queue": exploration_status.get("authentication_queue"),
                "warnings": exploration_status.get("warnings", []),
            }
            return attach_meta(response, create_minimal_meta())
        else:
            # No exploration state - return minimal info
            response = {
                "ok": True,
                "task_id": task_id,
                "status": db_status or "created",
                "query": task_query,
                "searches": [],
                "metrics": {
                    "total_searches": 0,
                    "satisfied_count": 0,
                    "total_pages": 0,
                    "total_fragments": 0,
                    "total_claims": 0,
                    "elapsed_seconds": 0,
                },
                "budget": {
                    "pages_used": 0,
                    "pages_limit": 120,
                    "time_used_seconds": 0,
                    "time_limit_seconds": 1200,
                    "remaining_percent": 100,
                },
                "auth_queue": None,
                "warnings": [],
            }
            return attach_meta(response, create_minimal_meta())


# ============================================================
# Research Execution Handlers
# ============================================================

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
    except Exception:
        return False


async def _auto_start_chrome() -> bool:
    """
    Auto-start Chrome using chrome.sh script.
    
    Executes ./scripts/chrome.sh start and returns success status.
    Per N.5.3: UX-first approach - Lancet auto-starts Chrome when needed.
    
    Uses asyncio.create_subprocess_exec() for non-blocking execution.
    
    Returns:
        True if chrome.sh start succeeded, False otherwise.
    """
    import asyncio
    from pathlib import Path
    
    # Find chrome.sh script relative to this file
    # src/mcp/server.py -> scripts/chrome.sh
    script_path = Path(__file__).parent.parent.parent / "scripts" / "chrome.sh"
    
    if not script_path.exists():
        logger.warning("chrome.sh not found", path=str(script_path))
        return False
    
    try:
        logger.info("Auto-starting Chrome", script=str(script_path))
        process = await asyncio.create_subprocess_exec(
            str(script_path),
            "start",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # Wait for process completion with timeout
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30.0,  # 30 second timeout for script execution
            )
        except asyncio.TimeoutError:
            logger.error("Chrome auto-start timed out")
            process.kill()
            await process.wait()
            return False
        
        stdout_text = stdout.decode() if stdout else ""
        stderr_text = stderr.decode() if stderr else ""
        
        if process.returncode == 0:
            logger.info("Chrome auto-start script completed", stdout=stdout_text[:200] if stdout_text else "")
            return True
        else:
            logger.warning(
                "Chrome auto-start script failed",
                returncode=process.returncode,
                stderr=stderr_text[:200] if stderr_text else "",
            )
            return False
    except Exception as e:
        logger.error("Chrome auto-start error", error=str(e))
        return False


async def _ensure_chrome_ready(timeout: float = 15.0, poll_interval: float = 0.5) -> bool:
    """
    Ensure Chrome CDP is ready, auto-starting if needed.
    
    Per N.5.3 and requirements.md §3.2.1:
    1. Check if CDP is already connected
    2. If not, auto-start Chrome using chrome.sh
    3. Wait up to timeout seconds for CDP connection
    4. Return True if connected, raise ChromeNotReadyError if failed
    
    Args:
        timeout: Maximum seconds to wait for CDP connection after auto-start.
        poll_interval: Seconds between CDP connection checks.
        
    Returns:
        True if Chrome CDP is ready.
        
    Raises:
        ChromeNotReadyError: If Chrome could not be started or connected.
    """
    import time
    from src.mcp.errors import ChromeNotReadyError
    
    # 1. Check if already connected
    if await _check_chrome_cdp_ready():
        logger.debug("Chrome CDP already ready")
        return True
    
    # 2. Auto-start Chrome
    logger.info("Chrome CDP not ready, attempting auto-start")
    auto_start_success = await _auto_start_chrome()
    
    if not auto_start_success:
        logger.warning("Chrome auto-start script failed")
        # Continue to wait anyway - script might have partially succeeded
    
    # 3. Wait for CDP connection with polling
    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout:
        if await _check_chrome_cdp_ready():
            elapsed = time.monotonic() - start_time
            logger.info("Chrome CDP ready after auto-start", elapsed_seconds=round(elapsed, 1))
            return True
        await asyncio.sleep(poll_interval)
    
    # 4. Failed - raise error
    logger.error("Chrome CDP not ready after auto-start", timeout=timeout)
    
    raise ChromeNotReadyError(
        "Chrome CDP is not connected. Auto-start failed. Check: ./scripts/chrome.sh start",
        auto_start_attempted=True,
    )


async def _handle_search(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle search tool call.
    
    Implements §3.2.1: Executes Cursor AI-designed query through
    the search→fetch→extract→evaluate pipeline.
    
    Supports refute:true for refutation mode.
    
    Per N.5.3: Auto-starts Chrome if not connected.
    
    Raises:
        ChromeNotReadyError: If Chrome CDP is not connected after auto-start attempt.
    """
    from src.mcp.errors import TaskNotFoundError, InvalidParamsError
    from src.research.pipeline import search_action
    
    task_id = args.get("task_id")
    query = args.get("query")
    options = args.get("options", {})
    
    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )
    
    if not query or not query.strip():
        raise InvalidParamsError(
            "query is required",
            param_name="query",
            expected="non-empty string",
        )
    
    # Pre-check: Ensure Chrome CDP is available, auto-starting if needed
    # Per N.5.3: UX-first - auto-start Chrome rather than returning error immediately
    await _ensure_chrome_ready()
    
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
        
        # Execute search through unified API
        result = await search_action(
            task_id=task_id,
            query=query,
            state=state,
            options=options,
        )
        
        return result


async def _handle_stop_task(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle stop_task tool call.
    
    Implements §3.2.1: Finalizes task and returns summary.
    """
    from src.mcp.errors import TaskNotFoundError, InvalidParamsError
    from src.research.pipeline import stop_task_action
    
    task_id = args.get("task_id")
    reason = args.get("reason", "completed")
    
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
        
        # Get exploration state
        state = await _get_exploration_state(task_id)
        
        # Execute stop through unified API
        result = await stop_task_action(
            task_id=task_id,
            state=state,
            reason=reason,
        )
        
        # Clear cached state
        _clear_exploration_state(task_id)
        
        # Update task status in DB
        await db.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (result.get("final_status", "completed"), task_id),
        )
        
        return result


# ============================================================
# Materials Handler
# ============================================================

async def _handle_get_materials(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_materials tool call.
    
    Implements §3.2.1: Returns report materials for Cursor AI.
    Does NOT generate report - composition is Cursor AI's responsibility.
    """
    from src.mcp.errors import TaskNotFoundError, InvalidParamsError
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
# Calibration Handlers (§3.2.1, §4.6.1)
# ============================================================

async def _handle_calibrate(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle calibrate tool call.
    
    Implements §3.2.1: Unified calibration operations (daily operations).
    Actions: add_sample, get_stats, evaluate, get_evaluations, get_diagram_data.
    
    For rollback (destructive operation), use calibrate_rollback tool.
    """
    from src.utils.calibration import calibrate_action
    from src.mcp.errors import InvalidParamsError
    
    action = args.get("action")
    data = args.get("data", {})
    
    if not action:
        raise InvalidParamsError(
            "action is required",
            param_name="action",
            expected="one of: add_sample, get_stats, evaluate, get_evaluations, get_diagram_data",
        )
    
    return await calibrate_action(action, data)


async def _handle_calibrate_rollback(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle calibrate_rollback tool call.
    
    Implements §3.2.1: Rollback calibration parameters (destructive operation).
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
        raise CalibrationError(str(e), source=source)
    
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
# Authentication Queue Handlers (§3.2.1, §3.6.1)
# ============================================================

async def _handle_get_auth_queue(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_auth_queue tool call.
    
    Implements §3.2.1: Get pending authentication queue.
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
    
    Per §3.6.1: Capture session data after authentication completion
    so subsequent requests can reuse the authenticated session.
    
    Args:
        domain: Domain to capture cookies for.
        
    Returns:
        Session data dict with cookies, or None if capture failed.
    """
    from datetime import datetime, timezone
    
    try:
        # Try to get cookies from existing browser context
        from src.search.browser_search_provider import BrowserSearchProvider
        
        provider = BrowserSearchProvider()
        # Check if browser is already connected (don't force connection)
        if provider._browser is None or provider._context is None:
            logger.debug(
                "Browser not connected, skipping cookie capture",
                domain=domain,
            )
            return None
        
        # Get cookies for the domain
        cookies = await provider._context.cookies()
        
        # Filter cookies that match the domain
        domain_cookies = []
        for cookie in cookies:
            cookie_domain = cookie.get("domain", "")
            # Match domain and subdomains (e.g., .example.com matches www.example.com)
            if cookie_domain.endswith(domain) or domain.endswith(cookie_domain.lstrip(".")):
                domain_cookies.append(dict(cookie))
        
        if not domain_cookies:
            logger.debug(
                "No cookies found for domain",
                domain=domain,
            )
            return None
        
        session_data = {
            "cookies": domain_cookies,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "domain": domain,
        }
        
        logger.info(
            "Captured authentication session cookies",
            domain=domain,
            cookie_count=len(domain_cookies),
        )
        
        return session_data
        
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
    
    Implements §3.2.1: Report authentication completion or skip.
    Per §3.6.1: Captures session cookies on completion for reuse.
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
# Notification Handlers (§3.2.1)
# ============================================================

async def _handle_notify_user(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle notify_user tool call.
    
    Implements §3.2.1: Send notification to user.
    Per §3.6.1: No DOM operations during auth sessions.
    """
    from src.mcp.errors import InvalidParamsError
    from src.utils.notification import notify_user as send_notification
    
    event = args.get("event")
    payload = args.get("payload")
    
    # Validate required params
    if not event:
        raise InvalidParamsError(
            "event is required",
            param_name="event",
            expected="one of: auth_required, task_progress, task_complete, error, info",
        )
    
    valid_events = {"auth_required", "task_progress", "task_complete", "error", "info"}
    if event not in valid_events:
        raise InvalidParamsError(
            f"Invalid event type: {event}",
            param_name="event",
            expected="one of: auth_required, task_progress, task_complete, error, info",
        )
    
    if payload is None:
        raise InvalidParamsError(
            "payload is required",
            param_name="payload",
            expected="object",
        )
    
    # Allow empty payload dict (TC-B-04)
    if not isinstance(payload, dict):
        payload = {}
    
    # Map event types to notification
    title_map = {
        "auth_required": "認証が必要です",
        "task_progress": "タスク進捗",
        "task_complete": "タスク完了",
        "error": "エラー",
        "info": "お知らせ",
    }
    
    title = title_map.get(event, "Lancet通知")
    message = payload.get("message", "")
    
    if event == "auth_required":
        url = payload.get("url", "")
        domain = payload.get("domain", "")
        message = f"認証が必要: {domain or url}"
    
    await send_notification(
        event=event,
        payload=payload,
    )
    
    return {
        "ok": True,
        "event": event,
        "notified": True,
    }


async def _handle_wait_for_user(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle wait_for_user tool call.
    
    Implements §3.2.1: Wait for user input/acknowledgment.
    
    Note: This is a simplified implementation that sends a notification
    and returns immediately with a "waiting" status. The actual wait
    is handled by Cursor AI polling get_status or get_auth_queue.
    
    For blocking waits with timeout, the MCP protocol doesn't support
    true blocking operations - Cursor AI should poll for completion.
    """
    from src.mcp.errors import InvalidParamsError
    from src.utils.notification import notify_user
    
    prompt = args.get("prompt")
    timeout_seconds = args.get("timeout_seconds", 300)
    options = args.get("options", [])
    
    # Validate required params
    if not prompt or not prompt.strip():
        raise InvalidParamsError(
            "prompt is required",
            param_name="prompt",
            expected="non-empty string",
        )
    
    # Send notification with prompt
    await notify_user(
        event="info",
        payload={"message": prompt},
    )
    
    logger.info(
        "User input requested",
        prompt=prompt[:100],
        timeout_seconds=timeout_seconds,
        options=options,
    )
    
    # Return immediately - MCP doesn't support true blocking
    # Cursor AI should poll get_status or get_auth_queue for completion
    return {
        "ok": True,
        "status": "notification_sent",
        "prompt": prompt,
        "timeout_seconds": timeout_seconds,
        "message": "Notification sent. Poll get_status or get_auth_queue for completion.",
    }


# ============================================================
# Server Entry Point
# ============================================================

async def run_server() -> None:
    """Run the MCP server."""
    logger.info("Starting Lancet MCP server (Phase M - 11 tools)")
    
    # Initialize database
    await get_database()
    
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )
    finally:
        await close_database()
        logger.info("Lancet MCP server stopped")


def main() -> None:
    """Main entry point."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
