#!/bin/bash
# Chrome Connection Utilities
#
# Functions for connecting to Chrome CDP endpoints.

# Function: try_connect
# Description: Try multiple endpoints to connect to Chrome CDP
# Arguments:
#   $1: Port number to connect to
# Returns:
#   0: Success, outputs hostname that works
#   1: Failed to connect to any endpoint
try_connect() {
    local port="$1"
    local endpoints=("localhost" "127.0.0.1")
    
    if [ "$ENV_TYPE" = "wsl" ]; then
        endpoints+=("$(get_windows_host)")
    fi
    
    for host in "${endpoints[@]}"; do
        if curl -s --connect-timeout "$CURL_TIMEOUT" "http://$host:$port/json/version" > /dev/null 2>&1; then
            echo "$host"
            return 0
        fi
    done
    return 1
}

# Function: try_connect_with_backoff
# Description: Try to connect to Chrome CDP with exponential backoff
#              Uses total timeout approach to prevent accidental timeout explosion
# Arguments:
#   $1: Port number to connect to
#   $2: Total timeout in seconds (default: 15)
#   $3: Base delay in seconds (default: 0.5)
#   $4: Maximum delay cap in seconds (default: 4.0)
# Returns:
#   0: Success, outputs hostname that works
#   1: Failed to connect after timeout
# Note: Exponential backoff sequence with base=0.5, cap=4: 0.5, 1, 2, 4, 4, 4...
try_connect_with_backoff() {
    local port="$1"
    local total_timeout="${2:-15}"
    local base_delay="${3:-0.5}"
    local max_delay="${4:-4.0}"  # Maximum delay cap (default: 4 seconds)
    local endpoints=("localhost" "127.0.0.1")
    
    if [ "$ENV_TYPE" = "wsl" ]; then
        endpoints+=("$(get_windows_host)")
    fi
    
    local delay=$base_delay
    local elapsed=0
    local start_time
    start_time=$(date +%s.%N 2>/dev/null || date +%s)
    
    while true; do
        # Try all endpoints
        for host in "${endpoints[@]}"; do
            if curl -s --connect-timeout "$CURL_TIMEOUT" "http://$host:$port/json/version" > /dev/null 2>&1; then
                echo "$host"
                return 0
            fi
        done
        
        # Calculate elapsed time
        local current_time
        current_time=$(date +%s.%N 2>/dev/null || date +%s)
        elapsed=$(awk "BEGIN {print $current_time - $start_time}")
        
        # Check if we've exceeded timeout (with buffer for next delay)
        local remaining
        remaining=$(awk "BEGIN {print $total_timeout - $elapsed}")
        if awk "BEGIN {exit !($remaining <= 0)}"; then
            break
        fi
        
        # Use smaller of delay or remaining time
        local sleep_time
        sleep_time=$(awk "BEGIN {print ($delay < $remaining) ? $delay : $remaining}")
        if awk "BEGIN {exit !($sleep_time <= 0)}"; then
            break
        fi
        
        sleep "$sleep_time"
        
        # Exponential backoff: double the delay each time, capped at max_delay
        delay=$(awk "BEGIN {d = $delay * 2; print (d < $max_delay) ? d : $max_delay}")
    done
    return 1
}

