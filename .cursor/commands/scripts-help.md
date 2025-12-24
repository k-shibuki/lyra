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
./scripts/test.sh check [run_id]  # Wait until DONE and print result (use run_id from run output)
./scripts/test.sh kill [run_id]   # Kill pytest for specific run
./scripts/test.sh kill --all      # Kill all pytest + clean up all result files
./scripts/test.sh env             # Show environment info (venv/container/cloud-agent detection)
```

Notes:
- `test.sh` accepts **any pytest args** after `run` (e.g. `tests/test_x.py::TestY -k foo -q`).
- **`test.sh` is pytest-only**. For debug scripts (standalone Python), run directly:
  ```bash
  ./.venv/bin/python tests/scripts/debug_{feature}_flow.py
  ```
- Default runtime is **auto=container > venv**:
  - If a container named `$CONTAINER_NAME` (default: `lyra`) is running, tests run in that container.
  - Otherwise tests run in the local WSL venv (`.venv`).
- You can force the runtime:
  - `--container`: require container (fails if not running)
  - `--venv`: force local venv
  - `--name NAME`: override container name
- Each `run` generates a unique `run_id` and displays it. Use this `run_id` with `check`/`kill`.
- Result files are stored in `/tmp/lyra_test/` with unique filenames per run.

Polling pattern:

```bash
./scripts/test.sh run tests/
# Output: "Started. To check results: ./scripts/test.sh check 20251224_123456_12345"
./scripts/test.sh check 20251224_123456_12345
```

Completion logic:

- `check` returns `DONE` when pytest summary line exists AND pytest process has exited
- `check` shows summary first, then tail of output with line count info

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
