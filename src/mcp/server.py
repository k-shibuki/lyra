"""
MCP Server implementation for Lyra.
Provides tools for research operations that can be called by Cursor/LLM.

Provides MCP tools per ADR-0010 async architecture:
- queue_targets: Unified query + URL queueing
- get_status: Long polling with wait parameter
- stop_task: Task stopping (default scope=all_jobs)
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
from src.mcp.tools import (
    auth,
    calibration,
    feedback,
    reference_candidates,
    sql,
    targets,
    task,
    vector,
    view,
)

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

TYPICAL FLOW (high level):
create_task → queue_targets → get_status(wait=180) → (vector_search / query_view / query_sql) → stop_task

WORKFLOW: This is the first step. After creating a task, use queue_targets to add search queries or URLs.
The same task_id accumulates data across multiple targets - design queries iteratively based on results.

STRATEGY: Start with broad queries, then refine based on get_status metrics. Include both supporting
and refuting queries to ensure balanced evidence collection. Use v_reference_candidates view to find
citation chase candidates and queue them as URL targets.""",
        inputSchema={
            "type": "object",
            "properties": {
                "hypothesis": {
                    "type": "string",
                    "description": "Central hypothesis to verify (ADR-0017). A falsifiable claim that guides the entire exploration. Search queries are designed to find evidence supporting or refuting this hypothesis.",
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
            "required": ["hypothesis"],
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

POLLING STRATEGY: Use wait=180 (default) for efficient long-polling during active exploration.
Use wait=0 for immediate status checks when making decisions.

MILESTONES (AI decision flags):
- milestones.citation_candidates_stable: true when v_reference_candidates won't change
  (target_queue + citation_graph drained, no pending auth). Safe to query for Citation Chasing.
- milestones.nli_results_stable: true when NLI verification jobs have drained.
  Bayesian confidence scores are finalized.
- milestones.blockers: List of reasons why citation_candidates_stable is false
  (e.g., ["target_queue", "citation_graph", "pending_auth"])

METRICS TO MONITOR:
- searches[].satisfaction_score: 0.0-1.0, source coverage metric
    Formula: min(1.0, (independent_sources / 3) * 0.7 + (has_primary_source ? 0.3 : 0))
    >= 0.8 means "satisfied" (sufficient independent sources + authoritative source found)
    Note: "primary_source" = authoritative domains (gov/academic/official)
- searches[].harvest_rate: Useful fragments per page fetched (can exceed 1.0)
- metrics.total_claims: Growing count indicates productive exploration
- budget.remaining_percent: Stop or adjust strategy when low

DECISION POINTS:
- If milestones.citation_candidates_stable: Safe to query v_reference_candidates for Citation Chasing
- If satisfaction_score < 0.5: Query needs more diverse sources or authoritative source
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
                    "description": "Long-polling: seconds to wait for changes before returning. 0=immediate, 180=default for monitoring.",
                    "default": 180,
                    "minimum": 0,
                    "maximum": 300,
                },
                "detail": {
                    "type": "string",
                    "enum": ["summary", "full"],
                    "default": "summary",
                    "description": "Response detail level. 'summary' for progress overview, 'full' for queue_items, pending_auth_detail, blocked_domains, etc.",
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
        name="queue_targets",
        title="Queue Targets",
        description="""Queue multiple targets (queries or URLs) for parallel background execution. Returns immediately.

UNIFIED API: This tool handles both search queries and direct URL ingestion (citation chasing).
Use kind='query' for search queries, kind='url' for direct URL fetch, kind='doi' for DOI fast path.

DUPLICATE HANDLING: Safe to queue overlapping targets - duplicates are auto-detected and skipped.
Same URL/DOI content is cached and reused across targets, maximizing coverage without waste.

EXPLORATION STRATEGY:
1. Start with 3-5 diverse queries covering different angles of the research question
2. Check results with get_status(wait=180) to monitor progress
3. Use query_view(v_reference_candidates) to find unfetched citations
4. Queue promising citations as URL targets for citation chasing
5. IMPORTANT: Include refutation queries (e.g., "X criticism", "X limitations", "against X")

QUERY TARGETS (kind='query'):
- Use academic terms and paper titles when known
- Try both English and target language queries
- Include author names for known experts
- Add "site:arxiv.org" or domain hints for academic sources

URL TARGETS (kind='url'):
- Use for citation chasing (reason='citation_chase')
- Or manual URL ingestion (reason='manual')
- Set depth to track citation chain depth (0 = direct, 1+ = chased)

DOI TARGETS (kind='doi'):
- Use for Academic API fast path (abstract-only ingestion without web fetch)
- Prioritizes Semantic Scholar, falls back to OpenAlex, then URL fetch
- Set depth to track citation chain depth (0 = direct, 1+ = chased)""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to add targets to",
                },
                "targets": {
                    "type": "array",
                    "description": "Targets to queue. Each is either a query or URL target.",
                    "minItems": 1,
                    "items": {
                        "oneOf": [
                            {
                                "type": "object",
                                "description": "Query target for search execution",
                                "properties": {
                                    "kind": {"type": "string", "const": "query"},
                                    "query": {
                                        "type": "string",
                                        "description": "Search query string",
                                    },
                                    "options": {
                                        "type": "object",
                                        "description": "Query-specific options (override batch options)",
                                    },
                                },
                                "required": ["kind", "query"],
                            },
                            {
                                "type": "object",
                                "description": "URL target for direct ingestion",
                                "properties": {
                                    "kind": {"type": "string", "const": "url"},
                                    "url": {
                                        "type": "string",
                                        "description": "URL to fetch and process",
                                    },
                                    "depth": {
                                        "type": "integer",
                                        "default": 0,
                                        "description": "Citation chain depth (0=direct, 1+=chased)",
                                    },
                                    "reason": {
                                        "type": "string",
                                        "enum": ["citation_chase", "manual"],
                                        "default": "manual",
                                        "description": "Why this URL is being ingested",
                                    },
                                    "context": {
                                        "type": "object",
                                        "description": "Optional context (referer, citation_context, etc.)",
                                    },
                                    "policy": {
                                        "type": "object",
                                        "description": "Optional fetch policy overrides",
                                    },
                                },
                                "required": ["kind", "url"],
                            },
                            {
                                "type": "object",
                                "description": "DOI target for Academic API fast path",
                                "properties": {
                                    "kind": {"type": "string", "const": "doi"},
                                    "doi": {
                                        "type": "string",
                                        "description": "DOI to fetch (e.g., 10.xxxx/yyyy)",
                                    },
                                    "depth": {
                                        "type": "integer",
                                        "default": 0,
                                        "description": "Citation chain depth (0=direct, 1+=chased)",
                                    },
                                    "reason": {
                                        "type": "string",
                                        "enum": ["citation_chase", "manual"],
                                        "default": "manual",
                                        "description": "Why this DOI is being ingested",
                                    },
                                    "context": {
                                        "type": "object",
                                        "description": "Optional context (source_page_id, citation_context, etc.)",
                                    },
                                    "policy": {
                                        "type": "object",
                                        "description": "Optional fetch policy overrides",
                                    },
                                },
                                "required": ["kind", "doi"],
                            },
                        ],
                    },
                },
                "options": {
                    "type": "object",
                    "description": "Options applied to all targets in this batch",
                    "properties": {
                        "serp_engines": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "SERP engines for query targets. Omit for auto-selection.",
                        },
                        "academic_apis": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Academic APIs for query targets. Omit for default (both).",
                        },
                        "budget_pages": {
                            "type": "integer",
                            "description": "Max pages per target. Leave unset to use task default.",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "default": "medium",
                            "description": "Scheduling priority. Use 'high' for critical targets, 'low' for exploratory.",
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["task_id", "targets"],
        },
        outputSchema=_load_schema("queue_targets"),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="stop_task",
        title="Stop Research Task",
        description="""Pause a research task session. Cancels pending targets and prepares materials.

IMPORTANT: Tasks are always RESUMABLE. After stopping, you can call queue_targets with the
same task_id to continue exploration in a new session.

WHEN TO STOP:
- budget.remaining_percent approaching 0
- Key queries have satisfaction_score >= 0.8 (satisfied: sufficient sources + primary found)
- Sufficient claims collected (check metrics.total_claims)
- Time constraints require wrapping up

SCOPE (ADR-0015):
- all_jobs (default): Cancel ALL job kinds for this task (target_queue, verify_nli, citation_graph, etc.).
  This is the recommended default to ensure "stop means stop".
- target_queue_only: Only cancel target_queue jobs. VERIFY_NLI and CITATION_GRAPH jobs
  are allowed to complete. Use when you want background processing to finish.

MODES:
- graceful: Cancel queued targets, wait for running targets to complete (up to 30s timeout), then finalize.
- immediate: Cancel all targets (queued + running) immediately, then finalize. Use when budget exhausted.
- full: Cancel all targets AND wait for ML/NLI operations to fully drain. Use for complete shutdown.

DB IMPACT (on stop):
- tasks.status → 'paused' (resumable)
- jobs.state → 'cancelled' for queued jobs (within scope, all modes) and running jobs (immediate/full modes)
- intervention_queue.status → 'cancelled' for pending auth items
- Claims/fragments persisted during the task remain in DB for query_sql/vector_search.
- With scope=target_queue_only: verify_nli and citation_graph jobs continue running and complete.

AFTER STOPPING: Use query_sql and vector_search tools to explore collected evidence.
To continue exploration, call queue_targets with the same task_id.""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to stop",
                },
                "reason": {
                    "type": "string",
                    "enum": ["session_completed", "budget_exhausted", "user_cancelled"],
                    "default": "session_completed",
                    "description": "Why the session is stopping. session_completed=normal pause, budget_exhausted=out of budget, user_cancelled=explicit cancel.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["graceful", "immediate", "full"],
                    "default": "graceful",
                    "description": "graceful=wait for running, immediate=cancel all, full=cancel all + drain ML",
                },
                "scope": {
                    "type": "string",
                    "enum": ["target_queue_only", "all_jobs"],
                    "default": "all_jobs",
                    "description": "all_jobs=cancel all job kinds, target_queue_only=only cancel target jobs (verify_nli/citation_graph complete)",
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
    Tool(
        name="queue_reference_candidates",
        title="Queue Reference Candidates",
        description="""Queue citation chase candidates from v_reference_candidates view with explicit control.

CITATION CHASING: After initial search, key references may be found in page citations.
This tool queries v_reference_candidates (pages cited but not yet processed for this task)
and enqueues selected candidates for fetching.

PREREQUISITE: Check get_status().milestones.citation_candidates_stable == true before using.
If blockers exist (target_queue, citation_graph, pending_auth), wait for them to clear first.

EXPLICIT CONTROL (UX):
- include_ids: Whitelist mode - only queue these specific candidates
- exclude_ids: Blacklist mode - queue all EXCEPT these candidates
- If neither: Queue top candidates up to limit (sorted by view's ORDER BY)

DOI OPTIMIZATION:
- If candidate URL contains a DOI (doi.org/10.xxxx/...), uses kind='doi' for Academic API fast path
- Academic API provides abstract-only ingestion without web fetch (faster, more reliable)
- Otherwise falls back to kind='url' for web fetch

DRY RUN: Set dry_run=true to preview candidates without queueing.

WORKFLOW:
1. get_status(wait=0) → check milestones.citation_candidates_stable
2. query_view(v_reference_candidates, task_id=...) to see all candidates
3. Review and decide which to include/exclude
4. queue_reference_candidates(include_ids=[...]) or queue_reference_candidates(exclude_ids=[...])
5. get_status(wait=180) to monitor progress
6. Repeat if new candidates appear""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID",
                },
                "include_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Citation edge IDs to include (whitelist mode). Mutually exclusive with exclude_ids.",
                },
                "exclude_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Citation edge IDs to exclude (blacklist mode). Mutually exclusive with include_ids.",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum candidates to enqueue (default: 10)",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, return candidates without enqueuing",
                },
                "options": {
                    "type": "object",
                    "description": "Queue options",
                    "properties": {
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "default": "medium",
                            "description": "Scheduling priority",
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["task_id"],
        },
        outputSchema=_load_schema("queue_reference_candidates"),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    # ============================================================
    # 3. Calibration (2 tools)
    # ============================================================
    Tool(
        name="calibration_metrics",
        title="Calibration Metrics",
        description="""View NLI model calibration statistics and evaluation history. (ADMIN TOOL)

ACTIONS:
- get_stats: Current calibration parameters and Brier scores per source model
- get_evaluations: Historical evaluation records for trend analysis

Most research workflows do NOT need this tool unless you are actively diagnosing NLI quality.

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
        description="""Rollback NLI calibration parameters to a previous version. DESTRUCTIVE operation. (ADMIN TOOL)

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
        name="query_sql",
        title="Execute SQL Query",
        description="""Execute read-only SQL against the Evidence Graph database.

This tool is intended for incremental graph exploration without context overflow.

CHOOSING TOOLS:
- Use list_views + query_view for common analysis queries (predefined, safe templates).
- Use vector_search first if you need to discover relevant IDs by meaning.
- Use query_sql for custom/ad-hoc queries not covered by templates.

SCHEMA HINTS (task_id column availability):
- claims: HAS task_id (primary task-scoped table)
- queries: HAS task_id
- pages: NO task_id (URL-based deduplication, global scope)
- fragments: NO task_id (linked via page_id → pages)
- edges: NO task_id (use JOINs with claims for task filtering)

KEY COLUMNS (commonly used):
- claims: id, task_id, claim_text, claim_type, granularity, llm_claim_confidence
- fragments: id, page_id, text_content, heading_context, fragment_type, position
- pages: id, url, title, domain, page_type, fetched_at, canonical_id (FK to works)
- works: canonical_id, title, year, venue, doi, source_api (normalized bibliographic data)
- work_authors: canonical_id, position, name, affiliation, orcid (authors by position)
- work_identifiers: canonical_id, provider, provider_paper_id (paper_id → canonical_id lookup)
- edges: id, source_type, source_id, target_type, target_id, relation, nli_edge_confidence

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
                    "description": "Read-only SQL query (single statement). Do NOT include LIMIT clause - use options.limit instead. Example: SELECT * FROM claims WHERE task_id = '...'",
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
        outputSchema=_load_schema("query_sql"),
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

Use this before query_sql when you don't know which IDs/tables to look at.

NOTE: If there are zero embeddings for the given target/task, this returns ok=false (hard error).""",
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
    Tool(
        name="query_view",
        title="Execute SQL View Template",
        description="""Execute a predefined SQL view template.

Use list_views first to see available templates. Views are predefined analysis queries
for common evidence graph exploration patterns.

AVAILABLE VIEWS:
- v_claim_evidence_summary: Per-claim support/refute counts
- v_contradictions: Claims with conflicting evidence
- v_unsupported_claims: Claims without support
- v_evidence_chain: Full evidence chain to sources
- v_citation_flow: Citation relationships
- v_evidence_timeline: Evidence by publication year
- v_emerging_consensus: Claims gaining recent support
- v_outdated_evidence: Older evidence needing review
- v_reference_candidates: Unfetched citations for Citation Chasing (requires task_id)
  IMPORTANT: Check get_status().milestones.citation_candidates_stable before querying.
  Results may change while target_queue or citation_graph jobs are running.

Use query_sql for custom queries not covered by templates.""",
        inputSchema={
            "type": "object",
            "properties": {
                "view_name": {
                    "type": "string",
                    "description": "View template name (e.g., v_contradictions). Use list_views to see available views.",
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID for scoping (required for most views)",
                },
                "params": {
                    "type": "object",
                    "description": "Additional template parameters (view-specific)",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "maximum": 200,
                    "description": "Maximum rows to return",
                },
            },
            "required": ["view_name"],
        },
        outputSchema=_load_schema("query_view"),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="list_views",
        title="List SQL View Templates",
        description="""List all available SQL view templates for evidence graph analysis.

Returns view names and descriptions. Use query_view to execute a template.""",
        inputSchema={
            "type": "object",
            "properties": {},
        },
        outputSchema=_load_schema("list_views"),
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

QUICK GUIDE:
- Use edge_correct when an evidence relation label is wrong (most common).
- Use claim_reject/claim_restore when an extracted claim is invalid/irrelevant.
- Use domain_* only when a whole source domain should be blocked/unblocked.

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
1. Get edge_id from query_sql or vector_search results
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
                    "description": "For claim_reject/claim_restore. Get from query_sql results (claims table)",
                },
                "edge_id": {
                    "type": "string",
                    "description": "For edge_correct. Get from query_sql results (edges table)",
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
        # Research Execution (unified target queue)
        "queue_targets": targets.handle_queue_targets,
        "stop_task": task.handle_stop_task,
        "queue_reference_candidates": reference_candidates.handle_queue_reference_candidates,
        # Calibration (ADR-0012: renamed from calibrate/calibrate_rollback)
        "calibration_metrics": calibration.handle_calibration_metrics,
        "calibration_rollback": calibration.handle_calibration_rollback,
        # Evidence Graph Exploration
        "query_sql": sql.handle_query_sql,
        "vector_search": vector.handle_vector_search,
        "query_view": view.handle_query_view,
        "list_views": view.handle_list_views,
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

    # Start job scheduler (ADR-0010: unified job execution via JobScheduler)
    from src.scheduler.jobs import get_scheduler

    scheduler = await get_scheduler()

    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )
    finally:
        # Stop job scheduler
        await scheduler.stop()
        await close_database()
        logger.info("Lyra MCP server stopped")


def main() -> None:
    """Main entry point."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
