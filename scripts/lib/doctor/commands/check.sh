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
        echo "[1/13] Environment..."
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
    
    # Check 2: make
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[2/13] make..."
    fi
    if check_make; then
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo "  ✓ make found"
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "make" "missing")")
        else
            echo "  ✗ make not found"
            echo "    -> Install: sudo apt install -y make"
        fi
        ((issues++)) || true
    fi
    
    # Check 3: curl
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[3/13] curl..."
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
            echo "    -> Install: sudo apt install -y curl"
        fi
        ((issues++)) || true
    fi
    
    # Check 4: uv
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[4/13] uv..."
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

    # Check 5: Python environment (.venv + version)
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[5/13] Python environment..."
    fi
    if check_dir "${VENV_DIR}"; then
        if check_python_version "${VENV_DIR}/bin/python"; then
            local py_version
            py_version=$("${VENV_DIR}/bin/python" -V 2>&1 | awk '{print $2}' || echo "unknown")
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  ✓ .venv exists (Python $py_version)"
            fi
        else
            local py_version
            py_version=$("${VENV_DIR}/bin/python" -V 2>&1 | awk '{print $2}' || echo "unknown")
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                json_parts+=("$(json_kv "python_version" "$py_version")")
                json_parts+=("$(json_kv "python_version_issue" "expected_3.14+")")
            else
                echo "  ⚠ .venv exists but Python version is $py_version (expected 3.14+)"
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

    # Check 6: Rust toolchain (sudachipy build)
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[6/13] Rust toolchain..."
    fi
    local rust_min="1.82.0"
    if check_rustc; then
        local rustc_version
        rustc_version="$(get_rustc_version)"
        if check_rustc_min_version "$rust_min"; then
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                json_parts+=("$(json_kv "rustc_version" "$rustc_version")")
            else
                echo "  ✓ rustc found (rustc $rustc_version)"
            fi
        else
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                json_parts+=("$(json_kv "rustc_version" "$rustc_version")")
                json_parts+=("$(json_kv "rustc_issue" "expected_${rust_min}+")")
            else
                echo "  ✗ rustc is too old (rustc $rustc_version, expected ${rust_min}+)"
                echo "    -> Recommended: install rustup (apt rustc may be too old)"
                echo "       curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"
                echo "       source \$HOME/.cargo/env"
            fi
            ((issues++)) || true
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "rustc" "missing")")
        else
            echo "  ✗ rustc not found (required for sudachipy build)"
            echo "    -> Install rustup:"
            echo "       curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"
            echo "       source \$HOME/.cargo/env"
        fi
        ((issues++)) || true
    fi
    if ! check_rustup; then
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "rustup" "missing")")
        else
            echo "  ⚠ rustup not found (recommended)"
        fi
        ((warnings++)) || true
    fi
    
    # Check 7: Container runtime (podman or docker)
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[7/13] Container runtime..."
    fi
    local has_podman="false"
    if check_command podman && check_command podman-compose; then
        has_podman="true"
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo "  ✓ podman and podman-compose found"
        fi
    elif check_command docker; then
        # Check for docker compose (V2) or docker-compose (V1)
        if docker compose version &> /dev/null; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  ✓ docker and docker compose found"
            fi
        elif check_command docker-compose; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  ✓ docker and docker-compose found"
            fi
        else
            if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                json_parts+=("$(json_kv "docker_compose" "missing")")
            else
                echo "  ✗ docker found but compose not available"
                echo "    -> Install: sudo apt install docker-compose-plugin"
            fi
            ((issues++)) || true
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
            json_parts+=("$(json_kv "container_runtime" "missing")")
        else
            echo "  ✗ No container runtime found"
            echo "    -> Install: sudo apt install podman podman-compose"
            echo "    -> Or: sudo apt install docker.io docker-compose-plugin"
        fi
        ((issues++)) || true
    fi
    
    # Check 8: GPU presence (nvidia-smi)
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[8/13] GPU (nvidia-smi)..."
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
            echo "    -> Required for container GPU passthrough (ml, ollama)"
            echo "    -> Install NVIDIA drivers and nvidia-container-toolkit"
            echo "    -> Then: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
        fi
        ((issues++)) || true
    fi

    # Check 9: Container GPU readiness (Podman CDI / Docker nvidia-container-toolkit)
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[9/13] GPU (Container Runtime)..."
    fi
    if check_gpu; then
        if [[ "$has_podman" == "true" ]]; then
            # Podman: requires CDI config for nvidia.com/gpu=all
            local cdi_ok="true"
            if ! check_nvidia_ctk; then
                cdi_ok="false"
            fi
            if ! check_podman_cdi; then
                cdi_ok="false"
            fi

            if [[ "$cdi_ok" == "true" ]]; then
                if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                    echo "  ✓ Podman: nvidia-ctk found"
                    echo "  ✓ Podman: CDI config found (/etc/cdi/nvidia.yaml)"
                else
                    json_parts+=("$(json_kv "podman_cdi" "ok")")
                fi
            else
                if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                    json_parts+=("$(json_kv "podman_cdi" "missing")")
                else
                    echo "  ✗ Podman CDI is not configured (required for nvidia.com/gpu=all)"
                    echo "    -> Install NVIDIA Container Toolkit (requires NVIDIA apt repo):"
                    echo "       curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
                    echo "       curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \\"
                    echo "         sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \\"
                    echo "         sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list"
                    echo "       sudo apt update && sudo apt install -y nvidia-container-toolkit"
                    echo "       sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
                fi
                ((issues++)) || true
            fi
        elif check_command docker; then
            # Docker: nvidia-container-toolkit enables GPU via deploy.resources in compose
            if check_nvidia_ctk; then
                if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                    echo "  ✓ Docker: nvidia-container-toolkit found"
                else
                    json_parts+=("$(json_kv "docker_gpu" "ok")")
                fi
            else
                if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
                    json_parts+=("$(json_kv "docker_gpu" "missing")")
                else
                    echo "  ✗ Docker: nvidia-container-toolkit not found"
                    echo "    -> Install NVIDIA Container Toolkit (requires NVIDIA apt repo):"
                    echo "       curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
                    echo "       curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \\"
                    echo "         sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \\"
                    echo "         sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list"
                    echo "       sudo apt update && sudo apt install -y nvidia-container-toolkit"
                    echo "       sudo systemctl restart docker"
                fi
                ((issues++)) || true
            fi
        else
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  - Skipped (no container runtime detected)"
            fi
        fi
    else
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo "  - Skipped (no NVIDIA GPU)"
        fi
    fi
    
    # Check 10: Disk space (~25GB required)
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[10/13] Disk space..."
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
            echo "    -> Free up disk space before running make build"
        fi
        ((issues++)) || true
    fi
    
    # Check 11: Chrome installed
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[11/13] Chrome installed..."
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
                echo "    -> Option A: Install Google Chrome (recommended; official repo)"
                echo "         curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg"
                echo "         echo \"deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main\" | sudo tee /etc/apt/sources.list.d/google-chrome.list"
                echo "         sudo apt update && sudo apt install -y google-chrome-stable"
                echo "    -> Option B: Install Chromium via snap (easier but less stable)"
                echo "         sudo snap install chromium"
                echo "    Note: 'apt install chromium-browser' may fail on Ubuntu 24.04 (redirects to snap)"
            fi
        fi
        ((issues++)) || true
    fi
    
    # Check 12: Chrome/CDP (WSL only)
    if [[ "$env_type" == "wsl" ]]; then
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo ""
            echo "[12/13] Chrome/CDP (WSL)..."
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
            echo "[12/13] Chrome/CDP..."
            echo "  - Skipped (not WSL)"
        fi
    fi
    
    # Check 13: Configuration files
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo ""
        echo "[13/13] Configuration..."
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
            echo "Quick fix:"
            echo "  sudo apt install -y make curl podman podman-compose"
            echo "  curl -LsSf https://astral.sh/uv/install.sh | sh && source \$HOME/.local/bin/env"
            echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && source \$HOME/.cargo/env"
            echo "  # For Podman GPU (CDI): install NVIDIA Container Toolkit + generate /etc/cdi/nvidia.yaml"
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

