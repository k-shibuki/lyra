#!/bin/bash
# Lyra Test Runner (Cloud Agent Compatible)
#
# Runs tests directly in WSL venv (hybrid architecture).
# This design provides fast test execution without container overhead.
#
# Supports multiple environments:
#   - Cloud Agents (Cursor, Claude Code): Unit/Integration tests only
#   - CI (GitHub Actions, GitLab): Unit/Integration tests only
#   - Local (WSL2): Unit/Integration + optional E2E
#
# Usage:
#   ./scripts/test.sh run [pytest_args...]  # Start test execution (async)
#   ./scripts/test.sh check                 # Wait until done and print result summary
#   ./scripts/test.sh kill          # Force stop pytest
#   ./scripts/test.sh env           # Show environment info

set -euo pipefail

# =============================================================================
# INITIALIZATION
# =============================================================================

# Source common functions and load .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# Note: PROJECT_DIR and VENV_DIR are provided by common.sh

# Enable debug mode if DEBUG=1
enable_debug_mode

# Set up error handler
trap 'cleanup_on_error ${LINENO}' ERR

# =============================================================================
# CONFIGURATION
# =============================================================================

# Parse global flags first (--json, --quiet)
parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

ACTION="${1:-run}"
shift || true

# Runtime selection:
#   - auto (default): container > venv
#   - container: force container execution
#   - venv: force local venv execution
# shellcheck disable=SC2034
RUNTIME_MODE="auto"
# shellcheck disable=SC2034
CONTAINER_NAME_SELECTED="${CONTAINER_NAME:-lyra}"

# State file persists the last started runtime so check/get/kill target the same env.
# shellcheck disable=SC2034
TEST_STATE_FILE="${LYRA_SCRIPT__TEST_STATE_FILE:-/tmp/lyra_test_state.env}"

# Note: VENV_DIR is provided by common.sh

# Result directory and file naming
# Each run creates unique files with timestamp to prevent result confusion
# shellcheck disable=SC2034
TEST_RESULT_DIR="${LYRA_SCRIPT__TEST_RESULT_DIR:-/tmp/lyra_test}"

# Legacy fixed paths (used only for cleanup of old runs)
# shellcheck disable=SC2034
LEGACY_RESULT_FILE="/tmp/lyra_test_result.txt"
# shellcheck disable=SC2034
LEGACY_PID_FILE="/tmp/lyra_test_pid"

# check() behavior
# shellcheck disable=SC2034
CHECK_INTERVAL_SECONDS="${LYRA_SCRIPT__CHECK_INTERVAL_SECONDS:-1}"
# shellcheck disable=SC2034
CHECK_TIMEOUT_SECONDS="${LYRA_SCRIPT__CHECK_TIMEOUT_SECONDS:-600}"
# shellcheck disable=SC2034
CHECK_TAIL_LINES="${LYRA_SCRIPT__CHECK_TAIL_LINES:-60}"

# Collected pytest args (can be a single target or multiple args)
# shellcheck disable=SC2034
PYTEST_ARGS=()

# Container detection is done in common.sh (detect_container function)
# Variables available: IN_CONTAINER, CURRENT_CONTAINER_NAME, IS_ML_CONTAINER

# =============================================================================
# LOAD TEST MODULES
# =============================================================================

# Load test lib modules in dependency order
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/test/args.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/test/state.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/test/runtime.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/test/markers.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/test/check_helpers.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/test/commands.sh"

# =============================================================================
# MAIN
# =============================================================================

case "$ACTION" in
    run)
        parse_common_flags "$@"
        cmd_run
        ;;

    check)
        parse_common_flags "$@"
        # First remaining arg (if any) is run_id
        cmd_check "${PYTEST_ARGS[0]:-}"
        ;;

    kill)
        parse_common_flags "$@"
        # First remaining arg (if any) is run_id
        cmd_kill "${PYTEST_ARGS[0]:-}"
        ;;
    
    debug)
        parse_common_flags "$@"
        # First remaining arg (if any) is run_id
        cmd_debug "${PYTEST_ARGS[0]:-}"
        ;;
    
    env)
        parse_common_flags "$@"
        cmd_env
        ;;
    
    help|--help|-h)
        show_help
        ;;

    *)
        echo "Usage: $0 {run|check|kill|env|help} [pytest_args...]"
        exit 1
        ;;
esac
