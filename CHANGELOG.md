# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-01-12

### Added

#### Core
- MCP server implementing Model Context Protocol with 14 tools for AI-collaborative research
- Evidence graph construction linking claims → fragments → pages with full provenance
- NLI-based exploration scoring (`nli_claim_support_ratio`) for evidence assessment
- Local-first architecture: all ML inference runs on researcher's hardware

#### Search & Discovery
- Multi-source search: Semantic Scholar, OpenAlex APIs + browser-based web search
- Citation chasing via `v_reference_candidates` view for expanding evidence
- DOI-based deduplication and cross-source enrichment

#### Machine Learning
- Local LLM inference via Ollama (default: Qwen2.5 3B) for claim extraction
- BGE-M3 embeddings for semantic search
- DeBERTa-based NLI classifier for stance detection (supports/refutes/neutral)
- GPU auto-detection with CPU fallback

#### Evidence Exploration
- SQL query interface for direct evidence graph access
- Vector search for semantic similarity queries
- 20 predefined SQL views for common analysis patterns
- Human-in-the-loop feedback mechanism for NLI corrections

#### Report & Visualization
- Evidence pack generation (`report-pack`)
- Draft report generation with LLM-editable markers (`report-draft`)
- Report validation against evidence constraints (`report-validate`)
- Interactive evidence dashboard generation (`report-dashboard`)

#### Infrastructure
- Network-isolated ML containers (no data exfiltration)
- Human-in-the-loop CAPTCHA/authentication handling
- SQLite-based persistent storage
- 17 Architecture Decision Records documenting design rationale

[0.1.0]: https://github.com/k-shibuki/lyra/releases/tag/v0.1.0
