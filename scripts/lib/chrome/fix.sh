#!/bin/bash
# Chrome Fix Functions
#
# Functions for auto-fixing WSL2 connectivity issues.

# Function: run_fix
# Description: Auto-fix WSL2 connectivity issues using mirrored networking mode
# Arguments:
#   $1: Port number (optional, for testing connection)
# Returns:
#   0: Fix instructions provided or no fix needed
#   1: Unable to check configuration or fix failed
run_fix() {
    local port="$1"
    
    if [ "$ENV_TYPE" != "wsl" ]; then
        echo "Fix is only needed for WSL2 environment"
        return 0
    fi
    
    echo "=== Lyra Chrome Auto-Fix (WSL2) ==="
    echo ""
    
    # Check current status
    echo "[1/2] Checking mirrored networking mode..."
    
    local mirrored_status
    mirrored_status=$(check_mirrored_mode)
    echo "  Status: $mirrored_status"
    
    # Check for errors in status check
    if [ "$mirrored_status" = "ERROR" ]; then
        echo ""
        echo "X Unable to check configuration (PowerShell errors)."
        echo "  -> Check PowerShell permissions and system configuration"
        return 1
    fi
    
    # If mirrored mode is enabled, just verify it works
    if [ "$mirrored_status" = "ENABLED" ]; then
        echo ""
        echo "[2/2] Mirrored mode is enabled. Testing connection..."
        if curl -s --connect-timeout 2 "http://localhost:$port/json/version" > /dev/null 2>&1; then
            echo "  OK Connection OK via localhost"
            echo ""
            echo "=== No fix needed ==="
            return 0
        else
            echo "  X Connection failed. WSL restart may be required."
            echo ""
            echo "Try:"
            echo "  wsl.exe --shutdown"
            echo "  # Then reopen your WSL terminal"
            return 1
        fi
    fi
    
    echo ""
    echo "[2/2] Mirrored mode not enabled. Here's how to fix it:"
    echo ""
    echo "  Benefits of mirrored networking mode:"
    echo "  - WSL and Windows share the same network stack"
    echo "  - localhost works directly (no port proxy needed)"
    echo "  - Chrome stays bound to 127.0.0.1 (secure)"
    echo ""
    
    # Get current .wslconfig content
    local current_config
    current_config=$(get_wslconfig_content)
    
    echo "+-------------------------------------------------------------------+"
    echo "| Edit %USERPROFILE%\\.wslconfig in Windows                         |"
    echo "| (Create the file if it doesn't exist)                            |"
    echo "+-------------------------------------------------------------------+"
    echo ""
    
    if [ -n "$current_config" ]; then
        # Check if [wsl2] section exists
        if echo "$current_config" | grep -q '^\[wsl2\]'; then
            echo "Add 'networkingMode=mirrored' under [wsl2] section:"
            echo ""
            echo "Current content:"
            echo "-----------------"
            echo "$current_config"
            echo "-----------------"
            echo ""
            echo "Add this line under [wsl2]:"
            echo "  networkingMode=mirrored"
        else
            echo "Add [wsl2] section with mirrored mode:"
            echo ""
            echo "-----------------"
            echo "$current_config"
            echo ""
            echo "[wsl2]"
            echo "networkingMode=mirrored"
            echo "-----------------"
        fi
    else
        echo "Create the file with this content:"
        echo ""
        echo "-----------------"
        echo "[wsl2]"
        echo "networkingMode=mirrored"
        echo "-----------------"
    fi
    
    echo ""
    echo "Or run this PowerShell command (non-admin):"
    echo ""
    # shellcheck disable=SC2016
    echo '  $c = "$env:USERPROFILE\.wslconfig"; if (Test-Path $c) { Add-Content $c "`nnetworkingMode=mirrored" } else { Set-Content $c "[wsl2]`nnetworkingMode=mirrored" }'
    echo ""
    echo "After editing:"
    echo "  1. Save the file"
    echo "  2. Restart WSL: wsl.exe --shutdown"
    echo "  3. Reopen terminal and verify: make chrome"
    echo ""
    echo "SECURITY NOTE:"
    echo "  - Mirrored mode does NOT disable any firewall"
    echo "  - Chrome remains bound to 127.0.0.1 (not exposed to LAN)"
    echo "  - Windows Defender firewall continues to protect all ports"
    echo "  - Only changes network topology (WSL shares Windows network stack)"
}

