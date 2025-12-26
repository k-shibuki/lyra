#!/bin/bash
# Lyra MCP Server Launcher (WSL Hybrid Mode)
#
# Launches MCP server on WSL host, with LLM/ML via container proxy.
# Called by Cursor via .cursor/mcp.json
#
# Usage: ./scripts/mcp.sh
#
# Architecture:
#   WSL Host:     MCP Server (this script) + Chrome CDP
#   Containers:   Proxy -> Ollama/ML (internal network)
#
# Prerequisites (auto-managed):
#   - Chrome with CDP: auto-started when needed via chrome.sh
#   - Containers: auto-started if not running
#   - venv: auto-created if not exists

set -euo pipefail

# =============================================================================
# INITIALIZATION
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common functions and load .env
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# Enable debug mode if DEBUG=1
enable_debug_mode

# Set up error handler
trap 'cleanup_on_error ${LINENO}' ERR

# =============================================================================
# MAIN
# =============================================================================

# 1. Setup venv if needed (uses common.sh function)
setup_venv "mcp"

# Install Playwright browsers if needed (first run only)
# Note: -d doesn't work with globs, so we use ls to check
if ! ls -d "${VENV_DIR}/lib/python"*"/site-packages/playwright" >/dev/null 2>&1 || \
   [[ ! -d "$HOME/.cache/ms-playwright" ]]; then
    log_info "Installing Playwright browsers..." >&2
    uv run playwright install chromium --with-deps 2>/dev/null || {
        log_warn "Playwright browser install failed. May need manual installation." >&2
    }
fi

# 2. Activate venv
# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

# 3. Auto-start containers if not running (for proxy/Ollama/ML)
if ! check_container_running; then
    log_info "Container not running. Starting..." >&2
    "${SCRIPT_DIR}/dev.sh" up >&2
    
    # Wait for container to be ready
    if wait_for_container "$CONTAINER_NAME" "$CONTAINER_TIMEOUT"; then
        log_info "Container ready." >&2
    else
        log_error "Container failed to start within ${CONTAINER_TIMEOUT}s" >&2
        log_info "Check logs: make dev-logs" >&2
        exit 1
    fi
fi

# 4. Wait for proxy server to be available (uses common.sh function)
PROXY_URL="${LYRA_GENERAL__PROXY_URL:-http://localhost:8080}"
wait_for_endpoint "${PROXY_URL}/health" 30 "Proxy server ready" || true  # Continue even if proxy not ready

# 5. Set environment for host execution
export PYTHONPATH="${PROJECT_DIR}:${PYTHONPATH:-}"

# Data directory (shared with container via volume mount)
export LYRA_DATA_DIR="${LYRA_DATA_DIR:-${PROJECT_DIR}/data}"

# Proxy URL for hybrid mode
export LYRA_GENERAL__PROXY_URL="${PROXY_URL}"

# Chrome settings (localhost for WSL direct connection)
export LYRA_BROWSER__CHROME_HOST="${LYRA_BROWSER__CHROME_HOST:-localhost}"
export LYRA_BROWSER__CHROME_PORT="${LYRA_BROWSER__CHROME_PORT:-9222}"

# 6. Start MCP server on host (enables chrome.sh auto-start)
cd "${PROJECT_DIR}"
exec uv run python -m src.mcp.server
