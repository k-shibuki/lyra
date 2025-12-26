#!/bin/bash
# Lyra shell - Podman/Compose utilities

# Function: get_compose_cmd
# Description: Get podman-compose command path
# Returns:
#   0: Success, outputs command name
#   1: Command not found
get_compose_cmd() {
    if command -v podman-compose &> /dev/null; then
        echo "podman-compose"
    else
        log_error "podman-compose not found"
        log_error "Install with: sudo apt install podman-compose"
        return 1
    fi
}

# Function: require_podman
# Description: Check if podman command exists
# Arguments:
#   $1: If "exit", exits on failure; otherwise returns 1
# Returns:
#   0: podman is available
#   Exits or returns 1: podman not found
require_podman() {
    if ! command -v podman &> /dev/null; then
        if [[ "${1:-}" == "exit" ]]; then
            output_error "$EXIT_DEPENDENCY" "podman not found" "hint=sudo apt install podman"
        else
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                log_error "podman not found"
                log_error "Install with: sudo apt install podman"
            fi
            return 1
        fi
    fi
    return 0
}

# Function: require_podman_compose
# Description: Check if podman and podman-compose commands exist
# Arguments:
#   $1: If "exit", exits on failure; otherwise returns 1
# Returns:
#   0: Both commands are available
#   Exits or returns 1: One or both commands not found
require_podman_compose() {
    local mode="${1:-}"
    require_podman "$mode" || return 1
    if ! command -v podman-compose &> /dev/null; then
        if [[ "$mode" == "exit" ]]; then
            output_error "$EXIT_DEPENDENCY" "podman-compose not found" "hint=sudo apt install podman-compose"
        else
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                log_error "podman-compose not found"
                log_error "Install with: sudo apt install podman-compose"
            fi
            return 1
        fi
    fi
    return 0
}


