"""Intervention types and result classes.

Defines enums and data classes for intervention management.
Includes unified message definitions for human (popup) and AI (MCP) interfaces.
"""

from dataclasses import dataclass
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


# =============================================================================
# Unified Challenge Messages (Human + AI)
# =============================================================================


@dataclass(frozen=True)
class ChallengeMessage:
    """Unified message structure for blocking challenges.

    Used for both human (popup notification) and AI (MCP response).
    """

    title: str
    description: str
    action_resolve: str
    action_skip: str

    def format_popup(self, domain: str, url: str) -> tuple[str, str]:
        """Format message for popup notification.

        Returns:
            Tuple of (title, body).
        """
        body_lines = [
            f"Domain: {domain}",
            self.description,
            "",
            f"• Resolve: {self.action_resolve}",
            f"• Skip: {self.action_skip}",
        ]
        return self.title, "\n".join(body_lines)

    def format_mcp(self, domain: str, url: str, queue_id: str | None = None) -> dict[str, Any]:
        """Format message for MCP response.

        Returns:
            Structured dict for AI consumption.
        """
        return {
            "challenge_detected": True,
            "title": self.title,
            "domain": domain,
            "url": url,
            "description": self.description,
            "actions": {
                "resolve": self.action_resolve,
                "skip": self.action_skip,
            },
            "queue_id": queue_id,
        }


# Unified messages per challenge type (English)
# NOTE: All titles use generic "Manual Action Required" to avoid exposing
# challenge type details (security/privacy per ADR-0007).
# Exception: LOGIN_REQUIRED uses explicit "Login Required" title as it's
# a user action (not a bot detection mechanism).
CHALLENGE_MESSAGES: dict[InterventionType, ChallengeMessage] = {
    InterventionType.CAPTCHA: ChallengeMessage(
        title="Lyra: Manual Action Required",
        description="A verification challenge is blocking access.",
        action_resolve="Complete verification manually, then tell AI 'resolved'",
        action_skip="Tell AI 'skip' to bypass this URL",
    ),
    InterventionType.CLOUDFLARE: ChallengeMessage(
        title="Lyra: Manual Action Required",
        description="A verification challenge is blocking access.",
        action_resolve="Complete verification manually, then tell AI 'resolved'",
        action_skip="Tell AI 'skip' to bypass this URL",
    ),
    InterventionType.TURNSTILE: ChallengeMessage(
        title="Lyra: Manual Action Required",
        description="A verification challenge is blocking access.",
        action_resolve="Complete the checkbox manually, then tell AI 'resolved'",
        action_skip="Tell AI 'skip' to bypass this URL",
    ),
    InterventionType.JS_CHALLENGE: ChallengeMessage(
        title="Lyra: Manual Action Required",
        description="Browser verification is in progress.",
        action_resolve="Wait for verification to complete, then tell AI 'resolved'",
        action_skip="Tell AI 'skip' to bypass this URL",
    ),
    InterventionType.LOGIN_REQUIRED: ChallengeMessage(
        title="Lyra: Login Required",
        description="This page requires authentication.",
        action_resolve="Log in manually, then tell AI 'resolved'",
        action_skip="Tell AI 'skip' to bypass this URL",
    ),
    InterventionType.COOKIE_BANNER: ChallengeMessage(
        title="Lyra: Manual Action Required",
        description="A cookie consent banner needs to be accepted.",
        action_resolve="Accept cookies manually, then tell AI 'resolved'",
        action_skip="Tell AI 'skip' to bypass this URL",
    ),
}

# Default message for unknown types
DEFAULT_CHALLENGE_MESSAGE = ChallengeMessage(
    title="Lyra: Manual Action Required",
    description="A blocking challenge was detected.",
    action_resolve="Resolve the challenge manually, then tell AI 'resolved'",
    action_skip="Tell AI 'skip' to bypass this URL",
)


def get_challenge_message(intervention_type: InterventionType | str) -> ChallengeMessage:
    """Get unified message for a challenge type.

    Args:
        intervention_type: Challenge type (enum or string).

    Returns:
        ChallengeMessage for the type.
    """
    if isinstance(intervention_type, str):
        try:
            intervention_type = InterventionType(intervention_type)
        except ValueError:
            return DEFAULT_CHALLENGE_MESSAGE

    return CHALLENGE_MESSAGES.get(intervention_type, DEFAULT_CHALLENGE_MESSAGE)


def format_batch_notification(pending_items: list[dict[str, Any]]) -> tuple[str, str]:
    """Format batch notification for multiple pending challenges.

    Args:
        pending_items: List of pending intervention queue items.

    Returns:
        Tuple of (title, body) for popup notification.
    """
    if not pending_items:
        return "Lyra: Auth Queue Empty", "No pending challenges."

    total = len(pending_items)

    # Group by domain (count only, no type details needed for user)
    by_domain: dict[str, int] = {}
    for item in pending_items:
        domain = item.get("domain", "unknown")
        by_domain[domain] = by_domain.get(domain, 0) + 1

    title = f"Lyra: {total} Challenge{'s' if total > 1 else ''} Pending"

    body_lines = [
        "Blocking challenges detected:",
        "",
    ]
    for domain, count in by_domain.items():
        body_lines.append(f"• {domain}: {count}")

    body_lines.extend(
        [
            "",
            "Actions:",
            "• Resolve manually, then tell AI 'resolved'",
            "• Or tell AI 'skip' to bypass",
        ]
    )

    return title, "\n".join(body_lines)


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
