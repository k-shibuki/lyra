"""
Database management for Lancet.
Handles SQLite connection, migrations, and common operations.
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class Database:
    """Async SQLite database manager."""

    def __init__(self, db_path: str | Path | None = None):
        """Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file. If None, uses settings.
        """
        if db_path is None:
            settings = get_settings()
            db_path = settings.storage.database_path
        
        self.db_path = Path(db_path)
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
    
    async def connect(self) -> None:
        """Connect to the database and initialize schema."""
        if self._connection is not None:
            return
        
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._connection = await aiosqlite.connect(
            self.db_path,
            isolation_level=None,  # Auto-commit mode
        )
        
        # Enable foreign keys and WAL mode for performance
        await self._connection.execute("PRAGMA foreign_keys = ON")
        await self._connection.execute("PRAGMA journal_mode = WAL")
        await self._connection.execute("PRAGMA synchronous = NORMAL")
        
        # Row factory for dict-like access
        self._connection.row_factory = aiosqlite.Row
        
        logger.info("Database connected", path=str(self.db_path))
    
    async def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")
    
    async def initialize_schema(self) -> None:
        """Initialize database schema from SQL file."""
        schema_path = Path(__file__).parent / "schema.sql"
        
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        
        schema_sql = schema_path.read_text(encoding="utf-8")
        
        async with self._lock:
            await self._connection.executescript(schema_sql)
        
        logger.info("Database schema initialized")
    
    async def execute(
        self,
        sql: str,
        parameters: tuple | dict | None = None,
    ) -> aiosqlite.Cursor:
        """Execute a SQL statement.
        
        Args:
            sql: SQL statement to execute.
            parameters: Optional parameters for the statement.
            
        Returns:
            Cursor with results.
        """
        async with self._lock:
            if parameters:
                cursor = await self._connection.execute(sql, parameters)
            else:
                cursor = await self._connection.execute(sql)
            return cursor
    
    async def execute_many(
        self,
        sql: str,
        parameters: list[tuple | dict],
    ) -> None:
        """Execute a SQL statement with multiple parameter sets.
        
        Args:
            sql: SQL statement to execute.
            parameters: List of parameter sets.
        """
        async with self._lock:
            await self._connection.executemany(sql, parameters)
    
    async def fetch_one(
        self,
        sql: str,
        parameters: tuple | dict | None = None,
    ) -> dict[str, Any] | None:
        """Fetch a single row.
        
        Args:
            sql: SQL query.
            parameters: Optional parameters.
            
        Returns:
            Row as dict or None.
        """
        cursor = await self.execute(sql, parameters)
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def fetch_all(
        self,
        sql: str,
        parameters: tuple | dict | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all rows.
        
        Args:
            sql: SQL query.
            parameters: Optional parameters.
            
        Returns:
            List of rows as dicts.
        """
        cursor = await self.execute(sql, parameters)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def insert(
        self,
        table: str,
        data: dict[str, Any],
        *,
        or_replace: bool = False,
        auto_id: bool = True,
    ) -> str | None:
        """Insert a row into a table.
        
        Args:
            table: Table name.
            data: Column-value mapping.
            or_replace: Use INSERT OR REPLACE.
            auto_id: Auto-generate UUID for 'id' column if missing.
            
        Returns:
            The ID of the inserted row, or None if no id column.
        """
        # Generate ID if not provided and auto_id is True
        if auto_id and "id" not in data:
            data = data.copy()
            data["id"] = str(uuid.uuid4())
        
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?" for _ in data])
        
        verb = "INSERT OR REPLACE" if or_replace else "INSERT"
        sql = f"{verb} INTO {table} ({columns}) VALUES ({placeholders})"
        
        await self.execute(sql, tuple(data.values()))
        return data.get("id")
    
    async def update(
        self,
        table: str,
        data: dict[str, Any],
        where: str,
        where_params: tuple | dict | None = None,
    ) -> int:
        """Update rows in a table.
        
        Args:
            table: Table name.
            data: Column-value mapping to update.
            where: WHERE clause.
            where_params: Parameters for WHERE clause.
            
        Returns:
            Number of affected rows.
        """
        set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        
        params = list(data.values())
        if where_params:
            if isinstance(where_params, dict):
                params.extend(where_params.values())
            else:
                params.extend(where_params)
        
        cursor = await self.execute(sql, tuple(params))
        return cursor.rowcount
    
    # ============================================================
    # Domain-specific operations
    # ============================================================
    
    async def create_task(
        self,
        query: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Create a new research task.
        
        Args:
            query: Research query.
            config: Optional task configuration.
            
        Returns:
            Task ID.
        """
        task_id = str(uuid.uuid4())
        await self.insert("tasks", {
            "id": task_id,
            "query": query,
            "status": "pending",
            "config_json": json.dumps(config) if config else None,
        })
        logger.info("Task created", task_id=task_id, query=query[:50])
        return task_id
    
    async def update_task_status(
        self,
        task_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update task status.
        
        Args:
            task_id: Task ID.
            status: New status.
            error_message: Optional error message.
        """
        data = {"status": status}
        
        if status == "running":
            data["started_at"] = datetime.now(timezone.utc).isoformat()
        elif status in ("completed", "failed", "cancelled"):
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
        
        if error_message:
            data["error_message"] = error_message
        
        await self.update("tasks", data, "id = ?", (task_id,))
        logger.info("Task status updated", task_id=task_id, status=status)
    
    async def log_event(
        self,
        event_type: str,
        message: str,
        *,
        level: str = "INFO",
        task_id: str | None = None,
        job_id: str | None = None,
        cause_id: str | None = None,
        component: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log an event to the database.
        
        Args:
            event_type: Type of event.
            message: Event message.
            level: Log level.
            task_id: Associated task ID.
            job_id: Associated job ID.
            cause_id: Causal trace ID.
            component: Component name.
            details: Additional details as dict.
        """
        await self.execute(
            """
            INSERT INTO event_log 
            (event_type, level, task_id, job_id, cause_id, component, message, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                level,
                task_id,
                job_id,
                cause_id,
                component,
                message,
                json.dumps(details) if details else None,
            ),
        )
    
    async def update_domain_metrics(
        self,
        domain: str,
        success: bool,
        *,
        is_captcha: bool = False,
        is_http_error: bool = False,
    ) -> None:
        """Update domain metrics after a request.
        
        Args:
            domain: Domain name.
            success: Whether the request succeeded.
            is_captcha: Whether a CAPTCHA was encountered.
            is_http_error: Whether an HTTP error occurred.
        """
        # Get or create domain record
        existing = await self.fetch_one(
            "SELECT * FROM domains WHERE domain = ?", (domain,)
        )
        
        if existing is None:
            await self.insert("domains", {"domain": domain}, auto_id=False)
            existing = {"success_rate_1h": 1.0, "captcha_rate": 0.0, "http_error_rate": 0.0}
        
        # Calculate EMA updates (alpha = 0.1 for 1h)
        alpha = 0.1
        success_rate = existing["success_rate_1h"]
        captcha_rate = existing["captcha_rate"]
        http_error_rate = existing["http_error_rate"]
        
        success_rate = alpha * (1.0 if success else 0.0) + (1 - alpha) * success_rate
        captcha_rate = alpha * (1.0 if is_captcha else 0.0) + (1 - alpha) * captcha_rate
        http_error_rate = alpha * (1.0 if is_http_error else 0.0) + (1 - alpha) * http_error_rate
        
        # Update
        update_data = {
            "success_rate_1h": success_rate,
            "captcha_rate": captcha_rate,
            "http_error_rate": http_error_rate,
            "total_requests": existing.get("total_requests", 0) + 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        if success:
            update_data["total_success"] = existing.get("total_success", 0) + 1
            update_data["last_success_at"] = datetime.now(timezone.utc).isoformat()
        else:
            update_data["total_failures"] = existing.get("total_failures", 0) + 1
            update_data["last_failure_at"] = datetime.now(timezone.utc).isoformat()
        
        if is_captcha:
            update_data["total_captchas"] = existing.get("total_captchas", 0) + 1
            update_data["last_captcha_at"] = datetime.now(timezone.utc).isoformat()
        
        await self.update("domains", update_data, "domain = ?", (domain,))
    
    async def set_domain_cooldown(
        self,
        domain: str,
        minutes: int,
        reason: str | None = None,
    ) -> None:
        """Set cooldown for a domain.
        
        Args:
            domain: Domain name.
            minutes: Cooldown duration in minutes.
            reason: Optional reason for cooldown.
        """
        cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        
        await self.update(
            "domains",
            {
                "cooldown_until": cooldown_until.isoformat(),
                "skip_reason": reason,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "domain = ?",
            (domain,),
        )
        
        logger.info(
            "Domain cooldown set",
            domain=domain,
            minutes=minutes,
            reason=reason,
        )
    
    async def is_domain_cooled_down(self, domain: str) -> bool:
        """Check if domain is in cooldown.
        
        Args:
            domain: Domain name.
            
        Returns:
            True if domain is cooled down.
        """
        result = await self.fetch_one(
            "SELECT cooldown_until FROM domains WHERE domain = ?",
            (domain,),
        )
        
        if result is None or result["cooldown_until"] is None:
            return False
        
        cooldown_until = datetime.fromisoformat(result["cooldown_until"])
        return datetime.now(timezone.utc) < cooldown_until
    
    async def update_engine_health(
        self,
        engine: str,
        success: bool,
        latency_ms: float | None = None,
        *,
        is_captcha: bool = False,
    ) -> None:
        """Update engine health metrics.
        
        Args:
            engine: Engine name.
            success: Whether the query succeeded.
            latency_ms: Response latency in milliseconds.
            is_captcha: Whether a CAPTCHA was encountered.
        """
        existing = await self.fetch_one(
            "SELECT * FROM engine_health WHERE engine = ?", (engine,)
        )
        
        if existing is None:
            await self.insert("engine_health", {"engine": engine}, auto_id=False)
            existing = {
                "success_rate_1h": 1.0,
                "captcha_rate": 0.0,
                "median_latency_ms": 1000.0,
                "consecutive_failures": 0,
                "status": "closed",
            }
        
        # Calculate EMA updates
        alpha = 0.1
        success_rate = existing["success_rate_1h"]
        captcha_rate = existing["captcha_rate"]
        
        success_rate = alpha * (1.0 if success else 0.0) + (1 - alpha) * success_rate
        captcha_rate = alpha * (1.0 if is_captcha else 0.0) + (1 - alpha) * captcha_rate
        
        # Update latency if provided
        median_latency = existing["median_latency_ms"]
        if latency_ms is not None:
            median_latency = alpha * latency_ms + (1 - alpha) * median_latency
        
        # Circuit breaker logic
        consecutive_failures = existing["consecutive_failures"]
        status = existing["status"]
        
        if success:
            consecutive_failures = 0
            if status == "half-open":
                status = "closed"
        else:
            consecutive_failures += 1
            if consecutive_failures >= 2 and status == "closed":
                status = "open"
        
        update_data = {
            "success_rate_1h": success_rate,
            "captcha_rate": captcha_rate,
            "median_latency_ms": median_latency,
            "consecutive_failures": consecutive_failures,
            "status": status,
            "total_queries": existing.get("total_queries", 0) + 1,
            "daily_usage": existing.get("daily_usage", 0) + 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        if success:
            update_data["total_success"] = existing.get("total_success", 0) + 1
        else:
            update_data["total_failures"] = existing.get("total_failures", 0) + 1
            update_data["last_failure_at"] = datetime.now(timezone.utc).isoformat()
        
        if status == "open":
            cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=30)
            update_data["cooldown_until"] = cooldown_until.isoformat()
        
        await self.update("engine_health", update_data, "engine = ?", (engine,))
    
    async def get_active_engines(self) -> list[dict[str, Any]]:
        """Get list of active (non-open) engines.
        
        Returns:
            List of active engine records.
        """
        return await self.fetch_all(
            """
            SELECT * FROM engine_health
            WHERE status != 'open'
              AND (cooldown_until IS NULL OR cooldown_until < ?)
              AND (daily_limit IS NULL OR daily_usage < daily_limit)
            ORDER BY weight DESC
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )


# Global database instance
_db: Database | None = None


async def get_database() -> Database:
    """Get the global database instance.
    
    Returns:
        Database instance.
    """
    global _db
    if _db is None:
        _db = Database()
        await _db.connect()
        await _db.initialize_schema()
    return _db


async def close_database() -> None:
    """Close the global database instance."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None

