#!/bin/bash
# Lyra shell - environment loading

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


