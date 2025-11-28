"""
Browser path archive utilities for Lancet.

Implements §4.3.2 requirements:
- CDXJ-like metadata: URL/hash list of main resources
- Simplified HAR generation from CDP Network events
- Correlation with HTTP client path WARC files

CDXJ (Crawl Index JSON) format:
    Each line contains: <surt_url> <timestamp> <json_data>
    Example: com,example)/page 20240101120000 {"url": "...", "digest": "sha256:..."}

Simplified HAR (HTTP Archive):
    A JSON format capturing HTTP request/response cycles.
    We generate a minimal HAR focusing on main resources.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Resource Types and Data Classes
# =============================================================================

@dataclass
class ResourceInfo:
    """Information about a fetched resource.
    
    Attributes:
        url: Resource URL.
        method: HTTP method used.
        status: HTTP status code.
        mime_type: MIME type of the resource.
        size: Content size in bytes.
        content_hash: SHA-256 hash of content (if available).
        start_time: Request start timestamp.
        end_time: Request end timestamp (or None if still loading).
        headers: Response headers.
        is_main_frame: Whether this is the main frame document.
        from_cache: Whether served from cache.
        initiator_type: Type of initiator (script, parser, etc.).
    """
    url: str
    method: str = "GET"
    status: int | None = None
    mime_type: str = ""
    size: int = 0
    content_hash: str | None = None
    start_time: float = 0.0
    end_time: float | None = None
    headers: dict[str, str] = field(default_factory=dict)
    is_main_frame: bool = False
    from_cache: bool = False
    initiator_type: str = ""
    
    @property
    def duration_ms(self) -> float | None:
        """Calculate request duration in milliseconds."""
        if self.end_time is not None and self.start_time > 0:
            return (self.end_time - self.start_time) * 1000
        return None


@dataclass
class CDXJEntry:
    """A CDXJ (Crawl Index JSON) entry.
    
    Attributes:
        url: Original URL.
        surt: SURT (Sort-friendly URI Reordering Transform) format URL.
        timestamp: Capture timestamp (YYYYMMDDHHMMSS format).
        digest: Content digest (sha256:hash).
        mime_type: MIME type.
        status: HTTP status code.
        extra: Additional metadata.
    """
    url: str
    surt: str
    timestamp: str
    digest: str
    mime_type: str = "text/html"
    status: int = 200
    extra: dict[str, Any] = field(default_factory=dict)
    
    def to_cdxj_line(self) -> str:
        """Convert to CDXJ line format."""
        data = {
            "url": self.url,
            "digest": self.digest,
            "mime": self.mime_type,
            "status": str(self.status),
            **self.extra,
        }
        return f"{self.surt} {self.timestamp} {json.dumps(data, ensure_ascii=False)}"


def url_to_surt(url: str) -> str:
    """Convert URL to SURT (Sort-friendly URI Reordering Transform) format.
    
    SURT reverses domain components and normalizes the URL for sorting.
    Example: https://www.example.com/path → com,example,www)/path
    
    Args:
        url: Original URL.
        
    Returns:
        SURT formatted string.
    """
    try:
        parsed = urlparse(url)
        
        # Reverse domain components
        domain_parts = parsed.netloc.lower().split(".")
        domain_parts.reverse()
        reversed_domain = ",".join(domain_parts)
        
        # Build path component
        path = parsed.path or "/"
        query = f"?{parsed.query}" if parsed.query else ""
        
        return f"{reversed_domain}){path}{query}"
        
    except Exception:
        # Fallback to simple format
        return url.replace("://", ",").replace("/", ")")


# =============================================================================
# Network Event Collector
# =============================================================================

class NetworkEventCollector:
    """Collects network events from CDP for HAR generation.
    
    Listens to Playwright page network events and accumulates
    resource information for later HAR/CDXJ generation.
    """
    
    def __init__(self):
        self._resources: dict[str, ResourceInfo] = {}
        self._main_frame_url: str | None = None
        self._start_time: float = 0.0
        self._request_id_map: dict[str, str] = {}  # request_id -> url
    
    def start_collection(self, main_url: str) -> None:
        """Start collecting network events for a page load.
        
        Args:
            main_url: The main frame URL being loaded.
        """
        self._resources = {}
        self._main_frame_url = main_url
        self._start_time = time.time()
        self._request_id_map = {}
        
        logger.debug("Network event collection started", url=main_url[:80])
    
    def on_request(
        self,
        url: str,
        method: str = "GET",
        resource_type: str = "",
        is_main_frame: bool = False,
    ) -> None:
        """Record a network request event.
        
        Args:
            url: Request URL.
            method: HTTP method.
            resource_type: Resource type (document, script, stylesheet, etc.).
            is_main_frame: Whether this is the main frame request.
        """
        self._resources[url] = ResourceInfo(
            url=url,
            method=method,
            start_time=time.time(),
            is_main_frame=is_main_frame,
            initiator_type=resource_type,
        )
    
    def on_response(
        self,
        url: str,
        status: int,
        headers: dict[str, str],
        mime_type: str = "",
        from_cache: bool = False,
    ) -> None:
        """Record a network response event.
        
        Args:
            url: Request URL.
            status: HTTP status code.
            headers: Response headers.
            mime_type: Content MIME type.
            from_cache: Whether served from cache.
        """
        if url in self._resources:
            resource = self._resources[url]
            resource.status = status
            resource.headers = headers
            resource.mime_type = mime_type
            resource.from_cache = from_cache
        else:
            # Response without prior request (can happen with redirects)
            self._resources[url] = ResourceInfo(
                url=url,
                status=status,
                headers=headers,
                mime_type=mime_type,
                from_cache=from_cache,
            )
    
    def on_request_finished(
        self,
        url: str,
        size: int = 0,
        encoded_size: int = 0,
    ) -> None:
        """Record request completion.
        
        Args:
            url: Request URL.
            size: Decoded content size.
            encoded_size: Encoded (transfer) size.
        """
        if url in self._resources:
            resource = self._resources[url]
            resource.end_time = time.time()
            resource.size = size or encoded_size
    
    def add_content_hash(self, url: str, content: bytes) -> None:
        """Add content hash for a resource.
        
        Args:
            url: Resource URL.
            content: Resource content bytes.
        """
        if url in self._resources:
            self._resources[url].content_hash = hashlib.sha256(content).hexdigest()
    
    @property
    def resources(self) -> list[ResourceInfo]:
        """Get all collected resources."""
        return list(self._resources.values())
    
    @property
    def main_resources(self) -> list[ResourceInfo]:
        """Get main resources (documents, scripts, stylesheets).
        
        Filters out images, fonts, and other non-essential resources
        for CDXJ index generation.
        """
        main_types = {
            "document", "script", "stylesheet", "xhr", "fetch",
            "text/html", "text/javascript", "application/javascript",
            "text/css", "application/json",
        }
        
        result = []
        for resource in self._resources.values():
            # Include main frame always
            if resource.is_main_frame:
                result.append(resource)
                continue
            
            # Check initiator type
            if resource.initiator_type.lower() in main_types:
                result.append(resource)
                continue
            
            # Check MIME type
            mime_lower = resource.mime_type.lower()
            if any(t in mime_lower for t in ["html", "javascript", "json", "css"]):
                result.append(resource)
        
        return result


# =============================================================================
# HAR Generator
# =============================================================================

@dataclass
class HAREntry:
    """A single entry in the HAR log."""
    request: dict[str, Any]
    response: dict[str, Any]
    started_datetime: str
    time: float
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "startedDateTime": self.started_datetime,
            "time": self.time,
            "request": self.request,
            "response": self.response,
            "cache": {},
            "timings": {"wait": self.time, "receive": 0},
        }


class HARGenerator:
    """Generates simplified HAR files from collected network events.
    
    Creates a minimal HAR 1.2 format file suitable for debugging
    and reproducibility per §4.3.2 requirements.
    """
    
    def __init__(self, page_url: str, page_title: str = ""):
        self._page_url = page_url
        self._page_title = page_title
        self._started_datetime = datetime.now(timezone.utc).isoformat()
        self._entries: list[HAREntry] = []
    
    def add_resource(self, resource: ResourceInfo) -> None:
        """Add a resource to the HAR.
        
        Args:
            resource: Resource information.
        """
        # Build request object
        request = {
            "method": resource.method,
            "url": resource.url,
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": [],
            "queryString": [],
            "headersSize": -1,
            "bodySize": 0,
        }
        
        # Build response object
        response = {
            "status": resource.status or 0,
            "statusText": self._get_status_text(resource.status or 0),
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": [
                {"name": k, "value": v}
                for k, v in resource.headers.items()
            ],
            "content": {
                "size": resource.size,
                "mimeType": resource.mime_type,
                "compression": 0,
            },
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": resource.size,
        }
        
        # Calculate timing
        started = datetime.fromtimestamp(
            resource.start_time,
            tz=timezone.utc,
        ).isoformat() if resource.start_time else self._started_datetime
        
        duration = resource.duration_ms or 0
        
        entry = HAREntry(
            request=request,
            response=response,
            started_datetime=started,
            time=duration,
        )
        
        self._entries.append(entry)
    
    def generate(self) -> dict[str, Any]:
        """Generate the complete HAR structure.
        
        Returns:
            HAR 1.2 format dictionary.
        """
        return {
            "log": {
                "version": "1.2",
                "creator": {
                    "name": "Lancet Browser Archiver",
                    "version": "1.0",
                },
                "pages": [
                    {
                        "startedDateTime": self._started_datetime,
                        "id": "page_1",
                        "title": self._page_title or self._page_url,
                        "pageTimings": {
                            "onContentLoad": -1,
                            "onLoad": -1,
                        },
                    }
                ],
                "entries": [entry.to_dict() for entry in self._entries],
            }
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Generate HAR as JSON string.
        
        Args:
            indent: JSON indentation level.
            
        Returns:
            JSON string.
        """
        return json.dumps(self.generate(), indent=indent, ensure_ascii=False)
    
    @staticmethod
    def _get_status_text(status: int) -> str:
        """Get HTTP status text."""
        status_texts = {
            200: "OK",
            201: "Created",
            204: "No Content",
            301: "Moved Permanently",
            302: "Found",
            304: "Not Modified",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            429: "Too Many Requests",
            500: "Internal Server Error",
            502: "Bad Gateway",
            503: "Service Unavailable",
        }
        return status_texts.get(status, "Unknown")


# =============================================================================
# CDXJ Generator
# =============================================================================

class CDXJGenerator:
    """Generates CDXJ (Crawl Index JSON) files from collected resources.
    
    Creates a line-based index of resources with their digests,
    suitable for archive verification and lookup.
    """
    
    def __init__(self):
        self._entries: list[CDXJEntry] = []
        self._capture_time = datetime.now(timezone.utc)
    
    def add_resource(
        self,
        resource: ResourceInfo,
        content: bytes | None = None,
    ) -> None:
        """Add a resource to the CDXJ index.
        
        Args:
            resource: Resource information.
            content: Optional content bytes for hash calculation.
        """
        # Calculate digest
        if resource.content_hash:
            digest = f"sha256:{resource.content_hash}"
        elif content:
            digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
        else:
            digest = "sha256:unknown"
        
        # Generate SURT
        surt = url_to_surt(resource.url)
        
        # Format timestamp
        timestamp = self._capture_time.strftime("%Y%m%d%H%M%S")
        
        entry = CDXJEntry(
            url=resource.url,
            surt=surt,
            timestamp=timestamp,
            digest=digest,
            mime_type=resource.mime_type or "application/octet-stream",
            status=resource.status or 200,
            extra={
                "size": resource.size,
                "is_main": resource.is_main_frame,
            },
        )
        
        self._entries.append(entry)
    
    def generate(self) -> list[str]:
        """Generate CDXJ lines sorted by SURT.
        
        Returns:
            List of CDXJ formatted lines.
        """
        # Sort by SURT for efficient lookup
        sorted_entries = sorted(self._entries, key=lambda e: e.surt)
        return [entry.to_cdxj_line() for entry in sorted_entries]
    
    def to_string(self) -> str:
        """Generate CDXJ as multi-line string.
        
        Returns:
            CDXJ formatted string with newline-separated entries.
        """
        return "\n".join(self.generate())


# =============================================================================
# Browser Archiver
# =============================================================================

class BrowserArchiver:
    """Archives browser-fetched pages with CDXJ metadata and HAR.
    
    Implements §4.3.2 requirements for browser path archive preservation:
    - Captures main page content with page.content()
    - Records resource URLs and hashes in CDXJ format
    - Generates simplified HAR for network debugging
    - Coordinates with HTTP client WARC for consistency
    """
    
    def __init__(self, output_dir: Path | None = None):
        """Initialize browser archiver.
        
        Args:
            output_dir: Directory for archive output.
                       Uses settings.storage.archive_dir if not provided.
        """
        settings = get_settings()
        self._output_dir = output_dir or Path(settings.storage.archive_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        
        self._collector: NetworkEventCollector | None = None
    
    def create_collector(self) -> NetworkEventCollector:
        """Create a network event collector for a page load.
        
        Returns:
            NetworkEventCollector instance to use with page events.
        """
        self._collector = NetworkEventCollector()
        return self._collector
    
    async def attach_to_page(self, page, main_url: str) -> NetworkEventCollector:
        """Attach network event listeners to a Playwright page.
        
        This sets up event handlers to automatically collect network
        information during page navigation.
        
        Args:
            page: Playwright page object.
            main_url: Main URL being loaded.
            
        Returns:
            NetworkEventCollector with attached handlers.
        """
        collector = self.create_collector()
        collector.start_collection(main_url)
        
        # Handle request events
        async def on_request(request):
            try:
                collector.on_request(
                    url=request.url,
                    method=request.method,
                    resource_type=request.resource_type,
                    is_main_frame=request.is_navigation_request(),
                )
            except Exception as e:
                logger.debug("Error handling request event", error=str(e))
        
        # Handle response events
        async def on_response(response):
            try:
                headers = {}
                try:
                    headers = await response.all_headers()
                except Exception:
                    pass
                
                collector.on_response(
                    url=response.url,
                    status=response.status,
                    headers=headers,
                    mime_type=headers.get("content-type", ""),
                    from_cache=response.from_service_worker,
                )
            except Exception as e:
                logger.debug("Error handling response event", error=str(e))
        
        # Handle request finished events
        async def on_request_finished(request):
            try:
                sizes = await request.sizes()
                collector.on_request_finished(
                    url=request.url,
                    size=sizes.get("responseBodySize", 0),
                    encoded_size=sizes.get("responseHeadersSize", 0) + sizes.get("responseBodySize", 0),
                )
            except Exception as e:
                logger.debug("Error handling request_finished event", error=str(e))
        
        # Attach handlers
        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfinished", on_request_finished)
        
        logger.debug("Network event handlers attached", url=main_url[:80])
        
        return collector
    
    async def save_archive(
        self,
        url: str,
        content: bytes,
        title: str = "",
        collector: NetworkEventCollector | None = None,
        warc_path: str | None = None,
    ) -> dict[str, str | None]:
        """Save browser archive (CDXJ + HAR).
        
        Args:
            url: Page URL.
            content: Page HTML content.
            title: Page title.
            collector: Network event collector (optional).
            warc_path: Associated WARC file path for cross-reference.
            
        Returns:
            Dict with paths: cdxj_path, har_path, and status.
        """
        collector = collector or self._collector
        
        # Generate timestamp-based filename prefix
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"{timestamp}_{url_hash}"
        
        cdxj_path = None
        har_path = None
        
        try:
            # Generate CDXJ
            cdxj_gen = CDXJGenerator()
            
            # Add main document
            main_resource = ResourceInfo(
                url=url,
                status=200,
                mime_type="text/html",
                size=len(content),
                is_main_frame=True,
            )
            cdxj_gen.add_resource(main_resource, content)
            
            # Add collected resources
            if collector:
                for resource in collector.main_resources:
                    if resource.url != url:  # Skip main (already added)
                        cdxj_gen.add_resource(resource)
            
            # Save CDXJ
            cdxj_content = cdxj_gen.to_string()
            if cdxj_content:
                cdxj_file = self._output_dir / f"{prefix}.cdxj"
                cdxj_file.write_text(cdxj_content, encoding="utf-8")
                cdxj_path = str(cdxj_file)
                
                logger.info(
                    "CDXJ saved",
                    url=url[:80],
                    path=cdxj_path,
                    entries=len(cdxj_gen._entries),
                )
            
            # Generate HAR
            har_gen = HARGenerator(url, title)
            har_gen.add_resource(main_resource)
            
            if collector:
                for resource in collector.resources:
                    if resource.url != url:
                        har_gen.add_resource(resource)
            
            # Save HAR
            har_content = har_gen.to_json()
            har_file = self._output_dir / f"{prefix}.har"
            har_file.write_text(har_content, encoding="utf-8")
            har_path = str(har_file)
            
            logger.info(
                "HAR saved",
                url=url[:80],
                path=har_path,
                entries=len(har_gen._entries),
            )
            
            # Add cross-reference to WARC if provided
            if warc_path and cdxj_path:
                self._add_warc_reference(cdxj_path, warc_path)
            
            return {
                "cdxj_path": cdxj_path,
                "har_path": har_path,
                "status": "success",
            }
            
        except Exception as e:
            logger.error(
                "Browser archive save failed",
                url=url[:80],
                error=str(e),
            )
            return {
                "cdxj_path": cdxj_path,
                "har_path": har_path,
                "status": f"error: {str(e)}",
            }
    
    def _add_warc_reference(self, cdxj_path: str, warc_path: str) -> None:
        """Add WARC reference to CDXJ file header.
        
        Args:
            cdxj_path: Path to CDXJ file.
            warc_path: Path to associated WARC file.
        """
        try:
            cdxj_file = Path(cdxj_path)
            original_content = cdxj_file.read_text(encoding="utf-8")
            
            # Add header comment with WARC reference
            header = f"# Associated WARC: {warc_path}\n"
            cdxj_file.write_text(header + original_content, encoding="utf-8")
            
        except Exception as e:
            logger.debug("Failed to add WARC reference", error=str(e))


# =============================================================================
# Global instance management
# =============================================================================

_archiver: BrowserArchiver | None = None


def get_browser_archiver() -> BrowserArchiver:
    """Get or create browser archiver instance.
    
    Returns:
        BrowserArchiver instance.
    """
    global _archiver
    if _archiver is None:
        _archiver = BrowserArchiver()
    return _archiver


async def archive_browser_page(
    page,
    url: str,
    content: bytes | None = None,
    warc_path: str | None = None,
) -> dict[str, str | None]:
    """Convenience function to archive a browser page.
    
    Creates CDXJ and HAR archives for a Playwright page.
    
    Args:
        page: Playwright page object.
        url: Page URL.
        content: Page content (will be fetched if not provided).
        warc_path: Associated WARC path for cross-reference.
        
    Returns:
        Dict with archive paths.
    """
    archiver = get_browser_archiver()
    
    # Get content if not provided
    if content is None:
        html = await page.content()
        content = html.encode("utf-8")
    
    # Get page title
    title = ""
    try:
        title = await page.title()
    except Exception:
        pass
    
    return await archiver.save_archive(
        url=url,
        content=content,
        title=title,
        warc_path=warc_path,
    )





