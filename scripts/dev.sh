#!/bin/bash
# Lyra Development Environment (Podman)
#
# Manages the Podman-based development environment for Lyra.
#
# Usage: ./scripts/dev.sh [command]

set -euo pipefail

# =============================================================================
# INITIALIZATION
# =============================================================================

# Source common functions and load .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# Enable debug mode if DEBUG=1
enable_debug_mode

# Set up error handler
trap 'cleanup_on_error ${LINENO}' ERR

# Parse global flags first (--json, --quiet)
parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

# Change to project directory
cd "$PROJECT_DIR"

# Function to show help (defined early for use before dependency check)
_show_help() {
    echo "Lyra Development Environment (Podman)"
    echo ""
    echo "Usage: ./scripts/dev.sh [global-options] [command]"
    echo ""
    echo "Commands:"
    echo "  up        Start all services"
    echo "  down      Stop all services"
    echo "  build     Build containers"
    echo "  rebuild   Rebuild containers (no cache)"
    echo "  shell     Enter development shell"
    echo "  logs      Show logs (logs [service] or logs -f [service])"
    echo "  test      Run tests"
    echo "  mcp       Start MCP server"
    echo "  research  Run research query"
    echo "  status    Show container status"
    echo "  clean     Remove containers and images"
    echo ""
    echo "Global Options:"
    echo "  --json        Output in JSON format (machine-readable)"
    echo "  --quiet, -q   Suppress non-essential output"
    echo ""
    echo "Examples:"
    echo "  ./scripts/dev.sh --json status   # JSON status output"
    echo ""
    echo "Exit Codes:"
    echo "  0   (EXIT_SUCCESS)     Operation successful"
    echo "  3   (EXIT_CONFIG)      Configuration error (.env missing)"
    echo "  4   (EXIT_DEPENDENCY)  Missing dependency (podman/podman-compose)"
    echo ""
}

# Handle help and unknown commands early (before dependency check)
# This allows showing help even when podman is not installed
# Valid commands: up|down|build|rebuild|shell|logs|test|mcp|research|status|clean|help
case "${1:-}" in
    help|--help|-h|"")
        _show_help
        exit 0
        ;;
    up|down|build|rebuild|shell|logs|test|mcp|research|status|clean)
        # Valid command, continue to dependency check
        ;;
    *)
        # Unknown command - show help
        _show_help
        exit 0
        ;;
esac

# Verify required commands (exit mode for JSON output support)
require_podman_compose "exit"

COMPOSE="podman-compose"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Function: start_dev_shell
# Description: Start development shell with multi-network support
#             Creates a container with access to both primary and internal networks
# Returns:
#   0: Success (container started and attached)
#   1: Failure (container creation or start failed)
start_dev_shell() {
    log_info "Entering development shell..."
    
    # Build dev image (base stage only, no GPU packages)
    podman build -t lyra-dev:latest -f docker/Dockerfile --target base .
    
    # Load environment from .env if exists, otherwise use defaults
    local env_opts=""
    if [ -f "${PROJECT_DIR}/.env" ]; then
        env_opts="--env-file ${PROJECT_DIR}/.env"
    else
        log_warn ".env not found, using default environment variables"
        # Fallback defaults for proxy server (internal services)
        env_opts="-e LYRA_TOR__SOCKS_HOST=tor -e LYRA_TOR__SOCKS_PORT=9050 -e LYRA_LLM__OLLAMA_HOST=http://ollama:11434"
    fi
    
    # Derive network names from project directory name (podman-compose prefix)
    local project_name
    project_name="$(basename "$PROJECT_DIR")"
    local net_primary="${project_name}_lyra-net"
    local net_internal="${project_name}_lyra-internal"
    
    # Cleanup function to ensure container is removed on exit/error
    cleanup_dev_container() {
        podman rm -f lyra-dev 2>/dev/null || true
    }
    trap cleanup_dev_container EXIT
    
    # Remove existing container if exists
    podman rm -f lyra-dev 2>/dev/null || true
    
    # Create container with primary network
    # Note: Podman doesn't support multiple --network flags in a single run command,
    # so we create the container first, connect to additional networks, then start it
    # shellcheck disable=SC2086
    podman create -it \
        -v "${PROJECT_DIR}/src:/app/src:rw" \
        -v "${PROJECT_DIR}/config:/app/config:ro" \
        -v "${PROJECT_DIR}/data:/app/data:rw" \
        -v "${PROJECT_DIR}/logs:/app/logs:rw" \
        -v "${PROJECT_DIR}/tests:/app/tests:rw" \
        --network "$net_primary" \
        $env_opts \
        --name lyra-dev \
        lyra-dev:latest \
        /bin/bash
    
    # Connect to internal network for inference services (Ollama/ML)
    podman network connect "$net_internal" lyra-dev
    
    # Start container interactively and attach
    podman start -ai lyra-dev
}

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

# =============================================================================
# COMMAND HANDLERS
# =============================================================================

cmd_up() {
    # Check for .env file (required for proxy server configuration)
    if [ ! -f "${PROJECT_DIR}/.env" ]; then
        output_error "$EXIT_CONFIG" ".env file not found. Copy from template: cp .env.example .env" "hint=cp .env.example .env"
    fi

    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        log_info "Starting Lyra development environment..."
    fi

    # --no-build: Require explicit build (use dev-build first)
    $COMPOSE up -d --no-build

    output_result "success" "Services started" \
        "exit_code=0" \
        "tor_socks=localhost:9050" \
        "container=$CONTAINER_NAME"

    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "Services started:"
        echo "  - Tor SOCKS: localhost:9050"
        echo "  - Lyra: Running in container"
        echo ""
        echo "To enter the development shell: ./scripts/dev.sh shell"
    fi
}

cmd_down() {
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        log_info "Stopping Lyra development environment..."
    fi
    $COMPOSE down
    output_result "success" "Containers stopped" "exit_code=0"
}

cmd_build() {
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        log_info "Building containers..."
    fi
    $COMPOSE build
    output_result "success" "Build complete" "exit_code=0"
}

cmd_rebuild() {
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        log_info "Rebuilding containers from scratch..."
    fi
    $COMPOSE build --no-cache
    output_result "success" "Rebuild complete" "exit_code=0"
}

cmd_test() {
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        log_info "Running tests..."
    fi
    local exit_code=0
    $COMPOSE exec "$CONTAINER_NAME" pytest tests/ -v || exit_code=$?
    if [[ $exit_code -eq 0 ]]; then
        output_result "success" "Tests passed" "exit_code=0"
    else
        output_result "error" "Tests failed" "exit_code=$exit_code"
        exit $exit_code
    fi
}

cmd_mcp() {
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        log_info "Starting MCP server..."
    fi
    $COMPOSE exec "$CONTAINER_NAME" python -m src.mcp.server
}

cmd_research() {
    local query="$1"
    if [ -z "$query" ]; then
        output_error "$EXIT_USAGE" "Query argument required" "usage=make dev-shell"
    fi
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        log_info "Running research: $query"
    fi
    $COMPOSE exec "$CONTAINER_NAME" python -m src.main research --query "$query"
}

cmd_status() {
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        # Get container status in JSON-friendly format
        local containers
        containers=$($COMPOSE ps --format json 2>/dev/null || echo "[]")
        local running="false"
        if check_container_running "$CONTAINER_NAME"; then
            running="true"
        fi
        cat <<EOF
{
  "status": "ok",
  "container_running": ${running},
  "container_name": "${CONTAINER_NAME}",
  "containers": ${containers:-[]}
}
EOF
    else
        $COMPOSE ps
    fi
}

# =============================================================================
# MAIN
# =============================================================================

# Note: Help and unknown commands are already handled above before dependency check
case "${1:-help}" in
    up)
        cmd_up
        ;;
    
    down)
        cmd_down
        ;;
    
    build)
        cmd_build
        ;;
    
    rebuild)
        cmd_rebuild
        ;;
    
    shell)
        start_dev_shell
        ;;
    
    logs)
        show_logs "$2" "$3"
        ;;
    
    test)
        cmd_test
        ;;
    
    mcp)
        cmd_mcp
        ;;
    
    research)
        cmd_research "$2"
        ;;
    
    status)
        cmd_status
        ;;
    
    clean)
        cleanup_environment
        ;;

    # help|--help|-h|* are handled above before dependency check
esac
