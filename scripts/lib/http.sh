#!/bin/bash
# Lyra shell - HTTP utilities

# Function: wait_for_endpoint
# Description: Wait for HTTP endpoint with exponential backoff
# Arguments:
#   $1: URL to check (e.g., "http://localhost:8080/health")
#   $2: Total timeout in seconds (default: 30)
#   $3: Success message (optional)
# Returns:
#   0: Endpoint is ready
#   1: Timeout waiting for endpoint
wait_for_endpoint() {
    local url="$1"
    local timeout="${2:-30}"
    local success_msg="${3:-Endpoint ready}"

    local delay=0.5
    local max_delay=4.0
    local start_time
    start_time=$(date +%s)

    while true; do
        if curl -s --connect-timeout 2 "$url" > /dev/null 2>&1; then
            log_info "$success_msg"
            return 0
        fi

        local elapsed=$(($(date +%s) - start_time))
        if (( elapsed >= timeout )); then
            log_warn "Timeout waiting for $url"
            return 1
        fi

        sleep "$delay"
        delay=$(awk "BEGIN {d=$delay*2; print (d<$max_delay)?d:$max_delay}")
    done
}


