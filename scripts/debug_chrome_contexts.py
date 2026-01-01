"""Debug script: inspect Chrome CDP contexts for a given worker.

This helps verify whether Lyra is reusing the default Chrome context (cookie-preserving)
or creating a new incognito-like context.
"""

import argparse
import asyncio


async def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Playwright CDP contexts for a worker.")
    parser.add_argument("--host", default="localhost", help="Chrome CDP host (default: localhost)")
    parser.add_argument(
        "--base-port",
        type=int,
        default=9222,
        help="Chrome base CDP port (worker 0) (default: 9222)",
    )
    parser.add_argument(
        "--worker-id",
        type=int,
        default=1,
        help="Worker id (0-indexed). Port = base-port + worker-id (default: 1)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=5.0,
        help="CDP connect timeout seconds (default: 5.0)",
    )
    args = parser.parse_args()

    port = args.base_port + args.worker_id
    cdp_url = f"http://{args.host}:{port}"

    from playwright.async_api import async_playwright

    print(f"cdp_url={cdp_url}")

    playwright = await async_playwright().start()
    try:
        browser = await asyncio.wait_for(
            playwright.chromium.connect_over_cdp(cdp_url),
            timeout=args.timeout_seconds,
        )
        contexts = browser.contexts

        print(f"contexts_count={len(contexts)}")
        for i, ctx in enumerate(contexts):
            try:
                cookies = await ctx.cookies()
                print(f"context[{i}].cookies_count={len(cookies)}")
            except Exception as e:  # pragma: no cover (debug script)
                print(f"context[{i}].cookies_error={type(e).__name__}:{e}")
    finally:
        await playwright.stop()

    return 0


if __name__ == "__main__":  # pragma: no cover (debug script)
    raise SystemExit(asyncio.run(main()))


