#!/bin/bash
# Test Runtime Management Functions
#
# Functions for managing test execution runtime (container vs venv).

# Function: detect_container_tool
# Description: Detect container runtime tool (podman/docker)
# Returns: Container tool name or empty string
detect_container_tool() {
    get_container_runtime_cmd 2>/dev/null || true
}

# Function: is_container_running_selected
# Description: Check if selected container is running
# Returns:
#   0: Container is running
#   1: Container is not running
is_container_running_selected() {
    check_container_running "$CONTAINER_NAME_SELECTED"
}

# Function: resolve_runtime
# Description: Resolve runtime mode (container/venv) based on environment and state
# Returns: "container" or "venv"
resolve_runtime() {
    local runtime="$RUNTIME_MODE"

    if [[ "$runtime" == "auto" ]]; then
        # If a run already happened, keep check/get/kill consistent.
        if load_test_state; then
            runtime="${LYRA_TEST__RUNTIME:-auto}"
            if [[ -n "${LYRA_TEST__CONTAINER_NAME:-}" ]]; then
                CONTAINER_NAME_SELECTED="${LYRA_TEST__CONTAINER_NAME}"
            fi
        fi
    fi

    if [[ "$runtime" == "auto" ]]; then
        # If we are inside the lyra container, run in-container mode.
        # Note: IN_CONTAINER=true can also mean CI sandbox (runsc), not lyra.
        # Only use container mode if we're actually in the lyra container.
        if [[ "${IN_CONTAINER:-false}" == "true" ]] && [[ "${CURRENT_CONTAINER_NAME:-}" == "$CONTAINER_NAME_SELECTED" ]]; then
            echo "container"
            return 0
        fi

        # Default: Prefer venv. Container runtime must be explicitly requested via:
        # - ./scripts/test.sh run --container
        # - make test RUNTIME=container
        # This matches the MCP-hosted workflow (pytest runs on host) and improves determinism.
        echo "venv"
        return 0
    fi

    echo "$runtime"
}

# Function: container_exec
# Description: Execute command in container
# Arguments:
#   $@: Command and arguments
# Returns:
#   0: Success
#   1: Container runtime not found or execution failed
container_exec() {
    local tool
    tool="$(detect_container_tool)"
    if [[ -z "$tool" ]]; then
        log_error "No container runtime found (podman/docker)."
        return 1
    fi
    "$tool" exec "$CONTAINER_NAME_SELECTED" "$@"
}

# Function: container_exec_sh
# Description: Execute shell command in container
# Arguments:
#   $1: Shell command string
# Returns:
#   0: Success
#   1: Container runtime not found or execution failed
container_exec_sh() {
    local tool
    tool="$(detect_container_tool)"
    if [[ -z "$tool" ]]; then
        log_error "No container runtime found (podman/docker)."
        return 1
    fi
    "$tool" exec "$CONTAINER_NAME_SELECTED" bash -lc "$1"
}

# Function: runtime_file_exists
# Description: Check if file exists in runtime (container or venv)
# Arguments:
#   $1: runtime ("container" or "venv")
#   $2: file path
# Returns:
#   0: File exists
#   1: File does not exist
runtime_file_exists() {
    local runtime="$1"
    local path="$2"
    if [[ "$runtime" == "container" ]]; then
        container_exec test -f "$path" >/dev/null 2>&1
    else
        [[ -f "$path" ]]
    fi
}

# Function: runtime_tail
# Description: Get last N lines from file in runtime
# Arguments:
#   $1: runtime ("container" or "venv")
#   $2: number of lines
#   $3: file path
# Returns: Last N lines of file
runtime_tail() {
    local runtime="$1"
    local n="$2"
    local path="$3"
    if [[ "$runtime" == "container" ]]; then
        container_exec tail -n "$n" "$path" 2>/dev/null
    else
        tail -n "$n" "$path" 2>/dev/null
    fi
}

# Function: runtime_last_summary_line
# Description: Get last summary line from pytest output in runtime
# Arguments:
#   $1: runtime ("container" or "venv")
#   $2: file path
# Returns: Last summary line or empty string
runtime_last_summary_line() {
    local runtime="$1"
    local path="$2"
    # Must include "in X.XXs" to avoid matching collection line
    local re="[0-9]+ (passed|failed).* in [0-9]+(\.[0-9]+)?s"
    if [[ "$runtime" == "container" ]]; then
        container_exec_sh "grep -E \"$re\" \"$path\" 2>/dev/null | tail -n 1" 2>/dev/null || true
    else
        grep -E "$re" "$path" 2>/dev/null | tail -n 1 || true
    fi
}

# Function: runtime_line_count
# Description: Get line count of file in runtime
# Arguments:
#   $1: runtime ("container" or "venv")
#   $2: file path
# Returns: Line count or "0"
runtime_line_count() {
    local runtime="$1"
    local path="$2"
    if [[ "$runtime" == "container" ]]; then
        container_exec_sh "wc -l \"$path\" 2>/dev/null | awk '{print \\$1}'" 2>/dev/null || echo "0"
    else
        wc -l "$path" 2>/dev/null | awk '{print $1}' || echo "0"
    fi
}

# Function: runtime_cat
# Description: Output file contents in runtime
# Arguments:
#   $1: runtime ("container" or "venv")
#   $2: file path
# Returns: File contents
runtime_cat() {
    local runtime="$1"
    local path="$2"
    if [[ "$runtime" == "container" ]]; then
        container_exec cat "$path" 2>/dev/null
    else
        cat "$path" 2>/dev/null
    fi
}

# Function: is_pytest_process_alive
# Description: Check if the given PID is a running pytest/python process
# This prevents false positives from PID reuse or zombie processes
# Arguments:
#   $1: runtime ("container" or "venv")
#   $2: PID to check
# Returns:
#   0: Process is alive and is pytest/python
#   1: Process is dead, or is not pytest/python (PID reused)
is_pytest_process_alive() {
    local runtime="$1"
    local pid="$2"
    
    if [[ -z "$pid" ]]; then
        return 1
    fi
    
    local proc_comm=""
    local proc_state=""
    
    if [[ "$runtime" == "container" ]]; then
        # Get process command name and state
        # ps -p PID -o comm=,stat= returns: "python3 S" or empty if not exists
        proc_comm=$(container_exec_sh "ps -p $pid -o comm= 2>/dev/null || true" 2>/dev/null || echo "")
        proc_state=$(container_exec_sh "ps -p $pid -o stat= 2>/dev/null || true" 2>/dev/null || echo "")
    else
        proc_comm=$(ps -p "$pid" -o comm= 2>/dev/null || echo "")
        proc_state=$(ps -p "$pid" -o stat= 2>/dev/null || echo "")
    fi
    
    # Trim whitespace
    proc_comm="${proc_comm// /}"
    proc_state="${proc_state// /}"
    
    # Debug output
    if [[ "${DEBUG:-}" == "1" ]]; then
        log_info "[DEBUG] PID=$pid, comm='$proc_comm', stat='$proc_state'" >&2
    fi
    
    # Check if process exists
    if [[ -z "$proc_comm" ]]; then
        return 1
    fi
    
    # Check if process is zombie (state starts with Z)
    if [[ "$proc_state" == Z* ]]; then
        if [[ "${DEBUG:-}" == "1" ]]; then
            log_info "[DEBUG] Process $pid is zombie, treating as dead" >&2
        fi
        return 1
    fi
    
    # Check if process name matches pytest/python
    # pytest is typically run as python or python3
    if [[ "$proc_comm" =~ ^(python|python3|pytest|py\.test)$ ]]; then
        return 0
    fi
    
    # PID exists but is not pytest/python - likely PID reuse
    if [[ "${DEBUG:-}" == "1" ]]; then
        log_info "[DEBUG] PID $pid is '$proc_comm', not pytest/python - PID reused" >&2
    fi
    return 1
}

