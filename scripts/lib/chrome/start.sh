#!/bin/bash
# Chrome Start Functions
#
# Functions for starting Chrome with remote debugging.
# Supports both single-instance (legacy) and worker pool modes.

# =============================================================================
# WORKER POOL FUNCTIONS (Dynamic Chrome Pool)
# =============================================================================

# Function: start_chrome_worker_wsl
# Description: Start Chrome for a specific worker on Windows (from WSL)
# Arguments:
#   $1: Worker ID (0-indexed)
#   $2: Port number for remote debugging
#   $3: Profile name (e.g., "Lyra-00")
# Returns:
#   0: Chrome started and ready
#   1: Failed to start Chrome or connect
start_chrome_worker_wsl() {
    local worker_id="$1"
    local port="$2"
    local profile="$3"
    
    # Start Chrome with worker-specific profile via PowerShell
    # Note: Bind to 127.0.0.1 only for security. WSL2 mirrored mode allows direct localhost access.
    local start_result
    start_result=$(run_ps "
        \$ErrorActionPreference = 'Stop'
        try {
            \$baseDir = [Environment]::GetFolderPath('LocalApplicationData') + '\LyraChrome'
            \$dataDir = \"\$baseDir\\$profile\"
            if (-not (Test-Path \$dataDir)) { New-Item -ItemType Directory -Path \$dataDir -Force | Out-Null }
            
            \$proc = Start-Process 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList @(
                '--remote-debugging-port=$port',
                '--remote-debugging-address=127.0.0.1',
                \"--user-data-dir=\$dataDir\",
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-background-networking',
                '--disable-sync',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding'
            ) -PassThru -ErrorAction Stop
            'SUCCESS'
        } catch {
            'ERROR'
        }
    " 2>/dev/null | tr -d '\r\n')
    
    local start_result_value="${start_result:-}"
    if [ -z "$start_result_value" ] || [ "$start_result_value" = "ERROR" ]; then
        return 1
    fi

    # Wait and try to connect with exponential backoff
    local host=""
    host=$(try_connect_with_backoff "$port" "$STARTUP_TIMEOUT_WSL" "$BACKOFF_BASE_DELAY" "$BACKOFF_MAX_DELAY" || true)
    if [ -n "${host:-}" ]; then
        return 0
    fi

    return 1
}

# Function: start_chrome_worker_linux
# Description: Start Chrome for a specific worker on Linux native
# Arguments:
#   $1: Worker ID (0-indexed)
#   $2: Port number for remote debugging
#   $3: Profile name (e.g., "Lyra-00")
# Returns:
#   0: Chrome started and ready
#   1: Failed to start Chrome or connect
start_chrome_worker_linux() {
    # shellcheck disable=SC2034  # worker_id reserved for future logging
    local worker_id="$1"
    local port="$2"
    local profile="$3"

    local chrome_path
    chrome_path=$(which google-chrome || which chromium-browser || which chromium 2>/dev/null || echo "")

    if [ -z "$chrome_path" ]; then
        return 1
    fi

    # Use worker-specific data dir
    local data_dir="$HOME/.local/share/lyra-chrome/$profile"
    mkdir -p "$data_dir"

    local extra_flags=()
    # Best-effort: try to reduce focus stealing on startup.
    # When enabled, Chrome may start minimized depending on platform/WM support.
    local start_minimized
    start_minimized="$(lyra_get_setting "browser.chrome_start_minimized" 2>/dev/null || echo "")"
    if [ "${start_minimized,,}" = "1" ] || [ "${start_minimized,,}" = "true" ]; then
        extra_flags+=(--start-minimized)
    fi

    "$chrome_path" \
        --remote-debugging-port="$port" \
        --user-data-dir="$data_dir" \
        --no-first-run \
        --no-default-browser-check \
        --disable-background-networking \
        --disable-sync \
        --disable-background-timer-throttling \
        --disable-backgrounding-occluded-windows \
        --disable-renderer-backgrounding \
        "${extra_flags[@]}" \
        > /dev/null 2>&1 &

    local host=""
    host=$(try_connect_with_backoff "$port" "$STARTUP_TIMEOUT_LINUX" "$BACKOFF_BASE_DELAY" "$BACKOFF_MAX_DELAY" || true)
    if [ -n "${host:-}" ]; then
        return 0
    fi

    return 1
}

# =============================================================================
# LEGACY SINGLE-INSTANCE FUNCTIONS (for backward compatibility during migration)
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

    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "STARTING"
        echo "Environment: WSL"
        echo "Port: $port"
    fi
    
    # Start Chrome with separate profile via PowerShell
    # Note: Bind to 127.0.0.1 only for security. WSL2 mirrored mode allows direct localhost access.
    local start_result
    start_result=$(run_ps "
        \$ErrorActionPreference = 'Stop'
        try {
            \$dataDir = [Environment]::GetFolderPath('LocalApplicationData') + '\LyraChrome'
            if (-not (Test-Path \$dataDir)) { New-Item -ItemType Directory -Path \$dataDir -Force | Out-Null }
            
            \$proc = Start-Process 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList @(
                '--remote-debugging-port=$port',
                '--remote-debugging-address=127.0.0.1',
                \"--user-data-dir=\$dataDir\",
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-background-networking',
                '--disable-sync',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding'
            ) -PassThru -ErrorAction Stop
            'SUCCESS'
        } catch {
            'ERROR'
        }
    " 2>/dev/null | tr -d '\r\n')
    
    local start_result_value="${start_result:-}"
    if [ -z "$start_result_value" ] || [ "$start_result_value" = "ERROR" ]; then
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            cat <<EOF
{
  "status": "error",
  "exit_code": ${EXIT_OPERATION_FAILED},
  "message": "Failed to start Chrome via PowerShell",
  "hint": "Check if Chrome is installed at C:\\\\Program Files\\\\Google\\\\Chrome\\\\Application\\\\chrome.exe"
}
EOF
        else
            echo "ERROR"
            echo "Failed to start Chrome via PowerShell"
            echo "  -> Check if Chrome is installed at: C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
            echo "  -> Check PowerShell permissions"
            echo "  -> Try running PowerShell manually to verify it works"
        fi
        return 1
    fi

    # Wait and try to connect with exponential backoff
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "Waiting for Chrome (${STARTUP_TIMEOUT_WSL}s timeout)..."
    fi
    local host=""
    host=$(try_connect_with_backoff "$port" "$STARTUP_TIMEOUT_WSL" "$BACKOFF_BASE_DELAY" "$BACKOFF_MAX_DELAY" || true)
    if [ -n "${host:-}" ]; then
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            cat <<EOF
{
  "status": "ready",
  "exit_code": ${EXIT_SUCCESS},
  "host": "${host}",
  "port": ${port},
  "connect_url": "http://${host}:${port}",
  "cdp_command": "chromium.connect_over_cdp('http://${host}:${port}')"
}
EOF
        else
            echo "READY"
            echo "Host: $host:$port"
            echo "Connect: chromium.connect_over_cdp('http://$host:$port')"
        fi
        return 0
    fi

    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        cat <<EOF
{
  "status": "timeout",
  "exit_code": ${EXIT_TIMEOUT},
  "message": "Chrome started but could not connect from WSL",
  "hint": "make doctor-chrome-fix"
}
EOF
    else
        echo "TIMEOUT"
        echo "Chrome started but could not connect from WSL"
        echo ""
        echo "Ensure WSL2 mirrored networking is enabled:"
        echo "  make doctor-chrome-fix"
    fi
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
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            cat <<EOF
{
  "status": "error",
  "exit_code": ${EXIT_DEPENDENCY},
  "message": "Chrome/Chromium not found"
}
EOF
        else
            echo "ERROR"
            echo "Chrome/Chromium not found"
        fi
        return 1
    fi

    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "STARTING"
        echo "Environment: Linux"
        echo "Port: $port"
    fi

    # Use separate data dir
    local data_dir="$HOME/.local/share/lyra-chrome"
    mkdir -p "$data_dir"

    "$chrome_path" \
        --remote-debugging-port="$port" \
        --user-data-dir="$data_dir" \
        --no-first-run \
        --no-default-browser-check \
        --disable-background-networking \
        --disable-sync \
        --disable-background-timer-throttling \
        --disable-backgrounding-occluded-windows \
        --disable-renderer-backgrounding \
        > /dev/null 2>&1 &

    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "Waiting for Chrome (${STARTUP_TIMEOUT_LINUX}s timeout)..."
    fi
    local host=""
    host=$(try_connect_with_backoff "$port" "$STARTUP_TIMEOUT_LINUX" "$BACKOFF_BASE_DELAY" "$BACKOFF_MAX_DELAY" || true)
    if [ -n "${host:-}" ]; then
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            cat <<EOF
{
  "status": "ready",
  "exit_code": ${EXIT_SUCCESS},
  "host": "${host}",
  "port": ${port},
  "connect_url": "http://${host}:${port}",
  "cdp_command": "chromium.connect_over_cdp('http://${host}:${port}')"
}
EOF
        else
            echo "READY"
            echo "Connect: chromium.connect_over_cdp('http://${host}:$port')"
        fi
        return 0
    fi

    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        cat <<EOF
{
  "status": "timeout",
  "exit_code": ${EXIT_TIMEOUT},
  "message": "Chrome startup timeout"
}
EOF
    else
        echo "TIMEOUT"
    fi
    return 1
}

