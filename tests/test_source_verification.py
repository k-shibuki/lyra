"""
Tests for Source Verification Flow (K.3-6, §4.4.1 L6).

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
    DomainVerificationState,
    PromotionResult,
    ReasonCode,
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
        "confidence": 0.5,
        "supporting_count": 0,
        "refuting_count": 0,
        "neutral_count": 0,
        "verdict": "unverified",
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
            "confidence": 0.0,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "unverified",
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
            "confidence": 0.8,
            "supporting_count": 2,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "supported",
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

    def test_verify_claim_with_contradictions_stays_pending(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-N-02: Claim with contradictions stays PENDING.

        // Given: Claim with contradiction detected
        // When: Verifying claim
        // Then: PENDING status, DomainCategory unchanged (for AI evaluation)

        Phase P.2 Update: Contradictions do NOT change DomainCategory.
        DomainCategory is only for ranking, not for verification decisions.
        High-inference AI interprets conflicting evidence.
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.3,
            "supporting_count": 1,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "contested",
            "independent_sources": 1,
        }
        mock_evidence_graph.find_contradictions.return_value = [
            {
                "claim1_id": "claim_003",
                "claim2_id": "claim_other",
                "confidence": 0.9,
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

        # Phase P.2: Contradictions → PENDING (not REJECTED)
        assert result.verification_status == VerificationStatus.PENDING
        # DomainCategory unchanged (not demoted)
        assert result.new_domain_category == DomainCategory.UNVERIFIED
        assert result.promotion_result == PromotionResult.UNCHANGED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE


class TestSourceVerifierEdgeCases:
    """Edge cases and boundary tests."""

    def test_already_blocked_domain_rejected_immediately(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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

    def test_dangerous_pattern_causes_immediate_block(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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

    def test_one_independent_source_stays_pending(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-B-03: Claim with exactly 1 independent source stays PENDING.

        // Given: Claim with exactly 1 independent source (below threshold)
        // When: Verifying claim
        // Then: PENDING status, no promotion
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.5,
            "supporting_count": 1,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "supported",
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

    def test_exactly_two_independent_sources_promotes(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-B-02: Claim with exactly 2 independent sources gets promoted.

        // Given: Claim with exactly 2 independent sources (at threshold)
        // When: Verifying claim
        // Then: VERIFIED, promoted to LOW
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.75,
            "supporting_count": 2,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "supported",
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

    def test_zero_independent_sources_stays_pending(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-B-01: Claim with 0 independent sources stays PENDING.

        // Given: Claim with no evidence
        // When: Verifying claim
        // Then: PENDING status
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.0,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "unverified",
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

    def test_domain_state_created_on_first_verification(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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

    def test_domain_state_tracks_verified_claims(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-N-05: Verified claims tracked in domain state.

        // Given: Claim that gets VERIFIED
        // When: Checking domain state
        // Then: Claim in verified_claims list
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.8,
            "supporting_count": 2,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "supported",
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
        assert "verified_claim" in state.verified_claims

    def test_high_rejection_rate_blocks_domain(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-A-03: High rejection rate causes domain block.

        // Given: Domain with many rejected claims (via dangerous pattern)
        // When: Rejection rate exceeds threshold
        // Then: Domain gets blocked

        Note: has_dangerous_pattern=True triggers REJECTED status.
        Normal contradictions return PENDING (Phase P.2).
        """
        mock_evidence_graph.find_contradictions.return_value = []
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.2,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "unknown",
            "independent_sources": 0,
        }

        # Pre-populate domain state with many rejections
        verifier._domain_states["high-reject.com"] = DomainVerificationState(
            domain="high-reject.com",
            domain_category=DomainCategory.UNVERIFIED,
            rejected_claims=["r1", "r2", "r3"],  # Already 3 rejections
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
            rejected_claims=["r1"],
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
            rejected_claims=["r1"],
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

    def test_rejection_rate_calculation(self) -> None:
        """
        TC-N-08: rejection_rate property calculates correctly.

        // Given: Domain state with rejections
        // When: Accessing rejection_rate
        // Then: Correct ratio returned
        """
        state = DomainVerificationState(
            domain="test.com",
            domain_category=DomainCategory.UNVERIFIED,
            verified_claims=["v1"],
            rejected_claims=["r1", "r2"],
            pending_claims=["p1"],
        )

        assert state.rejection_rate == 0.5  # 2/4


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

    def test_build_response_meta_with_verified_claims(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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
                reason="Corroborated",
            ),
            VerificationResult(
                claim_id="claim_2",
                domain="bad.com",
                original_domain_category=DomainCategory.UNVERIFIED,
                new_domain_category=DomainCategory.BLOCKED,
                verification_status=VerificationStatus.REJECTED,
                promotion_result=PromotionResult.DEMOTED,
                details=VerificationDetails(),
                reason="Contradiction",
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

        Phase P.2: Contradictions → PENDING for AI evaluation.
        DomainCategory is not used in verification decisions.
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.3,
            "supporting_count": 1,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "contested",
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

    def test_trusted_domain_verified_stays_trusted(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-N-14: Trusted domain with verification stays TRUSTED (no promotion).

        // Given: Claim from TRUSTED domain with 2+ sources
        // When: Verifying claim
        // Then: VERIFIED but trust level stays TRUSTED (no promotion)
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.9,
            "supporting_count": 3,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "well_supported",
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

    def test_rejection_rate_exactly_at_threshold_not_blocked(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-B-05: Rejection rate at threshold with dangerous pattern triggers block.

        // Given: Domain with existing rejections + dangerous pattern
        // When: Verifying claim with has_dangerous_pattern=True
        // Then: Blocked (dangerous pattern + high rejection rate)

        Note: Normal contradictions return PENDING (Phase P.2).
        """
        mock_evidence_graph.find_contradictions.return_value = []
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.2,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "unknown",
            "independent_sources": 0,
        }

        # 3 rejected out of 10 total = 30%
        verifier._domain_states["threshold.com"] = DomainVerificationState(
            domain="threshold.com",
            domain_category=DomainCategory.UNVERIFIED,
            rejected_claims=["r1", "r2"],  # 2 rejected
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

    def test_contradiction_stays_pending_not_demoted(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-B-06: Contradiction stays PENDING without demotion.

        // Given: Domain with contradiction
        // When: Verifying claim
        // Then: PENDING, DomainCategory unchanged

        Phase P.2: Contradictions do NOT change DomainCategory.
        High-inference AI evaluates conflicting evidence.
        """
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "below_threshold", "claim2_id": "other"}
        ]
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.2,
            "supporting_count": 0,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "likely_false",
            "independent_sources": 0,
        }

        # Pre-populate domain state
        verifier._domain_states["low-reject.com"] = DomainVerificationState(
            domain="low-reject.com",
            domain_category=DomainCategory.UNVERIFIED,
            rejected_claims=[],
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

        # Phase P.2: Contradictions → PENDING, DomainCategory unchanged
        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.UNVERIFIED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE

    def test_three_independent_sources_well_above_threshold(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-B-07: Claim with 3 independent sources (above threshold).

        // Given: Claim with 3 independent sources (threshold is 2)
        // When: Verifying claim
        // Then: VERIFIED and promoted
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.9,
            "supporting_count": 3,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "well_supported",
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

    def test_verify_same_claim_twice_no_duplicate(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-N-16: Verifying same claim twice doesn't create duplicates.

        // Given: Claim already verified
        // When: Verifying same claim again
        // Then: No duplicate entries in domain state
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.8,
            "supporting_count": 2,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "supported",
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

    def test_get_domain_category_exception(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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

    def test_verify_claim_empty_claim_id(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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

    def test_verify_claim_empty_domain(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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

    def test_domain_verification_state_rejection_rate_zero_claims(self) -> None:
        """
        TC-B-08: rejection_rate is 0 when no claims (division by zero protection).

        // Given: Empty domain state
        // When: Accessing rejection_rate
        // Then: Returns 0.0
        """
        state = DomainVerificationState(
            domain="empty.com",
            domain_category=DomainCategory.UNVERIFIED,
        )

        assert state.rejection_rate == 0.0

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

    def test_claim_moves_from_pending_to_verified(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-N-20: Claim transitions from PENDING to VERIFIED.

        // Given: Claim initially in pending state
        // When: Later verification succeeds
        // Then: Claim removed from pending, added to verified
        """
        # First verify with insufficient evidence -> PENDING
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.0,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "unverified",
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
        assert "transition_claim" in state.pending_claims

        # Now verify again with sufficient evidence -> VERIFIED
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.8,
            "supporting_count": 2,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "supported",
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
                reason="Insufficient evidence",
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

    def test_get_blocked_domains_after_blocking(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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

    def test_is_domain_blocked_checks_both_internal_and_domain_category(self, verifier: SourceVerifier) -> None:
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
    """Tests for contradicting_claims extraction to prevent None values."""

    def test_contradicting_claims_filters_out_none_values(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-A-20: contradicting_claims should not contain None values.

        // Given: Contradiction with only claim2_id (claim1_id missing)
        // When: Verifying claim
        // Then: contradicting_claims does not contain None
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.5,
            "supporting_count": 0,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "refuted",
            "independent_sources": 1,
        }
        # Malformed contradiction: missing claim1_id
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim2_id": "claim_001"}  # claim1_id is missing
        ]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_001",
                domain="example.com",
                evidence_graph=mock_evidence_graph,
            )

        # Should not contain None
        assert None not in result.details.contradicting_claims

    def test_contradicting_claims_with_missing_claim2_id(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-A-21: Handle contradiction with missing claim2_id.

        // Given: Contradiction with only claim1_id (claim2_id missing)
        // When: Verifying claim that matches claim1_id
        // Then: contradicting_claims does not contain None
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.5,
            "supporting_count": 0,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "refuted",
            "independent_sources": 1,
        }
        # Malformed contradiction: missing claim2_id
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "claim_001"}  # claim2_id is missing
        ]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_001",
                domain="example.com",
                evidence_graph=mock_evidence_graph,
            )

        # Should not contain None
        assert None not in result.details.contradicting_claims
        # Should be empty since there's no "other" claim ID to add
        assert result.details.contradicting_claims == []

    def test_contradicting_claims_extracts_correct_other_claim(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-N-22: Extract correct "other" claim ID from contradiction.

        // Given: Valid contradiction with both claim IDs
        // When: Verifying claim that is claim1_id
        // Then: contradicting_claims contains claim2_id
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.5,
            "supporting_count": 0,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "refuted",
            "independent_sources": 1,
        }
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "claim_001", "claim2_id": "claim_002"}
        ]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_001",
                domain="example.com",
                evidence_graph=mock_evidence_graph,
            )

        # Should contain claim_002 (the other claim)
        assert "claim_002" in result.details.contradicting_claims
        assert "claim_001" not in result.details.contradicting_claims

    def test_contradicting_claims_when_claim_is_claim2(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-N-23: Extract correct claim when current claim is claim2_id.

        // Given: Contradiction where current claim is claim2_id
        // When: Verifying
        // Then: contradicting_claims contains claim1_id
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.5,
            "supporting_count": 0,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "refuted",
            "independent_sources": 1,
        }
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "claim_001", "claim2_id": "claim_002"}
        ]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_002",  # This claim is claim2_id
                domain="example.com",
                evidence_graph=mock_evidence_graph,
            )

        # Should contain claim_001 (the other claim)
        assert "claim_001" in result.details.contradicting_claims
        assert "claim_002" not in result.details.contradicting_claims

    def test_contradicting_claims_empty_contradiction_dict(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-A-24: Handle empty contradiction dict.

        // Given: Empty contradiction dict in list
        // When: Verifying claim
        // Then: contradicting_claims is empty, no exception
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.5,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "unverified",
            "independent_sources": 1,
        }
        # Empty dict that somehow passed the filter (edge case)
        mock_evidence_graph.find_contradictions.return_value = [{}]

        with patch(
            "src.filter.source_verification.get_domain_category",
            return_value=DomainCategory.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_001",
                domain="example.com",
                evidence_graph=mock_evidence_graph,
            )

        # Should be empty and not contain None
        assert None not in result.details.contradicting_claims


# =============================================================================
# K.3-8: Blocked Domain Notification Tests
# =============================================================================


class TestBlockedDomainNotification:
    """Tests for K.3-8 blocked domain notification queueing.

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

    def test_dangerous_pattern_queues_notification(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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

    def test_high_rejection_rate_queues_notification(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-BN-N-02: Repeated dangerous patterns blocks domain and queues notification.

        // Given: Domain with dangerous patterns detected
        // When: Multiple dangerous pattern rejections occur
        // Then: Domain blocked, notification queued

        Note: Normal contradictions return PENDING (Phase P.2).
        Dangerous patterns trigger immediate REJECTED and blocking.
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.1,
            "supporting_count": 0,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "unknown",
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

    def test_contradiction_stays_pending_no_demotion(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-BN-N-03: Contradiction on UNVERIFIED domain stays PENDING.

        // Given: UNVERIFIED domain with contradictions
        // When: Verifying claim
        // Then: PENDING, DomainCategory unchanged, no notification

        Phase P.2: Contradictions do NOT demote or block.
        DomainCategory is for ranking only, not for verification decisions.
        High-inference AI interprets conflicting evidence.
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.5,
            "supporting_count": 1,
            "refuting_count": 1,  # Contradiction
            "neutral_count": 0,
            "verdict": "contradicted",
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

        # Phase P.2: PENDING, DomainCategory unchanged
        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.UNVERIFIED
        assert result.promotion_result == PromotionResult.UNCHANGED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE

        # No notification queued (no blocking occurred)
        assert verifier.get_pending_notification_count() == 0

    @pytest.mark.asyncio
    async def test_send_pending_notifications_sends_all(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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
            "src.utils.notification.notify_domain_blocked",
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

    def test_duplicate_domain_not_queued_twice(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
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
    async def test_send_pending_notifications_with_failure(
        self, verifier: SourceVerifier
    ) -> None:
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
            "src.utils.notification.notify_domain_blocked",
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

    def test_domain_state_preserves_original_domain_category_after_block(self, verifier: SourceVerifier) -> None:
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
        assert state.block_reason == ""
        assert state.is_blocked is True


class TestPhaseP2RelaxedBlocking:
    """Phase P.2: Relaxed immediate blocking tests.

    Phase P.2 changes the behavior when contradictions are detected:
    - UNVERIFIED domains: demoted to LOW (was BLOCKED)
    - Higher trust domains: stay unchanged (as before)
    - Trust levels are now recorded on edges for high-inference AI evaluation
    """

    def test_contradiction_unverified_domain_demoted_to_low(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-P2-N-01: Contradiction from UNVERIFIED domain demotes to LOW (not BLOCKED).

        // Given: Claim from UNVERIFIED domain with contradiction
        // When: Verifying claim
        // Then: REJECTED, demoted to LOW (Phase P.2 relaxation)
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.3,
            "supporting_count": 1,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "contested",
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

        # Phase P.2: Conflicting evidence → PENDING (no automatic demotion)
        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_domain_category == DomainCategory.UNVERIFIED
        assert result.promotion_result == PromotionResult.UNCHANGED
        assert result.reason == ReasonCode.CONFLICTING_EVIDENCE

    def test_contradiction_academic_domain_stays_unchanged(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-P2-N-02: Contradiction from ACADEMIC domain stays unchanged.

        // Given: Claim from ACADEMIC domain with contradiction (scientific debate)
        // When: Verifying claim
        // Then: REJECTED but trust level unchanged (for AI evaluation)
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.5,
            "supporting_count": 2,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "contested",
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

    def test_contradiction_trusted_domain_stays_unchanged(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-P2-N-03: Contradiction from TRUSTED domain stays unchanged.

        // Given: Claim from TRUSTED domain with contradiction
        // When: Verifying claim
        // Then: REJECTED but trust level unchanged
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.4,
            "supporting_count": 1,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "contested",
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

    def test_refuting_count_triggers_contested_not_blocked(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-P2-N-04: Refuting evidence (no explicit contradiction) also triggers contested handling.

        // Given: Claim with refuting evidence but no claim-claim contradiction
        // When: Verifying claim from UNVERIFIED domain
        // Then: REJECTED, demoted to LOW (Phase P.2)
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.3,
            "supporting_count": 1,
            "refuting_count": 2,  # Refuting evidence exists
            "neutral_count": 0,
            "verdict": "contested",
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

    def test_dangerous_pattern_still_blocks_immediately(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-P2-N-05: Dangerous patterns (L2/L4) still cause immediate blocking.

        // Given: Claim with dangerous pattern detected
        // When: Verifying claim
        // Then: BLOCKED immediately (Phase P.2 relaxation does NOT apply to L2/L4)
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

    def test_verification_ignores_domain_category(self, verifier: SourceVerifier, mock_evidence_graph: MagicMock) -> None:
        """
        TC-P2-N-06: Verification decisions do NOT depend on DomainCategory.

        // Given: Same evidence from different domain categories
        // When: Verifying claims
        // Then: Same verification status regardless of category
        """
        # Setup: Well-supported evidence (2+ independent sources, no refuting)
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.85,
            "supporting_count": 3,
            "refuting_count": 0,
            "neutral_count": 0,
            "verdict": "verified",
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
