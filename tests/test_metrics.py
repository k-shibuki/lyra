"""
Tests for metrics collection module.
Tests the MetricsCollector, TaskMetrics, and related functionality.

Related spec: §4.6 自動適応・メトリクス駆動制御
"""

import asyncio
import pytest
from datetime import datetime, timezone

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
    
    def test_initial_values(self):
        """Test initial metric value creation."""
        mv = MetricValue(
            raw_value=0.5,
            ema_short=0.5,
            ema_long=0.5,
            sample_count=1,
        )
        assert mv.raw_value == 0.5
        assert mv.ema_short == 0.5
        assert mv.ema_long == 0.5
        assert mv.sample_count == 1
    
    def test_ema_update(self):
        """Test EMA update calculation."""
        mv = MetricValue(
            raw_value=0.5,
            ema_short=0.5,
            ema_long=0.5,
            sample_count=1,
        )
        
        # Update with value 1.0
        mv.update(1.0, alpha_short=0.1, alpha_long=0.01)
        
        # EMA short: 0.1 * 1.0 + 0.9 * 0.5 = 0.55
        assert abs(mv.ema_short - 0.55) < 0.001
        # EMA long: 0.01 * 1.0 + 0.99 * 0.5 = 0.505
        assert abs(mv.ema_long - 0.505) < 0.001
        assert mv.sample_count == 2
        assert mv.raw_value == 1.0
    
    def test_to_dict(self):
        """Test conversion to dictionary.
        
        Verifies that to_dict produces a dictionary with all expected keys
        and correct values for serialization/logging.
        """
        mv = MetricValue(
            raw_value=0.75,
            ema_short=0.7,
            ema_long=0.65,
            sample_count=10,
        )
        
        d = mv.to_dict()
        assert d["raw"] == 0.75, f"Expected raw=0.75, got {d['raw']}"
        assert d["ema_short"] == 0.7, f"Expected ema_short=0.7, got {d['ema_short']}"
        assert d["ema_long"] == 0.65, f"Expected ema_long=0.65, got {d['ema_long']}"
        assert d["samples"] == 10, f"Expected samples=10, got {d['samples']}"
        # Verify updated_at is a valid ISO timestamp string
        assert "updated_at" in d, "updated_at key should exist"
        assert isinstance(d["updated_at"], str), f"updated_at should be string, got {type(d['updated_at'])}"


class TestTaskMetrics:
    """Tests for TaskMetrics class."""
    
    def test_task_metrics_creation(self):
        """Test task metrics initialization."""
        tm = TaskMetrics(task_id="test-task-1")
        
        assert tm.task_id == "test-task-1"
        assert tm.total_queries == 0
        assert tm.total_pages_fetched == 0
        assert len(tm.unique_domains) == 0
    
    def test_compute_harvest_rate(self):
        """Test harvest rate computation."""
        tm = TaskMetrics(task_id="test")
        tm.total_pages_fetched = 10
        tm.useful_fragments = 5
        
        metrics = tm.compute_metrics()
        assert metrics["harvest_rate"] == 0.5
    
    def test_compute_harvest_rate_zero_pages(self):
        """Test harvest rate with zero pages."""
        tm = TaskMetrics(task_id="test")
        tm.total_pages_fetched = 0
        
        metrics = tm.compute_metrics()
        assert metrics["harvest_rate"] == 0.0
    
    def test_compute_domain_diversity(self):
        """Test domain diversity computation."""
        tm = TaskMetrics(task_id="test")
        tm.unique_domains = {"example.com", "test.org", "demo.net"}
        tm.total_sources = 6
        
        metrics = tm.compute_metrics()
        assert metrics["domain_diversity"] == 0.5
    
    def test_compute_tor_usage_rate(self):
        """Test Tor usage rate computation."""
        tm = TaskMetrics(task_id="test")
        tm.total_requests = 100
        tm.tor_requests = 15
        
        metrics = tm.compute_metrics()
        assert metrics["tor_usage_rate"] == 0.15
    
    def test_compute_error_rates(self):
        """Test error rate computations."""
        tm = TaskMetrics(task_id="test")
        tm.total_requests = 100
        tm.captcha_count = 5
        tm.error_403_count = 3
        tm.error_429_count = 2
        
        metrics = tm.compute_metrics()
        assert metrics["captcha_rate"] == 0.05
        assert metrics["http_error_403_rate"] == 0.03
        assert metrics["http_error_429_rate"] == 0.02
    
    def test_compute_primary_source_rate(self):
        """Test primary source rate computation."""
        tm = TaskMetrics(task_id="test")
        tm.total_sources = 20
        tm.primary_sources = 12
        
        metrics = tm.compute_metrics()
        assert metrics["primary_source_rate"] == 0.6
    
    def test_compute_llm_time_ratio(self):
        """Test LLM time ratio computation."""
        tm = TaskMetrics(task_id="test")
        tm.total_time_ms = 60000  # 60 seconds
        tm.llm_time_ms = 15000   # 15 seconds
        
        metrics = tm.compute_metrics()
        assert metrics["llm_time_ratio"] == 0.25
    
    def test_to_dict(self):
        """Test full dictionary conversion."""
        tm = TaskMetrics(task_id="test")
        tm.total_queries = 5
        tm.total_pages_fetched = 20
        tm.useful_fragments = 10
        
        d = tm.to_dict()
        
        assert d["task_id"] == "test"
        assert d["counters"]["queries"] == 5
        assert d["counters"]["pages_fetched"] == 20
        assert "computed_metrics" in d
        assert d["computed_metrics"]["harvest_rate"] == 0.5


@pytest.mark.asyncio
class TestMetricsCollector:
    """Tests for MetricsCollector class."""
    
    async def test_start_task(self):
        """Test starting task metrics tracking."""
        collector = MetricsCollector()
        
        metrics = await collector.start_task("test-task-1")
        
        assert metrics.task_id == "test-task-1"
        assert metrics.total_queries == 0
    
    async def test_get_task_metrics(self):
        """Test retrieving task metrics."""
        collector = MetricsCollector()
        
        await collector.start_task("test-task-2")
        metrics = await collector.get_task_metrics("test-task-2")
        
        assert metrics is not None
        assert metrics.task_id == "test-task-2"
    
    async def test_get_nonexistent_task(self):
        """Test retrieving non-existent task metrics."""
        collector = MetricsCollector()
        
        metrics = await collector.get_task_metrics("nonexistent")
        
        assert metrics is None
    
    async def test_record_query(self):
        """Test recording a query."""
        collector = MetricsCollector()
        
        await collector.start_task("test-task-3")
        await collector.record_query("test-task-3")
        await collector.record_query("test-task-3")
        
        metrics = await collector.get_task_metrics("test-task-3")
        assert metrics.total_queries == 2
    
    async def test_record_page_fetch(self):
        """Test recording a page fetch."""
        collector = MetricsCollector()
        
        await collector.start_task("test-task-4")
        await collector.record_page_fetch(
            "test-task-4",
            "example.com",
            used_tor=True,
            used_headful=False,
            is_primary_source=True,
        )
        
        metrics = await collector.get_task_metrics("test-task-4")
        assert metrics.total_pages_fetched == 1
        assert metrics.tor_requests == 1
        assert metrics.primary_sources == 1
        assert "example.com" in metrics.unique_domains
    
    async def test_record_error(self):
        """Test recording errors."""
        collector = MetricsCollector()
        
        await collector.start_task("test-task-5")
        await collector.record_error("test-task-5", "blocked.com", is_403=True)
        await collector.record_error("test-task-5", "captcha.com", is_captcha=True)
        
        metrics = await collector.get_task_metrics("test-task-5")
        assert metrics.error_403_count == 1
        assert metrics.captcha_count == 1
    
    async def test_record_fragments(self):
        """Test recording fragment extraction."""
        collector = MetricsCollector()
        
        await collector.start_task("test-task-6")
        await collector.record_fragments("test-task-6", total=20, useful=15)
        
        metrics = await collector.get_task_metrics("test-task-6")
        assert metrics.total_fragments == 20
        assert metrics.useful_fragments == 15
    
    async def test_record_claim(self):
        """Test recording claims."""
        collector = MetricsCollector()
        
        await collector.start_task("test-task-7")
        await collector.record_claim("test-task-7", has_timeline=True)
        await collector.record_claim("test-task-7", has_contradiction=True)
        await collector.record_claim("test-task-7")
        
        metrics = await collector.get_task_metrics("test-task-7")
        assert metrics.total_claims == 3
        assert metrics.claims_with_timeline == 1
        assert metrics.contradictions_found == 1
    
    async def test_finish_task(self):
        """Test finishing task and computing final metrics."""
        collector = MetricsCollector()
        
        await collector.start_task("test-task-8")
        await collector.record_page_fetch("test-task-8", "example.com")
        await collector.record_fragments("test-task-8", total=10, useful=5)
        
        result = await collector.finish_task("test-task-8")
        
        assert "computed_metrics" in result
        assert result["computed_metrics"]["harvest_rate"] == 5.0  # useful/pages
    
    async def test_global_metrics(self):
        """Test global metrics retrieval.
        
        Verifies that global metrics dictionary contains expected metric types
        with proper MetricValue structure (raw, ema_short, ema_long, samples).
        Related spec: §4.6 メトリクス定義
        """
        collector = MetricsCollector()
        
        global_metrics = collector.get_global_metrics()
        
        # Verify key metrics exist with correct structure
        for metric_name in ["harvest_rate", "tor_usage_rate", "primary_source_rate"]:
            assert metric_name in global_metrics, f"{metric_name} should be in global metrics"
            metric_data = global_metrics[metric_name]
            assert "raw" in metric_data, f"{metric_name} should have 'raw' field"
            assert "ema_short" in metric_data, f"{metric_name} should have 'ema_short' field"
            assert "samples" in metric_data, f"{metric_name} should have 'samples' field"
    
    async def test_domain_metrics(self):
        """Test domain-specific metrics.
        
        Verifies that domain metrics are properly tracked and contain
        expected keys with valid values after recording fetch and error events.
        Related spec: §4.6 メトリクス定義
        """
        collector = MetricsCollector()
        
        await collector.start_task("test-task-9")
        await collector.record_page_fetch("test-task-9", "example.com")
        await collector.record_error("test-task-9", "example.com", is_403=True)
        
        domain_metrics = collector.get_domain_metrics("example.com")
        
        # Verify fetch_count exists and has correct value
        assert "fetch_count" in domain_metrics, "fetch_count should be tracked for domain"
        assert domain_metrics["fetch_count"]["raw"] == 1.0, "fetch_count should be 1 after single fetch"
        
        # Verify error_403_rate exists and has valid EMA value
        assert "error_403_rate" in domain_metrics, "error_403_rate should be tracked for domain"
        assert 0.0 <= domain_metrics["error_403_rate"]["ema_short"] <= 1.0, "error_403_rate EMA should be in [0, 1]"
    
    async def test_export_snapshot(self):
        """Test exporting full metrics snapshot.
        
        Verifies snapshot contains all required sections for persistence/analysis:
        timestamp, global metrics, domain metrics, and active tasks list.
        """
        collector = MetricsCollector()
        
        await collector.start_task("test-task-10")
        await collector.record_page_fetch("test-task-10", "example.com")
        
        snapshot = await collector.export_snapshot()
        
        # Verify required keys exist with correct types
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
    
    async def test_all_metric_types_initialized(self):
        """Test that all metric types are initialized in collector."""
        collector = MetricsCollector()
        global_metrics = collector.get_global_metrics()
        
        for metric_type in MetricType:
            assert metric_type.value in global_metrics, f"Missing metric: {metric_type.value}"


def test_get_metrics_collector_singleton():
    """Test that get_metrics_collector returns singleton."""
    collector1 = get_metrics_collector()
    collector2 = get_metrics_collector()
    
    assert collector1 is collector2

