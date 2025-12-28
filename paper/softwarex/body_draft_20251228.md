---
title: "Lyra: Local-First Evidence Synthesis for AI-Collaborative Research"
journal: SoftwareX
type: Original Software Publication
authors:
  - name: Katsuya Shibuki
    orcid: 0000-0003-3570-5038
    affiliation: Independent Researcher
date: 28 December 2025
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
  [x] 2. Software description
  [x] 3. Illustrative examples
  [x] 4. Impact
  [x] 5. Conclusions
  [x] Required Metadata Table

SOFTWARE REQUIREMENTS:
  [x] Open source with OSI-approved license (MIT)
  [x] Code publicly available (GitHub)
  [ ] Permanent archive (Zenodo DOI) - TODO before submission

DIFFERENTIATION FROM JOSS PAPER:
  - JOSS focus: Software architecture, MCP integration, evidence graph structure
  - SoftwareX focus: Research methodology, use cases, evaluation, comparison

BLOCKING ITEMS BEFORE SUBMISSION:
  1. [ ] Complete E2E debugging
  2. [ ] Create Zenodo archive with DOI
  3. [ ] Add benchmark/evaluation results
  4. [ ] Convert to official template
  5. [ ] Review word count (target: <3000 words)
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
| Software code language | Python 3.13 |
| Compilation requirements | NVIDIA GPU (8GB+ VRAM), CUDA 12.x |
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
- **P3**: How can contradicting evidence be systematically identified and presented?

## 1.3 Significance

Lyra introduces a "thinking-working separation" architecture that addresses these problems. The key insight is that frontier AI models excel at strategic reasoning (formulating queries, synthesizing findings), while mechanical tasks (fetching, extracting, classifying) can be performed locally with smaller models. This separation enables:

- Full local execution of data processing (zero operational expenditure)
- Traceable evidence graphs linking claims to source fragments
- Systematic refutation search via Natural Language Inference (NLI)

# 2. Software Description

## 2.1 Architecture Overview

Lyra implements the Model Context Protocol (MCP), enabling any compatible AI assistant to invoke research tools. The architecture separates concerns:

```
┌─────────────────────────────────────────────────────────────┐
│  MCP Client (Claude Desktop / Cursor AI / etc.)             │
│  • Research strategy formulation                            │
│  • Query design and prioritization                          │
│  • Evidence synthesis and report writing                    │
└─────────────────────────────────────────────────────────────┘
                              │ MCP Protocol (stdio)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Lyra MCP Server                                            │
│  • Web search execution (multi-engine)                      │
│  • Content extraction and structuring                       │
│  • NLI stance classification (supports/refutes/neutral)     │
│  • Evidence graph construction and persistence              │
└─────────────────────────────────────────────────────────────┘
```

## 2.2 Core Components

### 2.2.1 Unified Search Pipeline

All queries execute browser-based SERP and academic APIs (Semantic Scholar, OpenAlex) in parallel, with DOI-based deduplication. This ensures comprehensive coverage regardless of query type.

### 2.2.2 Evidence Graph

Lyra constructs a directed graph with three node types:
- **Claims**: User hypotheses or extracted assertions
- **Fragments**: Text excerpts from source documents
- **Pages**: Crawled web resources with provenance metadata

Edge types include SUPPORTS, REFUTES, NEUTRAL (from NLI classification), and CITES (citation relationships from academic APIs).

### 2.2.3 Bayesian Confidence Calculation

Claim confidence is computed via Beta distribution updating:

```
Prior: Beta(α=1, β=1)
α = 1 + Σ nli_confidence(e) for e in SUPPORTS edges
β = 1 + Σ nli_confidence(e) for e in REFUTES edges
confidence = α / (α + β)
```

This provides calibrated uncertainty estimates that incorporate contradicting evidence.

### 2.2.4 Local ML Pipeline

Four models run entirely on local GPU:
- **Qwen2.5-3B**: Claim extraction via structured prompts
- **BGE-M3**: Multilingual embeddings for semantic ranking
- **BGE-Reranker-v2-m3**: Cross-encoder reranking
- **DeBERTa-v3**: NLI stance classification

## 2.3 Security Model

An 8-layer defense-in-depth model protects against prompt injection and data exfiltration:
1. Input validation (schema, length limits)
2. URL allowlist/blocklist
3. Content pre-filtering
4. Prompt injection detection
5. LLM sandbox (token limits)
6. Output validation
7. Response sanitization
8. Audit logging

# 3. Illustrative Examples

## 3.1 Basic Research Session

<!-- TODO: After E2E completion, add actual session transcript -->

```python
# Example MCP tool invocations from AI assistant

# 1. Create research task
create_task(hypothesis="Caffeine consumption improves cognitive performance")

# 2. Execute searches (parallel browser SERP + academic APIs)
search(task_id, query="caffeine cognition meta-analysis")
search(task_id, query="caffeine cognitive performance RCT")

# 3. Execute refutation search
search(task_id, query="caffeine cognition negative effects", refute=True)

# 4. Check status with metrics
get_status(task_id)
# Returns: {completed: 45, harvest_rate: 0.73, novelty: 0.12, ...}

# 5. Retrieve evidence materials
get_materials(task_id, format="graph")
# Returns: claims, fragments, edges with confidence scores
```

## 3.2 Evidence Graph Visualization

<!-- TODO: Add figure showing evidence graph with supports/refutes edges -->

The evidence graph for a typical research session contains:
- 10-50 claims extracted from sources
- 50-200 fragments with NLI classifications
- Citation relationships from academic APIs

## 3.3 Human-in-the-Loop Authentication

When encountering CAPTCHA or login-required sites, Lyra queues the request and continues with other sources. Users can batch-resolve authentication challenges without blocking the research pipeline.

# 4. Impact

## 4.1 Research Applications

Lyra addresses needs across multiple research contexts:

| Domain | Use Case | Benefit |
|--------|----------|---------|
| Healthcare | Drug interaction review | Traceable evidence prevents hallucinated contraindications |
| Legal | Case law research | Citation chains maintained for court submission |
| Journalism | Investigative research | Source confidentiality via local-only processing |
| Academia | Literature review | Systematic refutation search reduces confirmation bias |

## 4.2 Comparison with Existing Tools

| Tool | Local Execution | Evidence Provenance | Refutation Search | Cost |
|------|-----------------|---------------------|-------------------|------|
| Perplexity AI | No | Citations only | No | Subscription |
| Elicit | No | Paper references | No | Subscription |
| Semantic Scholar | API only | Yes | No | Free |
| ChatGPT + Browsing | No | Minimal | No | Subscription |
| **Lyra** | Yes (all ML) | Full graph | Yes (NLI) | Zero OpEx |

## 4.3 Metrics

<!-- TODO: After E2E completion, add actual metrics -->

| Metric | Value |
|--------|-------|
| Source code | ~76,000 lines |
| Test code | ~90,000 lines |
| Unit tests | 3,000+ |
| Architecture Decision Records | 16 |

# 5. Conclusions

Lyra demonstrates that rigorous, evidence-based research can be conducted with AI assistance while maintaining complete data sovereignty. The thinking-working separation architecture enables researchers to leverage frontier AI reasoning capabilities for strategy while performing all data processing locally.

Key contributions:
1. MCP-based tool interface enabling AI-collaborative research
2. Evidence graph structure with Bayesian confidence calculation
3. Systematic refutation search via NLI classification
4. Zero operational expenditure through local-first design

Future work includes LoRA fine-tuning from user feedback and calibration of NLI confidence scores.

# Acknowledgements

Development was assisted by AI tools (Cursor AI, Claude) for code generation and documentation. The author maintains responsibility for all design decisions and code review. All 16 Architecture Decision Records document human-driven design rationale.

Lyra builds upon Ollama, Playwright, Trafilatura, Semantic Scholar API, OpenAlex API, and Hugging Face Transformers.

<!-- TODO: Add funding acknowledgements if applicable -->

# References

<!-- TODO: Create references list including:
     - MCP specification
     - Semantic Scholar API
     - OpenAlex API
     - Qwen2.5 model
     - BGE-M3 embedding
     - DeBERTa-v3
     - Beta distribution / Bayesian updating
     - Related work (Perplexity, Elicit, etc.)
-->
