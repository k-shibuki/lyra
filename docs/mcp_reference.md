# MCP Tools Reference

Lyra exposes 13 tools via MCP (Model Context Protocol).

**Schema locations:**
- Input schemas: `src/mcp/server.py` (`TOOLS` array)
- Output schemas: `src/mcp/schemas/*.json`

## Typical Workflow

```
create_task → queue_searches → get_status(wait=30) → vector_search/query_view → stop_task
```

### Job Chaining (Automatic)

When `search_queue` jobs complete, Lyra automatically enqueues follow-up jobs:

```
search_queue (completed)
    ├──► VERIFY_NLI (cross-source NLI verification)
    └──► CITATION_GRAPH (academic citation expansion)
```

These jobs run in the background and update `bayesian_truth_confidence` in the evidence graph.

## Tools

### Task Management

| Tool | Description |
|------|-------------|
| `create_task` | Create research task with query and optional config (budget, priority_domains) |
| `get_status` | Get task progress; supports long-polling via `wait` parameter |
| `stop_task` | Pause task session (graceful/immediate/full modes, scope parameter) |

#### get_status Response

Key fields in the response:

| Field | Description |
|-------|-------------|
| `status` | Task status: `created`, `exploring`, `paused`, `failed` |
| `searches` | Per-search progress (satisfaction_score, harvest_rate) |
| `metrics` | Totals: total_searches, total_pages, total_fragments, total_claims |
| `jobs` | Job summary by kind (search_queue, verify_nli, citation_graph) |
| `budget` | Budget usage and remaining percent |

#### stop_task Parameters

| Parameter | Values | Description |
|-----------|--------|-------------|
| `reason` | `session_completed` (default), `budget_exhausted`, `user_cancelled` | Why stopping |
| `mode` | `graceful` (default), `immediate`, `full` | How to stop running jobs |
| `scope` | `search_queue_only` (default), `all_jobs` | Which job kinds to cancel |

**Task Resumability**: After `stop_task`, task status becomes `paused` (not deleted). Call `queue_searches` with the same `task_id` to resume.

### Search

| Tool | Description |
|------|-------------|
| `queue_searches` | Queue multiple queries for parallel background execution |

### Evidence Exploration

| Tool | Description |
|------|-------------|
| `query_sql` | Execute read-only SQL against Evidence Graph |
| `vector_search` | Semantic similarity search over fragments/claims |
| `query_view` | Execute predefined SQL view template (18 views available) |
| `list_views` | List available view templates |

#### Key Views

| View | Description |
|------|-------------|
| `v_claim_evidence_summary` | Per-claim support/refute counts and bayesian_truth_confidence |
| `v_claim_origins` | Claim provenance (which fragment/page each claim was extracted from) |
| `v_contradictions` | Claims with conflicting evidence |
| `v_evidence_chain` | Full evidence chain from claims through fragments to sources |

### Authentication

| Tool | Description |
|------|-------------|
| `get_auth_queue` | Get pending CAPTCHA/auth items |
| `resolve_auth` | Mark auth items as solved/skipped; triggers retry |

### Feedback

| Tool | Description |
|------|-------------|
| `feedback` | Human corrections: `edge_correct`, `claim_reject/restore`, `domain_block/unblock` |

### Calibration

| Tool | Description |
|------|-------------|
| `calibration_metrics` | View NLI calibration stats (admin) |
| `calibration_rollback` | Rollback calibration to previous version (admin) |

## Related Documentation

- [Architecture Overview](architecture.md)
- [ADR-0002: Thinking-Working Separation](adr/0002-thinking-working-separation.md)
- [ADR-0005: Evidence Graph Structure](adr/0005-evidence-graph-structure.md) - Bayesian confidence, edge types
- [ADR-0010: Async Search Queue](adr/0010-async-search-queue.md) - Job chaining, stop_task scope
- [ADR-0012: Feedback Tool Design](adr/0012-feedback-tool-design.md)
- [ADR-0016: Unified Search Sources](adr/0016-unified-search-sources.md) - Web fetch priority, citation graph