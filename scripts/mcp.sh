#!/bin/bash
# Lancet MCP Server Launcher
# Launches MCP server in container via stdio
#
# Usage: Called by Cursor via .cursor/mcp.json
#   ./scripts/mcp.sh
#
# Prerequisites:
#   - Podman containers running: ./scripts/dev.sh up
#   - Chrome with CDP: ./scripts/chrome.sh start (before using search tools)

set -e

# Ensure containers are running
if ! podman ps --format "{{.Names}}" 2>/dev/null | grep -q "^lancet$"; then
    echo "Error: lancet container not running. Start with: ./scripts/dev.sh up" >&2
    exit 1
fi

# Start MCP server with stdin/stdout passthrough
# -i: Keep stdin open (required for MCP stdio transport)
exec podman exec -i lancet python -m src.mcp.server


