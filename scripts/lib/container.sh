#!/bin/bash
# Lyra shell - container utilities

# Function: get_container_runtime_cmd
# Description: Get container runtime command (prefer podman, fallback docker)
# Returns:
#   0: Success, outputs command name ("podman" or "docker")
#   1: No supported runtime found
get_container_runtime_cmd() {
    if command -v podman &> /dev/null; then
        echo "podman"
        return 0
    fi
    if command -v docker &> /dev/null; then
        echo "docker"
        return 0
    fi
    return 1
}

# Function: check_container_running
# Description: Check if the lyra container is running
# Arguments:
#   $1: Container name (optional, defaults to CONTAINER_NAME)
# Returns:
#   0: Container is running
#   1: Container is not running
check_container_running() {
    local name="${1:-$CONTAINER_NAME}"
    local runtime
    runtime="$(get_container_runtime_cmd 2>/dev/null || echo "")"
    if [ -z "$runtime" ]; then
        return 1
    fi
    "$runtime" ps --format "{{.Names}}" 2>/dev/null | grep -q "^${name}$"
}

# Function: wait_for_container
# Description: Wait for container to be ready with timeout
# Arguments:
#   $1: Container name (optional, defaults to CONTAINER_NAME)
#   $2: Timeout in seconds (optional, defaults to CONTAINER_TIMEOUT)
# Returns:
#   0: Container is ready
#   1: Timeout waiting for container
wait_for_container() {
    local name="${1:-$CONTAINER_NAME}"
    local timeout="${2:-$CONTAINER_TIMEOUT}"

    for ((i=1; i<=timeout; i++)); do
        if check_container_running "$name"; then
            return 0
        fi
        sleep 1
    done
    return 1
}


