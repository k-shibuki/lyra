#!/bin/bash
# Doctor Check Command Handler
#
# Function for handling doctor.sh check command.

# Function: cmd_check
# Description: Check environment dependencies and configuration
# Returns:
#   0: All checks passed
#   1: Issues found (exit code varies by issue type)
cmd_check() {
    # Guard: doctor must run on host, not inside container
    if ! require_host_execution "doctor check" "checks host-side dependencies (uv, podman, powershell.exe)" "return"; then
        return "$EXIT_CONFIG"
    fi
    
    local issues=0
    local warnings=0
    local json_parts=()
    
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        json_parts+=("$(json_kv "status" "checking")")
    else
        echo "=== Lyra Environment Doctor ==="
        echo ""
    fi

    # Source checks module
    # shellcheck source=/dev/null
    source "${SCRIPT_DIR}/lib/doctor/checks.sh"
    
    # Source chrome ps module for WSL checks (if needed)
    if [[ "$(detect_env)" == "wsl" ]]; then
        local chrome_ps_file="${SCRIPT_DIR}/lib/chrome/ps.sh"
        if [[ -f "$chrome_ps_file" ]]; then
            # shellcheck source=/dev/null
            source "$chrome_ps_file"
        fi
    fi
    
    # Check 1: Environment detection
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "[1/10] Environment..."
    fi
    local env_type
    env_type=$(detect_env)
    if [[ "$env_type" == "wsl" ]]; then
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo "  ✓ WSL2 detected"
        fi
    elif [[ "$env_type" == "linux" ]]; then
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo "  ✓ Linux detected"
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo "  ⚠ Windows native (WSL2 recommended)"
        fi
        ((warnings++)) || true
    fi
    
    # Check 2: curl
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[2/10] curl..."
    fi
    if check_command curl; then
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo "  ✓ curl found"
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "curl" "missing")")
        else
            echo "  ✗ curl not found"
            echo "    -> Install: sudo apt install curl"
        fi
        ((issues++)) || true
    fi
    
    # Check 3: uv
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[3/10] uv..."
    fi
    if check_command uv; then
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo "  ✓ uv found"
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "uv" "missing")")
        else
            echo "  ✗ uv not found"
            echo "    -> Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
            echo "    -> Then: source \$HOME/.local/bin/env"
        fi
        ((issues++)) || true
    fi
    
    # Check 4: .venv
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[4/10] Python environment..."
    fi
    if check_dir "${VENV_DIR}"; then
        if check_python_version "${VENV_DIR}/bin/python"; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  ✓ .venv exists (Python 3.13)"
            fi
        else
            local py_version
            py_version=$("${VENV_DIR}/bin/python" -V 2>&1 | awk '{print $2}' || echo "unknown")
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                json_parts+=("$(json_kv "python_version" "$py_version")")
                json_parts+=("$(json_kv "python_version_issue" "expected_3.13")")
            else
                echo "  ⚠ .venv exists but Python version is $py_version (expected 3.13.*)"
                echo "    -> Recreate: rm -rf .venv && make setup"
            fi
            ((warnings++)) || true
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "venv" "missing")")
        else
            echo "  ✗ .venv not found"
            echo "    -> Run: make setup"
        fi
        ((issues++)) || true
    fi
    
    # Check 5: Container runtime
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[5/10] Container runtime..."
    fi
    if check_command podman; then
        if check_command podman-compose; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  ✓ podman and podman-compose found"
            fi
        else
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                json_parts+=("$(json_kv "podman_compose" "missing")")
            else
                echo "  ✗ podman-compose not found"
                echo "    -> Install: sudo apt install podman-compose"
            fi
            ((issues++)) || true
        fi
    elif check_command docker; then
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "container_runtime" "docker_only")")
            json_parts+=("$(json_kv "container_runtime_issue" "podman_required")")
        else
            echo "  ⚠ docker found but podman is required for dev commands"
            echo "    -> Install: sudo apt install podman podman-compose"
        fi
        ((warnings++)) || true
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "container_runtime" "missing")")
        else
            echo "  ✗ No container runtime found (podman recommended)"
            echo "    -> Install: sudo apt install podman podman-compose"
        fi
        ((issues++)) || true
    fi
    
    # Check 6: GPU (required for containers)
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[6/10] GPU..."
    fi
    if check_gpu; then
        local gpu_info
        gpu_info=$(get_gpu_info)
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "gpu" "$gpu_info")")
        else
            echo "  ✓ nvidia-smi found"
            echo "  ✓ GPU: $gpu_info"
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "gpu" "missing")")
        else
            echo "  ✗ nvidia-smi not found"
            echo "    -> Required for container GPU passthrough (lyra-ml, lyra-ollama)"
            echo "    -> Install NVIDIA drivers and nvidia-container-toolkit"
            echo "    -> Then: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
        fi
        ((issues++)) || true
    fi
    
    # Check 7: Disk space (~25GB required)
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[7/10] Disk space..."
    fi
    local required_mb=25000
    if check_disk_space "$required_mb"; then
        local available_mb
        available_mb=$(get_disk_space_mb)
        local available_gb=$((available_mb / 1024))
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_num "disk_available_mb" "$available_mb")")
        else
            echo "  ✓ ${available_gb}GB available (25GB required)"
        fi
    else
        local available_mb
        available_mb=$(get_disk_space_mb)
        local available_gb=$((available_mb / 1024))
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_num "disk_available_mb" "$available_mb")")
            json_parts+=("$(json_kv "disk_space_issue" "insufficient")")
        else
            echo "  ✗ Only ${available_gb}GB available (25GB required)"
            echo "    -> ML image (~18GB) + Ollama models (~5GB) + data"
            echo "    -> Free up disk space before running make dev-build"
        fi
        ((issues++)) || true
    fi
    
    # Check 8: Chrome installed
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[8/10] Chrome installed..."
    fi
    if check_chrome_installed; then
        local chrome_path
        chrome_path=$(get_chrome_path)
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "chrome_path" "$chrome_path")")
        else
            echo "  ✓ Chrome found"
            if [[ "$env_type" == "wsl" ]]; then
                echo "  ✓ Path: $chrome_path"
            fi
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "chrome" "missing")")
        else
            echo "  ✗ Chrome not found"
            if [[ "$env_type" == "wsl" ]]; then
                echo "    -> Install Chrome on Windows: https://www.google.com/chrome/"
                echo "    -> Expected path: C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
            else
                echo "    -> Install: sudo apt install google-chrome-stable"
                echo "    -> Or: sudo apt install chromium-browser"
            fi
        fi
        ((issues++)) || true
    fi
    
    # Check 9: Chrome/CDP (WSL only)
    if [[ "$env_type" == "wsl" ]]; then
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo ""
            echo "[9/10] Chrome/CDP (WSL)..."
        fi
        
        # Check PowerShell
        if check_command powershell.exe; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  ✓ PowerShell available"
            fi
        else
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                json_parts+=("$(json_kv "powershell" "missing")")
            else
                echo "  ✗ powershell.exe not found"
                echo "    -> Ensure WSL2 is properly configured"
            fi
            ((issues++)) || true
        fi
        
        # Check mirrored networking
        if check_wsl_mirrored_networking; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  ✓ Mirrored networking enabled"
            fi
        else
            local mirrored_status
            mirrored_status=$(check_mirrored_mode 2>/dev/null || echo "ERROR")
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                json_parts+=("$(json_kv "mirrored_networking" "$mirrored_status")")
            else
                echo "  ✗ Mirrored networking not enabled"
                echo "    -> Run: make doctor-chrome-fix"
            fi
            ((issues++)) || true
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo ""
            echo "[9/10] Chrome/CDP..."
            echo "  - Skipped (not WSL)"
        fi
    fi
    
    # Check 10: Configuration files
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[10/10] Configuration..."
    fi
    if check_file "${PROJECT_DIR}/.env"; then
        if check_env_permissions "${PROJECT_DIR}/.env"; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  ✓ .env exists (permissions OK)"
            fi
        else
            local perms
            perms=$(stat -c "%a" "${PROJECT_DIR}/.env" 2>/dev/null || echo "unknown")
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                json_parts+=("$(json_kv "env_permissions" "$perms")")
                json_parts+=("$(json_kv "env_permissions_issue" "world_readable")")
            else
                echo "  ⚠ .env permissions are $perms (should be 600)"
                echo "    -> Fix: chmod 600 .env"
            fi
            ((warnings++)) || true
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "env_file" "missing")")
        else
            echo "  ✗ .env not found"
            echo "    -> Create: cp .env.example .env"
        fi
        ((issues++)) || true
    fi
    
    # Summary
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        json_parts+=("$(json_num "issues" "$issues")")
        json_parts+=("$(json_num "warnings" "$warnings")")
        
        if (( issues == 0 )); then
            json_parts[0]="$(json_kv "status" "ok")"
            json_parts+=("$(json_num "exit_code" "$EXIT_SUCCESS")")
        else
            json_parts[0]="$(json_kv "status" "issues_found")"
            json_parts+=("$(json_num "exit_code" "$EXIT_DEPENDENCY")")
        fi
        
        local IFS=','
        echo "{${json_parts[*]}}"
    else
        echo ""
        echo "=== Summary ==="
        if (( issues == 0 )); then
            echo "✓ All checks passed!"
            if (( warnings > 0 )); then
                echo "  ($warnings warning(s) - see above)"
            fi
        else
            echo "✗ Found $issues issue(s)"
            if (( warnings > 0 )); then
                echo "  ($warnings warning(s))"
            fi
            echo ""
            echo "Next steps:"
            echo "  1. Fix the issues listed above"
            echo "  2. Run 'make doctor' again to verify"
        fi
    fi
    
    if (( issues > 0 )); then
        return "$EXIT_DEPENDENCY"
    fi
    
    return "$EXIT_SUCCESS"
}

