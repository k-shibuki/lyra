#!/bin/bash
# Test Check Helper Functions
#
# Functions for filtering and checking test output.

# Function: filter_node_errors
# Description: Filter out Node.js error noise from test output
# Input: stdin (test output)
# Output: stdout (filtered output)
filter_node_errors() {
    grep -v -E "^(node:|Node\.js|Error: write EPIPE|    at |Emitted|  errno:|  code:|  syscall:|\{$|\}$)"
}

# Fatal error patterns that indicate test run should terminate immediately
# These errors typically crash pytest without producing a summary line
FATAL_ERROR_PATTERNS=(
    "sqlite3.OperationalError: disk I/O error"
    "sqlite3.OperationalError: database disk image is malformed"
    "MemoryError"
    "Segmentation fault"
    "SIGKILL"
    "killed"
    "out of memory"
    "OSError: \\[Errno 28\\] No space left on device"
)

# Function: check_fatal_errors
# Description: Check if result file contains fatal error patterns
# Arguments:
#   $1: result content (last N lines)
# Returns:
#   0: Fatal error found
#   1: No fatal error found
# Output: Prints the matched error pattern if found
check_fatal_errors() {
    local content="$1"
    for pattern in "${FATAL_ERROR_PATTERNS[@]}"; do
        if echo "$content" | grep -qE "$pattern"; then
            echo "$pattern"
            return 0
        fi
    done
    return 1
}

