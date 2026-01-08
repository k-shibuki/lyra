#!/bin/bash
# Lyra ML models downloader (host)
#
# Usage:
#   ./scripts/ml_models.sh [--json] [--quiet]
#
# Notes:
# - Downloads models to models/huggingface/ using scripts/download_models.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

enable_debug_mode
trap 'cleanup_on_error ${LINENO}' ERR

require_host_execution "ml_models.sh" "downloads ML models on the host"

parse_global_flags "$@"
set -- "${GLOBAL_ARGS[@]}"

cd "$PROJECT_DIR" || exit 1

log_info "Downloading ML models to models/huggingface/..."
mkdir -p models/huggingface

HF_HOME="${PROJECT_DIR}/models/huggingface" \
LYRA_ML__MODEL_PATHS_FILE="${PROJECT_DIR}/models/model_paths.json" \
uv run python scripts/download_models.py

log_info "ML model download complete"
output_result "success" "ML model download complete" "exit_code=0" "hf_home=models/huggingface" "model_paths=models/model_paths.json"

