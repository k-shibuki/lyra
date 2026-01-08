# Lyra Makefile - Unified Interface for Development Operations
#
# Usage: make [target]
# Run 'make help' for available targets
#
# Output Mode:
#   Set LYRA_OUTPUT_JSON=true for JSON output (AI agents / automation)
#   Default is human-readable output
#
#   Example: LYRA_OUTPUT_JSON=true make lint
#   Or add to .env: LYRA_OUTPUT_JSON=true
#
# Script Dependencies:
#   common.sh  <- (base, no dependencies)
#   dev.sh     <- common.sh, podman-compose or docker compose
#   chrome.sh  <- common.sh, curl, (WSL: powershell.exe)
#   test.sh    <- common.sh, pytest, uv
#   mcp.sh     <- common.sh, dev.sh, uv, playwright

.PHONY: help setup test test-all test-e2e test-e2e-internal test-e2e-external lint format clean up down build rebuild logs logs-f shell status clean-containers db-reset
.DEFAULT_GOAL := help

SHELL := /bin/bash
SCRIPTS := ./scripts

# =============================================================================
# SETUP
# =============================================================================

setup: ## Install dependencies with uv (MCP extras)
	@$(SCRIPTS)/setup.sh mcp

setup-full: ## Install all dependencies (full development)
	@$(SCRIPTS)/setup.sh full

setup-ml: ## Install ML dependencies
	@$(SCRIPTS)/setup.sh ml

setup-ml-models: ## Download ML models to host (embedding + NLI)
	@$(SCRIPTS)/ml_models.sh

setup-dev: ## Install development dependencies
	@$(SCRIPTS)/setup.sh dev

# =============================================================================
# CONTAINERS
# =============================================================================

up: ## Start Lyra (auto: uv, .env, build if needed)
	@$(SCRIPTS)/up.sh

down: ## Stop containers
	@$(SCRIPTS)/dev.sh down

build: ## Build containers
	@$(SCRIPTS)/dev.sh build

rebuild: ## Rebuild containers (no cache)
	@$(SCRIPTS)/dev.sh rebuild

logs: ## Show logs (SERVICE=proxy|ollama|ml|tor)
	@$(SCRIPTS)/dev.sh logs $(SERVICE)

logs-f: ## Follow logs (SERVICE=proxy|ollama|ml|tor)
	@$(SCRIPTS)/dev.sh logs -f $(SERVICE)

shell: ## Enter container shell (default: proxy)
	@$(SCRIPTS)/dev.sh shell

status: ## Show container status
	@$(SCRIPTS)/dev.sh status

clean-containers: ## Remove containers and images
	@$(SCRIPTS)/dev.sh clean

# dev-* aliases for backward compatibility
dev-up: up
dev-down: down
dev-build: build
dev-rebuild: rebuild
dev-logs: logs
dev-logs-f: logs-f
dev-shell: shell
dev-status: status
dev-clean: clean-containers

# =============================================================================
# OLLAMA MODEL MANAGEMENT
# =============================================================================

ollama-pull: ## Pull Ollama model (default: qwen2.5:3b, MODEL= to override)
	@$(SCRIPTS)/ollama.sh pull $(or $(MODEL),qwen2.5:3b)

ollama-list: ## List available Ollama models
	@$(SCRIPTS)/ollama.sh list

ollama-status: ## Show Ollama model status
	@$(SCRIPTS)/ollama.sh status

# =============================================================================
# MCP SERVER
# =============================================================================

mcp: ## Start MCP server (for Cursor)
	@$(SCRIPTS)/mcp.sh

mcp-stop: ## Stop MCP server (for code reload)
	@$(SCRIPTS)/mcp.sh stop

mcp-restart: ## Restart MCP server (stop + instructions)
	@$(SCRIPTS)/mcp.sh restart

mcp-status: ## Show MCP server status
	@$(SCRIPTS)/mcp.sh status

mcp-logs: ## Show MCP server logs (tail -100)
	@$(SCRIPTS)/mcp.sh logs

mcp-logs-f: ## Follow MCP server logs (tail -f)
	@$(SCRIPTS)/mcp.sh logs -f

mcp-logs-grep: ## Search MCP logs (PATTERN= required)
	@$(SCRIPTS)/mcp.sh logs --grep "$(PATTERN)"

# =============================================================================
# DOCTOR (Environment Check)
# =============================================================================

doctor: ## Check environment dependencies and configuration
	@$(SCRIPTS)/doctor.sh check

doctor-chrome-fix: ## Fix WSL2 Chrome networking (via doctor)
	@$(SCRIPTS)/doctor.sh chrome-fix

# =============================================================================
# CHROME / BROWSER (Dynamic Worker Pool)
# =============================================================================
# Each worker gets its own Chrome instance with dedicated port and profile.
# Number of instances is driven by num_workers in settings.yaml.

chrome: ## Show Chrome Pool status (all workers)
	@$(SCRIPTS)/chrome.sh status

chrome-start: ## Start Chrome Pool for all workers
	@$(SCRIPTS)/chrome.sh start

chrome-stop: ## Stop all Chrome instances
	@$(SCRIPTS)/chrome.sh stop

chrome-restart: ## Restart Chrome Pool
	@$(SCRIPTS)/chrome.sh restart

chrome-diagnose: ## Diagnose Chrome connection issues
	@$(SCRIPTS)/chrome.sh diagnose

# =============================================================================
# TESTING
# =============================================================================
# RUNTIME=container/venv to override auto-detection (venv preferred)
# RUN_ID= to specify a specific test run for check/kill/debug

test: ## Run all tests (use test-check for results; TARGET= for specific files)
	@$(SCRIPTS)/test.sh run $(if $(RUNTIME),--$(RUNTIME),) $(or $(TARGET),tests/)

test-all: ## Run ALL tests including e2e and slow (venv, no marker exclusions)
	@LYRA_TEST_LAYER=all $(SCRIPTS)/test.sh run --venv $(or $(TARGET),tests/)

test-unit: ## Run unit tests only (TARGET= for specific files)
	@$(SCRIPTS)/test.sh run $(if $(RUNTIME),--$(RUNTIME),) $(or $(TARGET),tests/) -m unit

test-integration: ## Run integration tests only (TARGET= for specific files)
	@$(SCRIPTS)/test.sh run $(if $(RUNTIME),--$(RUNTIME),) $(or $(TARGET),tests/) -m integration

test-e2e: ## Run E2E tests (TARGET= for specific files)
	LYRA_TEST_LAYER=e2e $(SCRIPTS)/test.sh run $(if $(RUNTIME),--$(RUNTIME),) $(or $(TARGET),tests/) -m e2e

test-e2e-internal: ## Run E2E tests against local services only (ML/Ollama/proxy)
	LYRA_TEST_LAYER=e2e $(SCRIPTS)/test.sh run $(if $(RUNTIME),--$(RUNTIME),) $(or $(TARGET),tests/) -m "e2e and internal"

test-e2e-external: ## Run E2E tests that access internet services (SERP/FETCH/Academic APIs)
	LYRA_TEST_LAYER=e2e $(SCRIPTS)/test.sh run $(if $(RUNTIME),--$(RUNTIME),) $(or $(TARGET),tests/) -m "e2e and external"

test-check: ## Check test run status (RUN_ID= optional, RUNTIME=container/venv)
	@$(SCRIPTS)/test.sh check $(if $(RUNTIME),--$(RUNTIME),) $(RUN_ID)

test-kill: ## Kill running tests (RUN_ID= optional)
	@$(SCRIPTS)/test.sh kill $(RUN_ID)

test-kill-all: ## Emergency kill all pytest processes
	@$(SCRIPTS)/test.sh kill --all

test-env: ## Show test environment info
	@$(SCRIPTS)/test.sh env

test-debug: ## Debug test run status (RUN_ID= optional)
	@$(SCRIPTS)/test.sh debug $(RUN_ID)

test-scripts: ## Run shell script tests
	@$(SCRIPTS)/test_scripts.sh

test-prompts: ## Run prompt template tests (syntax, rendering, structure)
	@$(SCRIPTS)/test_extra.sh prompts

test-llm-output: ## Run LLM output parsing tests
	@$(SCRIPTS)/test_extra.sh llm-output

# =============================================================================
# CODE QUALITY
# =============================================================================
# Output format controlled by LYRA_OUTPUT_JSON environment variable

lint: ## Run linters (ruff)
	@$(SCRIPTS)/quality.sh lint

lint-fix: ## Run linters with auto-fix
	@$(SCRIPTS)/quality.sh lint-fix

format: ## Format code (black + ruff)
	@$(SCRIPTS)/quality.sh format

format-check: ## Check code formatting
	@$(SCRIPTS)/quality.sh format-check

typecheck: ## Run type checker (mypy)
	@$(SCRIPTS)/quality.sh typecheck

jsonschema: ## Validate JSON Schema files
	@$(SCRIPTS)/quality.sh jsonschema

shellcheck: ## Run shellcheck on scripts
	@$(SCRIPTS)/quality.sh shellcheck

deadcode: ## Check for dead code (manual, not CI - may have false positives). Override via env: LYRA_SCRIPT__DEADCODE_MIN_CONFIDENCE=60 LYRA_SCRIPT__DEADCODE_FAIL=true
	@$(SCRIPTS)/deadcode.sh

quality: lint format-check typecheck jsonschema shellcheck ## Run all quality checks

# =============================================================================
# CLEANUP
# =============================================================================

clean: ## Clean temporary files
	@$(SCRIPTS)/clean.sh clean

clean-all: clean clean-containers ## Clean everything including containers
	@$(SCRIPTS)/clean.sh clean-all

db-reset: ## Reset database (destructive: deletes data/lyra.db, recreates on next server start)
	@$(SCRIPTS)/db.sh reset

# =============================================================================
# HELP
# =============================================================================

help: ## Show this help
	@echo "Lyra Development Commands"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Output Mode:"
	@echo "  - LYRA_OUTPUT_JSON=true : JSON output (machine-readable; stdout stays JSON)"
	@echo "  - LYRA_QUIET=true       : suppress non-essential human output"
	@echo "  Example: LYRA_OUTPUT_JSON=true make status"
	@echo "  Example: LYRA_QUIET=true make status"
	@echo ""
	@echo "Detail toggles (human mode):"
	@echo "  - LYRA_DEV_STATUS_DETAIL=full     : show full container/network listing for 'make status'"
	@echo "  - LYRA_CHROME_STATUS_DETAIL=full  : show per-worker details for 'make chrome'"
	@echo "  - LYRA_TEST_SHOW_TAIL_ON_SUCCESS=true : show test output tail even when tests pass"
	@echo "  - LYRA_TEST_JSON_DETAIL=full|minimal  : control JSON verbosity for 'make test'"
	@echo ""
	@echo "Quick Start:"
	@grep -E '^(up|down|build|logs|shell|status):.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Setup:"
	@grep -E '^setup[a-zA-Z_-]*:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "MCP:"
	@grep -E '^mcp[a-zA-Z_-]*:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Doctor:"
	@grep -E '^doctor[a-zA-Z_-]*:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Chrome:"
	@grep -E '^chrome[a-zA-Z_-]*:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Ollama:"
	@grep -E '^ollama[a-zA-Z_-]*:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Testing:"
	@grep -E '^test[a-zA-Z0-9_-]*:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Code Quality:"
	@grep -E '^(lint|format|typecheck|quality)[a-zA-Z_-]*:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Cleanup:"
	@grep -E '^clean[a-zA-Z_-]*:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
