"""
Wayback Machine differential exploration for Lancet.

Implements archive snapshot retrieval and diff extraction (§3.1.6):
- Snapshot discovery via HTML scraping (no API)
- Content comparison across time
- Timeline construction for claims
- Budget control per domain/task

References:
- §3.1.6: Wayback Differential Exploration
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urljoin, urlparse, quote

from bs4 import BeautifulSoup

from src.utils.config import get_settings
from src.utils.logging import get_logger, CausalTrace
from src.storage.database import get_database

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
            timestamp = timestamp.replace(tzinfo=timezone.utc)
            
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
            self.similarity_ratio < threshold or
            len(self.heading_changes) > 0 or
            abs(self.word_count_change) > 100
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
            r'<!-- BEGIN WAYBACK TOOLBAR INSERT -->.*?<!-- END WAYBACK TOOLBAR INSERT -->',
            r'<script[^>]*>.*?wm\.wombat\.js.*?</script>',
            r'<script[^>]*>.*?archive_sparkline.*?</script>',
            r'<script[^>]*>.*?wb-ext-header\.js.*?</script>',
        ]
        
        cleaned = html
        for pattern in patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL | re.IGNORECASE)
        
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
            r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',  # 2024-01-15 or 2024/01/15
            r'\d{1,2}[-/]\d{1,2}[-/]\d{4}',  # 15-01-2024
            r'\d{4}年\d{1,2}月\d{1,2}日',     # 2024年1月15日
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}',
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
            summary = summary[:max_length - 3] + "..."
        
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
        
        with CausalTrace() as trace:
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
                            prev_html, html,
                            prev_snapshot, snapshot,
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
            Snapshot(url=url, original_url=url, timestamp=datetime.now(timezone.utc)),
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
                "has_significant_change": entry.diff_from_previous.is_significant() if entry.diff_from_previous else False,
            }
            for entry in result.timeline
        ],
        "diffs": [
            diff.to_dict()
            for diff in result.significant_changes
        ],
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







