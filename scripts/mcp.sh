#!/bin/bash
# Lyra MCP Server Launcher (WSL Hybrid Mode)
#
# Launches MCP server on WSL host, with LLM/ML via container proxy.
# Called by Cursor via .cursor/mcp.json
#
# Usage:
#   ./scripts/mcp.sh          # Start MCP server (default)
#   ./scripts/mcp.sh start    # Start MCP server (explicit)
#   ./scripts/mcp.sh stop     # Stop MCP server (for code reload)
#   ./scripts/mcp.sh restart  # Restart MCP server
#   ./scripts/mcp.sh status   # Show MCP server status
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
# EARLY INITIALIZATION (for subcommands before STDIO guard)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# -----------------------------------------------------------------------------
# Global flags (standalone parsing; no common.sh dependency at this stage)
# -----------------------------------------------------------------------------
export LYRA_OUTPUT_JSON="${LYRA_OUTPUT_JSON:-false}"
export LYRA_QUIET="${LYRA_QUIET:-false}"

_parse_global_flags_standalone() {
    local args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --json)
                export LYRA_OUTPUT_JSON="true"
                shift
                ;;
            --quiet|-q)
                export LYRA_QUIET="true"
                shift
                ;;
            *)
                args+=("$1")
                shift
                ;;
        esac
    done
    # Return remaining args via GLOBAL_ARGS (bash global)
    GLOBAL_ARGS=("${args[@]}")
}

_parse_global_flags_standalone "$@"
set -- "${GLOBAL_ARGS[@]}"

# Source logs library (standalone, no common.sh dependency)
# shellcheck source=lib/logs.sh
source "${SCRIPT_DIR}/lib/logs.sh"

# =============================================================================
# MCP PROCESS MANAGEMENT (before STDIO guard)
# =============================================================================

# Find MCP server process(es)
find_mcp_processes() {
    pgrep -f "python -m src.mcp.server" 2>/dev/null || true
}

# Stop MCP server
mcp_stop() {
    local pids
    pids=$(find_mcp_processes)
    if [[ -z "$pids" ]]; then
        if [[ "${LYRA_OUTPUT_JSON}" == "true" ]]; then
            cat <<EOF
{"status":"ok","exit_code":0,"running":false,"message":"No MCP server processes found"}
EOF
        else
            if [[ "${LYRA_QUIET}" != "true" ]]; then
                echo "No MCP server processes found"
            fi
        fi
        return 0
    fi
    
    if [[ "${LYRA_OUTPUT_JSON}" != "true" ]] && [[ "${LYRA_QUIET}" != "true" ]]; then
        echo "Stopping MCP server processes: $pids"
    fi
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    
    # Wait for processes to terminate
    local timeout=5
    local count=0
    while [[ $count -lt $timeout ]]; do
        pids=$(find_mcp_processes)
        if [[ -z "$pids" ]]; then
            if [[ "${LYRA_OUTPUT_JSON}" == "true" ]]; then
                cat <<EOF
{"status":"ok","exit_code":0,"running":false,"message":"MCP server stopped"}
EOF
            else
                if [[ "${LYRA_QUIET}" != "true" ]]; then
                    echo "MCP server stopped"
                fi
            fi
            return 0
        fi
        sleep 1
        ((count++))
    done
    
    # Force kill if still running
    pids=$(find_mcp_processes)
    if [[ -n "$pids" ]]; then
        if [[ "${LYRA_OUTPUT_JSON}" != "true" ]] && [[ "${LYRA_QUIET}" != "true" ]]; then
            echo "Force killing MCP server processes: $pids"
        fi
        # shellcheck disable=SC2086
        kill -9 $pids 2>/dev/null || true
    fi
    if [[ "${LYRA_OUTPUT_JSON}" == "true" ]]; then
        cat <<EOF
{"status":"ok","exit_code":0,"running":false,"message":"MCP server stopped"}
EOF
    else
        if [[ "${LYRA_QUIET}" != "true" ]]; then
            echo "MCP server stopped"
        fi
    fi
}

# Show MCP server status
mcp_status() {
    local pids
    pids=$(find_mcp_processes)
    if [[ -z "$pids" ]]; then
        if [[ "${LYRA_OUTPUT_JSON}" == "true" ]]; then
            cat <<EOF
{"status":"ok","exit_code":0,"running":false}
EOF
        else
            if [[ "${LYRA_QUIET}" != "true" ]]; then
                echo "MCP server: not running"
            fi
        fi
        return 1
    fi
    
    if [[ "${LYRA_OUTPUT_JSON}" == "true" ]]; then
        # Best-effort JSON; keep it simple (PID list as string array)
        local pids_json
        pids_json=$(echo "$pids" | tr ' ' '\n' | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))' 2>/dev/null || echo "[]")
        cat <<EOF
{"status":"ok","exit_code":0,"running":true,"pids":${pids_json}}
EOF
    else
        if [[ "${LYRA_QUIET}" != "true" ]]; then
            echo "MCP server: running"
            echo "PIDs: $pids"
            # Show process details
            # shellcheck disable=SC2086
            ps -p $pids -o pid,ppid,etime,cmd --no-headers 2>/dev/null || true
        fi
    fi
}

# Handle subcommands before STDIO guard
case "${1:-}" in
    logs)
    shift
    if [[ "${LYRA_OUTPUT_JSON}" == "true" ]]; then
        # Keep stdout machine-readable; send log content to stderr.
        # shellcheck disable=SC2119  # Default argument is intentional
        latest_log=$(get_latest_log_file)
        if [[ -z "${latest_log:-}" ]]; then
            cat <<EOF
{"status":"error","exit_code":1,"message":"No log files found"}
EOF
            exit 1
        fi
        if [[ "${LYRA_QUIET}" != "true" ]]; then
            echo "=== Log file: ${latest_log} ===" >&2
        fi
        tail -100 "$latest_log" >&2 || true
        cat <<EOF
{"status":"ok","exit_code":0,"log_file":"${latest_log}","note":"log content was written to stderr"}
EOF
    else
        show_lyra_logs "$@"
    fi
        ;;
    stop)
        mcp_stop
        exit 0
        ;;
    status)
        mcp_status
        exit $?
        ;;
    restart)
        mcp_stop
        if [[ "${LYRA_OUTPUT_JSON}" == "true" ]]; then
            cat <<EOF
{"status":"ok","exit_code":0,"message":"Stopped. Reconnect MCP in Cursor to complete restart.","hint":"Command Palette -> MCP: Reconnect Server -> lyra"}
EOF
        else
            if [[ "${LYRA_QUIET}" != "true" ]]; then
                echo ""
                echo "To complete restart, reconnect MCP in Cursor:"
                echo "  1. Open Command Palette (Ctrl+Shift+P)"
                echo "  2. Run 'MCP: Reconnect Server'"
                echo "  3. Select 'lyra'"
            fi
        fi
        exit 0
        ;;
    start|"")
        # Continue to main startup logic
        ;;
    *)
        # Unknown command - continue to main startup logic
        # (might be flags or handled by common.sh)
        ;;
esac

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

# Note: Playwright browsers (chromium, firefox, webkit) are NOT needed.
# Lyra uses Chrome CDP connection only (ADR-0006: real profile consistency).
# The Playwright library is used solely for its CDP client, not its browsers.

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
        log_info "Check logs: make logs" >&2
        exit 1
    fi
fi

# 4. Wait for proxy server to be available (uses common.sh function)
PROXY_URL="$(lyra_get_setting "general.proxy_url" 2>/dev/null || echo "http://localhost:8080")"
wait_for_endpoint "${PROXY_URL}/health" 30 "Proxy server ready" || true  # Continue even if proxy not ready

# 5. Set environment for host execution
export PYTHONPATH="${PROJECT_DIR}:${PYTHONPATH:-}"

# Data directory (shared with container via volume mount)
export LYRA_DATA_DIR="${LYRA_DATA_DIR:-${PROJECT_DIR}/data}"

# Proxy URL/Chrome settings are read from settings.yaml/local.yaml by the Python runtime.
# Do not export them from scripts (keeps .env minimal and avoids drift).

# 6. Chrome is started lazily when needed (via _auto_start_chrome in browser providers)
# No pre-startup required - workers call chrome.sh start-worker N on demand

# 7. Start MCP server on host
cd "${PROJECT_DIR}"

# Restore stdout for JSON-RPC protocol before launching the server.
exec 1>&3 3>&-
# IMPORTANT: Do not use `uv run` here. `uv` may print informational logs to stdout,
# which breaks the JSON-RPC stdio protocol expected by MCP clients.
exec python -m src.mcp.server
