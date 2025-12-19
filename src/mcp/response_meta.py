"""
MCP Response Metadata Generator.

Implements L5 (MCP Response Metadata) per §4.4.1:
- Adds _lancet_meta to all MCP responses
- Includes source trust level and verification status
- Provides security warnings from L2/L4 detection

This enables Cursor AI to make informed decisions about source reliability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class VerificationStatus(str, Enum):
    """Verification status for claims/sources (§4.4.1 L6)."""

    PENDING = "pending"      # Not yet verified
    VERIFIED = "verified"    # Corroborated by independent sources
    REJECTED = "rejected"    # Contradiction detected or dangerous pattern


@dataclass
class VerificationDetails:
    """Details about verification status (§4.4.1 L5)."""

    independent_sources: int = 0
    corroborating_claims: list[str] = field(default_factory=list)
    contradicting_claims: list[str] = field(default_factory=list)
    nli_scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "independent_sources": self.independent_sources,
            "corroborating_claims": self.corroborating_claims,
            "contradicting_claims": self.contradicting_claims,
            "nli_scores": self.nli_scores,
        }


@dataclass
class SecurityWarning:
    """Security warning from L2/L4 detection."""

    type: str  # "dangerous_pattern", "external_url", "suspicious_ip", "prompt_leakage"
    message: str
    severity: str = "warning"  # "info", "warning", "critical"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class LancetMeta:
    """Metadata attached to MCP responses (§4.4.1 L5).

    This provides Cursor AI with information to assess trustworthiness
    of the data returned by Lancet.
    """

    # Timestamp of response generation
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    # Security warnings from L2/L4
    security_warnings: list[SecurityWarning] = field(default_factory=list)

    # Blocked domains encountered during this operation
    blocked_domains: list[str] = field(default_factory=list)

    # Unverified domains used (for Cursor AI awareness)
    unverified_domains: list[str] = field(default_factory=list)

    # Overall data quality indicator
    data_quality: str = "normal"  # "normal", "degraded", "limited"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "timestamp": self.timestamp,
            "data_quality": self.data_quality,
        }

        if self.security_warnings:
            result["security_warnings"] = [w.to_dict() for w in self.security_warnings]

        if self.blocked_domains:
            result["blocked_domains"] = self.blocked_domains

        if self.unverified_domains:
            result["unverified_domains"] = self.unverified_domains

        return result


@dataclass
class ClaimMeta:
    """Per-claim metadata for verification status (§4.4.1 L5/L6)."""

    claim_id: str
    source_trust_level: str  # TrustLevel value
    verification_status: VerificationStatus = VerificationStatus.PENDING
    verification_details: VerificationDetails | None = None
    source_domain: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "claim_id": self.claim_id,
            "source_trust_level": self.source_trust_level,
            "verification_status": self.verification_status.value,
        }

        if self.verification_details:
            result["verification_details"] = self.verification_details.to_dict()

        if self.source_domain:
            result["source_domain"] = self.source_domain

        return result


class ResponseMetaBuilder:
    """Builder for constructing _lancet_meta for MCP responses."""

    def __init__(self) -> None:
        """Initialize builder with empty metadata."""
        self._meta = LancetMeta()
        self._claim_metas: list[ClaimMeta] = []

    def add_security_warning(
        self,
        warning_type: str,
        message: str,
        severity: str = "warning",
    ) -> ResponseMetaBuilder:
        """Add a security warning.

        Args:
            warning_type: Type of warning (dangerous_pattern, external_url, etc.)
            message: Human-readable warning message
            severity: Severity level (info, warning, critical)

        Returns:
            Self for method chaining.
        """
        self._meta.security_warnings.append(
            SecurityWarning(type=warning_type, message=message, severity=severity)
        )
        return self

    def add_blocked_domain(self, domain: str) -> ResponseMetaBuilder:
        """Add a blocked domain.

        Args:
            domain: Domain that was blocked.

        Returns:
            Self for method chaining.
        """
        if domain not in self._meta.blocked_domains:
            self._meta.blocked_domains.append(domain)
        return self

    def add_unverified_domain(self, domain: str) -> ResponseMetaBuilder:
        """Add an unverified domain.

        Args:
            domain: Domain that is unverified.

        Returns:
            Self for method chaining.
        """
        if domain not in self._meta.unverified_domains:
            self._meta.unverified_domains.append(domain)
        return self

    def set_data_quality(self, quality: str) -> ResponseMetaBuilder:
        """Set overall data quality indicator.

        Args:
            quality: Quality level (normal, degraded, limited)

        Returns:
            Self for method chaining.
        """
        self._meta.data_quality = quality
        return self

    def add_claim_meta(self, claim_meta: ClaimMeta) -> ResponseMetaBuilder:
        """Add per-claim metadata.

        Args:
            claim_meta: Claim metadata to add.

        Returns:
            Self for method chaining.
        """
        self._claim_metas.append(claim_meta)
        return self

    def build(self) -> dict[str, Any]:
        """Build the _lancet_meta dictionary.

        Returns:
            Dictionary suitable for inclusion in MCP response.
        """
        result = self._meta.to_dict()

        if self._claim_metas:
            result["claims"] = [cm.to_dict() for cm in self._claim_metas]

        return result


def create_response_meta() -> ResponseMetaBuilder:
    """Create a new ResponseMetaBuilder.

    Returns:
        New builder instance.
    """
    return ResponseMetaBuilder()


def attach_meta(response: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """Attach _lancet_meta to a response dictionary.

    Args:
        response: Original response dictionary.
        meta: Metadata to attach.

    Returns:
        Response with _lancet_meta attached.
    """
    response["_lancet_meta"] = meta
    return response


def create_minimal_meta() -> dict[str, Any]:
    """Create minimal metadata for simple responses.

    Returns:
        Minimal _lancet_meta dictionary.
    """
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "data_quality": "normal",
    }

