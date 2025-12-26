#!/bin/bash
# Chrome Pool Management Functions
#
# Functions for managing the Chrome worker pool.
# Each worker gets its own Chrome instance with dedicated port and profile.

# Function: show_pool_status
# Description: Show status of all Chrome instances in the pool
# Returns:
#   0: Always succeeds
show_pool_status() {
    local num_workers="${NUM_WORKERS:-2}"
    local base_port="${CHROME_BASE_PORT:-9222}"
    
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        echo '{"workers": ['
        local first=true
        for ((i=0; i<num_workers; i++)); do
            local port=$((base_port + i))
            local profile
            profile=$(get_worker_profile "$i")
            local status="disconnected"
            
            if try_connect "$port" > /dev/null 2>&1; then
                status="connected"
            fi
            
            if [ "$first" = true ]; then
                first=false
            else
                echo ','
            fi
            
            cat <<EOF
  {
    "worker_id": $i,
    "port": $port,
    "profile": "$profile",
    "status": "$status"
  }
EOF
        done
        echo '],'
        echo "\"total\": $num_workers,"
        echo "\"base_port\": $base_port"
        echo '}'
    else
        echo "Chrome Worker Pool Status"
        echo "========================="
        echo "Workers: $num_workers"
        echo "Base Port: $base_port"
        echo ""
        
        local connected=0
        for ((i=0; i<num_workers; i++)); do
            local port=$((base_port + i))
            local profile
            profile=$(get_worker_profile "$i")
            local status="[DISCONNECTED]"
            
            if try_connect "$port" > /dev/null 2>&1; then
                status="[CONNECTED]"
                ((connected++)) || true
            fi
            
            printf "  Worker %d: port=%d profile=%s %s\n" "$i" "$port" "$profile" "$status"
        done
        
        echo ""
        echo "Connected: $connected/$num_workers"
    fi
}

# Function: start_chrome_pool
# Description: Start Chrome for all workers in the pool
# Returns:
#   0: All Chrome instances started successfully
#   1: Some Chrome instances failed to start
start_chrome_pool() {
    local num_workers="${NUM_WORKERS:-2}"
    local base_port="${CHROME_BASE_PORT:-9222}"
    local env_type="${ENV_TYPE:-wsl}"
    
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "Starting Chrome Pool"
        echo "===================="
        echo "Workers: $num_workers"
        echo "Base Port: $base_port"
        echo "Environment: $env_type"
        echo ""
    fi
    
    local success=0
    local failed=0
    local already_running=0
    local results=()
    
    for ((i=0; i<num_workers; i++)); do
        local port=$((base_port + i))
        local profile
        profile=$(get_worker_profile "$i")
        
        # Check if already running
        if try_connect "$port" > /dev/null 2>&1; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  Worker $i (port=$port): Already running"
            fi
            ((already_running++)) || true
            ((success++)) || true
            results+=("{\"worker_id\": $i, \"port\": $port, \"status\": \"already_running\"}")
            continue
        fi
        
        # Start Chrome for this worker
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo -n "  Worker $i (port=$port, profile=$profile): Starting... "
        fi
        
        local start_result=0
        case "$env_type" in
            wsl)
                start_chrome_worker_wsl "$i" "$port" "$profile" || start_result=$?
                ;;
            linux)
                start_chrome_worker_linux "$i" "$port" "$profile" || start_result=$?
                ;;
            *)
                start_result=1
                ;;
        esac
        
        if [ "$start_result" -eq 0 ]; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "OK"
            fi
            ((success++)) || true
            results+=("{\"worker_id\": $i, \"port\": $port, \"status\": \"started\"}")
        else
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "FAILED"
            fi
            ((failed++)) || true
            results+=("{\"worker_id\": $i, \"port\": $port, \"status\": \"failed\"}")
        fi
    done
    
    # Output results
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        echo '{'
        echo "  \"status\": \"$([ $failed -eq 0 ] && echo 'ready' || echo 'partial')\","
        echo "  \"total_workers\": $num_workers,"
        echo "  \"started\": $((success - already_running)),"
        echo "  \"already_running\": $already_running,"
        echo "  \"failed\": $failed,"
        echo "  \"workers\": ["
        local first=true
        for result in "${results[@]}"; do
            if [ "$first" = true ]; then
                first=false
            else
                echo ","
            fi
            echo "    $result"
        done
        echo "  ]"
        echo '}'
    else
        echo ""
        echo "Result: $success/$num_workers ready ($already_running already running, $failed failed)"
    fi
    
    [ $failed -eq 0 ]
}

# Function: stop_chrome_pool
# Description: Stop all Chrome instances in the pool
# Returns:
#   0: All Chrome instances stopped successfully
stop_chrome_pool() {
    local num_workers="${NUM_WORKERS:-2}"
    local base_port="${CHROME_BASE_PORT:-9222}"
    
    if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
        echo "Stopping Chrome Pool"
        echo "===================="
        echo ""
    fi
    
    local stopped=0
    local not_running=0
    local results=()
    
    for ((i=0; i<num_workers; i++)); do
        local port=$((base_port + i))
        
        # Check if running
        if ! try_connect "$port" > /dev/null 2>&1; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "  Worker $i (port=$port): Not running"
            fi
            ((not_running++)) || true
            results+=("{\"worker_id\": $i, \"port\": $port, \"status\": \"not_running\"}")
            continue
        fi
        
        if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
            echo -n "  Worker $i (port=$port): Stopping... "
        fi
        
        # Stop Chrome on this port
        stop_chrome "$port" > /dev/null 2>&1 || true
        
        # Verify stopped
        sleep 0.5
        if ! try_connect "$port" > /dev/null 2>&1; then
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "OK"
            fi
            ((stopped++)) || true
            results+=("{\"worker_id\": $i, \"port\": $port, \"status\": \"stopped\"}")
        else
            if [[ "$LYRA_OUTPUT_JSON" != "true" ]]; then
                echo "STILL RUNNING"
            fi
            results+=("{\"worker_id\": $i, \"port\": $port, \"status\": \"still_running\"}")
        fi
    done
    
    # Output results
    if [[ "$LYRA_OUTPUT_JSON" == "true" ]]; then
        echo '{'
        echo "  \"status\": \"stopped\","
        echo "  \"total_workers\": $num_workers,"
        echo "  \"stopped\": $stopped,"
        echo "  \"not_running\": $not_running,"
        echo "  \"workers\": ["
        local first=true
        for result in "${results[@]}"; do
            if [ "$first" = true ]; then
                first=false
            else
                echo ","
            fi
            echo "    $result"
        done
        echo "  ]"
        echo '}'
    else
        echo ""
        echo "Result: $stopped stopped, $not_running not running"
    fi
}

