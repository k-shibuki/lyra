#!/bin/bash
# Test Run Command Handler
#
# Function for handling test.sh run command.

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
            cd "${PROJECT_DIR}" || exit 1
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
  "markers": "${markers}",
  "container_name": "${CONTAINER_NAME_SELECTED:-}"
}
EOF
    else
        echo ""
        echo "Started. To check results:"
        echo "  make test-check RUN_ID=${run_id}"
        echo ""
        echo "Artifacts:"
        echo "  run_id:      ${run_id}"
        echo "  runtime:     ${runtime}"
        echo "  result_file: ${result_file}"
        echo "  pid_file:    ${pid_file}"
        echo ""
        echo "Tip:"
        if [[ "$runtime" == "container" ]]; then
            local tool
            tool=$(detect_container_tool)
            echo "  ${tool} exec ${CONTAINER_NAME_SELECTED} tail -100 ${result_file}"
        else
            echo "  less -R ${result_file}"
        fi
    fi
}

