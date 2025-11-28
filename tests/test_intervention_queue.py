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
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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
        # Act
        queue = InterventionQueue()
        
        # Assert
        assert queue._db is None, (
            "_db should be None before _ensure_db is called"
        )
    
    @pytest.mark.asyncio
    async def test_ensure_db_creates_connection(self, test_database):
        """Test _ensure_db establishes database connection."""
        # Arrange
        queue = InterventionQueue()
        
        with patch(
            "src.utils.notification.get_database",
            new_callable=AsyncMock,
            return_value=test_database,
        ):
            # Act
            await queue._ensure_db()
            
            # Assert
            assert queue._db is not None, (
                "_db should not be None after _ensure_db"
            )
            assert queue._db == test_database, (
                "_db should be the database returned by get_database"
            )


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
        # Act
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/protected",
            domain="example.com",
            auth_type="cloudflare",
        )
        
        # Assert
        assert isinstance(queue_id, str), (
            f"queue_id should be string, got {type(queue_id)}"
        )
        assert queue_id.startswith("iq_"), (
            f"queue_id should start with 'iq_', got '{queue_id}'"
        )
        assert len(queue_id) == 15, (  # "iq_" + 12 hex chars
            f"queue_id should have length 15, got {len(queue_id)}"
        )
    
    @pytest.mark.asyncio
    async def test_enqueue_stores_all_fields(self, queue_with_db, sample_task_id):
        """Test enqueue stores all required fields in database."""
        # Arrange
        url = "https://secure.example.com/page"
        domain = "secure.example.com"
        auth_type = "captcha"
        priority = "high"
        
        # Act
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url=url,
            domain=domain,
            auth_type=auth_type,
            priority=priority,
        )
        
        # Assert: Verify by fetching
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(items) == 1, (
            f"Should have 1 item in queue, got {len(items)}"
        )
        
        item = items[0]
        assert item["id"] == queue_id, (
            f"Item ID should be '{queue_id}', got '{item['id']}'"
        )
        assert item["url"] == url, (
            f"URL should be '{url}', got '{item['url']}'"
        )
        assert item["domain"] == domain, (
            f"Domain should be '{domain}', got '{item['domain']}'"
        )
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
        # Act
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
            # No priority specified - should default to 'medium'
        )
        
        # Assert
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        assert items[0]["priority"] == "medium", (
            f"Default priority should be 'medium', got '{items[0]['priority']}'"
        )
    
    @pytest.mark.asyncio
    async def test_enqueue_sets_default_expiration_one_hour(
        self, queue_with_db, sample_task_id
    ):
        """Test enqueue sets default expiration to 1 hour from now.
        
        Per design: Default expiration: 1 hour from now
        """
        # Arrange
        before = datetime.now(timezone.utc)
        
        # Act
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        
        after = datetime.now(timezone.utc)
        
        # Assert
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        expires_str = items[0]["expires_at"]
        assert expires_str is not None, (
            "expires_at should be set"
        )
        
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
        # Arrange
        custom_expires = datetime.now(timezone.utc) + timedelta(hours=2)
        
        # Act
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
            expires_at=custom_expires,
        )
        
        # Assert
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        expires_str = items[0]["expires_at"]
        expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        
        # Allow 1 second tolerance for test execution
        delta = abs((expires - custom_expires).total_seconds())
        assert delta < 2, (
            f"expires_at should match custom value, delta was {delta}s"
        )


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
        # Act
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        
        # Assert
        assert items == [], (
            f"Empty queue should return [], got {items}"
        )
    
    @pytest.mark.asyncio
    async def test_get_pending_returns_correct_items(self, queue_with_db, sample_task_id):
        """Test get_pending returns enqueued items."""
        # Arrange: Add 3 items
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
        
        # Act
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        
        # Assert
        assert len(items) == 3, (
            f"Should return 3 items, got {len(items)}"
        )
        returned_urls = [item["url"] for item in items]
        for url in urls:
            assert url in returned_urls, (
                f"URL '{url}' should be in returned items"
            )
    
    @pytest.mark.asyncio
    async def test_get_pending_orders_by_priority(self, queue_with_db, sample_task_id):
        """Test get_pending returns items ordered by priority (high first).
        
        Per §3.6.1: Priority management - high > medium > low.
        """
        # Arrange: Add items in reverse priority order
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
        
        # Act
        items = await queue_with_db.get_pending(task_id=sample_task_id)
        
        # Assert: Should be ordered high, medium, low
        priorities = [item["priority"] for item in items]
        assert priorities == ["high", "medium", "low"], (
            f"Items should be ordered by priority, got {priorities}"
        )
    
    @pytest.mark.asyncio
    async def test_get_pending_filters_by_task_id(self, queue_with_db, test_database):
        """Test get_pending filters by task_id correctly."""
        # Arrange: Create two tasks and add items to each
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
        
        # Act
        items_task1 = await queue_with_db.get_pending(task_id=task1)
        items_task2 = await queue_with_db.get_pending(task_id=task2)
        
        # Assert
        assert len(items_task1) == 1, (
            f"Task 1 should have 1 item, got {len(items_task1)}"
        )
        assert items_task1[0]["domain"] == "task1.com", (
            f"Task 1 item domain should be 'task1.com', got '{items_task1[0]['domain']}'"
        )
        
        assert len(items_task2) == 1, (
            f"Task 2 should have 1 item, got {len(items_task2)}"
        )
        assert items_task2[0]["domain"] == "task2.com", (
            f"Task 2 item domain should be 'task2.com', got '{items_task2[0]['domain']}'"
        )
    
    @pytest.mark.asyncio
    async def test_get_pending_filters_by_priority(self, queue_with_db, sample_task_id):
        """Test get_pending filters by priority correctly."""
        # Arrange: Add items with different priorities
        for priority in ["high", "medium", "low"]:
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url=f"https://example.com/{priority}",
                domain="example.com",
                auth_type="cloudflare",
                priority=priority,
            )
        
        # Act
        high_items = await queue_with_db.get_pending(
            task_id=sample_task_id,
            priority="high",
        )
        
        # Assert
        assert len(high_items) == 1, (
            f"Should have 1 high priority item, got {len(high_items)}"
        )
        assert high_items[0]["priority"] == "high", (
            f"Item priority should be 'high', got '{high_items[0]['priority']}'"
        )
    
    @pytest.mark.asyncio
    async def test_get_pending_respects_limit(self, queue_with_db, sample_task_id):
        """Test get_pending respects limit parameter."""
        # Arrange: Add 10 items
        for i in range(10):
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url=f"https://example.com/page{i}",
                domain="example.com",
                auth_type="cloudflare",
            )
        
        # Act
        items = await queue_with_db.get_pending(task_id=sample_task_id, limit=3)
        
        # Assert
        assert len(items) == 3, (
            f"Should return 3 items with limit=3, got {len(items)}"
        )


# =============================================================================
# Get Pending Count Tests
# =============================================================================

@pytest.mark.unit
class TestGetPendingCount:
    """Tests for get_pending_count functionality."""
    
    @pytest.mark.asyncio
    async def test_get_pending_count_empty_queue(self, queue_with_db, sample_task_id):
        """Test get_pending_count returns zeros for empty queue."""
        # Act
        counts = await queue_with_db.get_pending_count(sample_task_id)
        
        # Assert
        assert counts["high"] == 0, (
            f"high count should be 0, got {counts['high']}"
        )
        assert counts["medium"] == 0, (
            f"medium count should be 0, got {counts['medium']}"
        )
        assert counts["low"] == 0, (
            f"low count should be 0, got {counts['low']}"
        )
        assert counts["total"] == 0, (
            f"total count should be 0, got {counts['total']}"
        )
    
    @pytest.mark.asyncio
    async def test_get_pending_count_by_priority(self, queue_with_db, sample_task_id):
        """Test get_pending_count returns correct counts by priority."""
        # Arrange: Add specific number of each priority
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
        
        # Act
        counts = await queue_with_db.get_pending_count(sample_task_id)
        
        # Assert
        assert counts["high"] == 2, (
            f"high count should be 2, got {counts['high']}"
        )
        assert counts["medium"] == 3, (
            f"medium count should be 3, got {counts['medium']}"
        )
        assert counts["low"] == 1, (
            f"low count should be 1, got {counts['low']}"
        )
        assert counts["total"] == 6, (
            f"total count should be 6, got {counts['total']}"
        )


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
        # Act
        result = await queue_with_db.start_session(task_id=sample_task_id)
        
        # Assert
        assert result["ok"] is True, (
            "ok should be True even with empty queue"
        )
        assert result["session_started"] is False, (
            "session_started should be False with no pending items"
        )
        assert result["count"] == 0, (
            f"count should be 0, got {result['count']}"
        )
        assert result["items"] == [], (
            f"items should be empty list, got {result['items']}"
        )
    
    @pytest.mark.asyncio
    async def test_start_session_marks_items_in_progress(
        self, queue_with_db, sample_task_id
    ):
        """Test start_session changes item status to 'in_progress'."""
        # Arrange
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        
        # Act
        result = await queue_with_db.start_session(task_id=sample_task_id)
        
        # Assert
        assert result["session_started"] is True, (
            "session_started should be True"
        )
        assert result["count"] == 1, (
            f"count should be 1, got {result['count']}"
        )
        
        # Verify status changed - pending items should be 0 now
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 0, (
            f"No items should be pending after start_session, got {len(pending)}"
        )
    
    @pytest.mark.asyncio
    async def test_start_session_returns_item_details(
        self, queue_with_db, sample_task_id
    ):
        """Test start_session returns correct item details."""
        # Arrange
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
        
        # Act
        result = await queue_with_db.start_session(task_id=sample_task_id)
        
        # Assert
        items = result["items"]
        assert len(items) == 1, (
            f"Should return 1 item, got {len(items)}"
        )
        
        item = items[0]
        assert item["url"] == url, (
            f"Item URL should be '{url}', got '{item['url']}'"
        )
        assert item["domain"] == domain, (
            f"Item domain should be '{domain}', got '{item['domain']}'"
        )
        assert item["auth_type"] == auth_type, (
            f"Item auth_type should be '{auth_type}', got '{item['auth_type']}'"
        )
        assert item["priority"] == priority, (
            f"Item priority should be '{priority}', got '{item['priority']}'"
        )
    
    @pytest.mark.asyncio
    async def test_start_session_with_specific_queue_ids(
        self, queue_with_db, sample_task_id
    ):
        """Test start_session with specific queue_ids."""
        # Arrange: Add multiple items
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
        
        # Act: Start session with only 2 specific IDs
        result = await queue_with_db.start_session(
            task_id=sample_task_id,
            queue_ids=[id1, id3],
        )
        
        # Assert
        assert result["count"] == 2, (
            f"Should process 2 items, got {result['count']}"
        )
        
        # id2 should still be pending
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 1, (
            f"Should have 1 pending item, got {len(pending)}"
        )
        assert pending[0]["id"] == id2, (
            f"Pending item should be id2, got '{pending[0]['id']}'"
        )
    
    @pytest.mark.asyncio
    async def test_start_session_filters_by_priority(
        self, queue_with_db, sample_task_id
    ):
        """Test start_session filters by priority when specified."""
        # Arrange
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
        
        # Act: Start session for high priority only
        result = await queue_with_db.start_session(
            task_id=sample_task_id,
            priority_filter="high",
        )
        
        # Assert
        assert result["count"] == 1, (
            f"Should process 1 high priority item, got {result['count']}"
        )
        assert result["items"][0]["priority"] == "high", (
            f"Processed item should be high priority"
        )
        
        # Low priority should still be pending
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 1, (
            f"Should have 1 pending item, got {len(pending)}"
        )
        assert pending[0]["priority"] == "low", (
            f"Pending item should be low priority"
        )


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
    async def test_complete_success_updates_status(
        self, queue_with_db, sample_task_id
    ):
        """Test complete with success=True sets status to 'completed'."""
        # Arrange
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)
        
        # Act
        result = await queue_with_db.complete(queue_id=queue_id, success=True)
        
        # Assert
        assert result["ok"] is True, (
            "ok should be True"
        )
        assert result["queue_id"] == queue_id, (
            f"queue_id should be '{queue_id}', got '{result['queue_id']}'"
        )
        assert result["status"] == "completed", (
            f"status should be 'completed', got '{result['status']}'"
        )
    
    @pytest.mark.asyncio
    async def test_complete_failure_updates_status(
        self, queue_with_db, sample_task_id
    ):
        """Test complete with success=False sets status to 'skipped'."""
        # Arrange
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)
        
        # Act
        result = await queue_with_db.complete(queue_id=queue_id, success=False)
        
        # Assert
        assert result["status"] == "skipped", (
            f"status should be 'skipped' on failure, got '{result['status']}'"
        )
    
    @pytest.mark.asyncio
    async def test_complete_stores_session_data(
        self, queue_with_db, sample_task_id
    ):
        """Test complete stores session data when provided.
        
        Per §3.6.1: Session reuse - store authenticated session data.
        """
        # Arrange
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)
        
        session_data = {
            "cookies": [{"name": "cf_clearance", "value": "abc123"}],
            "authenticated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # Act
        await queue_with_db.complete(
            queue_id=queue_id,
            success=True,
            session_data=session_data,
        )
        
        # Assert: Retrieve session data
        stored_session = await queue_with_db.get_session_for_domain(
            domain="example.com",
        )
        assert stored_session is not None, (
            "Session data should be stored"
        )
        assert stored_session["cookies"][0]["name"] == "cf_clearance", (
            f"Session cookie name should be 'cf_clearance'"
        )
    
    @pytest.mark.asyncio
    async def test_complete_returns_url_and_domain(
        self, queue_with_db, sample_task_id
    ):
        """Test complete returns the URL and domain of completed item."""
        # Arrange
        url = "https://secure.example.com/protected"
        domain = "secure.example.com"
        queue_id = await queue_with_db.enqueue(
            task_id=sample_task_id,
            url=url,
            domain=domain,
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)
        
        # Act
        result = await queue_with_db.complete(queue_id=queue_id, success=True)
        
        # Assert
        assert result["url"] == url, (
            f"URL should be '{url}', got '{result['url']}'"
        )
        assert result["domain"] == domain, (
            f"Domain should be '{domain}', got '{result['domain']}'"
        )


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
        # Arrange
        for i in range(3):
            await queue_with_db.enqueue(
                task_id=sample_task_id,
                url=f"https://example.com/page{i}",
                domain="example.com",
                auth_type="cloudflare",
            )
        
        # Act
        result = await queue_with_db.skip(task_id=sample_task_id)
        
        # Assert
        assert result["ok"] is True, (
            "ok should be True"
        )
        assert result["skipped"] >= 3, (
            f"Should skip at least 3 items, got {result['skipped']}"
        )
        
        # Verify no pending items remain
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 0, (
            f"Should have no pending items, got {len(pending)}"
        )
    
    @pytest.mark.asyncio
    async def test_skip_specific_queue_ids(self, queue_with_db, sample_task_id):
        """Test skip with specific queue_ids skips only those items."""
        # Arrange
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
        
        # Act: Skip only id1
        await queue_with_db.skip(task_id=sample_task_id, queue_ids=[id1])
        
        # Assert: id2 should still be pending
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 1, (
            f"Should have 1 pending item, got {len(pending)}"
        )
        assert pending[0]["id"] == id2, (
            f"Pending item should be id2"
        )
    
    @pytest.mark.asyncio
    async def test_skip_in_progress_items(self, queue_with_db, sample_task_id):
        """Test skip works on items that are in_progress."""
        # Arrange
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        await queue_with_db.start_session(task_id=sample_task_id)
        
        # Act
        result = await queue_with_db.skip(task_id=sample_task_id)
        
        # Assert: Should have skipped the in_progress item
        assert result["ok"] is True, (
            "ok should be True"
        )


# =============================================================================
# Get Session for Domain Tests (§3.6.1)
# =============================================================================

@pytest.mark.unit
class TestGetSessionForDomain:
    """Tests for get_session_for_domain functionality.
    
    Per §3.6.1: Session reuse - reuse for subsequent requests to same domain.
    """
    
    @pytest.mark.asyncio
    async def test_get_session_returns_none_when_no_session(
        self, queue_with_db
    ):
        """Test get_session_for_domain returns None when no session exists."""
        # Act
        session = await queue_with_db.get_session_for_domain(domain="unknown.com")
        
        # Assert
        assert session is None, (
            "Should return None when no session exists"
        )
    
    @pytest.mark.asyncio
    async def test_get_session_returns_stored_session(
        self, queue_with_db, sample_task_id
    ):
        """Test get_session_for_domain returns stored session data."""
        # Arrange: Complete an authentication with session data
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
        
        # Act
        retrieved = await queue_with_db.get_session_for_domain(domain=domain)
        
        # Assert
        assert retrieved is not None, (
            "Should return session data"
        )
        assert retrieved["cf_token"] == "secret_token_123", (
            f"cf_token should be 'secret_token_123', got '{retrieved['cf_token']}'"
        )
    
    @pytest.mark.asyncio
    async def test_get_session_returns_most_recent(
        self, queue_with_db, sample_task_id
    ):
        """Test get_session_for_domain returns the most recent session."""
        # Arrange: Complete two authentications for same domain
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
        
        # Act
        session = await queue_with_db.get_session_for_domain(domain=domain)
        
        # Assert
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
    async def test_cleanup_expired_marks_expired_items(
        self, queue_with_db, sample_task_id
    ):
        """Test cleanup_expired marks expired items correctly."""
        # Arrange: Add item with past expiration
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/expired",
            domain="example.com",
            auth_type="cloudflare",
            expires_at=past_time,
        )
        
        # Act
        cleaned = await queue_with_db.cleanup_expired()
        
        # Assert
        assert cleaned >= 1, (
            f"Should have cleaned at least 1 expired item, got {cleaned}"
        )
        
        # Verify item is no longer pending
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 0, (
            f"Should have no pending items after cleanup, got {len(pending)}"
        )
    
    @pytest.mark.asyncio
    async def test_cleanup_does_not_affect_valid_items(
        self, queue_with_db, sample_task_id
    ):
        """Test cleanup_expired does not affect non-expired items."""
        # Arrange: Add item with future expiration
        future_time = datetime.now(timezone.utc) + timedelta(hours=2)
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/valid",
            domain="example.com",
            auth_type="cloudflare",
            expires_at=future_time,
        )
        
        # Act
        await queue_with_db.cleanup_expired()
        
        # Assert: Item should still be pending
        pending = await queue_with_db.get_pending(task_id=sample_task_id)
        assert len(pending) == 1, (
            f"Valid item should still be pending, got {len(pending)}"
        )


# =============================================================================
# Boundary Condition Tests (§7.1.2.4)
# =============================================================================

@pytest.mark.unit
class TestBoundaryConditions:
    """Tests for boundary conditions per §7.1.2.4."""
    
    @pytest.mark.asyncio
    async def test_get_pending_with_limit_zero(self, queue_with_db, sample_task_id):
        """Test get_pending with limit=0 returns empty list."""
        # Arrange
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/page",
            domain="example.com",
            auth_type="cloudflare",
        )
        
        # Act
        items = await queue_with_db.get_pending(task_id=sample_task_id, limit=0)
        
        # Assert
        assert items == [], (
            f"limit=0 should return empty list, got {len(items)} items"
        )
    
    @pytest.mark.asyncio
    async def test_start_session_with_nonexistent_queue_ids(
        self, queue_with_db, sample_task_id
    ):
        """Test start_session with non-existent queue_ids."""
        # Act
        result = await queue_with_db.start_session(
            task_id=sample_task_id,
            queue_ids=["nonexistent_id_1", "nonexistent_id_2"],
        )
        
        # Assert
        assert result["session_started"] is False, (
            "session_started should be False for non-existent IDs"
        )
        assert result["count"] == 0, (
            f"count should be 0 for non-existent IDs, got {result['count']}"
        )
    
    @pytest.mark.asyncio
    async def test_complete_nonexistent_queue_id(self, queue_with_db):
        """Test complete with non-existent queue_id."""
        # Act
        result = await queue_with_db.complete(
            queue_id="nonexistent_id",
            success=True,
        )
        
        # Assert: Should return ok but with None values
        assert result["ok"] is True, (
            "ok should be True even for non-existent ID"
        )
        assert result["url"] is None, (
            "url should be None for non-existent ID"
        )
        assert result["domain"] is None, (
            "domain should be None for non-existent ID"
        )


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
        # Act
        summary = await queue_with_db.get_authentication_queue_summary(sample_task_id)
        
        # Assert
        assert summary["pending_count"] == 0, (
            f"pending_count should be 0, got {summary['pending_count']}"
        )
        assert summary["high_priority_count"] == 0, (
            f"high_priority_count should be 0, got {summary['high_priority_count']}"
        )
        assert summary["domains"] == [], (
            f"domains should be empty, got {summary['domains']}"
        )
        assert summary["oldest_queued_at"] is None, (
            "oldest_queued_at should be None"
        )
        assert summary["by_auth_type"] == {}, (
            f"by_auth_type should be empty, got {summary['by_auth_type']}"
        )
    
    @pytest.mark.asyncio
    async def test_summary_counts_correctly(self, queue_with_db, sample_task_id):
        """Test summary returns correct counts."""
        # Arrange: Add items with different priorities
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
        
        # Act
        summary = await queue_with_db.get_authentication_queue_summary(sample_task_id)
        
        # Assert
        assert summary["pending_count"] == 5, (
            f"pending_count should be 5, got {summary['pending_count']}"
        )
        assert summary["high_priority_count"] == 2, (
            f"high_priority_count should be 2, got {summary['high_priority_count']}"
        )
    
    @pytest.mark.asyncio
    async def test_summary_lists_distinct_domains(self, queue_with_db, sample_task_id):
        """Test summary returns distinct domains."""
        # Arrange: Add items for same domain
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
        
        # Act
        summary = await queue_with_db.get_authentication_queue_summary(sample_task_id)
        
        # Assert
        assert len(summary["domains"]) == 2, (
            f"Should have 2 distinct domains, got {len(summary['domains'])}"
        )
        assert "example.com" in summary["domains"], (
            "example.com should be in domains"
        )
        assert "other.com" in summary["domains"], (
            "other.com should be in domains"
        )
    
    @pytest.mark.asyncio
    async def test_summary_tracks_oldest_queued_at(self, queue_with_db, sample_task_id):
        """Test summary returns oldest queued_at timestamp."""
        # Arrange: Add items
        await queue_with_db.enqueue(
            task_id=sample_task_id,
            url="https://example.com/first",
            domain="example.com",
            auth_type="cloudflare",
        )
        
        # Act
        summary = await queue_with_db.get_authentication_queue_summary(sample_task_id)
        
        # Assert
        assert summary["oldest_queued_at"] is not None, (
            "oldest_queued_at should not be None"
        )
    
    @pytest.mark.asyncio
    async def test_summary_counts_by_auth_type(self, queue_with_db, sample_task_id):
        """Test summary returns counts by auth_type."""
        # Arrange: Add items with different auth types
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
        
        # Act
        summary = await queue_with_db.get_authentication_queue_summary(sample_task_id)
        
        # Assert
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
        
        # Act
        queue = get_intervention_queue()
        
        # Assert
        assert isinstance(queue, InterventionQueue), (
            f"Should return InterventionQueue, got {type(queue)}"
        )
    
    def test_returns_same_instance_on_multiple_calls(self):
        """Test get_intervention_queue returns same instance (singleton)."""
        # Reset global state
        import src.utils.notification as notif_module
        notif_module._queue = None
        
        # Act
        queue1 = get_intervention_queue()
        queue2 = get_intervention_queue()
        
        # Assert
        assert queue1 is queue2, (
            "Should return same instance on multiple calls"
        )

