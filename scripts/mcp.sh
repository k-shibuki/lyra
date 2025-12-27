#!/bin/bash
# Lyra MCP Server Launcher (WSL Hybrid Mode)
#
# Launches MCP server on WSL host, with LLM/ML via container proxy.
# Called by Cursor via .cursor/mcp.json
#
# Usage:
#   ./scripts/mcp.sh          # Start MCP server (default)
#   ./scripts/mcp.sh logs     # Show recent logs (tail -100)
#   ./scripts/mcp.sh logs -f  # Follow logs
#   ./scripts/mcp.sh logs --grep "pattern"  # Search logs
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
# EARLY INITIALIZATION (for logs subcommand - before STDIO guard)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source logs library (standalone, no common.sh dependency)
# shellcheck source=lib/logs.sh
source "${SCRIPT_DIR}/lib/logs.sh"

# Handle 'logs' subcommand before STDIO guard (logs go to stdout)
if [[ "${1:-}" == "logs" ]]; then
    shift
    show_lyra_logs "$@"
fi

# =============================================================================
# STDIO PROTOCOL GUARD (Cursor MCP)
# =============================================================================
#
# Cursor expects the MCP server to speak JSON-RPC over stdout.
# Any human-readable logs printed to stdout before the server starts will break
# the protocol (e.g., "Unexpected token 'I', \"[INFO] ...\" is not valid JSON").
# We therefore:
#   - route script logs to stderr
#   - keep stdout reserved for the Python MCP server
#
# NOTE: Python logging is already configured to use stderr (src/utils/logging.py).
exec 3>&1
exec 1>&2
export LYRA_LOG_TO_STDERR="true"

# =============================================================================
# COMMON INITIALIZATION
# =============================================================================

# Source common functions and load .env
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# Enable debug mode if DEBUG=1
enable_debug_mode

# Set up error handler
trap 'cleanup_on_error ${LINENO}' ERR

# =============================================================================
# CONTAINER GUARD
# =============================================================================

require_host_execution "mcp.sh" "runs MCP server on WSL host and connects to Cursor"

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
# Dynamic Worker Pool: Each worker gets its own Chrome instance
export LYRA_BROWSER__CHROME_HOST="${LYRA_BROWSER__CHROME_HOST:-localhost}"
export LYRA_BROWSER__CHROME_BASE_PORT="${LYRA_BROWSER__CHROME_BASE_PORT:-9222}"
export LYRA_BROWSER__CHROME_PROFILE_PREFIX="${LYRA_BROWSER__CHROME_PROFILE_PREFIX:-Lyra-}"

# 6. Chrome is started lazily when needed (via _auto_start_chrome in browser providers)
# No pre-startup required - workers call chrome.sh start-worker N on demand

# 7. Start MCP server on host
cd "${PROJECT_DIR}"

# Restore stdout for JSON-RPC protocol before launching the server.
exec 1>&3 3>&-
exec uv run python -m src.mcp.server
