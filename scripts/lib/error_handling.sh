#!/bin/bash
# Lyra shell - debug and error handling utilities

# Function: enable_debug_mode
# Description: Enable debug mode with detailed tracing if DEBUG=1 is set
# Environment variables:
#   DEBUG: Set to "1" to enable debug mode
enable_debug_mode() {
    if [ "${DEBUG:-}" = "1" ]; then
        set -x
        export PS4='+ [${BASH_SOURCE[0]}:${LINENO}] ${FUNCNAME[0]:+${FUNCNAME[0]}(): }'
    fi
}

# Function: cleanup_on_error
# Description: Error handler that logs error information and cleans up
# Arguments:
#   $1: Line number where error occurred (optional)
# Note: This should be set up with trap in scripts that source this file
#       Usage: trap 'cleanup_on_error ${LINENO}' ERR
cleanup_on_error() {
    local exit_code=$?
    local line_num="${1:-unknown}"
    if [ $exit_code -ne 0 ]; then
        # In JSON mode, suppress human-readable error messages for expected exit codes
        # (These are already communicated via JSON output)
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]] || [[ "$exit_code" -eq 1 ]]; then
            log_error "Script failed at line ${line_num} with exit code ${exit_code}"
        fi
        if [ "${DEBUG:-}" = "1" ]; then
            log_error "Stack trace:"
            # Temporarily disable trace to avoid recursion
            local trace_enabled=false
            if [ "${-//[^x]/}" = "x" ]; then
                trace_enabled=true
                set +x
            fi
            local frame=0
            while caller $frame 2>/dev/null; do
                ((frame++))
            done
            if [ "$trace_enabled" = "true" ]; then
                set -x
            fi
        fi
    fi
    exit $exit_code
}


