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
date: 12 January 2026
bibliography: paper.bib
---

# Summary

Research demands auditable evidence chains—the ability to trace every claim back to its source. Lyra is an open-source server implementing the Model Context Protocol [MCP, @WhatModelContext]—a standard interface for connecting AI assistants to external tools—that enables AI assistants to conduct desktop research using structured provenance, providing accurate and auditable evidence. The software exposes research capabilities—web search, content extraction, natural language inference, and evidence graph construction—as structured tools that MCP-compatible AI clients can invoke directly.

I designed Lyra to separate strategic reasoning—performed by the AI assistant in the MCP client—from mechanical execution: evidence discovery, classification, and scoring (Figure 1). 

![System architecture. The MCP server runs on the host; ML inference containers are network-isolated to prevent data exfiltration.](figures/figure_1.png)

The AI assistant handles query design and synthesis, while Lyra executes search, extraction, and NLI-based stance detection. Lyra functions as a navigation tool: it discovers and organizes relevant sources, while detailed analysis of primary sources remains the researcher's responsibility (Figure 2).

![Three-layer collaboration model. The Thinking layer (human) provides domain expertise and final evaluation. The Reasoning layer (MCP client) handles query design and synthesis. The Working layer (Lyra) executes mechanical tasks: search, extraction, and NLI.](figures/figure_2.png)

The software incorporates three machine learning components for local inference: a 3B-parameter language model [Qwen2.5, @qwenQwen25TechnicalReport2025] for claim extraction, BGE-M3 embeddings [@chenM3EmbeddingMultiLingualityMultiFunctionality2024] for semantic search, and a DeBERTa-based classifier [@heDeBERTaDecodingenhancedBERT2021] for stance detection. The system automatically detects GPU availability and applies appropriate container configurations; while CPU-only operation is supported, GPU acceleration is strongly recommended due to significant performance differences. Lyra constructs an **evidence graph** linking extracted claims to source fragments with structured provenance metadata (Figure 3). 

![Evidence graph structure. Claims are extracted from fragments (ORIGIN edges track provenance). Cross-source verification via NLI creates SUPPORTS/REFUTES edges. The exploration score aggregates weighted evidence. CITES edges track academic citations.](figures/figure_3.png)

Each claim accumulates an exploration score (`nli_claim_support_ratio`) derived from Natural Language Inference [NLI, @bowmanLargeAnnotatedCorpus2015] judgments—automated classification of whether a text supports, refutes, or is neutral toward a claim. This score aggregates NLI-weighted evidence (supports vs. refutes) into a 0–1 ratio used for navigation and ranking, not as a statistically rigorous probability of truth.

# Statement of Need

Lyra targets researchers and practitioners—particularly in healthcare, biomedical sciences, and other fields well-covered by academic databases—who need AI-assisted evidence gathering for desktop research. It provides auditable evidence chains: the ability to trace claims to their sources for verifying conclusions. Large language models, however, are inherently probabilistic; verifying that AI-generated citations accurately reflect source materials demands substantial manual effort. Existing tools address different aspects of this challenge: cloud-based assistants [@Perplexity; @ElicitAIScientific] provide rapid retrieval with citation links; browser automation [@SeleniumHQSelenium2013; @MicrosoftPlaywright2019] offers programmatic access; RAG frameworks [@chaseLangChain2022; @liuLlamaIndex2022] specialize in document retrieval. However, these tools typically produce disposable answers—results that do not persist or improve with use. Lyra takes a different approach: it builds a persistent evidence graph that accumulates across research sessions, enabling traceable conclusions that grow stronger with continued use and researcher feedback.

From a context engineering perspective—designing systems that supply AI models with accurate, relevant information—Lyra constructs a transparent evidence graph that provides AI clients with traceable information. Every claim links to source fragments, which link to page URLs, creating an auditable chain from assertion to origin. The graph explicitly represents both supporting and refuting evidence, with exploration scores quantifying the evidence balance. Researchers can trace any claim back to its source text and evaluate the reasoning path themselves.

The software follows a local-first design: machine learning inference (LLM, embeddings, NLI) runs on the researcher's hardware, and all research artifacts—the evidence graph, extracted claims, and source fragments—are stored locally in a SQLite database. For evidence discovery, Lyra retrieves content via browser-based web search and academic APIs [@SemanticScholarAcademic; @priemOpenAlexFullyopenIndex2022], with identifier extraction from SERP URLs enabling cross-source enrichment and DOI-based deduplication. Each research task defines a central hypothesis to verify; Lyra then finds evidence supporting or refuting this hypothesis. A human-in-the-loop mechanism enables researchers to correct NLI judgments; these corrections are accumulated for planned domain adaptation via Low-Rank Adaptation [LoRA, @huLoRALowRankAdaptation2021] fine-tuning.

# AI Usage Disclosure

I used Cursor and Claude Code during Lyra's development. AI assistance covered code generation, refactoring, test scaffolding, and documentation drafting. All AI-assisted outputs were reviewed, and validated by me. Core design decisions—including the evidence graph architecture, three-layer collaboration model, and MCP tool interface—were made by me, as documented in 17 Architecture Decision Records covering local-first principles, evidence graph structure, and security models.

# Acknowledgements

Lyra builds upon several open-source projects: Ollama [@OllamaOllama2023] for local language model runtime, Playwright [@MicrosoftPlaywright2019] for browser automation, Trafilatura [@barbaresiTrafilaturaWebScraping2021] for web content extraction, and Hugging Face Transformers [@wolfTransformersStateoftheArtNatural2020] for NLI and embedding models. Academic metadata is provided by the Semantic Scholar [@SemanticScholarAcademic] and OpenAlex [@priemOpenAlexFullyopenIndex2022] APIs.

# References
