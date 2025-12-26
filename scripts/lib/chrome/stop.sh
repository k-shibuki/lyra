#!/bin/bash
# Chrome Stop Functions
#
# Functions for stopping Chrome instances.
# Used by pool.sh for stopping individual workers in the pool.

# Function: stop_chrome
# Description: Stop Chrome instance on a specific port
# Arguments:
#   $1: Port number (required)
# Returns:
#   0: Success
stop_chrome() {
    local port="${1:?Port number required}"
    local stopped_pid=""

    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "STOPPING"
    fi

    if [ "$ENV_TYPE" = "wsl" ]; then
        # Find process listening on debug port and kill it
        local stop_result
        stop_result=$(run_ps "
            \$ErrorActionPreference = 'Stop'
            try {
                \$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
                if (\$conn) {
                    Stop-Process -Id \$conn.OwningProcess -Force -ErrorAction SilentlyContinue
                    'Stopped process on port $port'
                } else {
                    'No process found on port $port'
                }
            } catch {
                'ERROR'
            }
        " 2>/dev/null | tr -d '\r\n')

        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            local was_running="false"
            if [ -n "$stop_result" ] && [[ "$stop_result" == *"Stopped"* ]]; then
                was_running="true"
            fi
            cat <<EOF
{
  "status": "success",
  "exit_code": ${EXIT_SUCCESS},
  "message": "${stop_result:-Chrome stop completed}",
  "was_running": ${was_running}
}
EOF
        else
            if [ -n "$stop_result" ] && [ "$stop_result" != "ERROR" ]; then
                echo "$stop_result"
            fi
            echo "DONE"
        fi
    else
        # Find process by port on Linux
        local pid
        pid=$(lsof -ti :"$port" 2>/dev/null || true)
        if [ -n "$pid" ]; then
            kill -9 "$pid" 2>/dev/null || true
            stopped_pid="$pid"
        fi

        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            local was_running="false"
            if [ -n "$stopped_pid" ]; then
                was_running="true"
            fi
            cat <<EOF
{
  "status": "success",
  "exit_code": ${EXIT_SUCCESS},
  "message": "Chrome stop completed",
  "was_running": ${was_running},
  "pid": "${stopped_pid:-null}"
}
EOF
        else
            if [ -n "$stopped_pid" ]; then
                echo "Stopped process $stopped_pid"
            fi
            echo "DONE"
        fi
    fi
}

