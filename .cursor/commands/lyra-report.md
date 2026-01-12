# lyra-report

## Purpose

Generate a **decision-first**, **traceable** research report from the **Lyra Evidence Graph**.

This command leverages Python-based deterministic generation with LLM-only enhancement:

| Stage | Execution | Output |
|-------|-----------|--------|
| Stage 1-2 | `make report` (Python) | `evidence_pack.json`, `citation_index.json`, `drafts/draft_01.md` |
| Stage 4 | LLM (this command) | `drafts/draft_02.md` (or iterative `drafts/draft_03.md`), `outputs/report_summary.json` |
| Stage 3 | `make report-validate` (Python) | `drafts/draft_validated.md`, `validation_log.json` |
| Finalize | `make report-finalize` (Python) | `outputs/report.md` (markers stripped) |
| Dashboard | `make report-dashboard` (Python) | `dashboard.html` |

---

## Draft Structure & Editing Markers

The `drafts/draft_01.md` contains **explicit markers** to guide your editing:

### Marker Types

| Marker | Meaning | Your Action |
|--------|---------|-------------|
| `<!-- LLM_EDITABLE: name -->` ... `<!-- /LLM_EDITABLE -->` | **Editable zone** | Fill in, replace, or expand content |
| `<!-- LLM_READONLY -->` ... `<!-- /LLM_READONLY -->` | **Read-only zone** | **Do NOT modify** (numbers, tables, IDs) |
| `<!-- LLM_DELETE_ONLY: name -->` ... `<!-- /LLM_DELETE_ONLY -->` | **Delete-only zone** | You may delete full lines (e.g., table rows) but must not edit remaining lines |

### Editable Zones in Draft

| Zone Name | Location | What to Write |
|-----------|----------|---------------|
| `executive_summary` | 1-Minute Summary | 3-6 line executive summary |
| `verdict` | Verdict section | SUPPORTED/REFUTED/INCONCLUSIVE + rationale |
| `efficacy_interpretation` | After Table A | 1-2 sentences on efficacy findings |
| `safety_interpretation` | After Table B | 1-2 sentences on safety findings |
| `support_interpretation` | After Table C | 1-2 sentences on support evidence |
| `synthesis_prose` | Short Synthesis | 2-4 paragraphs connecting findings to hypothesis |
| `contradictions_interpretation` | Appendix B | Explain why contradictions exist |
| `excluded_sources` | Appendix D | Sources not cited (with reasons) |

### Read-Only Zones (Do NOT Modify)

- Header metadata (task_id, hypothesis, generated date)
- Summary table (Top Claims Analyzed, Contradictions Found, Sources Cited)
- Score definition and context
- All data tables (Table A, B, C, Contradictions table)
- Methodology section
- Citable Source Catalog + References placeholder (Stage 3 auto-generates numbered references)

---

## Non-negotiables

| Constraint | Rationale |
|------------|-----------|
| **No new URLs** | All URLs must exist in `citation_index.json` |
| **No fabricated numbers** | All effect sizes from `evidence_pack.evidence_chains` |
| **No unknown citations** | Cite tokens must use `page_id` values from the Citable Source Catalog |
| **No new claims** | All claims from `evidence_pack.claims` |
| **Read-only zones intact** | Do not modify `<!-- LLM_READONLY -->` blocks |

---

## Stage 0: Generate Deterministic Artifacts

**Run this first (in terminal):**

```bash
make report TASKS="task_xxx task_yyy"
```

This generates for each task:

```
data/reports/{task_id}/
├── evidence_pack.json      # Facts + claim-level exploration score (nli_claim_support_ratio)
├── citation_index.json     # URL lookup (in-graph sources only)
└── drafts/
    └── draft_01.md         # Fact-only baseline draft with markers
```

**Verify files exist before proceeding:**

```
read_file("data/reports/{task_id}/evidence_pack.json")
read_file("data/reports/{task_id}/citation_index.json")
read_file("data/reports/{task_id}/drafts/draft_01.md")
```

---

## Stage 4: LLM Enhancement (This Command)

**Objective**: Copy-forward from `drafts/draft_01.md` to `drafts/draft_02.md` (and optionally iterate `drafts/draft_03.md`) by adding interpretation only, and insert citations using **stable cite tokens**:

- `{{CITE:page_id}}` (example: `{{CITE:page_123abc}}`)

Stage 3 will assign numeric citation numbers (`[^1]`, `[^2]`, ...) deterministically from these tokens.

Note: Template instructions for the LLM inside the draft are written in **English** (keep them as-is; they are stripped in finalization).

### Input Contract

**MUST read files first:**

```
read_file("data/reports/{task_id}/evidence_pack.json")
read_file("data/reports/{task_id}/citation_index.json")
read_file("data/reports/{task_id}/drafts/draft_01.md")
```

### Permitted Operations

| Operation | Scope | Example |
|-----------|-------|---------|
| **Fill editable zones** | `<!-- LLM_EDITABLE -->` blocks | Write executive summary |
| **Interpretation** | Editable zones only | Explain why contradictions exist |
| **Synthesis prose** | `synthesis_prose` zone | Rewrite observations as flowing paragraphs |
| **Verdict reasoning** | `verdict` zone | Explain SUPPORTED/REFUTED/INCONCLUSIVE |
| **Insert citations** | Editable zones only | Add `{{CITE:page_id}}` tokens copied from the Citable Source Catalog |
| **Full-text fetch** | In-graph URLs only | Read source papers for deeper context |
| **Domain knowledge** | Interpretation only | Add clinical context (no new citations) |

### Deep-Dive: Fetching Full Text

You **may** (and are encouraged to) fetch the full text of sources listed in `citation_index.json`:

1. **Find URL**: Look up `url` field in `citation_index.json` or `evidence_pack.citations[]`
2. **Fetch**: Use `browser_navigate` or equivalent to read the full paper/article
3. **Interpret**: Use the content to write better interpretation in editable zones
4. **Constraint**: Do NOT add the URL as a new citation. It's already in-graph.

Example workflow:
```
# 1. Read citation index
read_file("data/reports/{task_id}/citation_index.json")

# 2. Find a source you want to read in depth
# e.g., "https://pubmed.ncbi.nlm.nih.gov/30603867/"

# 3. Fetch and read
browser_navigate(url="https://pubmed.ncbi.nlm.nih.gov/30603867/")
browser_snapshot()

# 4. Use insights to write better interpretation in editable zones
```

### Forbidden Operations

| Operation | Why Forbidden |
|-----------|---------------|
| Modify `<!-- LLM_READONLY -->` blocks | Data integrity |
| Add new URLs not in `citation_index.json` | Traceability |
| Invent numbers/percentages | Fabrication |
| Add claims not in `evidence_pack.claims` | Out-of-graph data |
| Write numeric citations like `[^1]` | Stage 3 assigns citation numbers deterministically |
| Edit the References section manually | Stage 3 auto-generates numbered references with `page_id=` traces |

---

## Writing the Enhanced Report

### Step 1: Copy-forward, then edit minimally

1. Copy baseline:

```bash
cp data/reports/{task_id}/drafts/draft_01.md data/reports/{task_id}/drafts/draft_02.md
```

2. Edit `drafts/draft_02.md`:
- Modify **only** `<!-- LLM_EDITABLE: ... -->` blocks
- In `<!-- LLM_DELETE_ONLY: ... -->` blocks: **delete lines only** (no edits)
- Do NOT modify `<!-- LLM_READONLY -->` blocks
- Insert citations using `{{CITE:page_id}}` only (copy `page_id` from the Citable Source Catalog)
- Do NOT write numeric citations like `[^1]`

3. Save the enhanced draft:

```
write_file(
  file_path="data/reports/{task_id}/drafts/draft_02.md",
  contents=<enhanced draft with markers preserved>
)
```

### Step 2: Write `outputs/report_summary.json` (Required)

The dashboard treats `outputs/report_summary.json` as the **single source of truth** for the report verdict.

```json
{
  "schema_version": "report_summary_v1",
  "task_id": "task_xxx",
  "hypothesis": "…",
  "verdict": "SUPPORTED",
  "verdict_rationale": "1–3 sentences explaining why, citing only in-graph sources.",
  "key_outcomes": [
    {
      "topic": "HbA1c",
      "finding": "Reduced vs control in multiple RCTs/MA (see report footnotes)."
    }
  ],
  "evidence_notes": [
    "List key limitations or gaps."
  ],
  "generated_at": "2026-01-11T00:00:00Z"
}
```

Write it:

```
write_file(
  file_path="data/reports/{task_id}/outputs/report_summary.json",
  contents=<json string>
)
```
Do NOT strip markers yet. Finalization happens after Stage 3.

---

## Stage 3: Validation

**Run validation (in terminal):**

```bash
make report-validate TASKS="task_xxx"
```

If validation fails, fix issues and re-validate. Common failures:

| Violation | Fix |
|-----------|-----|
| `hallucinated_url` | Remove URL or cite only in-graph sources listed in `citation_index.json` |
| `numeric_footnotes_in_llm_stage` | Replace `[^N]` in prose with `{{CITE:page_id}}` tokens copied from the Citable Source Catalog |
| `unknown_cite_token` | Use only `page_id` values listed in the Citable Source Catalog |
| `cite_tokens_remaining` | Fix malformed tokens so Stage 3 can replace them (must match `{{CITE:page_id}}`) |
| `fabricated_numbers` | Remove or qualify numbers not present in `evidence_pack.evidence_chains` |
| `readonly_modified` | Restore original content from `drafts/draft_01.md` (copy-forward again) |

If validation fails:

- The system creates/uses `drafts/draft_03.md` for iterative fixes.
- Apply minimal edits to `drafts/draft_03.md` (do not regenerate from scratch).
- Re-run `make report-validate`.

The unified validation writes `validation_log.json` (LLM-readable JSON) with clear actions.

When validation passes, it writes `drafts/draft_validated.md`.

Then finalize:

```bash
make report-finalize TASKS="task_xxx"
```

This produces `outputs/report.md` (markers stripped).

---

## Generate Dashboard

After validation passes:

```bash
make report-dashboard TASKS="task_xxx [task_yyy ...]"
```

Output: `data/reports/dashboards/dashboard_*.html`

The dashboard will show:
- Claims with edge counts and exploration score (`nli_claim_support_ratio`)
- Verdict from `outputs/report_summary.json` (SUPPORTED/REFUTED/INCONCLUSIVE)
- TOP30 claims highlighted

---

## Complete Workflow

```bash
# 1. Generate evidence pack + draft (deterministic)
make report TASKS="task_xxx"

# 2. Copy-forward and enhance (LLM)
cp data/reports/task_xxx/drafts/draft_01.md data/reports/task_xxx/drafts/draft_02.md
#    → LLM edits drafts/draft_02.md (EDITABLE only; DELETE_ONLY deletions only)
#    → LLM writes outputs/report_summary.json

# 3. Validate + postprocess (unified)
make report-validate TASKS="task_xxx"

# 4. Finalize (strip markers)
make report-finalize TASKS="task_xxx"

# 5. Generate dashboard (requires outputs/report.md for each task)
make report-dashboard TASKS="task_xxx task_yyy"
```

---

## File Structure

```
data/reports/{task_id}/
├── evidence_pack.json      # Stage 1-2: Facts with exploration score (nli_claim_support_ratio)
├── citation_index.json     # Stage 1-2: URL→metadata lookup (in-graph only)
├── drafts/
│   ├── draft_01.md         # Stage 1-2: Baseline draft with markers
│   ├── draft_02.md         # Stage 4: LLM edits
│   ├── draft_03.md         # Stage 4: Iterative fix draft (copy-forward on failure)
│   └── draft_validated.md  # Stage 3: Postprocessed + validated draft
├── outputs/
│   ├── report.md           # Final report (markers stripped)
│   └── report_summary.json # Stage 4: Verdict + key outcomes (dashboard source of truth)
└── validation_log.json     # Stage 3: Unified, LLM-readable JSON log

data/reports/dashboards/
└── dashboard_{timestamp}.html  # Visualization
```

---

## Context Management

All facts are in `evidence_pack.json`. Key sections:

| Section | Content |
|---------|---------|
| `claims[]` | TOP30 claims with `nli_claim_support_ratio` + edge counts + ranking |
| `contradictions[]` | Claims with opposing evidence |
| `evidence_chains[]` | Fragment→Claim links with NLI confidence |
| `citations[]` | Page metadata for footnotes |
| `citation_flow[]` | Page→Page citation relationships |

For large evidence packs, load selectively:
1. First: `metadata` + `claims[]` summary
2. On-demand: `evidence_chains[]` for specific claims
3. Reference: `citations[]` when writing footnotes

---

## Exploration Score Definition

The `nli_claim_support_ratio` field in `evidence_pack.claims` is:

- **0.5** = No net tilt (or insufficient/offsetting evidence)
- **> 0.5** = More support than refutation
- **< 0.5** = More refutation than support

**IMPORTANT**: This is a claim-level exploration score, NOT a hypothesis verdict.
The hypothesis verdict must be written by YOU (the LLM) in Stage 4.

---

## Before Stopping

Ask the user:

- **A. Expand**: Add more evidence and regenerate
- **B. Regenerate**: Re-run with different focus
- **C. Stop**: Finalize session

Default: Do not stop until user chooses C.
