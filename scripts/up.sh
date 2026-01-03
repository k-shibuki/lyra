#!/bin/bash
# Lyra Quick Start
# Zero-to-running: uv/venv setup, .env creation, container build/start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# =============================================================================
# CONTAINER GUARD
# =============================================================================

require_host_execution "up.sh" "starts Lyra environment from the host"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Check if lyra container images exist
container_images_exist() {
    local runtime
    runtime=$(get_container_runtime_cmd 2>/dev/null) || return 1
    $runtime images --format "{{.Repository}}" 2>/dev/null | grep -q "lyra"
}

# =============================================================================
# MAIN
# =============================================================================

log_info "Starting Lyra environment..."

# 1. Setup venv (includes automatic uv installation if needed - venv.sh feature)
setup_venv "mcp"

# 2. Build containers if needed (first time)
if ! container_images_exist; then
    log_info "Building containers (first time, ~10-15 min)..."
    "${SCRIPT_DIR}/dev.sh" build
fi

# 3. Start containers
"${SCRIPT_DIR}/dev.sh" up

log_info ""
log_info "=== Lyra containers ready! ==="
log_info ""
log_info "Next steps:"
log_info "  1. Configure MCP client (see README)"
log_info "  2. Run: make mcp (for debug) or connect via Cursor"

