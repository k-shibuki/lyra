"""
Tests for replay module.
Tests DecisionLogger, ReplayEngine, and decision tracking.

Related spec: §4.6 Replay/Reproduction Mode

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-DT-01 | DecisionType values | Equivalence – enum | All types defined | - |
| TC-D-01 | Decision creation | Equivalence – normal | All fields stored | - |
| TC-D-02 | Decision serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-D-03 | Decision deserialization | Equivalence – from_dict | Object correctly populated | - |
| TC-DL-01 | Log decision | Equivalence – logging | Decision added to session | - |
| TC-DL-02 | Start new session | Equivalence – session | New session created | - |
| TC-DL-03 | End session | Equivalence – session | Session completed | - |
| TC-DL-04 | Get current session | Equivalence – retrieval | Returns active session | - |
| TC-RE-01 | Load session file | Equivalence – loading | Session loaded from file | - |
| TC-RE-02 | Replay decision | Equivalence – replay | Decision replayed | - |
| TC-RE-03 | Replay with verification | Equivalence – verification | Matches recorded outcome | - |
| TC-RS-01 | ReplaySession creation | Equivalence – session | Session with decisions | - |
| TC-RS-02 | ReplaySession serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-CF-01 | get_decision_logger | Equivalence – singleton | Returns logger instance | - |
| TC-CF-02 | get_replay_engine | Equivalence – factory | Returns engine instance | - |
| TC-CF-03 | cleanup_decision_logger | Equivalence – cleanup | Logger cleaned up | - |
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.utils.replay import (
    Decision,
    DecisionLogger,
    DecisionType,
    ReplayEngine,
    ReplaySession,
    cleanup_decision_logger,
    get_decision_logger,
    get_replay_engine,
)

pytestmark = pytest.mark.unit


class TestDecisionType:
    """Tests for DecisionType enum."""

    def test_all_decision_types_exist(self):
        """Test that expected decision types are defined."""
        expected = [
            "query_generated",
            "engine_selected",
            "url_prioritized",
            "fetch_method_chosen",
            "route_chosen",
            "fragment_evaluated",
            "claim_extracted",
            "llm_model_selected",
            "policy_adjusted",
            "error_handled",
        ]

        for dt in expected:
            assert DecisionType(dt) is not None


class TestDecision:
    """Tests for Decision dataclass."""

    def test_decision_creation(self):
        """Test creating a decision record."""
        decision = Decision(
            decision_id="test-001",
            timestamp=datetime.now(UTC),
            decision_type=DecisionType.QUERY_GENERATED,
            task_id="task-123",
            cause_id="parent-001",
            input_data={"query": "test query"},
            output_data={"expanded_queries": ["q1", "q2"]},
            context={"novelty_score": 0.8},
            duration_ms=50,
        )

        assert decision.decision_id == "test-001"
        assert decision.decision_type == DecisionType.QUERY_GENERATED
        assert decision.task_id == "task-123"
        assert decision.duration_ms == 50

    def test_decision_to_dict(self):
        """Test converting decision to dictionary."""
        decision = Decision(
            decision_id="test-002",
            timestamp=datetime.now(UTC),
            decision_type=DecisionType.ENGINE_SELECTED,
            task_id="task-456",
            cause_id=None,
            input_data={"available_engines": ["google", "bing"]},
            output_data={"selected": "google"},
            context={},
            duration_ms=10,
        )

        d = decision.to_dict()

        assert d["decision_id"] == "test-002"
        assert d["decision_type"] == "engine_selected"
        assert d["task_id"] == "task-456"
        assert d["input_data"]["available_engines"] == ["google", "bing"]
        assert d["output_data"]["selected"] == "google"
        assert "timestamp" in d

    def test_decision_from_dict(self):
        """Test creating decision from dictionary."""
        data = {
            "decision_id": "test-003",
            "timestamp": datetime.now(UTC).isoformat(),
            "decision_type": "fetch_method_chosen",
            "task_id": "task-789",
            "cause_id": "cause-001",
            "input_data": {"url": "https://example.com"},
            "output_data": {"method": "browser"},
            "context": {"block_score": 0.2},
            "duration_ms": 25,
        }

        decision = Decision.from_dict(data)

        assert decision.decision_id == "test-003"
        assert decision.decision_type == DecisionType.FETCH_METHOD_CHOSEN
        assert decision.input_data["url"] == "https://example.com"


@pytest.mark.asyncio
class TestDecisionLogger:
    """Tests for DecisionLogger class."""

    async def test_logger_creation(self):
        """Test creating a decision logger."""
        logger = DecisionLogger(task_id="test-task-1")

        assert logger.task_id == "test-task-1"
        assert len(logger._decisions) == 0

    async def test_log_decision(self):
        """Test logging a decision."""
        logger = DecisionLogger(task_id="test-task-2")

        decision = await logger.log_decision(
            decision_type=DecisionType.QUERY_GENERATED,
            input_data={"original": "AI research"},
            output_data={"queries": ["AI research", "artificial intelligence"]},
            context={"depth": 0},
            cause_id=None,
            duration_ms=100,
        )

        assert decision is not None
        assert decision.decision_type == DecisionType.QUERY_GENERATED
        assert len(logger._decisions) == 1

    async def test_multiple_decisions(self):
        """Test logging multiple decisions."""
        logger = DecisionLogger(task_id="test-task-3")

        await logger.log_decision(
            decision_type=DecisionType.QUERY_GENERATED,
            input_data={},
            output_data={},
        )
        await logger.log_decision(
            decision_type=DecisionType.ENGINE_SELECTED,
            input_data={},
            output_data={},
        )
        await logger.log_decision(
            decision_type=DecisionType.URL_PRIORITIZED,
            input_data={},
            output_data={},
        )

        assert len(logger._decisions) == 3

    async def test_export_decisions(self):
        """Test exporting decisions to list."""
        logger = DecisionLogger(task_id="test-task-4")

        await logger.log_decision(
            decision_type=DecisionType.CLAIM_EXTRACTED,
            input_data={"passage": "test passage"},
            output_data={"claims": ["claim1"]},
        )

        exported = await logger.export_decisions()

        assert len(exported) == 1
        assert exported[0]["decision_type"] == "claim_extracted"

    async def test_decision_ids_unique(self):
        """Test that decision IDs are unique."""
        logger = DecisionLogger(task_id="test-task-5")

        decisions = []
        for _ in range(10):
            d = await logger.log_decision(
                decision_type=DecisionType.FRAGMENT_EVALUATED,
                input_data={},
                output_data={},
            )
            decisions.append(d)

        ids = [d.decision_id for d in decisions]
        assert len(ids) == len(set(ids)), "Decision IDs should be unique"

    async def test_save_to_file(self, tmp_path):
        """Test saving decisions to file."""
        logger = DecisionLogger(task_id="test-task-6")

        await logger.log_decision(
            decision_type=DecisionType.POLICY_ADJUSTED,
            input_data={"metric": "error_rate"},
            output_data={"action": "increase_cooldown"},
        )

        output_file = tmp_path / "decisions.json"
        result_path = await logger.save_to_file(output_file)

        assert result_path.exists()

        with open(result_path) as f:
            data = json.load(f)

        assert data["task_id"] == "test-task-6"
        assert data["decision_count"] == 1
        assert len(data["decisions"]) == 1


@pytest.mark.asyncio
class TestReplayEngine:
    """Tests for ReplayEngine class."""

    async def test_engine_creation(self):
        """Test creating replay engine."""
        engine = ReplayEngine()

        assert len(engine._sessions) == 0

    async def test_create_replay_session(self):
        """Test creating a replay session."""
        engine = ReplayEngine()

        # Mock database (patching at source since lazy import)
        mock_db_instance = AsyncMock()
        mock_db_instance.fetch_all = AsyncMock(return_value=[])
        with patch("src.storage.database.get_database", new=AsyncMock(return_value=mock_db_instance)):
            session = await engine.create_replay_session("original-task-1")

            assert session.original_task_id == "original-task-1"
            assert session.status == "pending"
            assert session.session_id in engine._sessions

    async def test_compare_decisions_same(self):
        """Test comparing identical decisions."""
        engine = ReplayEngine()

        original = Decision(
            decision_id="orig-1",
            timestamp=datetime.now(UTC),
            decision_type=DecisionType.ENGINE_SELECTED,
            task_id="task-1",
            cause_id=None,
            input_data={"engines": ["a", "b"]},
            output_data={"selected": "a"},
            context={},
        )

        replayed = Decision(
            decision_id="replay-1",
            timestamp=datetime.now(UTC),
            decision_type=DecisionType.ENGINE_SELECTED,
            task_id="task-2",
            cause_id=None,
            input_data={"engines": ["a", "b"]},
            output_data={"selected": "a"},
            context={},
        )

        result = await engine.compare_decisions(original, replayed)

        assert result["diverged"] is False
        assert len(result["differences"]) == 0

    async def test_compare_decisions_diverged(self):
        """Test comparing diverged decisions.
        
        When output_data differs between original and replayed decisions,
        the comparison should indicate divergence and list the specific differences.
        """
        engine = ReplayEngine()

        original = Decision(
            decision_id="orig-2",
            timestamp=datetime.now(UTC),
            decision_type=DecisionType.ENGINE_SELECTED,
            task_id="task-1",
            cause_id=None,
            input_data={"engines": ["a", "b"]},
            output_data={"selected": "a"},
            context={},
        )

        replayed = Decision(
            decision_id="replay-2",
            timestamp=datetime.now(UTC),
            decision_type=DecisionType.ENGINE_SELECTED,
            task_id="task-2",
            cause_id=None,
            input_data={"engines": ["a", "b"]},
            output_data={"selected": "b"},  # Different output
            context={},
        )

        result = await engine.compare_decisions(original, replayed)

        assert result["diverged"] is True, "Decisions with different output should diverge"
        assert len(result["differences"]) == 1, f"Expected 1 difference (output_data), got {len(result['differences'])}"
        assert result["differences"][0]["field"] == "output_data", (
            f"Difference should be in output_data, got {result['differences'][0]['field']}"
        )

    async def test_load_decisions_from_file(self, tmp_path):
        """Test loading decisions from file."""
        engine = ReplayEngine()

        # Create test file
        test_data = {
            "task_id": "test-task",
            "exported_at": datetime.now(UTC).isoformat(),
            "decision_count": 2,
            "decisions": [
                {
                    "decision_id": "d1",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "decision_type": "query_generated",
                    "task_id": "test-task",
                    "cause_id": None,
                    "input_data": {},
                    "output_data": {},
                    "context": {},
                    "duration_ms": 10,
                },
                {
                    "decision_id": "d2",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "decision_type": "engine_selected",
                    "task_id": "test-task",
                    "cause_id": "d1",
                    "input_data": {},
                    "output_data": {},
                    "context": {},
                    "duration_ms": 5,
                },
            ],
        }

        test_file = tmp_path / "test_decisions.json"
        with open(test_file, "w") as f:
            json.dump(test_data, f)

        decisions = await engine.load_decisions_from_file(test_file)

        assert len(decisions) == 2
        assert decisions[0].decision_type == DecisionType.QUERY_GENERATED
        assert decisions[1].decision_type == DecisionType.ENGINE_SELECTED

    async def test_export_session_report(self, tmp_path):
        """Test exporting session report."""
        engine = ReplayEngine()

        # Create session
        session = ReplaySession(
            session_id="test-session",
            original_task_id="orig-task",
            replay_task_id="replay-task",
            status="completed",
            decisions_replayed=10,
            decisions_diverged=2,
        )
        engine._sessions["test-session"] = session

        output_file = tmp_path / "report.json"
        report = await engine.export_session_report("test-session", output_file)

        assert report["session_id"] == "test-session"
        assert report["statistics"]["decisions_replayed"] == 10
        assert report["statistics"]["decisions_diverged"] == 2
        assert report["statistics"]["divergence_rate"] == 0.2
        assert output_file.exists()


class TestReplaySession:
    """Tests for ReplaySession dataclass."""

    def test_session_creation(self):
        """Test creating a replay session."""
        session = ReplaySession(
            session_id="session-001",
            original_task_id="task-001",
        )

        assert session.session_id == "session-001"
        assert session.original_task_id == "task-001"
        assert session.status == "pending"
        assert session.decisions_replayed == 0
        assert session.decisions_diverged == 0


def test_get_decision_logger():
    """Test get_decision_logger helper function."""
    # Reset global state
    import src.utils.replay as replay
    replay._loggers.clear()

    logger1 = get_decision_logger("task-1")
    logger2 = get_decision_logger("task-1")
    logger3 = get_decision_logger("task-2")

    assert logger1 is logger2
    assert logger1 is not logger3


def test_get_replay_engine_singleton():
    """Test get_replay_engine returns singleton."""
    # Reset global state
    import src.utils.replay as replay
    replay._replay_engine = None

    engine1 = get_replay_engine()
    engine2 = get_replay_engine()

    assert engine1 is engine2

    # Cleanup
    replay._replay_engine = None


@pytest.mark.asyncio
async def test_cleanup_decision_logger():
    """Test cleanup_decision_logger helper."""
    import src.utils.replay as replay
    replay._loggers.clear()

    logger = get_decision_logger("cleanup-task")
    await logger.log_decision(
        decision_type=DecisionType.ERROR_HANDLED,
        input_data={},
        output_data={},
    )

    assert "cleanup-task" in replay._loggers

    # Mock save operations
    with patch.object(logger, "save_to_db", AsyncMock()):
        with patch.object(logger, "save_to_file", AsyncMock(return_value=Path("/tmp/test.json"))):
            await cleanup_decision_logger("cleanup-task", save=True)

    assert "cleanup-task" not in replay._loggers

