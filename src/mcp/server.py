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
        outputSchema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean", "description": "True if task created successfully"},
                "task_id": {"type": "string", "description": "Unique task identifier. Use this for all subsequent operations."},
                "query": {"type": "string", "description": "The research query"},
                "created_at": {"type": "string", "description": "ISO timestamp of creation"},
                "budget": {
                    "type": "object",
                    "properties": {
                        "budget_pages": {"type": "integer"},
                        "max_seconds": {"type": "integer"},
                    },
                },
            },
            "required": ["ok", "task_id"],
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
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
                    "maximum": 60,
                },
            },
            "required": ["task_id"],
        },
        outputSchema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "task_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["exploring", "paused", "completed", "failed"],
                    "description": "Current task state",
                },
                "query": {"type": "string", "description": "Original research query"},
                "searches": {
                    "type": "array",
                    "description": "Status of each search query",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "query": {"type": "string"},
                            "status": {"type": "string", "enum": ["queued", "running", "completed", "failed", "cancelled"]},
                            "pages_fetched": {"type": "integer"},
                            "useful_fragments": {"type": "integer"},
                            "harvest_rate": {"type": "number", "description": "0.0-1.0, ratio of useful content found"},
                            "satisfaction_score": {"type": "number", "description": "0.0-1.0, how well query is covered"},
                            "has_primary_source": {"type": "boolean", "description": "True if academic/primary source found"},
                        },
                    },
                },
                "queue": {
                    "type": "object",
                    "description": "Search queue status",
                    "properties": {
                        "depth": {"type": "integer", "description": "Queued searches waiting"},
                        "running": {"type": "integer", "description": "Currently executing searches"},
                    },
                },
                "pending_auth_count": {
                    "type": "integer",
                    "description": "CAPTCHAs awaiting user resolution. If > 0, use get_auth_queue.",
                },
                "metrics": {
                    "type": "object",
                    "properties": {
                        "total_searches": {"type": "integer"},
                        "satisfied_count": {"type": "integer", "description": "Searches with satisfaction >= 0.7"},
                        "total_pages": {"type": "integer"},
                        "total_fragments": {"type": "integer"},
                        "total_claims": {"type": "integer", "description": "Verified assertions extracted"},
                        "elapsed_seconds": {"type": "integer"},
                    },
                },
                "budget": {
                    "type": "object",
                    "properties": {
                        "budget_pages_used": {"type": "integer"},
                        "budget_pages_limit": {"type": "integer"},
                        "remaining_percent": {"type": "integer", "description": "0-100, budget remaining"},
                    },
                },
                "idle_seconds": {"type": "integer", "description": "Seconds since last activity"},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
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
                },
            },
            "required": ["task_id", "queries"],
        },
        outputSchema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "queued_count": {"type": "integer", "description": "Number of queries added to queue"},
                "skipped_count": {"type": "integer", "description": "Duplicates skipped (already queued/running)"},
                "search_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "IDs of queued searches for tracking",
                },
                "message": {"type": "string", "description": "Human-readable status message"},
            },
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
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

AFTER STOPPING: Use get_materials to retrieve collected evidence for report composition.""",
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
        outputSchema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "task_id": {"type": "string"},
                "final_status": {"type": "string"},
                "mode": {"type": "string"},
                "metrics": {
                    "type": "object",
                    "description": "Final task metrics",
                    "properties": {
                        "total_searches": {"type": "integer"},
                        "total_pages": {"type": "integer"},
                        "total_claims": {"type": "integer"},
                    },
                },
            },
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
        },
    ),
    # ============================================================
    # 3. Materials (1 tool)
    # ============================================================
    Tool(
        name="get_materials",
        title="Get Report Materials",
        description="""Get structured research materials for report composition. You compose the final report.

WHAT YOU RECEIVE:
- claims: Verified assertions with confidence scores and NLI classification
- fragments: Source excerpts with citations for inline quotes
- evidence_graph: Claim-evidence relationships (optional, for visualization)

USING CLAIMS FOR REPORT STRUCTURE:
- Each claim has confidence (0.0-1.0) based on Bayesian aggregation of evidence
- uncertainty: How much the evidence varies (high = conflicting sources)
- controversy: Degree of support vs refutation (high = debated topic)
- has_refutation: True if counter-evidence exists - address these in balanced reporting

NLI CLASSIFICATION (on evidence edges):
- supports: Evidence supports the claim
- refutes: Evidence contradicts the claim
- neutral: Evidence is related but neither supports nor refutes

EVIDENCE GRAPH USES (when include_graph=true):
- Visualize claim-evidence relationships
- Build citation networks (which sources cite which)
- Temporal analysis (evidence publication dates in evidence_years)
- Identify key sources that support multiple claims""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to get materials from",
                },
                "options": {
                    "type": "object",
                    "properties": {
                        "include_graph": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include evidence graph for visualization. Adds nodes/edges data.",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["structured", "narrative"],
                            "default": "structured",
                            "description": "Output format. 'structured' for programmatic use, 'narrative' for prose.",
                        },
                    },
                },
            },
            "required": ["task_id"],
        },
        outputSchema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "task_id": {"type": "string"},
                "query": {"type": "string", "description": "Original research query"},
                "claims": {
                    "type": "array",
                    "description": "Verified assertions extracted from sources. Use as report structure.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string", "description": "The claim assertion"},
                            "confidence": {"type": "number", "description": "0.0-1.0, Bayesian posterior mean"},
                            "uncertainty": {"type": "number", "description": "0.0-1.0, posterior stddev"},
                            "controversy": {"type": "number", "description": "0.0-1.0, support vs refute conflict"},
                            "evidence_count": {"type": "integer"},
                            "has_refutation": {"type": "boolean", "description": "True if refuting evidence exists"},
                            "sources": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "url": {"type": "string"},
                                        "title": {"type": "string"},
                                        "domain": {"type": "string"},
                                        "domain_category": {
                                            "type": "string",
                                            "enum": ["academic", "news", "government", "organization", "commercial", "social", "unknown"],
                                        },
                                        "is_primary": {"type": "boolean", "description": "True if academic/primary source"},
                                    },
                                },
                            },
                            "evidence": {
                                "type": "array",
                                "description": "Evidence details with NLI labels",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "fragment_id": {"type": "string"},
                                        "relation": {"type": "string", "enum": ["supports", "refutes", "neutral"]},
                                        "confidence": {"type": "number"},
                                    },
                                },
                            },
                            "evidence_years": {
                                "type": "object",
                                "description": "Publication year distribution for temporal analysis",
                            },
                        },
                    },
                },
                "fragments": {
                    "type": "array",
                    "description": "Source excerpts for inline citations",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string", "description": "Excerpt content (max 500 chars)"},
                            "source_url": {"type": "string"},
                            "context": {"type": "string", "description": "Heading/section context"},
                            "is_primary": {"type": "boolean"},
                        },
                    },
                },
                "evidence_graph": {
                    "type": "object",
                    "description": "Graph structure for visualization (only if include_graph=true)",
                    "properties": {
                        "nodes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "type": {"type": "string", "enum": ["claim", "fragment", "page"]},
                                    "label": {"type": "string"},
                                },
                            },
                        },
                        "edges": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "source": {"type": "string"},
                                    "target": {"type": "string"},
                                    "relation": {"type": "string", "enum": ["supports", "refutes", "neutral", "cites"]},
                                    "confidence": {"type": "number"},
                                },
                            },
                        },
                    },
                },
                "summary": {
                    "type": "object",
                    "properties": {
                        "total_claims": {"type": "integer"},
                        "verified_claims": {"type": "integer", "description": "Claims with 2+ evidence sources"},
                        "refuted_claims": {"type": "integer", "description": "Claims with refuting evidence"},
                        "primary_source_ratio": {"type": "number", "description": "Ratio of academic/primary sources"},
                    },
                },
            },
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    ),
    # ============================================================
    # 4. Calibration (2 tools)
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
                        "source": {"type": "string", "description": "Filter by source model (e.g., 'nli_judge')"},
                        "limit": {"type": "integer", "default": 50},
                        "since": {"type": "string", "description": "ISO timestamp to filter from"},
                    },
                },
            },
            "required": ["action"],
        },
        outputSchema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "action": {"type": "string"},
                "current_params": {
                    "type": "object",
                    "description": "For get_stats: calibration params per source",
                },
                "evaluations": {
                    "type": "array",
                    "description": "For get_evaluations: historical records",
                },
            },
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
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
        outputSchema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "source": {"type": "string"},
                "rolled_back_to": {"type": "integer", "description": "Version now active"},
                "previous_version": {"type": "integer", "description": "Version that was replaced"},
                "brier_after": {"type": "number", "description": "Brier score of restored version"},
                "method": {"type": "string", "enum": ["platt", "temperature"]},
            },
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
        },
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
        outputSchema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "group_by": {"type": "string"},
                "total_count": {"type": "integer"},
                "items": {
                    "type": "array",
                    "description": "When group_by=none",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "domain": {"type": "string"},
                            "auth_type": {"type": "string"},
                            "url": {"type": "string"},
                            "priority": {"type": "string"},
                        },
                    },
                },
                "groups": {
                    "type": "object",
                    "description": "When group_by=domain or type",
                },
            },
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
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
        outputSchema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "target": {"type": "string"},
                "action": {"type": "string"},
                "resolved_count": {"type": "integer", "description": "Items resolved"},
                "requeued_count": {"type": "integer", "description": "Searches requeued for retry"},
            },
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
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
1. Get edge_id from get_materials evidence data
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
                    "description": "For claim_reject/claim_restore. Get from get_materials claims[].id",
                },
                "edge_id": {
                    "type": "string",
                    "description": "For edge_correct. Get from get_materials claims[].evidence[].edge_id",
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
        outputSchema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "action": {"type": "string"},
                "domain_pattern": {"type": "string"},
                "claim_id": {"type": "string"},
                "edge_id": {"type": "string"},
                "previous_relation": {"type": "string", "description": "For edge_correct: old label"},
                "new_relation": {"type": "string", "description": "For edge_correct: new label"},
                "sample_id": {"type": "string", "description": "For edge_correct: training sample ID if label changed"},
                "rule_id": {"type": "string", "description": "For domain_*: created rule ID"},
            },
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
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
# Lock to prevent race condition in _get_exploration_state (H-F fix)
import asyncio
_exploration_state_locks: dict[str, asyncio.Lock] = {}
_exploration_state_global_lock = asyncio.Lock()


async def _get_exploration_state(task_id: str) -> Any:
    """Get or create exploration state for a task.

    Uses per-task locking to prevent race condition where multiple
    coroutines create separate ExplorationState instances for the
    same task_id (H-F fix).
    """
    from src.research.state import ExplorationState

    # Get or create per-task lock (with global lock protection)
    async with _exploration_state_global_lock:
        if task_id not in _exploration_state_locks:
            _exploration_state_locks[task_id] = asyncio.Lock()
        lock = _exploration_state_locks[task_id]

    # #region agent log
    import json, time as _time
    cache_hit = task_id in _exploration_states
    existing_id = id(_exploration_states.get(task_id)) if cache_hit else None
    with open("/home/statuser/lyra/.cursor/debug.log", "a") as _f:
        _f.write(json.dumps({
            "hypothesisId": "H-H",
            "location": "src/mcp/server.py:_get_exploration_state_entry",
            "message": "_get_exploration_state called",
            "data": {"task_id": task_id, "cache_hit": cache_hit, "existing_state_id": existing_id},
            "timestamp": _time.time() * 1000,
            "sessionId": "debug-session"
        }) + "\n")
    # #endregion

    # Use per-task lock to prevent race condition
    async with lock:
        if task_id not in _exploration_states:
            state = ExplorationState(task_id)
            await state.load_state()
            _exploration_states[task_id] = state
            # #region agent log
            with open("/home/statuser/lyra/.cursor/debug.log", "a") as _f:
                _f.write(json.dumps({
                    "hypothesisId": "H-H",
                    "location": "src/mcp/server.py:_get_exploration_state_new",
                    "message": "Created new ExplorationState",
                    "data": {"task_id": task_id, "new_state_id": id(state)},
                    "timestamp": _time.time() * 1000,
                    "sessionId": "debug-session"
                }) + "\n")
            # #endregion

        return _exploration_states[task_id]


def _clear_exploration_state(task_id: str) -> None:
    """Clear exploration state from cache."""
    if task_id in _exploration_states:
        del _exploration_states[task_id]


# ============================================================
# Task Management Handlers
# ============================================================


async def _get_metrics_from_db(db: Any, task_id: str) -> dict[str, Any]:
    """Get metrics directly from database for a task.

    H-D fix: Fallback when ExplorationState is not available.
    Fetches counts from DB tables instead of returning zeros.

    Note: DB schema has task_id on queries and claims, but pages/fragments
    are linked via serp_items → pages → fragments chain.

    Args:
        db: Database connection.
        task_id: Task ID.

    Returns:
        Metrics dict with counts from DB.
    """
    # #region agent log
    import json, time as _time
    with open("/home/statuser/lyra/.cursor/debug.log", "a") as _f:
        _f.write(json.dumps({
            "hypothesisId": "H-D",
            "location": "src/mcp/server.py:_get_metrics_from_db_entry",
            "message": "Fetching metrics from DB (fallback)",
            "data": {"task_id": task_id},
            "timestamp": _time.time() * 1000,
            "sessionId": "debug-session"
        }) + "\n")
    # #endregion

    try:
        # Count queries/searches
        cursor = await db.execute(
            "SELECT COUNT(*) FROM queries WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        total_searches = row[0] if row else 0

        # Count pages via serp_items (pages don't have task_id directly)
        cursor = await db.execute(
            """
            SELECT COUNT(DISTINCT p.id)
            FROM pages p
            JOIN serp_items si ON p.url = si.url
            JOIN queries q ON si.query_id = q.id
            WHERE q.task_id = ?
            """,
            (task_id,),
        )
        row = await cursor.fetchone()
        total_pages = row[0] if row else 0

        # Count fragments via pages → serp_items → queries
        cursor = await db.execute(
            """
            SELECT COUNT(DISTINCT f.id)
            FROM fragments f
            JOIN pages p ON f.page_id = p.id
            JOIN serp_items si ON p.url = si.url
            JOIN queries q ON si.query_id = q.id
            WHERE q.task_id = ?
            """,
            (task_id,),
        )
        row = await cursor.fetchone()
        total_fragments = row[0] if row else 0

        # Count claims (has direct task_id)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM claims WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        total_claims = row[0] if row else 0

        # Get task creation time for elapsed_seconds
        cursor = await db.execute(
            "SELECT created_at FROM tasks WHERE id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        elapsed_seconds = 0
        if row and row[0]:
            from datetime import datetime, timezone
            try:
                created_at = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                elapsed_seconds = int((datetime.now(timezone.utc) - created_at).total_seconds())
            except (ValueError, TypeError):
                pass

        result = {
            "total_searches": total_searches,
            "satisfied_count": 0,  # Can't determine from DB alone
            "total_pages": total_pages,
            "total_fragments": total_fragments,
            "total_claims": total_claims,
            "elapsed_seconds": elapsed_seconds,
        }

        # #region agent log
        import json, time as _time
        with open("/home/statuser/lyra/.cursor/debug.log", "a") as _f:
            _f.write(json.dumps({
                "hypothesisId": "H-D",
                "location": "src/mcp/server.py:_get_metrics_from_db_result",
                "message": "DB metrics fetched successfully",
                "data": {"task_id": task_id, "metrics": result},
                "timestamp": _time.time() * 1000,
                "sessionId": "debug-session"
            }) + "\n")
        # #endregion

        return result
    except Exception as e:
        logger.warning("Failed to get metrics from DB", task_id=task_id, error=str(e))

        # #region agent log
        import json, time as _time
        with open("/home/statuser/lyra/.cursor/debug.log", "a") as _f:
            _f.write(json.dumps({
                "hypothesisId": "H-D",
                "location": "src/mcp/server.py:_get_metrics_from_db_error",
                "message": "DB metrics fetch failed",
                "data": {"task_id": task_id, "error": str(e)},
                "timestamp": _time.time() * 1000,
                "sessionId": "debug-session"
            }) + "\n")
        # #endregion

        return {
            "total_searches": 0,
            "satisfied_count": 0,
            "total_pages": 0,
            "total_fragments": 0,
            "total_claims": 0,
            "elapsed_seconds": 0,
        }


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


async def _get_pending_auth_info(db: Any, task_id: str) -> dict[str, Any]:
    """Get pending authentication info for a task.

    Per ADR-0007: Returns info about CAPTCHAs awaiting human intervention.

    Args:
        db: Database connection.
        task_id: Task ID.

    Returns:
        Pending auth info dict.
    """
    try:
        # Count awaiting_auth jobs
        cursor = await db.execute(
            """
            SELECT COUNT(*) as count FROM jobs
            WHERE task_id = ? AND kind = 'search_queue' AND state = 'awaiting_auth'
            """,
            (task_id,),
        )
        row = await cursor.fetchone()
        awaiting_count = row["count"] if row else 0

        # Get pending intervention queue items for this task
        cursor = await db.execute(
            """
            SELECT domain, auth_type, queued_at FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
            ORDER BY queued_at ASC
            """,
            (task_id,),
        )
        pending_rows = await cursor.fetchall()

        # Group by domain
        by_domain: dict[str, list[str]] = {}
        for row in pending_rows:
            domain = row["domain"] if isinstance(row, dict) else row[0]
            auth_type = row["auth_type"] if isinstance(row, dict) else row[1]
            by_domain.setdefault(domain, []).append(auth_type)

        return {
            "awaiting_auth_jobs": awaiting_count,
            "pending_captchas": len(pending_rows),
            "domains": [
                {"domain": d, "auth_types": list(set(t)), "count": len(t)}
                for d, t in by_domain.items()
            ],
        }
    except Exception as e:
        logger.warning("Failed to get pending auth info", error=str(e))
        return {
            "awaiting_auth_jobs": 0,
            "pending_captchas": 0,
            "domains": [],
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
        # #region agent log
        import json, time as _time
        with open("/home/statuser/lyra/.cursor/debug.log", "a") as _f:
            _f.write(json.dumps({
                "hypothesisId": "H-D",
                "location": "src/mcp/server.py:_handle_get_status_branch",
                "message": "get_status exploration_status check",
                "data": {"task_id": task_id, "has_exploration_status": exploration_status is not None},
                "timestamp": _time.time() * 1000,
                "sessionId": "debug-session"
            }) + "\n")
        # #endregion

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

            # Get pending auth info (ADR-0007)
            pending_auth = await _get_pending_auth_info(db, task_id)

            response = {
                "ok": True,
                "task_id": task_id,
                "status": status,
                "query": task_query,
                "searches": searches,
                "queue": queue_info,  # ADR-0010: Search queue status
                "pending_auth": pending_auth,  # ADR-0007: CAPTCHA queue status
                # Convenience field for agents/clients: quick check without parsing nested structures
                "pending_auth_count": int(pending_auth.get("pending_captchas", 0)),
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

            # Get pending auth info (ADR-0007)
            pending_auth = await _get_pending_auth_info(db, task_id)

            # H-D fix: Fetch metrics directly from DB when exploration state unavailable
            db_metrics = await _get_metrics_from_db(db, task_id)

            response = {
                "ok": True,
                "task_id": task_id,
                "status": db_status or "created",
                "query": task_query,
                "searches": [],
                "queue": queue_info,  # ADR-0010: Search queue status
                "pending_auth": pending_auth,  # ADR-0007: CAPTCHA queue status
                # Convenience field for agents/clients: quick check without parsing nested structures
                "pending_auth_count": int(pending_auth.get("pending_captchas", 0)),
                "metrics": db_metrics,
                "budget": {
                    "budget_pages_used": db_metrics.get("total_pages", 0),
                    "budget_pages_limit": 120,
                    "time_used_seconds": db_metrics.get("elapsed_seconds", 0),
                    "time_limit_seconds": 1200,
                    "remaining_percent": max(0, int((1 - db_metrics.get("total_pages", 0) / 120) * 100)),
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

        # Queue each search (with duplicate detection)
        search_ids = []
        skipped_count = 0
        now = datetime.now(UTC).isoformat()

        for query in queries:
            # Check for duplicate query in same task (queued or running)
            existing = await db.fetch_one(
                """
                SELECT id FROM jobs
                WHERE task_id = ? AND kind = 'search_queue'
                  AND state IN ('queued', 'running')
                  AND json_extract(input_json, '$.query') = ?
                """,
                (task_id, query),
            )
            if existing:
                # Skip duplicate query
                logger.debug(
                    "Skipping duplicate query",
                    task_id=task_id,
                    query=query[:50],
                    existing_id=existing.get("id"),
                )
                skipped_count += 1
                continue

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
            queued=len(search_ids),
            skipped=skipped_count,
            priority=priority_str,
        )

        message = f"{len(search_ids)} searches queued"
        if skipped_count > 0:
            message += f" ({skipped_count} duplicates skipped)"
        message += ". Use get_status(wait=N) to monitor progress."

        return {
            "ok": True,
            "queued_count": len(search_ids),
            "skipped_count": skipped_count,
            "search_ids": search_ids,
            "message": message,
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
    # Use base port (worker 0) for health check
    chrome_port = settings.browser.chrome_base_port
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

        # Cancel pending auth queue items for this task
        await _cancel_auth_queue_for_task(task_id, db)

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


async def _cancel_auth_queue_for_task(task_id: str, db: Any) -> int:
    """Cancel pending auth queue items for a stopped task.

    Per ADR-0007: When a task is stopped, all pending authentication
    queue items for that task should be marked as cancelled.

    Args:
        task_id: The task ID.
        db: Database connection.

    Returns:
        Number of auth queue items cancelled.
    """
    cursor = await db.execute(
        """
        UPDATE intervention_queue
        SET status = 'cancelled', completed_at = datetime('now')
        WHERE task_id = ? AND status IN ('pending', 'in_progress')
        """,
        (task_id,),
    )
    cancelled_count = getattr(cursor, "rowcount", 0)

    if cancelled_count > 0:
        logger.info(
            "Auth queue items cancelled for stopped task",
            task_id=task_id,
            cancelled_count=cancelled_count,
        )

    return cancelled_count


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

    Implements calibration metrics operations (2 actions).
    Actions: get_stats, get_evaluations.

    Note: add_sample was removed. Use feedback(edge_correct) for ground-truth collection.
    Batch evaluation/visualization are handled by scripts (see ADR-0011).
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
            expected="one of: get_stats, get_evaluations",
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
        # Use base port (worker 0) for page retrieval
        chrome_port = getattr(settings.browser, "chrome_base_port", 9222)
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
    Supports single item, domain-batch, or task-batch operations.
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

    valid_targets = {"item", "domain", "task"}
    if target not in valid_targets:
        raise InvalidParamsError(
            f"Invalid target: {target}",
            param_name="target",
            expected="one of: item, domain, task",
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

            # ADR-0007: Auto-requeue awaiting_auth jobs and reset circuit breaker
            requeued_count = 0
            if success:
                requeued_count = await _requeue_awaiting_auth_jobs(domain)
                await _reset_circuit_breaker_for_engine(domain)
        else:  # skip
            result = await queue.skip(domain=domain)
            count = result.get("skipped", 0)
            requeued_count = 0

        return {
            "ok": True,
            "target": "domain",
            "domain": domain,
            "action": action,
            "resolved_count": count,
            "requeued_count": requeued_count,  # ADR-0007
        }

    elif target == "task":
        task_id = args.get("task_id")
        if not task_id:
            raise InvalidParamsError(
                "task_id is required when target=task",
                param_name="task_id",
                expected="non-empty string",
            )

        if action == "complete":
            # Get all pending items for this task
            pending_items = await queue.get_pending(task_id=task_id)
            if not pending_items:
                return {
                    "ok": True,
                    "target": "task",
                    "task_id": task_id,
                    "action": action,
                    "resolved_count": 0,
                    "requeued_count": 0,
                }

            # Complete each item individually to capture session data per domain
            completed_count = 0
            domains_processed: set[str] = set()
            for item in pending_items:
                queue_id = item.get("id")
                domain = item.get("domain")
                if not queue_id:
                    continue

                # Capture session data only once per domain
                session_data = None
                if success and domain and domain not in domains_processed:
                    session_data = await _capture_auth_session_cookies(domain)
                    domains_processed.add(domain)

                await queue.complete(queue_id, success=success, session_data=session_data)
                completed_count += 1

            # ADR-0007: Auto-requeue awaiting_auth jobs for all affected domains
            requeued_count = 0
            if success:
                for domain in domains_processed:
                    requeued_count += await _requeue_awaiting_auth_jobs(domain)
                    await _reset_circuit_breaker_for_engine(domain)

            return {
                "ok": True,
                "target": "task",
                "task_id": task_id,
                "action": action,
                "resolved_count": completed_count,
                "requeued_count": requeued_count,
            }
        else:  # skip
            result = await queue.skip(task_id=task_id)
            count = result.get("skipped", 0)

            return {
                "ok": True,
                "target": "task",
                "task_id": task_id,
                "action": action,
                "resolved_count": count,
                "requeued_count": 0,
            }

    else:
        raise InvalidParamsError(
            f"Invalid target: {target}",
            param_name="target",
            expected="one of: item, domain, task",
        )


# ============================================================
# ADR-0007: Auto-requeue helpers for resolve_auth
# ============================================================


async def _requeue_awaiting_auth_jobs(domain: str) -> int:
    """Requeue jobs that were awaiting authentication for a domain.

    Per ADR-0007: When CAPTCHA is resolved, automatically requeue
    the associated search jobs so they are retried.

    Args:
        domain: The domain/engine that was authenticated.

    Returns:
        Number of jobs requeued.
    """
    from datetime import UTC, datetime

    db = await get_database()

    # Find and requeue awaiting_auth jobs linked to this domain
    now = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        """
        UPDATE jobs
        SET state = 'queued', queued_at = ?, error_message = NULL
        WHERE id IN (
            SELECT search_job_id FROM intervention_queue
            WHERE domain = ? AND status = 'completed' AND search_job_id IS NOT NULL
        ) AND state = 'awaiting_auth'
        """,
        (now, domain),
    )

    requeued_count = getattr(cursor, "rowcount", 0)

    if requeued_count > 0:
        logger.info(
            "Requeued awaiting_auth jobs after auth resolution",
            domain=domain,
            requeued_count=requeued_count,
        )

    return requeued_count


async def _reset_circuit_breaker_for_engine(engine: str) -> None:
    """Reset circuit breaker for an engine after auth resolution.

    Per ADR-0007: When auth is resolved, reset the circuit breaker
    so the engine becomes available immediately.

    Args:
        engine: The engine/domain to reset.
    """
    try:
        from src.search.circuit_breaker import get_circuit_breaker_manager

        manager = await get_circuit_breaker_manager()
        breaker = await manager.get_breaker(engine)
        breaker.force_close()

        logger.info(
            "Circuit breaker reset after auth resolution",
            engine=engine,
        )
    except Exception as e:
        logger.warning(
            "Failed to reset circuit breaker",
            engine=engine,
            error=str(e),
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
