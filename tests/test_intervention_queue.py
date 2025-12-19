"""
Tests for InterventionQueue (Semi-automatic Operation) per §3.6.1.

Test Classification (§7.1.7):
- All tests here are unit tests (no external dependencies)
- Database uses in-memory SQLite for isolation

Requirements tested per §3.6.1 (Safe Operation Policy):
- Authentication queue with user-driven completion (no timeout)
- start_session returns URLs only (no DOM operations)
- User finds and resolves challenges themselves
- complete_authentication is primary completion method

Test Quality Standards (§7.1):
- No conditional assertions (§7.1.1.1)
- Specific value assertions (§7.1.1.2)
- No OR-condition assertions (§7.1.1.3)
- AAA pattern (Arrange-Act-Assert)
- Docstrings explaining test intent

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-QI-N-01 | Queue init | Equivalence – normal | _db is None | - |
| TC-QI-N-02 | ensure_db | Equivalence – normal | Connection established | - |
| TC-EN-N-01 | enqueue | Equivalence – normal | Returns queue_id | - |
| TC-EN-N-02 | enqueue stores fields | Equivalence – normal | All fields stored | - |
| TC-EN-N-03 | Default priority | Equivalence – normal | "medium" | - |
| TC-EN-N-04 | Default expiration | Equivalence – normal | 1 hour | - |
| TC-EN-N-05 | Custom expiration | Equivalence – normal | Custom value used | - |
| TC-GP-B-01 | get_pending empty | Boundary – empty | Empty list | - |
| TC-GP-N-01 | get_pending items | Equivalence – normal | Returns items | - |
| TC-GP-N-02 | Order by priority | Equivalence – normal | high > medium > low | - |
| TC-GP-N-03 | Filter by task_id | Equivalence – normal | Correct filtering | - |
| TC-GP-N-04 | Filter by priority | Equivalence – normal | Correct filtering | - |
| TC-GP-N-05 | Respects limit | Equivalence – normal | Limited results | - |
| TC-GC-B-01 | Empty queue counts | Boundary – zero | All zeros | - |
| TC-GC-N-01 | Count by priority | Equivalence – normal | Correct counts | - |
| TC-SS-B-01 | Empty queue session | Boundary – empty | session_started=False | - |
| TC-SS-N-01 | Marks in_progress | Equivalence – normal | Status changed | - |
| TC-SS-N-02 | Returns item details | Equivalence – normal | All fields | - |
| TC-SS-N-03 | Specific queue_ids | Equivalence – normal | Only those processed | - |
| TC-SS-N-04 | Priority filter | Equivalence – normal | Filtered correctly | - |
| TC-CM-N-01 | Complete success | Equivalence – normal | status=completed | - |
| TC-CM-N-02 | Complete failure | Equivalence – normal | status=skipped | - |
| TC-CM-N-03 | Stores session data | Equivalence – normal | Data retrievable | - |
| TC-CM-N-04 | Returns URL/domain | Equivalence – normal | Correct values | - |
| TC-SK-N-01 | Skip all for task | Equivalence – normal | All skipped | - |
| TC-SK-N-02 | Skip specific IDs | Equivalence – normal | Only those skipped | - |
| TC-SK-N-03 | Skip in_progress | Equivalence – normal | Works correctly | - |
| TC-GS-A-01 | No session | Equivalence – abnormal | Returns None | - |
| TC-GS-N-01 | Returns session | Equivalence – normal | Correct data | - |
| TC-GS-N-02 | Most recent | Equivalence – normal | Latest returned | - |
| TC-CL-N-01 | Cleanup expired | Equivalence – normal | Expired marked | - |
| TC-CL-N-02 | Valid unaffected | Equivalence – normal | Still pending | - |
| TC-BC-B-01 | Limit 0 | Boundary – zero | Empty list | - |
| TC-BC-A-01 | Nonexistent IDs | Equivalence – abnormal | No items | - |
| TC-BC-A-02 | Complete nonexistent | Equivalence – abnormal | ok=True, None values | - |
| TC-SU-B-01 | Empty queue summary | Boundary – zero | All zeros | - |
| TC-SU-N-01 | Counts correctly | Equivalence – normal | Correct totals | - |
| TC-SU-N-02 | Distinct domains | Equivalence – normal | Unique list | - |
| TC-SU-N-03 | Oldest queued_at | Equivalence – normal | Timestamp present | - |
| TC-SU-N-04 | By auth_type | Equivalence – normal | Correct breakdown | - |
| TC-GQ-N-01 | Returns instance | Equivalence – normal | InterventionQueue | - |
| TC-GQ-N-02 | Singleton | Equivalence – normal | Same instance | - |
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from src.utils.notification import InterventionQueue, get_intervention_queue

# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def queue_with_db(test_database):
    """Create InterventionQueue with real in-memory database.

    Per §7.1.7: Database should use in-memory SQLite for unit tests.
    """
    queue = InterventionQueue()
    queue._db = test_database
    return queue


@pytest_asyncio.fixture
async def sample_task_id(test_database):
    """Create a sample task and return its ID.

    Per schema: intervention_queue.task_id references tasks(id)
    """
    task_id = await test_database.create_task(query="Test query for intervention queue")
    return task_id


@pytest.fixture
def sample_domains():
    """Sample domains for testing.

    Per §7.1.3: Test data should be realistic and diverse.
    """
    return ["example.com", "cloudflare-protected.com", "login-required.org"]


# =============================================================================
# InterventionQueue Initialization Tests
# =============================================================================


@pytest.mark.unit
class TestInterventionQueueInit:
    """Tests for InterventionQueue initialization.

    Verifies correct construction and database connection.
    """

    def test_queue_initializes_with_null_db(self):
        """Test queue initializes with _db as None before use."""
        # When
        queue = InterventionQueue()

        # Then
        assert queue._db is None, "_db should be None before _ensure_db is called"

    @pytest.mark.asyncio
    async def test_ensure_db_creates_connection(self, test_database):
        """Test _ensure_db establishes database connection."""
        # Given
        queue = InterventionQueue()

        with patch(
            "src.utils.notification.get_database",
            new_callable=AsyncMock,
            return_value=test_database,
        ):
            # When
            await queue._ensure_db()

            # Then
            assert queue._db is not None, "_db should not be None after _ensure_db"
            assert queue._db == test_database, "_db should be the database returned by get_database"


# =============================================================================
# Enqueue Tests (§3.6.1)
# =============================================================================


@pytest.mark.unit
class TestEnqueue:
    """Tests for enqueue functionality.

    Per §3.6.1: Queue URLs requiring auth instead of blocking immediately.
    """

    @pytest.mark.asyncio
    async def test_enqueue_returns_queue_id(self, queue_with_db, sample_task_id):
        """Test enqueue returns a valid queue ID string."""
        # When
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/protected",
            domain="example.com",
            auth_type="cloudflare",
        )

        # Then
        assert isinstance(queue_id, str), f"queue_id should be string, got {type(queue_id)}"
        assert queue_id.startswith("iq_"), f"queue_id should start with 'iq_', got '{queue_id}'"
        assert len(queue_id) == 15, (  # "iq_" + 12 hex chars
            f"queue_id should have length 15, got {len(queue_id)}"
        )

    @pytest.mark.asyncio
    async def test_enqueue_stores_all_fields(self, queue_with_db, sample_task_id):
        """Test enqueue stores all required fields in database."""
        # Given
        url = "https://secure.example.com/page"
        domain = "secure.example.com"
        auth_type = "captcha"
        priority = "high"

        # When
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url=url,
            domain=domain,
            auth_type=auth_type,
            priority=priority,
        )

        # Then: Verify by fetching
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(items) == 1, f"Should have 1 item in queue, got {len(items)}"

        item = items[0]
        assert item["id"] == queue_id, f"Item ID should be '{queue_id}', got '{item['id']}'"
        assert item["url"] == url, f"URL should be '{url}', got '{item['url']}'"
        assert item["domain"] == domain, f"Domain should be '{domain}', got '{item['domain']}'"
        assert item["auth_type"] == auth_type, (
            f"auth_type should be '{auth_type}', got '{item['auth_type']}'"
        )
        assert item["priority"] == priority, (
            f"priority should be '{priority}', got '{item['priority']}'"
        )
        assert item["status"] == "pending", (
            f"Initial status should be 'pending', got '{item['status']}'"
        )

    @pytest.mark.asyncio
    async def test_enqueue_default_priority_is_medium(self, queue_with_db, sample_task_id):
        """Test enqueue uses 'medium' as default priority."""
        # When
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
            # No priority specified - should default to 'medium'
        )

        # Then
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        assert items[0]["priority"] == "medium", (
            f"Default priority should be 'medium', got '{items[0]['priority']}'"
        )

    @pytest.mark.asyncio
    async def test_enqueue_sets_default_expiration_one_hour(self, queue_with_db, sample_task_id):
        """Test enqueue sets default expiration to 1 hour from now.

        Per design: Default expiration: 1 hour from now
        """
        # Given
        before = datetime.now(UTC)

        # When
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )

        after = datetime.now(UTC)

        # Then
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        expires_str = items[0]["expires_at"]
        assert expires_str is not None, "expires_at should be set"

        # Parse and verify within 1 hour +/- 1 minute
        expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        expected_min = before + timedelta(hours=1) - timedelta(minutes=1)
        expected_max = after + timedelta(hours=1) + timedelta(minutes=1)

        assert expected_min <= expires <= expected_max, (
            f"expires_at should be ~1 hour from now, got {expires}"
        )

    @pytest.mark.asyncio
    async def test_enqueue_custom_expiration(self, queue_with_db, sample_task_id):
        """Test enqueue respects custom expiration time."""
        # Given
        custom_expires = datetime.now(UTC) + timedelta(hours=2)

        # When
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
            expires_at=custom_expires,
        )

        # Then
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        expires_str = items[0]["expires_at"]
        expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))

        # Allow 1 second tolerance for test execution
        delta = abs((expires - custom_expires).total_seconds())
        assert delta < 2, f"expires_at should match custom value, delta was {delta}s"


# =============================================================================
# Get Pending Tests (§3.6.1)
# =============================================================================


@pytest.mark.unit
class TestGetPending:
    """Tests for get_pending functionality.

    Per §3.6.1: Priority management: high (primary sources), medium (secondary), low.
    """

    @pytest.mark.asyncio
    async def test_get_pending_empty_returns_empty_list(self, queue_with_db, sample_task_id):
        """Test get_pending returns empty list when queue is empty."""
        # When
        items = await queue_with_db.get_pending(task_id=sample_task_id)

        # Then
        assert items == [], f"Empty queue should return [], got {items}"

    @pytest.mark.asyncio
    async def test_get_pending_returns_correct_items(self, queue_with_db, sample_task_id):
        """Test get_pending returns enqueued items."""
        # Given: Add 3 items
        urls = [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://example.com/page3",
        ]
        for url in urls:
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url=url,
                domain="example.com",
                auth_type="cloudflare",
            )

        # When
        items = await queue_with_db.get_pending(task_id=sample_task_id)

        # Then
        assert len(items) == 3, f"Should return 3 items, got {len(items)}"
        returned_urls = [item["url"] for item in items]
        for url in urls:
            assert url in returned_urls, f"URL '{url}' should be in returned items"

    @pytest.mark.asyncio
    async def test_get_pending_orders_by_priority(self, queue_with_db, sample_task_id):
        """Test get_pending returns items ordered by priority (high first).

        Per §3.6.1: Priority management - high > medium > low.
        """
        # Given: Add items in reverse priority order
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/low",
            domain="example.com",
            auth_type="cloudflare",
            priority="low",
        )
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/high",
            domain="example.com",
            auth_type="cloudflare",
            priority="high",
        )
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/medium",
            domain="example.com",
            auth_type="cloudflare",
            priority="medium",
        )

        # When
        items = await queue_with_db.get_pending(task_id=sample_task_id)

        # Then: Should be ordered high, medium, low
        priorities = [item["priority"] for item in items]
        assert priorities == ["high", "medium", "low"], (
            f"Items should be ordered by priority, got {priorities}"
        )

    @pytest.mark.asyncio
    async def test_get_pending_filters_by_task_id(self, queue_with_db, test_database):
        """Test get_pending filters by task_id correctly."""
        # Given: Create two tasks and add items to each
        task1 = await test_database.create_task(query="Task 1 query")
        task2 = await test_database.create_task(query="Task 2 query")

        await queue_with_db.enqueue(
            task_id=task1,
            url="https://task1.com/page",
            domain="task1.com",
            auth_type="cloudflare",
        )
        await queue_with_db.enqueue(
            task_id=task2,
            url="https://task2.com/page",
            domain="task2.com",
            auth_type="cloudflare",
        )

        # When
        items_task1 = await queue_with_db.get_pending(task_id=task1)
        items_task2 = await queue_with_db.get_pending(task_id=task2)

        # Then
        assert len(items_task1) == 1, f"Task 1 should have 1 item, got {len(items_task1)}"
        assert items_task1[0]["domain"] == "task1.com", (
            f"Task 1 item domain should be 'task1.com', got '{items_task1[0]['domain']}'"
        )

        assert len(items_task2) == 1, f"Task 2 should have 1 item, got {len(items_task2)}"
        assert items_task2[0]["domain"] == "task2.com", (
            f"Task 2 item domain should be 'task2.com', got '{items_task2[0]['domain']}'"
        )

    @pytest.mark.asyncio
    async def test_get_pending_filters_by_priority(self, queue_with_db, sample_task_id):
        """Test get_pending filters by priority correctly."""
        # Given: Add items with different priorities
        for priority in ["high", "medium", "low"]:
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url=f"https://example.com/{priority}",
                domain="example.com",
                auth_type="cloudflare",
                priority=priority,
            )

        # When
        high_items = await queue_with_db.get_pending(
            task_id=sample_task_id,
            priority="high",
        )

        # Then
        assert len(high_items) == 1, f"Should have 1 high priority item, got {len(high_items)}"
        assert high_items[0]["priority"] == "high", (
            f"Item priority should be 'high', got '{high_items[0]['priority']}'"
        )

    @pytest.mark.asyncio
    async def test_get_pending_respects_limit(self, queue_with_db, sample_task_id):
        """Test get_pending respects limit parameter."""
        # Given: Add 10 items
        for i in range(10):
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url=f"https://example.com/page{i}",
                domain="example.com",
                auth_type="cloudflare",
            )

        # When
        items = await queue_with_db.get_pending(task_id=sample_task_id, limit=3)

        # Then
        assert len(items) == 3, f"Should return 3 items with limit=3, got {len(items)}"


# =============================================================================
# Get Pending Count Tests
# =============================================================================


@pytest.mark.unit
class TestGetPendingCount:
    """Tests for get_pending_count functionality."""

    @pytest.mark.asyncio
    async def test_get_pending_count_empty_queue(self, queue_with_db, sample_task_id):
        """Test get_pending_count returns zeros for empty queue."""
        # When
        counts = await queue_with_db.get_pending_count(sample_task_id)

        # Then
        assert counts["high"] == 0, f"high count should be 0, got {counts['high']}"
        assert counts["medium"] == 0, f"medium count should be 0, got {counts['medium']}"
        assert counts["low"] == 0, f"low count should be 0, got {counts['low']}"
        assert counts["total"] == 0, f"total count should be 0, got {counts['total']}"

    @pytest.mark.asyncio
    async def test_get_pending_count_by_priority(self, queue_with_db, sample_task_id):
        """Test get_pending_count returns correct counts by priority."""
        # Given: Add specific number of each priority
        for _ in range(2):
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url="https://example.com/high",
                domain="example.com",
                auth_type="cloudflare",
                priority="high",
            )
        for _ in range(3):
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url="https://example.com/medium",
                domain="example.com",
                auth_type="cloudflare",
                priority="medium",
            )
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/low",
            domain="example.com",
            auth_type="cloudflare",
            priority="low",
        )

        # When
        counts = await queue_with_db.get_pending_count(sample_task_id)

        # Then
        assert counts["high"] == 2, f"high count should be 2, got {counts['high']}"
        assert counts["medium"] == 3, f"medium count should be 3, got {counts['medium']}"
        assert counts["low"] == 1, f"low count should be 1, got {counts['low']}"
        assert counts["total"] == 6, f"total count should be 6, got {counts['total']}"


# =============================================================================
# Start Session Tests (§3.6.1 Safe Operation Policy)
# =============================================================================


@pytest.mark.unit
class TestStartSession:
    """Tests for start_session functionality per §3.6.1.

    Safe Operation Policy:
    - Returns URLs for user to process (no DOM operations)
    - User finds and resolves challenges themselves
    - User calls complete_authentication when done
    - No timeout enforcement (user-driven completion)
    """

    @pytest.mark.asyncio
    async def test_start_session_empty_queue(self, queue_with_db, sample_task_id):
        """Test start_session with empty queue returns appropriate response."""
        # When
        result = await queue_with_db.start_session(task_id=sample_task_id)

        # Then
        assert result["ok"] is True, "ok should be True even with empty queue"
        assert result["session_started"] is False, (
            "session_started should be False with no pending items"
        )
        assert result["count"] == 0, f"count should be 0, got {result['count']}"
        assert result["items"] == [], f"items should be empty list, got {result['items']}"

    @pytest.mark.asyncio
    async def test_start_session_marks_items_in_progress(self, queue_with_db, sample_task_id):
        """Test start_session changes item status to 'in_progress'."""
        # Given
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )

        # When
        result = await queue_with_db.start_session(task_id=sample_task_id)

        # Then
        assert result["session_started"] is True, "session_started should be True"
        assert result["count"] == 1, f"count should be 1, got {result['count']}"

        # Verify status changed - pending items should be 0 now
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 0, (
            f"No items should be pending after start_session, got {len(pending)}"
        )

    @pytest.mark.asyncio
    async def test_start_session_returns_item_details(self, queue_with_db, sample_task_id):
        """Test start_session returns correct item details."""
        # Given
        url = "https://protected.example.com/secure"
        domain = "protected.example.com"
        auth_type = "turnstile"
        priority = "high"

        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url=url,
            domain=domain,
            auth_type=auth_type,
            priority=priority,
        )

        # When
        result = await queue_with_db.start_session(task_id=sample_task_id)

        # Then
        items = result["items"]
        assert len(items) == 1, f"Should return 1 item, got {len(items)}"

        item = items[0]
        assert item["url"] == url, f"Item URL should be '{url}', got '{item['url']}'"
        assert item["domain"] == domain, f"Item domain should be '{domain}', got '{item['domain']}'"
        assert item["auth_type"] == auth_type, (
            f"Item auth_type should be '{auth_type}', got '{item['auth_type']}'"
        )
        assert item["priority"] == priority, (
            f"Item priority should be '{priority}', got '{item['priority']}'"
        )

    @pytest.mark.asyncio
    async def test_start_session_with_specific_queue_ids(self, queue_with_db, sample_task_id):
        """Test start_session with specific queue_ids."""
        # Given: Add multiple items
        id1 = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page1",
            domain="example.com",
            auth_type="cloudflare",
        )
        id2 = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page2",
            domain="example.com",
            auth_type="cloudflare",
        )
        id3 = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page3",
            domain="example.com",
            auth_type="cloudflare",
        )

        # When: Start session with only 2 specific IDs
        result = await queue_with_db.start_session(
            task_id=sample_task_id,
            queue_ids=[id1, id3],
        )

        # Then
        assert result["count"] == 2, f"Should process 2 items, got {result['count']}"

        # id2 should still be pending
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 1, f"Should have 1 pending item, got {len(pending)}"
        assert pending[0]["id"] == id2, f"Pending item should be id2, got '{pending[0]['id']}'"

    @pytest.mark.asyncio
    async def test_start_session_filters_by_priority(self, queue_with_db, sample_task_id):
        """Test start_session filters by priority when specified."""
        # Given
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/high",
            domain="example.com",
            auth_type="cloudflare",
            priority="high",
        )
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/low",
            domain="example.com",
            auth_type="cloudflare",
            priority="low",
        )

        # When: Start session for high priority only
        result = await queue_with_db.start_session(
            task_id=sample_task_id,
            priority_filter="high",
        )

        # Then
        assert result["count"] == 1, f"Should process 1 high priority item, got {result['count']}"
        assert result["items"][0]["priority"] == "high", "Processed item should be high priority"

        # Low priority should still be pending
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 1, f"Should have 1 pending item, got {len(pending)}"
        assert pending[0]["priority"] == "low", "Pending item should be low priority"


# =============================================================================
# Complete Tests (§3.6.1 - Primary Completion Method)
# =============================================================================


@pytest.mark.unit
class TestComplete:
    """Tests for complete functionality per §3.6.1.

    Per §3.6.1: complete_authentication is the primary completion method.
    User explicitly reports when they have resolved the authentication challenge.
    This is the only way to mark authentication as complete (no timeout/auto-detect).
    """

    @pytest.mark.asyncio
    async def test_complete_success_updates_status(self, queue_with_db, sample_task_id):
        """Test complete with success=True sets status to 'completed'."""
        # Given
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)

        # When
        result = await queue_with_db.complete(queue_id=queue_id, success=True)

        # Then
        assert result["ok"] is True, "ok should be True"
        assert result["queue_id"] == queue_id, (
            f"queue_id should be '{queue_id}', got '{result['queue_id']}'"
        )
        assert result["status"] == "completed", (
            f"status should be 'completed', got '{result['status']}'"
        )

    @pytest.mark.asyncio
    async def test_complete_failure_updates_status(self, queue_with_db, sample_task_id):
        """Test complete with success=False sets status to 'skipped'."""
        # Given
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)

        # When
        result = await queue_with_db.complete(queue_id=queue_id, success=False)

        # Then
        assert result["status"] == "skipped", (
            f"status should be 'skipped' on failure, got '{result['status']}'"
        )

    @pytest.mark.asyncio
    async def test_complete_stores_session_data(self, queue_with_db, sample_task_id):
        """Test complete stores session data when provided.

        Per §3.6.1: Session reuse - store authenticated session data.
        """
        # Given
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)

        session_data = {
            "cookies": [{"name": "cf_clearance", "value": "abc123"}],
            "authenticated_at": datetime.now(UTC).isoformat(),
        }

        # When
        await queue_with_db.complete(
            queue_id=queue_id,
            success=True,
            session_data=session_data,
        )

        # Then: Retrieve session data
        stored_session = await queue_with_db.get_session_for_domain(
            domain="example.com",
        )
        assert stored_session is not None, "Session data should be stored"
        assert stored_session["cookies"][0]["name"] == "cf_clearance", (
            "Session cookie name should be 'cf_clearance'"
        )

    @pytest.mark.asyncio
    async def test_complete_returns_url_and_domain(self, queue_with_db, sample_task_id):
        """Test complete returns the URL and domain of completed item."""
        # Given
        url = "https://secure.example.com/protected"
        domain = "secure.example.com"
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url=url,
            domain=domain,
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)

        # When
        result = await queue_with_db.complete(queue_id=queue_id, success=True)

        # Then
        assert result["url"] == url, f"URL should be '{url}', got '{result['url']}'"
        assert result["domain"] == domain, f"Domain should be '{domain}', got '{result['domain']}'"


# =============================================================================
# Skip Tests (§3.6.1)
# =============================================================================


@pytest.mark.unit
class TestSkip:
    """Tests for skip functionality.

    Per §3.6.1: skip_authentication - skip authentication.
    """

    @pytest.mark.asyncio
    async def test_skip_all_for_task(self, queue_with_db, sample_task_id):
        """Test skip without queue_ids skips all items for task."""
        # Given
        for i in range(3):
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url=f"https://example.com/page{i}",
                domain="example.com",
                auth_type="cloudflare",
            )

        # When
        result = await queue_with_db.skip(task_id=sample_task_id)

        # Then
        assert result["ok"] is True, "ok should be True"
        assert result["skipped"] >= 3, f"Should skip at least 3 items, got {result['skipped']}"

        # Verify no pending items remain
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 0, f"Should have no pending items, got {len(pending)}"

    @pytest.mark.asyncio
    async def test_skip_specific_queue_ids(self, queue_with_db, sample_task_id):
        """Test skip with specific queue_ids skips only those items."""
        # Given
        id1 = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page1",
            domain="example.com",
            auth_type="cloudflare",
        )
        id2 = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page2",
            domain="example.com",
            auth_type="cloudflare",
        )

        # When: Skip only id1
        await queue_with_db.skip(task_id=sample_task_id, queue_ids=[id1])

        # Then: id2 should still be pending
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 1, f"Should have 1 pending item, got {len(pending)}"
        assert pending[0]["id"] == id2, "Pending item should be id2"

    @pytest.mark.asyncio
    async def test_skip_in_progress_items(self, queue_with_db, sample_task_id):
        """Test skip works on items that are in_progress."""
        # Given
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)

        # When
        result = await queue_with_db.skip(task_id=sample_task_id)

        # Then: Should have skipped the in_progress item
        assert result["ok"] is True, "ok should be True"


# =============================================================================
# Get Session for Domain Tests (§3.6.1)
# =============================================================================


@pytest.mark.unit
class TestGetSessionForDomain:
    """Tests for get_session_for_domain functionality.

    Per §3.6.1: Session reuse - reuse for subsequent requests to same domain.
    """

    @pytest.mark.asyncio
    async def test_get_session_returns_none_when_no_session(self, queue_with_db):
        """Test get_session_for_domain returns None when no session exists."""
        # When
        session = await queue_with_db.get_session_for_domain(domain="unknown.com")

        # Then
        assert session is None, "Should return None when no session exists"

    @pytest.mark.asyncio
    async def test_get_session_returns_stored_session(self, queue_with_db, sample_task_id):
        """Test get_session_for_domain returns stored session data."""
        # Given: Complete an authentication with session data
        domain = "example.com"
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url=f"https://{domain}/page",
            domain=domain,
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)

        session_data = {
            "cf_token": "secret_token_123",
            "expires": "2024-12-31",
        }
        await queue_with_db.complete(
            queue_id=queue_id,
            success=True,
            session_data=session_data,
        )

        # When
        retrieved = await queue_with_db.get_session_for_domain(domain=domain)

        # Then
        assert retrieved is not None, "Should return session data"
        assert retrieved["cf_token"] == "secret_token_123", (
            f"cf_token should be 'secret_token_123', got '{retrieved['cf_token']}'"
        )

    @pytest.mark.asyncio
    async def test_get_session_returns_most_recent(self, queue_with_db, sample_task_id):
        """Test get_session_for_domain returns the most recent session."""
        # Given: Complete two authentications for same domain
        domain = "example.com"

        # First authentication
        id1 = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url=f"https://{domain}/page1",
            domain=domain,
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id, queue_ids=[id1])
        await queue_with_db.complete(
            queue_id=id1,
            success=True,
            session_data={"version": "old"},
        )

        # Second authentication (more recent)
        id2 = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url=f"https://{domain}/page2",
            domain=domain,
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id, queue_ids=[id2])
        await queue_with_db.complete(
            queue_id=id2,
            success=True,
            session_data={"version": "new"},
        )

        # When
        session = await queue_with_db.get_session_for_domain(domain=domain)

        # Then
        assert session["version"] == "new", (
            f"Should return most recent session, got version '{session['version']}'"
        )


# =============================================================================
# Cleanup Expired Tests
# =============================================================================


@pytest.mark.unit
class TestCleanupExpired:
    """Tests for cleanup_expired functionality."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_marks_expired_items(self, queue_with_db, sample_task_id):
        """Test cleanup_expired marks expired items correctly."""
        # Given: Add item with past expiration
        past_time = datetime.now(UTC) - timedelta(hours=1)
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/expired",
            domain="example.com",
            auth_type="cloudflare",
            expires_at=past_time,
        )

        # When
        cleaned = await queue_with_db.cleanup_expired()

        # Then
        assert cleaned >= 1, f"Should have cleaned at least 1 expired item, got {cleaned}"

        # Verify item is no longer pending
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 0, f"Should have no pending items after cleanup, got {len(pending)}"

    @pytest.mark.asyncio
    async def test_cleanup_does_not_affect_valid_items(self, queue_with_db, sample_task_id):
        """Test cleanup_expired does not affect non-expired items."""
        # Given: Add item with future expiration
        future_time = datetime.now(UTC) + timedelta(hours=2)
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/valid",
            domain="example.com",
            auth_type="cloudflare",
            expires_at=future_time,
        )

        # When
        await queue_with_db.cleanup_expired()

        # Then: Item should still be pending
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 1, f"Valid item should still be pending, got {len(pending)}"


# =============================================================================
# Boundary Condition Tests (§7.1.2.4)
# =============================================================================


@pytest.mark.unit
class TestBoundaryConditions:
    """Tests for boundary conditions per §7.1.2.4."""

    @pytest.mark.asyncio
    async def test_get_pending_with_limit_zero(self, queue_with_db, sample_task_id):
        """Test get_pending with limit=0 returns empty list."""
        # Given
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )

        # When
        items = await queue_with_db.get_pending(task_id=sample_task_id, limit=0)

        # Then
        assert items == [], f"limit=0 should return empty list, got {len(items)} items"

    @pytest.mark.asyncio
    async def test_start_session_with_nonexistent_queue_ids(self, queue_with_db, sample_task_id):
        """Test start_session with non-existent queue_ids."""
        # When
        result = await queue_with_db.start_session(
            task_id=sample_task_id,
            queue_ids=["nonexistent_id_1", "nonexistent_id_2"],
        )

        # Then
        assert result["session_started"] is False, (
            "session_started should be False for non-existent IDs"
        )
        assert result["count"] == 0, (
            f"count should be 0 for non-existent IDs, got {result['count']}"
        )

    @pytest.mark.asyncio
    async def test_complete_nonexistent_queue_id(self, queue_with_db):
        """Test complete with non-existent queue_id."""
        # When
        result = await queue_with_db.complete(
            queue_id="nonexistent_id",
            success=True,
        )

        # Then: Should return ok but with None values
        assert result["ok"] is True, "ok should be True even for non-existent ID"
        assert result["url"] is None, "url should be None for non-existent ID"
        assert result["domain"] is None, "domain should be None for non-existent ID"


# =============================================================================
# Get Authentication Queue Summary Tests (§16.7.1)
# =============================================================================


@pytest.mark.unit
class TestGetAuthenticationQueueSummary:
    """Tests for get_authentication_queue_summary functionality.

    Per §16.7.1: Provides comprehensive summary for get_exploration_status.
    """

    @pytest.mark.asyncio
    async def test_summary_empty_queue_returns_zeros(self, queue_with_db, sample_task_id):
        """Test summary returns zeros for empty queue."""
        # When
        summary = await queue_with_db.get_authentication_queue_summary(sample_task_id)

        # Then
        assert summary["pending_count"] == 0, (
            f"pending_count should be 0, got {summary['pending_count']}"
        )
        assert summary["high_priority_count"] == 0, (
            f"high_priority_count should be 0, got {summary['high_priority_count']}"
        )
        assert summary["domains"] == [], f"domains should be empty, got {summary['domains']}"
        assert summary["oldest_queued_at"] is None, "oldest_queued_at should be None"
        assert summary["by_auth_type"] == {}, (
            f"by_auth_type should be empty, got {summary['by_auth_type']}"
        )

    @pytest.mark.asyncio
    async def test_summary_counts_correctly(self, queue_with_db, sample_task_id):
        """Test summary returns correct counts."""
        # Given: Add items with different priorities
        for _ in range(2):
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url="https://primary.gov/doc",
                domain="primary.gov",
                auth_type="cloudflare",
                priority="high",
            )
        for _ in range(3):
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url="https://secondary.com/page",
                domain="secondary.com",
                auth_type="captcha",
                priority="medium",
            )

        # When
        summary = await queue_with_db.get_authentication_queue_summary(sample_task_id)

        # Then
        assert summary["pending_count"] == 5, (
            f"pending_count should be 5, got {summary['pending_count']}"
        )
        assert summary["high_priority_count"] == 2, (
            f"high_priority_count should be 2, got {summary['high_priority_count']}"
        )

    @pytest.mark.asyncio
    async def test_summary_lists_distinct_domains(self, queue_with_db, sample_task_id):
        """Test summary returns distinct domains."""
        # Given: Add items for same domain
        for i in range(3):
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url=f"https://example.com/page{i}",
                domain="example.com",
                auth_type="cloudflare",
            )
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://other.com/page",
            domain="other.com",
            auth_type="captcha",
        )

        # When
        summary = await queue_with_db.get_authentication_queue_summary(sample_task_id)

        # Then
        assert len(summary["domains"]) == 2, (
            f"Should have 2 distinct domains, got {len(summary['domains'])}"
        )
        assert "example.com" in summary["domains"], "example.com should be in domains"
        assert "other.com" in summary["domains"], "other.com should be in domains"

    @pytest.mark.asyncio
    async def test_summary_tracks_oldest_queued_at(self, queue_with_db, sample_task_id):
        """Test summary returns oldest queued_at timestamp."""
        # Given: Add items
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/first",
            domain="example.com",
            auth_type="cloudflare",
        )

        # When
        summary = await queue_with_db.get_authentication_queue_summary(sample_task_id)

        # Then
        assert summary["oldest_queued_at"] is not None, "oldest_queued_at should not be None"

    @pytest.mark.asyncio
    async def test_summary_counts_by_auth_type(self, queue_with_db, sample_task_id):
        """Test summary returns counts by auth_type."""
        # Given: Add items with different auth types
        for _ in range(2):
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url="https://cf.example.com/page",
                domain="cf.example.com",
                auth_type="cloudflare",
            )
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://captcha.example.com/page",
            domain="captcha.example.com",
            auth_type="captcha",
        )
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://turnstile.example.com/page",
            domain="turnstile.example.com",
            auth_type="turnstile",
        )

        # When
        summary = await queue_with_db.get_authentication_queue_summary(sample_task_id)

        # Then
        assert summary["by_auth_type"]["cloudflare"] == 2, (
            f"cloudflare count should be 2, got {summary['by_auth_type'].get('cloudflare')}"
        )
        assert summary["by_auth_type"]["captcha"] == 1, (
            f"captcha count should be 1, got {summary['by_auth_type'].get('captcha')}"
        )
        assert summary["by_auth_type"]["turnstile"] == 1, (
            f"turnstile count should be 1, got {summary['by_auth_type'].get('turnstile')}"
        )


# =============================================================================
# Get Item Tests (O.6 Auth Compliance)
# =============================================================================


@pytest.mark.unit
class TestGetItem:
    """Tests for get_item functionality added for O.6 auth compliance.

    Per §3.6.1: Get specific queue item by ID for cookie capture.
    """

    @pytest.mark.asyncio
    async def test_get_item_returns_item(self, queue_with_db, sample_task_id):
        """TC-GI-N-01: Get item returns correct item data."""
        # Given
        url = "https://example.com/protected"
        domain = "example.com"
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url=url,
            domain=domain,
            auth_type="cloudflare",
            priority="high",
        )

        # When
        item = await queue_with_db.get_item(queue_id)

        # Then
        assert item is not None, "get_item should return item"
        assert item["id"] == queue_id, f"Item ID should be '{queue_id}', got '{item['id']}'"
        assert item["url"] == url, f"URL should be '{url}', got '{item['url']}'"
        assert item["domain"] == domain, f"Domain should be '{domain}', got '{item['domain']}'"
        assert item["auth_type"] == "cloudflare", "auth_type should be 'cloudflare'"
        assert item["priority"] == "high", "priority should be 'high'"

    @pytest.mark.asyncio
    async def test_get_item_nonexistent_returns_none(self, queue_with_db):
        """TC-GI-B-01: Get item with nonexistent ID returns None."""
        # When
        item = await queue_with_db.get_item("nonexistent_id")

        # Then
        assert item is None, "get_item should return None for nonexistent ID"

    @pytest.mark.asyncio
    async def test_get_item_includes_session_data(self, queue_with_db, sample_task_id):
        """Test get_item returns session_data if set."""
        # Given: Create and complete an item with session data
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        session_data = {"cookies": [{"name": "test", "value": "abc"}]}
        await queue_with_db.complete(queue_id, success=True, session_data=session_data)

        # When
        item = await queue_with_db.get_item(queue_id)

        # Then
        assert item is not None, "get_item should return completed item"
        assert "session_data" in item, "Item should have session_data field"


# =============================================================================
# Global Queue Instance Tests
# =============================================================================


@pytest.mark.unit
class TestGetInterventionQueue:
    """Tests for get_intervention_queue global instance."""

    def test_returns_intervention_queue_instance(self):
        """Test get_intervention_queue returns InterventionQueue instance."""
        # Reset global state
        import src.utils.notification as notif_module

        notif_module._queue = None

        # When
        queue = get_intervention_queue()

        # Then
        assert isinstance(queue, InterventionQueue), (
            f"Should return InterventionQueue, got {type(queue)}"
        )

    def test_returns_same_instance_on_multiple_calls(self):
        """Test get_intervention_queue returns same instance (singleton)."""
        # Reset global state
        import src.utils.notification as notif_module

        notif_module._queue = None

        # When
        queue1 = get_intervention_queue()
        queue2 = get_intervention_queue()

        # Then
        assert queue1 is queue2, "Should return same instance on multiple calls"
