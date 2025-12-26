#!/bin/bash
# Lyra shell - environment loading and common constants (with .env overrides)

# Function: load_env
# Description: Load environment variables from .env file with security checks
# Returns:
#   0: Successfully loaded .env file
#   1: .env file not found or error loading
load_env() {
    local env_file="${PROJECT_DIR}/.env"
    if [ -f "$env_file" ]; then
        # Check file permissions (warn if world-readable)
        local perms
        perms=$(stat -c "%a" "$env_file" 2>/dev/null || echo "000")
        if [ "${perms:2:1}" != "0" ]; then
            log_warn ".env file has world-readable permissions (should be 600)"
        fi

        # Check for dangerous variable names that could override critical paths
        if grep -qE '^(PATH|LD_LIBRARY_PATH|LD_PRELOAD)=' "$env_file" 2>/dev/null; then
            log_warn ".env file contains potentially dangerous variables (PATH, LD_LIBRARY_PATH, LD_PRELOAD)"
        fi

        # Export variables from .env (skip comments and empty lines)
        set -a
        # shellcheck disable=SC1090
        source "$env_file"
        set +a
        return 0
    fi
    return 1
}

# Common constants (initialized after .env is loaded)
# Chrome CDP settings
# LYRA_BROWSER__CHROME_PORT from .env overrides default
export CHROME_PORT="${LYRA_BROWSER__CHROME_PORT:-9222}"

# Container settings
export CONTAINER_NAME="${LYRA_SCRIPT__CONTAINER_NAME:-lyra}"

# Timeouts (seconds)
export CONTAINER_TIMEOUT="${LYRA_SCRIPT__CONTAINER_TIMEOUT:-30}"
export CONNECT_TIMEOUT="${LYRA_SCRIPT__CONNECT_TIMEOUT:-30}"
export COMPLETION_THRESHOLD="${LYRA_SCRIPT__COMPLETION_THRESHOLD:-5}"

# Test result file path (inside container)
export TEST_RESULT_FILE="${LYRA_SCRIPT__TEST_RESULT_FILE:-/app/test_result.txt}"


