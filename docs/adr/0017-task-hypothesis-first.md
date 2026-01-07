# ADR-0017: Task Hypothesis-First Architecture

## Date
2026-01-05

## Context

Lyra's `create_task` MCP tool previously accepted a `query` parameter that served dual purposes:
1. A "research question" to guide exploration
2. A "hypothesis" to verify through evidence

This conceptual ambiguity led to:
- Confusion about the relationship between task creation and search query design
- Terminology collision between task-level `query` and search-level `query_text`
- Unclear semantics for NLI's `hypothesis` parameter (which operates on claims, not tasks)

### Problem Summary

| Issue | Impact |
|-------|--------|
| Task `query` vs search `query_text` confusion | Unclear data flow in documentation and code |
| NLI `hypothesis` collides with task concept | Same term with different meanings |
| Implicit "what to verify" semantics | LLM extraction context was not explicit |

## Decision

**Adopt a "hypothesis-first" model where each task explicitly defines a central hypothesis to verify.**

### Breaking Changes (No Backward Compatibility)

1. **MCP `create_task` Input**: `query` parameter renamed to `hypothesis` (required)
2. **MCP Response Fields**: `query` → `hypothesis` in `create_task` and `get_status` responses
3. **Database Schema**: `tasks.query` column → `tasks.hypothesis`
4. **NLI API**: `hypothesis` field → `nli_hypothesis` in ML server API and `nli_corrections` table

### Terminology Standardization

| Term | Definition | Location |
|------|------------|----------|
| `task_hypothesis` | Central claim the task aims to verify (natural language) | `tasks.hypothesis` (DB), MCP tools |
| `query_text` | Search string submitted to search engines | `queries.query_text` (DB), `queue_searches` |
| `nli_hypothesis` | Hypothesis in NLI judgment (= `claim_text`) | ML server API, `nli_corrections` |

### Conceptual Model

```mermaid
flowchart TD
    CreateTask["create_task(hypothesis)"]
    QueueSearches["queue_searches(task_id, queries)"]
    SearchQueue[(search_queue_jobs)]
    Pages[(pages)]
    ExtractClaims["LLM extract_claims"]
    Claims[(claims)]
    CitationGraph[CITATION_GRAPH job]
    VerifyNli[VERIFY_NLI job]
    NliJudge["NLI judge"]
    Edges[(edges)]
    VectorSearch["vector_search"]
    QueryView["query_view / query_sql"]

    CreateTask -->|"returns task_id"| QueueSearches
    QueueSearches --> SearchQueue
    SearchQueue --> Pages
    SearchQueue --> ExtractClaims
    Pages -->|"academic papers"| CitationGraph
    CitationGraph -->|"CITES"| Edges
    ExtractClaims -->|"context: task.hypothesis"| Claims
    Claims -->|"triggers"| VerifyNli
    VerifyNli -->|"premise: fragment.text<br/>nli_hypothesis: claim.claim_text"| NliJudge
    NliJudge -->|"supports/refutes/neutral"| Edges
    Edges --> VectorSearch
    Claims --> VectorSearch
    VectorSearch --> QueryView
```

### Usage Flow

1. **Task Creation**: `create_task(hypothesis="DPP-4 inhibitors improve HbA1c in diabetics")`
2. **Query Design**: MCP client designs search queries to find supporting/refuting evidence
3. **Search Execution**: `queue_searches(task_id, queries=["DPP-4 inhibitors meta-analysis", ...])`
4. **Claim Extraction**: LLM extracts claims using `task_hypothesis` as context (focus)
5. **Citation Graph**: Academic papers trigger `CITATION_GRAPH` job to build CITES edges
6. **NLI Verification**: `premise=fragment.text`, `nli_hypothesis=claim.claim_text`
7. **Evidence Exploration**: `vector_search(query="...", task_id=task_id)` for semantic discovery
8. **Deep Dive**: `query_view` / `query_sql` for structured analysis (contradictions, hubs, etc.)

## Consequences

### Positive
- **Explicit Semantics**: Task purpose is clearly defined as hypothesis verification
- **Terminology Clarity**: No more collision between `query` (task), `query_text` (search), and `hypothesis` (NLI)
- **Better LLM Focus**: `task_hypothesis` provides clear context for claim extraction
- **Audit Trail**: DB stores the exact hypothesis being verified

### Negative
- **Breaking Changes**: Existing MCP clients must update to use `hypothesis`
- **DB Recreation Required**: Existing `data/lyra.db` must be regenerated
- **Extraction Bias**: Claims are extracted with task_hypothesis as focus, which may bias toward confirming the hypothesis. Mitigation: MCP client should include refutation queries.

## Alternatives Considered

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| Keep `query` for task, add `hypothesis` separately | Backward compatible | Two concepts for same thing | Rejected |
| Auto-generate hypothesis from query | Simpler API | Loses explicit hypothesis semantics | Rejected |
| Rename NLI `hypothesis` to `claim_hypothesis` | Clearer | Conflicts with standard NLI terminology | Rejected |
| **Rename NLI `hypothesis` to `nli_hypothesis`** | Clear, explicit, unique | API change | **Accepted** |

## Related

- [ADR-0002: Three-Layer Collaboration Model](0002-three-layer-collaboration-model.md) - Updated `create_task` field name
- [ADR-0005: Evidence Graph Structure](0005-evidence-graph-structure.md) - Updated NLI terminology
- [ADR-0010: Async Search Queue](0010-async-search-queue.md) - Updated task/query relationship
- [ADR-0012: Feedback Tool Design](0012-feedback-tool-design.md) - Updated `nli_corrections` schema
- `docs/debug/hypothesis-first-integration.md` - Integration design details

