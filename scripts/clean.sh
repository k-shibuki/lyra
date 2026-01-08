#!/bin/bash
# Lyra cleanup utilities
#
# Usage:
#   ./scripts/clean.sh [--json] [--quiet] <clean|clean-all>
#
# Notes:
# - clean: removes caches (__pycache__, *.pyc, tool caches)
# - clean-all: clean + remove venv + clean containers/images

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

enable_debug_mode
trap 'cleanup_on_error ${LINENO}' ERR

parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

ACTION="${1:-clean}"
shift || true

do_clean() {
    cd "$PROJECT_DIR" || exit 1
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    rm -rf .pytest_cache .mypy_cache .ruff_cache 2>/dev/null || true
}

case "$ACTION" in
    clean)
        do_clean
        output_result "success" "Clean complete" "exit_code=0"
        ;;
    clean-all)
        do_clean
        # Remove containers/images as well (consistent with previous Makefile clean-all)
        "${SCRIPT_DIR}/dev.sh" clean
        rm -rf "${PROJECT_DIR}/.venv" 2>/dev/null || true
        output_result "success" "Clean-all complete" "exit_code=0"
        ;;
    help|--help|-h)
        echo "Usage: $0 <clean|clean-all>"
        exit 0
        ;;
    *)
        output_error "$EXIT_USAGE" "Unknown action" "action=${ACTION}" "hint=Try: ./scripts/clean.sh help"
        ;;
esac

