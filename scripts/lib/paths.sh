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

SCRIPTS_DIR="$(get_scripts_dir)"
export SCRIPTS_DIR

PROJECT_DIR="$(get_project_dir)"
export PROJECT_DIR


