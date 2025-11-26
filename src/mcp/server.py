"""
MCP Server implementation for Lancet.
Provides tools for research operations that can be called by Cursor/LLM.
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

ensure_logging_configured()
logger = get_logger(__name__)

# Create MCP server instance
app = Server("lancet")


# ============================================================
# Tool Definitions
# ============================================================

TOOLS = [
    Tool(
        name="search_serp",
        description="Execute a search query across configured search engines and return SERP results.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query text"
                },
                "engines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of search engines to use (optional, uses defaults if not specified)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results per engine (default: 10)",
                    "default": 10
                },
                "time_range": {
                    "type": "string",
                    "enum": ["day", "week", "month", "year", "all"],
                    "description": "Time range filter for results",
                    "default": "all"
                },
                "task_id": {
                    "type": "string",
                    "description": "Associated task ID for tracking"
                }
            },
            "required": ["query"]
        }
    ),
    Tool(
        name="fetch_url",
        description="Fetch content from a URL using appropriate method (HTTP client or browser).",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch"
                },
                "context": {
                    "type": "object",
                    "description": "Context information (referer, headers, etc.)",
                    "properties": {
                        "referer": {"type": "string"},
                        "serp_item_id": {"type": "string"}
                    }
                },
                "policy": {
                    "type": "object",
                    "description": "Fetch policy override",
                    "properties": {
                        "force_browser": {"type": "boolean"},
                        "force_headful": {"type": "boolean"},
                        "use_tor": {"type": "boolean"}
                    }
                },
                "task_id": {
                    "type": "string",
                    "description": "Associated task ID"
                }
            },
            "required": ["url"]
        }
    ),
    Tool(
        name="extract_content",
        description="Extract text content from HTML or PDF.",
        inputSchema={
            "type": "object",
            "properties": {
                "input_path": {
                    "type": "string",
                    "description": "Path to HTML or PDF file"
                },
                "html": {
                    "type": "string",
                    "description": "Raw HTML content (alternative to input_path)"
                },
                "content_type": {
                    "type": "string",
                    "enum": ["html", "pdf", "auto"],
                    "description": "Content type (auto-detected if not specified)",
                    "default": "auto"
                },
                "page_id": {
                    "type": "string",
                    "description": "Associated page ID in database"
                }
            }
        }
    ),
    Tool(
        name="rank_candidates",
        description="Rank text passages by relevance using BM25, embeddings, and reranking.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query to rank against"
                },
                "passages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"}
                        },
                        "required": ["id", "text"]
                    },
                    "description": "List of passages to rank"
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of top results to return",
                    "default": 20
                }
            },
            "required": ["query", "passages"]
        }
    ),
    Tool(
        name="llm_extract",
        description="Use local LLM to extract facts, claims, and citations from passages.",
        inputSchema={
            "type": "object",
            "properties": {
                "passages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "source_url": {"type": "string"}
                        },
                        "required": ["id", "text"]
                    },
                    "description": "Passages to extract from"
                },
                "task": {
                    "type": "string",
                    "enum": ["extract_facts", "extract_claims", "summarize", "translate"],
                    "description": "Extraction task type"
                },
                "context": {
                    "type": "string",
                    "description": "Additional context for extraction (e.g., research question)"
                }
            },
            "required": ["passages", "task"]
        }
    ),
    Tool(
        name="nli_judge",
        description="Judge stance relationship (supports/refutes/neutral) between claim pairs.",
        inputSchema={
            "type": "object",
            "properties": {
                "pairs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "pair_id": {"type": "string"},
                            "premise": {"type": "string"},
                            "hypothesis": {"type": "string"}
                        },
                        "required": ["pair_id", "premise", "hypothesis"]
                    },
                    "description": "Pairs of texts to judge"
                }
            },
            "required": ["pairs"]
        }
    ),
    Tool(
        name="notify_user",
        description="Send notification to user (for CAPTCHA, login required, etc.).",
        inputSchema={
            "type": "object",
            "properties": {
                "event": {
                    "type": "string",
                    "enum": ["captcha", "login_required", "cookie_banner", "cloudflare", "error", "info"],
                    "description": "Type of notification event"
                },
                "payload": {
                    "type": "object",
                    "description": "Event-specific payload",
                    "properties": {
                        "url": {"type": "string"},
                        "domain": {"type": "string"},
                        "message": {"type": "string"},
                        "timeout_seconds": {"type": "integer"}
                    }
                }
            },
            "required": ["event", "payload"]
        }
    ),
    # Authentication Queue Tools (Semi-automatic operation)
    Tool(
        name="get_pending_authentications",
        description="Get pending authentication queue for a task. Returns URLs requiring user authentication.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID"
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low", "all"],
                    "description": "Filter by priority (optional)"
                }
            },
            "required": ["task_id"]
        }
    ),
    Tool(
        name="start_authentication_session",
        description="Start authentication session. Marks items as in_progress for user to process.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID"
                },
                "queue_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific queue IDs to process (optional)"
                },
                "priority_filter": {
                    "type": "string",
                    "enum": ["high", "medium", "low", "all"],
                    "description": "Process only this priority level (optional)"
                }
            },
            "required": ["task_id"]
        }
    ),
    Tool(
        name="complete_authentication",
        description="Mark authentication as complete after user bypasses challenge.",
        inputSchema={
            "type": "object",
            "properties": {
                "queue_id": {
                    "type": "string",
                    "description": "Queue item ID"
                },
                "success": {
                    "type": "boolean",
                    "description": "Whether authentication succeeded"
                },
                "session_data": {
                    "type": "object",
                    "description": "Session data to store (cookies, etc.) - optional"
                }
            },
            "required": ["queue_id", "success"]
        }
    ),
    Tool(
        name="skip_authentication",
        description="Skip authentication for specific URLs or entire task.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID"
                },
                "queue_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific queue IDs to skip (optional, skips all if omitted)"
                }
            },
            "required": ["task_id"]
        }
    ),
    Tool(
        name="schedule_job",
        description="Schedule a job for execution with slot and priority management.",
        inputSchema={
            "type": "object",
            "properties": {
                "job": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["serp", "fetch", "extract", "embed", "rerank", "llm_fast", "llm_slow", "nli"],
                            "description": "Job type"
                        },
                        "priority": {
                            "type": "integer",
                            "description": "Priority (lower = higher priority)",
                            "default": 50
                        },
                        "input": {
                            "type": "object",
                            "description": "Job input data"
                        },
                        "task_id": {
                            "type": "string",
                            "description": "Associated task ID"
                        }
                    },
                    "required": ["kind"]
                }
            },
            "required": ["job"]
        }
    ),
    Tool(
        name="create_task",
        description="Create a new research task.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research question or topic"
                },
                "config": {
                    "type": "object",
                    "description": "Task-specific configuration overrides"
                }
            },
            "required": ["query"]
        }
    ),
    Tool(
        name="get_task_status",
        description="Get the status of a research task.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to query"
                }
            },
            "required": ["task_id"]
        }
    ),
    Tool(
        name="get_report_materials",
        description="Get report materials (claims, fragments, evidence graph) for Cursor AI to compose a report. Does NOT generate report - Cursor AI handles composition/writing (§2.1).",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to get materials for"
                },
                "include_evidence_graph": {
                    "type": "boolean",
                    "description": "Include evidence graph structure",
                    "default": True
                },
                "include_fragments": {
                    "type": "boolean",
                    "description": "Include source fragments",
                    "default": True
                }
            },
            "required": ["task_id"]
        }
    ),
    Tool(
        name="get_evidence_graph",
        description="Get evidence graph structure (claims, fragments, edges) for a task. Returns structured data for Cursor AI to interpret.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID"
                },
                "claim_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional filter by specific claim IDs"
                },
                "include_fragments": {
                    "type": "boolean",
                    "description": "Include linked fragments",
                    "default": True
                }
            },
            "required": ["task_id"]
        }
    ),
    # ============================================================
    # Phase 11: Exploration Control Tools
    # ============================================================
    Tool(
        name="get_research_context",
        description="Get design support information for subquery design. Returns entities, templates, and past query success rates. Does NOT generate subquery candidates - Cursor AI designs subqueries using this information.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to get context for"
                }
            },
            "required": ["task_id"]
        }
    ),
    Tool(
        name="execute_subquery",
        description="Execute a subquery designed by Cursor AI. Performs search, fetch, extract pipeline and returns results.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID"
                },
                "subquery": {
                    "type": "string",
                    "description": "Subquery text designed by Cursor AI"
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Execution priority",
                    "default": "medium"
                },
                "budget_pages": {
                    "type": "integer",
                    "description": "Optional page budget for this subquery"
                },
                "budget_time_seconds": {
                    "type": "integer",
                    "description": "Optional time budget for this subquery"
                }
            },
            "required": ["task_id", "subquery"]
        }
    ),
    Tool(
        name="get_exploration_status",
        description="Get current exploration status including subquery states, metrics, and budget. Returns raw data only - no recommendations. Cursor AI makes all decisions.",
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
    Tool(
        name="execute_refutation",
        description="Execute refutation search for a claim or subquery using mechanical patterns. Cursor AI specifies the target; Lancet applies suffix patterns.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID"
                },
                "claim_id": {
                    "type": "string",
                    "description": "Claim ID to refute (optional)"
                },
                "subquery_id": {
                    "type": "string",
                    "description": "Subquery ID to refute (optional)"
                }
            },
            "required": ["task_id"]
        }
    ),
    Tool(
        name="finalize_exploration",
        description="Finalize exploration and return summary with unsatisfied subqueries and followup suggestions.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to finalize"
                }
            },
            "required": ["task_id"]
        }
    ),
    # ============================================================
    # Phase 16.3.2: Calibration Evaluation Tools (§4.6.1)
    # ============================================================
    Tool(
        name="save_calibration_evaluation",
        description="Execute calibration evaluation and save to database. Calculates Brier score, ECE, and reliability diagram data. Returns structured data (NOT a report).",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source model identifier (e.g., 'llm_extract', 'nli_judge')"
                },
                "predictions": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Predicted probabilities (0.0 to 1.0)"
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Ground truth labels (0 or 1)"
                }
            },
            "required": ["source", "predictions", "labels"]
        }
    ),
    Tool(
        name="get_calibration_evaluations",
        description="Get calibration evaluation history as structured data. Cursor AI interprets and reports on this data.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Optional source filter"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum evaluations to return (default: 50)",
                    "default": 50
                },
                "since": {
                    "type": "string",
                    "description": "Optional start datetime (ISO format)"
                }
            }
        }
    ),
    Tool(
        name="get_reliability_diagram_data",
        description="Get bin data for reliability diagram (confidence vs accuracy). Returns structured data for Cursor AI to visualize or interpret.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source model identifier"
                },
                "evaluation_id": {
                    "type": "string",
                    "description": "Optional specific evaluation ID (uses latest if not specified)"
                }
            },
            "required": ["source"]
        }
    ),
    Tool(
        name="add_calibration_sample",
        description="Add a calibration sample (prediction + ground truth). Used by Cursor AI to provide feedback for calibration improvement.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source model identifier (e.g., 'llm_extract', 'nli_judge')"
                },
                "predicted_prob": {
                    "type": "number",
                    "description": "Predicted probability (0.0 to 1.0)"
                },
                "actual_label": {
                    "type": "integer",
                    "description": "Ground truth label (0 or 1)"
                },
                "logit": {
                    "type": "number",
                    "description": "Optional raw logit value"
                }
            },
            "required": ["source", "predicted_prob", "actual_label"]
        }
    ),
    Tool(
        name="get_calibration_stats",
        description="Get calibration statistics including current parameters, history, and degradation detection. Cursor AI uses this to decide on rollback.",
        inputSchema={
            "type": "object",
            "properties": {}
        }
    ),
    Tool(
        name="rollback_calibration",
        description="Rollback calibration parameters to a previous version. Called by Cursor AI when degradation is detected.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source model identifier"
                },
                "to_version": {
                    "type": "integer",
                    "description": "Optional specific version to rollback to (defaults to previous)"
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for rollback"
                }
            },
            "required": ["source"]
        }
    ),
    # ============================================================
    # Phase 16.2.6: Claim Decomposition (§3.3.1)
    # ============================================================
    Tool(
        name="decompose_question",
        description="Decompose a research question into atomic claims for systematic verification. Per §3.3.1: 問い→主張分解. Returns claims with claim_id, text, expected_polarity, granularity, and verification hints.",
        inputSchema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Research question to decompose into atomic claims"
                },
                "use_llm": {
                    "type": "boolean",
                    "description": "Use LLM for decomposition (True) or rule-based (False). Default: True",
                    "default": True
                },
                "use_slow_model": {
                    "type": "boolean",
                    "description": "Use slower, more capable LLM model. Default: False",
                    "default": False
                }
            },
            "required": ["question"]
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
    """
    logger.info("Tool called", tool=name, arguments=arguments)
    
    try:
        result = await _dispatch_tool(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        logger.error("Tool error", tool=name, error=str(e), exc_info=True)
        error_result = {
            "ok": False,
            "error": str(e),
            "error_type": type(e).__name__
        }
        return [TextContent(type="text", text=json.dumps(error_result, ensure_ascii=False))]


async def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch tool call to appropriate handler.
    
    Args:
        name: Tool name.
        arguments: Tool arguments.
        
    Returns:
        Tool result.
    """
    handlers = {
        "search_serp": _handle_search_serp,
        "fetch_url": _handle_fetch_url,
        "extract_content": _handle_extract_content,
        "rank_candidates": _handle_rank_candidates,
        "llm_extract": _handle_llm_extract,
        "nli_judge": _handle_nli_judge,
        "notify_user": _handle_notify_user,
        # Authentication Queue
        "get_pending_authentications": _handle_get_pending_authentications,
        "start_authentication_session": _handle_start_authentication_session,
        "complete_authentication": _handle_complete_authentication,
        "skip_authentication": _handle_skip_authentication,
        "schedule_job": _handle_schedule_job,
        "create_task": _handle_create_task,
        "get_task_status": _handle_get_task_status,
        "get_report_materials": _handle_get_report_materials,
        "get_evidence_graph": _handle_get_evidence_graph,
        # Phase 11: Exploration Control
        "get_research_context": _handle_get_research_context,
        "execute_subquery": _handle_execute_subquery,
        "get_exploration_status": _handle_get_exploration_status,
        "execute_refutation": _handle_execute_refutation,
        "finalize_exploration": _handle_finalize_exploration,
        # Phase 16.3.2: Calibration Evaluation (§4.6.1)
        "save_calibration_evaluation": _handle_save_calibration_evaluation,
        "get_calibration_evaluations": _handle_get_calibration_evaluations,
        "get_reliability_diagram_data": _handle_get_reliability_diagram_data,
        "add_calibration_sample": _handle_add_calibration_sample,
        "get_calibration_stats": _handle_get_calibration_stats,
        "rollback_calibration": _handle_rollback_calibration,
        # Phase 16.2.6: Claim Decomposition (§3.3.1)
        "decompose_question": _handle_decompose_question,
    }
    
    handler = handlers.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    
    return await handler(arguments)


# ============================================================
# Tool Handlers
# ============================================================

async def _handle_search_serp(args: dict[str, Any]) -> dict[str, Any]:
    """Handle search_serp tool call."""
    from src.search.searxng import search_serp
    
    query = args["query"]
    engines = args.get("engines")
    limit = args.get("limit", 10)
    time_range = args.get("time_range", "all")
    task_id = args.get("task_id")
    
    with LogContext(task_id=task_id):
        results = await search_serp(
            query=query,
            engines=engines,
            limit=limit,
            time_range=time_range,
            task_id=task_id,
        )
        
        return {
            "ok": True,
            "query": query,
            "result_count": len(results),
            "results": results,
        }


async def _handle_fetch_url(args: dict[str, Any]) -> dict[str, Any]:
    """Handle fetch_url tool call."""
    from src.crawler.fetcher import fetch_url
    
    url = args["url"]
    context = args.get("context", {})
    policy = args.get("policy", {})
    task_id = args.get("task_id")
    
    with LogContext(task_id=task_id):
        result = await fetch_url(
            url=url,
            context=context,
            policy=policy,
            task_id=task_id,
        )
        
        return result


async def _handle_extract_content(args: dict[str, Any]) -> dict[str, Any]:
    """Handle extract_content tool call."""
    from src.extractor.content import extract_content
    
    input_path = args.get("input_path")
    html = args.get("html")
    content_type = args.get("content_type", "auto")
    page_id = args.get("page_id")
    
    result = await extract_content(
        input_path=input_path,
        html=html,
        content_type=content_type,
        page_id=page_id,
    )
    
    return result


async def _handle_rank_candidates(args: dict[str, Any]) -> dict[str, Any]:
    """Handle rank_candidates tool call."""
    from src.filter.ranking import rank_candidates
    
    query = args["query"]
    passages = args["passages"]
    top_k = args.get("top_k", 20)
    
    results = await rank_candidates(
        query=query,
        passages=passages,
        top_k=top_k,
    )
    
    return {
        "ok": True,
        "query": query,
        "ranked_count": len(results),
        "results": results,
    }


async def _handle_llm_extract(args: dict[str, Any]) -> dict[str, Any]:
    """Handle llm_extract tool call."""
    from src.filter.llm import llm_extract
    
    passages = args["passages"]
    task = args["task"]
    context = args.get("context")
    
    result = await llm_extract(
        passages=passages,
        task=task,
        context=context,
    )
    
    return result


async def _handle_nli_judge(args: dict[str, Any]) -> dict[str, Any]:
    """Handle nli_judge tool call."""
    from src.filter.nli import nli_judge
    
    pairs = args["pairs"]
    
    results = await nli_judge(pairs=pairs)
    
    return {
        "ok": True,
        "results": results,
    }


async def _handle_notify_user(args: dict[str, Any]) -> dict[str, Any]:
    """Handle notify_user tool call."""
    from src.utils.notification import notify_user
    
    event = args["event"]
    payload = args["payload"]
    
    result = await notify_user(event=event, payload=payload)
    
    return result


# Authentication Queue Handlers

async def _handle_get_pending_authentications(args: dict[str, Any]) -> dict[str, Any]:
    """Handle get_pending_authentications tool call."""
    from src.utils.notification import get_intervention_queue
    
    task_id = args["task_id"]
    priority = args.get("priority")
    
    queue = get_intervention_queue()
    
    # Get pending items
    pending = await queue.get_pending(
        task_id=task_id,
        priority=priority if priority and priority != "all" else None,
    )
    
    # Get counts
    counts = await queue.get_pending_count(task_id)
    
    return {
        "ok": True,
        "task_id": task_id,
        "pending": pending,
        "counts": counts,
    }


async def _handle_start_authentication_session(args: dict[str, Any]) -> dict[str, Any]:
    """Handle start_authentication_session tool call."""
    from src.utils.notification import get_intervention_queue
    
    task_id = args["task_id"]
    queue_ids = args.get("queue_ids")
    priority_filter = args.get("priority_filter")
    
    queue = get_intervention_queue()
    
    result = await queue.start_session(
        task_id=task_id,
        queue_ids=queue_ids,
        priority_filter=priority_filter,
    )
    
    return result


async def _handle_complete_authentication(args: dict[str, Any]) -> dict[str, Any]:
    """Handle complete_authentication tool call."""
    from src.utils.notification import get_intervention_queue
    
    queue_id = args["queue_id"]
    success = args["success"]
    session_data = args.get("session_data")
    
    queue = get_intervention_queue()
    
    result = await queue.complete(
        queue_id=queue_id,
        success=success,
        session_data=session_data,
    )
    
    return result


async def _handle_skip_authentication(args: dict[str, Any]) -> dict[str, Any]:
    """Handle skip_authentication tool call."""
    from src.utils.notification import get_intervention_queue
    
    task_id = args["task_id"]
    queue_ids = args.get("queue_ids")
    
    queue = get_intervention_queue()
    
    result = await queue.skip(
        task_id=task_id,
        queue_ids=queue_ids,
    )
    
    return result


async def _handle_schedule_job(args: dict[str, Any]) -> dict[str, Any]:
    """Handle schedule_job tool call."""
    from src.scheduler.jobs import schedule_job
    
    job = args["job"]
    
    result = await schedule_job(job=job)
    
    return result


async def _handle_create_task(args: dict[str, Any]) -> dict[str, Any]:
    """Handle create_task tool call."""
    query = args["query"]
    config = args.get("config")
    
    db = await get_database()
    task_id = await db.create_task(query=query, config=config)
    
    return {
        "ok": True,
        "task_id": task_id,
        "query": query,
        "status": "pending",
    }


async def _handle_get_task_status(args: dict[str, Any]) -> dict[str, Any]:
    """Handle get_task_status tool call."""
    task_id = args["task_id"]
    
    db = await get_database()
    task = await db.fetch_one(
        "SELECT * FROM tasks WHERE id = ?",
        (task_id,),
    )
    
    if task is None:
        return {
            "ok": False,
            "error": f"Task not found: {task_id}",
        }
    
    # Get progress stats
    progress = await db.fetch_one(
        "SELECT * FROM v_task_progress WHERE task_id = ?",
        (task_id,),
    )
    
    return {
        "ok": True,
        "task": task,
        "progress": progress,
    }


async def _handle_get_report_materials(args: dict[str, Any]) -> dict[str, Any]:
    """Handle get_report_materials tool call.
    
    Returns materials for Cursor AI to compose a report.
    Does NOT generate report - respects responsibility separation (§2.1).
    """
    from src.report.generator import get_report_materials
    
    task_id = args["task_id"]
    include_evidence_graph = args.get("include_evidence_graph", True)
    include_fragments = args.get("include_fragments", True)
    
    result = await get_report_materials(
        task_id=task_id,
        include_evidence_graph=include_evidence_graph,
        include_fragments=include_fragments,
    )
    
    return result


async def _handle_get_evidence_graph(args: dict[str, Any]) -> dict[str, Any]:
    """Handle get_evidence_graph tool call.
    
    Returns evidence graph structure for Cursor AI to interpret.
    """
    from src.report.generator import get_evidence_graph
    
    task_id = args["task_id"]
    claim_ids = args.get("claim_ids")
    include_fragments = args.get("include_fragments", True)
    
    result = await get_evidence_graph(
        task_id=task_id,
        claim_ids=claim_ids,
        include_fragments=include_fragments,
    )
    
    return result


# ============================================================
# Phase 11: Exploration Control Handlers
# ============================================================

# Global state managers (per task)
_exploration_states: dict[str, "ExplorationState"] = {}


async def _get_exploration_state(task_id: str) -> "ExplorationState":
    """Get or create exploration state for a task."""
    from src.research.state import ExplorationState
    
    if task_id not in _exploration_states:
        state = ExplorationState(task_id)
        await state.load_state()
        _exploration_states[task_id] = state
    
    return _exploration_states[task_id]


async def _handle_get_research_context(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_research_context tool call.
    
    Returns design support information for Cursor AI.
    Does NOT generate subquery candidates.
    """
    from src.research.context import ResearchContext
    
    task_id = args["task_id"]
    
    with LogContext(task_id=task_id):
        context = ResearchContext(task_id)
        result = await context.get_context()
        return result


async def _handle_execute_subquery(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle execute_subquery tool call.
    
    Executes a subquery designed by Cursor AI.
    """
    from src.research.executor import SubqueryExecutor
    
    task_id = args["task_id"]
    subquery = args["subquery"]
    priority = args.get("priority", "medium")
    budget_pages = args.get("budget_pages")
    budget_time_seconds = args.get("budget_time_seconds")
    
    with LogContext(task_id=task_id):
        state = await _get_exploration_state(task_id)
        executor = SubqueryExecutor(task_id, state)
        
        result = await executor.execute(
            subquery=subquery,
            priority=priority,
            budget_pages=budget_pages,
            budget_time_seconds=budget_time_seconds,
        )
        
        return result.to_dict()


async def _handle_get_exploration_status(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_exploration_status tool call.
    
    Returns current exploration status for Cursor AI decision making.
    """
    task_id = args["task_id"]
    
    with LogContext(task_id=task_id):
        state = await _get_exploration_state(task_id)
        return state.get_status()


async def _handle_execute_refutation(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle execute_refutation tool call.
    
    Executes refutation search using mechanical patterns.
    """
    from src.research.refutation import RefutationExecutor
    
    task_id = args["task_id"]
    claim_id = args.get("claim_id")
    subquery_id = args.get("subquery_id")
    
    with LogContext(task_id=task_id):
        state = await _get_exploration_state(task_id)
        executor = RefutationExecutor(task_id, state)
        
        if claim_id:
            result = await executor.execute_for_claim(claim_id)
        elif subquery_id:
            result = await executor.execute_for_subquery(subquery_id)
        else:
            return {
                "ok": False,
                "error": "Either claim_id or subquery_id must be provided",
            }
        
        return result.to_dict()


async def _handle_finalize_exploration(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle finalize_exploration tool call.
    
    Finalizes exploration and returns summary.
    """
    task_id = args["task_id"]
    
    with LogContext(task_id=task_id):
        state = await _get_exploration_state(task_id)
        result = await state.finalize()
        
        # Save final state
        await state.save_state()
        
        # Clean up state manager
        if task_id in _exploration_states:
            del _exploration_states[task_id]
        
        return result


# ============================================================
# Phase 16.3.2: Calibration Evaluation Handlers (§4.6.1)
# ============================================================

async def _handle_save_calibration_evaluation(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle save_calibration_evaluation tool call.
    
    Implements §4.6.1: Lancet責任 - 評価計算・DB保存.
    """
    from src.utils.calibration import save_calibration_evaluation
    
    source = args["source"]
    predictions = args["predictions"]
    labels = args["labels"]
    
    return await save_calibration_evaluation(
        source=source,
        predictions=predictions,
        labels=labels,
    )


async def _handle_get_calibration_evaluations(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_calibration_evaluations tool call.
    
    Implements §4.6.1: Lancet責任 - 構造化データの返却.
    """
    from src.utils.calibration import get_calibration_evaluations
    
    source = args.get("source")
    limit = args.get("limit", 50)
    since = args.get("since")
    
    return await get_calibration_evaluations(
        source=source,
        limit=limit,
        since=since,
    )


async def _handle_get_reliability_diagram_data(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_reliability_diagram_data tool call.
    
    Implements §4.6.1: Lancet責任 - 信頼度-精度曲線用ビンデータ返却.
    """
    from src.utils.calibration import get_reliability_diagram_data
    
    source = args["source"]
    evaluation_id = args.get("evaluation_id")
    
    return await get_reliability_diagram_data(
        source=source,
        evaluation_id=evaluation_id,
    )


async def _handle_add_calibration_sample(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle add_calibration_sample tool call.
    
    Allows Cursor AI to provide feedback for calibration improvement.
    """
    from src.utils.calibration import add_calibration_sample
    
    source = args["source"]
    predicted_prob = args["predicted_prob"]
    actual_label = args["actual_label"]
    logit = args.get("logit")
    
    return await add_calibration_sample(
        source=source,
        predicted_prob=predicted_prob,
        actual_label=actual_label,
        logit=logit,
    )


async def _handle_get_calibration_stats(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_calibration_stats tool call.
    
    Returns calibration statistics for Cursor AI to monitor and decide on rollback.
    """
    from src.utils.calibration import get_calibration_stats
    
    return await get_calibration_stats()


async def _handle_rollback_calibration(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle rollback_calibration tool call.
    
    Cursor AI decides when to rollback based on degradation detection.
    """
    from src.utils.calibration import rollback_calibration
    
    source = args["source"]
    to_version = args.get("to_version")
    reason = args.get("reason", "Manual rollback by Cursor AI")
    
    return await rollback_calibration(
        source=source,
        to_version=to_version,
        reason=reason,
    )


# ============================================================
# Phase 16.2.6: Claim Decomposition Handlers (§3.3.1)
# ============================================================

async def _handle_decompose_question(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle decompose_question tool call.
    
    Implements §3.3.1: 問い→主張分解.
    Decomposes research questions into atomic claims for systematic verification.
    """
    from src.filter.claim_decomposition import decompose_question
    
    question = args["question"]
    use_llm = args.get("use_llm", True)
    use_slow_model = args.get("use_slow_model", False)
    
    result = await decompose_question(
        question=question,
        use_llm=use_llm,
        use_slow_model=use_slow_model,
    )
    
    return result.to_dict()


# ============================================================
# Server Entry Point
# ============================================================

async def run_server() -> None:
    """Run the MCP server."""
    logger.info("Starting Lancet MCP server")
    
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

