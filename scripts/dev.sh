#!/bin/bash
# Lancet Development Environment (Podman)
# Usage: ./scripts/dev.sh [command]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Podman only
if ! command -v podman &> /dev/null; then
    echo "Error: podman not found"
    echo "Install with: sudo apt install podman"
    exit 1
fi

if ! command -v podman-compose &> /dev/null; then
    echo "Error: podman-compose not found"
    echo "Install with: sudo apt install podman-compose"
    exit 1
fi

COMPOSE="podman-compose"

case "${1:-help}" in
    up)
        echo "Starting Lancet development environment..."
        $COMPOSE up -d
        echo ""
        echo "Services started:"
        echo "  - Tor SOCKS: localhost:9050"
        echo "  - Lancet: Running in container"
        echo ""
        echo "To enter the development shell: ./scripts/dev.sh shell"
        ;;
    
    down)
        echo "Stopping Lancet development environment..."
        $COMPOSE down
        ;;
    
    build)
        echo "Building containers..."
        $COMPOSE build
        ;;
    
    rebuild)
        echo "Rebuilding containers from scratch..."
        $COMPOSE build --no-cache
        ;;
    
    shell)
        echo "Entering development shell..."
        # Build dev image if not exists
        podman build -t lancet-dev:latest -f Dockerfile.dev .
        
        podman run -it --rm \
            -v "$PROJECT_DIR/src:/app/src:rw" \
            -v "$PROJECT_DIR/config:/app/config:ro" \
            -v "$PROJECT_DIR/data:/app/data:rw" \
            -v "$PROJECT_DIR/logs:/app/logs:rw" \
            -v "$PROJECT_DIR/tests:/app/tests:rw" \
            --network lancet_lancet-net \
            -e TOR_SOCKS_HOST=lancet-tor \
            --name lancet-dev \
            lancet-dev:latest \
            /bin/bash
        ;;
    
    logs)
        # AI-friendly: no -f by default, use --tail
        if [ "$2" = "-f" ]; then
            $COMPOSE logs -f "${3:-}"
        else
            $COMPOSE logs --tail=50 "${2:-}"
        fi
        ;;
    
    test)
        echo "Running tests..."
        $COMPOSE exec lancet pytest tests/ -v
        ;;
    
    mcp)
        echo "Starting MCP server..."
        $COMPOSE exec lancet python -m src.main mcp
        ;;
    
    research)
        if [ -z "$2" ]; then
            echo "Usage: ./scripts/dev.sh research \"Your query\""
            exit 1
        fi
        echo "Running research: $2"
        $COMPOSE exec lancet python -m src.main research --query "$2"
        ;;
    
    status)
        $COMPOSE ps
        ;;
    
    clean)
        echo "Cleaning up containers and images..."
        $COMPOSE down --rmi local --volumes
        ;;
    
    *)
        echo "Lancet Development Environment (Podman)"
        echo ""
        echo "Usage: ./scripts/dev.sh [command]"
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
        ;;
esac
