"""
Tests for src/storage/database.py

All tests in this module use a temporary database and are classified
as integration tests per .1.7.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from src.storage.database import Database

pytestmark = pytest.mark.integration


# All tests in this module are integration tests (use database)
pytestmark = pytest.mark.integration


class TestDatabase:
    """Tests for Database class."""

    @pytest.mark.asyncio
    async def test_connect_creates_database_file(self, temp_db_path: Path) -> None:
        """Test that connect creates the database file."""
        from src.storage.database import Database

        db = Database(temp_db_path)
        await db.connect()

        assert temp_db_path.exists()

        await db.close()

    @pytest.mark.asyncio
    async def test_initialize_schema_creates_tables(self, test_database: Database) -> None:
        """Test that initialize_schema creates all required tables."""
        tables = await test_database.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {t["name"] for t in tables}

        expected_tables = {
            "tasks",
            "queries",
            "serp_items",
            "pages",
            "fragments",
            "claims",
            "edges",
            "domains",
            "engine_health",
            "jobs",
            "cache_serp",
            "cache_fetch",
            "embeddings",
            "event_log",
            "intervention_log",
        }

        for table in expected_tables:
            assert table in table_names, f"Table '{table}' not found"

    @pytest.mark.asyncio
    async def test_insert_and_fetch_one(self, test_database: Database) -> None:
        """Test insert and fetch_one operations."""
        task_id = await test_database.insert(
            "tasks",
            {
                "query": "test query",
                "status": "pending",
            },
        )

        assert task_id is not None

        result = await test_database.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))

        assert result is not None
        assert result["query"] == "test query"
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_insert_without_auto_id(self, test_database: Database) -> None:
        """Test insert with auto_id=False."""
        await test_database.insert(
            "domains",
            {"domain": "example.com"},
            auto_id=False,
        )

        result = await test_database.fetch_one(
            "SELECT * FROM domains WHERE domain = ?", ("example.com",)
        )

        assert result is not None
        assert result["domain"] == "example.com"

    @pytest.mark.asyncio
    async def test_insert_or_replace(self, test_database: Database) -> None:
        """Test INSERT OR REPLACE behavior."""
        await test_database.insert(
            "domains",
            {"domain": "test.com", "qps_limit": 0.2},
            auto_id=False,
        )

        await test_database.insert(
            "domains",
            {"domain": "test.com", "qps_limit": 0.5},
            auto_id=False,
            or_replace=True,
        )

        result = await test_database.fetch_one(
            "SELECT * FROM domains WHERE domain = ?", ("test.com",)
        )
        assert result is not None

        assert result["qps_limit"] == 0.5

    @pytest.mark.asyncio
    async def test_fetch_all(self, test_database: Database) -> None:
        """Test fetch_all returns multiple rows."""
        for i in range(3):
            await test_database.insert(
                "tasks",
                {
                    "query": f"query {i}",
                    "status": "pending",
                },
            )

        results = await test_database.fetch_all(
            "SELECT * FROM tasks WHERE status = ?", ("pending",)
        )

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_update(self, test_database: Database) -> None:
        """Test update operation."""
        task_id = await test_database.insert(
            "tasks",
            {
                "query": "original query",
                "status": "pending",
            },
        )

        rows_affected = await test_database.update(
            "tasks",
            {"status": "running"},
            "id = ?",
            (task_id,),
        )

        assert rows_affected == 1

        result = await test_database.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        assert result is not None
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_execute_many(self, test_database: Database) -> None:
        """Test execute_many for batch inserts."""
        await test_database.execute_many(
            "INSERT INTO domains (domain, qps_limit) VALUES (?, ?)",
            [
                ("domain1.com", 0.1),
                ("domain2.com", 0.2),
                ("domain3.com", 0.3),
            ],
        )

        results = await test_database.fetch_all("SELECT * FROM domains")
        assert len(results) == 3


class TestTaskOperations:
    """Tests for task-related database operations."""

    @pytest.mark.asyncio
    async def test_create_task(self, test_database: Database) -> None:
        """Test create_task creates a new task."""
        task_id = await test_database.create_task(
            query="What is AI?",
            config={"depth": 3},
        )

        assert task_id is not None

        result = await test_database.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        assert result is not None

        assert result["query"] == "What is AI?"
        assert result["status"] == "pending"
        assert json.loads(result["config_json"]) == {"depth": 3}

    @pytest.mark.asyncio
    async def test_update_task_status_to_running(self, test_database: Database) -> None:
        """Test updating task status to running sets started_at."""
        task_id = await test_database.create_task("test query")

        await test_database.update_task_status(task_id, "running")

        result = await test_database.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        assert result is not None

        assert result["status"] == "running"
        assert result["started_at"] is not None

    @pytest.mark.asyncio
    async def test_update_task_status_to_completed(self, test_database: Database) -> None:
        """Test updating task status to completed sets completed_at."""
        task_id = await test_database.create_task("test query")

        await test_database.update_task_status(task_id, "completed")

        result = await test_database.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        assert result is not None

        assert result["status"] == "completed"
        assert result["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_update_task_status_with_error(self, test_database: Database) -> None:
        """Test updating task status with error message."""
        task_id = await test_database.create_task("test query")

        await test_database.update_task_status(
            task_id, "failed", error_message="Connection timeout"
        )

        result = await test_database.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        assert result is not None

        assert result["status"] == "failed"
        assert result["error_message"] == "Connection timeout"


class TestEventLogging:
    """Tests for event logging."""

    @pytest.mark.asyncio
    async def test_log_event(self, test_database: Database) -> None:
        """Test logging an event."""
        task_id = await test_database.create_task("test query")

        await test_database.log_event(
            event_type="fetch",
            message="Started fetching URL",
            task_id=task_id,
            component="crawler",
            details={"url": "https://example.com"},
        )

        result = await test_database.fetch_one(
            "SELECT * FROM event_log WHERE task_id = ?", (task_id,)
        )

        assert result is not None
        assert result["event_type"] == "fetch"
        assert result["message"] == "Started fetching URL"
        assert result["component"] == "crawler"
        assert json.loads(result["details_json"])["url"] == "https://example.com"


class TestDomainMetrics:
    """Tests for domain metrics operations."""

    @pytest.mark.asyncio
    async def test_update_domain_metrics_creates_domain(self, test_database: Database) -> None:
        """Test that update_domain_metrics creates domain if not exists."""
        await test_database.update_domain_metrics(
            domain="newdomain.com",
            success=True,
        )

        result = await test_database.fetch_one(
            "SELECT * FROM domains WHERE domain = ?", ("newdomain.com",)
        )
        assert result is not None

        assert result["total_requests"] == 1
        assert result["total_success"] == 1

    @pytest.mark.asyncio
    async def test_update_domain_metrics_success(self, test_database: Database) -> None:
        """Test domain metrics update on success."""
        await test_database.insert(
            "domains",
            {"domain": "test.com", "success_rate_1h": 0.5},
            auto_id=False,
        )

        await test_database.update_domain_metrics("test.com", success=True)

        result = await test_database.fetch_one(
            "SELECT * FROM domains WHERE domain = ?", ("test.com",)
        )
        assert result is not None

        # EMA should increase: 0.1 * 1.0 + 0.9 * 0.5 = 0.55
        assert result["success_rate_1h"] == pytest.approx(0.55, rel=0.01)

    @pytest.mark.asyncio
    async def test_update_domain_metrics_failure(self, test_database: Database) -> None:
        """Test domain metrics update on failure."""
        await test_database.insert(
            "domains",
            {"domain": "test.com", "success_rate_1h": 1.0},
            auto_id=False,
        )

        await test_database.update_domain_metrics("test.com", success=False)

        result = await test_database.fetch_one(
            "SELECT * FROM domains WHERE domain = ?", ("test.com",)
        )
        assert result is not None

        # EMA should decrease: 0.1 * 0.0 + 0.9 * 1.0 = 0.9
        assert result["success_rate_1h"] == pytest.approx(0.9, rel=0.01)
        assert result["total_failures"] == 1

    @pytest.mark.asyncio
    async def test_update_domain_metrics_captcha(self, test_database: Database) -> None:
        """Test domain metrics update with CAPTCHA."""
        await test_database.insert(
            "domains",
            {"domain": "test.com", "captcha_rate": 0.0},
            auto_id=False,
        )

        await test_database.update_domain_metrics("test.com", success=False, is_captcha=True)

        result = await test_database.fetch_one(
            "SELECT * FROM domains WHERE domain = ?", ("test.com",)
        )
        assert result is not None

        # Captcha rate should increase: 0.1 * 1.0 + 0.9 * 0.0 = 0.1
        assert result["captcha_rate"] == pytest.approx(0.1, rel=0.01)
        assert result["total_captchas"] == 1


class TestDomainCooldown:
    """Tests for domain cooldown operations."""

    @pytest.mark.asyncio
    async def test_set_domain_cooldown(self, test_database: Database) -> None:
        """Test setting domain cooldown."""
        await test_database.insert(
            "domains",
            {"domain": "test.com"},
            auto_id=False,
        )

        await test_database.set_domain_cooldown(
            "test.com",
            minutes=60,
            reason="Rate limited",
        )

        result = await test_database.fetch_one(
            "SELECT * FROM domains WHERE domain = ?", ("test.com",)
        )
        assert result is not None

        assert result["cooldown_until"] is not None
        assert result["skip_reason"] == "Rate limited"

    @pytest.mark.asyncio
    async def test_is_domain_cooled_down_active(self, test_database: Database) -> None:
        """Test is_domain_cooled_down returns True when in cooldown."""
        await test_database.insert(
            "domains",
            {"domain": "test.com"},
            auto_id=False,
        )
        await test_database.set_domain_cooldown("test.com", minutes=60)

        is_cooled = await test_database.is_domain_cooled_down("test.com")

        assert is_cooled is True

    @pytest.mark.asyncio
    async def test_is_domain_cooled_down_expired(self, test_database: Database) -> None:
        """Test is_domain_cooled_down returns False when cooldown expired."""
        past_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

        await test_database.insert(
            "domains",
            {"domain": "test.com", "cooldown_until": past_time},
            auto_id=False,
        )

        is_cooled = await test_database.is_domain_cooled_down("test.com")

        assert is_cooled is False

    @pytest.mark.asyncio
    async def test_is_domain_cooled_down_no_cooldown(self, test_database: Database) -> None:
        """Test is_domain_cooled_down returns False when no cooldown set."""
        await test_database.insert(
            "domains",
            {"domain": "test.com"},
            auto_id=False,
        )

        is_cooled = await test_database.is_domain_cooled_down("test.com")

        assert is_cooled is False

    @pytest.mark.asyncio
    async def test_is_domain_cooled_down_unknown_domain(self, test_database: Database) -> None:
        """Test is_domain_cooled_down returns False for unknown domain."""
        is_cooled = await test_database.is_domain_cooled_down("unknown.com")

        assert is_cooled is False


class TestEngineHealth:
    """Tests for engine health operations."""

    @pytest.mark.asyncio
    async def test_update_engine_health_creates_engine(self, test_database: Database) -> None:
        """Test that update_engine_health creates engine if not exists."""
        await test_database.update_engine_health(
            engine="google",
            success=True,
            latency_ms=500.0,
        )

        result = await test_database.fetch_one(
            "SELECT * FROM engine_health WHERE engine = ?", ("google",)
        )
        assert result is not None

        assert result["total_queries"] == 1
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_update_engine_health_circuit_breaker_opens(
        self, test_database: Database
    ) -> None:
        """Test circuit breaker opens after consecutive failures."""
        await test_database.insert(
            "engine_health",
            {"engine": "test_engine", "consecutive_failures": 1, "status": "closed"},
            auto_id=False,
        )

        # Second failure should open the circuit
        await test_database.update_engine_health("test_engine", success=False)

        result = await test_database.fetch_one(
            "SELECT * FROM engine_health WHERE engine = ?", ("test_engine",)
        )
        assert result is not None

        assert result["status"] == "open"
        assert result["consecutive_failures"] == 2
        assert result["cooldown_until"] is not None

    @pytest.mark.asyncio
    async def test_update_engine_health_success_resets_failures(
        self, test_database: Database
    ) -> None:
        """Test success resets consecutive failures."""
        await test_database.insert(
            "engine_health",
            {"engine": "test_engine", "consecutive_failures": 1, "status": "half-open"},
            auto_id=False,
        )

        await test_database.update_engine_health("test_engine", success=True)

        result = await test_database.fetch_one(
            "SELECT * FROM engine_health WHERE engine = ?", ("test_engine",)
        )
        assert result is not None

        assert result["status"] == "closed"
        assert result["consecutive_failures"] == 0

    @pytest.mark.asyncio
    async def test_get_active_engines(self, test_database: Database) -> None:
        """Test get_active_engines returns only non-open engines."""
        # Add various engines
        await test_database.insert(
            "engine_health",
            {"engine": "active1", "status": "closed", "weight": 1.0},
            auto_id=False,
        )
        await test_database.insert(
            "engine_health",
            {"engine": "active2", "status": "half-open", "weight": 0.8},
            auto_id=False,
        )
        await test_database.insert(
            "engine_health",
            {"engine": "inactive", "status": "open", "weight": 0.5},
            auto_id=False,
        )

        active = await test_database.get_active_engines()

        engine_names = {e["engine"] for e in active}
        assert "active1" in engine_names
        assert "active2" in engine_names
        assert "inactive" not in engine_names
