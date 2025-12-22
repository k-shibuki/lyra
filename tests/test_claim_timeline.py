"""
Tests for claim timeline functionality.

Implements §3.4 requirements:
- Timeline event tracking (first_appeared, updated, corrected, retracted, confirmed)
- Wayback integration
- Timeline coverage metrics

Test quality complies with §7.1 standards.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-TE-01 | TimelineEvent with all fields | Equivalence – complete data | All fields correctly stored | - |
| TC-TE-02 | TimelineEvent serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-TE-03 | TimelineEvent deserialization | Equivalence – from_dict | Object correctly populated | - |
| TC-TE-04 | TimelineEvent with missing optional | Boundary – partial data | Defaults used for missing | - |
| TC-CT-01 | Empty ClaimTimeline | Boundary – no events | first_appeared=None, empty events | - |
| TC-CT-02 | Add FIRST_APPEARED event | Equivalence – first event | first_appeared set, event added | - |
| TC-CT-03 | Add CONFIRMED event | Equivalence – confirmation | last_confirmed updated | - |
| TC-CT-04 | Add RETRACTED event | Equivalence – retraction | is_retracted=True, penalty applied | - |
| TC-CT-05 | Add UPDATED event | Equivalence – update | Event added to timeline | - |
| TC-CT-06 | Add CORRECTED event | Equivalence – correction | was_corrected=True | - |
| TC-CT-07 | is_still_valid computation | Equivalence – status | Returns True if not retracted | - |
| TC-CT-08 | Timeline span calculation | Equivalence – calculation | Correct duration between events | - |
| TC-CT-09 | Coverage metrics | Equivalence – metrics | Correct wayback_coverage ratio | - |
| TC-CT-10 | ClaimTimeline serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-CT-11 | ClaimTimeline deserialization | Equivalence – from_dict | Object correctly populated | - |
| TC-CTM-01 | Create timeline | Equivalence – creation | New timeline with first event | - |
| TC-CTM-02 | Get existing timeline | Equivalence – retrieval | Returns correct timeline | - |
| TC-CTM-03 | Get non-existent timeline | Boundary – not found | Returns None | - |
| TC-CTM-04 | Record confirmation | Equivalence – confirmation | Event added to timeline | - |
| TC-CTM-05 | Record retraction | Equivalence – retraction | Timeline marked as retracted | - |
| TC-CTM-06 | Record multiple events | Equivalence – sequence | Events in correct order | - |
| TC-CTM-07 | Get timeline coverage | Equivalence – metrics | Coverage stats for all timelines | - |
| TC-CTM-08 | Integrate wayback | Integration – wayback | Wayback events added | - |
| TC-WB-01 | Fetch wayback snapshots | Integration – API | Snapshots fetched and integrated | - |
| TC-WB-02 | Wayback with no snapshots | Boundary – empty | Timeline unchanged | - |
| TC-WB-03 | Wayback API error | Abnormal – error | Handles gracefully | - |
| TC-CF-01 | record_first_appeared function | Equivalence – convenience | Timeline created with event | - |
| TC-CF-02 | record_confirmation function | Equivalence – convenience | Confirmation recorded | - |
| TC-CF-03 | record_retraction function | Equivalence – convenience | Retraction recorded | - |
| TC-CF-04 | get_claim_timeline function | Equivalence – convenience | Returns timeline | - |
| TC-CF-05 | get_timeline_coverage function | Equivalence – convenience | Returns coverage stats | - |
| TC-CF-06 | integrate_wayback_into_timeline function | Equivalence – convenience | Wayback integrated | - |
| TC-EC-01 | Timeline with single event | Boundary – single | Valid timeline with span=0 | - |
| TC-EC-02 | Timeline spanning years | Equivalence – long span | Correct span calculation | - |
| TC-EC-03 | Multiple retractions | Abnormal – repeated | Only first retraction counts | - |
| TC-EC-04 | Events out of order | Equivalence – ordering | Events sorted by timestamp | - |
| TC-ET-01 | TimelineEventType values | Equivalence – enum | Correct string values | - |
| TC-RP-01 | Retraction penalty applied | Equivalence – penalty | Confidence reduced by penalty | - |
| TC-RP-02 | Retraction on unconfirmed | Equivalence – unconfirmed | Still marks as retracted | - |
"""

import json

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.filter.claim_timeline import (
    ClaimTimeline,
    ClaimTimelineManager,
    TimelineEvent,
    TimelineEventType,
    get_timeline_manager,
    record_confirmation,
    record_first_appeared,
    record_retraction,
)

# =============================================================================
# TimelineEvent Tests
# =============================================================================


class TestTimelineEvent:
    """Tests for TimelineEvent dataclass."""

    def test_create_event_with_all_fields(self) -> None:
        """Verify TimelineEvent stores all fields correctly."""
        # Given: Timestamp and all event details
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

        # When: Creating TimelineEvent with all fields
        event = TimelineEvent(
            event_type=TimelineEventType.FIRST_APPEARED,
            timestamp=timestamp,
            source_url="https://example.com/article",
            evidence_fragment_id="frag_001",
            wayback_snapshot_url="https://web.archive.org/web/...",
            notes="Initial discovery",
            confidence=0.95,
        )

        # Then: All fields correctly stored
        assert event.event_type == TimelineEventType.FIRST_APPEARED
        assert event.timestamp == timestamp
        assert event.source_url == "https://example.com/article"
        assert event.evidence_fragment_id == "frag_001"
        assert event.wayback_snapshot_url == "https://web.archive.org/web/..."
        assert event.notes == "Initial discovery"
        assert event.confidence == 0.95
        assert len(event.event_id) == 8

    def test_to_dict_serialization(self) -> None:
        """Verify TimelineEvent serializes to dictionary correctly."""
        # Given: TimelineEvent with data
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        event = TimelineEvent(
            event_type=TimelineEventType.CONFIRMED,
            timestamp=timestamp,
            source_url="https://example.com",
            confidence=0.8,
        )

        # When: Serializing to dict
        result = event.to_dict()

        # Then: Dictionary with all fields
        assert result["event_type"] == "confirmed"
        assert result["timestamp"] == "2024-01-15T10:30:00+00:00"
        assert result["source_url"] == "https://example.com"
        assert result["confidence"] == 0.8
        assert "event_id" in result

    def test_from_dict_deserialization(self) -> None:
        """Verify TimelineEvent deserializes from dictionary correctly."""
        # Given: Dictionary with event data
        data = {
            "event_id": "test1234",
            "event_type": "retracted",
            "timestamp": "2024-02-20T14:00:00+00:00",
            "source_url": "https://retraction.example.com",
            "notes": "Claim withdrawn",
            "confidence": 0.9,
        }

        # When: Deserializing from dict
        event = TimelineEvent.from_dict(data)

        # Then: Object correctly populated
        assert event.event_id == "test1234"
        assert event.event_type == TimelineEventType.RETRACTED
        assert event.timestamp.year == 2024
        assert event.timestamp.month == 2
        assert event.timestamp.day == 20
        assert event.source_url == "https://retraction.example.com"
        assert event.notes == "Claim withdrawn"
        assert event.confidence == 0.9

    def test_from_dict_with_missing_fields(self) -> None:
        """Verify TimelineEvent handles missing optional fields gracefully."""
        # Given: Minimal dictionary
        data = {
            "event_type": "updated",
            "source_url": "https://example.com",
        }

        # When: Deserializing from dict
        event = TimelineEvent.from_dict(data)

        # Then: Defaults used for missing fields
        assert event.event_type == TimelineEventType.UPDATED
        assert event.source_url == "https://example.com"
        assert event.evidence_fragment_id is None
        assert event.wayback_snapshot_url is None
        assert event.notes is None
        assert event.confidence == 1.0


# =============================================================================
# ClaimTimeline Tests
# =============================================================================


class TestClaimTimeline:
    """Tests for ClaimTimeline class."""

    def test_create_empty_timeline(self) -> None:
        """Verify empty timeline has correct initial state."""
        # When:
        timeline = ClaimTimeline(claim_id="claim_001")

        # Then:
        assert timeline.claim_id == "claim_001"
        assert len(timeline.events) == 0
        assert timeline.first_appeared is None
        assert timeline.latest_event is None
        assert timeline.is_retracted is False
        assert timeline.is_corrected is False
        assert timeline.confirmation_count == 0
        assert timeline.has_timeline is False

    def test_add_first_appeared_event(self) -> None:
        """Verify first appearance event is added correctly."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_001")
        timestamp = datetime(2024, 1, 15, tzinfo=UTC)

        # When:
        timeline.add_event(
            event_type=TimelineEventType.FIRST_APPEARED,
            timestamp=timestamp,
            source_url="https://source.example.com",
            evidence_fragment_id="frag_001",
        )

        # Then:
        assert len(timeline.events) == 1
        assert timeline.first_appeared is not None
        assert timeline.first_appeared.event_type == TimelineEventType.FIRST_APPEARED
        assert timeline.first_appeared.timestamp == timestamp
        assert timeline.has_timeline is True

    def test_add_multiple_events_sorted_by_timestamp(self) -> None:
        """Verify events are sorted chronologically."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_001")
        ts1 = datetime(2024, 1, 15, tzinfo=UTC)
        ts2 = datetime(2024, 2, 20, tzinfo=UTC)
        ts3 = datetime(2024, 1, 25, tzinfo=UTC)  # Intentionally out of order

        # When:
        timeline.add_event(TimelineEventType.FIRST_APPEARED, ts1, "url1")
        timeline.add_event(TimelineEventType.CONFIRMED, ts2, "url2")
        timeline.add_event(TimelineEventType.UPDATED, ts3, "url3")

        # Then:
        assert len(timeline.events) == 3
        assert timeline.events[0].timestamp == ts1
        assert timeline.events[1].timestamp == ts3
        assert timeline.events[2].timestamp == ts2

    def test_is_retracted_flag(self) -> None:
        """Verify retraction detection works correctly."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_001")

        # Then: initial state
        assert timeline.is_retracted is False

        # When:
        timeline.add_event(
            TimelineEventType.FIRST_APPEARED,
            source_url="https://example.com",
        )
        timeline.add_event(
            TimelineEventType.RETRACTED,
            source_url="https://retraction.example.com",
        )

        # Then: after retraction
        assert timeline.is_retracted is True

    def test_is_corrected_flag(self) -> None:
        """Verify correction detection works correctly."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_001")

        # Then: initial state
        assert timeline.is_corrected is False

        # When:
        timeline.add_event(TimelineEventType.CORRECTED, source_url="url")

        # Then:
        assert timeline.is_corrected is True

    def test_confirmation_count(self) -> None:
        """Verify confirmation counting works correctly."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_001")

        # Then: initial state
        assert timeline.confirmation_count == 0

        # When:
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="url1")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url2")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url3")
        timeline.add_event(TimelineEventType.UPDATED, source_url="url4")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url5")

        # Then:
        assert timeline.confirmation_count == 3

    def test_latest_event(self) -> None:
        """Verify latest event retrieval works correctly."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_001")
        ts1 = datetime(2024, 1, 15, tzinfo=UTC)
        ts2 = datetime(2024, 3, 10, tzinfo=UTC)

        # When:
        timeline.add_event(TimelineEventType.FIRST_APPEARED, ts1, "url1")
        timeline.add_event(TimelineEventType.CONFIRMED, ts2, "url2")

        # Then:
        assert timeline.latest_event is not None
        assert timeline.latest_event.timestamp == ts2
        assert timeline.latest_event.event_type == TimelineEventType.CONFIRMED

    def test_get_events_by_type(self) -> None:
        """Verify filtering events by type works correctly."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_001")
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="url1")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url2")
        timeline.add_event(TimelineEventType.CONFIRMED, source_url="url3")
        timeline.add_event(TimelineEventType.UPDATED, source_url="url4")

        # When:
        confirmations = timeline.get_events_by_type(TimelineEventType.CONFIRMED)

        # Then:
        assert len(confirmations) == 2
        assert all(e.event_type == TimelineEventType.CONFIRMED for e in confirmations)

    def test_get_events_in_range(self) -> None:
        """Verify filtering events by date range works correctly."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_001")
        ts1 = datetime(2024, 1, 15, tzinfo=UTC)
        ts2 = datetime(2024, 2, 20, tzinfo=UTC)
        ts3 = datetime(2024, 3, 25, tzinfo=UTC)

        timeline.add_event(TimelineEventType.FIRST_APPEARED, ts1, "url1")
        timeline.add_event(TimelineEventType.UPDATED, ts2, "url2")
        timeline.add_event(TimelineEventType.CONFIRMED, ts3, "url3")

        # When:
        start = datetime(2024, 2, 1, tzinfo=UTC)
        end = datetime(2024, 3, 1, tzinfo=UTC)
        events_in_range = timeline.get_events_in_range(start, end)

        # Then:
        assert len(events_in_range) == 1
        assert events_in_range[0].timestamp == ts2

    def test_to_dict_serialization(self) -> None:
        """Verify timeline serializes to dictionary correctly."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_001")
        ts = datetime(2024, 1, 15, tzinfo=UTC)
        timeline.add_event(TimelineEventType.FIRST_APPEARED, ts, "https://example.com")

        # When:
        result = timeline.to_dict()

        # Then:
        assert result["claim_id"] == "claim_001"
        assert len(result["events"]) == 1
        assert "summary" in result
        assert result["summary"]["event_count"] == 1
        assert result["summary"]["is_retracted"] is False
        # Per Decision 13: confidence_adjustment is no longer included
        assert "confidence_adjustment" not in result["summary"]

    def test_to_json_serialization(self) -> None:
        """Verify timeline serializes to JSON correctly."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_001")
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="url")

        # When:
        json_str = timeline.to_json()

        # Then:
        data = json.loads(json_str)
        assert data["claim_id"] == "claim_001"
        assert len(data["events"]) == 1

    def test_from_dict_deserialization(self) -> None:
        """Verify timeline deserializes from dictionary correctly."""
        # Given:
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

        # When:
        timeline = ClaimTimeline.from_dict(data)

        # Then:
        assert timeline.claim_id == "claim_002"
        assert len(timeline.events) == 2
        assert timeline.first_appeared is not None
        assert timeline.confirmation_count == 1

    def test_from_json_deserialization(self) -> None:
        """Verify timeline deserializes from JSON correctly."""
        # Given:
        json_str = json.dumps(
            {
                "claim_id": "claim_003",
                "events": [
                    {
                        "event_type": "first_appeared",
                        "timestamp": "2024-01-15T10:00:00+00:00",
                        "source_url": "https://example.com",
                    },
                ],
            }
        )

        # When:
        timeline = ClaimTimeline.from_json(json_str)

        # Then:
        assert timeline is not None
        assert timeline.claim_id == "claim_003"
        assert len(timeline.events) == 1

    def test_from_json_with_invalid_json(self) -> None:
        """Verify from_json returns None for invalid JSON."""
        # Given:
        invalid_json = "not valid json {"

        # When:
        result = ClaimTimeline.from_json(invalid_json)

        # Then:
        assert result is None

    def test_from_json_with_none(self) -> None:
        """Verify from_json returns None for None input."""
        # When:
        result = ClaimTimeline.from_json(None)

        # Then:
        assert result is None


# =============================================================================
# ClaimTimelineManager Tests
# =============================================================================


class TestClaimTimelineManager:
    """Tests for ClaimTimelineManager class."""

    @pytest.fixture
    def manager(self) -> ClaimTimelineManager:
        """Create fresh manager for each test."""
        return ClaimTimelineManager()

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        mock = MagicMock()
        mock.fetch_one = AsyncMock(return_value=None)
        mock.fetch_all = AsyncMock(return_value=[])
        mock.update = AsyncMock(return_value=None)
        return mock

    @pytest.mark.asyncio
    async def test_get_timeline_creates_new_for_nonexistent_claim(
        self, manager: ClaimTimelineManager, mock_db: MagicMock
    ) -> None:
        """Verify get_timeline creates new timeline for non-existent claim."""
        # Given:
        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})

            # When:
            timeline = await manager.get_timeline("claim_new")

            # Then:
            assert timeline is not None
            assert timeline.claim_id == "claim_new"
            assert len(timeline.events) == 0

    @pytest.mark.asyncio
    async def test_get_timeline_loads_existing_from_db(
        self, manager: ClaimTimelineManager, mock_db: MagicMock
    ) -> None:
        """Verify get_timeline loads existing timeline from database."""
        # Given:
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

        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            mock_db.fetch_one = AsyncMock(
                return_value={"timeline_json": json.dumps(existing_timeline)}
            )

            # When:
            timeline = await manager.get_timeline("claim_existing")

            # Then:
            assert timeline is not None
            assert len(timeline.events) == 1
            assert timeline.first_appeared is not None

    @pytest.mark.asyncio
    async def test_get_timeline_uses_cache(
        self, manager: ClaimTimelineManager, mock_db: MagicMock
    ) -> None:
        """Verify get_timeline uses cache for repeated requests."""
        # Given:
        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})

            # First call
            await manager.get_timeline("claim_cached")

            # Reset mock to detect second call
            mock_db.fetch_one.reset_mock()

            # When: - Second call
            timeline = await manager.get_timeline("claim_cached")

            # Then: - Should use cache, not call DB
            mock_db.fetch_one.assert_not_called()
            assert timeline is not None

    @pytest.mark.asyncio
    async def test_save_timeline_updates_database(
        self, manager: ClaimTimelineManager, mock_db: MagicMock
    ) -> None:
        """Verify save_timeline updates database correctly."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_save")
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="url")

        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            # When:
            result = await manager.save_timeline(timeline)

            # Then:
            assert result is True
            mock_db.update.assert_called_once()
            call_args = mock_db.update.call_args
            assert call_args[0][0] == "claims"
            assert "timeline_json" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_add_first_appeared_creates_event(
        self, manager: ClaimTimelineManager, mock_db: MagicMock
    ) -> None:
        """Verify add_first_appeared creates first_appeared event."""
        # Given:
        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})

            # When:
            event = await manager.add_first_appeared(
                claim_id="claim_first",
                source_url="https://first.example.com",
                fragment_id="frag_001",
            )

            # Then:
            assert event is not None
            assert event.event_type == TimelineEventType.FIRST_APPEARED
            assert event.source_url == "https://first.example.com"

    @pytest.mark.asyncio
    async def test_add_first_appeared_skips_if_already_exists(
        self, manager: ClaimTimelineManager, mock_db: MagicMock
    ) -> None:
        """Verify add_first_appeared doesn't duplicate if event exists."""
        # Given:
        existing = {
            "claim_id": "claim_dup",
            "events": [
                {
                    "event_type": "first_appeared",
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "source_url": "https://original.example.com",
                }
            ],
        }

        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": json.dumps(existing)})

            # When:
            event = await manager.add_first_appeared(
                claim_id="claim_dup",
                source_url="https://new.example.com",
            )

            # Then: - Returns existing event, doesn't create new one
            assert event is not None
            assert event.source_url == "https://original.example.com"

    @pytest.mark.asyncio
    async def test_add_confirmation_creates_event(
        self, manager: ClaimTimelineManager, mock_db: MagicMock
    ) -> None:
        """Verify add_confirmation creates confirmation event."""
        # Given:
        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})

            # When:
            event = await manager.add_confirmation(
                claim_id="claim_conf",
                source_url="https://confirm.example.com",
                notes="Confirmed by independent source",
            )

            # Then:
            assert event is not None
            assert event.event_type == TimelineEventType.CONFIRMED
            assert event.notes == "Confirmed by independent source"

    @pytest.mark.asyncio
    async def test_add_retraction_creates_event(
        self, manager: ClaimTimelineManager, mock_db: MagicMock
    ) -> None:
        """Verify add_retraction creates retraction event for audit logging.

        Note: Per Decision 13, retraction events are for audit logging only.
        Confidence is computed solely via Bayesian updating on evidence graph edges.
        """
        # Given:
        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})

            # When:
            event = await manager.add_retraction(
                claim_id="claim_ret",
                source_url="https://retract.example.com",
                notes="Withdrawn due to errors",
            )

            # Then: - Event is created for audit logging
            assert event is not None
            assert event.event_type == TimelineEventType.RETRACTED
            assert event.notes == "Withdrawn due to errors"
            # Note: No confidence adjustment is applied (see Decision 13)

    @pytest.mark.asyncio
    async def test_integrate_wayback_result_adds_events(
        self, manager: ClaimTimelineManager, mock_db: MagicMock
    ) -> None:
        """Verify Wayback results are integrated into timeline."""
        # Given:
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

        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})

            # When:
            events_added = await manager.integrate_wayback_result(
                claim_id="claim_wb",
                source_url="https://source.example.com",
                wayback_result=wayback_result,
            )

            # Then:
            assert events_added == 2  # first_appeared + updated

    @pytest.mark.asyncio
    async def test_get_timeline_coverage_calculates_correctly(
        self, manager: ClaimTimelineManager, mock_db: MagicMock
    ) -> None:
        """Verify timeline coverage metrics are calculated correctly."""
        # Given:
        claims = [
            # Claim with timeline
            {
                "id": "c1",
                "timeline_json": json.dumps(
                    {
                        "claim_id": "c1",
                        "events": [
                            {
                                "event_type": "first_appeared",
                                "timestamp": "2024-01-01T00:00:00+00:00",
                                "source_url": "url1",
                            }
                        ],
                    }
                ),
            },
            # Claim with retraction
            {
                "id": "c2",
                "timeline_json": json.dumps(
                    {
                        "claim_id": "c2",
                        "events": [
                            {
                                "event_type": "retracted",
                                "timestamp": "2024-01-02T00:00:00+00:00",
                                "source_url": "url2",
                            }
                        ],
                    }
                ),
            },
            # Claim without timeline
            {"id": "c3", "timeline_json": None},
        ]

        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            mock_db.fetch_all = AsyncMock(return_value=claims)

            # When:
            coverage = await manager.get_timeline_coverage("task_001")

            # Then:
            assert coverage["total_claims"] == 3
            assert coverage["claims_with_timeline"] == 2
            assert coverage["coverage_rate"] == pytest.approx(2 / 3, abs=0.001)
            assert coverage["claims_retracted"] == 1

    def test_clear_cache(self, manager: ClaimTimelineManager) -> None:
        """Verify cache clearing works."""
        # Given:
        manager._cache["test"] = ClaimTimeline(claim_id="test")

        # When:
        manager.clear_cache()

        # Then:
        assert len(manager._cache) == 0


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_timeline_manager_returns_singleton(self) -> None:
        """Verify get_timeline_manager returns same instance."""
        # When:
        manager1 = get_timeline_manager()
        manager2 = get_timeline_manager()

        # Then:
        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_record_first_appeared_calls_manager(self) -> None:
        """Verify record_first_appeared delegates to manager."""
        # Given:
        mock_db = MagicMock()
        mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})
        mock_db.update = AsyncMock()

        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            # When:
            event = await record_first_appeared(
                claim_id="test_claim",
                source_url="https://example.com",
            )

            # Then:
            assert event is not None
            assert event.event_type == TimelineEventType.FIRST_APPEARED

    @pytest.mark.asyncio
    async def test_record_confirmation_calls_manager(self) -> None:
        """Verify record_confirmation delegates to manager."""
        # Given:
        mock_db = MagicMock()
        mock_db.fetch_one = AsyncMock(return_value={"timeline_json": None})
        mock_db.update = AsyncMock()

        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            # When:
            event = await record_confirmation(
                claim_id="test_claim",
                source_url="https://confirm.example.com",
            )

            # Then:
            assert event is not None
            assert event.event_type == TimelineEventType.CONFIRMED

    @pytest.mark.asyncio
    async def test_record_retraction_calls_manager(self) -> None:
        """Verify record_retraction delegates to manager."""
        # Given:
        mock_db = MagicMock()
        mock_db.fetch_one = AsyncMock(
            side_effect=[
                {"timeline_json": None},
                {"confidence_score": 0.8},
            ]
        )
        mock_db.update = AsyncMock()

        with patch("src.filter.claim_timeline.get_database", new=AsyncMock(return_value=mock_db)):
            # When:
            event = await record_retraction(
                claim_id="test_claim",
                source_url="https://retract.example.com",
                notes="Error found",
            )

            # Then:
            assert event is not None
            assert event.event_type == TimelineEventType.RETRACTED


# =============================================================================
# Edge Cases and Boundary Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_timeline_with_empty_source_url(self) -> None:
        """Verify timeline handles empty source URL."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_empty")

        # When:
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="")

        # Then: - Has event but has_timeline should be False (no valid source)
        assert len(timeline.events) == 1
        assert timeline.has_timeline is False

    def test_timeline_event_with_far_future_date(self) -> None:
        """Verify timeline handles far future dates."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_future")
        future_date = datetime(2099, 12, 31, tzinfo=UTC)

        # When:
        timeline.add_event(TimelineEventType.FIRST_APPEARED, future_date, "url")

        # Then:
        assert timeline.first_appeared is not None
        assert timeline.first_appeared.timestamp.year == 2099

    def test_timeline_event_with_past_date(self) -> None:
        """Verify timeline handles past dates."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_past")
        past_date = datetime(1990, 1, 1, tzinfo=UTC)

        # When:
        timeline.add_event(TimelineEventType.FIRST_APPEARED, past_date, "url")

        # Then:
        assert timeline.first_appeared is not None
        assert timeline.first_appeared.timestamp.year == 1990

    def test_from_dict_with_empty_events(self) -> None:
        """Verify from_dict handles empty events list."""
        # Given:
        data = {"claim_id": "claim_empty", "events": []}

        # When:
        timeline = ClaimTimeline.from_dict(data)

        # Then:
        assert timeline.claim_id == "claim_empty"
        assert len(timeline.events) == 0
        assert timeline.has_timeline is False

    def test_from_dict_with_missing_claim_id(self) -> None:
        """Verify from_dict handles missing claim_id."""
        # Given:
        data: dict[str, object] = {"events": []}

        # When:
        timeline = ClaimTimeline.from_dict(data)

        # Then:
        assert timeline.claim_id == ""

    def test_get_events_in_range_with_no_matches(self) -> None:
        """Verify get_events_in_range returns empty list when no matches."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_range")
        ts = datetime(2024, 6, 15, tzinfo=UTC)
        timeline.add_event(TimelineEventType.FIRST_APPEARED, ts, "url")

        # When: - Query range that doesn't include the event
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 3, 1, tzinfo=UTC)
        result = timeline.get_events_in_range(start, end)

        # Then:
        assert len(result) == 0

    def test_get_events_by_type_with_no_matches(self) -> None:
        """Verify get_events_by_type returns empty list when no matches."""
        # Given:
        timeline = ClaimTimeline(claim_id="claim_type")
        timeline.add_event(TimelineEventType.FIRST_APPEARED, source_url="url")

        # When:
        result = timeline.get_events_by_type(TimelineEventType.RETRACTED)

        # Then:
        assert len(result) == 0
