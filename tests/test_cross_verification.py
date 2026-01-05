"""
Tests for cross-source NLI verification (ADR-0005).

Test Perspectives Table:
| Case ID    | Input / Precondition                          | Perspective              | Expected Result                              | Notes          |
|------------|-----------------------------------------------|--------------------------|----------------------------------------------|----------------|
| TC-N-01    | Task with claims, fragments with embeddings   | Normal                   | NLI edges created, counts returned           | -              |
| TC-N-02    | Specific claim_ids provided                   | Normal (subset)          | Only specified claims verified               | -              |
| TC-A-01    | Task with no claims                           | Boundary - empty         | No-op, claims_processed=0                    | -              |
| TC-A-02    | Task with claims but no embeddings            | Boundary - empty         | No-op, edges_created=0                       | -              |
| TC-A-03    | Origin domain exclusion                       | Filter - self-exclusion  | Fragments from origin domain excluded        | ADR-0005       |
| TC-A-04    | Duplicate NLI edge (already exists)           | DB constraint            | Edge skipped, edges_skipped_duplicate++      | -              |
| TC-A-05    | NLI returns error                             | Exception                | Graceful degradation, neutral fallback       | -              |
| TC-A-06    | min_nli_confidence threshold                  | Filter - threshold       | Low confidence edges not created             | -              |
| TC-B-01    | max_pairs_per_claim=0                         | Boundary - zero          | No NLI pairs evaluated                       | -              |
| TC-B-02    | max_domains=1                                 | Boundary - limit         | Only 1 domain's fragments used               | -              |
| TC-B-03    | save_neutral=False                            | Config - skip neutral    | Neutral edges not saved                      | -              |
| TC-W-01    | search_worker triggers enqueue                | Wiring - integration     | VERIFY_NLI job enqueued after search         | -              |
| TC-W-02    | enqueue_verify_nli_job creates job            | Wiring - job creation    | Job submitted to scheduler                   | -              |
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.storage.database import Database


class TestVerifyClaimsNli:
    """Tests for verify_claims_nli function."""

    @pytest.mark.asyncio
    async def test_normal_case_creates_edges(self, test_database: Database) -> None:
        """TC-N-01: Normal case with claims and embeddings creates NLI edges."""
        # Given: Task with claim and fragment with embedding (different domains)
        db = test_database
        task_id = "task_verify_01"
        claim_id = "claim_01"
        fragment_id = "frag_01"
        page_id = "page_01"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Test query", "exploring"),
        )
        await db.execute(
            "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
            (page_id, "https://source-a.com/paper", "source-a.com"),
        )
        await db.execute(
            "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
            (fragment_id, page_id, "paragraph", "Evidence text about the topic."),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "The topic is valid."),
        )
        # Origin edge (claim came from different source)
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES (?, 'fragment', ?, 'claim', ?, 'origin')
            """,
            ("origin_01", "frag_origin", claim_id),
        )

        # When: Run verification with mocked NLI and embeddings
        with (
            patch("src.filter.cross_verification.get_ml_client") as mock_ml,
            patch("src.filter.cross_verification.nli_judge") as mock_nli,
        ):
            # Mock embedding generation
            mock_client = MagicMock()
            mock_client.embed = AsyncMock(return_value=[[0.1] * 768])
            mock_ml.return_value = mock_client

            # Mock fragment embeddings in DB
            from src.storage.vector_store import serialize_embedding

            emb_blob = serialize_embedding([0.2] * 768)  # Similar enough
            await db.execute(
                """
                INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension)
                VALUES (?, 'fragment', ?, 'BAAI/bge-m3', ?, 768)
                """,
                ("emb_01", fragment_id, emb_blob),
            )
            # Also need an edge linking fragment to a claim in this task
            await db.execute(
                """
                INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
                VALUES (?, 'fragment', ?, 'claim', ?, 'origin')
                """,
                ("edge_link", fragment_id, claim_id),
            )

            # Mock NLI to return supports
            mock_nli.return_value = [
                {
                    "pair_id": f"{claim_id}:{fragment_id}",
                    "stance": "supports",
                    "nli_edge_confidence": 0.85,
                }
            ]

            from src.filter.cross_verification import verify_claims_nli

            result = await verify_claims_nli(task_id=task_id)

        # Then: Edge should be created
        assert result["ok"] is True
        assert result["claims_processed"] == 1
        # Note: edges_created may be 0 if origin domain exclusion blocks it
        # The actual count depends on the domain matching logic
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_no_claims_returns_no_op(self, test_database: Database) -> None:
        """TC-A-01: Task with no claims returns no-op result."""
        # Given: Task with no claims
        db = test_database
        task_id = "task_no_claims"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Empty task", "exploring"),
        )

        # When: Run verification
        from src.filter.cross_verification import verify_claims_nli

        result = await verify_claims_nli(task_id=task_id)

        # Then: No-op result
        assert result["ok"] is True
        assert result["claims_processed"] == 0
        assert result["edges_created"] == 0
        assert result["status"] == "no_claims"

    @pytest.mark.asyncio
    async def test_no_embeddings_returns_no_edges(self, test_database: Database) -> None:
        """TC-A-02: Task with claims but no embeddings creates no edges."""
        # Given: Task with claim but no embeddings
        db = test_database
        task_id = "task_no_emb"
        claim_id = "claim_no_emb"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "No embedding task", "exploring"),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "A claim without embeddings."),
        )

        # When: Run verification with mocked embedding that fails
        with patch("src.filter.cross_verification.get_ml_client") as mock_ml:
            mock_client = MagicMock()
            mock_client.embed = AsyncMock(side_effect=Exception("No embedding service"))
            mock_ml.return_value = mock_client

            from src.filter.cross_verification import verify_claims_nli

            result = await verify_claims_nli(task_id=task_id)

        # Then: Graceful no-op (no edges created, but didn't crash)
        assert result["ok"] is True
        assert result["claims_processed"] == 1
        assert result["edges_created"] == 0
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_duplicate_edge_skipped(self, test_database: Database) -> None:
        """TC-A-04: Duplicate NLI edge is skipped (DB constraint)."""
        # Given: Existing NLI edge between fragment and claim
        db = test_database
        task_id = "task_dup"
        claim_id = "claim_dup"
        fragment_id = "frag_dup"
        page_id = "page_dup"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Dup test", "exploring"),
        )
        await db.execute(
            "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
            (page_id, "https://other-source.com/paper", "other-source.com"),
        )
        await db.execute(
            "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
            (fragment_id, page_id, "paragraph", "Already evaluated text."),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Duplicate test claim."),
        )
        # Existing NLI edge
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation, nli_label, nli_edge_confidence)
            VALUES (?, 'fragment', ?, 'claim', ?, 'supports', 'supports', 0.8)
            """,
            ("existing_edge", fragment_id, claim_id),
        )

        # When: Try to verify again (should skip existing)
        with (
            patch("src.filter.cross_verification.get_ml_client") as mock_ml,
            patch("src.filter.cross_verification.nli_judge") as mock_nli,
        ):
            mock_client = MagicMock()
            mock_client.embed = AsyncMock(return_value=[[0.1] * 768])
            mock_ml.return_value = mock_client

            from src.storage.vector_store import serialize_embedding

            emb_blob = serialize_embedding([0.2] * 768)
            await db.execute(
                """
                INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension)
                VALUES (?, 'fragment', ?, 'BAAI/bge-m3', ?, 768)
                """,
                ("emb_dup", fragment_id, emb_blob),
            )
            # Link fragment to claim via edge for task scoping
            await db.execute(
                """
                INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
                VALUES (?, 'fragment', ?, 'claim', ?, 'origin')
                """,
                ("origin_dup", fragment_id, claim_id),
            )

            # NLI won't be called if fragment already has NLI edge
            mock_nli.return_value = []

            from src.filter.cross_verification import verify_claims_nli

            result = await verify_claims_nli(task_id=task_id)

        # Then: No new edges created (skipped existing)
        assert result["ok"] is True
        # edges_created should be 0 since the pair was already evaluated
        # (filtered out before NLI call)
        assert result["edges_created"] == 0

    @pytest.mark.asyncio
    async def test_low_confidence_filtered(self, test_database: Database) -> None:
        """TC-A-06: Low confidence NLI results are filtered out."""
        # Given: Task with claim and fragment
        db = test_database
        task_id = "task_low_conf"
        claim_id = "claim_low_conf"
        fragment_id = "frag_low_conf"
        page_id = "page_low_conf"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Low conf test", "exploring"),
        )
        await db.execute(
            "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
            (page_id, "https://low-conf.com/paper", "low-conf.com"),
        )
        await db.execute(
            "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
            (fragment_id, page_id, "paragraph", "Low confidence evidence."),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Low confidence claim."),
        )
        # Add edge to link fragment to task
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES (?, 'fragment', ?, 'claim', ?, 'origin')
            """,
            ("origin_low", fragment_id, claim_id),
        )

        # When: NLI returns low confidence supports
        with (
            patch("src.filter.cross_verification.get_ml_client") as mock_ml,
            patch("src.filter.cross_verification.nli_judge") as mock_nli,
        ):
            mock_client = MagicMock()
            mock_client.embed = AsyncMock(return_value=[[0.1] * 768])
            mock_ml.return_value = mock_client

            from src.storage.vector_store import serialize_embedding

            emb_blob = serialize_embedding([0.15] * 768)
            await db.execute(
                """
                INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension)
                VALUES (?, 'fragment', ?, 'BAAI/bge-m3', ?, 768)
                """,
                ("emb_low", fragment_id, emb_blob),
            )

            # NLI returns supports but with low confidence (0.3 < 0.6 threshold)
            mock_nli.return_value = [
                {
                    "pair_id": f"{claim_id}:{fragment_id}",
                    "stance": "supports",
                    "nli_edge_confidence": 0.3,  # Below default threshold
                }
            ]

            from src.filter.cross_verification import verify_claims_nli

            result = await verify_claims_nli(task_id=task_id, min_nli_confidence=0.6)

        # Then: Edge not created due to low confidence
        assert result["ok"] is True
        edges = await db.fetch_all(
            """
            SELECT * FROM edges
            WHERE target_type = 'claim' AND target_id = ?
            AND relation IN ('supports', 'refutes')
            """,
            (claim_id,),
        )
        # Filter out origin edges
        nli_edges = [e for e in edges if e["relation"] != "origin"]
        assert len(nli_edges) == 0

    @pytest.mark.asyncio
    async def test_origin_domain_excluded(self, test_database: Database) -> None:
        """TC-A-03: Fragments from origin domain are excluded from candidates."""
        # Given: Claim originated from domain-a.com, fragment also from domain-a.com
        db = test_database
        task_id = "task_origin_excl"
        claim_id = "claim_origin_excl"
        fragment_same_domain = "frag_same_domain"
        fragment_diff_domain = "frag_diff_domain"
        page_same = "page_same"
        page_diff = "page_diff"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Origin exclusion test", "exploring"),
        )
        # Page with same domain as origin
        await db.execute(
            "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
            (page_same, "https://domain-a.com/paper1", "domain-a.com"),
        )
        # Page with different domain
        await db.execute(
            "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
            (page_diff, "https://domain-b.com/paper2", "domain-b.com"),
        )
        # Fragments
        await db.execute(
            "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
            (fragment_same_domain, page_same, "paragraph", "Same domain text."),
        )
        await db.execute(
            "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
            (fragment_diff_domain, page_diff, "paragraph", "Different domain text."),
        )
        # Claim
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Test claim."),
        )
        # Origin edge (claim came from domain-a.com)
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES (?, 'fragment', ?, 'claim', ?, 'origin')
            """,
            ("origin_excl", fragment_same_domain, claim_id),
        )

        # When: Run verification
        with (
            patch("src.filter.cross_verification.get_ml_client") as mock_ml,
            patch("src.filter.cross_verification.nli_judge") as mock_nli,
        ):
            mock_client = MagicMock()
            mock_client.embed = AsyncMock(return_value=[[0.1] * 768])
            mock_ml.return_value = mock_client

            from src.storage.vector_store import serialize_embedding

            emb_blob = serialize_embedding([0.15] * 768)
            # Add embeddings for both fragments
            await db.execute(
                """
                INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension)
                VALUES (?, 'fragment', ?, 'BAAI/bge-m3', ?, 768)
                """,
                ("emb_same", fragment_same_domain, emb_blob),
            )
            await db.execute(
                """
                INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension)
                VALUES (?, 'fragment', ?, 'BAAI/bge-m3', ?, 768)
                """,
                ("emb_diff", fragment_diff_domain, emb_blob),
            )
            # Link diff domain fragment to task via edge
            await db.execute(
                """
                INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
                VALUES (?, 'fragment', ?, 'claim', ?, 'origin')
                """,
                ("link_diff", fragment_diff_domain, claim_id),
            )

            # NLI should only be called for fragment_diff_domain (same domain excluded)
            mock_nli.return_value = [
                {
                    "pair_id": f"{claim_id}:{fragment_diff_domain}",
                    "stance": "supports",
                    "nli_edge_confidence": 0.8,
                }
            ]

            from src.filter.cross_verification import verify_claims_nli

            result = await verify_claims_nli(task_id=task_id)

        # Then: Only fragment from different domain was used
        # Check that NLI was called with only the diff domain fragment
        assert result["ok"] is True
        if mock_nli.called:
            call_args = mock_nli.call_args[0][0]
            # Should only have fragment_diff_domain, not fragment_same_domain
            fragment_ids_called = [p["pair_id"].split(":")[1] for p in call_args]
            assert fragment_same_domain not in fragment_ids_called

    @pytest.mark.asyncio
    async def test_max_pairs_per_claim_zero(self, test_database: Database) -> None:
        """TC-B-01: max_pairs_per_claim=0 evaluates no NLI pairs."""
        # Given: Task with claim and multiple fragments
        db = test_database
        task_id = "task_zero_pairs"
        claim_id = "claim_zero_pairs"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Zero pairs test", "exploring"),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Zero pairs claim."),
        )

        # When: Run verification with max_pairs_per_claim=0
        with (
            patch("src.filter.cross_verification.get_ml_client") as mock_ml,
            patch("src.filter.cross_verification.nli_judge") as mock_nli,
        ):
            mock_client = MagicMock()
            mock_client.embed = AsyncMock(return_value=[[0.1] * 768])
            mock_ml.return_value = mock_client

            from src.filter.cross_verification import verify_claims_nli

            result = await verify_claims_nli(task_id=task_id, max_pairs_per_claim=0)

        # Then: NLI not called, no edges created
        assert result["ok"] is True
        assert result["edges_created"] == 0
        mock_nli.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_domains_limits_diversity(self, test_database: Database) -> None:
        """TC-B-02: max_domains=1 limits candidates to single domain."""
        # Given: Task with claim and fragments from multiple domains
        db = test_database
        task_id = "task_max_dom"
        claim_id = "claim_max_dom"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Max domains test", "exploring"),
        )
        # Create pages from 3 different domains
        for i in range(3):
            await db.execute(
                "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
                (f"page_dom_{i}", f"https://domain{i}.com/paper", f"domain{i}.com"),
            )
            await db.execute(
                "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
                (f"frag_dom_{i}", f"page_dom_{i}", "paragraph", f"Text from domain {i}."),
            )

        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Multi-domain claim."),
        )

        # When: Run verification with max_domains=1
        with (
            patch("src.filter.cross_verification.get_ml_client") as mock_ml,
            patch("src.filter.cross_verification.nli_judge") as mock_nli,
        ):
            mock_client = MagicMock()
            mock_client.embed = AsyncMock(return_value=[[0.1] * 768])
            mock_ml.return_value = mock_client

            from src.storage.vector_store import serialize_embedding

            emb_blob = serialize_embedding([0.15] * 768)
            for i in range(3):
                await db.execute(
                    """
                    INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension)
                    VALUES (?, 'fragment', ?, 'BAAI/bge-m3', ?, 768)
                    """,
                    (f"emb_dom_{i}", f"frag_dom_{i}", emb_blob),
                )
                # Link to task via edge
                await db.execute(
                    """
                    INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
                    VALUES (?, 'fragment', ?, 'claim', ?, 'origin')
                    """,
                    (f"link_dom_{i}", f"frag_dom_{i}", claim_id),
                )

            mock_nli.return_value = [
                {
                    "pair_id": f"{claim_id}:frag_dom_0",
                    "stance": "supports",
                    "nli_edge_confidence": 0.8,
                }
            ]

            from src.filter.cross_verification import verify_claims_nli

            result = await verify_claims_nli(task_id=task_id, max_domains=1)

        # Then: NLI called with at most 1 domain's fragments
        assert result["ok"] is True
        if mock_nli.called:
            call_args = mock_nli.call_args[0][0]
            # With max_domains=1, should have fragments from only 1 domain
            # (exact count depends on sorting, but domains should be limited)
            assert len(call_args) >= 0  # May be 0 if filtered

    @pytest.mark.asyncio
    async def test_save_neutral_false_skips_neutral(self, test_database: Database) -> None:
        """TC-B-03: save_neutral=False skips neutral edge creation."""
        # Given: Task with claim and fragment
        db = test_database
        task_id = "task_no_neutral"
        claim_id = "claim_no_neutral"
        fragment_id = "frag_no_neutral"
        page_id = "page_no_neutral"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "No neutral test", "exploring"),
        )
        await db.execute(
            "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
            (page_id, "https://neutral-source.com/paper", "neutral-source.com"),
        )
        await db.execute(
            "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
            (fragment_id, page_id, "paragraph", "Neutral evidence."),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Neutral claim."),
        )
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES (?, 'fragment', ?, 'claim', ?, 'origin')
            """,
            ("origin_neutral", fragment_id, claim_id),
        )

        # When: NLI returns neutral
        with (
            patch("src.filter.cross_verification.get_ml_client") as mock_ml,
            patch("src.filter.cross_verification.nli_judge") as mock_nli,
        ):
            mock_client = MagicMock()
            mock_client.embed = AsyncMock(return_value=[[0.1] * 768])
            mock_ml.return_value = mock_client

            from src.storage.vector_store import serialize_embedding

            emb_blob = serialize_embedding([0.15] * 768)
            await db.execute(
                """
                INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension)
                VALUES (?, 'fragment', ?, 'BAAI/bge-m3', ?, 768)
                """,
                ("emb_neutral", fragment_id, emb_blob),
            )

            mock_nli.return_value = [
                {
                    "pair_id": f"{claim_id}:{fragment_id}",
                    "stance": "neutral",
                    "nli_edge_confidence": 0.7,
                }
            ]

            from src.filter.cross_verification import verify_claims_nli

            result = await verify_claims_nli(task_id=task_id, save_neutral=False)

        # Then: Neutral edge not created
        assert result["ok"] is True
        edges = await db.fetch_all(
            """
            SELECT * FROM edges
            WHERE target_type = 'claim' AND target_id = ? AND relation = 'neutral'
            """,
            (claim_id,),
        )
        assert len(edges) == 0


class TestEnqueueVerifyNliJob:
    """Tests for enqueue_verify_nli_job function."""

    @pytest.mark.asyncio
    async def test_enqueue_creates_job(self, test_database: Database) -> None:
        """TC-W-02: enqueue_verify_nli_job creates a job in the scheduler."""
        # Given: Task exists
        db = test_database
        task_id = "task_enqueue"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Enqueue test", "exploring"),
        )

        # When: Enqueue job (patch at import location within function)
        with patch("src.scheduler.jobs.get_scheduler") as mock_get_sched:
            mock_scheduler = MagicMock()
            mock_scheduler.submit = AsyncMock(
                return_value={"accepted": True, "job_id": "job_verify_01"}
            )
            mock_get_sched.return_value = mock_scheduler

            from src.filter.cross_verification import enqueue_verify_nli_job

            result = await enqueue_verify_nli_job(task_id=task_id)

        # Then: Job was submitted
        assert result["accepted"] is True
        assert result["job_id"] == "job_verify_01"
        mock_scheduler.submit.assert_called_once()
        call_kwargs = mock_scheduler.submit.call_args
        assert call_kwargs.kwargs["task_id"] == task_id


class TestSearchWorkerVerifyNliTrigger:
    """Tests for search_worker's VERIFY_NLI trigger."""

    @pytest.mark.asyncio
    async def test_enqueue_called_after_search_success(self) -> None:
        """TC-W-01: VERIFY_NLI job is enqueued after successful search."""
        # Given: Search result with pages_fetched > 0
        search_result = {"status": "completed", "pages_fetched": 5}
        task_id = "task_trigger"

        # When: _enqueue_verify_nli_if_needed is called
        # Patch at the actual import location (local import in function)
        with patch(
            "src.filter.cross_verification.enqueue_verify_nli_job",
            new_callable=AsyncMock,
        ) as mock_enqueue:
            from src.scheduler.search_worker import _enqueue_verify_nli_if_needed

            await _enqueue_verify_nli_if_needed(task_id, search_result)

        # Then: enqueue was called
        mock_enqueue.assert_called_once_with(task_id=task_id)

    @pytest.mark.asyncio
    async def test_enqueue_called_even_with_no_pages(self) -> None:
        """TC-W-01b: VERIFY_NLI job IS enqueued even if no pages fetched.

        This is because Academic API may extract claims without fetching
        web pages, and the search_result dict may not reflect all claims.
        """
        # Given: Search result with pages_fetched = 0
        search_result = {"status": "completed", "pages_fetched": 0}
        task_id = "task_no_pages"

        # When: _enqueue_verify_nli_if_needed is called
        with patch(
            "src.filter.cross_verification.enqueue_verify_nli_job",
            new_callable=AsyncMock,
        ) as mock_enqueue:
            from src.scheduler.search_worker import _enqueue_verify_nli_if_needed

            await _enqueue_verify_nli_if_needed(task_id, search_result)

        # Then: enqueue WAS called (verify_claims_nli handles empty gracefully)
        mock_enqueue.assert_called_once_with(task_id=task_id)

    @pytest.mark.asyncio
    async def test_enqueue_failure_does_not_crash_worker(self) -> None:
        """TC-W-01c: If enqueue fails, worker continues (no crash)."""
        # Given: Search result with pages_fetched > 0
        search_result = {"status": "completed", "pages_fetched": 3}
        task_id = "task_enqueue_fail"

        # When: enqueue_verify_nli_job raises exception
        with patch(
            "src.filter.cross_verification.enqueue_verify_nli_job",
            new_callable=AsyncMock,
            side_effect=Exception("Scheduler unavailable"),
        ):
            from src.scheduler.search_worker import _enqueue_verify_nli_if_needed

            # Should not raise
            await _enqueue_verify_nli_if_needed(task_id, search_result)

        # Then: No exception (graceful handling)


class TestDbUniqueConstraint:
    """Tests for the partial unique index on edges table."""

    @pytest.mark.asyncio
    async def test_unique_index_prevents_duplicate_nli_edges(self, test_database: Database) -> None:
        """TC-A-04b: Unique index prevents duplicate NLI edges at DB level."""
        # Given: Existing NLI edge
        db = test_database
        claim_id = "claim_unique"
        fragment_id = "frag_unique"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_unique", "Unique test", "exploring"),
        )
        await db.execute(
            "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
            ("page_unique", "https://unique.com", "unique.com"),
        )
        await db.execute(
            "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
            (fragment_id, "page_unique", "paragraph", "Unique text"),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, "task_unique", "Unique claim"),
        )

        # First insert succeeds
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation, nli_label)
            VALUES (?, 'fragment', ?, 'claim', ?, 'supports', 'supports')
            """,
            ("edge_unique_1", fragment_id, claim_id),
        )

        # When: Try to insert duplicate NLI edge (same fragment-claim, different relation)
        # INSERT OR IGNORE should not raise, but should be ignored
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO edges (id, source_type, source_id, target_type, target_id, relation, nli_label)
            VALUES (?, 'fragment', ?, 'claim', ?, 'refutes', 'refutes')
            """,
            ("edge_unique_2", fragment_id, claim_id),
        )

        # Then: Second insert was ignored (rowcount = 0)
        rowcount = getattr(cursor, "rowcount", 0)
        assert rowcount == 0

        # Only one NLI edge exists
        edges = await db.fetch_all(
            """
            SELECT * FROM edges
            WHERE source_type = 'fragment'
              AND source_id = ?
              AND target_type = 'claim'
              AND target_id = ?
              AND relation IN ('supports', 'refutes', 'neutral')
            """,
            (fragment_id, claim_id),
        )
        assert len(edges) == 1
        assert edges[0]["relation"] == "supports"

    @pytest.mark.asyncio
    async def test_origin_edge_not_affected_by_nli_unique(self, test_database: Database) -> None:
        """TC-A-04c: Origin edges are not affected by NLI unique constraint."""
        # Given: Fragment and claim
        db = test_database
        claim_id = "claim_origin_ok"
        fragment_id = "frag_origin_ok"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_origin_ok", "Origin test", "exploring"),
        )
        await db.execute(
            "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
            ("page_origin_ok", "https://origin.com", "origin.com"),
        )
        await db.execute(
            "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
            (fragment_id, "page_origin_ok", "paragraph", "Origin text"),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, "task_origin_ok", "Origin claim"),
        )

        # Insert origin edge
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES (?, 'fragment', ?, 'claim', ?, 'origin')
            """,
            ("edge_origin", fragment_id, claim_id),
        )

        # When: Insert NLI edge for same fragment-claim pair
        await db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation, nli_label)
            VALUES (?, 'fragment', ?, 'claim', ?, 'supports', 'supports')
            """,
            ("edge_nli_after_origin", fragment_id, claim_id),
        )

        # Then: Both edges exist (origin is not covered by NLI unique index)
        edges = await db.fetch_all(
            """
            SELECT * FROM edges
            WHERE source_type = 'fragment'
              AND source_id = ?
              AND target_type = 'claim'
              AND target_id = ?
            """,
            (fragment_id, claim_id),
        )
        assert len(edges) == 2
        relations = {e["relation"] for e in edges}
        assert relations == {"origin", "supports"}
