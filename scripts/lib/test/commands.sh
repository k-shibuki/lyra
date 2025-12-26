#!/bin/bash
# Test Command Handlers
#
# Functions for handling test.sh commands (run, check, kill, debug, env, help).

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

    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "=== Cleanup ==="
    fi
    # Clean up old result files (prevents /tmp bloat)
    cleanup_old_results

    if [[ "$runtime" == "container" ]]; then
        if ! is_container_running_selected; then
            output_error "$EXIT_NOT_RUNNING" "Container '${CONTAINER_NAME_SELECTED}' is not running" \
                "container=${CONTAINER_NAME_SELECTED}" "hint=make dev-up"
        fi
    else
        ensure_venv
    fi

    if [[ ${#PYTEST_ARGS[@]} -eq 0 ]]; then
        PYTEST_ARGS=("tests/")
    fi

    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "=== Running: ${PYTEST_ARGS[*]} ==="
    fi

    # Get appropriate markers for this environment
    local markers
    markers=$(get_pytest_markers 2>/dev/null)

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

    # Container uses uv venv, prepend "uv run" to pytest command
    if [[ "$runtime" == "container" ]]; then
        pytest_cmd=("uv" "run" "${pytest_cmd[@]}")
    fi

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

    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        cat <<EOF
{
  "status": "started",
  "exit_code": ${EXIT_SUCCESS},
  "run_id": "${run_id}",
  "runtime": "${runtime}",
  "result_file": "${result_file}",
  "pid_file": "${pid_file}",
  "check_command": "make test-check RUN_ID=${run_id}",
  "markers": "${markers}"
}
EOF
    else
        echo ""
        echo "Started. To check results:"
        echo "  make test-check RUN_ID=${run_id}"
        echo ""
        echo "Artifacts:"
        echo "  run_id:      ${run_id}"
        echo "  result_file: ${result_file}"
        echo "  pid_file:    ${pid_file}"
        echo ""
        echo "Tip:"
        echo "  less -R ${result_file}"
    fi
}

# Function: cmd_env
# Description: Show environment detection information
# Returns:
#   0: Success
# Supports: --json flag for machine-readable output
cmd_env() {
    local os_type
    os_type=$(detect_env)
    local container_tool
    container_tool=$(detect_container_tool 2>/dev/null || echo "")
    local container_running
    container_running=$(is_container_running_selected && echo "true" || echo "false")
    local e2e_capable
    e2e_capable=$(is_e2e_capable && echo "true" || echo "false")
    local markers
    markers=$(get_pytest_markers 2>/dev/null || echo "")

    # Load state file info
    local last_runtime=""
    local last_result_file=""
    local last_run_id=""
    local state_file_exists="false"
    if [[ -f "$TEST_STATE_FILE" ]]; then
        state_file_exists="true"
        # shellcheck disable=SC1090
        source "$TEST_STATE_FILE"
        last_runtime="${LYRA_TEST__RUNTIME:-}"
        last_result_file="${LYRA_TEST__RESULT_FILE:-}"
        last_run_id="${LYRA_TEST__RUN_ID:-}"
    fi

    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        # JSON output for AI agents
        cat <<EOF
{
  "environment": {
    "os_type": "${os_type}",
    "in_container": ${IN_CONTAINER:-false},
    "container_name": "${CURRENT_CONTAINER_NAME:-}",
    "is_ml_container": ${IS_ML_CONTAINER:-false}
  },
  "execution": {
    "runtime_mode": "${RUNTIME_MODE}",
    "container_name_selected": "${CONTAINER_NAME_SELECTED}",
    "container_runtime_tool": "${container_tool}",
    "container_running": ${container_running}
  },
  "state": {
    "state_file_exists": ${state_file_exists},
    "last_runtime": "${last_runtime}",
    "last_result_file": "${last_result_file}",
    "last_run_id": "${last_run_id}"
  },
  "cloud_agent": {
    "is_cloud_agent": ${IS_CLOUD_AGENT:-false},
    "agent_type": "${CLOUD_AGENT_TYPE:-none}",
    "e2e_capable": ${e2e_capable}
  },
  "test_config": {
    "test_layer": "${LYRA_TEST_LAYER:-default}",
    "markers": "${markers}"
  },
  "exit_codes": {
    "EXIT_SUCCESS": ${EXIT_SUCCESS},
    "EXIT_TEST_FAILED": ${EXIT_TEST_FAILED},
    "EXIT_TEST_ERROR": ${EXIT_TEST_ERROR},
    "EXIT_TEST_TIMEOUT": ${EXIT_TEST_TIMEOUT},
    "EXIT_TEST_FATAL": ${EXIT_TEST_FATAL},
    "EXIT_NOT_RUNNING": ${EXIT_NOT_RUNNING}
  }
}
EOF
    else
        # Human-readable output
        echo "=== Lyra Test Environment ==="
        echo ""
        echo "Environment Detection:"
        echo "  OS Type: ${os_type}"
        echo "  In Container: ${IN_CONTAINER:-false}"
        echo "  Container Name: ${CURRENT_CONTAINER_NAME:-N/A}"
        echo "  Is ML Container: ${IS_ML_CONTAINER:-false}"
        echo ""
        echo "Execution Mode:"
        echo "  Requested Runtime: ${RUNTIME_MODE}"
        echo "  Selected Container Name: ${CONTAINER_NAME_SELECTED}"
        echo "  Container Runtime Tool: ${container_tool:-<none>}"
        echo "  Container Running: ${container_running}"
        if [[ "$state_file_exists" == "true" ]]; then
            echo "  State File: $TEST_STATE_FILE (present)"
            echo "  Last Runtime: ${last_runtime:-<unknown>}"
            echo "  Last Result File: ${last_result_file:-<unknown>}"
        else
            echo "  State File: $TEST_STATE_FILE (missing)"
        fi
        echo ""
        echo "Cloud Agent Detection:"
        echo "  Is Cloud Agent: ${IS_CLOUD_AGENT:-false}"
        echo "  Agent Type: ${CLOUD_AGENT_TYPE:-none}"
        echo "  E2E Capable: ${e2e_capable}"
        echo ""
        echo "Test Configuration:"
        echo "  Test Layer: ${LYRA_TEST_LAYER:-default (unit + integration)}"
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
    fi
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
            log_error "No test state found. Run 'make test' first."
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
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                local total_lines
                total_lines="$(runtime_line_count "$runtime" "$result_file")"
                cat <<EOF
{
  "status": "fatal_error",
  "exit_code": ${EXIT_TEST_FATAL},
  "fatal_error_pattern": "${fatal_error}",
  "result_file": "${result_file}",
  "total_lines": ${total_lines}
}
EOF
            else
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
            fi
            return "$EXIT_TEST_FATAL"
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
            local summary_line
            summary_line=$(runtime_last_summary_line "$runtime" "$result_file" | filter_node_errors || true)
            local total_lines
            total_lines="$(runtime_line_count "$runtime" "$result_file")"
            local has_failed="false"
            local exit_code=$EXIT_SUCCESS
            if echo "$result_content" | grep -qE "[0-9]+ failed"; then
                has_failed="true"
                exit_code=$EXIT_TEST_FAILED
            fi

            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                cat <<EOF
{
  "status": "done",
  "exit_code": ${exit_code},
  "passed": $([ "$has_failed" == "false" ] && echo "true" || echo "false"),
  "summary": "${summary_line}",
  "result_file": "${result_file}",
  "total_lines": ${total_lines},
  "run_id": "${run_id}"
}
EOF
            else
                echo "DONE"
                echo "=== Summary ==="
                echo "$summary_line"
                echo "=== Artifact ==="
                echo "result_file: ${result_file}"
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
            fi
            return "$exit_code"
        fi

        # DONE condition 2: pid file exists and pytest process is gone
        if [[ -n "$pid" ]] && [[ "$pid_alive" == "false" ]]; then
            local summary_line
            summary_line=$(runtime_last_summary_line "$runtime" "$result_file" | filter_node_errors || true)
            local total_lines
            total_lines="$(runtime_line_count "$runtime" "$result_file")"
            local has_failed="false"
            local exit_code=$EXIT_SUCCESS
            if echo "$result_content" | grep -qE "(FAILED|ERROR|[0-9]+ failed)"; then
                has_failed="true"
                exit_code=$EXIT_TEST_FAILED
            fi

            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                cat <<EOF
{
  "status": "done",
  "exit_code": ${exit_code},
  "passed": $([ "$has_failed" == "false" ] && echo "true" || echo "false"),
  "summary": "${summary_line}",
  "result_file": "${result_file}",
  "total_lines": ${total_lines},
  "run_id": "${run_id}"
}
EOF
            else
                echo "DONE"
                echo "=== Summary ==="
                echo "$summary_line"
                echo "=== Artifact ==="
                echo "result_file: ${result_file}"
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
            fi
            return "$exit_code"
        fi

        # Timeout guard
        local now
        now=$(date +%s)
        if (( now - start_ts > CHECK_TIMEOUT_SECONDS )); then
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                cat <<EOF
{
  "status": "timeout",
  "exit_code": ${EXIT_TEST_TIMEOUT},
  "timeout_seconds": ${CHECK_TIMEOUT_SECONDS},
  "pid": "${pid:-}",
  "pid_alive": ${pid_alive},
  "result_file": "${result_file}",
  "run_id": "${run_id}"
}
EOF
            else
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
            fi
            return "$EXIT_TEST_TIMEOUT"
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
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "Killing..."
    fi

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
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            cat <<EOF
{
  "status": "success",
  "exit_code": ${EXIT_SUCCESS},
  "message": "All pytest processes killed and artifacts cleaned"
}
EOF
        else
            echo "Done"
        fi
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
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                cat <<EOF
{
  "status": "success",
  "exit_code": ${EXIT_SUCCESS},
  "message": "No test state found",
  "hint": "make test-kill-all"
}
EOF
            else
                log_warn "No test state found. Use: make test-kill-all"
            fi
            return 0
        fi
        runtime="${LYRA_TEST__RUNTIME}"
        result_file="${LYRA_TEST__RESULT_FILE}"
        pid_file="${LYRA_TEST__PID_FILE}"
        run_id="${LYRA_TEST__RUN_ID:-}"
    fi

    local killed_pid=""
    # Kill process if PID file exists and process is running
    if runtime_file_exists "$runtime" "$pid_file"; then
        local pid
        pid="$(runtime_cat "$runtime" "$pid_file" | tr -d '[:space:]')"
        if [[ -n "$pid" ]] && is_pytest_process_alive "$runtime" "$pid"; then
            killed_pid="$pid"
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

    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        local was_running="false"
        if [[ -n "$killed_pid" ]]; then
            was_running="true"
        fi
        cat <<EOF
{
  "status": "success",
  "exit_code": ${EXIT_SUCCESS},
  "message": "Test run killed",
  "run_id": "${run_id}",
  "was_running": ${was_running},
  "pid": "${killed_pid:-null}"
}
EOF
    else
        echo "Done"
    fi
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
            echo "Run 'make test' first, or provide a run_id."
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
    echo "Usage: $0 [global-options] {run|check|kill|debug|env|help} [options] [args...]"
    echo ""
    echo "Commands:"
    echo "  run [pytest_args...]      Start test execution (background)"
    echo "  check [run_id]            Wait until tests are done and print result tail"
    echo "  kill [run_id|--all]       Force stop pytest process (or emergency kill/cleanup)"
    echo "  debug [run_id]            Show detailed debug info about test run"
    echo "  env                       Show environment detection info"
    echo ""
    echo "Global Options:"
    echo "  --json        Output in JSON format (machine-readable)"
    echo "  --quiet, -q   Suppress non-essential output"
    echo ""
    echo "Recommended Pattern:"
    echo "  make test"
    echo "  make test-check RUN_ID=<run_id>"
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
    echo ""
    echo "Exit Codes (standardized for AI agents):"
    echo "  0   (EXIT_SUCCESS)      All tests passed"
    echo "  20  (EXIT_TEST_FAILED)  One or more tests failed"
    echo "  21  (EXIT_TEST_ERROR)   Test execution error"
    echo "  22  (EXIT_TEST_TIMEOUT) Test timeout"
    echo "  23  (EXIT_TEST_FATAL)   Fatal error (disk I/O, OOM)"
    echo "  12  (EXIT_NOT_RUNNING)  Container not running"
}
