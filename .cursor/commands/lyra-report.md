# lyra-report

## Purpose

Generate a **decision-first**, **traceable** research report from the **Lyra Evidence Graph**.

This command operates in **4 stages** with intermediate file outputs to ensure:

1. **Fact extraction** — Stage 1 extracts facts from Evidence Graph
2. **Fact structuring** — Stage 2 arranges facts into report structure (NO AI interpretation)
3. **Validation** — Stage 3 verifies draft matches facts via diff
4. **AI enhancement** — Stage 4 adds interpretation and polish to validated facts

### Non-negotiables (control > brevity)

- **Citations**: Only cite sources that exist in the Lyra graph (claim→fragment→page→URL).
- **No web-search evidence**: Web search is for query design only.
- **No out-of-graph metadata**: Author/year/title/evidence-type labels must be **extractable from the Lyra graph rows you fetched**. If a field is not extractable, write `unknown` (do **not** guess).
- **No "good enough" shortcuts**: Every key claim in the body must have a footnote.
- **Prefer stable IDs**: DOI / PMID / PMCID over raw PDF links.
- **Scope guard**: Keep the report focused on the hypothesis' outcomes; off-scope sections go to Appendix.

### Mandatory file I/O (structural enforcement)

**This command REQUIRES intermediate file writes. Do NOT skip them.**

| Stage | Required file writes | Purpose |
|-------|---------------------|---------|
| Stage 1 end | `write_file(evidence_pack.json)`, `write_file(citation_index.json)` | Persist facts for Stage 2 input |
| Stage 2 end | `write_file(report_draft.md)` | Persist **fact-only** draft for Stage 3 validation |
| Stage 3 (if violations) | `write_file(violation_report.json)` | Record validation failures |
| Stage 4 end | `write_file(docs/reports/{YYYYMMDD_HHMMSS}_{topic}.md)`, `write_file(audit_trail.json)` | Final report + audit log |

**Context isolation rule**:

- **Do NOT hold query results in context across stage boundaries**
- Stage 1 → writes files → **context cleared** → Stage 2 reads files
- This ensures Stage 2 operates ONLY on persisted facts, not on "remembered" data

---

## Stage 0: Setup

### Working directory

All intermediate files go to:

```
data/reports/{task_id}/
├── evidence_pack.json      # Stage 1 output (facts)
├── citation_index.json     # Stage 1 output (URL lookup)
├── report_draft.md         # Stage 2 output (facts only, no AI)
├── violation_report.json   # Stage 3 output (if violations)
└── audit_trail.json        # Stage 4 output (audit log)

Final report (only this is published):
docs/reports/{YYYYMMDD_HHMMSS}_{short_topic}.md  # Stage 4 output (AI-enhanced)
```

### Create working directory

```bash
mkdir -p data/reports/{task_id}
```

---

## Stage 1: Evidence Extraction (Lyra-only)

**Objective**: Extract **minimal necessary** facts from Evidence Graph

### ⚠️ Context overflow prevention

**CRITICAL**: Do NOT accumulate query results in context. Write to file IMMEDIATELY after each query.

**Anti-pattern** (causes context overflow):
```
# ❌ BAD: Accumulate everything, then write
claims = query_view(...)      # 200 rows in context
contradictions = query_view(...)  # +100 rows
citations = query_sql(...)    # +500 rows → CONTEXT OVERFLOW
write_file(all_combined)      # Never reached
```

**Required pattern** (incremental write):
```
# ✅ GOOD: Query → Write → Clear → Next query
query_view(...) → write_file(claims_section) → forget results
query_view(...) → write_file(contradictions_section) → forget results
```

### Constraints

- ✅ Lyra MCP tools allowed: `query_view`, `query_sql`, `get_status`
- ✅ File writes: incremental append to `evidence_pack.json`
- ❌ LLM interpretation forbidden (no summarize, no paraphrase)
- ❌ Holding multiple query results in context simultaneously FORBIDDEN

### Minimum viable dataset (what's actually needed for report)

| Data | Purpose | Required columns | Max rows |
|------|---------|------------------|----------|
| Top claims | Verdict, tables | claim_id, claim_text, bayesian_conf, support/refute counts | 30 |
| Contradictions | Appendix B | claim_id, claim_text, controversy_score | 15 |
| Citations (for top claims only) | Footnotes | page_id, url, title, author, year, doi | ~30 |
| Fragment snippets (for cited claims only) | Number verification | fragment_id, snippet (300 chars), claim_id | ~50 |

**Total target**: ~125 rows, not 500+

### Step 1.1: Initialize evidence pack file

**First, create the file with metadata only:**

```
write_file(
  file_path="data/reports/{task_id}/evidence_pack.json",
  contents={
    "$schema": "evidence_pack_v1",
    "metadata": {
      "task_id": "{task_id}",
      "hypothesis": "{hypothesis}",
      "generated_at": "{timestamp}"
    },
    "claims": [],
    "contradictions": [],
    "citations": [],
    "evidence_chains": []
  }
)
```

### Step 1.2: Extract TOP claims only (not all)

**Query top 30 claims by evidence strength:**

```
query_view(view_name="v_claim_evidence_summary", task_id=task_id, limit=30)
```

**IMMEDIATELY write to file** (do not hold in context for next query):

```
read_file("data/reports/{task_id}/evidence_pack.json")  # Get current state
# Update claims[] section
write_file("data/reports/{task_id}/evidence_pack.json", updated_content)
```

**Then clear from context** — do not reference these results in subsequent steps.

### Step 1.3: Extract contradictions

```
query_view(view_name="v_contradictions", task_id=task_id, limit=15)
```

**IMMEDIATELY write and clear.**

### Step 1.4: Identify which pages need citation metadata

**From Steps 1.2-1.3, collect unique page_ids that will be cited.** This is a derived list, not a new query.

Typically this is 20-40 unique pages for a focused report.

### Step 1.5: Extract citation metadata (ONLY for pages that will be cited)

```
query_sql(sql="SELECT
                 p.id AS page_id,
                 p.url AS page_url,
                 p.title AS page_title,
                 p.domain,
                 w.year AS work_year,
                 w.venue AS work_venue,
                 w.doi AS work_doi,
                 CASE
                   WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 0 THEN NULL
                   WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 1
                     THEN (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id LIMIT 1)
                   ELSE (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id ORDER BY wa.position LIMIT 1) || ' et al.'
                 END AS author_display
               FROM pages p
               LEFT JOIN works w ON w.canonical_id = p.canonical_id
               WHERE p.id IN ({page_ids_from_step_1_4})",
          options={"limit": 50})
```

**IMMEDIATELY write and clear.**

### Step 1.6: Extract fragment snippets (ONLY for claims that will be cited)

```
query_sql(sql="SELECT
                 c.id AS claim_id,
                 f.id AS fragment_id,
                 substr(f.text_content, 1, 300) AS fragment_snippet,
                 f.heading_context,
                 e.relation,
                 e.nli_edge_confidence,
                 p.id AS page_id
               FROM claims c
               JOIN edges e ON e.target_id = c.id AND e.target_type = 'claim'
               JOIN fragments f ON f.id = e.source_id AND e.source_type = 'fragment'
               JOIN pages p ON p.id = f.page_id
               WHERE c.id IN ({claim_ids_from_step_1_2})
                 AND e.relation IN ('supports', 'refutes')
               ORDER BY e.nli_edge_confidence DESC",
          options={"limit": 50})
```

**IMMEDIATELY write and clear.**

### Step 1.7: Build citation_index.json

Generate URL→metadata lookup for Stage 3 validation.

**This is derived from citations[] already in evidence_pack.json:**

```
read_file("data/reports/{task_id}/evidence_pack.json")
# Extract citations[], build index
write_file("data/reports/{task_id}/citation_index.json", index)
```

Index structure:

```json
{
  "https://doi.org/10.1234/example": {
    "citation_id": "cit_001",
    "page_id": "p_abc",
    "has_doi": true,
    "has_author": true,
    "has_year": true
  }
}
```

### Step 1.8: Verify files and print summary

At this point, files should already exist from incremental writes in Steps 1.1-1.7.

**Verify:**

```
read_file(target_file="data/reports/{task_id}/evidence_pack.json")  # Should have claims, contradictions, citations, evidence_chains
read_file(target_file="data/reports/{task_id}/citation_index.json") # Should have URL→page_id map
```

**Final evidence_pack.json structure:**

```json
{
  "$schema": "evidence_pack_v1",
  "metadata": {
    "task_id": "...",
    "hypothesis": "...",
    "generated_at": "...",
    "counts": {
      "claims": 30,
      "contradictions": 15,
      "citations": 35,
      "evidence_chains": 50
    }
  },
  "claims": [],
  "contradictions": [],
  "citations": [],
  "evidence_chains": []
}
```

Print summary:

```
=== Stage 1 Complete ===
Evidence Pack: data/reports/{task_id}/evidence_pack.json ✓
Citation Index: data/reports/{task_id}/citation_index.json ✓

Counts (should be minimal, not exhaustive):
- Top claims: ~30
- Contradictions: ~15
- Citations (for cited claims only): ~35
- Evidence chains (for cited claims only): ~50

⚠️  CONTEXT BOUNDARY: Do not carry query results into Stage 2.
    Stage 2 must read from files only.

Proceeding to Stage 2...
```

---

## Stage 2: Fact Structuring (NO AI Interpretation)

**Objective**: Arrange Stage 1 facts into report structure — **mechanically, without AI interpretation**

### Key principle: Draft = Pure facts

The `report_draft.md` is a **fact-only** document:
- Tables contain raw data from `evidence_pack.json`
- Footnotes are mechanical lookups from `citation_index.json`
- Synthesis section lists observations, NOT interpretations
- Contradictions section lists discrepancies, NOT explanations

**NO AI interpretation in Stage 2.** All interpretation happens in Stage 4.

### ⚠️ Context isolation checkpoint

**Before starting Stage 2, verify you are NOT using any data from Stage 1 context.**

All data for Stage 2 MUST come from reading files. If you find yourself "remembering" claims or citations from Stage 1 without reading the file, STOP and read the file first.

### Constraints

- ✅ File operations allowed: `read_file`, `write_file`
- ❌ Lyra MCP tools FORBIDDEN (no `query_sql`, no `query_view`, no `queue_targets`)
- ❌ Web search FORBIDDEN
- ❌ Creating data not in evidence_pack FORBIDDEN
- ❌ Using "remembered" data from Stage 1 FORBIDDEN

### Input contract (MANDATORY)

**First action of Stage 2 MUST be file reads:**

```
read_file(target_file="data/reports/{task_id}/evidence_pack.json")
read_file(target_file="data/reports/{task_id}/citation_index.json")
```

**If file read fails**: STOP. Return to Stage 1 and ensure files were written.

**If file exceeds context window**, use tiered loading strategy:

1. First read: Extract `metadata` + `claims[]` (id, text, confidence only)
2. Second read: Extract `citations[]` for footnote lookup
3. On-demand: Read specific `evidence_chains[]` entries only when citing that claim

**Tiered loading example** (for large packs):

```
# Read 1: Get structure and claims
read_file(target_file="data/reports/{task_id}/evidence_pack.json")
# → Parse and keep only: metadata, claims[].{claim_id, claim_text, bayesian_truth_confidence}
# → Write working subset to context

# Read 2: When writing footnote for claim X
read_file(target_file="data/reports/{task_id}/evidence_pack.json")
# → Search for citations[] entry matching claim X's page_id
# → Extract only that citation's metadata
```

### Absolute constraints (violation = Stage 3 FAIL)

These are **hard rules**. Any violation triggers Stage 3 rejection.

| Constraint | Rationale | Detection |
|------------|-----------|-----------|
| **No footnote changes** — Do not add, remove, or modify `[^n]` references or their content | Footnotes are facts from Stage 1 | Footnote diff |
| **No numeric changes** — Do not add, modify, or invent effect sizes, CIs, RRs, percentages, sample sizes | Numbers are facts from fragments | Number grep |
| **No new evidence claims** — Do not introduce claims not in `evidence_pack.claims[]` | Would bypass Evidence Graph | claim_id diff |
| **No URL changes** — Do not add URLs not in `citation_index.json` | Hallucination risk | URL diff |
| **No author/year invention** — Use only `author_display`, `work_year` from pack; otherwise `unknown` | Fabrication risk | Metadata diff |
| **No Lyra MCP calls** — Stage 2 operates on files only | Stage isolation | Tool audit |

### Permitted operations in Stage 2 (MINIMAL)

Stage 2 is **mechanical structuring only**. The only allowed transformations:

| Operation | Scope | Example |
|-----------|-------|---------|
| **Evidence type inference** | Infer GL/SR/MA/RCT/Obs from `domain`, `page_title` | `pubmed.gov` + "meta-analysis" in title → label as "MA" |
| **Number formatting** | Normalize format without changing values | "0.5-0.8%" ↔ "0.5% to 0.8%" |
| **Table construction** | Arrange data into tables | Populate rows from claims[] |

**NOT allowed in Stage 2** (reserved for Stage 4):
- ❌ Interpretation of contradictions
- ❌ Synthesis prose improvement
- ❌ Verdict reasoning beyond fact listing
- ❌ Claim paraphrasing

### Boundary cases

| Situation | Rule |
|-----------|------|
| Fragment says "0.5-0.8%" but you want to write "0.5% to 0.8%" | ✅ Allowed — format change, same values |
| Fragment says "0.5%" but you want to write "0.6%" | ❌ Forbidden — numeric change |
| No author in pack, but you "know" it's Smith et al. | ❌ Forbidden — must write `unknown` |
| Claim text is awkward, you want to improve grammar | ❌ Forbidden in Stage 2 — keep verbatim |
| Contradictions section is bare, you want to add interpretation | ❌ Forbidden in Stage 2 — Stage 4 will add |

### Report structure

Generate `report_draft.md` with the following sections:

#### 0) Header (required)

- Date
- task_id
- Hypothesis (verbatim from `evidence_pack.metadata.hypothesis`)

#### 1) 1-minute summary (required)

**3–6 lines + 1 mini table**. Decision-ready without scrolling.

**Purpose**: Executive summary for rapid decision-making. Reader should know the verdict and key numbers without scrolling.

Rules:
- Include: population, comparator, core outcomes, representative effect-size **range**, and 1–2 caveats
- If an effect size is not available from `claims[]` or `evidence_chains[].fragment_snippet`, write "not extractable from graph" explicitly
- **Do NOT repeat** the detailed findings from Key Findings tables — summarize at a higher level

Mini table (required):

| Outcome | Effect (range) | Population / Comparator | Evidence type | Notes |
|---|---:|---|---|---|

#### 2) Verdict (required)

Format:
- `{hypothesis}: SUPPORTED / REFUTED / INCONCLUSIVE (confidence: X.XX)`

Confidence definition:
- **Lyra Conf** = `bayesian_truth_confidence` (0–1) derived from cross-source NLI evidence edges
- **0.50 means "no net cross-source signal yet"**, not "50% efficacy"
- Prefer effect sizes + evidence type for decisions; use Lyra Conf as traceability aid

#### 3) Key Findings — exactly 3 tables

**Table granularity rule**: One row per unique (Outcome, Population/Comparator) pair. If multiple claims report the same outcome for the same population, **merge into one row** with the most authoritative source (prefer GL > MA > SR > RCT > Obs).

**Table A: Efficacy (required)**

| Outcome | Effect (range) | Population / Comparator | Evidence type (GL/SR/MA/RCT) | Citation |
|---|---:|---|---|---|

Deduplication example:
- ❌ Row 1: HbA1c, -0.7%, T2DM + insulin, RCT, [^1]
- ❌ Row 2: HbA1c, -0.6%, T2DM + insulin, RCT, [^2]
- ✅ Merged: HbA1c, -0.6% to -0.7%, T2DM + insulin, RCT, [^1][^2]

**Table B: Safety (required)**

| Outcome | Direction | Population / Comparator | Evidence type | Citation |
|---|---|---|---|---|

**Table C: Applicability / Practical notes (required)**

| Topic | Practical implication | Evidence type | Citation |
|---|---|---|---|

#### 4) Short synthesis (required, max 8 lines)

**In Stage 2 (draft)**: List factual observations only. No interpretation.

```markdown
## Short Synthesis

Observations from evidence:
- {n} sources support the hypothesis
- {n} sources show contradictory findings
- Key effect sizes: {list from claims[]}
- Evidence types: {GL/MA/RCT/etc. distribution}
- Gaps: {missing data points, e.g., "no studies >2 years"}
```

**Stage 4 will transform this into analytical prose.**

#### Appendix sections

- **A) Methodology**: Stages executed, query set used, citation-chasing iterations
- **B) Contradictions**: From `contradictions[]` with footnotes — **list only, no interpretation in Stage 2**
- **C) Full references**: All URLs from `citations[]`
- **D) Excluded / Retracted / Unresolved ID**: Sources not used in main body

**Contradictions format (Stage 2 — facts only)**:

```markdown
## Appendix B: Contradictions

| Claim A | Claim B | Source A | Source B |
|---------|---------|----------|----------|
| {claim_a_text} | {claim_b_text} | [^n] | [^m] |
```

**Stage 4 will add interpretive sentences explaining each contradiction.**

### Footnote generation rule

For each footnote `[^n]`:

1. Look up URL in `citation_index.json` → get `page_id`
2. Get full metadata from `evidence_pack.citations[]` entry with that `page_id`
3. Render using ONLY these fields

**Template**:

```markdown
[^n]: {author_display}, {work_year}. {page_title} ({evidence_type}).
      {work_doi|page_url}.
      Lyra: page_id={page_id}, fragment_id={fragment_id}.
```

**Handling missing metadata (unknown display)**:

Do NOT write literal `unknown`. Use graceful fallbacks:

| Missing field | Display format |
|---------------|----------------|
| `author_display` is null | Omit author entirely: `{work_year}. {page_title}...` |
| `work_year` is null | Use "n.d." (no date): `{author_display}, n.d. {page_title}...` |
| Both missing | Start with title: `{page_title} ({evidence_type})...` |
| `work_doi` is null | Use `page_url` instead |

Examples:
- ✅ `Smith et al., 2023. Effect of DPP-4i... (Meta-analysis). DOI:10.1234/...`
- ✅ `2022. ADA Standards of Care... (Guideline). https://diabetes.org/...`
- ✅ `Clinical review of sitagliptin (Educational). https://example.com/...`
- ❌ `unknown, unknown. Title... (unknown).` ← Never do this

### Write draft (MANDATORY — do not skip)

**You MUST call `write_file` to persist the draft. Stage 3 reads this file.**

```
write_file(
  file_path="data/reports/{task_id}/report_draft.md",
  contents=<full markdown report>
)
```

**Verify file was written:**

```
read_file(target_file="data/reports/{task_id}/report_draft.md")  # Should return the draft
```

```
=== Stage 2 Complete ===
Report Draft: data/reports/{task_id}/report_draft.md ✓ (written)

⚠️  CONTEXT BOUNDARY: Stage 3 will re-read all files for validation.
    Do not assume Stage 3 has access to Stage 2's working data.

Proceeding to Stage 3...
```

---

## Stage 3: Validation Gate (Diff-based)

**Objective**: Mechanically verify Stage 2 output against Stage 1 facts

**This is NOT self-reported validation. This is structural diff.**

### Step 3.1: Read inputs (MANDATORY)

**Stage 3 MUST re-read all files. Do not use data from previous stages.**

```
read_file(target_file="data/reports/{task_id}/report_draft.md")
read_file(target_file="data/reports/{task_id}/citation_index.json")
read_file(target_file="data/reports/{task_id}/evidence_pack.json")
```

**If any file read fails**: STOP. Previous stage did not complete correctly.

### Step 3.2: Extract cited URLs from draft

Parse `report_draft.md` and extract all:
- URLs in footnotes (after `Source:` or as DOI links)
- URLs in markdown links `[text](url)`
- DOIs mentioned as `DOI:10.xxxx/...`

### Step 3.3: Diff URLs against citation_index

```
cited_urls = extract_urls_from_draft(report_draft)
allowed_urls = set(citation_index.keys())

hallucinated_urls = cited_urls - allowed_urls
```

If `hallucinated_urls` is not empty → **FAIL**

### Step 3.4: Extract and verify effect sizes

For each number/percentage/range in tables (e.g., "0.5-0.8%", "12 RCTs", "-0.7 kg"):

1. Search all `evidence_chains[].fragment_snippet` for exact or near-exact match
2. If not found → add to `fabricated_numbers`

Acceptable variations:
- "0.5%" ↔ "0.5 percent" ↔ "0.50%"
- "0.5-0.8%" ↔ "0.5% to 0.8%"

Not acceptable:
- "0.9%" when only "0.8%" appears in fragments

### Step 3.5: Verify Lyra trace IDs

Every footnote must have `page_id=` and `fragment_id=`:

1. Parse each footnote for `Lyra: page_id={id}, fragment_id={id}`
2. Verify both IDs exist in `evidence_pack`
3. If missing → add to `missing_trace_ids`

### Step 3.6: Generate violation report

If any violations exist, write to `violation_report.json`:

```json
{
  "validation_timestamp": "...",
  "passed": false,
  "violations": {
    "hallucinated_urls": ["https://example.com/not-in-lyra"],
    "fabricated_numbers": [
      {
        "value": "0.9%",
        "context": "Table A row 2",
        "nearest_match": "0.8% (fragment_id: f_xyz)"
      }
    ],
    "missing_trace_ids": ["footnote 3", "footnote 7"]
  },
  "remediation": {
    "hallucinated_urls": "Remove URL or return to Stage 1 to add source",
    "fabricated_numbers": "Use nearest_match or mark as 'not extractable'",
    "missing_trace_ids": "Add Lyra trace IDs from evidence_pack"
  }
}
```

### Step 3.7: Gate decision

```
IF hallucinated_urls is not empty:
    FAIL — Remove URLs and re-run from Step 3.2

IF fabricated_numbers is not empty:
    OPTION A: Replace with nearest_match (if semantically equivalent)
    OPTION B: Replace with "not extractable from graph"
    OPTION C: Move entire claim to Appendix D

IF missing_trace_ids is not empty:
    FAIL — Add trace IDs from evidence_pack.citations[]
```

### Step 3.8: Validation passed

If all checks pass:

```
=== Stage 3: Validation Passed ===
- URLs checked: {n} (all in citation_index)
- Numbers verified: {n}
- Trace IDs present: {n}

Proceeding to Stage 4...
```

Update `audit_trail.json` with validation results.

---

## Stage 4: AI Enhancement

**Objective**: Add interpretation and polish to validated draft — **this is where AI reasoning happens**

### Step 4.1: Read validated draft (MANDATORY)

```
read_file(target_file="data/reports/{task_id}/report_draft.md")
read_file(target_file="data/reports/{task_id}/evidence_pack.json")  # For context
```

### Absolute constraints (still apply)

| Constraint | Rationale |
|------------|-----------|
| **No footnote changes** | Footnotes are validated facts |
| **No numeric changes** | Numbers are validated facts |
| **No new evidence claims** | Would bypass validation |
| **No URL changes** | URLs are validated |
| **No author/year invention** | Metadata is validated |

### Permitted operations (AI reasoning NOW allowed)

These operations transform the fact-only draft into polished prose:

| Operation | Scope | Example |
|-----------|-------|---------|
| **Interpretation in Contradictions** | Add 1 interpretive sentence per contradiction | "This discrepancy may reflect differences in baseline HbA1c across study populations." |
| **Synthesis prose improvement** | Rewrite for clarity, flow, readability | Convert bullet list → flowing paragraphs |
| **Verdict reasoning** | Explain why verdict is SUPPORTED/REFUTED/INCONCLUSIVE | "The preponderance of RCT evidence supports..." |
| **Uncertainty framing** | Highlight gaps, caveats, limitations | "Long-term data (>2 years) remain limited." |
| **Claim paraphrase** | Reword `claim_text` while preserving meaning | "reduces HbA1c" → "lowers HbA1c levels" |
| **Table header adjustment** | Improve readability | "Effect (range)" → "Effect Size (95% CI)" |

### Step 4.2: Transform sections

**Short Synthesis transformation**:

Input (Stage 2 draft):
```markdown
Observations from evidence:
- 5 sources support the hypothesis
- 2 sources show contradictory findings
- Key effect sizes: -0.5% to -0.8% HbA1c
- Evidence types: 1 GL, 2 MA, 2 RCT
- Gaps: no studies >2 years
```

Output (Stage 4 final):
```markdown
The hypothesis is supported by convergent evidence from five independent sources,
including two meta-analyses and an ADA guideline. Effect sizes cluster around
-0.5% to -0.8% HbA1c reduction, with remarkable consistency across study designs.
Two contradicting findings appear to reflect methodological differences rather than
true clinical heterogeneity (see Appendix B). The main limitation is the absence
of long-term data beyond 2 years.
```

**Contradictions transformation**:

Input (Stage 2 draft):
```markdown
| Claim A | Claim B | Source A | Source B |
|---------|---------|----------|----------|
| DPP-4i reduces HbA1c by 0.7% | DPP-4i reduces HbA1c by only 0.3% | [^1] | [^4] |
```

Output (Stage 4 final):
```markdown
| Claim A | Claim B | Source A | Source B | Interpretation |
|---------|---------|----------|----------|----------------|
| DPP-4i reduces HbA1c by 0.7% | DPP-4i reduces HbA1c by only 0.3% | [^1] | [^4] | This discrepancy may reflect higher baseline HbA1c in [^1] (9.2%) vs [^4] (7.8%). |
```

### Contradiction interpretation guideline

For each contradiction, add **one interpretive sentence** explaining the likely cause:

| Contradiction pattern | Example interpretation |
|----------------------|------------------------|
| Different populations | "This discrepancy may reflect higher baseline HbA1c in Study A (9.2% vs 7.8%)." |
| Different comparators | "Study A used placebo; Study B used active comparator (sulfonylurea)." |
| Different endpoints | "Study A reported FPG; Study B reported 2h-PPG." |
| Different follow-up | "The 52-week study showed regression to mean not seen at 12 weeks." |
| Low-quality vs high-quality | "The contradicting study was observational with potential confounding." |

If the cause is unclear from `fragment_snippet`, write: "Cause unclear from available evidence."

### Step 4.3: Write final report (MANDATORY)

**Single output location** (no duplicate file):

```
write_file(
  file_path="docs/reports/{YYYYMMDD_HHMMSS}_{short_topic}.md",
  contents=<AI-enhanced report>
)
```

### Step 4.4: Write audit trail (MANDATORY)

```
write_file(
  file_path="data/reports/{task_id}/audit_trail.json",
  contents=<JSON string of audit record>
)
```

Audit trail structure:

```json
{
  "task_id": "...",
  "hypothesis": "...",
  "stages_completed": ["stage0", "stage1", "stage2", "stage3", "stage4"],
  "stage3_violations_fixed": [],
  "artifacts": {
    "evidence_pack": "data/reports/{task_id}/evidence_pack.json",
    "citation_index": "data/reports/{task_id}/citation_index.json",
    "report_draft": "data/reports/{task_id}/report_draft.md",
    "report_final": "docs/reports/{YYYYMMDD_HHMMSS}_{short_topic}.md"
  },
  "completed_at": "..."
}
```

### Step 4.5: Summary output

```
=== Report Generation Complete ===

Final report: docs/reports/{YYYYMMDD_HHMMSS}_{short_topic}.md
Audit trail: data/reports/{task_id}/audit_trail.json

Summary:
- Claims cited: {n}
- Sources used: {n}
- Contradictions noted: {n}
- Validation iterations: {n}
- AI enhancements applied: synthesis prose, contradiction interpretations
```

---

## Context-window management

### Problem

Evidence graph may have 500+ claims, 1000+ fragments → exceeds context window.

### Solution: File-based handoff

Stage 1 writes everything to files. Stage 2 reads selectively:

1. **Always load first**: `metadata` + `claims[]` summary
2. **Load on demand**: `evidence_chains[]` for specific claim_ids being cited
3. **Reference lookup**: `citations[]` when writing each footnote

### Large evidence_pack handling

If `evidence_pack.json` > 100KB, Stage 1 may split into:

```
evidence_pack_meta.json      # metadata + claims summary only
evidence_pack_chains.json    # evidence_chains (may be large)
evidence_pack_citations.json # full citation metadata
```

Stage 2 loads `_meta.json` first, then selectively reads others as needed.

---

## Stable ID resolution (during Stage 1)

If a source is a raw PDF link without DOI/PMID/PMCID:

1. **Attempt ID extraction from URL**: If URL contains `10.` pattern → extract DOI
2. **Check page_title**: If title contains DOI/PMID → record it
3. **Mark resolution status** in `citation_index.json`:

```json
{
  "https://example.com/paper.pdf": {
    "page_id": "p_xyz",
    "has_doi": false,
    "has_pmid": false,
    "resolution_status": "unresolved",
    "main_body_eligible": false
  }
}
```

Sources with `main_body_eligible: false` are automatically moved to Appendix D in Stage 2.

---

## Finish the task

Before calling `stop_task`, ask the user:

- **A. Expand**: Continue evidence graph growth (add queries and/or more citation chasing), then regenerate report
- **B. Regenerate**: Re-run Stage 2 with different prioritization
- **C. Stop**: Finalize session (call `stop_task`)

Default behavior: **Do not call `stop_task` until user explicitly chooses C**.
