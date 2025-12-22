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
shift || true

# Runtime selection:
#   - auto (default): container > venv
#   - container: force container execution
#   - venv: force local venv execution
RUNTIME_MODE="auto"
CONTAINER_NAME_SELECTED="${CONTAINER_NAME:-lyra}"

# State file persists the last started runtime so check/get/kill target the same env.
TEST_STATE_FILE="${LYRA_SCRIPT__TEST_STATE_FILE:-/tmp/lyra_test_state.env}"

VENV_DIR="${PROJECT_ROOT}/.venv"

# Result/PID files
VENV_TEST_RESULT_FILE="${LYRA_SCRIPT__VENV_TEST_RESULT_FILE:-${LYRA_SCRIPT__TEST_RESULT_FILE:-/tmp/lyra_test_result.txt}}"
VENV_TEST_PID_FILE="${LYRA_SCRIPT__VENV_TEST_PID_FILE:-${LYRA_SCRIPT__TEST_PID_FILE:-/tmp/lyra_test_pid}}"
CONTAINER_TEST_RESULT_FILE="${LYRA_SCRIPT__CONTAINER_TEST_RESULT_FILE:-/tmp/lyra_test_result.txt}"
CONTAINER_TEST_PID_FILE="${LYRA_SCRIPT__CONTAINER_TEST_PID_FILE:-/tmp/lyra_test_pid}"

# check() behavior
CHECK_INTERVAL_SECONDS="${LYRA_SCRIPT__CHECK_INTERVAL_SECONDS:-1}"
CHECK_TIMEOUT_SECONDS="${LYRA_SCRIPT__CHECK_TIMEOUT_SECONDS:-1800}"
CHECK_TAIL_LINES="${LYRA_SCRIPT__CHECK_TAIL_LINES:-60}"

# Collected pytest args (can be a single target or multiple args)
PYTEST_ARGS=()

# Container detection is done in common.sh (detect_container function)
# Variables available: IN_CONTAINER, CURRENT_CONTAINER_NAME, IS_ML_CONTAINER

# =============================================================================
# ARGUMENT PARSING / RUNTIME RESOLUTION
# =============================================================================

parse_common_flags() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --venv)
                RUNTIME_MODE="venv"
                shift
                ;;
            --container)
                RUNTIME_MODE="container"
                shift
                ;;
            --auto)
                RUNTIME_MODE="auto"
                shift
                ;;
            --name)
                CONTAINER_NAME_SELECTED="${2:-}"
                if [[ -z "$CONTAINER_NAME_SELECTED" ]]; then
                    log_error "--name requires a container name"
                    exit 1
                fi
                shift 2
                ;;
            --)
                shift
                break
                ;;
            *)
                break
                ;;
        esac
    done

    # The remainder are pytest args (optional)
    PYTEST_ARGS=("$@")
    if [[ ${#PYTEST_ARGS[@]} -eq 0 ]]; then
        PYTEST_ARGS=("tests/")
    fi
}

write_test_state() {
    local runtime="$1"
    local container_tool="$2"
    local container_name="$3"
    local result_file="$4"
    local pid_file="$5"

    cat >"$TEST_STATE_FILE" <<EOF
LYRA_TEST__RUNTIME=${runtime}
LYRA_TEST__CONTAINER_TOOL=${container_tool}
LYRA_TEST__CONTAINER_NAME=${container_name}
LYRA_TEST__RESULT_FILE=${result_file}
LYRA_TEST__PID_FILE=${pid_file}
EOF
}

load_test_state() {
    if [[ -f "$TEST_STATE_FILE" ]]; then
        # shellcheck disable=SC1090
        source "$TEST_STATE_FILE"
        return 0
    fi
    return 1
}

detect_container_tool() {
    get_container_runtime_cmd 2>/dev/null || true
}

is_container_running_selected() {
    check_container_running "$CONTAINER_NAME_SELECTED"
}

resolve_runtime() {
    local runtime="$RUNTIME_MODE"

    if [[ "$runtime" == "auto" ]]; then
        # If a run already happened, keep check/get/kill consistent.
        if load_test_state; then
            runtime="${LYRA_TEST__RUNTIME:-auto}"
            if [[ -n "${LYRA_TEST__CONTAINER_NAME:-}" ]]; then
                CONTAINER_NAME_SELECTED="${LYRA_TEST__CONTAINER_NAME}"
            fi
        fi
    fi

    if [[ "$runtime" == "auto" ]]; then
        # If we are already inside a container, run in-container.
        if [[ "${IN_CONTAINER:-false}" == "true" ]]; then
            echo "container"
            return 0
        fi

        # Prefer container if available and running
        if [[ -n "$(detect_container_tool)" ]] && is_container_running_selected; then
            echo "container"
            return 0
        fi

        echo "venv"
        return 0
    fi

    echo "$runtime"
}

container_exec() {
    local tool
    tool="$(detect_container_tool)"
    if [[ -z "$tool" ]]; then
        log_error "No container runtime found (podman/docker)."
        return 1
    fi
    "$tool" exec "$CONTAINER_NAME_SELECTED" "$@"
}

container_exec_sh() {
    local tool
    tool="$(detect_container_tool)"
    if [[ -z "$tool" ]]; then
        log_error "No container runtime found (podman/docker)."
        return 1
    fi
    "$tool" exec "$CONTAINER_NAME_SELECTED" bash -lc "$1"
}

runtime_result_file() {
    local runtime="$1"
    if [[ "$runtime" == "container" ]]; then
        echo "$CONTAINER_TEST_RESULT_FILE"
    else
        echo "$VENV_TEST_RESULT_FILE"
    fi
}

runtime_pid_file() {
    local runtime="$1"
    if [[ "$runtime" == "container" ]]; then
        echo "$CONTAINER_TEST_PID_FILE"
    else
        echo "$VENV_TEST_PID_FILE"
    fi
}

runtime_file_exists() {
    local runtime="$1"
    local path="$2"
    if [[ "$runtime" == "container" ]]; then
        container_exec test -f "$path" >/dev/null 2>&1
    else
        [[ -f "$path" ]]
    fi
}

runtime_tail() {
    local runtime="$1"
    local n="$2"
    local path="$3"
    if [[ "$runtime" == "container" ]]; then
        container_exec tail -n "$n" "$path" 2>/dev/null
    else
        tail -n "$n" "$path" 2>/dev/null
    fi
}

runtime_stat_mtime() {
    local runtime="$1"
    local path="$2"
    if [[ "$runtime" == "container" ]]; then
        container_exec stat -c "%Y" "$path" 2>/dev/null || echo "0"
    else
        stat -c "%Y" "$path" 2>/dev/null || echo "0"
    fi
}

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
    local runtime
    runtime="$(resolve_runtime)"

    local result_file
    local pid_file
    result_file="$(runtime_result_file "$runtime")"
    pid_file="$(runtime_pid_file "$runtime")"

    echo "=== Cleanup ==="
    if [[ "$runtime" == "container" ]]; then
        if ! is_container_running_selected; then
            log_error "Container '${CONTAINER_NAME_SELECTED}' is not running."
            log_error "Start it with: ./scripts/dev.sh up"
            exit 1
        fi
        # Best-effort cleanup inside container
        container_exec_sh "pkill -9 -f pytest 2>/dev/null || true; rm -f \"$result_file\" \"$pid_file\""
    else
        ensure_venv
        pkill -9 -f "pytest" 2>/dev/null || true
        sleep 1
        rm -f "$result_file" "$pid_file"
    fi

    echo "=== Running: ${PYTEST_ARGS[*]} ==="
    
    # Get appropriate markers for this environment
    local markers
    markers=$(get_pytest_markers)

    # Build pytest command args (no eval; allow multiple args)
    local pytest_cmd=()
    pytest_cmd+=(pytest)
    pytest_cmd+=("${PYTEST_ARGS[@]}")
    pytest_cmd+=(--tb=short -q)
    if [[ -n "$markers" ]]; then
        pytest_cmd+=(-m "$markers")
    fi

    # Export cloud agent detection for Python-side detection
    export IS_CLOUD_AGENT="${IS_CLOUD_AGENT:-false}"
    export CLOUD_AGENT_TYPE="${CLOUD_AGENT_TYPE:-none}"

    if [[ "$runtime" == "container" ]]; then
        local escaped
        escaped="$(printf "%q " "${pytest_cmd[@]}")"
        local export_env=""
        export_env+="export IS_CLOUD_AGENT=$(printf "%q" "${IS_CLOUD_AGENT}") ; "
        export_env+="export CLOUD_AGENT_TYPE=$(printf "%q" "${CLOUD_AGENT_TYPE}") ; "
        export_env+="export PYTHONPATH=/app:\\${PYTHONPATH:-} ; "
        container_exec_sh "cd /app && ${export_env} PYTHONUNBUFFERED=1 ${escaped} > \"$result_file\" 2>&1 & echo \\$! > \"$pid_file\""
        write_test_state "container" "$(detect_container_tool)" "$CONTAINER_NAME_SELECTED" "$result_file" "$pid_file"
    else
        (
            # shellcheck source=/dev/null
            source "${VENV_DIR}/bin/activate"
            cd "${PROJECT_ROOT}"
            export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

            # Export container detection flags (local default: off unless explicitly enabled)
            export LYRA_RUN_ML_TESTS="${LYRA_RUN_ML_TESTS:-0}"
            export LYRA_RUN_ML_API_TESTS="${LYRA_RUN_ML_API_TESTS:-0}"
            export LYRA_RUN_EXTRACTOR_TESTS="${LYRA_RUN_EXTRACTOR_TESTS:-0}"

            PYTHONUNBUFFERED=1 "${pytest_cmd[@]}" >"$result_file" 2>&1 &
            echo $! >"$pid_file"
        )
        write_test_state "venv" "" "" "$result_file" "$pid_file"
    fi

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
    echo "Execution Mode:"
    echo "  Requested Runtime: ${RUNTIME_MODE}"
    echo "  Selected Container Name: ${CONTAINER_NAME_SELECTED}"
    echo "  Container Runtime Tool: $(detect_container_tool || echo "<none>")"
    echo "  Container Running: $(is_container_running_selected && echo "true" || echo "false")"
    if [[ -f "$TEST_STATE_FILE" ]]; then
        echo "  State File: $TEST_STATE_FILE (present)"
        # shellcheck disable=SC1090
        source "$TEST_STATE_FILE"
        echo "  Last Runtime: ${LYRA_TEST__RUNTIME:-<unknown>}"
        echo "  Last Result File: ${LYRA_TEST__RESULT_FILE:-<unknown>}"
    else
        echo "  State File: $TEST_STATE_FILE (missing)"
    fi
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
# Description: Wait until tests are completed and print a concise result tail
# Returns:
#   0: Tests completed (all passed / skipped / deselected)
#   1: Result file not found
cmd_check() {
    local runtime
    runtime="$(resolve_runtime)"

    local result_file
    local pid_file
    result_file="$(runtime_result_file "$runtime")"
    pid_file="$(runtime_pid_file "$runtime")"

    local start_ts
    start_ts=$(date +%s)

    while true; do
        # Check if result file exists
        if ! runtime_file_exists "$runtime" "$result_file"; then
            echo "NOT_STARTED"
            log_error "Test result file not found"
            return 1
        fi

        local last_line
        local result_content
        result_content=$(runtime_tail "$runtime" 50 "$result_file" | filter_node_errors || echo "")
        last_line=$(runtime_tail "$runtime" 1 "$result_file" | filter_node_errors || echo "waiting...")

        # DONE condition 1: pytest summary line exists
        # Examples:
        #   "========== 10 passed, 1 skipped in 1.23s =========="
        #   "1 passed in 0.39s"  (quiet runs)
        if echo "$result_content" | grep -qE "([=]{3,}.*)?[0-9]+ (passed|failed|skipped|deselected)"; then
            echo "DONE"
            echo "=== Result ==="
            runtime_tail "$runtime" "$CHECK_TAIL_LINES" "$result_file" | filter_node_errors || echo "No output"
            if echo "$result_content" | grep -qE "[0-9]+ failed"; then
                return 1
            fi
            return 0
        fi

        # DONE condition 2: pid file exists and pytest process is gone
        if runtime_file_exists "$runtime" "$pid_file"; then
            local pid
            if [[ "$runtime" == "container" ]]; then
                pid="$(container_exec cat "$pid_file" 2>/dev/null || echo "")"
                if [[ -n "$pid" ]] && ! container_exec ps -p "$pid" >/dev/null 2>&1; then
                    echo "DONE"
                    echo "=== Result ==="
                    runtime_tail "$runtime" "$CHECK_TAIL_LINES" "$result_file" | filter_node_errors || echo "No output"
                    if echo "$result_content" | grep -qE "(FAILED|ERROR|[0-9]+ failed)"; then
                        return 1
                    fi
                    return 0
                fi
            else
                pid="$(cat "$pid_file" 2>/dev/null || echo "")"
                if [[ -n "$pid" ]] && ! ps -p "$pid" >/dev/null 2>&1; then
                    echo "DONE"
                    echo "=== Result ==="
                    runtime_tail "$runtime" "$CHECK_TAIL_LINES" "$result_file" | filter_node_errors || echo "No output"
                    if echo "$result_content" | grep -qE "(FAILED|ERROR|[0-9]+ failed)"; then
                        return 1
                    fi
                    return 0
                fi
            fi
        fi

        # DONE condition 3 (fallback): no output update for COMPLETION_THRESHOLD seconds
        local now
        local mtime
        now=$(date +%s)
        mtime=$(runtime_stat_mtime "$runtime" "$result_file")
        if [[ "$mtime" -gt 0 ]] && (( now - mtime > COMPLETION_THRESHOLD )); then
            echo "DONE"
            echo "=== Result ==="
            runtime_tail "$runtime" "$CHECK_TAIL_LINES" "$result_file" | filter_node_errors || echo "No output"
            if echo "$result_content" | grep -qE "(FAILED|ERROR|[0-9]+ failed)"; then
                return 1
            fi
            return 0
        fi

        # Timeout guard
        if (( now - start_ts > CHECK_TIMEOUT_SECONDS )); then
            echo "TIMEOUT"
            echo "=== Result ==="
            runtime_tail "$runtime" "$CHECK_TAIL_LINES" "$result_file" | filter_node_errors || echo "No output"
            return 1
        fi

        echo "RUNNING | $last_line"
        sleep "$CHECK_INTERVAL_SECONDS"
    done
}

# Function: cmd_kill
# Description: Force stop pytest process
# Returns:
#   0: Success
cmd_kill() {
    echo "Killing..."

    local runtime
    runtime="$(resolve_runtime)"
    local pid_file
    pid_file="$(runtime_pid_file "$runtime")"

    if [[ "$runtime" == "container" ]]; then
        container_exec_sh "pkill -9 -f pytest 2>/dev/null || true"
        if container_exec test -f "$pid_file" >/dev/null 2>&1; then
            local pid
            pid="$(container_exec cat "$pid_file" 2>/dev/null || echo "")"
            if [[ -n "$pid" ]]; then
                container_exec_sh "kill -9 $pid 2>/dev/null || true"
            fi
            container_exec_sh "rm -f \"$pid_file\""
        fi
    else
        pkill -9 -f "pytest" 2>/dev/null || true
        if [[ -f "$pid_file" ]]; then
            local pid
            pid=$(cat "$pid_file" 2>/dev/null || echo "")
            if [[ -n "$pid" ]]; then
                kill -9 "$pid" 2>/dev/null || true
            fi
            rm -f "$pid_file"
        fi
    fi
    echo "Done"
}

show_help() {
    echo "Lyra Test Runner (Cloud Agent Compatible)"
    echo ""
    echo "Usage: $0 {run|check|kill|env|help} [--container|--venv|--auto] [--name NAME] [--] [pytest_args...]"
    echo ""
    echo "Commands:"
    echo "  run [pytest_args...]  Start test execution (default: tests/)"
    echo "  check         Wait until tests are done and print result tail"
    echo "  kill          Force stop pytest process"
    echo "  env           Show environment detection info"
    echo ""
    echo "Pattern: Start with 'run', then run 'check' once (it waits until DONE)"
    echo ""
    echo "Runtime selection (default: auto=container>venv):"
    echo "  --auto        Prefer container if running, otherwise venv"
    echo "  --container   Force container execution (requires running container)"
    echo "  --venv        Force local venv execution"
    echo "  --name NAME   Override container name (default: \$CONTAINER_NAME or 'lyra')"
    echo ""
    echo "State:"
    echo "  Persists last runtime to: ${TEST_STATE_FILE}"
    echo "  So check/get/kill will target the same environment by default."
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
        parse_common_flags "$@"
        cmd_run
        ;;

    check)
        parse_common_flags "$@"
        cmd_check
        ;;

    kill)
        parse_common_flags "$@"
        cmd_kill
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
