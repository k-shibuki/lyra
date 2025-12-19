# Lyra

> **L**ocal **Y**ielding **R**esearch **A**ide — An MCP Toolkit with Embedded ML for AI-Collaborative Desktop Research

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-3000%2B-success.svg)](tests/)

---

## Summary

Lyra is an open-source MCP (Model Context Protocol) toolkit that collaborates with [Cursor AI](https://cursor.sh/) for desktop research. It implements **thinking-working separation**: Cursor AI handles strategic decisions (query design, report composition), while Lyra handles mechanical execution (search, extraction, metrics calculation). This separation minimizes context pollution in the AI's reasoning while offloading compute-intensive ML tasks to dedicated local components.

**Embedded ML Components:**

| Component | Model | Purpose |
|-----------|-------|---------|
| Local LLM | Qwen2.5-3B (Ollama) | Fact/claim extraction, quality assessment |
| Embedding | bge-m3 | Semantic similarity for candidate ranking |
| Reranker | bge-reranker-v2-m3 | Cross-encoder reranking of search results |
| NLI | DeBERTa-v3 | Stance detection (supports/refutes/neutral) |

**Core Design Principles:**

1. **Complete Local Processing**: All data remains on the user's machine. Search queries and collected information are never transmitted to external servers.
2. **Thinking-Working Separation**: Cursor AI decides *what* to search; Lyra executes *how* to search. Lyra never proposes queries or makes strategic decisions.
3. **Evidence Graph Construction**: Every claim is linked to source fragments with provenance tracking, enabling verification and reproducibility.

---

## Statement of Need

### The Problem

Commercial research tools (Perplexity, ChatGPT with browsing, etc.) present significant challenges for privacy-sensitive research:

| Challenge | Commercial Tools | Lyra's Approach |
|-----------|-----------------|-----------------|
| **Privacy** | Queries and data transmitted to external servers | All processing occurs locally |
| **Transparency** | Proprietary algorithms | Fully open-source, auditable code |
| **Cost** | API fees, subscription costs | Zero operational expense |
| **Reproducibility** | Non-deterministic, changing models | Consistent local environment |
| **Customization** | Limited domain adaptation | Configurable via YAML policies |

### Target Use Cases

- **Healthcare & Research Institutions**: Sensitive investigations (drug safety, patient data) that cannot be exposed to third parties
- **Legal & Compliance Teams**: Research requiring strict confidentiality
- **Independent Researchers & Journalists**: Cost-effective alternative to commercial tools
- **Security-Conscious Organizations**: Auditable, deployable within controlled environments

### Differentiation from Existing Tools

Unlike browser automation tools (Selenium, Playwright scripts) that require custom coding for each task, Lyra provides:

1. **Unified Research Pipeline**: Search, fetch, extract, and evaluate in a single workflow
2. **Evidence Graph**: Structured claim-fragment-source relationships, not just raw text
3. **AI-Assisted Filtering**: Local LLM (Ollama) extracts facts and assesses source quality
4. **Multi-Engine Search**: Aggregates results from DuckDuckGo, Mojeek, Brave, academic APIs, and more
5. **Human-in-the-Loop**: Graceful handling of CAPTCHAs and authentication via intervention queues

---

## System Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Windows 11 Host                             │
│  ┌──────────────┐                                                   │
│  │  Cursor AI   │  ◄── User designs queries, composes reports       │
│  │  (Thinking)  │                                                   │
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

1. **Task Creation**: User provides a research question via Cursor AI → `create_task` MCP tool
2. **Query Execution**: Cursor AI designs search queries → `search` tool executes pipeline:
   - Search engine query (Playwright browser automation)
   - URL fetching with rate limiting and block detection
   - Content extraction (trafilatura)
   - LLM-based fact/claim extraction (Ollama)
   - NLI stance detection (supports/refutes/neutral)
   - Evidence graph construction
3. **Iterative Refinement**: Cursor AI reviews metrics via `get_status`, designs follow-up queries
4. **Materials Export**: `get_materials` returns claims, fragments, and evidence graph for report composition

### Key Modules

| Module | Location | Responsibility |
|--------|----------|----------------|
| **MCP Server** | `src/mcp/` | 11 tools for Cursor AI integration |
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
- **GPU**: NVIDIA RTX 4060 or equivalent (8GB VRAM recommended; CPU fallback available)

### Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/k-shibuki/lyra.git
cd lyra

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-mcp.txt
playwright install chromium

# 3. Configure environment
cp .env.example .env
# Edit .env as needed (ports, paths, model selection)

# 4. Start containers (Ollama, ML Server, Tor proxy)
./scripts/dev.sh up

# 5. Start Chrome with remote debugging
./scripts/chrome.sh start
```

### WSL2 Network Configuration

For WSL2 to communicate with Windows Chrome via CDP:

1. Create or edit `%USERPROFILE%\.wslconfig`:
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```
2. Restart WSL: `wsl.exe --shutdown`

### Cursor AI Integration

Add to Cursor's MCP configuration (`.cursor/mcp.json`):

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

Lyra exposes the following tools to Cursor AI:

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

# 2. Execute search queries (designed by Cursor AI)
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
