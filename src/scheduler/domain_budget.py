"""
Domain Daily Budget Manager for rate limiting.

Per §4.3: "時間帯・日次の予算上限を設定" for IP block prevention.
Implements per-domain daily request and page limits with automatic daily reset.

References:
- §4.3 (Stealth/Anti-detection policies)
- Problem 11 in docs/O6_ADDITIONAL_ISSUES.md
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Any

from src.utils.domain_policy import get_domain_policy_manager
from src.utils.logging import get_logger
from src.utils.schemas import DomainBudgetCheckResult, DomainDailyBudget

logger = get_logger(__name__)


# Default daily budget limits (used when not specified in domain policy)
DEFAULT_MAX_REQUESTS_PER_DAY = 200
DEFAULT_MAX_PAGES_PER_DAY = 100


class DomainDailyBudgetManager:
    """
    Manages daily request and page budgets per domain.
    
    Features:
    - Per-domain daily request and page limits
    - Automatic counter reset on date change
    - Thread-safe operations
    - Fail-open on errors (allows requests if budget check fails)
    
    Usage:
        manager = get_domain_budget_manager()
        
        # Check if request is allowed
        result = manager.can_request_to_domain("example.com")
        if result.allowed:
            # Make request
            manager.record_domain_request("example.com", is_page=True)
        else:
            logger.warning("Budget exceeded", reason=result.reason)
    """

    _instance: DomainDailyBudgetManager | None = None
    _lock = threading.Lock()

    def __init__(self):
        """Initialize domain daily budget manager."""
        self._budgets: dict[str, DomainDailyBudget] = {}
        self._data_lock = threading.RLock()
        self._current_date: str = self._get_today()

        logger.info(
            "Domain daily budget manager initialized",
            default_max_requests=DEFAULT_MAX_REQUESTS_PER_DAY,
            default_max_pages=DEFAULT_MAX_PAGES_PER_DAY,
        )

    @classmethod
    def get_instance(cls) -> DomainDailyBudgetManager:
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def _get_today(self) -> str:
        """Get current date in YYYY-MM-DD format."""
        return date.today().isoformat()

    def _check_date_reset(self) -> None:
        """Check if date has changed and reset counters if needed."""
        today = self._get_today()

        if today != self._current_date:
            logger.info(
                "Date changed, resetting domain budgets",
                old_date=self._current_date,
                new_date=today,
                domains_reset=len(self._budgets),
            )

            # Reset all budgets (they'll be recreated on next access)
            with self._data_lock:
                self._budgets.clear()
                self._current_date = today

    def _get_domain_limits(self, domain: str) -> tuple[int, int]:
        """
        Get daily limits for a domain from policy.
        
        Args:
            domain: Domain name.
            
        Returns:
            Tuple of (max_requests_per_day, max_pages_per_day).
        """
        try:
            policy_manager = get_domain_policy_manager()
            policy = policy_manager.get_policy(domain)

            # Use domain policy limits if available, otherwise defaults
            max_requests = getattr(policy, "max_requests_per_day", None)
            max_pages = getattr(policy, "max_pages_per_day", None)

            if max_requests is None:
                max_requests = DEFAULT_MAX_REQUESTS_PER_DAY
            if max_pages is None:
                max_pages = DEFAULT_MAX_PAGES_PER_DAY

            return max_requests, max_pages

        except Exception as e:
            logger.warning(
                "Failed to get domain limits, using defaults",
                domain=domain,
                error=str(e),
            )
            return DEFAULT_MAX_REQUESTS_PER_DAY, DEFAULT_MAX_PAGES_PER_DAY

    def _get_or_create_budget(self, domain: str) -> DomainDailyBudget:
        """
        Get or create budget for a domain.
        
        Args:
            domain: Domain name.
            
        Returns:
            DomainDailyBudget instance.
        """
        domain = domain.lower().strip()

        # Check date reset first
        self._check_date_reset()

        with self._data_lock:
            if domain not in self._budgets:
                max_requests, max_pages = self._get_domain_limits(domain)

                self._budgets[domain] = DomainDailyBudget(
                    domain=domain,
                    requests_today=0,
                    pages_today=0,
                    max_requests_per_day=max_requests,
                    max_pages_per_day=max_pages,
                    date=self._current_date,
                )

                logger.debug(
                    "Created domain budget",
                    domain=domain,
                    max_requests=max_requests,
                    max_pages=max_pages,
                )

            return self._budgets[domain]

    def can_request_to_domain(self, domain: str) -> DomainBudgetCheckResult:
        """
        Check if a request to domain is allowed within budget.
        
        Implements fail-open: if an error occurs during check,
        the request is allowed to prevent blocking due to bugs.
        
        Args:
            domain: Domain name.
            
        Returns:
            DomainBudgetCheckResult with allowed status and details.
        """
        try:
            budget = self._get_or_create_budget(domain)

            # Check if request limit exceeded (0 = unlimited)
            if budget.max_requests_per_day > 0:
                if budget.requests_today >= budget.max_requests_per_day:
                    logger.debug(
                        "Domain request budget exceeded",
                        domain=domain,
                        requests_today=budget.requests_today,
                        max_requests=budget.max_requests_per_day,
                    )
                    return DomainBudgetCheckResult(
                        allowed=False,
                        reason=f"request_limit_exceeded: {budget.requests_today}/{budget.max_requests_per_day}",
                        requests_remaining=0,
                        pages_remaining=budget.pages_remaining,
                    )

            # Check if page limit exceeded (0 = unlimited)
            if budget.max_pages_per_day > 0:
                if budget.pages_today >= budget.max_pages_per_day:
                    logger.debug(
                        "Domain page budget exceeded",
                        domain=domain,
                        pages_today=budget.pages_today,
                        max_pages=budget.max_pages_per_day,
                    )
                    return DomainBudgetCheckResult(
                        allowed=False,
                        reason=f"page_limit_exceeded: {budget.pages_today}/{budget.max_pages_per_day}",
                        requests_remaining=budget.requests_remaining,
                        pages_remaining=0,
                    )

            # Request allowed
            return DomainBudgetCheckResult(
                allowed=True,
                reason=None,
                requests_remaining=budget.requests_remaining,
                pages_remaining=budget.pages_remaining,
            )

        except Exception as e:
            # Fail-open: allow request on error
            logger.error(
                "Error checking domain budget, allowing request (fail-open)",
                domain=domain,
                error=str(e),
            )
            return DomainBudgetCheckResult(
                allowed=True,
                reason=f"check_error_failopen: {str(e)}",
                requests_remaining=DEFAULT_MAX_REQUESTS_PER_DAY,
                pages_remaining=DEFAULT_MAX_PAGES_PER_DAY,
            )

    def record_domain_request(self, domain: str, is_page: bool = False) -> None:
        """
        Record a request to a domain.
        
        Args:
            domain: Domain name.
            is_page: Whether this request is a page fetch (vs. API/resource).
        """
        try:
            budget = self._get_or_create_budget(domain)

            with self._data_lock:
                budget.requests_today += 1

                if is_page:
                    budget.pages_today += 1

                logger.debug(
                    "Domain request recorded",
                    domain=domain,
                    requests_today=budget.requests_today,
                    pages_today=budget.pages_today,
                    is_page=is_page,
                )

        except Exception as e:
            logger.error(
                "Error recording domain request",
                domain=domain,
                error=str(e),
            )

    def get_domain_budget(self, domain: str) -> DomainDailyBudget:
        """
        Get current budget state for a domain.
        
        Args:
            domain: Domain name.
            
        Returns:
            DomainDailyBudget instance.
        """
        return self._get_or_create_budget(domain)

    def get_all_budgets(self) -> dict[str, DomainDailyBudget]:
        """
        Get all domain budgets.
        
        Returns:
            Dictionary of domain -> DomainDailyBudget.
        """
        self._check_date_reset()

        with self._data_lock:
            return dict(self._budgets)

    def get_stats(self) -> dict[str, Any]:
        """
        Get budget manager statistics.
        
        Returns:
            Dictionary with stats.
        """
        self._check_date_reset()

        with self._data_lock:
            total_requests = sum(b.requests_today for b in self._budgets.values())
            total_pages = sum(b.pages_today for b in self._budgets.values())
            exceeded_domains = [
                domain
                for domain, budget in self._budgets.items()
                if (budget.max_requests_per_day > 0 and budget.requests_today >= budget.max_requests_per_day)
                or (budget.max_pages_per_day > 0 and budget.pages_today >= budget.max_pages_per_day)
            ]

            return {
                "date": self._current_date,
                "domains_tracked": len(self._budgets),
                "total_requests_today": total_requests,
                "total_pages_today": total_pages,
                "exceeded_domains": exceeded_domains,
            }

    def clear_budgets(self) -> None:
        """Clear all budgets (for testing)."""
        with self._data_lock:
            self._budgets.clear()
            logger.debug("Domain budgets cleared")


# =============================================================================
# Module-level singleton access
# =============================================================================

_manager_instance: DomainDailyBudgetManager | None = None
_manager_lock = threading.Lock()


def get_domain_budget_manager() -> DomainDailyBudgetManager:
    """
    Get the singleton DomainDailyBudgetManager instance.
    
    Usage:
        manager = get_domain_budget_manager()
        result = manager.can_request_to_domain("example.com")
    """
    global _manager_instance

    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = DomainDailyBudgetManager()

    return _manager_instance


def reset_domain_budget_manager() -> None:
    """Reset the singleton instance (for testing)."""
    global _manager_instance

    with _manager_lock:
        _manager_instance = None
        DomainDailyBudgetManager.reset_instance()


# =============================================================================
# Convenience functions
# =============================================================================


def can_request_to_domain(domain: str) -> DomainBudgetCheckResult:
    """Check if request to domain is allowed (convenience function)."""
    return get_domain_budget_manager().can_request_to_domain(domain)


def record_domain_request(domain: str, is_page: bool = False) -> None:
    """Record a request to domain (convenience function)."""
    get_domain_budget_manager().record_domain_request(domain, is_page)


def get_domain_daily_budget(domain: str) -> DomainDailyBudget:
    """Get budget for domain (convenience function)."""
    return get_domain_budget_manager().get_domain_budget(domain)
