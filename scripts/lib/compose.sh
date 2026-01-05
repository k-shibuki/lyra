#!/bin/bash
# Lyra shell - Compose utilities (Podman/Docker)

# =============================================================================
# GPU Detection
# =============================================================================

# Track if GPU warning has been shown (to avoid duplicate warnings)
_GPU_WARNING_SHOWN="${_GPU_WARNING_SHOWN:-false}"

# Function: detect_gpu
# Description: Detect if NVIDIA GPU is available for container use
#              Can be explicitly disabled via LYRA_DISABLE_GPU=1
# Returns:
#   0: GPU is available and not explicitly disabled
#   1: GPU not available or disabled
detect_gpu() {
    # Allow explicit opt-out for CPU-only mode
    if [[ "${LYRA_DISABLE_GPU:-}" == "1" ]]; then
        return 1
    fi
    # Check if nvidia-smi command exists and works
    if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
        return 0
    fi
    return 1
}

# Function: detect_podman_cdi_ready
# Description: Detect if Podman GPU CDI is configured (required for nvidia.com/gpu=all)
# Returns:
#   0: CDI appears ready
#   1: Not ready
detect_podman_cdi_ready() {
    command -v nvidia-ctk &> /dev/null && [[ -f /etc/cdi/nvidia.yaml ]]
}

# Function: require_podman_cdi_or_fail
# Description: Fail fast with actionable message when GPU is present but Podman CDI is missing
# Returns:
#   Exits with EXIT_DEPENDENCY
require_podman_cdi_or_fail() {
    if detect_podman_cdi_ready; then
        return 0
    fi
    output_error "$EXIT_DEPENDENCY" "GPU detected but Podman CDI is not configured (nvidia.com/gpu=all is unresolvable)" \
        "hint=curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list && sudo apt update && sudo apt install -y nvidia-container-toolkit && sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
}

# Function: _log_gpu_warning
# Description: Log GPU warning once (internal helper)
_log_gpu_warning() {
    if [[ "$_GPU_WARNING_SHOWN" != "true" ]]; then
        if [[ "${LYRA_DISABLE_GPU:-}" == "1" ]]; then
            log_info "GPU disabled (LYRA_DISABLE_GPU=1). Running in CPU mode."
        else
            log_warn "GPU not detected. Running in CPU mode (inference will be significantly slower)."
            log_warn "For GPU support, install nvidia-container-toolkit and run: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
        fi
        _GPU_WARNING_SHOWN=true
        export _GPU_WARNING_SHOWN
    fi
}

# =============================================================================
# Compose Command
# =============================================================================

# Function: get_compose_cmd
# Description: Get compose command with file path (podman-compose or docker compose)
#              Automatically includes GPU overlay if nvidia-smi is detected
# Returns:
#   0: Success, outputs full command with -f flag(s)
#   1: No supported runtime found
get_compose_cmd() {
    local compose_dir="${PROJECT_DIR}/containers"
    local project_name="lyra"
    
    # Allow forcing runtime via env var (for testing)
    # LYRA_COMPOSE_RUNTIME=docker or LYRA_COMPOSE_RUNTIME=podman
    local force_runtime="${LYRA_COMPOSE_RUNTIME:-}"
    
    # Podman (if not forcing docker)
    if [[ "$force_runtime" != "docker" ]] && command -v podman-compose &> /dev/null; then
        # Detect GPU availability
        local gpu_available=false
        if detect_gpu; then
            # Fail-fast: if GPU exists, Podman CDI must be configured before applying GPU overlay
            require_podman_cdi_or_fail
            gpu_available=true
        else
            _log_gpu_warning
        fi

        local cmd="podman-compose -p ${project_name} -f ${compose_dir}/podman-compose.yml"
        if [[ "$gpu_available" == "true" ]]; then
            cmd="$cmd -f ${compose_dir}/podman-compose.gpu.yml"
        fi
        echo "$cmd"
        return 0
    fi
    
    # Docker (if not forcing podman)
    if [[ "$force_runtime" != "podman" ]] && command -v docker &> /dev/null; then
        # Detect GPU availability (Docker GPU preflight is handled by Docker runtime; we only gate on nvidia-smi)
        local gpu_available=false
        if detect_gpu; then
            gpu_available=true
        else
            _log_gpu_warning
        fi

        # Docker Compose V2 (docker compose)
        if docker compose version &> /dev/null; then
            local cmd="docker compose -p ${project_name} -f ${compose_dir}/docker-compose.yml"
            if [[ "$gpu_available" == "true" ]]; then
                cmd="$cmd -f ${compose_dir}/docker-compose.gpu.yml"
            fi
            echo "$cmd"
            return 0
        fi
        # Docker Compose V1 (docker-compose)
        if command -v docker-compose &> /dev/null; then
            local cmd="docker-compose -p ${project_name} -f ${compose_dir}/docker-compose.yml"
            if [[ "$gpu_available" == "true" ]]; then
                cmd="$cmd -f ${compose_dir}/docker-compose.gpu.yml"
            fi
            echo "$cmd"
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

