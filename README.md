# Lyra

[![CI](https://github.com/k-shibuki/lyra/actions/workflows/ci.yml/badge.svg)](https://github.com/k-shibuki/lyra/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)

**MCP server that enables AI assistants to conduct research with traceable, high-quality evidence.**

Lyra is an open-source MCP (Model Context Protocol) server that provides AI assistants with structured, verifiable evidence for desktop research. By building an Evidence Graph with full source traceability, Lyra solves the fundamental problem of AI-assisted research: knowing where information comes from and how reliable it is.

## Statement of Need

When AI assistants conduct web research, they face critical evidence quality problems:

| Problem | Impact |
|---------|--------|
| **Untraceable sources** | AI returns information without clear provenance |
| **Contradictory evidence** | Conflicting claims are mixed without structure |
| **No confidence metrics** | Impossible to assess reliability objectively |

**Lyra solves these by providing:**

- **Evidence Graph**: Every claim links to source fragments and URLs with NLI stance detection
- **Bayesian Confidence**: Automatic reliability scoring from accumulated evidence
- **Incremental Exploration**: SQL and vector search for granular evidence access
- **Local-First**: All ML processing on your machine (zero data exfiltration, zero operational cost)

For detailed architecture, see [docs/architecture.md](docs/architecture.md).

## Key Concepts

### Key Principle

Lyra is a *navigation tool*, not a disposable answer generator ([ADR-0001](docs/adr/0001-local-first-zero-opex.md)). It discovers and organizes sources; detailed analysis is the researcher's role. The evidence graph persists and accumulates value across sessions—corrections improve model quality over time.

### Three-Layer Collaboration

Lyra implements a clear separation of responsibilities ([ADR-0002](docs/adr/0002-three-layer-collaboration-model.md)):

| Layer | Actor | Role |
|-------|-------|------|
| **Thinking** | Human | Primary source reading, final judgment, domain expertise |
| **Reasoning** | AI Client | Research planning, query design, synthesis |
| **Working** | Lyra | Source discovery, extraction, NLI, persistence |

### Evidence Graph

Claims connect to evidence through a structured graph ([ADR-0005](docs/adr/0005-evidence-graph-structure.md)):

```
Claim ← Fragment (SUPPORTS/REFUTES/NEUTRAL) ← Page ← URL
```

Each task defines a central hypothesis to verify ([ADR-0017](docs/adr/0017-task-hypothesis-first.md)). Claims are extracted using this hypothesis as context, and NLI edges carry calibrated confidence. Claims accumulate Bayesian confidence from cross-source evidence.

## Features

- 🔍 **Multi-source Search**: Academic APIs (Semantic Scholar, OpenAlex) + web engines ([ADR-0015](docs/adr/0015-unified-search-sources.md))
- 🧠 **Evidence Extraction**: LLM claim extraction with NLI stance detection ([ADR-0004](docs/adr/0004-local-llm-extraction-only.md))
- 📊 **Evidence Graph**: SQLite-backed with Bayesian confidence ([ADR-0005](docs/adr/0005-evidence-graph-structure.md))
- 📚 **Citation Chasing**: Expand evidence by selectively queuing unfetched references via `v_reference_candidates` view ([ADR-0015](docs/adr/0015-unified-search-sources.md))
- 🔒 **Network Isolation**: ML containers have no internet access ([ADR-0006](docs/adr/0006-eight-layer-security-model.md))
- 🔄 **Human-in-the-Loop**: CAPTCHA handling and feedback-driven improvement ([ADR-0007](docs/adr/0007-human-in-the-loop-auth.md))

## Prerequisites

- **Linux or Windows** (WSL2)
- **Python 3.14+** (managed via `uv`)
- **Podman** or **Docker**
- **Browser for automation (CDP)**:
  - **WSL2**: Windows **Google Chrome** (required; fixed path)
  - **Native Linux**: **Google Chrome** (recommended) or **Chromium** (supported)
- **NVIDIA GPU** (recommended, optional - CPU fallback available)

## Quick Start

```bash
git clone https://github.com/k-shibuki/lyra.git && cd lyra
make doctor   # Check environment
make setup    # Install Python deps (uv will auto-manage Python 3.14+)
make up       # Start (auto-build first time)
```

Note: `.env` is created automatically from `.env.example` on the first run of `make doctor` / `make setup` / `make up`.
Edit `.env` if you need to customize settings.

### Output Mode (make commands)

- **Machine-readable**: `LYRA_OUTPUT_JSON=true make <target>` (stdout stays JSON)
- **Quiet**: `LYRA_QUIET=true make <target>` (suppress non-essential output)
- **Details (human mode)**:
  - `LYRA_DEV_STATUS_DETAIL=full make status`
  - `LYRA_CHROME_STATUS_DETAIL=full make chrome`
  - `LYRA_TEST_SHOW_TAIL_ON_SUCCESS=true make test-check RUN_ID=...`
  - `LYRA_TEST_JSON_DETAIL=full|minimal make test`

## Platform Setup

Tested on: Windows 11 + WSL2-Ubuntu 24.04 LTS, Ubuntu Desktop 24.04 LTS

### Common (WSL2 / Linux)

```bash
# Core dependencies (make is required for build commands)
sudo apt install -y curl git make podman podman-compose libcurl4-openssl-dev shellcheck

# Rust toolchain (required for building sudachipy)
# sudachipy: Japanese NLP tokenizer, used in tests and text processing
# Note: apt's rustc is too old; use rustup for latest version
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source $HOME/.cargo/env

# GPU support (optional but recommended for performance) - requires NVIDIA repository
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

Note: `source $HOME/.cargo/env` is only for enabling `rustc/cargo` in your current shell (it is not related to Lyra's `.env`).

### Windows (WSL2)

Browser automation uses **Windows Google Chrome** via CDP.
Install Chrome on Windows and keep the default path:
`C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe`

### Linux

```bash
# Browser automation
# Option A: Google Chrome (recommended; official repo)
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update && sudo apt install -y google-chrome-stable
#
# Option B: Chromium (supported; easier but less stable)
# sudo snap install chromium

# Desktop notifications (optional)
sudo apt install -y libnotify-bin

# Window activation for CAPTCHA handling (optional)
sudo apt install -y xdotool
```

### Notes

**Python 3.14**: Automatically managed by `uv` - no system installation required.

**GPU Auto-Detection**: Lyra automatically detects GPU availability at startup. If `nvidia-smi` is not found, it runs in CPU mode (slower inference, but fully functional).

**CPU-only Mode**: To explicitly disable GPU and run in CPU mode (even when GPU is available), set `LYRA_DISABLE_GPU=1` in your `.env` file. This is useful for testing or when you want to avoid nvidia-container-toolkit setup.

## Configuration

### Academic API Settings (Recommended)

For better rate limits on academic searches, add these to `.env`:

```bash
# Semantic Scholar: Get free API key at https://www.semanticscholar.org/product/api
# Provides dedicated 1 req/s (vs shared global pool)
LYRA_ACADEMIC_APIS__APIS__SEMANTIC_SCHOLAR__API_KEY=your_key

# OpenAlex: Your email for "polite pool" (10 req/s vs 1 req/s)
LYRA_ACADEMIC_APIS__APIS__OPENALEX__EMAIL=your_email@example.com
```

### Local Configuration Overrides

For extensive local customization beyond environment variables, use `local.yaml`:

```bash
cp config/local.yaml.example config/local.yaml
```

Edit `config/local.yaml` to override settings from any config file (`settings.yaml`, `academic_apis.yaml`, etc.). See the example file for available options.

Priority (lowest to highest):
1. Base YAML files (`config/*.yaml`)
2. `config/local.yaml`
3. Environment variables (`LYRA_*` prefix)

### MCP Client Configuration

```bash
# Cursor
mkdir -p .cursor && cp config/mcp.json.example .cursor/mcp.json
```

**Important**: Edit `.cursor/mcp.json` and update the path to match your installation:

```json
{
  "mcpServers": {
    "lyra": {
      "command": "/full/path/to/lyra/scripts/mcp.sh",
      "args": []
    }
  }
}
```

Replace `/full/path/to/lyra` with your actual Lyra installation path (e.g., `/home/username/Projects/lyra`).

For other clients, copy `config/mcp.json.example` to your client's config location and adjust the path accordingly.

## Usage Example

See [docs/examples/](docs/examples/) for commands, sample research, and programmatic usage.

**Quick setup** (Cursor):
```bash
cp docs/examples/commands/*.md .cursor/commands/
```

Then invoke `/lyra-search` in Cursor chat. For Claude Desktop, add as Skills via Settings → Skills.

## MCP Tools

| Category | Tools | Reference |
|----------|-------|-----------|
| Task Management | `create_task`, `get_status`, `stop_task` | [ADR-0010](docs/adr/0010-async-search-queue.md), [ADR-0017](docs/adr/0017-task-hypothesis-first.md) |
| Target Queue | `queue_targets`, `queue_reference_candidates` | [ADR-0010](docs/adr/0010-async-search-queue.md), [ADR-0015](docs/adr/0015-unified-search-sources.md) |
| Evidence Exploration | `query_sql`, `vector_search`, `query_view`, `list_views` | [ADR-0016](docs/adr/0016-ranking-simplification.md) |
| Authentication | `get_auth_queue`, `resolve_auth` | [ADR-0007](docs/adr/0007-human-in-the-loop-auth.md) |
| Feedback | `feedback` | [ADR-0012](docs/adr/0012-feedback-tool-design.md) |
| Calibration | `calibration_metrics`, `calibration_rollback` | [ADR-0011](docs/adr/0011-lora-fine-tuning.md) |

## Commands

```bash
make up          # Start services
make down        # Stop services
make doctor      # Check environment
make test        # Run tests (async, returns immediately)
make test-all    # Run ALL tests (async; overrides default -m 'not e2e')
make test-check  # Poll for test results
make test-cov    # Run tests with coverage (async, venv-only)
make test-e2e    # Run E2E tests only
make test-e2e-internal  # E2E against local services (proxy/ml/ollama)
make test-e2e-external  # E2E against internet services (SERP/FETCH/Academic APIs)
make quality     # Run all code quality checks
make help        # Show all commands
```

## Documentation

- [Architecture Overview](docs/architecture.md) - System design and data flow
- [Examples](docs/examples/) - Commands and sample research
- [MCP Tools Reference](docs/mcp_reference.md) - Tool descriptions and schemas
- [ADR Index](docs/adr/index.md) - Architecture decision records
- [Contributing Guide](.github/CONTRIBUTING.md)
- [Code of Conduct](.github/CODE_OF_CONDUCT.md) - Contributor Covenant 3.0

## Limitations

- **Platform**: Linux (WSL2 or Native Ubuntu Desktop 24.04 LTS); NVIDIA GPU recommended for performance
- **Scope**: Navigation tool; primary source analysis is researcher's role
- **Content**: Academic papers via abstracts; web content limited to initial portions
- **NLI**: General-purpose model; domain adaptation via LoRA ([ADR-0011](docs/adr/0011-lora-fine-tuning.md))
- **CPU Mode**: Functional but significantly slower inference (20-100x compared to GPU)

## Citation

If you use Lyra in your research, please cite using [CITATION.cff](CITATION.cff).

## License

MIT License - see [LICENSE](LICENSE) for details.

Copyright (c) 2026 Katsuya Shibuki
