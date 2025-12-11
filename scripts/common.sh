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
#   - Debug mode support
#   - Error handling utilities

# =============================================================================
# INITIALIZATION
# =============================================================================

# Note: Scripts sourcing this file should set "set -euo pipefail" after sourcing
# This file does not set it here to avoid affecting the sourcing script's behavior
# before it has a chance to set its own error handling

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

# Function: load_env
# Description: Load environment variables from .env file with security checks
# Returns:
#   0: Successfully loaded .env file
#   1: .env file not found or error loading
load_env() {
    local env_file="${PROJECT_DIR}/.env"
    if [ -f "$env_file" ]; then
        # Check file permissions (warn if world-readable)
        local perms
        perms=$(stat -c "%a" "$env_file" 2>/dev/null || echo "000")
        if [ "${perms:2:1}" != "0" ]; then
            log_warn ".env file has world-readable permissions (should be 600)"
        fi
        
        # Check for dangerous variable names that could override critical paths
        if grep -qE '^(PATH|LD_LIBRARY_PATH|LD_PRELOAD)=' "$env_file" 2>/dev/null; then
            log_warn ".env file contains potentially dangerous variables (PATH, LD_LIBRARY_PATH, LD_PRELOAD)"
        fi
        
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
# Note: We use || true to allow script to continue even if .env doesn't exist
load_env 2>/dev/null || true

# =============================================================================
# CONSTANTS (with .env overrides)
# Exported for use by scripts that source this file
# =============================================================================

# Chrome CDP settings
# LANCET_BROWSER__CHROME_PORT from .env overrides default
export CHROME_PORT="${LANCET_BROWSER__CHROME_PORT:-9222}"

# Container settings
export CONTAINER_NAME="${LANCET_SCRIPT__CONTAINER_NAME:-lancet}"

# Timeouts (seconds)
export CONTAINER_TIMEOUT="${LANCET_SCRIPT__CONTAINER_TIMEOUT:-30}"
export CONNECT_TIMEOUT="${LANCET_SCRIPT__CONNECT_TIMEOUT:-30}"
export COMPLETION_THRESHOLD="${LANCET_SCRIPT__COMPLETION_THRESHOLD:-5}"

# Test result file path (inside container)
export TEST_RESULT_FILE="${LANCET_SCRIPT__TEST_RESULT_FILE:-/app/test_result.txt}"

# =============================================================================
# DEBUG MODE
# =============================================================================

# Function: enable_debug_mode
# Description: Enable debug mode with detailed tracing if DEBUG=1 is set
# Environment variables:
#   DEBUG: Set to "1" to enable debug mode
enable_debug_mode() {
    if [ "${DEBUG:-}" = "1" ]; then
        set -x
        export PS4='+ [${BASH_SOURCE[0]}:${LINENO}] ${FUNCNAME[0]:+${FUNCNAME[0]}(): }'
    fi
}

# =============================================================================
# ERROR HANDLING
# =============================================================================

# Function: cleanup_on_error
# Description: Error handler that logs error information and cleans up
# Arguments:
#   $1: Line number where error occurred (optional)
# Note: This should be set up with trap in scripts that source this file
#       Usage: trap 'cleanup_on_error ${LINENO}' ERR
cleanup_on_error() {
    local exit_code=$?
    local line_num="${1:-unknown}"
    if [ $exit_code -ne 0 ]; then
        log_error "Script failed at line ${line_num} with exit code ${exit_code}"
        if [ "${DEBUG:-}" = "1" ]; then
            log_error "Stack trace:"
            # Temporarily disable trace to avoid recursion
            local trace_enabled=false
            if [ "${-//[^x]/}" = "x" ]; then
                trace_enabled=true
                set +x
            fi
            local frame=0
            while caller $frame 2>/dev/null; do
                ((frame++))
            done
            if [ "$trace_enabled" = "true" ]; then
                set -x
            fi
        fi
    fi
    exit $exit_code
}

# =============================================================================
# LOGGING FUNCTIONS
# =============================================================================

# Function: log_info
# Description: Log info message to stdout
# Arguments:
#   $*: Message to log
log_info() {
    echo "[INFO] $*"
}

# Function: log_warn
# Description: Log warning message to stderr
# Arguments:
#   $*: Message to log
log_warn() {
    echo "[WARN] $*" >&2
}

# Function: log_error
# Description: Log error message to stderr
# Arguments:
#   $*: Message to log
log_error() {
    echo "[ERROR] $*" >&2
}

# =============================================================================
# CONTAINER UTILITIES
# =============================================================================

# Function: check_container_running
# Description: Check if the lancet container is running
# Arguments:
#   $1: Container name (optional, defaults to CONTAINER_NAME)
# Returns:
#   0: Container is running
#   1: Container is not running
check_container_running() {
    local name="${1:-$CONTAINER_NAME}"
    podman ps --format "{{.Names}}" 2>/dev/null | grep -q "^${name}$"
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

# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================

# Function: detect_env
# Description: Detect the current environment type
# Returns: "wsl", "linux", or "windows"
detect_env() {
    if [[ "${OSTYPE:-}" == "msys" ]] || [[ "${OSTYPE:-}" == "win32" ]]; then
        echo "windows"
    elif grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl"
    else
        echo "linux"
    fi
}

# Function: get_windows_host
# Description: Get Windows host IP for WSL2 networking
# Returns: Windows host IP if WSL, "localhost" otherwise
get_windows_host() {
    if [ "$(detect_env)" = "wsl" ]; then
        ip route | grep default | awk '{print $3}' || echo "localhost"
    else
        echo "localhost"
    fi
}

# =============================================================================
# PODMAN/COMPOSE UTILITIES
# =============================================================================

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
# Returns:
#   0: podman is available
#   1: podman not found
require_podman() {
    if ! command -v podman &> /dev/null; then
        log_error "podman not found"
        log_error "Install with: sudo apt install podman"
        return 1
    fi
    return 0
}

# Function: require_podman_compose
# Description: Check if podman and podman-compose commands exist
# Returns:
#   0: Both commands are available
#   1: One or both commands not found
require_podman_compose() {
    require_podman || return 1
    if ! command -v podman-compose &> /dev/null; then
        log_error "podman-compose not found"
        log_error "Install with: sudo apt install podman-compose"
        return 1
    fi
    return 0
}

