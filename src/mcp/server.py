"""
MCP Server implementation for Lyra.
Provides tools for research operations that can be called by Cursor/LLM.

Provides MCP tools per ADR-0010 async architecture:
- Removed: search (replaced by queue_searches), notify_user, wait_for_user
- Added: queue_searches (ADR-0010)
- Modified: get_status (long polling with wait parameter)
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp.server.stdio import stdio_server
from mcp.types import Tool, ToolAnnotations

from mcp.server import Server
from src.storage.database import close_database, get_database
from src.utils.logging import ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)

# IMPORTANT:
# Import modules that may emit logs only AFTER logging is configured.
from src.mcp.tools import auth, calibration, feedback, search, sql, task, vector

# Create MCP server instance
app = Server("lyra")


def _load_schema(name: str) -> dict[str, Any]:
    """Load JSON schema from src/mcp/schemas/{name}.json.

    Args:
        name: Schema name (without .json extension).

    Returns:
        Parsed JSON schema dict.

    Raises:
        FileNotFoundError: If schema file does not exist.
    """
    path = Path(__file__).parent / "schemas" / f"{name}.json"
    with open(path) as f:
        schema: dict[str, Any] = json.load(f)
        return schema


# ============================================================
# Tool Definitions
# ============================================================

# Common _lyra_meta schema for all outputSchema definitions
_LYRA_META_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Lyra response metadata (ADR-0005 L5)",
    "properties": {
        "timestamp": {"type": "string", "description": "ISO timestamp of response generation"},
        "data_quality": {
            "type": "string",
            "enum": ["normal", "degraded", "limited"],
            "description": "Overall data quality indicator",
        },
        "security_warnings": {
            "type": "array",
            "description": "Security warnings from L2/L4 detection",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "message": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                },
            },
        },
        "blocked_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Domains blocked during this operation",
        },
        "unverified_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Unverified domains used",
        },
    },
    "required": ["timestamp", "data_quality"],
}

TOOLS = [
    # ============================================================
    # 1. Task Management (2 tools)
    # ============================================================
    Tool(
        name="create_task",
        title="Create Research Task",
        description="""Create a new research task to begin evidence collection.

WORKFLOW: This is the first step. After creating a task, use queue_searches to add search queries.
The same task_id accumulates data across multiple searches - design queries iteratively based on results.

STRATEGY: Start with broad queries, then refine based on get_status metrics. Include both supporting
and refuting queries to ensure balanced evidence collection.""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research question or hypothesis to investigate. Be specific - this guides the entire exploration.",
                },
                "config": {
                    "type": "object",
                    "description": "Task configuration. Defaults work well for most research.",
                    "properties": {
                        "budget": {
                            "type": "object",
                            "description": "Resource limits for the task",
                            "properties": {
                                "budget_pages": {
                                    "type": "integer",
                                    "default": 120,
                                    "description": "Max pages to fetch across all searches. Shared across the task.",
                                },
                                "max_seconds": {
                                    "type": "integer",
                                    "default": 1200,
                                    "description": "Max task duration in seconds (20 min default).",
                                },
                            },
                            "additionalProperties": False,
                        },
                        "priority_domains": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Domains to prioritize (e.g., ['arxiv.org', 'nature.com']). Academic sources recommended.",
                        },
                        "language": {
                            "type": "string",
                            "description": "Primary language for search (ja, en, etc.). Affects query expansion.",
                        },
                    },
                },
            },
            "required": ["query"],
        },
        outputSchema=_load_schema("create_task"),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
        ),
    ),
    Tool(
        name="get_status",
        title="Get Task Status",
        description="""Get comprehensive task status including search progress, metrics, and pending auth.

POLLING STRATEGY: Use wait=30 for efficient long-polling during active exploration.
Use wait=0 for immediate status checks when making decisions.

METRICS TO MONITOR:
- searches[].satisfaction_score: 0.0-1.0, higher means query is well-covered
- searches[].harvest_rate: Ratio of useful fragments found
- metrics.total_claims: Growing count indicates productive exploration
- budget.remaining_percent: Stop or adjust strategy when low

DECISION POINTS:
- If satisfaction_score < 0.5: Consider refining or expanding queries
- If harvest_rate low: Try different query angles or sources
- If pending_auth_count > 0: User needs to solve CAPTCHAs (use get_auth_queue)""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to check status for",
                },
                "wait": {
                    "type": "integer",
                    "description": "Long-polling: seconds to wait for changes before returning. 0=immediate, 30=recommended for monitoring.",
                    "default": 0,
                    "minimum": 0,
                    "maximum": 180,
                },
            },
            "required": ["task_id"],
        },
        outputSchema=_load_schema("get_status"),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    # ============================================================
    # 2. Research Execution (2 tools)
    # ============================================================
    Tool(
        name="queue_searches",
        title="Queue Search Queries",
        description="""Queue multiple search queries for parallel background execution. Returns immediately.

DUPLICATE HANDLING: Safe to queue overlapping queries - duplicates are auto-detected and skipped.
Same URL/DOI content is cached and reused across queries, maximizing coverage without waste.

EXPLORATION STRATEGY:
1. Start with 3-5 diverse queries covering different angles of the research question
2. Check results with get_status(wait=30) to monitor progress
3. Based on findings, add more specific or contrasting queries
4. IMPORTANT: Include refutation queries (e.g., "X criticism", "X limitations", "against X")
   to ensure balanced evidence collection

QUERY DESIGN TIPS:
- Use academic terms and paper titles when known
- Try both English and target language queries
- Include author names for known experts
- Add "site:arxiv.org" or domain hints for academic sources""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to add searches to",
                },
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Search queries to execute. Include both supporting and refuting angles.",
                    "minItems": 1,
                },
                "options": {
                    "type": "object",
                    "description": "Options applied to all queries in this batch",
                    "properties": {
                        "engines": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific search engines (google, bing, duckduckgo, scholar). Omit for auto-selection.",
                        },
                        "budget_pages": {
                            "type": "integer",
                            "description": "Max pages per query. Leave unset to use task default.",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "default": "medium",
                            "description": "Scheduling priority. Use 'high' for critical queries, 'low' for exploratory.",
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["task_id", "queries"],
        },
        outputSchema=_load_schema("queue_searches"),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="stop_task",
        title="Stop Research Task",
        description="""Stop and finalize a research task. Cancels pending searches and prepares materials.

WHEN TO STOP:
- budget.remaining_percent approaching 0
- All key queries have satisfaction_score >= 0.7
- Sufficient claims collected (check metrics.total_claims)
- Time constraints require wrapping up

MODES:
- graceful: Wait for running searches to complete, then stop. Recommended for quality.
- immediate: Cancel everything now. Use when budget exhausted or time critical.

AFTER STOPPING: Use query_graph and vector_search tools to explore collected evidence.""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to stop",
                },
                "reason": {
                    "type": "string",
                    "enum": ["completed", "budget_exhausted", "user_cancelled"],
                    "default": "completed",
                    "description": "Why the task is stopping. Logged for analysis.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["graceful", "immediate"],
                    "default": "graceful",
                    "description": "graceful=wait for running searches, immediate=cancel all",
                },
            },
            "required": ["task_id"],
        },
        outputSchema=_load_schema("stop_task"),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
        ),
    ),
    # ============================================================
    # 3. Calibration (2 tools)
    # ============================================================
    Tool(
        name="calibration_metrics",
        title="Calibration Metrics",
        description="""View NLI model calibration statistics and evaluation history.

ACTIONS:
- get_stats: Current calibration parameters and Brier scores per source model
- get_evaluations: Historical evaluation records for trend analysis

For collecting ground-truth corrections, use feedback(action=edge_correct).
For rolling back to previous calibration, use calibration_rollback (separate tool for safety).""",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get_stats", "get_evaluations"],
                    "description": "get_stats: current params, get_evaluations: history",
                },
                "data": {
                    "type": "object",
                    "description": "For get_evaluations: {source?, limit?, since?}",
                    "properties": {
                        "source": {
                            "type": "string",
                            "description": "Filter by source model (e.g., 'nli_judge')",
                        },
                        "limit": {"type": "integer", "default": 50},
                        "since": {"type": "string", "description": "ISO timestamp to filter from"},
                    },
                },
            },
            "required": ["action"],
        },
        outputSchema=_load_schema("calibration_metrics"),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="calibration_rollback",
        title="Rollback Calibration",
        description="""Rollback NLI calibration parameters to a previous version. DESTRUCTIVE operation.

USE CASES:
- Brier score degraded after recalibration
- Incorrect ground-truth samples contaminated training
- Need to restore known-good parameters

This is a separate tool from calibration_metrics because rollback is irreversible.
Always provide a reason for audit trail.""",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source model identifier (e.g., 'nli_judge', 'llm_extract')",
                },
                "version": {
                    "type": "integer",
                    "description": "Target version number. Omit to rollback to previous version.",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for rollback. Required for audit log.",
                },
            },
            "required": ["source"],
        },
        outputSchema=_load_schema("calibration_rollback"),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
        ),
    ),
    # ============================================================
    # 4. Evidence Graph Exploration (2 tools)
    # ============================================================
    Tool(
        name="query_graph",
        title="Query Evidence Graph (SQL)",
        description="""Execute read-only SQL against the Evidence Graph database.

This tool is intended for incremental graph exploration without context overflow.

SCHEMA HINTS (task_id column availability):
- claims: HAS task_id (primary task-scoped table)
- queries: HAS task_id
- pages: NO task_id (URL-based deduplication, global scope)
- fragments: NO task_id (linked via page_id → pages)
- edges: NO task_id (use JOINs with claims for task filtering)

To filter task-scoped data, start with claims/queries tables or use JOINs.
Use options.include_schema=true to get full schema snapshot.

SECURITY:
- Read-only only (no INSERT/UPDATE/DELETE/DDL)
- Single statement only
- Timeouts and strict output limits are enforced""",
        inputSchema={
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Read-only SQL query (single statement). Example: SELECT * FROM claims WHERE task_id = '...' LIMIT 10",
                },
                "options": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "default": 50,
                            "maximum": 200,
                            "description": "Maximum rows to return (safety limit for output size)",
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "default": 300,
                            "maximum": 2000,
                            "description": "Hard timeout to interrupt long-running queries",
                        },
                        "max_vm_steps": {
                            "type": "integer",
                            "default": 500000,
                            "maximum": 5000000,
                            "description": "SQLite VM instruction budget (DoS guard)",
                        },
                        "include_schema": {
                            "type": "boolean",
                            "default": False,
                            "description": "Return a safe schema snapshot (tables/columns only)",
                        },
                    },
                },
            },
            "required": ["sql"],
        },
        outputSchema=_load_schema("query_graph"),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="vector_search",
        title="Semantic Vector Search",
        description="""Semantic similarity search over fragments/claims using persisted embeddings.

Use this before query_graph when you don't know which IDs/tables to look at.""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query for semantic search",
                },
                "target": {
                    "type": "string",
                    "enum": ["fragments", "claims"],
                    "default": "claims",
                    "description": "Table to search",
                },
                "task_id": {
                    "type": "string",
                    "description": "Optional task scope (recommended for claims)",
                },
                "top_k": {
                    "type": "integer",
                    "default": 10,
                    "maximum": 50,
                    "description": "Number of results to return",
                },
                "min_similarity": {
                    "type": "number",
                    "default": 0.5,
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Minimum cosine similarity threshold",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        outputSchema=_load_schema("vector_search"),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    # ============================================================
    # 5. Authentication Queue (2 tools)
    # ============================================================
    Tool(
        name="get_auth_queue",
        title="Get Auth Queue",
        description="""Get pending CAPTCHA/authentication items awaiting user resolution.

WORKFLOW: When get_status shows pending_auth_count > 0:
1. Call get_auth_queue to see what needs solving
2. User solves CAPTCHAs in browser (URLs are provided)
3. Call resolve_auth to mark completion and trigger retry

Group by domain to batch-solve CAPTCHAs from the same site.
Research continues on other domains while CAPTCHAs are pending.""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Filter to specific task. Omit for all tasks.",
                },
                "group_by": {
                    "type": "string",
                    "enum": ["none", "domain", "type"],
                    "default": "none",
                    "description": "Group results by domain or auth type for batch handling.",
                },
                "priority_filter": {
                    "type": "string",
                    "enum": ["high", "medium", "low", "all"],
                    "default": "all",
                    "description": "Filter by priority level.",
                },
            },
        },
        outputSchema=_load_schema("get_auth_queue"),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="resolve_auth",
        title="Resolve Authentication",
        description="""Mark CAPTCHA/auth items as solved or skipped. Triggers automatic retry of blocked searches.

TARGETS:
- item: Resolve single queue item by ID
- domain: Batch resolve all items for a domain (efficient for same-site CAPTCHAs)
- task: Resolve all auth items for a task

On success, blocked searches are automatically requeued and circuit breakers reset.
Session cookies are captured and reused for future requests to that domain.""",
        inputSchema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["item", "domain", "task"],
                    "default": "item",
                    "description": "Resolution scope",
                },
                "queue_id": {
                    "type": "string",
                    "description": "Queue item ID (required when target=item)",
                },
                "domain": {
                    "type": "string",
                    "description": "Domain to resolve (required when target=domain)",
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID (required when target=task)",
                },
                "action": {
                    "type": "string",
                    "enum": ["complete", "skip"],
                    "description": "complete=auth successful, skip=abandon these items",
                },
                "success": {
                    "type": "boolean",
                    "default": True,
                    "description": "For action=complete: whether auth actually succeeded",
                },
            },
            "required": ["action"],
        },
        outputSchema=_load_schema("resolve_auth"),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    # ============================================================
    # 6. Feedback (1 tool)
    # ============================================================
    Tool(
        name="feedback",
        title="Submit Feedback",
        description="""Human-in-the-loop corrections for improving evidence quality. Changes take effect immediately.

3 LEVELS, 6 ACTIONS:

DOMAIN LEVEL - Block/unblock sources:
- domain_block: Block a domain (e.g., low-quality site). Requires reason.
- domain_unblock: Unblock a previously blocked domain. Requires reason.
- domain_clear_override: Remove all overrides for a domain pattern.

CLAIM LEVEL - Accept/reject extracted claims:
- claim_reject: Mark claim as invalid/irrelevant. Removes from materials. Requires reason.
- claim_restore: Restore a previously rejected claim.

EDGE LEVEL - Correct NLI classifications:
- edge_correct: Fix incorrect supports/refutes/neutral label. This also marks the edge as
  human-reviewed. Corrections are saved for future model improvement (LoRA training data).

EDGE_CORRECT DETAILS:
When you find an edge with wrong NLI classification (e.g., marked 'neutral' but actually 'supports'):
1. Get edge_id from query_graph or vector_search results
2. Call feedback(action=edge_correct, edge_id=..., correct_relation='supports')
3. Edge confidence is set to 1.0 (human certainty) and claim confidence recalculates""",
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
                    "description": "Feedback action to perform",
                },
                "domain_pattern": {
                    "type": "string",
                    "description": "For domain_* actions. Glob pattern (e.g., 'example.com', '*.example.com'). TLD-level patterns forbidden.",
                },
                "claim_id": {
                    "type": "string",
                    "description": "For claim_reject/claim_restore. Get from query_graph results (claims table)",
                },
                "edge_id": {
                    "type": "string",
                    "description": "For edge_correct. Get from query_graph results (edges table)",
                },
                "correct_relation": {
                    "type": "string",
                    "enum": ["supports", "refutes", "neutral"],
                    "description": "For edge_correct: the correct NLI label",
                },
                "reason": {
                    "type": "string",
                    "description": "Required for domain_block, domain_unblock, domain_clear_override, claim_reject. Logged for audit.",
                },
            },
            "required": ["action"],
        },
        outputSchema=_load_schema("feedback"),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
        ),
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Handle tool calls.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Structured response dict. MCP SDK automatically creates both:
        - structuredContent (for outputSchema validation)
        - content[].text (for display in Cursor AI)

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
        # Return dict directly - SDK creates both structuredContent and TextContent
        return sanitize_response(result, name)

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
        return sanitize_response(error_dict, "error")

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
        return sanitize_error(e, error_id)


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
        "create_task": task.handle_create_task,
        "get_status": task.handle_get_status,
        # Research Execution (search removed per ADR-0010, use queue_searches)
        "queue_searches": search.handle_queue_searches,
        "stop_task": task.handle_stop_task,
        # Calibration (ADR-0012: renamed from calibrate/calibrate_rollback)
        "calibration_metrics": calibration.handle_calibration_metrics,
        "calibration_rollback": calibration.handle_calibration_rollback,
        # Evidence Graph Exploration
        "query_graph": sql.handle_query_graph,
        "vector_search": vector.handle_vector_search,
        # Authentication Queue
        "get_auth_queue": auth.handle_get_auth_queue,
        "resolve_auth": auth.handle_resolve_auth,
        # Feedback (notify_user, wait_for_user removed per ADR-0010)
        "feedback": feedback.handle_feedback,
    }

    handler = handlers.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")

    return await handler(arguments)


# ============================================================
# Server Entry Point
# ============================================================


async def run_server() -> None:
    """Run the MCP server."""
    logger.info("Starting Lyra MCP server", tool_count=len(TOOLS))

    # Initialize database
    await get_database()

    # Restore domain overrides from DB on startup
    # Ensures domain-specific policies persist across server restarts
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
