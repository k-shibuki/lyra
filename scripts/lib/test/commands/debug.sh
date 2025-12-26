#!/bin/bash
# Test Debug Command Handler
#
# Function for handling test.sh debug command.

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

