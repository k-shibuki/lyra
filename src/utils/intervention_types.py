"""Intervention types and result classes.

Defines enums and data classes for intervention management.
"""

from datetime import datetime
from enum import Enum
from typing import Any


class InterventionStatus(Enum):
    """Status of an intervention request."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    TIMEOUT = "timeout"
    FAILED = "failed"
    SKIPPED = "skipped"


class InterventionType(Enum):
    """Type of intervention needed."""

    CAPTCHA = "captcha"
    LOGIN_REQUIRED = "login_required"
    COOKIE_BANNER = "cookie_banner"
    CLOUDFLARE = "cloudflare"
    TURNSTILE = "turnstile"
    JS_CHALLENGE = "js_challenge"
    # Domain blocked notification (informational, no user action needed)
    DOMAIN_BLOCKED = "domain_blocked"


class InterventionResult:
    """Result of an intervention attempt."""

    def __init__(
        self,
        intervention_id: str,
        status: InterventionStatus,
        *,
        elapsed_seconds: float = 0.0,
        should_retry: bool = False,
        cooldown_until: datetime | None = None,
        skip_domain_today: bool = False,
        notes: str | None = None,
    ):
        self.intervention_id = intervention_id
        self.status = status
        self.elapsed_seconds = elapsed_seconds
        self.should_retry = should_retry
        self.cooldown_until = cooldown_until
        self.skip_domain_today = skip_domain_today
        self.notes = notes

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intervention_id": self.intervention_id,
            "status": self.status.value,
            "elapsed_seconds": self.elapsed_seconds,
            "should_retry": self.should_retry,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "skip_domain_today": self.skip_domain_today,
            "notes": self.notes,
        }

