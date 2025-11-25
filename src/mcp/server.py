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
        name="generate_report",
        description="Generate a research report from collected evidence.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to generate report for"
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "description": "Output format",
                    "default": "markdown"
                },
                "include_evidence_graph": {
                    "type": "boolean",
                    "description": "Include evidence graph in report",
                    "default": True
                }
            },
            "required": ["task_id"]
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
        "schedule_job": _handle_schedule_job,
        "create_task": _handle_create_task,
        "get_task_status": _handle_get_task_status,
        "generate_report": _handle_generate_report,
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


async def _handle_generate_report(args: dict[str, Any]) -> dict[str, Any]:
    """Handle generate_report tool call."""
    from src.report.generator import generate_report
    
    task_id = args["task_id"]
    format_type = args.get("format", "markdown")
    include_evidence_graph = args.get("include_evidence_graph", True)
    
    result = await generate_report(
        task_id=task_id,
        format_type=format_type,
        include_evidence_graph=include_evidence_graph,
    )
    
    return result


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

