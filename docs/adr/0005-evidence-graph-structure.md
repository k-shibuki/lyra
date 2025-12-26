# ADR-0005: Evidence Graph Structure

## Date
2025-11-15

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
    └── Page ── Domain
```

### Node Types

| Node | Description | Key Attributes |
|------|-------------|----------------|
| Claim | User's assertion/hypothesis | text, confidence |
| Fragment | Excerpt extracted from page | text_content, extraction_method |
| Page | Crawled web page | url, title, crawled_at |
| Domain | Domain (reference info) | domain_name |

### Edge Types

| Edge | From | To | Description |
|------|------|-----|-------------|
| SUPPORTS | Fragment | Claim | Fragment supports claim |
| REFUTES | Fragment | Claim | Fragment contradicts claim |
| NEUTRAL | Fragment | Claim | Relationship unclear |
| EXTRACTED_FROM | Fragment | Page | Source of extraction |
| CITES | Fragment | Fragment | Citation relationship |

### Confidence Calculation (Bayesian Approach)

```python
def calculate_confidence(claim: Claim) -> float:
    """
    Calculate Claim confidence

    P(H|E) ∝ P(E|H) × P(H)
    - P(H): Prior probability (default 0.5)
    - P(E|H): Likelihood (depends on evidence quality and quantity)
    """
    supports = get_edges(claim, "SUPPORTS")
    refutes = get_edges(claim, "REFUTES")

    support_weight = sum(
        edge.source.reliability_score * edge.nli_confidence
        for edge in supports
    )
    refute_weight = sum(
        edge.source.reliability_score * edge.nli_confidence
        for edge in refutes
    )

    # Normalize to 0-1 with logistic function
    log_odds = support_weight - refute_weight
    confidence = 1 / (1 + exp(-log_odds))

    return confidence
```

### Domain Category (Reference Only)

**Important**: Domain categories are reference information and are **NOT used** in confidence calculation.

Reasons:
- Article quality varies within the same domain
- Domain-based weighting introduces bias
- Fragment-level evaluation is essential

```python
# Domain categories (for reference display)
DOMAIN_CATEGORIES = {
    "academic": ["arxiv.org", "nature.com", ...],
    "news": ["reuters.com", "nytimes.com", ...],
    "government": [".gov", ".go.jp", ...],
}

# Confidence calculation does NOT reference domain
def calculate_reliability(fragment: Fragment) -> float:
    # ❌ domain_weight = DOMAIN_WEIGHTS[fragment.page.domain.category]
    # ✓ Use only Fragment's own features
    return compute_from_fragment_features(fragment)
```

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

## References
- `src/storage/schema.sql` - Graph schema (edges, claims, fragments tables)
- `src/filter/evidence_graph.py` - Evidence graph implementation (NetworkX + SQLite)
