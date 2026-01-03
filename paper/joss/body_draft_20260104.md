---
title: 'Lyra: A Local-First MCP Server for AI-Collaborative Desktop Research with Evidence Graph Construction'
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
date: 4 January 2026
bibliography: paper.bib
---

# Summary

Lyra is an open-source Python toolkit that enables AI assistants to conduct desktop research with complete local data sovereignty. It implements the Model Context Protocol (MCP) to expose research capabilities—web search, content extraction, claim verification, and evidence graph construction—as structured tools that AI models can invoke directly.

The toolkit embeds four ML components for local inference: a 3B-parameter LLM (Qwen2.5) for claim extraction, BGE-M3 embeddings for semantic search, a cross-encoder reranker, and a DeBERTa-based NLI classifier for stance detection. All inference runs on local GPU (NVIDIA, 8GB+ VRAM required), eliminating API costs and external data transmission.

Lyra constructs an **evidence graph** linking extracted claims to source fragments with full provenance metadata. Each claim accumulates Bayesian confidence from weighted NLI judgments (SUPPORTS/REFUTES/NEUTRAL), enabling researchers to assess evidence quality transparently. The architecture supports human-in-the-loop correction: users can override NLI judgments via the feedback tool, with corrections immediately reflected in confidence scores and accumulated for future domain adaptation via LoRA fine-tuning.

# Statement of Need

AI-assisted research faces a fundamental tension: powerful reasoning models are cloud-based, but transmitting research queries and collected evidence to external servers is unacceptable for sensitive domains such as healthcare research, legal analysis, and investigative journalism. Existing approaches force a choice between capability and privacy.

Lyra resolves this through a **thinking-working separation** architecture: the MCP client (cloud AI) handles strategic reasoning—deciding *what* to search and how to synthesize findings—while Lyra handles mechanical execution locally. Research data never leaves the machine; only the user's conversation with their AI assistant traverses the network.

This architecture specifically benefits:

- **Healthcare researchers**: Where a hallucinated drug interaction claim could be fatal, Lyra provides traceable evidence chains from claim to source URL
- **Legal and compliance teams**: Research requiring strict confidentiality and audit trails
- **Independent researchers**: Cost-effective alternative to commercial research tools with zero operational expenditure
- **Security-conscious organizations**: Auditable, deployable within air-gapped environments

# State of the Field

Several tools address aspects of AI-assisted research, but none combine local-first execution with structured evidence provenance:

| Tool | Local ML | Evidence Provenance | MCP Integration |
|------|----------|---------------------|-----------------|
| Perplexity AI | No (cloud) | Citations only | No |
| Elicit | No (cloud) | Paper references | No |
| Semantic Scholar | API only | Yes | No |
| LangChain/LlamaIndex | Partial | Limited | Partial |
| **Lyra** | Yes (all ML) | Full graph | Yes |

Browser automation frameworks (Selenium, Playwright) provide execution capability but require custom scripting and offer no structured evidence management. RAG frameworks focus on document retrieval rather than claim verification and evidence synthesis.

Lyra differentiates by providing: (1) complete local ML pipeline without external API calls; (2) evidence graph structure with Bayesian confidence calculation; (3) native MCP integration with any compatible client; (4) multi-source search aggregating browser SERP and academic APIs; and (5) human-in-the-loop CAPTCHA and authentication handling.

# Implementation

Lyra is implemented in Python 3.13+ with an async architecture comprising 76,000+ lines of source code and 95,000+ lines of tests. The reference environment requires WSL2/Linux, NVIDIA GPU (8GB+ VRAM), and approximately 25GB storage for ML containers and models.

Key components include:

- **MCP Server** (`src/mcp/`): 10 tools for task management, search execution, evidence exploration, feedback collection, and calibration
- **Evidence Graph** (`src/filter/evidence_graph.py`): NetworkX-based graph with SQLite persistence; Bayesian confidence via Beta distribution updating over NLI-weighted edges
- **ML Server** (`src/ml_server/`): FastAPI service for embedding (BGE-M3), reranking, and NLI inference (DeBERTa-v3), running in network-isolated containers
- **Async Search Queue** (`src/scheduler/`): Non-blocking search with parallel workers, long-polling status updates, and DOI-based deduplication across browser and academic API sources
- **Browser Automation** (`src/crawler/`): Playwright-based fetching with CDP isolation per worker
- **Security** (`src/filter/llm_security.py`): 8-layer defense-in-depth model including input sanitization, session tags, and output validation

The codebase includes 17 Architecture Decision Records (ADRs) documenting design rationale, from local-first principles to thinking-working separation to evidence graph structure. All ML components are configurable via YAML, allowing users to substitute domain-specific or updated models.

# Acknowledgements

Lyra builds upon Ollama for local LLM runtime, Playwright for browser automation, Trafilatura for web content extraction, and Hugging Face Transformers for NLI and embedding models. Academic metadata is provided by Semantic Scholar and OpenAlex APIs.

# References
