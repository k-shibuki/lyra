#!/bin/bash
# Test State Management Functions
#
# Functions for managing test run state files and IDs.
#
# Reliable Completion Detection (ADR: make test/check trust):
#   - Each RUN_ID has a host-side manifest for independent tracking
#   - Completion is determined by done_file (marker) + exit_file (exit code)
#   - PID detection is auxiliary, NOT the primary completion signal
#   - Works reliably across venv/container and uv/direct wrappers

# =============================================================================
# MANIFEST PATH FUNCTIONS (per-RUN_ID tracking)
# =============================================================================

# Function: get_manifest_file
# Description: Get host-side manifest file path for a run_id
# Arguments:
#   $1: run_id
# Returns: Manifest file path (host-side, always accessible)
get_manifest_file() {
    local run_id="$1"
    echo "${TEST_RESULT_DIR}/run_${run_id}.env"
}

# Function: get_done_file
# Description: Get done marker file path for a run_id
# Arguments:
#   $1: run_id
# Returns: Done file path (runtime-side)
get_done_file() {
    local run_id="$1"
    echo "${TEST_RESULT_DIR}/done_${run_id}"
}

# Function: get_exit_file
# Description: Get exit code file path for a run_id
# Arguments:
#   $1: run_id
# Returns: Exit file path (runtime-side)
get_exit_file() {
    local run_id="$1"
    echo "${TEST_RESULT_DIR}/exit_${run_id}"
}

# Function: get_cancelled_file
# Description: Get cancelled marker file path for a run_id (written by kill)
# Arguments:
#   $1: run_id
# Returns: Cancelled file path (host-side)
get_cancelled_file() {
    local run_id="$1"
    echo "${TEST_RESULT_DIR}/cancelled_${run_id}"
}

# =============================================================================
# MANIFEST WRITE/LOAD FUNCTIONS
# =============================================================================

# Function: write_run_manifest
# Description: Write per-run manifest to host-side file
# Arguments:
#   $1: run_id
#   $2: runtime (venv/container)
#   $3: container_tool (podman/docker, empty for venv)
#   $4: container_name (empty for venv)
#   $5: result_file path
#   $6: pid_file path
#   $7: done_file path
#   $8: exit_file path
write_run_manifest() {
    local run_id="$1"
    local runtime="$2"
    local container_tool="$3"
    local container_name="$4"
    local result_file="$5"
    local pid_file="$6"
    local done_file="$7"
    local exit_file="$8"
    local manifest_file
    manifest_file=$(get_manifest_file "$run_id")
    local started_at
    started_at=$(date -Iseconds)

    cat >"$manifest_file" <<EOF
# Lyra Test Run Manifest (auto-generated)
# RUN_ID: ${run_id}
LYRA_MANIFEST__RUN_ID=${run_id}
LYRA_MANIFEST__RUNTIME=${runtime}
LYRA_MANIFEST__CONTAINER_TOOL=${container_tool}
LYRA_MANIFEST__CONTAINER_NAME=${container_name}
LYRA_MANIFEST__RESULT_FILE=${result_file}
LYRA_MANIFEST__PID_FILE=${pid_file}
LYRA_MANIFEST__DONE_FILE=${done_file}
LYRA_MANIFEST__EXIT_FILE=${exit_file}
LYRA_MANIFEST__STARTED_AT=${started_at}
EOF
}

# Function: load_run_manifest
# Description: Load per-run manifest from host-side file into LYRA_MANIFEST__* variables
# Arguments:
#   $1: run_id
# Returns:
#   0: Manifest loaded successfully
#   1: Manifest file not found
# Side effects:
#   Sets LYRA_MANIFEST__* variables and updates CONTAINER_NAME_SELECTED if container runtime
load_run_manifest() {
    local run_id="$1"
    local manifest_file
    manifest_file=$(get_manifest_file "$run_id")

    if [[ -f "$manifest_file" ]]; then
        # shellcheck disable=SC1090
        source "$manifest_file"
        # Update CONTAINER_NAME_SELECTED for runtime functions if container runtime
        if [[ "${LYRA_MANIFEST__RUNTIME:-}" == "container" ]] && [[ -n "${LYRA_MANIFEST__CONTAINER_NAME:-}" ]]; then
            # shellcheck disable=SC2034
            CONTAINER_NAME_SELECTED="${LYRA_MANIFEST__CONTAINER_NAME}"
        fi
        return 0
    fi
    return 1
}

# Function: manifest_exists
# Description: Check if manifest file exists for a run_id
# Arguments:
#   $1: run_id
# Returns:
#   0: Manifest exists
#   1: Manifest does not exist
manifest_exists() {
    local run_id="$1"
    local manifest_file
    manifest_file=$(get_manifest_file "$run_id")
    [[ -f "$manifest_file" ]]
}

# =============================================================================
# LEGACY STATE FUNCTIONS (for backward compatibility)
# =============================================================================

# Function: write_test_state
# Description: Write test run state to file (last-run state for default RUN_ID resolution)
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
# Description: Clean up old test result files (result, pid, done, exit, cancelled, manifest)
cleanup_old_results() {
    # Remove legacy fixed-path files
    rm -f "$LEGACY_RESULT_FILE" "$LEGACY_PID_FILE" 2>/dev/null || true
    
    # Remove old result files (older than 1 hour)
    # Includes: result_*, pid_*, done_*, exit_*, cancelled_*, run_*.env
    if [[ -d "$TEST_RESULT_DIR" ]]; then
        find "$TEST_RESULT_DIR" -type f -mmin +60 -delete 2>/dev/null || true
    fi
}

# Function: cleanup_run_artifacts
# Description: Clean up all artifacts for a specific run_id
# Arguments:
#   $1: run_id
#   $2: runtime (optional, will load from manifest if not provided)
cleanup_run_artifacts() {
    local run_id="$1"
    local runtime="${2:-}"
    
    # Load runtime from manifest if not provided
    if [[ -z "$runtime" ]]; then
        if load_run_manifest "$run_id"; then
            runtime="${LYRA_MANIFEST__RUNTIME:-venv}"
        else
            runtime="venv"
        fi
    fi
    
    local result_file pid_file done_file exit_file cancelled_file manifest_file
    result_file=$(get_result_file "$run_id")
    pid_file=$(get_pid_file "$run_id")
    done_file=$(get_done_file "$run_id")
    exit_file=$(get_exit_file "$run_id")
    cancelled_file=$(get_cancelled_file "$run_id")
    manifest_file=$(get_manifest_file "$run_id")
    
    if [[ "$runtime" == "container" ]]; then
        # Clean up runtime-side files in container
        container_exec_sh "rm -f \"$result_file\" \"$pid_file\" \"$done_file\" \"$exit_file\" 2>/dev/null || true" 2>/dev/null || true
    else
        # Clean up local files
        rm -f "$result_file" "$pid_file" "$done_file" "$exit_file" 2>/dev/null || true
    fi
    
    # Host-side files (manifest, cancelled) are always local
    rm -f "$cancelled_file" "$manifest_file" 2>/dev/null || true
}

