# Lyra

> **L**ocal **Y**ielding **R**esearch **A**ide — An MCP Toolkit with Embedded ML for AI-Collaborative Desktop Research

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-3000%2B-success.svg)](tests/)

---

## Terminology

| Term | Meaning |
|------|---------|
| **MCP** | [Model Context Protocol](https://modelcontextprotocol.io/) — a standard for AI models to invoke external tools with structured input/output |
| **CDP** | [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/) — interface for browser automation via remote debugging |
| **NLI** | Natural Language Inference — ML task to determine if one text supports, refutes, or is neutral to another |
| **LLM** | Large Language Model — AI model for text understanding/generation (e.g., GPT-4, Claude, Qwen) |

---

## Summary

Lyra is an open-source toolkit for AI-collaborative desktop research. It exposes research capabilities (search, content extraction, claim verification) as tools that AI assistants can directly invoke via **MCP (Model Context Protocol)**—a standard interface that lets AI models call external functions.

**What this means in practice**: When you ask Cursor AI or Claude Desktop to "research drug X safety", the AI decides *what* to search and designs queries—then calls Lyra's `search` tool to execute them. Lyra fetches pages, extracts claims, detects supporting/refuting evidence, and returns structured results. The AI never sees raw HTML or manages rate limits; Lyra handles mechanical execution while the AI focuses on reasoning.

This **thinking-working separation** keeps the AI's context clean for strategic decisions while offloading compute-intensive ML tasks (embedding, NLI) to Lyra's local runtime.

**MCP Compatibility**: Lyra is protocol-compliant and works with any MCP client—[Cursor AI](https://cursor.sh/), [Claude Desktop](https://claude.ai/desktop), [Zed Editor](https://zed.dev/), or other MCP-enabled tools. The "thinking" side requires Claude/GPT-4-class reasoning capability.

**Embedded ML Components:**

| Component | Model | License | Purpose |
|-----------|-------|---------|---------|
| Local LLM | Qwen2.5-3B (Ollama) | Qwen Research* | Fact/claim extraction, quality assessment |
| Embedding | bge-m3 | MIT | Semantic similarity for candidate ranking |
| NLI | DeBERTa-v3 | Apache-2.0 | Stance detection (supports/refutes/neutral) |

*\*Qwen2.5-3B uses the Qwen Research License (non-commercial). See [Model Licenses](#model-licenses) for alternatives.*

**Core Design Principles:**

1. **Complete Local Processing**: All data remains on the user's machine. Search queries and collected information are never transmitted to external servers.
2. **Thinking-Working Separation**: The MCP client decides *what* to search; Lyra executes *how* to search. Lyra never proposes queries or makes strategic decisions.
3. **Evidence Graph Construction**: Every claim is linked to source fragments with provenance tracking, enabling verification and reproducibility.

---

## Statement of Need

### The Problem

AI-assisted web research faces a fundamental tension: powerful reasoning models (GPT-4, Claude) are cloud-based, but transmitting research queries and collected evidence to external servers is unacceptable for sensitive domains. Existing approaches force a choice:

- **Use cloud AI with web access**: Queries and findings leave the machine
- **Use local tools only**: Lose frontier reasoning capability

Lyra resolves this by **separating concerns**: the MCP client (cloud AI) handles reasoning; Lyra handles data collection locally. Research data never leaves the machine.

### Why Auditability Matters

In domains like healthcare research, a hallucinated claim can be fatal. Lyra constructs an **evidence graph** where every claim links to source fragments with provenance metadata. This enables:

- **Verification**: Trace any claim back to its source URL and extracted text
- **Reproducibility**: Replay research sessions with identical results
- **Accountability**: Full audit trail from question to conclusion

### Target Use Cases

- **Healthcare-Related Research**: Drug safety, clinical evidence—where hallucinations can be fatal. Full auditability from claim to source is critical.
- **Legal & Compliance Teams**: Research requiring strict confidentiality
- **Independent Researchers & Journalists**: Cost-effective alternative to commercial tools
- **Security-Conscious Organizations**: Auditable, deployable within controlled environments

> **Status**: Lyra is a working prototype. Core functionality is implemented and tested, but APIs may change.

### Differentiation from Existing Tools

Unlike browser automation tools (Selenium, Playwright scripts) that require custom coding for each task, Lyra provides:

1. **Unified Research Pipeline**: Search, fetch, extract, and evaluate in a single workflow
2. **Evidence Graph**: Structured claim-fragment-source relationships, not just raw text
3. **AI-Assisted Filtering**: Local LLM (Ollama) extracts facts and assesses source quality
4. **Multi-Engine Search**: Aggregates results from DuckDuckGo, Mojeek, Brave, academic APIs, and more
5. **Human-in-the-Loop**: Graceful handling of CAPTCHAs and authentication via intervention queues

---

## Why This Design

### Why Thinking-Working Separation?

Research requires both strategic reasoning ("what should I search next?") and mechanical execution ("fetch this URL, parse that HTML"). Mixing these in one context creates problems:

- **Context pollution**: Raw HTML, rate-limit errors, and parsing details crowd out strategic thinking
- **Inference cost**: Large AI models process every token; mechanical work wastes expensive reasoning capacity
- **Reproducibility**: Interleaved logic makes it hard to replay or audit a research session

Lyra delegates mechanical work to a local runtime while the AI focuses purely on strategy. The AI never sees raw page content—only structured claims with provenance metadata.

### Why MCP (Not CLI)?

| Approach | Pros | Cons |
|----------|------|------|
| **CLI scripts** | Simple to build, no protocol overhead | AI must parse stdout, no structured typing, hard to iterate |
| **REST API** | Familiar, language-agnostic | Requires server lifecycle management, authentication complexity |
| **MCP** | Structured tool calls, native AI integration, bidirectional communication | Protocol learning curve |

MCP was designed specifically for AI-tool communication. It provides typed tool schemas, progress notifications, and error handling that map directly to how AI assistants work. Since Lyra exists to be called by AI, MCP is the natural fit.

### Why Local LLM?

Commercial APIs (GPT-4, Claude) would provide better extraction quality but violate Lyra's core principle: **no data leaves the machine**. Research queries and collected evidence may be sensitive; transmitting them to external APIs defeats the purpose.

The embedded Qwen2.5-3B handles fact extraction and quality assessment. It's not as capable as frontier models, but:
- Runs entirely on local GPU (8GB VRAM)
- Zero API cost, zero data transmission
- Consistent behavior across sessions

The MCP client (Cursor AI, Claude Desktop) provides frontier reasoning for strategy; Lyra's local LLM handles only mechanical extraction tasks where 3B performance is sufficient.

---

## System Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Windows 11 Host                             │
│  ┌──────────────┐                                                   │
│  │ MCP Client   │  ◄── User designs queries, composes reports       │
│  │  (Thinking)  │      (Cursor AI, Claude Desktop, etc.)            │
│  └──────┬───────┘                                                   │
│         │ MCP Protocol (stdio)                                      │
│  ┌──────▼───────────────────────────────────────────────────────┐   │
│  │                      WSL2 (Ubuntu)                            │   │
│  │  ┌──────────────────────────────────────────────────────┐    │   │
│  │  │              Lyra MCP Server (Python)                 │    │   │
│  │  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │    │   │
│  │  │  │ Search  │  │ Crawler │  │ Filter  │  │Research │  │    │   │
│  │  │  │Provider │  │(Fetcher)│  │  (LLM)  │  │Pipeline │  │    │   │
│  │  │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  │    │   │
│  │  │       │            │            │            │        │    │   │
│  │  │       └────────────┴─────┬──────┴────────────┘        │    │   │
│  │  │                          │                             │    │   │
│  │  │              ┌───────────▼───────────┐                │    │   │
│  │  │              │   Evidence Graph      │                │    │   │
│  │  │              │   (SQLite + NetworkX) │                │    │   │
│  │  │              └───────────────────────┘                │    │   │
│  │  └──────────────────────────────────────────────────────┘    │   │
│  │         │                    │                                │   │
│  │         │ CDP:9222           │ HTTP                           │   │
│  │         ▼                    ▼                                │   │
│  │  ┌──────────────┐    ┌──────────────────────────────────┐    │   │
│  │  │Chrome Profile│    │       Podman Containers          │    │   │
│  │  │ (Research)   │    │  ┌────────┐ ┌────────┐ ┌─────┐  │    │   │
│  │  └──────────────┘    │  │ Ollama │ │ML Server│ │ Tor │  │    │   │
│  │                       │  │(LLM)   │ │(Embed/ │ │     │  │    │   │
│  │                       │  │        │ │  NLI)  │ │     │  │    │   │
│  │                       │  └────────┘ └────────┘ └─────┘  │    │   │
│  │                       └──────────────────────────────────┘    │   │
│  └───────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Task Creation**: User provides a research question via MCP client → `create_task` MCP tool
2. **Query Execution**: MCP client designs search queries → `search` tool executes pipeline:
   - Search engine query (Playwright browser automation)
   - URL fetching with rate limiting and block detection
   - Content extraction (trafilatura)
   - LLM-based fact/claim extraction (Ollama)
   - NLI stance detection (supports/refutes/neutral)
   - Evidence graph construction
3. **Iterative Refinement**: MCP client reviews metrics via `get_status`, designs follow-up queries
4. **Evidence Exploration**: `query_graph` (SQL) and `vector_search` (semantic) enable granular evidence graph exploration

### Key Modules

| Module | Location | Responsibility |
|--------|----------|----------------|
| **MCP Server** | `src/mcp/` | 11 tools for MCP client integration (per ADR-0010 async architecture) |
| **Search Providers** | `src/search/` | Multi-engine search, academic APIs |
| **Citation Filter** | `src/search/citation_filter.py` | 2-stage relevance filtering (embedding + LLM) for citation tracking |
| **Crawler** | `src/crawler/` | Browser automation, HTTP fetching, session management |
| **Filter** | `src/filter/` | LLM extraction, NLI analysis, ranking |
| **Research Pipeline** | `src/research/` | Orchestration, state management |
| **Storage** | `src/storage/` | SQLite database, migrations |
| **ML Server** | `src/ml_server/` | Embedding (bge-m3), NLI models |

---

## Key Concepts

### Evidence Graph

Lyra maintains a directed graph linking claims to supporting evidence:

```
                    ┌─────────────────┐
                    │   Claim: C1     │
                    │ "Drug X reduces │
                    │  mortality by   │
                    │  15%"           │
                    └────────┬────────┘
                             │
           ┌─────────────────┼─────────────────┐
           │                 │                 │
     [supports]         [supports]        [refutes]
     conf: 0.92         conf: 0.87        conf: 0.78
           │                 │                 │
           ▼                 ▼                 ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ Fragment: F1 │ │ Fragment: F2 │ │ Fragment: F3 │
    │ FDA Warning  │ │ Clinical     │ │ Manufacturer │
    │ Letter       │ │ Trial Data   │ │ Press Release│
    └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
           │                 │                 │
           ▼                 ▼                 ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ Page: P1     │ │ Page: P2     │ │ Page: P3     │
    │ fda.gov      │ │ pubmed.gov   │ │ company.com  │
    │ trust:GOV    │ │ trust:ACAD   │ │ trust:LOW    │
    └──────────────┘ └──────────────┘ └──────────────┘
```

### Domain Categories

Sources are classified by institutional category for **ranking adjustment only** (not used in confidence calculation—confidence is computed purely from fragment-level NLI scores):

| Category | Description |
|----------|-------------|
| `PRIMARY` | Standards bodies, registries (iso.org, ietf.org) |
| `GOVERNMENT` | Government agencies (.go.jp, .gov) |
| `ACADEMIC` | Academic/research institutions (arxiv.org, pubmed.gov) |
| `TRUSTED` | Curated knowledge bases (wikipedia.org) |
| `LOW` | Verified through L6 (promoted from UNVERIFIED) |
| `UNVERIFIED` | Unknown domains (default) |
| `BLOCKED` | Excluded (high rejection rate or contradiction) |

**How categories are assigned:**

1. **Pre-assigned (allowlist)**: Known domains in `config/domains.yaml` have fixed categories
2. **Unknown domains**: Start as `UNVERIFIED`
3. **L6 verification** promotes/demotes based on evidence (see `src/filter/source_verification.py`):
   - Corroborated by ≥2 independent sources → `UNVERIFIED` promoted to `LOW`
   - Contradiction detected → `UNVERIFIED` demoted to `BLOCKED`
   - Rejection rate >30% → `UNVERIFIED`/`LOW` demoted to `BLOCKED`
   - Higher categories (PRIMARY–TRUSTED): marked REJECTED but not auto-demoted

### Security Architecture (8 Layers)

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| L1 | Network isolation | Ollama runs in internal-only container network |
| L2 | Input sanitization | Unicode normalization, dangerous pattern removal |
| L3 | Session tags | Enabled by default: in-band delimiters that enclose INPUT DATA to create a hard boundary (defense-in-depth). Can be disabled via `LYRA_LLM__SESSION_TAGS_ENABLED=false`. |
| L4 | Output validation | Detect leaked prompts, suspicious URLs |
| L5 | Response metadata | Trust levels attached to all MCP responses |
| L6 | Source verification | Automatic promotion/demotion based on evidence |
| L7 | Schema validation | MCP responses validated before return |
| L8 | Secure logging | No prompts written to logs |

---

## Installation

### Prerequisites

- **OS**: Windows 11 + WSL2 (Ubuntu 22.04 or 24.04)
- **Python**: 3.14.* (required, see `pyproject.toml`)
- **Browser**: Google Chrome (for CDP remote debugging)
- **Container Runtime**: Podman (recommended) or Docker

**Reference Environment** (tested configuration; lower specs may work):

| Resource | Reference Spec | Notes |
|----------|----------------|-------|
| RAM | 64GB host, 32GB WSL2 | Lower limits not yet determined |
| GPU | NVIDIA RTX 4060 Laptop (8GB VRAM) | **Required** (no CPU fallback) |
| Storage | ~25 GB | ML image (~3GB) + models on host (~1.4GB) + Ollama models (~5GB) + data |

The default `podman-compose.yml` expects GPU access via CDI. **CPU-only operation is not supported.**

### Quick Start

```bash
# 1. Clone and check environment
git clone https://github.com/k-shibuki/lyra.git
cd lyra
make doctor             # Check dependencies and configuration

# 2. Setup Python environment (using uv)
curl -LsSf https://astral.sh/uv/install.sh | sh  # Install uv if needed
make setup              # Install MCP server dependencies

# 3. Configure and start services
cp .env.example .env
make dev-build          # Build containers (first time or after changes)
make dev-up             # Start containers (auto-downloads models if needed)
make doctor-chrome-fix  # Fix WSL2 networking if needed
make chrome-start       # Start Chrome with CDP

# 4. Configure MCP client (see below)
```

### Makefile Commands

All operations are available via `make`. Run `make help` for the full list.

**Setup:**

| Command | Purpose |
|---------|---------|
| `make doctor` | Check environment dependencies and configuration |
| `make setup` | Install dependencies with uv (MCP extras) |
| `make setup-full` | Install all dependencies (full development) |
| `make setup-dev` | Install development dependencies |
| `make setup-ml-models` | Download ML models to host (embedding + NLI) |

**Development Environment:**

| Command | Purpose |
|---------|---------|
| `make dev-build` | Build containers (required before dev-up) |
| `make dev-up` | Start containers (requires dev-build first) |
| `make dev-down` | Stop containers |
| `make dev-shell` | Enter development shell with container network access |
| `make dev-logs` | Show container logs (tail) |
| `make dev-status` | Show container status |
| `make dev-clean` | Remove containers and images |

**Doctor (Environment Check):**

| Command | Purpose |
|---------|---------|
| `make doctor` | Check environment dependencies and configuration |
| `make doctor-chrome-fix` | Fix WSL2 Chrome networking issues |

**Chrome / Browser:**

| Command | Purpose |
|---------|---------|
| `make chrome` | Check Chrome CDP status (all workers) |
| `make chrome-start` | Start Chrome pool (one per worker) |
| `make chrome-stop` | Stop all Chrome instances |
| `make chrome-restart` | Restart Chrome pool |
| `make chrome-diagnose` | Diagnose connection issues |

**Testing:**

| Command | Purpose |
|---------|---------|
| `make test` | Run all tests (use test-check for results; TARGET= for specific files) |
| `make test TARGET="tests/test_foo.py"` | Run specific test files |
| `make test-unit` | Run unit tests only (TARGET= for specific files) |
| `make test-e2e` | Run E2E tests (TARGET= for specific files) |
| `make test-check` | Check test run status (RUN_ID= optional) |
| `make test-env` | Show environment detection info |
| `make test-prompts` | Run prompt template tests (syntax, rendering, structure) |
| `make test-llm-output` | Run LLM output parsing tests |

**Code Quality:**

| Command | Purpose |
|---------|---------|
| `make lint` | Run linters (ruff, Python only) |
| `make format` | Format code (black + ruff) |
| `make typecheck` | Run type checker (mypy) |
| `make jsonschema` | Validate JSON Schema files |
| `make shellcheck` | Run shellcheck on scripts |
| `make quality` | Run all quality checks (lint + typecheck + jsonschema + shellcheck) |

**JSON Output Mode (for AI agents):**

Set `LYRA_OUTPUT_JSON=true` for machine-readable JSON output:

```bash
# Single command
LYRA_OUTPUT_JSON=true make lint

# Or add to .env for persistent JSON mode
echo "LYRA_OUTPUT_JSON=true" >> .env
```

All commands (`make lint`, `make typecheck`, `make test-env`, `make dev-status`, `make chrome`, etc.) automatically switch to JSON output when this variable is set.

**Test execution**: Tests run in WSL venv (`.venv/`) by default. The script auto-detects:
- Cloud agents (Cursor, Claude Code) → unit + integration only
- Container environment → enables ML/extractor tests
- Local WSL → unit + integration (add `LYRA_TEST_LAYER=e2e` for E2E)

### WSL2 Network Configuration

For WSL2 to communicate with Windows Chrome via CDP:

Run `make doctor-chrome-fix` to automatically configure mirrored networking mode.

Alternatively, manually:

1. Create or edit `%USERPROFILE%\.wslconfig`:
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```
2. Restart WSL: `wsl.exe --shutdown`

### MCP Client Configuration

Lyra works with any MCP-compatible client. Example configurations:

**Cursor AI** (`.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "lyra": {
      "command": "/path/to/lyra/.venv/bin/python",
      "args": ["-m", "src.main", "mcp"],
      "cwd": "/path/to/lyra"
    }
  }
}
```

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "lyra": {
      "command": "/path/to/lyra/.venv/bin/python",
      "args": ["-m", "src.main", "mcp"],
      "cwd": "/path/to/lyra"
    }
  }
}
```

---

## Usage

### MCP Tools (10 Tools)

Lyra exposes the following tools to MCP clients:

| Category | Tool | Description |
|----------|------|-------------|
| **Task Management** | `create_task` | Create a new research task |
| | `get_status` | Get unified task status, metrics, and budget (supports long polling with `wait` parameter) |
| **Research** | `queue_searches` | Queue multiple search queries for background execution (non-blocking) |
| | `stop_task` | Finalize a task |
| **Materials** | `get_materials` | Retrieve claims, fragments, and evidence graph |
| **Calibration** | `calibration_metrics` | Get statistics, evaluate calibration performance |
| | `calibration_rollback` | Rollback calibration parameters |
| **Auth Queue** | `get_auth_queue` | Get pending authentication requests |
| | `resolve_auth` | Report authentication completion |
| **Feedback** | `feedback` | Human-in-the-loop feedback (domain/claim/edge management) |

> **Note**: Per ADR-0010, `search`, `notify_user`, `wait_for_user` were removed.
> Use `queue_searches` + `get_status(wait=N)` for non-blocking search execution.

### Example Research Workflow

```python
# 1. Create a research task
create_task(query="Liraglutide cardiovascular safety profile")
# Returns: {"task_id": "task_abc123", "budget": {"budget_pages": 120}}

# 2. Queue multiple search queries (non-blocking, immediate response)
queue_searches(
    task_id="task_abc123",
    queries=[
        "liraglutide FDA cardiovascular warning",
        "liraglutide LEADER trial results",
        "liraglutide cardiovascular risk"
    ],
    options={"priority": "high"}
)
# Returns: {"ok": true, "queued_count": 3, "search_ids": ["s_1", "s_2", "s_3"]}

# 3. Monitor progress with long polling (server waits up to N seconds before responding)
get_status(task_id="task_abc123", wait=10)
# Returns: {
#   "searches": [...],
#   "queue": {"depth": 1, "running": 1, "items": [...]},
#   "budget": {"remaining_percent": 45},
#   "blocked_domains": [...],
#   "idle_seconds": 12.5,
#   "evidence_summary": {"total_claims": 42, "total_fragments": 87, ...}  # when completed
# }

# 4. Explore evidence graph with SQL
query_graph(sql="SELECT * FROM v_contradictions ORDER BY controversy_score DESC LIMIT 10")
# Returns: {"ok": true, "rows": [...], "row_count": 10}

# 5. Semantic search for related claims
vector_search(query="cardiovascular safety concerns", target="claims", task_id="task_abc123")
# Returns: {"ok": true, "results": [{"id": "c_123", "similarity": 0.89, "text_preview": "..."}]}

# 6. Finalize task
stop_task(task_id="task_abc123", reason="completed")
```

---

## Configuration

### Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Environment variables (ports, paths, model selection) |
| `config/settings.yaml` | Core settings (timeouts, budgets, thresholds) |
| `config/local.yaml` | Local overrides (gitignored, see `local.yaml.example`) |
| `config/engines.yaml` | Search engine definitions and priorities |
| `config/domains.yaml` | Domain trust levels and rate policies |
| `config/search_parsers.yaml` | HTML selectors for search result parsing |
| `config/academic_apis.yaml` | Academic API endpoints (Semantic Scholar, OpenAlex, etc.) |

### Local Configuration Overrides

For local customization without modifying tracked files, create `config/local.yaml`:

```bash
cp config/local.yaml.example config/local.yaml
```

**Override priority** (lowest to highest):

1. Base YAML files (`settings.yaml`, `academic_apis.yaml`, etc.)
2. `local.yaml` (section-based overrides)
3. Environment variables (`LYRA_*` prefix)

**Example `local.yaml`**:

```yaml
# Top-level keys = target config file (without .yaml)
settings:
  task_limits:
    cursor_idle_timeout_seconds: 180
  concurrency:
    browser_serp:
      max_tabs: 2

academic_apis:
  apis:
    semantic_scholar:
      enabled: false
```

**Environment variable alternative** (for CI/containers):

```bash
LYRA_TASK_LIMITS__CURSOR_IDLE_TIMEOUT_SECONDS=180
LYRA_GENERAL__LOG_LEVEL=DEBUG
```

### Key Settings

```yaml
# config/settings.yaml
task_limits:
  budget_pages_per_task: 120     # Page fetch budget per task
  max_time_minutes_gpu: 20       # Time budget (GPU mode)

search:
  min_independent_sources: 3     # Required for claim satisfaction
  novelty_threshold: 0.10        # Stop when novelty drops below 10%
  
  # Citation tracking (Phase 3)
  citation_graph_top_n_papers: 5  # Number of papers to process for citation expansion
  citation_graph_depth: 1         # Citation graph depth
  citation_graph_direction: "both" # "references", "citations", or "both"
  citation_filter:
    # Stage 1: Embedding + impact_score (fast coarse filter)
    stage1_top_k: 30
    stage1_weight_embedding: 0.5
    stage1_weight_impact: 0.5
    
    # Stage 2: LLM evidence-usefulness + Stage 1 signals (precise selection)
    stage2_top_k: 10
    stage2_weight_llm: 0.5
    stage2_weight_embedding: 0.3
    stage2_weight_impact: 0.2
    
    # Prompt/input limits
    max_source_abstract_chars: 1200
    max_target_abstract_chars: 1200
    llm_timeout_seconds: 60.0
    llm_max_tokens: 16

crawler:
  engine_qps: 0.25               # Requests per second per engine
  domain_qps: 0.2                # Requests per second per domain
```

---

## Quality Control

### Testing

Lyra includes 3000+ tests across three layers (see [ADR-0009](docs/adr/0009-test-layer-strategy.md) for rationale):

| Layer | Scope | External Dependencies | Command |
|:-----:|-------|----------------------|---------|
| L1 | Unit | None (all mocked) | `pytest -m "not e2e and not slow"` |
| L2 | Integration | SQLite real, others mocked | (same as L1) |
| L3 | E2E | All real (Chrome, Ollama, network) | `pytest -m e2e` |

```bash
# Run tests via Makefile (recommended - handles venv and environment detection)
make test                                 # Unit + integration tests
make test-check                           # Check completion
make test TARGET="tests/test_foo.py"      # Specific test files
make test-e2e                             # E2E tests (requires Chrome CDP + containers)

# Or run pytest directly in venv
source .venv/bin/activate
pytest tests/ -m 'not e2e' --tb=short -q  # Unit + integration
pytest tests/ -m 'e2e'                    # E2E (requires Chrome CDP + containers)
```

#### DB Isolation: Tests vs Scripts

| Scenario | Mechanism | Notes |
|----------|-----------|-------|
| pytest tests | `test_database` fixture (`tests/conftest.py`) | Auto setup/teardown per test |
| Debug scripts / manual verification | `isolated_database_path()` (`src/storage/isolation.py`) | Auto cleanup on block exit |

For standalone scripts that need a fresh, reproducible DB without touching `data/lyra.db`, use the async context manager:

```python
import asyncio

from src.storage.database import get_database
from src.storage.isolation import isolated_database_path


async def main() -> None:
    async with isolated_database_path() as _db_path:
        db = await get_database()
        _ = await db.fetch_one("SELECT 1")


asyncio.run(main())
```

**Running debug scripts**:

```bash
# Use venv Python directly (test.sh is pytest-only)
./.venv/bin/python tests/scripts/debug_{feature}_flow.py
```

### Test Markers

| Marker | Description | CI/Cloud | Local | Full |
|--------|-------------|:--------:|:-----:|:----:|
| `unit` | No external dependencies, fast | ✅ | ✅ | ✅ |
| `integration` | Mocked external dependencies | ✅ | ✅ | ✅ |
| `e2e` | Real environment required | ❌ | ⚠️ | ✅ |
| `slow` | Tests taking >5 seconds | ❌ | ⚠️ | ✅ |
| `external` | E2E + moderate block risk (Mojeek, Qwant) | ❌ | ❌ | ✅ |
| `rate_limited` | E2E + high block risk (DuckDuckGo) | ❌ | ❌ | ✅ |
| `manual` | Requires human interaction (CAPTCHA) | ❌ | ❌ | ✅ |

### Cloud Agent / CI Environment

The test runner auto-detects cloud agent environments (Cursor, Claude Code, GitHub Actions, GitLab CI) and automatically excludes E2E/slow tests:

| Environment | Detection Method |
|-------------|------------------|
| Cursor Cloud Agent | `CURSOR_CLOUD_AGENT`, `CURSOR_SESSION_ID`, `CURSOR_BACKGROUND` |
| Claude Code | `CLAUDE_CODE` |
| GitHub Actions | `GITHUB_ACTIONS=true` |
| Generic CI | `CI=true` |

**⚠️ Important**: After CI/cloud agent testing, run E2E tests locally:

```bash
pytest -m e2e      # E2E tests (Chrome, Ollama required)
pytest -m slow     # Slow tests (>5s)
pytest             # All tests
```

**Environment variables**:

| Variable | Description |
|----------|-------------|
| `LYRA_TEST_LAYER=e2e` | Run E2E tests explicitly |
| `LYRA_TEST_LAYER=all` | Run all tests |
| `LYRA_LOCAL=1` | Force local mode (disable cloud detection) |

### Code Quality

```bash
# Using Makefile (recommended)
make lint       # Lint check
make typecheck  # Type check
make quality    # Run all quality checks

# Or run directly
uv run ruff check src/ tests/
uv run mypy src/
```

---

## For Developers

### Project Structure

```
lyra/
├── src/
│   ├── main.py              # CLI entry point (init, research, mcp)
│   ├── mcp/                  # MCP server and tool handlers
│   │   ├── server.py         # Tool definitions and dispatch
│   │   ├── errors.py         # Error code definitions
│   │   └── response_sanitizer.py  # L7 security layer
│   ├── search/               # Search providers
│   │   ├── browser_search_provider.py  # Playwright-based search
│   │   ├── academic_provider.py        # Semantic Scholar, OpenAlex, etc.
│   │   └── circuit_breaker.py          # Rate limiting
│   ├── crawler/              # Web fetching
│   │   ├── fetcher.py        # URL fetching with caching
│   │   ├── browser_provider.py  # Browser instance management
│   │   └── human_behavior.py    # Anti-detection measures
│   ├── filter/               # LLM processing
│   │   ├── llm.py            # Ollama integration
│   │   ├── llm_security.py   # L2-L4 security layers
│   │   ├── evidence_graph.py # Graph construction
│   │   └── nli.py            # Stance detection
│   ├── research/             # Pipeline orchestration
│   │   ├── pipeline.py       # Main research pipeline
│   │   ├── executor.py       # Search execution
│   │   └── state.py          # Exploration state machine
│   ├── storage/              # Database layer
│   │   ├── database.py       # Async SQLite operations
│   │   └── schema.sql        # Database schema
│   └── utils/                # Utilities
│       ├── config.py         # YAML configuration loading
│       └── logging.py        # JSON structured logging
├── config/                   # Configuration files
├── scripts/                  # Shell scripts (dev.sh, chrome.sh)
├── tests/                    # Test suites
├── migrations/               # Database migrations
└── docs/                     # Documentation
```

### Key Entry Points

1. **MCP Server**: `src/mcp/server.py` — Start here to understand tool dispatch
2. **Research Pipeline**: `src/research/pipeline.py` — Core orchestration logic
3. **Evidence Graph**: `src/filter/evidence_graph.py` — Claim-fragment relationships
4. **Security Layers**: `src/filter/llm_security.py` — L2-L4 implementation

### Adding a New Search Engine

1. Add engine definition to `config/engines.yaml`
2. Add HTML selectors to `config/search_parsers.yaml`
3. Implement parser in `src/search/search_parsers.py`
4. Add tests in `tests/test_search_parsers.py`

---

## Limitations

- **Platform Dependency**: Currently requires Windows 11 + WSL2 environment
- **HTML Selector Maintenance**: Search engine HTML changes may require selector updates
- **GPU Required**: ML inference requires NVIDIA GPU + CUDA (no CPU fallback)
- **Chrome Dependency**: Browser-based operations require Chrome with CDP

---

## Roadmap

- [ ] LoRA fine-tuning for domain-specific NLI adaptation (see [T_LORA.md](docs/T_LORA.md))

---

## Documentation

| Document | Description |
|----------|-------------|
| [ADRs](docs/adr/) | Architecture Decision Records (16 ADRs) |
| [T_LORA.md](docs/T_LORA.md) | LoRA fine-tuning design (planned) |
| [archive/](docs/archive/) | Historical snapshots (not maintained) |

### Directory Structure

```
docs/
├── adr/           # Architecture Decision Records (16 ADRs)
├── archive/       # Historical snapshots (not maintained)
└── T_LORA.md
```

---

## Contributing

Contributions are welcome. Please:

1. Read the [ADRs](docs/adr/) for design context
2. Ensure tests pass before submitting pull requests
3. Follow existing code style (enforced by ruff)

```bash
# Before committing (using Makefile)
make test           # Run unit + integration tests
make quality        # Run lint + typecheck

# Or run directly
make test-check     # Check test completion
```

---

## License

This project is licensed under the [MIT License](LICENSE).

### Model Licenses

Lyra depends on external ML models with their own licenses:

| Model | License | Commercial Use | Source |
|-------|---------|----------------|--------|
| Qwen2.5-3B | Qwen Research License | ❌ No | [Hugging Face](https://huggingface.co/Qwen/Qwen2.5-3B) |
| Qwen2.5-7B | Apache-2.0 | ✅ Yes | [Hugging Face](https://huggingface.co/Qwen/Qwen2.5-7B) |
| bge-m3 | MIT | ✅ Yes | [Hugging Face](https://huggingface.co/BAAI/bge-m3) |
| nli-deberta-v3-small | Apache-2.0 | ✅ Yes | [Hugging Face](https://huggingface.co/cross-encoder/nli-deberta-v3-small) |

**Note**: The default LLM (Qwen2.5-3B) uses a research-only license. For commercial use, configure an alternative model in `.env`:

```bash
# .env
LYRA_LLM__MODEL=qwen2.5:7b    # Apache-2.0, commercial OK
  # or
LYRA_LLM__MODEL=llama3.2:3b   # Llama License, commercial OK
```

Then restart containers:
```bash
make dev-down
make dev-up  # Auto-pulls new Ollama model
```

### Changing Models

All model names are configured in `.env` (Single Source of Truth). To change models:

1. Edit `.env`:
   ```bash
   # LLM (Ollama)
   LYRA_LLM__MODEL=qwen2.5:7b
   
   # ML Server (HuggingFace)
   LYRA_ML__EMBEDDING_MODEL=BAAI/bge-m3
   LYRA_ML__NLI_MODEL=cross-encoder/nli-deberta-v3-base
   ```

2. Download new models (if ML models changed):
   ```bash
   make setup-ml-models
   ```

3. Restart containers:
   ```bash
   make dev-down
   make dev-up  # Auto-pulls Ollama model, mounts ML models from host
```

---

## Citation

*Paper in preparation. Citation information will be added upon publication.*

---

## Acknowledgments

- [Ollama](https://ollama.ai/) — Local LLM runtime
- [Playwright](https://playwright.dev/) — Browser automation
- [Cursor](https://cursor.sh/) — AI-integrated development environment
- [trafilatura](https://trafilatura.readthedocs.io/) — Web content extraction
- [NetworkX](https://networkx.org/) — Graph data structures
- [Semantic Scholar](https://www.semanticscholar.org/) — Academic paper API
- [OpenAlex](https://openalex.org/) — Open scholarly metadata
