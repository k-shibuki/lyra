#!/bin/bash
# Dev Logs Functions
#
# Functions for showing container logs.

# Function: show_logs
# Description: Show container logs with optional follow mode
# Arguments:
#   $1: Follow flag ("-f" for follow mode) or service name
#   $2: Service name (optional, if $1 is "-f")
# Returns:
#   0: Success
show_logs() {
    local follow_flag="$1"
    local service="$2"
    
    if [ "$follow_flag" = "-f" ]; then
        $COMPOSE logs -f "${service:-}"
    else
        # Default: show last 50 lines without following
        $COMPOSE logs --tail=50 "${follow_flag:-}"
    fi
}

