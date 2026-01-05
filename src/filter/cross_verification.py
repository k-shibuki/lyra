"""
Cross-source NLI verification for Lyra.

Automatically verifies claims against fragments from different sources
to create supports/refutes/neutral edges. Per ADR-0005.

Key behaviors:
- Excludes origin domain/page (no self-referencing NLI)
- Uses vector search to find candidate fragments
- Creates edges with DB uniqueness constraint (INSERT OR IGNORE)
- No-ops gracefully when embeddings are missing or 0 candidates found
"""

import uuid
from typing import Any

from src.filter.nli import nli_judge
from src.ml_client import get_ml_client
from src.storage.database import get_database
from src.storage.vector_store import cosine_similarity, deserialize_embedding
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Default parameters (can be overridden via input_data)
DEFAULT_TOP_K = 30
DEFAULT_MIN_SIMILARITY = 0.55
DEFAULT_MAX_DOMAINS = 6
DEFAULT_MAX_PAIRS_PER_CLAIM = 20
DEFAULT_MIN_NLI_CONFIDENCE = 0.6


async def verify_claims_nli(
    task_id: str,
    claim_ids: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    max_domains: int = DEFAULT_MAX_DOMAINS,
    max_pairs_per_claim: int = DEFAULT_MAX_PAIRS_PER_CLAIM,
    min_nli_confidence: float = DEFAULT_MIN_NLI_CONFIDENCE,
    save_neutral: bool = True,
) -> dict[str, Any]:
    """
    Verify claims against cross-source fragments using NLI.

    Args:
        task_id: Task ID to scope verification.
        claim_ids: Specific claim IDs to verify (if None, verify all task claims).
        top_k: Max candidate fragments to retrieve per claim.
        min_similarity: Minimum cosine similarity threshold.
        max_domains: Max distinct domains for candidate selection.
        max_pairs_per_claim: Max NLI pairs to evaluate per claim.
        min_nli_confidence: Minimum confidence to persist supports/refutes edge.
        save_neutral: Whether to persist neutral edges.

    Returns:
        Summary dict with counts and status.
    """
    db = await get_database()

    # 1. Get claims to verify
    if claim_ids:
        placeholders = ",".join("?" for _ in claim_ids)
        claims = await db.fetch_all(
            f"""
            SELECT id, claim_text
            FROM claims
            WHERE task_id = ? AND id IN ({placeholders})
            """,
            [task_id, *claim_ids],
        )
    else:
        claims = await db.fetch_all(
            """
            SELECT id, claim_text
            FROM claims
            WHERE task_id = ?
            """,
            (task_id,),
        )

    if not claims:
        logger.info("No claims to verify", task_id=task_id)
        return {
            "ok": True,
            "task_id": task_id,
            "claims_processed": 0,
            "edges_created": 0,
            "edges_skipped_duplicate": 0,
            "status": "no_claims",
        }

    total_edges_created = 0
    total_edges_skipped = 0
    claims_processed = 0

    for claim in claims:
        claim_id = claim["id"]
        claim_text = claim["claim_text"]

        result = await _verify_single_claim(
            db=db,
            task_id=task_id,
            claim_id=claim_id,
            claim_text=claim_text,
            top_k=top_k,
            min_similarity=min_similarity,
            max_domains=max_domains,
            max_pairs_per_claim=max_pairs_per_claim,
            min_nli_confidence=min_nli_confidence,
            save_neutral=save_neutral,
        )

        total_edges_created += result["edges_created"]
        total_edges_skipped += result["edges_skipped"]
        claims_processed += 1

    logger.info(
        "Cross-source NLI verification completed",
        task_id=task_id,
        claims_processed=claims_processed,
        edges_created=total_edges_created,
        edges_skipped_duplicate=total_edges_skipped,
    )

    return {
        "ok": True,
        "task_id": task_id,
        "claims_processed": claims_processed,
        "edges_created": total_edges_created,
        "edges_skipped_duplicate": total_edges_skipped,
        "status": "completed",
    }


async def _verify_single_claim(
    db: Any,
    task_id: str,
    claim_id: str,
    claim_text: str,
    top_k: int,
    min_similarity: float,
    max_domains: int,
    max_pairs_per_claim: int,
    min_nli_confidence: float,
    save_neutral: bool,
) -> dict[str, int]:
    """Verify a single claim against candidate fragments."""

    # 1. Get origin domain(s) to exclude
    origin_domains = await _get_claim_origin_domains(db, claim_id)

    # 2. Get candidate fragments via vector search (excluding origin domains)
    candidates = await _get_candidate_fragments(
        db=db,
        task_id=task_id,
        claim_id=claim_id,
        claim_text=claim_text,
        origin_domains=origin_domains,
        top_k=top_k,
        min_similarity=min_similarity,
        max_domains=max_domains,
    )

    if not candidates:
        logger.debug(
            "No candidate fragments found",
            claim_id=claim_id,
            origin_domains=origin_domains,
        )
        return {"edges_created": 0, "edges_skipped": 0}

    # 3. Check existing edges to skip already-evaluated pairs
    existing_fragment_ids = await _get_existing_nli_fragment_ids(db, claim_id)
    candidates = [c for c in candidates if c["fragment_id"] not in existing_fragment_ids]

    if not candidates:
        logger.debug("All candidates already evaluated", claim_id=claim_id)
        return {"edges_created": 0, "edges_skipped": 0}

    # 4. Limit to max_pairs_per_claim
    candidates = candidates[:max_pairs_per_claim]

    # 5. Build NLI pairs
    pairs = [
        {
            "pair_id": f"{claim_id}:{c['fragment_id']}",
            "premise": c["text_content"],
            "nli_hypothesis": claim_text,
        }
        for c in candidates
    ]

    # 6. Run NLI
    nli_results = await nli_judge(pairs)

    # 7. Persist edges
    edges_created = 0
    edges_skipped = 0

    for nli_result, candidate in zip(nli_results, candidates, strict=False):
        stance = nli_result.get("stance", "neutral")
        confidence = nli_result.get("nli_edge_confidence", 0.0)

        # Apply confidence threshold for supports/refutes
        if stance in ("supports", "refutes") and confidence < min_nli_confidence:
            continue

        # Skip neutral if not saving
        if stance == "neutral" and not save_neutral:
            continue

        # Insert edge (unique index will prevent duplicates)
        created = await _insert_nli_edge(
            db=db,
            claim_id=claim_id,
            fragment_id=candidate["fragment_id"],
            stance=stance,
            confidence=confidence,
            source_domain=candidate.get("domain"),
        )

        if created:
            edges_created += 1
        else:
            edges_skipped += 1

    return {"edges_created": edges_created, "edges_skipped": edges_skipped}


async def _get_claim_origin_domains(db: Any, claim_id: str) -> set[str]:
    """Get domains from which the claim was extracted (origin edges)."""
    rows = await db.fetch_all(
        """
        SELECT DISTINCT p.domain
        FROM edges e
        JOIN fragments f ON e.source_type = 'fragment' AND e.source_id = f.id
        JOIN pages p ON f.page_id = p.id
        WHERE e.target_type = 'claim'
          AND e.target_id = ?
          AND e.relation = 'origin'
        """,
        (claim_id,),
    )
    return {row["domain"] for row in rows if row["domain"]}


async def _get_candidate_fragments(
    db: Any,
    task_id: str,
    claim_id: str,
    claim_text: str,
    origin_domains: set[str],
    top_k: int,
    min_similarity: float,
    max_domains: int,
) -> list[dict[str, Any]]:
    """Get candidate fragments for NLI using vector similarity."""
    settings = get_settings()
    model_id = settings.embedding.model_name

    # 1. Generate claim embedding
    try:
        ml_client = get_ml_client()
        claim_embeddings = await ml_client.embed([claim_text])
        claim_vec = claim_embeddings[0]
    except Exception as e:
        logger.warning(
            "Failed to generate claim embedding",
            claim_id=claim_id,
            error=str(e),
        )
        return []

    # 2. Get task-scoped fragment embeddings (excluding origin domains)
    # Join via edges to get fragments related to this task's claims
    domain_exclusion = ""
    params: list[Any] = [task_id, "fragment", model_id]

    if origin_domains:
        placeholders = ",".join("?" for _ in origin_domains)
        domain_exclusion = f"AND p.domain NOT IN ({placeholders})"
        params.extend(origin_domains)

    sql = f"""
    WITH task_fragments AS (
        SELECT DISTINCT e.source_id AS fragment_id
        FROM edges e
        JOIN claims c ON e.target_type = 'claim' AND e.target_id = c.id
        WHERE e.source_type = 'fragment'
          AND c.task_id = ?
    )
    SELECT
        emb.target_id AS fragment_id,
        emb.embedding_blob,
        f.text_content,
        p.domain
    FROM embeddings emb
    JOIN fragments f ON emb.target_id = f.id
    JOIN pages p ON f.page_id = p.id
    WHERE emb.target_type = ?
      AND emb.model_id = ?
      AND emb.target_id IN (SELECT fragment_id FROM task_fragments)
      {domain_exclusion}
    """

    rows = await db.fetch_all(sql, params)

    if not rows:
        logger.debug(
            "No fragment embeddings found for task",
            task_id=task_id,
            claim_id=claim_id,
        )
        return []

    # 3. Calculate similarity and filter
    candidates = []
    for row in rows:
        emb_blob = row["embedding_blob"]
        if not emb_blob:
            continue

        emb = deserialize_embedding(emb_blob)
        sim = cosine_similarity(claim_vec, emb)

        if sim >= min_similarity:
            candidates.append(
                {
                    "fragment_id": row["fragment_id"],
                    "similarity": sim,
                    "text_content": row["text_content"] or "",
                    "domain": row["domain"],
                }
            )

    # 4. Sort by similarity and limit
    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    candidates = candidates[:top_k]

    # 5. Limit to max_domains for diversity
    if max_domains > 0:
        seen_domains: set[str] = set()
        filtered = []
        for c in candidates:
            domain = c.get("domain") or "unknown"
            if len(seen_domains) < max_domains or domain in seen_domains:
                filtered.append(c)
                seen_domains.add(domain)
        candidates = filtered

    return candidates


async def _get_existing_nli_fragment_ids(db: Any, claim_id: str) -> set[str]:
    """Get fragment IDs that already have NLI edges to this claim."""
    rows = await db.fetch_all(
        """
        SELECT source_id
        FROM edges
        WHERE source_type = 'fragment'
          AND target_type = 'claim'
          AND target_id = ?
          AND relation IN ('supports', 'refutes', 'neutral')
        """,
        (claim_id,),
    )
    return {row["source_id"] for row in rows}


async def _insert_nli_edge(
    db: Any,
    claim_id: str,
    fragment_id: str,
    stance: str,
    confidence: float,
    source_domain: str | None,
) -> bool:
    """Insert NLI edge, returning True if created (not duplicate)."""
    edge_id = f"e_{uuid.uuid4().hex[:8]}"

    try:
        # Use INSERT OR IGNORE to respect unique index
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO edges
            (id, source_type, source_id, target_type, target_id,
             relation, nli_label, nli_edge_confidence, source_domain_category)
            VALUES (?, 'fragment', ?, 'claim', ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                fragment_id,
                claim_id,
                stance,
                stance,  # nli_label same as relation for NLI edges
                confidence,
                source_domain,
            ),
        )

        # Check if row was inserted
        rowcount = getattr(cursor, "rowcount", 0)
        if rowcount > 0:
            logger.debug(
                "NLI edge created",
                edge_id=edge_id,
                claim_id=claim_id,
                fragment_id=fragment_id,
                stance=stance,
                confidence=confidence,
            )
            return True
        else:
            logger.debug(
                "NLI edge skipped (duplicate)",
                claim_id=claim_id,
                fragment_id=fragment_id,
            )
            return False

    except Exception as e:
        logger.warning(
            "Failed to insert NLI edge",
            claim_id=claim_id,
            fragment_id=fragment_id,
            error=str(e),
        )
        return False


async def enqueue_verify_nli_job(
    task_id: str,
    claim_ids: list[str] | None = None,
    priority: int | None = None,
) -> dict[str, Any]:
    """
    Enqueue a VERIFY_NLI job for cross-source verification.

    Called by search_worker after successful search completion.

    Args:
        task_id: Task ID.
        claim_ids: Specific claim IDs to verify (None = all task claims).
        priority: Job priority override.

    Returns:
        Job submission result.
    """
    from src.scheduler.jobs import JobKind, get_scheduler

    scheduler = await get_scheduler()

    input_data: dict[str, Any] = {
        "task_id": task_id,
    }
    if claim_ids:
        input_data["claim_ids"] = claim_ids

    result = await scheduler.submit(
        kind=JobKind.VERIFY_NLI,
        input_data=input_data,
        priority=priority,
        task_id=task_id,
    )

    logger.info(
        "VERIFY_NLI job enqueued",
        task_id=task_id,
        claim_ids_count=len(claim_ids) if claim_ids else "all",
        job_id=result.get("job_id"),
        accepted=result.get("accepted"),
    )

    return result
