#!/bin/bash
# Lyra Logs Utility Library
#
# Provides functions for viewing and searching log files.
# Used by mcp.sh and other scripts that need log access.
#
# Usage:
#   source "${SCRIPT_DIR}/lib/logs.sh"
#   show_lyra_logs              # Show recent logs (tail -100)
#   show_lyra_logs -f           # Follow logs
#   show_lyra_logs --grep "pattern"  # Search logs
#
# Note: This library is intentionally standalone (no common.sh dependency)
# to allow early loading before STDIO guards in mcp.sh.

# =============================================================================
# CONSTANTS
# =============================================================================

# Determine project directory (works when sourced from various locations)
_LOGS_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_LOGS_PROJECT_DIR="$(cd "${_LOGS_LIB_DIR}/../.." && pwd)"
LYRA_LOGS_DIR="${LYRA_LOGS_DIR:-${_LOGS_PROJECT_DIR}/logs}"

# =============================================================================
# FUNCTIONS
# =============================================================================

# Get the path to the latest log file
# Args: pattern (optional, default: "lyra_*.log")
# Returns: path to latest log file, or empty string if none found
# shellcheck disable=SC2120  # Default argument is intentional
get_latest_log_file() {
    local pattern="${1:-lyra_*.log}"
    # shellcheck disable=SC2012  # ls is fine for sorted timestamps
    ls -t "${LYRA_LOGS_DIR}"/"${pattern}" 2>/dev/null | head -1
}

# Show Lyra logs with various options
# Usage: show_lyra_logs [-f|--follow] [--grep "pattern"] [--lines N]
show_lyra_logs() {
    local follow=false
    local grep_pattern=""
    local lines=100
    
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -f|--follow)
                follow=true
                shift
                ;;
            --grep)
                grep_pattern="$2"
                shift 2
                ;;
            --lines|-n)
                lines="$2"
                shift 2
                ;;
            *)
                shift
                ;;
        esac
    done
    
    # Find latest log file
    local latest_log
    # shellcheck disable=SC2119  # Default argument is intentional
    latest_log=$(get_latest_log_file)
    
    if [[ -z "$latest_log" ]]; then
        echo "No log files found in ${LYRA_LOGS_DIR}/" >&2
        exit 1
    fi
    
    echo "=== Log file: ${latest_log} ===" >&2
    
    if [[ -n "$grep_pattern" ]]; then
        grep -i "$grep_pattern" "$latest_log" || echo "No matches found"
    elif [[ "$follow" == "true" ]]; then
        tail -f "$latest_log"
    else
        tail -"${lines}" "$latest_log"
    fi
    
    exit 0
}

