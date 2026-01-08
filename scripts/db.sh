#!/bin/bash
# Lyra DB maintenance utilities
#
# Usage:
#   ./scripts/db.sh [--json] [--quiet] reset

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

enable_debug_mode
trap 'cleanup_on_error ${LINENO}' ERR

require_host_execution "db.sh" "manages local DB files on the host"

parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

ACTION="${1:-}"

case "$ACTION" in
    reset)
        cd "$PROJECT_DIR" || exit 1
        log_warn "WARNING: This will delete all data in data/lyra.db"
        log_warn "Press Ctrl+C to cancel, or wait 3 seconds..."
        sleep 3
        rm -f data/lyra.db data/lyra.db-wal data/lyra.db-shm 2>/dev/null || true
        log_info "Database deleted. Schema will be recreated on next server start."
        output_result "success" "Database deleted" "exit_code=0" "path=data/lyra.db"
        ;;
    help|--help|-h|"")
        echo "Usage: $0 reset"
        exit 0
        ;;
    *)
        output_error "$EXIT_USAGE" "Unknown action" "action=${ACTION}" "hint=Try: ./scripts/db.sh help"
        ;;
esac

