# Examples

This directory contains example commands and sample research outputs for Lyra.

## Philosophy: Evidence Graph as Primary Output

**Lyra's primary output is the Evidence Graph, not reports or visualizations.**

The "main path" of Lyra is:

- **Grow an Evidence Graph** (task → targets → pages/fragments/claims)
- **Query the graph** (views, search, contradictions, provenance) iteratively until the hypothesis is answered

Reports and visualizations exist because:

1. **Shareability**: Stakeholders who can't query your local DB need portable artifacts
2. **Auditability**: Reports provide snapshots with explicit provenance (claim → fragment → page → URL)
3. **Customizability**: With your data in a local SQLite DB, you can build any visualization or export format you want.

> **Important**: Reports and dashboards are **exports of the Evidence Graph**, not separate evidence sources. All citations must already exist in the graph.

---

## Commands

Workflow templates for AI assistants (Cursor, Claude Desktop, etc.):

| File | Purpose |
|------|---------|
| [commands/lyra-search.md](commands/lyra-search.md) | Build evidence graph iteratively |
| [commands/lyra-report.md](commands/lyra-report.md) | Generate traceable research report |

### Setup (Cursor)

```bash
cp docs/examples/commands/*.md .cursor/commands/
```

Then invoke with `/lyra-search` or `/lyra-report` in Cursor chat.

### Setup (Claude Desktop)

Add as Skills via Settings → Skills.

---

## Sample Research Sessions

> ⚠️ **Disclaimer**: These samples were created with only 3 sessions for demonstration purposes.
> The reports and dashboard **should not be treated as reliable medical information**.
> They exist solely to illustrate Lyra's capabilities and workflow.

### Session 01: DPP-4 Inhibitors (`task_ed3b72cf`)

Research question: *"Efficacy and safety of DPP-4 inhibitors as insulin add-on therapy"*

| File | Description |
|------|-------------|
| [session_01/prompt.md](session_01/prompt.md) | User's research question |
| [session_01/report.md](session_01/report.md) | Generated research report with citations |
| [session_01/chat_log.md](session_01/chat_log.md) | Full conversation log |

### Session 02: SGLT2 Inhibitors (`task_8f90d8f6`)

Research question: *"Efficacy and safety of SGLT2 inhibitors as insulin add-on therapy"*

| File | Description |
|------|-------------|
| [session_02/prompt.md](session_02/prompt.md) | User's research question |
| [session_02/report.md](session_02/report.md) | Generated research report with citations |
| [session_02/chat_log.md](session_02/chat_log.md) | Full conversation log |

### Session 03: Comparative Visualization Dashboard

Interactive HTML dashboard comparing DPP-4i vs SGLT2i evidence — demonstrating that **local data enables unlimited customization**.

| File | Description |
|------|-------------|
| [session_03/src/generate_dashboard.py](session_03/src/generate_dashboard.py) | Python script to generate dashboard from DB |
| [session_03/src/dashboard_template.html](session_03/src/dashboard_template.html) | D3.js visualization template |
| [session_03/output/evidence_dashboard.html](session_03/output/evidence_dashboard.html) | Generated interactive dashboard |

**Dashboard Features:**

- Bayesian Confidence Distribution (lollipop chart)
- Source Authority Treemap
- Contradiction Analysis Heatmap
- Evidence Timeline (area chart)
- Toggle between Compare / DPP-4i / SGLT2i views

**Why this matters**: The evidence you collect is **yours** — stored locally in SQLite, queryable with standard tools, exportable in any format. This dashboard was built with a simple Python script that queries the DB directly. Unlike ephemeral "deep research" outputs that vanish after a session, your evidence graph persists and grows over time.

---

## Direct MCP Tool Calls

For programmatic access or custom workflows:

```python
# 1. Create task
task = create_task(hypothesis="DPP-4 inhibitors improve HbA1c in type 2 diabetes")

# 2. Queue targets (async execution)
queue_targets(task_id=task.task_id, targets=[
    {"kind": "query", "query": "DPP-4 inhibitors efficacy meta-analysis"},
    {"kind": "query", "query": "DPP-4 inhibitors cardiovascular safety"},
    {"kind": "query", "query": "DPP-4 inhibitors limitations"},  # Include refutation queries
])

# 3. Monitor progress
get_status(task_id=task.task_id, wait=180)

# 4. Explore evidence (the main path!)
vector_search(query="cardiovascular", target="claims", task_id=task.task_id)
query_view(view_name="v_claim_evidence_summary", task_id=task.task_id)
query_view(view_name="v_contradictions", task_id=task.task_id)

# 5. Provide feedback (improves model over time)
feedback(action="edge_correct", edge_id="...", correct_relation="supports")

# 6. (Optional) Generate report or custom visualization
# See commands/lyra-report.md or session_03/src/generate_dashboard.py
```
