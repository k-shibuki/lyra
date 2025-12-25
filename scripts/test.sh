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

# Note: VENV_DIR is provided by common.sh

# Result directory and file naming
# Each run creates unique files with timestamp to prevent result confusion
TEST_RESULT_DIR="${LYRA_SCRIPT__TEST_RESULT_DIR:-/tmp/lyra_test}"

# Legacy fixed paths (used only for cleanup of old runs)
LEGACY_RESULT_FILE="/tmp/lyra_test_result.txt"
LEGACY_PID_FILE="/tmp/lyra_test_pid"

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

    # The remainder are command args
    # - run: pytest args (optional; default handled in cmd_run)
    # - check/kill: run_id (optional; default handled in cmd_check/cmd_kill via state file)
    PYTEST_ARGS=("$@")
}

write_test_state() {
    local runtime="$1"
    local container_tool="$2"
    local container_name="$3"
    local result_file="$4"
    local pid_file="$5"
    local run_id="$6"

    cat >"$TEST_STATE_FILE" <<EOF
LYRA_TEST__RUNTIME=${runtime}
LYRA_TEST__CONTAINER_TOOL=${container_tool}
LYRA_TEST__CONTAINER_NAME=${container_name}
LYRA_TEST__RESULT_FILE=${result_file}
LYRA_TEST__PID_FILE=${pid_file}
LYRA_TEST__RUN_ID=${run_id}
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

generate_run_id() {
    # Generate unique run ID using timestamp and PID
    local ts
    ts=$(date +%Y%m%d_%H%M%S)
    echo "${ts}_$$"
}

get_result_file() {
    local run_id="$1"
    echo "${TEST_RESULT_DIR}/result_${run_id}.txt"
}

get_pid_file() {
    local run_id="$1"
    echo "${TEST_RESULT_DIR}/pid_${run_id}"
}

cleanup_old_results() {
    # Remove legacy fixed-path files
    rm -f "$LEGACY_RESULT_FILE" "$LEGACY_PID_FILE" 2>/dev/null || true
    
    # Remove old result files (older than 1 hour)
    if [[ -d "$TEST_RESULT_DIR" ]]; then
        find "$TEST_RESULT_DIR" -type f -mmin +60 -delete 2>/dev/null || true
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

runtime_last_summary_line() {
    local runtime="$1"
    local path="$2"
    # Must include "in X.XXs" to avoid matching collection line
    local re="[0-9]+ (passed|failed).* in [0-9]+(\.[0-9]+)?s"
    if [[ "$runtime" == "container" ]]; then
        container_exec_sh "grep -E \"$re\" \"$path\" 2>/dev/null | tail -n 1" 2>/dev/null || true
    else
        grep -E "$re" "$path" 2>/dev/null | tail -n 1 || true
    fi
}

runtime_line_count() {
    local runtime="$1"
    local path="$2"
    if [[ "$runtime" == "container" ]]; then
        container_exec_sh "wc -l \"$path\" 2>/dev/null | awk '{print \\$1}'" 2>/dev/null || echo "0"
    else
        wc -l "$path" 2>/dev/null | awk '{print $1}' || echo "0"
    fi
}

runtime_cat() {
    local runtime="$1"
    local path="$2"
    if [[ "$runtime" == "container" ]]; then
        container_exec cat "$path" 2>/dev/null
    else
        cat "$path" 2>/dev/null
    fi
}

# Function: is_pytest_process_alive
# Description: Check if the given PID is a running pytest/python process
# This prevents false positives from PID reuse or zombie processes
# Arguments:
#   $1: runtime ("container" or "venv")
#   $2: PID to check
# Returns:
#   0: Process is alive and is pytest/python
#   1: Process is dead, or is not pytest/python (PID reused)
is_pytest_process_alive() {
    local runtime="$1"
    local pid="$2"
    
    if [[ -z "$pid" ]]; then
        return 1
    fi
    
    local proc_comm=""
    local proc_state=""
    
    if [[ "$runtime" == "container" ]]; then
        # Get process command name and state
        # ps -p PID -o comm=,stat= returns: "python3 S" or empty if not exists
        proc_comm=$(container_exec_sh "ps -p $pid -o comm= 2>/dev/null || true" 2>/dev/null || echo "")
        proc_state=$(container_exec_sh "ps -p $pid -o stat= 2>/dev/null || true" 2>/dev/null || echo "")
    else
        proc_comm=$(ps -p "$pid" -o comm= 2>/dev/null || echo "")
        proc_state=$(ps -p "$pid" -o stat= 2>/dev/null || echo "")
    fi
    
    # Trim whitespace
    proc_comm="${proc_comm// /}"
    proc_state="${proc_state// /}"
    
    # Debug output
    if [[ "${DEBUG:-}" == "1" ]]; then
        log_info "[DEBUG] PID=$pid, comm='$proc_comm', stat='$proc_state'" >&2
    fi
    
    # Check if process exists
    if [[ -z "$proc_comm" ]]; then
        return 1
    fi
    
    # Check if process is zombie (state starts with Z)
    if [[ "$proc_state" == Z* ]]; then
        if [[ "${DEBUG:-}" == "1" ]]; then
            log_info "[DEBUG] Process $pid is zombie, treating as dead" >&2
        fi
        return 1
    fi
    
    # Check if process name matches pytest/python
    # pytest is typically run as python or python3
    if [[ "$proc_comm" =~ ^(python|python3|pytest|py\.test)$ ]]; then
        return 0
    fi
    
    # PID exists but is not pytest/python - likely PID reuse
    if [[ "${DEBUG:-}" == "1" ]]; then
        log_info "[DEBUG] PID $pid is '$proc_comm', not pytest/python - PID reused" >&2
    fi
    return 1
}

# =============================================================================
# TEST MARKER SELECTION
# =============================================================================

# Note: ensure_venv() is provided by common.sh

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

    # Generate unique run ID and file paths
    local run_id
    run_id=$(generate_run_id)
    mkdir -p "$TEST_RESULT_DIR"
    
    local result_file
    local pid_file
    result_file=$(get_result_file "$run_id")
    pid_file=$(get_pid_file "$run_id")

    echo "=== Cleanup ==="
    # Clean up old result files (prevents /tmp bloat)
    cleanup_old_results
    
    if [[ "$runtime" == "container" ]]; then
        if ! is_container_running_selected; then
            log_error "Container '${CONTAINER_NAME_SELECTED}' is not running."
            log_error "Start it with: ./scripts/dev.sh up"
            exit 1
        fi
    else
        ensure_venv
    fi

    if [[ ${#PYTEST_ARGS[@]} -eq 0 ]]; then
        PYTEST_ARGS=("tests/")
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
        # Note: Use single quotes around '$!' to prevent host-side expansion
        container_exec_sh 'mkdir -p "'"$TEST_RESULT_DIR"'" && cd /app && '"${export_env}"' PYTHONUNBUFFERED=1 '"${escaped}"' > "'"$result_file"'" 2>&1 & echo $! > "'"$pid_file"'"'
        write_test_state "container" "$(detect_container_tool)" "$CONTAINER_NAME_SELECTED" "$result_file" "$pid_file" "$run_id"
    else
        (
            # shellcheck source=/dev/null
            source "${VENV_DIR}/bin/activate"
            cd "${PROJECT_DIR}"
            export PYTHONPATH="${PROJECT_DIR}:${PYTHONPATH:-}"

            # Export container detection flags (local default: off unless explicitly enabled)
            export LYRA_RUN_ML_TESTS="${LYRA_RUN_ML_TESTS:-0}"
            export LYRA_RUN_ML_API_TESTS="${LYRA_RUN_ML_API_TESTS:-0}"
            export LYRA_RUN_EXTRACTOR_TESTS="${LYRA_RUN_EXTRACTOR_TESTS:-0}"

            PYTHONUNBUFFERED=1 "${pytest_cmd[@]}" >"$result_file" 2>&1 &
            echo $! >"$pid_file"
        )
        write_test_state "venv" "" "" "$result_file" "$pid_file" "$run_id"
    fi

    echo ""
    echo "Started. To check results:"
    echo "  ./scripts/test.sh check ${run_id}"
    echo ""
    echo "Artifacts:"
    echo "  run_id:      ${run_id}"
    echo "  result_file: ${result_file}"
    echo "  pid_file:    ${pid_file}"
    echo ""
    echo "Tip:"
    echo "  less -R ${result_file}"
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

# Fatal error patterns that indicate test run should terminate immediately
# These errors typically crash pytest without producing a summary line
FATAL_ERROR_PATTERNS=(
    "sqlite3.OperationalError: disk I/O error"
    "sqlite3.OperationalError: database disk image is malformed"
    "MemoryError"
    "Segmentation fault"
    "SIGKILL"
    "killed"
    "out of memory"
    "OSError: \\[Errno 28\\] No space left on device"
)

# Function: check_fatal_errors
# Description: Check if result file contains fatal error patterns
# Arguments:
#   $1: result content (last N lines)
# Returns:
#   0: Fatal error found
#   1: No fatal error found
# Output: Prints the matched error pattern if found
check_fatal_errors() {
    local content="$1"
    for pattern in "${FATAL_ERROR_PATTERNS[@]}"; do
        if echo "$content" | grep -qE "$pattern"; then
            echo "$pattern"
            return 0
        fi
    done
    return 1
}

# Function: cmd_check
# Description: Wait until tests are completed and print a concise result tail
# Arguments:
#   $1: run_id (optional, uses state file if not provided)
# Returns:
#   0: Tests completed (all passed / skipped / deselected)
#   1: Result file not found or no active test run
cmd_check() {
    local run_id="${1:-}"
    local runtime=""
    local result_file=""
    local pid_file=""

    if [[ -n "$run_id" ]]; then
        # Explicit run_id provided.
        # If it matches the last run in state, use the state (supports container runtime).
        # Otherwise, fall back to venv-local file paths for that run_id.
        if load_test_state && [[ "${LYRA_TEST__RUN_ID:-}" == "$run_id" ]]; then
            runtime="${LYRA_TEST__RUNTIME}"
            result_file="${LYRA_TEST__RESULT_FILE}"
            pid_file="${LYRA_TEST__PID_FILE}"
        else
            runtime="venv"
            result_file=$(get_result_file "$run_id")
            pid_file=$(get_pid_file "$run_id")
        fi
    else
        # No run_id - load from state file (legacy behavior)
        if ! load_test_state; then
            echo "NOT_STARTED"
            log_error "No test state found. Run './scripts/test.sh run' first."
            return 1
        fi
        runtime="${LYRA_TEST__RUNTIME}"
        result_file="${LYRA_TEST__RESULT_FILE}"
        pid_file="${LYRA_TEST__PID_FILE}"
        run_id="${LYRA_TEST__RUN_ID:-}"
    fi

    if [[ -z "$result_file" ]] || [[ -z "$pid_file" ]]; then
        echo "NOT_STARTED"
        log_error "Invalid run_id or test state."
        return 1
    fi

    local start_ts
    start_ts=$(date +%s)
    local last_printed_line=""
    local last_print_ts=0

    while true; do
        # Check if result file exists
        if ! runtime_file_exists "$runtime" "$result_file"; then
            echo "NOT_STARTED"
            log_error "Test result file not found"
            return 1
        fi

        # Determine whether pytest is still running (if pid file is present).
        # Use is_pytest_process_alive() for robust detection:
        # - Checks PID exists AND is a python/pytest process (not PID reuse)
        # - Detects zombie processes (treats as dead)
        local pid=""
        local pid_alive=false
        if runtime_file_exists "$runtime" "$pid_file"; then
            pid="$(runtime_cat "$runtime" "$pid_file" | tr -d '[:space:]')"
            if is_pytest_process_alive "$runtime" "$pid"; then
                pid_alive=true
            fi
        fi

        local last_line
        local result_content
        result_content=$(runtime_tail "$runtime" 50 "$result_file" | filter_node_errors || echo "")
        last_line=$(runtime_tail "$runtime" 1 "$result_file" | filter_node_errors || echo "waiting...")

        # DONE condition 0: Fatal error detected (e.g., disk I/O error, OOM)
        # Check this first to fail fast on catastrophic errors
        local fatal_error=""
        if fatal_error=$(check_fatal_errors "$result_content"); then
            echo "FATAL_ERROR"
            echo "=== Fatal Error Detected ==="
            echo "Pattern matched: $fatal_error"
            echo ""
            echo "=== Artifact ==="
            echo "result_file: ${result_file}"
            local total_lines
            total_lines="$(runtime_line_count "$runtime" "$result_file")"
            if [[ "$total_lines" =~ ^[0-9]+$ ]] && (( total_lines > 0 )); then
                if (( total_lines <= CHECK_TAIL_LINES )); then
                    echo "=== Tail (full output: ${total_lines} lines) ==="
                else
                    echo "=== Tail (last ${CHECK_TAIL_LINES}/${total_lines} lines) ==="
                fi
            else
                echo "=== Tail ==="
            fi
            runtime_tail "$runtime" "$CHECK_TAIL_LINES" "$result_file" | filter_node_errors || echo "No output"
            return 1
        fi

        # DONE condition 1: pytest summary line exists
        # Check this BEFORE pid_alive to handle cases where pytest outputs summary
        # but is still in teardown/cleanup (process alive but test results are final)
        # Examples:
        #   "========== 10 passed, 1 skipped in 1.23s =========="
        #   "1 passed in 0.39s"  (quiet runs)
        # Note: Must include "in X.XXs" to avoid matching collection line like:
        #   "collected 3377 items / 23 deselected / 3354 selected"
        if echo "$result_content" | grep -qE "[0-9]+ (passed|failed).* in [0-9]+(\.[0-9]+)?s"; then
            echo "DONE"
            echo "=== Summary ==="
            runtime_last_summary_line "$runtime" "$result_file" | filter_node_errors || true
            echo "=== Artifact ==="
            echo "result_file: ${result_file}"
            local total_lines
            total_lines="$(runtime_line_count "$runtime" "$result_file")"
            if [[ "$total_lines" =~ ^[0-9]+$ ]] && (( total_lines > 0 )); then
                if (( total_lines <= CHECK_TAIL_LINES )); then
                    echo "=== Tail (full output: ${total_lines} lines) ==="
                else
                    echo "=== Tail (last ${CHECK_TAIL_LINES}/${total_lines} lines) ==="
                fi
            else
                echo "=== Tail ==="
            fi
            runtime_tail "$runtime" "$CHECK_TAIL_LINES" "$result_file" | filter_node_errors || echo "No output"
            if echo "$result_content" | grep -qE "[0-9]+ failed"; then
                return 1
            fi
            return 0
        fi

        # DONE condition 2: pid file exists and pytest process is gone
        if [[ -n "$pid" ]] && [[ "$pid_alive" == "false" ]]; then
            echo "DONE"
            echo "=== Summary ==="
            runtime_last_summary_line "$runtime" "$result_file" | filter_node_errors || true
            echo "=== Artifact ==="
            echo "result_file: ${result_file}"
            local total_lines
            total_lines="$(runtime_line_count "$runtime" "$result_file")"
            if [[ "$total_lines" =~ ^[0-9]+$ ]] && (( total_lines > 0 )); then
                if (( total_lines <= CHECK_TAIL_LINES )); then
                    echo "=== Tail (full output: ${total_lines} lines) ==="
                else
                    echo "=== Tail (last ${CHECK_TAIL_LINES}/${total_lines} lines) ==="
                fi
            else
                echo "=== Tail ==="
            fi
            runtime_tail "$runtime" "$CHECK_TAIL_LINES" "$result_file" | filter_node_errors || echo "No output"
            if echo "$result_content" | grep -qE "(FAILED|ERROR|[0-9]+ failed)"; then
                return 1
            fi
            return 0
        fi

        # Timeout guard
        local now
        now=$(date +%s)
        if (( now - start_ts > CHECK_TIMEOUT_SECONDS )); then
            echo "TIMEOUT (after ${CHECK_TIMEOUT_SECONDS}s)"
            echo ""
            echo "=== Debug Info ==="
            echo "PID: ${pid:-<none>}"
            echo "PID alive: ${pid_alive}"
            if [[ -n "$pid" ]]; then
                local proc_comm proc_state
                if [[ "$runtime" == "container" ]]; then
                    proc_comm=$(container_exec_sh "ps -p $pid -o comm= 2>/dev/null || true" 2>/dev/null || echo "")
                    proc_state=$(container_exec_sh "ps -p $pid -o stat= 2>/dev/null || true" 2>/dev/null || echo "")
                else
                    proc_comm=$(ps -p "$pid" -o comm= 2>/dev/null || echo "")
                    proc_state=$(ps -p "$pid" -o stat= 2>/dev/null || echo "")
                fi
                echo "Process comm: '${proc_comm:-<empty>}'"
                echo "Process state: '${proc_state:-<empty>}'"
            fi
            echo ""
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
# Arguments:
#   $1: run_id (optional, uses state file if not provided)
# Returns:
#   0: Success
cmd_kill() {
    echo "Killing..."

    local run_id="${1:-}"
    local runtime=""
    local result_file=""
    local pid_file=""

    if [[ "$run_id" == "--all" ]]; then
        # Emergency cleanup: kill all pytest and remove all test artifacts
        if is_container_running_selected; then
            container_exec_sh "pkill -9 -f pytest 2>/dev/null || true"
            container_exec_sh "rm -rf \"$TEST_RESULT_DIR\" \"$LEGACY_RESULT_FILE\" \"$LEGACY_PID_FILE\" 2>/dev/null || true"
        fi
        pkill -9 -f "pytest" 2>/dev/null || true
        rm -rf "$TEST_RESULT_DIR" "$LEGACY_RESULT_FILE" "$LEGACY_PID_FILE" "$TEST_STATE_FILE" 2>/dev/null || true
        echo "Done"
        return 0
    fi

    if [[ -n "$run_id" ]]; then
        # Explicit run_id provided.
        # If it matches the last run in state, use the state (supports container runtime).
        # Otherwise, fall back to venv-local file paths for that run_id.
        if load_test_state && [[ "${LYRA_TEST__RUN_ID:-}" == "$run_id" ]]; then
            runtime="${LYRA_TEST__RUNTIME}"
            result_file="${LYRA_TEST__RESULT_FILE}"
            pid_file="${LYRA_TEST__PID_FILE}"
        else
            runtime="venv"
            result_file=$(get_result_file "$run_id")
            pid_file=$(get_pid_file "$run_id")
        fi
    else
        # No run_id - load from state file
        if ! load_test_state; then
            log_warn "No test state found. Use: ./scripts/test.sh kill --all"
            return 0
        fi
        runtime="${LYRA_TEST__RUNTIME}"
        result_file="${LYRA_TEST__RESULT_FILE}"
        pid_file="${LYRA_TEST__PID_FILE}"
        run_id="${LYRA_TEST__RUN_ID:-}"
    fi

    # Kill process if PID file exists and process is running
    if runtime_file_exists "$runtime" "$pid_file"; then
        local pid
        pid="$(runtime_cat "$runtime" "$pid_file" | tr -d '[:space:]')"
        if [[ -n "$pid" ]] && is_pytest_process_alive "$runtime" "$pid"; then
            if [[ "$runtime" == "container" ]]; then
                container_exec_sh "kill -TERM $pid 2>/dev/null || true"
                sleep 1
                container_exec_sh "kill -KILL $pid 2>/dev/null || true"
            else
                kill -TERM "$pid" 2>/dev/null || true
                sleep 1
                kill -KILL "$pid" 2>/dev/null || true
            fi
        fi
    fi
    
    # Clean up files
    if [[ "$runtime" == "container" ]]; then
        if is_container_running_selected; then
            container_exec_sh "rm -f \"$pid_file\" \"$result_file\" 2>/dev/null || true"
        fi
    else
        rm -f "$pid_file" "$result_file" 2>/dev/null || true
    fi

    # If we killed the last run, clear the state file as well
    if [[ -n "$run_id" ]] && load_test_state && [[ "${LYRA_TEST__RUN_ID:-}" == "$run_id" ]]; then
        rm -f "$TEST_STATE_FILE" 2>/dev/null || true
    fi
    cleanup_old_results
    echo "Done"
}

# Function: cmd_debug
# Description: Show detailed debug information about current test run
# Arguments:
#   $1: run_id (optional, uses state file if not provided)
# Returns:
#   0: Success
cmd_debug() {
    local run_id="${1:-}"
    local runtime=""
    local result_file=""
    local pid_file=""

    echo "=== Test Debug Information ==="
    echo ""

    if [[ -n "$run_id" ]]; then
        if load_test_state && [[ "${LYRA_TEST__RUN_ID:-}" == "$run_id" ]]; then
            runtime="${LYRA_TEST__RUNTIME}"
            result_file="${LYRA_TEST__RESULT_FILE}"
            pid_file="${LYRA_TEST__PID_FILE}"
        else
            runtime="venv"
            result_file=$(get_result_file "$run_id")
            pid_file=$(get_pid_file "$run_id")
        fi
    else
        if ! load_test_state; then
            echo "No test state found."
            echo "Run './scripts/test.sh run' first, or provide a run_id."
            return 1
        fi
        runtime="${LYRA_TEST__RUNTIME}"
        result_file="${LYRA_TEST__RESULT_FILE}"
        pid_file="${LYRA_TEST__PID_FILE}"
        run_id="${LYRA_TEST__RUN_ID:-}"
    fi

    echo "Run ID: ${run_id:-<none>}"
    echo "Runtime: $runtime"
    echo "Result File: $result_file"
    echo "PID File: $pid_file"
    echo ""

    # Check file existence
    echo "=== File Status ==="
    if runtime_file_exists "$runtime" "$result_file"; then
        local result_lines
        result_lines=$(runtime_line_count "$runtime" "$result_file")
        echo "Result file: EXISTS ($result_lines lines)"
    else
        echo "Result file: NOT FOUND"
    fi

    if runtime_file_exists "$runtime" "$pid_file"; then
        echo "PID file: EXISTS"
    else
        echo "PID file: NOT FOUND"
    fi
    echo ""

    # Check PID status
    echo "=== Process Status ==="
    if runtime_file_exists "$runtime" "$pid_file"; then
        local pid
        pid="$(runtime_cat "$runtime" "$pid_file" | tr -d '[:space:]')"
        echo "PID from file: $pid"
        
        if [[ -n "$pid" ]]; then
            local proc_comm=""
            local proc_state=""
            local proc_exists="false"
            
            if [[ "$runtime" == "container" ]]; then
                proc_comm=$(container_exec_sh "ps -p $pid -o comm= 2>/dev/null || true" 2>/dev/null || echo "")
                proc_state=$(container_exec_sh "ps -p $pid -o stat= 2>/dev/null || true" 2>/dev/null || echo "")
                if container_exec ps -p "$pid" >/dev/null 2>&1; then
                    proc_exists="true"
                fi
            else
                proc_comm=$(ps -p "$pid" -o comm= 2>/dev/null || echo "")
                proc_state=$(ps -p "$pid" -o stat= 2>/dev/null || echo "")
                if ps -p "$pid" >/dev/null 2>&1; then
                    proc_exists="true"
                fi
            fi
            
            echo "Process exists (ps -p): $proc_exists"
            echo "Process command: '${proc_comm:-<empty>}'"
            echo "Process state: '${proc_state:-<empty>}'"
            
            if is_pytest_process_alive "$runtime" "$pid"; then
                echo "is_pytest_process_alive: TRUE (pytest is running)"
            else
                echo "is_pytest_process_alive: FALSE (not pytest or dead)"
            fi
        fi
    else
        echo "No PID file found"
    fi
    echo ""

    # Check pytest summary
    echo "=== Pytest Summary Detection ==="
    if runtime_file_exists "$runtime" "$result_file"; then
        local summary_line
        summary_line=$(runtime_last_summary_line "$runtime" "$result_file" | filter_node_errors || true)
        if [[ -n "$summary_line" ]]; then
            echo "Summary line found: $summary_line"
        else
            echo "Summary line: NOT FOUND (pytest may still be running)"
        fi
        
        echo ""
        echo "=== Last 10 lines of result ==="
        runtime_tail "$runtime" 10 "$result_file" | filter_node_errors || echo "No output"
    else
        echo "Result file not found"
    fi
}

show_help() {
    echo "Lyra Test Runner (Cloud Agent Compatible)"
    echo ""
    echo "Usage: $0 {run|check|kill|debug|env|help} [options] [args...]"
    echo ""
    echo "Commands:"
    echo "  run [pytest_args...]    Start test execution (default: tests/)"
    echo "  check [run_id]          Wait until tests are done and print result tail"
    echo "  kill [run_id|--all]     Force stop pytest process (or emergency kill/cleanup)"
    echo "  debug [run_id]          Show detailed debug info about test run"
    echo "  env                     Show environment detection info"
    echo ""
    echo "Pattern:"
    echo "  ./scripts/test.sh run tests/"
    echo "  # Output shows: ./scripts/test.sh check <run_id>"
    echo "  ./scripts/test.sh check <run_id>   # Use the displayed run_id"
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
