#!/bin/bash
# Lyra extra test runners (small, direct pytest invocations)
#
# Usage:
#   ./scripts/test_extra.sh [--json] [--quiet] <prompts|llm-output>
#
# Notes:
# - Uses host uv environment (consistent with existing Makefile behavior).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

enable_debug_mode
trap 'cleanup_on_error ${LINENO}' ERR

require_host_execution "test_extra.sh" "runs targeted pytest commands on the host"

parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

ACTION="${1:-}"

cd "$PROJECT_DIR" || exit 1

case "$ACTION" in
    prompts)
        uv run pytest tests/prompts/ -v
        ;;
    llm-output)
        uv run pytest tests/test_llm_output.py -v
        ;;
    help|--help|-h|"")
        echo "Usage: $0 <prompts|llm-output>"
        exit 0
        ;;
    *)
        output_error "$EXIT_USAGE" "Unknown action" "action=${ACTION}" "hint=Try: ./scripts/test_extra.sh help"
        ;;
esac

