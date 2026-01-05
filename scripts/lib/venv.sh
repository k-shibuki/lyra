#!/bin/bash
# Lyra shell - venv management (uv)
#
# Note: VENV_DIR is defined in paths.sh (loaded earlier by common.sh)

# Function: ensure_venv
# Description: Check if venv exists, fail if not
# Returns:
#   0: venv exists
#   Exits with EXIT_DEPENDENCY if venv not found
ensure_venv() {
    if [[ ! -f "${VENV_DIR}/bin/activate" ]]; then
        output_error "$EXIT_DEPENDENCY" "venv not found at ${VENV_DIR}" "hint=make setup"
    fi
}

# Function: setup_venv
# Description: Create venv with uv if not exists
# Arguments:
#   $1: Extra dependencies (e.g., "mcp", "ml", "full")
# Returns:
#   0: venv ready
#   1: Failed to setup venv
setup_venv() {
    local extras="${1:-mcp}"

    if [[ -f "${VENV_DIR}/bin/activate" ]]; then
        log_info "venv already exists"
        return 0
    fi

    log_info "Setting up Python environment with uv..."

    if ! command -v uv &> /dev/null; then
        log_info "Installing uv package manager..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # shellcheck source=/dev/null
        source "$HOME/.local/bin/env" 2>/dev/null || true
    fi

    cd "$PROJECT_DIR" || return 1
    uv sync --frozen --extra "$extras"
    log_info "venv setup complete"
}


