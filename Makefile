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

.PHONY: help setup test lint format clean up down build rebuild logs logs-f shell status clean-containers
.DEFAULT_GOAL := help

SHELL := /bin/bash
SCRIPTS := ./scripts

# =============================================================================
# SETUP
# =============================================================================

setup: ## Install dependencies with uv (MCP extras)
	uv sync --frozen --extra mcp

setup-full: ## Install all dependencies (full development)
	uv sync --frozen --extra full

setup-ml: ## Install ML dependencies
	uv sync --frozen --extra ml

setup-ml-models: ## Download ML models to host (embedding + NLI)
	@echo "Downloading ML models to models/huggingface/..."
	@mkdir -p models/huggingface
	HF_HOME=$(PWD)/models/huggingface \
	LYRA_ML__MODEL_PATHS_FILE=$(PWD)/models/model_paths.json \
	uv run python scripts/download_models.py

setup-dev: ## Install development dependencies
	uv sync --frozen --group dev

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
	@podman network connect lyra_lyra-net ollama 2>/dev/null || true
	@podman exec ollama ollama pull $(or $(MODEL),qwen2.5:3b)
	@podman network disconnect lyra_lyra-net ollama 2>/dev/null || true

ollama-list: ## List available Ollama models
	@podman exec ollama ollama list

ollama-status: ## Show Ollama model status
	@podman exec ollama ollama list 2>/dev/null || echo "Ollama container not running"

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
# RUNTIME=container/venv to override auto-detection (container preferred)
# RUN_ID= to specify a specific test run for check/kill/debug

test: ## Run all tests (use test-check for results; TARGET= for specific files)
	@$(SCRIPTS)/test.sh run $(if $(RUNTIME),--$(RUNTIME),) $(or $(TARGET),tests/)

test-unit: ## Run unit tests only (TARGET= for specific files)
	@$(SCRIPTS)/test.sh run $(if $(RUNTIME),--$(RUNTIME),) $(or $(TARGET),tests/) -m unit

test-integration: ## Run integration tests only (TARGET= for specific files)
	@$(SCRIPTS)/test.sh run $(if $(RUNTIME),--$(RUNTIME),) $(or $(TARGET),tests/) -m integration

test-e2e: ## Run E2E tests (TARGET= for specific files)
	LYRA_TEST_LAYER=e2e $(SCRIPTS)/test.sh run $(if $(RUNTIME),--$(RUNTIME),) $(or $(TARGET),tests/) -m e2e

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
	@uv run pytest tests/prompts/ -v

test-llm-output: ## Run LLM output parsing tests
	@uv run pytest tests/test_llm_output.py -v

# =============================================================================
# CODE QUALITY
# =============================================================================
# Output format controlled by LYRA_OUTPUT_JSON environment variable

lint: ## Run linters (ruff)
ifeq ($(LYRA_OUTPUT_JSON),true)
	uv run ruff check --output-format json src/ tests/
else
	uv run ruff check src/ tests/
endif

lint-fix: ## Run linters with auto-fix
	uv run ruff check --fix src/ tests/

format: ## Format code (black + ruff)
	uv run black src/ tests/
	uv run ruff check --fix src/ tests/

format-check: ## Check code formatting
	uv run black --check src/ tests/

typecheck: ## Run type checker (mypy)
ifeq ($(LYRA_OUTPUT_JSON),true)
	uv run mypy --output json src/ tests/
else
	uv run mypy src/ tests/
endif

jsonschema: ## Validate JSON Schema files
	uv run check-jsonschema --schemafile http://json-schema.org/draft-07/schema# src/mcp/schemas/*.json

shellcheck: ## Run shellcheck on scripts
	find scripts -name "*.sh" -type f | xargs shellcheck -x -e SC1091

quality: lint format-check typecheck jsonschema shellcheck ## Run all quality checks

# =============================================================================
# CLEANUP
# =============================================================================

clean: ## Clean temporary files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache 2>/dev/null || true

clean-all: clean clean-containers ## Clean everything including containers
	rm -rf .venv 2>/dev/null || true

# =============================================================================
# HELP
# =============================================================================

help: ## Show this help
	@echo "Lyra Development Commands"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Output Mode:"
	@echo "  Set LYRA_OUTPUT_JSON=true for JSON output (AI agents)"
	@echo "  Example: LYRA_OUTPUT_JSON=true make lint"
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
