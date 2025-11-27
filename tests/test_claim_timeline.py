"""
Tests for claim timeline functionality.

Implements §3.4 requirements:
- Timeline event tracking (first_appeared, updated, corrected, retracted, confirmed)
- Wayback integration
- Timeline coverage metrics

Test quality complies with §7.1 standards.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.filter.claim_timeline import (
    ClaimTimeline,
    ClaimTimelineManager,
    TimelineEvent,
    TimelineEventType,
    get_timeline_manager,
    record_first_appeared,
    record_confirmation,
    record_retraction,
    get_claim_timeline,
    get_timeline_coverage,
    integrate_wayback_into_timeline,
    RETRACTION_CONFIDENCE_PENALTY,
)


# =============================================================================
# TimelineEvent Tests
# =============================================================================

class TestTimelineEvent:
    """Tests for TimelineEvent dataclass."""
    
    def test_create_event_with_all_fields(self):
        """Verify TimelineEvent stores all fields correctly."""
        # Arrange
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        
        # Act
        event = TimelineEvent(
            event_type=TimelineEventType.FIRST_APPEARED,
            timestamp=timestamp,
            source_url="https://example.com/article",
            evidence_fragment_id="frag_001",
            wayback_snapshot_url="https://web.archive.org/web/...",
            notes="Initial discovery",
            confidence=0.95,
        )
        
        # Assert
        assert event.event_type == TimelineEventType.FIRST_APPEARED
        assert event.timestamp == timestamp
        assert event.source_url == "https://example.com/article"
        assert event.evidence_fragment_id == "frag_001"
        assert event.wayback_snapshot_url == "https://web.archive.org/web/..."
        assert event.notes == "Initial discovery"
        assert event.confidence == 0.95
        assert len(event.event_id) == 8  # UUID prefix length
    
    def test_to_dict_serialization(self):
        """Verify TimelineEvent serializes to dictionary correctly."""
        # Arrange
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        event = TimelineEvent(
            event_type=TimelineEventType.CONFIRMED,
            timestamp=timestamp,
            source_url="https://example.com",
            confidence=0.8,
        )
        
        # Act
        result = event.to_dict()
        
        # Assert
        assert result["event_type"] == "confirmed"
        assert result["timestamp"] == "2024-01-15T10:30:00+00:00"
        assert result["source_url"] == "https://example.com"
        assert result["confidence"] == 0.8
        assert "event_id" in result
    
    def test_from_dict_deserialization(self):
        """Verify TimelineEvent deserializes from dictionary correctly."""
        # Arrange
        data = {
            "event_id": "test1234",
            "event_type": "retracted",
            "timestamp": "2024-02-20T14:00:00+00:00",
            "source_url": "https://retraction.example.com",
            "notes": "Claim withdrawn",
            "confidence": 0.9,
        }
        
        # Act
        event = TimelineEvent.from_dict(data)
        
        # Assert
        assert event.event_id == "test1234"
        assert event.event_type == TimelineEventType.RETRACTED
        assert event.timestamp.year == 2024
        assert event.timestamp.month == 2
        assert event.timestamp.day == 20
        assert event.source_url == "https://retraction.example.com"
        assert event.notes == "Claim withdrawn"
        assert event.confidence == 0.9
    
    def test_from_dict_with_missing_fields(self):
        """Verify TimelineEvent handles missing optional fields gracefully."""
        # Arrange
        data = {
            "event_type": "updated",
            "source_url": "https://example.com",
        }
        
        # Act
        event = TimelineEvent.from_dict(data)
        
        # Assert
        assert event.event_type == TimelineEventType.UPDATED
        assert event.source_url == "https://example.com"
        assert event.evidence_fragment_id is None
        assert event.wayback_snapshot_url is None
        assert event.notes is None
        assert event.confidence == 1.0  # Default value


# =============================================================================
# ClaimTimeline Tests
# =============================================================================

class TestClaimTimeline:
    """Tests for ClaimTimeline class."""
    
    def test_create_empty_timeline(self):
        """Verify empty timeline has correct initial state."""
        # Act
        timeline = ClaimTimeline(claim_id="claim_001")
        
        # Assert
        assert timeline.claim_id == "claim_001"
        assert len(timeline.events) == 0
        assert timeline.first_appeared is None
        assert timeline.latest_event is None
        assert timeline.is_retracted is False
        assert timeline.is_corrected is False
        assert timeline.confirmation_count == 0
        assert timeline.has_timeline is False
    
    def test_add_first_appeared_event(self):
        """Verify first appearance event is added correctly."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        timestamp = datetime(2024, 1, 15, tzinfo=timezone.utc)
        
        # Act
        event = timeline.add_event(
            event_type=TimelineEventType.FIRST_APPEARED,
            timestamp=timestamp,
            source_url="https://source.example.com",
            evidence_fragment_id="frag_001",
        )
        
        # Assert
        assert len(timeline.events) == 1
        assert timeline.first_appeared is not None
        assert timeline.first_appeared.event_type == TimelineEventType.FIRST_APPEARED
        assert timeline.first_appeared.timestamp == timestamp
        assert timeline.has_timeline is True
    
    def test_add_multiple_events_sorted_by_timestamp(self):
        """Verify events are sorted chronologically."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        ts1 = datetime(2024, 1, 15, tzinfo=timezone.utc)
        ts2 = datetime(2024, 2, 20, tzinfo=timezone.utc)
        ts3 = datetime(2024, 1, 25, tzinfo=timezone.utc)  # Intentionally out of order
        
        # Act
        timeline.add_event(TimelineEventType.FIRST_APPEARED, ts1, "url1")
        timeline.add_event(TimelineEventType.CONFIRMED, ts2, "url2")
        timeline.add_event(TimelineEventType.UPDATED, ts3, "url3")
        
        # Assert
        assert len(timeline.events) == 3
        assert timeline.events[0].timestamp == ts1
        assert timeline.events[1].timestamp == ts3
        assert timeline.events[2].timestamp == ts2
    
    def test_is_retracted_flag(self):
        """Verify retraction detection works correctly."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        
        # Assert initial state
        assert timeline.is_retracted is False
        
        # Act
        timeline.add_event(
            TimelineEventType.FIRST_APPEARED,
            source_url="https://example.com",
        )
        timeline.add_event(
            TimelineEventType.RETRACTED,
            source_url="https://retraction.example.com",
        )
        
        # Assert after retraction
        assert timeline.is_retracted is True
    
    def test_is_corrected_flag(self):
        """Verify correction detection works correctly."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        
        # Assert initial state
        assert timeline.is_corrected is False
        
        # Act
        timeline.add_event(TimelineEventType.CORRECTED, source_url="url")
        
        # Assert
        assert timeline.is_corrected is True
    
    def test_confirmation_count(self):
        """Verify confirmation counting works correctly."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        
        # Assert initial state
        assert timeline.confirmation_count == 0
        
        # Act
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="url1")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url2")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url3")
        timeline.add_event(TimelineEventType.UPDATED, source_url="url4")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url5")
        
        # Assert
        assert timeline.confirmation_count == 3
    
    def test_latest_event(self):
        """Verify latest event retrieval works correctly."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        ts1 = datetime(2024, 1, 15, tzinfo=timezone.utc)
        ts2 = datetime(2024, 3, 10, tzinfo=timezone.utc)
        
        # Act
        timeline.add_event(TimelineEventType.FIRST_APPEARED, ts1, "url1")
        timeline.add_event(TimelineEventType.CONFIRMED, ts2, "url2")
        
        # Assert
        assert timeline.latest_event is not None
        assert timeline.latest_event.timestamp == ts2
        assert timeline.latest_event.event_type == TimelineEventType.CONFIRMED
    
    def test_get_events_by_type(self):
        """Verify filtering events by type works correctly."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="url1")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url2")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url3")
        timeline.add_event(TimelineEventType.UPDATED, source_url="url4")
        
        # Act
        confirmations = timeline.get_events_by_type(TimelineEventType.CONFIRMED)
        
        # Assert
        assert len(confirmations) == 2
        assert all(e.event_type == TimelineEventType.CONFIRMED for e in confirmations)
    
    def test_get_events_in_range(self):
        """Verify filtering events by date range works correctly."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        ts1 = datetime(2024, 1, 15, tzinfo=timezone.utc)
        ts2 = datetime(2024, 2, 20, tzinfo=timezone.utc)
        ts3 = datetime(2024, 3, 25, tzinfo=timezone.utc)
        
        timeline.add_event(TimelineEventType.FIRST_APPEARED, ts1, "url1")
        timeline.add_event(TimelineEventType.UPDATED, ts2, "url2")
        timeline.add_event(TimelineEventType.CONFIRMED, ts3, "url3")
        
        # Act
        start = datetime(2024, 2, 1, tzinfo=timezone.utc)
        end = datetime(2024, 3, 1, tzinfo=timezone.utc)
        events_in_range = timeline.get_events_in_range(start, end)
        
        # Assert
        assert len(events_in_range) == 1
        assert events_in_range[0].timestamp == ts2
    
    def test_calculate_confidence_adjustment_no_events(self):
        """Verify confidence adjustment is 1.0 for empty timeline."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        
        # Act
        adjustment = timeline.calculate_confidence_adjustment()
        
        # Assert
        assert adjustment == 1.0
    
    def test_calculate_confidence_adjustment_retraction(self):
        """Verify retraction applies correct penalty."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        timeline.add_event(TimelineEventType.RETRACTED, source_url="url")
        
        # Act
        adjustment = timeline.calculate_confidence_adjustment()
        
        # Assert
        assert adjustment == RETRACTION_CONFIDENCE_PENALTY
    
    def test_calculate_confidence_adjustment_correction(self):
        """Verify correction applies correct penalty."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        timeline.add_event(TimelineEventType.CORRECTED, source_url="url")
        
        # Act
        adjustment = timeline.calculate_confidence_adjustment()
        
        # Assert
        assert adjustment == 0.8
    
    def test_calculate_confidence_adjustment_confirmations(self):
        """Verify confirmations apply correct bonus."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url1")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url2")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url3")
        
        # Act
        adjustment = timeline.calculate_confidence_adjustment()
        
        # Assert - 3 confirmations = 30% bonus, capped at 50%
        assert adjustment == 1.3
    
    def test_calculate_confidence_adjustment_confirmations_capped(self):
        """Verify confirmation bonus is capped at 50%."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        for i in range(10):  # 10 confirmations
            timeline.add_event(TimelineEventType.CONFIRMED, source_url=f"url{i}")
        
        # Act
        adjustment = timeline.calculate_confidence_adjustment()
        
        # Assert - Capped at 1.5 (50% bonus)
        assert adjustment == 1.5
    
    def test_to_dict_serialization(self):
        """Verify timeline serializes to dictionary correctly."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        ts = datetime(2024, 1, 15, tzinfo=timezone.utc)
        timeline.add_event(TimelineEventType.FIRST_APPEARED, ts, "https://example.com")
        
        # Act
        result = timeline.to_dict()
        
        # Assert
        assert result["claim_id"] == "claim_001"
        assert len(result["events"]) == 1
        assert "summary" in result
        assert result["summary"]["event_count"] == 1
        assert result["summary"]["is_retracted"] is False
    
    def test_to_json_serialization(self):
        """Verify timeline serializes to JSON correctly."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_001")
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="url")
        
        # Act
        json_str = timeline.to_json()
        
        # Assert
        data = json.loads(json_str)
        assert data["claim_id"] == "claim_001"
        assert len(data["events"]) == 1
    
    def test_from_dict_deserialization(self):
        """Verify timeline deserializes from dictionary correctly."""
        # Arrange
        data = {
            "claim_id": "claim_002",
            "events": [
                {
                    "event_type": "first_appeared",
                    "timestamp": "2024-01-15T10:00:00+00:00",
                    "source_url": "https://source.example.com",
                },
                {
                    "event_type": "confirmed",
                    "timestamp": "2024-02-20T15:00:00+00:00",
                    "source_url": "https://confirm.example.com",
                },
            ],
        }
        
        # Act
        timeline = ClaimTimeline.from_dict(data)
        
        # Assert
        assert timeline.claim_id == "claim_002"
        assert len(timeline.events) == 2
        assert timeline.first_appeared is not None
        assert timeline.confirmation_count == 1
    
    def test_from_json_deserialization(self):
        """Verify timeline deserializes from JSON correctly."""
        # Arrange
        json_str = json.dumps({
            "claim_id": "claim_003",
            "events": [
                {
                    "event_type": "first_appeared",
                    "timestamp": "2024-01-15T10:00:00+00:00",
                    "source_url": "https://example.com",
                },
            ],
        })
        
        # Act
        timeline = ClaimTimeline.from_json(json_str)
        
        # Assert
        assert timeline is not None
        assert timeline.claim_id == "claim_003"
        assert len(timeline.events) == 1
    
    def test_from_json_with_invalid_json(self):
        """Verify from_json returns None for invalid JSON."""
        # Arrange
        invalid_json = "not valid json {"
        
        # Act
        result = ClaimTimeline.from_json(invalid_json)
        
        # Assert
        assert result is None
    
    def test_from_json_with_none(self):
        """Verify from_json returns None for None input."""
        # Act
        result = ClaimTimeline.from_json(None)
        
        # Assert
        assert result is None


# =============================================================================
# ClaimTimelineManager Tests
# =============================================================================

class TestClaimTimelineManager:
    """Tests for ClaimTimelineManager class."""
    
    @pytest.fixture
    def manager(self):
        """Create fresh manager for each test."""
        return ClaimTimelineManager()
    
    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        mock = MagicMock()
        mock.fetch_one = AsyncMock(return_value=None)
        mock.fetch_all = AsyncMock(return_value=[])
        mock.update = AsyncMock(return_value=None)
        return mock
    
    @pytest.mark.asyncio
    async def test_get_timeline_creates_new_for_nonexistent_claim(self, manager, mock_db):
        """Verify get_timeline creates new timeline for non-existent claim."""
        # Arrange
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})
            
            # Act
            timeline = await manager.get_timeline("claim_new")
            
            # Assert
            assert timeline is not None
            assert timeline.claim_id == "claim_new"
            assert len(timeline.events) == 0
    
    @pytest.mark.asyncio
    async def test_get_timeline_loads_existing_from_db(self, manager, mock_db):
        """Verify get_timeline loads existing timeline from database."""
        # Arrange
        existing_timeline = {
            "claim_id": "claim_existing",
            "events": [
                {
                    "event_type": "first_appeared",
                    "timestamp": "2024-01-15T10:00:00+00:00",
                    "source_url": "https://example.com",
                },
            ],
        }
        
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            mock_db.fetch_one = AsyncMock(return_value={
                "timeline_json": json.dumps(existing_timeline)
            })
            
            # Act
            timeline = await manager.get_timeline("claim_existing")
            
            # Assert
            assert timeline is not None
            assert len(timeline.events) == 1
            assert timeline.first_appeared is not None
    
    @pytest.mark.asyncio
    async def test_get_timeline_uses_cache(self, manager, mock_db):
        """Verify get_timeline uses cache for repeated requests."""
        # Arrange
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})
            
            # First call
            await manager.get_timeline("claim_cached")
            
            # Reset mock to detect second call
            mock_db.fetch_one.reset_mock()
            
            # Act - Second call
            timeline = await manager.get_timeline("claim_cached")
            
            # Assert - Should use cache, not call DB
            mock_db.fetch_one.assert_not_called()
            assert timeline is not None
    
    @pytest.mark.asyncio
    async def test_save_timeline_updates_database(self, manager, mock_db):
        """Verify save_timeline updates database correctly."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_save")
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="url")
        
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            # Act
            result = await manager.save_timeline(timeline)
            
            # Assert
            assert result is True
            mock_db.update.assert_called_once()
            call_args = mock_db.update.call_args
            assert call_args[0][0] == "claims"
            assert "timeline_json" in call_args[0][1]
    
    @pytest.mark.asyncio
    async def test_add_first_appeared_creates_event(self, manager, mock_db):
        """Verify add_first_appeared creates first_appeared event."""
        # Arrange
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})
            
            # Act
            event = await manager.add_first_appeared(
                claim_id="claim_first",
                source_url="https://first.example.com",
                fragment_id="frag_001",
            )
            
            # Assert
            assert event is not None
            assert event.event_type == TimelineEventType.FIRST_APPEARED
            assert event.source_url == "https://first.example.com"
    
    @pytest.mark.asyncio
    async def test_add_first_appeared_skips_if_already_exists(self, manager, mock_db):
        """Verify add_first_appeared doesn't duplicate if event exists."""
        # Arrange
        existing = {
            "claim_id": "claim_dup",
            "events": [{
                "event_type": "first_appeared",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "source_url": "https://original.example.com",
            }],
        }
        
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            mock_db.fetch_one = AsyncMock(return_value={
                "timeline_json": json.dumps(existing)
            })
            
            # Act
            event = await manager.add_first_appeared(
                claim_id="claim_dup",
                source_url="https://new.example.com",
            )
            
            # Assert - Returns existing event, doesn't create new one
            assert event is not None
            assert event.source_url == "https://original.example.com"
    
    @pytest.mark.asyncio
    async def test_add_confirmation_creates_event(self, manager, mock_db):
        """Verify add_confirmation creates confirmation event."""
        # Arrange
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})
            
            # Act
            event = await manager.add_confirmation(
                claim_id="claim_conf",
                source_url="https://confirm.example.com",
                notes="Confirmed by independent source",
            )
            
            # Assert
            assert event is not None
            assert event.event_type == TimelineEventType.CONFIRMED
            assert event.notes == "Confirmed by independent source"
    
    @pytest.mark.asyncio
    async def test_add_retraction_creates_event_and_adjusts_confidence(self, manager, mock_db):
        """Verify add_retraction creates event and updates confidence."""
        # Arrange
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            mock_db.fetch_one = AsyncMock(side_effect=[
                {"timeline_json": None},  # First call for get_timeline
                {"confidence_score": 0.9},  # Second call for confidence adjustment
            ])
            
            # Act
            event = await manager.add_retraction(
                claim_id="claim_ret",
                source_url="https://retract.example.com",
                notes="Withdrawn due to errors",
            )
            
            # Assert
            assert event is not None
            assert event.event_type == TimelineEventType.RETRACTED
            # Verify confidence update was called
            assert mock_db.update.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_integrate_wayback_result_adds_events(self, manager, mock_db):
        """Verify Wayback results are integrated into timeline."""
        # Arrange
        wayback_result = {
            "timeline": [
                {
                    "timestamp": "2024-01-15T10:00:00+00:00",
                    "snapshot_url": "https://web.archive.org/web/1",
                    "has_significant_change": False,
                },
                {
                    "timestamp": "2024-02-20T15:00:00+00:00",
                    "snapshot_url": "https://web.archive.org/web/2",
                    "has_significant_change": True,
                },
            ],
        }
        
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})
            
            # Act
            events_added = await manager.integrate_wayback_result(
                claim_id="claim_wb",
                source_url="https://source.example.com",
                wayback_result=wayback_result,
            )
            
            # Assert
            assert events_added == 2  # first_appeared + updated
    
    @pytest.mark.asyncio
    async def test_get_timeline_coverage_calculates_correctly(self, manager, mock_db):
        """Verify timeline coverage metrics are calculated correctly."""
        # Arrange
        claims = [
            # Claim with timeline
            {"id": "c1", "timeline_json": json.dumps({
                "claim_id": "c1",
                "events": [{"event_type": "first_appeared", "timestamp": "2024-01-01T00:00:00+00:00", "source_url": "url1"}],
            })},
            # Claim with retraction
            {"id": "c2", "timeline_json": json.dumps({
                "claim_id": "c2",
                "events": [{"event_type": "retracted", "timestamp": "2024-01-02T00:00:00+00:00", "source_url": "url2"}],
            })},
            # Claim without timeline
            {"id": "c3", "timeline_json": None},
        ]
        
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            mock_db.fetch_all = AsyncMock(return_value=claims)
            
            # Act
            coverage = await manager.get_timeline_coverage("task_001")
            
            # Assert
            assert coverage["total_claims"] == 3
            assert coverage["claims_with_timeline"] == 2
            assert coverage["coverage_rate"] == pytest.approx(2/3, abs=0.001)
            assert coverage["claims_retracted"] == 1
    
    def test_clear_cache(self, manager):
        """Verify cache clearing works."""
        # Arrange
        manager._cache["test"] = ClaimTimeline(claim_id="test")
        
        # Act
        manager.clear_cache()
        
        # Assert
        assert len(manager._cache) == 0


# =============================================================================
# Convenience Function Tests
# =============================================================================

class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_get_timeline_manager_returns_singleton(self):
        """Verify get_timeline_manager returns same instance."""
        # Act
        manager1 = get_timeline_manager()
        manager2 = get_timeline_manager()
        
        # Assert
        assert manager1 is manager2
    
    @pytest.mark.asyncio
    async def test_record_first_appeared_calls_manager(self):
        """Verify record_first_appeared delegates to manager."""
        # Arrange
        mock_db = MagicMock()
        mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})
        mock_db.update = AsyncMock()
        
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            # Act
            event = await record_first_appeared(
                claim_id="test_claim",
                source_url="https://example.com",
            )
            
            # Assert
            assert event is not None
            assert event.event_type == TimelineEventType.FIRST_APPEARED
    
    @pytest.mark.asyncio
    async def test_record_confirmation_calls_manager(self):
        """Verify record_confirmation delegates to manager."""
        # Arrange
        mock_db = MagicMock()
        mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})
        mock_db.update = AsyncMock()
        
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            # Act
            event = await record_confirmation(
                claim_id="test_claim",
                source_url="https://confirm.example.com",
            )
            
            # Assert
            assert event is not None
            assert event.event_type == TimelineEventType.CONFIRMED
    
    @pytest.mark.asyncio
    async def test_record_retraction_calls_manager(self):
        """Verify record_retraction delegates to manager."""
        # Arrange
        mock_db = MagicMock()
        mock_db.fetch_one = AsyncMock(side_effect=[
            {"timeline_json": None},
            {"confidence_score": 0.8},
        ])
        mock_db.update = AsyncMock()
        
        with patch("src.filter.claim_timeline.get_database", return_value=mock_db):
            # Act
            event = await record_retraction(
                claim_id="test_claim",
                source_url="https://retract.example.com",
                notes="Error found",
            )
            
            # Assert
            assert event is not None
            assert event.event_type == TimelineEventType.RETRACTED


# =============================================================================
# Edge Cases and Boundary Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_timeline_with_empty_source_url(self):
        """Verify timeline handles empty source URL."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_empty")
        
        # Act
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="")
        
        # Assert - Has event but has_timeline should be False (no valid source)
        assert len(timeline.events) == 1
        assert timeline.has_timeline is False
    
    def test_timeline_event_with_far_future_date(self):
        """Verify timeline handles far future dates."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_future")
        future_date = datetime(2099, 12, 31, tzinfo=timezone.utc)
        
        # Act
        timeline.add_event(TimelineEventType.FIRST_APPEARED, future_date, "url")
        
        # Assert
        assert timeline.first_appeared is not None
        assert timeline.first_appeared.timestamp.year == 2099
    
    def test_timeline_event_with_past_date(self):
        """Verify timeline handles past dates."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_past")
        past_date = datetime(1990, 1, 1, tzinfo=timezone.utc)
        
        # Act
        timeline.add_event(TimelineEventType.FIRST_APPEARED, past_date, "url")
        
        # Assert
        assert timeline.first_appeared is not None
        assert timeline.first_appeared.timestamp.year == 1990
    
    def test_from_dict_with_empty_events(self):
        """Verify from_dict handles empty events list."""
        # Arrange
        data = {"claim_id": "claim_empty", "events": []}
        
        # Act
        timeline = ClaimTimeline.from_dict(data)
        
        # Assert
        assert timeline.claim_id == "claim_empty"
        assert len(timeline.events) == 0
        assert timeline.has_timeline is False
    
    def test_from_dict_with_missing_claim_id(self):
        """Verify from_dict handles missing claim_id."""
        # Arrange
        data = {"events": []}
        
        # Act
        timeline = ClaimTimeline.from_dict(data)
        
        # Assert
        assert timeline.claim_id == ""
    
    def test_confidence_adjustment_with_both_retraction_and_confirmations(self):
        """Verify confidence adjustment combines retraction and confirmations."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_complex")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url1")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url2")
        timeline.add_event(TimelineEventType.RETRACTED, source_url="url3")
        
        # Act
        adjustment = timeline.calculate_confidence_adjustment()
        
        # Assert - Retraction (0.5) * confirmation bonus (1.2) = 0.6
        expected = RETRACTION_CONFIDENCE_PENALTY * (1.0 + 0.2)
        assert adjustment == pytest.approx(expected, abs=0.01)
    
    def test_get_events_in_range_with_no_matches(self):
        """Verify get_events_in_range returns empty list when no matches."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_range")
        ts = datetime(2024, 6, 15, tzinfo=timezone.utc)
        timeline.add_event(TimelineEventType.FIRST_APPEARED, ts, "url")
        
        # Act - Query range that doesn't include the event
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 3, 1, tzinfo=timezone.utc)
        result = timeline.get_events_in_range(start, end)
        
        # Assert
        assert len(result) == 0
    
    def test_get_events_by_type_with_no_matches(self):
        """Verify get_events_by_type returns empty list when no matches."""
        # Arrange
        timeline = ClaimTimeline(claim_id="claim_type")
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="url")
        
        # Act
        result = timeline.get_events_by_type(TimelineEventType.RETRACTED)
        
        # Assert
        assert len(result) == 0

