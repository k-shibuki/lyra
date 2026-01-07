#!/bin/bash
# Test Run Command Handler
#
# Function for handling test.sh run command.
#
# Reliable Completion Detection:
#   - Wraps pytest in a subshell that writes exit_file and done_file on completion
#   - The wrapper subshell PID is saved to pid_file
#   - check.sh uses done_file as primary completion signal (not PID detection)

cmd_run() {
    local runtime
    runtime="$(resolve_runtime)"

    # Generate unique run ID and file paths
    local run_id
    run_id=$(generate_run_id)
    mkdir -p "$TEST_RESULT_DIR"

    local result_file pid_file done_file exit_file
    result_file=$(get_result_file "$run_id")
    pid_file=$(get_pid_file "$run_id")
    done_file=$(get_done_file "$run_id")
    exit_file=$(get_exit_file "$run_id")

    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "=== Cleanup ==="
    fi
    # Clean up old result files (prevents /tmp bloat)
    cleanup_old_results

    if [[ "$runtime" == "container" ]]; then
        if ! is_container_running_selected; then
            output_error "$EXIT_NOT_RUNNING" "Container '${CONTAINER_NAME_SELECTED}' is not running" \
                "container=${CONTAINER_NAME_SELECTED}" "hint=make up"
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
    # Skip if PYTEST_ARGS already contains -m (user-specified marker expression)
    local has_marker_arg=false
    for arg in "${PYTEST_ARGS[@]}"; do
        if [[ "$arg" == "-m" ]]; then
            has_marker_arg=true
            break
        fi
    done

    local markers=""
    if [[ "$has_marker_arg" == "false" ]]; then
        markers=$(get_pytest_markers 2>/dev/null)
    fi

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

    # Container tool for manifest (empty for venv)
    local container_tool=""
    local container_name=""

    if [[ "$runtime" == "container" ]]; then
        container_tool="$(detect_container_tool)"
        container_name="$CONTAINER_NAME_SELECTED"
        
        local escaped
        escaped="$(printf "%q " "${pytest_cmd[@]}")"
        local export_env=""
        export_env+="export IS_CLOUD_AGENT=$(printf "%q" "${IS_CLOUD_AGENT}") ; "
        export_env+="export CLOUD_AGENT_TYPE=$(printf "%q" "${CLOUD_AGENT_TYPE}") ; "
        export_env+="export PYTHONPATH=/app:\\${PYTHONPATH:-} ; "
        
        # Wrapper subshell: run pytest, then write exit code and done marker
        # The subshell PID is saved to pid_file
        # On completion (success or failure), exit_file and done_file are created
        # shellcheck disable=SC2016  # Intentional: $_exit_code expands inside container
        container_exec_sh 'mkdir -p "'"$TEST_RESULT_DIR"'" && cd /app && ( '"${export_env}"' PYTHONUNBUFFERED=1 '"${escaped}"' > "'"$result_file"'" 2>&1 ; _exit_code=$? ; echo $_exit_code > "'"$exit_file"'".tmp && mv "'"$exit_file"'".tmp "'"$exit_file"'" ; touch "'"$done_file"'" ) & echo $! > "'"$pid_file"'"'
        
        # Write both legacy state (for backward compat) and new manifest
        write_test_state "container" "$container_tool" "$container_name" "$result_file" "$pid_file" "$run_id"
        write_run_manifest "$run_id" "container" "$container_tool" "$container_name" "$result_file" "$pid_file" "$done_file" "$exit_file"
    else
        # Venv execution with wrapper subshell for done/exit markers
        (
            # shellcheck source=/dev/null
            source "${VENV_DIR}/bin/activate"
            cd "${PROJECT_DIR}" || exit 1
            export PYTHONPATH="${PROJECT_DIR}:${PYTHONPATH:-}"

            # Export container detection flags (local default: off unless explicitly enabled)
            export LYRA_RUN_ML_TESTS="${LYRA_RUN_ML_TESTS:-0}"
            export LYRA_RUN_ML_API_TESTS="${LYRA_RUN_ML_API_TESTS:-0}"
            export LYRA_RUN_EXTRACTOR_TESTS="${LYRA_RUN_EXTRACTOR_TESTS:-0}"

            # Wrapper subshell: run pytest, then write exit code and done marker
            (
                PYTHONUNBUFFERED=1 "${pytest_cmd[@]}" >"$result_file" 2>&1
                _exit_code=$?
                # Atomic write: tmp -> mv
                echo "$_exit_code" >"${exit_file}.tmp" && mv "${exit_file}.tmp" "$exit_file"
                touch "$done_file"
            ) &
            echo $! >"$pid_file"
        )
        
        # Write both legacy state (for backward compat) and new manifest
        write_test_state "venv" "" "" "$result_file" "$pid_file" "$run_id"
        write_run_manifest "$run_id" "venv" "" "" "$result_file" "$pid_file" "$done_file" "$exit_file"
    fi

    local manifest_file
    manifest_file=$(get_manifest_file "$run_id")
    
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        cat <<EOF
{
  "status": "started",
  "exit_code": ${EXIT_SUCCESS},
  "run_id": "${run_id}",
  "runtime": "${runtime}",
  "result_file": "${result_file}",
  "pid_file": "${pid_file}",
  "done_file": "${done_file}",
  "exit_file": "${exit_file}",
  "manifest_file": "${manifest_file}",
  "check_command": "make test-check RUN_ID=${run_id}",
  "markers": "${markers}",
  "container_name": "${container_name}"
}
EOF
    else
        echo ""
        echo "Started. To check results:"
        echo "  make test-check RUN_ID=${run_id}"
        echo ""
        echo "Artifacts:"
        echo "  run_id:       ${run_id}"
        echo "  runtime:      ${runtime}"
        echo "  result_file:  ${result_file}"
        echo "  pid_file:     ${pid_file}"
        echo "  done_file:    ${done_file}"
        echo "  exit_file:    ${exit_file}"
        echo "  manifest:     ${manifest_file}"
        echo ""
        echo "Tip:"
        if [[ "$runtime" == "container" ]]; then
            echo "  ${container_tool} exec ${container_name} tail -100 ${result_file}"
        else
            echo "  less -R ${result_file}"
        fi
    fi
}

