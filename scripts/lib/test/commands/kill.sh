#!/bin/bash
# Test Kill Command Handler
#
# Function for handling test.sh kill command.

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
        # Note: Use timeout to prevent hanging on unresponsive containers
        local my_pid=$$
        if is_container_running_selected; then
            timeout 10 container_exec_sh "pkill -9 -f pytest 2>/dev/null || true" 2>/dev/null || true
            timeout 10 container_exec_sh "rm -rf \"$TEST_RESULT_DIR\" \"$LEGACY_RESULT_FILE\" \"$LEGACY_PID_FILE\" 2>/dev/null || true" 2>/dev/null || true
        fi
        # Kill pytest processes but exclude this script and its parent make process
        # Using pgrep to get PIDs first, then kill them individually
        local pids
        pids=$(pgrep -f "pytest" 2>/dev/null | grep -v "^${my_pid}$" || true)
        if [[ -n "$pids" ]]; then
            echo "$pids" | xargs -r kill -9 2>/dev/null || true
        fi
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

