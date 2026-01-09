# lyra-report

## Purpose

Generate a **decision-first**, **traceable** research report from the **Lyra Evidence Graph**.

### Non-negotiables (control > brevity)

- **Citations**: Only cite sources that exist in the Lyra graph (claim→fragment→page→URL).
- **No web-search evidence**: Web search is for query design only.
- **No out-of-graph metadata**: Author/year/title/evidence-type labels must be **extractable from the Lyra graph rows you fetched**. If a field is not extractable, write `unknown` (do **not** guess).
- **No “good enough” shortcuts**: Every key claim in the body must have a footnote.
- **Prefer stable IDs**: DOI / PMID / PMCID over raw PDF links.
- **Scope guard**: Keep the report focused on the hypothesis’ outcomes; off-scope sections go to Appendix.

### Anti-hallucination gate (structural; mandatory)

**Citations must be produced by a 2-step pipeline, not free-form writing:**

1) **Extract** citation fields from Lyra via SQL (URL/title/fragment snippet + IDs).  
2) **Render** footnotes by **only templating those extracted fields**.

Hard rules:
- **Never** introduce author names, years, journal names, or effect sizes unless they appear in the extracted Lyra rows.
- If the template asks for a field that is missing in Lyra, fill with `unknown` and (if needed) move the claim to Appendix per eligibility rules.
- Do not write phrases like “verified externally”. External verification is prohibited for report content.

### Context-window safety (mandatory)

This command must not pull “everything” at once.

- **Never call views without an explicit `limit`**.
- **Never dump the full reference list into the chat context in one shot**.
  Paginate and **append directly to the output report file** instead.
- Prefer **two-pass reporting**:
  - Pass 1: Fetch only what is needed to decide structure (top claims/sources + contradictions).
  - Pass 2: Fetch provenance/details **only for the claims you will cite**.

---

## Inputs (Lyra-only)

Run these first; the report must be based on the outputs.

### Evidence extraction (required)

```
query_view(view_name="v_claim_evidence_summary", task_id=task_id, limit=50)
query_view(view_name="v_contradictions", task_id=task_id, limit=30)
query_view(view_name="v_unsupported_claims", task_id=task_id, limit=30)
```

### Source selection + freshness (required)

```
query_view(view_name="v_source_impact", task_id=task_id, limit=10)
query_view(view_name="v_evidence_timeline", task_id=task_id)
query_view(view_name="v_outdated_evidence", task_id=task_id, limit=30)
```

### Full reference list (required)

Fetch in pages and append to the report file (do not hold the entire list in memory):

**Page 1**

```
query_sql(sql="SELECT DISTINCT p.url, p.title
               FROM pages p
               JOIN fragments f ON f.page_id = p.id
               JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
               JOIN claims c ON c.id = e.target_id AND e.target_type = 'claim'
               WHERE c.task_id = '{task_id}'
               ORDER BY p.title, p.url",
          options={"limit": 50})
```

**Next pages (cursor-based pagination)**  
Use the last row from the previous page as `(last_title, last_url)`:

```
query_sql(sql="SELECT DISTINCT p.url, p.title
               FROM pages p
               JOIN fragments f ON f.page_id = p.id
               JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
               JOIN claims c ON c.id = e.target_id AND e.target_type = 'claim'
               WHERE c.task_id = '{task_id}'
                 AND (p.title > '{last_title}'
                      OR (p.title = '{last_title}' AND p.url > '{last_url}'))
               ORDER BY p.title, p.url",
          options={"limit": 50})
```

### Provenance support (optional but recommended for tighter citations)

Use claim origins to tie claims to specific pages/fragments. This view includes bibliographic metadata:

```
query_view(view_name="v_claim_origins", task_id=task_id, limit=200)
```

**Available columns** (for academic sources): `claim_id`, `claim_text`, `page_id`, `page_url`, `work_title`, `work_year`, `work_venue`, `work_doi`, `author_display`

### Provenance drill-down (required for claims you cite)

Do **not** fetch the whole evidence chain. For each claim you will cite in the main body,
fetch provenance to `page.url` in small slices.

Template (run once per claim_id):

```
query_sql(sql="SELECT
                 c.id as claim_id,
                 c.claim_text,
                 p.title as page_title,
                 p.url as page_url,
                 p.domain as page_domain,
                 f.id as fragment_id,
                 f.heading_context as fragment_heading,
                 substr(f.text_content, 1, 300) as fragment_preview
               FROM claims c
               JOIN edges e ON e.target_id = c.id AND e.target_type = 'claim'
               JOIN fragments f ON f.id = e.source_id AND e.source_type = 'fragment'
               JOIN pages p ON p.id = f.page_id
               WHERE c.task_id = '{task_id}' AND c.id = '{claim_id}'
               ORDER BY p.domain, p.url",
          options={"limit": 20})
```

### Citation metadata extraction (mandatory for each URL you will cite)

Before you write a footnote `[^n]`, you must extract the footnote fields for that URL from Lyra.
Run this **once per cited URL** (small, deterministic, and traceable):

```
query_sql(sql="SELECT
                 p.id as page_id,
                 p.url as page_url,
                 p.title as page_title,
                 p.domain as page_domain,
                 f.id as fragment_id,
                 f.heading_context as fragment_heading,
                 substr(f.text_content, 1, 600) as fragment_snippet,
                 w.year as work_year,
                 w.venue as work_venue,
                 w.doi as work_doi,
                 CASE
                   WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 0 THEN NULL
                   WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 1
                     THEN (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id LIMIT 1)
                   ELSE (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id ORDER BY wa.position LIMIT 1) || ' et al.'
                 END as author_display
               FROM pages p
               JOIN fragments f ON f.page_id = p.id
               LEFT JOIN works w ON w.canonical_id = p.canonical_id
               WHERE p.url = '{page_url}'
               ORDER BY length(f.text_content) DESC",
          options={"limit": 3})
```

**Rendering rule**: Footnote fields must come from the returned columns.
- **Year**: Use `work_year` if present; otherwise check `page_title` or `fragment_snippet`; fallback to `unknown`
- **Author/Org**: Use `author_display` if present; otherwise check `page_title` or `fragment_snippet`; fallback to `unknown`
- **Venue**: Use `work_venue` if available (for academic sources)
- **DOI**: Use `work_doi` if available (preferred stable ID for academic papers)

---

## Output format (Markdown)

**Output path**: `docs/reports/{YYYYMMDD_HHMMSS}_{short_topic}.md`

Example: `docs/reports/20260107_231500_dpp4_insulin_addon.md`

### 0) Header (required)

- Date
- task_id
- Hypothesis (verbatim)

### 1) **1-minute summary** (required, top of file)

**3–6 lines + 1 mini table**. This must be “decision-ready” without scrolling.

**Rules**
- Include: population, comparator, core outcomes (HbA1c / hypoglycemia / weight), representative effect-size **range**, and 1–2 caveats (follow-up, baseline HbA1c, insulin regimen).
- If an effect size is not available from Lyra claims/fragments, write “not extractable from graph” explicitly (do not infer).

Mini table (required):

| Outcome | Effect (range) | Population / Comparator | Evidence type | Notes |
|---|---:|---|---|---|

### 2) Verdict (required)

Format:
- `{hypothesis}: SUPPORTED / REFUTED / INCONCLUSIVE (confidence: X.XX)`

**Define confidence**

- **Lyra Conf** = `bayesian_truth_confidence` (0–1) derived from cross-source NLI evidence edges.
- **0.50 means “no net cross-source signal yet”**, not “50% efficacy”.
- Prefer effect sizes + evidence type for decisions; use Lyra Conf as a traceability aid.

### 3) Key Findings (required) — **exactly 3 tables**

Only these tables appear in the main body. Everything else goes to Appendix.

#### Table A: Efficacy (required)

| Outcome | Effect (range) | Population / Comparator | Evidence type (GL/SR/MA/RCT) | Citation |
|---|---:|---|---|---|

Include only:
- HbA1c
- FPG/PPG (optional if available)
- Insulin dose change (optional if available)

#### Table B: Safety (required)

| Outcome | Direction | Population / Comparator | Evidence type | Citation |
|---|---|---|---|---|

Include only:
- Hypoglycemia
- Weight
- Major adverse events relevant to the hypothesis’ safety framing (if present)

**Do NOT add cardioprotection sections** unless the hypothesis explicitly includes CV outcomes.

#### Table C: Applicability / Practical notes (required)

| Topic | Practical implication | Evidence type | Citation |
|---|---|---|---|

Include only:
- CKD / elderly / dose adjustments (if available)
- Where DPP-4i fits vs alternatives *as applicability*, not as a new outcome claim

### 4) Short synthesis (required, max 8 lines)

No repetition of the 1-minute summary. Only:
- Why the verdict is what it is
- What would change the decision (key uncertainty)

---

## Citations (Markdown footnotes) — mandatory style

### Rule 1: Every important claim must have a footnote

Attach `[^n]` to each **claim sentence** (not only in a table source cell).

### Rule 2: Footnote content must be minimal but sufficient

Each footnote must include:
- Year + first author or organization (if not extractable from Lyra: write `unknown`)
- Short title
- Evidence type label: `Guideline` / `Meta-analysis` / `Systematic review` / `RCT` / `Observational` / `Secondary` / `Educational` / `Retracted`
- Stable identifier (prefer): `DOI:` / `PMID:` / `PMCID:`
- URL (must be in Lyra `pages` list)
- Location hint: section/table/figure/page (if available from fragment/PDF)
- **Lyra trace IDs**: `page_id` + `fragment_id` (mandatory)

Template:

```markdown
[^1]: {Author/Org|unknown, Year|unknown} {Short title} ({Evidence type}; {Reliability label}). {ID}. Source: `{URL}`. Location: {location_hint|unknown}. Lyra: page_id={page_id}, fragment_id={fragment_id}.
```

### Rule 3: Prefer stable IDs; avoid raw PDF links for key claims

- Prefer citing a DOI/PMID/PMCID landing page over `.../article-pdf/...` or `...pdf`.
- If the only available Lyra page is a raw PDF link, still cite it, but **add** the DOI/PMID/PMCID if present in the URL or title.

**Mandatory: Stable-ID resolution procedure (no exceptions)**

If a claim would appear in the **main body** but its best source is a raw PDF link **without** DOI/PMID/PMCID:

1) **Attempt ID extraction (deterministic)**
   - If the PDF URL contains a DOI (`10.` pattern) → cite that DOI via `queue_targets(kind="doi")`
   - Else if the Lyra page title contains a DOI/PMID/PMCID → cite the corresponding landing page by queueing it (DOI fast path preferred)

2) **If still missing, resolve via Lyra search (1 pass only)**
   - Queue up to **2** additional Lyra queries to find the stable landing page:
     - `{exact_title} DOI`
     - `{exact_title} PMID OR PMCID`
   - Then wait for completion and re-check sources:
     ```
     get_status(task_id=task_id, wait=180)
     query_sql(...)  # Full reference list
     ```

3) **Main-body eligibility rule**
   - If, after step (2), no DOI/PMID/PMCID landing page exists in the Lyra `pages` list for that work:
     - Set `{ID: unknown}`
     - Move that claim to **Appendix D (Secondary / Unresolved ID)**.
     - Do **not** use it to support the verdict in the main body.

### Rule 4: Reliability labels and exclusions

- **Wikipedia / general blogs / education pages**: allowed only for background in Appendix; **never** as evidence for the main verdict.
- **Retracted** sources: must be listed under Appendix “Excluded / Retracted” and must not support the main verdict.

### Citation audit (mandatory; structural)

Before finalizing the report, run a citation audit for every footnote URL you used:
- Confirm the URL exists in the “Full reference list” outputs for this task.
- Confirm you have a `page_id` + `fragment_id` row from **Citation metadata extraction** for that URL.
- If any footnote lacks extractable `{Author/Org}` or `{Year}`, set them to `unknown` (do not “fix” by guessing).

---

## Appendix (required, keep at end)

### A) Methodology (required)

- Steps executed (Step 1–4)
- Query set used (verbatim)
- Citation-chasing iterations count

### B) Contradictions (required)

Summarize from `v_contradictions` with pointers to footnotes.

### C) Full references (required)

Paste the full list from the “Full reference list” SQL output.

### D) Excluded / Retracted / Secondary (required if present)

List excluded sources with reasons and ensure none were used for main claims.

**Include a subsection**: “Unresolved ID (PDF-only)”
- List claims moved here by Rule 3 step (3)
- Each must include the raw PDF URL and why a stable ID could not be found via the procedure

## Finish the task

Before calling `stop_task`, ask the user:
- **A. Expand**: continue evidence graph growth (add queries and/or more citation chasing)
- **B. Stop**: finalize session (call `stop_task`)

Default behavior: **do not call `stop_task` until user chooses B**.
