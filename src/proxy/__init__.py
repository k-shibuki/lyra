"""
Lancet Proxy Server.

Lightweight reverse proxy for Ollama and ML Server access.
Runs inside the lyra container, providing access to internal network services.

This enables the hybrid architecture where:
- MCP server runs on WSL host (for Chrome auto-start)
- LLM/ML inference runs in containers on internal network (for security)
- Proxy bridges the gap via HTTP
"""
