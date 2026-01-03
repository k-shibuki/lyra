#!/bin/bash
# Lyra shell - host execution guard
#
# Provides functions to ensure scripts run on host, not inside containers.

# Function: require_host_execution
# Description: Exit/return if running inside a container
# Arguments:
#   $1: Script/command name (for error message)
#   $2: Reason why host execution is required
#   $3: Mode - "exit" (default) or "return" (for use inside functions)
# Returns:
#   0: Running on host (safe to continue)
#   Exits with EXIT_CONFIG or returns 1 if inside container
# Example:
#   require_host_execution "dev.sh" "manages Podman containers from the host"
#   require_host_execution "doctor check" "checks host-side dependencies" "return"
require_host_execution() {
    local script_name="${1:-script}"
    local reason="${2:-must run on host}"
    local mode="${3:-exit}"
    
    if [[ "${IN_CONTAINER:-false}" != "true" ]]; then
        return 0
    fi
    
    # Inside container - report error
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        local json_msg
        json_msg="${script_name} must be run on host, not inside container"
        # Use output_error if available (exits), otherwise manual JSON
        if command -v output_error > /dev/null 2>&1; then
            output_error "$EXIT_CONFIG" "$json_msg" "container=${CURRENT_CONTAINER_NAME:-unknown}"
        else
            echo "{\"status\": \"error\", \"exit_code\": ${EXIT_CONFIG:-3}, \"message\": \"${json_msg}\", \"container\": \"${CURRENT_CONTAINER_NAME:-unknown}\"}"
            if [[ "$mode" == "exit" ]]; then
                exit "${EXIT_CONFIG:-3}"
            fi
            return 1
        fi
    else
        echo "ERROR: ${script_name} must be run on host, not inside container."
        echo ""
        echo "${script_name} ${reason}."
        echo "Run from WSL terminal, not from 'make shell' or 'podman exec'."
    fi
    
    if [[ "$mode" == "exit" ]]; then
        exit "${EXIT_CONFIG:-3}"
    fi
    return 1
}

# Function: require_host_execution_unless
# Description: Exit/return if running inside a container, unless action matches skip list
# Arguments:
#   $1: Script/command name (for error message)
#   $2: Reason why host execution is required
#   $3: Current action
#   $4+: Actions to skip (e.g., "help" "--help" "-h")
# Returns:
#   0: Running on host or action is in skip list
#   Exits with EXIT_CONFIG if inside container and action not in skip list
# Example:
#   require_host_execution_unless "chrome.sh" "manages Windows Chrome via CDP" "$ACTION" "help" "--help" "-h"
require_host_execution_unless() {
    local script_name="$1"
    local reason="$2"
    local action="$3"
    shift 3
    
    # Check if action is in skip list
    for skip_action in "$@"; do
        if [[ "$action" == "$skip_action" ]]; then
            return 0
        fi
    done
    
    require_host_execution "$script_name" "$reason" "exit"
}

