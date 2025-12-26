#!/bin/bash
# Dev Shell Functions
#
# Functions for managing development shell.

# Function: start_dev_shell
# Description: Start development shell with multi-network support
#             Creates a container with access to both primary and internal networks
# Returns:
#   0: Success (container started and attached)
#   1: Failure (container creation or start failed)
start_dev_shell() {
    log_info "Entering development shell..."
    
    # Build dev image (base stage only, no GPU packages)
    podman build -t lyra-dev:latest -f docker/Dockerfile --target base .
    
    # Load environment from .env if exists, otherwise use defaults
    local env_opts=""
    if [ -f "${PROJECT_DIR}/.env" ]; then
        env_opts="--env-file ${PROJECT_DIR}/.env"
    else
        log_warn ".env not found, using default environment variables"
        # Fallback defaults for proxy server (internal services)
        env_opts="-e LYRA_TOR__SOCKS_HOST=tor -e LYRA_TOR__SOCKS_PORT=9050 -e LYRA_LLM__OLLAMA_HOST=http://ollama:11434"
    fi
    
    # Derive network names from project directory name (podman-compose prefix)
    local project_name
    project_name="$(basename "$PROJECT_DIR")"
    local net_primary="${project_name}_lyra-net"
    local net_internal="${project_name}_lyra-internal"
    
    # Cleanup function to ensure container is removed on exit/error
    cleanup_dev_container() {
        # shellcheck disable=SC2317
        podman rm -f lyra-dev 2>/dev/null || true
    }
    trap cleanup_dev_container EXIT
    
    # Remove existing container if exists
    # shellcheck disable=SC2317
    podman rm -f lyra-dev 2>/dev/null || true
    
    # Create container with primary network
    # Note: Podman doesn't support multiple --network flags in a single run command,
    # so we create the container first, connect to additional networks, then start it
    # shellcheck disable=SC2086
    podman create -it \
        -v "${PROJECT_DIR}/src:/app/src:rw" \
        -v "${PROJECT_DIR}/config:/app/config:ro" \
        -v "${PROJECT_DIR}/data:/app/data:rw" \
        -v "${PROJECT_DIR}/logs:/app/logs:rw" \
        -v "${PROJECT_DIR}/tests:/app/tests:rw" \
        --network "$net_primary" \
        $env_opts \
        --name lyra-dev \
        lyra-dev:latest \
        /bin/bash
    
    # Connect to internal network for inference services (Ollama/ML)
    podman network connect "$net_internal" lyra-dev
    
    # Start container interactively and attach
    podman start -ai lyra-dev
}

