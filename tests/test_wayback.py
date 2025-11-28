"""
Tests for Wayback Machine differential exploration module.

Covers:
- Snapshot: Parsing and URL generation
- ContentAnalyzer: Text extraction and comparison
- WaybackExplorer: Archive exploration
- WaybackBudgetManager: Budget tracking
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.crawler.wayback import (
    Snapshot,
    ContentDiff,
    TimelineEntry,
    WaybackResult,
    WaybackClient,
    ContentAnalyzer,
    WaybackExplorer,
    WaybackBudgetManager,
    explore_wayback,
    get_archived_content,
    check_content_modified,
    WAYBACK_BUDGET_RATIO,
)


# =============================================================================
# Sample HTML for Testing
# =============================================================================

SAMPLE_HTML_V1 = """
<!DOCTYPE html>
<html>
<head><title>Test Page V1</title></head>
<body>
    <header><nav>Navigation</nav></header>
    <article>
        <h1>Main Title</h1>
        <h2>Section One</h2>
        <p>This is the original content from version 1.</p>
        <p>Published on 2023-01-15.</p>
        <h2>Section Two</h2>
        <p>More content here.</p>
    </article>
    <footer>Footer content</footer>
</body>
</html>
"""

SAMPLE_HTML_V2 = """
<!DOCTYPE html>
<html>
<head><title>Test Page V2</title></head>
<body>
    <header><nav>Navigation</nav></header>
    <article>
        <h1>Main Title Updated</h1>
        <h2>Section One</h2>
        <p>This is the updated content from version 2.</p>
        <p>Updated on 2024-01-15.</p>
        <h2>Section Three</h2>
        <p>New section added in version 2.</p>
        <p>Additional paragraph with more information.</p>
    </article>
    <footer>Footer content</footer>
</body>
</html>
"""


# =============================================================================
# Snapshot Tests
# =============================================================================

class TestSnapshot:
    """Tests for Snapshot dataclass."""
    
    def test_wayback_url_generation(self):
        """Should generate correct Wayback URL."""
        snapshot = Snapshot(
            url="example.com/page",
            original_url="https://example.com/page",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        )
        
        assert "20240115103000" in snapshot.wayback_url
        assert "example.com/page" in snapshot.wayback_url
        assert snapshot.wayback_url.startswith("https://web.archive.org/web/")
    
    def test_from_cdx_line_valid(self):
        """Should parse valid CDX line."""
        line = "com,example)/page 20240115103000 https://example.com/page text/html 200 ABC123 1234"
        
        snapshot = Snapshot.from_cdx_line(line, "https://example.com/page")
        
        assert snapshot is not None
        assert snapshot.timestamp.year == 2024
        assert snapshot.timestamp.month == 1
        assert snapshot.timestamp.day == 15
        assert snapshot.status_code == 200
        assert snapshot.mime_type == "text/html"
    
    def test_from_cdx_line_invalid(self):
        """Should return None for invalid CDX line."""
        line = "invalid line"
        
        snapshot = Snapshot.from_cdx_line(line, "https://example.com/page")
        
        assert snapshot is None
    
    def test_from_cdx_line_missing_status(self):
        """Should handle missing status code."""
        line = "com,example)/page 20240115103000 https://example.com/page text/html - ABC123 1234"
        
        snapshot = Snapshot.from_cdx_line(line, "https://example.com/page")
        
        assert snapshot is not None
        assert snapshot.status_code == 200  # Default


# =============================================================================
# ContentDiff Tests
# =============================================================================

class TestContentDiff:
    """Tests for ContentDiff dataclass."""
    
    def test_is_significant_low_similarity(self):
        """Low similarity should be significant."""
        old_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        new_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        
        diff = ContentDiff(
            old_snapshot=old_snap,
            new_snapshot=new_snap,
            similarity_ratio=0.5,  # 50% similar
        )
        
        assert diff.is_significant(threshold=0.8)
    
    def test_is_significant_heading_changes(self):
        """Heading changes should be significant."""
        old_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        new_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        
        diff = ContentDiff(
            old_snapshot=old_snap,
            new_snapshot=new_snap,
            similarity_ratio=0.9,  # High similarity
            heading_changes=[("added", "", "New Heading")],
        )
        
        assert diff.is_significant()
    
    def test_is_significant_large_word_count_change(self):
        """Large word count change should be significant."""
        old_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        new_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        
        diff = ContentDiff(
            old_snapshot=old_snap,
            new_snapshot=new_snap,
            similarity_ratio=0.9,
            word_count_change=500,  # Large change
        )
        
        assert diff.is_significant()
    
    def test_not_significant(self):
        """High similarity with no changes should not be significant."""
        old_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        new_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        
        diff = ContentDiff(
            old_snapshot=old_snap,
            new_snapshot=new_snap,
            similarity_ratio=0.95,
            word_count_change=10,
        )
        
        assert not diff.is_significant()
    
    def test_to_dict(self):
        """Should convert to serializable dict."""
        old_snap = Snapshot(
            url="",
            original_url="",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        new_snap = Snapshot(
            url="",
            original_url="",
            timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        
        diff = ContentDiff(
            old_snapshot=old_snap,
            new_snapshot=new_snap,
            similarity_ratio=0.7,
            word_count_change=100,
        )
        
        d = diff.to_dict()
        
        assert "old_timestamp" in d
        assert "similarity_ratio" in d
        assert d["is_significant"] is True


# =============================================================================
# WaybackResult Tests
# =============================================================================

class TestWaybackResult:
    """Tests for WaybackResult dataclass."""
    
    def test_to_dict(self):
        """Should convert to serializable dict."""
        result = WaybackResult(
            url="https://example.com/page",
            snapshots_found=5,
            snapshots_fetched=4,
            earliest_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            latest_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        
        d = result.to_dict()
        
        assert d["url"] == "https://example.com/page"
        assert d["snapshots_found"] == 5
        assert d["earliest_date"] is not None


# =============================================================================
# ContentAnalyzer Tests
# =============================================================================

class TestContentAnalyzer:
    """Tests for ContentAnalyzer class."""
    
    def test_extract_text(self):
        """Should extract main text content.
        
        SAMPLE_HTML_V1 contains article with 'Main Title' and 'original content'.
        Navigation text is in <header><nav> and should be excluded.
        """
        analyzer = ContentAnalyzer()
        text = analyzer.extract_text(SAMPLE_HTML_V1)
        
        # Article content should be present
        assert "Main Title" in text, "Expected 'Main Title' in extracted text"
        assert "original content" in text, "Expected 'original content' in extracted text"
        # Navigation content should be excluded (trafilatura filters nav elements)
        assert "Navigation" not in text, "Expected 'Navigation' to be excluded from article extraction"
    
    def test_extract_headings(self):
        """Should extract all headings."""
        analyzer = ContentAnalyzer()
        headings = analyzer.extract_headings(SAMPLE_HTML_V1)
        
        assert "Main Title" in headings
        assert "Section One" in headings
        assert "Section Two" in headings
    
    def test_extract_dates(self):
        """Should extract date references."""
        analyzer = ContentAnalyzer()
        dates = analyzer.extract_dates(SAMPLE_HTML_V1)
        
        assert any("2023" in d for d in dates)
    
    def test_extract_dates_japanese(self):
        """Should extract Japanese date format."""
        analyzer = ContentAnalyzer()
        html = "<html><body><p>2024年1月15日に公開</p></body></html>"
        
        dates = analyzer.extract_dates(html)
        
        assert len(dates) >= 1
        assert any("2024年1月15日" in d for d in dates)
    
    def test_compare_detects_changes(self):
        """Should detect differences between versions.
        
        SAMPLE_HTML_V1 has 'Main Title' while V2 has 'Main Title Updated'.
        SAMPLE_HTML_V1 has 'Section Two' while V2 has 'Section Three'.
        """
        analyzer = ContentAnalyzer()
        
        old_snap = Snapshot(
            url="", original_url="",
            timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )
        new_snap = Snapshot(
            url="", original_url="",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        
        diff = analyzer.compare(SAMPLE_HTML_V1, SAMPLE_HTML_V2, old_snap, new_snap)
        
        # V1 and V2 have different content - similarity should be below 1.0
        assert diff.similarity_ratio < 1.0, f"Expected similarity < 1.0 for different content, got {diff.similarity_ratio}"
        # Heading changed from 'Main Title' to 'Main Title Updated' and 'Section Two' to 'Section Three'
        assert len(diff.heading_changes) >= 1, f"Expected at least 1 heading change, got {len(diff.heading_changes)}"
    
    def test_compare_identical(self):
        """Identical content should have high similarity."""
        analyzer = ContentAnalyzer()
        
        old_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        new_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        
        diff = analyzer.compare(SAMPLE_HTML_V1, SAMPLE_HTML_V1, old_snap, new_snap)
        
        assert diff.similarity_ratio == 1.0
        assert len(diff.added_lines) == 0
        assert len(diff.removed_lines) == 0
    
    def test_summarize_content(self):
        """Should generate brief summary."""
        analyzer = ContentAnalyzer()
        summary = analyzer.summarize_content(SAMPLE_HTML_V1, max_length=100)
        
        assert len(summary) <= 100
        assert len(summary) > 0


# =============================================================================
# WaybackClient Tests
# =============================================================================

class TestWaybackClient:
    """Tests for WaybackClient class."""
    
    def test_remove_wayback_toolbar(self):
        """Should remove Wayback toolbar from HTML."""
        client = WaybackClient()
        
        html_with_toolbar = """
        <html>
        <!-- BEGIN WAYBACK TOOLBAR INSERT -->
        <div id="wm-ipp">Toolbar content</div>
        <!-- END WAYBACK TOOLBAR INSERT -->
        <body><p>Real content</p></body>
        </html>
        """
        
        cleaned = client._remove_wayback_toolbar(html_with_toolbar)
        
        assert "WAYBACK TOOLBAR" not in cleaned
        assert "Real content" in cleaned


# =============================================================================
# WaybackBudgetManager Tests
# =============================================================================

class TestWaybackBudgetManager:
    """Tests for WaybackBudgetManager class."""
    
    def test_get_task_budget(self):
        """Should calculate correct budget."""
        manager = WaybackBudgetManager()
        
        budget = manager.get_task_budget("task1", total_pages=100)
        
        expected = int(100 * WAYBACK_BUDGET_RATIO)
        assert budget == expected
    
    def test_consume_budget_success(self):
        """Should consume budget when available."""
        manager = WaybackBudgetManager()
        manager.get_task_budget("task1", total_pages=100)
        
        assert manager.consume_budget("task1", 5) is True
        assert manager._task_budgets["task1"] == int(100 * WAYBACK_BUDGET_RATIO) - 5
    
    def test_consume_budget_insufficient(self):
        """Should fail when insufficient budget."""
        manager = WaybackBudgetManager()
        manager._task_budgets["task1"] = 3
        
        assert manager.consume_budget("task1", 5) is False
        assert manager._task_budgets["task1"] == 3  # Unchanged
    
    def test_consume_budget_unknown_task(self):
        """Should fail for unknown task."""
        manager = WaybackBudgetManager()
        
        assert manager.consume_budget("unknown", 1) is False
    
    def test_reset_task_budget(self):
        """Should reset task budget."""
        manager = WaybackBudgetManager()
        manager._task_budgets["task1"] = 10
        
        manager.reset_task_budget("task1")
        
        assert "task1" not in manager._task_budgets


# =============================================================================
# WaybackExplorer Tests
# =============================================================================

class TestWaybackExplorer:
    """Tests for WaybackExplorer class."""
    
    @pytest.mark.asyncio
    async def test_explore_no_snapshots(self):
        """Should handle no snapshots gracefully."""
        explorer = WaybackExplorer()
        
        with patch.object(explorer._client, 'get_snapshots', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            
            result = await explorer.explore("https://example.com/page")
            
            assert result.snapshots_found == 0
            assert len(result.timeline) == 0
    
    @pytest.mark.asyncio
    async def test_check_content_changes(self):
        """Should detect changes from archive."""
        explorer = WaybackExplorer()
        
        archived_snapshot = Snapshot(
            url="example.com/page",
            original_url="https://example.com/page",
            timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )
        
        with patch.object(explorer._client, 'get_snapshots', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [archived_snapshot]
            
            with patch.object(explorer._client, 'fetch_snapshot', new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = SAMPLE_HTML_V1
                
                has_changes = await explorer.check_content_changes(
                    "https://example.com/page",
                    SAMPLE_HTML_V2,
                )
                
                assert has_changes is True


# =============================================================================
# MCP Tool Function Tests
# =============================================================================

class TestMCPToolFunctions:
    """Tests for MCP tool integration functions."""
    
    @pytest.mark.asyncio
    async def test_explore_wayback_function(self):
        """explore_wayback should return structured result."""
        with patch("src.crawler.wayback.get_wayback_explorer") as mock_get:
            mock_explorer = MagicMock()
            mock_explorer.explore = AsyncMock(return_value=WaybackResult(
                url="https://example.com/page",
                snapshots_found=3,
                snapshots_fetched=3,
            ))
            mock_get.return_value = mock_explorer
            
            result = await explore_wayback("https://example.com/page")
            
            assert result["url"] == "https://example.com/page"
            assert "timeline" in result
            assert "diffs" in result
    
    @pytest.mark.asyncio
    async def test_get_archived_content_found(self):
        """get_archived_content should return content when found."""
        with patch("src.crawler.wayback.get_wayback_explorer") as mock_get:
            mock_explorer = MagicMock()
            mock_snapshot = Snapshot(
                url="",
                original_url="https://example.com/page",
                timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            )
            mock_explorer.get_historical_content = AsyncMock(
                return_value=(SAMPLE_HTML_V1, mock_snapshot)
            )
            mock_get.return_value = mock_explorer
            
            result = await get_archived_content(
                "https://example.com/page",
                "2024-01-15T00:00:00+00:00",
            )
            
            assert result["found"] is True
            assert "summary" in result
            assert "headings" in result
    
    @pytest.mark.asyncio
    async def test_get_archived_content_not_found(self):
        """get_archived_content should handle not found."""
        with patch("src.crawler.wayback.get_wayback_explorer") as mock_get:
            mock_explorer = MagicMock()
            mock_explorer.get_historical_content = AsyncMock(return_value=(None, None))
            mock_get.return_value = mock_explorer
            
            result = await get_archived_content(
                "https://example.com/page",
                "2024-01-15T00:00:00+00:00",
            )
            
            assert result["found"] is False
    
    @pytest.mark.asyncio
    async def test_check_content_modified_function(self):
        """check_content_modified should return modification status."""
        with patch("src.crawler.wayback.get_wayback_explorer") as mock_get:
            mock_explorer = MagicMock()
            mock_explorer.check_content_changes = AsyncMock(return_value=True)
            mock_get.return_value = mock_explorer
            
            result = await check_content_modified(
                "https://example.com/page",
                "<html></html>",
            )
            
            assert result["has_significant_changes"] is True


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge case tests."""
    
    def test_empty_html_extraction(self):
        """Should handle empty HTML."""
        analyzer = ContentAnalyzer()
        
        text = analyzer.extract_text("")
        headings = analyzer.extract_headings("")
        
        assert text == ""
        assert headings == []
    
    def test_malformed_html(self):
        """Should handle malformed HTML without raising exceptions.
        
        Malformed HTML with unclosed tags should be handled gracefully.
        """
        analyzer = ContentAnalyzer()
        
        html = "<html><body><h1>Unclosed heading<p>Text</body>"
        
        # Should not raise exception - both should complete successfully
        text = analyzer.extract_text(html)
        headings = analyzer.extract_headings(html)
        
        # At minimum, should return valid types without exception
        assert isinstance(text, str), "extract_text should return str"
        assert isinstance(headings, list), "extract_headings should return list"
        # The content should be extracted in some form
        combined = text + " ".join(headings)
        assert "Unclosed" in combined or "Text" in combined, "Expected some content to be extracted from malformed HTML"
    
    def test_compare_empty_content(self):
        """Should handle empty content comparison."""
        analyzer = ContentAnalyzer()
        
        old_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        new_snap = Snapshot(url="", original_url="", timestamp=datetime.now(timezone.utc))
        
        diff = analyzer.compare("", "", old_snap, new_snap)
        
        assert diff.similarity_ratio == 1.0  # Empty == empty
    
    def test_budget_manager_multiple_tasks(self):
        """Should track budgets for multiple tasks."""
        manager = WaybackBudgetManager()
        
        manager.get_task_budget("task1", 100)
        manager.get_task_budget("task2", 200)
        
        assert manager._task_budgets["task1"] != manager._task_budgets["task2"]
        
        manager.consume_budget("task1", 5)
        
        # task2 budget should be unchanged
        assert manager._task_budgets["task2"] == int(200 * WAYBACK_BUDGET_RATIO)

