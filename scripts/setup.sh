#!/bin/bash
# Lyra Setup Script
# Install Python dependencies via uv with .env environment variables
#
# Usage:
#   ./scripts/setup.sh         # Install MCP extras (default)
#   ./scripts/setup.sh mcp     # Install MCP extras
#   ./scripts/setup.sh ml      # Install ML extras
#   ./scripts/setup.sh full    # Install all extras

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# =============================================================================
# HELPERS
# =============================================================================

version_ge() {
    local actual="${1:-}"
    local required="${2:-}"
    if [[ -z "$actual" || -z "$required" ]]; then
        return 1
    fi
    local smallest
    smallest="$(printf '%s\n' "$required" "$actual" | sort -V | head -n 1)"
    [[ "$smallest" == "$required" ]]
}

get_rustc_version() {
    rustc --version 2>/dev/null | awk '{print $2}' | head -1
}

ensure_rust_toolchain() {
    local min_version="${1:-1.82.0}"

    if command -v rustc &> /dev/null; then
        local current
        current="$(get_rustc_version)"
        if version_ge "$current" "$min_version"; then
            log_info "rustc already available (rustc $current)"
            return 0
        fi
        log_warn "rustc is too old (rustc $current, expected ${min_version}+). Installing rustup toolchain..."
    else
        log_info "rustc not found. Installing rustup toolchain..."
    fi

    # Install rustup (non-interactive)
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    # shellcheck source=/dev/null
    source "$HOME/.cargo/env" 2>/dev/null || true

    # Verify
    if ! command -v rustc &> /dev/null; then
        output_error "$EXIT_DEPENDENCY" "rustc installation failed" "hint=Check rustup installation logs"
    fi
    local current
    current="$(get_rustc_version)"
    if ! version_ge "$current" "$min_version"; then
        output_error "$EXIT_DEPENDENCY" "rustc is still too old after rustup install (rustc $current)" "hint=Try: rustup update stable"
    fi
}

# =============================================================================
# CONTAINER GUARD
# =============================================================================

require_host_execution "setup.sh" "installs dependencies on the host"

# =============================================================================
# MAIN
# =============================================================================

EXTRAS="${1:-mcp}"

log_info "Installing dependencies (extras: $EXTRAS)..."

# Ensure Rust is available for building sudachipy (Python 3.14)
ensure_rust_toolchain "1.82.0"

# Ensure uv is installed
if ! command -v uv &> /dev/null; then
    log_info "Installing uv package manager..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck source=/dev/null
    source "$HOME/.local/bin/env" 2>/dev/null || true
fi

# Run uv sync (load_env already called by common.sh, so .env vars are set)
cd "$PROJECT_DIR" || exit 1
uv sync --frozen --extra "$EXTRAS"

log_info "Setup complete (extras: $EXTRAS)"
