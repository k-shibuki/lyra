#!/bin/bash
# Lyra Ollama helper (container-side operations)
#
# Usage:
#   ./scripts/ollama.sh [--json] [--quiet] <action> [args...]
#
# Actions:
#   pull   Pull model (MODEL=... env or argument, default: qwen2.5:3b)
#   list   List available models
#   status Show status (non-fatal if container is not running)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

enable_debug_mode
trap 'cleanup_on_error ${LINENO}' ERR

require_host_execution "ollama.sh" "manages Ollama model inside container"

parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

ACTION="${1:-status}"
shift || true

MODEL_ARG="${1:-}"
MODEL="${MODEL:-${MODEL_ARG:-qwen2.5:3b}}"

case "$ACTION" in
    pull)
        log_info "Pulling Ollama model: ${MODEL}"
        podman network connect lyra_lyra-net ollama 2>/dev/null || true
        if [[ "${LYRA_OUTPUT_JSON:-false}" == "true" ]]; then
            # Keep stdout machine-readable; send pull progress to stderr.
            podman exec ollama ollama pull "${MODEL}" >&2
            output_result "success" "Ollama model pulled" "exit_code=0" "model=${MODEL}"
        else
            podman exec ollama ollama pull "${MODEL}"
        fi
        podman network disconnect lyra_lyra-net ollama 2>/dev/null || true
        ;;
    list)
        if [[ "${LYRA_OUTPUT_JSON:-false}" == "true" ]]; then
            # Parse list output into JSON (best-effort).
            # NOTE: Keep stdout machine-readable; do not print the raw table.
            out=$(podman exec ollama ollama list 2>/dev/null || true)
            models_json="[]"
            if [[ -n "$out" ]]; then
                # Extract first column (NAME) after header.
                # Format: NAME ID SIZE MODIFIED
                models_json=$(echo "$out" | tail -n +2 | awk 'NF>0{print $1}' | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))' 2>/dev/null || echo "[]")
            fi
            cat <<EOF
{
  "status": "ok",
  "exit_code": 0,
  "models": ${models_json}
}
EOF
        else
            podman exec ollama ollama list
        fi
        ;;
    status)
        if podman exec ollama ollama list >/dev/null 2>&1; then
            if [[ "${LYRA_OUTPUT_JSON:-false}" == "true" ]]; then
                cat <<EOF
{
  "status": "ok",
  "exit_code": 0,
  "running": true
}
EOF
            else
                if [[ "${LYRA_QUIET:-false}" != "true" ]]; then
                    echo "RUNNING | container=ollama"
                fi
            fi
        else
            log_warn "Ollama container not running"
            if [[ "${LYRA_OUTPUT_JSON:-false}" == "true" ]]; then
                cat <<EOF
{
  "status": "ok",
  "exit_code": 0,
  "running": false,
  "hint": "make up"
}
EOF
            else
                if [[ "${LYRA_QUIET:-false}" != "true" ]]; then
                    echo "NOT_RUNNING | container=ollama | hint=make up"
                fi
            fi
        fi
        ;;
    help|--help|-h)
        echo "Usage: $0 <pull|list|status> [model]"
        exit 0
        ;;
    *)
        output_error "$EXIT_USAGE" "Unknown action" "action=${ACTION}" "hint=Try: ./scripts/ollama.sh help"
        ;;
esac

