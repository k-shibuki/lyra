#!/bin/bash
# Lyra Shell Scripts Test Suite
#
# Tests for shell scripts to ensure they work correctly.
# This script tests basic functionality of all Lyra shell scripts.
#
# Usage:
#   ./scripts/test_scripts.sh        # Run all tests
#   ./scripts/test_scripts.sh common # Test common.sh only
#   ./scripts/test_scripts.sh dev   # Test dev.sh only
#   ./scripts/test_scripts.sh chrome # Test chrome.sh only
#   ./scripts/test_scripts.sh test  # Test test.sh only
#   ./scripts/test_scripts.sh mcp   # Test mcp.sh only
#   ./scripts/test_scripts.sh doctor # Test doctor.sh only

set -euo pipefail

# =============================================================================
# INITIALIZATION
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# PROJECT_DIR is not used in this test script, but kept for consistency
# shellcheck disable=SC2034
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Test results tracking
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

# =============================================================================
# TEST UTILITIES
# =============================================================================

# Function: test_pass
# Description: Record a passing test
# Arguments:
#   $1: Test name
test_pass() {
    echo "✓ PASS: $1"
    ((TESTS_PASSED++)) || true
}

# Function: test_fail
# Description: Record a failing test
# Arguments:
#   $1: Test name
#   $2: Error message (optional)
test_fail() {
    echo "✗ FAIL: $1"
    if [ -n "${2:-}" ]; then
        echo "  Error: $2"
    fi
    ((TESTS_FAILED++)) || true
    FAILED_TESTS+=("$1")
}

# Function: test_info
# Description: Print test information
# Arguments:
#   $1: Message
test_info() {
    echo "  → $1"
}

# =============================================================================
# COMMON.SH TESTS
# =============================================================================

test_common() {
    echo ""
    echo "=== Testing common.sh ==="
    
    # Test 1: Source common.sh without errors
    if source "${SCRIPT_DIR}/common.sh" 2>&1; then
        test_pass "common.sh can be sourced"
    else
        test_fail "common.sh can be sourced" "Failed to source common.sh"
        return
    fi
    
    # Test 2: Check log functions exist
    if command -v log_info > /dev/null && \
       command -v log_warn > /dev/null && \
       command -v log_error > /dev/null; then
        test_pass "Log functions are available"
    else
        test_fail "Log functions are available" "Log functions not found"
    fi
    
    # Test 3: Check container utilities exist
    if command -v check_container_running > /dev/null && \
       command -v wait_for_container > /dev/null; then
        test_pass "Container utilities are available"
    else
        test_fail "Container utilities are available" "Container utilities not found"
    fi
    
    # Test 4: Check environment detection
    if command -v detect_env > /dev/null && \
       command -v get_windows_host > /dev/null; then
        test_pass "Environment detection functions are available"
    else
        test_fail "Environment detection functions are available" "Environment detection functions not found"
    fi
    
    # Test 5: Test log functions output
    local log_output
    log_output=$(log_info "test" 2>&1)
    if echo "$log_output" | grep -q "\[INFO\] test"; then
        test_pass "log_info outputs correct format"
    else
        test_fail "log_info outputs correct format" "Expected [INFO] test, got: $log_output"
    fi
}

# =============================================================================
# DEV.SH TESTS
# =============================================================================

test_dev() {
    echo ""
    echo "=== Testing dev.sh ==="
    
    # Test 1: Help command works
    if "${SCRIPT_DIR}/dev.sh" help > /dev/null 2>&1; then
        test_pass "dev.sh help command works"
    else
        test_fail "dev.sh help command works" "Help command failed"
    fi
    
    # Test 2: Unknown command shows help
    local output
    output=$("${SCRIPT_DIR}/dev.sh" unknown_command 2>&1 || true)
    if echo "$output" | grep -q "Usage:"; then
        test_pass "dev.sh shows help for unknown commands"
    else
        test_fail "dev.sh shows help for unknown commands" "Help not shown for unknown command"
    fi
    
    # Test 3: Status command (may fail if containers not running, but should not crash)
    if "${SCRIPT_DIR}/dev.sh" status > /dev/null 2>&1; then
        test_pass "dev.sh status command works"
    else
        # Status may fail if containers aren't running, which is OK
        test_info "dev.sh status failed (containers may not be running - this is OK)"
    fi
    
    # Test 4: JSON output mode works
    local json_output
    json_output=$(LYRA_OUTPUT_JSON=true "${SCRIPT_DIR}/dev.sh" status 2>&1 || true)
    if echo "$json_output" | grep -qE '"status"|"container_running"'; then
        test_pass "dev.sh JSON output mode works"
    else
        test_fail "dev.sh JSON output mode works" "JSON output not detected"
    fi
    
    # Test 5: Dev modules can be sourced (dependency-free modules first)
    if source "${SCRIPT_DIR}/lib/dev/help.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/dev/dispatch_precheck.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/dev/shell.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/dev/logs.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/dev/clean.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/dev/commands.sh" 2>&1; then
        test_pass "dev.sh modules can be sourced"
    else
        test_fail "dev.sh modules can be sourced" "Failed to source dev modules"
    fi
}

# =============================================================================
# CHROME.SH TESTS
# =============================================================================

test_chrome() {
    echo ""
    echo "=== Testing chrome.sh ==="
    
    # Test 1: Help command works
    if "${SCRIPT_DIR}/chrome.sh" help > /dev/null 2>&1; then
        test_pass "chrome.sh help command works"
    else
        test_fail "chrome.sh help command works" "Help command failed"
    fi
    
    # Test 2: Check command works (may fail if Chrome not running, but should not crash)
    if "${SCRIPT_DIR}/chrome.sh" check > /dev/null 2>&1; then
        test_pass "chrome.sh check command works"
    else
        # Check may fail if Chrome isn't running, which is OK
        test_info "chrome.sh check failed (Chrome may not be running - this is OK)"
    fi
    
    # Test 3: Unknown command shows error
    local output
    output=$("${SCRIPT_DIR}/chrome.sh" unknown_command 2>&1 || true)
    if echo "$output" | grep -q "Unknown action\|Usage:"; then
        test_pass "chrome.sh shows error for unknown commands"
    else
        test_fail "chrome.sh shows error for unknown commands" "Error not shown for unknown command"
    fi
    
    # Test 4: JSON output mode works
    local json_output
    json_output=$(LYRA_OUTPUT_JSON=true "${SCRIPT_DIR}/chrome.sh" check 2>&1 || true)
    if echo "$json_output" | grep -qE '"status"|"exit_code"'; then
        test_pass "chrome.sh JSON output mode works"
    else
        test_fail "chrome.sh JSON output mode works" "JSON output not detected"
    fi
    
    # Test 5: Chrome modules can be sourced
    if source "${SCRIPT_DIR}/lib/chrome/ps.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/chrome/connect.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/chrome/status.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/chrome/start.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/chrome/stop.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/chrome/diagnose.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/chrome/fix.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/chrome/help.sh" 2>&1; then
        test_pass "chrome.sh modules can be sourced"
    else
        test_fail "chrome.sh modules can be sourced" "Failed to source chrome modules"
    fi
}

# =============================================================================
# TEST.SH TESTS
# =============================================================================

test_test() {
    echo ""
    echo "=== Testing test.sh ==="
    
    # Test 1: Help command works
    if "${SCRIPT_DIR}/test.sh" help > /dev/null 2>&1; then
        test_pass "test.sh help command works"
    else
        test_fail "test.sh help command works" "Help command failed"
    fi
    
    # Test 2: Unknown command shows usage
    local output
    output=$("${SCRIPT_DIR}/test.sh" unknown_command 2>&1 || true)
    if echo "$output" | grep -q "Usage:"; then
        test_pass "test.sh shows usage for unknown commands"
    else
        test_fail "test.sh shows usage for unknown commands" "Usage not shown for unknown command"
    fi
    
    # Test 3: Check command (may fail if container not running, but should not crash)
    if "${SCRIPT_DIR}/test.sh" check > /dev/null 2>&1; then
        test_pass "test.sh check command works"
    else
        # Check may fail if container isn't running, which is OK
        test_info "test.sh check failed (container may not be running - this is OK)"
    fi
    
    # Test 4: JSON output mode works
    local json_output
    json_output=$(LYRA_OUTPUT_JSON=true "${SCRIPT_DIR}/test.sh" env 2>&1 || true)
    if echo "$json_output" | grep -qE '"environment"|"exit_code"'; then
        test_pass "test.sh JSON output mode works"
    else
        test_fail "test.sh JSON output mode works" "JSON output not detected"
    fi
    
    # Test 5: Test modules can be sourced (in dependency order)
    if source "${SCRIPT_DIR}/lib/test/args.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/test/state.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/test/runtime.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/test/markers.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/test/check_helpers.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/test/commands.sh" 2>&1; then
        test_pass "test.sh modules can be sourced"
    else
        test_fail "test.sh modules can be sourced" "Failed to source test modules"
    fi
}

# =============================================================================
# TEST COMPLETION MARKER TESTS (manifest + done/exit based)
# =============================================================================

test_completion_markers() {
    echo ""
    echo "=== Testing completion marker system ==="
    
    # Source required modules
    source "${SCRIPT_DIR}/common.sh"
    source "${SCRIPT_DIR}/lib/test/state.sh"
    
    # Use isolated temp directory
    local test_dir
    test_dir=$(mktemp -d)
    # shellcheck disable=SC2034
    TEST_RESULT_DIR="$test_dir"
    
    local test_run_id
    test_run_id="test_$(date +%s)_$$"
    
    # Test 1: Manifest file path generation
    local manifest_file
    manifest_file=$(get_manifest_file "$test_run_id")
    if [[ "$manifest_file" == "${test_dir}/run_${test_run_id}.env" ]]; then
        test_pass "get_manifest_file generates correct path"
    else
        test_fail "get_manifest_file generates correct path" "Got: $manifest_file"
    fi
    
    # Test 2: Done/Exit/Cancelled file path generation
    local done_file exit_file cancelled_file
    done_file=$(get_done_file "$test_run_id")
    exit_file=$(get_exit_file "$test_run_id")
    cancelled_file=$(get_cancelled_file "$test_run_id")
    
    if [[ "$done_file" == "${test_dir}/done_${test_run_id}" ]] && \
       [[ "$exit_file" == "${test_dir}/exit_${test_run_id}" ]] && \
       [[ "$cancelled_file" == "${test_dir}/cancelled_${test_run_id}" ]]; then
        test_pass "done/exit/cancelled file paths generated correctly"
    else
        test_fail "done/exit/cancelled file paths generated correctly" \
            "done=$done_file, exit=$exit_file, cancelled=$cancelled_file"
    fi
    
    # Test 3: Write and load manifest
    local result_file="${test_dir}/result_${test_run_id}.txt"
    local pid_file="${test_dir}/pid_${test_run_id}"
    
    write_run_manifest "$test_run_id" "venv" "" "" "$result_file" "$pid_file" "$done_file" "$exit_file"
    
    if [[ -f "$manifest_file" ]]; then
        test_pass "write_run_manifest creates manifest file"
    else
        test_fail "write_run_manifest creates manifest file" "File not found"
    fi
    
    # Test 4: Load manifest and verify contents
    if load_run_manifest "$test_run_id"; then
        if [[ "${LYRA_MANIFEST__RUN_ID}" == "$test_run_id" ]] && \
           [[ "${LYRA_MANIFEST__RUNTIME}" == "venv" ]] && \
           [[ "${LYRA_MANIFEST__RESULT_FILE}" == "$result_file" ]]; then
            test_pass "load_run_manifest loads correct values"
        else
            test_fail "load_run_manifest loads correct values" \
                "run_id=${LYRA_MANIFEST__RUN_ID}, runtime=${LYRA_MANIFEST__RUNTIME}"
        fi
    else
        test_fail "load_run_manifest loads correct values" "load_run_manifest returned non-zero"
    fi
    
    # Test 5: manifest_exists function
    if manifest_exists "$test_run_id"; then
        test_pass "manifest_exists returns true for existing manifest"
    else
        test_fail "manifest_exists returns true for existing manifest"
    fi
    
    if ! manifest_exists "nonexistent_run_id"; then
        test_pass "manifest_exists returns false for non-existing manifest"
    else
        test_fail "manifest_exists returns false for non-existing manifest"
    fi
    
    # Test 6: Exit code mapping (from check.sh helper)
    source "${SCRIPT_DIR}/lib/test/commands/check.sh"
    source "${SCRIPT_DIR}/lib/exit_codes.sh"
    
    local mapped_code
    mapped_code=$(map_pytest_exit_code "0")
    if [[ "$mapped_code" == "$EXIT_SUCCESS" ]]; then
        test_pass "map_pytest_exit_code: 0 -> EXIT_SUCCESS"
    else
        test_fail "map_pytest_exit_code: 0 -> EXIT_SUCCESS" "Got: $mapped_code"
    fi
    
    mapped_code=$(map_pytest_exit_code "1")
    if [[ "$mapped_code" == "$EXIT_TEST_FAILED" ]]; then
        test_pass "map_pytest_exit_code: 1 -> EXIT_TEST_FAILED"
    else
        test_fail "map_pytest_exit_code: 1 -> EXIT_TEST_FAILED" "Got: $mapped_code"
    fi
    
    mapped_code=$(map_pytest_exit_code "2")
    if [[ "$mapped_code" == "$EXIT_TEST_CANCELLED" ]]; then
        test_pass "map_pytest_exit_code: 2 -> EXIT_TEST_CANCELLED"
    else
        test_fail "map_pytest_exit_code: 2 -> EXIT_TEST_CANCELLED" "Got: $mapped_code"
    fi
    
    mapped_code=$(map_pytest_exit_code "3")
    if [[ "$mapped_code" == "$EXIT_TEST_ERROR" ]]; then
        test_pass "map_pytest_exit_code: 3 -> EXIT_TEST_ERROR"
    else
        test_fail "map_pytest_exit_code: 3 -> EXIT_TEST_ERROR" "Got: $mapped_code"
    fi
    
    # Test 7: Verify new exit codes exist
    if [[ -n "$EXIT_TEST_CRASHED" ]] && [[ "$EXIT_TEST_CRASHED" == "24" ]]; then
        test_pass "EXIT_TEST_CRASHED defined as 24"
    else
        test_fail "EXIT_TEST_CRASHED defined as 24" "Got: ${EXIT_TEST_CRASHED:-undefined}"
    fi
    
    if [[ -n "$EXIT_TEST_CANCELLED" ]] && [[ "$EXIT_TEST_CANCELLED" == "25" ]]; then
        test_pass "EXIT_TEST_CANCELLED defined as 25"
    else
        test_fail "EXIT_TEST_CANCELLED defined as 25" "Got: ${EXIT_TEST_CANCELLED:-undefined}"
    fi
    
    # Cleanup
    rm -rf "$test_dir"
}

# =============================================================================
# MCP.SH TESTS
# =============================================================================

test_mcp() {
    echo ""
    echo "=== Testing mcp.sh ==="
    
    # Test 1: Script exists and is executable
    if [ -x "${SCRIPT_DIR}/mcp.sh" ]; then
        test_pass "mcp.sh is executable"
    else
        test_fail "mcp.sh is executable" "mcp.sh is not executable"
    fi
    
    # Note: mcp.sh is designed to be called by Cursor and may hang waiting for stdio
    # So we don't test actual execution here
    test_info "mcp.sh execution test skipped (requires stdio connection)"
}

# =============================================================================
# DOCTOR.SH TESTS
# =============================================================================

test_doctor() {
    echo ""
    echo "=== Testing doctor.sh ==="
    
    # Test 1: Help command works
    if "${SCRIPT_DIR}/doctor.sh" help > /dev/null 2>&1; then
        test_pass "doctor.sh help command works"
    else
        test_fail "doctor.sh help command works" "Help command failed"
    fi
    
    # Test 2: Unknown command shows help
    local output
    output=$("${SCRIPT_DIR}/doctor.sh" unknown_command 2>&1 || true)
    if echo "$output" | grep -q "Usage:"; then
        test_pass "doctor.sh shows help for unknown commands"
    else
        test_fail "doctor.sh shows help for unknown commands" "Help not shown for unknown command"
    fi
    
    # Test 3: Check command (should not crash even if dependencies are missing)
    if "${SCRIPT_DIR}/doctor.sh" check > /dev/null 2>&1; then
        test_pass "doctor.sh check command works"
    else
        # Check may fail if dependencies are missing, which is OK
        test_info "doctor.sh check failed (dependencies may be missing - this is OK)"
    fi
    
    # Test 4: JSON output mode works
    local json_output
    json_output=$(LYRA_OUTPUT_JSON=true "${SCRIPT_DIR}/doctor.sh" check 2>&1 || true)
    if echo "$json_output" | grep -qE '"status"|"exit_code"'; then
        test_pass "doctor.sh JSON output mode works"
    else
        test_fail "doctor.sh JSON output mode works" "JSON output not detected"
    fi
    
    # Test 5: Doctor modules can be sourced
    if source "${SCRIPT_DIR}/lib/doctor/checks.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/doctor/help.sh" 2>&1 && \
       source "${SCRIPT_DIR}/lib/doctor/commands.sh" 2>&1; then
        test_pass "doctor.sh modules can be sourced"
    else
        test_fail "doctor.sh modules can be sourced" "Failed to source doctor modules"
    fi
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    local test_target="${1:-all}"
    
    echo "Lyra Shell Scripts Test Suite"
    echo "================================"
    
    case "$test_target" in
        common)
            test_common
            ;;
        dev)
            test_dev
            ;;
        chrome)
            test_chrome
            ;;
        test)
            test_test
            ;;
        completion)
            test_completion_markers
            ;;
        mcp)
            test_mcp
            ;;
        doctor)
            test_doctor
            ;;
        all)
            test_common
            test_dev
            test_chrome
            test_test
            test_completion_markers
            test_mcp
            test_doctor
            ;;
        *)
            echo "Unknown test target: $test_target"
            echo "Usage: $0 {all|common|dev|chrome|test|completion|mcp|doctor}"
            exit 1
            ;;
    esac
    
    # Summary
    echo ""
    echo "================================"
    echo "Test Summary"
    echo "================================"
    echo "Passed: $TESTS_PASSED"
    echo "Failed: $TESTS_FAILED"
    
    if [ $TESTS_FAILED -gt 0 ]; then
        echo ""
        echo "Failed tests:"
        for test in "${FAILED_TESTS[@]}"; do
            echo "  - $test"
        done
        exit 1
    else
        echo ""
        echo "All tests passed!"
        exit 0
    fi
}

main "$@"

