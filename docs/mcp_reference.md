# MCP Tools Reference

Lyra exposes 14 tools via MCP (Model Context Protocol).

**Schema locations:**
- Input schemas: `src/mcp/server.py` (`TOOLS` array)
- Output schemas: `src/mcp/schemas/*.json`

## Typical Workflow

```
create_task → queue_targets → get_status(wait=180) → vector_search/query_view → stop_task
```

### Job Chaining (Automatic)

When `target_queue` jobs complete, Lyra automatically enqueues follow-up jobs:

```
target_queue (completed)
    ├──► VERIFY_NLI (cross-source NLI verification)
    └──► CITATION_GRAPH (academic citation expansion)
```

These jobs run in the background and update `bayesian_truth_confidence` in the evidence graph.

## Tools

### Task Management

| Tool | Description |
|------|-------------|
| `create_task` | Create research task with central hypothesis (ADR-0017) and optional config (budget, priority_domains) |
| `get_status` | Get task progress; supports long-polling via `wait` parameter |
| `stop_task` | Pause task session (graceful/immediate/full modes, scope parameter) |

#### get_status Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `task_id` | string | (required) | Task ID to check status for |
| `wait` | integer | 180 | Long-polling: seconds to wait for changes (0=immediate) |
| `detail` | string | "summary" | Response detail level: `summary` or `full` |

#### get_status Response

Key fields in the response:

| Field | Description |
|-------|-------------|
| `status` | Task status: `created`, `exploring`, `paused`, `failed` |
| `progress.searches` | Search progress (satisfied/running/total) |
| `progress.jobs_by_phase` | Jobs grouped by phase: `exploration` (target_queue), `verification` (verify_nli), `citation` (citation_graph) |
| `metrics` | Totals: total_pages, total_fragments, total_claims, elapsed_seconds |
| `budget` | Budget usage and remaining percent |
| `milestones` | Action-readiness flags: `target_queue_drained`, `nli_verification_done`, `citation_chase_ready` |
| `waiting_for` | Detailed list of what's blocking progress (kind, status, queued/running counts) |

**Milestones semantics:**

| Flag | Meaning | Next Action |
|------|---------|-------------|
| `target_queue_drained: true` | All target_queue jobs done | Can stop get_status wait loop |
| `nli_verification_done: true` | NLI verification complete | Can query_view(v_claim_evidence_summary) |
| `citation_chase_ready: true` | Citation graph stable | Can queue_reference_candidates |

**waiting_for structure:**

```json
"waiting_for": [
  {"kind": "target_queue", "status": "running", "queued": 0, "running": 2, "completed": 1},
  {"kind": "verify_nli", "status": "not_enqueued", "queued": 0, "running": 0, "completed": 0}
]
```

Status values: `not_enqueued`, `queued`, `running`, `drained`, `pending` (for auth)

#### stop_task Parameters

| Parameter | Values | Description |
|-----------|--------|-------------|
| `reason` | `session_completed` (default), `budget_exhausted`, `user_cancelled` | Why stopping |
| `mode` | `graceful` (default), `immediate`, `full` | How to stop running jobs |
| `scope` | `all_jobs` (default), `target_queue_only` | Which job kinds to cancel |

**Task Resumability**: After `stop_task`, task status becomes `paused` (not deleted). Call `queue_targets` with the same `task_id` to resume.

### Target Queue

| Tool | Description |
|------|-------------|
| `queue_targets` | Queue targets (query/url/doi) for parallel execution. Supports `kind='query'` (search), `kind='url'` (direct fetch), `kind='doi'` (Academic API fast path). |
| `queue_reference_candidates` | Queue citation candidates from `v_reference_candidates` view. Supports whitelist (`include_ids`) or blacklist (`exclude_ids`) mode. Auto-extracts DOI from URLs for fast path. |

#### queue_reference_candidates Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `task_id` | string | (required) | Task ID to queue candidates for |
| `include_ids` | string[] | - | Citation edge IDs to include (whitelist mode). Mutually exclusive with `exclude_ids`. |
| `exclude_ids` | string[] | - | Citation edge IDs to exclude (blacklist mode). Mutually exclusive with `include_ids`. |
| `limit` | integer | 10 | Maximum candidates to enqueue |
| `dry_run` | boolean | false | If true, return candidates without enqueuing |
| `options.priority` | string | "medium" | Scheduling priority: `high`, `medium`, `low` |

**Prerequisites**: Check `get_status().milestones.citation_chase_ready == true` before using.

**Workflow**:
1. `get_status(wait=0)` → check `milestones.citation_chase_ready`
2. `query_view(v_reference_candidates, task_id=...)` to see all candidates
3. Review and decide which to include/exclude
4. `queue_reference_candidates(include_ids=[...])` or `queue_reference_candidates(exclude_ids=[...])`
5. `get_status(wait=180)` to monitor progress

**DOI Optimization**: URLs containing DOI (e.g., `doi.org/10.xxxx/...`) are automatically routed to Academic API for abstract-only ingestion.

### Evidence Exploration

| Tool | Description |
|------|-------------|
| `query_sql` | Execute read-only SQL against Evidence Graph |
| `vector_search` | Semantic similarity search over fragments/claims |
| `query_view` | Execute predefined SQL view template (20 views available) |
| `list_views` | List available view templates |

#### Key Views (20 available, use `list_views` for full list)

**Claim Analysis:**
| View | Description |
|------|-------------|
| `v_claim_evidence_summary` | Per-claim support/refute counts and bayesian_truth_confidence |
| `v_claim_origins` | Claim provenance with bibliographic metadata (`author_display`, `work_year`, `work_venue`, `work_doi` for academic sources) |
| `v_contradictions` | Claims with conflicting evidence |
| `v_unsupported_claims` | Claims without supporting evidence |

**Evidence Chain:**
| View | Description |
|------|-------------|
| `v_evidence_chain` | Full evidence chain from claims through fragments to sources (includes `author_display`, `work_year`, `work_venue`, `work_doi` for academic sources) |
| `v_evidence_timeline` | Evidence organized by publication year |
| `v_evidence_freshness` | Age of supporting evidence |

**Source Evaluation:**
| View | Description |
|------|-------------|
| `v_source_impact` | Ranks sources by knowledge generation + corroboration (recommended for Key Sources) |
| `v_source_authority` | Ranks by NLI support edges (use `v_source_impact` instead for Key Sources) |

**Citation Graph:**
| View | Description |
|------|-------------|
| `v_reference_candidates` | Unfetched citation candidates for Citation Chasing (requires `task_id`) |
| `v_citation_flow` | Citation relationships between pages |
| `v_bibliographic_coupling` | Papers sharing common references |

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

- [Architecture Overview](architecture.md) - Full ADR index with categories
- [ADR-0002: Three-Layer Collaboration Model](adr/0002-three-layer-collaboration-model.md) - Three-layer collaboration
- [ADR-0005: Evidence Graph Structure](adr/0005-evidence-graph-structure.md) - Bayesian confidence, edge types
- [ADR-0007: Human-in-the-Loop Authentication](adr/0007-human-in-the-loop-auth.md) - CAPTCHA handling, auth queue
- [ADR-0010: Async Target Queue Architecture](adr/0010-async-search-queue.md) - Job chaining, stop_task scope
- [ADR-0012: Feedback Tool Design](adr/0012-feedback-tool-design.md) - 3 levels, 6 actions
- [ADR-0015: Unified Search Sources](adr/0015-unified-search-sources.md) - Web fetch priority, citation graph
- [ADR-0016: Ranking Simplification](adr/0016-ranking-simplification.md) - Evidence Graph exploration interface
- [ADR-0017: Task Hypothesis-First Architecture](adr/0017-task-hypothesis-first.md) - Hypothesis-driven exploration