#!/bin/bash
# Lyra shell - logging functions

# Function: log_info
# Description: Log info message to stdout
# Arguments:
#   $*: Message to log
log_info() {
    echo "[INFO] $*"
}

# Function: log_warn
# Description: Log warning message to stderr
# Arguments:
#   $*: Message to log
log_warn() {
    echo "[WARN] $*" >&2
}

# Function: log_error
# Description: Log error message to stderr (JSON-aware)
# Arguments:
#   $*: Message to log
# Note: In JSON mode, this outputs to stderr only (main output should use output_error)
log_error() {
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "[ERROR] $*" >&2
    fi
}


