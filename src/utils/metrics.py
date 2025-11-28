"""
Metrics collection and aggregation for Lancet.
Implements comprehensive metrics as defined in requirements §4.6.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class MetricType(str, Enum):
    """Types of metrics collected."""
    # Search quality metrics
    HARVEST_RATE = "harvest_rate"              # useful_fragments / fetched_pages
    NOVELTY_SCORE = "novelty_score"            # unique n-gram ratio
    DUPLICATE_RATE = "duplicate_rate"          # duplicate fragments rate
    DOMAIN_DIVERSITY = "domain_diversity"       # unique domains / total sources
    
    # Exposure/avoidance metrics
    TOR_USAGE_RATE = "tor_usage_rate"          # tor requests / total requests
    HEADFUL_RATE = "headful_rate"              # headful requests / total browser requests
    REFERER_MATCH_RATE = "referer_match_rate"  # proper referer / total requests
    CACHE_304_RATE = "cache_304_rate"          # 304 responses / revisits
    CAPTCHA_RATE = "captcha_rate"              # captcha encounters / total requests
    HTTP_ERROR_403_RATE = "http_error_403_rate"  # 403 responses / total requests
    HTTP_ERROR_429_RATE = "http_error_429_rate"  # 429 responses / total requests
    
    # OSINT quality metrics
    PRIMARY_SOURCE_RATE = "primary_source_rate"   # primary sources / total sources
    CITATION_LOOP_RATE = "citation_loop_rate"     # loops detected / total citations
    NARRATIVE_DIVERSITY = "narrative_diversity"   # narrative clusters diversity
    CONTRADICTION_RATE = "contradiction_rate"     # contradictions found / claims
    TIMELINE_COVERAGE = "timeline_coverage"       # claims with timeline / total claims
    AGGREGATOR_RATE = "aggregator_rate"           # aggregator sources / total sources
    
    # System performance metrics
    LLM_TIME_RATIO = "llm_time_ratio"           # LLM time / total time
    GPU_UTILIZATION = "gpu_utilization"         # GPU slot usage
    BROWSER_UTILIZATION = "browser_utilization" # Browser slot usage


@dataclass
class MetricValue:
    """A single metric value with timestamp and EMA calculation."""
    raw_value: float
    ema_short: float  # 1h equivalent (alpha=0.1)
    ema_long: float   # 24h equivalent (alpha=0.01)
    sample_count: int
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def update(self, new_value: float, alpha_short: float = 0.1, alpha_long: float = 0.01) -> None:
        """Update metric with new value using EMA.
        
        Args:
            new_value: New raw value to incorporate.
            alpha_short: Short-term EMA alpha (default 0.1 for ~1h).
            alpha_long: Long-term EMA alpha (default 0.01 for ~24h).
        """
        self.raw_value = new_value
        self.ema_short = alpha_short * new_value + (1 - alpha_short) * self.ema_short
        self.ema_long = alpha_long * new_value + (1 - alpha_long) * self.ema_long
        self.sample_count += 1
        self.last_updated = datetime.now(timezone.utc)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "raw": round(self.raw_value, 4),
            "ema_short": round(self.ema_short, 4),
            "ema_long": round(self.ema_long, 4),
            "samples": self.sample_count,
            "updated_at": self.last_updated.isoformat(),
        }


@dataclass
class TaskMetrics:
    """Metrics aggregated for a single task."""
    task_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Counters
    total_queries: int = 0
    total_pages_fetched: int = 0
    total_fragments: int = 0
    useful_fragments: int = 0
    
    # Request counters
    total_requests: int = 0
    tor_requests: int = 0
    headful_requests: int = 0
    cache_304_hits: int = 0
    revisit_count: int = 0
    referer_matched: int = 0
    
    # Error counters
    captcha_count: int = 0
    error_403_count: int = 0
    error_429_count: int = 0
    
    # Source quality
    primary_sources: int = 0
    total_sources: int = 0
    unique_domains: set[str] = field(default_factory=set)
    
    # OSINT quality
    citation_loops_detected: int = 0
    total_citations: int = 0
    contradictions_found: int = 0
    total_claims: int = 0
    claims_with_timeline: int = 0
    aggregator_sources: int = 0
    
    # Time tracking
    llm_time_ms: int = 0
    total_time_ms: int = 0
    
    def compute_metrics(self) -> dict[str, float]:
        """Compute all derived metrics.
        
        Returns:
            Dictionary of metric name to value.
        """
        metrics = {}
        
        # Harvest rate
        if self.total_pages_fetched > 0:
            metrics[MetricType.HARVEST_RATE.value] = self.useful_fragments / self.total_pages_fetched
        else:
            metrics[MetricType.HARVEST_RATE.value] = 0.0
        
        # Duplicate rate (complement of useful fragments ratio)
        if self.total_fragments > 0:
            metrics[MetricType.DUPLICATE_RATE.value] = 1.0 - (self.useful_fragments / self.total_fragments)
        else:
            metrics[MetricType.DUPLICATE_RATE.value] = 0.0
        
        # Domain diversity
        if self.total_sources > 0:
            metrics[MetricType.DOMAIN_DIVERSITY.value] = len(self.unique_domains) / self.total_sources
        else:
            metrics[MetricType.DOMAIN_DIVERSITY.value] = 0.0
        
        # Tor usage rate
        if self.total_requests > 0:
            metrics[MetricType.TOR_USAGE_RATE.value] = self.tor_requests / self.total_requests
        else:
            metrics[MetricType.TOR_USAGE_RATE.value] = 0.0
        
        # Headful rate
        if self.total_requests > 0:
            metrics[MetricType.HEADFUL_RATE.value] = self.headful_requests / self.total_requests
        else:
            metrics[MetricType.HEADFUL_RATE.value] = 0.0
        
        # Referer match rate
        if self.total_requests > 0:
            metrics[MetricType.REFERER_MATCH_RATE.value] = self.referer_matched / self.total_requests
        else:
            metrics[MetricType.REFERER_MATCH_RATE.value] = 0.0
        
        # Cache 304 rate
        if self.revisit_count > 0:
            metrics[MetricType.CACHE_304_RATE.value] = self.cache_304_hits / self.revisit_count
        else:
            metrics[MetricType.CACHE_304_RATE.value] = 0.0
        
        # Error rates
        if self.total_requests > 0:
            metrics[MetricType.CAPTCHA_RATE.value] = self.captcha_count / self.total_requests
            metrics[MetricType.HTTP_ERROR_403_RATE.value] = self.error_403_count / self.total_requests
            metrics[MetricType.HTTP_ERROR_429_RATE.value] = self.error_429_count / self.total_requests
        else:
            metrics[MetricType.CAPTCHA_RATE.value] = 0.0
            metrics[MetricType.HTTP_ERROR_403_RATE.value] = 0.0
            metrics[MetricType.HTTP_ERROR_429_RATE.value] = 0.0
        
        # Primary source rate
        if self.total_sources > 0:
            metrics[MetricType.PRIMARY_SOURCE_RATE.value] = self.primary_sources / self.total_sources
        else:
            metrics[MetricType.PRIMARY_SOURCE_RATE.value] = 0.0
        
        # Citation loop rate
        if self.total_citations > 0:
            metrics[MetricType.CITATION_LOOP_RATE.value] = self.citation_loops_detected / self.total_citations
        else:
            metrics[MetricType.CITATION_LOOP_RATE.value] = 0.0
        
        # Contradiction rate
        if self.total_claims > 0:
            metrics[MetricType.CONTRADICTION_RATE.value] = self.contradictions_found / self.total_claims
        else:
            metrics[MetricType.CONTRADICTION_RATE.value] = 0.0
        
        # Timeline coverage
        if self.total_claims > 0:
            metrics[MetricType.TIMELINE_COVERAGE.value] = self.claims_with_timeline / self.total_claims
        else:
            metrics[MetricType.TIMELINE_COVERAGE.value] = 0.0
        
        # Aggregator rate
        if self.total_sources > 0:
            metrics[MetricType.AGGREGATOR_RATE.value] = self.aggregator_sources / self.total_sources
        else:
            metrics[MetricType.AGGREGATOR_RATE.value] = 0.0
        
        # LLM time ratio
        if self.total_time_ms > 0:
            metrics[MetricType.LLM_TIME_RATIO.value] = self.llm_time_ms / self.total_time_ms
        else:
            metrics[MetricType.LLM_TIME_RATIO.value] = 0.0
        
        return metrics
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "task_id": self.task_id,
            "started_at": self.started_at.isoformat(),
            "counters": {
                "queries": self.total_queries,
                "pages_fetched": self.total_pages_fetched,
                "fragments": self.total_fragments,
                "useful_fragments": self.useful_fragments,
                "requests": self.total_requests,
                "tor_requests": self.tor_requests,
                "headful_requests": self.headful_requests,
                "cache_304_hits": self.cache_304_hits,
                "revisits": self.revisit_count,
                "referer_matched": self.referer_matched,
            },
            "errors": {
                "captcha": self.captcha_count,
                "http_403": self.error_403_count,
                "http_429": self.error_429_count,
            },
            "quality": {
                "primary_sources": self.primary_sources,
                "total_sources": self.total_sources,
                "unique_domains": len(self.unique_domains),
                "citation_loops": self.citation_loops_detected,
                "total_citations": self.total_citations,
                "contradictions": self.contradictions_found,
                "total_claims": self.total_claims,
                "claims_with_timeline": self.claims_with_timeline,
                "aggregator_sources": self.aggregator_sources,
            },
            "timing": {
                "llm_time_ms": self.llm_time_ms,
                "total_time_ms": self.total_time_ms,
            },
            "computed_metrics": self.compute_metrics(),
        }


class MetricsCollector:
    """Central metrics collector for the system.
    
    Collects metrics at multiple levels:
    - Global system metrics (EMA over all operations)
    - Per-task metrics
    - Per-domain metrics
    - Per-engine metrics
    """
    
    def __init__(self):
        """Initialize metrics collector."""
        self._settings = get_settings()
        self._global_metrics: dict[str, MetricValue] = {}
        self._task_metrics: dict[str, TaskMetrics] = {}
        self._domain_metrics: dict[str, dict[str, MetricValue]] = {}
        self._engine_metrics: dict[str, dict[str, MetricValue]] = {}
        self._lock = asyncio.Lock()
        
        # Initialize global metrics
        for metric_type in MetricType:
            self._global_metrics[metric_type.value] = MetricValue(
                raw_value=0.0,
                ema_short=0.0,
                ema_long=0.0,
                sample_count=0,
            )
    
    # =========================================================
    # Task-level metric recording
    # =========================================================
    
    async def start_task(self, task_id: str) -> TaskMetrics:
        """Start tracking metrics for a task.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            TaskMetrics instance.
        """
        async with self._lock:
            metrics = TaskMetrics(task_id=task_id)
            self._task_metrics[task_id] = metrics
            logger.info("Task metrics started", task_id=task_id)
            return metrics
    
    async def get_task_metrics(self, task_id: str) -> TaskMetrics | None:
        """Get metrics for a task.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            TaskMetrics or None if not found.
        """
        return self._task_metrics.get(task_id)
    
    async def finish_task(self, task_id: str) -> dict[str, Any]:
        """Finish task and compute final metrics.
        
        Updates global EMA metrics with task results.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            Final task metrics dictionary.
        """
        async with self._lock:
            task_metrics = self._task_metrics.get(task_id)
            if task_metrics is None:
                return {}
            
            # Compute task metrics
            computed = task_metrics.compute_metrics()
            
            # Update global EMAs
            alpha_short = self._settings.metrics.ema_short_alpha
            alpha_long = self._settings.metrics.ema_long_alpha
            
            for metric_name, value in computed.items():
                if metric_name in self._global_metrics:
                    self._global_metrics[metric_name].update(
                        value, alpha_short, alpha_long
                    )
            
            result = task_metrics.to_dict()
            logger.info(
                "Task metrics finished",
                task_id=task_id,
                harvest_rate=computed.get(MetricType.HARVEST_RATE.value, 0),
                primary_source_rate=computed.get(MetricType.PRIMARY_SOURCE_RATE.value, 0),
            )
            
            return result
    
    # =========================================================
    # Event recording methods
    # =========================================================
    
    async def record_query(self, task_id: str) -> None:
        """Record a search query execution."""
        if task_id in self._task_metrics:
            self._task_metrics[task_id].total_queries += 1
    
    async def record_page_fetch(
        self,
        task_id: str,
        domain: str,
        *,
        used_tor: bool = False,
        used_headful: bool = False,
        had_referer: bool = False,
        was_revisit: bool = False,
        got_304: bool = False,
        is_primary_source: bool = False,
        is_aggregator: bool = False,
    ) -> None:
        """Record a page fetch event.
        
        Args:
            task_id: Task identifier.
            domain: Domain of fetched page.
            used_tor: Whether Tor was used.
            used_headful: Whether headful browser was used.
            had_referer: Whether proper Referer header was set.
            was_revisit: Whether this was a revisit.
            got_304: Whether 304 Not Modified was received.
            is_primary_source: Whether source is primary (government, academic, etc.).
            is_aggregator: Whether source is an aggregator site.
        """
        if task_id not in self._task_metrics:
            return
        
        metrics = self._task_metrics[task_id]
        metrics.total_pages_fetched += 1
        metrics.total_requests += 1
        metrics.total_sources += 1
        metrics.unique_domains.add(domain)
        
        if used_tor:
            metrics.tor_requests += 1
        if used_headful:
            metrics.headful_requests += 1
        if had_referer:
            metrics.referer_matched += 1
        if was_revisit:
            metrics.revisit_count += 1
            if got_304:
                metrics.cache_304_hits += 1
        if is_primary_source:
            metrics.primary_sources += 1
        if is_aggregator:
            metrics.aggregator_sources += 1
        
        # Update domain metrics
        await self._update_domain_metric(domain, "fetch_count", 1.0, increment=True)
        if used_tor:
            await self._update_domain_metric(domain, "tor_usage", 1.0)
    
    async def record_error(
        self,
        task_id: str,
        domain: str,
        *,
        is_captcha: bool = False,
        is_403: bool = False,
        is_429: bool = False,
    ) -> None:
        """Record an error event.
        
        Args:
            task_id: Task identifier.
            domain: Domain where error occurred.
            is_captcha: Whether error was CAPTCHA.
            is_403: Whether error was 403 Forbidden.
            is_429: Whether error was 429 Too Many Requests.
        """
        if task_id not in self._task_metrics:
            return
        
        metrics = self._task_metrics[task_id]
        
        if is_captcha:
            metrics.captcha_count += 1
            await self._update_domain_metric(domain, "captcha_rate", 1.0)
        if is_403:
            metrics.error_403_count += 1
            await self._update_domain_metric(domain, "error_403_rate", 1.0)
        if is_429:
            metrics.error_429_count += 1
            await self._update_domain_metric(domain, "error_429_rate", 1.0)
    
    async def record_fragments(
        self,
        task_id: str,
        total: int,
        useful: int,
    ) -> None:
        """Record fragment extraction results.
        
        Args:
            task_id: Task identifier.
            total: Total fragments extracted.
            useful: Useful/relevant fragments.
        """
        if task_id in self._task_metrics:
            self._task_metrics[task_id].total_fragments += total
            self._task_metrics[task_id].useful_fragments += useful
    
    async def record_claim(
        self,
        task_id: str,
        *,
        has_timeline: bool = False,
        has_contradiction: bool = False,
    ) -> None:
        """Record a claim extraction.
        
        Args:
            task_id: Task identifier.
            has_timeline: Whether claim has timeline info.
            has_contradiction: Whether contradiction was found.
        """
        if task_id not in self._task_metrics:
            return
        
        metrics = self._task_metrics[task_id]
        metrics.total_claims += 1
        
        if has_timeline:
            metrics.claims_with_timeline += 1
        if has_contradiction:
            metrics.contradictions_found += 1
    
    async def record_citation(
        self,
        task_id: str,
        *,
        is_loop: bool = False,
    ) -> None:
        """Record a citation.
        
        Args:
            task_id: Task identifier.
            is_loop: Whether citation loop was detected.
        """
        if task_id not in self._task_metrics:
            return
        
        metrics = self._task_metrics[task_id]
        metrics.total_citations += 1
        
        if is_loop:
            metrics.citation_loops_detected += 1
    
    async def record_llm_time(self, task_id: str, time_ms: int) -> None:
        """Record LLM processing time.
        
        Args:
            task_id: Task identifier.
            time_ms: LLM processing time in milliseconds.
        """
        if task_id in self._task_metrics:
            self._task_metrics[task_id].llm_time_ms += time_ms
    
    async def record_total_time(self, task_id: str, time_ms: int) -> None:
        """Record total processing time.
        
        Args:
            task_id: Task identifier.
            time_ms: Total processing time in milliseconds.
        """
        if task_id in self._task_metrics:
            self._task_metrics[task_id].total_time_ms += time_ms
    
    async def record_engine_result(
        self,
        engine: str,
        success: bool,
        latency_ms: float | None = None,
    ) -> None:
        """Record search engine result.
        
        Args:
            engine: Engine name.
            success: Whether query succeeded.
            latency_ms: Query latency in milliseconds.
        """
        await self._update_engine_metric(
            engine, "success_rate", 1.0 if success else 0.0
        )
        if latency_ms is not None:
            await self._update_engine_metric(engine, "latency_ms", latency_ms)
    
    # =========================================================
    # Domain and engine metric helpers
    # =========================================================
    
    async def _update_domain_metric(
        self,
        domain: str,
        metric_name: str,
        value: float,
        increment: bool = False,
    ) -> None:
        """Update a domain-specific metric.
        
        Args:
            domain: Domain name.
            metric_name: Metric name.
            value: Value to update with.
            increment: If True, increment raw value instead of EMA update.
        """
        async with self._lock:
            if domain not in self._domain_metrics:
                self._domain_metrics[domain] = {}
            
            if metric_name not in self._domain_metrics[domain]:
                self._domain_metrics[domain][metric_name] = MetricValue(
                    raw_value=0.0,
                    ema_short=0.0,
                    ema_long=0.0,
                    sample_count=0,
                )
            
            metric = self._domain_metrics[domain][metric_name]
            if increment:
                metric.raw_value += value
                metric.sample_count += 1
                metric.last_updated = datetime.now(timezone.utc)
            else:
                metric.update(value)
    
    async def _update_engine_metric(
        self,
        engine: str,
        metric_name: str,
        value: float,
    ) -> None:
        """Update an engine-specific metric.
        
        Args:
            engine: Engine name.
            metric_name: Metric name.
            value: Value to update with.
        """
        async with self._lock:
            if engine not in self._engine_metrics:
                self._engine_metrics[engine] = {}
            
            if metric_name not in self._engine_metrics[engine]:
                self._engine_metrics[engine][metric_name] = MetricValue(
                    raw_value=0.0,
                    ema_short=0.5,  # Start with neutral
                    ema_long=0.5,
                    sample_count=0,
                )
            
            self._engine_metrics[engine][metric_name].update(value)
    
    # =========================================================
    # Metric retrieval
    # =========================================================
    
    def get_global_metrics(self) -> dict[str, dict[str, Any]]:
        """Get all global metrics.
        
        Returns:
            Dictionary of metric name to value info.
        """
        return {
            name: value.to_dict()
            for name, value in self._global_metrics.items()
        }
    
    def get_domain_metrics(self, domain: str) -> dict[str, dict[str, Any]]:
        """Get metrics for a specific domain.
        
        Args:
            domain: Domain name.
            
        Returns:
            Dictionary of metric name to value info.
        """
        if domain not in self._domain_metrics:
            return {}
        
        return {
            name: value.to_dict()
            for name, value in self._domain_metrics[domain].items()
        }
    
    def get_engine_metrics(self, engine: str) -> dict[str, dict[str, Any]]:
        """Get metrics for a specific engine.
        
        Args:
            engine: Engine name.
            
        Returns:
            Dictionary of metric name to value info.
        """
        if engine not in self._engine_metrics:
            return {}
        
        return {
            name: value.to_dict()
            for name, value in self._engine_metrics[engine].items()
        }
    
    def get_all_domain_metrics(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Get metrics for all domains.
        
        Returns:
            Nested dictionary of domain -> metric -> value.
        """
        return {
            domain: {
                name: value.to_dict()
                for name, value in metrics.items()
            }
            for domain, metrics in self._domain_metrics.items()
        }
    
    def get_all_engine_metrics(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Get metrics for all engines.
        
        Returns:
            Nested dictionary of engine -> metric -> value.
        """
        return {
            engine: {
                name: value.to_dict()
                for name, value in metrics.items()
            }
            for engine, metrics in self._engine_metrics.items()
        }
    
    async def export_snapshot(self) -> dict[str, Any]:
        """Export complete metrics snapshot.
        
        Returns:
            Complete metrics state for persistence/analysis.
        """
        async with self._lock:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "global": self.get_global_metrics(),
                "domains": self.get_all_domain_metrics(),
                "engines": self.get_all_engine_metrics(),
                "active_tasks": list(self._task_metrics.keys()),
            }


# Global collector instance
_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance.
    
    Returns:
        MetricsCollector instance.
    """
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector


# Convenience functions for common operations
async def record_fetch(
    task_id: str,
    domain: str,
    **kwargs: Any,
) -> None:
    """Convenience function to record a fetch event."""
    collector = get_metrics_collector()
    await collector.record_page_fetch(task_id, domain, **kwargs)


async def record_error(
    task_id: str,
    domain: str,
    **kwargs: Any,
) -> None:
    """Convenience function to record an error event."""
    collector = get_metrics_collector()
    await collector.record_error(task_id, domain, **kwargs)








