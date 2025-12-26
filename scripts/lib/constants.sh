#!/bin/bash
# Lyra shell - common constants (with .env overrides)

# Chrome CDP settings
# LYRA_BROWSER__CHROME_PORT from .env overrides default
export CHROME_PORT="${LYRA_BROWSER__CHROME_PORT:-9222}"

# Container settings
export CONTAINER_NAME="${LYRA_SCRIPT__CONTAINER_NAME:-lyra}"

# Timeouts (seconds)
export CONTAINER_TIMEOUT="${LYRA_SCRIPT__CONTAINER_TIMEOUT:-30}"
export CONNECT_TIMEOUT="${LYRA_SCRIPT__CONNECT_TIMEOUT:-30}"
export COMPLETION_THRESHOLD="${LYRA_SCRIPT__COMPLETION_THRESHOLD:-5}"

# Test result file path (inside container)
export TEST_RESULT_FILE="${LYRA_SCRIPT__TEST_RESULT_FILE:-/app/test_result.txt}"


