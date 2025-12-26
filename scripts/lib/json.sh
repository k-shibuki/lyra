#!/bin/bash
# Lyra shell - JSON output utilities

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


