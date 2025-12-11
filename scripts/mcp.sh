#!/bin/bash
# Lancet MCP Server Launcher
#
# Launches MCP server in container via stdio.
# Called by Cursor via .cursor/mcp.json
#
# Usage: ./scripts/mcp.sh
#
# Prerequisites:
#   - Chrome with CDP: ./scripts/chrome.sh start (before using search tools)
#   - Containers are auto-started if not running

set -e

# =============================================================================
# INITIALIZATION
# =============================================================================

# Source common functions and load .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# =============================================================================
# MAIN
# =============================================================================

# Auto-start containers if not running
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

# Start MCP server with stdin/stdout passthrough
# -i: Keep stdin open (required for MCP stdio transport)
exec podman exec -i "$CONTAINER_NAME" python -m src.mcp.server
