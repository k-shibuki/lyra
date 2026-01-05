"""
Main entry point for Lyra.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.database import close_database, get_database
from src.utils.config import ensure_directories, get_settings
from src.utils.logging import configure_logging, get_logger


async def initialize() -> None:
    """Initialize the application."""
    # Ensure directories exist
    ensure_directories()

    # Configure logging
    settings = get_settings()
    configure_logging(
        log_level=settings.general.log_level,
        json_format=True,
    )

    logger = get_logger(__name__)
    logger.info(
        "Lyra initializing",
        version=settings.general.version,
        log_level=settings.general.log_level,
    )

    # Initialize database
    await get_database()

    logger.info("Lyra initialized successfully")


async def shutdown() -> None:
    """Shutdown the application."""
    logger = get_logger(__name__)
    logger.info("Lyra shutting down")

    await close_database()

    logger.info("Lyra shutdown complete")


def main() -> None:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Lyra - Local Yielding Research Aide")
    parser.add_argument(
        "command",
        choices=["init", "mcp"],
        help="Command to run",
    )

    args = parser.parse_args()

    async def async_main() -> None:
        await initialize()

        try:
            if args.command == "init":
                print("Lyra initialized successfully.")

            elif args.command == "mcp":
                from src.mcp.server import run_server

                await run_server()

        finally:
            await shutdown()

    asyncio.run(async_main())


if __name__ == "__main__":
    main()
