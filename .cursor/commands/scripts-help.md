# scripts-help

## Purpose

Reference for project development commands.

## Unified Interface: Makefile

All development operations are available via `make`. Run `make help` for the full list of available commands.

```bash
make help
```

### Quick Reference

| Category | Command | Purpose |
|----------|---------|---------|
| **Setup** | `make setup` | Install dependencies (MCP extras) |
| | `make setup-full` | Install all dependencies |
| | `make setup-dev` | Install development dependencies |
| **Development** | `make dev-up` | Start containers |
| | `make dev-down` | Stop containers |
| | `make dev-shell` | Enter development shell |
| | `make dev-logs` | Show container logs |
| | `make dev-status` | Container status |
| **Testing** | `make test` | Run all tests |
| | `make test-unit` | Run unit tests only |
| | `make test-check` | Check test run status |
| | `make test-kill` | Kill running tests |
| | `make test-env` | Show environment info |
| **Chrome** | `make chrome` | Check Chrome CDP status |
| | `make chrome-start` | Start Chrome with CDP |
| | `make chrome-stop` | Stop Chrome |
| | `make chrome-diagnose` | Diagnose connectivity |
| **Quality** | `make lint` | Run linters |
| | `make format` | Format code |
| | `make typecheck` | Run type checker |
| | `make quality` | All quality checks |
| **MCP** | `make mcp` | Start MCP server |
| **Cleanup** | `make clean` | Clean temporary files |
| | `make clean-all` | Clean everything |

## Direct Script Access (advanced)

For fine-grained control, scripts are available under `scripts/`:

| Script | Purpose |
|--------|---------|
| `scripts/test.sh` | Test runner with run_id tracking |
| `scripts/dev.sh` | Container management |
| `scripts/chrome.sh` | Chrome CDP management |
| `scripts/mcp.sh` | MCP server launcher |
| `scripts/common.sh` | Shared utilities (source only) |

**Note**: Prefer `make` commands for consistency. Use scripts directly only when fine-grained control is needed (e.g., `./scripts/test.sh run tests/test_xxx.py -k specific_test`).
