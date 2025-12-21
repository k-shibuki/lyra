# scripts-help

## Purpose

Reference for project helper scripts (`scripts/*.sh`).

## `dev.sh` (development environment)

```bash
./scripts/dev.sh up        # Start container
./scripts/dev.sh down      # Stop container
./scripts/dev.sh shell     # Open dev shell
./scripts/dev.sh build     # Build container
./scripts/dev.sh rebuild   # Rebuild without cache
./scripts/dev.sh logs      # Show logs (last 50 lines, non-hanging)
./scripts/dev.sh logs -f   # Follow logs (Ctrl+C to stop)
./scripts/dev.sh status    # Container status
./scripts/dev.sh test      # Run tests inside container
./scripts/dev.sh mcp       # Start MCP server
./scripts/dev.sh research  # Run research query
./scripts/dev.sh clean     # Remove container/images
```

## `test.sh` (test runner, AI-friendly)

```bash
./scripts/test.sh run [target]  # Start tests (default: tests/)
./scripts/test.sh check         # Status (DONE/RUNNING)
./scripts/test.sh get           # Fetch results (tail)
./scripts/test.sh kill          # Kill pytest
```

Polling pattern:

```bash
./scripts/test.sh run tests/
for i in {1..60}; do
    sleep 5
    status=$(./scripts/test.sh check 2>&1)
    echo "[$i] $status"
    if echo "$status" | grep -qE "(DONE|passed|failed|skipped|deselected)"; then
        break
    fi
done
./scripts/test.sh get
```

Completion logic:

- `check` returns `DONE` when output contains `passed`/`failed`/`skipped`/`deselected`
- Otherwise it uses file modification time (no updates for 5s => `DONE`)

## `chrome.sh` (Chrome management)

```bash
./scripts/chrome.sh check [port]     # Check connectivity
./scripts/chrome.sh start [port]     # Start Chrome (isolated profile)
./scripts/chrome.sh stop [port]      # Stop Chrome
./scripts/chrome.sh diagnose [port]  # Diagnose connectivity (WSL)
./scripts/chrome.sh fix [port]       # Auto-fix WSL2 networking
```

Default port: `.env` key `LYRA_BROWSER__CHROME_PORT` (default: 9222).
Chrome uses a dedicated `LyraChrome` profile to avoid affecting existing sessions.

## `mcp.sh` (MCP server)

```bash
./scripts/mcp.sh
```

If the container is not running, it will run `dev.sh up`. Search tools require Chrome connectivity; if missing, follow the error guidance to run `chrome.sh start`.

## `common.sh` (shared utilities)

```bash
source scripts/common.sh  # Do not execute directly; source from other scripts
```

Provides:

- `.env` loading
- Logging helpers (`log_info`, `log_warn`, `log_error`)
- Container helpers (`check_container_running`, `wait_for_container`)
- Shared constants (`CHROME_PORT`, `SOCAT_PORT`, `CONTAINER_NAME`, etc.)
