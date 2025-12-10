#!/bin/bash
# Start Chrome with remote debugging for Lancet (AI-friendly)
# Designed to coexist with existing Chrome sessions by using separate user-data-dir
#
# Usage:
#   ./scripts/chrome.sh              # Check status
#   ./scripts/chrome.sh check        # Check if debug port is available
#   ./scripts/chrome.sh start        # Start Chrome with remote debugging
#   ./scripts/chrome.sh stop         # Stop Lancet Chrome instance
#   ./scripts/chrome.sh setup        # One-time setup (port proxy, firewall)

set -e

ACTION="${1:-check}"
CHROME_PORT="${2:-9222}"

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

# Get Chrome debug info
get_status() {
    local port="$1"
    local host
    
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
    
    # Use a completely separate user-data-dir to avoid conflicts with existing Chrome
    # This allows running alongside user's normal Chrome session
    local lancet_data_dir='$env:LOCALAPPDATA\LancetChrome'
    
    # Start Chrome with separate profile via PowerShell
    # Note: Bind to 127.0.0.1 only for security. WSL2 access requires port proxy.
    powershell.exe -Command "
        \$dataDir = [Environment]::GetFolderPath('LocalApplicationData') + '\LancetChrome'
        if (-not (Test-Path \$dataDir)) { New-Item -ItemType Directory -Path \$dataDir -Force | Out-Null }
        
        Start-Process 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList @(
            '--remote-debugging-port=$port',
            '--remote-debugging-address=127.0.0.1',
            \"--user-data-dir=\$dataDir\",
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-background-networking',
            '--disable-sync'
        )
    " 2>/dev/null
    
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
    
    # If localhost didn't work, try setting up port proxy
    echo "Direct connection failed. Attempting port proxy setup..."
    setup_port_proxy "$port"
    
    # Try again after port proxy
    for i in {1..10}; do
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
    echo "Manual fix: Run in Admin PowerShell:"
    echo "  netsh interface portproxy add v4tov4 listenaddress=$(get_windows_host) listenport=$port connectaddress=127.0.0.1 connectport=$port"
    return 1
}

# Setup port proxy (requires admin, but try anyway)
setup_port_proxy() {
    local port="$1"
    local wsl_gateway
    wsl_gateway=$(get_windows_host)
    
    # Try to set up port proxy (may fail without admin rights)
    powershell.exe -Command "
        try {
            netsh interface portproxy add v4tov4 listenaddress=$wsl_gateway listenport=$port connectaddress=127.0.0.1 connectport=$port 2>\$null
            Write-Host 'Port proxy configured'
        } catch {
            # Silently fail - will show manual instructions
        }
    " 2>/dev/null || true
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
    
    if [ "$ENV_TYPE" = "wsl" ]; then
        # Find process listening on debug port and kill it
        powershell.exe -Command "
            \$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if (\$conn) {
                Stop-Process -Id \$conn.OwningProcess -Force -ErrorAction SilentlyContinue
                Write-Host 'Stopped process on port $port'
            } else {
                Write-Host 'No process found on port $port'
            }
        " 2>/dev/null || true
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

# One-time setup
run_setup() {
    local port="$1"
    
    if [ "$ENV_TYPE" != "wsl" ]; then
        echo "Setup is only needed for WSL environment"
        return 0
    fi
    
    local wsl_gateway
    wsl_gateway=$(get_windows_host)
    
    echo "=== Lancet Chrome Setup (WSL2) ==="
    echo ""
    echo "SECURITY NOTE:"
    echo "  Chrome binds to 127.0.0.1 only (not exposed to LAN)."
    echo "  Port proxy forwards WSL2 traffic to localhost."
    echo ""
    echo "This setup requires Administrator privileges."
    echo "Run the following in an Admin PowerShell:"
    echo ""
    echo "# 1. Port proxy (REQUIRED for WSL2 access)"
    echo "netsh interface portproxy add v4tov4 listenaddress=$wsl_gateway listenport=$port connectaddress=127.0.0.1 connectport=$port"
    echo ""
    echo "# 2. Firewall rule (allows WSL2 subnet only)"
    echo "New-NetFirewallRule -DisplayName 'Chrome Debug WSL' -Direction Inbound -LocalPort $port -Protocol TCP -Action Allow -RemoteAddress 172.16.0.0/12"
    echo ""
    echo "WARNING: Do NOT use -RemoteAddress Any. This limits access to WSL2 subnet."
    echo ""
    echo "After running these commands, use: ./scripts/chrome.sh start"
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
    
    setup)
        run_setup "$CHROME_PORT"
        ;;
    
    help|--help|-h)
        echo "Lancet Chrome Manager (AI-friendly)"
        echo ""
        echo "Usage: $0 {check|start|stop|setup} [port]"
        echo ""
        echo "Commands:"
        echo "  check   Check if Chrome debug port is available (default)"
        echo "  start   Start Chrome with remote debugging (separate profile)"
        echo "  stop    Stop Lancet Chrome instance"
        echo "  setup   Show one-time setup commands (WSL only)"
        echo ""
        echo "Default port: 9222"
        echo ""
        echo "The Chrome instance uses a separate profile (LancetChrome)"
        echo "so it won't interfere with your normal browsing."
        ;;
    
    *)
        echo "Unknown action: $ACTION"
        echo "Use: $0 {check|start|stop|setup|help}"
        exit 1
        ;;
esac
