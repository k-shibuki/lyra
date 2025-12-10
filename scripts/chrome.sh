#!/bin/bash
# Start Chrome with remote debugging for Lancet (AI-friendly)
# Designed to coexist with existing Chrome sessions by using separate user-data-dir
#
# Usage:
#   ./scripts/chrome.sh              # Check status
#   ./scripts/chrome.sh check        # Check if debug port is available
#   ./scripts/chrome.sh start        # Start Chrome with remote debugging
#   ./scripts/chrome.sh stop         # Stop Lancet Chrome instance
#   ./scripts/chrome.sh diagnose     # Troubleshoot connection issues
#   ./scripts/chrome.sh fix          # Auto-fix WSL2 mirrored networking issues

set -e

ACTION="${1:-check}"
CHROME_PORT="${2:-9222}"

# Run PowerShell without environment variable leakage
# Note: Errors should be handled within PowerShell commands using try-catch
# This function suppresses stderr to prevent environment variable leakage
# If PowerShell command fails, it should return an error marker (e.g., "ERROR") in the output
run_ps() {
    env -i PATH="$PATH" powershell.exe -NoProfile -NonInteractive -Command "$1" 2>/dev/null
}

# Check if WSL2 mirrored networking mode is enabled
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
    if [ -z "$result" ] || [ "$result" = "ERROR" ]; then
        echo "ERROR"
        return 1
    fi
    
    echo "$result"
}

# Get current .wslconfig content
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

# Detect environment
detect_env() {
    if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
        echo "windows"
    elif grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl"
    else
        echo "linux"
    fi
}

ENV_TYPE=$(detect_env)

# Get Windows host IP for WSL2
get_windows_host() {
    if [ "$ENV_TYPE" = "wsl" ]; then
        ip route | grep default | awk '{print $3}'
    else
        echo "localhost"
    fi
}

# Try multiple endpoints to connect
try_connect() {
    local port="$1"
    local endpoints=("localhost" "127.0.0.1")
    
    if [ "$ENV_TYPE" = "wsl" ]; then
        endpoints+=("$(get_windows_host)")
    fi
    
    for host in "${endpoints[@]}"; do
        if curl -s --connect-timeout 1 "http://$host:$port/json/version" > /dev/null 2>&1; then
            echo "$host"
            return 0
        fi
    done
    return 1
}

# Check if socat is running
check_socat() {
    local pid_file="/tmp/lancet-socat.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null || echo "")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        else
            rm -f "$pid_file"
            return 1
        fi
    fi
    return 1
}

# Start socat port forward (WSL2 -> Windows Chrome)
start_socat() {
    local socat_port=19222
    local chrome_port=9222
    
    if check_socat > /dev/null; then
        echo "socat already running"
        return 0
    fi
    
    if ! command -v socat > /dev/null 2>&1; then
        echo "WARNING: socat not found. Install with: sudo apt-get install socat"
        return 1
    fi
    
    socat TCP-LISTEN:$socat_port,fork,reuseaddr TCP:localhost:$chrome_port > /dev/null 2>&1 &
    local socat_pid=$!
    echo "$socat_pid" > /tmp/lancet-socat.pid
    
    # Wait a moment for socat to start
    sleep 0.5
    
    if kill -0 "$socat_pid" 2>/dev/null; then
        echo "socat started (PID: $socat_pid, port: $socat_port -> $chrome_port)"
        return 0
    else
        rm -f /tmp/lancet-socat.pid
        echo "ERROR: Failed to start socat"
        return 1
    fi
}

# Stop socat port forward
stop_socat() {
    local pid_file="/tmp/lancet-socat.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null || echo "")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            echo "Stopped socat (PID: $pid)"
        fi
        rm -f "$pid_file"
    fi
}

# Get Chrome debug info
get_status() {
    local port="$1"
    local host
    
    # Check socat status (WSL2 only)
    if [ "$ENV_TYPE" = "wsl" ]; then
        if check_socat > /dev/null; then
            local socat_pid
            socat_pid=$(check_socat)
            echo "socat: RUNNING (PID: $socat_pid, port: 19222 -> 9222)"
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

# Start Chrome (WSL -> Windows)
start_chrome_wsl() {
    local port="$1"
    
    echo "STARTING"
    echo "Environment: WSL"
    echo "Port: $port"
    
    # Start socat port forward for Podman containers (if not already running)
    if [ "$port" = "9222" ]; then
        echo "Checking socat port forward..."
        if ! check_socat > /dev/null; then
            if start_socat; then
                echo "  ✓ socat port forward started (19222 -> 9222)"
            else
                echo "  ! socat port forward failed (containers may not be able to connect)"
            fi
        else
            echo "  ✓ socat already running"
        fi
    fi
    
    # Use a completely separate user-data-dir to avoid conflicts with existing Chrome
    # This allows running alongside user's normal Chrome session
    local lancet_data_dir='$env:LOCALAPPDATA\LancetChrome'
    
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
    
    if [ -z "$start_result" ] || [ "$start_result" = "ERROR" ]; then
        echo "ERROR"
        echo "Failed to start Chrome via PowerShell"
        echo "  → Check if Chrome is installed"
        echo "  → Check PowerShell permissions"
        return 1
    fi
    
    # Wait and try to connect
    echo "Waiting for Chrome..."
    local host=""
    for i in {1..30}; do
        sleep 0.5
        if host=$(try_connect "$port"); then
            echo "READY"
            echo "Host: $host:$port"
            echo "Connect: chromium.connect_over_cdp('http://$host:$port')"
            return 0
        fi
    done
    
    echo "TIMEOUT"
    echo "Chrome started but could not connect from WSL"
    echo ""
    echo "Ensure WSL2 mirrored networking is enabled:"
    echo "  ./scripts/chrome.sh fix"
    return 1
}

# Start Chrome (Linux native)
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
        --remote-debugging-port=$port \
        --user-data-dir="$data_dir" \
        --no-first-run \
        --no-default-browser-check \
        --disable-background-networking \
        --disable-sync \
        > /dev/null 2>&1 &
    
    echo "Waiting for Chrome..."
    for i in {1..20}; do
        sleep 0.5
        if try_connect "$port" > /dev/null; then
            echo "READY"
            echo "Connect: chromium.connect_over_cdp('http://localhost:$port')"
            return 0
        fi
    done
    
    echo "TIMEOUT"
    return 1
}

# Stop Lancet Chrome instance
stop_chrome() {
    local port="${1:-9222}"
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
        pid=$(lsof -ti :$port 2>/dev/null || true)
        if [ -n "$pid" ]; then
            kill -9 $pid 2>/dev/null || true
            echo "Stopped process $pid"
        fi
        echo "DONE"
    fi
}

# Diagnose connection issues (WSL2)
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
    echo "[5/5] WSL → Chrome connectivity..."
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
        echo "✗ Diagnostic checks failed (PowerShell errors encountered)."
        echo ""
        echo "Please check the error messages above and ensure:"
        echo "  - PowerShell is functioning correctly"
        echo "  - WSL2 is properly configured"
        return 1
    elif [ "$chrome_running" = "NOT_RUNNING" ]; then
        echo "✗ Chrome is not running."
        echo "  → Start with: ./scripts/chrome.sh start"
    elif [ "$port_listening" = "NOT_LISTENING" ]; then
        echo "✗ Chrome is running but not listening on port $port."
        echo "  → Chrome may not have started with --remote-debugging-port"
        echo "  → Run: ./scripts/chrome.sh stop && ./scripts/chrome.sh start"
    elif [ "$win_cdp" = "NOT_REACHABLE" ]; then
        echo "✗ Port is listening but CDP not responding."
        echo "  → Chrome may have crashed. Restart it."
    elif [ "$localhost_ok" = "yes" ]; then
        echo "✓ All checks passed! CDP is accessible."
        echo "  Connect via: localhost:$port"
    else
        echo "✗ WSL cannot reach Chrome on Windows."
        echo ""
        
        if [ "$mirrored_status" != "ENABLED" ]; then
            echo "SOLUTION: Enable mirrored networking mode"
            echo "  → Run: ./scripts/chrome.sh fix"
        else
            echo "Mirrored mode is enabled but connection failed."
            echo "  → Try: wsl.exe --shutdown"
            echo "  → Then reopen your WSL terminal"
        fi
    fi
}

# Auto-fix WSL2 connectivity issues using mirrored networking mode
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
        echo "✗ Unable to check configuration (PowerShell errors)."
        echo "  → Check PowerShell permissions and system configuration"
        return 1
    fi
    
    # If mirrored mode is enabled, just verify it works
    if [ "$mirrored_status" = "ENABLED" ]; then
        echo ""
        echo "[2/2] Mirrored mode is enabled. Testing connection..."
        if curl -s --connect-timeout 2 "http://localhost:$port/json/version" > /dev/null 2>&1; then
            echo "  ✓ Connection OK via localhost"
            echo ""
            echo "=== No fix needed ==="
            return 0
        else
            echo "  ✗ Connection failed. WSL restart may be required."
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
    
    echo "┌─────────────────────────────────────────────────────────────────┐"
    echo "│ Edit %USERPROFILE%\\.wslconfig in Windows                       │"
    echo "│ (Create the file if it doesn't exist)                          │"
    echo "└─────────────────────────────────────────────────────────────────┘"
    echo ""
    
    if [ -n "$current_config" ]; then
        # Check if [wsl2] section exists
        if echo "$current_config" | grep -q '^\[wsl2\]'; then
            echo "Add 'networkingMode=mirrored' under [wsl2] section:"
            echo ""
            echo "Current content:"
            echo "─────────────────"
            echo "$current_config"
            echo "─────────────────"
            echo ""
            echo "Add this line under [wsl2]:"
            echo "  networkingMode=mirrored"
        else
            echo "Add [wsl2] section with mirrored mode:"
            echo ""
            echo "─────────────────"
            echo "$current_config"
            echo ""
            echo "[wsl2]"
            echo "networkingMode=mirrored"
            echo "─────────────────"
        fi
    else
        echo "Create the file with this content:"
        echo ""
        echo "─────────────────"
        echo "[wsl2]"
        echo "networkingMode=mirrored"
        echo "─────────────────"
    fi
    
    echo ""
    echo "Or run this PowerShell command (non-admin):"
    echo ""
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
        echo "Default port: 9222"
        echo ""
        echo "The Chrome instance uses a separate profile (LancetChrome)"
        echo "so it won't interfere with your normal browsing."
        echo ""
        echo "WSL2 Note:"
        echo "  WSL2 requires mirrored networking mode for localhost access."
        echo "  Run 'fix' command if connection fails after WSL2 update."
        ;;
    
    *)
        echo "Unknown action: $ACTION"
        echo "Use: $0 {check|start|stop|diagnose|fix|help}"
        exit 1
        ;;
esac
