# Lyra Examples

## 🎯 See It In Action

**[→ View Demo](https://k-shibuki.github.io/lyra/)**

This Evidence Dashboard was created entirely through AI conversation — no manual coding required.

---

## Workflow

### Step 1: Build Evidence Graph

```
/lyra-search
```

Ask a research question. AI searches, extracts claims, and builds a traceable evidence graph.

### Step 2: Generate Report

```
/lyra-report
```

Export the evidence graph to a structured research report with citations.

### Step 3: Generate Dashboard (optional)

```bash
cd docs/examples/session_03/src
python generate_dashboard.py \
  --tasks task_ed3b72cf:../../session_01/report.md \
          task_8f90d8f6:../../session_02/report.md \
  --output ../output/evidence_dashboard.html
```

Pass task IDs (with optional report paths) from your research sessions. The script queries the local SQLite database and generates an interactive HTML dashboard.

---

## Setup

Copy workflow commands to your AI assistant:

```bash
# For Cursor
cp docs/examples/commands/*.md .cursor/commands/
```

Then invoke with `/lyra-search` or `/lyra-report` in chat.

---

## Sample Sessions

| Session | Research Question | Output |
|---------|-------------------|--------|
| [01](session_01/) | DPP-4 inhibitors as insulin add-on | [Report](session_01/report.md) |
| [02](session_02/) | SGLT2 inhibitors as insulin add-on | [Report](session_02/report.md) |
| [03](session_03/) | Comparative visualization | [Dashboard](https://k-shibuki.github.io/lyra/session_03/output/evidence_dashboard.html) |

---

## ⚠️ Disclaimer

These samples were created with only 3 sessions for demonstration purposes. The reports and dashboard **should not be treated as reliable medical information**. They exist solely to illustrate Lyra's capabilities and workflow.

---

## ⚠️ Philosophy: Evidence Graph as Primary Output

**Lyra's primary output is the Evidence Graph, not reports or visualizations.**

The "main path" of Lyra is:

1. **Grow an Evidence Graph** — task → targets → pages/fragments/claims
2. **Query the graph** — views, search, contradictions, provenance — iteratively until the hypothesis is answered

Reports and visualizations exist because:

- **Shareability**: Stakeholders who can't query your local DB need portable artifacts
- **Auditability**: Reports provide snapshots with explicit provenance (claim → fragment → page → URL)
- **Customizability**: With your data in a local SQLite DB, you can build any visualization or export format you want

The evidence you collect is **yours** — stored locally, queryable with standard tools, exportable in any format. Unlike cloud "deep research" that vanishes after a session, your Evidence Graph is a permanent, auditable asset.
