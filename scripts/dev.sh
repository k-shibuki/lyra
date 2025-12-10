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
        # Check for .env file (required for container networking)
        if [ ! -f "$PROJECT_DIR/.env" ]; then
            echo "Error: .env file not found"
            echo "Copy from template: cp .env.example .env"
            echo "Then edit LANCET_BROWSER__CHROME_HOST with your WSL2 gateway IP"
            exit 1
        fi
        
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
        podman build -t lancet-dev:latest -f Dockerfile .
        
        # Load environment from .env if exists, otherwise use defaults
        ENV_OPTS=""
        if [ -f "$PROJECT_DIR/.env" ]; then
            ENV_OPTS="--env-file $PROJECT_DIR/.env"
        else
            echo "Warning: .env not found, using default environment variables"
            # Fallback defaults for container networking
            ENV_OPTS="-e LANCET_TOR__SOCKS_HOST=tor -e LANCET_TOR__SOCKS_PORT=9050 -e LANCET_LLM__OLLAMA_HOST=http://ollama:11434"
        fi
        
        # Remove existing container if exists
        podman rm -f lancet-dev 2>/dev/null || true
        
        # Create container with primary network
        # Note: Podman doesn't support multiple --network flags in a single run command,
        # so we create the container first, connect to additional networks, then start it
        podman create -it \
            -v "$PROJECT_DIR/src:/app/src:rw" \
            -v "$PROJECT_DIR/config:/app/config:ro" \
            -v "$PROJECT_DIR/data:/app/data:rw" \
            -v "$PROJECT_DIR/logs:/app/logs:rw" \
            -v "$PROJECT_DIR/tests:/app/tests:rw" \
            --network lancet_lancet-net \
            $ENV_OPTS \
            --name lancet-dev \
            lancet-dev:latest \
            /bin/bash
        
        # Connect to secondary network for LLM services
        podman network connect lancet_lancet-llm-internal lancet-dev
        
        # Start container interactively and attach
        podman start -ai lancet-dev
        
        # Cleanup after exit (replaces --rm behavior)
        podman rm -f lancet-dev 2>/dev/null || true
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
        $COMPOSE exec lancet python -m src.mcp.server
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
        $COMPOSE down --volumes
        # Remove project images manually (podman-compose doesn't support --rmi)
        podman images --filter "reference=lancet*" -q | xargs -r podman rmi -f 2>/dev/null || true
        podman images --filter "dangling=true" -q | xargs -r podman rmi -f 2>/dev/null || true
        echo "Cleanup complete."
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
