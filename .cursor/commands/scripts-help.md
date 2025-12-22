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

Notes:
- `dev.sh` uses `podman-compose` under the hood (see `scripts/dev.sh` header).
- `./scripts/dev.sh test` runs `pytest tests/ -v` inside the container and does **not** accept extra args.
  - To run an arbitrary command inside the container, use `./scripts/dev.sh shell` and run it there.

## `test.sh` (test runner, AI-friendly)

```bash
./scripts/test.sh run [--container|--venv|--auto] [--name NAME] [--] [pytest_args...]  # Start tests (default: tests/)
./scripts/test.sh check         # Wait until DONE and print result tail
./scripts/test.sh kill          # Kill pytest
./scripts/test.sh env           # Show environment info (venv/container/cloud-agent detection)
```

Notes:
- `test.sh` accepts **any pytest args** after `run` (e.g. `tests/test_x.py::TestY -k foo -q`).
- Default runtime is **auto=container > venv**:
  - If a container named `$CONTAINER_NAME` (default: `lyra`) is running, tests run in that container.
  - Otherwise tests run in the local WSL venv (`.venv`).
- You can force the runtime:
  - `--container`: require container (fails if not running)
  - `--venv`: force local venv
  - `--name NAME`: override container name
- `check/get/kill` target the **same runtime as the last `run`** (state file: `/tmp/lyra_test_state.env` by default).

Polling pattern:

```bash
./scripts/test.sh run tests/
./scripts/test.sh check
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
- Shared constants (`CHROME_PORT`, `CONTAINER_NAME`, etc.)
