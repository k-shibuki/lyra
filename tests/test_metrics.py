"""
Tests for metrics collection module.
Tests the MetricsCollector, TaskMetrics, and related functionality.

Related spec: Auto-adaptation and Metrics-driven Control

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-MV-N-01 | MetricValue init | Equivalence – normal | All fields set | - |
| TC-MV-N-02 | MetricValue update | Equivalence – normal | EMA updated correctly | - |
| TC-MV-N-03 | MetricValue to_dict | Equivalence – normal | Dict with all keys | - |
| TC-TM-N-01 | TaskMetrics init | Equivalence – normal | Default values set | - |
| TC-TM-N-02 | harvest_rate calc | Equivalence – normal | useful/pages ratio | - |
| TC-TM-B-01 | harvest_rate 0 pages | Boundary – zero | Returns 0.0 | - |
| TC-TM-N-03 | domain_diversity calc | Equivalence – normal | domains/sources | - |
| TC-TM-N-04 | tor_usage_rate calc | Equivalence – normal | tor/total ratio | - |
| TC-TM-N-05 | error_rates calc | Equivalence – normal | Each rate calculated | - |
| TC-TM-N-06 | primary_source_rate | Equivalence – normal | primary/total | - |
| TC-TM-N-07 | llm_time_ratio | Equivalence – normal | llm/total time | - |
| TC-TM-N-08 | to_dict full | Equivalence – normal | All fields included | - |
| TC-MC-N-01 | start_task | Equivalence – normal | TaskMetrics created | - |
| TC-MC-N-02 | get_task_metrics | Equivalence – normal | Returns metrics | - |
| TC-MC-A-01 | get nonexistent task | Equivalence – abnormal | Returns None | - |
| TC-MC-N-03 | record_query | Equivalence – normal | Counter incremented | - |
| TC-MC-N-04 | record_page_fetch | Equivalence – normal | All fields updated | - |
| TC-MC-N-05 | record_error | Equivalence – normal | Error counts updated | - |
| TC-MC-N-06 | record_fragments | Equivalence – normal | Fragment counts set | - |
| TC-MC-N-07 | record_claim | Equivalence – normal | Claim counts updated | - |
| TC-MC-N-08 | finish_task | Equivalence – normal | Final metrics computed | - |
| TC-MC-N-09 | global_metrics | Equivalence – normal | All metric types | - |
| TC-MC-N-10 | domain_metrics | Equivalence – normal | Domain-specific data | - |
| TC-MC-N-11 | export_snapshot | Equivalence – normal | Full snapshot | - |
| TC-MT-N-01 | all types init | Equivalence – normal | All types in global | - |
| TC-SG-N-01 | singleton | Equivalence – normal | Same instance | - |
"""

import pytest

from src.utils.metrics import (
    MetricsCollector,
    MetricType,
    MetricValue,
    TaskMetrics,
    get_metrics_collector,
)

pytestmark = pytest.mark.unit


class TestMetricValue:
    """Tests for MetricValue class."""

    def test_initial_values(self) -> None:
        """Test initial metric value creation."""
        # Given: Parameters for a MetricValue
        # When: Creating a MetricValue instance
        mv = MetricValue(
            raw_value=0.5,
            ema_short=0.5,
            ema_long=0.5,
            sample_count=1,
        )

        # Then: All values are set correctly
        assert mv.raw_value == 0.5
        assert mv.ema_short == 0.5
        assert mv.ema_long == 0.5
        assert mv.sample_count == 1

    def test_ema_update(self) -> None:
        """Test EMA update calculation."""
        # Given: A MetricValue with initial values
        mv = MetricValue(
            raw_value=0.5,
            ema_short=0.5,
            ema_long=0.5,
            sample_count=1,
        )

        # When: Updating with value 1.0
        mv.update(1.0, alpha_short=0.1, alpha_long=0.01)

        # Then: EMAs are updated correctly
        # EMA short: 0.1 * 1.0 + 0.9 * 0.5 = 0.55
        assert abs(mv.ema_short - 0.55) < 0.001
        # EMA long: 0.01 * 1.0 + 0.99 * 0.5 = 0.505
        assert abs(mv.ema_long - 0.505) < 0.001
        assert mv.sample_count == 2
        assert mv.raw_value == 1.0

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        # Given: A MetricValue with known values
        mv = MetricValue(
            raw_value=0.75,
            ema_short=0.7,
            ema_long=0.65,
            sample_count=10,
        )

        # When: Converting to dict
        d = mv.to_dict()

        # Then: All expected keys are present with correct values
        assert d["raw"] == 0.75, f"Expected raw=0.75, got {d['raw']}"
        assert d["ema_short"] == 0.7, f"Expected ema_short=0.7, got {d['ema_short']}"
        assert d["ema_long"] == 0.65, f"Expected ema_long=0.65, got {d['ema_long']}"
        assert d["samples"] == 10, f"Expected samples=10, got {d['samples']}"
        assert "updated_at" in d, "updated_at key should exist"
        assert isinstance(
            d["updated_at"], str
        ), f"updated_at should be string, got {type(d['updated_at'])}"


class TestTaskMetrics:
    """Tests for TaskMetrics class."""

    def test_task_metrics_creation(self) -> None:
        """Test task metrics initialization."""
        # Given: A task ID
        # When: Creating TaskMetrics
        tm = TaskMetrics(task_id="test-task-1")

        # Then: Default values are set
        assert tm.task_id == "test-task-1"
        assert tm.total_queries == 0
        assert tm.total_pages_fetched == 0
        assert len(tm.unique_domains) == 0

    def test_compute_harvest_rate(self) -> None:
        """Test harvest rate computation."""
        # Given: TaskMetrics with 10 pages fetched, 5 useful fragments
        tm = TaskMetrics(task_id="test")
        tm.total_pages_fetched = 10
        tm.useful_fragments = 5

        # When: Computing metrics
        metrics = tm.compute_metrics()

        # Then: harvest_rate = 5/10 = 0.5
        assert metrics["harvest_rate"] == 0.5

    def test_compute_harvest_rate_zero_pages(self) -> None:
        """Test harvest rate with zero pages."""
        # Given: TaskMetrics with 0 pages fetched
        tm = TaskMetrics(task_id="test")
        tm.total_pages_fetched = 0

        # When: Computing metrics
        metrics = tm.compute_metrics()

        # Then: harvest_rate = 0.0 (no division by zero)
        assert metrics["harvest_rate"] == 0.0

    def test_compute_domain_diversity(self) -> None:
        """Test domain diversity computation."""
        # Given: TaskMetrics with 3 unique domains, 6 total sources
        tm = TaskMetrics(task_id="test")
        tm.unique_domains = {"example.com", "test.org", "demo.net"}
        tm.total_sources = 6

        # When: Computing metrics
        metrics = tm.compute_metrics()

        # Then: domain_diversity = 3/6 = 0.5
        assert metrics["domain_diversity"] == 0.5

    def test_compute_tor_usage_rate(self) -> None:
        """Test Tor usage rate computation."""
        # Given: TaskMetrics with 15 tor requests out of 100
        tm = TaskMetrics(task_id="test")
        tm.total_requests = 100
        tm.tor_requests = 15

        # When: Computing metrics
        metrics = tm.compute_metrics()

        # Then: tor_usage_rate = 15/100 = 0.15
        assert metrics["tor_usage_rate"] == 0.15

    def test_compute_error_rates(self) -> None:
        """Test error rate computations."""
        # Given: TaskMetrics with various error counts
        tm = TaskMetrics(task_id="test")
        tm.total_requests = 100
        tm.captcha_count = 5
        tm.error_403_count = 3
        tm.error_429_count = 2

        # When: Computing metrics
        metrics = tm.compute_metrics()

        # Then: Each error rate is calculated correctly
        assert metrics["captcha_rate"] == 0.05
        assert metrics["http_error_403_rate"] == 0.03
        assert metrics["http_error_429_rate"] == 0.02

    def test_compute_primary_source_rate(self) -> None:
        """Test primary source rate computation."""
        # Given: TaskMetrics with 12 primary sources out of 20
        tm = TaskMetrics(task_id="test")
        tm.total_sources = 20
        tm.primary_sources = 12

        # When: Computing metrics
        metrics = tm.compute_metrics()

        # Then: primary_source_rate = 12/20 = 0.6
        assert metrics["primary_source_rate"] == 0.6

    def test_compute_llm_time_ratio(self) -> None:
        """Test LLM time ratio computation."""
        # Given: TaskMetrics with 15s LLM time out of 60s total
        tm = TaskMetrics(task_id="test")
        tm.total_time_ms = 60000  # 60 seconds
        tm.llm_time_ms = 15000  # 15 seconds

        # When: Computing metrics
        metrics = tm.compute_metrics()

        # Then: llm_time_ratio = 15000/60000 = 0.25
        assert metrics["llm_time_ratio"] == 0.25

    def test_to_dict(self) -> None:
        """Test full dictionary conversion."""
        # Given: TaskMetrics with various values
        tm = TaskMetrics(task_id="test")
        tm.total_queries = 5
        tm.total_pages_fetched = 20
        tm.useful_fragments = 10

        # When: Converting to dict
        d = tm.to_dict()

        # Then: All fields are included
        assert d["task_id"] == "test"
        assert d["counters"]["queries"] == 5
        assert d["counters"]["pages_fetched"] == 20
        assert "computed_metrics" in d
        assert d["computed_metrics"]["harvest_rate"] == 0.5


@pytest.mark.asyncio
class TestMetricsCollector:
    """Tests for MetricsCollector class."""

    async def test_start_task(self) -> None:
        """Test starting task metrics tracking."""
        # Given: A MetricsCollector instance
        collector = MetricsCollector()

        # When: Starting a new task
        metrics = await collector.start_task("test-task-1")

        # Then: TaskMetrics is created with defaults
        assert metrics.task_id == "test-task-1"
        assert metrics.total_queries == 0

    async def test_get_task_metrics(self) -> None:
        """Test retrieving task metrics."""
        # Given: A collector with an active task
        collector = MetricsCollector()
        await collector.start_task("test-task-2")

        # When: Getting task metrics
        metrics = await collector.get_task_metrics("test-task-2")

        # Then: Correct metrics are returned
        assert metrics is not None
        assert metrics.task_id == "test-task-2"

    async def test_get_nonexistent_task(self) -> None:
        """Test retrieving non-existent task metrics."""
        # Given: A collector with no tasks
        collector = MetricsCollector()

        # When: Getting metrics for nonexistent task
        metrics = await collector.get_task_metrics("nonexistent")

        # Then: None is returned
        assert metrics is None

    async def test_record_query(self) -> None:
        """Test recording a query."""
        # Given: A collector with an active task
        collector = MetricsCollector()
        await collector.start_task("test-task-3")

        # When: Recording two queries
        await collector.record_query("test-task-3")
        await collector.record_query("test-task-3")

        # Then: Query count is 2
        metrics = await collector.get_task_metrics("test-task-3")
        assert metrics is not None
        assert metrics.total_queries == 2

    async def test_record_page_fetch(self) -> None:
        """Test recording a page fetch."""
        # Given: A collector with an active task
        collector = MetricsCollector()
        await collector.start_task("test-task-4")

        # When: Recording a page fetch with tor and primary source
        await collector.record_page_fetch(
            "test-task-4",
            "example.com",
            used_tor=True,
            used_headful=False,
            is_primary_source=True,
        )

        # Then: All fields are updated
        metrics = await collector.get_task_metrics("test-task-4")
        assert metrics is not None
        assert metrics.total_pages_fetched == 1
        assert metrics.tor_requests == 1
        assert metrics.primary_sources == 1
        assert "example.com" in metrics.unique_domains

    async def test_record_error(self) -> None:
        """Test recording errors."""
        # Given: A collector with an active task
        collector = MetricsCollector()
        await collector.start_task("test-task-5")

        # When: Recording 403 and captcha errors
        await collector.record_error("test-task-5", "blocked.com", is_403=True)
        await collector.record_error("test-task-5", "captcha.com", is_captcha=True)

        # Then: Error counts are updated
        metrics = await collector.get_task_metrics("test-task-5")
        assert metrics is not None
        assert metrics.error_403_count == 1
        assert metrics.captcha_count == 1

    async def test_record_fragments(self) -> None:
        """Test recording fragment extraction."""
        # Given: A collector with an active task
        collector = MetricsCollector()
        await collector.start_task("test-task-6")

        # When: Recording fragments
        await collector.record_fragments("test-task-6", total=20, useful=15)

        # Then: Fragment counts are set
        metrics = await collector.get_task_metrics("test-task-6")
        assert metrics is not None
        assert metrics.total_fragments == 20
        assert metrics.useful_fragments == 15

    async def test_record_claim(self) -> None:
        """Test recording claims."""
        # Given: A collector with an active task
        collector = MetricsCollector()
        await collector.start_task("test-task-7")

        # When: Recording claims with various flags
        await collector.record_claim("test-task-7", has_timeline=True)
        await collector.record_claim("test-task-7", has_contradiction=True)
        await collector.record_claim("test-task-7")

        # Then: Claim counts are updated
        metrics = await collector.get_task_metrics("test-task-7")
        assert metrics is not None
        assert metrics.total_claims == 3
        assert metrics.claims_with_timeline == 1
        assert metrics.contradictions_found == 1

    async def test_finish_task(self) -> None:
        """Test finishing task and computing final metrics."""
        # Given: A collector with recorded activity
        collector = MetricsCollector()
        await collector.start_task("test-task-8")
        await collector.record_page_fetch("test-task-8", "example.com")
        await collector.record_fragments("test-task-8", total=10, useful=5)

        # When: Finishing the task
        result = await collector.finish_task("test-task-8")

        # Then: Final metrics are computed
        assert "computed_metrics" in result
        assert result["computed_metrics"]["harvest_rate"] == 5.0  # useful/pages

    async def test_global_metrics(self) -> None:
        """Test global metrics retrieval."""
        # Given: A MetricsCollector instance
        collector = MetricsCollector()

        # When: Getting global metrics
        global_metrics = collector.get_global_metrics()

        # Then: Key metrics exist with correct structure
        for metric_name in ["harvest_rate", "tor_usage_rate", "primary_source_rate"]:
            assert metric_name in global_metrics, f"{metric_name} should be in global metrics"
            metric_data = global_metrics[metric_name]
            assert "raw" in metric_data, f"{metric_name} should have 'raw' field"
            assert "ema_short" in metric_data, f"{metric_name} should have 'ema_short' field"
            assert "samples" in metric_data, f"{metric_name} should have 'samples' field"

    async def test_domain_metrics(self) -> None:
        """Test domain-specific metrics."""
        # Given: A collector with recorded domain activity
        collector = MetricsCollector()
        await collector.start_task("test-task-9")
        await collector.record_page_fetch("test-task-9", "example.com")
        await collector.record_error("test-task-9", "example.com", is_403=True)

        # When: Getting domain metrics
        domain_metrics = collector.get_domain_metrics("example.com")

        # Then: Domain-specific data is tracked
        assert "fetch_count" in domain_metrics, "fetch_count should be tracked for domain"
        assert (
            domain_metrics["fetch_count"]["raw"] == 1.0
        ), "fetch_count should be 1 after single fetch"
        assert "error_403_rate" in domain_metrics, "error_403_rate should be tracked for domain"
        assert (
            0.0 <= domain_metrics["error_403_rate"]["ema_short"] <= 1.0
        ), "error_403_rate EMA should be in [0, 1]"

    async def test_export_snapshot(self) -> None:
        """Test exporting full metrics snapshot."""
        # Given: A collector with recorded activity
        collector = MetricsCollector()
        await collector.start_task("test-task-10")
        await collector.record_page_fetch("test-task-10", "example.com")

        # When: Exporting snapshot
        snapshot = await collector.export_snapshot()

        # Then: All required sections are present
        assert "timestamp" in snapshot, "snapshot should have timestamp"
        assert isinstance(snapshot["timestamp"], str), "timestamp should be ISO string"
        assert "global" in snapshot, "snapshot should have global metrics"
        assert isinstance(snapshot["global"], dict), "global should be dict"
        assert "domains" in snapshot, "snapshot should have domains"
        assert isinstance(snapshot["domains"], dict), "domains should be dict"
        assert "example.com" in snapshot["domains"], "example.com should be in domains"
        assert "active_tasks" in snapshot, "snapshot should have active_tasks"
        assert isinstance(snapshot["active_tasks"], list), "active_tasks should be list"
        assert "test-task-10" in snapshot["active_tasks"], "test-task-10 should be in active_tasks"


@pytest.mark.asyncio
class TestMetricTypes:
    """Tests for MetricType enum coverage."""

    async def test_all_metric_types_initialized(self) -> None:
        """Test that all metric types are initialized in collector."""
        # Given: A MetricsCollector instance
        collector = MetricsCollector()

        # When: Getting global metrics
        global_metrics = collector.get_global_metrics()

        # Then: All MetricType values are present
        for metric_type in MetricType:
            assert metric_type.value in global_metrics, f"Missing metric: {metric_type.value}"


def test_get_metrics_collector_singleton() -> None:
    """Test that get_metrics_collector returns singleton."""
    # Given: No prior collector access
    # When: Getting collector twice
    collector1 = get_metrics_collector()
    collector2 = get_metrics_collector()

    # Then: Same instance is returned
    assert collector1 is collector2
