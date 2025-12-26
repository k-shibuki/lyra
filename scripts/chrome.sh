#!/bin/bash
# Lyra Chrome Manager - Dynamic Worker Pool
#
# Manages Chrome instances for the worker pool.
# Each worker gets its own Chrome with dedicated port and profile.
# Number of Chrome instances is driven by num_workers in settings.yaml.
#
# Usage:
#   ./scripts/chrome.sh              # Show pool status
#   ./scripts/chrome.sh status       # Show pool status (all workers)
#   ./scripts/chrome.sh start        # Start Chrome for all workers
#   ./scripts/chrome.sh stop         # Stop all Chrome instances
#   ./scripts/chrome.sh restart      # Restart Chrome pool
#   ./scripts/chrome.sh diagnose     # Troubleshoot connection issues
#   ./scripts/chrome.sh fix          # Auto-fix WSL2 mirrored networking issues

set -euo pipefail

# =============================================================================
# INITIALIZATION
# =============================================================================

# Source common functions and load .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# Enable debug mode if DEBUG=1
enable_debug_mode

# Set up error handler
trap 'cleanup_on_error ${LINENO}' ERR

# Parse global flags first (--json, --quiet)
parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

# Command line arguments
ACTION="${1:-status}"

# =============================================================================
# CONTAINER GUARD (allow help)
# =============================================================================

require_host_execution_unless "chrome.sh" "manages Windows Chrome via CDP from WSL" "$ACTION" "help" "--help" "-h"

# =============================================================================
# DYNAMIC WORKER POOL CONFIGURATION
# =============================================================================

# Get num_workers from settings.yaml
get_num_workers() {
    local yaml_file="${PROJECT_ROOT}/config/settings.yaml"
    if [ -f "$yaml_file" ]; then
        grep -oP 'num_workers:\s*\K\d+' "$yaml_file" 2>/dev/null || echo 2
    else
        echo 2
    fi
}

# Get base port from environment or settings.yaml
get_base_port() {
    if [ -n "${LYRA_BROWSER__CHROME_BASE_PORT:-}" ]; then
        echo "$LYRA_BROWSER__CHROME_BASE_PORT"
    else
        local yaml_file="${PROJECT_ROOT}/config/settings.yaml"
        if [ -f "$yaml_file" ]; then
            grep -oP 'chrome_base_port:\s*\K\d+' "$yaml_file" 2>/dev/null || echo 9222
        else
            echo 9222
        fi
    fi
}

# Get profile prefix from environment or settings.yaml
get_profile_prefix() {
    if [ -n "${LYRA_BROWSER__CHROME_PROFILE_PREFIX:-}" ]; then
        echo "$LYRA_BROWSER__CHROME_PROFILE_PREFIX"
    else
        local yaml_file="${PROJECT_ROOT}/config/settings.yaml"
        if [ -f "$yaml_file" ]; then
            grep -oP 'chrome_profile_prefix:\s*"\K[^"]+' "$yaml_file" 2>/dev/null || echo "Lyra-"
        else
            echo "Lyra-"
        fi
    fi
}

# Calculate port for a specific worker
get_worker_port() {
    local worker_id="$1"
    local base_port
    base_port=$(get_base_port)
    echo $((base_port + worker_id))
}

# Calculate profile name for a specific worker
get_worker_profile() {
    local worker_id="$1"
    local prefix
    prefix=$(get_profile_prefix)
    printf '%s%02d' "$prefix" "$worker_id"
}

# Export for use in submodules
NUM_WORKERS=$(get_num_workers)
CHROME_BASE_PORT=$(get_base_port)
CHROME_PROFILE_PREFIX=$(get_profile_prefix)
export NUM_WORKERS CHROME_BASE_PORT CHROME_PROFILE_PREFIX

# =============================================================================
# CONSTANTS
# =============================================================================

# Connection attempt settings
# shellcheck disable=SC2034
CURL_TIMEOUT=1
# Total timeout for Chrome startup connection (seconds)
# shellcheck disable=SC2034
STARTUP_TIMEOUT_WSL=15
# shellcheck disable=SC2034
STARTUP_TIMEOUT_LINUX=10
# Exponential backoff parameters
# shellcheck disable=SC2034
BACKOFF_BASE_DELAY=0.5
# shellcheck disable=SC2034
BACKOFF_MAX_DELAY=4.0

# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================

# Use common environment detection function
ENV_TYPE=$(detect_env)
export ENV_TYPE

# =============================================================================
# LOAD CHROME MODULES
# =============================================================================

# Load chrome lib modules in dependency order
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/ps.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/connect.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/status.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/start.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/stop.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/pool.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/diagnose.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/fix.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/help.sh"

# =============================================================================
# MAIN
# =============================================================================

case "$ACTION" in
    status|check)
        # Show status for all workers in the pool
        show_pool_status
        ;;
    
    start)
        # Start Chrome for all workers
        start_chrome_pool
        ;;
    
    stop)
        # Stop all Chrome instances
        stop_chrome_pool
        ;;
    
    restart)
        # Restart Chrome pool
        stop_chrome_pool
        sleep 1
        start_chrome_pool
        ;;
    
    diagnose|diag)
        # Diagnose all workers in the pool (or specific port if provided)
        DIAGNOSE_PORT="${2:-}"
        if [ -n "$DIAGNOSE_PORT" ]; then
            # Single port diagnosis
            run_diagnose "$DIAGNOSE_PORT"
        else
            # Full pool diagnosis
            run_diagnose_pool
        fi
        ;;
    
    fix)
        run_fix "$CHROME_BASE_PORT"
        ;;
    
    help|--help|-h)
        show_help
        ;;
    
    *)
        echo "Unknown action: $ACTION"
        echo "Use: $0 {status|start|stop|restart|diagnose|fix|help}"
        exit 1
        ;;
esac
