#!/bin/bash
# Chrome Status Functions
#
# Functions for checking Chrome CDP status.

# Function: get_status
# Description: Get Chrome debug port status and connection information
# Arguments:
#   $1: Port number to check
# Returns:
#   0: Chrome is ready, outputs connection info
#   1: Chrome is not ready
# Supports: --json flag for machine-readable output
get_status() {
    local port="$1"
    local host

    if host=$(try_connect "$port"); then
        local info
        info=$(curl -s --connect-timeout 2 "http://$host:$port/json/version" 2>/dev/null)
        local browser
        # Note: JSON may have space after colon ("Browser": "..."), use flexible pattern
        browser=$(echo "$info" | grep -oE '"Browser":\s*"[^"]*"' | cut -d'"' -f4 || echo "")

        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            cat <<EOF
{
  "status": "ready",
  "exit_code": ${EXIT_SUCCESS},
  "host": "${host}",
  "port": ${port},
  "browser": "${browser}",
  "connect_url": "http://${host}:${port}",
  "cdp_command": "chromium.connect_over_cdp('http://${host}:${port}')"
}
EOF
        else
            echo "READY"
            echo "Host: $host:$port"
            echo "Browser: $browser"
            echo "Connect: chromium.connect_over_cdp('http://$host:$port')"
        fi
        return "$EXIT_SUCCESS"
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            cat <<EOF
{
  "status": "not_ready",
  "exit_code": ${EXIT_NOT_READY},
  "port": ${port},
  "message": "Chrome CDP not responding"
}
EOF
        else
            echo "NOT_READY"
            echo "Port: $port"
        fi
        return "$EXIT_NOT_READY"
    fi
}

