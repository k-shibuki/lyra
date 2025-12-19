"""
Tests for Wayback fallback functionality (§16.12).

Tests WaybackFallback, calculate_freshness_penalty, and integration with fetch_url.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-CFP-01 | Fresh snapshot (< 30 days) | Equivalence – fresh | Low penalty | - |
| TC-CFP-02 | Old snapshot (> 180 days) | Equivalence – old | High penalty | - |
| TC-CFP-03 | Snapshot 90 days old | Equivalence – medium | Medium penalty | - |
| TC-CFP-04 | Very old snapshot (5 years) | Boundary – ancient | Max penalty | - |
| TC-FR-01 | FallbackResult success | Equivalence – success | ok=True with content | - |
| TC-FR-02 | FallbackResult failure | Equivalence – failure | ok=False with error | - |
| TC-WF-01 | Fallback to archived | Equivalence – fallback | Returns archived content | - |
| TC-WF-02 | Fallback with freshest | Equivalence – freshest | Most recent snapshot | - |
| TC-WF-03 | Fallback no archive | Boundary – none | Returns failure | - |
| TC-WF-04 | Fallback with penalty | Equivalence – penalty | Confidence adjusted | - |
| TC-WF-05 | Fallback disabled | Equivalence – disabled | No fallback attempt | - |
| TC-CF-01 | get_wayback_fallback | Equivalence – singleton | Returns fallback | - |
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.crawler.wayback import (
    FallbackResult,
    Snapshot,
    WaybackFallback,
    calculate_freshness_penalty,
    get_wayback_fallback,
)

# Mark all tests as unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# calculate_freshness_penalty Tests
# =============================================================================


class TestCalculateFreshnessPenalty:
    """Tests for calculate_freshness_penalty function."""

    def test_fresh_content_no_penalty(self):
        """Test content less than 7 days old has no penalty."""
        now = datetime.now(UTC)

        # 0 days old
        snapshot_date = now
        assert calculate_freshness_penalty(snapshot_date) == 0.0

        # 3 days old
        snapshot_date = now - timedelta(days=3)
        assert calculate_freshness_penalty(snapshot_date) == 0.0

        # 6 days old
        snapshot_date = now - timedelta(days=6)
        assert calculate_freshness_penalty(snapshot_date) == 0.0

    def test_one_week_to_month_minor_penalty(self):
        """Test content 7-30 days old has minor penalty (0.0-0.2)."""
        now = datetime.now(UTC)

        # 7 days old - just starting penalty
        snapshot_date = now - timedelta(days=7)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.0 <= penalty <= 0.05

        # 15 days old - middle of range
        snapshot_date = now - timedelta(days=15)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.0 <= penalty <= 0.2

        # 29 days old - near end of range
        snapshot_date = now - timedelta(days=29)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.1 <= penalty <= 0.2

    def test_one_to_six_months_moderate_penalty(self):
        """Test content 1-6 months old has moderate penalty (0.2-0.5)."""
        now = datetime.now(UTC)

        # 30 days old
        snapshot_date = now - timedelta(days=30)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.15 <= penalty <= 0.25

        # 90 days old (~3 months)
        snapshot_date = now - timedelta(days=90)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.2 <= penalty <= 0.4

        # 179 days old (~6 months)
        snapshot_date = now - timedelta(days=179)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.4 <= penalty <= 0.5

    def test_six_to_twelve_months_significant_penalty(self):
        """Test content 6-12 months old has significant penalty (0.5-0.7)."""
        now = datetime.now(UTC)

        # 180 days old
        snapshot_date = now - timedelta(days=180)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.45 <= penalty <= 0.55

        # 270 days old (~9 months)
        snapshot_date = now - timedelta(days=270)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.55 <= penalty <= 0.65

        # 364 days old
        snapshot_date = now - timedelta(days=364)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.65 <= penalty <= 0.75

    def test_over_one_year_major_penalty(self):
        """Test content over 1 year old has major penalty (0.7-1.0)."""
        now = datetime.now(UTC)

        # 365 days old (1 year)
        snapshot_date = now - timedelta(days=365)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.65 <= penalty <= 0.75

        # 730 days old (2 years)
        snapshot_date = now - timedelta(days=730)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert 0.85 <= penalty <= 1.0

        # 1095 days old (3 years) - should be capped at 1.0
        snapshot_date = now - timedelta(days=1095)
        penalty = calculate_freshness_penalty(snapshot_date)
        assert penalty == 1.0

    def test_future_date_no_penalty(self):
        """Test future dates (shouldn't happen) have no penalty."""
        now = datetime.now(UTC)
        future_date = now + timedelta(days=10)

        penalty = calculate_freshness_penalty(future_date)
        assert penalty == 0.0


# =============================================================================
# FallbackResult Tests
# =============================================================================


class TestFallbackResult:
    """Tests for FallbackResult dataclass."""

    def test_to_dict_success(self):
        """Test to_dict for successful result."""
        snapshot = Snapshot(
            url="https://example.com/page",
            original_url="https://example.com/page",
            timestamp=datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        )

        result = FallbackResult(
            ok=True,
            url="https://example.com/page",
            html="<html>content</html>",
            snapshot=snapshot,
            freshness_penalty=0.3,
            attempts=1,
        )

        d = result.to_dict()

        assert d["ok"] is True
        assert d["url"] == "https://example.com/page"
        assert d["has_content"] is True
        assert d["snapshot_date"] == "2024-06-15T12:00:00+00:00"
        assert d["freshness_penalty"] == 0.3
        assert d["attempts"] == 1
        assert d["error"] is None

    def test_to_dict_failure(self):
        """Test to_dict for failed result."""
        result = FallbackResult(
            ok=False,
            url="https://example.com/blocked",
            error="no_snapshots_available",
            attempts=0,
        )

        d = result.to_dict()

        assert d["ok"] is False
        assert d["has_content"] is False
        assert d["snapshot_date"] is None
        assert d["error"] == "no_snapshots_available"


# =============================================================================
# WaybackFallback Tests
# =============================================================================


class TestWaybackFallback:
    """Tests for WaybackFallback class."""

    @pytest.fixture
    def wayback_fallback(self):
        """Create WaybackFallback instance."""
        return WaybackFallback()

    @pytest.mark.asyncio
    async def test_get_fallback_content_success(self, wayback_fallback):
        """Test successful fallback content retrieval."""
        snapshot = Snapshot(
            url="https://example.com/page",
            original_url="https://example.com/page",
            timestamp=datetime.now(UTC) - timedelta(days=10),
        )

        # Create content longer than 500 chars to pass validity check
        long_content = "<html><body>" + "Archived content. " * 50 + "</body></html>"

        with (
            patch.object(
                wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
            ) as mock_get,
            patch.object(
                wayback_fallback._client, "fetch_snapshot", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_get.return_value = [snapshot]
            mock_fetch.return_value = long_content

            result = await wayback_fallback.get_fallback_content("https://example.com/page")

            assert result.ok is True
            # Verify HTML content is present and contains expected text
            assert result.html is not None, "Expected HTML content but got None"
            assert len(result.html) > 500, f"Expected content > 500 chars, got {len(result.html)}"
            assert "Archived content" in result.html
            assert result.snapshot == snapshot
            assert result.freshness_penalty > 0  # 10 days old
            assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_get_fallback_content_no_snapshots(self, wayback_fallback):
        """Test fallback when no snapshots available."""
        with patch.object(
            wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = []

            result = await wayback_fallback.get_fallback_content("https://example.com/new-page")

            assert result.ok is False
            assert result.error == "no_snapshots_available"
            assert result.html is None

    @pytest.mark.asyncio
    async def test_get_fallback_content_all_fail(self, wayback_fallback):
        """Test fallback when all snapshot fetches fail."""
        snapshots = [
            Snapshot(
                url=f"https://example.com/page{i}",
                original_url="https://example.com/page",
                timestamp=datetime.now(UTC) - timedelta(days=i * 30),
            )
            for i in range(3)
        ]

        with (
            patch.object(
                wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
            ) as mock_get,
            patch.object(
                wayback_fallback._client, "fetch_snapshot", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_get.return_value = snapshots
            mock_fetch.return_value = None  # All fetches fail

            result = await wayback_fallback.get_fallback_content(
                "https://example.com/page",
                max_attempts=3,
            )

            assert result.ok is False
            assert result.error == "all_snapshots_failed"
            assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_get_fallback_content_second_attempt_success(self, wayback_fallback):
        """Test fallback succeeds on second attempt."""
        snapshots = [
            Snapshot(
                url="https://example.com/page1",
                original_url="https://example.com/page",
                timestamp=datetime.now(UTC) - timedelta(days=10),
            ),
            Snapshot(
                url="https://example.com/page2",
                original_url="https://example.com/page",
                timestamp=datetime.now(UTC) - timedelta(days=30),
            ),
        ]

        # Create content longer than 500 chars to pass validity check
        long_content = "<html><body>" + "Second attempt content. " * 40 + "</body></html>"

        with (
            patch.object(
                wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
            ) as mock_get,
            patch.object(
                wayback_fallback._client, "fetch_snapshot", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_get.return_value = snapshots
            # First fetch fails, second succeeds
            mock_fetch.side_effect = [
                None,
                long_content,
            ]

            result = await wayback_fallback.get_fallback_content("https://example.com/page")

            assert result.ok is True
            assert result.attempts == 2
            assert result.snapshot == snapshots[1]

    @pytest.mark.asyncio
    async def test_get_fallback_content_error_page_detection(self, wayback_fallback):
        """Test detection of Wayback error pages."""
        snapshot = Snapshot(
            url="https://example.com/page",
            original_url="https://example.com/page",
            timestamp=datetime.now(UTC) - timedelta(days=10),
        )

        with (
            patch.object(
                wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
            ) as mock_get,
            patch.object(
                wayback_fallback._client, "fetch_snapshot", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_get.return_value = [snapshot]
            # Return a Wayback error page
            mock_fetch.return_value = """
                <html>
                <body>
                Wayback Machine has not archived that URL.
                </body>
                </html>
            """

            result = await wayback_fallback.get_fallback_content("https://example.com/page")

            # Should fail because it's an error page
            assert result.ok is False

    @pytest.mark.asyncio
    async def test_get_fallback_content_short_content_rejected(self, wayback_fallback):
        """Test very short content is rejected."""
        snapshot = Snapshot(
            url="https://example.com/page",
            original_url="https://example.com/page",
            timestamp=datetime.now(UTC) - timedelta(days=10),
        )

        with (
            patch.object(
                wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
            ) as mock_get,
            patch.object(
                wayback_fallback._client, "fetch_snapshot", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_get.return_value = [snapshot]
            # Return very short content (less than 500 chars)
            mock_fetch.return_value = "<html>short</html>"

            result = await wayback_fallback.get_fallback_content("https://example.com/page")

            # Should fail because content is too short
            assert result.ok is False

    def test_is_error_page_detection(self, wayback_fallback):
        """Test error page detection patterns."""
        # Should detect as error page
        assert wayback_fallback._is_error_page("The Wayback Machine has not archived that URL")
        assert wayback_fallback._is_error_page(
            "This URL has been excluded from the Wayback Machine"
        )
        assert wayback_fallback._is_error_page("Snapshot cannot be displayed")
        assert wayback_fallback._is_error_page("Access denied to this resource")

        # Should NOT detect as error page
        assert not wayback_fallback._is_error_page("<html><body>Normal content here</body></html>")
        assert not wayback_fallback._is_error_page("This is a regular article about web archives")

    @pytest.mark.asyncio
    async def test_get_best_snapshot_content_success(self, wayback_fallback):
        """Test get_best_snapshot_content returns content."""
        snapshot = Snapshot(
            url="https://example.com/page",
            original_url="https://example.com/page",
            timestamp=datetime.now(UTC) - timedelta(days=5),
        )

        # Create content longer than 500 chars to pass validity check
        long_content = "<html><body>" + "Content from archive. " * 40 + "</body></html>"

        with (
            patch.object(
                wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
            ) as mock_get,
            patch.object(
                wayback_fallback._client, "fetch_snapshot", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_get.return_value = [snapshot]
            mock_fetch.return_value = long_content

            html, snap, penalty = await wayback_fallback.get_best_snapshot_content(
                "https://example.com/page"
            )

            # Verify content is returned and matches expected
            assert html is not None, "Expected HTML content but got None"
            assert len(html) > 500, f"Expected content > 500 chars, got {len(html)}"
            assert "Content from archive" in html
            assert snap == snapshot
            assert penalty == 0.0  # 5 days old, no penalty

    @pytest.mark.asyncio
    async def test_get_best_snapshot_content_failure(self, wayback_fallback):
        """Test get_best_snapshot_content when no content available."""
        with patch.object(
            wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = []

            html, snap, penalty = await wayback_fallback.get_best_snapshot_content(
                "https://example.com/missing"
            )

            assert html is None
            assert snap is None
            assert penalty == 0.0


# =============================================================================
# Global Instance Tests
# =============================================================================


class TestGlobalWaybackFallback:
    """Tests for global WaybackFallback instance."""

    def test_get_wayback_fallback_singleton(self):
        """Test get_wayback_fallback returns same instance."""
        fb1 = get_wayback_fallback()
        fb2 = get_wayback_fallback()

        assert fb1 is fb2
        assert isinstance(fb1, WaybackFallback)


# =============================================================================
# Integration Tests (with FetchResult)
# =============================================================================


class TestFetchResultArchiveFields:
    """Tests for FetchResult archive-related fields."""

    def test_fetch_result_default_not_archived(self):
        """Test FetchResult defaults to not archived."""
        from src.crawler.fetcher import FetchResult

        result = FetchResult(ok=True, url="https://example.com")

        assert result.is_archived is False
        assert result.archive_date is None
        assert result.archive_url is None
        assert result.freshness_penalty == 0.0

    def test_fetch_result_archived_fields(self):
        """Test FetchResult with archive fields set."""
        from src.crawler.fetcher import FetchResult

        archive_date = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)

        result = FetchResult(
            ok=True,
            url="https://example.com/page",
            method="wayback_fallback",
            is_archived=True,
            archive_date=archive_date,
            archive_url="https://web.archive.org/web/20240615/https://example.com/page",
            freshness_penalty=0.25,
        )

        assert result.is_archived is True
        assert result.archive_date == archive_date
        assert "web.archive.org" in result.archive_url
        assert result.freshness_penalty == 0.25

    def test_fetch_result_to_dict_includes_archive(self):
        """Test to_dict includes archive fields when archived."""
        from src.crawler.fetcher import FetchResult

        archive_date = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)

        result = FetchResult(
            ok=True,
            url="https://example.com/page",
            is_archived=True,
            archive_date=archive_date,
            archive_url="https://web.archive.org/...",
            freshness_penalty=0.3,
        )

        d = result.to_dict()

        assert d["is_archived"] is True
        assert d["archive_date"] == "2024-06-15T12:00:00+00:00"
        assert d["archive_url"] == "https://web.archive.org/..."
        assert d["freshness_penalty"] == 0.3

    def test_fetch_result_to_dict_excludes_archive_when_not_archived(self):
        """Test to_dict excludes archive fields when not archived."""
        from src.crawler.fetcher import FetchResult

        result = FetchResult(
            ok=True,
            url="https://example.com/page",
            is_archived=False,
        )

        d = result.to_dict()

        assert "is_archived" not in d
        assert "archive_date" not in d
        assert "archive_url" not in d
        assert "freshness_penalty" not in d


# =============================================================================
# 16.12.2 Tests: Diff Detection Enhancement
# =============================================================================


class TestApplyFreshnessPenalty:
    """Tests for apply_freshness_penalty function."""

    def test_no_penalty_no_change(self):
        """Test zero penalty doesn't change confidence."""
        from src.crawler.wayback import apply_freshness_penalty

        result = apply_freshness_penalty(0.9, 0.0)
        assert result == 0.9

    def test_max_penalty_halves_confidence(self):
        """Test max penalty with default weight reduces by 50%."""
        from src.crawler.wayback import apply_freshness_penalty

        # 1.0 penalty with 0.5 weight = 50% reduction
        result = apply_freshness_penalty(1.0, 1.0, weight=0.5)
        assert result == 0.5

    def test_moderate_penalty(self):
        """Test moderate penalty application."""
        from src.crawler.wayback import apply_freshness_penalty

        # 0.5 penalty with 0.5 weight = 25% reduction
        result = apply_freshness_penalty(0.8, 0.5, weight=0.5)
        assert 0.55 < result < 0.65

    def test_custom_weight(self):
        """Test custom weight parameter."""
        from src.crawler.wayback import apply_freshness_penalty

        # 1.0 penalty with 0.3 weight = 30% reduction
        result = apply_freshness_penalty(1.0, 1.0, weight=0.3)
        assert result == 0.7

    def test_bounds(self):
        """Test result stays within [0.0, 1.0]."""
        from src.crawler.wayback import apply_freshness_penalty

        # Should not go below 0
        result = apply_freshness_penalty(0.1, 1.0, weight=1.0)
        assert result == 0.0

        # Should not exceed 1
        result = apply_freshness_penalty(1.0, 0.0)
        assert result == 1.0


class TestArchiveDiffResult:
    """Tests for ArchiveDiffResult dataclass."""

    def test_default_values(self):
        """Test default values."""
        from src.crawler.wayback import ArchiveDiffResult

        result = ArchiveDiffResult(url="https://example.com")

        assert result.has_significant_changes is False
        assert result.similarity_ratio == 1.0
        assert result.headings_added == []
        assert result.headings_removed == []
        assert result.timeline_event_type == "content_unchanged"

    def test_to_dict(self):
        """Test to_dict conversion."""
        from src.crawler.wayback import ArchiveDiffResult

        result = ArchiveDiffResult(
            url="https://example.com",
            has_significant_changes=True,
            similarity_ratio=0.7,
            headings_added=["New Section"],
            headings_removed=["Old Section"],
            timeline_event_type="content_modified",
            freshness_penalty=0.3,
            adjusted_confidence=0.85,
        )

        d = result.to_dict()

        assert d["url"] == "https://example.com"
        assert d["has_significant_changes"] is True
        assert d["similarity_ratio"] == 0.7
        assert d["headings_added"] == ["New Section"]
        assert d["headings_removed"] == ["Old Section"]
        assert d["freshness_penalty"] == 0.3
        assert d["adjusted_confidence"] == 0.85

    def test_generate_timeline_notes_outdated(self):
        """Test timeline notes for outdated archive."""
        from src.crawler.wayback import ArchiveDiffResult

        result = ArchiveDiffResult(
            url="https://example.com",
            freshness_penalty=0.6,
        )

        notes = result.generate_timeline_notes()
        assert "significantly outdated" in notes.lower()

    def test_generate_timeline_notes_headings(self):
        """Test timeline notes include heading changes."""
        from src.crawler.wayback import ArchiveDiffResult

        result = ArchiveDiffResult(
            url="https://example.com",
            headings_added=["New Feature", "Updates"],
            headings_removed=["Deprecated"],
        )

        notes = result.generate_timeline_notes()
        # Notes should contain section references
        assert "New sections:" in notes, f"Expected 'New sections:' in notes: {notes}"
        assert "Removed sections:" in notes, f"Expected 'Removed sections:' in notes: {notes}"
        # Should include heading names (first 3)
        assert "New Feature" in notes, f"Expected 'New Feature' in notes: {notes}"
        assert "Deprecated" in notes, f"Expected 'Deprecated' in notes: {notes}"


class TestCompareWithCurrent:
    """Tests for WaybackFallback.compare_with_current method."""

    @pytest.fixture
    def wayback_fallback(self):
        """Create WaybackFallback instance."""
        return WaybackFallback()

    @pytest.mark.asyncio
    async def test_compare_no_archive(self, wayback_fallback):
        """Test comparison when no archive available."""
        with patch.object(
            wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = []

            result = await wayback_fallback.compare_with_current(
                "https://example.com",
                "<html><body>Current content</body></html>",
            )

            assert result.has_significant_changes is False
            assert "No archive" in result.timeline_notes

    @pytest.mark.asyncio
    async def test_compare_similar_content(self, wayback_fallback):
        """Test comparison with similar content."""
        snapshot = Snapshot(
            url="https://example.com",
            original_url="https://example.com",
            timestamp=datetime.now(UTC) - timedelta(days=5),
        )

        current_html = "<html><body><h1>Title</h1><p>Some content here.</p></body></html>"
        archived_html = "<html><body><h1>Title</h1><p>Some content here.</p></body></html>"

        with (
            patch.object(
                wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
            ) as mock_get,
            patch.object(
                wayback_fallback._client, "fetch_snapshot", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_get.return_value = [snapshot]
            mock_fetch.return_value = archived_html

            result = await wayback_fallback.compare_with_current(
                "https://example.com",
                current_html,
            )

            assert result.similarity_ratio > 0.9
            assert result.timeline_event_type == "content_unchanged"

    @pytest.mark.asyncio
    async def test_compare_modified_content(self, wayback_fallback):
        """Test comparison with modified content."""
        snapshot = Snapshot(
            url="https://example.com",
            original_url="https://example.com",
            timestamp=datetime.now(UTC) - timedelta(days=30),
        )

        current_html = """
        <html><body>
        <h1>Title</h1>
        <h2>New Section</h2>
        <p>Completely new content that wasn't there before.</p>
        <p>More new paragraphs with different information.</p>
        </body></html>
        """
        archived_html = """
        <html><body>
        <h1>Title</h1>
        <h2>Old Section</h2>
        <p>Original content from before.</p>
        </body></html>
        """

        with (
            patch.object(
                wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
            ) as mock_get,
            patch.object(
                wayback_fallback._client, "fetch_snapshot", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_get.return_value = [snapshot]
            mock_fetch.return_value = archived_html

            result = await wayback_fallback.compare_with_current(
                "https://example.com",
                current_html,
            )

            assert result.has_significant_changes is True
            assert result.similarity_ratio < 0.9
            assert "New Section" in result.headings_added
            assert "Old Section" in result.headings_removed

    @pytest.mark.asyncio
    async def test_compare_applies_freshness_penalty(self, wayback_fallback):
        """Test that comparison applies freshness penalty to confidence."""
        snapshot = Snapshot(
            url="https://example.com",
            original_url="https://example.com",
            timestamp=datetime.now(UTC) - timedelta(days=200),  # ~6 months old
        )

        current_html = "<html><body><h1>Content</h1></body></html>"
        archived_html = "<html><body><h1>Content</h1></body></html>"

        with (
            patch.object(
                wayback_fallback._client, "get_snapshots", new_callable=AsyncMock
            ) as mock_get,
            patch.object(
                wayback_fallback._client, "fetch_snapshot", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_get.return_value = [snapshot]
            mock_fetch.return_value = archived_html

            result = await wayback_fallback.compare_with_current(
                "https://example.com",
                current_html,
                base_confidence=1.0,
            )

            # 6 months = ~0.5 penalty
            assert result.freshness_penalty > 0.4
            assert result.adjusted_confidence < 1.0
            assert result.adjusted_confidence > 0.7


class TestTimelineEventTypes:
    """Tests for new timeline event types."""

    def test_content_modified_event_type(self):
        """Test CONTENT_MODIFIED event type exists."""
        from src.filter.claim_timeline import TimelineEventType

        assert TimelineEventType.CONTENT_MODIFIED.value == "content_modified"
        assert TimelineEventType.CONTENT_MAJOR_CHANGE.value == "content_major_change"
        assert TimelineEventType.ARCHIVE_ONLY.value == "archive_only"
