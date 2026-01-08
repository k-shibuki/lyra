"""
Lyra utilities module.
"""

from src.utils.config import ensure_directories, get_project_root, get_settings
from src.utils.logging import (
    CausalTrace,
    LogContext,
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
    unbind_context,
)
from src.utils.metrics import (
    MetricsCollector,
    MetricType,
    TaskMetrics,
    get_metrics_collector,
    record_error,
    record_fetch,
)
from src.utils.policy_engine import (
    PolicyEngine,
    PolicyParameter,
    get_policy_engine,
    start_policy_engine,
    stop_policy_engine,
)

__all__ = [
    # Config
    "get_settings",
    "get_project_root",
    "ensure_directories",
    # Logging
    "get_logger",
    "configure_logging",
    "bind_context",
    "unbind_context",
    "clear_context",
    "LogContext",
    "CausalTrace",
    # Metrics
    "MetricsCollector",
    "get_metrics_collector",
    "TaskMetrics",
    "MetricType",
    "record_fetch",
    "record_error",
    # Policy
    "PolicyEngine",
    "PolicyParameter",
    "get_policy_engine",
    "start_policy_engine",
    "stop_policy_engine",
]
