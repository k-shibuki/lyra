#!/bin/bash
# Lyra shell - environment detection utilities

# Function: detect_env
# Description: Detect the current environment type
# Returns: "wsl", "linux", or "windows"
detect_env() {
    if [[ "${OSTYPE:-}" == "msys" ]] || [[ "${OSTYPE:-}" == "win32" ]]; then
        echo "windows"
    elif grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl"
    else
        echo "linux"
    fi
}

# Function: detect_container
# Description: Detect if running inside container and which container
# Sets global variables: IN_CONTAINER, CURRENT_CONTAINER_NAME, IS_ML_CONTAINER
# Returns:
#   0: Successfully detected container status
detect_container() {
    # Detect if running inside container
    # Check for container markers (Docker/Podman)
    IN_CONTAINER=false
    CURRENT_CONTAINER_NAME=""
    if [[ -f "/.dockerenv" ]] || [[ -f "/run/.containerenv" ]]; then
        IN_CONTAINER=true
        # Try to detect container name from HOSTNAME (set by Podman/Docker)
        # HOSTNAME is typically set to container name
        if [[ -n "${HOSTNAME:-}" ]]; then
            CURRENT_CONTAINER_NAME="$HOSTNAME"
        elif [[ -n "${CONTAINER_NAME:-}" ]]; then
            CURRENT_CONTAINER_NAME="$CONTAINER_NAME"
        fi
    fi

    # Detect if running in ML container (ml has FastAPI and ML libs)
    # Other containers: proxy (main), ollama (LLM), tor (proxy)
    IS_ML_CONTAINER=false
    if [[ "$IN_CONTAINER" == "true" ]] && [[ "$CURRENT_CONTAINER_NAME" == "ml" ]]; then
        IS_ML_CONTAINER=true
    fi

    # Export for use by scripts
    export IN_CONTAINER
    export CURRENT_CONTAINER_NAME
    export IS_ML_CONTAINER
}

# Function: detect_cloud_agent
# Description: Detect if running in a cloud agent environment (CI/CD)
# Sets global variables: IS_CLOUD_AGENT, CLOUD_AGENT_TYPE
# Returns:
#   0: Successfully detected cloud agent status
#
# Cloud Agent Types:
#   - cursor: Cursor Cloud Agent
#   - claude_code: Claude Code (Anthropic)
#   - github_actions: GitHub Actions
#   - generic_ci: Generic CI environment
#   - none: Not a cloud agent environment
detect_cloud_agent() {
    IS_CLOUD_AGENT=false
    CLOUD_AGENT_TYPE="none"

    # Cursor Cloud Agent detection
    # Cursor sets specific environment variables when running as cloud agent
    if [[ -n "${CURSOR_CLOUD_AGENT:-}" ]] || [[ -n "${CURSOR_SESSION_ID:-}" ]] || [[ "${CURSOR_BACKGROUND:-}" == "true" ]]; then
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="cursor"
    # Claude Code detection (Anthropic)
    # Claude Code typically runs in a sandboxed environment
    elif [[ -n "${CLAUDE_CODE:-}" ]] || [[ -n "${ANTHROPIC_API_KEY:-}" && -z "${DISPLAY:-}" && "${CI:-}" == "true" ]]; then
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="claude_code"
    # GitHub Actions detection
    elif [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="github_actions"
    # GitLab CI detection
    elif [[ -n "${GITLAB_CI:-}" ]]; then
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="gitlab_ci"
    # Generic CI detection (many CI systems set CI=true)
    elif [[ "${CI:-}" == "true" ]]; then
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="generic_ci"
    # No display available (headless environment without explicit CI marker)
    # This is a heuristic for cloud/remote environments
    elif [[ -z "${DISPLAY:-}" ]] && [[ -z "${WAYLAND_DISPLAY:-}" ]] && [[ "$(detect_env)" != "wsl" ]]; then
        # In WSL, lack of DISPLAY is normal (uses Windows display)
        # In pure Linux without display, likely a server/cloud environment
        IS_CLOUD_AGENT=true
        CLOUD_AGENT_TYPE="headless"
    fi

    # Export for use by scripts
    export IS_CLOUD_AGENT
    export CLOUD_AGENT_TYPE
}

# Function: is_e2e_capable
# Description: Check if the environment can run E2E tests
# Returns:
#   0: E2E capable (has display or headless browser configured)
#   1: Not E2E capable
is_e2e_capable() {
    # If explicitly configured for headless E2E
    if [[ "${LYRA_HEADLESS:-}" == "true" ]]; then
        return 0
    fi

    # If display is available
    if [[ -n "${DISPLAY:-}" ]] || [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
        return 0
    fi

    # WSL can access Windows display via CDP
    if [[ "$(detect_env)" == "wsl" ]]; then
        return 0
    fi

    # Not E2E capable
    return 1
}

# Function: get_windows_host
# Description: Get Windows host IP for WSL2 networking
# Returns: Windows host IP if WSL, "localhost" otherwise
get_windows_host() {
    if [ "$(detect_env)" = "wsl" ]; then
        ip route | grep default | awk '{print $3}' || echo "localhost"
    else
        echo "localhost"
    fi
}


