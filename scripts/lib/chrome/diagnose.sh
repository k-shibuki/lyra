#!/bin/bash
# Chrome Diagnostics Functions
#
# Functions for diagnosing Chrome CDP connection issues.

# Function: run_diagnose
# Description: Diagnose Chrome CDP connection issues (WSL2)
# Arguments:
#   $1: Port number to diagnose
# Returns:
#   0: Diagnostics completed successfully
#   1: Diagnostic errors encountered
run_diagnose() {
    local port="$1"
    
    echo "=== Lyra Chrome Diagnostics ==="
    echo ""
    echo "Environment: $ENV_TYPE"
    echo "Port: $port"
    echo ""
    
    if [ "$ENV_TYPE" != "wsl" ]; then
        echo "Diagnostics are designed for WSL2 environment."
        echo ""
        return 0
    fi
    
    local wsl_gateway
    wsl_gateway=$(get_windows_host)
    echo "WSL2 Gateway IP: $wsl_gateway"
    echo ""
    
    # Check 1: Is Chrome process running on Windows?
    echo "[1/5] Chrome process on Windows..."
    local chrome_running
    chrome_running=$(run_ps "
        \$ErrorActionPreference = 'Stop'
        try {
            \$proc = Get-Process -Name chrome -ErrorAction SilentlyContinue
            if (\$proc) { 'RUNNING' } else { 'NOT_RUNNING' }
        } catch {
            'ERROR'
        }
    " 2>/dev/null | tr -d '\r\n')
    
    if [ -z "$chrome_running" ] || [ "$chrome_running" = "ERROR" ]; then
        echo "  Chrome process: ERROR (unable to check)"
        chrome_running="ERROR"
    else
        echo "  Chrome process: $chrome_running"
    fi
    
    # Check 2: Is port listening on Windows localhost?
    echo ""
    echo "[2/5] Port $port listening on Windows..."
    local port_listening
    port_listening=$(run_ps "
        \$ErrorActionPreference = 'Stop'
        try {
            \$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if (\$conn) { 'LISTENING' } else { 'NOT_LISTENING' }
        } catch {
            'ERROR'
        }
    " 2>/dev/null | tr -d '\r\n')
    
    if [ -z "$port_listening" ] || [ "$port_listening" = "ERROR" ]; then
        echo "  Port status: ERROR (unable to check)"
        port_listening="ERROR"
    else
        echo "  Port status: $port_listening"
    fi
    
    # Check 3: Can we reach localhost:port from Windows?
    echo ""
    echo "[3/5] CDP endpoint on Windows localhost..."
    local win_cdp
    win_cdp=$(run_ps "
        \$ErrorActionPreference = 'Stop'
        try {
            \$null = Invoke-WebRequest -Uri 'http://127.0.0.1:$port/json/version' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            'REACHABLE'
        } catch [System.Net.WebException] {
            # Network/HTTP errors - endpoint not reachable
            'NOT_REACHABLE'
        } catch {
            # PowerShell command errors or other exceptions
            'ERROR'
        }
    " 2>/dev/null | tr -d '\r\n')
    
    if [ -z "$win_cdp" ] || [ "$win_cdp" = "ERROR" ]; then
        echo "  Windows localhost: ERROR (unable to check)"
        win_cdp="ERROR"
    else
        echo "  Windows localhost: $win_cdp"
    fi
    
    # Check 4: Mirrored networking mode
    echo ""
    echo "[4/5] Mirrored networking mode..."
    local mirrored_status
    mirrored_status=$(check_mirrored_mode)
    echo "  Status: $mirrored_status"
    
    # Check 5: Can WSL reach Chrome?
    echo ""
    echo "[5/5] WSL -> Chrome connectivity..."
    local localhost_ok="no"
    
    # With mirrored mode, localhost should work directly
    if curl -s --connect-timeout 2 "http://localhost:$port/json/version" > /dev/null 2>&1; then
        echo "  localhost: OK"
        localhost_ok="yes"
    else
        echo "  localhost: FAILED"
    fi
    
    # Summary and recommendations
    echo ""
    echo "=== Summary ==="
    
    # Check for diagnostic errors first
    local has_errors="no"
    if [ "$chrome_running" = "ERROR" ] || [ "$port_listening" = "ERROR" ] || [ "$win_cdp" = "ERROR" ] || [ "$mirrored_status" = "ERROR" ]; then
        has_errors="yes"
    fi
    
    if [ "$has_errors" = "yes" ]; then
        echo "X Diagnostic checks failed (PowerShell errors encountered)."
        echo ""
        echo "Please check the error messages above and ensure:"
        echo "  - PowerShell is functioning correctly"
        echo "  - WSL2 is properly configured"
        return 1
    elif [ "$chrome_running" = "NOT_RUNNING" ]; then
        echo "X Chrome is not running."
        echo "  -> Start with: make chrome-start"
    elif [ "$port_listening" = "NOT_LISTENING" ]; then
        echo "X Chrome is running but not listening on port $port."
        echo "  -> Chrome may not have started with --remote-debugging-port"
        echo "  -> Run: make chrome-stop && make chrome-start"
    elif [ "$win_cdp" = "NOT_REACHABLE" ]; then
        echo "X Port is listening but CDP not responding."
        echo "  -> Chrome may have crashed. Restart it."
    elif [ "$localhost_ok" = "yes" ]; then
        echo "OK All checks passed! CDP is accessible."
        echo "  Connect via: localhost:$port"
    else
        echo "X WSL cannot reach Chrome on Windows."
        echo ""
        
        if [ "$mirrored_status" != "ENABLED" ]; then
            echo "SOLUTION: Enable mirrored networking mode"
            echo "  -> Run: make doctor-chrome-fix"
        else
            echo "Mirrored mode is enabled but connection failed."
            echo "  -> Try: wsl.exe --shutdown"
            echo "  -> Then reopen your WSL terminal"
        fi
    fi
}

