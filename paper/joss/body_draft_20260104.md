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

Lyra is an open-source server implementing the Model Context Protocol (MCP) that enables AI assistants to conduct desktop research with full provenance tracking. The software exposes research capabilities—web search, content extraction, natural language inference, and evidence graph construction—as structured tools that MCP-compatible AI clients can invoke directly.

I designed Lyra around a **thinking-working separation** architecture. The MCP client handles strategic reasoning such as query design and synthesis, while Lyra executes mechanical tasks including search, extraction, and classification. Lyra functions as a navigation tool: it discovers and organizes relevant sources, while detailed analysis of primary sources remains the researcher's responsibility.

The software incorporates three machine learning components for local GPU inference: a 3B-parameter language model for claim extraction, BGE-M3 embeddings for semantic search, and a DeBERTa-based classifier for stance detection. Lyra constructs an **evidence graph** linking extracted claims to source fragments with full provenance metadata. Each claim accumulates a Bayesian confidence score calculated via Beta distribution updating over evidence edges weighted by Natural Language Inference (NLI) judgments (supports, refutes, or neutral), enabling transparent assessment of evidence quality.

# Statement of Need

AI-assisted research tools face a fundamental credibility problem. Large language models hallucinate citations, fabricate quotations, and provide no traceable path from conclusions to source materials. Researchers cannot verify AI-generated claims without manually locating and checking every referenced source. Existing search algorithms operate as black boxes, offering no explanation for why particular results appear or how confidence scores are derived.

Current approaches fail to address these issues. Cloud-based research assistants such as Perplexity AI and Elicit provide citation links but lack structured provenance; researchers still must verify each claim independently. Browser automation frameworks such as Selenium and Playwright offer programmatic access but require custom scripting and provide no evidence management. Retrieval-Augmented Generation (RAG) frameworks such as LangChain and LlamaIndex focus on document retrieval rather than claim verification and evidence synthesis.

Lyra addresses these gaps by constructing a transparent evidence graph. Every claim links to source fragments, which link to page URLs, creating an auditable chain from assertion to origin. The graph explicitly represents both supporting and refuting evidence, with Bayesian confidence scores quantifying the balance. Researchers can trace any claim back to its source text and evaluate the reasoning path themselves.

The software runs entirely on local hardware, eliminating dependence on external APIs and ensuring research data remains under researcher control. Multi-source search aggregates browser-based web search and academic APIs (Semantic Scholar, OpenAlex) with Digital Object Identifier (DOI) based deduplication. A human-in-the-loop mechanism enables researchers to correct NLI judgments; these corrections are accumulated for planned domain adaptation via Low-Rank Adaptation (LoRA) fine-tuning.

The software comprises approximately 76,000 lines of Python source code and 95,000 lines of tests. I documented design rationale in 17 Architecture Decision Records covering local-first principles, evidence graph structure, and security models.

# Acknowledgements

Lyra builds upon several open-source projects: Ollama for local language model runtime, Playwright for browser automation, Trafilatura for web content extraction, and Hugging Face Transformers for NLI and embedding models. Academic metadata is provided by the Semantic Scholar and OpenAlex APIs.

# References
