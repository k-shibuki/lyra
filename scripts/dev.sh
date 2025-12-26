#!/bin/bash
# Lyra Development Environment (Podman)
#
# Manages the Podman-based development environment for Lyra.
#
# Usage: ./scripts/dev.sh [command]

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

# Change to project directory
cd "$PROJECT_DIR" || exit 1

# =============================================================================
# LOAD DEV MODULES (dependency-free modules first)
# =============================================================================

# Load help and precheck modules before dependency check
# This allows showing help even when podman is not installed
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/dev/help.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/dev/dispatch_precheck.sh"

# =============================================================================
# EARLY COMMAND HANDLING (before dependency check)
# =============================================================================

# Handle help and unknown commands early (before dependency check)
# This allows showing help even when podman is not installed
if ! handle_dev_precheck "${1:-}"; then
    # Help was shown or unknown command - exit
    exit 0
fi

# Valid command, continue to dependency check
ACTION="${1:-help}"

# =============================================================================
# DEPENDENCY CHECK
# =============================================================================

# Verify required commands (exit mode for JSON output support)
require_podman_compose "exit"

# shellcheck disable=SC2034
COMPOSE="podman-compose"

# =============================================================================
# LOAD REMAINING DEV MODULES
# =============================================================================

# Load remaining dev modules (after dependency check)
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/dev/shell.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/dev/logs.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/dev/clean.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/dev/commands.sh"

# =============================================================================
# MAIN
# =============================================================================

case "$ACTION" in
    up)
        cmd_up
        ;;
    
    down)
        cmd_down
        ;;
    
    build)
        cmd_build
        ;;
    
    rebuild)
        cmd_rebuild
        ;;
    
    shell)
        start_dev_shell
        ;;
    
    logs)
        show_logs "${2:-}" "${3:-}"
        ;;
    
    test)
        cmd_test
        ;;
    
    mcp)
        cmd_mcp
        ;;
    
    research)
        cmd_research "${2:-}"
        ;;
    
    status)
        cmd_status
        ;;
    
    clean)
        cleanup_environment
        ;;
    
    # help|--help|-h|* are handled above before dependency check
esac
