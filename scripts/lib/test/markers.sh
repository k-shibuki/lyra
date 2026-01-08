#!/bin/bash
# Test Marker Selection Functions
#
# Functions for selecting pytest markers based on environment.

# Function: get_pytest_markers
# Description: Get appropriate pytest markers based on environment
# Returns: Marker expression string for pytest -m option
# Note: Log messages are written to stderr to avoid polluting the return value
get_pytest_markers() {
    local markers=""
    
    if [[ "${IS_CLOUD_AGENT:-false}" == "true" ]]; then
        # Cloud agent environment: unit + integration only (no e2e)
        markers="not e2e"
        log_info "Cloud agent detected (${CLOUD_AGENT_TYPE:-unknown}): Running unit + integration tests only" >&2
    elif [[ "${LYRA_TEST_LAYER:-}" == "e2e" ]]; then
        # Explicitly request E2E tests
        markers="e2e"
        log_info "E2E layer requested: Running E2E tests" >&2
    elif [[ "${LYRA_TEST_LAYER:-}" == "all" ]]; then
        # Run all tests
        markers=""
        log_info "All tests requested" >&2
    else
        # Default: unit + integration (exclude e2e)
        markers="not e2e"
        log_info "Default layer: Running unit + integration tests" >&2
    fi
    
    echo "$markers"
}

