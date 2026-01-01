---
title: "Lyra: Local-First Evidence Synthesis for AI-Collaborative Research"
journal: SoftwareX
type: Original Software Publication
authors:
  - name: Katsuya Shibuki
    orcid: 0000-0003-3570-5038
    affiliation: Independent Researcher
date: 29 December 2025
---

<!--
================================================================================
SOFTWAREX SUBMISSION REQUIREMENTS CHECKLIST
================================================================================
Status: DRAFT (Pre-E2E completion)

FORMAT REQUIREMENTS:
  [x] Use SoftwareX template structure
  [ ] Convert to official Word/LaTeX template before submission
  [ ] Max 6 pages (excluding metadata, tables, figures, references)
  [ ] Max 3000 words for main body (sections 1-5)

REQUIRED SECTIONS:
  [x] 1. Motivation and significance
  [x] 2. Software description (CONDENSED - details in JOSS paper)
  [x] 3. Illustrative examples (3-domain quantitative evaluation)
  [x] 4. Impact (quantitative comparison)
  [x] 5. Conclusions
  [x] Required Metadata Table

SOFTWARE REQUIREMENTS:
  [x] Open source with OSI-approved license (MIT)
  [x] Code publicly available (GitHub)
  [ ] Permanent archive (Zenodo DOI) - TODO before submission

EVALUATION DESIGN (v0.3):
  - Quantitative metrics only (no qualitative evaluation)
  - 3 domains: Pharmacology, Computer Science, Health Science
  - Fair metrics achievable by both tools
  - Architectural differences reported descriptively

BLOCKING ITEMS BEFORE SUBMISSION:
  1. [ ] Complete E2E debugging
  2. [ ] Prepare Ground Truth for 3 domains
  3. [ ] Execute case studies (Lyra + Claude Research)
  4. [ ] Create Zenodo archive with DOI
  5. [ ] Convert to official template
  6. [ ] Review word count (target: <3000 words)
================================================================================
-->

# Required Metadata

<!-- TODO: Update version and DOI before submission -->

| Item | Description |
|------|-------------|
| Current code version | v0.1.0 |
| Permanent link to code/repository | https://github.com/k-shibuki/lyra |
| Permanent link to reproducible capsule | TODO: Zenodo DOI |
| Legal code license | MIT |
| Code versioning system | git |
| Software code language | Python 3.14 |
| Compilation requirements | NVIDIA GPU (8GB+ VRAM), CUDA 12.x |
| Operating system | Windows 11 + WSL2 (Ubuntu 22.04/24.04) |
| RAM | 32GB+ (WSL2 allocation) |
| Storage | ~25GB (ML containers ~18GB + Ollama models ~5GB) |
| Dependencies | See pyproject.toml |
| Support email | TODO |

# 1. Motivation and Significance

## 1.1 Scientific Background

AI-assisted research tools have transformed how researchers gather and synthesize information. Large language models (LLMs) such as GPT-4 and Claude can search the web, summarize documents, and draft literature reviews. However, these tools present fundamental challenges for rigorous research:

1. **Hallucination risk**: LLMs generate plausible but unverifiable claims without traceable evidence chains
2. **Privacy concerns**: Research queries and collected materials are transmitted to cloud services
3. **Reproducibility gap**: The path from source to conclusion is opaque and non-reproducible
4. **Cost barriers**: Commercial API usage scales with research volume, disadvantaging independent researchers

## 1.2 Problem Statement

Researchers require tools that combine AI reasoning capabilities with verifiable evidence trails. The specific problems Lyra addresses are:

- **P1**: How can researchers leverage frontier AI reasoning while maintaining data sovereignty?
- **P2**: How can evidence provenance be tracked from source documents through to synthesized claims?
- **P3**: How can the verification cost of AI-generated research reports be reduced?

## 1.3 Significance

Lyra introduces a "thinking-working separation" architecture that addresses these problems. The key insight is that frontier AI models excel at strategic reasoning (formulating queries, synthesizing findings), while mechanical tasks (fetching, extracting, classifying) can be performed locally with smaller models. This separation enables:

- Full local execution of data processing (zero operational expenditure)
- Traceable evidence graphs linking claims to source fragments
- Reduced verification cost through fragment-level citations
- Human-in-the-loop correction with continuous improvement path

The contribution is not classification accuracy per se, but rather the **architectural design** that makes evidence relationships explicit and verifiable.

# 2. Software Description

This section provides an overview of Lyra's architecture. For detailed implementation specifications, see the companion JOSS paper [JOSS-REF].

## 2.1 Architecture Overview

Lyra implements the Model Context Protocol (MCP), enabling any compatible AI assistant to invoke research tools:

```
┌─────────────────────────────────────────────────────────────┐
│  MCP Client (Claude Desktop / Cursor AI / Zed)              │
│  • Research strategy formulation                            │
│  • Query design and prioritization                          │
│  • Evidence synthesis and report composition                │
└─────────────────────────────────────────────────────────────┘
                              │ MCP Protocol (stdio)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Lyra MCP Server                                            │
│  • Unified search (browser SERP + academic APIs in parallel)│
│  • Content extraction and NLI stance classification         │
│  • Evidence graph construction with Bayesian confidence     │
└─────────────────────────────────────────────────────────────┘
```

## 2.2 Key Capabilities

| Capability | Description |
|------------|-------------|
| **Unified Search** | All queries execute browser SERP and academic APIs (Semantic Scholar, OpenAlex) in parallel with DOI-based deduplication |
| **NLI Classification** | DeBERTa-v3 classifies fragment-claim relationships as SUPPORTS, REFUTES, or NEUTRAL; human-correctable via feedback tool |
| **Evidence Graph** | Directed graph linking Claims ← Fragments ← Pages with provenance metadata |
| **Bayesian Confidence** | Beta distribution updating incorporates both supporting and refuting evidence |
| **Feedback Loop** | User corrections are immediately reflected and accumulated for future model adaptation |
| **Human-in-the-Loop** | CAPTCHA/authentication queued for batch resolution without blocking pipeline |

## 2.3 MCP Tool Interface

Lyra exposes 10 MCP tools for research operations:

| Tool | Purpose |
|------|---------|
| `create_task` | Initialize research session with hypothesis |
| `queue_searches` | Submit queries for background execution |
| `get_status` | Monitor progress with long-polling support |
| `stop_task` | Finalize session (graceful or immediate) |
| `get_materials` | Retrieve evidence graph for report composition |
| `feedback` | Submit corrections (domain/claim/edge level) |

# 3. Illustrative Examples

## 3.1 Evaluation Design

To evaluate Lyra's capabilities, we conducted case studies across three research domains, comparing Lyra against Claude Research—both using the same AI model (Claude Opus 4.5).

### 3.1.1 Domain Selection

| # | Domain | Query Focus | Selection Rationale |
|:-:|--------|-------------|---------------------|
| 1 | **Pharmacology** | DPP-4 inhibitors for T2DM | Author expertise; PubMed/FDA coverage |
| 2 | **Computer Science** | LLM hallucination mitigation | Semantic Scholar API strength |
| 3 | **Health Science** | Intermittent fasting efficacy | Contradicting evidence exists |

### 3.1.2 Evaluation Metrics

All competitive metrics are achievable by both tools:

| Layer | Metric | Definition |
|:-----:|--------|------------|
| L1 | Recall@GT | Proportion of Ground Truth papers found |
| L1 | Academic Ratio | Proportion of sources with DOI |
| L2 | URL Validity | Proportion of valid URLs |
| L2 | Quote Verifiability | Proportion of quotes found in source |
| L3 | Verification Time | Time to verify 10 sampled claims |
| L3 | Verification Success | Claims verified within 2 min each |

## 3.2 Domain 1: Pharmacology (DPP-4 Inhibitors)

**Research Question**: What is the efficacy and safety of DPP-4 inhibitors as add-on therapy for insulin-treated type 2 diabetes patients with HbA1c ≥7%?

**Ground Truth**: Cochrane Systematic Review; FDA prescribing information (Januvia, Onglyza, Tradjenta, Nesina); EMA EPAR documents (~15-20 key papers)

### Execution Workflow

```python
# 1. Task Creation
create_task(query="DPP-4 inhibitors efficacy safety insulin T2DM")

# 2. Query Execution (designed by MCP client)
queue_searches(task_id, queries=[
    "DPP-4 inhibitors efficacy meta-analysis HbA1c",
    "sitagliptin add-on insulin RCT",
    "DPP-4 inhibitors hypoglycemia risk systematic review"
])

# 3. Progress Monitoring
get_status(task_id, wait=30)

# 4. Materials Retrieval
get_materials(task_id, include_graph=True)
```

### Results

<!-- TODO: Fill in after case study execution -->

| Metric | Lyra | Claude Research |
|--------|:----:|:---------------:|
| Recall@GT | TODO | TODO |
| Academic Ratio | TODO | TODO |
| URL Validity | TODO | TODO |
| Verification Time (10 claims) | TODO | TODO |
| Verification Success Rate | TODO | TODO |

## 3.3 Domain 2: Computer Science (LLM Hallucination)

**Research Question**: What techniques have been proposed to reduce hallucination in LLMs? Compare RAG, fine-tuning, and prompt engineering approaches.

**Ground Truth**: Survey papers (2023-2024); Semantic Scholar top-cited papers on RAG, fine-tuning, prompt engineering; benchmark papers (TruthfulQA, HaluEval) (~25-30 key papers)

### Results

<!-- TODO: Fill in after case study execution -->

| Metric | Lyra | Claude Research |
|--------|:----:|:---------------:|
| Recall@GT | TODO | TODO |
| Academic Ratio | TODO | TODO |
| URL Validity | TODO | TODO |
| Verification Time (10 claims) | TODO | TODO |
| Verification Success Rate | TODO | TODO |

## 3.4 Domain 3: Health Science (Intermittent Fasting)

**Research Question**: What is the evidence for intermittent fasting on weight loss and metabolic health? Are there contradicting findings?

**Ground Truth**: Cochrane Review on intermittent fasting; umbrella reviews (2022-2024); studies with both positive and negative findings (~15-20 key papers)

### Results

<!-- TODO: Fill in after case study execution -->

| Metric | Lyra | Claude Research |
|--------|:----:|:---------------:|
| Recall@GT | TODO | TODO |
| Academic Ratio | TODO | TODO |
| URL Validity | TODO | TODO |
| Verification Time (10 claims) | TODO | TODO |
| Verification Success Rate | TODO | TODO |

## 3.5 Cross-Domain Summary

<!-- TODO: Fill in after case study execution -->

| Metric | Lyra (Mean) | Claude Research (Mean) |
|--------|:-----------:|:----------------------:|
| Recall@GT | TODO | TODO |
| Academic Ratio | TODO | TODO |
| Verification Time | TODO | TODO |
| Verification Success | TODO | TODO |

# 4. Impact

## 4.1 Architectural Comparison

Both tools use the same AI model (Claude Opus 4.5), isolating architectural differences:

| Capability | Lyra | Claude Research | Notes |
|------------|:----:|:---------------:|-------|
| Evidence Graph structure | ✓ | — | Claim→Fragment→Page links |
| Explicit stance labels | ✓ | — | SUPPORTS/REFUTES/NEUTRAL |
| Local ML processing | ✓ | — | NLI, embedding, reranking |
| Academic API integration | ✓ | — | Semantic Scholar, OpenAlex |
| Human-correctable outputs | ✓ | — | Feedback tool |
| Monthly cost | $16 | $17 | Cursor Pro vs Claude Pro |

*Note: The presence of a capability does not imply superiority. These are structural differences enabling different workflows.*

## 4.2 Verification Cost Analysis

The key differentiator is **verification efficiency**: Lyra's fragment-level citations enable claim verification in seconds rather than minutes.

<!-- TODO: Add specific timing comparison after case study -->

| Verification Step | Lyra | Claude Research |
|-------------------|------|-----------------|
| Locate cited passage | Fragment text provided | Navigate to URL, search |
| Confirm quote exists | Direct comparison | Manual text search |
| Check context | Surrounding text available | Read full section |

## 4.3 Research Applications

| Domain | Use Case | Lyra Advantage |
|--------|----------|----------------|
| **Healthcare** | Drug interaction review | Traceable evidence chains |
| **Legal** | Case law research | Citation provenance maintained |
| **Journalism** | Investigative research | Local-only processing |
| **Academia** | Literature review | Academic API integration |

## 4.4 Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **NLI domain gap** | General-purpose model may misclassify | Fragment-level provenance enables rapid verification; feedback accumulation → LoRA fine-tuning |
| **Coverage** | May miss sources behind paywalls | Academic APIs prioritize open-access; HITL for auth |
| **Platform** | Windows 11 + WSL2 only | Cross-platform support planned |
| **GPU required** | Not accessible to all users | Minimum 8GB VRAM documented |

# 5. Conclusions

This paper demonstrates Lyra's application as a research methodology tool through case studies across three domains: pharmacology, computer science, and health science. The thinking-working separation architecture enables researchers to:

1. **Leverage frontier AI reasoning** (query design, synthesis) while **keeping data local** (extraction, classification)
2. **Track evidence provenance** from source fragments through to synthesized claims
3. **Reduce verification cost** through fragment-level citations
4. **Accumulate domain knowledge** through feedback for future model adaptation

Compared to Claude Research—using the same AI model (Opus 4.5)—Lyra provides structural advantages for evidence traceability through its local Evidence Graph, at equivalent subscription cost.

## 5.1 Future Work

- **Domain adaptation**: LoRA fine-tuning from accumulated NLI corrections
- **Confidence calibration**: Platt/temperature scaling to improve probability estimates
- **Cross-platform support**: Native Linux and macOS without WSL2 requirement

# Acknowledgements

Lyra builds upon: Ollama, Playwright, Trafilatura, Semantic Scholar API, OpenAlex API, Hugging Face Transformers.

<!-- TODO: Add funding acknowledgements if applicable -->

# References

<!-- TODO: Create references list including:
     - [JOSS-REF] Companion JOSS paper (software architecture)
     - MCP specification
     - Semantic Scholar API
     - OpenAlex API
     - DeBERTa-v3 NLI paper
     - Beta distribution / Bayesian updating reference
-->
