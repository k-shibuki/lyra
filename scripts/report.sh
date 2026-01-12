#!/bin/bash
# Lyra Report Generation utilities
#
# Usage:
#   ./scripts/report.sh [--json] [--quiet] <command> [OPTIONS]
#
# Commands:
#   pack        Generate evidence_pack.json and citation_index.json from DB
#   draft       Generate drafts/draft_01.md from evidence_pack.json
#   validate    Stage 3 unified postprocess + validate (draft_02/draft_03)
#   finalize    Produce outputs/report.md (markers stripped) from draft_validated.md
#   dashboard   Generate evidence dashboard from task data
#   all         Run pack + draft (deterministic pipeline)
#
# Examples:
#   # Generate evidence pack and draft for tasks
#   ./scripts/report.sh pack --tasks task_ed3b72cf task_8f90d8f6
#   ./scripts/report.sh draft --tasks task_ed3b72cf task_8f90d8f6
#
#   # Validate LLM-enhanced draft
#   ./scripts/report.sh validate --tasks task_ed3b72cf
#
#   # Finalize validated draft into outputs/report.md
#   ./scripts/report.sh finalize --tasks task_ed3b72cf
#
#   # Generate dashboard
#   ./scripts/report.sh dashboard --tasks task_ed3b72cf task_8f90d8f6
#
#   # Via make (recommended)
#   make report TASKS="task_ed3b72cf task_8f90d8f6"
#   make report-dashboard TASKS="task_ed3b72cf task_8f90d8f6"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

enable_debug_mode
trap 'cleanup_on_error ${LINENO}' ERR

require_host_execution "report.sh" "generates reports from local DB"

parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

ACTION="${1:-}"
shift || true

show_help() {
    cat << 'EOF'
Lyra Report Generation

Usage: ./scripts/report.sh [--json] [--quiet] <command> [options]

Commands:
  pack        Generate evidence_pack.json and citation_index.json from DB
  draft       Generate drafts/draft_01.md from evidence_pack.json
  validate    Stage 3 unified postprocess + validate (draft_02/draft_03)
  finalize    Produce outputs/report.md (markers stripped) from draft_validated.md
  dashboard   Generate evidence dashboard from task data
  all         Run pack + draft (deterministic pipeline)
  help        Show this help message

Common Options:
  --tasks TASK ...        Task IDs (for pack/draft/all)
  --tasks TASK ...        Task IDs (for validate/finalize/dashboard)
  --db PATH               Database path (default: data/lyra.db)
  --output-dir PATH       Output directory (default: data/reports)

Dashboard Options:
  --template PATH         Template path (default: config/templates/dashboard.html)
  --output PATH           Output file path (default: auto-generated)

Examples:
  # Generate evidence pack and draft
  ./scripts/report.sh pack --tasks task_ed3b72cf task_8f90d8f6
  ./scripts/report.sh draft --tasks task_ed3b72cf task_8f90d8f6

  # Full deterministic pipeline
  ./scripts/report.sh all --tasks task_ed3b72cf task_8f90d8f6

  # Validate LLM-enhanced draft (draft_02.md or draft_03.md)
  ./scripts/report.sh validate --tasks task_ed3b72cf

  # Finalize validated draft into outputs/report.md
  ./scripts/report.sh finalize --tasks task_ed3b72cf

  # Generate dashboard
  ./scripts/report.sh dashboard --tasks task_ed3b72cf task_8f90d8f6

  # Via make (recommended)
  make report TASKS="task_ed3b72cf task_8f90d8f6"
  make report-validate TASKS="task_ed3b72cf"
  make report-finalize TASKS="task_ed3b72cf"
  make report-dashboard TASKS="task_ed3b72cf task_8f90d8f6"
EOF
}

# Generic command handler for pack/draft/validate/all
cmd_report() {
    local subcommand="$1"
    shift
    
    local db_path=""
    local output_dir=""
    local tasks=()

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tasks)
                shift
                while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                    tasks+=("$1")
                    shift
                done
                ;;
            --db)
                db_path="$2"
                shift 2
                ;;
            --output-dir)
                output_dir="$2"
                shift 2
                ;;
            *)
                output_error "$EXIT_USAGE" "Unknown option" "option=$1" "hint=Try: ./scripts/report.sh help"
                ;;
        esac
    done

    # Validate required arguments
    if [[ ${#tasks[@]} -eq 0 ]]; then
        output_error "$EXIT_USAGE" "No tasks specified" "hint=Use --tasks task_id [task_id...]"
    fi

    # Ensure venv exists
    ensure_venv

    # Build Python command arguments
    local py_args=("$subcommand" "--tasks")
    for task in "${tasks[@]}"; do
        py_args+=("$task")
    done

    if [[ -n "$db_path" ]]; then
        py_args+=("--db" "$db_path")
    fi

    if [[ -n "$output_dir" ]]; then
        py_args+=("--output-dir" "$output_dir")
    fi

    log_info "Running report ${subcommand} for ${#tasks[@]} task(s)..."

    # Run Python module in venv
    cd "$PROJECT_DIR" || exit 1
    
    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"
    
    if ! python -m src.report.report "${py_args[@]}"; then
        output_error "${EXIT_OPERATION_FAILED:-30}" "Report ${subcommand} failed" "tasks=${tasks[*]}"
    fi

    output_result "success" "Report ${subcommand} completed" "tasks=${#tasks[@]}"
}

cmd_dashboard() {
    local db_path=""
    local template_path=""
    local output_path=""
    local tasks=()

    # Parse dashboard-specific arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tasks)
                shift
                # Collect all task arguments until next flag or end
                while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                    tasks+=("$1")
                    shift
                done
                ;;
            --db)
                db_path="$2"
                shift 2
                ;;
            --template)
                template_path="$2"
                shift 2
                ;;
            --output)
                output_path="$2"
                shift 2
                ;;
            *)
                output_error "$EXIT_USAGE" "Unknown option" "option=$1" "hint=Try: ./scripts/report.sh help"
                ;;
        esac
    done

    # Validate required arguments
    if [[ ${#tasks[@]} -eq 0 ]]; then
        output_error "$EXIT_USAGE" "No tasks specified" "hint=Use --tasks task_id [task_id...]"
    fi

    # Ensure venv exists
    ensure_venv

    # Build Python command arguments
    local py_args=("--tasks")
    for task in "${tasks[@]}"; do
        py_args+=("$task")
    done

    if [[ -n "$db_path" ]]; then
        py_args+=("--db" "$db_path")
    fi

    if [[ -n "$template_path" ]]; then
        py_args+=("--template" "$template_path")
    fi

    if [[ -n "$output_path" ]]; then
        py_args+=("--output" "$output_path")
    fi

    log_info "Generating dashboard for ${#tasks[@]} task(s)..."

    # Run Python module in venv
    cd "$PROJECT_DIR" || exit 1
    
    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"
    
    if ! python -m src.report.dashboard "${py_args[@]}"; then
        output_error "${EXIT_OPERATION_FAILED:-30}" "Dashboard generation failed" "tasks=${tasks[*]}"
    fi

    output_result "success" "Dashboard generated" "tasks=${#tasks[@]}"
}

case "$ACTION" in
    pack)
        cmd_report "pack" "$@"
        ;;
    draft)
        cmd_report "draft" "$@"
        ;;
    validate)
        cmd_report "validate" "$@"
        ;;
    finalize)
        cmd_report "finalize" "$@"
        ;;
    all)
        cmd_report "all" "$@"
        ;;
    dashboard)
        cmd_dashboard "$@"
        ;;
    help|--help|-h|"")
        show_help
        exit 0
        ;;
    *)
        output_error "$EXIT_USAGE" "Unknown action" "action=${ACTION}" "hint=Try: ./scripts/report.sh help"
        ;;
esac
