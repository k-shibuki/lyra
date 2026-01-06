# Evaluation Protocol for Lyra Case Study

**Version**: 0.1
**Created**: 2025-12-28
**Status**: Pre-registration draft (pending Zenodo DOI)
**Authors**: Katsuya Shibuki (ORCID: 0000-0003-3570-5038)

---

## 1. Overview

This document defines the evaluation protocol for comparing Lyra against Claude Research. The protocol uses **quantitative metrics only**, focusing on search quality, factuality, and verification cost across three research domains.

### 1.1 Objectives

1. Quantitatively evaluate Lyra's evidence retrieval capabilities across multiple domains
2. Compare with Claude Research using fair metrics achievable by both tools
3. Measure verification cost as a practitioner-relevant outcome

### 1.2 Evaluation Design Philosophy

This evaluation uses **quantitative metrics only**. Qualitative evaluation (expert rankings, Likert scales) is intentionally excluded for the following reasons:

| Reason | Explanation |
|--------|-------------|
| **Reproducibility** | Quantitative metrics can be independently verified |
| **Objectivity** | Removes evaluator bias and inter-rater reliability concerns |
| **Scalability** | Protocol can be extended to additional domains without evaluator coordination |

### 1.3 Conflict of Interest Disclosure

The author (K.S.) is the developer of Lyra. This conflict is mitigated by:

- Pre-registration of evaluation protocol before execution
- Automated metrics where possible
- Screen recordings for verification cost measurements
- Transparent reporting of all results (including negative findings)
- Ground truth derived from authoritative external sources

### 1.4 Fair Comparison Principle

**Critical**: All competitive metrics must be achievable by both tools. Architectural differences are reported descriptively, not as performance metrics.

```
Fair metrics: Both tools can achieve (compete on performance)
Descriptive features: Only one tool has (report as table, not metric)
```

---

## 2. Research Domains

Three domains are selected to demonstrate Lyra's capabilities across different research contexts and to leverage academic API coverage (Semantic Scholar, OpenAlex).

### 2.1 Domain Overview

| # | Domain | Focus | Lyra Advantage Hypothesis |
|:-:|--------|-------|---------------------------|
| 1 | Pharmacology | DPP-4 inhibitors | Author expertise; PubMed/FDA coverage |
| 2 | Computer Science | LLM hallucination | Semantic Scholar API strength |
| 3 | Health Science | Intermittent fasting | Contradicting evidence exists |

### 2.2 Domain 1: Pharmacology (DPP-4 Inhibitors)

| Element | Specification |
|---------|---------------|
| **Topic** | DPP-4 inhibitors as add-on therapy for insulin-treated T2DM |
| **PICO** | P: T2DM + insulin + HbA1c ≥7%; I: DPP-4 inhibitor; C: Placebo; O: Efficacy + safety |
| **Ground Truth Source** | Cochrane Review; FDA prescribing information; EMA EPAR |
| **Selection Rationale** | Author has 2 peer-reviewed meta-regression publications on incretin drugs |

### 2.3 Domain 2: Computer Science (LLM Hallucination)

| Element | Specification |
|---------|---------------|
| **Topic** | Techniques to reduce hallucination in large language models |
| **Focus** | Comparison of RAG, fine-tuning, and prompt engineering approaches |
| **Ground Truth Source** | Survey papers (2023-2024); citation counts; benchmark results |
| **Selection Rationale** | Semantic Scholar is strongest in CS/AI; high open-access rate |

### 2.4 Domain 3: Health Science (Intermittent Fasting)

| Element | Specification |
|---------|---------------|
| **Topic** | Evidence for intermittent fasting on weight loss and metabolic health |
| **Focus** | RCTs and systematic reviews; contradicting findings |
| **Ground Truth Source** | Cochrane/umbrella reviews; recent meta-analyses |
| **Selection Rationale** | Well-studied topic with both supporting and refuting evidence |

---

## 3. Evaluation Prompts

### 3.1 Design Philosophy

Prompts are intentionally **minimal and natural**. We do not explicitly request provenance tracking, academic sources, or contradiction detection. Differences in output quality reflect each tool's inherent capabilities.

### 3.2 Domain 1 Prompt (Pharmacology)

```
I'm a clinical pharmacist reviewing treatment options for a patient with
type 2 diabetes. They're currently on insulin but their HbA1c remains above 7%.

I'm considering adding a DPP-4 inhibitor. Could you summarize what the
clinical evidence says about efficacy and safety in this situation?
I'd like to focus on RCTs and meta-analyses.

Please provide a complete report in English.
```

### 3.3 Domain 2 Prompt (Computer Science)

```
I'm a machine learning researcher investigating methods to reduce
hallucination in large language models.

Could you summarize the current evidence comparing retrieval-augmented
generation (RAG), fine-tuning, and prompt engineering approaches?
I'd like to focus on peer-reviewed papers and benchmark results.

Please provide a complete report in English.
```

### 3.4 Domain 3 Prompt (Health Science)

```
I'm reviewing the evidence on intermittent fasting.

Could you summarize what the research says about its effects
on weight loss and metabolic health? Are there contradicting findings?

Please provide a complete report in English.
```

### 3.5 Lyra-Specific Suffix

For Cursor IDE with Lyra MCP, append only:

```
Use Lyra to conduct this research.
```

---

## 4. Tools Under Evaluation

| Tool | Version/Access | AI Backend | Monthly Cost |
|------|----------------|------------|--------------|
| **Lyra** | v0.1.0 + Cursor Pro | Claude Opus 4.5 + Local ML | $16/mo |
| **Claude Research** | Claude Pro | Claude Opus 4.5 | $17/mo |

**Same Model Comparison**: Both tools use Claude Opus 4.5 as the reasoning engine, isolating architectural differences:

- **Lyra**: Thinking (cloud) + Working (local ML, Evidence Graph, Academic APIs)
- **Claude Research**: Fully cloud-based research and synthesis

### 4.1 Lyra Execution Environment

**Important**: Lyra is not a standalone tool. It operates as an MCP (Model Context Protocol) server that requires an AI assistant (MCP client) to orchestrate its tools.

Lyra provides a reusable custom instruction ([`navigate`](navigate.md.example)) that can be used with any MCP-compatible client:
- **Cursor IDE**: As a Cursor Command (`.cursor/commands/navigate.md`)
- **Claude Desktop**: As a Skill (Settings → Skills)
- **Other MCP clients**: As system prompt or custom instruction

**For this case study**, we use **Cursor IDE with Cursor Commands**:

| Component | Role |
|-----------|------|
| **Cursor IDE** | Host environment; provides AI assistant (Claude Opus 4.5) |
| **Lyra MCP Server** | Executes search→fetch→extract→NLI→store pipeline |
| **`navigate` Command** | Cursor Command defining workflow ([source](navigate.md.example)) |

**Execution Stack**:
```
User Query
    ↓
Cursor AI (Claude Opus 4.5) — Thinking layer: plans queries, analyzes results
    ↓ MCP tool calls
Lyra Server — Working layer: executes searches, builds Evidence Graph
    ↓
Report (synthesized by Cursor AI from Evidence Graph)
```

### 4.2 Execution Conditions

- Both tools receive identical prompts (Sections 3.2-3.4)
- Lyra additionally receives the Lyra-Specific Suffix (Section 3.5)
- All domains executed on the same calendar day
- No manual intervention during execution (except CAPTCHA resolution for Lyra)
- Screen recording enabled for verification cost measurement
- Output frozen immediately after completion

---

## 5. Evaluation Metrics

### 5.1 Layer 1: Search Quality (Automated)

All metrics are achievable by both tools.

| Metric | Definition | Calculation |
|--------|------------|-------------|
| **Recall@GT** | Proportion of Ground Truth papers found | `found ∩ GT / GT` |
| **Source Count** | Number of unique sources cited | `len(unique(URLs))` |
| **Academic Ratio** | Proportion of sources with DOI | `DOI_present / total` |
| **Recency Ratio** | Proportion from 2020 onwards | `year >= 2020 / total` |

### 5.2 Layer 2: Factuality (Semi-Automated)

| Metric | Definition | Calculation |
|--------|------------|-------------|
| **URL Validity** | URLs returning HTTP 200 | `valid / total` |
| **Quote Verifiability** | Cited text exists in source | `fuzzy_match > 0.8` |
| **Claim Accuracy** | Claims accurate vs Ground Truth | `accurate / total` |

### 5.3 Layer 3: Verification Cost (Author-Measured, Recorded)

| Metric | Definition | Measurement |
|--------|------------|-------------|
| **Total Verification Time** | Time to verify 10 sampled claims | Stopwatch (from recording) |
| **Verification Success Rate** | Claims verified within 2 min each | `found / attempted` |

**Transparency Measures**:
- Full screen recordings provided as Supplementary Video
- Raw timing data provided as Supplementary Data
- Timeout: 2 minutes per claim (mark as "not found" if exceeded)

**Protocol**:
1. Sample 10 claims randomly from each tool's output (per domain)
2. For each claim, attempt to locate the supporting passage in the cited source
3. Record: elapsed time, success/failure
4. Stop after 2 minutes per claim

### 5.4 Architectural Comparison (Descriptive Only)

Structural differences are reported as a descriptive table, **not as competitive metrics**.

| Capability | Lyra | Claude Research | Notes |
|------------|:----:|:---------------:|-------|
| Evidence Graph structure | ✓ | — | Claim→Fragment→Page links |
| Explicit stance labels | ✓ | — | SUPPORTS/REFUTES/NEUTRAL |
| Local ML processing | ✓ | — | NLI, embedding, reranking |
| Academic API integration | ✓ | — | Semantic Scholar, OpenAlex |
| Human-correctable outputs | ✓ | — | Feedback tool |

*Note: The presence of a capability does not imply superiority. These are structural differences, reported for transparency.*

---

## 6. Ground Truth Definition

### 6.1 Domain 1: Pharmacology

| Source | Content | Papers |
|--------|---------|:------:|
| Cochrane Systematic Review | DPP-4 inhibitors for T2DM | Key RCTs |
| FDA Prescribing Information | Januvia, Onglyza, Tradjenta, Nesina | 4 |
| EMA EPAR documents | European assessment reports | 4 |
| **Total Ground Truth Set** | | ~15-20 |

### 6.2 Domain 2: Computer Science

| Source | Content | Papers |
|--------|---------|:------:|
| Survey: "Hallucination in LLMs" (2024) | Comprehensive technique review | Key papers |
| Semantic Scholar: Top cited | RAG, fine-tuning, prompt engineering | Top 10 each |
| Benchmark papers | TruthfulQA, HaluEval, etc. | ~5 |
| **Total Ground Truth Set** | | ~25-30 |

### 6.3 Domain 3: Health Science

| Source | Content | Papers |
|--------|---------|:------:|
| Cochrane Review on IF | Systematic review | Key RCTs |
| Umbrella reviews (2022-2024) | Meta-analyses of meta-analyses | ~5 |
| Contradicting studies | Both positive and negative findings | ~5 each |
| **Total Ground Truth Set** | | ~15-20 |

### 6.4 Ground Truth Preparation

1. Author prepares Ground Truth lists **before** tool execution
2. Lists are sealed (hash recorded) before evaluation
3. Ground Truth sources are documented in Supplementary Material

---

## 7. Statistical Analysis Plan

### 7.1 Descriptive Statistics

- Mean, SD, median, IQR for continuous metrics
- Counts and proportions for categorical metrics
- Per-domain and cross-domain aggregation

### 7.2 Cross-Domain Comparison

| Comparison | Aggregation |
|------------|-------------|
| **Recall@GT** | Mean across 3 domains |
| **Academic Ratio** | Mean across 3 domains |
| **Verification Time** | Mean across 3 domains |

### 7.3 Reporting

Results are reported as:
1. Per-domain tables with all metrics
2. Cross-domain summary table
3. Architectural comparison table (descriptive)

No statistical significance tests are performed (descriptive study design).

---

## 8. Data Management

### 8.1 Output Preservation

| Artifact | Format | Storage |
|----------|--------|---------|
| Lyra `get_materials` output (×3 domains) | JSON | `data/case_study/lyra/` |
| Claude Research output (×3 domains) | Markdown + Screenshots | `data/case_study/claude/` |
| Screen recordings (verification) | MP4 | `data/case_study/recordings/` |
| Ground Truth lists (sealed) | JSON + SHA256 | `data/case_study/ground_truth/` |

### 8.2 Supplementary Materials for Publication

| Material | Description | Availability |
|----------|-------------|--------------|
| S1 | Ground Truth paper lists (3 domains) | With manuscript |
| S2 | Raw Lyra output JSON (3 domains) | Zenodo archive |
| S3 | Screen recordings (verification) | Zenodo archive |
| S4 | Evaluation script (Python) | GitHub repository |

---

## 9. Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Author-measured verification cost | Potential expectation bias | Screen recordings for independent verification |
| Commercial tool opacity | Cannot control Claude Research execution | Same-day execution, identical prompts |
| Ground Truth completeness | May miss relevant papers | Multiple authoritative sources per domain |
| Single evaluator for Claim Accuracy | Subjective judgment | Clear criteria documented; edge cases noted |
| Lyra developer as author | Conflict of interest | Pre-registration; automated metrics; recordings |

---

## 10. Timeline

| Phase | Activities | Status |
|-------|------------|--------|
| **Phase 1: Protocol Design** | This document | Complete |
| **Phase 2: Ground Truth Preparation** | 3 domain paper lists | Pending |
| **Phase 3: Pre-registration** | Zenodo DOI | Pending |
| **Phase 4: E2E Completion** | Lyra debugging | In progress |
| **Phase 5: Execution** | All tools, all domains, same day | Pending |
| **Phase 6: Metric Calculation** | Automated + manual verification | Pending |
| **Phase 7: Reporting** | SoftwareX manuscript | Pending |

---

## 11. Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2025-12-28 | Initial draft |
| 0.2 | 2025-12-29 | Added independent evaluators; blinding protocol; score sheet |
| 0.3 | 2025-12-29 | **Major revision**: Removed qualitative evaluation entirely; expanded to 3 domains; redesigned metrics for fairness; architectural differences now descriptive only |
| 0.4 | 2026-01-06 | Added Lyra execution environment details (Section 4.1); linked `navigate` command |

---

## Appendix A: Lyra Output Schema Reference

```json
{
  "claims": [{
    "id": "string",
    "text": "string",
    "confidence": "number (0-1)",
    "uncertainty": "number (Bayesian stddev)",
    "evidence_count": "integer",
    "sources": [{
      "url": "string",
      "domain": "string",
      "doi": "string|null"
    }]
  }],
  "fragments": [{
    "id": "string",
    "text": "string (max 500 chars)",
    "source_url": "string"
  }],
  "summary": {
    "total_claims": "integer",
    "primary_source_ratio": "number"
  }
}
```

---

## Appendix B: Evaluation Script (Python)

```python
"""
Automated evaluation metrics for Lyra case study.
Run after get_materials() output is collected.
"""

import asyncio
import json
import sys
from dataclasses import asdict, dataclass

import httpx


@dataclass
class SearchQualityMetrics:
    """Layer 1: Search quality metrics."""

    source_count: int
    academic_ratio: float
    recency_ratio: float
    recall_at_gt: float  # Requires ground truth


@dataclass
class FactualityMetrics:
    """Layer 2: Factuality metrics."""

    url_validity_ratio: float
    urls_checked: int
    urls_valid: int


async def evaluate_output(
    materials: dict,
    ground_truth_dois: set[str],
) -> dict:
    """Evaluate tool output against ground truth."""
    claims = materials.get("claims", [])

    # Collect all DOIs and URLs
    all_urls: set[str] = set()
    all_dois: set[str] = set()
    recent_count = 0
    total_sources = 0

    for claim in claims:
        for src in claim.get("sources", []):
            if url := src.get("url"):
                all_urls.add(url)
            if doi := src.get("doi"):
                all_dois.add(doi.lower())
            total_sources += 1

            year = src.get("year")
            if year and int(year) >= 2020:
                recent_count += 1

    # Layer 1: Search Quality
    recall = len(all_dois & ground_truth_dois) / max(1, len(ground_truth_dois))

    layer1 = SearchQualityMetrics(
        source_count=len(all_urls),
        academic_ratio=len(all_dois) / max(1, total_sources),
        recency_ratio=recent_count / max(1, total_sources),
        recall_at_gt=recall,
    )

    # Layer 2: URL Validity
    valid_count = 0
    urls_to_check = list(all_urls)[:50]

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for url in urls_to_check:
            try:
                resp = await client.head(url)
                if resp.status_code == 200:
                    valid_count += 1
            except Exception:
                pass

    layer2 = FactualityMetrics(
        url_validity_ratio=valid_count / max(1, len(urls_to_check)),
        urls_checked=len(urls_to_check),
        urls_valid=valid_count,
    )

    return {
        "layer1_search_quality": asdict(layer1),
        "layer2_factuality": asdict(layer2),
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python evaluate.py <materials.json> <ground_truth.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        materials = json.load(f)

    with open(sys.argv[2]) as f:
        gt_data = json.load(f)
        ground_truth_dois = set(d.lower() for d in gt_data.get("dois", []))

    results = asyncio.run(evaluate_output(materials, ground_truth_dois))
    print(json.dumps(results, indent=2))
```

