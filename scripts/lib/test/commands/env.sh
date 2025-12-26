#!/bin/bash
# Test Environment Command Handler
#
# Function for handling test.sh env command.

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

