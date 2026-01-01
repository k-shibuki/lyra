"""Fetch result data class for URL fetcher."""

from datetime import datetime
from typing import Any


class FetchResult:
    """Result of a fetch operation.

    Includes detailed authentication information, IPv6 connection information,
    and archive/Wayback fallback information.
    """

    def __init__(
        self,
        ok: bool,
        url: str,
        *,
        status: int | None = None,
        headers: dict[str, str] | None = None,
        html_path: str | None = None,
        pdf_path: str | None = None,
        warc_path: str | None = None,
        screenshot_path: str | None = None,
        content_hash: str | None = None,
        reason: str | None = None,
        method: str = "http_client",
        from_cache: bool = False,
        etag: str | None = None,
        last_modified: str | None = None,
        # Authentication queue (semi-automatic operation)
        auth_queued: bool = False,
        queue_id: str | None = None,
        # Detailed authentication information
        auth_type: str | None = None,  # cloudflare/captcha/turnstile/hcaptcha/login
        estimated_effort: str | None = None,  # low/medium/high
        # IPv6 connection information
        ip_family: str | None = None,  # ipv4/ipv6/unknown
        ip_switched: bool = False,  # True if we switched from primary family
        # Wayback/archive fallback information
        is_archived: bool = False,  # True if content came from Wayback
        archive_date: datetime | None = None,  # Date of the archive snapshot
        archive_url: str | None = None,  # Original Wayback Machine URL
        freshness_penalty: float = 0.0,  # Penalty for stale content (0.0-1.0)
        # Redirect tracking
        final_url: str | None = None,  # URL after following redirects
    ):
        self.ok = ok
        self.url = url
        self.final_url = final_url or url  # Default to original URL if not provided
        self.status = status
        self.headers = headers or {}
        self.html_path = html_path
        self.pdf_path = pdf_path
        self.warc_path = warc_path
        self.screenshot_path = screenshot_path
        self.content_hash = content_hash
        self.reason = reason
        self.method = method
        self.from_cache = from_cache
        self.etag = etag
        self.last_modified = last_modified
        self.auth_queued = auth_queued
        self.queue_id = queue_id
        self.auth_type = auth_type
        self.estimated_effort = estimated_effort
        self.ip_family = ip_family
        self.ip_switched = ip_switched
        # Archive fields
        self.is_archived = is_archived
        self.archive_date = archive_date
        self.archive_url = archive_url
        self.freshness_penalty = freshness_penalty
        # Page ID for database reference (set after page record created)
        self.page_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "ok": self.ok,
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "headers": self.headers,
            "html_path": self.html_path,
            "pdf_path": self.pdf_path,
            "warc_path": self.warc_path,
            "screenshot_path": self.screenshot_path,
            "content_hash": self.content_hash,
            "reason": self.reason,
            "method": self.method,
            "from_cache": self.from_cache,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "auth_queued": self.auth_queued,
            "queue_id": self.queue_id,
            "page_id": self.page_id,
        }
        # Include auth details only when relevant
        if self.auth_type:
            result["auth_type"] = self.auth_type
        if self.estimated_effort:
            result["estimated_effort"] = self.estimated_effort
        # Include IPv6 details
        if self.ip_family:
            result["ip_family"] = self.ip_family
        if self.ip_switched:
            result["ip_switched"] = self.ip_switched
        # Include archive details when content is from archive
        if self.is_archived:
            result["is_archived"] = self.is_archived
            result["archive_date"] = self.archive_date.isoformat() if self.archive_date else None
            result["archive_url"] = self.archive_url
            result["freshness_penalty"] = self.freshness_penalty
        return result

