#!/bin/bash
# Doctor Check Functions
#
# Functions for checking various dependencies and configuration.

# Function: check_command
# Description: Check if a command exists
# Arguments:
#   $1: Command name
# Returns:
#   0: Command exists
#   1: Command not found
check_command() {
    local cmd="$1"
    command -v "$cmd" > /dev/null 2>&1
}

# Function: check_file
# Description: Check if a file exists
# Arguments:
#   $1: File path
# Returns:
#   0: File exists
#   1: File not found
check_file() {
    local file="$1"
    [[ -f "$file" ]]
}

# Function: check_dir
# Description: Check if a directory exists
# Arguments:
#   $1: Directory path
# Returns:
#   0: Directory exists
#   1: Directory not found
check_dir() {
    local dir="$1"
    [[ -d "$dir" ]]
}

# Function: check_python_version
# Description: Check if Python version matches requirement (3.14.*)
# Arguments:
#   $1: Python executable path (optional, defaults to .venv/bin/python)
# Returns:
#   0: Version matches
#   1: Version mismatch or check failed
check_python_version() {
    local python_exe="${1:-${VENV_DIR}/bin/python}"
    
    if [[ ! -f "$python_exe" ]]; then
        return 1
    fi
    
    local version
    version=$("$python_exe" -V 2>&1 | awk '{print $2}' || echo "")
    
    if [[ "$version" =~ ^3\.14\. ]]; then
        return 0
    fi
    
    return 1
}

# Function: check_wsl_mirrored_networking
# Description: Check WSL2 mirrored networking mode status
# Returns:
#   0: Mirrored mode is enabled
#   1: Mirrored mode is disabled or check failed
# Note: Requires scripts/lib/chrome/ps.sh to be sourced
check_wsl_mirrored_networking() {
    if [[ "$(detect_env)" != "wsl" ]]; then
        return 1
    fi
    
    # Source chrome ps module if not already available
    if ! command -v check_mirrored_mode > /dev/null 2>&1; then
        local chrome_ps_file="${SCRIPT_DIR}/lib/chrome/ps.sh"
        if [[ -f "$chrome_ps_file" ]]; then
            # shellcheck source=/dev/null
            source "$chrome_ps_file"
        else
            return 1
        fi
    fi
    
    local status
    status=$(check_mirrored_mode 2>/dev/null || echo "ERROR")
    
    if [[ "$status" == "ENABLED" ]]; then
        return 0
    fi
    
    return 1
}

# Function: check_env_permissions
# Description: Check .env file permissions (should be 600)
# Arguments:
#   $1: .env file path (optional, defaults to PROJECT_DIR/.env)
# Returns:
#   0: Permissions are safe (600 or stricter)
#   1: Permissions are too permissive
check_env_permissions() {
    local env_file="${1:-${PROJECT_DIR}/.env}"
    
    if [[ ! -f "$env_file" ]]; then
        return 1
    fi
    
    local perms
    perms=$(stat -c "%a" "$env_file" 2>/dev/null || echo "000")
    
    # Check if world-readable (last digit is not 0)
    if [[ "${perms:2:1}" != "0" ]]; then
        return 1
    fi
    
    return 0
}

# Function: check_gpu
# Description: Check if nvidia-smi is available (required for container GPU passthrough)
# Returns:
#   0: nvidia-smi found
#   1: nvidia-smi not found
check_gpu() {
    check_command nvidia-smi
}

# Function: get_gpu_info
# Description: Get GPU name and memory information
# Returns:
#   GPU info string (e.g., "NVIDIA GeForce RTX 4060, 8192 MiB")
#   Empty string on error
get_gpu_info() {
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1
}

# Function: check_disk_space
# Description: Check if sufficient disk space is available
# Arguments:
#   $1: Required space in MB (default: 25000 = ~25GB)
# Returns:
#   0: Sufficient space available
#   1: Insufficient space
check_disk_space() {
    local required_mb="${1:-25000}"
    local available_mb
    available_mb=$(df -m "${PROJECT_DIR}" 2>/dev/null | awk 'NR==2 {print $4}')
    
    if [[ -z "$available_mb" ]]; then
        return 1
    fi
    
    (( available_mb >= required_mb ))
}

# Function: get_disk_space_mb
# Description: Get available disk space in MB
# Returns:
#   Available space in MB, or empty on error
get_disk_space_mb() {
    df -m "${PROJECT_DIR}" 2>/dev/null | awk 'NR==2 {print $4}'
}

# Function: check_chrome_installed
# Description: Check if Chrome/Chromium is installed
# Returns:
#   0: Chrome found
#   1: Chrome not found
# Note: On WSL, checks Windows Chrome path via PowerShell
check_chrome_installed() {
    local env_type
    env_type=$(detect_env)
    
    if [[ "$env_type" == "wsl" ]]; then
        # WSL: Check Windows Chrome installation via PowerShell
        # Source chrome ps module if not already available
        if ! command -v run_ps > /dev/null 2>&1; then
            local chrome_ps_file="${SCRIPT_DIR}/lib/chrome/ps.sh"
            if [[ -f "$chrome_ps_file" ]]; then
                # shellcheck source=/dev/null
                source "$chrome_ps_file"
            else
                return 1
            fi
        fi
        
        local result
        result=$(run_ps "Test-Path 'C:\Program Files\Google\Chrome\Application\chrome.exe'" 2>/dev/null | tr -d '\r\n')
        [[ "$result" == "True" ]]
    else
        # Linux: Check for google-chrome or chromium
        check_command google-chrome || check_command chromium-browser || check_command chromium
    fi
}

# Function: get_chrome_path
# Description: Get the path to Chrome executable
# Returns:
#   Chrome path string, or empty on error
get_chrome_path() {
    local env_type
    env_type=$(detect_env)
    
    if [[ "$env_type" == "wsl" ]]; then
        echo "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    else
        which google-chrome 2>/dev/null || which chromium-browser 2>/dev/null || which chromium 2>/dev/null || echo ""
    fi
}

