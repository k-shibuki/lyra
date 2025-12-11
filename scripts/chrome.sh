#!/bin/bash
# Lancet Chrome Manager (AI-friendly)
#
# Start Chrome with remote debugging for Lancet.
# Designed to coexist with existing Chrome sessions by using separate user-data-dir.
#
# Usage:
#   ./scripts/chrome.sh              # Check status
#   ./scripts/chrome.sh check        # Check if debug port is available
#   ./scripts/chrome.sh start        # Start Chrome with remote debugging
#   ./scripts/chrome.sh stop         # Stop Lancet Chrome instance
#   ./scripts/chrome.sh diagnose     # Troubleshoot connection issues
#   ./scripts/chrome.sh fix          # Auto-fix WSL2 mirrored networking issues

set -euo pipefail

# =============================================================================
# INITIALIZATION
# =============================================================================

# Source common functions and load .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# Enable debug mode if DEBUG=1
enable_debug_mode

# Set up error handler
trap 'cleanup_on_error ${LINENO}' ERR

# Command line arguments (override .env defaults)
ACTION="${1:-check}"
CHROME_PORT_ARG="${2:-}"

# Use argument if provided, otherwise use .env value (from common.sh)
if [ -n "$CHROME_PORT_ARG" ]; then
    CHROME_PORT="$CHROME_PORT_ARG"
fi
# CHROME_PORT is already set from common.sh with .env override

# =============================================================================
# CONSTANTS
# =============================================================================

# PID file for socat process tracking
SOCAT_PID_FILE="/tmp/lancet-socat.pid"

# Connection attempt settings
CURL_TIMEOUT=1
STARTUP_WAIT_ITERATIONS=30
STARTUP_WAIT_INTERVAL=0.5

# =============================================================================
# POWERSHELL UTILITIES (WSL only)
# =============================================================================

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

# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================

# Use common environment detection function
ENV_TYPE=$(detect_env)

# =============================================================================
# NETWORKING UTILITIES
# =============================================================================

# Function: try_connect
# Description: Try multiple endpoints to connect to Chrome CDP
# Arguments:
#   $1: Port number to connect to
# Returns:
#   0: Success, outputs hostname that works
#   1: Failed to connect to any endpoint
try_connect() {
    local port="$1"
    local endpoints=("localhost" "127.0.0.1")
    
    if [ "$ENV_TYPE" = "wsl" ]; then
        endpoints+=("$(get_windows_host)")
    fi
    
    for host in "${endpoints[@]}"; do
        if curl -s --connect-timeout "$CURL_TIMEOUT" "http://$host:$port/json/version" > /dev/null 2>&1; then
            echo "$host"
            return 0
        fi
    done
    return 1
}

# Function: try_connect_with_backoff
# Description: Try to connect to Chrome CDP with exponential backoff
# Arguments:
#   $1: Port number to connect to
#   $2: Maximum attempts (default: 5)
#   $3: Base delay in seconds (default: 0.5)
#   $4: Maximum delay cap in seconds (default: 5.0)
# Returns:
#   0: Success, outputs hostname that works
#   1: Failed to connect after all attempts
try_connect_with_backoff() {
    local port="$1"
    local max_attempts="${2:-5}"
    local base_delay="${3:-0.5}"
    local max_delay="${4:-5.0}"  # Maximum delay cap (default: 5 seconds)
    local endpoints=("localhost" "127.0.0.1")
    
    if [ "$ENV_TYPE" = "wsl" ]; then
        endpoints+=("$(get_windows_host)")
    fi
    
    local delay=$base_delay
    for ((attempt=1; attempt<=max_attempts; attempt++)); do
        for host in "${endpoints[@]}"; do
            if curl -s --connect-timeout "$CURL_TIMEOUT" "http://$host:$port/json/version" > /dev/null 2>&1; then
                echo "$host"
                return 0
            fi
        done
        # Wait before next attempt (except on last attempt)
        if [ "$attempt" -lt "$max_attempts" ]; then
            sleep "$delay"
            # Exponential backoff: double the delay each time, capped at max_delay
            delay=$(awk "BEGIN {print ($delay * 2) < $max_delay ? ($delay * 2) : $max_delay}")
        fi
    done
    return 1
}

# =============================================================================
# SOCAT PORT FORWARDING (WSL2 only)
# Part of NETWORKING UTILITIES
# =============================================================================

# Function: check_socat
# Description: Check if socat port forwarding process is running
# Returns:
#   0: socat is running, outputs PID
#   1: socat is not running
check_socat() {
    if [ -f "$SOCAT_PID_FILE" ]; then
        local pid
        pid=$(cat "$SOCAT_PID_FILE" 2>/dev/null || echo "")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        else
            rm -f "$SOCAT_PID_FILE"
            return 1
        fi
    fi
    return 1
}

# Function: start_socat
# Description: Start socat port forward (WSL2 -> Windows Chrome)
#             Forwards SOCAT_PORT to the base Chrome port (9222)
# Returns:
#   0: socat started successfully
#   1: Failed to start socat
start_socat() {
    local base_chrome_port=9222
    
    if check_socat > /dev/null; then
        echo "socat already running"
        return 0
    fi
    
    if ! command -v socat > /dev/null 2>&1; then
        log_warn "socat not found. Install with: sudo apt-get install socat"
        return 1
    fi
    
    socat TCP-LISTEN:"$SOCAT_PORT",fork,reuseaddr TCP:localhost:"$base_chrome_port" > /dev/null 2>&1 &
    local socat_pid=$!
    echo "$socat_pid" > "$SOCAT_PID_FILE"
    
    # Wait a moment for socat to start
    sleep 0.5
    
    if kill -0 "$socat_pid" 2>/dev/null; then
        echo "socat started (PID: $socat_pid, port: $SOCAT_PORT -> $base_chrome_port)"
        return 0
    else
        rm -f "$SOCAT_PID_FILE"
        log_error "Failed to start socat"
        log_error "Check if port $SOCAT_PORT is available: netstat -tuln | grep $SOCAT_PORT || ss -tuln | grep $SOCAT_PORT"
        log_error "Check socat installation: socat -V"
        return 1
    fi
}

# Function: stop_socat
# Description: Stop socat port forwarding process
# Returns:
#   0: Success (or socat was not running)
stop_socat() {
    if [ -f "$SOCAT_PID_FILE" ]; then
        local pid
        pid=$(cat "$SOCAT_PID_FILE" 2>/dev/null || echo "")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            echo "Stopped socat (PID: $pid)"
        fi
        rm -f "$SOCAT_PID_FILE"
    fi
}

# =============================================================================
# STATUS AND INFO
# Part of CHROME MANAGEMENT
# =============================================================================

# Function: get_status
# Description: Get Chrome debug port status and connection information
# Arguments:
#   $1: Port number to check
# Returns:
#   0: Chrome is ready, outputs connection info
#   1: Chrome is not ready
get_status() {
    local port="$1"
    local host
    
    # Check socat status (WSL2 only)
    if [ "$ENV_TYPE" = "wsl" ]; then
        if check_socat > /dev/null; then
            local socat_pid
            socat_pid=$(check_socat)
            echo "socat: RUNNING (PID: $socat_pid, port: $SOCAT_PORT -> 9222)"
        else
            echo "socat: NOT_RUNNING"
        fi
    fi
    
    if host=$(try_connect "$port"); then
        local info
        info=$(curl -s --connect-timeout 2 "http://$host:$port/json/version" 2>/dev/null)
        echo "READY"
        echo "Host: $host:$port"
        echo "Browser: $(echo "$info" | grep -o '"Browser":"[^"]*"' | cut -d'"' -f4)"
        echo "Connect: chromium.connect_over_cdp('http://$host:$port')"
        return 0
    else
        echo "NOT_READY"
        echo "Port: $port"
        return 1
    fi
}

# =============================================================================
# CHROME MANAGEMENT
# =============================================================================

# Function: start_chrome_wsl
# Description: Start Chrome with remote debugging on Windows (from WSL)
# Arguments:
#   $1: Port number for remote debugging
# Returns:
#   0: Chrome started and ready
#   1: Failed to start Chrome or connect
start_chrome_wsl() {
    local port="$1"
    
    echo "STARTING"
    echo "Environment: WSL"
    echo "Port: $port"
    
    # Start socat port forward for Podman containers (if not already running)
    # Only needed when using the base Chrome port
    if [ "$port" = "9222" ]; then
        echo "Checking socat port forward..."
        if ! check_socat > /dev/null; then
            if start_socat; then
                echo "  ✓ socat port forward started ($SOCAT_PORT -> 9222)"
            else
                echo "  ! socat port forward failed (containers may not be able to connect)"
            fi
        else
            echo "  ✓ socat already running"
        fi
    fi
    
    # Start Chrome with separate profile via PowerShell
    # Note: Bind to 127.0.0.1 only for security. WSL2 mirrored mode allows direct localhost access.
    local start_result
    start_result=$(run_ps "
        \$ErrorActionPreference = 'Stop'
        try {
            \$dataDir = [Environment]::GetFolderPath('LocalApplicationData') + '\LancetChrome'
            if (-not (Test-Path \$dataDir)) { New-Item -ItemType Directory -Path \$dataDir -Force | Out-Null }
            
            \$proc = Start-Process 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList @(
                '--remote-debugging-port=$port',
                '--remote-debugging-address=127.0.0.1',
                \"--user-data-dir=\$dataDir\",
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-background-networking',
                '--disable-sync'
            ) -PassThru -ErrorAction Stop
            'SUCCESS'
        } catch {
            'ERROR'
        }
    " 2>/dev/null | tr -d '\r\n')
    
    local start_result_value="${start_result:-}"
    if [ -z "$start_result_value" ] || [ "$start_result_value" = "ERROR" ]; then
        echo "ERROR"
        echo "Failed to start Chrome via PowerShell"
        echo "  -> Check if Chrome is installed at: C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
        echo "  -> Check PowerShell permissions"
        echo "  -> Try running PowerShell manually to verify it works"
        log_error "PowerShell command failed or returned ERROR"
        return 1
    fi
    
    # Wait and try to connect with exponential backoff
    echo "Waiting for Chrome..."
    local host=""
    host=$(try_connect_with_backoff "$port" "$STARTUP_WAIT_ITERATIONS" "$STARTUP_WAIT_INTERVAL" || true)
    if [ -n "${host:-}" ]; then
        echo "READY"
        echo "Host: $host:$port"
        echo "Connect: chromium.connect_over_cdp('http://$host:$port')"
        return 0
    fi
    
    echo "TIMEOUT"
    echo "Chrome started but could not connect from WSL"
    echo ""
    echo "Ensure WSL2 mirrored networking is enabled:"
    echo "  ./scripts/chrome.sh fix"
    return 1
}

# Function: start_chrome_linux
# Description: Start Chrome with remote debugging on Linux native
# Arguments:
#   $1: Port number for remote debugging
# Returns:
#   0: Chrome started and ready
#   1: Failed to start Chrome or connect
start_chrome_linux() {
    local port="$1"
    
    local chrome_path
    chrome_path=$(which google-chrome || which chromium-browser || which chromium 2>/dev/null || echo "")
    
    if [ -z "$chrome_path" ]; then
        echo "ERROR"
        echo "Chrome/Chromium not found"
        return 1
    fi
    
    echo "STARTING"
    echo "Environment: Linux"
    echo "Port: $port"
    
    # Use separate data dir
    local data_dir="$HOME/.local/share/lancet-chrome"
    mkdir -p "$data_dir"
    
    "$chrome_path" \
        --remote-debugging-port="$port" \
        --user-data-dir="$data_dir" \
        --no-first-run \
        --no-default-browser-check \
        --disable-background-networking \
        --disable-sync \
        > /dev/null 2>&1 &
    
    echo "Waiting for Chrome..."
    local host=""
    host=$(try_connect_with_backoff "$port" 20 "$STARTUP_WAIT_INTERVAL" || true)
    if [ -n "${host:-}" ]; then
        echo "READY"
        echo "Connect: chromium.connect_over_cdp('http://${host}:$port')"
        return 0
    fi
    
    echo "TIMEOUT"
    return 1
}

# Function: stop_chrome
# Description: Stop Lancet Chrome instance
# Arguments:
#   $1: Port number (optional, defaults to CHROME_PORT)
# Returns:
#   0: Success
stop_chrome() {
    local port="${1:-$CHROME_PORT}"
    echo "STOPPING"
    
    # Stop socat port forward (WSL2 only)
    if [ "$ENV_TYPE" = "wsl" ] && [ "$port" = "9222" ]; then
        stop_socat
    fi
    
    if [ "$ENV_TYPE" = "wsl" ]; then
        # Find process listening on debug port and kill it
        local stop_result
        stop_result=$(run_ps "
            \$ErrorActionPreference = 'Stop'
            try {
                \$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
                if (\$conn) {
                    Stop-Process -Id \$conn.OwningProcess -Force -ErrorAction SilentlyContinue
                    'Stopped process on port $port'
                } else {
                    'No process found on port $port'
                }
            } catch {
                'ERROR'
            }
        " 2>/dev/null | tr -d '\r\n')
        
        if [ -n "$stop_result" ] && [ "$stop_result" != "ERROR" ]; then
            echo "$stop_result"
        fi
        echo "DONE"
    else
        # Find process by port on Linux
        local pid
        pid=$(lsof -ti :"$port" 2>/dev/null || true)
        if [ -n "$pid" ]; then
            kill -9 "$pid" 2>/dev/null || true
            echo "Stopped process $pid"
        fi
        echo "DONE"
    fi
}

# =============================================================================
# DIAGNOSTICS
# =============================================================================

# Function: run_diagnose
# Description: Diagnose Chrome CDP connection issues (WSL2)
# Arguments:
#   $1: Port number to diagnose
# Returns:
#   0: Diagnostics completed successfully
#   1: Diagnostic errors encountered
run_diagnose() {
    local port="$1"
    
    echo "=== Lancet Chrome Diagnostics ==="
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
        echo "  -> Start with: ./scripts/chrome.sh start"
    elif [ "$port_listening" = "NOT_LISTENING" ]; then
        echo "X Chrome is running but not listening on port $port."
        echo "  -> Chrome may not have started with --remote-debugging-port"
        echo "  -> Run: ./scripts/chrome.sh stop && ./scripts/chrome.sh start"
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
            echo "  -> Run: ./scripts/chrome.sh fix"
        else
            echo "Mirrored mode is enabled but connection failed."
            echo "  -> Try: wsl.exe --shutdown"
            echo "  -> Then reopen your WSL terminal"
        fi
    fi
}

# =============================================================================
# AUTO-FIX
# =============================================================================

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
    
    echo "=== Lancet Chrome Auto-Fix (WSL2) ==="
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
    echo "  3. Reopen terminal and verify: ./scripts/chrome.sh check"
    echo ""
    echo "SECURITY NOTE:"
    echo "  - Mirrored mode does NOT disable any firewall"
    echo "  - Chrome remains bound to 127.0.0.1 (not exposed to LAN)"
    echo "  - Windows Defender firewall continues to protect all ports"
    echo "  - Only changes network topology (WSL shares Windows network stack)"
}

# =============================================================================
# HELP
# =============================================================================

show_help() {
    echo "Lancet Chrome Manager (AI-friendly)"
    echo ""
    echo "Usage: $0 {check|start|stop|diagnose|fix} [port]"
    echo ""
    echo "Commands:"
    echo "  check     Check if Chrome debug port is available (default)"
    echo "  start     Start Chrome with remote debugging (separate profile)"
    echo "  stop      Stop Lancet Chrome instance"
    echo "  diagnose  Troubleshoot connection issues (WSL only)"
    echo "  fix       Auto-generate fix commands for WSL2 mirrored networking"
    echo ""
    echo "Default port: $CHROME_PORT (from .env: LANCET_BROWSER__CHROME_PORT)"
    echo ""
    echo "The Chrome instance uses a separate profile (LancetChrome)"
    echo "so it won't interfere with your normal browsing."
    echo ""
    echo "WSL2 Note:"
    echo "  WSL2 requires mirrored networking mode for localhost access."
    echo "  Run 'fix' command if connection fails after WSL2 update."
}

# =============================================================================
# MAIN
# =============================================================================

case "$ACTION" in
    check|status)
        get_status "$CHROME_PORT"
        ;;
    
    start)
        # Check if already running
        if try_connect "$CHROME_PORT" > /dev/null 2>&1; then
            echo "ALREADY_RUNNING"
            get_status "$CHROME_PORT"
            exit 0
        fi
        
        case "$ENV_TYPE" in
            wsl)
                start_chrome_wsl "$CHROME_PORT"
                ;;
            linux)
                start_chrome_linux "$CHROME_PORT"
                ;;
            windows)
                echo "ERROR"
                echo "Run from WSL or Linux, or use PowerShell directly on Windows"
                exit 1
                ;;
        esac
        ;;
    
    stop)
        stop_chrome "$CHROME_PORT"
        ;;
    
    diagnose|diag)
        run_diagnose "$CHROME_PORT"
        ;;
    
    fix)
        run_fix "$CHROME_PORT"
        ;;
    
    help|--help|-h)
        show_help
        ;;
    
    *)
        echo "Unknown action: $ACTION"
        echo "Use: $0 {check|start|stop|diagnose|fix|help}"
        exit 1
        ;;
esac
