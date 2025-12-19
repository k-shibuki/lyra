# Lyra

> **L**ocal **Y**ielding **R**esearch **A**ide — A Privacy-Preserving Agent for Autonomous Research with Evidence Verification

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-3000%2B-success.svg)](tests/)

## Overview

Lyra is a **local-first AI agent** that collaborates with [Cursor AI](https://cursor.sh/) to perform comprehensive desktop research. It automates the search→fetch→extract→evaluate pipeline and builds an **evidence graph** for reliable information gathering.

**Key Principle**: All processing happens locally. Your search queries and collected information are never sent to external servers.

---

## Why Lyra?

| Challenge | Commercial Tools | Lyra's Solution |
|-----------|-----------------|-----------------|
| **Privacy** | Queries & data sent to servers | Entirely local processing |
| **Transparency** | Black-box algorithms | Fully open-source, auditable |
| **Cost** | API fees, subscriptions | **Zero OpEx** (no additional cost) |
| **Customization** | Limited domain adaptation | Flexible YAML configuration |

### Target Users

- **Healthcare & Research Institutions**: Handle sensitive investigations without data leakage
- **Legal & Compliance Teams**: Maintain confidentiality of research content
- **Independent Researchers & Journalists**: Avoid commercial tool costs
- **Security-Conscious Organizations**: Deploy auditable open-source solutions

---

## Features

### Core Capabilities

- 🔒 **Complete Local Processing**: No external data transmission
- 💰 **Zero OpEx**: No commercial API dependencies
- 📊 **Evidence Graph**: Manage claim-fragment-source relationships in a graph structure
- 🛡️ **Multi-Layer Security**: Prompt injection protection (L1-L8)
- 🤖 **MCP Integration**: Seamless collaboration with Cursor AI
- 🌐 **Multi-Engine Search**: DuckDuckGo, Mojeek, Brave, Ecosia, Startpage, and more
- 📚 **Academic API Integration**: Semantic Scholar, OpenAlex, Crossref, arXiv, Unpaywall

### Architecture

```
Cursor AI (Thinking)                 Lyra (Working)
     │                                   │
     │  MCP Protocol                     │
     ├─────────────────────────────────►│
     │                                   │
     │  create_task / search / ...      │
     │                                   ├─► Browser Search (Playwright)
     │                                   ├─► Content Extraction (trafilatura)
     │                                   ├─► LLM Analysis (Ollama)
     │                                   └─► Evidence Graph Construction
```

**Responsibility Separation** (per §2.1):
- **Cursor AI**: Query design, strategic decisions, report composition
- **Lyra**: Pipeline execution, metrics calculation, data retrieval

---

## Quick Start

### Prerequisites

- **OS**: Windows 11 + WSL2 (Ubuntu 22.04 or 24.04)
- **Python**: 3.12+
- **Browser**: Google Chrome (for CDP remote debugging)
- **Container**: Podman (recommended) or Docker
- **GPU**: NVIDIA RTX 4060 or equivalent (recommended, 8GB VRAM)

### Installation

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
# Edit .env as needed

# 4. Start containers (Ollama, ML Server, Proxy)
./scripts/dev.sh up

# 5. Start Chrome with remote debugging
./scripts/chrome.sh start
```

### WSL2 Network Configuration

For WSL2 to communicate with Windows Chrome, enable mirrored networking:

1. Create or edit `%USERPROFILE%\.wslconfig`:
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```
2. Restart WSL: `wsl.exe --shutdown`

---

## Usage

Lyra operates through MCP (Model Context Protocol) tools called from Cursor AI.

### MCP Tools (11 tools)

| Category | Tool | Description |
|----------|------|-------------|
| **Task Management** | `create_task` | Create a new research task |
| | `get_status` | Get unified task and exploration status |
| **Research Execution** | `search` | Execute search pipeline |
| | `stop_task` | Finalize a task |
| **Materials** | `get_materials` | Retrieve claims, fragments, evidence graph |
| **Calibration** | `calibrate` | Calibration operations (5 actions) |
| | `calibrate_rollback` | Rollback calibration parameters |
| **Auth Queue** | `get_auth_queue` | Get pending authentication list |
| | `resolve_auth` | Report authentication completion |
| **Notification** | `notify_user` | Send notification to user |
| | `wait_for_user` | Wait for user input |

### Example Workflow

```python
# 1. Create a research task
create_task(query="Liraglutide safety information survey")

# 2. Execute search queries (designed by Cursor AI)
search(task_id="...", query="liraglutide FDA safety alert")
search(task_id="...", query="liraglutide PMDA adverse events", refute=True)

# 3. Check progress
get_status(task_id="...")

# 4. Retrieve materials for report
get_materials(task_id="...", include_graph=True)

# 5. Finalize task
stop_task(task_id="...", reason="completed")
```

---

## Configuration

### Key Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Environment variables (ports, paths) |
| `config/settings.yaml` | Core settings (timeouts, budgets) |
| `config/engines.yaml` | Search engine configuration |
| `config/domains.yaml` | Domain trust levels and policies |
| `config/search_parsers.yaml` | Search result parser selectors |
| `config/academic_apis.yaml` | Academic API settings |

### Chrome Profile

Lyra uses a dedicated Chrome profile for research to maintain session isolation:

```bash
# Default profile location (configurable in .env)
~/.lyra/chrome-profile/
```

---

## Security

Lyra implements **8 layers of defense** against prompt injection attacks:

| Layer | Purpose |
|-------|---------|
| **L1** | Network isolation (Ollama in internal-only network) |
| **L2** | Input sanitization (dangerous patterns, Unicode normalization) |
| **L3** | System/user prompt separation (random session tags) |
| **L4** | Output validation (URL/IP detection, prompt fragment detection) |
| **L5** | MCP response metadata (trust levels, verification status) |
| **L6** | Source verification flow (auto-promotion/demotion) |
| **L7** | MCP response sanitization (schema validation) |
| **L8** | Log security policy (no prompt logging) |

### Trust Levels

| Level | Description | Examples |
|-------|-------------|----------|
| `PRIMARY` | Standards bodies, registries | iso.org, ietf.org |
| `GOVERNMENT` | Government agencies | go.jp, .gov |
| `ACADEMIC` | Academic institutions | arxiv.org, pubmed |
| `TRUSTED` | Reliable knowledge bases | wikipedia.org |
| `LOW` | Verified low-trust | Promoted via verification |
| `UNVERIFIED` | Not yet verified | Default for unknown domains |
| `BLOCKED` | Excluded | Demoted via contradiction detection |

---

## Testing

```bash
# Activate virtual environment
source .venv/bin/activate

# Run unit and integration tests
pytest tests/ -m 'not e2e' --tb=short -q

# Run specific test file
pytest tests/test_evidence_graph.py -v

# Run E2E tests (requires Chrome CDP)
./scripts/chrome.sh start
python tests/scripts/verify_duckduckgo_search.py
```

**Test Coverage**: 3000+ tests (unit, integration, E2E)

---

## Project Structure

```
lyra/
├── src/
│   ├── mcp/           # MCP server and handlers
│   ├── search/        # Search providers and parsers
│   ├── crawler/       # Web crawling and fetching
│   ├── filter/        # LLM extraction, NLI, ranking
│   ├── research/      # Research pipeline orchestration
│   ├── storage/       # SQLite database layer
│   └── utils/         # Configuration, logging, utilities
├── config/            # YAML configuration files
├── scripts/           # Shell scripts (dev, chrome, mcp)
├── tests/             # Test suites
├── docs/              # Documentation
└── migrations/        # Database migrations
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [REQUIREMENTS.md](docs/REQUIREMENTS.md) | Detailed specification (Japanese) |
| [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Implementation status and roadmap |
| [J2_ACADEMIC_API_INTEGRATION.md](docs/J2_ACADEMIC_API_INTEGRATION.md) | Academic API integration details |
| [TEST_LAYERS.md](docs/TEST_LAYERS.md) | Test execution guide |

---

## Limitations

- **Platform Dependency**: Requires Windows 11 + WSL2 environment
- **HTML Selector Maintenance**: Search engine HTML changes may require selector updates
- **GPU Recommended**: Inference speed significantly depends on GPU availability
- **Chrome Dependency**: Requires Chrome for browser-based operations

---

## Roadmap

- [ ] Japanese Government API integration (e-Stat, e-Gov, EDINET)
- [ ] Patent database integration (USPTO, EPO, J-PlatPat)
- [ ] Automated parser repair
- [ ] Cross-platform support

---

## Contributing

Contributions are welcome! Please read our documentation and ensure tests pass before submitting pull requests.

```bash
# Run tests before committing
pytest tests/ -m 'not e2e' --tb=short

# Check code style
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
- [Semantic Scholar](https://www.semanticscholar.org/) — Academic paper API
