#!/bin/bash
# Dev Logs Functions
#
# Functions for showing container logs.
#
# Note: podman-compose logs requires explicit service names.
# We use the container runtime directly (via get_container_runtime_cmd from lib/container.sh)
# for better compatibility.

# All lyra container names
readonly LYRA_CONTAINERS=("proxy" "ml" "ollama" "tor")

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
    
    # Use get_container_runtime_cmd from lib/container.sh (sourced via common.sh)
    local container_tool
    container_tool=$(get_container_runtime_cmd 2>/dev/null) || {
        log_error "No container runtime found (podman/docker)"
        return 1
    }
    
    if [ "$follow_flag" = "-f" ]; then
        if [ -n "$service" ]; then
            # Follow specific service
            $container_tool logs -f "$service"
        else
            # Follow all lyra containers
            $container_tool logs -f "${LYRA_CONTAINERS[@]}" 2>/dev/null || \
                log_error "Some containers may not be running"
        fi
    else
        if [ -n "$follow_flag" ]; then
            # Specific service requested
            $container_tool logs --tail=50 "$follow_flag"
        else
            # All lyra containers - show each with section header
            local container
            for container in "${LYRA_CONTAINERS[@]}"; do
                echo "=== $container ==="
                if check_container_running "$container"; then
                    $container_tool logs --tail=20 "$container" 2>/dev/null
                else
                    echo "(not running)"
                fi
                echo ""
            done
        fi
    fi
}

