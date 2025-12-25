#!/bin/bash
# Lyra Shell Scripts - Common Functions and Constants
#
# This file provides shared utilities for all Lyra shell scripts.
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
#   - Standardized exit codes (AI-friendly)
#   - JSON output support (--json flag)
#   - Dry-run mode support (--dry-run flag)
#
# Script Dependencies:
#   common.sh  <- (base, no dependencies)
#   dev.sh     <- common.sh, podman-compose
#   chrome.sh  <- common.sh, curl, (WSL: powershell.exe)
#   test.sh    <- common.sh, pytest, uv
#   mcp.sh     <- common.sh, dev.sh, uv, playwright

# =============================================================================
# INITIALIZATION
# =============================================================================

# Note: Scripts sourcing this file should set "set -euo pipefail" after sourcing
# This file does not set it here to avoid affecting the sourcing script's behavior
# before it has a chance to set its own error handling

# =============================================================================
# STANDARDIZED EXIT CODES (AI-friendly)
# =============================================================================
# These exit codes provide machine-readable status for AI agents and CI systems.
# Exit codes follow a semantic convention for easy parsing.

# Success
export EXIT_SUCCESS=0

# General errors (1-9)
export EXIT_ERROR=1              # General/unknown error
export EXIT_USAGE=2              # Invalid usage/arguments
export EXIT_CONFIG=3             # Configuration error (missing .env, invalid config)
export EXIT_DEPENDENCY=4         # Missing dependency (podman, uv, etc.)
export EXIT_TIMEOUT=5            # Operation timed out
export EXIT_PERMISSION=6         # Permission denied

# Resource errors (10-19)
export EXIT_NOT_FOUND=10         # Resource not found (file, container, etc.)
export EXIT_ALREADY_EXISTS=11    # Resource already exists
export EXIT_NOT_RUNNING=12       # Service/container not running
export EXIT_NOT_READY=13         # Service not ready (health check failed)

# Test-specific errors (20-29)
export EXIT_TEST_FAILED=20       # Tests failed
export EXIT_TEST_ERROR=21        # Test execution error (not test failure)
export EXIT_TEST_TIMEOUT=22      # Test timeout
export EXIT_TEST_FATAL=23        # Fatal test error (disk I/O, OOM)

# Operation errors (30-39)
export EXIT_OPERATION_FAILED=30  # Generic operation failure
export EXIT_NETWORK=31           # Network/connection error
export EXIT_CONTAINER=32         # Container operation failed

# =============================================================================
# GLOBAL OUTPUT MODE FLAGS
# =============================================================================
# These flags control output format and behavior across all scripts.

# JSON output mode (set via --json flag)
# When true, commands output JSON instead of human-readable text
export LYRA_OUTPUT_JSON="${LYRA_OUTPUT_JSON:-false}"

# Dry-run mode (set via --dry-run flag)
# When true, destructive operations are simulated but not executed
export LYRA_DRY_RUN="${LYRA_DRY_RUN:-false}"

# Quiet mode (set via --quiet or -q flag)
# When true, suppress non-essential output
export LYRA_QUIET="${LYRA_QUIET:-false}"

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
# LYRA_BROWSER__CHROME_PORT from .env overrides default
export CHROME_PORT="${LYRA_BROWSER__CHROME_PORT:-9222}"

# Container settings
export CONTAINER_NAME="${LYRA_SCRIPT__CONTAINER_NAME:-lyra}"

# Timeouts (seconds)
export CONTAINER_TIMEOUT="${LYRA_SCRIPT__CONTAINER_TIMEOUT:-30}"
export CONNECT_TIMEOUT="${LYRA_SCRIPT__CONNECT_TIMEOUT:-30}"
export COMPLETION_THRESHOLD="${LYRA_SCRIPT__COMPLETION_THRESHOLD:-5}"

# Test result file path (inside container)
export TEST_RESULT_FILE="${LYRA_SCRIPT__TEST_RESULT_FILE:-/app/test_result.txt}"

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
        # In JSON mode, suppress human-readable error messages for expected exit codes
        # (These are already communicated via JSON output)
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]] || [[ "$exit_code" -eq 1 ]]; then
            log_error "Script failed at line ${line_num} with exit code ${exit_code}"
        fi
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
# JSON OUTPUT UTILITIES
# =============================================================================
# These functions provide machine-readable JSON output for AI agents.

# Function: json_output
# Description: Output a JSON object (only if JSON mode is enabled)
# Arguments:
#   $1: JSON string to output
# Example:
#   json_output '{"status": "ready", "port": 9222}'
json_output() {
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        echo "$1"
    fi
}

# Function: json_kv
# Description: Build a JSON key-value pair (properly escaped)
# Arguments:
#   $1: key
#   $2: value
# Returns: "key": "value" (with proper escaping)
json_kv() {
    local key="$1"
    local value="$2"
    # Escape special characters for JSON
    value="${value//\\/\\\\}"  # backslash
    value="${value//\"/\\\"}"  # double quote
    value="${value//$'\n'/\\n}" # newline
    value="${value//$'\r'/\\r}" # carriage return
    value="${value//$'\t'/\\t}" # tab
    printf '"%s": "%s"' "$key" "$value"
}

# Function: json_bool
# Description: Build a JSON key-boolean pair
# Arguments:
#   $1: key
#   $2: value (will be converted to true/false)
json_bool() {
    local key="$1"
    local value="$2"
    if [[ "$value" == "true" ]] || [[ "$value" == "1" ]] || [[ "$value" == "yes" ]]; then
        printf '"%s": true' "$key"
    else
        printf '"%s": false' "$key"
    fi
}

# Function: json_num
# Description: Build a JSON key-number pair
# Arguments:
#   $1: key
#   $2: numeric value
json_num() {
    local key="$1"
    local value="$2"
    printf '"%s": %s' "$key" "$value"
}

# Function: output_result
# Description: Output result in appropriate format (JSON or human-readable)
# Arguments:
#   $1: status (e.g., "success", "error", "running")
#   $2: message (human-readable)
#   $3+: Additional key=value pairs for JSON output
# Example:
#   output_result "success" "Container started" "container=lyra" "port=8080"
output_result() {
    local status="$1"
    local message="$2"
    shift 2

    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        local json_parts=()
        json_parts+=("$(json_kv "status" "$status")")
        json_parts+=("$(json_kv "message" "$message")")

        # Add additional key=value pairs
        for kv in "$@"; do
            local key="${kv%%=*}"
            local value="${kv#*=}"
            # Detect if value looks like a number or boolean
            if [[ "$value" =~ ^[0-9]+$ ]]; then
                json_parts+=("$(json_num "$key" "$value")")
            elif [[ "$value" == "true" ]] || [[ "$value" == "false" ]]; then
                json_parts+=("$(json_bool "$key" "$value")")
            else
                json_parts+=("$(json_kv "$key" "$value")")
            fi
        done

        # Join with commas and wrap in braces
        local IFS=','
        echo "{${json_parts[*]}}"
    else
        if [[ "$LYRA_QUIET" != "true" ]]; then
            echo "$message"
        fi
    fi
}

# =============================================================================
# DRY-RUN UTILITIES
# =============================================================================

# Function: dry_run_guard
# Description: Check if in dry-run mode and log intended action
# Arguments:
#   $1: Action description (what would be done)
# Returns:
#   0: Dry-run mode is active (caller should skip the action)
#   1: Normal mode (caller should proceed with action)
# Example:
#   if dry_run_guard "Delete container 'lyra'"; then
#       return 0  # Skip actual deletion
#   fi
#   podman rm lyra  # Actually delete
dry_run_guard() {
    local action="$1"
    if [[ "$LYRA_DRY_RUN" == "true" ]]; then
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_output "{$(json_kv "dry_run" "true"), $(json_kv "action" "$action")}"
        else
            echo "[DRY-RUN] Would: $action"
        fi
        return 0
    fi
    return 1
}

# Function: parse_global_flags
# Description: Parse global flags (--json, --dry-run, --quiet) from arguments
# Arguments:
#   $@: Command line arguments
# Returns:
#   Remaining arguments after removing global flags (via GLOBAL_ARGS array)
# Side effects:
#   Sets LYRA_OUTPUT_JSON, LYRA_DRY_RUN, LYRA_QUIET
parse_global_flags() {
    GLOBAL_ARGS=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --json)
                export LYRA_OUTPUT_JSON="true"
                shift
                ;;
            --dry-run)
                export LYRA_DRY_RUN="true"
                shift
                ;;
            --quiet|-q)
                export LYRA_QUIET="true"
                shift
                ;;
            *)
                GLOBAL_ARGS+=("$1")
                shift
                ;;
        esac
    done
}

# =============================================================================
# CONTAINER UTILITIES
# =============================================================================

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

# Function: detect_container
# Description: Detect if running inside container and which container
# Sets global variables: IN_CONTAINER, CURRENT_CONTAINER_NAME, IS_ML_CONTAINER
# Returns:
#   0: Successfully detected container status
detect_container() {
    # Detect if running inside container
    # Check for container markers (Docker/Podman)
    IN_CONTAINER=false
    CURRENT_CONTAINER_NAME=""
    if [[ -f "/.dockerenv" ]] || [[ -f "/run/.containerenv" ]]; then
        IN_CONTAINER=true
        # Try to detect container name from HOSTNAME (set by Podman/Docker)
        # HOSTNAME is typically set to container name
        if [[ -n "${HOSTNAME:-}" ]]; then
            CURRENT_CONTAINER_NAME="$HOSTNAME"
        elif [[ -n "${CONTAINER_NAME:-}" ]]; then
            CURRENT_CONTAINER_NAME="$CONTAINER_NAME"
        fi
    fi
    
    # Detect if running in ML container (lyra-ml has FastAPI and ML libs)
    # Other containers: lyra (main), lyra-ollama (LLM), lyra-tor (proxy)
    IS_ML_CONTAINER=false
    if [[ "$IN_CONTAINER" == "true" ]] && [[ "$CURRENT_CONTAINER_NAME" == "lyra-ml" ]]; then
        IS_ML_CONTAINER=true
    fi
    
    # Export for use by scripts
    export IN_CONTAINER
    export CURRENT_CONTAINER_NAME
    export IS_ML_CONTAINER
}

# Auto-detect container on source
detect_container

# Function: detect_cloud_agent
# Description: Detect if running in a cloud agent environment (CI/CD)
# Sets global variables: IS_CLOUD_AGENT, CLOUD_AGENT_TYPE
# Returns:
#   0: Successfully detected cloud agent status
#
# Cloud Agent Types:
#   - cursor: Cursor Cloud Agent
#   - claude_code: Claude Code (Anthropic)
#   - github_actions: GitHub Actions
#   - generic_ci: Generic CI environment
#   - none: Not a cloud agent environment
detect_cloud_agent() {
    IS_CLOUD_AGENT=false
    CLOUD_AGENT_TYPE="none"
    
    # Cursor Cloud Agent detection
    # Cursor sets specific environment variables when running as cloud agent
    if [[ -n "${CURSOR_CLOUD_AGENT:-}" ]] || [[ -n "${CURSOR_SESSION_ID:-}" ]] || [[ "${CURSOR_BACKGROUND:-}" == "true" ]]; then
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="cursor"
    # Claude Code detection (Anthropic)
    # Claude Code typically runs in a sandboxed environment
    elif [[ -n "${CLAUDE_CODE:-}" ]] || [[ -n "${ANTHROPIC_API_KEY:-}" && -z "${DISPLAY:-}" && "${CI:-}" == "true" ]]; then
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="claude_code"
    # GitHub Actions detection
    elif [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="github_actions"
    # GitLab CI detection
    elif [[ -n "${GITLAB_CI:-}" ]]; then
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="gitlab_ci"
    # Generic CI detection (many CI systems set CI=true)
    elif [[ "${CI:-}" == "true" ]]; then
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="generic_ci"
    # No display available (headless environment without explicit CI marker)
    # This is a heuristic for cloud/remote environments
    elif [[ -z "${DISPLAY:-}" ]] && [[ -z "${WAYLAND_DISPLAY:-}" ]] && [[ "$(detect_env)" != "wsl" ]]; then
        # In WSL, lack of DISPLAY is normal (uses Windows display)
        # In pure Linux without display, likely a server/cloud environment
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="headless"
    fi
    
    # Export for use by scripts
    export IS_CLOUD_AGENT
    export CLOUD_AGENT_TYPE
}

# Auto-detect cloud agent on source
detect_cloud_agent

# Function: is_e2e_capable
# Description: Check if the environment can run E2E tests
# Returns:
#   0: E2E capable (has display or headless browser configured)
#   1: Not E2E capable
is_e2e_capable() {
    # If explicitly configured for headless E2E
    if [[ "${LYRA_HEADLESS:-}" == "true" ]]; then
        return 0
    fi
    
    # If display is available
    if [[ -n "${DISPLAY:-}" ]] || [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
        return 0
    fi
    
    # WSL can access Windows display via CDP
    if [[ "$(detect_env)" == "wsl" ]]; then
        return 0
    fi
    
    # Not E2E capable
    return 1
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

# =============================================================================
# VENV MANAGEMENT (uv)
# =============================================================================

VENV_DIR="${PROJECT_DIR}/.venv"
export VENV_DIR

# Function: ensure_venv
# Description: Check if venv exists, fail if not
# Returns:
#   0: venv exists
#   1: venv not found
ensure_venv() {
    if [[ ! -f "${VENV_DIR}/bin/activate" ]]; then
        log_error "venv not found at ${VENV_DIR}"
        log_error "Run: make setup"
        return 1
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

# =============================================================================
# HTTP UTILITIES
# =============================================================================

# Function: wait_for_endpoint
# Description: Wait for HTTP endpoint with exponential backoff
# Arguments:
#   $1: URL to check (e.g., "http://localhost:8080/health")
#   $2: Total timeout in seconds (default: 30)
#   $3: Success message (optional)
# Returns:
#   0: Endpoint is ready
#   1: Timeout waiting for endpoint
wait_for_endpoint() {
    local url="$1"
    local timeout="${2:-30}"
    local success_msg="${3:-Endpoint ready}"
    
    local delay=0.5
    local max_delay=4.0
    local start_time
    start_time=$(date +%s)
    
    while true; do
        if curl -s --connect-timeout 2 "$url" > /dev/null 2>&1; then
            log_info "$success_msg"
            return 0
        fi
        
        local elapsed=$(($(date +%s) - start_time))
        if (( elapsed >= timeout )); then
            log_warn "Timeout waiting for $url"
            return 1
        fi
        
        sleep "$delay"
        delay=$(awk "BEGIN {d=$delay*2; print (d<$max_delay)?d:$max_delay}")
    done
}

