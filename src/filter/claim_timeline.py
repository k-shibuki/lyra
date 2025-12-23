"""
Claim Timeline for Lyra.

Implements ADR-0005 requirement for claim timeline tracking:
- First appearance / update / correction / retraction / confirmation events
- Integration with Wayback differential exploration
- Timeline coverage metrics

This module provides comprehensive timeline tracking for claims,
enabling audit trails and temporal analysis of information evolution.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from src.storage.database import get_database
from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Timeline event freshness threshold (days)
FRESHNESS_THRESHOLD_DAYS = 365


class TimelineEventType(str, Enum):
    """Types of timeline events (ADR-0005)."""

    FIRST_APPEARED = "first_appeared"  # Initial discovery
    UPDATED = "updated"  # Content modified
    CORRECTED = "corrected"  # Error correction issued
    RETRACTED = "retracted"  # Claim withdrawn
    CONFIRMED = "confirmed"  # Additional supporting evidence
    # ADR-0005: Archive-related events
    CONTENT_MODIFIED = "content_modified"  # Archive differs from current
    CONTENT_MAJOR_CHANGE = "content_major_change"  # Significant archive diff
    ARCHIVE_ONLY = "archive_only"  # Only available in archive


@dataclass
class TimelineEvent:
    """A single event in a claim's timeline.

    Attributes:
        event_type: Type of the event.
        timestamp: When the event occurred.
        source_url: URL where the event was observed.
        evidence_fragment_id: ID of the supporting fragment.
        wayback_snapshot_url: Optional Wayback Machine snapshot URL.
        notes: Optional notes about the event.
        confidence: Confidence in this event (0.0-1.0).
    """

    event_type: TimelineEventType
    timestamp: datetime
    source_url: str
    evidence_fragment_id: str | None = None
    wayback_snapshot_url: str | None = None
    notes: str | None = None
    confidence: float = 1.0
    event_id: str = field(default_factory=lambda: str(uuid4())[:8])

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source_url": self.source_url,
            "evidence_fragment_id": self.evidence_fragment_id,
            "wayback_snapshot_url": self.wayback_snapshot_url,
            "notes": self.notes,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimelineEvent":
        """Create TimelineEvent from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        elif timestamp is None:
            timestamp = datetime.now(UTC)

        return cls(
            event_id=data.get("event_id", str(uuid4())[:8]),
            event_type=TimelineEventType(data.get("event_type", "first_appeared")),
            timestamp=timestamp,
            source_url=data.get("source_url", ""),
            evidence_fragment_id=data.get("evidence_fragment_id"),
            wayback_snapshot_url=data.get("wayback_snapshot_url"),
            notes=data.get("notes"),
            confidence=data.get("confidence", 1.0),
        )


@dataclass
class ClaimTimeline:
    """Timeline of events for a specific claim.

    Tracks the evolution of a claim over time, including:
    - When it first appeared
    - Updates and corrections
    - Retractions
    - Confirmations from other sources
    """

    claim_id: str
    events: list[TimelineEvent] = field(default_factory=list)

    @property
    def first_appeared(self) -> TimelineEvent | None:
        """Get the first appearance event."""
        for event in self.events:
            if event.event_type == TimelineEventType.FIRST_APPEARED:
                return event
        return None

    @property
    def latest_event(self) -> TimelineEvent | None:
        """Get the most recent event."""
        if not self.events:
            return None
        return max(self.events, key=lambda e: e.timestamp)

    @property
    def is_retracted(self) -> bool:
        """Check if the claim has been retracted."""
        return any(e.event_type == TimelineEventType.RETRACTED for e in self.events)

    @property
    def is_corrected(self) -> bool:
        """Check if the claim has been corrected."""
        return any(e.event_type == TimelineEventType.CORRECTED for e in self.events)

    @property
    def confirmation_count(self) -> int:
        """Count the number of confirmations."""
        return sum(1 for e in self.events if e.event_type == TimelineEventType.CONFIRMED)

    @property
    def has_timeline(self) -> bool:
        """Check if this claim has meaningful timeline data.

        A claim has a timeline if it has at least one event
        with a valid timestamp and source.
        """
        return len(self.events) > 0 and any(e.source_url for e in self.events)

    def add_event(
        self,
        event_type: TimelineEventType,
        timestamp: datetime | None = None,
        source_url: str = "",
        evidence_fragment_id: str | None = None,
        wayback_snapshot_url: str | None = None,
        notes: str | None = None,
        confidence: float = 1.0,
    ) -> TimelineEvent:
        """Add an event to the timeline.

        Args:
            event_type: Type of event.
            timestamp: When it occurred (default: now).
            source_url: Source URL.
            evidence_fragment_id: Supporting fragment ID.
            wayback_snapshot_url: Wayback snapshot if applicable.
            notes: Additional notes.
            confidence: Event confidence.

        Returns:
            The created TimelineEvent.
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)

        event = TimelineEvent(
            event_type=event_type,
            timestamp=timestamp,
            source_url=source_url,
            evidence_fragment_id=evidence_fragment_id,
            wayback_snapshot_url=wayback_snapshot_url,
            notes=notes,
            confidence=confidence,
        )

        self.events.append(event)
        self.events.sort(key=lambda e: e.timestamp)

        logger.debug(
            "Timeline event added",
            claim_id=self.claim_id,
            event_type=event_type.value,
            source_url=source_url[:80] if source_url else None,
        )

        return event

    def get_events_by_type(
        self,
        event_type: TimelineEventType,
    ) -> list[TimelineEvent]:
        """Get all events of a specific type.

        Args:
            event_type: Type to filter by.

        Returns:
            List of matching events.
        """
        return [e for e in self.events if e.event_type == event_type]

    def get_events_in_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[TimelineEvent]:
        """Get events within a time range.

        Args:
            start: Start datetime.
            end: End datetime.

        Returns:
            List of events in range.
        """
        return [e for e in self.events if start <= e.timestamp <= end]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Note: Confidence adjustment is no longer calculated here.
        Per ADR-0005, confidence is computed solely via Bayesian updating
        on evidence graph edges (SUPPORTS/REFUTES with nli_confidence).
        Timeline events are for audit logging only.
        """
        return {
            "claim_id": self.claim_id,
            "events": [e.to_dict() for e in self.events],
            "summary": {
                "event_count": len(self.events),
                "first_appeared_at": self.first_appeared.timestamp.isoformat()
                if self.first_appeared
                else None,
                "latest_event_at": self.latest_event.timestamp.isoformat()
                if self.latest_event
                else None,
                "is_retracted": self.is_retracted,
                "is_corrected": self.is_corrected,
                "confirmation_count": self.confirmation_count,
            },
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClaimTimeline":
        """Create ClaimTimeline from dictionary."""
        timeline = cls(claim_id=data.get("claim_id", ""))

        events_data = data.get("events", [])
        for event_data in events_data:
            event = TimelineEvent.from_dict(event_data)
            timeline.events.append(event)

        timeline.events.sort(key=lambda e: e.timestamp)
        return timeline

    @classmethod
    def from_json(cls, json_str: str | None) -> "ClaimTimeline | None":
        """Create ClaimTimeline from JSON string.

        Args:
            json_str: JSON string or None.

        Returns:
            ClaimTimeline or None if parsing fails.
        """
        if not json_str:
            return None

        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse timeline JSON", error=str(e))
            return None


# =============================================================================
# Timeline Manager
# =============================================================================


class ClaimTimelineManager:
    """Manages claim timelines with database persistence.

    Provides:
    - Timeline creation and updates
    - Wayback integration
    - Metrics tracking
    """

    def __init__(self) -> None:
        """Initialize the timeline manager."""
        self._cache: dict[str, ClaimTimeline] = {}

    async def get_timeline(self, claim_id: str) -> ClaimTimeline | None:
        """Get timeline for a claim.

        Args:
            claim_id: Claim ID.

        Returns:
            ClaimTimeline or None if not found.
        """
        # Check cache
        if claim_id in self._cache:
            return self._cache[claim_id]

        # Load from database
        db = await get_database()
        claim = await db.fetch_one(
            "SELECT timeline_json FROM claims WHERE id = ?",
            (claim_id,),
        )

        if claim is None:
            return None

        timeline_json = claim.get("timeline_json")
        if timeline_json:
            timeline = ClaimTimeline.from_json(timeline_json)
            if timeline:
                timeline.claim_id = claim_id
                self._cache[claim_id] = timeline
                return timeline

        # Create new timeline if none exists
        timeline = ClaimTimeline(claim_id=claim_id)
        self._cache[claim_id] = timeline
        return timeline

    async def save_timeline(self, timeline: ClaimTimeline) -> bool:
        """Save timeline to database.

        Args:
            timeline: Timeline to save.

        Returns:
            True if saved successfully.
        """
        db = await get_database()

        try:
            await db.update(
                "claims",
                {"timeline_json": timeline.to_json()},
                "id = ?",
                (timeline.claim_id,),
            )

            self._cache[timeline.claim_id] = timeline

            logger.info(
                "Timeline saved",
                claim_id=timeline.claim_id,
                event_count=len(timeline.events),
            )
            return True

        except Exception as e:
            logger.error("Failed to save timeline", claim_id=timeline.claim_id, error=str(e))
            return False

    async def add_first_appeared(
        self,
        claim_id: str,
        source_url: str,
        timestamp: datetime | None = None,
        fragment_id: str | None = None,
    ) -> TimelineEvent | None:
        """Record first appearance of a claim.

        Args:
            claim_id: Claim ID.
            source_url: Source URL.
            timestamp: When discovered (default: now).
            fragment_id: Source fragment ID.

        Returns:
            Created event or None if failed.
        """
        timeline = await self.get_timeline(claim_id)
        if timeline is None:
            timeline = ClaimTimeline(claim_id=claim_id)

        # Only add if no first_appeared event exists
        if timeline.first_appeared is not None:
            logger.debug("Claim already has first_appeared event", claim_id=claim_id)
            return timeline.first_appeared

        event = timeline.add_event(
            event_type=TimelineEventType.FIRST_APPEARED,
            timestamp=timestamp,
            source_url=source_url,
            evidence_fragment_id=fragment_id,
        )

        await self.save_timeline(timeline)
        return event

    async def add_confirmation(
        self,
        claim_id: str,
        source_url: str,
        timestamp: datetime | None = None,
        fragment_id: str | None = None,
        notes: str | None = None,
    ) -> TimelineEvent | None:
        """Record a confirmation of a claim from another source.

        Args:
            claim_id: Claim ID.
            source_url: Confirming source URL.
            timestamp: When confirmed.
            fragment_id: Source fragment ID.
            notes: Optional notes.

        Returns:
            Created event or None.
        """
        timeline = await self.get_timeline(claim_id)
        if timeline is None:
            timeline = ClaimTimeline(claim_id=claim_id)

        event = timeline.add_event(
            event_type=TimelineEventType.CONFIRMED,
            timestamp=timestamp,
            source_url=source_url,
            evidence_fragment_id=fragment_id,
            notes=notes,
        )

        await self.save_timeline(timeline)
        return event

    async def add_update(
        self,
        claim_id: str,
        source_url: str,
        timestamp: datetime | None = None,
        fragment_id: str | None = None,
        wayback_url: str | None = None,
        notes: str | None = None,
    ) -> TimelineEvent | None:
        """Record an update to a claim.

        Args:
            claim_id: Claim ID.
            source_url: Source URL of the update.
            timestamp: When updated.
            fragment_id: Source fragment ID.
            wayback_url: Wayback snapshot showing the change.
            notes: Description of the update.

        Returns:
            Created event or None.
        """
        timeline = await self.get_timeline(claim_id)
        if timeline is None:
            timeline = ClaimTimeline(claim_id=claim_id)

        event = timeline.add_event(
            event_type=TimelineEventType.UPDATED,
            timestamp=timestamp,
            source_url=source_url,
            evidence_fragment_id=fragment_id,
            wayback_snapshot_url=wayback_url,
            notes=notes,
        )

        await self.save_timeline(timeline)
        return event

    async def add_correction(
        self,
        claim_id: str,
        source_url: str,
        timestamp: datetime | None = None,
        fragment_id: str | None = None,
        wayback_url: str | None = None,
        notes: str | None = None,
    ) -> TimelineEvent | None:
        """Record a correction to a claim.

        Args:
            claim_id: Claim ID.
            source_url: Source URL of the correction.
            timestamp: When corrected.
            fragment_id: Source fragment ID.
            wayback_url: Wayback snapshot.
            notes: Description of the correction.

        Returns:
            Created event or None.
        """
        timeline = await self.get_timeline(claim_id)
        if timeline is None:
            timeline = ClaimTimeline(claim_id=claim_id)

        event = timeline.add_event(
            event_type=TimelineEventType.CORRECTED,
            timestamp=timestamp,
            source_url=source_url,
            evidence_fragment_id=fragment_id,
            wayback_snapshot_url=wayback_url,
            notes=notes,
            confidence=0.8,  # Corrections have slightly lower confidence
        )

        await self.save_timeline(timeline)
        return event

    async def add_retraction(
        self,
        claim_id: str,
        source_url: str,
        timestamp: datetime | None = None,
        fragment_id: str | None = None,
        notes: str | None = None,
    ) -> TimelineEvent | None:
        """Record a retraction of a claim.

        Args:
            claim_id: Claim ID.
            source_url: Source URL of the retraction.
            timestamp: When retracted.
            fragment_id: Source fragment ID.
            notes: Reason for retraction.

        Returns:
            Created event or None.
        """
        timeline = await self.get_timeline(claim_id)
        if timeline is None:
            timeline = ClaimTimeline(claim_id=claim_id)

        event = timeline.add_event(
            event_type=TimelineEventType.RETRACTED,
            timestamp=timestamp,
            source_url=source_url,
            evidence_fragment_id=fragment_id,
            notes=notes,
        )

        await self.save_timeline(timeline)

        # Note: Per ADR-0005, confidence is computed solely via Bayesian updating
        # on evidence graph edges. Retraction events are for audit logging only.
        # To affect confidence, create a REFUTES edge in the evidence graph.

        return event

    async def integrate_wayback_result(
        self,
        claim_id: str,
        source_url: str,
        wayback_result: dict[str, Any],
    ) -> int:
        """Integrate Wayback exploration results into claim timeline.

        Args:
            claim_id: Claim ID.
            source_url: Original source URL.
            wayback_result: Result from WaybackExplorer.

        Returns:
            Number of events added.
        """
        timeline = await self.get_timeline(claim_id)
        if timeline is None:
            timeline = ClaimTimeline(claim_id=claim_id)

        events_added = 0

        # Process timeline entries from Wayback
        timeline_entries = wayback_result.get("timeline", [])

        for entry in timeline_entries:
            timestamp_str = entry.get("timestamp")
            if not timestamp_str:
                continue

            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            snapshot_url = entry.get("snapshot_url", "")
            has_change = entry.get("has_significant_change", False)

            # First entry is the first appearance
            if timeline_entries.index(entry) == 0:
                if timeline.first_appeared is None:
                    timeline.add_event(
                        event_type=TimelineEventType.FIRST_APPEARED,
                        timestamp=timestamp,
                        source_url=source_url,
                        wayback_snapshot_url=snapshot_url,
                    )
                    events_added += 1

            # Significant changes are updates
            elif has_change:
                timeline.add_event(
                    event_type=TimelineEventType.UPDATED,
                    timestamp=timestamp,
                    source_url=source_url,
                    wayback_snapshot_url=snapshot_url,
                    notes="Detected via Wayback Machine analysis",
                )
                events_added += 1

        if events_added > 0:
            await self.save_timeline(timeline)
            logger.info(
                "Wayback results integrated",
                claim_id=claim_id,
                events_added=events_added,
            )

        return events_added

    async def add_archive_diff_event(
        self,
        claim_id: str,
        source_url: str,
        diff_result: dict[str, Any],
        fragment_id: str | None = None,
    ) -> TimelineEvent | None:
        """Add a timeline event from archive diff comparison.

        Per ADR-0005: Records content changes detected between
        archived and current versions.

        Args:
            claim_id: Claim ID.
            source_url: Source URL.
            diff_result: ArchiveDiffResult.to_dict() output.
            fragment_id: Optional fragment ID.

        Returns:
            Created event or None if no significant changes.
        """
        has_changes = diff_result.get("has_significant_changes", False)
        event_type_str = diff_result.get("timeline_event_type", "content_unchanged")

        # Skip if no significant changes
        if event_type_str == "content_unchanged" and not has_changes:
            return None

        timeline = await self.get_timeline(claim_id)
        if timeline is None:
            timeline = ClaimTimeline(claim_id=claim_id)

        # Map event type
        if event_type_str == "content_major_change":
            event_type = TimelineEventType.CONTENT_MAJOR_CHANGE
        elif event_type_str == "content_modified":
            event_type = TimelineEventType.CONTENT_MODIFIED
        else:
            event_type = TimelineEventType.UPDATED

        # Get archive date
        archive_date_str = diff_result.get("archive_date")
        if archive_date_str:
            try:
                datetime.fromisoformat(archive_date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                datetime.now(UTC)
        else:
            datetime.now(UTC)

        # Calculate confidence based on freshness
        freshness_penalty = diff_result.get("freshness_penalty", 0.0)
        adjusted_confidence = diff_result.get("adjusted_confidence", 1.0)

        # Generate notes
        notes = diff_result.get("timeline_notes", "")
        if not notes:
            key_changes = diff_result.get("key_changes", [])
            if key_changes:
                notes = "; ".join(key_changes[:3])

        # Add similarity info to notes
        similarity = diff_result.get("similarity_ratio", 1.0)
        if similarity < 1.0:
            notes = f"Similarity: {similarity:.1%}. {notes}"

        event = timeline.add_event(
            event_type=event_type,
            timestamp=datetime.now(UTC),  # When we detected
            source_url=source_url,
            evidence_fragment_id=fragment_id,
            notes=notes,
            confidence=adjusted_confidence,
        )

        await self.save_timeline(timeline)

        # Note: Per ADR-0005, confidence is computed solely via Bayesian updating
        # on evidence graph edges. Archive diff events are for audit logging only.

        logger.info(
            "Archive diff event added",
            claim_id=claim_id,
            event_type=event_type.value,
            similarity=similarity,
            freshness_penalty=freshness_penalty,
        )

        return event

    async def get_timeline_coverage(self, task_id: str) -> dict[str, Any]:
        """Calculate timeline coverage metrics for a task.

        Args:
            task_id: Task ID.

        Returns:
            Coverage metrics.
        """
        db = await get_database()

        # Get all claims for the task
        claims = await db.fetch_all(
            "SELECT id, timeline_json FROM claims WHERE task_id = ?",
            (task_id,),
        )

        total_claims = len(claims)
        claims_with_timeline = 0
        claims_with_first_appeared = 0
        claims_with_confirmations = 0
        claims_retracted = 0
        claims_corrected = 0
        total_events = 0

        for claim in claims:
            timeline = ClaimTimeline.from_json(claim.get("timeline_json"))
            if timeline and timeline.has_timeline:
                claims_with_timeline += 1
                total_events += len(timeline.events)

                if timeline.first_appeared:
                    claims_with_first_appeared += 1
                if timeline.confirmation_count > 0:
                    claims_with_confirmations += 1
                if timeline.is_retracted:
                    claims_retracted += 1
                if timeline.is_corrected:
                    claims_corrected += 1

        coverage_rate = claims_with_timeline / total_claims if total_claims > 0 else 0.0

        return {
            "task_id": task_id,
            "total_claims": total_claims,
            "claims_with_timeline": claims_with_timeline,
            "coverage_rate": coverage_rate,
            "claims_with_first_appeared": claims_with_first_appeared,
            "claims_with_confirmations": claims_with_confirmations,
            "claims_retracted": claims_retracted,
            "claims_corrected": claims_corrected,
            "total_events": total_events,
            "average_events_per_claim": total_events / claims_with_timeline
            if claims_with_timeline > 0
            else 0.0,
            "meets_target": coverage_rate >= 0.9, # : ≥90%
        }

    def clear_cache(self) -> None:
        """Clear the internal cache."""
        self._cache.clear()


# =============================================================================
# Global Instance
# =============================================================================

_manager: ClaimTimelineManager | None = None


def get_timeline_manager() -> ClaimTimelineManager:
    """Get the global timeline manager instance.

    Returns:
        ClaimTimelineManager instance.
    """
    global _manager
    if _manager is None:
        _manager = ClaimTimelineManager()
    return _manager


# =============================================================================
# Convenience Functions
# =============================================================================


async def record_first_appeared(
    claim_id: str,
    source_url: str,
    timestamp: datetime | None = None,
    fragment_id: str | None = None,
) -> TimelineEvent | None:
    """Record first appearance of a claim.

    Args:
        claim_id: Claim ID.
        source_url: Source URL.
        timestamp: When discovered.
        fragment_id: Source fragment ID.

    Returns:
        Created event or None.
    """
    manager = get_timeline_manager()
    return await manager.add_first_appeared(claim_id, source_url, timestamp, fragment_id)


async def record_confirmation(
    claim_id: str,
    source_url: str,
    timestamp: datetime | None = None,
    fragment_id: str | None = None,
) -> TimelineEvent | None:
    """Record a confirmation of a claim.

    Args:
        claim_id: Claim ID.
        source_url: Confirming source URL.
        timestamp: When confirmed.
        fragment_id: Source fragment ID.

    Returns:
        Created event or None.
    """
    manager = get_timeline_manager()
    return await manager.add_confirmation(claim_id, source_url, timestamp, fragment_id)


async def record_retraction(
    claim_id: str,
    source_url: str,
    timestamp: datetime | None = None,
    notes: str | None = None,
) -> TimelineEvent | None:
    """Record a retraction of a claim.

    Args:
        claim_id: Claim ID.
        source_url: Source URL of retraction.
        timestamp: When retracted.
        notes: Reason for retraction.

    Returns:
        Created event or None.
    """
    manager = get_timeline_manager()
    return await manager.add_retraction(claim_id, source_url, timestamp, notes=notes)


async def get_claim_timeline(claim_id: str) -> ClaimTimeline | None:
    """Get timeline for a claim.

    Args:
        claim_id: Claim ID.

    Returns:
        ClaimTimeline or None.
    """
    manager = get_timeline_manager()
    return await manager.get_timeline(claim_id)


async def get_timeline_coverage(task_id: str) -> dict[str, Any]:
    """Calculate timeline coverage metrics for a task.

    Args:
        task_id: Task ID.

    Returns:
        Coverage metrics dictionary.
    """
    manager = get_timeline_manager()
    return await manager.get_timeline_coverage(task_id)


async def integrate_wayback_into_timeline(
    claim_id: str,
    source_url: str,
    wayback_result: dict[str, Any],
) -> int:
    """Integrate Wayback results into claim timeline.

    Args:
        claim_id: Claim ID.
        source_url: Original source URL.
        wayback_result: Wayback exploration result.

    Returns:
        Number of events added.
    """
    manager = get_timeline_manager()
    return await manager.integrate_wayback_result(claim_id, source_url, wayback_result)
