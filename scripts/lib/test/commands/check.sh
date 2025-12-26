#!/bin/bash
# Test Check Command Handler
#
# Function for handling test.sh check command.

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

