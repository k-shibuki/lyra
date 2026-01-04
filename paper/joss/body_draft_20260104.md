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

Lyra is an open-source server implementing the Model Context Protocol (MCP) that enables AI assistants to conduct desktop research while maintaining complete local data sovereignty. The software exposes research capabilities—web search, content extraction, natural language inference, and evidence graph construction—as structured tools that MCP-compatible AI clients can invoke directly.

I designed Lyra around a **thinking-working separation** architecture. The MCP client handles strategic reasoning such as query design and synthesis, while Lyra executes mechanical tasks locally. This separation allows researchers to leverage frontier AI reasoning capabilities without transmitting research data to external servers.

The software embeds three machine learning components for local GPU inference: a 3B-parameter language model for claim extraction, BGE-M3 embeddings for semantic search, and a DeBERTa-based classifier for stance detection. Lyra constructs an **evidence graph** linking extracted claims to source fragments with full provenance metadata. Each claim accumulates a Bayesian confidence score calculated via Beta distribution updating over evidence edges weighted by Natural Language Inference (NLI) judgments (supports, refutes, or neutral), enabling transparent assessment of evidence quality.

# Statement of Need

AI-assisted research faces a tension between capability and privacy. Powerful reasoning models such as GPT-4 and Claude are cloud-based, yet transmitting research queries and collected evidence to external servers is unacceptable for sensitive domains including healthcare research, legal analysis, and investigative journalism. Existing tools force researchers to choose between these concerns.

Current approaches have specific limitations. Cloud-based research assistants such as Perplexity AI and Elicit provide citation capabilities but require transmitting all queries and findings to external servers. Browser automation frameworks such as Selenium and Playwright offer local execution but demand custom scripting for each task and lack structured evidence management. Retrieval-Augmented Generation (RAG) frameworks such as LangChain and LlamaIndex support partial local execution but focus on document retrieval rather than claim verification and evidence synthesis.

Lyra addresses these gaps through several design decisions. All machine learning inference runs on local GPU, eliminating API costs and external data transmission. The evidence graph structure with Bayesian confidence calculation provides transparent provenance from claims to source URLs. Native MCP integration enables compatibility with any MCP-compatible client including Claude Desktop, Cursor, and Zed. Multi-source search aggregates browser-based web search and academic APIs (Semantic Scholar, OpenAlex) with Digital Object Identifier (DOI) based deduplication. A human-in-the-loop mechanism handles CAPTCHA challenges and enables researchers to correct NLI judgments; these corrections are accumulated for planned domain adaptation via Low-Rank Adaptation (LoRA) fine-tuning.

This architecture benefits healthcare researchers requiring traceable evidence chains, legal teams needing strict confidentiality, independent researchers seeking zero-cost alternatives to commercial tools, and security-conscious organizations requiring auditable systems deployable within controlled environments.

The software comprises approximately 76,000 lines of Python source code and 95,000 lines of tests. I documented design rationale in 17 Architecture Decision Records covering local-first principles, evidence graph structure, and security models.

# Acknowledgements

Lyra builds upon several open-source projects: Ollama for local language model runtime, Playwright for browser automation, Trafilatura for web content extraction, and Hugging Face Transformers for NLI and embedding models. Academic metadata is provided by the Semantic Scholar and OpenAlex APIs.

# References
