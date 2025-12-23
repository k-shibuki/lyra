"""
Tests for feedback ⇔ SourceVerifier integration .

Test matrix based on P_EVIDENCE_SYSTEM.md テスト観点表（）:

| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|---------------------|-------------|-----------------|-------|
| TC-FI-01 | domain_block call | Normal | Added to SourceVerifier._blocked_domains | wiring |
| TC-FI-02 | domain_unblock (dangerous_pattern) | Normal (TC-DU-03) | Removed from _blocked_domains | ADR-0012 |
| TC-FI-03 | domain_unblock (high_rejection_rate) | Normal | Removed from _blocked_domains | |
| TC-FI-04 | domain_unblock (manual) | Normal | Removed from _blocked_domains | |
| TC-FI-05 | get_status | Normal | domain_overrides[] contains active rules | |
| TC-FI-06 | domain_clear_override | Normal | DB deactivated | |
| TC-FI-07 | unblock non-blocked domain | Boundary | No error (idempotent) | |
"""

from typing import Any

import pytest

from src.filter.source_verification import (
    DomainBlockReason,
    get_source_verifier,
    reset_source_verifier,
)
from src.mcp.feedback_handler import handle_feedback_action

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(autouse=True)
def reset_verifier() -> None:
    """Reset SourceVerifier before each test."""
    reset_source_verifier()


# ============================================================
# TC-FI-01: domain_block → SourceVerifier wiring
# ============================================================


@pytest.mark.asyncio
class TestDomainBlockSourceVerifierWiring:
    """Tests for domain_block → SourceVerifier integration."""

    async def test_domain_block_reflects_to_source_verifier(self, test_database: Any) -> None:
        """
        TC-FI-01: domain_block should add domain to SourceVerifier._blocked_domains.

        // Given: Domain not in blocked list
        // When: Calling feedback(domain_block)
        // Then: Domain added to SourceVerifier._blocked_domains
        """
        verifier = get_source_verifier()
        domain = "blocked-test.com"

        # Precondition: domain not blocked
        assert domain not in verifier._blocked_domains

        # When
        result = await handle_feedback_action(
            "domain_block",
            {
                "domain_pattern": domain,
                "reason": "Test block via feedback",
            },
        )

        # Then: DB persisted and SourceVerifier updated
        assert result["ok"] is True
        assert domain in verifier._blocked_domains

        # Verify domain state has correct block reason
        state = verifier.get_domain_state(domain)
        assert state is not None
        assert state.is_blocked is True
        assert state.domain_block_reason == DomainBlockReason.MANUAL


# ============================================================
# TC-FI-02/03/04: domain_unblock → SourceVerifier wiring
# ============================================================


@pytest.mark.asyncio
class TestDomainUnblockSourceVerifierWiring:
    """Tests for domain_unblock → SourceVerifier integration."""

    async def test_domain_unblock_dangerous_pattern(self, test_database: Any) -> None:
        """
        TC-FI-02 (TC-DU-03): domain_unblock should unblock dangerous_pattern domain.

        Per ADR-0012: feedback(domain_unblock) can unblock any domain,
        including dangerous_pattern.

        // Given: Domain blocked with dangerous_pattern reason
        // When: Calling feedback(domain_unblock)
        // Then: Domain removed from SourceVerifier._blocked_domains
        """
        verifier = get_source_verifier()
        domain = "dangerous-test.com"

        # Block domain with dangerous_pattern reason
        verifier._mark_domain_blocked(
            domain,
            "Dangerous pattern detected (L2/L4)",
            block_reason_code=DomainBlockReason.DANGEROUS_PATTERN,
        )
        assert domain in verifier._blocked_domains

        # When: unblock via feedback
        result = await handle_feedback_action(
            "domain_unblock",
            {
                "domain_pattern": domain,
                "reason": "Manual verification: safe domain",
            },
        )

        # Then: domain unblocked
        assert result["ok"] is True
        assert domain not in verifier._blocked_domains

        # Verify domain state updated
        state = verifier.get_domain_state(domain)
        assert state is not None
        assert state.is_blocked is False

    async def test_domain_unblock_high_rejection_rate(self, test_database: Any) -> None:
        """
        TC-FI-03: domain_unblock should unblock high_rejection_rate domain.

        // Given: Domain blocked with high_rejection_rate reason
        // When: Calling feedback(domain_unblock)
        // Then: Domain removed from SourceVerifier._blocked_domains
        """
        verifier = get_source_verifier()
        domain = "high-rejection-test.com"

        # Block domain with high_rejection_rate reason
        verifier._mark_domain_blocked(
            domain,
            "High rejection rate (50%)",
            block_reason_code=DomainBlockReason.HIGH_REJECTION_RATE,
        )
        assert domain in verifier._blocked_domains

        # When
        result = await handle_feedback_action(
            "domain_unblock",
            {
                "domain_pattern": domain,
                "reason": "False positive - domain is reliable",
            },
        )

        # Then
        assert result["ok"] is True
        assert domain not in verifier._blocked_domains

    async def test_domain_unblock_manual(self, test_database: Any) -> None:
        """
        TC-FI-04: domain_unblock should unblock manual-blocked domain.

        // Given: Domain blocked manually
        // When: Calling feedback(domain_unblock)
        // Then: Domain removed from SourceVerifier._blocked_domains
        """
        verifier = get_source_verifier()
        domain = "manual-blocked-test.com"

        # Block domain manually (via block_domain_manual which sets MANUAL reason)
        verifier.block_domain_manual(domain, "User requested block")
        assert domain in verifier._blocked_domains

        # When
        result = await handle_feedback_action(
            "domain_unblock",
            {
                "domain_pattern": domain,
                "reason": "User requested unblock",
            },
        )

        # Then
        assert result["ok"] is True
        assert domain not in verifier._blocked_domains


# ============================================================
# TC-FI-05: get_status with domain_overrides
# ============================================================


@pytest.mark.asyncio
class TestGetStatusDomainOverrides:
    """Tests for get_status.domain_overrides field."""

    async def test_get_status_includes_domain_overrides(self, test_database: Any) -> None:
        """
        TC-FI-05: get_status should include domain_overrides from DB.

        // Given: Active domain override rules in DB
        // When: Calling get_status
        // Then: domain_overrides[] contains the active rules
        """
        from src.mcp.server import _handle_get_status

        db = test_database

        # Create task first
        task_id = "test-task-overrides"
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            (task_id, "Test query", "running"),
        )

        # Create override rules via feedback
        await handle_feedback_action(
            "domain_block",
            {
                "domain_pattern": "blocked-for-status.com",
                "reason": "Test override for get_status",
            },
        )

        # When: call get_status
        result = await _handle_get_status({"task_id": task_id})

        # Then: domain_overrides contains the rule
        assert result["ok"] is True
        assert "domain_overrides" in result
        overrides = result["domain_overrides"]
        assert isinstance(overrides, list)

        # Find our override
        matching = [o for o in overrides if o["domain_pattern"] == "blocked-for-status.com"]
        assert len(matching) == 1
        assert matching[0]["decision"] == "block"
        assert matching[0]["reason"] == "Test override for get_status"
        assert "rule_id" in matching[0]
        assert "updated_at" in matching[0]


# ============================================================
# TC-FI-06: domain_clear_override
# ============================================================


@pytest.mark.asyncio
class TestDomainClearOverride:
    """Tests for domain_clear_override action."""

    async def test_domain_clear_override_deactivates_rule(self, test_database: Any) -> None:
        """
        TC-FI-06: domain_clear_override should deactivate override in DB.

        // Given: Active override rule
        // When: Calling domain_clear_override
        // Then: Rule is deactivated (is_active=0)
        """
        db = test_database
        domain = "clear-override-test.com"

        # Create override
        await handle_feedback_action(
            "domain_block",
            {
                "domain_pattern": domain,
                "reason": "Initial block",
            },
        )

        # Verify rule is active
        rule = await db.fetch_one(
            "SELECT * FROM domain_override_rules WHERE domain_pattern = ? AND is_active = 1",
            (domain,),
        )
        assert rule is not None

        # When: clear override
        result = await handle_feedback_action(
            "domain_clear_override",
            {
                "domain_pattern": domain,
                "reason": "Override no longer needed",
            },
        )

        # Then: rule deactivated
        assert result["ok"] is True
        assert result["cleared_rules"] >= 1

        rule = await db.fetch_one(
            "SELECT * FROM domain_override_rules WHERE domain_pattern = ? AND is_active = 1",
            (domain,),
        )
        assert rule is None  # No active rule


# ============================================================
# TC-FI-07: Boundary cases
# ============================================================


@pytest.mark.asyncio
class TestBoundaryCases:
    """Tests for boundary cases."""

    async def test_unblock_non_blocked_domain_is_idempotent(self, test_database: Any) -> None:
        """
        TC-FI-07: unblocking a non-blocked domain should be idempotent.

        // Given: Domain not in blocked list
        // When: Calling feedback(domain_unblock)
        // Then: No error, rule created in DB
        """
        verifier = get_source_verifier()
        domain = "never-blocked.com"

        # Precondition: domain not blocked
        assert domain not in verifier._blocked_domains

        # When
        result = await handle_feedback_action(
            "domain_unblock",
            {
                "domain_pattern": domain,
                "reason": "Preemptive unblock",
            },
        )

        # Then: success (idempotent)
        assert result["ok"] is True
        assert result["rule_id"].startswith("dor_")

        # Domain still not in blocked list (was never blocked)
        assert domain not in verifier._blocked_domains


# ============================================================
# SourceVerifier API Tests (Unit)
# ============================================================


class TestSourceVerifierAPI:
    """Unit tests for SourceVerifier methods added in ."""

    def test_unblock_domain_returns_true_when_blocked(self) -> None:
        """
        unblock_domain returns True when domain was blocked.

        // Given: Domain in _blocked_domains
        // When: Calling unblock_domain
        // Then: Returns True, domain removed
        """
        verifier = get_source_verifier()
        domain = "test-unblock.com"

        # Block it first
        verifier._mark_domain_blocked(domain, "Test", block_reason_code=DomainBlockReason.MANUAL)
        assert domain in verifier._blocked_domains

        # When
        result = verifier.unblock_domain(domain)

        # Then
        assert result is True
        assert domain not in verifier._blocked_domains

    def test_unblock_domain_returns_false_when_not_blocked(self) -> None:
        """
        unblock_domain returns False when domain was not blocked.

        // Given: Domain not in _blocked_domains
        // When: Calling unblock_domain
        // Then: Returns False
        """
        verifier = get_source_verifier()
        domain = "not-blocked.com"

        # Precondition
        assert domain not in verifier._blocked_domains

        # When
        result = verifier.unblock_domain(domain)

        # Then
        assert result is False

    def test_block_domain_manual_sets_correct_reason(self) -> None:
        """
        block_domain_manual sets domain_block_reason to MANUAL.

        // Given: Domain not blocked
        // When: Calling block_domain_manual
        // Then: domain_block_reason is MANUAL
        """
        verifier = get_source_verifier()
        domain = "manual-block.com"

        # When
        verifier.block_domain_manual(domain, "Manual block reason")

        # Then
        assert domain in verifier._blocked_domains
        state = verifier.get_domain_state(domain)
        assert state is not None
        assert state.domain_block_reason == DomainBlockReason.MANUAL
        assert state.block_reason == "Manual block reason"
