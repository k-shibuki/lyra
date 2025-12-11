#!/bin/bash
# Lancet Shell Scripts - Common Functions and Constants
#
# This file provides shared utilities for all Lancet shell scripts.
# Source this file at the beginning of each script:
#   source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
#
# Features:
#   - Environment loading from .env
#   - Unified logging functions
#   - Container management utilities
#   - Common constants with .env overrides

# =============================================================================
# INITIALIZATION
# =============================================================================

# Get project directory (parent of scripts/)
get_project_dir() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    dirname "$script_dir"
}

PROJECT_DIR="$(get_project_dir)"

# =============================================================================
# ENVIRONMENT LOADING
# =============================================================================

# Load environment variables from .env file
# Variables are loaded with LANCET_ prefix and can override defaults
load_env() {
    local env_file="${PROJECT_DIR}/.env"
    if [ -f "$env_file" ]; then
        # Export variables from .env (skip comments and empty lines)
        set -a
        # shellcheck disable=SC1090
        source "$env_file"
        set +a
        return 0
    fi
    return 1
}

# Load .env if available (silent failure is OK - defaults will be used)
load_env 2>/dev/null || true

# =============================================================================
# CONSTANTS (with .env overrides)
# Exported for use by scripts that source this file
# =============================================================================

# Chrome CDP settings
# LANCET_BROWSER__CHROME_PORT from .env overrides default
export CHROME_PORT="${LANCET_BROWSER__CHROME_PORT:-9222}"

# Socat port for WSL2 -> Windows Chrome forwarding
export SOCAT_PORT="${LANCET_SCRIPT__SOCAT_PORT:-19222}"

# Container settings
export CONTAINER_NAME="${LANCET_SCRIPT__CONTAINER_NAME:-lancet}"

# Timeouts (seconds)
export CONTAINER_TIMEOUT="${LANCET_SCRIPT__CONTAINER_TIMEOUT:-30}"
export CONNECT_TIMEOUT="${LANCET_SCRIPT__CONNECT_TIMEOUT:-30}"
export COMPLETION_THRESHOLD="${LANCET_SCRIPT__COMPLETION_THRESHOLD:-5}"

# Test result file path (inside container)
export TEST_RESULT_FILE="${LANCET_SCRIPT__TEST_RESULT_FILE:-/app/test_result.txt}"

# =============================================================================
# LOGGING FUNCTIONS
# =============================================================================

# Log info message to stdout
log_info() {
    echo "[INFO] $*"
}

# Log warning message to stderr
log_warn() {
    echo "[WARN] $*" >&2
}

# Log error message to stderr
log_error() {
    echo "[ERROR] $*" >&2
}

# =============================================================================
# CONTAINER UTILITIES
# =============================================================================

# Check if the lancet container is running
# Returns: 0 if running, 1 otherwise
check_container_running() {
    local name="${1:-$CONTAINER_NAME}"
    podman ps --format "{{.Names}}" 2>/dev/null | grep -q "^${name}$"
}

# Wait for container to be ready
# Args: [container_name] [timeout_seconds]
# Returns: 0 if ready, 1 if timeout
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

# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================

# Detect the current environment type
# Returns: "wsl", "linux", or "windows"
detect_env() {
    if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
        echo "windows"
    elif grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl"
    else
        echo "linux"
    fi
}

# Get Windows host IP for WSL2 networking
get_windows_host() {
    if [ "$(detect_env)" = "wsl" ]; then
        ip route | grep default | awk '{print $3}'
    else
        echo "localhost"
    fi
}

# =============================================================================
# PODMAN/COMPOSE UTILITIES
# =============================================================================

# Get podman-compose command
get_compose_cmd() {
    if command -v podman-compose &> /dev/null; then
        echo "podman-compose"
    else
        log_error "podman-compose not found"
        log_error "Install with: sudo apt install podman-compose"
        return 1
    fi
}

# Check required commands exist
require_podman() {
    if ! command -v podman &> /dev/null; then
        log_error "podman not found"
        log_error "Install with: sudo apt install podman"
        return 1
    fi
    return 0
}

require_podman_compose() {
    require_podman || return 1
    if ! command -v podman-compose &> /dev/null; then
        log_error "podman-compose not found"
        log_error "Install with: sudo apt install podman-compose"
        return 1
    fi
    return 0
}

