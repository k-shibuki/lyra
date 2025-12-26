#!/bin/bash
# Lyra Shell Scripts - Common Functions and Constants
#
# This file provides shared utilities for all Lyra shell scripts.
# Source this file at the beginning of each script:
#   source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
#
# Features:
#   - Environment loading from .env
#   - Unified logging functions
#   - Container management utilities
#   - Common constants with .env overrides
#   - Debug mode support
#   - Error handling utilities
#   - Standardized exit codes
#   - JSON output support (--json flag)
#
# Script Dependencies:
#   common.sh  <- (base, no dependencies)
#   dev.sh     <- common.sh, podman-compose
#   chrome.sh  <- common.sh, curl, (WSL: powershell.exe)
#   test.sh    <- common.sh, pytest, uv
#   mcp.sh     <- common.sh, dev.sh, uv, playwright
#   doctor.sh  <- common.sh, (WSL: powershell.exe for chrome checks)

# =============================================================================
# INITIALIZATION
# =============================================================================

#
# This file is the public entrypoint for all shell scripts.
# Implementation is split into modules under scripts/lib/.
#
# Note: Many scripts source this file with set -euo pipefail already enabled.
# Keep this file free of unsafe unbound variable usage.

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Core paths first
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/paths.sh"

# Exit codes
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/exit_codes.sh"

# Output utilities (JSON, logging, result formatting)
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/output.sh"

# Error handling / debug
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/error_handling.sh"

# Load env and apply constants
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/env_load.sh"
load_env 2>/dev/null || true

# CLI flag parsing (includes output mode flags initialization)
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/flags.sh"

# Platform detection (auto-detect on source to preserve existing behavior)
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/platform.sh"
detect_container
detect_cloud_agent

# Host execution guard (requires platform.sh for IN_CONTAINER)
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/host_guard.sh"

# Runtime/infra helpers
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/container.sh"
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/compose.sh"
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/venv.sh"
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/http.sh"
# shellcheck source=/dev/null
source "${COMMON_DIR}/lib/logs.sh"

