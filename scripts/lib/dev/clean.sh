#!/bin/bash
# Dev Clean Functions
#
# Functions for cleaning up containers and images.

# Function: cleanup_environment
# Description: Clean up containers, volumes, networks, and images
#             Removes all Lyra containers, volumes, networks, and images
# Returns:
#   0: Success
cleanup_environment() {
    local container_tool
    container_tool=$(get_container_runtime_cmd 2>/dev/null || echo "podman")
    
    log_info "Cleaning up containers and images..."
    
    # Stop and remove containers, volumes
    $COMPOSE down --volumes
    
    # Remove project images manually (podman-compose doesn't support --rmi)
    # Use xargs -r to skip if input is empty (safe with set -u)
    local image_ids
    image_ids=$("$container_tool" images --filter "reference=lyra*" -q 2>/dev/null || true)
    if [ -n "${image_ids:-}" ]; then
        echo "$image_ids" | xargs -r "$container_tool" rmi -f 2>/dev/null || true
    fi

    local dangling_ids
    dangling_ids=$("$container_tool" images --filter "dangling=true" -q 2>/dev/null || true)
    if [ -n "${dangling_ids:-}" ]; then
        echo "$dangling_ids" | xargs -r "$container_tool" rmi -f 2>/dev/null || true
    fi
    
    # Remove project networks (dynamically detected via compose label)
    local network_ids
    network_ids=$("$container_tool" network ls --filter "label=io.podman.compose.project=lyra" --format "{{.Name}}" 2>/dev/null || true)
    if [ -n "${network_ids:-}" ]; then
        echo "$network_ids" | xargs -r "$container_tool" network rm 2>/dev/null || true
    fi
    
    log_info "Cleanup complete."
    output_result "success" "Cleanup complete"
}

