"""
Replay mode for Lancet.
Enables reconstruction and re-execution of decision flows from logs.

Features:
- Export decision logs for analysis
- Replay task flows for A/B testing
- Compare metrics between runs
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.config import get_project_root, get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class DecisionType(str, Enum):
    """Types of decisions that can be replayed."""
    QUERY_GENERATED = "query_generated"
    ENGINE_SELECTED = "engine_selected"
    URL_PRIORITIZED = "url_prioritized"
    FETCH_METHOD_CHOSEN = "fetch_method_chosen"
    ROUTE_CHOSEN = "route_chosen"       # direct/tor/browser
    FRAGMENT_EVALUATED = "fragment_evaluated"
    CLAIM_EXTRACTED = "claim_extracted"
    LLM_MODEL_SELECTED = "llm_model_selected"
    POLICY_ADJUSTED = "policy_adjusted"
    ERROR_HANDLED = "error_handled"


@dataclass
class Decision:
    """A single decision made during task execution."""
    decision_id: str
    timestamp: datetime
    decision_type: DecisionType
    task_id: str
    cause_id: str | None
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    context: dict[str, Any]  # Metrics/state at decision time
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp.isoformat(),
            "decision_type": self.decision_type.value,
            "task_id": self.task_id,
            "cause_id": self.cause_id,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "context": self.context,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Decision":
        """Create from dictionary."""
        return cls(
            decision_id=data["decision_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            decision_type=DecisionType(data["decision_type"]),
            task_id=data["task_id"],
            cause_id=data.get("cause_id"),
            input_data=data["input_data"],
            output_data=data["output_data"],
            context=data.get("context", {}),
            duration_ms=data.get("duration_ms", 0),
        )


@dataclass
class ReplaySession:
    """A replay session tracking decisions and outcomes."""
    session_id: str
    original_task_id: str
    replay_task_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    decisions_replayed: int = 0
    decisions_diverged: int = 0
    divergence_points: list[dict[str, Any]] = field(default_factory=list)
    metrics_comparison: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, failed


class DecisionLogger:
    """Logger for recording decisions during task execution.

    Records all decision points to enable later replay and analysis.
    """

    def __init__(self, task_id: str):
        """Initialize decision logger.

        Args:
            task_id: Task being logged.
        """
        self.task_id = task_id
        self._decisions: list[Decision] = []
        self._lock = asyncio.Lock()
        self._counter = 0

    def _generate_id(self) -> str:
        """Generate unique decision ID."""
        self._counter += 1
        timestamp = datetime.now(UTC).isoformat()
        data = f"{self.task_id}:{self._counter}:{timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    async def log_decision(
        self,
        decision_type: DecisionType,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        context: dict[str, Any] | None = None,
        cause_id: str | None = None,
        duration_ms: int = 0,
    ) -> Decision:
        """Log a decision.

        Args:
            decision_type: Type of decision.
            input_data: Input to the decision.
            output_data: Output/result of the decision.
            context: Additional context (metrics, state).
            cause_id: Parent cause ID for tracing.
            duration_ms: Time taken for decision.

        Returns:
            Logged Decision object.
        """
        async with self._lock:
            decision = Decision(
                decision_id=self._generate_id(),
                timestamp=datetime.now(UTC),
                decision_type=decision_type,
                task_id=self.task_id,
                cause_id=cause_id,
                input_data=input_data,
                output_data=output_data,
                context=context or {},
                duration_ms=duration_ms,
            )

            self._decisions.append(decision)
            return decision

    async def export_decisions(self) -> list[dict[str, Any]]:
        """Export all logged decisions.

        Returns:
            List of decision dictionaries.
        """
        async with self._lock:
            return [d.to_dict() for d in self._decisions]

    async def save_to_db(self) -> None:
        """Persist decisions to database."""
        # Lazy import to avoid circular dependency
        from src.storage.database import get_database
        db = await get_database()

        async with self._lock:
            for decision in self._decisions:
                await db.log_event(
                    event_type="decision",
                    message=f"Decision: {decision.decision_type.value}",
                    task_id=self.task_id,
                    cause_id=decision.cause_id,
                    component="decision_logger",
                    details=decision.to_dict(),
                )

    async def save_to_file(self, path: Path | None = None) -> Path:
        """Save decisions to JSON file.

        Args:
            path: Output path. Auto-generated if None.

        Returns:
            Path to saved file.
        """
        if path is None:
            settings = get_settings()
            logs_dir = get_project_root() / settings.general.logs_dir / "decisions"
            logs_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            path = logs_dir / f"decisions_{self.task_id}_{timestamp}.json"

        async with self._lock:
            decisions = [d.to_dict() for d in self._decisions]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "task_id": self.task_id,
                    "exported_at": datetime.now(UTC).isoformat(),
                    "decision_count": len(decisions),
                    "decisions": decisions,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

        logger.info("Decisions exported", path=str(path), count=len(decisions))
        return path


class ReplayEngine:
    """Engine for replaying task decision flows.

    Enables:
    - Re-execution of tasks with same or modified parameters
    - Comparison of outcomes between runs
    - A/B testing of policy changes
    """

    def __init__(self):
        """Initialize replay engine."""
        self._sessions: dict[str, ReplaySession] = {}
        self._lock = asyncio.Lock()

    async def load_decisions_from_file(self, path: Path) -> list[Decision]:
        """Load decisions from JSON file.

        Args:
            path: Path to decision file.

        Returns:
            List of Decision objects.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        return [Decision.from_dict(d) for d in data["decisions"]]

    async def load_decisions_from_db(
        self,
        task_id: str,
    ) -> list[Decision]:
        """Load decisions from database.

        Args:
            task_id: Task ID to load decisions for.

        Returns:
            List of Decision objects.
        """
        # Lazy import to avoid circular dependency
        from src.storage.database import get_database
        db = await get_database()

        rows = await db.fetch_all(
            """
            SELECT details_json FROM event_log
            WHERE task_id = ? AND event_type = 'decision'
            ORDER BY timestamp ASC
            """,
            (task_id,),
        )

        decisions = []
        for row in rows:
            if row["details_json"]:
                data = json.loads(row["details_json"])
                decisions.append(Decision.from_dict(data))

        return decisions

    async def create_replay_session(
        self,
        original_task_id: str,
        decisions: list[Decision] | None = None,
    ) -> ReplaySession:
        """Create a new replay session.

        Args:
            original_task_id: Task ID to replay.
            decisions: Pre-loaded decisions (loads from DB if None).

        Returns:
            ReplaySession object.
        """
        import uuid

        session_id = str(uuid.uuid4())[:8]

        if decisions is None:
            decisions = await self.load_decisions_from_db(original_task_id)

        session = ReplaySession(
            session_id=session_id,
            original_task_id=original_task_id,
        )

        async with self._lock:
            self._sessions[session_id] = session

        logger.info(
            "Replay session created",
            session_id=session_id,
            original_task_id=original_task_id,
            decision_count=len(decisions),
        )

        return session

    async def compare_decisions(
        self,
        original: Decision,
        replayed: Decision,
    ) -> dict[str, Any]:
        """Compare two decisions for divergence.

        Args:
            original: Original decision.
            replayed: Replayed decision.

        Returns:
            Comparison result with divergence info.
        """
        diverged = False
        differences = []

        # Compare output data
        if original.output_data != replayed.output_data:
            diverged = True
            differences.append({
                "field": "output_data",
                "original": original.output_data,
                "replayed": replayed.output_data,
            })

        # Compare decision type
        if original.decision_type != replayed.decision_type:
            diverged = True
            differences.append({
                "field": "decision_type",
                "original": original.decision_type.value,
                "replayed": replayed.decision_type.value,
            })

        return {
            "diverged": diverged,
            "differences": differences,
            "original_id": original.decision_id,
            "replayed_id": replayed.decision_id,
            "decision_type": original.decision_type.value,
        }

    async def export_session_report(
        self,
        session_id: str,
        output_path: Path | None = None,
    ) -> dict[str, Any]:
        """Export replay session report.

        Args:
            session_id: Session to export.
            output_path: Optional path to save report.

        Returns:
            Report dictionary.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        report = {
            "session_id": session.session_id,
            "original_task_id": session.original_task_id,
            "replay_task_id": session.replay_task_id,
            "started_at": session.started_at.isoformat(),
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            "status": session.status,
            "statistics": {
                "decisions_replayed": session.decisions_replayed,
                "decisions_diverged": session.decisions_diverged,
                "divergence_rate": (
                    session.decisions_diverged / session.decisions_replayed
                    if session.decisions_replayed > 0 else 0
                ),
            },
            "divergence_points": session.divergence_points,
            "metrics_comparison": session.metrics_comparison,
        }

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info("Replay report exported", path=str(output_path))

        return report

    async def compare_task_metrics(
        self,
        task_id_a: str,
        task_id_b: str,
    ) -> dict[str, Any]:
        """Compare metrics between two task runs.

        Args:
            task_id_a: First task ID.
            task_id_b: Second task ID.

        Returns:
            Metrics comparison dictionary.
        """
        # Lazy import to avoid circular dependency
        from src.storage.database import get_database
        db = await get_database()

        # Get task info
        task_a = await db.fetch_one(
            "SELECT * FROM tasks WHERE id = ?", (task_id_a,)
        )
        task_b = await db.fetch_one(
            "SELECT * FROM tasks WHERE id = ?", (task_id_b,)
        )

        if not task_a or not task_b:
            raise ValueError("One or both tasks not found")

        # Get query counts
        queries_a = await db.fetch_one(
            "SELECT COUNT(*) as count FROM queries WHERE task_id = ?", (task_id_a,)
        )
        queries_b = await db.fetch_one(
            "SELECT COUNT(*) as count FROM queries WHERE task_id = ?", (task_id_b,)
        )

        # Get page counts
        pages_a = await db.fetch_one(
            """
            SELECT COUNT(DISTINCT p.id) as count 
            FROM pages p
            JOIN serp_items s ON s.url = p.url
            JOIN queries q ON q.id = s.query_id
            WHERE q.task_id = ?
            """,
            (task_id_a,),
        )
        pages_b = await db.fetch_one(
            """
            SELECT COUNT(DISTINCT p.id) as count 
            FROM pages p
            JOIN serp_items s ON s.url = p.url
            JOIN queries q ON q.id = s.query_id
            WHERE q.task_id = ?
            """,
            (task_id_b,),
        )

        # Get claim counts
        claims_a = await db.fetch_one(
            "SELECT COUNT(*) as count FROM claims WHERE task_id = ?", (task_id_a,)
        )
        claims_b = await db.fetch_one(
            "SELECT COUNT(*) as count FROM claims WHERE task_id = ?", (task_id_b,)
        )

        return {
            "task_a": {
                "id": task_id_a,
                "query": task_a.get("query"),
                "status": task_a.get("status"),
                "queries": queries_a.get("count", 0) if queries_a else 0,
                "pages": pages_a.get("count", 0) if pages_a else 0,
                "claims": claims_a.get("count", 0) if claims_a else 0,
            },
            "task_b": {
                "id": task_id_b,
                "query": task_b.get("query"),
                "status": task_b.get("status"),
                "queries": queries_b.get("count", 0) if queries_b else 0,
                "pages": pages_b.get("count", 0) if pages_b else 0,
                "claims": claims_b.get("count", 0) if claims_b else 0,
            },
            "differences": {
                "queries": (queries_b.get("count", 0) if queries_b else 0) - (queries_a.get("count", 0) if queries_a else 0),
                "pages": (pages_b.get("count", 0) if pages_b else 0) - (pages_a.get("count", 0) if pages_a else 0),
                "claims": (claims_b.get("count", 0) if claims_b else 0) - (claims_a.get("count", 0) if claims_a else 0),
            },
        }


# Global instances
_loggers: dict[str, DecisionLogger] = {}
_replay_engine: ReplayEngine | None = None


def get_decision_logger(task_id: str) -> DecisionLogger:
    """Get or create a decision logger for a task.

    Args:
        task_id: Task identifier.

    Returns:
        DecisionLogger instance.
    """
    if task_id not in _loggers:
        _loggers[task_id] = DecisionLogger(task_id)
    return _loggers[task_id]


def get_replay_engine() -> ReplayEngine:
    """Get the global replay engine.

    Returns:
        ReplayEngine instance.
    """
    global _replay_engine
    if _replay_engine is None:
        _replay_engine = ReplayEngine()
    return _replay_engine


async def cleanup_decision_logger(task_id: str, save: bool = True) -> None:
    """Cleanup decision logger after task completion.

    Args:
        task_id: Task identifier.
        save: Whether to save decisions before cleanup.
    """
    if task_id in _loggers:
        logger_instance = _loggers[task_id]
        if save:
            await logger_instance.save_to_db()
            await logger_instance.save_to_file()
        del _loggers[task_id]

