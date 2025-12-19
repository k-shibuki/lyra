"""
Source Verification Flow.

Implements L6 (Source Verification Flow) per §4.4.1:
- Automatic verification using EvidenceGraph
- Trust level promotion/demotion based on corroboration
- Integration with security detection (L2/L4)

This module handles the "Human in the Loop" verification process
where Cursor AI is informed of verification status to make decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.mcp.response_meta import (
    ClaimMeta,
    ResponseMetaBuilder,
    VerificationDetails,
    VerificationStatus,
)
from src.utils.domain_policy import TrustLevel, get_domain_trust_level
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.filter.evidence_graph import EvidenceGraph

logger = get_logger(__name__)


class PromotionResult(str, Enum):
    """Result of trust level promotion/demotion check."""

    PROMOTED = "promoted"      # Promoted to LOW from UNVERIFIED
    DEMOTED = "demoted"        # Demoted to BLOCKED
    UNCHANGED = "unchanged"    # No change in trust level


@dataclass
class VerificationResult:
    """Result of verifying a claim or source."""

    claim_id: str
    domain: str
    original_trust_level: TrustLevel
    new_trust_level: TrustLevel
    verification_status: VerificationStatus
    promotion_result: PromotionResult
    details: VerificationDetails
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "claim_id": self.claim_id,
            "domain": self.domain,
            "original_trust_level": self.original_trust_level.value,
            "new_trust_level": self.new_trust_level.value,
            "verification_status": self.verification_status.value,
            "promotion_result": self.promotion_result.value,
            "reason": self.reason,
            "details": self.details.to_dict(),
        }


@dataclass
class DomainVerificationState:
    """Tracks verification state for a domain across claims."""

    domain: str
    trust_level: TrustLevel
    verified_claims: list[str] = field(default_factory=list)
    rejected_claims: list[str] = field(default_factory=list)
    pending_claims: list[str] = field(default_factory=list)
    last_updated: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    @property
    def total_claims(self) -> int:
        """Total number of claims from this domain."""
        return len(self.verified_claims) + len(self.rejected_claims) + len(self.pending_claims)

    @property
    def verification_rate(self) -> float:
        """Rate of verified claims (0.0 to 1.0)."""
        if self.total_claims == 0:
            return 0.0
        return len(self.verified_claims) / self.total_claims

    @property
    def rejection_rate(self) -> float:
        """Rate of rejected claims (0.0 to 1.0)."""
        if self.total_claims == 0:
            return 0.0
        return len(self.rejected_claims) / self.total_claims


class SourceVerifier:
    """Verifies sources and manages trust level changes (§4.4.1 L6).

    This class coordinates:
    1. EvidenceGraph queries for claim confidence
    2. Contradiction detection
    3. Trust level promotion/demotion decisions
    4. Metadata generation for Cursor AI
    """

    # Thresholds per §4.4.1 L6
    MIN_INDEPENDENT_SOURCES_FOR_PROMOTION = 2
    MIN_VERIFICATION_RATE_FOR_PROMOTION = 0.5
    MAX_REJECTION_RATE_BEFORE_BLOCK = 0.3

    def __init__(self) -> None:
        """Initialize the source verifier."""
        self._domain_states: dict[str, DomainVerificationState] = {}
        self._blocked_domains: set[str] = set()
        # K.3-8: Pending blocked notifications (processed via send_pending_notifications)
        self._pending_blocked_notifications: list[tuple[str, str, str | None]] = []  # (domain, reason, task_id)

    def verify_claim(
        self,
        claim_id: str,
        domain: str,
        evidence_graph: EvidenceGraph,
        has_dangerous_pattern: bool = False,
    ) -> VerificationResult:
        """Verify a claim using EvidenceGraph.

        Args:
            claim_id: ID of the claim to verify.
            domain: Source domain of the claim.
            evidence_graph: EvidenceGraph instance for querying.
            has_dangerous_pattern: Whether L2/L4 detected dangerous patterns.

        Returns:
            VerificationResult with status and trust level changes.
        """
        # Get current trust level
        original_trust_level = get_domain_trust_level(domain)

        # If already blocked, reject immediately
        if original_trust_level == TrustLevel.BLOCKED or domain in self._blocked_domains:
            return VerificationResult(
                claim_id=claim_id,
                domain=domain,
                original_trust_level=original_trust_level,
                new_trust_level=TrustLevel.BLOCKED,
                verification_status=VerificationStatus.REJECTED,
                promotion_result=PromotionResult.UNCHANGED,
                details=VerificationDetails(),
                reason="Domain is blocked",
            )

        # If dangerous pattern detected, block immediately
        if has_dangerous_pattern:
            self._blocked_domains.add(domain)
            self._update_domain_state(domain, claim_id, VerificationStatus.REJECTED)

            reason = "Dangerous pattern detected (L2/L4)"
            logger.warning(
                "Domain blocked due to dangerous pattern",
                domain=domain,
                claim_id=claim_id,
            )

            # K.3-8: Queue notification for blocked domain
            self._queue_blocked_notification(domain, reason, task_id=None)

            return VerificationResult(
                claim_id=claim_id,
                domain=domain,
                original_trust_level=original_trust_level,
                new_trust_level=TrustLevel.BLOCKED,
                verification_status=VerificationStatus.REJECTED,
                promotion_result=PromotionResult.DEMOTED,
                details=VerificationDetails(),
                reason=reason,
            )

        # Get confidence from EvidenceGraph
        confidence_info = evidence_graph.calculate_claim_confidence(claim_id)

        # Check for contradictions
        contradictions = evidence_graph.find_contradictions()
        claim_contradictions = [
            c for c in contradictions
            if c.get("claim1_id") == claim_id or c.get("claim2_id") == claim_id
        ]

        # Build verification details
        # Extract contradicting claim IDs, filtering out None values
        contradicting_claim_ids = []
        for c in claim_contradictions:
            claim1_id = c.get("claim1_id")
            claim2_id = c.get("claim2_id")
            # Get the "other" claim ID (not the current claim)
            other_id = claim2_id if claim1_id == claim_id else claim1_id
            if other_id is not None:
                contradicting_claim_ids.append(other_id)

        details = VerificationDetails(
            independent_sources=confidence_info.get("independent_sources", 0),
            corroborating_claims=[],  # Would need additional EvidenceGraph query
            contradicting_claims=contradicting_claim_ids,
            nli_scores={
                "supporting": confidence_info.get("supporting_count", 0),
                "refuting": confidence_info.get("refuting_count", 0),
                "neutral": confidence_info.get("neutral_count", 0),
            },
        )

        # Determine verification status
        verification_status, new_trust_level, promotion_result, reason = (
            self._determine_verification_outcome(
                original_trust_level=original_trust_level,
                confidence_info=confidence_info,
                has_contradictions=len(claim_contradictions) > 0,
            )
        )

        # K.3-8: If demoted to BLOCKED via contradictions, queue notification
        if (
            promotion_result == PromotionResult.DEMOTED
            and new_trust_level == TrustLevel.BLOCKED
        ):
            self._blocked_domains.add(domain)
            self._queue_blocked_notification(domain, reason, task_id=None)

        # Update domain state
        self._update_domain_state(domain, claim_id, verification_status)

        # Check if domain should be blocked based on aggregate stats
        # Only auto-block UNVERIFIED or LOW trust domains (not TRUSTED+)
        if verification_status == VerificationStatus.REJECTED:
            domain_state = self._domain_states.get(domain)
            can_auto_block = original_trust_level in (
                TrustLevel.UNVERIFIED,
                TrustLevel.LOW,
            )
            if (
                can_auto_block
                and domain_state
                and domain_state.rejection_rate > self.MAX_REJECTION_RATE_BEFORE_BLOCK
            ):
                self._blocked_domains.add(domain)
                new_trust_level = TrustLevel.BLOCKED
                promotion_result = PromotionResult.DEMOTED
                reason = f"High rejection rate ({domain_state.rejection_rate:.0%})"

                logger.warning(
                    "Domain blocked due to high rejection rate",
                    domain=domain,
                    rejection_rate=domain_state.rejection_rate,
                )

                # K.3-8: Queue notification for blocked domain
                self._queue_blocked_notification(domain, reason, task_id=None)

        return VerificationResult(
            claim_id=claim_id,
            domain=domain,
            original_trust_level=original_trust_level,
            new_trust_level=new_trust_level,
            verification_status=verification_status,
            promotion_result=promotion_result,
            details=details,
            reason=reason,
        )

    def _determine_verification_outcome(
        self,
        original_trust_level: TrustLevel,
        confidence_info: dict[str, Any],
        has_contradictions: bool,
    ) -> tuple[VerificationStatus, TrustLevel, PromotionResult, str]:
        """Determine verification outcome based on evidence.

        Args:
            original_trust_level: Current trust level of domain.
            confidence_info: Confidence assessment from EvidenceGraph.
            has_contradictions: Whether contradictions were found.

        Returns:
            Tuple of (status, new_trust_level, promotion_result, reason).
        """
        independent_sources = confidence_info.get("independent_sources", 0)
        confidence_info.get("verdict", "unverified")
        refuting_count = confidence_info.get("refuting_count", 0)

        # Case 1: Contradiction detected → REJECTED, possibly BLOCKED
        if has_contradictions or refuting_count > 0:
            if original_trust_level == TrustLevel.UNVERIFIED:
                return (
                    VerificationStatus.REJECTED,
                    TrustLevel.BLOCKED,
                    PromotionResult.DEMOTED,
                    "Contradiction detected",
                )
            else:
                # Higher trust levels get rejected but not immediately blocked
                return (
                    VerificationStatus.REJECTED,
                    original_trust_level,
                    PromotionResult.UNCHANGED,
                    "Contradiction detected (trusted source)",
                )

        # Case 2: Well supported → VERIFIED, possibly promoted
        if independent_sources >= self.MIN_INDEPENDENT_SOURCES_FOR_PROMOTION:
            if original_trust_level == TrustLevel.UNVERIFIED:
                return (
                    VerificationStatus.VERIFIED,
                    TrustLevel.LOW,
                    PromotionResult.PROMOTED,
                    f"Corroborated by {independent_sources} independent sources",
                )
            else:
                return (
                    VerificationStatus.VERIFIED,
                    original_trust_level,
                    PromotionResult.UNCHANGED,
                    f"Corroborated by {independent_sources} independent sources",
                )

        # Case 3: Insufficient evidence → PENDING
        return (
            VerificationStatus.PENDING,
            original_trust_level,
            PromotionResult.UNCHANGED,
            f"Insufficient evidence ({independent_sources} sources)",
        )

    def _update_domain_state(
        self,
        domain: str,
        claim_id: str,
        status: VerificationStatus,
    ) -> None:
        """Update domain verification state.

        Args:
            domain: Domain to update.
            claim_id: Claim ID being verified.
            status: Verification status.
        """
        if domain not in self._domain_states:
            self._domain_states[domain] = DomainVerificationState(
                domain=domain,
                trust_level=get_domain_trust_level(domain),
            )

        state = self._domain_states[domain]
        state.last_updated = datetime.now(UTC).isoformat()

        # Remove from pending if present
        if claim_id in state.pending_claims:
            state.pending_claims.remove(claim_id)

        # Add to appropriate list
        if status == VerificationStatus.VERIFIED:
            if claim_id not in state.verified_claims:
                state.verified_claims.append(claim_id)
        elif status == VerificationStatus.REJECTED:
            if claim_id not in state.rejected_claims:
                state.rejected_claims.append(claim_id)
        else:  # PENDING
            if claim_id not in state.pending_claims:
                state.pending_claims.append(claim_id)

    def get_domain_state(self, domain: str) -> DomainVerificationState | None:
        """Get verification state for a domain.

        Args:
            domain: Domain to look up.

        Returns:
            Domain state or None if not tracked.
        """
        return self._domain_states.get(domain)

    def is_domain_blocked(self, domain: str) -> bool:
        """Check if a domain is blocked.

        Args:
            domain: Domain to check.

        Returns:
            True if domain is blocked.
        """
        if domain in self._blocked_domains:
            return True
        return get_domain_trust_level(domain) == TrustLevel.BLOCKED

    def get_blocked_domains(self) -> list[str]:
        """Get list of blocked domains.

        Returns:
            List of blocked domain names.
        """
        return list(self._blocked_domains)

    def _queue_blocked_notification(
        self,
        domain: str,
        reason: str,
        task_id: str | None = None,
    ) -> None:
        """Queue a blocked domain notification (K.3-8).

        Notifications are queued and sent asynchronously via send_pending_notifications().

        Args:
            domain: Domain that was blocked.
            reason: Reason for blocking.
            task_id: Associated task ID (optional).
        """
        # Avoid duplicate notifications for the same domain
        existing_domains = {d for d, _, _ in self._pending_blocked_notifications}
        if domain not in existing_domains:
            self._pending_blocked_notifications.append((domain, reason, task_id))
            logger.debug(
                "Blocked domain notification queued",
                domain=domain,
                reason=reason,
                task_id=task_id,
            )

    async def send_pending_notifications(self, task_id: str | None = None) -> list[dict]:
        """Send pending blocked domain notifications (K.3-8).

        Call this method after batch verification to send notifications.
        The notifications inform Cursor AI that domains have been blocked.

        Args:
            task_id: Override task_id for all notifications (optional).

        Returns:
            List of notification results.
        """
        from src.utils.notification import notify_domain_blocked

        if not self._pending_blocked_notifications:
            return []

        results = []
        notifications_to_send = self._pending_blocked_notifications.copy()
        self._pending_blocked_notifications.clear()

        for domain, reason, queued_task_id in notifications_to_send:
            try:
                result = await notify_domain_blocked(
                    domain=domain,
                    reason=reason,
                    task_id=task_id or queued_task_id,
                )
                results.append(result)
            except Exception as e:
                logger.error(
                    "Failed to send blocked domain notification",
                    domain=domain,
                    error=str(e),
                )
                results.append({
                    "error": str(e),
                    "domain": domain,
                    "reason": reason,
                })

        return results

    def get_pending_notification_count(self) -> int:
        """Get count of pending blocked notifications.

        Returns:
            Number of pending notifications.
        """
        return len(self._pending_blocked_notifications)

    def build_response_meta(
        self,
        verification_results: list[VerificationResult],
    ) -> ResponseMetaBuilder:
        """Build response metadata from verification results.

        Args:
            verification_results: List of verification results.

        Returns:
            ResponseMetaBuilder with claim metadata attached.
        """
        builder = ResponseMetaBuilder()

        has_degraded = False

        for result in verification_results:
            # Add claim metadata
            claim_meta = ClaimMeta(
                claim_id=result.claim_id,
                source_trust_level=result.new_trust_level.value,
                verification_status=result.verification_status,
                verification_details=result.details,
                source_domain=result.domain,
            )
            builder.add_claim_meta(claim_meta)

            # Track blocked/unverified domains
            if result.new_trust_level == TrustLevel.BLOCKED:
                builder.add_blocked_domain(result.domain)
                has_degraded = True
            elif result.new_trust_level == TrustLevel.UNVERIFIED:
                builder.add_unverified_domain(result.domain)

            # Add security warnings for demotions
            if result.promotion_result == PromotionResult.DEMOTED:
                builder.add_security_warning(
                    warning_type="domain_blocked",
                    message=f"Domain {result.domain} blocked: {result.reason}",
                    severity="warning",
                )

        # Set data quality
        if has_degraded:
            builder.set_data_quality("degraded")

        return builder


# Global instance for reuse
_verifier: SourceVerifier | None = None


def get_source_verifier() -> SourceVerifier:
    """Get global source verifier instance.

    Returns:
        SourceVerifier instance.
    """
    global _verifier
    if _verifier is None:
        _verifier = SourceVerifier()
    return _verifier


def reset_source_verifier() -> None:
    """Reset global source verifier (for testing)."""
    global _verifier
    _verifier = None

