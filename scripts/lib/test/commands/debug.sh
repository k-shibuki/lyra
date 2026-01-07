#!/bin/bash
# Test Debug Command Handler
#
# Function for handling test.sh debug command.
#
# Shows detailed debug information including:
#   - Manifest information (per-run tracking)
#   - Completion markers (done_file, exit_file, cancelled_file)
#   - Process status
#   - Result file status

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
    local done_file=""
    local exit_file=""
    local cancelled_file=""
    local manifest_file=""
    local container_name=""
    local manifest_loaded="false"

    echo "=== Test Debug Information ==="
    echo ""

    # ==========================================================================
    # Load run information (prefer manifest)
    # ==========================================================================
    
    if [[ -n "$run_id" ]]; then
        manifest_file=$(get_manifest_file "$run_id")
        cancelled_file=$(get_cancelled_file "$run_id")
        
        if load_run_manifest "$run_id"; then
            manifest_loaded="true"
            runtime="${LYRA_MANIFEST__RUNTIME}"
            result_file="${LYRA_MANIFEST__RESULT_FILE}"
            pid_file="${LYRA_MANIFEST__PID_FILE}"
            done_file="${LYRA_MANIFEST__DONE_FILE}"
            exit_file="${LYRA_MANIFEST__EXIT_FILE}"
            container_name="${LYRA_MANIFEST__CONTAINER_NAME:-}"
        elif load_test_state && [[ "${LYRA_TEST__RUN_ID:-}" == "$run_id" ]]; then
            runtime="${LYRA_TEST__RUNTIME}"
            result_file="${LYRA_TEST__RESULT_FILE}"
            pid_file="${LYRA_TEST__PID_FILE}"
            done_file=$(get_done_file "$run_id")
            exit_file=$(get_exit_file "$run_id")
            container_name="${LYRA_TEST__CONTAINER_NAME:-}"
        else
            runtime="venv"
            result_file=$(get_result_file "$run_id")
            pid_file=$(get_pid_file "$run_id")
            done_file=$(get_done_file "$run_id")
            exit_file=$(get_exit_file "$run_id")
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
        done_file=$(get_done_file "$run_id")
        exit_file=$(get_exit_file "$run_id")
        cancelled_file=$(get_cancelled_file "$run_id")
        manifest_file=$(get_manifest_file "$run_id")
        container_name="${LYRA_TEST__CONTAINER_NAME:-}"
        
        # Try to load manifest for additional info
        if load_run_manifest "$run_id"; then
            manifest_loaded="true"
        fi
    fi

    # Update CONTAINER_NAME_SELECTED for runtime functions
    if [[ -n "$container_name" ]]; then
        # shellcheck disable=SC2034
        export CONTAINER_NAME_SELECTED="$container_name"
    fi

    # ==========================================================================
    # Basic Info
    # ==========================================================================
    
    echo "=== Basic Info ==="
    echo "Run ID:         ${run_id:-<none>}"
    echo "Runtime:        $runtime"
    echo "Container:      ${container_name:-<none>}"
    echo ""

    # ==========================================================================
    # Manifest Status
    # ==========================================================================
    
    echo "=== Manifest Status ==="
    echo "Manifest file:  ${manifest_file:-<unknown>}"
    if [[ -f "$manifest_file" ]]; then
        echo "Manifest:       EXISTS (loaded: ${manifest_loaded})"
        if [[ "$manifest_loaded" == "true" ]]; then
            echo "  Started at:   ${LYRA_MANIFEST__STARTED_AT:-<unknown>}"
        fi
    else
        echo "Manifest:       NOT FOUND"
    fi
    echo ""

    # ==========================================================================
    # Completion Markers (PRIMARY for status detection)
    # ==========================================================================
    
    echo "=== Completion Markers (Primary) ==="
    
    # Done file
    echo "Done file:      ${done_file:-<unknown>}"
    if runtime_file_exists "$runtime" "$done_file"; then
        echo "  Status:       EXISTS (run completed)"
    else
        echo "  Status:       NOT FOUND (run may be in progress)"
    fi
    
    # Exit file
    echo "Exit file:      ${exit_file:-<unknown>}"
    if runtime_file_exists "$runtime" "$exit_file"; then
        local exit_code
        exit_code="$(runtime_cat "$runtime" "$exit_file" | tr -d '[:space:]')"
        echo "  Status:       EXISTS"
        echo "  Exit code:    ${exit_code:-<empty>}"
    else
        echo "  Status:       NOT FOUND"
    fi
    
    # Cancelled file (host-side)
    echo "Cancelled file: ${cancelled_file:-<unknown>}"
    if [[ -f "$cancelled_file" ]]; then
        echo "  Status:       EXISTS (run was explicitly killed)"
    else
        echo "  Status:       NOT FOUND"
    fi
    echo ""

    # ==========================================================================
    # Runtime Files
    # ==========================================================================
    
    echo "=== Runtime Files ==="
    echo "Result file:    $result_file"
    if runtime_file_exists "$runtime" "$result_file"; then
        local result_lines
        result_lines=$(runtime_line_count "$runtime" "$result_file")
        echo "  Status:       EXISTS ($result_lines lines)"
    else
        echo "  Status:       NOT FOUND"
    fi

    echo "PID file:       $pid_file"
    if runtime_file_exists "$runtime" "$pid_file"; then
        echo "  Status:       EXISTS"
    else
        echo "  Status:       NOT FOUND"
    fi
    echo ""

    # ==========================================================================
    # Process Status (Auxiliary)
    # ==========================================================================
    
    echo "=== Process Status (Auxiliary) ==="
    if runtime_file_exists "$runtime" "$pid_file"; then
        local pid
        pid="$(runtime_cat "$runtime" "$pid_file" | tr -d '[:space:]')"
        echo "PID from file:  $pid"
        
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
            
            echo "Process exists: $proc_exists"
            echo "Process comm:   '${proc_comm:-<empty>}'"
            echo "Process state:  '${proc_state:-<empty>}'"
            
            # Check with legacy function for comparison
            if is_pytest_process_alive "$runtime" "$pid"; then
                echo "is_pytest_process_alive: TRUE"
            else
                echo "is_pytest_process_alive: FALSE (may be wrapper subshell, not pytest)"
            fi
        fi
    else
        echo "No PID file found"
    fi
    echo ""

    # ==========================================================================
    # Pytest Summary Detection (for display purposes)
    # ==========================================================================
    
    echo "=== Pytest Summary Detection ==="
    if runtime_file_exists "$runtime" "$result_file"; then
        local summary_line
        summary_line=$(runtime_last_summary_line "$runtime" "$result_file" | filter_node_errors || true)
        if [[ -n "$summary_line" ]]; then
            echo "Summary line:   $summary_line"
        else
            echo "Summary line:   NOT FOUND (pytest may still be running)"
        fi
        
        echo ""
        echo "=== Last 10 lines of result ==="
        runtime_tail "$runtime" 10 "$result_file" | filter_node_errors || echo "No output"
    else
        echo "Result file not found"
    fi
    echo ""

    # ==========================================================================
    # Status Summary
    # ==========================================================================
    
    echo "=== Status Summary ==="
    local status="UNKNOWN"
    
    if [[ -f "$cancelled_file" ]]; then
        status="CANCELLED"
    elif runtime_file_exists "$runtime" "$done_file"; then
        local exit_code
        if runtime_file_exists "$runtime" "$exit_file"; then
            exit_code="$(runtime_cat "$runtime" "$exit_file" | tr -d '[:space:]')"
        fi
        if [[ "$exit_code" == "0" ]]; then
            status="DONE (passed)"
        elif [[ -n "$exit_code" ]]; then
            status="DONE (exit=$exit_code)"
        else
            status="DONE (exit unknown)"
        fi
    elif runtime_file_exists "$runtime" "$pid_file"; then
        local pid
        pid="$(runtime_cat "$runtime" "$pid_file" | tr -d '[:space:]')"
        local proc_state=""
        if [[ "$runtime" == "container" ]]; then
            proc_state=$(container_exec_sh "ps -p $pid -o stat= 2>/dev/null || true" 2>/dev/null || echo "")
        else
            proc_state=$(ps -p "$pid" -o stat= 2>/dev/null || echo "")
        fi
        proc_state="${proc_state// /}"
        
        if [[ -n "$proc_state" ]] && [[ "$proc_state" != Z* ]]; then
            status="RUNNING"
        else
            status="CRASHED (pid dead, no done marker)"
        fi
    else
        status="NOT_STARTED"
    fi
    
    echo "Detected status: $status"
}

