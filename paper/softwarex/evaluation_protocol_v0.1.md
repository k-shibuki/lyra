# Evaluation Protocol for Lyra Case Study

**Version**: 0.1 (Draft)
**Created**: 2025-12-28
**Status**: Pre-registration draft (pending Zenodo DOI)
**Authors**: Katsuya Shibuki (ORCID: 0000-0003-3570-5038)

---

## 1. Overview

This document defines the evaluation protocol for comparing Lyra against commercial AI research tools. The protocol is designed for pre-registration on Zenodo to ensure transparency and reduce bias.

### 1.1 Objectives

1. Quantitatively evaluate Lyra's evidence retrieval and attribution capabilities
2. Compare with commercial tools (Google Deep Research, ChatGPT Deep Research)
3. Assess factuality and provenance tracking in a medical research domain

### 1.2 Conflict of Interest Disclosure

The evaluator (K.S.) is the developer of Lyra. This conflict is mitigated by:
- Pre-registration of evaluation protocol before execution
- Automated metrics where possible
- Transparent reporting of all results (including negative findings)

---

## 2. Research Query

### 2.1 Primary Query (PICO Framework)

| Element | Specification |
|---------|---------------|
| **Population** | Type 2 diabetes patients receiving insulin therapy with HbA1c ≥7% |
| **Intervention** | DPP-4 inhibitors as add-on therapy |
| **Comparison** | Placebo as add-on (no additional active therapy) |
| **Outcomes** | Efficacy (HbA1c reduction) and safety (hypoglycemia risk) |

**Query Text**:
```
What is the efficacy and safety of DPP-4 inhibitors as add-on therapy
for type 2 diabetes patients receiving insulin therapy with HbA1c ≥7%?
```

### 2.2 Query Selection Rationale

| Criterion | Justification |
|-----------|---------------|
| **Domain Expertise** | Evaluator has 2 peer-reviewed meta-regression publications on incretin-related drugs |
| **Complexity** | Multi-faceted question spanning efficacy and safety domains |
| **Evidence Availability** | Sufficient RCTs and meta-analyses exist in PubMed, Cochrane, FDA/EMA |
| **Refutability** | The condition "HbA1c ≥7% despite insulin" creates room for nuanced evidence |

### 2.3 Decomposed Queries (for Lyra execution)

These queries will be submitted via `queue_searches`:

1. `DPP-4 inhibitors efficacy meta-analysis HbA1c`
2. `DPP-4 inhibitors safety cardiovascular outcomes`
3. `sitagliptin add-on therapy insulin-treated HbA1c 7 RCT`
4. `DPP-4 inhibitors vs GLP-1 agonists comparison`
5. `FDA DPP-4 inhibitors approval label`
6. `EMA DPP-4 inhibitors EPAR`
7. `DPP-4 inhibitors hypoglycemia risk systematic review`

---

## 3. Tools Under Evaluation

| Tool | Version/Access | MCP Client | Execution Date |
|------|----------------|------------|----------------|
| **Lyra** | v0.1.0 | Cursor AI (Claude 3.5 Sonnet) | TBD (same day) |
| **Google Deep Research** | Gemini Advanced ($20/mo) | N/A | TBD (same day) |
| **ChatGPT Deep Research** | ChatGPT Pro ($200/mo) | N/A | TBD (same day) |

### 3.1 Execution Conditions

- All tools receive the identical primary query (Section 2.1)
- Execution occurs on the same calendar day to control for temporal availability
- No manual intervention during tool execution (except CAPTCHA resolution for Lyra)
- Output is frozen immediately after completion

---

## 4. Evaluation Metrics

### 4.1 Layer 1: Retrieval Metrics (Fully Automated)

| Metric | Definition | Calculation | Data Source |
|--------|------------|-------------|-------------|
| **Source Count** | Number of unique information sources | `len(unique(URLs))` | All tools |
| **Primary Source Ratio** | Proportion of primary sources | `(PubMed + FDA/EMA + RCT) / Total` | Domain classification |
| **Academic Source Ratio** | Proportion with DOI | `DOI_present / Total` | DOI extraction |
| **Recency Ratio** | Proportion from 2020 onwards | `year >= 2020 / Total` | Publication year |
| **Domain Diversity** | Number of unique domains | `len(unique(domains))` | URL parsing |

**Lyra Data Source**: `get_materials()` output
- `claims[].sources[].url`
- `claims[].sources[].domain`
- `claims[].evidence[].doi`
- `claims[].evidence[].year`
- `summary.primary_source_ratio`

**Google/ChatGPT Data Source**: Manual extraction from output text

### 4.2 Layer 2: Factuality Metrics (Semi-Automated)

| Metric | Definition | Calculation | Automation |
|--------|------------|-------------|------------|
| **URL Validity** | URLs returning HTTP 200 | `valid_URLs / total_URLs` | Automated |
| **Quote Existence** | Cited text exists in source | `fuzzy_match(quote, page) > 0.8` | Semi-automated |
| **Claim Precision** | Accurate claims / Total claims | Expert review | Manual |
| **Claim Recall** | Accurate claims / Ground truth claims | Expert review | Manual |
| **Hallucination Count** | Factually incorrect claims | Expert review | Manual |

**Ground Truth Source**:
- Cochrane Systematic Review on DPP-4 inhibitors for T2DM
- FDA Prescribing Information (Januvia, Onglyza, Tradjenta, Nesina)
- EMA EPAR documents

### 4.3 Layer 3: Attribution Metrics (Lyra Differentiation)

| Metric | Definition | Lyra | Google | ChatGPT |
|--------|------------|------|--------|---------|
| **Provenance Depth** | Claim→Fragment→Page traceability | 100% | 0% | 0% |
| **NLI Stance Explicit** | SUPPORTS/REFUTES/NEUTRAL labeled | Yes | No | No |
| **Contradiction Count** | Explicit refuting evidence count | Measurable | N/A | N/A |
| **Uncertainty Score** | Bayesian posterior stddev | Available | N/A | N/A |
| **Controversy Score** | Evidence conflict degree | Available | N/A | N/A |

**Lyra Data Source**:
- `claims[].evidence[].relation` (supports/refutes/neutral)
- `claims[].has_refutation`
- `claims[].uncertainty`
- `claims[].controversy`
- `evidence_graph` (full provenance chain)

---

## 5. Expert Evaluation Protocol

### 5.1 Evaluator Credentials

| Item | Value |
|------|-------|
| **Evaluator ID** | K.S. |
| **Credentials** | PhD Pharmaceutical Sciences |
| **Relevant Publications** | 2 peer-reviewed meta-regression papers on incretin drugs |
| **Conflict of Interest** | Lyra developer (disclosed) |

### 5.2 Blinding

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **Tool Identity** | Single-blind (evaluator knows) | Lyra outputs include Evidence Graph structure |
| **Claim Order** | Randomized | Prevent order bias in accuracy assessment |

### 5.3 Sampling Strategy

| Evaluation Target | Sample Size | Method |
|-------------------|-------------|--------|
| **Claims (per tool)** | 30 | Random sample if >30, else full enumeration |
| **NLI Edges (Lyra only)** | 30 | Stratified by relation (10 SUPPORTS, 10 REFUTES, 10 NEUTRAL) |
| **Overall Quality** | 3 reports | Full report review |

### 5.4 Scoring Criteria

#### 5.4.1 Claim Accuracy (Binary)

| Score | Definition |
|-------|------------|
| **Correct** | Claim is factually accurate per Ground Truth |
| **Incorrect** | Claim contains factual error or is unverifiable |

#### 5.4.2 NLI Edge Accuracy (3-class)

| Score | Definition |
|-------|------------|
| **Correct** | NLI label matches expert judgment |
| **Incorrect** | NLI label contradicts expert judgment |
| **Ambiguous** | Expert cannot determine correct label |

#### 5.4.3 Overall Quality (5-point Likert)

| Score | Definition |
|-------|------------|
| 5 | Excellent - comprehensive, accurate, well-sourced |
| 4 | Good - minor gaps or inaccuracies |
| 3 | Adequate - some significant gaps |
| 2 | Poor - major gaps or inaccuracies |
| 1 | Unacceptable - unreliable for research use |

---

## 6. Statistical Analysis Plan

### 6.1 Descriptive Statistics

- Mean, SD, median, IQR for continuous metrics
- Counts and proportions for categorical metrics

### 6.2 Comparative Tests

| Comparison | Test | Justification |
|------------|------|---------------|
| Source counts | Chi-square | Count data |
| Ratio comparisons | Mann-Whitney U | Non-parametric, small sample |
| Accuracy rates | Fisher's exact | Small sample proportions |

### 6.3 Significance Level

- α = 0.05 (two-tailed)
- No correction for multiple comparisons (exploratory study)

---

## 7. Data Management

### 7.1 Output Preservation

| Artifact | Format | Storage |
|----------|--------|---------|
| Lyra `get_materials` output | JSON | `data/case_study/lyra_output.json` |
| Google Deep Research output | Markdown + Screenshots | `data/case_study/google/` |
| ChatGPT Deep Research output | Markdown + Screenshots | `data/case_study/chatgpt/` |
| Expert evaluation sheets | CSV | `data/case_study/evaluation/` |

### 7.2 Reproducibility

- Lyra execution: Full database snapshot preserved
- Commercial tools: Screenshots at each interaction step
- Evaluation: Raw scores before aggregation

---

## 8. Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Single evaluator | Potential bias | Pre-registration, automated metrics |
| Single query domain | Limited generalizability | Domain expertise ensures validity |
| Commercial tool opacity | Cannot control execution | Same-day execution, identical query |
| Lyra developer as evaluator | Conflict of interest | Transparent disclosure, automated metrics prioritized |

---

## 9. Timeline

| Phase | Activities | Status |
|-------|------------|--------|
| **Phase 1: Protocol Design** | This document | Complete |
| **Phase 2: Pre-registration** | Zenodo DOI | Pending |
| **Phase 3: E2E Completion** | Lyra debugging | In progress |
| **Phase 4: Execution** | All tools, same day | Pending |
| **Phase 5: Evaluation** | Expert review | Pending |
| **Phase 6: Analysis** | Statistical analysis | Pending |
| **Phase 7: Reporting** | SoftwareX manuscript | Pending |

---

## 10. Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2025-12-28 | Initial draft |

---

## Appendix A: Lyra Output Schema Reference

```json
{
  "claims": [{
    "id": "string",
    "text": "string",
    "confidence": "number (0-1)",
    "uncertainty": "number (Bayesian stddev)",
    "controversy": "number (conflict degree)",
    "evidence_count": "integer",
    "has_refutation": "boolean",
    "sources": [{
      "url": "string",
      "domain": "string",
      "domain_category": "string",
      "is_primary": "boolean"
    }],
    "evidence": [{
      "relation": "supports|refutes|neutral",
      "nli_confidence": "number",
      "year": "integer",
      "doi": "string|null",
      "venue": "string|null"
    }]
  }],
  "fragments": [{
    "id": "string",
    "text": "string (max 500 chars)",
    "source_url": "string",
    "context": "string",
    "is_primary": "boolean"
  }],
  "summary": {
    "total_claims": "integer",
    "verified_claims": "integer",
    "refuted_claims": "integer",
    "primary_source_ratio": "number"
  },
  "evidence_graph": {
    "nodes": [],
    "edges": []
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
import httpx
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class Layer1Metrics:
    """Retrieval metrics (fully automated)."""
    source_count: int
    primary_source_ratio: float
    academic_source_ratio: float
    recency_ratio: float
    domain_diversity: int

@dataclass
class Layer2Metrics:
    """Factuality metrics (semi-automated)."""
    url_validity_ratio: float
    urls_checked: int
    urls_valid: int

@dataclass
class Layer3Metrics:
    """Attribution metrics (Lyra-specific)."""
    provenance_depth: float  # Always 1.0 for Lyra
    contradiction_count: int
    avg_uncertainty: float
    avg_controversy: float
    nli_supports_count: int
    nli_refutes_count: int
    nli_neutral_count: int

async def evaluate_lyra_output(materials: dict[str, Any]) -> dict[str, Any]:
    """Evaluate Lyra get_materials output."""
    claims = materials.get("claims", [])

    # Layer 1: Retrieval
    all_urls: set[str] = set()
    all_domains: set[str] = set()
    doi_count = 0
    recent_count = 0
    total_evidence = 0

    for claim in claims:
        for src in claim.get("sources", []):
            if url := src.get("url"):
                all_urls.add(url)
            if domain := src.get("domain"):
                all_domains.add(domain)

        for ev in claim.get("evidence", []):
            total_evidence += 1
            if ev.get("doi"):
                doi_count += 1
            year = ev.get("year")
            if year and int(year) >= 2020:
                recent_count += 1

    layer1 = Layer1Metrics(
        source_count=len(all_urls),
        primary_source_ratio=materials.get("summary", {}).get("primary_source_ratio", 0.0),
        academic_source_ratio=doi_count / max(1, total_evidence),
        recency_ratio=recent_count / max(1, total_evidence),
        domain_diversity=len(all_domains),
    )

    # Layer 2: URL Validity Check
    valid_count = 0
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for url in list(all_urls)[:50]:  # Limit to 50 URLs
            try:
                resp = await client.head(url)
                if resp.status_code == 200:
                    valid_count += 1
            except Exception:
                pass

    layer2 = Layer2Metrics(
        url_validity_ratio=valid_count / max(1, min(len(all_urls), 50)),
        urls_checked=min(len(all_urls), 50),
        urls_valid=valid_count,
    )

    # Layer 3: Attribution
    refuted = sum(1 for c in claims if c.get("has_refutation"))
    uncertainties = [c.get("uncertainty", 0) for c in claims]
    controversies = [c.get("controversy", 0) for c in claims]

    supports = refutes = neutral = 0
    for claim in claims:
        for ev in claim.get("evidence", []):
            rel = ev.get("relation", "").lower()
            if rel == "supports":
                supports += 1
            elif rel == "refutes":
                refutes += 1
            elif rel == "neutral":
                neutral += 1

    layer3 = Layer3Metrics(
        provenance_depth=1.0,  # Lyra always 100%
        contradiction_count=refuted,
        avg_uncertainty=sum(uncertainties) / max(1, len(uncertainties)),
        avg_controversy=sum(controversies) / max(1, len(controversies)),
        nli_supports_count=supports,
        nli_refutes_count=refutes,
        nli_neutral_count=neutral,
    )

    return {
        "layer1_retrieval": asdict(layer1),
        "layer2_factuality": asdict(layer2),
        "layer3_attribution": asdict(layer3),
    }

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python evaluate.py <materials.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        materials = json.load(f)

    results = asyncio.run(evaluate_lyra_output(materials))
    print(json.dumps(results, indent=2))
```
