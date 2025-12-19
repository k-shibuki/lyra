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
#   ./scripts/test.sh run [target]  # Start test execution
#   ./scripts/test.sh check         # Check completion status
#   ./scripts/test.sh get           # Get test results
#   ./scripts/test.sh kill          # Force stop pytest
#   ./scripts/test.sh env           # Show environment info

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
# Override common.sh defaults for local (non-container) execution
TEST_RESULT_FILE="${LYRA_SCRIPT__TEST_RESULT_FILE:-/tmp/lyra_test_result.txt}"
TEST_PID_FILE="${LYRA_SCRIPT__TEST_PID_FILE:-/tmp/lyra_test_pid}"

# Container detection is done in common.sh (detect_container function)
# Variables available: IN_CONTAINER, CURRENT_CONTAINER_NAME, IS_ML_CONTAINER

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
# TEST MARKER SELECTION
# =============================================================================

# Function: get_pytest_markers
# Description: Get appropriate pytest markers based on environment
# Returns: Marker expression string for pytest -m option
# Note: Log messages are written to stderr to avoid polluting the return value
get_pytest_markers() {
    local markers=""
    
    if [[ "${IS_CLOUD_AGENT:-false}" == "true" ]]; then
        # Cloud agent environment: unit + integration only (no e2e, no slow)
        markers="not e2e and not slow"
        log_info "Cloud agent detected (${CLOUD_AGENT_TYPE:-unknown}): Running unit + integration tests only" >&2
    elif [[ "${LYRA_TEST_LAYER:-}" == "e2e" ]]; then
        # Explicitly request E2E tests
        markers="e2e"
        log_info "E2E layer requested: Running E2E tests" >&2
    elif [[ "${LYRA_TEST_LAYER:-}" == "all" ]]; then
        # Run all tests
        markers=""
        log_info "All tests requested" >&2
    else
        # Default: unit + integration (exclude e2e)
        markers="not e2e"
        log_info "Default layer: Running unit + integration tests" >&2
    fi
    
    echo "$markers"
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
    
    # Get appropriate markers for this environment
    local markers
    markers=$(get_pytest_markers)
    
    # Activate venv and run pytest in background
    (
        # shellcheck source=/dev/null
        source "${VENV_DIR}/bin/activate"
        cd "${PROJECT_ROOT}"
        export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
        
        # Export cloud agent detection for Python-side detection
        export IS_CLOUD_AGENT="${IS_CLOUD_AGENT:-false}"
        export CLOUD_AGENT_TYPE="${CLOUD_AGENT_TYPE:-none}"
        
        # Set environment variables for container-specific tests
        # - lyra-ml container: Has FastAPI and ML libs (enable all ML tests)
        # - lyra container: May have ML libs but no FastAPI (enable ML lib tests only)
        # Note: .env file values take precedence (already loaded by common.sh)
        # Note: Ollama/Tor tests are unit tests with mocks, so no special handling needed
        if [[ "${IN_CONTAINER:-false}" == "true" ]]; then
            # ML tests (lyra-ml container has all ML libs)
            export LYRA_RUN_ML_TESTS="${LYRA_RUN_ML_TESTS:-1}"
            # ML API tests (lyra-ml container has FastAPI)
            if [[ "${IS_ML_CONTAINER:-false}" == "true" ]]; then
                export LYRA_RUN_ML_API_TESTS="${LYRA_RUN_ML_API_TESTS:-1}"
            else
                # Check if FastAPI is available (fallback for other containers)
                if python3 -c "import fastapi" 2>/dev/null; then
                    export LYRA_RUN_ML_API_TESTS="${LYRA_RUN_ML_API_TESTS:-1}"
                fi
            fi
            # Extractor tests (PDF/OCR - typically in ML container but may be in lyra)
            export LYRA_RUN_EXTRACTOR_TESTS="${LYRA_RUN_EXTRACTOR_TESTS:-1}"
        fi

        # Export container detection flags (default to 0 if not set and not in container)
        export LYRA_RUN_ML_TESTS="${LYRA_RUN_ML_TESTS:-0}"
        export LYRA_RUN_ML_API_TESTS="${LYRA_RUN_ML_API_TESTS:-0}"
        export LYRA_RUN_EXTRACTOR_TESTS="${LYRA_RUN_EXTRACTOR_TESTS:-0}"
        
        # Build pytest command with appropriate markers
        local pytest_cmd="pytest $target --tb=short -q"
        if [[ -n "$markers" ]]; then
            pytest_cmd="$pytest_cmd -m '$markers'"
        fi
        
        PYTHONUNBUFFERED=1 eval "$pytest_cmd" > "$TEST_RESULT_FILE" 2>&1 &
        echo $! > "$TEST_PID_FILE"
    )

    echo "Started. Run: ./scripts/test.sh check"
}

# Function: cmd_env
# Description: Show environment detection information
# Returns:
#   0: Success
cmd_env() {
    echo "=== Lyra Test Environment ==="
    echo ""
    echo "Environment Detection:"
    echo "  OS Type: $(detect_env)"
    echo "  In Container: ${IN_CONTAINER:-false}"
    echo "  Container Name: ${CURRENT_CONTAINER_NAME:-N/A}"
    echo "  Is ML Container: ${IS_ML_CONTAINER:-false}"
    echo ""
    echo "Cloud Agent Detection:"
    echo "  Is Cloud Agent: ${IS_CLOUD_AGENT:-false}"
    echo "  Agent Type: ${CLOUD_AGENT_TYPE:-none}"
    echo "  E2E Capable: $(is_e2e_capable && echo "true" || echo "false")"
    echo ""
    echo "Test Configuration:"
    echo "  Test Layer: ${LYRA_TEST_LAYER:-default (unit + integration)}"
    local markers
    markers=$(get_pytest_markers 2>/dev/null)
    echo "  Markers: ${markers:-<none>}"
    echo ""
    echo "Environment Variables:"
    echo "  DISPLAY: ${DISPLAY:-<not set>}"
    echo "  CI: ${CI:-<not set>}"
    echo "  GITHUB_ACTIONS: ${GITHUB_ACTIONS:-<not set>}"
    echo "  CURSOR_CLOUD_AGENT: ${CURSOR_CLOUD_AGENT:-<not set>}"
    echo "  CURSOR_SESSION_ID: ${CURSOR_SESSION_ID:-<not set>}"
    echo "  CURSOR_BACKGROUND: ${CURSOR_BACKGROUND:-<not set>}"
    echo "  CLAUDE_CODE: ${CLAUDE_CODE:-<not set>}"
    echo ""
}

# Function: filter_node_errors
# Description: Filter out Node.js EPIPE errors from Cursor terminal
# These errors occur when the terminal pipe is closed unexpectedly
filter_node_errors() {
    grep -v -E "^(node:|Node\.js|Error: write EPIPE|    at |Emitted|  errno:|  code:|  syscall:|\{$|\}$)"
}

# Function: cmd_check
# Description: Check if tests are completed by checking:
#             1. Test result keywords (passed/failed/skipped/deselected)
#             2. File modification time (fallback: if no updates for COMPLETION_THRESHOLD seconds)
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
    local result_content

    # Read last few lines to check for test completion keywords (filter Node.js errors)
    result_content=$(tail -10 "$TEST_RESULT_FILE" 2>/dev/null | filter_node_errors || echo "")
    last_line=$(tail -1 "$TEST_RESULT_FILE" 2>/dev/null | filter_node_errors || echo "waiting...")

    # Check if test result contains pytest summary line
    # pytest output format: "==== X passed, Y failed, Z skipped, W deselected ... ===="
    # Match: equals signs + number + (passed|failed|skipped|deselected)
    if echo "$result_content" | grep -qE "={3,}.*[0-9]+ (passed|failed|skipped|deselected)"; then
        echo "DONE"
        tail -5 "$TEST_RESULT_FILE" 2>/dev/null | filter_node_errors || echo "No output"
        return 0
    fi

    # Fallback: Check file modification time
    mtime=$(stat -c %Y "$TEST_RESULT_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$((now - mtime))

    if [ "$age" -gt "$COMPLETION_THRESHOLD" ]; then
        echo "DONE (${age}s ago)"
        tail -5 "$TEST_RESULT_FILE" 2>/dev/null | filter_node_errors || echo "No output"
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

    # Filter out Node.js EPIPE errors from Cursor terminal
    tail -20 "$TEST_RESULT_FILE" 2>/dev/null | filter_node_errors || {
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
    echo "Lyra Test Runner (Cloud Agent Compatible)"
    echo ""
    echo "Usage: $0 {run|check|get|kill|env|help} [target]"
    echo ""
    echo "Commands:"
    echo "  run [target]  Start test execution (default: tests/)"
    echo "  check         Check if tests are done (DONE/RUNNING)"
    echo "  get           Get test results (last 20 lines)"
    echo "  kill          Force stop pytest process"
    echo "  env           Show environment detection info"
    echo ""
    echo "Pattern: Start with 'run', poll with 'check', get results with 'get'"
    echo ""
    echo "Test Layers:"
    echo "  L1 (Cloud Agent/CI): Unit + Integration tests only (default in cloud)"
    echo "  L2 (Local):          Unit + Integration tests (default locally)"
    echo "  L3 (E2E):            All tests including E2E"
    echo ""
    echo "Environment Variables:"
    echo "  LYRA_TEST_LAYER=e2e  Run E2E tests explicitly"
    echo "  LYRA_TEST_LAYER=all  Run all tests"
    echo "  LYRA_LOCAL=1         Force local mode (disable cloud agent detection)"
    echo ""
    echo "Cloud Agent Detection:"
    echo "  Automatically detects these cloud agent environments:"
    echo "  - Cursor Cloud Agent: CURSOR_CLOUD_AGENT, CURSOR_SESSION_ID"
    echo "  - Claude Code: CLAUDE_CODE"
    echo "  - GitHub Actions: GITHUB_ACTIONS=true"
    echo "  - GitLab CI: GITLAB_CI"
    echo "  - Generic CI: CI=true"
    echo ""
    echo "Container Detection:"
    echo "  - Automatically detects if running inside container"
    echo "  - Container detection: /.dockerenv, /run/.containerenv, HOSTNAME"
    echo "  - In any container: ML tests (test_ml_server.py) are enabled"
    echo "  - In lyra-ml container: ML API tests (TestMLServerAPI) are enabled"
    echo ""
    echo "Container Architecture:"
    echo "  - lyra: Main container (proxy server, no ML libs)"
    echo "  - lyra-ml: ML container (FastAPI + ML libs, GPU)"
    echo "  - lyra-ollama: LLM container (Ollama, GPU) - unit tests use mocks"
    echo "  - lyra-tor: Tor proxy container - unit tests use mocks"
    echo ""
    echo "Manual Override (via .env or environment):"
    echo "  LYRA_RUN_ML_TESTS=1      Enable ML tests even without libs"
    echo "  LYRA_RUN_ML_API_TESTS=1  Enable ML API tests even without FastAPI"
    echo "  LYRA_RUN_EXTRACTOR_TESTS=1  Enable extractor tests even without libs"
    echo ""
    echo "Note: Tests run in WSL venv (.venv) by default, or in container if detected."
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
    
    env)
        cmd_env
        ;;
    
    help|--help|-h)
        show_help
        ;;

    *)
        echo "Usage: $0 {run|check|get|kill|env|help} [target]"
        exit 1
        ;;
esac
