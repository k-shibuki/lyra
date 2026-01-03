#!/bin/bash
# Lyra shell - Compose utilities (Podman/Docker)

# Function: get_compose_cmd
# Description: Get compose command with file path (podman-compose or docker compose)
# Returns:
#   0: Success, outputs full command with -f flag
#   1: No supported runtime found
get_compose_cmd() {
    local compose_dir="${PROJECT_DIR}/containers"
    local project_name="lyra"
    
    # Allow forcing runtime via env var (for testing)
    # LYRA_COMPOSE_RUNTIME=docker or LYRA_COMPOSE_RUNTIME=podman
    local force_runtime="${LYRA_COMPOSE_RUNTIME:-}"
    
    # Podman (if not forcing docker)
    if [[ "$force_runtime" != "docker" ]] && command -v podman-compose &> /dev/null; then
        echo "podman-compose -p ${project_name} -f ${compose_dir}/podman-compose.yml"
        return 0
    fi
    
    # Docker (if not forcing podman)
    if [[ "$force_runtime" != "podman" ]] && command -v docker &> /dev/null; then
        # Docker Compose V2 (docker compose)
        if docker compose version &> /dev/null; then
            echo "docker compose -p ${project_name} -f ${compose_dir}/docker-compose.yml"
            return 0
        fi
        # Docker Compose V1 (docker-compose)
        if command -v docker-compose &> /dev/null; then
            echo "docker-compose -p ${project_name} -f ${compose_dir}/docker-compose.yml"
            return 0
        fi
    fi
    
    log_error "No container runtime found (podman-compose or docker)"
    log_error "Install with: sudo apt install podman podman-compose"
    log_error "Or: sudo apt install docker.io docker-compose-plugin"
    return 1
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

# Function: require_compose
# Description: Check if a supported compose runtime exists (podman-compose or docker compose)
# Arguments:
#   $1: If "exit", exits on failure; otherwise returns 1
# Returns:
#   0: A supported runtime is available
#   Exits or returns 1: No supported runtime found
require_compose() {
    local mode="${1:-}"
    
    # Check if get_compose_cmd succeeds (silently)
    if get_compose_cmd &> /dev/null; then
        return 0
    fi
    
    if [[ "$mode" == "exit" ]]; then
        output_error "$EXIT_DEPENDENCY" "No container runtime found" \
            "hint=sudo apt install podman podman-compose"
    else
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            log_error "No container runtime found"
            log_error "Install with: sudo apt install podman podman-compose"
            log_error "Or: sudo apt install docker.io docker-compose-plugin"
        fi
    fi
    return 1
}

# Function: require_podman_compose (DEPRECATED - use require_compose)
# Description: Alias for backward compatibility
# Arguments:
#   $1: If "exit", exits on failure; otherwise returns 1
# Returns:
#   0: A supported runtime is available
#   Exits or returns 1: No supported runtime found
require_podman_compose() {
    require_compose "$@"
}

