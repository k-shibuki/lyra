#!/bin/bash
# Lancet Test Runner (Cursor AI-friendly)
#
# Runs tests directly in WSL venv (hybrid architecture).
# This design provides fast test execution without container overhead.
#
# Usage:
#   ./scripts/test.sh run [target]  # Start test execution
#   ./scripts/test.sh check         # Check completion status
#   ./scripts/test.sh get           # Get test results
#   ./scripts/test.sh kill          # Force stop pytest

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

# =============================================================================
# CONFIGURATION
# =============================================================================

ACTION="${1:-run}"
TARGET="${2:-tests/}"

VENV_DIR="${PROJECT_ROOT}/.venv"
TEST_RESULT_FILE="${PROJECT_ROOT}/.test_result.txt"
TEST_PID_FILE="${PROJECT_ROOT}/.test_pid"

# =============================================================================
# VENV MANAGEMENT
# =============================================================================

ensure_venv() {
    if [[ ! -f "${VENV_DIR}/bin/activate" ]]; then
        log_error "venv not found. Run: ./scripts/mcp.sh (or create manually)"
        exit 1
    fi
}

# =============================================================================
# COMMAND HANDLERS
# =============================================================================

# Function: cmd_run
# Description: Start test execution in background
# Arguments:
#   $1: Test target (default: tests/)
# Returns:
#   0: Test execution started
cmd_run() {
    local target="$1"
    
    ensure_venv
    
    echo "=== Cleanup ==="
    pkill -9 -f "pytest" 2>/dev/null || true
    sleep 1
    
    echo "=== Running: $target ==="
    rm -f "$TEST_RESULT_FILE" "$TEST_PID_FILE"
    
    # Activate venv and run pytest in background
    (
        # shellcheck source=/dev/null
        source "${VENV_DIR}/bin/activate"
        cd "${PROJECT_ROOT}"
        export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
        PYTHONUNBUFFERED=1 pytest "$target" -m 'not e2e' --tb=short -q > "$TEST_RESULT_FILE" 2>&1 &
        echo $! > "$TEST_PID_FILE"
    )
    
    echo "Started. Run: ./scripts/test.sh check"
}

# Function: cmd_check
# Description: Check if tests are completed by checking file modification time
#             If no updates for COMPLETION_THRESHOLD seconds, test is done
# Returns:
#   0: Tests completed or still running
#   1: Result file not found
cmd_check() {
    # Check if result file exists
    if [[ ! -f "$TEST_RESULT_FILE" ]]; then
        echo "NOT_STARTED"
        log_error "Test result file not found"
        return 1
    fi
    
    local mtime
    local now
    local age
    local last_line
    
    mtime=$(stat -c %Y "$TEST_RESULT_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$((now - mtime))
    last_line=$(tail -1 "$TEST_RESULT_FILE" 2>/dev/null || echo "waiting...")
    
    if [ "$age" -gt "$COMPLETION_THRESHOLD" ]; then
        echo "DONE (${age}s ago)"
        tail -5 "$TEST_RESULT_FILE" 2>/dev/null || echo "No output"
    else
        echo "RUNNING | $last_line"
    fi
}

# Function: cmd_get
# Description: Get test results (last 20 lines)
# Returns:
#   0: Success, outputs test results
#   1: Result file not found
cmd_get() {
    echo "=== Result ==="
    
    # Check if result file exists
    if [[ ! -f "$TEST_RESULT_FILE" ]]; then
        log_error "Test result file not found"
        echo "No result - file not found"
        return 1
    fi
    
    tail -20 "$TEST_RESULT_FILE" 2>/dev/null || {
        log_error "Failed to read test result file"
        echo "No result - read error"
        return 1
    }
}

# Function: cmd_kill
# Description: Force stop pytest process
# Returns:
#   0: Success
cmd_kill() {
    echo "Killing..."
    pkill -9 -f "pytest" 2>/dev/null || true
    if [[ -f "$TEST_PID_FILE" ]]; then
        local pid
        pid=$(cat "$TEST_PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$pid" ]]; then
            kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$TEST_PID_FILE"
    fi
    echo "Done"
}

show_help() {
    echo "Lancet Test Runner (AI-friendly)"
    echo ""
    echo "Usage: $0 {run|check|get|kill} [target]"
    echo ""
    echo "Commands:"
    echo "  run [target]  Start test execution (default: tests/)"
    echo "  check         Check if tests are done (DONE/RUNNING)"
    echo "  get           Get test results (last 20 lines)"
    echo "  kill          Force stop pytest process"
    echo ""
    echo "Pattern: Start with 'run', poll with 'check', get results with 'get'"
    echo ""
    echo "Note: Tests run in WSL venv (.venv), not in container."
}

# =============================================================================
# MAIN
# =============================================================================

case "$ACTION" in
    run)
        cmd_run "$TARGET"
        ;;
    
    check)
        cmd_check
        ;;
    
    get)
        cmd_get
        ;;
    
    kill)
        cmd_kill
        ;;
    
    help|--help|-h)
        show_help
        ;;
    
    *)
        echo "Usage: $0 {run|check|get|kill} [target]"
        exit 1
        ;;
esac
