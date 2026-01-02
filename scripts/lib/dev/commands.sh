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

    # Ensure ML models are available BEFORE starting containers
    # (podman creates directories instead of files for non-existent mount sources)
    ensure_ml_models

    # --no-build: Require explicit build (use dev-build first)
    $COMPOSE up -d --no-build

    # Ensure Ollama model is available (auto-pull if not present)
    ensure_ollama_model

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

# Ensure Ollama model is available, pull if not present
# Model name is read from LYRA_LLM__MODEL or defaults to qwen2.5:3b
# Note: Ollama runs on internal network only (security). We temporarily
# connect to external network for model download, then disconnect.
ensure_ollama_model() {
    local model="${LYRA_LLM__MODEL:-qwen2.5:3b}"
    local ollama_container="lyra-ollama"
    local external_network="lyra_lyra-net"
    local max_retries=30
    local retry_interval=2

    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        log_info "Ensuring Ollama model: $model"
    fi

    # Wait for Ollama container to be ready
    local retries=0
    while ! podman exec "$ollama_container" ollama list >/dev/null 2>&1; do
        retries=$((retries + 1))
        if [[ $retries -ge $max_retries ]]; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                log_warn "Ollama container not ready after ${max_retries} attempts. Model may need to be pulled manually."
            fi
            return 0  # Don't fail the entire startup
        fi
        sleep "$retry_interval"
    done

    # Check if model is already available
    if podman exec "$ollama_container" ollama list 2>/dev/null | grep -q "^${model}[[:space:]]"; then
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            log_info "Ollama model $model is already available"
        fi
        return 0
    fi

    # Pull the model (requires temporary internet access)
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        log_info "Pulling Ollama model: $model (this may take a few minutes)..."
    fi

    # Temporarily connect to external network for download
    if podman network exists "$external_network" >/dev/null 2>&1; then
        podman network connect "$external_network" "$ollama_container" 2>/dev/null || true
    fi

    if podman exec "$ollama_container" ollama pull "$model"; then
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            log_info "Ollama model $model pulled successfully"
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            log_warn "Failed to pull Ollama model $model. You can pull it manually: make ollama-pull"
        fi
    fi

    # Disconnect from external network (restore security posture)
    if podman network exists "$external_network" >/dev/null 2>&1; then
        podman network disconnect "$external_network" "$ollama_container" 2>/dev/null || true
    fi
}

# Ensure ML models are available, download if not present
ensure_ml_models() {
    if [ ! -f "${PROJECT_DIR}/models/model_paths.json" ]; then
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            log_info "ML models not found, downloading..."
        fi
        (cd "${PROJECT_DIR}" && make setup-ml-models) || {
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                log_warn "Failed to download ML models. You can download them manually: make setup-ml-models"
            fi
        }
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
    local container_tool
    container_tool=$(get_container_runtime_cmd 2>/dev/null || echo "podman")
    
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        # Get container status in JSON-friendly format
        local containers
        containers=$($COMPOSE ps --format json 2>/dev/null || echo "[]")
        local running="false"
        if check_container_running "$CONTAINER_NAME"; then
            running="true"
        fi
        # Get network list
        local networks
        networks=$($container_tool network ls --filter "label=io.podman.compose.project=lyra" --format "{{.Name}}" 2>/dev/null | jq -R -s 'split("\n") | map(select(length > 0))' 2>/dev/null || echo "[]")
        cat <<EOF
{
  "status": "ok",
  "container_running": ${running},
  "container_name": "${CONTAINER_NAME}",
  "containers": ${containers:-[]},
  "networks": ${networks:-[]}
}
EOF
    else
        echo "=== Containers ==="
        $COMPOSE ps
        echo ""
        echo "=== Networks ==="
        $container_tool network ls --filter "label=io.podman.compose.project=lyra"
    fi
}

