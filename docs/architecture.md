# Lyra Architecture

## Overview

Lyra is an open-source server implementing the Model Context Protocol (MCP)—a standard interface for connecting AI assistants to external tools—that enables AI assistants to conduct desktop research with structured provenance, providing accurate and auditable evidence. The software exposes research capabilities—web search, content extraction, natural language inference, and evidence graph construction—as structured tools that MCP-compatible AI clients can invoke directly.

The architecture separates strategic reasoning (performed by the AI assistant in the MCP client) from mechanical execution (evidence discovery, classification, and scoring). Lyra uses a hybrid architecture where the MCP server runs on the host (WSL2/Linux) while inference services run in network-isolated containers.

## System Architecture

See [figures/figure1-architecture.mmd](figures/figure1-architecture.mmd) for the Mermaid source.

```mermaid
flowchart TB
    subgraph Host["WSL2/Linux Host"]
        MCP["MCP Client<br/>(Claude, etc.)"]
        Server["MCP Server<br/>+ Evidence Graph"]
        Chrome["Chrome"]
    end
    subgraph Containers["Containers (Podman)"]
        subgraph lyra-internal["lyra-internal (isolated)"]
            Ollama["ollama<br/>qwen2.5:3b"]
            ML["ml<br/>BGE-M3, NLI"]
        end
        Proxy["proxy"]
        subgraph lyra-net["lyra-net"]
            Tor["tor"]
        end
    end
    Internet((Internet))
    Academic["Academic APIs<br/>(S2, OpenAlex)"]
    MCP <-->|stdio| Server
    Server --> Chrome
    Server --> Academic
    Chrome --> Internet
    Academic --> Internet
    Server <-->|HTTP| Proxy
    Proxy <--> Ollama
    Proxy <--> ML
    Proxy <--> Tor
    Tor <-->|SOCKS| Internet
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
| `ollama` | `ollama` | lyra-internal | Local LLM runtime (qwen2.5:3b). GPU-accelerated when available, network-isolated. |
| `ml` | `ml` | lyra-internal | Embedding (bge-m3) and NLI inference. GPU-accelerated when available, network-isolated. |
| `tor` | `tor` | lyra-net | SOCKS proxy for anonymous web access |

### GPU Auto-Detection

Lyra automatically detects GPU availability at startup:
- **GPU detected** (`nvidia-smi` available): GPU overlay files are applied, enabling CUDA acceleration
- **No GPU**: Runs in CPU mode with a warning logged; fully functional but slower (20-100x)

The compose scripts (`scripts/lib/compose.sh`) handle this automatically via overlay files (`podman-compose.gpu.yml` / `docker-compose.gpu.yml`).

### Networks

| Network | Type | Purpose |
|---------|------|---------|
| `lyra-net` | Bridge | External-capable. Used by proxy and tor. |
| `lyra-internal` | Internal | Isolated (no internet). Ollama and ML only communicate with proxy. Prevents data exfiltration. |

## Data Flow

```mermaid
flowchart TB
    Query["User Query"]
    MCP["MCP Client<br/>(Cursor)"]
    Server["MCP Server<br/>(Host)"]
    Queue["Search Queue"]
    
    Chrome["Chrome<br/>(Browser)"]
    Tor["Tor<br/>Proxy"]
    Academic["Academic<br/>APIs"]
    Internet((Internet))
    
    Extract["Content Extraction<br/>(trafilatura, etc.)"]
    Ollama["Ollama<br/>(LLM)"]
    ML["ML<br/>Embed/NLI"]
    Graph["Evidence Graph<br/>(SQLite)"]
    
    Query --> MCP --> Server --> Queue
    Server --> Chrome
    Server --> Tor
    Queue --> Academic
    
    Chrome --> Internet
    Tor --> Internet
    Academic --> Internet
    
    Internet --> Extract
    Extract --> Ollama
    Extract --> ML
    Ollama --> Graph
    ML --> Graph
```

## Security Model

See [ADR-0006: Eight Layer Security Model](adr/0006-eight-layer-security-model.md) for details.

Key points:
- **Network Isolation**: Ollama/ML containers have no internet access
- **GPU Isolation**: When GPU is available, shared via CDI/runtime with no direct host access
- **Data Isolation**: Evidence graph is local-only
- **Prompt Injection Defense**: Isolated inference prevents exfiltration

## Directory Structure

```
lyra/
├── containers/           # Container definitions
│   ├── Dockerfile        # proxy container (custom)
│   ├── Dockerfile.ml     # ml container (custom)
│   ├── podman-compose.yml        # Base compose (CPU mode)
│   ├── podman-compose.gpu.yml    # GPU overlay (auto-applied when GPU detected)
│   ├── docker-compose.yml        # Base compose (CPU mode)
│   └── docker-compose.gpu.yml    # GPU overlay (auto-applied when GPU detected)
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

