"""
Main entry point for Lancet.
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
        "Lancet initializing",
        version=settings.general.version,
        log_level=settings.general.log_level,
    )

    # Initialize database
    await get_database()

    logger.info("Lancet initialized successfully")


async def shutdown() -> None:
    """Shutdown the application."""
    logger = get_logger(__name__)
    logger.info("Lancet shutting down")

    await close_database()

    logger.info("Lancet shutdown complete")


async def run_research(query: str) -> None:
    """Run a research task.
    
    Args:
        query: Research query.
    """
    from src.crawler.fetcher import fetch_url
    from src.extractor.content import extract_content
    from src.filter.ranking import rank_candidates
    from src.report.generator import generate_report
    from src.search import search_serp
    from src.storage.database import get_database

    logger = get_logger(__name__)

    # Create task
    db = await get_database()
    task_id = await db.create_task(query)

    logger.info("Research task created", task_id=task_id, query=query)

    try:
        # Update status to running
        await db.update_task_status(task_id, "running")

        # Phase 1: Search
        logger.info("Phase 1: Searching...")
        results = await search_serp(query, task_id=task_id, limit=20)
        logger.info(f"Found {len(results)} search results")

        # Phase 2: Fetch top results
        logger.info("Phase 2: Fetching pages...")
        pages = []
        for result in results[:10]:
            url = result.get("url")
            if url:
                fetch_result = await fetch_url(
                    url,
                    context={"referer": "https://www.google.com/"},
                    task_id=task_id,
                )
                if fetch_result.get("ok"):
                    pages.append({
                        "url": url,
                        "html_path": fetch_result.get("html_path"),
                    })

        logger.info(f"Fetched {len(pages)} pages")

        # Phase 3: Extract content
        logger.info("Phase 3: Extracting content...")
        passages = []
        for page in pages:
            if page.get("html_path"):
                extract_result = await extract_content(
                    input_path=page["html_path"],
                )
                if extract_result.get("ok"):
                    for i, frag in enumerate(extract_result.get("fragments", [])):
                        passages.append({
                            "id": f"{page['url']}_{i}",
                            "text": frag.get("text", ""),
                            "source_url": page["url"],
                        })

        logger.info(f"Extracted {len(passages)} passages")

        # Phase 4: Rank passages
        if passages:
            logger.info("Phase 4: Ranking passages...")
            ranked = await rank_candidates(query, passages[:100], top_k=20)
            logger.info(f"Ranked {len(ranked)} passages")

        # Phase 5: Generate report
        logger.info("Phase 5: Generating report...")
        report_result = await generate_report(task_id)

        if report_result.get("ok"):
            logger.info("Report generated", filepath=report_result.get("filepath"))
        else:
            logger.error("Report generation failed", error=report_result.get("error"))

    except Exception as e:
        logger.error("Research task failed", task_id=task_id, error=str(e))
        await db.update_task_status(task_id, "failed", error_message=str(e))
        raise


def main() -> None:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Lancet - Local Autonomous Deep Research Agent"
    )
    parser.add_argument(
        "command",
        choices=["init", "research", "mcp"],
        help="Command to run",
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        help="Research query (for 'research' command)",
    )

    args = parser.parse_args()

    async def async_main():
        await initialize()

        try:
            if args.command == "init":
                print("Lancet initialized successfully.")

            elif args.command == "research":
                if not args.query:
                    print("Error: --query is required for research command")
                    return
                await run_research(args.query)

            elif args.command == "mcp":
                from src.mcp.server import run_server
                await run_server()

        finally:
            await shutdown()

    asyncio.run(async_main())


if __name__ == "__main__":
    main()

