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

Lyra is an open-source Model Context Protocol (MCP) server that enables AI assistants to conduct desktop research while maintaining complete local data sovereignty. The software exposes research capabilities—web search, content extraction, natural language inference (NLI), and evidence graph construction—as structured tools that MCP-compatible AI clients can invoke directly.

I designed Lyra around a **thinking-working separation** architecture: the MCP client handles strategic reasoning (query design, synthesis), while Lyra executes mechanical tasks locally. This separation allows researchers to leverage frontier AI reasoning capabilities without transmitting research data to external servers.

The software embeds four machine learning components for local GPU inference: a 3B-parameter language model for claim extraction, BGE-M3 embeddings for semantic search, a cross-encoder for reranking, and a DeBERTa-based classifier for stance detection (supports/refutes/neutral). Lyra constructs an **evidence graph** linking extracted claims to source fragments with full provenance metadata. Each claim accumulates Bayesian confidence calculated via Beta distribution updating over NLI-weighted edges, enabling transparent assessment of evidence quality.

# Statement of Need

AI-assisted research faces a fundamental tension between capability and privacy. Powerful reasoning models such as GPT-4 and Claude are cloud-based, but transmitting research queries and collected evidence to external servers is unacceptable for sensitive domains including healthcare research, legal analysis, and investigative journalism. Existing tools force researchers to choose between these concerns.

Current approaches exhibit specific limitations. Cloud-based research assistants such as Perplexity AI and Elicit provide citation capabilities but require transmitting all queries and findings to external servers. Browser automation frameworks such as Selenium and Playwright offer local execution but require custom scripting for each task and provide no structured evidence management. Retrieval-augmented generation (RAG) frameworks such as LangChain and LlamaIndex support partial local execution but focus on document retrieval rather than claim verification and evidence synthesis.

Lyra addresses these gaps through several design decisions. First, all machine learning inference runs on local GPU, eliminating API costs and external data transmission. Second, the evidence graph structure with Bayesian confidence calculation provides transparent provenance from claims to source URLs. Third, native MCP integration enables compatibility with any MCP client (Claude Desktop, Cursor, Zed, and others). Fourth, multi-source search aggregates browser-based web search and academic APIs (Semantic Scholar, OpenAlex) with DOI-based deduplication. Fifth, a human-in-the-loop mechanism handles CAPTCHA challenges and enables researchers to correct NLI judgments, with corrections accumulated for future domain adaptation via LoRA fine-tuning.

This architecture specifically benefits healthcare researchers requiring traceable evidence chains, legal teams needing strict confidentiality, independent researchers seeking zero-cost alternatives to commercial tools, and security-conscious organizations requiring auditable systems deployable within controlled environments.

The software comprises approximately 76,000 lines of Python source code and 95,000 lines of tests. I documented design rationale in 17 Architecture Decision Records covering topics from local-first principles to evidence graph structure to security models.

# Acknowledgements

Lyra builds upon several open-source projects: Ollama for local language model runtime, Playwright for browser automation, Trafilatura for web content extraction, and Hugging Face Transformers for NLI and embedding models. Academic metadata is provided by Semantic Scholar and OpenAlex APIs.

# References
