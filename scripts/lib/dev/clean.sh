#!/bin/bash
# Dev Clean Functions
#
# Functions for cleaning up containers and images.

# Function: cleanup_environment
# Description: Clean up containers and images
#             Removes all Lyra containers, volumes, and images
# Returns:
#   0: Success
cleanup_environment() {
    log_info "Cleaning up containers and images..."
    $COMPOSE down --volumes
    # Remove project images manually (podman-compose doesn't support --rmi)
    # Use xargs -r to skip if input is empty (safe with set -u)
    local image_ids
    image_ids=$(podman images --filter "reference=lyra*" -q 2>/dev/null || true)
    if [ -n "${image_ids:-}" ]; then
        echo "$image_ids" | xargs -r podman rmi -f 2>/dev/null || true
    fi

    local dangling_ids
    dangling_ids=$(podman images --filter "dangling=true" -q 2>/dev/null || true)
    if [ -n "${dangling_ids:-}" ]; then
        echo "$dangling_ids" | xargs -r podman rmi -f 2>/dev/null || true
    fi
    log_info "Cleanup complete."
    output_result "success" "Cleanup complete"
}

