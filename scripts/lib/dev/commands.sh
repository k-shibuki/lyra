#!/bin/bash
# Dev Command Handlers
#
# Functions for handling dev.sh commands.

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
        echo "To enter the development shell: make dev-shell"
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

