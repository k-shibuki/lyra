#!/bin/bash
# Lancet Test Runner (Cursor AI-friendly)
#
# Runs tests in a background process and provides polling-based result checking.
# This design prevents terminal blocking when running from AI assistants.
#
# Usage:
#   ./scripts/test.sh run [target]  # Start test execution
#   ./scripts/test.sh check         # Check completion status
#   ./scripts/test.sh get           # Get test results
#   ./scripts/test.sh kill          # Force stop pytest

set -e

# =============================================================================
# INITIALIZATION
# =============================================================================

# Source common functions and load .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# =============================================================================
# CONFIGURATION
# =============================================================================

ACTION="${1:-run}"
TARGET="${2:-tests/}"

# =============================================================================
# COMMAND HANDLERS
# =============================================================================

cmd_run() {
    local target="$1"
    
    echo "=== Cleanup ==="
    podman exec "$CONTAINER_NAME" pkill -9 -f "pytest" 2>/dev/null || true
    sleep 1
    
    echo "=== Running: $target ==="
    # Run pytest in detached mode (independent process in container)
    podman exec "$CONTAINER_NAME" rm -f "$TEST_RESULT_FILE"
    podman exec -d "$CONTAINER_NAME" sh -c "PYTHONUNBUFFERED=1 pytest $target -m 'not e2e' --tb=short -q > $TEST_RESULT_FILE 2>&1"
    echo "Started. Run: ./scripts/test.sh check"
}

cmd_check() {
    # Determine completion by file modification time
    # If no updates for COMPLETION_THRESHOLD seconds, test is done
    local mtime
    local now
    local age
    local last_line
    
    mtime=$(podman exec "$CONTAINER_NAME" stat -c %Y "$TEST_RESULT_FILE" 2>/dev/null || echo 0)
    now=$(podman exec "$CONTAINER_NAME" date +%s)
    age=$((now - mtime))
    last_line=$(podman exec "$CONTAINER_NAME" tail -1 "$TEST_RESULT_FILE" 2>/dev/null || echo "waiting...")
    
    if [ "$age" -gt "$COMPLETION_THRESHOLD" ]; then
        echo "DONE (${age}s ago)"
        podman exec "$CONTAINER_NAME" tail -5 "$TEST_RESULT_FILE" 2>/dev/null
    else
        echo "RUNNING | $last_line"
    fi
}

cmd_get() {
    echo "=== Result ==="
    podman exec "$CONTAINER_NAME" tail -20 "$TEST_RESULT_FILE" 2>/dev/null || echo "No result"
}

cmd_kill() {
    echo "Killing..."
    podman exec "$CONTAINER_NAME" pkill -9 -f "pytest" 2>/dev/null || true
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
