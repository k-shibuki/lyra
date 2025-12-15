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
    
    async def get_engine_health_metrics(self, engine: str) -> dict[str, Any] | None:
        """Get engine health metrics for dynamic weight calculation.
        
        Per §3.1.4: Retrieve EMA metrics from engine_health table for
        calculating dynamic engine weights.
        
        Args:
            engine: Engine name (case-insensitive).
            
        Returns:
            Dictionary with keys:
            - success_rate_1h: 1-hour EMA success rate
            - success_rate_24h: 24-hour EMA success rate
            - captcha_rate: CAPTCHA encounter rate
            - median_latency_ms: Median latency in milliseconds
            - http_error_rate: HTTP error rate
            - updated_at: Last update timestamp (used as last_used_at)
            Returns None if engine not found.
        """
        result = await self.fetch_one(
            """
            SELECT 
                engine,
                success_rate_1h,
                success_rate_24h,
                captcha_rate,
                median_latency_ms,
                http_error_rate,
                updated_at
            FROM engine_health 
            WHERE engine = ?
            """,
            (engine.lower(),),
        )
        
        if result is None:
            return None
        
        return {
            "engine": result["engine"],
            "success_rate_1h": result.get("success_rate_1h", 1.0) or 1.0,
            "success_rate_24h": result.get("success_rate_24h", 1.0) or 1.0,
            "captcha_rate": result.get("captcha_rate", 0.0) or 0.0,
            "median_latency_ms": result.get("median_latency_ms", 1000.0) or 1000.0,
            "http_error_rate": result.get("http_error_rate", 0.0) or 0.0,
            "updated_at": result.get("updated_at"),
        }
    
    # ============================================================
    # Fetch Cache Operations (304 support)
    # ============================================================
    
    async def get_fetch_cache(
        self,
        url: str,
    ) -> dict[str, Any] | None:
        """Get cached fetch data for a URL.
        
        Args:
            url: URL to look up (will be normalized).
            
        Returns:
            Cache record or None if not found/expired.
        """
        url_normalized = self._normalize_url(url)
        
        result = await self.fetch_one(
            """
            SELECT * FROM cache_fetch 
            WHERE url_normalized = ?
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            (url_normalized, datetime.now(timezone.utc).isoformat()),
        )
        
        if result:
            # Update hit statistics
            await self.execute(
                """
                UPDATE cache_fetch 
                SET last_validated_at = ?
                WHERE url_normalized = ?
                """,
                (datetime.now(timezone.utc).isoformat(), url_normalized),
            )
        
        return result
    
    async def set_fetch_cache(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        content_hash: str | None = None,
        content_path: str | None = None,
        ttl_hours: int = 24,
    ) -> None:
        """Store or update fetch cache for a URL.
        
        Args:
            url: URL (will be normalized).
            etag: ETag header value.
            last_modified: Last-Modified header value.
            content_hash: SHA256 hash of content.
            content_path: Path to cached content file.
            ttl_hours: Cache TTL in hours.
        """
        url_normalized = self._normalize_url(url)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        
        await self.execute(
            """
            INSERT OR REPLACE INTO cache_fetch 
            (url_normalized, etag, last_modified, content_hash, content_path, 
             created_at, last_validated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url_normalized,
                etag,
                last_modified,
                content_hash,
                content_path,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                expires_at.isoformat(),
            ),
        )
    
    async def invalidate_fetch_cache(self, url: str) -> None:
        """Invalidate fetch cache for a URL.
        
        Args:
            url: URL to invalidate.
        """
        url_normalized = self._normalize_url(url)
        await self.execute(
            "DELETE FROM cache_fetch WHERE url_normalized = ?",
            (url_normalized,),
        )
    
    async def update_fetch_cache_validation(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        ttl_hours: int = 24,
    ) -> None:
        """Update cache validation timestamp (for 304 responses).
        
        Args:
            url: URL (will be normalized).
            etag: New ETag if provided.
            last_modified: New Last-Modified if provided.
            ttl_hours: Cache TTL extension in hours.
        """
        url_normalized = self._normalize_url(url)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        
        # Build dynamic update
        updates = ["last_validated_at = ?", "expires_at = ?"]
        params: list[Any] = [
            datetime.now(timezone.utc).isoformat(),
            expires_at.isoformat(),
        ]
        
        if etag is not None:
            updates.append("etag = ?")
            params.append(etag)
        
        if last_modified is not None:
            updates.append("last_modified = ?")
            params.append(last_modified)
        
        params.append(url_normalized)
        
        await self.execute(
            f"UPDATE cache_fetch SET {', '.join(updates)} WHERE url_normalized = ?",
            tuple(params),
        )
    
    async def get_fetch_cache_stats(self) -> dict[str, Any]:
        """Get fetch cache statistics.
        
        Returns:
            Statistics dict with cache hit rate, total entries, etc.
        """
        result = await self.fetch_one(
            """
            SELECT 
                COUNT(*) as total_entries,
                COUNT(CASE WHEN expires_at > ? THEN 1 END) as valid_entries,
                COUNT(CASE WHEN etag IS NOT NULL THEN 1 END) as with_etag,
                COUNT(CASE WHEN last_modified IS NOT NULL THEN 1 END) as with_last_modified
            FROM cache_fetch
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
        return result or {}
    
    async def cleanup_expired_fetch_cache(self) -> int:
        """Remove expired fetch cache entries.
        
        Returns:
            Number of entries removed.
        """
        cursor = await self.execute(
            "DELETE FROM cache_fetch WHERE expires_at < ?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        return cursor.rowcount
    
    # ============================================================
    # Metrics & Policy Operations
    # ============================================================
    
    async def save_metrics_snapshot(
        self,
        metrics: dict[str, float],
        full_snapshot: dict[str, Any] | None = None,
    ) -> int:
        """Save a global metrics snapshot.
        
        Args:
            metrics: Dictionary of metric name to value.
            full_snapshot: Optional full snapshot JSON.
            
        Returns:
            Row ID of inserted snapshot.
        """
        cursor = await self.execute(
            """
            INSERT INTO metrics_snapshot (
                harvest_rate, novelty_score, duplicate_rate, domain_diversity,
                tor_usage_rate, headful_rate, referer_match_rate, cache_304_rate,
                captcha_rate, http_error_403_rate, http_error_429_rate,
                primary_source_rate, citation_loop_rate, narrative_diversity,
                contradiction_rate, timeline_coverage, aggregator_rate,
                llm_time_ratio, gpu_utilization, browser_utilization,
                full_snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics.get("harvest_rate"),
                metrics.get("novelty_score"),
                metrics.get("duplicate_rate"),
                metrics.get("domain_diversity"),
                metrics.get("tor_usage_rate"),
                metrics.get("headful_rate"),
                metrics.get("referer_match_rate"),
                metrics.get("cache_304_rate"),
                metrics.get("captcha_rate"),
                metrics.get("http_error_403_rate"),
                metrics.get("http_error_429_rate"),
                metrics.get("primary_source_rate"),
                metrics.get("citation_loop_rate"),
                metrics.get("narrative_diversity"),
                metrics.get("contradiction_rate"),
                metrics.get("timeline_coverage"),
                metrics.get("aggregator_rate"),
                metrics.get("llm_time_ratio"),
                metrics.get("gpu_utilization"),
                metrics.get("browser_utilization"),
                json.dumps(full_snapshot) if full_snapshot else None,
            ),
        )
        return cursor.lastrowid
    
    async def save_task_metrics(
        self,
        task_id: str,
        metrics_data: dict[str, Any],
    ) -> None:
        """Save metrics for a completed task.
        
        Args:
            task_id: Task identifier.
            metrics_data: Full metrics data from TaskMetrics.to_dict().
        """
        counters = metrics_data.get("counters", {})
        errors = metrics_data.get("errors", {})
        quality = metrics_data.get("quality", {})
        timing = metrics_data.get("timing", {})
        computed = metrics_data.get("computed_metrics", {})
        
        await self.execute(
            """
            INSERT INTO task_metrics (
                task_id,
                total_queries, total_pages_fetched, total_fragments, useful_fragments,
                total_requests, tor_requests, headful_requests, cache_304_hits,
                revisit_count, referer_matched,
                captcha_count, error_403_count, error_429_count,
                primary_sources, total_sources, unique_domains,
                citation_loops_detected, total_citations, contradictions_found,
                total_claims, claims_with_timeline, aggregator_sources,
                llm_time_ms, total_time_ms, computed_metrics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                counters.get("queries", 0),
                counters.get("pages_fetched", 0),
                counters.get("fragments", 0),
                counters.get("useful_fragments", 0),
                counters.get("requests", 0),
                counters.get("tor_requests", 0),
                counters.get("headful_requests", 0),
                counters.get("cache_304_hits", 0),
                counters.get("revisits", 0),
                counters.get("referer_matched", 0),
                errors.get("captcha", 0),
                errors.get("http_403", 0),
                errors.get("http_429", 0),
                quality.get("primary_sources", 0),
                quality.get("total_sources", 0),
                quality.get("unique_domains", 0),
                quality.get("citation_loops", 0),
                quality.get("total_citations", 0),
                quality.get("contradictions", 0),
                quality.get("total_claims", 0),
                quality.get("claims_with_timeline", 0),
                quality.get("aggregator_sources", 0),
                timing.get("llm_time_ms", 0),
                timing.get("total_time_ms", 0),
                json.dumps(computed) if computed else None,
            ),
        )
        
        logger.info("Task metrics saved", task_id=task_id)
    
    async def save_policy_update(
        self,
        target_type: str,
        target_id: str,
        parameter: str,
        old_value: float,
        new_value: float,
        reason: str,
        metrics_snapshot: dict[str, Any] | None = None,
    ) -> None:
        """Save a policy update record.
        
        Args:
            target_type: "engine" or "domain".
            target_id: Engine or domain name.
            parameter: Parameter that was changed.
            old_value: Previous value.
            new_value: New value.
            reason: Reason for the change.
            metrics_snapshot: Optional metrics at time of change.
        """
        await self.execute(
            """
            INSERT INTO policy_updates 
            (target_type, target_id, parameter, old_value, new_value, reason, metrics_snapshot_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_type,
                target_id,
                parameter,
                old_value,
                new_value,
                reason,
                json.dumps(metrics_snapshot) if metrics_snapshot else None,
            ),
        )
    
    async def save_decision(
        self,
        decision_id: str,
        task_id: str,
        decision_type: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        context: dict[str, Any] | None = None,
        cause_id: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        """Save a decision for replay.
        
        Args:
            decision_id: Unique decision identifier.
            task_id: Task identifier.
            decision_type: Type of decision.
            input_data: Decision input.
            output_data: Decision output.
            context: Optional context data.
            cause_id: Parent cause ID.
            duration_ms: Decision duration.
        """
        await self.execute(
            """
            INSERT INTO decisions 
            (id, task_id, decision_type, cause_id, input_json, output_json, context_json, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                task_id,
                decision_type,
                cause_id,
                json.dumps(input_data),
                json.dumps(output_data),
                json.dumps(context) if context else None,
                duration_ms,
            ),
        )
    
    async def get_latest_metrics_snapshot(self) -> dict[str, Any] | None:
        """Get the most recent metrics snapshot.
        
        Returns:
            Latest snapshot or None.
        """
        return await self.fetch_one(
            "SELECT * FROM metrics_snapshot ORDER BY timestamp DESC LIMIT 1"
        )
    
    async def get_task_metrics(self, task_id: str) -> dict[str, Any] | None:
        """Get metrics for a specific task.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            Task metrics or None.
        """
        return await self.fetch_one(
            "SELECT * FROM task_metrics WHERE task_id = ?",
            (task_id,),
        )
    
    async def get_policy_update_history(
        self,
        limit: int = 100,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get policy update history.
        
        Args:
            limit: Maximum records to return.
            target_type: Filter by target type.
            target_id: Filter by target ID.
            
        Returns:
            List of policy update records.
        """
        query = "SELECT * FROM policy_updates WHERE 1=1"
        params: list[Any] = []
        
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)
        
        if target_id:
            query += " AND target_id = ?"
            params.append(target_id)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        return await self.fetch_all(query, tuple(params))
    
    async def get_decisions_for_task(self, task_id: str) -> list[dict[str, Any]]:
        """Get all decisions for a task.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            List of decision records.
        """
        return await self.fetch_all(
            "SELECT * FROM decisions WHERE task_id = ? ORDER BY timestamp ASC",
            (task_id,),
        )
    
    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for cache key.
        
        Removes fragment, sorts query parameters, lowercases scheme and host.
        
        Args:
            url: URL to normalize.
            
        Returns:
            Normalized URL string.
        """
        from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
        
        parsed = urlparse(url)
        
        # Lowercase scheme and host
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        
        # Sort query parameters
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        query_params.sort()
        query = urlencode(query_params)
        
        # Remove fragment
        normalized = urlunparse((scheme, netloc, parsed.path, parsed.params, query, ""))
        
        return normalized


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

