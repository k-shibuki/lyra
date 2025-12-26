#!/bin/bash
# Lyra Environment Doctor
#
# Checks environment dependencies and configuration for WSL2 Ubuntu setup.
#
# Usage:
#   ./scripts/doctor.sh              # Check environment (default)
#   ./scripts/doctor.sh check        # Explicit check command
#   ./scripts/doctor.sh chrome-fix   # Fix WSL2 Chrome networking
#   ./scripts/doctor.sh help         # Show help

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

# =============================================================================
# LOAD DOCTOR MODULES
# =============================================================================

# Load help module first (allows showing help even if other modules fail)
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/doctor/help.sh"

# Load command handlers
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/doctor/commands.sh"

# =============================================================================
# MAIN
# =============================================================================

ACTION="${1:-check}"

case "$ACTION" in
    check)
        cmd_check
        ;;
    
    chrome-fix)
        cmd_chrome_fix
        ;;
    
    help|--help|-h)
        show_help
        ;;
    
    *)
        # Keep help/usage human-readable even when LYRA_OUTPUT_JSON=true.
        # This matches existing script behavior (dev.sh/test.sh).
        echo "Unknown action: $ACTION"
        echo ""
        show_help
        exit "$EXIT_USAGE"
        ;;
esac

