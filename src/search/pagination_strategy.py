"""
Pagination Strategy for SERP Enhancement.

Implements hybrid approach for determining when to stop fetching additional pages:
- Saturation detection (novelty rate)
- Harvest rate based stopping
- Fixed maximum pages limit
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class PaginationConfig:
    """Configuration for pagination strategy."""

    serp_max_pages: int = 10  # Absolute maximum pages to fetch
    min_novelty_rate: float = 0.1  # Minimum novelty rate to continue (from state.py threshold)
    min_harvest_rate: float = 0.05  # Minimum harvest rate to continue
    strategy: Literal["fixed", "auto", "exhaustive"] = "auto"


@dataclass
class PaginationContext:
    """Context for pagination decision making."""

    current_page: int
    novelty_rate: float | None = None  # New URL rate (new_urls / total_urls)
    harvest_rate: float | None = None  # Useful fragments rate
    total_urls_seen: int = 0
    new_urls_in_page: int = 0


class PaginationStrategy:
    """
    Determines when to stop fetching additional SERP pages.

    Uses hybrid approach:
    1. Fixed maximum (serp_max_pages)
    2. Saturation detection (novelty_rate < min_novelty_rate)
    3. Harvest rate (harvest_rate < min_harvest_rate)
    """

    def __init__(self, config: PaginationConfig | None = None):
        """
        Initialize pagination strategy.

        Args:
            config: Pagination configuration. Uses defaults if None.
        """
        self.config = config or PaginationConfig()

    def should_fetch_next(self, context: PaginationContext) -> bool:
        """
        Determine if next page should be fetched.

        Args:
            context: Current pagination context.

        Returns:
            True if next page should be fetched, False otherwise.
        """
        # Fixed maximum check
        if context.current_page >= self.config.serp_max_pages:
            return False

        # Strategy-specific checks
        if self.config.strategy == "fixed":
            # Fixed strategy: always fetch up to max_pages
            return True

        if self.config.strategy == "exhaustive":
            # Exhaustive strategy: fetch all pages up to max_pages
            return True

        # Auto strategy: use saturation and harvest rate
        if self.config.strategy == "auto":
            # Saturation check
            if context.novelty_rate is not None:
                if context.novelty_rate < self.config.min_novelty_rate:
                    return False

            # Harvest rate check
            if context.harvest_rate is not None:
                if context.harvest_rate < self.config.min_harvest_rate:
                    return False

        return True

    def calculate_novelty_rate(self, new_urls: list[str], seen_urls: set[str]) -> float:
        """
        Calculate novelty rate (new URL rate).

        Args:
            new_urls: URLs found in current page.
            seen_urls: URLs already seen in previous pages.

        Returns:
            Novelty rate (0.0-1.0). Returns 1.0 if no URLs seen before.
        """
        if not new_urls:
            return 0.0

        if not seen_urls:
            return 1.0

        new_count = sum(1 for url in new_urls if url not in seen_urls)
        return new_count / len(new_urls)
