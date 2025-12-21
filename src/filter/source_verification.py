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
from src.utils.domain_policy import DomainCategory, get_domain_category
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.filter.evidence_graph import EvidenceGraph

logger = get_logger(__name__)


class PromotionResult(str, Enum):
    """Result of domain category promotion/demotion check."""

    PROMOTED = "promoted"  # Promoted to LOW from UNVERIFIED
    DEMOTED = "demoted"  # Demoted to BLOCKED
    UNCHANGED = "unchanged"  # No change in domain category


class ReasonCode(str, Enum):
    """Factual reason codes for verification outcomes.

    These codes describe evidence state, not interpretation.
    DomainCategory is NOT used in verification decisions.
    """

    CONFLICTING_EVIDENCE = "conflicting_evidence"  # Refuting evidence exists
    WELL_SUPPORTED = "well_supported"  # Multiple independent sources support
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # Not enough evidence
    DANGEROUS_PATTERN = "dangerous_pattern"  # L2/L4 security detection
    ALREADY_BLOCKED = "already_blocked"  # Domain was already blocked


@dataclass
class VerificationResult:
    """Result of verifying a claim or source."""

    claim_id: str
    domain: str
    original_domain_category: DomainCategory
    new_domain_category: DomainCategory
    verification_status: VerificationStatus
    promotion_result: PromotionResult
    details: VerificationDetails
    reason: ReasonCode | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "claim_id": self.claim_id,
            "domain": self.domain,
            "original_domain_category": self.original_domain_category.value,
            "new_domain_category": self.new_domain_category.value,
            "verification_status": self.verification_status.value,
            "promotion_result": self.promotion_result.value,
            "reason": self.reason.value if self.reason else None,
            "details": self.details.to_dict(),
        }


@dataclass
class DomainVerificationState:
    """Tracks verification state for a domain across claims."""

    domain: str
    domain_category: DomainCategory
    verified_claims: list[str] = field(default_factory=list)
    rejected_claims: list[str] = field(default_factory=list)
    pending_claims: list[str] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    # Block information (added for transparency)
    is_blocked: bool = False
    blocked_at: str | None = None
    block_reason: str | None = None
    block_cause_id: str | None = None
    original_domain_category: DomainCategory | None = None

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
        self._pending_blocked_notifications: list[
            tuple[str, str, str | None, str | None]
        ] = []  # (domain, reason, task_id, cause_id)

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
        # Get current domain category
        original_domain_category = get_domain_category(domain)

        # If already blocked, reject immediately
        if original_domain_category == DomainCategory.BLOCKED or domain in self._blocked_domains:
            return VerificationResult(
                claim_id=claim_id,
                domain=domain,
                original_domain_category=original_domain_category,
                new_domain_category=DomainCategory.BLOCKED,
                verification_status=VerificationStatus.REJECTED,
                promotion_result=PromotionResult.UNCHANGED,
                details=VerificationDetails(),
                reason=ReasonCode.ALREADY_BLOCKED,
            )

        # If dangerous pattern detected, block immediately
        if has_dangerous_pattern:
            self._mark_domain_blocked(domain, "Dangerous pattern detected (L2/L4)")
            self._update_domain_state(domain, claim_id, VerificationStatus.REJECTED)

            logger.warning(
                "Domain blocked due to dangerous pattern",
                domain=domain,
                claim_id=claim_id,
            )

            # K.3-8: Queue notification for blocked domain
            self._queue_blocked_notification(
                domain, "Dangerous pattern detected (L2/L4)", task_id=None
            )

            return VerificationResult(
                claim_id=claim_id,
                domain=domain,
                original_domain_category=original_domain_category,
                new_domain_category=DomainCategory.BLOCKED,
                verification_status=VerificationStatus.REJECTED,
                promotion_result=PromotionResult.DEMOTED,
                details=VerificationDetails(),
                reason=ReasonCode.DANGEROUS_PATTERN,
            )

        # Get confidence from EvidenceGraph
        confidence_info = evidence_graph.calculate_claim_confidence(claim_id)

        details = VerificationDetails(
            independent_sources=confidence_info.get("independent_sources", 0),
            corroborating_claims=[],  # Would need additional EvidenceGraph query
            # Single-user refactor: treat "contradiction" as "refuting evidence exists".
            # We do not attempt to infer "contradicting_claims" (claim-vs-claim pairs)
            # from fragment-based evidence.
            contradicting_claims=[],
            nli_scores={
                "supporting": confidence_info.get("supporting_count", 0),
                "refuting": confidence_info.get("refuting_count", 0),
                "neutral": confidence_info.get("neutral_count", 0),
            },
        )

        # Determine verification status (evidence only, no DomainCategory dependency)
        verification_status, new_domain_category, promotion_result, reason_code = (
            self._determine_verification_outcome(
                original_domain_category=original_domain_category,
                confidence_info=confidence_info,
            )
        )

        # Update domain state
        self._update_domain_state(domain, claim_id, verification_status)

        # Check if domain should be blocked based on aggregate stats
        # Only auto-block after repeated rejections (at least 3 rejected claims with high rejection rate).
        # Single contradictions are NOT sufficient for blocking.
        if verification_status == VerificationStatus.REJECTED:
            domain_state = self._domain_states.get(domain)
            can_auto_block = original_domain_category in (
                DomainCategory.UNVERIFIED,
                DomainCategory.LOW,
            )
            # Require at least 3 rejected claims before auto-blocking
            min_rejections_for_block = 3
            if (
                can_auto_block
                and domain_state
                and len(domain_state.rejected_claims) >= min_rejections_for_block
                and domain_state.rejection_rate > self.MAX_REJECTION_RATE_BEFORE_BLOCK
            ):
                self._mark_domain_blocked(
                    domain,
                    f"High rejection rate ({domain_state.rejection_rate:.0%}) with {len(domain_state.rejected_claims)} rejections",
                )
                new_domain_category = DomainCategory.BLOCKED
                promotion_result = PromotionResult.DEMOTED
                reason_code = ReasonCode.DANGEROUS_PATTERN  # Repeated rejections = pattern

                logger.warning(
                    "Domain blocked due to high rejection rate",
                    domain=domain,
                    rejection_rate=domain_state.rejection_rate,
                    rejected_count=len(domain_state.rejected_claims),
                )

                # K.3-8: Queue notification for blocked domain
                self._queue_blocked_notification(
                    domain,
                    f"High rejection rate ({domain_state.rejection_rate:.0%})",
                    task_id=None,
                )

        return VerificationResult(
            claim_id=claim_id,
            domain=domain,
            original_domain_category=original_domain_category,
            new_domain_category=new_domain_category,
            verification_status=verification_status,
            promotion_result=promotion_result,
            details=details,
            reason=reason_code,
        )

    def _determine_verification_outcome(
        self,
        original_domain_category: DomainCategory,
        confidence_info: dict[str, Any],
    ) -> tuple[VerificationStatus, DomainCategory, PromotionResult, ReasonCode]:
        """Determine verification outcome based on evidence only.

        DomainCategory is NOT used in verification decisions.
        Only evidence (NLI confidence, independent sources) is considered.

        Args:
            original_domain_category: Current domain category (for tracking only).
            confidence_info: Confidence assessment from EvidenceGraph.
        Returns:
            Tuple of (status, new_domain_category, promotion_result, reason_code).
        """
        independent_sources = confidence_info.get("independent_sources", 0)
        refuting_count = confidence_info.get("refuting_count", 0)

        # Case 1: Conflicting evidence → PENDING (no automatic BLOCKED)
        # DomainCategory is recorded on edges for high-inference AI to interpret
        if refuting_count > 0:
            # Keep original category, return PENDING for AI evaluation
            return (
                VerificationStatus.PENDING,
                original_domain_category,
                PromotionResult.UNCHANGED,
                ReasonCode.CONFLICTING_EVIDENCE,
            )

        # Case 2: Well supported → VERIFIED, possibly promoted
        if independent_sources >= self.MIN_INDEPENDENT_SOURCES_FOR_PROMOTION:
            if original_domain_category == DomainCategory.UNVERIFIED:
                return (
                    VerificationStatus.VERIFIED,
                    DomainCategory.LOW,
                    PromotionResult.PROMOTED,
                    ReasonCode.WELL_SUPPORTED,
                )
            else:
                return (
                    VerificationStatus.VERIFIED,
                    original_domain_category,
                    PromotionResult.UNCHANGED,
                    ReasonCode.WELL_SUPPORTED,
                )

        # Case 3: Insufficient evidence → PENDING
        return (
            VerificationStatus.PENDING,
            original_domain_category,
            PromotionResult.UNCHANGED,
            ReasonCode.INSUFFICIENT_EVIDENCE,
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
                domain_category=get_domain_category(domain),
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
        return get_domain_category(domain) == DomainCategory.BLOCKED

    def get_blocked_domains(self) -> list[str]:
        """Get list of blocked domains.

        Returns:
            List of blocked domain names.
        """
        return list(self._blocked_domains)

    def get_blocked_domains_info(self) -> list[dict[str, Any]]:
        """Get structured info about blocked domains for get_status response.

        Returns:
            List of blocked domain info dicts with:
            - domain: Domain name
            - blocked_at: ISO timestamp when blocked
            - reason: Reason for blocking
            - cause_id: Causal trace ID (if available)
            - original_domain_category: Domain category before blocking
            - can_restore: Whether domain can be manually restored
            - restore_via: How to restore (config file path)
        """
        result = []
        for domain in self._blocked_domains:
            state = self._domain_states.get(domain)
            if state and state.is_blocked:
                result.append(
                    {
                        "domain": domain,
                        "blocked_at": state.blocked_at,
                        "reason": state.block_reason,
                        "cause_id": state.block_cause_id,
                        "original_domain_category": (
                            state.original_domain_category.value
                            if state.original_domain_category
                            else None
                        ),
                        "can_restore": True,
                        "restore_via": "config/domains.yaml user_overrides",
                    }
                )
            else:
                # Domain is blocked but no detailed state available
                result.append(
                    {
                        "domain": domain,
                        "blocked_at": None,
                        "reason": "Domain is blocked",
                        "cause_id": None,
                        "original_domain_category": None,
                        "can_restore": True,
                        "restore_via": "config/domains.yaml user_overrides",
                    }
                )
        return result

    def _mark_domain_blocked(
        self,
        domain: str,
        reason: str,
        cause_id: str | None = None,
    ) -> None:
        """Mark a domain as blocked and record state.

        Args:
            domain: Domain to block.
            reason: Reason for blocking.
            cause_id: Causal trace ID (optional).
        """
        self._blocked_domains.add(domain)

        # Ensure domain state exists
        if domain not in self._domain_states:
            self._domain_states[domain] = DomainVerificationState(
                domain=domain,
                domain_category=get_domain_category(domain),
            )

        state = self._domain_states[domain]
        state.original_domain_category = state.domain_category
        state.domain_category = DomainCategory.BLOCKED
        state.is_blocked = True
        state.blocked_at = datetime.now(UTC).isoformat()
        state.block_reason = reason
        state.block_cause_id = cause_id

    def _queue_blocked_notification(
        self,
        domain: str,
        reason: str,
        task_id: str | None = None,
        cause_id: str | None = None,
    ) -> None:
        """Queue a blocked domain notification (K.3-8).

        Notifications are queued and sent asynchronously via send_pending_notifications().

        Args:
            domain: Domain that was blocked.
            reason: Reason for blocking.
            task_id: Associated task ID (optional).
            cause_id: Causal trace ID for log correlation (optional).
        """
        # Avoid duplicate notifications for the same domain
        existing_domains = {d for d, _, _, _ in self._pending_blocked_notifications}
        if domain not in existing_domains:
            self._pending_blocked_notifications.append((domain, reason, task_id, cause_id))
            logger.warning(
                "Domain blocked",
                domain=domain,
                reason=reason,
                task_id=task_id,
                cause_id=cause_id,
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

        for domain, reason, queued_task_id, cause_id in notifications_to_send:
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
                    cause_id=cause_id,
                )
                results.append(
                    {
                        "error": str(e),
                        "domain": domain,
                        "reason": reason,
                        "cause_id": cause_id,
                    }
                )

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
                source_domain_category=result.new_domain_category.value,
                verification_status=result.verification_status,
                verification_details=result.details,
                source_domain=result.domain,
            )
            builder.add_claim_meta(claim_meta)

            # Track blocked/unverified domains
            if result.new_domain_category == DomainCategory.BLOCKED:
                builder.add_blocked_domain(result.domain)
                has_degraded = True
            elif result.new_domain_category == DomainCategory.UNVERIFIED:
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
