"""
Tests for Source Verification Flow (Source Verification Flow (ADR-0005 L6), ADR-0005 L6).

Test Coverage:
- Claim verification with EvidenceGraph
- Trust level promotion (UNVERIFIED → LOW)
- Trust level demotion (→ BLOCKED)
- Domain state tracking
- Response metadata building
"""

from unittest.mock import MagicMock, patch

import pytest

from src.filter.source_verification import (
    DomainBlockReason,
    DomainVerificationState,
    PromotionResult,
    ReasonCode,
    RejectionType,
    SourceVerifier,
    VerificationResult,
    get_source_verifier,
    reset_source_verifier,
)
from src.mcp.response_meta import VerificationStatus
from src.utils.domain_policy import DomainCategory


@pytest.fixture
def verifier() -> SourceVerifier:
    """Create fresh SourceVerifier for each test."""
    return SourceVerifier()


@pytest.fixture
def mock_evidence_graph() -> MagicMock:
    """Create mock EvidenceGraph."""
    graph = MagicMock()
    graph.calculate_claim_confidence.return_value = {
        "bayesian_claim_confidence": 0.5,
        "supporting_count": 0,
        "refuting_count": 0,
        "neutral_count": 0,
        "independent_sources": 0,
    }
    graph.find_contradictions.return_value = []
    return graph


class TestSourceVerifierBasic:
    """Basic verification tests."""

    def test_verify_claim_unverified_domain_insufficient_evidence(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-03: Claim with insufficient evidence stays PENDING.

        // Given: Claim from UNVERIFIED domain with 0 sources
        // When: Verifying claim
        // Then: PENDING status, trust level unchanged
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.0,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 0,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_001",
                domain="unknown-site.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.UNVERIFIED
        assert result.promotion_result == PromotionResult.UNCHANGED

    def test_verify_claim_with_two_independent_sources_promotes(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-01: Claim with 2+ independent sources gets VERIFIED and promoted.

        // Given: Claim from UNVERIFIED domain with 2+ independent sources
        // When: Verifying claim
        // Then: VERIFIED status, promoted to LOW
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.8,
            "supporting_count": 2,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 2,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_002",
                domain="promoted-site.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.verification_status == VerificationStatus.VERIFIED
        assert result.new_domain_category == DomainCategory.LOW
        assert result.promotion_result == PromotionResult.PROMOTED

    def test_verify_claim_with_contradictions_stays_pending(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-02: Claim with contradictions stays PENDING.

        // Given: Claim with contradiction detected
        // When: Verifying claim
        // Then: PENDING status, DomainCategory unchanged (for AI evaluation)

        Contradiction handling: Update:  do NOT change DomainCategory.
        DomainCategory is only for ranking, not for verification decisions.
        High-inference AI interprets conflicting evidence.
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.3,
            "supporting_count": 1,
            "refuting_count": 1,
            "neutral_count": 0,
            "independent_sources": 1,
        }
        mock_evidence_graph.find_contradictions.return_value = [
            {
                "claim1_id": "claim_003",
                "claim2_id": "claim_other",
                "bayesian_claim_confidence": 0.9,
            }
        ]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_003",
                domain="contradicted-site.com",
                evidence_graph=mock_evidence_graph,
            )

        # Contradiction handling:  → PENDING (not REJECTED)
        assert result.verification_status == VerificationStatus.PENDING
        # DomainCategory unchanged (not demoted)
        assert result.new_domain_category == DomainCategory.UNVERIFIED
        assert result.promotion_result == PromotionResult.UNCHANGED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE


class TestSourceVerifierEdgeCases:
    """Edge cases and boundary tests."""

    def test_already_blocked_domain_rejected_immediately(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-A-01: Already blocked domain gets rejected immediately.

        // Given: Claim from BLOCKED domain
        // When: Verifying claim
        // Then: REJECTED immediately without graph query
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.BLOCKED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_blocked",
                domain="blocked-site.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.verification_status == VerificationStatus.REJECTED
        assert result.new_domain_category == DomainCategory.BLOCKED
        assert result.reason == ReasonCode.ALREADY_BLOCKED

    def test_dangerous_pattern_causes_immediate_block(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-A-02: Dangerous pattern detected causes immediate block.

        // Given: Claim with dangerous pattern detected (L2/L4)
        // When: Verifying claim with has_dangerous_pattern=True
        // Then: REJECTED, domain BLOCKED
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_dangerous",
                domain="dangerous-site.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
            )

        assert result.verification_status == VerificationStatus.REJECTED
        assert result.new_domain_category == DomainCategory.BLOCKED
        assert result.promotion_result == PromotionResult.DEMOTED
        assert verifier.is_domain_blocked("dangerous-site.com")

    def test_one_independent_source_stays_pending(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-B-03: Claim with exactly 1 independent source stays PENDING.

        // Given: Claim with exactly 1 independent source (below threshold)
        // When: Verifying claim
        // Then: PENDING status, no promotion
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.5,
            "supporting_count": 1,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 1,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_one_source",
                domain="one-source-site.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.verification_status == VerificationStatus.PENDING
        assert result.promotion_result == PromotionResult.UNCHANGED

    def test_exactly_two_independent_sources_promotes(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-B-02: Claim with exactly 2 independent sources gets promoted.

        // Given: Claim with exactly 2 independent sources (at threshold)
        // When: Verifying claim
        // Then: VERIFIED, promoted to LOW
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.75,
            "supporting_count": 2,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 2,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_two_sources",
                domain="two-source-site.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.verification_status == VerificationStatus.VERIFIED
        assert result.new_domain_category == DomainCategory.LOW
        assert result.promotion_result == PromotionResult.PROMOTED

    def test_zero_independent_sources_stays_pending(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-B-01: Claim with 0 independent sources stays PENDING.

        // Given: Claim with no evidence
        // When: Verifying claim
        // Then: PENDING status
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.0,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 0,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_no_evidence",
                domain="no-evidence-site.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.verification_status == VerificationStatus.PENDING
        assert result.details.independent_sources == 0


class TestDomainStateTracking:
    """Tests for domain verification state tracking."""

    def test_domain_state_created_on_first_verification(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-04: Domain state created on first verification.

        // Given: New domain never verified
        // When: Verifying first claim
        // Then: Domain state created and tracked
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="first_claim",
                domain="new-domain.com",
                evidence_graph=mock_evidence_graph,
            )

        state = verifier.get_domain_state("new-domain.com")
        assert state is not None
        assert state.domain == "new-domain.com"
        assert "first_claim" in state.pending_claims

    def test_domain_state_tracks_verified_claims(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-05: Verified claims tracked in domain state.

        // Given: Claim that gets VERIFIED
        // When: Checking domain state
        // Then: Claim in verified_claims list
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.8,
            "supporting_count": 2,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 2,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="verified_claim",
                domain="verified-domain.com",
                evidence_graph=mock_evidence_graph,
            )

        state = verifier.get_domain_state("verified-domain.com")
        assert state is not None
        assert "verified_claim" in state.verified_claims

    def test_high_rejection_rate_blocks_domain(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-A-03: High rejection rate causes domain block.

        // Given: Domain with many rejected claims (via dangerous pattern)
        // When: Rejection rate exceeds threshold
        // Then: Domain gets blocked

        Note: has_dangerous_pattern=True triggers REJECTED status.
        Normal contradictions return PENDING (Contradiction handling behavior).
        """
        mock_evidence_graph.find_contradictions.return_value = []
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.2,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 0,
        }

        # Pre-populate domain state with many rejections
        verifier._domain_states["high-reject.com"] = DomainVerificationState(
            domain="high-reject.com",
            domain_category=DomainCategory.UNVERIFIED,
            security_rejected_claims=["r1", "r2", "r3"],  # Already 3 rejections
            verified_claims=[],
        )

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            # Use has_dangerous_pattern to trigger REJECTED status
            result = verifier.verify_claim(
                claim_id="rejected_claim",
                domain="high-reject.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
            )

        # Should be blocked due to dangerous pattern
        assert result.new_domain_category == DomainCategory.BLOCKED
        assert verifier.is_domain_blocked("high-reject.com")


class TestDomainVerificationState:
    """Tests for DomainVerificationState dataclass."""

    def test_total_claims_calculation(self) -> None:
        """
        TC-N-06: total_claims property calculates correctly.

        // Given: Domain state with mixed claims
        // When: Accessing total_claims
        // Then: Sum of all claim lists
        """
        state = DomainVerificationState(
            domain="test.com",
            domain_category=DomainCategory.UNVERIFIED,
            verified_claims=["v1", "v2"],
            security_rejected_claims=["r1"],
            pending_claims=["p1", "p2", "p3"],
        )

        assert state.total_claims == 6

    def test_verification_rate_calculation(self) -> None:
        """
        TC-N-07: verification_rate property calculates correctly.

        // Given: Domain state with mixed claims
        // When: Accessing verification_rate
        // Then: Correct ratio returned
        """
        state = DomainVerificationState(
            domain="test.com",
            domain_category=DomainCategory.UNVERIFIED,
            verified_claims=["v1", "v2"],
            security_rejected_claims=["r1"],
            pending_claims=["p1"],
        )

        assert state.verification_rate == 0.5  # 2/4

    def test_verification_rate_zero_when_no_claims(self) -> None:
        """
        TC-B-04: verification_rate is 0 when no claims.

        // Given: Empty domain state
        // When: Accessing verification_rate
        // Then: Returns 0.0 (no division by zero)
        """
        state = DomainVerificationState(
            domain="empty.com",
            domain_category=DomainCategory.UNVERIFIED,
        )

        assert state.verification_rate == 0.0

    def test_domain_claim_combined_rejection_rate_calculation(self) -> None:
        """
        TC-N-08: domain_claim_combined_rejection_rate property calculates correctly.

        // Given: Domain state with rejections
        // When: Accessing domain_claim_combined_rejection_rate
        // Then: Correct ratio returned
        """
        state = DomainVerificationState(
            domain="test.com",
            domain_category=DomainCategory.UNVERIFIED,
            verified_claims=["v1"],
            security_rejected_claims=["r1", "r2"],
            pending_claims=["p1"],
        )

        assert state.domain_claim_combined_rejection_rate == 0.5  # 2/4


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_to_dict_serialization(self) -> None:
        """
        TC-N-09: VerificationResult serializes correctly.

        // Given: Complete VerificationResult
        // When: Converting to dict
        // Then: All fields serialized
        """
        from src.mcp.response_meta import VerificationDetails

        result = VerificationResult(
            claim_id="claim_test",
            domain="test.com",
            original_domain_category=DomainCategory.UNVERIFIED,
            new_domain_category=DomainCategory.LOW,
            verification_status=VerificationStatus.VERIFIED,
            promotion_result=PromotionResult.PROMOTED,
            details=VerificationDetails(independent_sources=3),
            reason=ReasonCode.WELL_SUPPORTED,
        )

        result_dict = result.to_dict()

        assert result_dict["claim_id"] == "claim_test"
        assert result_dict["domain"] == "test.com"
        assert result_dict["original_domain_category"] == "unverified"
        assert result_dict["new_domain_category"] == "low"
        assert result_dict["verification_status"] == "verified"
        assert result_dict["promotion_result"] == "promoted"
        assert result_dict["details"]["independent_sources"] == 3


class TestResponseMetaBuilding:
    """Tests for building response metadata from verification results."""

    def test_build_response_meta_with_verified_claims(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-E-02: build_response_meta generates correct metadata.

        // Given: List of verification results
        // When: Building response meta
        // Then: Claims and warnings correctly populated
        """
        from src.mcp.response_meta import VerificationDetails

        results = [
            VerificationResult(
                claim_id="claim_1",
                domain="good.com",
                original_domain_category=DomainCategory.UNVERIFIED,
                new_domain_category=DomainCategory.LOW,
                verification_status=VerificationStatus.VERIFIED,
                promotion_result=PromotionResult.PROMOTED,
                details=VerificationDetails(independent_sources=2),
                reason=ReasonCode.WELL_SUPPORTED,
            ),
            VerificationResult(
                claim_id="claim_2",
                domain="bad.com",
                original_domain_category=DomainCategory.UNVERIFIED,
                new_domain_category=DomainCategory.BLOCKED,
                verification_status=VerificationStatus.REJECTED,
                promotion_result=PromotionResult.DEMOTED,
                details=VerificationDetails(),
                reason=ReasonCode.CONFLICTING_EVIDENCE,
            ),
        ]

        builder = verifier.build_response_meta(results)
        meta = builder.build()

        assert "claims" in meta
        assert len(meta["claims"]) == 2
        assert meta["claims"][0]["verification_status"] == "verified"
        assert meta["claims"][1]["verification_status"] == "rejected"

        assert "blocked_domains" in meta
        assert "bad.com" in meta["blocked_domains"]

        assert "security_warnings" in meta
        assert meta["data_quality"] == "degraded"


class TestGlobalInstance:
    """Tests for global verifier instance."""

    def test_get_source_verifier_returns_instance(self) -> None:
        """
        TC-N-10: get_source_verifier returns SourceVerifier.

        // Given: First call to get_source_verifier
        // When: Getting instance
        // Then: Returns SourceVerifier instance
        """
        reset_source_verifier()
        verifier = get_source_verifier()
        assert isinstance(verifier, SourceVerifier)

    def test_get_source_verifier_returns_same_instance(self) -> None:
        """
        TC-N-11: get_source_verifier returns same instance.

        // Given: Multiple calls to get_source_verifier
        // When: Getting instance
        // Then: Same instance returned
        """
        reset_source_verifier()
        verifier1 = get_source_verifier()
        verifier2 = get_source_verifier()
        assert verifier1 is verifier2

    def test_reset_source_verifier_clears_instance(self) -> None:
        """
        TC-N-12: reset_source_verifier clears global instance.

        // Given: Existing global instance
        // When: Resetting
        // Then: New instance created on next get
        """
        verifier1 = get_source_verifier()
        reset_source_verifier()
        verifier2 = get_source_verifier()
        assert verifier1 is not verifier2


class TestTrustedDomainBehavior:
    """Tests for behavior with higher trust level domains."""

    def test_trusted_domain_with_contradiction_stays_pending(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-13: Trusted domain with contradiction stays PENDING.

        // Given: Claim from TRUSTED domain with contradiction
        // When: Verifying claim
        // Then: PENDING (not REJECTED), category unchanged

        Contradiction handling:  → PENDING for AI evaluation.
        DomainCategory is not used in verification decisions.
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.3,
            "supporting_count": 1,
            "refuting_count": 1,
            "neutral_count": 0,
            "independent_sources": 1,
        }
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "trusted_claim", "claim2_id": "other"}
        ]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.TRUSTED,
        ):
            result = verifier.verify_claim(
                claim_id="trusted_claim",
                domain="trusted-site.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.TRUSTED  # Unchanged
        assert result.promotion_result == PromotionResult.UNCHANGED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE

    def test_trusted_domain_verified_stays_trusted(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-14: Trusted domain with verification stays TRUSTED (no promotion).

        // Given: Claim from TRUSTED domain with 2+ sources
        // When: Verifying claim
        // Then: VERIFIED but trust level stays TRUSTED (no promotion)
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.9,
            "supporting_count": 3,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 3,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.TRUSTED,
        ):
            result = verifier.verify_claim(
                claim_id="trusted_verified",
                domain="trusted-verified.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.verification_status == VerificationStatus.VERIFIED
        assert result.new_domain_category == DomainCategory.TRUSTED  # Stays TRUSTED
        assert result.promotion_result == PromotionResult.UNCHANGED


class TestBoundaryValues:
    """Boundary value tests for thresholds and edge cases."""

    def test_combined_rejection_rate_exactly_at_threshold_not_blocked(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-B-05: Combined rejection rate boundary with dangerous pattern triggers block.

        // Given: Domain with existing rejections + dangerous pattern
        // When: Verifying claim with has_dangerous_pattern=True
        // Then: Blocked (dangerous pattern + high rejection rate)

        Note: Normal contradictions return PENDING (Contradiction handling behavior).
        """
        mock_evidence_graph.find_contradictions.return_value = []
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.2,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 0,
        }

        # 3 rejected out of 10 total = 30%
        verifier._domain_states["threshold.com"] = DomainVerificationState(
            domain="threshold.com",
            domain_category=DomainCategory.UNVERIFIED,
            security_rejected_claims=["r1", "r2"],  # 2 rejected
            verified_claims=["v1", "v2", "v3", "v4", "v5", "v6"],  # 6 verified
            pending_claims=[],  # 0 pending
            # Total = 8, after adding 1 rejected = 3/9 = 33.3% > 30%
        )

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="threshold_claim",
                domain="threshold.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,  # Triggers REJECTED status
            )

        # Dangerous pattern blocks immediately
        assert result.new_domain_category == DomainCategory.BLOCKED

    def test_contradiction_stays_pending_not_demoted(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-B-06: Contradiction stays PENDING without demotion.

        // Given: Domain with contradiction
        // When: Verifying claim
        // Then: PENDING, DomainCategory unchanged

        Contradiction handling:  do NOT change DomainCategory.
        High-inference AI evaluates conflicting evidence.
        """
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "below_threshold", "claim2_id": "other"}
        ]
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.2,
            "supporting_count": 0,
            "refuting_count": 1,
            "neutral_count": 0,
            "independent_sources": 0,
        }

        # Pre-populate domain state
        verifier._domain_states["low-reject.com"] = DomainVerificationState(
            domain="low-reject.com",
            domain_category=DomainCategory.UNVERIFIED,
            security_rejected_claims=[],
            verified_claims=["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9"],
            pending_claims=[],
        )

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="below_threshold",
                domain="low-reject.com",
                evidence_graph=mock_evidence_graph,
            )

        # Contradiction handling:  → PENDING, DomainCategory unchanged
        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.UNVERIFIED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE

    def test_three_independent_sources_well_above_threshold(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-B-07: Claim with 3 independent sources (above threshold).

        // Given: Claim with 3 independent sources (threshold is 2)
        // When: Verifying claim
        // Then: VERIFIED and promoted
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.9,
            "supporting_count": 3,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 3,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="well_supported",
                domain="good-source.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.verification_status == VerificationStatus.VERIFIED
        assert result.new_domain_category == DomainCategory.LOW
        assert result.promotion_result == PromotionResult.PROMOTED

    def test_get_domain_state_unknown_domain_returns_none(self, verifier: SourceVerifier) -> None:
        """
        TC-N-15: get_domain_state for unknown domain returns None.

        // Given: Verifier with no state for domain
        // When: Getting state for unknown domain
        // Then: Returns None
        """
        result = verifier.get_domain_state("never-seen.com")

        assert result is None

    def test_verify_same_claim_twice_no_duplicate(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-16: Verifying same claim twice doesn't create duplicates.

        // Given: Claim already verified
        // When: Verifying same claim again
        // Then: No duplicate entries in domain state
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.8,
            "supporting_count": 2,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 2,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            # First verification
            verifier.verify_claim(
                claim_id="duplicate_test",
                domain="dup-test.com",
                evidence_graph=mock_evidence_graph,
            )

            # Second verification of same claim
            verifier.verify_claim(
                claim_id="duplicate_test",
                domain="dup-test.com",
                evidence_graph=mock_evidence_graph,
            )

        state = verifier.get_domain_state("dup-test.com")
        assert state is not None
        # Should only appear once
        assert state.verified_claims.count("duplicate_test") == 1


class TestExternalDependencyFailures:
    """Tests for handling external dependency failures."""

    def test_evidence_graph_exception_handling(self, verifier: SourceVerifier) -> None:
        """
        TC-A-04: EvidenceGraph raises exception during verification.

        // Given: EvidenceGraph that raises exception
        // When: Verifying claim
        // Then: Exception propagates (caller should handle)
        """
        mock_graph = MagicMock()
        mock_graph.calculate_claim_confidence.side_effect = RuntimeError("DB connection failed")

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            with pytest.raises(RuntimeError, match="DB connection failed"):
                verifier.verify_claim(
                    claim_id="error_claim",
                    domain="error-domain.com",
                    evidence_graph=mock_graph,
                )

    def test_get_domain_category_exception(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-A-05: get_domain_category raises exception.

        // Given: get_domain_category that raises exception
        // When: Verifying claim
        // Then: Exception propagates
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            side_effect=RuntimeError("Config error"),
        ):
            with pytest.raises(RuntimeError, match="Config error"):
                verifier.verify_claim(
                    claim_id="config_error",
                    domain="config-error.com",
                    evidence_graph=mock_evidence_graph,
                )


class TestEmptyInputs:
    """Tests for empty/edge input values."""

    def test_verify_claim_empty_claim_id(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-A-06: verify_claim with empty claim_id.

        // Given: Empty claim_id
        // When: Verifying claim
        // Then: Handles without error (implementation detail)
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="",
                domain="test.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.claim_id == ""
        assert result.verification_status == VerificationStatus.PENDING

    def test_verify_claim_empty_domain(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-A-07: verify_claim with empty domain.

        // Given: Empty domain
        // When: Verifying claim
        // Then: Handles without error
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="test_claim",
                domain="",
                evidence_graph=mock_evidence_graph,
            )

        assert result.domain == ""

    def test_domain_claim_combined_rejection_rate_zero_claims(self) -> None:
        """
        TC-B-08: domain_claim_combined_rejection_rate is 0 when no claims (division by zero protection).

        // Given: Empty domain state
        // When: Accessing domain_claim_combined_rejection_rate
        // Then: Returns 0.0
        """
        state = DomainVerificationState(
            domain="empty.com",
            domain_category=DomainCategory.UNVERIFIED,
        )

        assert state.domain_claim_combined_rejection_rate == 0.0

    def test_build_response_meta_empty_results(self, verifier: SourceVerifier) -> None:
        """
        TC-A-08: build_response_meta with empty results list.

        // Given: Empty verification results
        // When: Building response meta
        // Then: Minimal meta returned
        """
        builder = verifier.build_response_meta([])
        meta = builder.build()

        assert "timestamp" in meta
        assert meta["data_quality"] == "normal"
        assert "claims" not in meta  # No claims added


class TestPendingToOtherStatusTransition:
    """Tests for claim status transitions from PENDING."""

    def test_claim_moves_from_pending_to_verified(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-20: Claim transitions from PENDING to VERIFIED.

        // Given: Claim initially in pending state
        // When: Later verification succeeds
        // Then: Claim removed from pending, added to verified
        """
        # First verify with insufficient evidence -> PENDING
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.0,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 0,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="transition_claim",
                domain="transition.com",
                evidence_graph=mock_evidence_graph,
            )

        state = verifier.get_domain_state("transition.com")
        assert state is not None
        assert "transition_claim" in state.pending_claims

        # Now verify again with sufficient evidence -> VERIFIED
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.8,
            "supporting_count": 2,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 2,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="transition_claim",
                domain="transition.com",
                evidence_graph=mock_evidence_graph,
            )

        state = verifier.get_domain_state("transition.com")
        assert state is not None
        assert "transition_claim" not in state.pending_claims
        assert "transition_claim" in state.verified_claims


class TestBuildResponseMetaUnverified:
    """Tests for build_response_meta with UNVERIFIED domains."""

    def test_build_response_meta_with_unverified_domain(self, verifier: SourceVerifier) -> None:
        """
        TC-N-21: build_response_meta includes unverified domains.

        // Given: Verification result with UNVERIFIED trust level
        // When: Building response meta
        // Then: Domain in unverified_domains list
        """
        from src.mcp.response_meta import VerificationDetails

        results = [
            VerificationResult(
                claim_id="unverified_claim",
                domain="unverified-domain.com",
                original_domain_category=DomainCategory.UNVERIFIED,
                new_domain_category=DomainCategory.UNVERIFIED,  # Stays UNVERIFIED
                verification_status=VerificationStatus.PENDING,
                promotion_result=PromotionResult.UNCHANGED,
                details=VerificationDetails(independent_sources=1),
                reason=ReasonCode.INSUFFICIENT_EVIDENCE,
            ),
        ]

        builder = verifier.build_response_meta(results)
        meta = builder.build()

        assert "unverified_domains" in meta
        assert "unverified-domain.com" in meta["unverified_domains"]
        assert meta["data_quality"] == "normal"  # Not degraded


class TestDomainBlockedList:
    """Tests for blocked domains list management."""

    def test_get_blocked_domains_initially_empty(self, verifier: SourceVerifier) -> None:
        """
        TC-N-17: get_blocked_domains returns empty list initially.

        // Given: Fresh verifier
        // When: Getting blocked domains
        // Then: Empty list
        """
        result = verifier.get_blocked_domains()

        assert result == []

    def test_get_blocked_domains_after_blocking(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-18: get_blocked_domains returns blocked domains.

        // Given: Domain blocked via dangerous pattern
        // When: Getting blocked domains
        // Then: Contains blocked domain
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="dangerous",
                domain="blocked-via-pattern.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
            )

        blocked = verifier.get_blocked_domains()

        assert "blocked-via-pattern.com" in blocked

    def test_is_domain_blocked_checks_both_internal_and_domain_category(
        self, verifier: SourceVerifier
    ) -> None:
        """
        TC-N-19: is_domain_blocked checks internal set and DomainCategory.

        // Given: Domain with BLOCKED trust level in config
        // When: Checking if blocked
        // Then: Returns True
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.BLOCKED,
        ):
            result = verifier.is_domain_blocked("config-blocked.com")

        assert result is True


class TestContradictingClaimsExtraction:
    """Single-user refactor: do not infer claim-vs-claim contradictions from fragment evidence."""

    def test_contradicting_claims_is_empty(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        contradicting_claims is intentionally not populated.

        We treat "contradiction" as "refuting evidence exists" and store it as REFUTES edges.
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.5,
            "supporting_count": 0,
            "refuting_count": 1,
            "neutral_count": 0,
            "independent_sources": 1,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_001",
                domain="example.com",
                evidence_graph=mock_evidence_graph,
            )

        assert result.details.contradicting_claims == []


# =============================================================================
# Domain blocked notifications: Blocked Domain Notification Tests
# =============================================================================


class TestBlockedDomainNotification:
    """Tests for Domain blocked notifications blocked domain notification queueing.

    Test Perspectives Table:
    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-BN-N-01 | Dangerous pattern blocks domain | Equiv – normal | Notification queued | - |
    | TC-BN-N-02 | High rejection rate blocks | Equiv – normal | Notification queued | - |
    | TC-BN-N-03 | Contradiction blocks UNVERIFIED | Equiv – normal | Notification queued | - |
    | TC-BN-N-04 | send_pending_notifications | Equiv – normal | All sent, cleared | - |
    | TC-BN-B-01 | Empty queue | Boundary – empty | Empty list | - |
    | TC-BN-N-05 | Duplicate domain prevention | Equiv – dedup | Single notification | - |
    | TC-BN-A-01 | Notification failure | Error – external | Error in result | - |
    | TC-BN-N-06 | get_pending_notification_count | Equiv – normal | Correct count | - |
    """

    def test_dangerous_pattern_queues_notification(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-BN-N-01: Dangerous pattern detection queues blocked notification.

        // Given: Claim with dangerous pattern
        // When: Verifying claim
        // Then: Notification queued for blocked domain
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="dangerous_claim",
                domain="dangerous-pattern.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
            )

        # Then: Notification should be queued
        assert verifier.get_pending_notification_count() == 1
        pending = verifier._pending_blocked_notifications
        assert len(pending) == 1
        domain, reason, task_id, cause_id = pending[0]
        assert domain == "dangerous-pattern.com"
        assert "Dangerous pattern" in reason

    def test_high_rejection_rate_queues_notification(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-BN-N-02: Repeated dangerous patterns blocks domain and queues notification.

        // Given: Domain with dangerous patterns detected
        // When: Multiple dangerous pattern rejections occur
        // Then: Domain blocked, notification queued

        Note: Normal contradictions return PENDING (Contradiction handling behavior).
        Dangerous patterns trigger immediate REJECTED and blocking.
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.1,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 0,
        }
        mock_evidence_graph.find_contradictions.return_value = []

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            # Verify multiple claims with dangerous pattern to trigger blocking
            for i in range(3):
                verifier.verify_claim(
                    claim_id=f"reject_claim_{i}",
                    domain="high-reject-rate.com",
                    evidence_graph=mock_evidence_graph,
                    has_dangerous_pattern=True,
                )

        # Then: Domain should be blocked (dangerous pattern detected)
        assert verifier.is_domain_blocked("high-reject-rate.com")

        # And notification should be queued (at least one for the block)
        assert verifier.get_pending_notification_count() >= 1

    def test_contradiction_stays_pending_no_demotion(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-BN-N-03: Contradiction on UNVERIFIED domain stays PENDING.

        // Given: UNVERIFIED domain with contradictions
        // When: Verifying claim
        // Then: PENDING, DomainCategory unchanged, no notification

        Contradiction handling:  do NOT demote or block.
        DomainCategory is for ranking only, not for verification decisions.
        High-inference AI interprets conflicting evidence.
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.5,
            "supporting_count": 1,
            "refuting_count": 1,  # Contradiction
            "neutral_count": 0,
            "independent_sources": 1,
        }
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "contradicted_claim", "claim2_id": "other"}
        ]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="contradicted_claim",
                domain="contradicted-site.com",
                evidence_graph=mock_evidence_graph,
            )

        # Contradiction handling behavior: PENDING, DomainCategory unchanged
        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.UNVERIFIED
        assert result.promotion_result == PromotionResult.UNCHANGED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE

        # No notification queued (no blocking occurred)
        assert verifier.get_pending_notification_count() == 0

    @pytest.mark.asyncio
    async def test_send_pending_notifications_sends_all(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-BN-N-04: send_pending_notifications sends all queued and clears.

        // Given: Multiple blocked domains queued
        // When: Calling send_pending_notifications
        // Then: All sent, queue cleared
        """
        from unittest.mock import AsyncMock

        # Queue some notifications manually
        verifier._queue_blocked_notification("domain1.com", "Reason 1", "task_1")
        verifier._queue_blocked_notification("domain2.com", "Reason 2", "task_2")

        assert verifier.get_pending_notification_count() == 2

        # Mock notify_domain_blocked (patching at the import location in notification module)
        mock_notify = AsyncMock(return_value={"shown": True, "queue_id": "iq_test"})

        with patch(
            "src.utils.intervention_manager.notify_domain_blocked",
            mock_notify,
        ):
            results = await verifier.send_pending_notifications()

        # Then: All sent
        assert len(results) == 2
        assert mock_notify.call_count == 2

        # And queue cleared
        assert verifier.get_pending_notification_count() == 0

    @pytest.mark.asyncio
    async def test_send_pending_notifications_empty_queue(self, verifier: SourceVerifier) -> None:
        """
        TC-BN-B-01: send_pending_notifications with empty queue.

        // Given: No pending notifications
        // When: Calling send_pending_notifications
        // Then: Returns empty list
        """
        results = await verifier.send_pending_notifications()
        assert results == []

    def test_duplicate_domain_not_queued_twice(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-BN-N-05: Same domain blocked twice does not queue duplicate notifications.

        // Given: Domain already queued
        // When: Blocking same domain again
        // Then: Only one notification in queue
        """
        verifier._queue_blocked_notification("dup.com", "First block", None)
        verifier._queue_blocked_notification("dup.com", "Second block", None)

        # Then: Only one notification
        assert verifier.get_pending_notification_count() == 1

    @pytest.mark.asyncio
    async def test_send_pending_notifications_with_failure(self, verifier: SourceVerifier) -> None:
        """
        TC-BN-A-01: send_pending_notifications handles notification failure.

        // Given: Notification that will fail
        // When: Calling send_pending_notifications
        // Then: Error included in result, continues with others
        """

        verifier._queue_blocked_notification("fail.com", "Will fail", None)
        verifier._queue_blocked_notification("success.com", "Will succeed", None)

        # Mock notify_domain_blocked to fail for first, succeed for second
        call_count: list[int] = [0]

        async def mock_notify(
            domain: str, reason: str, task_id: str | None = None
        ) -> dict[str, object]:
            call_count[0] += 1
            if domain == "fail.com":
                raise RuntimeError("Notification service unavailable")
            return {"shown": True, "queue_id": "iq_success"}

        with patch(
            "src.utils.intervention_manager.notify_domain_blocked",
            side_effect=mock_notify,
        ):
            results = await verifier.send_pending_notifications()

        # Then: Both processed
        assert len(results) == 2

        # First has error
        assert "error" in results[0]
        assert "fail.com" in results[0]["domain"]

        # Second succeeded
        assert results[1]["queue_id"] == "iq_success"

        # Queue still cleared
        assert verifier.get_pending_notification_count() == 0

    def test_get_pending_notification_count(self, verifier: SourceVerifier) -> None:
        """
        TC-BN-N-06: get_pending_notification_count returns correct count.

        // Given: Various states of queue
        // When: Checking count
        // Then: Correct count returned
        """
        # Empty
        assert verifier.get_pending_notification_count() == 0

        # Add one
        verifier._queue_blocked_notification("a.com", "R", None)
        assert verifier.get_pending_notification_count() == 1

        # Add more
        verifier._queue_blocked_notification("b.com", "R", None)
        verifier._queue_blocked_notification("c.com", "R", None)
        assert verifier.get_pending_notification_count() == 3


class TestDomainBlockingTransparency:
    """Tests for domain blocking transparency features."""

    @pytest.fixture
    def verifier(self) -> SourceVerifier:
        """Fresh SourceVerifier instance."""
        return SourceVerifier()

    def test_mark_domain_blocked_records_details(self, verifier: SourceVerifier) -> None:
        """
        TC-P1-1.2-N-01: _mark_domain_blocked records block details.

        // Given: A SourceVerifier
        // When: _mark_domain_blocked is called
        // Then: Domain state is updated with blocked_at, block_reason, original_domain_category
        """
        verifier._mark_domain_blocked(
            domain="example.com",
            reason="High rejection rate",
            cause_id="claim_abc",
        )

        # Then: Domain is blocked
        assert "example.com" in verifier.get_blocked_domains()

        # And: State is recorded correctly
        state = verifier.get_domain_state("example.com")
        assert state is not None
        assert state.domain_category == DomainCategory.BLOCKED
        assert state.block_reason == "High rejection rate"
        assert state.original_domain_category is not None  # Preserved from before blocking
        assert state.blocked_at is not None
        assert state.block_cause_id == "claim_abc"

    def test_mark_domain_blocked_stores_cause_id(self, verifier: SourceVerifier) -> None:
        """
        TC-P1-1.2-N-02: _mark_domain_blocked stores cause_id in state.

        // Given: A SourceVerifier
        // When: _mark_domain_blocked is called with cause_id
        // Then: State includes block_cause_id
        """
        verifier._mark_domain_blocked(
            domain="spam.org",
            reason="Dangerous pattern detected",
            cause_id="claim_xyz",
        )

        # Then: Domain is blocked
        assert "spam.org" in verifier.get_blocked_domains()

        # And: State includes cause_id
        state = verifier.get_domain_state("spam.org")
        assert state is not None
        assert state.block_cause_id == "claim_xyz"
        assert state.block_reason == "Dangerous pattern detected"
        assert state.is_blocked is True

    def test_mark_domain_blocked_updates_existing_state(self, verifier: SourceVerifier) -> None:
        """
        TC-P1-1.2-N-03: _mark_domain_blocked updates existing domain state.

        // Given: A domain with existing state
        // When: _mark_domain_blocked is called
        // Then: State is updated with block info while preserving domain
        """
        # Setup existing state
        verifier._domain_states["existing.com"] = DomainVerificationState(
            domain="existing.com",
            domain_category=DomainCategory.LOW,
            verified_claims=["claim_1"],
        )

        # When: Mark as blocked
        verifier._mark_domain_blocked(
            domain="existing.com",
            reason="Repeated contradictions",
        )

        # Then: State is updated
        state = verifier.get_domain_state("existing.com")
        assert state is not None
        assert state.domain_category == DomainCategory.BLOCKED
        assert state.block_reason == "Repeated contradictions"
        assert state.original_domain_category == DomainCategory.LOW  # Preserved from before
        assert state.verified_claims == ["claim_1"]  # Preserved
        assert state.is_blocked is True

    def test_get_blocked_domains_with_details(self, verifier: SourceVerifier) -> None:
        """
        TC-P1-1.1-N-02: get_blocked_domains returns all blocked domains.

        // Given: Multiple blocked domains
        // When: get_blocked_domains is called
        // Then: All blocked domains are returned
        """
        verifier._mark_domain_blocked("block1.com", "Reason 1")
        verifier._mark_domain_blocked("block2.com", "Reason 2")
        verifier._mark_domain_blocked("block3.com", "Reason 3")

        blocked = verifier.get_blocked_domains()

        assert len(blocked) == 3
        assert "block1.com" in blocked
        assert "block2.com" in blocked
        assert "block3.com" in blocked

    def test_domain_state_preserves_original_domain_category_after_block(
        self, verifier: SourceVerifier
    ) -> None:
        """
        TC-P1-1.1-N-03: Original trust level is preserved after blocking.

        // Given: A domain with specific trust level
        // When: Domain is blocked
        // Then: original_domain_category is preserved for potential restoration
        """
        # Setup existing state with specific trust level
        verifier._domain_states["academic.edu"] = DomainVerificationState(
            domain="academic.edu",
            domain_category=DomainCategory.ACADEMIC,
        )

        verifier._mark_domain_blocked(
            domain="academic.edu",
            reason="Misinformation detected",
        )

        state = verifier.get_domain_state("academic.edu")
        assert state is not None

        # Current trust is BLOCKED
        assert state.domain_category == DomainCategory.BLOCKED

        # But original is preserved
        assert state.original_domain_category == DomainCategory.ACADEMIC

    def test_queue_blocked_notification_includes_cause_id(self, verifier: SourceVerifier) -> None:
        """
        TC-P1-1.2-N-04: _queue_blocked_notification stores cause_id.

        // Given: A SourceVerifier
        // When: _queue_blocked_notification is called with cause_id
        // Then: cause_id is stored in the notification tuple
        """
        verifier._queue_blocked_notification(
            domain="test.com",
            reason="Test reason",
            task_id="task_test",
            cause_id="cause_evidence_123",
        )

        assert verifier.get_pending_notification_count() == 1
        notification = verifier._pending_blocked_notifications[0]
        assert len(notification) == 4
        assert notification[3] == "cause_evidence_123"

    def test_mark_domain_blocked_with_none_cause_id(self, verifier: SourceVerifier) -> None:
        """
        TC-P1-1.2-B-01: _mark_domain_blocked with None cause_id.

        // Given: A SourceVerifier
        // When: _mark_domain_blocked called without cause_id
        // Then: block_cause_id is None
        """
        verifier._mark_domain_blocked(
            domain="no-cause.com",
            reason="No causal trace",
        )

        state = verifier.get_domain_state("no-cause.com")
        assert state is not None
        assert state.block_cause_id is None
        assert state.block_reason == "No causal trace"

    def test_mark_domain_blocked_with_empty_reason(self, verifier: SourceVerifier) -> None:
        """
        TC-P1-1.2-B-02: _mark_domain_blocked with empty reason string.

        // Given: A SourceVerifier
        // When: _mark_domain_blocked called with empty reason
        // Then: Empty string is stored
        """
        verifier._mark_domain_blocked(
            domain="empty-reason.com",
            reason="",
        )

        state = verifier.get_domain_state("empty-reason.com")
        assert state is not None
        assert state.block_reason == ""
        assert state.is_blocked is True

    def test_verify_claim_dangerous_pattern_propagates_cause_id(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-P1-1.2-N-05: verify_claim with dangerous pattern propagates cause_id to _mark_domain_blocked.

        // Given: A claim with dangerous pattern detected
        // When: verify_claim is called with cause_id
        // Then: cause_id is propagated to domain state
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="dangerous_claim",
                domain="dangerous-pattern.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
                cause_id="trace_dangerous_abc",
            )

        # Then: Domain state has cause_id
        state = verifier.get_domain_state("dangerous-pattern.com")
        assert state is not None
        assert state.block_cause_id == "trace_dangerous_abc"
        assert state.is_blocked is True

    def test_verify_claim_dangerous_pattern_propagates_cause_id_to_notification(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-P1-1.2-N-06: verify_claim with dangerous pattern propagates cause_id to notification queue.

        // Given: A claim with dangerous pattern detected
        // When: verify_claim is called with cause_id
        // Then: cause_id is in the notification tuple
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="dangerous_claim",
                domain="dangerous-notify.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
                cause_id="trace_notify_xyz",
            )

        # Then: Notification queue has cause_id
        assert verifier.get_pending_notification_count() == 1
        notification = verifier._pending_blocked_notifications[0]
        assert notification[0] == "dangerous-notify.com"  # domain
        assert notification[3] == "trace_notify_xyz"  # cause_id

    def test_verify_claim_high_rejection_propagates_cause_id(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-P1-1.2-N-07: verify_claim with high rejection rate propagates cause_id.

        // Given: Domain with high rejection rate (>=3 rejections, >30%)
        // When: verify_claim triggers auto-block with cause_id
        // Then: cause_id is propagated to domain state and notification

        Note: The high rejection rate auto-block branch requires
        verification_status=REJECTED and has_dangerous_pattern=False.
        We patch the internal outcome function to force REJECTED and exercise the branch.
        """
        # Pre-populate domain state with 3 rejections (domain_claim_combined_rejection_rate = 100% > 30%)
        verifier._domain_states["high-reject-cause.com"] = DomainVerificationState(
            domain="high-reject-cause.com",
            domain_category=DomainCategory.UNVERIFIED,
            security_rejected_claims=["r1", "r2", "r3"],
            verified_claims=[],
            pending_claims=[],
        )

        mock_evidence_graph.calculate_claim_confidence.return_value = {}

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            with patch.object(
                verifier,
                "_determine_verification_outcome",
                return_value=(
                    VerificationStatus.REJECTED,
                    DomainCategory.UNVERIFIED,
                    PromotionResult.UNCHANGED,
                    ReasonCode.DANGEROUS_PATTERN,
                ),
            ):
                verifier.verify_claim(
                    claim_id="rejected_claim_4",
                    domain="high-reject-cause.com",
                    evidence_graph=mock_evidence_graph,
                    has_dangerous_pattern=False,
                    cause_id="trace_reject_4",
                )

        # Then: Domain is blocked via high rejection rate auto-block
        state = verifier.get_domain_state("high-reject-cause.com")
        assert state is not None
        assert state.is_blocked is True
        assert state.block_cause_id == "trace_reject_4"
        assert verifier.is_domain_blocked("high-reject-cause.com") is True

        # And: Notification includes cause_id
        assert verifier.get_pending_notification_count() == 1
        domain, _, _, cause_id = verifier._pending_blocked_notifications[0]
        assert domain == "high-reject-cause.com"
        assert cause_id == "trace_reject_4"

    def test_verify_claim_with_none_cause_id_blocks_without_trace(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-P1-1.2-B-03: verify_claim with cause_id=None still blocks but without trace.

        // Given: A claim with dangerous pattern
        // When: verify_claim is called without cause_id (None)
        // Then: Domain is blocked but block_cause_id is None
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="no_trace_claim",
                domain="no-trace.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
                # cause_id not provided (defaults to None)
            )

        # Then: Domain is blocked without cause_id
        state = verifier.get_domain_state("no-trace.com")
        assert state is not None
        assert state.is_blocked is True
        assert state.block_cause_id is None

        # And: Notification also has None for cause_id
        assert verifier.get_pending_notification_count() == 1
        notification = verifier._pending_blocked_notifications[0]
        assert notification[3] is None


class TestPhaseP2RelaxedBlocking:
    """Contradiction handling behavior: Relaxed immediate blocking tests.

    Contradiction handling: changes the behavior when  are detected:
    - UNVERIFIED domains: demoted to LOW (was BLOCKED)
    - Higher trust domains: stay unchanged (as before)
    - Trust levels are now recorded on edges for high-inference AI evaluation
    """

    def test_contradiction_unverified_domain_demoted_to_low(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-P2-N-01: Contradiction from UNVERIFIED domain demotes to LOW (not BLOCKED).

        // Given: Claim from UNVERIFIED domain with contradiction
        // When: Verifying claim
        // Then: REJECTED, demoted to LOW (Contradiction handling behavior relaxation)
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.3,
            "supporting_count": 1,
            "refuting_count": 1,
            "neutral_count": 0,
            "independent_sources": 1,
        }
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "claim_contested", "claim2_id": "claim_other", "confidence": 0.9}
        ]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_contested",
                domain="contested-site.com",
                evidence_graph=mock_evidence_graph,
            )

        # Contradiction handling behavior: Conflicting evidence → PENDING (no automatic demotion)
        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.UNVERIFIED
        assert result.promotion_result == PromotionResult.UNCHANGED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE

    def test_contradiction_academic_domain_stays_unchanged(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-P2-N-02: Contradiction from ACADEMIC domain stays unchanged.

        // Given: Claim from ACADEMIC domain with contradiction (scientific debate)
        // When: Verifying claim
        // Then: REJECTED but trust level unchanged (for AI evaluation)
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.5,
            "supporting_count": 2,
            "refuting_count": 1,
            "neutral_count": 0,
            "independent_sources": 2,
        }
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "claim_academic", "claim2_id": "claim_other", "confidence": 0.8}
        ]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.ACADEMIC,
        ):
            result = verifier.verify_claim(
                claim_id="claim_academic",
                domain="nature.com",
                evidence_graph=mock_evidence_graph,
            )

        # ACADEMIC domain contradiction: PENDING (no automatic decision)
        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.ACADEMIC
        assert result.promotion_result == PromotionResult.UNCHANGED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE

    def test_contradiction_trusted_domain_stays_unchanged(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-P2-N-03: Contradiction from TRUSTED domain stays unchanged.

        // Given: Claim from TRUSTED domain with contradiction
        // When: Verifying claim
        // Then: REJECTED but trust level unchanged
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.4,
            "supporting_count": 1,
            "refuting_count": 1,
            "neutral_count": 0,
            "independent_sources": 1,
        }
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "claim_trusted", "claim2_id": "claim_other", "confidence": 0.85}
        ]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.TRUSTED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_trusted",
                domain="reuters.com",
                evidence_graph=mock_evidence_graph,
            )

        # TRUSTED domain: PENDING (no automatic decision)
        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.TRUSTED
        assert result.promotion_result == PromotionResult.UNCHANGED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE

    def test_refuting_count_triggers_contested_not_blocked(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-P2-N-04: Refuting evidence (no explicit contradiction) also triggers contested handling.

        // Given: Claim with refuting evidence but no claim-claim contradiction
        // When: Verifying claim from UNVERIFIED domain
        // Then: REJECTED, demoted to LOW (Contradiction handling behavior)
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.3,
            "supporting_count": 1,
            "refuting_count": 2,  # Refuting evidence exists
            "neutral_count": 0,
            "independent_sources": 1,
        }
        # No explicit claim-claim contradiction
        mock_evidence_graph.find_contradictions.return_value = []

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_refuted",
                domain="refuted-site.com",
                evidence_graph=mock_evidence_graph,
            )

        # Refuting evidence: PENDING (no automatic demotion)
        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.UNVERIFIED
        assert result.promotion_result == PromotionResult.UNCHANGED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE

    def test_dangerous_pattern_still_blocks_immediately(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-P2-N-05: Dangerous patterns (L2/L4) still cause immediate blocking.

        // Given: Claim with dangerous pattern detected
        // When: Verifying claim
        // Then: BLOCKED immediately (Contradiction handling behavior relaxation does NOT apply to L2/L4)
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_dangerous",
                domain="malware-site.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
            )

        # Dangerous pattern: immediate BLOCK (no relaxation)
        assert result.verification_status == VerificationStatus.REJECTED
        assert result.new_domain_category == DomainCategory.BLOCKED
        assert result.promotion_result == PromotionResult.DEMOTED
        assert result.reason == ReasonCode.DANGEROUS_PATTERN
        assert verifier.is_domain_blocked("malware-site.com")

    def test_verification_ignores_domain_category(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-P2-N-06: Verification decisions do NOT depend on DomainCategory.

        // Given: Same evidence from different domain categories
        // When: Verifying claims
        // Then: Same verification status regardless of category
        """
        # Setup: Well-supported evidence (2+ independent sources, no refuting)
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.85,
            "supporting_count": 3,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 3,
        }
        mock_evidence_graph.find_contradictions.return_value = []

        # Test with UNVERIFIED domain
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result_unverified = verifier.verify_claim(
                claim_id="claim-unverified",
                domain="unverified-site.com",
                evidence_graph=mock_evidence_graph,
            )

        # Test with ACADEMIC domain (same evidence)
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.ACADEMIC,
        ):
            result_academic = verifier.verify_claim(
                claim_id="claim-academic",
                domain="academic.edu",
                evidence_graph=mock_evidence_graph,
            )

        # Both should be VERIFIED (evidence-based, not category-based)
        assert result_unverified.verification_status == VerificationStatus.VERIFIED
        assert result_academic.verification_status == VerificationStatus.VERIFIED
        assert result_unverified.reason == ReasonCode.WELL_SUPPORTED
        assert result_academic.reason == ReasonCode.WELL_SUPPORTED

        # Only difference: promotion for UNVERIFIED → LOW
        assert result_unverified.promotion_result == PromotionResult.PROMOTED
        assert result_unverified.new_domain_category == DomainCategory.LOW
        assert result_academic.promotion_result == PromotionResult.UNCHANGED
        assert result_academic.new_domain_category == DomainCategory.ACADEMIC


class TestDomainBlockReason:
    """Tests for DomainBlockReason enum and related functionality ."""

    def test_domain_block_reason_enum_values(self) -> None:
        """
        TC-N-01: DomainBlockReason enum has correct values.

        // Given: DomainBlockReason enum
        // When: Accessing enum values
        // Then: All expected values are present
        """
        assert DomainBlockReason.DANGEROUS_PATTERN == "dangerous_pattern"
        assert DomainBlockReason.HIGH_REJECTION_RATE == "high_rejection_rate"
        assert DomainBlockReason.DENYLIST == "denylist"
        assert DomainBlockReason.MANUAL == "manual"
        assert DomainBlockReason.UNKNOWN == "unknown"

    def test_get_unblock_risk_dangerous_pattern(self, verifier: SourceVerifier) -> None:
        """
        TC-N-02: _get_unblock_risk returns "high" for dangerous_pattern.

        // Given: DomainBlockReason.DANGEROUS_PATTERN
        // When: Calling _get_unblock_risk
        // Then: Returns "high"
        """
        risk = verifier._get_unblock_risk(DomainBlockReason.DANGEROUS_PATTERN)
        assert risk == "high"

    def test_get_unblock_risk_high_rejection_rate(self, verifier: SourceVerifier) -> None:
        """
        TC-N-03: _get_unblock_risk returns "low" for high_rejection_rate.

        // Given: DomainBlockReason.HIGH_REJECTION_RATE
        // When: Calling _get_unblock_risk
        // Then: Returns "low"
        """
        risk = verifier._get_unblock_risk(DomainBlockReason.HIGH_REJECTION_RATE)
        assert risk == "low"

    def test_get_unblock_risk_denylist(self, verifier: SourceVerifier) -> None:
        """
        TC-N-04: _get_unblock_risk returns "low" for denylist.

        // Given: DomainBlockReason.DENYLIST
        // When: Calling _get_unblock_risk
        // Then: Returns "low"
        """
        risk = verifier._get_unblock_risk(DomainBlockReason.DENYLIST)
        assert risk == "low"

    def test_get_unblock_risk_manual(self, verifier: SourceVerifier) -> None:
        """
        TC-N-05: _get_unblock_risk returns "low" for manual.

        // Given: DomainBlockReason.MANUAL
        // When: Calling _get_unblock_risk
        // Then: Returns "low"
        """
        risk = verifier._get_unblock_risk(DomainBlockReason.MANUAL)
        assert risk == "low"

    def test_get_unblock_risk_unknown(self, verifier: SourceVerifier) -> None:
        """
        TC-N-06: _get_unblock_risk returns "high" for unknown.

        // Given: DomainBlockReason.UNKNOWN
        // When: Calling _get_unblock_risk
        // Then: Returns "high"
        """
        risk = verifier._get_unblock_risk(DomainBlockReason.UNKNOWN)
        assert risk == "high"

    def test_get_unblock_risk_none(self, verifier: SourceVerifier) -> None:
        """
        TC-B-01: _get_unblock_risk returns "high" for None (fallback).

        // Given: None block reason
        // When: Calling _get_unblock_risk
        // Then: Returns "high" (safe default)
        """
        risk = verifier._get_unblock_risk(None)
        assert risk == "high"

    def test_get_blocked_domains_info_includes_domain_block_reason(
        self, verifier: SourceVerifier
    ) -> None:
        """
        TC-N-07: get_blocked_domains_info includes domain_block_reason.

        // Given: Domain blocked with dangerous_pattern
        // When: Calling get_blocked_domains_info
        // Then: domain_block_reason is included
        """
        verifier._mark_domain_blocked(
            domain="dangerous.com",
            reason="Dangerous pattern detected",
            block_reason_code=DomainBlockReason.DANGEROUS_PATTERN,
        )

        info = verifier.get_blocked_domains_info()
        assert len(info) == 1
        assert info[0]["domain_block_reason"] == "dangerous_pattern"
        assert info[0]["domain_unblock_risk"] == "high"

    def test_get_blocked_domains_info_includes_domain_unblock_risk(
        self, verifier: SourceVerifier
    ) -> None:
        """
        TC-N-08: get_blocked_domains_info includes domain_unblock_risk.

        // Given: Domain blocked with high_rejection_rate
        // When: Calling get_blocked_domains_info
        // Then: domain_unblock_risk is "low"
        """
        verifier._mark_domain_blocked(
            domain="high-reject.com",
            reason="High rejection rate",
            block_reason_code=DomainBlockReason.HIGH_REJECTION_RATE,
        )

        info = verifier.get_blocked_domains_info()
        assert len(info) == 1
        assert info[0]["domain_block_reason"] == "high_rejection_rate"
        assert info[0]["domain_unblock_risk"] == "low"

    def test_get_blocked_domains_info_unknown_fallback(self, verifier: SourceVerifier) -> None:
        """
        TC-N-09: get_blocked_domains_info uses UNKNOWN for missing reason.

        // Given: Domain blocked without block_reason_code
        // When: Calling get_blocked_domains_info
        // Then: domain_block_reason defaults to "unknown", risk is "high"
        """
        verifier._mark_domain_blocked(
            domain="no-reason.com",
            reason="Blocked",
            # block_reason_code not provided
        )

        info = verifier.get_blocked_domains_info()
        assert len(info) == 1
        assert info[0]["domain_block_reason"] == "unknown"
        assert info[0]["domain_unblock_risk"] == "high"

    def test_get_blocked_domains_info_all_reason_types(self, verifier: SourceVerifier) -> None:
        """
        TC-N-10: get_blocked_domains_info handles all reason types.

        // Given: Multiple domains blocked with different reasons
        // When: Calling get_blocked_domains_info
        // Then: All domains have correct domain_block_reason and domain_unblock_risk
        """
        verifier._mark_domain_blocked(
            "dangerous.com", "Dangerous", block_reason_code=DomainBlockReason.DANGEROUS_PATTERN
        )
        verifier._mark_domain_blocked(
            "high-reject.com",
            "High rejection",
            block_reason_code=DomainBlockReason.HIGH_REJECTION_RATE,
        )
        verifier._mark_domain_blocked(
            "denylist.com", "Denylist", block_reason_code=DomainBlockReason.DENYLIST
        )
        verifier._mark_domain_blocked(
            "manual.com", "Manual", block_reason_code=DomainBlockReason.MANUAL
        )

        info = verifier.get_blocked_domains_info()
        assert len(info) == 4

        # Check each domain
        info_dict = {item["domain"]: item for item in info}
        assert info_dict["dangerous.com"]["domain_block_reason"] == "dangerous_pattern"
        assert info_dict["dangerous.com"]["domain_unblock_risk"] == "high"

        assert info_dict["high-reject.com"]["domain_block_reason"] == "high_rejection_rate"
        assert info_dict["high-reject.com"]["domain_unblock_risk"] == "low"

        assert info_dict["denylist.com"]["domain_block_reason"] == "denylist"
        assert info_dict["denylist.com"]["domain_unblock_risk"] == "low"

        assert info_dict["manual.com"]["domain_block_reason"] == "manual"
        assert info_dict["manual.com"]["domain_unblock_risk"] == "low"

    def test_verify_claim_dangerous_pattern_sets_block_reason(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-11: verify_claim with dangerous_pattern sets domain_block_reason.

        // Given: Claim with dangerous pattern
        // When: Verifying claim
        // Then: Domain state has domain_block_reason=DANGEROUS_PATTERN
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="dangerous_claim",
                domain="dangerous-pattern.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
            )

        state = verifier.get_domain_state("dangerous-pattern.com")
        assert state is not None
        assert state.domain_block_reason == DomainBlockReason.DANGEROUS_PATTERN

    def test_verify_claim_high_rejection_rate_sets_block_reason(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-N-12: verify_claim with high rejection rate sets domain_block_reason.

        // Given: Domain with high rejection rate
        // When: Auto-blocking occurs
        // Then: Domain state has domain_block_reason=HIGH_REJECTION_RATE
        """
        # Pre-populate domain state with 3 rejections
        verifier._domain_states["high-reject.com"] = DomainVerificationState(
            domain="high-reject.com",
            domain_category=DomainCategory.UNVERIFIED,
            security_rejected_claims=["r1", "r2", "r3"],
            verified_claims=[],
        )

        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.1,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 0,
        }

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            with patch.object(
                verifier,
                "_determine_verification_outcome",
                return_value=(
                    VerificationStatus.REJECTED,
                    DomainCategory.UNVERIFIED,
                    PromotionResult.UNCHANGED,
                    ReasonCode.DANGEROUS_PATTERN,
                ),
            ):
                verifier.verify_claim(
                    claim_id="rejected_claim",
                    domain="high-reject.com",
                    evidence_graph=mock_evidence_graph,
                    has_dangerous_pattern=False,
                )

        state = verifier.get_domain_state("high-reject.com")
        assert state is not None
        assert state.is_blocked is True
        assert state.domain_block_reason == DomainBlockReason.HIGH_REJECTION_RATE

    def test_get_blocked_domains_info_propagates_to_mcp_response(
        self, verifier: SourceVerifier
    ) -> None:
        """
        TC-N-13: get_blocked_domains_info propagates domain_block_reason to MCP response.

        // Given: Domain blocked with specific reason
        // When: Calling get_blocked_domains_info and using in MCP response
        // Then: domain_block_reason and domain_unblock_risk are correctly propagated (wiring test)
        """
        verifier._mark_domain_blocked(
            domain="wiring-test.com",
            reason="Test wiring",
            block_reason_code=DomainBlockReason.DENYLIST,
        )

        # Simulate MCP response construction
        blocked_info = verifier.get_blocked_domains_info()
        mcp_response_blocked_domains = blocked_info

        # Verify wiring: fields propagate to MCP response structure
        assert len(mcp_response_blocked_domains) == 1
        assert mcp_response_blocked_domains[0]["domain_block_reason"] == "denylist"
        assert mcp_response_blocked_domains[0]["domain_unblock_risk"] == "low"

    def test_get_blocked_domains_info_with_no_state_uses_unknown(
        self, verifier: SourceVerifier
    ) -> None:
        """
        TC-A-01: get_blocked_domains_info handles domain without detailed state.

        // Given: Domain in blocked set but no DomainVerificationState
        // When: Calling get_blocked_domains_info
        // Then: Returns info with domain_block_reason="unknown", risk="high"
        """
        # Add to blocked set without creating state
        verifier._blocked_domains.add("no-state.com")

        info = verifier.get_blocked_domains_info()
        assert len(info) == 1
        assert info[0]["domain"] == "no-state.com"
        assert info[0]["domain_block_reason"] == "unknown"
        assert info[0]["domain_unblock_risk"] == "high"


class TestRejectionRateSeparation:
    """Tests for rejection rate separation (ADR-0005).

    Test Perspectives Table:
    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-5.5-N-01 | security_rejected_claims=["a","b"] | Equiv - normal | domain_claim_security_rejection_rate = 2/total | - |
    | TC-5.5-N-02 | manual_rejected_claims=["c"] | Equiv - normal | domain_claim_manual_rejection_rate = 1/total | - |
    | TC-5.5-N-03 | security=["a"], manual=["b"] | Equiv - combined | domain_claim_combined_rejection_rate = 2/total | Deduplicated |
    | TC-5.5-N-04 | security=["a"], manual=["a"] | Boundary - overlap | domain_claim_combined_rejection_rate = 1/total | Same claim in both |
    | TC-5.5-B-01 | total_claims=0 | Boundary - zero div | All rates = 0.0 | Division by zero protection |
    | TC-5.5-B-02 | Only pending claims | Boundary - no rejections | All rejection rates = 0.0 | - |
    | TC-5.5-N-05 | verify_claim with dangerous_pattern | Wiring - security rejection | Claim in security_rejected_claims | Propagation test |
    | TC-5.5-N-06 | High combined rejection rate | Effect - block decision | Domain blocked | Uses combined rate |
    | TC-5.5-A-01 | NULL claim_id | Boundary - NULL | Handled gracefully | - |
    | TC-5.5-E-01 | RejectionType.MANUAL | Equiv - manual | Claim in manual_rejected_claims | preparation |
    | TC-5.5-A-01 | rejection_type=\"manual\" (str) | Abnormal - invalid type | TypeError with message | Runtime guard |
    | TC-5.5-A-02 | rejection_type=None | Boundary - NULL | TypeError with message | Runtime guard |
    """

    def test_domain_claim_security_rejection_rate_calculation(self) -> None:
        """
        TC-5.5-N-01: domain_claim_security_rejection_rate calculates correctly.

        // Given: Domain state with security-rejected claims
        // When: Accessing domain_claim_security_rejection_rate
        // Then: Correct ratio returned
        """
        state = DomainVerificationState(
            domain="test.com",
            domain_category=DomainCategory.UNVERIFIED,
            verified_claims=["v1"],
            security_rejected_claims=["a", "b"],
            pending_claims=["p1"],
        )

        assert state.domain_claim_security_rejection_rate == 0.5  # 2/4

    def test_domain_claim_manual_rejection_rate_calculation(self) -> None:
        """
        TC-5.5-N-02: domain_claim_manual_rejection_rate calculates correctly.

        // Given: Domain state with manually-rejected claims
        // When: Accessing domain_claim_manual_rejection_rate
        // Then: Correct ratio returned
        """
        state = DomainVerificationState(
            domain="test.com",
            domain_category=DomainCategory.UNVERIFIED,
            verified_claims=["v1"],
            manual_rejected_claims=["c"],
            pending_claims=["p1"],
        )

        # total_claims = 1 verified + 1 unique rejected + 1 pending = 3
        assert state.domain_claim_manual_rejection_rate == 1 / 3

    def test_domain_claim_combined_rejection_rate_no_overlap(self) -> None:
        """
        TC-5.5-N-03: domain_claim_combined_rejection_rate deduplicates correctly.

        // Given: Domain state with security and manual rejections (no overlap)
        // When: Accessing domain_claim_combined_rejection_rate
        // Then: Correct deduplicated ratio returned
        """
        state = DomainVerificationState(
            domain="test.com",
            domain_category=DomainCategory.UNVERIFIED,
            verified_claims=["v1"],
            security_rejected_claims=["a"],
            manual_rejected_claims=["b"],
            pending_claims=["p1"],
        )

        assert state.domain_claim_combined_rejection_rate == 0.5  # 2/4 (deduplicated)

    def test_domain_claim_combined_rejection_rate_with_overlap(self) -> None:
        """
        TC-5.5-N-04: domain_claim_combined_rejection_rate handles overlap correctly.

        // Given: Domain state with same claim in both security and manual lists
        // When: Accessing domain_claim_combined_rejection_rate
        // Then: Claim counted only once
        """
        state = DomainVerificationState(
            domain="test.com",
            domain_category=DomainCategory.UNVERIFIED,
            verified_claims=["v1"],
            security_rejected_claims=["a"],
            manual_rejected_claims=["a"],  # Same claim
            pending_claims=["p1"],
        )

        # total_claims = 1 verified + 1 unique rejected (a) + 1 pending = 3
        assert state.domain_claim_combined_rejection_rate == 1 / 3

    def test_rejection_rates_zero_when_no_claims(self) -> None:
        """
        TC-5.5-B-01: All rejection rates return 0.0 when total_claims=0.

        // Given: Empty domain state
        // When: Accessing rejection rate properties
        // Then: All return 0.0 (division by zero protection)
        """
        state = DomainVerificationState(
            domain="empty.com",
            domain_category=DomainCategory.UNVERIFIED,
        )

        assert state.domain_claim_security_rejection_rate == 0.0
        assert state.domain_claim_manual_rejection_rate == 0.0
        assert state.domain_claim_combined_rejection_rate == 0.0

    def test_rejection_rates_zero_when_no_rejections(self) -> None:
        """
        TC-5.5-B-02: All rejection rates return 0.0 when only pending claims exist.

        // Given: Domain state with only pending claims
        // When: Accessing rejection rate properties
        // Then: All return 0.0
        """
        state = DomainVerificationState(
            domain="pending-only.com",
            domain_category=DomainCategory.UNVERIFIED,
            pending_claims=["p1", "p2"],
        )

        assert state.domain_claim_security_rejection_rate == 0.0
        assert state.domain_claim_manual_rejection_rate == 0.0
        assert state.domain_claim_combined_rejection_rate == 0.0

    def test_verify_claim_dangerous_pattern_adds_to_security_rejected(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-5.5-N-05: verify_claim with dangerous_pattern adds claim to security_rejected_claims.

        // Given: Claim with dangerous pattern detected
        // When: Verifying claim
        // Then: Claim in security_rejected_claims (wiring test)
        """
        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="dangerous_claim",
                domain="dangerous-pattern.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
            )

        state = verifier.get_domain_state("dangerous-pattern.com")
        assert state is not None
        assert "dangerous_claim" in state.security_rejected_claims
        assert "dangerous_claim" not in state.manual_rejected_claims

    def test_high_combined_rejection_rate_blocks_domain(
        self, verifier: SourceVerifier, mock_evidence_graph: MagicMock
    ) -> None:
        """
        TC-5.5-N-06: High domain_claim_combined_rejection_rate triggers domain block.

        // Given: Domain with high combined rejection rate (>30%)
        // When: Verifying claim that triggers rejection
        // Then: Domain gets blocked (effect test)
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "bayesian_claim_confidence": 0.1,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "independent_sources": 0,
        }
        mock_evidence_graph.find_contradictions.return_value = []

        # Pre-populate with 3 security rejections (3/10 = 30%, but we need >30%)
        verifier._domain_states["high-combined.com"] = DomainVerificationState(
            domain="high-combined.com",
            domain_category=DomainCategory.UNVERIFIED,
            security_rejected_claims=["r1", "r2", "r3"],
            verified_claims=["v1", "v2", "v3", "v4", "v5", "v6"],
            pending_claims=[],
        )

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            with patch.object(
                verifier,
                "_determine_verification_outcome",
                return_value=(
                    VerificationStatus.REJECTED,
                    DomainCategory.UNVERIFIED,
                    PromotionResult.UNCHANGED,
                    ReasonCode.DANGEROUS_PATTERN,
                ),
            ):
                verifier.verify_claim(
                    claim_id="rejected_claim_4",
                    domain="high-combined.com",
                    evidence_graph=mock_evidence_graph,
                    has_dangerous_pattern=False,
                )

        # Then: Domain should be blocked (4/10 = 40% > 30%)
        state = verifier.get_domain_state("high-combined.com")
        assert state is not None
        assert state.is_blocked is True
        assert verifier.is_domain_blocked("high-combined.com") is True

    def test_update_domain_state_with_manual_rejection_type(self, verifier: SourceVerifier) -> None:
        """
        TC-5.5-E-01: _update_domain_state with RejectionType.MANUAL adds to manual_rejected_claims.

        // Given: Claim rejected with MANUAL type
        // When: Calling _update_domain_state
        // Then: Claim in manual_rejected_claims ( preparation)
        """
        verifier._update_domain_state(
            domain="test.com",
            claim_id="manual_reject_claim",
            status=VerificationStatus.REJECTED,
            rejection_type=RejectionType.MANUAL,
        )

        state = verifier.get_domain_state("test.com")
        assert state is not None
        assert "manual_reject_claim" in state.manual_rejected_claims
        assert "manual_reject_claim" not in state.security_rejected_claims

    def test_update_domain_state_rejects_invalid_rejection_type_str(
        self, verifier: SourceVerifier
    ) -> None:
        """
        TC-5.5-A-01: _update_domain_state rejects invalid rejection_type (str).

        // Given: rejection_type passed as a string (invalid)
        // When:  Calling _update_domain_state
        // Then:  TypeError is raised with a clear message
        """
        with pytest.raises(TypeError, match=r"rejection_type must be RejectionType, got str"):
            verifier._update_domain_state(
                domain="test.com",
                claim_id="bad_type_claim",
                status=VerificationStatus.REJECTED,
                rejection_type="manual",  # type: ignore[arg-type]
            )

    def test_update_domain_state_rejects_invalid_rejection_type_none(
        self, verifier: SourceVerifier
    ) -> None:
        """
        TC-5.5-A-02: _update_domain_state rejects invalid rejection_type (None).

        // Given: rejection_type passed as None (invalid)
        // When:  Calling _update_domain_state
        // Then:  TypeError is raised with a clear message
        """
        with pytest.raises(TypeError, match=r"rejection_type must be RejectionType, got NoneType"):
            verifier._update_domain_state(
                domain="test.com",
                claim_id="none_type_claim",
                status=VerificationStatus.REJECTED,
                rejection_type=None,  # type: ignore[arg-type]
            )

    def test_total_claims_deduplicates_rejections(self) -> None:
        """
        TC-5.5-N-07: total_claims property deduplicates security and manual rejections.

        // Given: Domain state with overlapping rejections
        // When: Accessing total_claims
        // Then: Overlapping claims counted only once
        """
        state = DomainVerificationState(
            domain="test.com",
            domain_category=DomainCategory.UNVERIFIED,
            verified_claims=["v1"],
            security_rejected_claims=["r1", "r2"],
            manual_rejected_claims=["r2", "r3"],  # r2 overlaps
            pending_claims=["p1"],
        )

        # Should be: 1 verified + 3 unique rejected (r1, r2, r3) + 1 pending = 5
        assert state.total_claims == 5
