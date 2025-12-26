#!/bin/bash
# Lyra shell - result and error output

# Function: output_error
# Description: Output error in appropriate format (JSON or human-readable) and exit
# Arguments:
#   $1: exit_code (from EXIT_* constants)
#   $2: error message
#   $3+: Additional key=value pairs for JSON output
# Example:
#   output_error $EXIT_CONFIG "Configuration file not found" "file=.env"
output_error() {
    local exit_code="$1"
    local message="$2"
    shift 2

    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        local json_parts=()
        json_parts+=("$(json_kv "status" "error")")
        json_parts+=("$(json_num "exit_code" "$exit_code")")
        json_parts+=("$(json_kv "message" "$message")")

        for kv in "$@"; do
            local key="${kv%%=*}"
            local value="${kv#*=}"
            if [[ "$value" =~ ^[0-9]+$ ]]; then
                json_parts+=("$(json_num "$key" "$value")")
            elif [[ "$value" == "true" ]] || [[ "$value" == "false" ]]; then
                json_parts+=("$(json_bool "$key" "$value")")
            else
                json_parts+=("$(json_kv "$key" "$value")")
            fi
        done

        local IFS=','
        echo "{${json_parts[*]}}"
    else
        echo "[ERROR] $message" >&2
    fi
    exit "$exit_code"
}

# Function: output_result
# Description: Output result in appropriate format (JSON or human-readable)
# Arguments:
#   $1: status (e.g., "success", "error", "running")
#   $2: message (human-readable)
#   $3+: Additional key=value pairs for JSON output
# Example:
#   output_result "success" "Container started" "container=lyra" "port=8080"
output_result() {
    local status="$1"
    local message="$2"
    shift 2

    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        local json_parts=()
        json_parts+=("$(json_kv "status" "$status")")
        json_parts+=("$(json_kv "message" "$message")")

        # Add additional key=value pairs
        for kv in "$@"; do
            local key="${kv%%=*}"
            local value="${kv#*=}"
            # Detect if value looks like a number or boolean
            if [[ "$value" =~ ^[0-9]+$ ]]; then
                json_parts+=("$(json_num "$key" "$value")")
            elif [[ "$value" == "true" ]] || [[ "$value" == "false" ]]; then
                json_parts+=("$(json_bool "$key" "$value")")
            else
                json_parts+=("$(json_kv "$key" "$value")")
            fi
        done

        # Join with commas and wrap in braces
        local IFS=','
        echo "{${json_parts[*]}}"
    else
        if [[ "$LYRA_QUIET" != "true" ]]; then
            echo "$message"
        fi
    fi
}


