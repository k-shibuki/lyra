#!/bin/bash
# Dev Dispatch Precheck
#
# Early command validation and help handling before dependency checks.
# This allows showing help even when podman is not installed.

# Valid commands list (used for validation)
# shellcheck disable=SC2034
VALID_DEV_COMMANDS="up|down|build|rebuild|shell|logs|test|mcp|research|status|clean|help"

# Function: handle_dev_precheck
# Description: Handle help and unknown commands early (before dependency check)
# Arguments:
#   $1: First command argument
# Returns:
#   0: Help shown or valid command (continue)
#   1: Unknown command (help shown, should exit)
handle_dev_precheck() {
    local action="${1:-}"
    
    case "$action" in
        help|--help|-h|"")
            _show_help
            return 1  # Signal to exit
            ;;
        up|down|build|rebuild|shell|logs|test|mcp|research|status|clean)
            # Valid command, continue to dependency check
            return 0
            ;;
        *)
            # Unknown command - show help
            _show_help
            return 1  # Signal to exit
            ;;
    esac
}

