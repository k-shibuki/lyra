#!/bin/bash
# Dev Help Functions
#
# Functions for displaying dev.sh help information.

# Function to show help (defined early for use before dependency check)
_show_help() {
    echo "Lyra Development Environment (Podman)"
    echo ""
    echo "Usage: ./scripts/dev.sh [global-options] [command]"
    echo ""
    echo "Commands:"
    echo "  up        Start all services"
    echo "  down      Stop all services"
    echo "  build     Build containers"
    echo "  rebuild   Rebuild containers (no cache)"
    echo "  shell     Enter development shell"
    echo "  logs      Show logs (logs [service] or logs -f [service])"
    echo "  test      Run tests"
    echo "  mcp       Start MCP server"
    echo "  research  Run research query"
    echo "  status    Show container status"
    echo "  clean     Remove containers and images"
    echo ""
    echo "Global Options:"
    echo "  --json        Output in JSON format (machine-readable)"
    echo "  --quiet, -q   Suppress non-essential output"
    echo ""
    echo "Examples:"
    echo "  make dev-status              # Show container status"
    echo "  make dev-up                  # Start containers"
    echo ""
    echo "Exit Codes:"
    echo "  0   (EXIT_SUCCESS)     Operation successful"
    echo "  3   (EXIT_CONFIG)      Configuration error (.env missing)"
    echo "  4   (EXIT_DEPENDENCY)  Missing dependency (podman/podman-compose)"
    echo ""
}

