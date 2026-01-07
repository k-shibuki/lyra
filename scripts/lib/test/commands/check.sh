#!/bin/bash
# Test Check Command Handler
#
# Function for handling test.sh check command.
#
# Reliable Completion Detection (done/exit marker based):
#   Priority order:
#     1. done_file exists -> DONE (read exit_file for exit code)
#     2. cancelled_file exists -> CANCELLED (killed by user)
#     3. fatal error pattern in output -> FATAL_ERROR
#     4. runner PID alive -> RUNNING (continue polling)
#     5. runner PID dead + no done marker -> CRASHED
#     6. timeout reached -> TIMEOUT
#
# This design eliminates reliance on PID detection or pytest output parsing
# as the PRIMARY completion signal, making it reliable across:
#   - venv vs container runtimes
#   - direct pytest vs uv wrapper execution

# Function: cmd_check
# Description: Wait until tests are completed and print a concise result tail
# Arguments:
#   $1: run_id (optional, uses state file if not provided)
#   RUNTIME_MODE: Override runtime detection (container/venv)
# Returns:
#   0:  Tests completed (all passed / skipped / deselected)
#   20: EXIT_TEST_FAILED - One or more tests failed
#   21: EXIT_TEST_ERROR - Test execution error
#   22: EXIT_TEST_TIMEOUT - Test timeout
#   23: EXIT_TEST_FATAL - Fatal error (disk I/O, OOM)
#   24: EXIT_TEST_CRASHED - Runner exited without done marker
#   25: EXIT_TEST_CANCELLED - Test explicitly cancelled
cmd_check() {
    local run_id="${1:-}"
    local runtime=""
    local result_file=""
    local pid_file=""
    local done_file=""
    local exit_file=""
    local cancelled_file=""
    local container_name=""

    # ==========================================================================
    # STEP 1: Load run information (prefer manifest, fall back to legacy state)
    # ==========================================================================
    
    if [[ -n "$run_id" ]]; then
        # Explicit run_id provided - try to load manifest first
        if load_run_manifest "$run_id"; then
            runtime="${LYRA_MANIFEST__RUNTIME}"
            result_file="${LYRA_MANIFEST__RESULT_FILE}"
            pid_file="${LYRA_MANIFEST__PID_FILE}"
            done_file="${LYRA_MANIFEST__DONE_FILE}"
            exit_file="${LYRA_MANIFEST__EXIT_FILE}"
            container_name="${LYRA_MANIFEST__CONTAINER_NAME:-}"
        elif load_test_state && [[ "${LYRA_TEST__RUN_ID:-}" == "$run_id" ]]; then
            # Fall back to legacy state if manifest not found but state matches
            runtime="${LYRA_TEST__RUNTIME}"
            result_file="${LYRA_TEST__RESULT_FILE}"
            pid_file="${LYRA_TEST__PID_FILE}"
            done_file=$(get_done_file "$run_id")
            exit_file=$(get_exit_file "$run_id")
            container_name="${LYRA_TEST__CONTAINER_NAME:-}"
        else
            # Neither manifest nor matching state - construct paths manually
            if [[ "$RUNTIME_MODE" == "container" ]]; then
                runtime="container"
            else
                runtime="venv"
            fi
            result_file=$(get_result_file "$run_id")
            pid_file=$(get_pid_file "$run_id")
            done_file=$(get_done_file "$run_id")
            exit_file=$(get_exit_file "$run_id")
        fi
        cancelled_file=$(get_cancelled_file "$run_id")
    else
        # No run_id - load from state file (legacy behavior)
        if ! load_test_state; then
            echo "NOT_STARTED"
            log_error "No test state found. Run 'make test' first."
            return 1
        fi
        run_id="${LYRA_TEST__RUN_ID:-}"
        runtime="${LYRA_TEST__RUNTIME}"
        result_file="${LYRA_TEST__RESULT_FILE}"
        pid_file="${LYRA_TEST__PID_FILE}"
        done_file=$(get_done_file "$run_id")
        exit_file=$(get_exit_file "$run_id")
        cancelled_file=$(get_cancelled_file "$run_id")
        container_name="${LYRA_TEST__CONTAINER_NAME:-}"
    fi

    # Update CONTAINER_NAME_SELECTED for runtime_* functions
    if [[ -n "$container_name" ]]; then
        # shellcheck disable=SC2034
        export CONTAINER_NAME_SELECTED="$container_name"
    fi

    if [[ -z "$result_file" ]] || [[ -z "$pid_file" ]]; then
        echo "NOT_STARTED"
        log_error "Invalid run_id or test state."
        return 1
    fi

    local start_ts
    start_ts=$(date +%s)

    # ==========================================================================
    # STEP 2: Polling loop with done/exit marker priority
    # ==========================================================================
    
    while true; do
        # ------------------------------------------------------------------
        # CONDITION 0: Check for cancelled marker (host-side, always accessible)
        # ------------------------------------------------------------------
        if [[ -f "$cancelled_file" ]]; then
            output_cancelled "$run_id" "$runtime" "$result_file"
            return "$EXIT_TEST_CANCELLED"
        fi

        # ------------------------------------------------------------------
        # CONDITION 1: Check for done marker (PRIMARY completion signal)
        # ------------------------------------------------------------------
        if runtime_file_exists "$runtime" "$done_file"; then
            local pytest_exit_code=""
            if runtime_file_exists "$runtime" "$exit_file"; then
                pytest_exit_code="$(runtime_cat "$runtime" "$exit_file" | tr -d '[:space:]')"
            fi
            output_done "$run_id" "$runtime" "$result_file" "$pytest_exit_code"
            return "$(map_pytest_exit_code "$pytest_exit_code")"
        fi

        # ------------------------------------------------------------------
        # Get result content for further checks
        # ------------------------------------------------------------------
        local result_content=""
        local last_line="waiting..."
        if runtime_file_exists "$runtime" "$result_file"; then
            result_content=$(runtime_tail "$runtime" 50 "$result_file" | filter_node_errors || echo "")
            last_line=$(runtime_tail "$runtime" 1 "$result_file" | filter_node_errors || echo "waiting...")
        fi

        # ------------------------------------------------------------------
        # CONDITION 2: Fatal error detected (e.g., disk I/O error, OOM)
        # ------------------------------------------------------------------
        local fatal_error=""
        if fatal_error=$(check_fatal_errors "$result_content"); then
            output_fatal_error "$run_id" "$runtime" "$result_file" "$fatal_error"
            return "$EXIT_TEST_FATAL"
        fi

        # ------------------------------------------------------------------
        # CONDITION 2.5: Pytest summary line detected (FALLBACK for slow done_file)
        # When pytest outputs summary but done_file hasn't been written yet
        # (e.g., playwright cleanup taking too long), treat as completed.
        # Patterns:
        #   - "X passed in Y.YYs"
        #   - "X passed, Y skipped in Z.ZZs"
        #   - "X skipped in Y.YYs" (all skipped)
        #   - "X deselected in Y.YYs" (all deselected)
        #   - "no tests ran in Y.YYs"
        # ------------------------------------------------------------------
        if echo "$result_content" | grep -qE "(([0-9]+ (passed|failed|skipped|deselected|error))|no tests ran).* in [0-9]+(\.[0-9]+)?s"; then
            # Summary detected - determine exit code from output
            local has_failed="false"
            local inferred_exit_code="0"
            if echo "$result_content" | grep -qE "[0-9]+ (failed|error)"; then
                has_failed="true"
                inferred_exit_code="1"
            fi
            output_done "$run_id" "$runtime" "$result_file" "$inferred_exit_code"
            return "$(map_pytest_exit_code "$inferred_exit_code")"
        fi

        # ------------------------------------------------------------------
        # CONDITION 3: Check runner PID status (auxiliary, not primary)
        # ------------------------------------------------------------------
        local pid=""
        local pid_alive=false
        if runtime_file_exists "$runtime" "$pid_file"; then
            pid="$(runtime_cat "$runtime" "$pid_file" | tr -d '[:space:]')"
            if is_runner_process_alive "$runtime" "$pid"; then
                pid_alive=true
            fi
        fi

        # ------------------------------------------------------------------
        # CONDITION 4: PID dead + no done marker = CRASHED
        # (Runner exited unexpectedly without writing completion markers)
        # ------------------------------------------------------------------
        if [[ -n "$pid" ]] && [[ "$pid_alive" == "false" ]]; then
            # Give a brief grace period for done_file to appear (filesystem sync)
            sleep 0.5
            if runtime_file_exists "$runtime" "$done_file"; then
                # Done marker appeared - handle as normal completion
                local pytest_exit_code=""
                if runtime_file_exists "$runtime" "$exit_file"; then
                    pytest_exit_code="$(runtime_cat "$runtime" "$exit_file" | tr -d '[:space:]')"
                fi
                output_done "$run_id" "$runtime" "$result_file" "$pytest_exit_code"
                return "$(map_pytest_exit_code "$pytest_exit_code")"
            fi
            
            # No done marker after grace period - runner crashed
            output_crashed "$run_id" "$runtime" "$result_file" "$pid"
            return "$EXIT_TEST_CRASHED"
        fi

        # ------------------------------------------------------------------
        # CONDITION 5: Timeout guard
        # ------------------------------------------------------------------
        local now
        now=$(date +%s)
        if (( now - start_ts > CHECK_TIMEOUT_SECONDS )); then
            output_timeout "$run_id" "$runtime" "$result_file" "$pid" "$pid_alive"
            return "$EXIT_TEST_TIMEOUT"
        fi

        # ------------------------------------------------------------------
        # Still running - display progress and continue polling
        # ------------------------------------------------------------------
        if [[ "$pid_alive" == "true" ]]; then
            echo "RUNNING | $last_line"
        else
            # PID not detected but no done marker yet - could be starting up or detection failed
            echo "RUNNING (awaiting done marker) | $last_line"
        fi
        sleep "$CHECK_INTERVAL_SECONDS"
    done
}

# =============================================================================
# HELPER FUNCTIONS: Exit code mapping
# =============================================================================

# Function: map_pytest_exit_code
# Description: Map pytest exit code to our standardized exit codes
# Arguments:
#   $1: pytest exit code (0-5, or empty)
# Returns: Standardized exit code
map_pytest_exit_code() {
    local pytest_code="${1:-}"
    
    case "$pytest_code" in
        0)
            echo "$EXIT_SUCCESS"
            ;;
        1)
            # Tests were collected and run but some failed
            echo "$EXIT_TEST_FAILED"
            ;;
        2)
            # Test execution was interrupted by the user
            echo "$EXIT_TEST_CANCELLED"
            ;;
        3)
            # Internal error happened while executing tests
            echo "$EXIT_TEST_ERROR"
            ;;
        4)
            # pytest command line usage error
            echo "$EXIT_TEST_ERROR"
            ;;
        5)
            # No tests were collected
            echo "$EXIT_SUCCESS"  # Treat as success (e.g., marker filter excluded all)
            ;;
        "")
            # No exit code available - treat as error
            echo "$EXIT_TEST_ERROR"
            ;;
        *)
            # Unknown exit code - if non-zero, treat as failed
            if [[ "$pytest_code" -ne 0 ]]; then
                echo "$EXIT_TEST_FAILED"
            else
                echo "$EXIT_SUCCESS"
            fi
            ;;
    esac
}

# =============================================================================
# HELPER FUNCTIONS: Output formatters
# =============================================================================

# Function: output_done
# Description: Output DONE status with summary
output_done() {
    local run_id="$1"
    local runtime="$2"
    local result_file="$3"
    local pytest_exit_code="$4"
    
    local exit_code
    exit_code=$(map_pytest_exit_code "$pytest_exit_code")
    local has_failed="false"
    [[ "$exit_code" -ne 0 ]] && has_failed="true"
    
    local total_lines=""
    local summary_line=""
    if runtime_file_exists "$runtime" "$result_file"; then
        total_lines="$(runtime_line_count "$runtime" "$result_file")"
        summary_line=$(runtime_last_summary_line "$runtime" "$result_file" | filter_node_errors || true)
    fi
    
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        cat <<EOF
{
  "status": "done",
  "exit_code": ${exit_code},
  "pytest_exit_code": ${pytest_exit_code:-null},
  "passed": $([ "$has_failed" == "false" ] && echo "true" || echo "false"),
  "summary": "${summary_line}",
  "total_lines": ${total_lines:-0},
  "run_id": "${run_id}",
  "runtime": "${runtime}"
}
EOF
    else
        echo "DONE"
        echo "=== Summary ==="
        if [[ -n "$summary_line" ]]; then
            echo "$summary_line"
        else
            echo "(no pytest summary line found)"
        fi
        echo ""
        echo "runtime: ${runtime}  run_id: ${run_id}  exit_code: ${pytest_exit_code:-unknown}"
        output_tail "$runtime" "$result_file" "$total_lines"
    fi
}

# Function: output_crashed
# Description: Output CRASHED status (runner exited without done marker)
output_crashed() {
    local run_id="$1"
    local runtime="$2"
    local result_file="$3"
    local pid="$4"
    
    local total_lines=""
    if runtime_file_exists "$runtime" "$result_file"; then
        total_lines="$(runtime_line_count "$runtime" "$result_file")"
    fi
    
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        cat <<EOF
{
  "status": "crashed",
  "exit_code": ${EXIT_TEST_CRASHED},
  "message": "Runner process exited without writing done marker",
  "pid": "${pid}",
  "result_file": "${result_file}",
  "total_lines": ${total_lines:-0},
  "run_id": "${run_id}",
  "runtime": "${runtime}"
}
EOF
    else
        echo "CRASHED"
        echo "=== Error ==="
        echo "Runner process (PID: ${pid}) exited without writing completion marker."
        echo "This usually indicates an unexpected crash or signal."
        echo ""
        echo "runtime: ${runtime}  run_id: ${run_id}"
        output_tail "$runtime" "$result_file" "$total_lines"
    fi
}

# Function: output_cancelled
# Description: Output CANCELLED status (killed by user)
output_cancelled() {
    local run_id="$1"
    local runtime="$2"
    local result_file="$3"
    
    local total_lines=""
    if runtime_file_exists "$runtime" "$result_file"; then
        total_lines="$(runtime_line_count "$runtime" "$result_file")"
    fi
    
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        cat <<EOF
{
  "status": "cancelled",
  "exit_code": ${EXIT_TEST_CANCELLED},
  "message": "Test run was explicitly cancelled via kill command",
  "result_file": "${result_file}",
  "total_lines": ${total_lines:-0},
  "run_id": "${run_id}",
  "runtime": "${runtime}"
}
EOF
    else
        echo "CANCELLED"
        echo "=== Info ==="
        echo "Test run was explicitly cancelled via 'make test-kill'."
        echo ""
        echo "runtime: ${runtime}  run_id: ${run_id}"
        output_tail "$runtime" "$result_file" "$total_lines"
    fi
}

# Function: output_fatal_error
# Description: Output FATAL_ERROR status
output_fatal_error() {
    local run_id="$1"
    local runtime="$2"
    local result_file="$3"
    local fatal_error="$4"
    
    local total_lines=""
    if runtime_file_exists "$runtime" "$result_file"; then
        total_lines="$(runtime_line_count "$runtime" "$result_file")"
    fi
    
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        cat <<EOF
{
  "status": "fatal_error",
  "exit_code": ${EXIT_TEST_FATAL},
  "fatal_error_pattern": "${fatal_error}",
  "result_file": "${result_file}",
  "total_lines": ${total_lines:-0},
  "run_id": "${run_id}",
  "runtime": "${runtime}"
}
EOF
    else
        echo "FATAL_ERROR"
        echo "=== Fatal Error Detected ==="
        echo "Pattern matched: $fatal_error"
        echo ""
        echo "runtime: ${runtime}  run_id: ${run_id}"
        output_tail "$runtime" "$result_file" "$total_lines"
    fi
}

# Function: output_timeout
# Description: Output TIMEOUT status
output_timeout() {
    local run_id="$1"
    local runtime="$2"
    local result_file="$3"
    local pid="$4"
    local pid_alive="$5"
    
    local total_lines=""
    if runtime_file_exists "$runtime" "$result_file"; then
        total_lines="$(runtime_line_count "$runtime" "$result_file")"
    fi
    
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        cat <<EOF
{
  "status": "timeout",
  "exit_code": ${EXIT_TEST_TIMEOUT},
  "timeout_seconds": ${CHECK_TIMEOUT_SECONDS},
  "pid": "${pid:-}",
  "pid_alive": ${pid_alive},
  "result_file": "${result_file}",
  "total_lines": ${total_lines:-0},
  "run_id": "${run_id}",
  "runtime": "${runtime}"
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
        echo "runtime: ${runtime}  run_id: ${run_id}"
        output_tail "$runtime" "$result_file" "$total_lines"
    fi
}

# Function: output_tail
# Description: Output tail of result file (text mode helper)
output_tail() {
    local runtime="$1"
    local result_file="$2"
    local total_lines="$3"
    
    if [[ "$total_lines" =~ ^[0-9]+$ ]] && (( total_lines > 0 )); then
        if (( total_lines <= CHECK_TAIL_LINES )); then
            echo "=== Tail (full output: ${total_lines} lines) ==="
        else
            echo "=== Tail (last ${CHECK_TAIL_LINES}/${total_lines} lines) ==="
        fi
        runtime_tail "$runtime" "$CHECK_TAIL_LINES" "$result_file" | filter_node_errors || echo "No output"
    else
        echo "=== Tail ==="
        echo "No output"
    fi
}

# =============================================================================
# HELPER FUNCTIONS: Process detection (auxiliary, not primary)
# =============================================================================

# Function: is_runner_process_alive
# Description: Check if the runner process (wrapper subshell) is alive
#   This is more lenient than is_pytest_process_alive - it accepts any process
#   at the given PID since we're checking the wrapper subshell, not pytest directly.
# Arguments:
#   $1: runtime ("container" or "venv")
#   $2: PID to check
# Returns:
#   0: Process is alive
#   1: Process is dead or zombie
is_runner_process_alive() {
    local runtime="$1"
    local pid="$2"
    
    if [[ -z "$pid" ]]; then
        return 1
    fi
    
    local proc_state=""
    
    if [[ "$runtime" == "container" ]]; then
        proc_state=$(container_exec_sh "ps -p $pid -o stat= 2>/dev/null || true" 2>/dev/null || echo "")
    else
        proc_state=$(ps -p "$pid" -o stat= 2>/dev/null || echo "")
    fi
    
    # Trim whitespace
    proc_state="${proc_state// /}"
    
    # Check if process exists (non-empty state)
    if [[ -z "$proc_state" ]]; then
        return 1
    fi
    
    # Check if process is zombie (state starts with Z)
    if [[ "$proc_state" == Z* ]]; then
        return 1
    fi
    
    return 0
}

