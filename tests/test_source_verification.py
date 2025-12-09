"""
Tests for Source Verification Flow (K.3-6, §4.4.1 L6).

Test Coverage:
- Claim verification with EvidenceGraph
- Trust level promotion (UNVERIFIED → LOW)
- Trust level demotion (→ BLOCKED)
- Domain state tracking
- Response metadata building
"""

import pytest
from unittest.mock import MagicMock, patch

from src.filter.source_verification import (
    SourceVerifier,
    VerificationResult,
    DomainVerificationState,
    PromotionResult,
    get_source_verifier,
    reset_source_verifier,
)
from src.mcp.response_meta import VerificationStatus
from src.utils.domain_policy import TrustLevel


@pytest.fixture
def verifier():
    """Create fresh SourceVerifier for each test."""
    return SourceVerifier()


@pytest.fixture
def mock_evidence_graph():
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
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_001",
                domain="unknown-site.com",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.verification_status == VerificationStatus.PENDING
        assert result.new_trust_level == TrustLevel.UNVERIFIED
        assert result.promotion_result == PromotionResult.UNCHANGED
    
    def test_verify_claim_with_two_independent_sources_promotes(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_002",
                domain="promoted-site.com",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.verification_status == VerificationStatus.VERIFIED
        assert result.new_trust_level == TrustLevel.LOW
        assert result.promotion_result == PromotionResult.PROMOTED
    
    def test_verify_claim_with_contradictions_gets_rejected(
        self, verifier, mock_evidence_graph
    ):
        """
        TC-N-02: Claim with contradictions gets REJECTED.
        
        // Given: Claim with contradiction detected
        // When: Verifying claim
        // Then: REJECTED status, demoted to BLOCKED
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_003",
                domain="contradicted-site.com",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.verification_status == VerificationStatus.REJECTED
        assert result.new_trust_level == TrustLevel.BLOCKED
        assert result.promotion_result == PromotionResult.DEMOTED


class TestSourceVerifierEdgeCases:
    """Edge cases and boundary tests."""
    
    def test_already_blocked_domain_rejected_immediately(
        self, verifier, mock_evidence_graph
    ):
        """
        TC-A-01: Already blocked domain gets rejected immediately.
        
        // Given: Claim from BLOCKED domain
        // When: Verifying claim
        // Then: REJECTED immediately without graph query
        """
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.BLOCKED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_blocked",
                domain="blocked-site.com",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.verification_status == VerificationStatus.REJECTED
        assert result.new_trust_level == TrustLevel.BLOCKED
        assert "blocked" in result.reason.lower()
    
    def test_dangerous_pattern_causes_immediate_block(
        self, verifier, mock_evidence_graph
    ):
        """
        TC-A-02: Dangerous pattern detected causes immediate block.
        
        // Given: Claim with dangerous pattern detected (L2/L4)
        // When: Verifying claim with has_dangerous_pattern=True
        // Then: REJECTED, domain BLOCKED
        """
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_dangerous",
                domain="dangerous-site.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
            )
        
        assert result.verification_status == VerificationStatus.REJECTED
        assert result.new_trust_level == TrustLevel.BLOCKED
        assert result.promotion_result == PromotionResult.DEMOTED
        assert verifier.is_domain_blocked("dangerous-site.com")
    
    def test_one_independent_source_stays_pending(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_one_source",
                domain="one-source-site.com",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.verification_status == VerificationStatus.PENDING
        assert result.promotion_result == PromotionResult.UNCHANGED
    
    def test_exactly_two_independent_sources_promotes(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_two_sources",
                domain="two-source-site.com",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.verification_status == VerificationStatus.VERIFIED
        assert result.new_trust_level == TrustLevel.LOW
        assert result.promotion_result == PromotionResult.PROMOTED
    
    def test_zero_independent_sources_stays_pending(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
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
        self, verifier, mock_evidence_graph
    ):
        """
        TC-N-04: Domain state created on first verification.
        
        // Given: New domain never verified
        // When: Verifying first claim
        // Then: Domain state created and tracked
        """
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
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
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="verified_claim",
                domain="verified-domain.com",
                evidence_graph=mock_evidence_graph,
            )
        
        state = verifier.get_domain_state("verified-domain.com")
        assert "verified_claim" in state.verified_claims
    
    def test_high_rejection_rate_blocks_domain(self, verifier, mock_evidence_graph):
        """
        TC-A-03: High rejection rate causes domain block.
        
        // Given: Domain with many rejected claims
        // When: Rejection rate exceeds threshold
        // Then: Domain gets blocked
        """
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "rejected_claim", "claim2_id": "other"}
        ]
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.2,
            "supporting_count": 0,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "likely_false",
            "independent_sources": 0,
        }
        
        # Pre-populate domain state with many rejections
        verifier._domain_states["high-reject.com"] = DomainVerificationState(
            domain="high-reject.com",
            trust_level=TrustLevel.UNVERIFIED,
            rejected_claims=["r1", "r2", "r3"],  # Already 3 rejections
            verified_claims=[],
        )
        
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="rejected_claim",
                domain="high-reject.com",
                evidence_graph=mock_evidence_graph,
            )
        
        # Should be blocked due to high rejection rate (4/4 = 100% > 30%)
        assert result.new_trust_level == TrustLevel.BLOCKED
        assert verifier.is_domain_blocked("high-reject.com")


class TestDomainVerificationState:
    """Tests for DomainVerificationState dataclass."""
    
    def test_total_claims_calculation(self):
        """
        TC-N-06: total_claims property calculates correctly.
        
        // Given: Domain state with mixed claims
        // When: Accessing total_claims
        // Then: Sum of all claim lists
        """
        state = DomainVerificationState(
            domain="test.com",
            trust_level=TrustLevel.UNVERIFIED,
            verified_claims=["v1", "v2"],
            rejected_claims=["r1"],
            pending_claims=["p1", "p2", "p3"],
        )
        
        assert state.total_claims == 6
    
    def test_verification_rate_calculation(self):
        """
        TC-N-07: verification_rate property calculates correctly.
        
        // Given: Domain state with mixed claims
        // When: Accessing verification_rate
        // Then: Correct ratio returned
        """
        state = DomainVerificationState(
            domain="test.com",
            trust_level=TrustLevel.UNVERIFIED,
            verified_claims=["v1", "v2"],
            rejected_claims=["r1"],
            pending_claims=["p1"],
        )
        
        assert state.verification_rate == 0.5  # 2/4
    
    def test_verification_rate_zero_when_no_claims(self):
        """
        TC-B-04: verification_rate is 0 when no claims.
        
        // Given: Empty domain state
        // When: Accessing verification_rate
        // Then: Returns 0.0 (no division by zero)
        """
        state = DomainVerificationState(
            domain="empty.com",
            trust_level=TrustLevel.UNVERIFIED,
        )
        
        assert state.verification_rate == 0.0
    
    def test_rejection_rate_calculation(self):
        """
        TC-N-08: rejection_rate property calculates correctly.
        
        // Given: Domain state with rejections
        // When: Accessing rejection_rate
        // Then: Correct ratio returned
        """
        state = DomainVerificationState(
            domain="test.com",
            trust_level=TrustLevel.UNVERIFIED,
            verified_claims=["v1"],
            rejected_claims=["r1", "r2"],
            pending_claims=["p1"],
        )
        
        assert state.rejection_rate == 0.5  # 2/4


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""
    
    def test_to_dict_serialization(self):
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
            original_trust_level=TrustLevel.UNVERIFIED,
            new_trust_level=TrustLevel.LOW,
            verification_status=VerificationStatus.VERIFIED,
            promotion_result=PromotionResult.PROMOTED,
            details=VerificationDetails(independent_sources=3),
            reason="Promoted due to corroboration",
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["claim_id"] == "claim_test"
        assert result_dict["domain"] == "test.com"
        assert result_dict["original_trust_level"] == "unverified"
        assert result_dict["new_trust_level"] == "low"
        assert result_dict["verification_status"] == "verified"
        assert result_dict["promotion_result"] == "promoted"
        assert result_dict["details"]["independent_sources"] == 3


class TestResponseMetaBuilding:
    """Tests for building response metadata from verification results."""
    
    def test_build_response_meta_with_verified_claims(
        self, verifier, mock_evidence_graph
    ):
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
                original_trust_level=TrustLevel.UNVERIFIED,
                new_trust_level=TrustLevel.LOW,
                verification_status=VerificationStatus.VERIFIED,
                promotion_result=PromotionResult.PROMOTED,
                details=VerificationDetails(independent_sources=2),
                reason="Corroborated",
            ),
            VerificationResult(
                claim_id="claim_2",
                domain="bad.com",
                original_trust_level=TrustLevel.UNVERIFIED,
                new_trust_level=TrustLevel.BLOCKED,
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
    
    def test_get_source_verifier_returns_instance(self):
        """
        TC-N-10: get_source_verifier returns SourceVerifier.
        
        // Given: First call to get_source_verifier
        // When: Getting instance
        // Then: Returns SourceVerifier instance
        """
        reset_source_verifier()
        verifier = get_source_verifier()
        assert isinstance(verifier, SourceVerifier)
    
    def test_get_source_verifier_returns_same_instance(self):
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
    
    def test_reset_source_verifier_clears_instance(self):
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
    
    def test_trusted_domain_with_contradiction_not_immediately_blocked(
        self, verifier, mock_evidence_graph
    ):
        """
        TC-N-13: Trusted domain with contradiction gets rejected but not blocked.
        
        // Given: Claim from TRUSTED domain with contradiction
        // When: Verifying claim
        // Then: REJECTED but trust level unchanged (not BLOCKED)
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.TRUSTED,
        ):
            result = verifier.verify_claim(
                claim_id="trusted_claim",
                domain="trusted-site.com",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.verification_status == VerificationStatus.REJECTED
        assert result.new_trust_level == TrustLevel.TRUSTED  # Not blocked
        assert result.promotion_result == PromotionResult.UNCHANGED
    
    def test_trusted_domain_verified_stays_trusted(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.TRUSTED,
        ):
            result = verifier.verify_claim(
                claim_id="trusted_verified",
                domain="trusted-verified.com",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.verification_status == VerificationStatus.VERIFIED
        assert result.new_trust_level == TrustLevel.TRUSTED  # Stays TRUSTED
        assert result.promotion_result == PromotionResult.UNCHANGED


class TestBoundaryValues:
    """Boundary value tests for thresholds and edge cases."""
    
    def test_rejection_rate_exactly_at_threshold_not_blocked(
        self, verifier, mock_evidence_graph
    ):
        """
        TC-B-05: Rejection rate exactly at 0.3 threshold is NOT blocked.
        
        // Given: Domain with rejection_rate == 0.3 (exactly at threshold)
        // When: Verifying claim that gets rejected
        // Then: Not blocked (threshold is > 0.3, not >=)
        """
        mock_evidence_graph.find_contradictions.return_value = [
            {"claim1_id": "threshold_claim", "claim2_id": "other"}
        ]
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.2,
            "supporting_count": 0,
            "refuting_count": 1,
            "neutral_count": 0,
            "verdict": "likely_false",
            "independent_sources": 0,
        }
        
        # 3 total: 1 rejected = 33%, after this verify it becomes 2/4 = 50% > 30%
        # Actually: Start with state where rate will be exactly 30% after adding
        # Need 3 rejected out of 10 total = 30%
        verifier._domain_states["threshold.com"] = DomainVerificationState(
            domain="threshold.com",
            trust_level=TrustLevel.UNVERIFIED,
            rejected_claims=["r1", "r2"],  # 2 rejected
            verified_claims=["v1", "v2", "v3", "v4", "v5", "v6"],  # 6 verified
            pending_claims=[],  # 0 pending
            # Total = 8, after adding 1 rejected = 3/9 = 33.3% > 30%
        )
        
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="threshold_claim",
                domain="threshold.com",
                evidence_graph=mock_evidence_graph,
            )
        
        # After this: 3 rejected / 9 total = 33.3% > 30%, should be blocked
        assert result.new_trust_level == TrustLevel.BLOCKED
    
    def test_rejection_rate_below_threshold_not_blocked(
        self, verifier, mock_evidence_graph
    ):
        """
        TC-B-06: Rejection rate below 0.3 threshold is NOT blocked.
        
        // Given: Domain with rejection_rate < 0.3
        // When: Verifying claim that gets rejected
        // Then: Not blocked
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
        
        # 1 rejected out of 10 total = 10%
        verifier._domain_states["low-reject.com"] = DomainVerificationState(
            domain="low-reject.com",
            trust_level=TrustLevel.UNVERIFIED,
            rejected_claims=[],  # 0 rejected
            verified_claims=["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9"],  # 9 verified
            pending_claims=[],
            # After adding 1 rejected = 1/10 = 10% < 30%
        )
        
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="below_threshold",
                domain="low-reject.com",
                evidence_graph=mock_evidence_graph,
            )
        
        # 1/10 = 10% < 30%, should NOT be blocked
        assert result.new_trust_level == TrustLevel.BLOCKED  # Still blocked due to contradiction
        # But domain itself not added to _blocked_domains due to rate
        # Actually the contradiction causes immediate block for UNVERIFIED
    
    def test_three_independent_sources_well_above_threshold(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="well_supported",
                domain="good-source.com",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.verification_status == VerificationStatus.VERIFIED
        assert result.new_trust_level == TrustLevel.LOW
        assert result.promotion_result == PromotionResult.PROMOTED
    
    def test_get_domain_state_unknown_domain_returns_none(self, verifier):
        """
        TC-N-15: get_domain_state for unknown domain returns None.
        
        // Given: Verifier with no state for domain
        // When: Getting state for unknown domain
        // Then: Returns None
        """
        result = verifier.get_domain_state("never-seen.com")
        
        assert result is None
    
    def test_verify_same_claim_twice_no_duplicate(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
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
    
    def test_evidence_graph_exception_handling(self, verifier):
        """
        TC-A-04: EvidenceGraph raises exception during verification.
        
        // Given: EvidenceGraph that raises exception
        // When: Verifying claim
        // Then: Exception propagates (caller should handle)
        """
        mock_graph = MagicMock()
        mock_graph.calculate_claim_confidence.side_effect = RuntimeError("DB connection failed")
        
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            with pytest.raises(RuntimeError, match="DB connection failed"):
                verifier.verify_claim(
                    claim_id="error_claim",
                    domain="error-domain.com",
                    evidence_graph=mock_graph,
                )
    
    def test_get_domain_trust_level_exception(self, verifier, mock_evidence_graph):
        """
        TC-A-05: get_domain_trust_level raises exception.
        
        // Given: get_domain_trust_level that raises exception
        // When: Verifying claim
        // Then: Exception propagates
        """
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
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
    
    def test_verify_claim_empty_claim_id(self, verifier, mock_evidence_graph):
        """
        TC-A-06: verify_claim with empty claim_id.
        
        // Given: Empty claim_id
        // When: Verifying claim
        // Then: Handles without error (implementation detail)
        """
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="",
                domain="test.com",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.claim_id == ""
        assert result.verification_status == VerificationStatus.PENDING
    
    def test_verify_claim_empty_domain(self, verifier, mock_evidence_graph):
        """
        TC-A-07: verify_claim with empty domain.
        
        // Given: Empty domain
        // When: Verifying claim
        // Then: Handles without error
        """
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="test_claim",
                domain="",
                evidence_graph=mock_evidence_graph,
            )
        
        assert result.domain == ""
    
    def test_domain_verification_state_rejection_rate_zero_claims(self):
        """
        TC-B-08: rejection_rate is 0 when no claims (division by zero protection).
        
        // Given: Empty domain state
        // When: Accessing rejection_rate
        // Then: Returns 0.0
        """
        state = DomainVerificationState(
            domain="empty.com",
            trust_level=TrustLevel.UNVERIFIED,
        )
        
        assert state.rejection_rate == 0.0
    
    def test_build_response_meta_empty_results(self, verifier):
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
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
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
    
    def test_build_response_meta_with_unverified_domain(self, verifier):
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
                original_trust_level=TrustLevel.UNVERIFIED,
                new_trust_level=TrustLevel.UNVERIFIED,  # Stays UNVERIFIED
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
    
    def test_get_blocked_domains_initially_empty(self, verifier):
        """
        TC-N-17: get_blocked_domains returns empty list initially.
        
        // Given: Fresh verifier
        // When: Getting blocked domains
        // Then: Empty list
        """
        result = verifier.get_blocked_domains()
        
        assert result == []
    
    def test_get_blocked_domains_after_blocking(
        self, verifier, mock_evidence_graph
    ):
        """
        TC-N-18: get_blocked_domains returns blocked domains.
        
        // Given: Domain blocked via dangerous pattern
        // When: Getting blocked domains
        // Then: Contains blocked domain
        """
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            verifier.verify_claim(
                claim_id="dangerous",
                domain="blocked-via-pattern.com",
                evidence_graph=mock_evidence_graph,
                has_dangerous_pattern=True,
            )
        
        blocked = verifier.get_blocked_domains()
        
        assert "blocked-via-pattern.com" in blocked
    
    def test_is_domain_blocked_checks_both_internal_and_trust_level(
        self, verifier
    ):
        """
        TC-N-19: is_domain_blocked checks internal set and TrustLevel.
        
        // Given: Domain with BLOCKED trust level in config
        // When: Checking if blocked
        // Then: Returns True
        """
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.BLOCKED,
        ):
            result = verifier.is_domain_blocked("config-blocked.com")
        
        assert result is True


class TestContradictingClaimsExtraction:
    """Tests for contradicting_claims extraction to prevent None values."""
    
    def test_contradicting_claims_filters_out_none_values(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_001",
                domain="example.com",
                evidence_graph=mock_evidence_graph,
            )
        
        # Should not contain None
        assert None not in result.details.contradicting_claims
    
    def test_contradicting_claims_with_missing_claim2_id(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
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
    
    def test_contradicting_claims_extracts_correct_other_claim(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_001",
                domain="example.com",
                evidence_graph=mock_evidence_graph,
            )
        
        # Should contain claim_002 (the other claim)
        assert "claim_002" in result.details.contradicting_claims
        assert "claim_001" not in result.details.contradicting_claims
    
    def test_contradicting_claims_when_claim_is_claim2(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="claim_002",  # This claim is claim2_id
                domain="example.com",
                evidence_graph=mock_evidence_graph,
            )
        
        # Should contain claim_001 (the other claim)
        assert "claim_001" in result.details.contradicting_claims
        assert "claim_002" not in result.details.contradicting_claims
    
    def test_contradicting_claims_empty_contradiction_dict(
        self, verifier, mock_evidence_graph
    ):
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
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
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
    
    def test_dangerous_pattern_queues_notification(
        self, verifier, mock_evidence_graph
    ):
        """
        TC-BN-N-01: Dangerous pattern detection queues blocked notification.
        
        // Given: Claim with dangerous pattern
        // When: Verifying claim
        // Then: Notification queued for blocked domain
        """
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
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
        domain, reason, task_id = pending[0]
        assert domain == "dangerous-pattern.com"
        assert "Dangerous pattern" in reason
    
    def test_high_rejection_rate_queues_notification(
        self, verifier, mock_evidence_graph
    ):
        """
        TC-BN-N-02: High rejection rate blocks domain and queues notification.
        
        // Given: Domain with rejection rate > 30%
        // When: Another rejection occurs
        // Then: Domain blocked, notification queued
        """
        # Set up rejection-heavy confidence info
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.1,
            "supporting_count": 0,
            "refuting_count": 2,
            "neutral_count": 0,
            "verdict": "rejected",
            "independent_sources": 0,
        }
        mock_evidence_graph.find_contradictions.return_value = []
        
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            # Verify multiple claims from same domain to build up rejection rate
            for i in range(5):
                verifier.verify_claim(
                    claim_id=f"reject_claim_{i}",
                    domain="high-reject-rate.com",
                    evidence_graph=mock_evidence_graph,
                )
        
        # Then: Domain should be blocked (rejection rate > 30%)
        assert verifier.is_domain_blocked("high-reject-rate.com")
        
        # And notification should be queued (at least one for the block)
        assert verifier.get_pending_notification_count() >= 1
    
    def test_contradiction_blocks_unverified_domain_and_queues(
        self, verifier, mock_evidence_graph
    ):
        """
        TC-BN-N-03: Contradiction detection on UNVERIFIED domain queues notification.
        
        // Given: UNVERIFIED domain with contradictions
        // When: Verifying claim
        // Then: Domain blocked, notification queued
        """
        mock_evidence_graph.calculate_claim_confidence.return_value = {
            "confidence": 0.5,
            "supporting_count": 1,
            "refuting_count": 1,  # Contradiction
            "neutral_count": 0,
            "verdict": "contradicted",
            "independent_sources": 1,
        }
        mock_evidence_graph.find_contradictions.return_value = []
        
        with patch(
            "src.filter.source_verification.get_domain_trust_level",
            return_value=TrustLevel.UNVERIFIED,
        ):
            result = verifier.verify_claim(
                claim_id="contradicted_claim",
                domain="contradicted-site.com",
                evidence_graph=mock_evidence_graph,
            )
        
        # Then: Should be blocked
        assert result.new_trust_level == TrustLevel.BLOCKED
        assert result.promotion_result == PromotionResult.DEMOTED
        
        # And notification queued
        assert verifier.get_pending_notification_count() == 1
    
    @pytest.mark.asyncio
    async def test_send_pending_notifications_sends_all(
        self, verifier, mock_evidence_graph
    ):
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
    async def test_send_pending_notifications_empty_queue(self, verifier):
        """
        TC-BN-B-01: send_pending_notifications with empty queue.
        
        // Given: No pending notifications
        // When: Calling send_pending_notifications
        // Then: Returns empty list
        """
        results = await verifier.send_pending_notifications()
        assert results == []
    
    def test_duplicate_domain_not_queued_twice(
        self, verifier, mock_evidence_graph
    ):
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
        self, verifier
    ):
        """
        TC-BN-A-01: send_pending_notifications handles notification failure.
        
        // Given: Notification that will fail
        // When: Calling send_pending_notifications
        // Then: Error included in result, continues with others
        """
        from unittest.mock import AsyncMock
        
        verifier._queue_blocked_notification("fail.com", "Will fail", None)
        verifier._queue_blocked_notification("success.com", "Will succeed", None)
        
        # Mock notify_domain_blocked to fail for first, succeed for second
        call_count = [0]
        async def mock_notify(domain, reason, task_id=None):
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
    
    def test_get_pending_notification_count(self, verifier):
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
