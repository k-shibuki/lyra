# Architecture Decision Records (ADR) Index

This document provides multiple views into Lyra's architecture decisions.

## Overview

- [ADR-0001](0001-local-first-zero-opex.md): Local-First / Zero OpEx
- [ADR-0002](0002-three-layer-collaboration-model.md): Three-Layer Collaboration Model
- [ADR-0003](0003-mcp-over-cli-rest.md): MCP over CLI/REST
- [ADR-0004](0004-local-llm-extraction-only.md): Local LLM for Extraction Only
- [ADR-0005](0005-evidence-graph-structure.md): Evidence Graph Structure
- [ADR-0006](0006-eight-layer-security-model.md): 8-Layer Security Model
- [ADR-0007](0007-human-in-the-loop-auth.md): Human-in-the-Loop Authentication
- [ADR-0008](0008-academic-data-source-strategy.md): Academic Data Source Strategy
- [ADR-0009](0009-test-layer-strategy.md): Test Layer Strategy
- [ADR-0010](0010-async-search-queue.md): Async Search Queue Architecture
- [ADR-0011](0011-lora-fine-tuning.md): LoRA Fine-tuning Strategy
- [ADR-0012](0012-feedback-tool-design.md): Feedback Tool Design
- [ADR-0013](0013-worker-resource-contention.md): Worker Resource Contention
- [ADR-0014](0014-browser-serp-resource-control.md): Browser SERP Resource Control
- [ADR-0015](0015-unified-search-sources.md): Unified Search Sources
- [ADR-0016](0016-ranking-simplification.md): Ranking Simplification
- [ADR-0017](0017-task-hypothesis-first.md): Task Hypothesis-First Architecture

---

## Reading Order for New Contributors

1. **Start here**: [ADR-0001](0001-local-first-zero-opex.md) — Understand the "why"
2. **Core model**: [ADR-0002](0002-three-layer-collaboration-model.md) — Three-layer collaboration and Search Phases
3. **Data structure**: [ADR-0005](0005-evidence-graph-structure.md) — Evidence graph basics
4. **Security**: [ADR-0006](0006-eight-layer-security-model.md) — Why containers are isolated
5. **Search flow**: [ADR-0010](0010-async-search-queue.md) + [ADR-0015](0015-unified-search-sources.md) — How searches work

---

## By Category

**Foundation** — Core principles
- [ADR-0001](0001-local-first-zero-opex.md): All ML runs locally; navigation tool, not answer generator
- [ADR-0002](0002-three-layer-collaboration-model.md): Human=Thinking, AI=Reasoning, Lyra=Working

**Protocol** — AI client integration
- [ADR-0003](0003-mcp-over-cli-rest.md): MCP protocol over stdio; no custom REST API

**Machine Learning** — Local inference
- [ADR-0004](0004-local-llm-extraction-only.md): qwen2.5:3b for extraction; DeBERTa for NLI
- [ADR-0011](0011-lora-fine-tuning.md): Domain adaptation from accumulated corrections

**Data & Evidence** — Evidence graph
- [ADR-0005](0005-evidence-graph-structure.md): Claim-Fragment-Page; Bayesian confidence; NLI edges
- [ADR-0016](0016-ranking-simplification.md): SQL views replace complex ranking
- [ADR-0017](0017-task-hypothesis-first.md): Each task has central hypothesis

**Search & Sources** — Discovery
- [ADR-0008](0008-academic-data-source-strategy.md): S2 + OpenAlex two-pillar approach
- [ADR-0010](0010-async-search-queue.md): Background job queue; immediate return
- [ADR-0015](0015-unified-search-sources.md): Parallel Browser SERP + Academic API

**Security** — Defense-in-depth
- [ADR-0006](0006-eight-layer-security-model.md): Network isolation; no exfiltration path
- [ADR-0007](0007-human-in-the-loop-auth.md): CAPTCHA/login solved by human

**Resource Management** — Performance
- [ADR-0013](0013-worker-resource-contention.md): Global rate limiter for Academic APIs
- [ADR-0014](0014-browser-serp-resource-control.md): TabPool limits concurrent browser tabs

**Feedback** — Model improvement
- [ADR-0012](0012-feedback-tool-design.md): 3-level corrections: domain/claim/edge

**Process** — Development practices
- [ADR-0009](0009-test-layer-strategy.md): L1 (unit), L2 (integration), L3 (E2E)

---

## By Evolution (Dependency Tree)

How the architecture evolved from foundational principles:

```
ADR-0001: Local-First / Zero OpEx
│   "All computation runs locally, zero operational cost"
│
├── ADR-0002: Three-Layer Collaboration Model
│   │   "Human thinks, AI reasons, Lyra works"
│   │
│   ├── ADR-0003: MCP over CLI/REST
│   │       "Standard protocol for AI client integration"
│   │
│   ├── ADR-0004: Local LLM for Extraction Only
│   │   │   "Local LLM handles extraction, not reasoning"
│   │   │
│   │   └── ADR-0006: 8-Layer Security Model
│   │       │   "Defense-in-depth with network isolation"
│   │       │
│   │       └── ADR-0007: Human-in-the-Loop Auth
│   │               "CAPTCHA/login handled by human"
│   │
│   ├── ADR-0005: Evidence Graph Structure
│   │   │   "Claims, fragments, pages with Bayesian confidence"
│   │   │
│   │   ├── ADR-0016: Ranking Simplification
│   │   │       "SQL views for evidence exploration"
│   │   │
│   │   ├── ADR-0017: Task Hypothesis-First
│   │   │       "Research driven by central hypothesis"
│   │   │
│   │   ├── ADR-0011: LoRA Fine-tuning Strategy
│   │   │   │   "Domain adaptation from human corrections"
│   │   │   │
│   │   │   └── ADR-0012: Feedback Tool Design
│   │   │           "Collect human corrections for NLI"
│   │   │
│   │   └── ADR-0008: Academic Data Source Strategy
│   │       │   "S2 + OpenAlex two-pillar approach"
│   │       │
│   │       └── ADR-0015: Unified Search Sources
│   │               "Parallel SERP + Academic API"
│   │
│   └── ADR-0010: Async Search Queue
│       │   "Background job processing for searches"
│       │
│       ├── ADR-0013: Worker Resource Contention
│       │       "Rate limiting for Academic APIs"
│       │
│       └── ADR-0014: Browser SERP Resource Control
│               "TabPool for browser isolation"
│
└── ADR-0009: Test Layer Strategy (Process)
        "L1/L2/L3 test layers"
```

---