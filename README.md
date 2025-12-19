# Lyra

> **L**ocal **Y**ielding **R**esearch **A**ide — An MCP Toolkit with Embedded ML for AI-Collaborative Desktop Research

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
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

This **thinking-working separation** keeps the AI's context clean for strategic decisions while offloading compute-intensive ML tasks (embedding, NLI, reranking) to Lyra's local runtime.

**MCP Compatibility**: Lyra is protocol-compliant and works with any MCP client—[Cursor AI](https://cursor.sh/), [Claude Desktop](https://claude.ai/desktop), [Zed Editor](https://zed.dev/), or other MCP-enabled tools. The "thinking" side requires Claude/GPT-4-class reasoning capability.

**Embedded ML Components:**

| Component | Model | Purpose |
|-----------|-------|---------|
| Local LLM | Qwen2.5-3B (Ollama) | Fact/claim extraction, quality assessment |
| Embedding | bge-m3 | Semantic similarity for candidate ranking |
| Reranker | bge-reranker-v2-m3 | Cross-encoder reranking of search results |
| NLI | DeBERTa-v3 | Stance detection (supports/refutes/neutral) |

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
│  │                       │  │        │ │Rerank) │ │     │  │    │   │
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
4. **Materials Export**: `get_materials` returns claims, fragments, and evidence graph for report composition

### Key Modules

| Module | Location | Responsibility |
|--------|----------|----------------|
| **MCP Server** | `src/mcp/` | 11 tools for MCP client integration |
| **Search Providers** | `src/search/` | Multi-engine search, academic APIs |
| **Crawler** | `src/crawler/` | Browser automation, HTTP fetching, session management |
| **Filter** | `src/filter/` | LLM extraction, NLI analysis, ranking |
| **Research Pipeline** | `src/research/` | Orchestration, state management |
| **Storage** | `src/storage/` | SQLite database, migrations |
| **ML Server** | `src/ml_server/` | Embedding (bge-m3), reranking, NLI models |

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

### Trust Levels

Sources are classified by institutional authority:

| Level | Description | Examples |
|-------|-------------|----------|
| `PRIMARY` | Standards bodies, registries | iso.org, ietf.org |
| `GOVERNMENT` | Government agencies | .go.jp, .gov |
| `ACADEMIC` | Academic/research institutions | arxiv.org, pubmed.gov |
| `TRUSTED` | Established knowledge bases | wikipedia.org |
| `LOW` | Verified low-trust sources | User-promoted sources |
| `UNVERIFIED` | Not yet verified | Default for unknown domains |
| `BLOCKED` | Excluded sources | Demoted via contradiction detection |

### Security Architecture (8 Layers)

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| L1 | Network isolation | Ollama runs in internal-only container network |
| L2 | Input sanitization | Unicode normalization, dangerous pattern removal |
| L3 | Session tags | Random delimiters prevent prompt injection |
| L4 | Output validation | Detect leaked prompts, suspicious URLs |
| L5 | Response metadata | Trust levels attached to all MCP responses |
| L6 | Source verification | Automatic promotion/demotion based on evidence |
| L7 | Schema validation | MCP responses validated before return |
| L8 | Secure logging | No prompts written to logs |

---

## Installation

### Prerequisites

- **OS**: Windows 11 + WSL2 (Ubuntu 22.04 or 24.04)
- **Python**: 3.12+
- **Browser**: Google Chrome (for CDP remote debugging)
- **Container Runtime**: Podman (recommended) or Docker

**Reference Environment** (tested configuration; lower specs may work):

| Resource | Reference Spec | Notes |
|----------|----------------|-------|
| RAM | 64GB host, 32GB WSL2 | Lower limits not yet determined |
| GPU | NVIDIA RTX 4060 Laptop (8GB VRAM) | CPU fallback available |
| Task time | ~20 min (GPU), ~25 min (CPU) | Per 120-page research task |

The default `podman-compose.yml` expects GPU access via CDI. For CPU-only operation, remove `devices: nvidia.com/gpu=all` from the compose file and set `LYRA_ML__USE_GPU=false` in `.env`.

### Quick Start

```bash
# 1. Clone and setup Python environment
git clone https://github.com/k-shibuki/lyra.git
cd lyra
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-mcp.txt

# 2. Configure and start services
cp .env.example .env
./scripts/dev.sh up      # Start Ollama, ML Server, Tor containers
./scripts/chrome.sh start # Start Chrome with CDP

# 3. Configure MCP client (see below)
```

### Helper Scripts

| Script | Purpose |
|--------|---------|
| `./scripts/dev.sh up` | Start all containers (Ollama, ML Server, Tor) |
| `./scripts/dev.sh down` | Stop all containers |
| `./scripts/dev.sh shell` | Enter development shell with network access |
| `./scripts/dev.sh logs [service]` | View container logs |
| `./scripts/dev.sh clean` | Remove containers and images |
| `./scripts/chrome.sh start` | Start Chrome with CDP on port 9222 |
| `./scripts/chrome.sh stop` | Stop Chrome |
| `./scripts/test.sh` | Run test suite with appropriate markers |

The scripts auto-detect environment (WSL/Linux) and handle container networking.

### WSL2 Network Configuration

For WSL2 to communicate with Windows Chrome via CDP:

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

### MCP Tools (11 Tools)

Lyra exposes the following tools to MCP clients:

| Category | Tool | Description |
|----------|------|-------------|
| **Task Management** | `create_task` | Create a new research task |
| | `get_status` | Get unified task status, metrics, and budget |
| **Research** | `search` | Execute search→fetch→extract→evaluate pipeline |
| | `stop_task` | Finalize a task |
| **Materials** | `get_materials` | Retrieve claims, fragments, and evidence graph |
| **Calibration** | `calibrate` | Add samples, get statistics, evaluate performance |
| | `calibrate_rollback` | Rollback calibration parameters |
| **Auth Queue** | `get_auth_queue` | Get pending authentication requests |
| | `resolve_auth` | Report authentication completion |
| **Notification** | `notify_user` | Send user notification |
| | `wait_for_user` | Wait for user input |

### Example Research Workflow

```python
# 1. Create a research task
create_task(query="Liraglutide cardiovascular safety profile")
# Returns: {"task_id": "task_abc123", "budget": {"max_pages": 120}}

# 2. Execute search queries (designed by MCP client)
search(task_id="task_abc123", query="liraglutide FDA cardiovascular warning")
# Returns: {"claims_found": [...], "harvest_rate": 0.53, "satisfaction_score": 0.85}

search(task_id="task_abc123", query="liraglutide LEADER trial results")
# Returns: {"claims_found": [...], "harvest_rate": 0.61}

# 3. Execute refutation search
search(task_id="task_abc123", query="liraglutide cardiovascular risk", refute=True)
# Returns: {"claims_found": [...], "refutations_found": 2, "harvest_rate": 0.45}

# 4. Check progress
get_status(task_id="task_abc123")
# Returns: {"searches": [...], "budget": {"remaining_percent": 45}}

# 5. Retrieve materials for report composition
get_materials(task_id="task_abc123", include_graph=True)
# Returns: {"claims": [...], "fragments": [...], "evidence_graph": {...}}

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
| `config/engines.yaml` | Search engine definitions and priorities |
| `config/domains.yaml` | Domain trust levels and rate policies |
| `config/search_parsers.yaml` | HTML selectors for search result parsing |
| `config/academic_apis.yaml` | Academic API endpoints (Semantic Scholar, OpenAlex, etc.) |

### Key Settings

```yaml
# config/settings.yaml
task_limits:
  max_pages_per_task: 120        # Maximum pages to fetch per task
  max_time_minutes_gpu: 20       # Time budget (GPU mode)

search:
  min_independent_sources: 3     # Required for claim satisfaction
  novelty_threshold: 0.10        # Stop when novelty drops below 10%

crawler:
  engine_qps: 0.25               # Requests per second per engine
  domain_qps: 0.2                # Requests per second per domain
```

---

## Quality Control

### Testing

Lyra includes 3000+ tests across three layers:

```bash
# Run unit and integration tests
pytest tests/ -m 'not e2e' --tb=short -q

# Run specific test file
pytest tests/test_evidence_graph.py -v

# Run E2E tests (requires Chrome CDP and containers)
./scripts/chrome.sh start
pytest tests/ -m 'e2e'
```

### Test Markers

| Marker | Scope | Environment |
|--------|-------|-------------|
| `unit` | Pure functions, no I/O | Any |
| `integration` | Mocked dependencies | Local |
| `e2e` | Full system (Chrome, Ollama) | Local with containers |
| `external` | External services | Local with network |

### Code Quality

```bash
# Lint check
ruff check src/ tests/

# Type check
mypy src/
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
- **GPU Recommended**: Inference speed depends significantly on GPU availability
- **Chrome Dependency**: Browser-based operations require Chrome with CDP

---

## Roadmap

- [ ] Japanese Government API integration (e-Stat, e-Gov, EDINET)
- [ ] Patent database integration (USPTO, EPO, J-PlatPat)
- [ ] Automated parser repair for search engine changes
- [ ] Cross-platform support (Linux, macOS)

---

## Documentation

| Document | Description |
|----------|-------------|
| [REQUIREMENTS.md](docs/REQUIREMENTS.md) | Detailed specification |
| [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Implementation status and roadmap |
| [J2_ACADEMIC_API_INTEGRATION.md](docs/J2_ACADEMIC_API_INTEGRATION.md) | Academic API integration details |
| [TEST_LAYERS.md](docs/TEST_LAYERS.md) | Test execution guide |

---

## Contributing

Contributions are welcome. Please:

1. Read the [REQUIREMENTS.md](docs/REQUIREMENTS.md) for design context
2. Ensure tests pass before submitting pull requests
3. Follow existing code style (enforced by ruff)

```bash
# Before committing
pytest tests/ -m 'not e2e' --tb=short
ruff check src/ tests/
```

---

## License

This project is licensed under the [MIT License](LICENSE).

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
