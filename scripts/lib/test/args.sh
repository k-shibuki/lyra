#!/bin/bash
# Test Argument Parsing Functions
#
# Functions for parsing test.sh command-line arguments.

# Function: parse_common_flags
# Description: Parse test.sh-specific flags (--venv, --container, --name)
# Arguments:
#   $@: Command line arguments
# Side effects:
#   Sets RUNTIME_MODE, CONTAINER_NAME_SELECTED, PYTEST_ARGS array
parse_common_flags() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --venv)
                RUNTIME_MODE="venv"
                shift
                ;;
            --container)
                RUNTIME_MODE="container"
                shift
                ;;
            --auto)
                # shellcheck disable=SC2034
                RUNTIME_MODE="auto"
                shift
                ;;
            --name)
                CONTAINER_NAME_SELECTED="${2:-}"
                if [[ -z "$CONTAINER_NAME_SELECTED" ]]; then
                    log_error "--name requires a container name"
                    exit 1
                fi
                shift 2
                ;;
            --)
                shift
                break
                ;;
            *)
                break
                ;;
        esac
    done

    # The remainder are command args
    # - run: pytest args (optional; default handled in cmd_run)
    # - check/kill: run_id (optional; default handled in cmd_check/cmd_kill via state file)
    # shellcheck disable=SC2034
    PYTEST_ARGS=("$@")
}

