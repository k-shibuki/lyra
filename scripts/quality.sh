#!/bin/bash
# Lyra Quality Runner
#
# Usage:
#   ./scripts/quality.sh [--json] [--quiet] <action> [args...]
#
# Actions:
#   lint         Run ruff check
#   lint-fix     Run ruff check --fix
#   format       Run black + ruff --fix
#   format-check Run black --check
#   typecheck    Run mypy
#   jsonschema   Validate MCP JSON schemas
#   sh-check     Run shellcheck on scripts
#   quality      Run lint + format-check + typecheck + jsonschema + shellcheck
#
# Notes:
# - Honors LYRA_OUTPUT_JSON=true (or --json) for ruff/mypy output formatting.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

enable_debug_mode
trap 'cleanup_on_error ${LINENO}' ERR

require_host_execution "quality.sh" "runs code quality tools on the host"

# Parse global flags first (--json, --quiet)
parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

ACTION="${1:-quality}"
shift || true

run_ruff_check() {
    if [[ "${LYRA_OUTPUT_JSON:-false}" == "true" ]]; then
        uv run ruff check --output-format json "$@"
    else
        uv run ruff check "$@"
    fi
}

run_mypy() {
    if [[ "${LYRA_OUTPUT_JSON:-false}" == "true" ]]; then
        uv run mypy --output json "$@"
    else
        uv run mypy "$@"
    fi
}

case "$ACTION" in
    lint)
        uv run ruff --version >/dev/null
        run_ruff_check src/ tests/ "$@"
        ;;
    lint-fix)
        uv run ruff --version >/dev/null
        run_ruff_check --fix src/ tests/ "$@"
        ;;
    format)
        uv run black src/ tests/ "$@"
        run_ruff_check --fix src/ tests/
        ;;
    format-check)
        uv run black --check src/ tests/ "$@"
        ;;
    typecheck)
        run_mypy src/ tests/ "$@"
        ;;
    jsonschema)
        uv run check-jsonschema --schemafile http://json-schema.org/draft-07/schema# src/mcp/schemas/*.json "$@"
        ;;
    shellcheck)
        # Use NUL-delimited pipeline to be safe with unusual filenames.
        find scripts -name "*.sh" -type f -print0 | xargs -0 shellcheck -x -e SC1091
        ;;
    quality)
        "$0" lint
        "$0" format-check
        "$0" typecheck
        "$0" jsonschema
        "$0" shellcheck
        ;;
    help|--help|-h)
        echo "Usage: $0 [--json] [--quiet] <action> [args...]"
        echo "Actions: lint, lint-fix, format, format-check, typecheck, jsonschema, shellcheck, quality"
        exit 0
        ;;
    *)
        output_error "$EXIT_USAGE" "Unknown action" "action=${ACTION}" "hint=Try: ./scripts/quality.sh help"
        ;;
esac

