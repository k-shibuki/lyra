#!/bin/bash
# Lyra shell - CLI flag parsing and global output mode flags

# Global output mode flags (initialized before parsing)
# JSON output mode (set via --json flag)
export LYRA_OUTPUT_JSON="${LYRA_OUTPUT_JSON:-false}"

# Quiet mode (set via --quiet or -q flag)
export LYRA_QUIET="${LYRA_QUIET:-false}"

# Function: parse_global_flags
# Description: Parse global flags (--json, --quiet) from arguments
# Arguments:
#   $@: Command line arguments
# Returns:
#   Remaining arguments after removing global flags (via GLOBAL_ARGS array)
# Side effects:
#   Sets LYRA_OUTPUT_JSON, LYRA_QUIET
parse_global_flags() {
    GLOBAL_ARGS=()
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
                GLOBAL_ARGS+=("$1")
                shift
                ;;
        esac
    done
}


