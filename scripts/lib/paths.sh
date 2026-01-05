#!/bin/bash
# Lyra shell - path utilities

# Function: get_scripts_dir
# Description: Get absolute path to scripts/ directory based on this file location.
get_scripts_dir() {
    local lib_dir
    lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    dirname "$lib_dir"
}

# Function: get_project_dir
# Description: Get absolute path to project root (parent of scripts/).
get_project_dir() {
    local scripts_dir
    scripts_dir="$(get_scripts_dir)"
    dirname "$scripts_dir"
}

# Function: ensure_user_paths
# Description: Add common user tool paths (uv, cargo) to PATH if they exist.
# This ensures scripts work correctly even when sourced from non-login shells
# (e.g., IDE terminals, CI environments) where ~/.bashrc may not be loaded.
ensure_user_paths() {
    # uv installs to ~/.local/bin
    if [[ -d "$HOME/.local/bin" ]] && [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi

    # cargo/rustup installs to ~/.cargo/bin
    if [[ -d "$HOME/.cargo/bin" ]] && [[ ":$PATH:" != *":$HOME/.cargo/bin:"* ]]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    fi
}

SCRIPTS_DIR="$(get_scripts_dir)"
export SCRIPTS_DIR

PROJECT_DIR="$(get_project_dir)"
export PROJECT_DIR

# Ensure user tool paths are available
ensure_user_paths

# Virtual environment path
VENV_DIR="${PROJECT_DIR}/.venv"
export VENV_DIR


