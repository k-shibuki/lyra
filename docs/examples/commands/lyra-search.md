# lyra-search

## Purpose

Build an evidence graph iteratively using Lyra MCP tools, then synthesize a traceable research report.

## When to use

- Answering evidence-based questions ("Is X effective?", "Does Y cause Z?")
- Comparing alternatives with structured evidence
- Any research requiring source traceability and confidence scoring

---

## Available Tools

### Lyra MCP Tools (evidence collection)
- **Core**: `create_task`, `queue_targets`, `get_status`, `stop_task`
- **Citation Chasing**: `queue_reference_candidates` (explicit control over which references to fetch)
- **Explore**: `vector_search`, `query_view`, `query_sql`, `list_views`
- **Auth**: `get_auth_queue`, `resolve_auth`
- **Admin**: `feedback`, `calibration_metrics`, `calibration_rollback`

### Non-MCP Tools (analysis & exploration)
- **Web search**: Background research, terminology, query brainstorming
- **Browser**: Navigate to URLs, take screenshots, read full-text sources
- **File write**: Export final report to `docs/reports/`

**Key insight**: Combine Lyra (systematic evidence) with non-MCP tools (flexible exploration) for best results.

### Terminology

| Term | Definition |
|------|------------|
| `task_id` | Unique identifier for a task; hypothesis is fixed at creation |
| `hypothesis` | Central claim bound to task_id; immutable after `create_task(hypothesis=...)` |
| `target` | A query or URL object submitted via `queue_targets(...)` — **this is what you optimize** |
| `claim` | Extracted assertion stored in Lyra's evidence graph |

### Bayesian confidence (`bayesian_truth_confidence`)

- **0.5** = no evidence yet (prior)
- **> 0.5** = more support; **< 0.5** = more refutation
- Only **cross-source** NLI edges update confidence (self-citation ignored)
- Abbreviated as "conf" in reports

### Evidence Sources (do not mix in citations)

| Source | Step | What it is | Allowed use |
|---|---|---|---|
| **Web search** | Step 1 | Background, terminology, query brainstorming | Query design, gap identification; **never as direct evidence** |
| **Lyra Evidence Graph** | Step 2/3 | Traceable chain: claim→fragment→page→URL | **Only basis for citations** in report |
| **Full-text reading (browser)** | Step 4 | Methods/results/limitations notes | Deep analysis of key sources; adds context to Step 2/3 claims |

---

## Step 1: Scout

**Goal**: Explore the topic, gather terminology, and design an effective initial query.

### 1.1 Create Task

**New task**: Create one with a testable hypothesis:
```
create_task(hypothesis="{testable_hypothesis}")
→ record task_id
```

**Existing task**: Retrieve task_id and check status:
```
get_status(task_id=task_id, wait=0)
```

The hypothesis is fixed once `create_task` is called. From here, focus on **query optimization**.

### 1.2 Web Search Exploration

Use **web search** (non-MCP tool) to:
- Understand domain terminology
- Identify key papers, authors, concepts
- Find both supporting and refuting perspectives (ADR-0017)
- Brainstorm effective search queries

**Output**: A single, well-crafted initial query for Step 2.

---

## Step 2: Evidence

**Goal**: Build the traceable evidence graph systematically.

### 2.1 Initial Query (Probe)

Start with **one query** to calibrate:

```
queue_targets(task_id=task_id, targets=[
  {"kind": "query", "query": "{initial_query_from_step_1}"}
])

get_status(task_id=task_id, wait=60)
```

Review results:
- Check `metrics.total_claims` — are claims being extracted?
- In **summary mode**, `get_status` only returns aggregated counts.
  To inspect per-query quality metrics (harvest/satisfaction), use **full mode**:
  ```
  get_status(task_id=task_id, wait=0, detail="full")
  → inspect searches_detail[*].harvest_rate, searches_detail[*].satisfaction_score, searches_detail[*].has_primary_source
  ```
- Use `query_view(view_name="v_claim_evidence_summary", task_id=task_id)` to inspect evidence quality (support/refute/neutral)

### 2.2 Design Full Target Set

Based on initial results, design a comprehensive target set:

**Required query categories** (ensure coverage):
1. **Core evidence**: `{core_concept} meta-analysis`, `{core_concept} systematic review`
2. **Mechanism**: `{mechanism} evidence`, `{mechanism} study`
3. **Refutation** (ADR-0017): `{hypothesis} limitations`, `{hypothesis} criticism`
4. **Alternative perspectives**: `{alternative_viewpoint}`, `{competing_hypothesis}`
5. **Gap-filling**: Specific queries addressing gaps from Step 2.1

**Before deploying, validate the target set**:
- Does it cover both supporting AND refuting angles?
- Are there obvious gaps given the hypothesis?
- Is each query distinct (minimal overlap)?

If validation reveals gaps, add queries. If queries seem redundant, consolidate.

```
queue_targets(task_id=task_id, targets=[
  {"kind": "query", "query": "{query_1}"},
  {"kind": "query", "query": "{query_2}"},
  ...
])
```

**Note (IMPORTANT)**: `queue_targets` **does not accept raw strings**.
All targets must be objects with `kind`:
- `{"kind": "query", "query": "..."}`
- `{"kind": "url", "url": "https://...", "reason": "manual" | "citation_chase"}`
- `{"kind": "doi", "doi": "10.xxxx/yyy", "reason": "manual" | "citation_chase"}`

### 2.3 Full Deployment & Wait

Wait for all targets to complete:

```
get_status(task_id=task_id, wait=180) # wait: adjust 30-300 as needed
```

Monitor progress using **phase-based job tracking**:

| Field | Meaning |
|-------|---------|
| `progress.jobs_by_phase.exploration` | target_queue jobs (SERP + fetch + extract) |
| `progress.jobs_by_phase.verification` | verify_nli jobs (cross-source NLI) |
| `progress.jobs_by_phase.citation` | citation_graph jobs (reference extraction) |

Each phase reports `{queued, running, completed, failed}` — use this to diagnose bottlenecks:
- `exploration.running > 0` → still fetching/extracting
- `verification.queued > 0` → NLI jobs pending
- `citation.running > 0` → citation graph processing

For per-query metrics, use **full mode**:
```
get_status(task_id=task_id, wait=0, detail="full")
→ searches_detail[*].satisfaction_score (0.7+ = good)
→ searches_detail[*].harvest_rate
→ searches_detail[*].has_primary_source
```

- `budget.remaining_percent` — resource usage

**If auth blocked**: 
```
get_auth_queue(task_id=task_id)
→ user solves CAPTCHA in browser
→ resolve_auth(action="complete", target="domain", domain="...")
```

Other domains continue while one is blocked—don't stop prematurely.

### 2.4 Review Evidence Graph

Once all targets complete, analyze the collected evidence:

```
query_view(view_name="v_claim_evidence_summary", task_id=task_id)
query_view(view_name="v_contradictions", task_id=task_id)
query_view(view_name="v_unsupported_claims", task_id=task_id)
```

This review informs Step 3 (Citation Chasing) and Step 4 exploration.

---

## Step 3: Citation Chasing

**Goal**: Acquire important references found in the References sections of fetched pages.

Citation Chasing is useful when:
- Meta-analyses and systematic reviews reference key primary studies
- Important papers are mentioned but not yet in the evidence graph
- You want deeper coverage of the citation network

### 3.1 Check Readiness

Before querying reference candidates, ensure the citation graph is stable:

```
get_status(task_id=task_id, wait=0)
→ check milestones.citation_chase_ready == true
```

If `milestones.citation_chase_ready == false`, inspect `waiting_for` (top-level array) for details:

```json
"waiting_for": [
  {"kind": "target_queue", "status": "running", "queued": 0, "running": 2},
  {"kind": "citation_graph", "status": "queued", "queued": 5, "running": 0}
]
```

| kind | status | Action |
|------|--------|--------|
| `target_queue` | running | Wait — exploration still in progress |
| `citation_graph` | queued/running | Wait — reference extraction pending |
| `pending_auth` | blocked | User must solve CAPTCHA |

When `waiting_for == []`, citation candidates are stable.

### 3.2 Query Reference Candidates

Check for unfetched citations:

```
query_view(view_name="v_reference_candidates", task_id=task_id, limit=20)
```

This returns pages cited by task's pages but not yet processed for this task:
- `citation_edge_id` — ID for explicit selection
- `candidate_url` — URL to fetch
- `candidate_domain` — Domain of the candidate
- `citation_context` — Text context where citation was found
- `citing_page_url` — Page that cited this reference

### 3.3 Select and Queue References

**Option A: Using `queue_reference_candidates` (recommended)**

Explicit control with minimal effort:

```
# Whitelist mode: only fetch these specific candidates
queue_reference_candidates(task_id=task_id, include_ids=["edge_id_1", "edge_id_2"])

# Blacklist mode: fetch all EXCEPT these
queue_reference_candidates(task_id=task_id, exclude_ids=["edge_id_3"])

# Dry run to preview
queue_reference_candidates(task_id=task_id, limit=10, dry_run=true)
```

DOI URLs are automatically routed to Academic API for faster abstract-only ingestion.

**Option B: Using `queue_targets` directly**

For fine-grained control or mixed target types:

```
queue_targets(task_id=task_id, targets=[
  {"kind": "url", "url": "https://example.com/paper1", "reason": "citation_chase"},
  {"kind": "doi", "doi": "10.1234/example", "reason": "citation_chase"},
  ...
])
```

**Selection criteria**:
- Prioritize primary studies and meta-analyses
- Focus on papers from authoritative domains (pubmed.ncbi, doi.org, arxiv.org)
- Consider citation context — is this likely relevant to your hypothesis?
- Use DOI fast path (`kind: "doi"`) when DOI is known for faster ingestion

### 3.4 Wait and Iterate

```
get_status(task_id=task_id, wait=120)
→ wait until milestones.citation_chase_ready == true
→ optionally check waiting_for for blocking details
```

After completion, check for new reference candidates:
```
query_view(view_name="v_reference_candidates", task_id=task_id, limit=20)
```

**Iteration rule (simplified)**:

- Citation Chasing is limited to **2 rounds maximum**
- After 2 rounds, proceed to Step 4 regardless of remaining candidates
- If `v_reference_candidates` returns 0 rows before 2 rounds, stop early

---

## Step 4: Deep Dive

**Goal**: Verify key sources and discover new angles to strengthen the evidence graph.

### 4.1 Primary Source Reading

Use browser tools to read full-text sources:

1. **Select sources**: Pick high-impact papers from evidence chain
   ```
   query_view(view_name="v_source_impact", task_id=task_id, limit=10)
   ```

2. **Browser read**: Navigate to URLs, screenshot key figures/tables
   ```
   browser_navigate(url="{source_url}")
   browser_snapshot()
   browser_take_screenshot()
   ```

3. **Note observations**: Methods, sample size, limitations, generalizability

### 4.2 Additional Web Search

Use web search to:
- Clarify terminology discovered in Step 2
- Find related concepts not yet captured
- Identify contradicting viewpoints

### 4.3 Loop Back Decision

After Step 4 exploration, ask: **Did I discover information that should be in the evidence graph but isn't?**

**If YES** — discoveries exist that warrant new queries:
```
→ Return to Step 1: Scout
   - Formulate new queries based on discoveries
   - Execute Step 2 with additional queries
   - Grow the evidence graph
```

**If NO** — no new information to add:
```
→ Proceed to Report
```

This is a binary decision based on discoveries, not a subjective "is it enough?" judgment.

**Anti-shortcut guard (explicit)**:
- You MUST perform Step 3 (Citation Chasing) at least once if `v_reference_candidates` returns any rows.
- You MUST NOT proceed to Step 5 (Report) while:
  - `milestones.target_queue_drained == false` (exploration still running), OR
  - `milestones.nli_verification_done == false` (NLI verification not finished), OR
  - `pending_auth_count > 0` (auth is blocking fetches).

**Quick readiness check**:
```
get_status(task_id=task_id, wait=0)
→ if waiting_for != [] → not ready (inspect for details)
→ if waiting_for == [] → all phases complete, safe to report
```

---

## Principles

1. **Lyra navigates, you analyze**: Lyra finds and organizes; detailed reading is your job
2. **Seek refutation early**: Include limitation/criticism queries from the start (ADR-0017)
3. **Probe → validate → deploy**: Start with 1 query, design full set, validate coverage, then deploy
4. **Trace everything**: Every claim in report links to a Step 2/3 source only
5. **Step 4 enriches, not replaces**: Deep dive adds context to Step 2/3 claims, not new citations
6. **Loop to grow**: Discoveries in Step 4 feed back into Step 1→2→3 to become traceable
7. **Objective termination**: Task ends when all searches complete and report is written — no subjective "is it enough?" criteria
8. Human checkpoint: **do not call `stop_task` until the user explicitly chooses “Stop”.**

## Finish the search

Before proceeding, ask the user:
- **A. Report**: Proceed to report generation (`/lyra-report`)
- **B. Expand**: Continue evidence graph growth (add queries and/or more citation chasing)
- **C. Stop**: Finalize session without report (call `stop_task`)

Default behavior: **do not call `stop_task` or proceed to report until user explicitly chooses**.

---

## Reference

### SQL Views

Use `list_views()` to discover available views. Key views:

**Core Evidence Views**:
- `v_claim_evidence_summary` — confidence per claim with support/refute counts
- `v_contradictions` — conflicting evidence requiring resolution
- `v_evidence_chain` — full provenance to URL
- `v_unsupported_claims` — claims without supporting evidence

**Source Evaluation Views**:
- `v_source_impact` — ranks sources by knowledge generation + corroboration (recommended)
- `v_source_authority` — citation-based authority ranking (optional; use alongside `v_source_impact`)

**Temporal Views**:
- `v_evidence_timeline` — publication year distribution
- `v_emerging_consensus` — claims with growing support trend
- `v_outdated_evidence` — stale evidence needing review

**Citation Network Views** (for advanced analysis):
- `v_citation_flow` — page-to-page citation relationships
- `v_citation_chains` — A→B→C citation paths
- `v_bibliographic_coupling` — papers citing same sources
- `v_reference_candidates` — unfetched citations for Citation Chasing (requires task_id)

### Auth Handling (CAPTCHA / Login)

`get_auth_queue(task_id=task_id)` → user solves in browser → `resolve_auth(action="complete", target="domain", domain="...")`

Other domains continue while one is blocked—don't stop prematurely.
