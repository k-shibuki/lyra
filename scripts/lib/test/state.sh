#!/bin/bash
# Test State Management Functions
#
# Functions for managing test run state files and IDs.

# Function: write_test_state
# Description: Write test run state to file
# Arguments:
#   $1: runtime (venv/container)
#   $2: container_tool (podman/docker)
#   $3: container_name
#   $4: result_file path
#   $5: pid_file path
#   $6: run_id
write_test_state() {
    local runtime="$1"
    local container_tool="$2"
    local container_name="$3"
    local result_file="$4"
    local pid_file="$5"
    local run_id="$6"

    cat >"$TEST_STATE_FILE" <<EOF
LYRA_TEST__RUNTIME=${runtime}
LYRA_TEST__CONTAINER_TOOL=${container_tool}
LYRA_TEST__CONTAINER_NAME=${container_name}
LYRA_TEST__RESULT_FILE=${result_file}
LYRA_TEST__PID_FILE=${pid_file}
LYRA_TEST__RUN_ID=${run_id}
EOF
}

# Function: load_test_state
# Description: Load test run state from file
# Returns:
#   0: State loaded successfully
#   1: State file not found
load_test_state() {
    if [[ -f "$TEST_STATE_FILE" ]]; then
        # shellcheck disable=SC1090
        source "$TEST_STATE_FILE"
        return 0
    fi
    return 1
}

# Function: generate_run_id
# Description: Generate unique run ID using timestamp and PID
# Returns: Unique run ID string
generate_run_id() {
    # Generate unique run ID using timestamp and PID
    local ts
    ts=$(date +%Y%m%d_%H%M%S)
    echo "${ts}_$$"
}

# Function: get_result_file
# Description: Get result file path for a run_id
# Arguments:
#   $1: run_id
# Returns: Result file path
get_result_file() {
    local run_id="$1"
    echo "${TEST_RESULT_DIR}/result_${run_id}.txt"
}

# Function: get_pid_file
# Description: Get PID file path for a run_id
# Arguments:
#   $1: run_id
# Returns: PID file path
get_pid_file() {
    local run_id="$1"
    echo "${TEST_RESULT_DIR}/pid_${run_id}"
}

# Function: cleanup_old_results
# Description: Clean up old test result files
cleanup_old_results() {
    # Remove legacy fixed-path files
    rm -f "$LEGACY_RESULT_FILE" "$LEGACY_PID_FILE" 2>/dev/null || true
    
    # Remove old result files (older than 1 hour)
    if [[ -d "$TEST_RESULT_DIR" ]]; then
        find "$TEST_RESULT_DIR" -type f -mmin +60 -delete 2>/dev/null || true
    fi
}

