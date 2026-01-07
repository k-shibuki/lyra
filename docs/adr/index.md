# Architecture Decision Records (ADR) Index

This document provides multiple views into Lyra's architecture decisions.

## Overview

| ADR | Title |
|-----|-------|
| [0001](0001-local-first-zero-opex.md) | Local-First / Zero OpEx |
| [0002](0002-three-layer-collaboration-model.md) | Three-Layer Collaboration Model |
| [0003](0003-mcp-over-cli-rest.md) | MCP over CLI/REST |
| [0004](0004-local-llm-extraction-only.md) | Local LLM for Extraction Only |
| [0005](0005-evidence-graph-structure.md) | Evidence Graph Structure |
| [0006](0006-eight-layer-security-model.md) | 8-Layer Security Model |
| [0007](0007-human-in-the-loop-auth.md) | Human-in-the-Loop Authentication |
| [0008](0008-academic-data-source-strategy.md) | Academic Data Source Strategy |
| [0009](0009-test-layer-strategy.md) | Test Layer Strategy |
| [0010](0010-async-search-queue.md) | Async Search Queue Architecture |
| [0011](0011-lora-fine-tuning.md) | LoRA Fine-tuning Strategy |
| [0012](0012-feedback-tool-design.md) | Feedback Tool Design |
| [0013](0013-worker-resource-contention.md) | Worker Resource Contention |
| [0014](0014-browser-serp-resource-control.md) | Browser SERP Resource Control |
| [0015](0015-unified-search-sources.md) | Unified Search Sources |
| [0016](0016-ranking-simplification.md) | Ranking Simplification |
| [0017](0017-task-hypothesis-first.md) | Task Hypothesis-First Architecture |

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

## By Category

### Foundation
Core principles that shape all other decisions.

| ADR | Title | Key Decision |
|-----|-------|--------------|
| [0001](0001-local-first-zero-opex.md) | Local-First / Zero OpEx | All ML runs locally; navigation tool, not answer generator |
| [0002](0002-three-layer-collaboration-model.md) | Three-Layer Collaboration | Human=Thinking, AI=Reasoning, Lyra=Working; Search Phases (P1/P2/P3) |

### Protocol & Integration
How Lyra communicates with AI clients.

| ADR | Title | Key Decision |
|-----|-------|--------------|
| [0003](0003-mcp-over-cli-rest.md) | MCP over CLI/REST | MCP protocol over stdio; no custom REST API |

### Machine Learning
Local inference and model improvement.

| ADR | Title | Key Decision |
|-----|-------|--------------|
| [0004](0004-local-llm-extraction-only.md) | Local LLM Extraction Only | qwen2.5:3b for extraction; DeBERTa for NLI; no reasoning |
| [0011](0011-lora-fine-tuning.md) | LoRA Fine-tuning | Domain adaptation from accumulated corrections |

### Data & Evidence
Evidence graph structure and exploration.

| ADR | Title | Key Decision |
|-----|-------|--------------|
| [0005](0005-evidence-graph-structure.md) | Evidence Graph Structure | Claim-Fragment-Page; Bayesian confidence; NLI edges |
| [0016](0016-ranking-simplification.md) | Ranking Simplification | SQL views replace complex ranking; MCP client drives exploration |
| [0017](0017-task-hypothesis-first.md) | Task Hypothesis-First | Each task has central hypothesis; guides extraction |

### Search & Sources
How Lyra discovers and retrieves sources.

| ADR | Title | Key Decision |
|-----|-------|--------------|
| [0008](0008-academic-data-source-strategy.md) | Academic Data Source | S2 (references) + OpenAlex (free metadata) |
| [0010](0010-async-search-queue.md) | Async Search Queue | Background job queue; immediate return |
| [0015](0015-unified-search-sources.md) | Unified Search Sources | Parallel Browser SERP + Academic API; ID extraction |

### Security
Defense-in-depth and authentication.

| ADR | Title | Key Decision |
|-----|-------|--------------|
| [0006](0006-eight-layer-security-model.md) | 8-Layer Security | Network isolation; no exfiltration path for injected prompts |
| [0007](0007-human-in-the-loop-auth.md) | Human-in-the-Loop Auth | CAPTCHA/login solved by human; auth queue |

### Resource Management
Performance and resource control.

| ADR | Title | Key Decision |
|-----|-------|--------------|
| [0013](0013-worker-resource-contention.md) | Worker Resource Contention | Global rate limiter for Academic APIs |
| [0014](0014-browser-serp-resource-control.md) | Browser SERP Resource | TabPool limits concurrent browser tabs |

### Quality & Feedback
Human corrections and model improvement.

| ADR | Title | Key Decision |
|-----|-------|--------------|
| [0012](0012-feedback-tool-design.md) | Feedback Tool Design | 3-level corrections: domain/claim/edge |

### Process
Development and testing practices.

| ADR | Title | Key Decision |
|-----|-------|--------------|
| [0009](0009-test-layer-strategy.md) | Test Layer Strategy | L1 (unit), L2 (integration), L3 (E2E) |

---

## Reading Order for New Contributors

1. **Start here**: [ADR-0001](0001-local-first-zero-opex.md) — Understand the "why"
2. **Core model**: [ADR-0002](0002-three-layer-collaboration-model.md) — Three-layer collaboration and Search Phases
3. **Data structure**: [ADR-0005](0005-evidence-graph-structure.md) — Evidence graph basics
4. **Security**: [ADR-0006](0006-eight-layer-security-model.md) — Why containers are isolated
5. **Search flow**: [ADR-0010](0010-async-search-queue.md) + [ADR-0015](0015-unified-search-sources.md) — How searches work

