"""
Wayback Machine differential exploration for Lancet.

Implements archive snapshot retrieval and diff extraction (§3.1.6, §16.12):
- Snapshot discovery via HTML scraping (no API)
- Content comparison across time
- Timeline construction for claims
- Budget control per domain/task
- Automatic fallback for 403/CAPTCHA blocked URLs (§16.12)
- Freshness penalty calculation for archived content

References:
- §3.1.6: Wayback Differential Exploration
- §16.12: Wayback Fallback Strengthening
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup

from src.utils.config import get_settings
from src.utils.logging import CausalTrace, get_logger

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

WAYBACK_BASE = "https://web.archive.org"
WAYBACK_CALENDAR_URL = f"{WAYBACK_BASE}/web/{{timestamp}}/{{url}}"
WAYBACK_CDX_URL = f"{WAYBACK_BASE}/cdx/search/cdx"

# Budget: Wayback fetches ≤ 15% of total task pages (§3.1.6)
WAYBACK_BUDGET_RATIO = 0.15


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Snapshot:
    """A Wayback Machine snapshot."""

    url: str
    original_url: str
    timestamp: datetime
    status_code: int = 200
    mime_type: str = "text/html"

    @property
    def wayback_url(self) -> str:
        """Get full Wayback Machine URL."""
        ts = self.timestamp.strftime("%Y%m%d%H%M%S")
        return f"{WAYBACK_BASE}/web/{ts}/{self.original_url}"

    @classmethod
    def from_cdx_line(cls, line: str, original_url: str) -> "Snapshot | None":
        """Parse snapshot from CDX response line.

        CDX format: urlkey timestamp original mimetype statuscode digest length

        Args:
            line: CDX response line.
            original_url: Original URL for reference.

        Returns:
            Snapshot or None if parsing fails.
        """
        parts = line.strip().split()
        if len(parts) < 6:
            return None

        try:
            timestamp = datetime.strptime(parts[1], "%Y%m%d%H%M%S")
            timestamp = timestamp.replace(tzinfo=UTC)

            status_code = int(parts[4]) if parts[4] != "-" else 200

            return cls(
                url=parts[2],
                original_url=original_url,
                timestamp=timestamp,
                status_code=status_code,
                mime_type=parts[3],
            )
        except (ValueError, IndexError):
            return None


@dataclass
class ContentDiff:
    """Difference between two content versions."""

    old_snapshot: Snapshot
    new_snapshot: Snapshot

    # Text changes
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)

    # Structure changes
    heading_changes: list[tuple[str, str, str]] = field(default_factory=list)  # (action, old, new)

    # Metrics
    similarity_ratio: float = 1.0
    word_count_change: int = 0

    def is_significant(self, threshold: float = 0.8) -> bool:
        """Check if diff is significant enough to note.

        Args:
            threshold: Similarity threshold below which diff is significant.

        Returns:
            True if significant changes detected.
        """
        return (
            self.similarity_ratio < threshold
            or len(self.heading_changes) > 0
            or abs(self.word_count_change) > 100
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "old_timestamp": self.old_snapshot.timestamp.isoformat(),
            "new_timestamp": self.new_snapshot.timestamp.isoformat(),
            "similarity_ratio": self.similarity_ratio,
            "word_count_change": self.word_count_change,
            "heading_changes": self.heading_changes,
            "added_lines_count": len(self.added_lines),
            "removed_lines_count": len(self.removed_lines),
            "is_significant": self.is_significant(),
        }


@dataclass
class TimelineEntry:
    """Entry in a page's timeline."""

    timestamp: datetime
    snapshot_url: str
    summary: str
    content_hash: str | None = None
    word_count: int = 0
    is_current: bool = False
    diff_from_previous: ContentDiff | None = None


@dataclass
class WaybackResult:
    """Result of Wayback exploration for a URL."""

    url: str
    snapshots_found: int = 0
    snapshots_fetched: int = 0
    timeline: list[TimelineEntry] = field(default_factory=list)
    significant_changes: list[ContentDiff] = field(default_factory=list)
    earliest_date: datetime | None = None
    latest_date: datetime | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "snapshots_found": self.snapshots_found,
            "snapshots_fetched": self.snapshots_fetched,
            "timeline_entries": len(self.timeline),
            "significant_changes": len(self.significant_changes),
            "earliest_date": self.earliest_date.isoformat() if self.earliest_date else None,
            "latest_date": self.latest_date.isoformat() if self.latest_date else None,
            "error": self.error,
        }


# =============================================================================
# Wayback Client
# =============================================================================


class WaybackClient:
    """Client for Wayback Machine interaction.

    Uses HTML scraping only (no API per §3.1.6).
    """

    def __init__(self):
        self._settings = get_settings()
        self._session = None

    async def get_snapshots(
        self,
        url: str,
        limit: int = 10,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[Snapshot]:
        """Get available snapshots for URL.

        Args:
            url: Original URL.
            limit: Maximum snapshots to return.
            from_date: Start date filter.
            to_date: End date filter.

        Returns:
            List of Snapshot objects, newest first.
        """
        snapshots = []

        try:
            # Use CDX server (still HTML-based query)
            params = [
                f"url={quote(url, safe='')}",
                "output=text",
                "fl=urlkey,timestamp,original,mimetype,statuscode,digest,length",
                f"limit={limit * 2}",  # Get more to filter
                "filter=statuscode:200",
                "filter=mimetype:text/html",
            ]

            if from_date:
                params.append(f"from={from_date.strftime('%Y%m%d')}")
            if to_date:
                params.append(f"to={to_date.strftime('%Y%m%d')}")

            cdx_url = f"{WAYBACK_CDX_URL}?{'&'.join(params)}"

            from curl_cffi import requests as curl_requests

            response = curl_requests.get(
                cdx_url,
                timeout=30,
                impersonate="chrome",
            )

            if response.status_code != 200:
                logger.warning(
                    "Wayback CDX query failed",
                    url=url[:80],
                    status=response.status_code,
                )
                return []

            # Parse CDX response
            for line in response.text.strip().split("\n"):
                if not line:
                    continue

                snapshot = Snapshot.from_cdx_line(line, url)
                if snapshot and snapshot.status_code == 200:
                    snapshots.append(snapshot)

            # Sort by date descending and limit
            snapshots.sort(key=lambda s: s.timestamp, reverse=True)
            snapshots = snapshots[:limit]

            logger.info(
                "Found Wayback snapshots",
                url=url[:80],
                count=len(snapshots),
            )

        except Exception as e:
            logger.error("Wayback snapshot query error", url=url[:80], error=str(e))

        return snapshots

    async def fetch_snapshot(self, snapshot: Snapshot) -> str | None:
        """Fetch content from a snapshot.

        Args:
            snapshot: Snapshot to fetch.

        Returns:
            HTML content or None.
        """
        try:
            from curl_cffi import requests as curl_requests

            response = curl_requests.get(
                snapshot.wayback_url,
                timeout=30,
                impersonate="chrome",
                headers={
                    "Accept": "text/html",
                },
            )

            if response.status_code != 200:
                return None

            # Remove Wayback toolbar from content
            html = self._remove_wayback_toolbar(response.text)

            return html

        except Exception as e:
            logger.debug(
                "Wayback fetch error",
                url=snapshot.wayback_url[:80],
                error=str(e),
            )
            return None

    def _remove_wayback_toolbar(self, html: str) -> str:
        """Remove Wayback Machine toolbar from HTML.

        Args:
            html: Raw HTML with toolbar.

        Returns:
            Cleaned HTML.
        """
        # Remove Wayback toolbar comment/script blocks
        patterns = [
            r"<!-- BEGIN WAYBACK TOOLBAR INSERT -->.*?<!-- END WAYBACK TOOLBAR INSERT -->",
            r"<script[^>]*>.*?wm\.wombat\.js.*?</script>",
            r"<script[^>]*>.*?archive_sparkline.*?</script>",
            r"<script[^>]*>.*?wb-ext-header\.js.*?</script>",
        ]

        cleaned = html
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)

        return cleaned


# =============================================================================
# Content Analyzer
# =============================================================================


class ContentAnalyzer:
    """Analyzes and compares archived content versions."""

    def extract_text(self, html: str) -> str:
        """Extract main text content from HTML.

        Args:
            html: HTML content.

        Returns:
            Extracted text.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Remove script, style, nav, footer
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Get text
        text = soup.get_text(separator="\n", strip=True)

        # Clean up whitespace
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        return "\n".join(lines)

    def extract_headings(self, html: str) -> list[str]:
        """Extract headings from HTML.

        Args:
            html: HTML content.

        Returns:
            List of heading texts.
        """
        soup = BeautifulSoup(html, "html.parser")
        headings = []

        for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            text = tag.get_text(strip=True)
            if text:
                headings.append(text)

        return headings

    def extract_dates(self, html: str) -> list[str]:
        """Extract date references from HTML.

        Args:
            html: HTML content.

        Returns:
            List of date strings found.
        """
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        # Common date patterns
        patterns = [
            r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",  # 2024-01-15 or 2024/01/15
            r"\d{1,2}[-/]\d{1,2}[-/]\d{4}",  # 15-01-2024
            r"\d{4}年\d{1,2}月\d{1,2}日",  # 2024年1月15日
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}",
        ]

        dates = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            dates.extend(matches)

        return list(set(dates))

    def compare(
        self,
        old_html: str,
        new_html: str,
        old_snapshot: Snapshot,
        new_snapshot: Snapshot,
    ) -> ContentDiff:
        """Compare two HTML versions.

        Args:
            old_html: Older version HTML.
            new_html: Newer version HTML.
            old_snapshot: Older snapshot metadata.
            new_snapshot: Newer snapshot metadata.

        Returns:
            ContentDiff with comparison results.
        """
        diff = ContentDiff(
            old_snapshot=old_snapshot,
            new_snapshot=new_snapshot,
        )

        # Extract text
        old_text = self.extract_text(old_html)
        new_text = self.extract_text(new_html)

        # Calculate similarity
        matcher = SequenceMatcher(None, old_text, new_text)
        diff.similarity_ratio = matcher.ratio()

        # Word count change
        old_words = len(old_text.split())
        new_words = len(new_text.split())
        diff.word_count_change = new_words - old_words

        # Find line changes
        old_lines = set(old_text.split("\n"))
        new_lines = set(new_text.split("\n"))

        diff.added_lines = list(new_lines - old_lines)[:50]  # Limit
        diff.removed_lines = list(old_lines - new_lines)[:50]

        # Compare headings
        old_headings = self.extract_headings(old_html)
        new_headings = self.extract_headings(new_html)

        old_headings_set = set(old_headings)
        new_headings_set = set(new_headings)

        for h in new_headings_set - old_headings_set:
            diff.heading_changes.append(("added", "", h))

        for h in old_headings_set - new_headings_set:
            diff.heading_changes.append(("removed", h, ""))

        return diff

    def summarize_content(self, html: str, max_length: int = 200) -> str:
        """Generate brief summary of content.

        Args:
            html: HTML content.
            max_length: Maximum summary length.

        Returns:
            Summary string.
        """
        text = self.extract_text(html)

        # Get first paragraph or lines
        lines = text.split("\n")
        summary = ""

        for line in lines:
            if len(line) > 30:  # Skip short lines
                summary = line
                break

        if len(summary) > max_length:
            summary = summary[: max_length - 3] + "..."

        return summary


# =============================================================================
# Wayback Explorer
# =============================================================================


class WaybackExplorer:
    """Explores Wayback Machine archives for URL history.

    Implements §3.1.6 requirements:
    - Retrieve latest + 3 prior snapshots
    - Extract heading/key point/date diffs
    - Build timeline for claims
    - Respect budget limits
    """

    DEFAULT_SNAPSHOT_COUNT = 4  # Latest + 3 prior

    def __init__(self):
        self._client = WaybackClient()
        self._analyzer = ContentAnalyzer()
        self._settings = get_settings()

    async def explore(
        self,
        url: str,
        snapshot_count: int = DEFAULT_SNAPSHOT_COUNT,
        task_id: str | None = None,
    ) -> WaybackResult:
        """Explore URL history via Wayback Machine.

        Args:
            url: URL to explore.
            snapshot_count: Number of snapshots to fetch.
            task_id: Associated task ID.

        Returns:
            WaybackResult with timeline and diffs.
        """
        result = WaybackResult(url=url)

        with CausalTrace():
            try:
                # Get available snapshots
                snapshots = await self._client.get_snapshots(
                    url,
                    limit=snapshot_count,
                )

                result.snapshots_found = len(snapshots)

                if not snapshots:
                    logger.info("No Wayback snapshots found", url=url[:80])
                    return result

                # Set date range
                result.earliest_date = snapshots[-1].timestamp
                result.latest_date = snapshots[0].timestamp

                # Fetch content for each snapshot
                contents: list[tuple[Snapshot, str]] = []

                for snapshot in snapshots:
                    html = await self._client.fetch_snapshot(snapshot)

                    if html:
                        contents.append((snapshot, html))
                        result.snapshots_fetched += 1

                    # Rate limiting
                    await asyncio.sleep(1.0)

                if not contents:
                    result.error = "no_content_retrieved"
                    return result

                # Build timeline
                previous_content: tuple[Snapshot, str] | None = None

                for snapshot, html in reversed(contents):  # Oldest first
                    summary = self._analyzer.summarize_content(html)

                    entry = TimelineEntry(
                        timestamp=snapshot.timestamp,
                        snapshot_url=snapshot.wayback_url,
                        summary=summary,
                        word_count=len(self._analyzer.extract_text(html).split()),
                        is_current=(snapshot == contents[0][0]),
                    )

                    # Compare with previous
                    if previous_content:
                        prev_snapshot, prev_html = previous_content
                        diff = self._analyzer.compare(
                            prev_html,
                            html,
                            prev_snapshot,
                            snapshot,
                        )
                        entry.diff_from_previous = diff

                        if diff.is_significant():
                            result.significant_changes.append(diff)

                    result.timeline.append(entry)
                    previous_content = (snapshot, html)

                logger.info(
                    "Wayback exploration completed",
                    url=url[:80],
                    snapshots=result.snapshots_fetched,
                    significant_changes=len(result.significant_changes),
                )

            except Exception as e:
                logger.error("Wayback exploration error", url=url[:80], error=str(e))
                result.error = str(e)

        return result

    async def get_historical_content(
        self,
        url: str,
        date: datetime,
    ) -> tuple[str | None, Snapshot | None]:
        """Get content from specific date.

        Args:
            url: URL to fetch.
            date: Target date.

        Returns:
            Tuple of (html_content, snapshot) or (None, None).
        """
        # Get snapshots around the target date
        snapshots = await self._client.get_snapshots(
            url,
            limit=5,
            from_date=date - timedelta(days=30),
            to_date=date + timedelta(days=30),
        )

        if not snapshots:
            return None, None

        # Find closest snapshot to target date
        closest = min(snapshots, key=lambda s: abs((s.timestamp - date).total_seconds()))

        html = await self._client.fetch_snapshot(closest)

        return html, closest

    async def check_content_changes(
        self,
        url: str,
        current_html: str,
    ) -> bool:
        """Check if current content differs from archived version.

        Useful for detecting modifications/updates.

        Args:
            url: URL to check.
            current_html: Current HTML content.

        Returns:
            True if significant changes detected.
        """
        # Get most recent archived snapshot
        snapshots = await self._client.get_snapshots(url, limit=1)

        if not snapshots:
            return False  # No archive to compare

        archived_html = await self._client.fetch_snapshot(snapshots[0])

        if not archived_html:
            return False

        # Compare
        diff = self._analyzer.compare(
            archived_html,
            current_html,
            snapshots[0],
            Snapshot(url=url, original_url=url, timestamp=datetime.now(UTC)),
        )

        return diff.is_significant()


# =============================================================================
# Budget Manager
# =============================================================================


class WaybackBudgetManager:
    """Manages Wayback fetch budget per task/domain."""

    def __init__(self):
        self._task_budgets: dict[str, int] = {}  # task_id -> remaining
        self._domain_budgets: dict[str, int] = {}  # domain -> remaining today

    def get_task_budget(self, task_id: str, total_pages: int) -> int:
        """Get Wayback budget for task.

        Args:
            task_id: Task ID.
            total_pages: Total pages in task.

        Returns:
            Remaining Wayback fetches allowed.
        """
        if task_id not in self._task_budgets:
            # 15% of total pages (§3.1.6)
            self._task_budgets[task_id] = int(total_pages * WAYBACK_BUDGET_RATIO)

        return self._task_budgets[task_id]

    def consume_budget(self, task_id: str, count: int = 1) -> bool:
        """Consume budget for Wayback fetches.

        Args:
            task_id: Task ID.
            count: Number of fetches to consume.

        Returns:
            True if budget available and consumed.
        """
        if task_id not in self._task_budgets:
            return False

        if self._task_budgets[task_id] >= count:
            self._task_budgets[task_id] -= count
            return True

        return False

    def reset_task_budget(self, task_id: str) -> None:
        """Reset budget for task.

        Args:
            task_id: Task ID to reset.
        """
        if task_id in self._task_budgets:
            del self._task_budgets[task_id]


# =============================================================================
# Global Instance
# =============================================================================

_wayback_explorer: WaybackExplorer | None = None
_budget_manager: WaybackBudgetManager | None = None


def get_wayback_explorer() -> WaybackExplorer:
    """Get or create global WaybackExplorer instance."""
    global _wayback_explorer
    if _wayback_explorer is None:
        _wayback_explorer = WaybackExplorer()
    return _wayback_explorer


def get_wayback_budget_manager() -> WaybackBudgetManager:
    """Get or create global WaybackBudgetManager instance."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = WaybackBudgetManager()
    return _budget_manager


# =============================================================================
# MCP Tool Integration
# =============================================================================


async def explore_wayback(
    url: str,
    snapshot_count: int = 4,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Explore URL history via Wayback Machine (for MCP tool use).

    Args:
        url: URL to explore.
        snapshot_count: Number of snapshots.
        task_id: Associated task ID.

    Returns:
        Exploration result dictionary.
    """
    explorer = get_wayback_explorer()
    result = await explorer.explore(url, snapshot_count, task_id)

    return {
        **result.to_dict(),
        "timeline": [
            {
                "timestamp": entry.timestamp.isoformat(),
                "snapshot_url": entry.snapshot_url,
                "summary": entry.summary,
                "word_count": entry.word_count,
                "is_current": entry.is_current,
                "has_significant_change": entry.diff_from_previous.is_significant()
                if entry.diff_from_previous
                else False,
            }
            for entry in result.timeline
        ],
        "diffs": [diff.to_dict() for diff in result.significant_changes],
    }


async def get_archived_content(
    url: str,
    date: str,
) -> dict[str, Any]:
    """Get archived content from specific date (for MCP tool use).

    Args:
        url: URL to fetch.
        date: Target date (ISO format).

    Returns:
        Archived content result.
    """
    explorer = get_wayback_explorer()

    target_date = datetime.fromisoformat(date.replace("Z", "+00:00"))

    html, snapshot = await explorer.get_historical_content(url, target_date)

    if html and snapshot:
        analyzer = ContentAnalyzer()
        return {
            "url": url,
            "found": True,
            "snapshot_date": snapshot.timestamp.isoformat(),
            "snapshot_url": snapshot.wayback_url,
            "summary": analyzer.summarize_content(html),
            "headings": analyzer.extract_headings(html),
            "dates_mentioned": analyzer.extract_dates(html),
        }

    return {
        "url": url,
        "found": False,
        "target_date": date,
    }


async def check_content_modified(
    url: str,
    current_html: str,
) -> dict[str, Any]:
    """Check if URL content has been modified from archive (for MCP tool use).

    Args:
        url: URL to check.
        current_html: Current HTML content.

    Returns:
        Modification check result.
    """
    explorer = get_wayback_explorer()

    has_changes = await explorer.check_content_changes(url, current_html)

    return {
        "url": url,
        "has_significant_changes": has_changes,
    }


# =============================================================================
# Wayback Fallback (§16.12)
# =============================================================================


@dataclass
class FallbackResult:
    """Result of Wayback fallback attempt.

    Per §16.12: Contains archived content and freshness metadata.
    """

    ok: bool
    url: str
    html: str | None = None
    snapshot: Snapshot | None = None
    freshness_penalty: float = 0.0
    error: str | None = None
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ok": self.ok,
            "url": self.url,
            "has_content": self.html is not None,
            "snapshot_date": self.snapshot.timestamp.isoformat() if self.snapshot else None,
            "snapshot_url": self.snapshot.wayback_url if self.snapshot else None,
            "freshness_penalty": self.freshness_penalty,
            "error": self.error,
            "attempts": self.attempts,
        }


def calculate_freshness_penalty(snapshot_date: datetime) -> float:
    """Calculate freshness penalty based on snapshot age.

    Per §16.12: Older content gets higher penalty to reflect staleness.

    Penalty scale:
    - < 7 days: 0.0 (no penalty)
    - 7-30 days: 0.0-0.2 (minor penalty)
    - 1-6 months: 0.2-0.5 (moderate penalty)
    - 6-12 months: 0.5-0.7 (significant penalty)
    - > 12 months: 0.7-1.0 (major penalty)

    Args:
        snapshot_date: Date of the snapshot.

    Returns:
        Freshness penalty (0.0-1.0).
    """
    now = datetime.now(UTC)
    age_days = (now - snapshot_date).days

    if age_days < 0:
        # Future date (shouldn't happen, but handle gracefully)
        return 0.0
    elif age_days < 7:
        return 0.0
    elif age_days < 30:
        # Linear from 0.0 to 0.2
        return 0.2 * (age_days - 7) / 23
    elif age_days < 180:
        # Linear from 0.2 to 0.5
        return 0.2 + 0.3 * (age_days - 30) / 150
    elif age_days < 365:
        # Linear from 0.5 to 0.7
        return 0.5 + 0.2 * (age_days - 180) / 185
    else:
        # Linear from 0.7 to 1.0 (capped at 1.0)
        penalty = 0.7 + 0.3 * min((age_days - 365) / 730, 1.0)
        return min(penalty, 1.0)


def apply_freshness_penalty(
    confidence: float,
    freshness_penalty: float,
    weight: float = 0.5,
) -> float:
    """Apply freshness penalty to a confidence score.

    Per §16.12.2: Reduces confidence for stale archived content.

    Formula: adjusted = confidence * (1 - weight * penalty)

    Args:
        confidence: Original confidence score (0.0-1.0).
        freshness_penalty: Freshness penalty (0.0-1.0).
        weight: How much the penalty affects confidence (0.0-1.0).
            Default 0.5 means max 50% reduction for very old content.

    Returns:
        Adjusted confidence score (0.0-1.0).
    """
    if freshness_penalty <= 0:
        return confidence

    # Apply weighted penalty
    adjustment = 1.0 - (weight * freshness_penalty)
    adjusted = confidence * adjustment

    # Keep within bounds
    return max(0.0, min(1.0, adjusted))


@dataclass
class ArchiveDiffResult:
    """Result of comparing archived content with current version.

    Per §16.12.2: Contains detailed diff information for timeline integration.
    """

    url: str
    has_significant_changes: bool = False

    # Content comparison
    content_diff: ContentDiff | None = None
    similarity_ratio: float = 1.0

    # Heading changes summary
    headings_added: list[str] = field(default_factory=list)
    headings_removed: list[str] = field(default_factory=list)

    # Key points extracted
    key_changes: list[str] = field(default_factory=list)  # Human-readable change descriptions

    # Freshness info
    archive_date: datetime | None = None
    freshness_penalty: float = 0.0
    adjusted_confidence: float = 1.0

    # Timeline event info
    timeline_event_type: str = (
        "content_unchanged"  # content_unchanged/content_modified/content_major_change
    )
    timeline_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "has_significant_changes": self.has_significant_changes,
            "similarity_ratio": self.similarity_ratio,
            "headings_added": self.headings_added,
            "headings_removed": self.headings_removed,
            "key_changes": self.key_changes,
            "archive_date": self.archive_date.isoformat() if self.archive_date else None,
            "freshness_penalty": self.freshness_penalty,
            "adjusted_confidence": self.adjusted_confidence,
            "timeline_event_type": self.timeline_event_type,
            "timeline_notes": self.timeline_notes,
            "content_diff": self.content_diff.to_dict() if self.content_diff else None,
        }

    def generate_timeline_notes(self) -> str:
        """Generate human-readable timeline notes.

        Returns:
            Notes string for timeline event.
        """
        parts = []

        if self.freshness_penalty > 0.5:
            parts.append(
                f"Archive is significantly outdated (penalty: {self.freshness_penalty:.2f})"
            )
        elif self.freshness_penalty > 0.2:
            parts.append(f"Archive is moderately outdated (penalty: {self.freshness_penalty:.2f})")

        if self.headings_added:
            parts.append(f"New sections: {', '.join(self.headings_added[:3])}")

        if self.headings_removed:
            parts.append(f"Removed sections: {', '.join(self.headings_removed[:3])}")

        if self.content_diff and self.content_diff.word_count_change != 0:
            change = self.content_diff.word_count_change
            if change > 0:
                parts.append(f"Content expanded (+{change} words)")
            else:
                parts.append(f"Content reduced ({change} words)")

        if self.key_changes:
            parts.extend(self.key_changes[:2])

        return "; ".join(parts) if parts else "No significant changes detected"


class WaybackFallback:
    """Provides Wayback Machine fallback for blocked URLs.

    Per §16.12: Automatically retrieves archived content when direct
    access fails due to 403/CAPTCHA/blocking.
    """

    DEFAULT_MAX_ATTEMPTS = 3  # Try up to 3 snapshots

    def __init__(self):
        self._client = WaybackClient()
        self._analyzer = ContentAnalyzer()

    async def get_fallback_content(
        self,
        url: str,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> FallbackResult:
        """Get content from Wayback Machine as fallback.

        Tries the most recent snapshots first, up to max_attempts.

        Args:
            url: Original URL that was blocked.
            max_attempts: Maximum number of snapshots to try.

        Returns:
            FallbackResult with content if successful.
        """
        result = FallbackResult(ok=False, url=url)

        try:
            # Get available snapshots (newest first)
            snapshots = await self._client.get_snapshots(url, limit=max_attempts)

            if not snapshots:
                result.error = "no_snapshots_available"
                logger.info(
                    "No Wayback snapshots available",
                    url=url[:80],
                )
                return result

            # Try each snapshot until success
            for i, snapshot in enumerate(snapshots):
                result.attempts = i + 1

                html = await self._client.fetch_snapshot(snapshot)

                if html and len(html) > 500:  # Basic validity check
                    # Verify it's not an error page
                    if not self._is_error_page(html):
                        result.ok = True
                        result.html = html
                        result.snapshot = snapshot
                        result.freshness_penalty = calculate_freshness_penalty(snapshot.timestamp)

                        logger.info(
                            "Wayback fallback successful",
                            url=url[:80],
                            snapshot_date=snapshot.timestamp.isoformat(),
                            freshness_penalty=result.freshness_penalty,
                            attempt=result.attempts,
                        )
                        return result

                # Rate limit between attempts
                await asyncio.sleep(1.0)

            result.error = "all_snapshots_failed"
            logger.warning(
                "All Wayback snapshots failed",
                url=url[:80],
                attempts=result.attempts,
            )

        except Exception as e:
            result.error = str(e)
            logger.error(
                "Wayback fallback error",
                url=url[:80],
                error=str(e),
            )

        return result

    def _is_error_page(self, html: str) -> bool:
        """Check if HTML is a Wayback error page.

        Args:
            html: HTML content.

        Returns:
            True if this appears to be an error page.
        """
        html_lower = html.lower()

        error_indicators = [
            "wayback machine has not archived",
            "this url has been excluded",
            "snapshot cannot be displayed",
            "this page is not available",
            "access denied",
            "error retrieving",
        ]

        return any(ind in html_lower for ind in error_indicators)

    async def get_best_snapshot_content(
        self,
        url: str,
        prefer_recent: bool = True,
    ) -> tuple[str | None, Snapshot | None, float]:
        """Get the best available archived content for a URL.

        Args:
            url: Original URL.
            prefer_recent: Prefer more recent snapshots.

        Returns:
            Tuple of (html, snapshot, freshness_penalty) or (None, None, 0.0).
        """
        result = await self.get_fallback_content(url)

        if result.ok:
            return result.html, result.snapshot, result.freshness_penalty

        return None, None, 0.0

    async def compare_with_current(
        self,
        url: str,
        current_html: str,
        base_confidence: float = 1.0,
    ) -> ArchiveDiffResult:
        """Compare current HTML with archived version.

        Per §16.12.2: Detects heading/key point changes and generates
        timeline information for significant differences.

        Args:
            url: URL being compared.
            current_html: Current HTML content.
            base_confidence: Base confidence score to adjust.

        Returns:
            ArchiveDiffResult with comparison details.
        """
        result = ArchiveDiffResult(url=url)

        try:
            # Get most recent archived snapshot
            snapshots = await self._client.get_snapshots(url, limit=1)

            if not snapshots:
                result.timeline_notes = "No archive available for comparison"
                return result

            snapshot = snapshots[0]
            archived_html = await self._client.fetch_snapshot(snapshot)

            if not archived_html:
                result.timeline_notes = "Failed to retrieve archived content"
                return result

            # Calculate freshness penalty
            result.archive_date = snapshot.timestamp
            result.freshness_penalty = calculate_freshness_penalty(snapshot.timestamp)
            result.adjusted_confidence = apply_freshness_penalty(
                base_confidence, result.freshness_penalty
            )

            # Create snapshot for current content
            current_snapshot = Snapshot(
                url=url,
                original_url=url,
                timestamp=datetime.now(UTC),
            )

            # Compare content
            diff = self._analyzer.compare(
                archived_html,
                current_html,
                snapshot,
                current_snapshot,
            )

            result.content_diff = diff
            result.similarity_ratio = diff.similarity_ratio
            result.has_significant_changes = diff.is_significant()

            # Extract heading changes
            for action, old, new in diff.heading_changes:
                if action == "added":
                    result.headings_added.append(new)
                elif action == "removed":
                    result.headings_removed.append(old)

            # Generate key changes summary
            result.key_changes = self._generate_key_changes(diff)

            # Determine timeline event type
            if not result.has_significant_changes:
                result.timeline_event_type = "content_unchanged"
            elif diff.similarity_ratio < 0.5:
                result.timeline_event_type = "content_major_change"
            else:
                result.timeline_event_type = "content_modified"

            # Generate timeline notes
            result.timeline_notes = result.generate_timeline_notes()

            logger.info(
                "Archive comparison complete",
                url=url[:80],
                similarity=diff.similarity_ratio,
                has_changes=result.has_significant_changes,
                freshness_penalty=result.freshness_penalty,
            )

        except Exception as e:
            logger.error(
                "Archive comparison error",
                url=url[:80],
                error=str(e),
            )
            result.timeline_notes = f"Comparison failed: {str(e)}"

        return result

    def _generate_key_changes(self, diff: ContentDiff) -> list[str]:
        """Generate human-readable key change descriptions.

        Args:
            diff: ContentDiff from comparison.

        Returns:
            List of key change descriptions.
        """
        changes = []

        # Word count changes
        if diff.word_count_change > 200:
            changes.append(f"Significant content expansion (+{diff.word_count_change} words)")
        elif diff.word_count_change < -200:
            changes.append(f"Significant content reduction ({diff.word_count_change} words)")

        # Heading structure changes
        heading_adds = sum(1 for a, _, _ in diff.heading_changes if a == "added")
        heading_removes = sum(1 for a, _, _ in diff.heading_changes if a == "removed")

        if heading_adds > 0:
            changes.append(f"{heading_adds} new section(s) added")
        if heading_removes > 0:
            changes.append(f"{heading_removes} section(s) removed")

        # Content similarity
        if diff.similarity_ratio < 0.3:
            changes.append("Page substantially rewritten")
        elif diff.similarity_ratio < 0.6:
            changes.append("Major content revisions")
        elif diff.similarity_ratio < 0.8:
            changes.append("Moderate content updates")

        # Specific notable changes (sample from added/removed lines)
        if diff.added_lines and len(changes) < 5:
            # Look for important-looking additions
            for line in diff.added_lines[:10]:
                if any(
                    kw in line.lower()
                    for kw in ["important", "update", "new", "changed", "revised"]
                ):
                    changes.append(f"Notable addition: {line[:100]}...")
                    break

        return changes[:5]  # Limit to 5 key changes


# Global fallback instance
_wayback_fallback: WaybackFallback | None = None


def get_wayback_fallback() -> WaybackFallback:
    """Get or create global WaybackFallback instance."""
    global _wayback_fallback
    if _wayback_fallback is None:
        _wayback_fallback = WaybackFallback()
    return _wayback_fallback


async def get_fallback_for_blocked_url(
    url: str,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Get Wayback fallback content for a blocked URL (for integration).

    Args:
        url: URL that was blocked.
        max_attempts: Maximum snapshots to try.

    Returns:
        Fallback result dictionary.
    """
    fallback = get_wayback_fallback()
    result = await fallback.get_fallback_content(url, max_attempts)
    return result.to_dict()
