#!/bin/bash
# Lyra Dead Code Checker (manual, not CI by default)
#
# Usage:
#   ./scripts/deadcode.sh [--min-confidence N] [--fail] [--json] [--quiet] -- [vulture_args...]
#
# Examples:
#   make deadcode
#   LYRA_SCRIPT__DEADCODE_MIN_CONFIDENCE=60 make deadcode
#   LYRA_SCRIPT__DEADCODE_FAIL=true make deadcode
#   ./scripts/deadcode.sh --min-confidence 60 -- --exclude "src/mcp/schemas/"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

enable_debug_mode
trap 'cleanup_on_error ${LINENO}' ERR

# Parse global flags first (--json, --quiet)
parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

MIN_CONFIDENCE="${LYRA_SCRIPT__DEADCODE_MIN_CONFIDENCE:-80}"
FAIL_MODE="${LYRA_SCRIPT__DEADCODE_FAIL:-false}"
VULTURE_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --min-confidence)
            MIN_CONFIDENCE="${2:-}"
            shift 2
            ;;
        --fail)
            FAIL_MODE="true"
            shift
            ;;
        --)
            shift
            VULTURE_ARGS+=("$@")
            break
            ;;
        *)
            VULTURE_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ -z "${MIN_CONFIDENCE}" ]] || ! [[ "${MIN_CONFIDENCE}" =~ ^[0-9]+$ ]]; then
    output_error "$EXIT_USAGE" "Invalid --min-confidence (expected integer)" "min_confidence=${MIN_CONFIDENCE}"
fi

cd "$PROJECT_DIR" || exit 1

log_info "Dead code check (vulture) starting..."
log_info "min_confidence=${MIN_CONFIDENCE} fail_mode=${FAIL_MODE}"

set +e
uv run vulture src/ --min-confidence "${MIN_CONFIDENCE}" "${VULTURE_ARGS[@]}"
status=$?
set -e

if [[ "${status}" -eq 0 ]]; then
    output_result "success" "Dead code check: no issues found" "min_confidence=${MIN_CONFIDENCE}"
    exit 0
fi

if [[ "${FAIL_MODE}" == "true" ]]; then
    output_result "error" "Dead code check: issues found" "min_confidence=${MIN_CONFIDENCE}" "exit_code=${status}"
    exit "${status}"
fi

log_warn "Dead code check found issues (non-failing mode)."
output_result "success" "Dead code check: issues found (non-failing)" "min_confidence=${MIN_CONFIDENCE}" "exit_code=${status}"
exit 0

