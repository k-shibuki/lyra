"""
Feedback handler for human-in-the-loop corrections.

Implements 6 actions across 3 levels:
- Domain: domain_block, domain_unblock, domain_clear_override
- Claim: claim_reject, claim_restore
- Edge: edge_correct
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from src.mcp.errors import InvalidParamsError, ResourceNotFoundError
from src.storage.database import get_database
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Forbidden patterns for domain operations (ADR-0012)
FORBIDDEN_PATTERNS = [
    "*",  # All domains
    "*.com",  # TLD-level
    "*.co.jp",
    "*.org",
    "*.net",
    "*.gov",
    "*.edu",
    "**",  # Recursive glob
]


def _validate_domain_pattern(pattern: str) -> None:
    """Validate domain pattern is not forbidden.

    Args:
        pattern: Domain glob pattern.

    Raises:
        InvalidParamsError: If pattern is forbidden.
    """
    if not pattern or not pattern.strip():
        raise InvalidParamsError(
            "domain_pattern is required and cannot be empty",
            param_name="domain_pattern",
            expected="non-empty domain pattern",
        )

    pattern = pattern.strip()

    if pattern in FORBIDDEN_PATTERNS:
        raise InvalidParamsError(
            f"Forbidden domain pattern: '{pattern}'. Cannot block/unblock at TLD level.",
            param_name="domain_pattern",
            expected="specific domain pattern (e.g., 'example.com', '*.example.com')",
        )


async def handle_feedback_action(action: str, args: dict[str, Any]) -> dict[str, Any]:
    """Route feedback action to appropriate handler.

    Args:
        action: Action to perform.
        args: Action arguments.

    Returns:
        Action result.
    """
    handlers = {
        "domain_block": _handle_domain_block,
        "domain_unblock": _handle_domain_unblock,
        "domain_clear_override": _handle_domain_clear_override,
        "claim_reject": _handle_claim_reject,
        "claim_restore": _handle_claim_restore,
        "edge_correct": _handle_edge_correct,
    }

    handler = handlers.get(action)
    if handler is None:
        raise InvalidParamsError(
            f"Unknown action: {action}",
            param_name="action",
            expected="one of: domain_block, domain_unblock, domain_clear_override, claim_reject, claim_restore, edge_correct",
        )

    return await handler(args)


# ============================================================
# Domain Actions
# ============================================================


async def _handle_domain_block(args: dict[str, Any]) -> dict[str, Any]:
    """Handle domain_block action.

    Blocks a domain pattern, persisting to DB and reflecting in SourceVerifier.
    """
    domain_pattern = args.get("domain_pattern", "").strip()
    reason = args.get("reason", "").strip()

    _validate_domain_pattern(domain_pattern)

    if not reason:
        raise InvalidParamsError(
            "reason is required for domain_block",
            param_name="reason",
            expected="non-empty string explaining why domain is blocked",
        )

    db = await get_database()
    now = datetime.now(UTC).isoformat()
    rule_id = f"dor_{uuid.uuid4().hex[:12]}"
    event_id = f"doe_{uuid.uuid4().hex[:12]}"

    # Insert rule
    await db.execute(
        """
        INSERT INTO domain_override_rules (id, domain_pattern, decision, reason, created_at, updated_at, is_active, created_by)
        VALUES (?, ?, 'block', ?, ?, ?, 1, 'feedback')
        """,
        (rule_id, domain_pattern, reason, now, now),
    )

    # Insert event (append-only audit log)
    await db.execute(
        """
        INSERT INTO domain_override_events (id, rule_id, action, domain_pattern, decision, reason, created_at, created_by)
        VALUES (?, ?, 'domain_block', ?, 'block', ?, ?, 'feedback')
        """,
        (event_id, rule_id, domain_pattern, reason, now),
    )

    # Reflect to SourceVerifier immediately
    from src.filter.source_verification import get_source_verifier

    verifier = get_source_verifier()
    verifier.block_domain_manual(domain_pattern, reason)

    logger.info(
        "Domain blocked via feedback",
        domain_pattern=domain_pattern,
        rule_id=rule_id,
        reason=reason,
    )

    return {
        "ok": True,
        "action": "domain_block",
        "domain_pattern": domain_pattern,
        "rule_id": rule_id,
        "message": f"Domain '{domain_pattern}' blocked. Future searches will skip this domain.",
    }


async def _handle_domain_unblock(args: dict[str, Any]) -> dict[str, Any]:
    """Handle domain_unblock action.

    Unblocks a domain pattern, persisting to DB and reflecting in SourceVerifier.
    """
    domain_pattern = args.get("domain_pattern", "").strip()
    reason = args.get("reason", "").strip()

    _validate_domain_pattern(domain_pattern)

    if not reason:
        raise InvalidParamsError(
            "reason is required for domain_unblock",
            param_name="reason",
            expected="non-empty string explaining why domain is unblocked",
        )

    db = await get_database()
    now = datetime.now(UTC).isoformat()
    rule_id = f"dor_{uuid.uuid4().hex[:12]}"
    event_id = f"doe_{uuid.uuid4().hex[:12]}"

    # Insert rule
    await db.execute(
        """
        INSERT INTO domain_override_rules (id, domain_pattern, decision, reason, created_at, updated_at, is_active, created_by)
        VALUES (?, ?, 'unblock', ?, ?, ?, 1, 'feedback')
        """,
        (rule_id, domain_pattern, reason, now, now),
    )

    # Insert event (append-only audit log)
    await db.execute(
        """
        INSERT INTO domain_override_events (id, rule_id, action, domain_pattern, decision, reason, created_at, created_by)
        VALUES (?, ?, 'domain_unblock', ?, 'unblock', ?, ?, 'feedback')
        """,
        (event_id, rule_id, domain_pattern, reason, now),
    )

    # Reflect to SourceVerifier immediately
    # This can unblock any domain, including dangerous_pattern (ADR-0012)
    from src.filter.source_verification import get_source_verifier

    verifier = get_source_verifier()
    verifier.unblock_domain(domain_pattern)

    logger.info(
        "Domain unblocked via feedback",
        domain_pattern=domain_pattern,
        rule_id=rule_id,
        reason=reason,
    )

    return {
        "ok": True,
        "action": "domain_unblock",
        "domain_pattern": domain_pattern,
        "rule_id": rule_id,
    }


async def _handle_domain_clear_override(args: dict[str, Any]) -> dict[str, Any]:
    """Handle domain_clear_override action.

    Clears override for a domain pattern (sets is_active=0).
    """
    domain_pattern = args.get("domain_pattern", "").strip()
    reason = args.get("reason", "").strip()

    _validate_domain_pattern(domain_pattern)

    if not reason:
        raise InvalidParamsError(
            "reason is required for domain_clear_override",
            param_name="reason",
            expected="non-empty string explaining why override is cleared",
        )

    db = await get_database()
    now = datetime.now(UTC).isoformat()
    event_id = f"doe_{uuid.uuid4().hex[:12]}"

    # Deactivate matching rules
    result = await db.execute(
        """
        UPDATE domain_override_rules
        SET is_active = 0, updated_at = ?
        WHERE domain_pattern = ? AND is_active = 1
        """,
        (now, domain_pattern),
    )
    cleared_count = result.rowcount if hasattr(result, "rowcount") else 0

    # Insert event (append-only audit log)
    await db.execute(
        """
        INSERT INTO domain_override_events (id, rule_id, action, domain_pattern, decision, reason, created_at, created_by)
        VALUES (?, NULL, 'domain_clear_override', ?, 'clear', ?, ?, 'feedback')
        """,
        (event_id, domain_pattern, reason, now),
    )

    logger.info(
        "Domain override cleared via feedback",
        domain_pattern=domain_pattern,
        cleared_rules=cleared_count,
        reason=reason,
    )

    return {
        "ok": True,
        "action": "domain_clear_override",
        "domain_pattern": domain_pattern,
        "cleared_rules": cleared_count,
    }


# ============================================================
# Claim Actions
# ============================================================


async def _handle_claim_reject(args: dict[str, Any]) -> dict[str, Any]:
    """Handle claim_reject action.

    Rejects a claim (sets claim_adoption_status to 'not_adopted').
    """
    claim_id = args.get("claim_id", "").strip()
    reason = args.get("reason", "").strip()

    if not claim_id:
        raise InvalidParamsError(
            "claim_id is required for claim_reject",
            param_name="claim_id",
            expected="non-empty claim ID",
        )

    if not reason:
        raise InvalidParamsError(
            "reason is required for claim_reject",
            param_name="reason",
            expected="non-empty string explaining why claim is rejected",
        )

    db = await get_database()

    # Check claim exists
    claim = await db.fetch_one(
        "SELECT id, claim_adoption_status FROM claims WHERE id = ?",
        (claim_id,),
    )

    if not claim:
        raise ResourceNotFoundError(
            f"Claim not found: {claim_id}",
            resource_type="claim",
            resource_id=claim_id,
        )

    now = datetime.now(UTC).isoformat()

    # Update claim
    await db.execute(
        """
        UPDATE claims
        SET claim_adoption_status = 'not_adopted',
            claim_rejection_reason = ?,
            claim_rejected_at = ?
        WHERE id = ?
        """,
        (reason, now, claim_id),
    )

    logger.info(
        "Claim rejected via feedback",
        claim_id=claim_id,
        reason=reason,
    )

    return {
        "ok": True,
        "action": "claim_reject",
        "claim_id": claim_id,
    }


async def _handle_claim_restore(args: dict[str, Any]) -> dict[str, Any]:
    """Handle claim_restore action.

    Restores a claim (sets claim_adoption_status to 'adopted').
    """
    claim_id = args.get("claim_id", "").strip()

    if not claim_id:
        raise InvalidParamsError(
            "claim_id is required for claim_restore",
            param_name="claim_id",
            expected="non-empty claim ID",
        )

    db = await get_database()

    # Check claim exists
    claim = await db.fetch_one(
        "SELECT id, claim_adoption_status FROM claims WHERE id = ?",
        (claim_id,),
    )

    if not claim:
        raise ResourceNotFoundError(
            f"Claim not found: {claim_id}",
            resource_type="claim",
            resource_id=claim_id,
        )

    # Update claim
    await db.execute(
        """
        UPDATE claims
        SET claim_adoption_status = 'adopted',
            claim_rejection_reason = NULL,
            claim_rejected_at = NULL
        WHERE id = ?
        """,
        (claim_id,),
    )

    logger.info(
        "Claim restored via feedback",
        claim_id=claim_id,
    )

    return {
        "ok": True,
        "action": "claim_restore",
        "claim_id": claim_id,
    }


# ============================================================
# Edge Actions
# ============================================================


async def _handle_edge_correct(args: dict[str, Any]) -> dict[str, Any]:
    """Handle edge_correct action.

    Marks an edge as human-reviewed, and optionally corrects its NLI relation.

    Semantics:
    - Always: mark the edge as human-reviewed (`edge_human_corrected=1`) and set timestamps.
    - If the label changes: update the edge relation/label and persist a correction sample
      to `nli_corrections` for training (predicted_label != correct_label).
    - If the label does not change: do NOT create a `nli_corrections` record.
    """
    edge_id = args.get("edge_id", "").strip()
    correct_relation = args.get("correct_relation", "").strip()
    reason = args.get("reason", "").strip()

    if not edge_id:
        raise InvalidParamsError(
            "edge_id is required for edge_correct",
            param_name="edge_id",
            expected="non-empty edge ID",
        )

    if not correct_relation:
        raise InvalidParamsError(
            "correct_relation is required for edge_correct",
            param_name="correct_relation",
            expected="one of: supports, refutes, neutral",
        )

    if correct_relation not in ("supports", "refutes", "neutral"):
        raise InvalidParamsError(
            f"Invalid correct_relation: {correct_relation}",
            param_name="correct_relation",
            expected="one of: supports, refutes, neutral",
        )

    db = await get_database()

    # Get edge with premise/nli_hypothesis from related entities (ADR-0018)
    edge = await db.fetch_one(
        """
        SELECT e.id, e.source_type, e.source_id, e.target_type, e.target_id,
               e.relation, e.nli_label, e.nli_edge_confidence,
               COALESCE(f.text_content, '') as premise,
               COALESCE(c.claim_text, '') as nli_hypothesis
        FROM edges e
        LEFT JOIN fragments f ON e.source_type = 'fragment' AND e.source_id = f.id
        LEFT JOIN claims c ON e.target_type = 'claim' AND e.target_id = c.id
        WHERE e.id = ?
        """,
        (edge_id,),
    )

    if not edge:
        raise ResourceNotFoundError(
            f"Edge not found: {edge_id}",
            resource_type="edge",
            resource_id=edge_id,
        )

    # Only NLI evidence edges (supports/refutes/neutral) can be corrected.
    # Origin edges are provenance, not NLI classification.
    # Cites edges are citations, not NLI classification.
    current_relation = edge.get("relation") or "unknown"
    if current_relation not in ("supports", "refutes", "neutral"):
        raise InvalidParamsError(
            f"Edge {edge_id} has relation '{current_relation}' which cannot be corrected. "
            f"Only NLI evidence edges (supports/refutes/neutral) can be corrected via edge_correct.",
            param_name="edge_id",
            expected="edge with relation supports/refutes/neutral",
        )

    now = datetime.now(UTC).isoformat()
    previous_relation = edge.get("nli_label") or current_relation
    predicted_confidence = edge.get("nli_edge_confidence") or 0.0
    is_correction = previous_relation != correct_relation

    # Get task_id from claim if available
    task_id = None
    target_id = edge.get("target_id")
    if target_id:
        claim = await db.fetch_one(
            "SELECT task_id FROM claims WHERE id = ?",
            (target_id,),
        )
        if claim:
            task_id = claim.get("task_id")

    sample_id: str | None = None
    if is_correction:
        # Insert nli_correction (only when label changes) - ADR-0018: nli_hypothesis
        sample_id = f"nlc_{uuid.uuid4().hex[:12]}"
        await db.execute(
            """
            INSERT INTO nli_corrections (id, edge_id, task_id, premise, nli_hypothesis,
                                         predicted_label, predicted_confidence,
                                         correct_label, reason, corrected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                edge_id,
                task_id,
                edge.get("premise", ""),
                edge.get("nli_hypothesis", ""),
                previous_relation,
                predicted_confidence,
                correct_relation,
                reason or None,
                now,
            ),
        )

        # Update edge (correction)
        await db.execute(
            """
            UPDATE edges
            SET relation = ?,
                nli_label = ?,
                nli_edge_confidence = 1.0,
                edge_human_corrected = 1,
                edge_correction_reason = ?,
                edge_corrected_at = ?
            WHERE id = ?
            """,
            (correct_relation, correct_relation, reason or None, now, edge_id),
        )
        logger.info(
            "Edge corrected via feedback",
            edge_id=edge_id,
            previous_relation=previous_relation,
            new_relation=correct_relation,
            sample_id=sample_id,
        )
    else:
        # Update edge (review only): do not modify relation/label/confidence
        await db.execute(
            """
            UPDATE edges
            SET edge_human_corrected = 1,
                edge_correction_reason = ?,
                edge_corrected_at = ?
            WHERE id = ?
            """,
            (reason or None, now, edge_id),
        )
        logger.info(
            "Edge reviewed via feedback",
            edge_id=edge_id,
            relation=previous_relation,
        )

    response: dict[str, Any] = {
        "ok": True,
        "action": "edge_correct",
        "edge_id": edge_id,
        "previous_relation": previous_relation,
        "new_relation": correct_relation,
        "message": f"Edge corrected: {previous_relation} → {correct_relation}. Saved for future model improvement.",
    }
    if sample_id is not None:
        response["sample_id"] = sample_id
    return response
