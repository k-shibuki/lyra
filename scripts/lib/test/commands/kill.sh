#!/bin/bash
# Test Kill Command Handler
#
# Function for handling test.sh kill command.
#
# Writes cancelled_file marker so check.sh can detect explicit cancellation.

# Function: cmd_kill
# Description: Force stop pytest process and write cancelled marker
# Arguments:
#   $1: run_id (optional, uses state file if not provided)
#       "--all" for emergency kill of all pytest processes
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
    local done_file=""
    local exit_file=""
    local cancelled_file=""
    local container_name=""

    # ==========================================================================
    # CASE 1: Emergency kill all (--all)
    # ==========================================================================
    if [[ "$run_id" == "--all" ]]; then
        # Emergency cleanup: kill all pytest/uv and clean up zombie processes
        # Note: Use timeout to prevent hanging on unresponsive containers
        local my_pid=$$
        if is_container_running_selected; then
            # Kill active pytest/uv processes
            timeout 10 container_exec_sh "pkill -9 -f pytest 2>/dev/null || true" 2>/dev/null || true
            timeout 10 container_exec_sh "pkill -9 -f 'uv run pytest' 2>/dev/null || true" 2>/dev/null || true
            # Clean up zombie processes by killing their parent bash processes
            # Zombies can't be killed directly; we must terminate their parents
            # shellcheck disable=SC2016  # Intentional: variables expand inside container
            timeout 10 container_exec_sh '
                for ppid in $(ps -eo ppid,stat,comm | grep -E "Z.*(pytest|uv)" | awk "{print \$1}" | sort -u); do
                    # Only kill bash parents that are test wrappers (not the main shell)
                    pcomm=$(ps -p $ppid -o comm= 2>/dev/null || echo "")
                    if [[ "$pcomm" == "bash" ]]; then
                        kill -9 $ppid 2>/dev/null || true
                    fi
                done
            ' 2>/dev/null || true
            # Remove test artifacts
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

    # ==========================================================================
    # CASE 2: Kill specific run (by run_id or last run)
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
            runtime="venv"
            result_file=$(get_result_file "$run_id")
            pid_file=$(get_pid_file "$run_id")
            done_file=$(get_done_file "$run_id")
            exit_file=$(get_exit_file "$run_id")
        fi
        cancelled_file=$(get_cancelled_file "$run_id")
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
        done_file=$(get_done_file "$run_id")
        exit_file=$(get_exit_file "$run_id")
        cancelled_file=$(get_cancelled_file "$run_id")
        container_name="${LYRA_TEST__CONTAINER_NAME:-}"
    fi

    # Update CONTAINER_NAME_SELECTED for runtime functions
    if [[ -n "$container_name" ]]; then
        # shellcheck disable=SC2034
        export CONTAINER_NAME_SELECTED="$container_name"
    fi

    local killed_pid=""
    # Kill process if PID file exists and process is running
    if runtime_file_exists "$runtime" "$pid_file"; then
        local pid
        pid="$(runtime_cat "$runtime" "$pid_file" | tr -d '[:space:]')"
        if [[ -n "$pid" ]]; then
            # Use relaxed process detection (wrapper subshell, not just pytest)
            local proc_state=""
            if [[ "$runtime" == "container" ]]; then
                proc_state=$(container_exec_sh "ps -p $pid -o stat= 2>/dev/null || true" 2>/dev/null || echo "")
            else
                proc_state=$(ps -p "$pid" -o stat= 2>/dev/null || echo "")
            fi
            proc_state="${proc_state// /}"
            
            # Kill if process exists and is not zombie
            if [[ -n "$proc_state" ]] && [[ "$proc_state" != Z* ]]; then
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
    fi

    # Write cancelled marker (host-side) so check.sh knows this was explicit cancellation
    if [[ -n "$cancelled_file" ]]; then
        touch "$cancelled_file"
    fi

    # Clean up runtime-side files (result, pid, done, exit)
    if [[ "$runtime" == "container" ]]; then
        if is_container_running_selected; then
            container_exec_sh "rm -f \"$pid_file\" \"$result_file\" \"$done_file\" \"$exit_file\" 2>/dev/null || true"
        fi
    else
        rm -f "$pid_file" "$result_file" "$done_file" "$exit_file" 2>/dev/null || true
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
  "pid": "${killed_pid:-null}",
  "cancelled_file": "${cancelled_file}"
}
EOF
    else
        if [[ -n "$killed_pid" ]]; then
            echo "Killed process ${killed_pid}"
        else
            echo "No running process found"
        fi
        echo "Cancelled marker written: ${cancelled_file}"
        echo "Done"
    fi
}

