#!/bin/bash
# Lancet MCP Server Launcher
# Launches MCP server in container via stdio
#
# Usage: Called by Cursor via .cursor/mcp.json
#   ./scripts/mcp.sh
#
# Prerequisites:
#   - Chrome with CDP: ./scripts/chrome.sh start (before using search tools)
#   - Containers are auto-started if not running

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Auto-start containers if not running
if ! podman ps --format "{{.Names}}" 2>/dev/null | grep -q "^lancet$"; then
    echo "Container not running. Starting..." >&2
    "$SCRIPT_DIR/dev.sh" up >&2
    # Wait for container to be ready
    for i in {1..30}; do
        if podman ps --format "{{.Names}}" 2>/dev/null | grep -q "^lancet$"; then
            echo "Container ready." >&2
            break
        fi
        sleep 1
    done
    
    # Verify container started successfully
    if ! podman ps --format "{{.Names}}" 2>/dev/null | grep -q "^lancet$"; then
        echo "Error: Container failed to start within 30s" >&2
        echo "Check logs: ./scripts/dev.sh logs" >&2
        exit 1
    fi
fi

# Start MCP server with stdin/stdout passthrough
# -i: Keep stdin open (required for MCP stdio transport)
exec podman exec -i lancet python -m src.mcp.server


