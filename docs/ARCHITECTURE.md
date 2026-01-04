# Lyra Architecture

## Overview

Lyra is an AI-powered academic research assistant that runs as an MCP (Model Context Protocol) server. It uses a hybrid architecture where the MCP server runs on the host (WSL2/Linux) while inference services run in containers.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ WSL2/Linux Host                                                 │
│                                                                 │
│  ┌─────────────┐   stdio    ┌────────────────────────────────┐ │
│  │ Cursor/MCP  │◄──────────►│ MCP Server (scripts/mcp.sh)    │ │
│  │   Client    │            │   - Python + uv venv           │ │
│  └─────────────┘            │   - Evidence Graph (SQLite)    │ │
│                             │   - Search orchestration       │ │
│                             └───────────┬───────┬────────────┘ │
│                                         │       │               │
│                              HTTP       │       │ Playwright    │
│                              :8080      │       ▼               │
│                                         │  ┌─────────┐          │
│                                         │  │ Chrome  │─────────────────►
│                                         │  └─────────┘          │  Internet
│                                         ▼                       │
└─────────────────────────────────────────────────────────────────┘
                                          │
┌─────────────────────────────────────────│───────────────────────┐
│ Containers (Podman/Docker)              │                       │
│                                         ▼                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                       proxy                               │   │
│  │        Bridge: Host MCP ↔ Internal Services               │   │
│  └────────┬─────────────────────────────────────────┬───────┘   │
│           │                                         │            │
│           │ lyra-internal                           │ lyra-net   │
│           ▼                                         ▼            │
│  ┌────────────────────────────────────────┐  ┌────────────────┐ │
│  │    lyra-internal (isolated, no inet)   │  │    lyra-net    │ │
│  │  ┌────────────┐     ┌────────────┐     │  │   (external)   │ │
│  │  │   ollama   │     │     ml     │     │  │ ┌────────────┐ │ │
│  │  │  LLM(GPU)  │     │ Embed/NLI  │     │  │ │    tor     │───────────►
│  │  │ qwen2.5:3b │     │ bge-m3,NLI │     │  │ │SOCKS Proxy │ │ │ Internet
│  │  └────────────┘     └────────────┘     │  │ │ Anonymous  │ │ │
│  │       GPU                GPU           │  │ └────────────┘ │ │
│  └────────────────────────────────────────┘  └────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### Host Components

| Component | Description |
|-----------|-------------|
| **MCP Server** | Main application server (Python). Handles MCP protocol, search orchestration, evidence graph management. Runs directly on host for optimal I/O. |
| **Evidence Graph** | SQLite database storing claims, evidence, and relationships. Located at `data/lyra.db`. |
| **Chrome** | Browser automation for web scraping. Runs on host (Windows Chrome for WSL2). |

### Container Services

| Service | Container | Network | Description |
|---------|-----------|---------|-------------|
| `proxy` | `proxy` | lyra-net, lyra-internal | HTTP bridge between host MCP server and internal services |
| `ollama` | `ollama` | lyra-internal | Local LLM runtime (qwen2.5:3b). GPU-accelerated, network-isolated. |
| `ml` | `ml` | lyra-internal | Embedding (bge-m3) and NLI inference. GPU-accelerated, network-isolated. |
| `tor` | `tor` | lyra-net | SOCKS proxy for anonymous web access |

### Networks

| Network | Type | Purpose |
|---------|------|---------|
| `lyra-net` | Bridge | External-capable. Used by proxy and tor. |
| `lyra-internal` | Internal | Isolated (no internet). Ollama and ML only communicate with proxy. Prevents data exfiltration. |

## Data Flow

```
User Query
    │
    ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  MCP Client     │────►│  MCP Server     │────►│  Search Queue   │
│  (Cursor)       │     │  (Host)         │     │                 │
└─────────────────┘     └────────┬────────┘     └────────┬────────┘
                                 │                       │
                    ┌────────────┴────────────┐          │
                    ▼                         ▼          ▼
             ┌──────────┐              ┌──────────┐  ┌──────────┐
             │  Chrome  │              │   Tor    │  │ Academic │
             │ (Browser)│              │  Proxy   │  │   APIs   │
             └────┬─────┘              └────┬─────┘  └────┬─────┘
                  │                         │             │
                  ▼                         ▼             ▼
             ┌────────────────────────────────────────────────┐
             │                   Internet                      │
             └────────────────────────────────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Content Extraction    │
                    │   (trafilatura, etc.)   │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
             ┌──────────┐              ┌──────────┐
             │  Ollama  │              │    ML    │
             │  (LLM)   │              │ Embed/NLI│
             └──────────┘              └──────────┘
                    │                         │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │    Evidence Graph       │
                    │    (SQLite)             │
                    └─────────────────────────┘
```

## Security Model

See [ADR-0006: Eight Layer Security Model](adr/0006-eight-layer-security-model.md) for details.

Key points:
- **Network Isolation**: Ollama/ML containers have no internet access
- **GPU Isolation**: Shared via CDI/runtime, no direct host access
- **Data Isolation**: Evidence graph is local-only
- **Prompt Injection Defense**: Isolated inference prevents exfiltration

## Directory Structure

```
lyra/
├── containers/           # Container definitions
│   ├── Dockerfile        # proxy container (custom)
│   ├── Dockerfile.ml     # ml container (custom)
│   ├── podman-compose.yml
│   └── docker-compose.yml
│   # Note: ollama uses ollama/ollama:latest, tor uses dperson/torproxy:latest
│   # (official images, no custom Dockerfile needed)
├── scripts/              # Shell scripts for operations
├── src/                  # Python source code
├── config/               # Configuration files
├── data/                 # SQLite database, cache
├── models/               # ML models (ollama, huggingface)
└── logs/                 # Application logs
```

## Related ADRs

- [ADR-0001: Local-First Zero-OPEX](adr/0001-local-first-zero-opex.md)
- [ADR-0003: MCP over CLI/REST](adr/0003-mcp-over-cli-rest.md)
- [ADR-0005: Evidence Graph Structure](adr/0005-evidence-graph-structure.md)
- [ADR-0006: Eight Layer Security Model](adr/0006-eight-layer-security-model.md)

