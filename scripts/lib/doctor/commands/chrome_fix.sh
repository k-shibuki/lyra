#!/bin/bash
# Doctor Chrome Fix Command Handler
#
# Function for handling doctor.sh chrome-fix command.
# This is a thin wrapper that calls scripts/chrome.sh fix.

# Function: cmd_chrome_fix
# Description: Fix WSL2 Chrome networking issues (delegates to chrome.sh fix)
# Returns:
#   Exit code from chrome.sh fix
cmd_chrome_fix() {
    # Guard: chrome-fix must run on host, not inside container
    if ! require_host_execution "doctor chrome-fix" "fixes WSL2 Chrome networking" "return"; then
        return "$EXIT_CONFIG"
    fi
    
    # Get script directory
    local doctor_script_dir
    doctor_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    local chrome_script="${doctor_script_dir}/chrome.sh"
    
    if [[ ! -f "$chrome_script" ]]; then
        output_error "$EXIT_NOT_FOUND" "chrome.sh not found" "path=$chrome_script"
    fi
    
    if [[ "$(detect_env)" != "wsl" ]]; then
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            output_error "$EXIT_CONFIG" "chrome-fix is only for WSL2 environment" "env=$(detect_env)"
        else
            echo "chrome-fix is only needed for WSL2 environment."
            echo "Current environment: $(detect_env)"
            return "$EXIT_CONFIG"
        fi
    fi
    
    # Call chrome.sh fix (preserve global flags)
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        LYRA_OUTPUT_JSON=true "$chrome_script" fix
    else
        "$chrome_script" fix
    fi
}

