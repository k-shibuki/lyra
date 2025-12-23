"""
Tests for feedback MCP tool (Phase 6.2).

Test matrix based on P_EVIDENCE_SYSTEM.md テスト観点表（Task 6.2 feedback）:

| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|---------------------|-------------|-----------------|-------|
| **domain_block** | | | | |
| TC-DB-01 | Valid pattern `example.com` | Normal | rule_id returned, DB persisted | |
| TC-DB-02 | Glob pattern `*.example.com` | Normal | Same as above | |
| TC-DB-03 | Forbidden pattern `*` | Abnormal | InvalidParamsError | |
| TC-DB-04 | Forbidden pattern `*.com` | Abnormal | InvalidParamsError | |
| TC-DB-05 | reason unspecified | Abnormal | InvalidParamsError (reason required) | |
| TC-DB-06 | Empty string `""` | Boundary | InvalidParamsError | |
| **domain_unblock** | | | | |
| TC-DU-01 | Unblock blocked domain | Normal | rule_id returned, removed from blocked_domains | |
| TC-DU-02 | Unblock non-blocked domain | Normal | rule_id returned (idempotent) | |
| **domain_clear_override** | | | | |
| TC-DC-01 | Clear existing override | Normal | cleared_rules=1 | |
| TC-DC-02 | Non-existing pattern | Normal | cleared_rules=0 (idempotent) | |
| **claim_reject** | | | | |
| TC-CR-01 | Valid claim_id | Normal | adoption_status="not_adopted" | |
| TC-CR-02 | Non-existing claim_id | Abnormal | ResourceNotFoundError | |
| TC-CR-03 | reason unspecified | Abnormal | InvalidParamsError | |
| TC-CR-04 | Already rejected claim | Normal | Idempotent (no change) | |
| **claim_restore** | | | | |
| TC-CS-01 | Restore rejected claim | Normal | adoption_status="adopted" | |
| TC-CS-02 | Restore already adopted claim | Normal | Idempotent | |
| TC-CS-03 | Non-existing claim_id | Abnormal | ResourceNotFoundError | |
| **edge_correct** | | | | |
| TC-EC-01 | supports → refutes | Normal | relation updated, nli_corrections accumulated | |
| TC-EC-02 | Same label (supports → supports) | Normal | No change but sample accumulated | ground-truth collection |
| TC-EC-03 | Non-existing edge_id | Abnormal | ResourceNotFoundError | |
| TC-EC-04 | Invalid relation `"unknown"` | Abnormal | InvalidParamsError | |
| TC-EC-05 | 3-class: supports | Normal | | |
| TC-EC-06 | 3-class: refutes | Normal | | |
| TC-EC-07 | 3-class: neutral | Normal | | |
"""

import uuid
from typing import Any

import pytest

from src.mcp.errors import InvalidParamsError, ResourceNotFoundError
from src.mcp.feedback_handler import (
    _validate_domain_pattern,
    handle_feedback_action,
)

# ============================================================
# Domain Pattern Validation Tests
# ============================================================


class TestDomainPatternValidation:
    """Tests for domain pattern validation."""

    def test_valid_domain_pattern(self) -> None:
        """
        TC-DB-01/02: Valid domain patterns should not raise.

        // Given: Valid domain patterns
        // When: Validating pattern
        // Then: No exception raised
        """
        # Should not raise
        _validate_domain_pattern("example.com")
        _validate_domain_pattern("*.example.com")
        _validate_domain_pattern("sub.example.com")

    def test_forbidden_pattern_star(self) -> None:
        """
        TC-DB-03: Forbidden pattern `*` should raise InvalidParamsError.

        // Given: Forbidden pattern "*"
        // When: Validating pattern
        // Then: InvalidParamsError raised
        """
        with pytest.raises(InvalidParamsError) as exc_info:
            _validate_domain_pattern("*")

        assert "Forbidden domain pattern" in str(exc_info.value)

    def test_forbidden_pattern_tld(self) -> None:
        """
        TC-DB-04: Forbidden TLD patterns should raise InvalidParamsError.

        // Given: Forbidden TLD patterns
        // When: Validating pattern
        // Then: InvalidParamsError raised
        """
        for pattern in ["*.com", "*.org", "*.net", "*.gov", "*.edu", "*.co.jp"]:
            with pytest.raises(InvalidParamsError) as exc_info:
                _validate_domain_pattern(pattern)

            assert "Forbidden domain pattern" in str(exc_info.value)

    def test_empty_pattern(self) -> None:
        """
        TC-DB-06: Empty pattern should raise InvalidParamsError.

        // Given: Empty or whitespace-only pattern
        // When: Validating pattern
        // Then: InvalidParamsError raised
        """
        with pytest.raises(InvalidParamsError):
            _validate_domain_pattern("")

        with pytest.raises(InvalidParamsError):
            _validate_domain_pattern("   ")


# ============================================================
# Domain Block Tests
# ============================================================


@pytest.mark.asyncio
class TestDomainBlock:
    """Tests for domain_block action."""

    async def test_domain_block_valid(self, test_database: Any) -> None:
        """
        TC-DB-01: Valid domain pattern should be blocked.

        // Given: Valid domain pattern and reason
        // When: Calling domain_block
        // Then: Rule created, event logged
        """
        result = await handle_feedback_action(
            "domain_block",
            {
                "domain_pattern": "example.com",
                "reason": "Test block reason",
            },
        )

        assert result["ok"] is True
        assert result["action"] == "domain_block"
        assert result["domain_pattern"] == "example.com"
        assert result["rule_id"].startswith("dor_")

        # Verify DB persistence
        db = test_database
        rule = await db.fetch_one(
            "SELECT * FROM domain_override_rules WHERE id = ?",
            (result["rule_id"],),
        )
        assert rule is not None
        assert rule["decision"] == "block"
        assert rule["reason"] == "Test block reason"

    async def test_domain_block_glob_pattern(self, test_database: Any) -> None:
        """
        TC-DB-02: Glob pattern should be blocked.

        // Given: Glob domain pattern
        // When: Calling domain_block
        // Then: Rule created
        """
        result = await handle_feedback_action(
            "domain_block",
            {
                "domain_pattern": "*.example.com",
                "reason": "Block all subdomains",
            },
        )

        assert result["ok"] is True
        assert result["domain_pattern"] == "*.example.com"

    async def test_domain_block_forbidden_pattern(self, test_database: Any) -> None:
        """
        TC-DB-03: Forbidden pattern should raise error.

        // Given: Forbidden pattern
        // When: Calling domain_block
        // Then: InvalidParamsError raised
        """
        with pytest.raises(InvalidParamsError) as exc_info:
            await handle_feedback_action(
                "domain_block",
                {
                    "domain_pattern": "*",
                    "reason": "Block everything",
                },
            )

        assert "Forbidden domain pattern" in str(exc_info.value)

    async def test_domain_block_no_reason(self, test_database: Any) -> None:
        """
        TC-DB-05: Missing reason should raise error.

        // Given: Valid pattern but no reason
        // When: Calling domain_block
        // Then: InvalidParamsError raised
        """
        with pytest.raises(InvalidParamsError) as exc_info:
            await handle_feedback_action(
                "domain_block",
                {
                    "domain_pattern": "example.com",
                },
            )

        assert "reason is required" in str(exc_info.value)


# ============================================================
# Domain Unblock Tests
# ============================================================


@pytest.mark.asyncio
class TestDomainUnblock:
    """Tests for domain_unblock action."""

    async def test_domain_unblock_valid(self, test_database: Any) -> None:
        """
        TC-DU-01: Valid domain should be unblocked.

        // Given: Domain pattern and reason
        // When: Calling domain_unblock
        // Then: Rule created with decision=unblock
        """
        result = await handle_feedback_action(
            "domain_unblock",
            {
                "domain_pattern": "example.com",
                "reason": "Verified safe domain",
            },
        )

        assert result["ok"] is True
        assert result["action"] == "domain_unblock"
        assert result["domain_pattern"] == "example.com"
        assert result["rule_id"].startswith("dor_")

        # Verify DB
        db = test_database
        rule = await db.fetch_one(
            "SELECT * FROM domain_override_rules WHERE id = ?",
            (result["rule_id"],),
        )
        assert rule["decision"] == "unblock"

    async def test_domain_unblock_non_blocked(self, test_database: Any) -> None:
        """
        TC-DU-02: Unblocking non-blocked domain should be idempotent.

        // Given: Domain that was never blocked
        // When: Calling domain_unblock
        // Then: Rule created (idempotent)
        """
        result = await handle_feedback_action(
            "domain_unblock",
            {
                "domain_pattern": "never-blocked.com",
                "reason": "Confirming safe",
            },
        )

        assert result["ok"] is True
        assert result["rule_id"].startswith("dor_")


# ============================================================
# Domain Clear Override Tests
# ============================================================


@pytest.mark.asyncio
class TestDomainClearOverride:
    """Tests for domain_clear_override action."""

    async def test_domain_clear_override_existing(self, test_database: Any) -> None:
        """
        TC-DC-01: Existing override should be cleared.

        // Given: Active override rule
        // When: Calling domain_clear_override
        // Then: Rule deactivated, cleared_rules=1
        """
        db = test_database

        # First create an override
        await handle_feedback_action(
            "domain_block",
            {
                "domain_pattern": "test-clear.com",
                "reason": "Initial block",
            },
        )

        # Then clear it
        result = await handle_feedback_action(
            "domain_clear_override",
            {
                "domain_pattern": "test-clear.com",
                "reason": "No longer needed",
            },
        )

        assert result["ok"] is True
        assert result["action"] == "domain_clear_override"
        assert result["cleared_rules"] >= 1

        # Verify rule is deactivated
        rule = await db.fetch_one(
            "SELECT * FROM domain_override_rules WHERE domain_pattern = ? AND is_active = 1",
            ("test-clear.com",),
        )
        assert rule is None  # Should be deactivated

    async def test_domain_clear_override_non_existing(self, test_database: Any) -> None:
        """
        TC-DC-02: Non-existing pattern should return cleared_rules=0.

        // Given: Pattern with no override
        // When: Calling domain_clear_override
        // Then: cleared_rules=0 (idempotent)
        """
        result = await handle_feedback_action(
            "domain_clear_override",
            {
                "domain_pattern": "never-existed.com",
                "reason": "Cleanup",
            },
        )

        assert result["ok"] is True
        assert result["cleared_rules"] == 0


# ============================================================
# Claim Reject Tests
# ============================================================


@pytest.mark.asyncio
class TestClaimReject:
    """Tests for claim_reject action."""

    async def test_claim_reject_valid(self, test_database: Any) -> None:
        """
        TC-CR-01: Valid claim should be rejected.

        // Given: Existing claim
        // When: Calling claim_reject
        // Then: adoption_status set to 'not_adopted'
        """
        db = test_database
        claim_id = f"claim_{uuid.uuid4().hex[:8]}"
        task_id = "test-task"

        # Create test task (for foreign key constraint)
        await db.execute(
            "INSERT INTO tasks (id, query) VALUES (?, ?)",
            (task_id, "Test query"),
        )

        # Create test claim
        await db.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, claim_confidence, claim_adoption_status)
            VALUES (?, ?, 'Test claim text', 0.8, 'adopted')
            """,
            (claim_id, task_id),
        )

        result = await handle_feedback_action(
            "claim_reject",
            {
                "claim_id": claim_id,
                "reason": "Factually incorrect",
            },
        )

        assert result["ok"] is True
        assert result["action"] == "claim_reject"
        assert result["claim_id"] == claim_id

        # Verify DB update
        claim = await db.fetch_one(
            "SELECT * FROM claims WHERE id = ?",
            (claim_id,),
        )
        assert claim["claim_adoption_status"] == "not_adopted"
        assert claim["claim_rejection_reason"] == "Factually incorrect"
        assert claim["claim_rejected_at"] is not None

    async def test_claim_reject_not_found(self, test_database: Any) -> None:
        """
        TC-CR-02: Non-existing claim should raise error.

        // Given: Non-existing claim_id
        // When: Calling claim_reject
        // Then: ResourceNotFoundError raised
        """
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await handle_feedback_action(
                "claim_reject",
                {
                    "claim_id": "nonexistent-claim",
                    "reason": "Test reason",
                },
            )

        assert "Claim not found" in str(exc_info.value)

    async def test_claim_reject_no_reason(self, test_database: Any) -> None:
        """
        TC-CR-03: Missing reason should raise error.

        // Given: Valid claim but no reason
        // When: Calling claim_reject
        // Then: InvalidParamsError raised
        """
        with pytest.raises(InvalidParamsError) as exc_info:
            await handle_feedback_action(
                "claim_reject",
                {
                    "claim_id": "some-claim",
                },
            )

        assert "reason is required" in str(exc_info.value)

    async def test_claim_reject_already_rejected(self, test_database: Any) -> None:
        """
        TC-CR-04: Rejecting already rejected claim should be idempotent.

        // Given: Already rejected claim
        // When: Calling claim_reject again
        // Then: Success (idempotent)
        """
        db = test_database
        claim_id = f"claim_{uuid.uuid4().hex[:8]}"
        task_id = "test-task"

        # Create test task (for foreign key constraint)
        await db.execute(
            "INSERT INTO tasks (id, query) VALUES (?, ?)",
            (task_id, "Test query"),
        )

        # Create already rejected claim
        await db.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, claim_confidence, claim_adoption_status)
            VALUES (?, ?, 'Already rejected', 0.5, 'not_adopted')
            """,
            (claim_id, task_id),
        )

        result = await handle_feedback_action(
            "claim_reject",
            {
                "claim_id": claim_id,
                "reason": "Rejecting again",
            },
        )

        assert result["ok"] is True


# ============================================================
# Claim Restore Tests
# ============================================================


@pytest.mark.asyncio
class TestClaimRestore:
    """Tests for claim_restore action."""

    async def test_claim_restore_rejected(self, test_database: Any) -> None:
        """
        TC-CS-01: Rejected claim should be restored.

        // Given: Rejected claim
        // When: Calling claim_restore
        // Then: adoption_status set to 'adopted'
        """
        db = test_database
        claim_id = f"claim_{uuid.uuid4().hex[:8]}"
        task_id = "test-task"

        # Create test task (for foreign key constraint)
        await db.execute(
            "INSERT INTO tasks (id, query) VALUES (?, ?)",
            (task_id, "Test query"),
        )

        # Create rejected claim
        await db.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, claim_confidence, claim_adoption_status,
                               claim_rejection_reason, claim_rejected_at)
            VALUES (?, ?, 'Rejected claim', 0.5, 'not_adopted', 'Some reason', datetime('now'))
            """,
            (claim_id, task_id),
        )

        result = await handle_feedback_action(
            "claim_restore",
            {
                "claim_id": claim_id,
            },
        )

        assert result["ok"] is True
        assert result["action"] == "claim_restore"
        assert result["claim_id"] == claim_id

        # Verify DB update
        claim = await db.fetch_one(
            "SELECT * FROM claims WHERE id = ?",
            (claim_id,),
        )
        assert claim["claim_adoption_status"] == "adopted"
        assert claim["claim_rejection_reason"] is None
        assert claim["claim_rejected_at"] is None

    async def test_claim_restore_already_adopted(self, test_database: Any) -> None:
        """
        TC-CS-02: Restoring already adopted claim should be idempotent.

        // Given: Already adopted claim
        // When: Calling claim_restore
        // Then: Success (idempotent)
        """
        db = test_database
        claim_id = f"claim_{uuid.uuid4().hex[:8]}"
        task_id = "test-task"

        # Create test task (for foreign key constraint)
        await db.execute(
            "INSERT INTO tasks (id, query) VALUES (?, ?)",
            (task_id, "Test query"),
        )

        # Create adopted claim
        await db.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, claim_confidence, claim_adoption_status)
            VALUES (?, ?, 'Adopted claim', 0.8, 'adopted')
            """,
            (claim_id, task_id),
        )

        result = await handle_feedback_action(
            "claim_restore",
            {
                "claim_id": claim_id,
            },
        )

        assert result["ok"] is True

    async def test_claim_restore_not_found(self, test_database: Any) -> None:
        """
        TC-CS-03: Non-existing claim should raise error.

        // Given: Non-existing claim_id
        // When: Calling claim_restore
        // Then: ResourceNotFoundError raised
        """
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await handle_feedback_action(
                "claim_restore",
                {
                    "claim_id": "nonexistent-claim",
                },
            )

        assert "Claim not found" in str(exc_info.value)


# ============================================================
# Edge Correct Tests
# ============================================================


@pytest.mark.asyncio
class TestEdgeCorrect:
    """Tests for edge_correct action."""

    async def test_edge_correct_change_relation(self, test_database: Any) -> None:
        """
        TC-EC-01: Edge relation should be changed and sample accumulated.

        // Given: Edge with supports relation
        // When: Correcting to refutes
        // Then: Relation updated, nli_corrections entry created
        """
        db = test_database
        edge_id = f"edge_{uuid.uuid4().hex[:8]}"
        claim_id = f"claim_{uuid.uuid4().hex[:8]}"
        frag_id = f"frag_{uuid.uuid4().hex[:8]}"

        # Create task
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES ('test-task', 'test', 'running')"
        )

        # Create claim
        await db.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, claim_confidence)
            VALUES (?, 'test-task', 'Test claim', 0.8)
            """,
            (claim_id,),
        )

        # Create fragment (we need a page first)
        await db.execute(
            "INSERT INTO pages (id, url, domain) VALUES ('page-1', 'https://example.com', 'example.com')"
        )
        await db.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content)
            VALUES (?, 'page-1', 'paragraph', 'Test fragment text')
            """,
            (frag_id,),
        )

        # Create edge
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id,
                             relation, nli_label, nli_confidence)
            VALUES (?, 'fragment', ?, 'claim', ?, 'supports', 'supports', 0.7)
            """,
            (edge_id, frag_id, claim_id),
        )

        result = await handle_feedback_action(
            "edge_correct",
            {
                "edge_id": edge_id,
                "correct_relation": "refutes",
                "reason": "Actually contradicts the claim",
            },
        )

        assert result["ok"] is True
        assert result["action"] == "edge_correct"
        assert result["edge_id"] == edge_id
        assert result["previous_relation"] == "supports"
        assert result["new_relation"] == "refutes"
        assert result["sample_id"].startswith("nlc_")

        # Verify edge update
        edge = await db.fetch_one(
            "SELECT * FROM edges WHERE id = ?",
            (edge_id,),
        )
        assert edge["relation"] == "refutes"
        assert edge["nli_label"] == "refutes"
        assert edge["nli_confidence"] == 1.0
        assert edge["edge_human_corrected"] == 1

        # Verify nli_corrections entry
        correction = await db.fetch_one(
            "SELECT * FROM nli_corrections WHERE edge_id = ?",
            (edge_id,),
        )
        assert correction is not None
        assert correction["predicted_label"] == "supports"
        assert correction["correct_label"] == "refutes"

    async def test_edge_correct_same_label(self, test_database: Any) -> None:
        """
        TC-EC-02: Same label should still accumulate sample.

        // Given: Edge with supports relation
        // When: Confirming supports (same label)
        // Then: Sample accumulated for ground-truth collection
        """
        db = test_database
        edge_id = f"edge_{uuid.uuid4().hex[:8]}"
        claim_id = f"claim_{uuid.uuid4().hex[:8]}"

        # Create minimal test data
        await db.execute(
            "INSERT OR IGNORE INTO tasks (id, query, status) VALUES ('test-task', 'test', 'running')"
        )
        await db.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, claim_confidence)
            VALUES (?, 'test-task', 'Test claim', 0.8)
            """,
            (claim_id,),
        )
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id,
                             relation, nli_label, nli_confidence)
            VALUES (?, 'fragment', 'frag-1', 'claim', ?, 'supports', 'supports', 0.9)
            """,
            (edge_id, claim_id),
        )

        result = await handle_feedback_action(
            "edge_correct",
            {
                "edge_id": edge_id,
                "correct_relation": "supports",  # Same as current
            },
        )

        assert result["ok"] is True
        assert result["previous_relation"] == "supports"
        assert result["new_relation"] == "supports"

        # Sample should still be accumulated
        correction = await db.fetch_one(
            "SELECT * FROM nli_corrections WHERE edge_id = ?",
            (edge_id,),
        )
        assert correction is not None

    async def test_edge_correct_not_found(self, test_database: Any) -> None:
        """
        TC-EC-03: Non-existing edge should raise error.

        // Given: Non-existing edge_id
        // When: Calling edge_correct
        // Then: ResourceNotFoundError raised
        """
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await handle_feedback_action(
                "edge_correct",
                {
                    "edge_id": "nonexistent-edge",
                    "correct_relation": "refutes",
                },
            )

        assert "Edge not found" in str(exc_info.value)

    async def test_edge_correct_invalid_relation(self, test_database: Any) -> None:
        """
        TC-EC-04: Invalid relation should raise error.

        // Given: Invalid relation value
        // When: Calling edge_correct
        // Then: InvalidParamsError raised
        """
        with pytest.raises(InvalidParamsError) as exc_info:
            await handle_feedback_action(
                "edge_correct",
                {
                    "edge_id": "some-edge",
                    "correct_relation": "unknown",
                },
            )

        assert "Invalid correct_relation" in str(exc_info.value)

    @pytest.mark.parametrize("relation", ["supports", "refutes", "neutral"])
    async def test_edge_correct_all_three_classes(self, test_database: Any, relation: str) -> None:
        """
        TC-EC-05/06/07: All three relation classes should work.

        // Given: Edge
        // When: Correcting to each valid relation
        // Then: Correction succeeds
        """
        db = test_database
        edge_id = f"edge_{uuid.uuid4().hex[:8]}"
        claim_id = f"claim_{uuid.uuid4().hex[:8]}"

        # Create minimal test data
        await db.execute(
            "INSERT OR IGNORE INTO tasks (id, query, status) VALUES ('test-task', 'test', 'running')"
        )
        await db.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, claim_confidence)
            VALUES (?, 'test-task', 'Test claim', 0.8)
            """,
            (claim_id,),
        )
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id,
                             relation, nli_label, nli_confidence)
            VALUES (?, 'fragment', 'frag-1', 'claim', ?, 'neutral', 'neutral', 0.5)
            """,
            (edge_id, claim_id),
        )

        result = await handle_feedback_action(
            "edge_correct",
            {
                "edge_id": edge_id,
                "correct_relation": relation,
            },
        )

        assert result["ok"] is True
        assert result["new_relation"] == relation


# ============================================================
# Unknown Action Test
# ============================================================


@pytest.mark.asyncio
class TestUnknownAction:
    """Tests for unknown action handling."""

    async def test_unknown_action(self, test_database: Any) -> None:
        """
        Unknown action should raise InvalidParamsError.

        // Given: Unknown action
        // When: Calling handle_feedback_action
        // Then: InvalidParamsError raised
        """
        with pytest.raises(InvalidParamsError) as exc_info:
            await handle_feedback_action(
                "unknown_action",
                {},
            )

        assert "Unknown action" in str(exc_info.value)
