---
title: 'Lyra: A Local-First MCP Toolkit for AI-Collaborative Desktop Research with Evidence Graph Construction'
tags:
  - Python
  - research automation
  - evidence synthesis
  - natural language inference
  - Model Context Protocol
authors:
  - name: Katsuya Shibuki
    orcid: 0000-0003-3570-5038
    affiliation: 1
affiliations:
  - name: Independent Researcher
    index: 1
date: 28 December 2025
bibliography: paper.bib
---

<!--
================================================================================
JOSS SUBMISSION REQUIREMENTS CHECKLIST
================================================================================
Status: DRAFT (Pre-E2E completion)

REQUIRED FILES:
  [x] LICENSE (MIT) - exists
  [x] README.md - exists (37KB, comprehensive)
  [ ] CONTRIBUTING.md - TODO: Create before submission
  [ ] CITATION.cff - TODO: Create before submission
  [ ] paper.bib - TODO: Create with references

JOSS CRITERIA:
  [x] Software functionality documented - README comprehensive
  [x] Installation instructions - README Quick Start section
  [x] Example usage - README Usage section
  [x] Tests - 3000+ unit tests, test commands documented
  [x] Statement of Need - README has section, adapted below
  [x] Community guidelines - Basic info in README, CONTRIBUTING.md needed
  [ ] API documentation - Partial (MCP tools documented, no full API docs)

CODE METRICS (JOSS minimum: 300 LOC, recommended: 1000+ LOC):
  - Source code: 76,166 lines (src/)
  - Test code: 90,580 lines (tests/)
  - Total commits: 126
  - ADRs: 16 architecture decision records

AI-GENERATED CONTENT NOTICE:
  This software was developed with AI assistance (Cursor AI, Claude).
  The author maintains full responsibility for design decisions,
  architecture, and code review. All 16 ADRs document human-driven
  design rationale.

BLOCKING ITEMS BEFORE SUBMISSION:
  1. [ ] Complete E2E debugging (currently in progress)
  2. [ ] Create CONTRIBUTING.md
  3. [ ] Create CITATION.cff
  4. [ ] Create paper.bib with all references
  5. [x] Confirm author affiliation and ORCID
  6. [ ] Review word count (target: 250-1000 words)
================================================================================
-->

# Summary

Lyra is an open-source Python toolkit that enables AI assistants to conduct desktop research with full local data sovereignty. It implements the Model Context Protocol (MCP) to expose research capabilities—web search, content extraction, claim verification, and evidence graph construction—as structured tools that AI models can invoke directly. The separation of "thinking" (strategic reasoning by cloud AI) from "working" (mechanical execution by Lyra) keeps research data entirely on the user's machine while leveraging frontier AI reasoning capabilities.

The toolkit embeds four ML components for local inference: a 3B-parameter LLM (Qwen2.5) for claim extraction, BGE-M3 embeddings for semantic ranking, a cross-encoder reranker, and a DeBERTa-based NLI classifier for stance detection. All inference runs on local GPU (NVIDIA, 8GB+ VRAM required), eliminating API costs and external data transmission.

Lyra constructs an **evidence graph** linking extracted claims to source fragments with provenance metadata, enabling verification and reproducibility. Confidence is calculated via Bayesian updating over NLI-weighted evidence, with explicit tracking of supporting and refuting sources.

<!-- TODO: After E2E completion, add concrete metrics:
     - Typical research session statistics (pages processed, claims extracted)
     - Evidence graph characteristics (nodes, edges, citation depth)
-->

# Statement of Need

AI-assisted web research faces a fundamental tension: powerful reasoning models (GPT-4, Claude) are cloud-based, but transmitting research queries and collected evidence to external servers is unacceptable for sensitive domains such as healthcare research, legal analysis, and investigative journalism.

Existing approaches force a choice between capability and privacy:

- **Cloud AI with web access**: Queries and findings leave the machine
- **Local-only tools**: Sacrifice frontier reasoning capability
- **Browser automation scripts**: Require custom coding per task, no evidence tracking

Lyra resolves this by separating concerns: the MCP client (cloud AI) handles strategic reasoning—deciding *what* to search and how to synthesize findings—while Lyra handles mechanical execution locally. Research data never leaves the machine; only the user's conversation with their AI assistant traverses the network.

This architecture specifically benefits:

- **Healthcare researchers**: Where a hallucinated drug interaction claim could be fatal, Lyra provides traceable evidence chains from claim to source
- **Legal and compliance teams**: Research requiring strict confidentiality
- **Independent researchers and journalists**: Cost-effective alternative to commercial research tools
- **Security-conscious organizations**: Auditable, deployable within controlled environments

<!-- TODO: After E2E completion, consider adding a brief case study or usage example -->

# State of the Field

Several tools address aspects of AI-assisted research, but none combine local-first execution with evidence graph construction:

| Tool | Local Execution | Evidence Provenance | MCP Integration |
|------|-----------------|---------------------|-----------------|
| Perplexity AI | No (cloud) | Citations only | No |
| Elicit | No (cloud) | Paper references | No |
| Semantic Scholar | API only | Yes | No |
| LangChain/LlamaIndex | Partial | Limited | Partial |
| **Lyra** | Yes (all ML) | Full graph | Yes |

Browser automation frameworks (Selenium, Playwright) provide execution capability but require custom scripting for each research task and offer no structured evidence management. RAG frameworks (LangChain, LlamaIndex) focus on document retrieval rather than claim verification and evidence synthesis.

Lyra differentiates by providing:

1. **Complete local ML pipeline**: Embedding, reranking, NLI, and LLM extraction without external API calls
2. **Evidence graph structure**: Bayesian confidence calculation over claim-fragment-source relationships (ADR-0005)
3. **Native MCP integration**: Works with any MCP client (Cursor AI, Claude Desktop, Zed)
4. **Multi-source search**: Aggregates DuckDuckGo, Brave, academic APIs (Semantic Scholar, OpenAlex)
5. **Human-in-the-loop handling**: Graceful CAPTCHA and authentication queue management

# Implementation

Lyra is implemented in Python 3.13 with an async architecture (~76,000 lines of source code, ~90,000 lines of tests). The reference environment requires Windows 11 + WSL2 (Ubuntu), NVIDIA GPU (8GB+ VRAM), and ~25GB storage for ML containers and models. Key components include:

- **MCP Server** (`src/mcp/`): 10 tools for task management, search execution, and materials retrieval
- **Evidence Graph** (`src/filter/evidence_graph.py`): NetworkX-based graph with SQLite persistence; Bayesian confidence via Beta distribution updating
- **ML Server** (`src/ml_server/`): FastAPI service for embedding (BGE-M3), reranking (BGE-Reranker-v2-m3), and NLI inference (DeBERTa-v3)
- **Async Search Queue** (`src/scheduler/`): Non-blocking search with 2 parallel workers, long-polling status updates (ADR-0010)
- **Browser Automation** (`src/crawler/`): Playwright-based fetching with CDP isolation per worker (ADR-0014)
- **Academic APIs** (`src/search/apis/`): Semantic Scholar and OpenAlex with global rate limiting (ADR-0013)
- **Security** (`src/filter/llm_security.py`): 8-layer defense-in-depth model including input sanitization, session tags, and output validation (ADR-0006)
- **Human-in-the-Loop** (`src/utils/notification.py`): Authentication queue for CAPTCHAs and login-required sites (ADR-0007)

All queries execute both browser SERP and academic APIs in parallel, with DOI-based deduplication (ADR-0016). The feedback tool enables human correction of NLI judgments, accumulating training data for future LoRA fine-tuning (ADR-0011, ADR-0012).

The codebase includes 16 Architecture Decision Records (ADRs) documenting design rationale, from local-first principles (ADR-0001) to thinking-working separation (ADR-0002) to evidence graph structure (ADR-0005).

<!-- TODO: After E2E completion, add:
     - Performance characteristics (throughput, latency)
     - Resource requirements validation
     - Any benchmark results
-->

# Acknowledgements

Development was assisted by AI tools (Cursor AI, Claude) for code generation and documentation. The author maintains responsibility for all design decisions and code review.

Lyra builds upon:

- [Ollama](https://ollama.ai/) for local LLM runtime
- [Playwright](https://playwright.dev/) for browser automation
- [Trafilatura](https://trafilatura.readthedocs.io/) for web content extraction
- [Semantic Scholar](https://www.semanticscholar.org/) and [OpenAlex](https://openalex.org/) for academic metadata
- [Hugging Face Transformers](https://huggingface.co/) for NLI and embedding models

<!-- TODO: Add funding acknowledgements if applicable -->

# References

<!-- TODO: Create paper.bib with the following references:
     - MCP specification (modelcontextprotocol.io)
     - Semantic Scholar API documentation
     - OpenAlex documentation
     - Qwen2.5 model paper
     - BGE-M3 embedding paper
     - DeBERTa-v3 paper
     - Trafilatura paper (if exists)
     - Beta distribution / Bayesian updating reference
     - Related work: Perplexity, Elicit, etc.
-->
