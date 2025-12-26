"""
Tests for resource deduplication across workers.

Covers:
- claim_resource/complete_resource/fail_resource/get_resource APIs
- Race condition handling with INSERT OR IGNORE pattern
- Query deduplication in queue_searches
- Integration with pipeline and executor
"""

import asyncio
import json
import uuid

import pytest

from src.storage.database import Database


class TestClaimResource:
    """Test claim_resource method for cross-worker deduplication."""

    @pytest.mark.asyncio
    async def test_first_worker_claims_resource(self, test_database: Database) -> None:
        """
        Given: Empty resource_index
        When: Worker 0 claims a DOI
        Then: Returns (True, None) indicating successful claim
        """
        # Given: Empty resource_index (fresh test database)
        db = test_database

        # When: Worker 0 claims a DOI
        is_new, page_id = await db.claim_resource(
            identifier_type="doi",
            identifier_value="10.1234/test.paper",
            task_id="task_001",
            worker_id=0,
        )

        # Then: Returns (True, None) indicating successful claim
        assert is_new is True
        assert page_id is None

    @pytest.mark.asyncio
    async def test_second_worker_gets_existing_page_id(
        self, test_database: Database
    ) -> None:
        """
        Given: DOI already claimed and completed by Worker 0
        When: Worker 1 claims same DOI
        Then: Returns (False, page_id) with existing page_id
        """
        # Given: DOI already claimed and completed by Worker 0
        db = test_database
        await db.claim_resource(
            identifier_type="doi",
            identifier_value="10.1234/existing.paper",
            task_id="task_001",
            worker_id=0,
        )
        await db.complete_resource(
            identifier_type="doi",
            identifier_value="10.1234/existing.paper",
            page_id="page_abc123",
        )

        # When: Worker 1 claims same DOI
        is_new, page_id = await db.claim_resource(
            identifier_type="doi",
            identifier_value="10.1234/existing.paper",
            task_id="task_001",
            worker_id=1,
        )

        # Then: Returns (False, page_id) with existing page_id
        assert is_new is False
        assert page_id == "page_abc123"

    @pytest.mark.asyncio
    async def test_concurrent_claims_only_one_succeeds(
        self, test_database: Database
    ) -> None:
        """
        Given: Empty resource_index
        When: Two workers claim same DOI simultaneously
        Then: Exactly one gets (True, None), other gets (False, ...)
        """
        # Given: Empty resource_index
        db = test_database
        doi = "10.1234/concurrent.paper"

        # When: Two workers claim same DOI simultaneously
        results = await asyncio.gather(
            db.claim_resource(
                identifier_type="doi",
                identifier_value=doi,
                task_id="task_001",
                worker_id=0,
            ),
            db.claim_resource(
                identifier_type="doi",
                identifier_value=doi,
                task_id="task_001",
                worker_id=1,
            ),
        )

        # Then: Exactly one gets (True, None), other gets (False, ...)
        new_claims = [r for r in results if r[0] is True]
        existing_claims = [r for r in results if r[0] is False]

        assert len(new_claims) == 1, "Exactly one worker should win the race"
        assert len(existing_claims) == 1, "Exactly one worker should see existing"
        assert new_claims[0][1] is None, "Winner should have no existing page_id"

    @pytest.mark.asyncio
    async def test_empty_identifier_value_raises_error(
        self, test_database: Database
    ) -> None:
        """
        Given: Empty identifier_value
        When: claim_resource is called
        Then: ValueError is raised
        """
        # Given: Empty identifier_value
        db = test_database

        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="identifier_value cannot be empty"):
            await db.claim_resource(
                identifier_type="doi",
                identifier_value="",
                task_id="task_001",
                worker_id=0,
            )

    @pytest.mark.asyncio
    async def test_different_identifier_types_are_separate(
        self, test_database: Database
    ) -> None:
        """
        Given: DOI claimed
        When: URL with same value is claimed
        Then: Both succeed as they are different identifier types
        """
        # Given: DOI claimed
        db = test_database
        await db.claim_resource(
            identifier_type="doi",
            identifier_value="10.1234/test",
            task_id="task_001",
            worker_id=0,
        )

        # When: URL with same value is claimed
        is_new, page_id = await db.claim_resource(
            identifier_type="url",
            identifier_value="10.1234/test",
            task_id="task_001",
            worker_id=1,
        )

        # Then: Both succeed as they are different identifier types
        assert is_new is True
        assert page_id is None


class TestCompleteResource:
    """Test complete_resource method."""

    @pytest.mark.asyncio
    async def test_complete_resource_updates_status_and_page_id(
        self, test_database: Database
    ) -> None:
        """
        Given: Resource claimed by worker
        When: complete_resource is called with page_id
        Then: Status is 'completed' and page_id is set
        """
        # Given: Resource claimed by worker
        db = test_database
        await db.claim_resource(
            identifier_type="doi",
            identifier_value="10.1234/complete.test",
            task_id="task_001",
            worker_id=0,
        )

        # When: complete_resource is called with page_id
        await db.complete_resource(
            identifier_type="doi",
            identifier_value="10.1234/complete.test",
            page_id="page_xyz789",
        )

        # Then: Status is 'completed' and page_id is set
        resource = await db.get_resource(
            identifier_type="doi",
            identifier_value="10.1234/complete.test",
        )
        assert resource is not None
        assert resource["status"] == "completed"
        assert resource["page_id"] == "page_xyz789"
        assert resource["completed_at"] is not None


class TestFailResource:
    """Test fail_resource method."""

    @pytest.mark.asyncio
    async def test_fail_resource_updates_status(
        self, test_database: Database
    ) -> None:
        """
        Given: Resource claimed by worker
        When: fail_resource is called
        Then: Status is 'failed'
        """
        # Given: Resource claimed by worker
        db = test_database
        await db.claim_resource(
            identifier_type="doi",
            identifier_value="10.1234/fail.test",
            task_id="task_001",
            worker_id=0,
        )

        # When: fail_resource is called
        await db.fail_resource(
            identifier_type="doi",
            identifier_value="10.1234/fail.test",
            error_message="Test error",
        )

        # Then: Status is 'failed'
        resource = await db.get_resource(
            identifier_type="doi",
            identifier_value="10.1234/fail.test",
        )
        assert resource is not None
        assert resource["status"] == "failed"
        assert resource["completed_at"] is not None


class TestGetResource:
    """Test get_resource method."""

    @pytest.mark.asyncio
    async def test_get_resource_returns_none_for_nonexistent(
        self, test_database: Database
    ) -> None:
        """
        Given: Empty resource_index
        When: get_resource is called
        Then: Returns None
        """
        # Given: Empty resource_index
        db = test_database

        # When: get_resource is called
        resource = await db.get_resource(
            identifier_type="doi",
            identifier_value="10.1234/nonexistent",
        )

        # Then: Returns None
        assert resource is None

    @pytest.mark.asyncio
    async def test_get_resource_returns_all_fields(
        self, test_database: Database
    ) -> None:
        """
        Given: Resource exists
        When: get_resource is called
        Then: Returns all expected fields
        """
        # Given: Resource exists
        db = test_database
        await db.claim_resource(
            identifier_type="pmid",
            identifier_value="12345678",
            task_id="task_002",
            worker_id=2,
        )

        # When: get_resource is called
        resource = await db.get_resource(
            identifier_type="pmid",
            identifier_value="12345678",
        )

        # Then: Returns all expected fields
        assert resource is not None
        assert resource["identifier_type"] == "pmid"
        assert resource["identifier_value"] == "12345678"
        assert resource["task_id"] == "task_002"
        assert resource["worker_id"] == 2
        assert resource["status"] == "processing"
        assert resource["created_at"] is not None
        assert resource["claimed_at"] is not None


class TestInsertOrIgnore:
    """Test insert with or_ignore option."""

    @pytest.mark.asyncio
    async def test_insert_or_ignore_silently_skips_on_conflict(
        self, test_database: Database
    ) -> None:
        """
        Given: A unique constraint exists
        When: Duplicate row is inserted with or_ignore=True
        Then: No error is raised, first row is preserved
        """
        # Given: Insert a resource
        db = test_database
        await db.insert(
            "resource_index",
            {
                "id": "res_001",
                "identifier_type": "doi",
                "identifier_value": "10.1234/ignore.test",
                "task_id": "task_001",
                "status": "pending",
                "worker_id": 0,
            },
        )

        # When: Duplicate row is inserted with or_ignore=True
        await db.insert(
            "resource_index",
            {
                "id": "res_002",  # Different ID
                "identifier_type": "doi",
                "identifier_value": "10.1234/ignore.test",  # Same value
                "task_id": "task_002",
                "status": "processing",
                "worker_id": 1,
            },
            or_ignore=True,
        )

        # Then: No error is raised, first row is preserved
        resource = await db.get_resource(
            identifier_type="doi",
            identifier_value="10.1234/ignore.test",
        )
        assert resource is not None
        assert resource["id"] == "res_001"  # First row preserved
        assert resource["task_id"] == "task_001"


class TestQueueSearchesDedup:
    """Test query deduplication in queue_searches handler."""

    @pytest.mark.asyncio
    async def test_duplicate_query_is_skipped(self, test_database: Database) -> None:
        """
        Given: Query 'foo' already queued for task
        When: queue_searches called with same query
        Then: Query not duplicated in jobs table
        """
        # Given: Query 'foo' already queued for task
        db = test_database
        task_id = f"task_{uuid.uuid4().hex[:8]}"

        # Create task first
        await db.insert("tasks", {"id": task_id, "query": "test", "status": "running"})

        # Queue first search
        input_data = {"query": "test query", "options": {}}
        await db.execute(
            """
            INSERT INTO jobs
                (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "s_first",
                task_id,
                "search_queue",
                50,
                "network_client",
                "queued",
                json.dumps(input_data),
            ),
        )

        # When: Check for duplicate (simulating queue_searches logic)
        existing = await db.fetch_one(
            """
            SELECT id FROM jobs
            WHERE task_id = ? AND kind = 'search_queue'
              AND state IN ('queued', 'running')
              AND json_extract(input_json, '$.query') = ?
            """,
            (task_id, "test query"),
        )

        # Then: Duplicate is detected
        assert existing is not None
        assert existing["id"] == "s_first"

    @pytest.mark.asyncio
    async def test_same_query_different_task_is_allowed(
        self, test_database: Database
    ) -> None:
        """
        Given: Query 'foo' queued for task_1
        When: Same query queued for task_2
        Then: Both are allowed (different tasks)
        """
        # Given: Query 'foo' queued for task_1
        db = test_database
        task_1 = f"task_1_{uuid.uuid4().hex[:8]}"
        task_2 = f"task_2_{uuid.uuid4().hex[:8]}"

        # Create tasks
        await db.insert("tasks", {"id": task_1, "query": "test", "status": "running"})
        await db.insert("tasks", {"id": task_2, "query": "test", "status": "running"})

        # Queue search for task_1
        input_data = {"query": "shared query", "options": {}}
        await db.execute(
            """
            INSERT INTO jobs
                (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "s_task1",
                task_1,
                "search_queue",
                50,
                "network_client",
                "queued",
                json.dumps(input_data),
            ),
        )

        # When: Check for duplicate in task_2
        existing = await db.fetch_one(
            """
            SELECT id FROM jobs
            WHERE task_id = ? AND kind = 'search_queue'
              AND state IN ('queued', 'running')
              AND json_extract(input_json, '$.query') = ?
            """,
            (task_2, "shared query"),
        )

        # Then: No duplicate detected (different task)
        assert existing is None

    @pytest.mark.asyncio
    async def test_completed_query_can_be_requeued(
        self, test_database: Database
    ) -> None:
        """
        Given: Query 'foo' completed for task
        When: Same query queued again
        Then: Query is allowed (not in queued/running state)
        """
        # Given: Query 'foo' completed for task
        db = test_database
        task_id = f"task_{uuid.uuid4().hex[:8]}"

        # Create task
        await db.insert("tasks", {"id": task_id, "query": "test", "status": "running"})

        # Queue and complete search
        input_data = {"query": "requeue test", "options": {}}
        await db.execute(
            """
            INSERT INTO jobs
                (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "s_completed",
                task_id,
                "search_queue",
                50,
                "network_client",
                "completed",  # Already completed
                json.dumps(input_data),
            ),
        )

        # When: Check for duplicate
        existing = await db.fetch_one(
            """
            SELECT id FROM jobs
            WHERE task_id = ? AND kind = 'search_queue'
              AND state IN ('queued', 'running')
              AND json_extract(input_json, '$.query') = ?
            """,
            (task_id, "requeue test"),
        )

        # Then: No duplicate detected (completed state not checked)
        assert existing is None


class TestResourceIndexIntegration:
    """Integration tests for resource deduplication flow."""

    @pytest.mark.asyncio
    async def test_full_workflow_claim_complete_retrieve(
        self, test_database: Database
    ) -> None:
        """
        Given: Fresh database
        When: Full workflow: claim -> complete -> retrieve by second worker
        Then: Second worker gets completed page_id
        """
        # Given: Fresh database
        db = test_database

        # When: Worker 0 claims resource
        is_new_0, _ = await db.claim_resource(
            identifier_type="arxiv",
            identifier_value="2401.12345",
            task_id="task_001",
            worker_id=0,
        )
        assert is_new_0 is True

        # Worker 0 completes resource
        await db.complete_resource(
            identifier_type="arxiv",
            identifier_value="2401.12345",
            page_id="page_arxiv_001",
        )

        # Then: Worker 1 gets completed page_id
        is_new_1, page_id = await db.claim_resource(
            identifier_type="arxiv",
            identifier_value="2401.12345",
            task_id="task_001",
            worker_id=1,
        )
        assert is_new_1 is False
        assert page_id == "page_arxiv_001"

    @pytest.mark.asyncio
    async def test_url_normalization_not_applied(
        self, test_database: Database
    ) -> None:
        """
        Given: URL with trailing slash
        When: Same URL without trailing slash is claimed
        Then: They are treated as different (caller must normalize)

        Note: URL normalization is the caller's responsibility.
        """
        # Given: URL with trailing slash claimed
        db = test_database
        await db.claim_resource(
            identifier_type="url",
            identifier_value="https://example.com/page/",
            task_id="task_001",
            worker_id=0,
        )

        # When: Same URL without trailing slash is claimed
        is_new, page_id = await db.claim_resource(
            identifier_type="url",
            identifier_value="https://example.com/page",  # No trailing slash
            task_id="task_001",
            worker_id=1,
        )

        # Then: Treated as different (caller must normalize)
        assert is_new is True
        assert page_id is None

