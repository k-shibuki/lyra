"""
Lancet Proxy Server.

Lightweight reverse proxy for Ollama and ML Server.
Runs inside lancet container, exposes port 8080.

Routes:
  /ollama/* -> http://ollama:11434/*
  /ml/* -> http://lancet-ml:8100/*
  /health -> Health check

This enables WSL-based MCP server to access containerized inference services
while maintaining network isolation (lancet-internal remains internal: true).

Security:
- Proxy port is bound to 127.0.0.1 only (localhost)
- No authentication (trusted local network)
- Ollama/ML remain on internal network
"""

import asyncio
import os
import signal

import httpx
import structlog
from aiohttp import web

logger = structlog.get_logger(__name__)

# Target services (container names on internal network)
OLLAMA_URL = os.environ.get("OLLAMA_TARGET_URL", "http://ollama:11434")
ML_SERVER_URL = os.environ.get("ML_TARGET_URL", "http://lancet-ml:8100")

# Proxy settings
PROXY_HOST = os.environ.get("PROXY_HOST", "0.0.0.0")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8080"))
REQUEST_TIMEOUT = float(os.environ.get("PROXY_TIMEOUT", "300"))  # 5 min for LLM


async def proxy_request(
    request: web.Request,
    target_base_url: str,
    path_prefix: str,
) -> web.Response:
    """
    Proxy a request to target service.

    Args:
        request: Incoming aiohttp request.
        target_base_url: Base URL of target service.
        path_prefix: Prefix to strip from path (e.g., "/ollama").

    Returns:
        Proxied response.
    """
    # Build target URL
    path = request.path
    if path.startswith(path_prefix):
        path = path[len(path_prefix) :]
    if not path.startswith("/"):
        path = "/" + path

    target_url = f"{target_base_url}{path}"
    if request.query_string:
        target_url = f"{target_url}?{request.query_string}"

    # Read request body
    body = await request.read()

    # Forward headers (excluding hop-by-hop headers)
    headers = {}
    for key, value in request.headers.items():
        key_lower = key.lower()
        if key_lower not in ("host", "connection", "transfer-encoding", "content-length"):
            headers[key] = value

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body if body else None,
            )

            # Build response
            response_headers = {}
            for key, value in response.headers.items():
                key_lower = key.lower()
                if key_lower not in ("connection", "transfer-encoding", "content-encoding"):
                    response_headers[key] = value

            return web.Response(
                status=response.status_code,
                headers=response_headers,
                body=response.content,
            )

    except httpx.ConnectError as e:
        logger.error("Proxy connection error", target=target_url, error=str(e))
        return web.json_response(
            {"error": f"Connection failed: {target_base_url}", "details": str(e)},
            status=503,
        )
    except httpx.TimeoutException as e:
        logger.error("Proxy timeout", target=target_url, error=str(e))
        return web.json_response(
            {"error": "Request timeout", "details": str(e)},
            status=504,
        )
    except Exception as e:
        logger.error("Proxy error", target=target_url, error=str(e))
        return web.json_response(
            {"error": "Proxy error", "details": str(e)},
            status=500,
        )


async def handle_ollama(request: web.Request) -> web.Response:
    """Proxy requests to Ollama."""
    return await proxy_request(request, OLLAMA_URL, "/ollama")


async def handle_ml(request: web.Request) -> web.Response:
    """Proxy requests to ML Server."""
    return await proxy_request(request, ML_SERVER_URL, "/ml")


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    # Check connectivity to backend services
    ollama_health: dict[str, str] = {"url": OLLAMA_URL, "status": "unknown"}
    ml_health: dict[str, str] = {"url": ML_SERVER_URL, "status": "unknown"}

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Check Ollama
        try:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            ollama_health["status"] = "ok" if resp.status_code == 200 else "error"
        except Exception as e:
            ollama_health["status"] = f"error: {e}"

        # Check ML Server
        try:
            resp = await client.get(f"{ML_SERVER_URL}/health")
            ml_health["status"] = "ok" if resp.status_code == 200 else "error"
        except Exception as e:
            ml_health["status"] = f"error: {e}"

    # Overall status
    status = "ok"
    if "error" in ollama_health["status"] or "error" in ml_health["status"]:
        status = "degraded"

    health = {"status": status, "ollama": ollama_health, "ml_server": ml_health}

    return web.json_response(health)


def create_app() -> web.Application:
    """Create aiohttp application."""
    app = web.Application()

    # Routes
    app.router.add_route("*", "/ollama/{path:.*}", handle_ollama)
    app.router.add_route("*", "/ollama", handle_ollama)
    app.router.add_route("*", "/ml/{path:.*}", handle_ml)
    app.router.add_route("*", "/ml", handle_ml)
    app.router.add_get("/health", handle_health)

    # Root health check
    app.router.add_get("/", handle_health)

    return app


async def main() -> None:
    """Run proxy server."""
    logger.info(
        "Starting Lancet Proxy Server",
        host=PROXY_HOST,
        port=PROXY_PORT,
        ollama_url=OLLAMA_URL,
        ml_server_url=ML_SERVER_URL,
    )

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, PROXY_HOST, PROXY_PORT)
    await site.start()

    logger.info(f"Proxy server running on http://{PROXY_HOST}:{PROXY_PORT}")

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def handle_signal(sig: int) -> None:
        logger.info("Received shutdown signal", signal=sig)
        stop_event.set()

    import functools
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, functools.partial(handle_signal, sig))

    await stop_event.wait()

    logger.info("Shutting down proxy server")
    await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
