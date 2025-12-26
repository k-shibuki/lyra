#!/bin/bash
# Lyra shell - output utilities (JSON, logging, and result formatting)

# =============================================================================
# JSON OUTPUT HELPERS
# =============================================================================

# Function: json_output
# Description: Output a JSON object (only if JSON mode is enabled)
# Arguments:
#   $1: JSON string to output
# Example:
#   json_output '{"status": "ready", "port": 9222}'
json_output() {
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        echo "$1"
    fi
}

# Function: json_kv
# Description: Build a JSON key-value pair (properly escaped)
# Arguments:
#   $1: key
#   $2: value
# Returns: "key": "value" (with proper escaping)
json_kv() {
    local key="$1"
    local value="$2"
    # Escape special characters for JSON
    value="${value//\\/\\\\}"  # backslash
    value="${value//\"/\\\"}"  # double quote
    value="${value//$'\n'/\\n}" # newline
    value="${value//$'\r'/\\r}" # carriage return
    value="${value//$'\t'/\\t}" # tab
    printf '"%s": "%s"' "$key" "$value"
}

# Function: json_bool
# Description: Build a JSON key-boolean pair
# Arguments:
#   $1: key
#   $2: value (will be converted to true/false)
json_bool() {
    local key="$1"
    local value="$2"
    if [[ "$value" == "true" ]] || [[ "$value" == "1" ]] || [[ "$value" == "yes" ]]; then
        printf '"%s": true' "$key"
    else
        printf '"%s": false' "$key"
    fi
}

# Function: json_num
# Description: Build a JSON key-number pair
# Arguments:
#   $1: key
#   $2: numeric value
json_num() {
    local key="$1"
    local value="$2"
    printf '"%s": %s' "$key" "$value"
}

# =============================================================================
# LOGGING FUNCTIONS
# =============================================================================

# Function: log_info
# Description: Log info message to stdout
# Arguments:
#   $*: Message to log
log_info() {
    echo "[INFO] $*"
}

# Function: log_warn
# Description: Log warning message to stderr
# Arguments:
#   $*: Message to log
log_warn() {
    echo "[WARN] $*" >&2
}

# Function: log_error
# Description: Log error message to stderr (JSON-aware)
# Arguments:
#   $*: Message to log
# Note: In JSON mode, this outputs to stderr only (main output should use output_error)
log_error() {
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "[ERROR] $*" >&2
    fi
}

# =============================================================================
# RESULT AND ERROR OUTPUT FUNCTIONS
# =============================================================================

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

