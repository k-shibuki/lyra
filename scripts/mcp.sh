#!/bin/bash
# Lancet MCP Server Launcher (WSL Hybrid Mode)
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
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Source common functions and load .env
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# Enable debug mode if DEBUG=1
enable_debug_mode

# Set up error handler
trap 'cleanup_on_error ${LINENO}' ERR

# =============================================================================
# VENV MANAGEMENT
# =============================================================================

VENV_DIR="${PROJECT_ROOT}/.venv"
REQUIREMENTS_MCP="${PROJECT_ROOT}/requirements-mcp.txt"

setup_venv() {
    if [[ -f "${VENV_DIR}/bin/activate" ]]; then
        return 0
    fi
    
    echo "Creating Python virtual environment..." >&2
    python3 -m venv "${VENV_DIR}"
    
    # Activate and install dependencies
    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"
    
    echo "Installing MCP server dependencies..." >&2
    pip install --quiet --upgrade pip
    pip install --quiet -r "${REQUIREMENTS_MCP}"
    
    # Install Playwright browsers
    echo "Installing Playwright browsers..." >&2
    playwright install chromium --with-deps 2>/dev/null || {
        echo "Warning: Playwright browser install failed. May need manual installation." >&2
    }
    
    echo "venv setup complete." >&2
}

# =============================================================================
# CONTAINER MANAGEMENT
# =============================================================================

wait_for_proxy() {
    local max_attempts=30
    local attempt=0
    local proxy_url="${LANCET_GENERAL__PROXY_URL:-http://localhost:8080}"
    
    echo "Waiting for proxy server at ${proxy_url}..." >&2
    
    while [[ $attempt -lt $max_attempts ]]; do
        if curl -s "${proxy_url}/health" >/dev/null 2>&1; then
            echo "Proxy server ready." >&2
            return 0
        fi
        
        attempt=$((attempt + 1))
        sleep 1
    done
    
    echo "Warning: Proxy server not responding. LLM/ML calls may fail." >&2
    return 1
}

# =============================================================================
# MAIN
# =============================================================================

# 1. Setup venv if needed
setup_venv

# 2. Activate venv
# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

# 3. Auto-start containers if not running (for proxy/Ollama/ML)
if ! check_container_running; then
    echo "Container not running. Starting..." >&2
    "${SCRIPT_DIR}/dev.sh" up >&2
    
    # Wait for container to be ready
    if wait_for_container "$CONTAINER_NAME" "$CONTAINER_TIMEOUT"; then
        echo "Container ready." >&2
    else
        log_error "Container failed to start within ${CONTAINER_TIMEOUT}s" >&2
        echo "Check logs: ./scripts/dev.sh logs" >&2
        exit 1
    fi
fi

# 4. Wait for proxy server to be available
wait_for_proxy || true  # Continue even if proxy not ready

# 5. Set environment for host execution
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

# Data directory (shared with container via volume mount)
export LANCET_DATA_DIR="${LANCET_DATA_DIR:-${PROJECT_ROOT}/data}"

# Proxy URL for hybrid mode
export LANCET_GENERAL__PROXY_URL="${LANCET_GENERAL__PROXY_URL:-http://localhost:8080}"

# Chrome settings (localhost for WSL direct connection)
export LANCET_BROWSER__CHROME_HOST="${LANCET_BROWSER__CHROME_HOST:-localhost}"
export LANCET_BROWSER__CHROME_PORT="${LANCET_BROWSER__CHROME_PORT:-9222}"

# 6. Start MCP server on host (enables chrome.sh auto-start)
cd "${PROJECT_ROOT}"
exec python -m src.mcp.server
