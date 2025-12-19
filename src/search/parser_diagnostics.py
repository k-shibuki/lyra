"""
Parser Diagnostics for AI-Assisted Selector Repair.

Generates structured diagnostic reports when search result parsers fail,
enabling AI (Cursor) to efficiently suggest fixes.

Design Philosophy:
- Provide actionable information for AI to generate fixes
- Output candidate selectors based on HTML structure analysis
- Generate ready-to-use YAML fix suggestions
- Support hot-reload workflow (edit config → test → verify)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from src.search.parser_config import get_parser_config_manager
from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _sanitize_for_yaml_comment(text: str, max_length: int = 50) -> str:
    """
    Sanitize text for use in YAML comments.

    Removes/replaces characters that could break YAML comment syntax:
    - '#' characters (would start new comment)
    - Newlines (would break comment line)
    - Control characters

    Args:
        text: Text to sanitize.
        max_length: Maximum length of output.

    Returns:
        Sanitized text safe for YAML comments.
    """
    # Replace # with → to preserve meaning
    sanitized = text.replace("#", "→")
    # Replace newlines with spaces
    sanitized = sanitized.replace("\n", " ").replace("\r", "")
    # Remove other control characters
    sanitized = "".join(c for c in sanitized if c.isprintable() or c == " ")
    # Truncate
    if len(sanitized) > max_length:
        return sanitized[:max_length] + "..."
    return sanitized


def _escape_css_attribute_value(value: str) -> str:
    """
    Escape a value for use in CSS attribute selector.

    CSS attribute selector rules:
    - If value contains single quotes, use double quotes and escape double quotes
    - If value contains double quotes, use single quotes and escape single quotes
    - If value contains both, escape appropriately and use double quotes

    Args:
        value: Attribute value to escape.

    Returns:
        Escaped value safe for CSS attribute selector (with quotes).
    """
    if not value:
        return "''"

    # If contains single quotes but not double quotes, use double quotes
    if "'" in value and '"' not in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    # If contains double quotes but not single quotes, use single quotes
    if '"' in value and "'" not in value:
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

    # If contains both or neither, prefer single quotes and escape single quotes
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _escape_css_id(id_value: str) -> str:
    """
    Escape an ID value for use in CSS ID selector (#id).

    CSS ID selector rules:
    - Special characters need to be escaped with backslash
    - Common special chars: space, ., #, :, [, ], (, ), etc.

    Args:
        id_value: ID value to escape.

    Returns:
        Escaped ID safe for CSS ID selector.
    """
    if not id_value:
        return ""

    # Escape special characters according to CSS spec
    # See: https://www.w3.org/TR/CSS21/syndata.html#value-def-identifier
    special_chars = r' !"#$%&\'()*+,./:;<=>?@[\\]^`{|}~'
    escaped = ""
    for char in id_value:
        if char in special_chars:
            escaped += f"\\{char}"
        else:
            escaped += char

    return escaped


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class FailedSelector:
    """Information about a selector that failed to find elements."""

    name: str
    selector: str
    required: bool
    diagnostic_message: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "selector": self.selector,
            "required": self.required,
            "diagnostic_message": self.diagnostic_message,
        }


@dataclass
class CandidateElement:
    """A potential element that could be a search result component."""

    tag: str
    selector: str
    sample_text: str
    occurrence_count: int
    confidence: float  # 0.0 to 1.0
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tag": self.tag,
            "selector": self.selector,
            "sample_text": self.sample_text[:100] if self.sample_text else "",
            "occurrence_count": self.occurrence_count,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class ParserDiagnosticReport:
    """
    Comprehensive diagnostic report for parser failure.

    Contains all information needed for AI-assisted repair:
    - What failed (selectors)
    - What exists in HTML (candidates)
    - How to fix (YAML suggestions)
    """

    engine: str
    query: str
    failed_selectors: list[FailedSelector]
    candidate_elements: list[CandidateElement]
    suggested_fixes: list[str]  # YAML fragment strings
    html_path: Path | None
    html_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "engine": self.engine,
            "query": self.query,
            "failed_selectors": [s.to_dict() for s in self.failed_selectors],
            "candidate_elements": [c.to_dict() for c in self.candidate_elements],
            "suggested_fixes": self.suggested_fixes,
            "html_path": str(self.html_path) if self.html_path else None,
            "html_summary": self.html_summary,
        }

    def to_log_dict(self) -> dict[str, Any]:
        """Convert to a compact dict suitable for structured logging."""
        return {
            "engine": self.engine,
            "failed_selector_names": [s.name for s in self.failed_selectors],
            "candidate_count": len(self.candidate_elements),
            "top_candidate": self.candidate_elements[0].selector
            if self.candidate_elements
            else None,
            "html_path": str(self.html_path) if self.html_path else None,
            "has_suggestions": len(self.suggested_fixes) > 0,
        }


# =============================================================================
# HTML Analysis
# =============================================================================


class HTMLAnalyzer:
    """
    Analyzes HTML to find candidate elements for search result selectors.

    Uses heuristics to identify:
    - Result containers (lists, repeating divs)
    - Title elements (h2, h3, links with certain patterns)
    - URL elements (links)
    - Snippet elements (paragraphs, spans with text)
    """

    # Common patterns for search result elements
    RESULT_CONTAINER_PATTERNS = [
        # Class patterns that often indicate results
        r"result",
        r"search.*item",
        r"serp.*item",
        r"snippet",
        r"algo",  # Bing
        r"mainline",  # Ecosia
        r"web-result",
        r"organic",
    ]

    TITLE_PATTERNS = [
        r"title",
        r"heading",
        r"header",
    ]

    SNIPPET_PATTERNS = [
        r"snippet",
        r"description",
        r"desc",
        r"abstract",
        r"summary",
        r"caption",
    ]

    URL_PATTERNS = [
        r"url",
        r"link",
        r"cite",
        r"domain",
    ]

    def __init__(self, html: str):
        """Initialize with HTML content."""
        self.html = html
        self.soup = BeautifulSoup(html, "html.parser")
        self._class_counts: Counter | None = None

    def get_html_summary(self) -> dict[str, Any]:
        """Get summary statistics about the HTML."""
        return {
            "total_elements": len(self.soup.find_all(True)),
            "total_links": len(self.soup.find_all("a")),
            "total_divs": len(self.soup.find_all("div")),
            "total_lists": len(self.soup.find_all(["ul", "ol", "li"])),
            "has_scripts": len(self.soup.find_all("script")) > 0,
            "title": self.soup.title.string if self.soup.title else None,
        }

    def _get_class_counts(self) -> Counter:
        """Count occurrences of each class."""
        if self._class_counts is None:
            self._class_counts = Counter()
            for elem in self.soup.find_all(True):
                classes = elem.get("class", [])
                if classes:
                    for cls in classes:
                        self._class_counts[cls] += 1
        return self._class_counts

    def _matches_patterns(self, text: str, patterns: list[str]) -> bool:
        """Check if text matches any pattern (case-insensitive)."""
        text_lower = text.lower()
        return any(re.search(p, text_lower) for p in patterns)

    def _safe_select(self, selector: str, context: BeautifulSoup | Tag | None = None) -> list[Tag]:
        """
        Safely execute select() with exception handling.

        Args:
            selector: CSS selector string.
            context: Element to search within (defaults to self.soup).

        Returns:
            List of matching elements, or empty list on error.
        """
        target = context if context is not None else self.soup
        try:
            return target.select(selector)
        except Exception as e:
            logger.debug(
                "CSS selector failed",
                selector=selector,
                error=str(e),
            )
            return []

    def _build_selector(self, elem: Tag) -> str:
        """Build a CSS selector for an element."""
        selectors = []

        # Prefer ID (unique, so early return is fine)
        if elem.get("id"):
            escaped_id = _escape_css_id(elem["id"])
            return f"#{escaped_id}"

        # Use tag name
        selectors.append(elem.name)

        # Add classes
        classes = elem.get("class", [])
        if classes:
            # Use most specific class (longest or most unique)
            class_counts = self._get_class_counts()
            sorted_classes = sorted(
                classes,
                key=lambda c: (class_counts.get(c, 999), -len(c)),
            )
            if sorted_classes:
                # Escape dots in class names (rare but possible)
                class_name = sorted_classes[0].replace(".", "\\.")
                selectors.append(f".{class_name}")

        # Add data-testid if present (combine with tag+class for specificity)
        test_id = elem.get("data-testid")
        if test_id:
            escaped_testid = _escape_css_attribute_value(test_id)
            selectors.append(f"[data-testid={escaped_testid}]")

        return "".join(selectors)

    def _get_sample_text(self, elem: Tag, max_length: int = 100) -> str:
        """Get sample text from element."""
        text = elem.get_text(strip=True)
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text

    def find_result_containers(self) -> list[CandidateElement]:
        """Find potential search result container elements."""
        candidates = []

        # Look for repeating structures (common in search results)
        # Find elements with result-like classes
        for elem in self.soup.find_all(True):
            classes = elem.get("class", [])
            class_str = " ".join(classes)

            # Check if class matches result patterns
            if self._matches_patterns(class_str, self.RESULT_CONTAINER_PATTERNS):
                selector = self._build_selector(elem)

                # Count similar elements
                similar = self._safe_select(selector)
                count = len(similar)

                # Higher confidence if multiple occurrences (search results repeat)
                confidence = min(0.9, 0.3 + (count * 0.1))

                candidates.append(
                    CandidateElement(
                        tag=elem.name,
                        selector=selector,
                        sample_text=self._get_sample_text(elem),
                        occurrence_count=count,
                        confidence=confidence,
                        reason=f"Class matches result pattern: {class_str}",
                    )
                )

        # Look for data-testid attributes (modern React/Vue apps)
        for elem in self.soup.find_all(attrs={"data-testid": True}):
            test_id = elem["data-testid"]
            if self._matches_patterns(test_id, self.RESULT_CONTAINER_PATTERNS):
                escaped_testid = _escape_css_attribute_value(test_id)
                selector = f"[data-testid={escaped_testid}]"
                similar = self._safe_select(selector)

                candidates.append(
                    CandidateElement(
                        tag=elem.name,
                        selector=selector,
                        sample_text=self._get_sample_text(elem),
                        occurrence_count=len(similar),
                        confidence=0.8,
                        reason=f"data-testid matches result pattern: {test_id}",
                    )
                )

        # Look for li elements within ul/ol (common list structure)
        for ul in self.soup.find_all(["ul", "ol"]):
            li_items = ul.find_all("li", recursive=False)
            if 3 <= len(li_items) <= 20:  # Reasonable result count
                # Check if li items have links (likely results)
                links_count = sum(1 for li in li_items if li.find("a"))
                if links_count >= len(li_items) * 0.5:
                    parent_selector = self._build_selector(ul)
                    selector = f"{parent_selector} li" if parent_selector else "li"

                    candidates.append(
                        CandidateElement(
                            tag="li",
                            selector=selector,
                            sample_text=self._get_sample_text(li_items[0]) if li_items else "",
                            occurrence_count=len(li_items),
                            confidence=0.7,
                            reason="List items with links (common result pattern)",
                        )
                    )

        # Deduplicate and sort by confidence
        seen_selectors = set()
        unique_candidates = []
        for c in sorted(candidates, key=lambda x: -x.confidence):
            if c.selector not in seen_selectors:
                seen_selectors.add(c.selector)
                unique_candidates.append(c)

        return unique_candidates[:10]  # Top 10 candidates

    def find_title_elements(self, container_selector: str | None = None) -> list[CandidateElement]:
        """Find potential title elements within containers."""
        candidates = []

        # Search context
        context = self.soup
        # Use explicit None check and handle empty strings defensively
        if container_selector is not None and container_selector:
            containers = self._safe_select(container_selector)
            if containers:
                context = containers[0]

        # Look for headings (h1-h6) with links
        for level in range(1, 7):
            headings = context.find_all(f"h{level}")
            for h in headings:
                link = h.find("a")
                if link and link.get("href"):
                    selector = f"h{level} a"

                    candidates.append(
                        CandidateElement(
                            tag=f"h{level}",
                            selector=selector,
                            sample_text=self._get_sample_text(h),
                            occurrence_count=len(context.find_all(f"h{level}")),
                            confidence=0.8 - (level * 0.05),  # h2 > h3 > h4
                            reason=f"Heading with link (h{level})",
                        )
                    )

        # Look for elements with title-like classes
        for elem in context.find_all(True):
            classes = elem.get("class", [])
            class_str = " ".join(classes)

            if self._matches_patterns(class_str, self.TITLE_PATTERNS):
                selector = self._build_selector(elem)

                candidates.append(
                    CandidateElement(
                        tag=elem.name,
                        selector=selector,
                        sample_text=self._get_sample_text(elem),
                        occurrence_count=len(self._safe_select(selector, context)),
                        confidence=0.7,
                        reason=f"Class matches title pattern: {class_str}",
                    )
                )

        # Deduplicate and sort
        seen = set()
        unique = []
        for c in sorted(candidates, key=lambda x: -x.confidence):
            if c.selector not in seen:
                seen.add(c.selector)
                unique.append(c)

        return unique[:5]

    def find_snippet_elements(
        self, container_selector: str | None = None
    ) -> list[CandidateElement]:
        """Find potential snippet/description elements."""
        candidates = []

        context = self.soup
        # Use explicit None check and handle empty strings defensively
        if container_selector is not None and container_selector:
            containers = self._safe_select(container_selector)
            if containers:
                context = containers[0]

        # Look for paragraphs with substantial text
        for p in context.find_all("p"):
            text = p.get_text(strip=True)
            if 30 <= len(text) <= 500:  # Reasonable snippet length
                selector = self._build_selector(p)

                candidates.append(
                    CandidateElement(
                        tag="p",
                        selector=selector,
                        sample_text=text[:100],
                        occurrence_count=len(self._safe_select(selector, context)),
                        confidence=0.6,
                        reason="Paragraph with snippet-length text",
                    )
                )

        # Look for elements with snippet-like classes
        for elem in context.find_all(True):
            classes = elem.get("class", [])
            class_str = " ".join(classes)

            if self._matches_patterns(class_str, self.SNIPPET_PATTERNS):
                selector = self._build_selector(elem)
                text = self._get_sample_text(elem)

                if len(text) >= 20:  # Has meaningful content
                    candidates.append(
                        CandidateElement(
                            tag=elem.name,
                            selector=selector,
                            sample_text=text,
                            occurrence_count=len(self._safe_select(selector, context)),
                            confidence=0.75,
                            reason=f"Class matches snippet pattern: {class_str}",
                        )
                    )

        # Deduplicate and sort
        seen = set()
        unique = []
        for c in sorted(candidates, key=lambda x: -x.confidence):
            if c.selector not in seen:
                seen.add(c.selector)
                unique.append(c)

        return unique[:5]

    def find_url_elements(self, container_selector: str | None = None) -> list[CandidateElement]:
        """Find potential URL elements."""
        candidates = []

        context = self.soup
        # Use explicit None check and handle empty strings defensively
        if container_selector is not None and container_selector:
            containers = self._safe_select(container_selector)
            if containers:
                context = containers[0]

        # All links with external URLs
        for link in context.find_all("a", href=True):
            href = link["href"]
            if href.startswith(("http://", "https://")):
                selector = self._build_selector(link)

                candidates.append(
                    CandidateElement(
                        tag="a",
                        selector=selector,
                        sample_text=href[:100],
                        occurrence_count=len(self._safe_select(selector, context)),
                        confidence=0.7,
                        reason="Link with external URL",
                    )
                )

        # Elements with URL-like classes
        for elem in context.find_all(True):
            classes = elem.get("class", [])
            class_str = " ".join(classes)

            if self._matches_patterns(class_str, self.URL_PATTERNS):
                selector = self._build_selector(elem)

                candidates.append(
                    CandidateElement(
                        tag=elem.name,
                        selector=selector,
                        sample_text=self._get_sample_text(elem),
                        occurrence_count=len(self._safe_select(selector, context)),
                        confidence=0.65,
                        reason=f"Class matches URL pattern: {class_str}",
                    )
                )

        # Deduplicate and sort
        seen = set()
        unique = []
        for c in sorted(candidates, key=lambda x: -x.confidence):
            if c.selector not in seen:
                seen.add(c.selector)
                unique.append(c)

        return unique[:5]


# =============================================================================
# YAML Fix Generation
# =============================================================================


def generate_yaml_fix(
    selector_name: str,
    candidate: CandidateElement,
    engine: str,
) -> str:
    """
    Generate a YAML fix suggestion for a selector.

    Args:
        selector_name: Name of the selector to fix.
        candidate: Candidate element to use.
        engine: Search engine name.

    Returns:
        YAML fragment string.
    """
    # Escape special characters in selector for YAML double-quoted string
    # Must escape backslashes first, then quotes
    escaped_selector = candidate.selector.replace("\\", "\\\\").replace('"', '\\"')

    # Sanitize text fields for YAML comments (avoid # and newlines breaking syntax)
    sanitized_reason = _sanitize_for_yaml_comment(candidate.reason, 80)
    sanitized_sample = _sanitize_for_yaml_comment(candidate.sample_text, 50)

    yaml_fix = f"""# Fix for {engine} {selector_name}
# Candidate: {sanitized_reason}
# Sample text: {sanitized_sample}
# Occurrences: {candidate.occurrence_count}

{engine}:
  selectors:
    {selector_name}:
      selector: "{escaped_selector}"
      required: true
      diagnostic_message: |
        {selector_name.replace("_", " ").title()} not found.
        Expected: {escaped_selector}
        Confidence: {candidate.confidence:.0%}
"""
    return yaml_fix


def generate_multiple_yaml_fixes(
    failed_selectors: list[FailedSelector],
    candidates_by_type: dict[str, list[CandidateElement]],
    engine: str,
) -> list[str]:
    """
    Generate YAML fixes for multiple failed selectors.

    Args:
        failed_selectors: List of selectors that failed.
        candidates_by_type: Dict mapping selector type to candidate elements.
        engine: Search engine name.

    Returns:
        List of YAML fix strings.
    """
    fixes = []

    # Map selector names to candidate types
    selector_type_map = {
        "results_container": "container",
        "results_container_alt": "container",
        "title": "title",
        "url": "url",
        "snippet": "snippet",
        "date": "snippet",  # Dates are often near snippets
    }

    for failed in failed_selectors:
        selector_type = selector_type_map.get(failed.name, "container")
        candidates = candidates_by_type.get(selector_type, [])

        if candidates:
            # Use top candidate
            fix = generate_yaml_fix(failed.name, candidates[0], engine)
            fixes.append(fix)

    return fixes


# =============================================================================
# Diagnostic Report Generation
# =============================================================================


def create_diagnostic_report(
    engine: str,
    query: str,
    html: str,
    failed_selectors: list[FailedSelector],
    html_path: Path | None = None,
) -> ParserDiagnosticReport:
    """
    Create a comprehensive diagnostic report for parser failure.

    Args:
        engine: Search engine name.
        query: Search query that was used.
        html: HTML content that failed to parse.
        failed_selectors: List of selectors that failed.
        html_path: Path where HTML was saved for debugging.

    Returns:
        ParserDiagnosticReport with analysis and suggestions.
        Returns a minimal report with error info if analysis fails.
    """
    try:
        analyzer = HTMLAnalyzer(html)

        # Get HTML summary
        html_summary = analyzer.get_html_summary()

        # Find candidate elements for each type
        container_candidates = analyzer.find_result_containers()

        # Use top container for searching within
        top_container = container_candidates[0].selector if container_candidates else None

        title_candidates = analyzer.find_title_elements(top_container)
        snippet_candidates = analyzer.find_snippet_elements(top_container)
        url_candidates = analyzer.find_url_elements(top_container)

        # Collect all candidates
        all_candidates = (
            container_candidates[:3]
            + title_candidates[:2]
            + url_candidates[:2]
            + snippet_candidates[:2]
        )

        # Generate YAML fixes
        candidates_by_type = {
            "container": container_candidates,
            "title": title_candidates,
            "url": url_candidates,
            "snippet": snippet_candidates,
        }

        suggested_fixes = generate_multiple_yaml_fixes(
            failed_selectors,
            candidates_by_type,
            engine,
        )

        report = ParserDiagnosticReport(
            engine=engine,
            query=query,
            failed_selectors=failed_selectors,
            candidate_elements=all_candidates,
            suggested_fixes=suggested_fixes,
            html_path=html_path,
            html_summary=html_summary,
        )

        logger.info(
            "Parser diagnostic report created",
            engine=engine,
            failed_count=len(failed_selectors),
            candidate_count=len(all_candidates),
            suggestion_count=len(suggested_fixes),
        )

        return report

    except Exception as e:
        # Log the error and return a minimal report
        logger.error(
            "Failed to create diagnostic report",
            engine=engine,
            error=str(e),
        )

        # Return minimal report with error info
        return ParserDiagnosticReport(
            engine=engine,
            query=query,
            failed_selectors=failed_selectors,
            candidate_elements=[],
            suggested_fixes=[],
            html_path=html_path,
            html_summary={"error": str(e)},
        )


def get_latest_debug_html(engine: str | None = None) -> Path | None:
    """
    Get the most recent debug HTML file.

    Args:
        engine: Optional engine filter.

    Returns:
        Path to latest debug HTML or None.
    """
    # Use configured debug directory from ParserSettings
    manager = get_parser_config_manager()
    debug_dir = manager.settings.debug_html_dir

    if not debug_dir.exists():
        return None

    # Use explicit None check and handle empty strings defensively
    if engine is not None and engine:
        pattern = f"{engine}_*.html"
    else:
        pattern = "*.html"

    html_files = list(debug_dir.glob(pattern))

    if not html_files:
        return None

    # Sort by modification time (newest first)
    html_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return html_files[0]


def analyze_debug_html(html_path: Path) -> ParserDiagnosticReport | None:
    """
    Analyze a debug HTML file and create diagnostic report.

    Args:
        html_path: Path to debug HTML file.

    Returns:
        ParserDiagnosticReport or None if file cannot be read.
    """
    if not html_path.exists():
        logger.warning("Debug HTML file not found", path=str(html_path))
        return None

    try:
        content = html_path.read_text(encoding="utf-8")

        # Extract metadata from header comment
        metadata = {}
        if content.startswith("<!-- Parser Debug Info"):
            # Parse metadata from comment
            match = re.search(r"Engine: (.+?)\n", content)
            if match:
                metadata["engine"] = match.group(1)

            match = re.search(r"Query: (.+?)\n", content)
            if match:
                metadata["query"] = match.group(1)

            match = re.search(r"Error: (.+?)\n", content)
            if match:
                metadata["error"] = match.group(1)

            # Remove metadata comment
            content = re.sub(r"^<!-- Parser Debug Info.+?-->\s*", "", content, flags=re.DOTALL)

        engine = metadata.get("engine", html_path.stem.split("_")[0])
        query = metadata.get("query", "unknown")

        # Create report with empty failed selectors (we don't know which failed)
        # The analysis will still identify candidates
        return create_diagnostic_report(
            engine=engine,
            query=query,
            html=content,
            failed_selectors=[],
            html_path=html_path,
        )

    except Exception as e:
        logger.error("Failed to analyze debug HTML", path=str(html_path), error=str(e))
        return None
