#!/bin/bash
# Lyra Chrome Manager
#
# Start Chrome with remote debugging for Lyra.
# Designed to coexist with existing Chrome sessions by using separate user-data-dir.
#
# Usage:
#   ./scripts/chrome.sh              # Check status
#   ./scripts/chrome.sh check        # Check if debug port is available
#   ./scripts/chrome.sh start        # Start Chrome with remote debugging
#   ./scripts/chrome.sh stop         # Stop Lyra Chrome instance
#   ./scripts/chrome.sh diagnose     # Troubleshoot connection issues
#   ./scripts/chrome.sh fix          # Auto-fix WSL2 mirrored networking issues

set -euo pipefail

# =============================================================================
# INITIALIZATION
# =============================================================================

# Source common functions and load .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# Enable debug mode if DEBUG=1
enable_debug_mode

# Set up error handler
trap 'cleanup_on_error ${LINENO}' ERR

# Parse global flags first (--json, --quiet)
parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

# Command line arguments (override .env defaults)
ACTION="${1:-check}"
CHROME_PORT_ARG="${2:-}"

# Use argument if provided, otherwise use .env value (from common.sh)
if [ -n "$CHROME_PORT_ARG" ]; then
    CHROME_PORT="$CHROME_PORT_ARG"
fi
# CHROME_PORT is already set from common.sh with .env override

# =============================================================================
# CONTAINER GUARD (allow help)
# =============================================================================

require_host_execution_unless "chrome.sh" "manages Windows Chrome via CDP from WSL" "$ACTION" "help" "--help" "-h"

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
source "${SCRIPT_DIR}/lib/chrome/diagnose.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/fix.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/chrome/help.sh"

# =============================================================================
# MAIN
# =============================================================================

case "$ACTION" in
    check|status)
        get_status "$CHROME_PORT"
        ;;
    
    start)
        # Check if already running
        if try_connect "$CHROME_PORT" > /dev/null 2>&1; then
            echo "ALREADY_RUNNING"
            get_status "$CHROME_PORT"
            exit 0
        fi
        
        case "$ENV_TYPE" in
            wsl)
                start_chrome_wsl "$CHROME_PORT"
                ;;
            linux)
                start_chrome_linux "$CHROME_PORT"
                ;;
            windows)
                echo "ERROR"
                echo "Run from WSL or Linux, or use PowerShell directly on Windows"
                exit 1
                ;;
        esac
        ;;
    
    stop)
        stop_chrome "$CHROME_PORT"
        ;;
    
    diagnose|diag)
        run_diagnose "$CHROME_PORT"
        ;;
    
    fix)
        run_fix "$CHROME_PORT"
        ;;
    
    help|--help|-h)
        show_help
        ;;
    
    *)
        echo "Unknown action: $ACTION"
        echo "Use: $0 {check|start|stop|diagnose|fix|help}"
        exit 1
        ;;
esac
