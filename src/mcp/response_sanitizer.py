"""
MCP Response Sanitizer.

Implements L7 (MCP Response Sanitization) per ADR-0006 (8-Layer Security Model):
- Schema-based allowlist filtering (only defined fields pass through)
- LLM-generated field sanitization (L4 validation)
- Error response sanitization (no stack traces or internal paths)

This is the final defense layer before responses reach Cursor AI.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from typing import Any

from src.filter.llm_security import validate_llm_output
from src.mcp.schemas import get_schema
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

# Fields that contain LLM-generated content and require L4 sanitization
# Also includes user-provided fields that should be defensively sanitized
LLM_CONTENT_FIELDS = frozenset(
    [
        "text",  # Claim/fragment text
        "summary",  # Any summary field
        "message",  # Messages that might contain LLM content
        "description",  # Descriptions
        "extracted_text",  # Extracted content
        "query",  # User-provided search queries (defensive sanitization)
    ]
)

# Fields in nested objects that contain LLM content
LLM_NESTED_PATHS = [
    ("claims", "text"),
    ("fragments", "text"),
    ("searches", "query"),  # User-provided but sanitize anyway
]

# Pattern for sensitive internal paths
_INTERNAL_PATH_PATTERN = re.compile(
    r"/home/[^/]+/|"
    r"/root/|"
    r"/tmp/|"
    r"/var/|"
    r"/usr/local/|"
    r"C:\\\\Users\\\\|"
    r"\\\\src\\\\|"
    r"File \"[^\"]+\"|"  # Python traceback file paths
    r"line \d+, in \w+",  # Python traceback line info
    re.IGNORECASE,
)

# Pattern for stack trace fragments
_STACK_TRACE_PATTERN = re.compile(
    r"Traceback \(most recent call last\)|"
    r"^\s+File |"
    r"^\s+at \w+|"  # JavaScript style
    r"Exception:|"
    r"Error:|"
    r"^\s+raise \w+",
    re.MULTILINE,
)


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class SanitizationStats:
    """Statistics from sanitization process."""

    fields_removed: int = 0
    fields_sanitized: int = 0
    llm_fields_processed: int = 0
    leakage_detected: int = 0
    error_sanitized: bool = False

    @property
    def had_modifications(self) -> bool:
        """Check if any modifications were made."""
        return self.fields_removed > 0 or self.fields_sanitized > 0 or self.leakage_detected > 0


@dataclass
class SanitizationResult:
    """Result of response sanitization."""

    sanitized_response: dict[str, Any]
    stats: SanitizationStats = field(default_factory=SanitizationStats)
    original_field_count: int = 0

    @property
    def was_modified(self) -> bool:
        """Check if response was modified."""
        return self.stats.had_modifications


# ============================================================================
# Response Sanitizer
# ============================================================================


class ResponseSanitizer:
    """
    Sanitizes MCP responses before they reach Cursor AI.

    Implements L7 per ADR-0005:
    - Allowlist-based field filtering using JSON schemas
    - L4 validation for LLM-generated content
    - Error response sanitization

    Example:
        sanitizer = ResponseSanitizer()
        # Example tool name (MCP "search" tool was removed; use queue_searches instead)
        result = sanitizer.sanitize_response(response, "query_sql")
        return result.sanitized_response
    """

    def __init__(self, system_prompt: str | None = None):
        """
        Initialize sanitizer.

        Args:
            system_prompt: System prompt for L4 leakage detection (optional).
        """
        self._system_prompt = system_prompt
        self._stats = SanitizationStats()

    def sanitize_response(
        self,
        response: dict[str, Any],
        tool_name: str,
    ) -> SanitizationResult:
        """
        Sanitize an MCP response.

        Applies:
        1. Schema-based field filtering (allowlist)
        2. LLM content field sanitization (L4)

        Args:
            response: Raw response from handler.
            tool_name: Tool name for schema lookup.

        Returns:
            SanitizationResult with sanitized response.
        """
        stats = SanitizationStats()
        original_field_count = _count_fields(response)

        # Get schema for this tool
        schema = get_schema(tool_name)

        if schema is None:
            # No schema - log warning but allow through
            # This enables graceful handling of new tools
            logger.warning(
                "No schema found for tool - response passed through unsanitized",
                tool=tool_name,
            )
            return SanitizationResult(
                sanitized_response=response,
                stats=stats,
                original_field_count=original_field_count,
            )

        # Step 1: Strip unknown fields (allowlist filtering)
        sanitized, removed = self._strip_unknown_fields(response, schema)
        stats.fields_removed = removed

        # Step 2: Sanitize LLM content fields
        sanitized, llm_stats = self._sanitize_llm_fields(sanitized)
        stats.llm_fields_processed = llm_stats["processed"]
        stats.leakage_detected = llm_stats["leakage_count"]
        stats.fields_sanitized = llm_stats["sanitized"]

        if stats.had_modifications:
            logger.info(
                "Response sanitized",
                tool=tool_name,
                fields_removed=stats.fields_removed,
                llm_fields_processed=stats.llm_fields_processed,
                leakage_detected=stats.leakage_detected,
            )

        return SanitizationResult(
            sanitized_response=sanitized,
            stats=stats,
            original_field_count=original_field_count,
        )

    def sanitize_error(
        self,
        error: Exception,
        error_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Sanitize an error into a safe response.

        Removes:
        - Stack traces
        - Internal file paths
        - Sensitive details

        Args:
            error: Exception to sanitize.
            error_id: Error ID for log reference (generated if not provided).

        Returns:
            Safe error response dict.
        """
        if error_id is None:
            error_id = _generate_error_id()

        # Get error message and sanitize it
        error_message = str(error)
        sanitized_message = self._sanitize_error_message(error_message)

        # Log the full error internally
        logger.error(
            "Error sanitized for MCP response",
            error_id=error_id,
            error_type=type(error).__name__,
            original_message=error_message[:200],  # Truncate for log
        )

        return {
            "ok": False,
            "error_code": "INTERNAL_ERROR",
            "error": sanitized_message,
            "error_id": error_id,
        }

    def _strip_unknown_fields(
        self,
        obj: dict[str, Any],
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        """
        Strip fields not defined in schema (allowlist approach).

        Args:
            obj: Object to filter.
            schema: JSON schema defining allowed fields.

        Returns:
            Tuple of (filtered object, count of removed fields).
        """
        removed_count = 0

        # Handle oneOf schemas (multiple valid shapes)
        if "oneOf" in schema:
            # Try to match against oneOf variants
            best_match = self._match_one_of(obj, schema["oneOf"])
            if best_match is not None:
                return self._strip_unknown_fields(obj, best_match)
            # No match - use first variant as fallback
            return self._strip_unknown_fields(obj, schema["oneOf"][0])

        # Get allowed properties from schema
        properties = schema.get("properties", {})
        if not properties:
            # No properties defined - return as-is
            return obj, 0

        result: dict[str, Any] = {}

        for key, value in obj.items():
            if key not in properties:
                # Field not in allowlist - remove
                removed_count += 1
                logger.debug(
                    "Removed unknown field from response",
                    field=key,
                )
                continue

            prop_schema = properties[key]

            # Recursively process nested objects
            if isinstance(value, dict) and prop_schema.get("type") == "object":
                nested, nested_removed = self._strip_unknown_fields(value, prop_schema)
                result[key] = nested
                removed_count += nested_removed

            # Process arrays
            elif isinstance(value, list) and prop_schema.get("type") == "array":
                items_schema = prop_schema.get("items", {})
                if items_schema.get("type") == "object":
                    cleaned_items = []
                    for item in value:
                        if isinstance(item, dict):
                            cleaned, item_removed = self._strip_unknown_fields(item, items_schema)
                            cleaned_items.append(cleaned)
                            removed_count += item_removed
                        else:
                            cleaned_items.append(item)
                    result[key] = cleaned_items
                else:
                    result[key] = value
            else:
                result[key] = value

        return result, removed_count

    def _match_one_of(
        self,
        obj: dict[str, Any],
        variants: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """
        Match object against oneOf schema variants.

        Returns the best matching variant based on required fields.
        """
        for variant in variants:
            required = set(variant.get("required", []))
            obj_keys = set(obj.keys())

            # Check if all required fields are present
            if required.issubset(obj_keys):
                # Check const fields match
                props = variant.get("properties", {})
                matches = True
                for key, prop in props.items():
                    if "const" in prop:
                        if obj.get(key) != prop["const"]:
                            matches = False
                            break

                if matches:
                    return variant

        return None

    def _sanitize_llm_fields(
        self,
        obj: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """
        Sanitize fields containing LLM-generated content.

        Applies L4 validation (prompt leakage detection, URL detection).
        Uses recursive processing to handle all nested structures uniformly,
        avoiding duplicate processing of top-level and nested fields.

        Args:
            obj: Object with potential LLM content.

        Returns:
            Tuple of (sanitized object, stats dict).
        """
        stats = {"processed": 0, "sanitized": 0, "leakage_count": 0}

        # Use single recursive pass to process all LLM content fields
        # This avoids duplicate processing that occurred when direct fields
        # and nested paths were processed separately before recursion
        result = self._recursive_llm_sanitize(obj, stats)

        return result, stats

    def _recursive_llm_sanitize(
        self,
        obj: Any,
        stats: dict[str, int],
    ) -> Any:
        """Recursively sanitize LLM content in nested structures."""
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                if key in LLM_CONTENT_FIELDS and isinstance(value, str):
                    sanitized_value, had_issues = self._validate_llm_content(value)
                    result[key] = sanitized_value
                    stats["processed"] += 1
                    if had_issues:
                        stats["sanitized"] += 1
                else:
                    result[key] = self._recursive_llm_sanitize(value, stats)
            return result
        elif isinstance(obj, list):
            return [self._recursive_llm_sanitize(item, stats) for item in obj]
        else:
            return obj

    def _validate_llm_content(self, text: str) -> tuple[str, bool]:
        """
        Validate LLM content using L4 security.

        Args:
            text: Text to validate.

        Returns:
            Tuple of (validated text, whether issues were found).
        """
        result = validate_llm_output(
            text,
            warn_on_suspicious=True,
            system_prompt=self._system_prompt,
            mask_leakage=True,
        )

        had_issues = result.had_suspicious_content

        if result.leakage_detected:
            logger.warning(
                "Prompt leakage detected in MCP response field",
            )

        return result.validated_text, had_issues

    def _sanitize_error_message(self, message: str) -> str:
        """
        Remove sensitive information from error message.

        Args:
            message: Raw error message.

        Returns:
            Sanitized message.
        """
        # Remove internal paths
        sanitized = _INTERNAL_PATH_PATTERN.sub("[PATH]", message)

        # Remove stack trace fragments
        sanitized = _STACK_TRACE_PATTERN.sub("[TRACE]", sanitized)

        # Truncate if too long
        max_length = 200
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + "..."

        # If message is mostly redacted, use generic message
        redaction_count = sanitized.count("[PATH]") + sanitized.count("[TRACE]")
        if redaction_count > 3:
            return "An internal error occurred. Check logs for error_id."

        return sanitized


# ============================================================================
# Helper Functions
# ============================================================================


def _count_fields(obj: Any, depth: int = 0) -> int:
    """Count total fields in nested structure."""
    if depth > 10:  # Prevent infinite recursion
        return 0

    if isinstance(obj, dict):
        count = len(obj)
        for value in obj.values():
            count += _count_fields(value, depth + 1)
        return count
    elif isinstance(obj, list):
        return sum(_count_fields(item, depth + 1) for item in obj)
    return 0


def _generate_error_id() -> str:
    """Generate a unique error ID for log correlation."""
    return f"err_{secrets.token_hex(8)}"


# ============================================================================
# Module-level Sanitizer
# ============================================================================

_default_sanitizer: ResponseSanitizer | None = None


def get_sanitizer(system_prompt: str | None = None) -> ResponseSanitizer:
    """
    Get or create the default sanitizer instance.

    Args:
        system_prompt: System prompt for L4 detection (optional).

    Returns:
        ResponseSanitizer instance.
    """
    global _default_sanitizer

    if _default_sanitizer is None or system_prompt is not None:
        _default_sanitizer = ResponseSanitizer(system_prompt=system_prompt)

    return _default_sanitizer


def sanitize_response(
    response: dict[str, Any],
    tool_name: str,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """
    Convenience function to sanitize a response.

    Args:
        response: Raw response from handler.
        tool_name: Tool name for schema lookup.
        system_prompt: System prompt for L4 detection (optional).

    Returns:
        Sanitized response dict.
    """
    sanitizer = get_sanitizer(system_prompt)
    result = sanitizer.sanitize_response(response, tool_name)
    return result.sanitized_response


def sanitize_error(
    error: Exception,
    error_id: str | None = None,
) -> dict[str, Any]:
    """
    Convenience function to sanitize an error.

    Args:
        error: Exception to sanitize.
        error_id: Error ID for log reference.

    Returns:
        Safe error response dict.
    """
    sanitizer = get_sanitizer()
    return sanitizer.sanitize_error(error, error_id)
