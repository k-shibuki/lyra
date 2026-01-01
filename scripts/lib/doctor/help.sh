#!/bin/bash
# Doctor Help Functions
#
# Functions for displaying help information.

show_help() {
    echo "Lyra Environment Doctor"
    echo ""
    echo "Usage: $0 [global-options] {check|chrome-fix|help} [options]"
    echo ""
    echo "Commands:"
    echo "  check           Check environment dependencies and configuration (default)"
    echo "  chrome-fix      Fix WSL2 Chrome networking issues (calls chrome.sh fix)"
    echo "  help            Show this help message"
    echo ""
    echo "Global Options:"
    echo "  --json        Output in JSON format (machine-readable)"
    echo "  --quiet, -q   Suppress non-essential output"
    echo ""
    echo "Examples:"
    echo "  make doctor              # Check environment"
    echo "  make doctor-chrome-fix   # Fix Chrome networking"
    echo ""
    echo "What doctor checks (10 items):"
    echo "  - Environment: WSL2/Linux detection"
    echo "  - Python/uv: uv command, .venv existence, Python 3.14 version"
    echo "  - Container: podman, podman-compose availability"
    echo "  - GPU: nvidia-smi for container GPU passthrough"
    echo "  - Disk space: ~25GB required for ML images and models"
    echo "  - Chrome: Browser installation (Windows path for WSL)"
    echo "  - Chrome/CDP: PowerShell, mirrored networking (WSL only)"
    echo "  - Configuration: .env file existence and permissions"
    echo ""
    echo "Exit Codes:"
    echo "  0   (EXIT_SUCCESS)      All checks passed"
    echo "  4   (EXIT_DEPENDENCY)   Missing dependencies"
    echo "  3   (EXIT_CONFIG)       Configuration issues"
    echo ""
    echo "Note: doctor only diagnoses issues. It does not automatically install"
    echo "dependencies or modify system configuration."
}

