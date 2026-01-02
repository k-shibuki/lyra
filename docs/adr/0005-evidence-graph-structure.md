# ADR-0005: Evidence Graph Structure

## Date
2025-11-15

## Status
Accepted

**Updates**:
- 2025-12-27: Updated to reflect current implementation in `src/filter/evidence_graph.py`
- 2024-12-31: Citation Network Integration completed (Phases 1-4) - see [Sb_CITATION_NETWORK](../Sb_CITATION_NETWORK.md)

## Context

Academic research requires integrating evidence from multiple sources to evaluate hypothesis confidence.

Traditional approaches:

| Approach | Problem |
|----------|---------|
| Flat List | Relationships between evidence unclear |
| Simple Scoring | Difficult to handle contradicting evidence |
| Manual Evaluation Only | Doesn't scale |

Required capabilities:
- Represent relationships between hypotheses and evidence
- Track both supporting and refuting evidence
- Represent citation relationships between evidence
- Automatic confidence calculation

## Decision

**Adopt an evidence graph structure with Claim as root, using Bayesian confidence calculation.**

> NOTE (2025-12-27):
> This ADR has been updated to reflect the current implementation in `src/filter/evidence_graph.py`
> and `src/storage/schema.sql`. Where this ADR previously described an alternative modeling choice,
> those items are captured as explicit "Open Issues / Gaps" instead of being left as ambiguous truth.

### Data Ownership & Scope (Global / Task-scoped Boundary)

The "Evidence Graph" in this ADR does not have `task_id` column on all persisted data. In Lyra, **task-scoped** and **global (reusable)** data coexist, and task-specific materials are assembled by **"slicing" via task_id**.

#### Basic Scope Principles

- **Task-scoped**
  - `claims` has `task_id` and represents task outputs (claim nodes).
  - A task's Evidence Graph is principally sliced **starting from claims of that task**.
- **Global / Reusable (cross-task reuse possible)**
  - `pages` has `url UNIQUE` with no `task_id`; same URL can be shared across tasks (cache/reuse design).
  - `fragments` also has no `task_id` and hangs off `page_id → pages.id`, so task-specific ownership is weak.
  - `edges` also has no `task_id`; **filter by claims** to construct task subgraph.

#### Implementation Scoping (Important)

- Evidence Graph load specifies `task_id` and reads **only edges connected to claims(task_id=...)**.
  - This allows task-specific material slicing even though `edges/pages/fragments` exist globally.

#### Rediscovery of Same Resource (Different Query/Context)

Behavior when the same paper (DOI/URL) is **rediscovered from different query or context**:

| Layer | Behavior | Reason |
|-------|----------|--------|
| `pages` | Returns existing `page_id` on subsequent finds (no insert) | UNIQUE on URL, stored once as global resource |
| `fragments` | Returns existing `fragment_id` on subsequent finds | Global resource tied to `page_id` |
| `claims` | **New creation** | Task-specific; different queries/contexts are different Claims |
| `edges` | **New creation** (Fragment → new Claim) | Same Fragment can support/refute multiple Claims |

Implementation workflow:

1. **On resource discovery**: Check DOI/URL in `resource_index`
2. **If exists**: Get and return existing `page_id` and `fragment_id`
3. **Caller**: Creates new `claims` and `edges` using retrieved `fragment_id`

This enables:
- **Storage efficiency**: Same paper data stored once
- **Context preservation**: Evaluable as query-specific Claims
- **Citation tracking**: Expressed via edges from same Fragment to multiple Claims

### Cleanup Policy (Soft / Hard)

Due to this ADR's scope design, stop/delete cleanup is safe as two stages.

#### Soft Cleanup (Safe, Default)

Purpose: Logically hide task materials **without touching data that could affect other tasks (pages/fragments, etc.)**.

- Delete/invalidate **task-scoped** items (e.g., `tasks`, `claims`, `queries`, `serp_items`, `task_metrics`, `decisions`, `jobs`, `event_log`, `intervention_queue`).
- From Evidence Graph perspective, target at minimum:
  - **claims**: `claims.task_id = ?`
  - **edges**: Those where source/target reference this task's claims
    - `edges` lacks FK protection, so edges referencing deleted claims dirty the DB if left.
    - However, claim IDs are task-specific, so deleting relevant edges rarely ripples to other tasks.

After Soft cleanup:
- `pages/fragments/edges(non-claim-referencing)` may remain in DB, but are unreachable via `task_id`-based material collection (logically invisible).

#### Hard Cleanup (Careful)

Purpose: Reclaim storage by deleting **shareable data** only when "safety conditions are met."

Hard cleanup **must compute set reachable from task_id and verify "not referenced by other tasks"** before deletion.

Recommended: Hard cleanup should be **hard(orphans_only)**.

- After Soft cleanup, additionally delete the following "orphans":
  - **orphan edges**: Edges whose source_id/target_id reference non-existent (or deleted) nodes
  - **orphan fragments**: Fragments not referenced by any edges
  - **orphan pages**: Pages not referenced by any fragments and not referenced by edges
- `pages` has file path columns (html/warc/screenshot), so page deletion should also delete corresponding files (best-effort).

Note:
- "Zero intermediate state (strong atomicity)" is impractical given async I/O + incremental persistence characteristics.

### Graph Structure

```
         Claim (Assertion/Hypothesis)
              │
    ┌─────────┼─────────┐
    │         │         │
Fragment  Fragment  Fragment
(SUPPORTS) (REFUTES) (NEUTRAL)
    │
    └── Page ── Domain (reference only; not a persisted node)
```

### Node Types

| Node | Description | Key Attributes |
|------|-------------|----------------|
| Claim | User's assertion/hypothesis | text, confidence |
| Fragment | Excerpt extracted from page | text_content, extraction_method |
| Page | Crawled web page | url, title, crawled_at |
| Domain | Domain (reference info) | domain_name |

**Implementation note**:
- `Domain` is not currently represented as a first-class node type in the persisted graph.
  Domain category is stored as edge metadata (for audit/UI) and separately in the `domains` table.

### Edge Types

| Edge | From | To | Description |
|------|------|-----|-------------|
| SUPPORTS | Fragment | Claim | Fragment supports claim |
| REFUTES | Fragment | Claim | Fragment contradicts claim |
| NEUTRAL | Fragment | Claim | Relationship unclear |
| CITES | Page | Page | Citation relationship between sources |
| EVIDENCE_SOURCE | Claim | Page | Claim is based on evidence from this page |

**Implementation note**:
- `EXTRACTED_FROM (Fragment → Page)` is represented implicitly by the relational link `fragments.page_id → pages.id`,
  not as an explicit `edges` record.
- `CITES` is persisted as `edges` rows with `source_type='page'` and `target_type='page'`.
- `EVIDENCE_SOURCE` is derived in-memory by `load_from_db()` from `fragment→claim` + `fragment.page_id` (not persisted to DB). See [Sb_CITATION_NETWORK](../Sb_CITATION_NETWORK.md).

### Confidence Calculation (Bayesian Approach)

Current implementation uses **Beta distribution updating** (conjugate prior) with an uninformative prior `Beta(1, 1)`.

- Evidence edges carry `edges.nli_edge_confidence` (NLI model output, calibrated).
- For a claim, all incoming evidence edges of type `supports/refutes/neutral` are collected.
- Only `supports/refutes` update the posterior; `neutral` is treated as "no information".

Implementation-equivalent formulation:

```text
Prior: Beta(α=1, β=1)

α = 1 + Σ nli_edge_confidence(e) for e in SUPPORTS edges
β = 1 + Σ nli_edge_confidence(e) for e in REFUTES edges

bayesian_claim_confidence  = α / (α + β)                       # posterior mean
uncertainty = sqrt( (αβ) / ((α+β)^2 (α+β+1)) )   # posterior stddev
controversy = min(α-1, β-1) / (α+β-2)            # conflict degree (0 when no evidence)
```

**Important semantics**:
- `edges.nli_edge_confidence` is treated as *evidence weight* (calibrated probability from NLI model).
- Legacy `edges.confidence` column has been **removed** as of PR #50 (terminology unification).
- `claims.llm_claim_confidence` stores LLM's self-reported extraction quality (NOT used in Bayesian update).

### Domain Category (Reference Only)

**Important**: Domain categories are reference information and are **NOT used** in confidence calculation.

Reasons:
- Article quality varies within the same domain
- Domain-based weighting introduces bias
- Fragment-level evaluation is essential

**Principle**: Confidence calculation uses only Fragment-level features, not domain-based weighting, to avoid bias.

## Consequences

### Positive
- **Transparency**: Traceable why a confidence level was assigned
- **Contradiction Visibility**: Support and refutation displayed in parallel
- **Extensibility**: New edge types can be added
- **Citation Tracking**: Academic paper citation relationships expressible

### Negative
- **Computation Cost**: Graph traversal required
- **Complexity**: More difficult to understand than simple list
- **Maintenance**: Graph consistency maintenance required

## Alternatives Considered

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| Flat List | Simple | Cannot express relationships | Rejected |
| Knowledge Graph (RDF) | Standardized | Overly complex | Rejected |
| Vector DB Only | Fast similarity search | Weak relationships | Supplementary adoption |
| Score Only | Lightweight | Opaque rationale | Rejected |

## Implementation Notes

### Citation Network Integration (2024-12-31)

Full citation network support was added in [Sb_CITATION_NETWORK](../Sb_CITATION_NETWORK.md):

| Feature | Implementation |
|---------|---------------|
| `EVIDENCE_SOURCE` edge | Derived in-memory from `fragment→claim` + `fragment.page_id` |
| `CITES` edge loading | `load_from_db(task_id)` includes page→page edges reachable from task's claims |
| MCP API | `query_sql` tool for SQL queries, `vector_search` for semantic search (per ADR-0017) |
| Graph analysis | `calculate_pagerank()`, `calculate_betweenness_centrality()`, `get_citation_hub_pages()` |

This enables full graph traversal from Claim → Page → Cited Pages via NetworkX.

## References
- `src/storage/schema.sql` - Graph schema (edges, claims, fragments tables)
- `src/filter/evidence_graph.py` - Evidence graph implementation (NetworkX + SQLite)
- `docs/archive/Rc_CONFIDENCE_CALIBRATION_DESIGN.md` - Confidence/Calibration design (completed)
- `docs/Sb_CITATION_NETWORK.md` - Citation network integration proposal (Phase Sb)