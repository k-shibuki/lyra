# Examples

This directory contains example commands and sample research outputs for Lyra.

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

## Sample Research

### DPP-4 Inhibitors as Add-on Therapy to Insulin

A complete research example investigating:
> "What is the efficacy and safety of DPP-4 inhibitors as add-on therapy for type 2 diabetes patients receiving insulin therapy with HbA1c ≥7%?"

| File | Description |
|------|-------------|
| [dpp4-insulin-addon/user_prompt.md](dpp4-insulin-addon/user_prompt.md) | User's research question |
| [dpp4-insulin-addon/report.md](dpp4-insulin-addon/report.md) | Generated research report with citations |
| [dpp4-insulin-addon/chatlog.md](dpp4-insulin-addon/chatlog.md) | Full conversation log (reference) |

The report demonstrates:
- Structured evidence tables with citations
- Bayesian confidence scoring
- Source traceability (claim → fragment → page → URL)
- Comparison of alternatives (DPP-4i vs GLP-1 RA vs SGLT2i)

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

# 4. Explore evidence
vector_search(query="cardiovascular", target="claims", task_id=task.task_id)
query_view(view_name="v_source_impact", task_id=task.task_id)  # Key Sources
query_view(view_name="v_contradictions", task_id=task.task_id)

# 5. Provide feedback (improves model over time)
feedback(action="edge_correct", edge_id="...", correct_relation="supports")
```
