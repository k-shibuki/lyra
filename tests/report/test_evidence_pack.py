"""
Tests for Lyra Evidence Pack Generator (v2).

This suite intentionally avoids database I/O and focuses on deterministic
contracts that can be validated as pure logic.

Key change:
- v1 used CI-based "stance" and exposed CI bounds.
- v2 exposes `nli_claim_support_ratio` only (exploration score), and removes
  `stance/ci_*` from the evidence pack surface.
"""

import pytest

from src.report.evidence_pack import TOP_CLAIMS_LIMIT, EvidencePackConfig


def _ratio(support_weight: float, refute_weight: float) -> float:
    """Mirror v_claim_evidence_summary ratio formula (pseudo-count baseline)."""
    return (1.0 + support_weight) / ((1.0 + support_weight) + (1.0 + refute_weight))


class TestEvidencePackV2Basics:
    def test_top_claims_limit_constant(self) -> None:
        assert TOP_CLAIMS_LIMIT == 30

    def test_extraction_config_default_top_claims_limit(self) -> None:
        cfg = EvidencePackConfig()
        assert cfg.top_claims_limit >= TOP_CLAIMS_LIMIT


class TestNliClaimSupportRatio:
    def test_no_evidence_is_neutral_baseline(self) -> None:
        assert _ratio(0.0, 0.0) == pytest.approx(0.5)

    def test_more_support_weight_increases_ratio(self) -> None:
        assert _ratio(5.0, 0.0) > 0.5

    def test_more_refute_weight_decreases_ratio(self) -> None:
        assert _ratio(0.0, 5.0) < 0.5
