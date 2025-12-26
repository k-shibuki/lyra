#!/bin/bash
# Chrome PowerShell Utilities (WSL only)
#
# Functions for interacting with Windows PowerShell from WSL2.

# Function: run_ps
# Description: Run PowerShell command without environment variable leakage
# Arguments:
#   $1: PowerShell command to execute
# Returns:
#   Outputs PowerShell command result (stdout only)
# Note: Errors should be handled within PowerShell commands using try-catch.
#       This function suppresses stderr to prevent environment variable leakage.
#       If PowerShell command fails, it should return an error marker (e.g., "ERROR") in the output.
run_ps() {
    env -i PATH="$PATH" powershell.exe -NoProfile -NonInteractive -Command "$1" 2>/dev/null
}

# Function: check_mirrored_mode
# Description: Check if WSL2 mirrored networking mode is enabled
# Returns:
#   "ENABLED" if mirrored mode is enabled
#   "DISABLED" if mirrored mode is disabled
#   "NO_CONFIG" if .wslconfig file doesn't exist
#   "ERROR" if check failed
check_mirrored_mode() {
    local result
    result=$(run_ps "
        \$ErrorActionPreference = 'Stop'
        try {
            \$wslconfig = \"\$env:USERPROFILE\\.wslconfig\"
            if (Test-Path \$wslconfig) {
                \$content = Get-Content \$wslconfig -Raw -ErrorAction Stop
                if (\$content -match 'networkingMode\s*=\s*mirrored') {
                    'ENABLED'
                } else {
                    'DISABLED'
                }
            } else {
                'NO_CONFIG'
            }
        } catch {
            'ERROR'
        }
    " 2>/dev/null | tr -d '\r\n')
    
    # If result is empty or ERROR, return ERROR
    # Use ${result:-} to handle empty string safely with set -u
    local result_value="${result:-}"
    if [ -z "$result_value" ] || [ "$result_value" = "ERROR" ]; then
        echo "ERROR"
        return 1
    fi
    
    echo "$result_value"
}

# Function: get_wslconfig_content
# Description: Get current .wslconfig file content from Windows
# Returns:
#   Content of .wslconfig file, or empty string on error
get_wslconfig_content() {
    run_ps "
        \$ErrorActionPreference = 'Stop'
        try {
            \$wslconfig = \"\$env:USERPROFILE\\.wslconfig\"
            if (Test-Path \$wslconfig) {
                Get-Content \$wslconfig -Raw -ErrorAction Stop
            }
        } catch {
            # Return empty string on error
            ''
        }
    " 2>/dev/null | tr -d '\r'
}

