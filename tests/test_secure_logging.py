"""
Tests for Secure Logging (L8).

Implements ADR-0005 L8: Log Security Policy.

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|---------------------|-------------|-----------------|-------|
| TC-N-01 | log_llm_io with normal input/output | Normal | Hash/length/preview logged | - |
| TC-N-02 | log_exception with ValueError | Normal | Sanitized message, error_id | - |
| TC-N-03 | log_sensitive_operation with normal dict | Normal | Dict values sanitized | - |
| TC-N-04 | log_security_event with PROMPT_LEAKAGE | Normal | Event logged with severity | - |
| TC-N-05 | log_prompt_leakage helper | Normal | Correct event type | - |
| TC-N-06 | log_dangerous_pattern helper | Normal | Correct event type | - |
| TC-N-07 | Event dict with normal text field | Normal | No modification | - |
| TC-N-08 | Response with LLM fields at multiple levels | Normal | Each field processed once | - |
| TC-A-01 | log_llm_io with prompt-like content | Abnormal | Content masked | - |
| TC-A-02 | log_llm_io with path-like content | Abnormal | Paths masked | - |
| TC-A-03 | log_exception with stack trace | Abnormal | Trace removed | - |
| TC-A-04 | log_exception with file path | Abnormal | Path removed | - |
| TC-A-05 | log_security_event with long details | Abnormal | Details sanitized | - |
| TC-A-06 | Event dict with prompt-like text | Abnormal | Content sanitized | - |
| TC-A-07 | Event dict with long text (>500 chars) | Abnormal | Content truncated | - |
| TC-B-01 | log_llm_io with empty string | Boundary | No error, length=0 | - |
| TC-B-02 | log_llm_io with very long text | Boundary | Preview truncated | - |
| TC-B-03 | log_llm_io with None input | Boundary | No input in log | - |
| TC-B-04 | log_security_event with None details | Boundary | No details in log | - |
| TC-B-05 | Verify stats counts correctly | Boundary | No double counting | - |
"""

from unittest.mock import patch

import pytest

from src.utils.secure_logging import (
    MAX_PREVIEW_LENGTH,
    AuditLogger,
    LLMIOSummary,
    SanitizedExceptionInfo,
    SecureLogger,
    SecurityEventType,
    get_audit_logger,
    get_secure_logger,
    sanitize_log_processor,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def secure_logger() -> SecureLogger:
    """Create a SecureLogger instance."""
    return SecureLogger("test_module")


@pytest.fixture
def audit_logger() -> AuditLogger:
    """Create an AuditLogger instance."""
    return AuditLogger()


# ============================================================================
# SecureLogger Normal Cases (TC-N-01 to TC-N-03)
# ============================================================================


class TestSecureLoggerNormal:
    """Test SecureLogger normal cases."""

    def test_log_llm_io_normal(self, secure_logger: SecureLogger) -> None:
        """
        TC-N-01: log_llm_io with normal input/output

        // Given: Normal input and output text
        // When: Calling log_llm_io
        // Then: Hash, length, and preview are generated correctly
        """
        input_text = "What is Python programming language?"
        output_text = "Python is a high-level programming language."

        with patch.object(secure_logger, "_logger") as mock_logger:
            secure_logger.log_llm_io(
                "extract_facts",
                input_text=input_text,
                output_text=output_text,
            )

            mock_logger.debug.assert_called_once()
            call_kwargs = mock_logger.debug.call_args[1]

            # Verify structure
            assert "input" in call_kwargs
            assert "output" in call_kwargs
            assert call_kwargs["operation"] == "extract_facts"

            # Verify input summary
            assert call_kwargs["input"]["length"] == len(input_text)
            assert len(call_kwargs["input"]["hash"]) == 16  # SHA256 prefix
            assert call_kwargs["input"]["preview"] == input_text

            # Verify output summary
            assert call_kwargs["output"]["length"] == len(output_text)

    def test_log_exception_normal(self, secure_logger: SecureLogger) -> None:
        """
        TC-N-02: log_exception with ValueError

        // Given: A simple ValueError
        // When: Logging the exception
        // Then: Sanitized message and error_id are generated
        """
        try:
            raise ValueError("Invalid input value")
        except Exception as e:
            with patch.object(secure_logger, "_logger") as mock_logger:
                result = secure_logger.log_exception(e)

                mock_logger.error.assert_called_once()

                assert isinstance(result, SanitizedExceptionInfo)
                assert result.exception_type == "ValueError"
                assert "Invalid input value" in result.sanitized_message
                assert result.error_id.startswith("err_")

    def test_log_sensitive_operation_normal(self, secure_logger: SecureLogger) -> None:
        """
        TC-N-03: log_sensitive_operation with normal dict

        // Given: A dict with normal values
        // When: Logging sensitive operation
        // Then: Values are passed through (or sanitized if needed)
        """
        details = {
            "operation_type": "extract",
            "count": 5,
            "status": "success",
        }

        with patch.object(secure_logger, "_logger") as mock_logger:
            secure_logger.log_sensitive_operation("test_op", details)

            mock_logger.info.assert_called_once()
            call_kwargs = mock_logger.info.call_args[1]

            assert call_kwargs["operation"] == "test_op"
            assert call_kwargs["details"]["count"] == 5


# ============================================================================
# SecureLogger Abnormal Cases (TC-A-01 to TC-A-04)
# ============================================================================


class TestSecureLoggerAbnormal:
    """Test SecureLogger abnormal/error cases."""

    def test_log_llm_io_with_prompt_content(self, secure_logger: SecureLogger) -> None:
        """
        TC-A-01: log_llm_io with prompt-like content

        // Given: Input containing LYRA tag patterns
        // When: Logging LLM I/O
        // Then: Content is masked with [MASKED]
        """
        input_text = "This is <LYRA-abc123> system instruction text"

        with patch.object(secure_logger, "_logger") as mock_logger:
            secure_logger.log_llm_io("test", input_text=input_text)

            call_kwargs = mock_logger.debug.call_args[1]

            assert "[MASKED]" in call_kwargs["input"]["preview"]
            assert call_kwargs["input"]["had_sensitive"] is True

    def test_log_llm_io_with_path_content(self, secure_logger: SecureLogger) -> None:
        """
        TC-A-02: log_llm_io with path-like content

        // Given: Input containing file paths
        // When: Logging LLM I/O
        // Then: Paths are masked with [PATH]
        """
        input_text = "Error in file /home/user/secret/config.py"

        with patch.object(secure_logger, "_logger") as mock_logger:
            secure_logger.log_llm_io("test", input_text=input_text)

            call_kwargs = mock_logger.debug.call_args[1]

            assert "[PATH]" in call_kwargs["input"]["preview"]
            assert call_kwargs["input"]["had_sensitive"] is True

    def test_log_exception_with_stack_trace(self, secure_logger: SecureLogger) -> None:
        """
        TC-A-03: log_exception with stack trace

        // Given: An exception message containing stack trace
        // When: Logging the exception
        // Then: Trace is removed from sanitized message
        """
        try:
            raise ValueError(
                "Error occurred\n"
                "Traceback (most recent call last):\n"
                '  File "/home/user/test.py", line 10, in test_func\n'
                "    raise ValueError"
            )
        except Exception as e:
            result = secure_logger.log_exception(e)

            assert "Traceback" not in result.sanitized_message
            assert "/home/user" not in result.sanitized_message

    def test_log_exception_with_file_path(self, secure_logger: SecureLogger) -> None:
        """
        TC-A-04: log_exception with file path

        // Given: An exception containing file paths
        // When: Logging the exception
        // Then: Paths are removed/masked
        """
        try:
            raise FileNotFoundError("Cannot open /home/statuser/lyra/secrets.txt")
        except Exception as e:
            result = secure_logger.log_exception(e)

            assert "/home/statuser" not in result.sanitized_message


# ============================================================================
# SecureLogger Boundary Cases (TC-B-01 to TC-B-03)
# ============================================================================


class TestSecureLoggerBoundary:
    """Test SecureLogger boundary cases."""

    def test_log_llm_io_empty_string(self, secure_logger: SecureLogger) -> None:
        """
        TC-B-01: log_llm_io with empty string

        // Given: Empty input text
        // When: Logging LLM I/O
        // Then: No error, length=0
        """
        with patch.object(secure_logger, "_logger") as mock_logger:
            secure_logger.log_llm_io("test", input_text="", output_text="")

            call_kwargs = mock_logger.debug.call_args[1]

            assert call_kwargs["input"]["length"] == 0
            assert call_kwargs["output"]["length"] == 0

    def test_log_llm_io_very_long_text(self, secure_logger: SecureLogger) -> None:
        """
        TC-B-02: log_llm_io with very long text (10000 chars)

        // Given: Very long input text
        // When: Logging LLM I/O
        // Then: Preview is truncated to MAX_PREVIEW_LENGTH
        """
        long_text = "A" * 10000

        with patch.object(secure_logger, "_logger") as mock_logger:
            secure_logger.log_llm_io("test", input_text=long_text)

            call_kwargs = mock_logger.debug.call_args[1]

            assert call_kwargs["input"]["length"] == 10000
            # Preview should be truncated + "..."
            assert len(call_kwargs["input"]["preview"]) <= MAX_PREVIEW_LENGTH + 3
            assert call_kwargs["input"]["preview"].endswith("...")

    def test_log_llm_io_none_input(self, secure_logger: SecureLogger) -> None:
        """
        TC-B-03: log_llm_io with None input

        // Given: None as input text
        // When: Logging LLM I/O
        // Then: No 'input' key in log data
        """
        with patch.object(secure_logger, "_logger") as mock_logger:
            secure_logger.log_llm_io("test", input_text=None, output_text="response")

            call_kwargs = mock_logger.debug.call_args[1]

            assert "input" not in call_kwargs
            assert "output" in call_kwargs


# ============================================================================
# AuditLogger Normal Cases (TC-N-04 to TC-N-06)
# ============================================================================


class TestAuditLoggerNormal:
    """Test AuditLogger normal cases."""

    def test_log_security_event_prompt_leakage(self, audit_logger: AuditLogger) -> None:
        """
        TC-N-04: log_security_event with PROMPT_LEAKAGE

        // Given: A prompt leakage event
        // When: Logging security event
        // Then: Event is logged with correct severity
        """
        with patch.object(audit_logger, "_logger") as mock_logger:
            event_id = audit_logger.log_security_event(
                SecurityEventType.PROMPT_LEAKAGE_DETECTED,
                severity="high",
                details={"source": "llm_extract", "fragment_count": 2},
            )

            mock_logger.warning.assert_called_once()
            call_kwargs = mock_logger.warning.call_args[1]

            assert event_id.startswith("sec_")
            assert call_kwargs["event_type"] == "prompt_leakage_detected"
            assert call_kwargs["severity"] == "high"

    def test_log_prompt_leakage_helper(self, audit_logger: AuditLogger) -> None:
        """
        TC-N-05: log_prompt_leakage helper

        // Given: Leakage details
        // When: Using log_prompt_leakage helper
        // Then: Correct event type and fragment count
        """
        with patch.object(audit_logger, "_logger") as mock_logger:
            event_id = audit_logger.log_prompt_leakage(
                source="llm_extract",
                fragment_count=3,
            )

            assert event_id.startswith("sec_")
            call_kwargs = mock_logger.warning.call_args[1]
            assert call_kwargs["event_type"] == "prompt_leakage_detected"
            assert call_kwargs["details"]["fragment_count"] == 3

    def test_log_dangerous_pattern_helper(self, audit_logger: AuditLogger) -> None:
        """
        TC-N-06: log_dangerous_pattern helper

        // Given: Dangerous patterns detected
        // When: Using log_dangerous_pattern helper
        // Then: Correct event type and pattern count
        """
        with patch.object(audit_logger, "_logger") as mock_logger:
            event_id = audit_logger.log_dangerous_pattern(
                patterns=["ignore previous", "system prompt"],
                source="user_input",
            )

            assert event_id.startswith("sec_")
            call_kwargs = mock_logger.info.call_args[1]
            assert call_kwargs["event_type"] == "dangerous_pattern_detected"
            assert call_kwargs["details"]["pattern_count"] == 2


# ============================================================================
# AuditLogger Abnormal and Boundary Cases (TC-A-05, TC-B-04)
# ============================================================================


class TestAuditLoggerAbnormalBoundary:
    """Test AuditLogger abnormal and boundary cases."""

    def test_log_security_event_long_details(self, audit_logger: AuditLogger) -> None:
        """
        TC-A-05: log_security_event with long details

        // Given: Details with very long string values
        // When: Logging security event
        // Then: Long values are sanitized (length indicator)
        """
        long_value = "A" * 100

        with patch.object(audit_logger, "_logger") as mock_logger:
            audit_logger.log_security_event(
                SecurityEventType.UNKNOWN_FIELD_REMOVED,
                details={"long_field": long_value},
            )

            call_kwargs = mock_logger.info.call_args[1]

            # Long strings should be replaced with length indicator
            assert call_kwargs["details"]["long_field"] == "[100 chars]"

    def test_log_security_event_none_details(self, audit_logger: AuditLogger) -> None:
        """
        TC-B-04: log_security_event with None details

        // Given: None as details
        // When: Logging security event
        // Then: No 'details' key in log
        """
        with patch.object(audit_logger, "_logger") as mock_logger:
            audit_logger.log_security_event(
                SecurityEventType.OUTPUT_TRUNCATED,
                details=None,
            )

            call_kwargs = mock_logger.info.call_args[1]
            assert "details" not in call_kwargs


# ============================================================================
# Structlog Processor Tests (TC-N-07, TC-A-06, TC-A-07)
# ============================================================================


class TestStructlogProcessor:
    """Test structlog sanitization processor."""

    def test_processor_normal_text(self) -> None:
        """
        TC-N-07: Event dict with normal text field

        // Given: Event dict with normal short text
        // When: Processing through sanitize_log_processor
        // Then: No modification
        """
        event_dict = {
            "event": "test_event",
            "text": "This is normal text",
            "count": 5,
        }

        result = sanitize_log_processor(None, "info", event_dict)

        assert result["text"] == "This is normal text"

    def test_processor_prompt_like_text(self) -> None:
        """
        TC-A-06: Event dict with prompt-like text

        // Given: Event dict with prompt-like content in text field
        // When: Processing through sanitize_log_processor
        // Then: Content is sanitized
        """
        event_dict = {
            "event": "test_event",
            "prompt": "This is LYRA-secret123 instruction",
        }

        result = sanitize_log_processor(None, "info", event_dict)

        assert "LYRA" not in result["prompt"]
        assert "[SANITIZED:" in result["prompt"]

    def test_processor_long_text(self) -> None:
        """
        TC-A-07: Event dict with long text (>500 chars)

        // Given: Event dict with long text
        // When: Processing through sanitize_log_processor
        // Then: Content is truncated
        """
        long_text = "A" * 600
        event_dict = {
            "event": "test_event",
            "content": long_text,
        }

        result = sanitize_log_processor(None, "info", event_dict)

        # Should be truncated with hash/len info
        assert len(result["content"]) < 600
        assert "hash=" in result["content"]
        assert "len=600" in result["content"]


# ============================================================================
# L7 Bug Fix Test (TC-N-08, TC-B-05)
# ============================================================================


class TestL7BugFix:
    """Test L7 duplicate processing bug fix."""

    def test_no_duplicate_processing(self) -> None:
        """
        TC-N-08: Response with LLM fields at multiple levels

        // Given: A response with LLM text fields in nested arrays
        // When: Sanitizing the response
        // Then: Each field is processed exactly once (no double counting)

        NOTE: Per ADR-0010, uses get_materials instead of search.
        """
        from src.mcp.response_sanitizer import ResponseSanitizer

        sanitizer = ResponseSanitizer()

        # Use schema-valid response structure for 'get_materials' tool
        # 'claims' contains objects with 'text' (LLM content field)
        response = {
            "ok": True,
            "task_id": "task_123",
            "query": "test query",
            "claims": [
                {
                    "id": "1",
                    "text": "Nested claim text 1",
                    "confidence": 0.9,
                    "evidence_count": 2,
                    "has_refutation": False,
                    "sources": [],
                },
                {
                    "id": "2",
                    "text": "Nested claim text 2",
                    "confidence": 0.8,
                    "evidence_count": 1,
                    "has_refutation": False,
                    "sources": [],
                },
            ],
            "fragments": [],
            "summary": {
                "total_claims": 2,
                "verified_claims": 2,
                "refuted_claims": 0,
                "primary_source_ratio": 0.0,
            },
        }

        result = sanitizer.sanitize_response(response, "get_materials")

        # Each LLM content field should be processed exactly once:
        # - "query" at top level = 1
        # - "text" in claims[0] = 1
        # - "text" in claims[1] = 1
        # Total = 3 (not 6 which would indicate double counting from before the fix)
        assert result.stats.llm_fields_processed == 3

    def test_stats_count_correctly(self) -> None:
        """
        TC-B-05: Verify stats.llm_fields_processed counts correctly

        // Given: A response with known number of LLM fields
        // When: Sanitizing the response
        // Then: llm_fields_processed matches actual field count
        """
        from src.mcp.response_sanitizer import ResponseSanitizer

        sanitizer = ResponseSanitizer()

        # Use schema-valid response structure for 'get_materials' tool
        # 'claims' array contains objects with 'text' (LLM content field)
        response = {
            "ok": True,
            "task_id": "task_123",
            "claims": [
                {"id": "c1", "text": "This is claim text", "confidence": 0.9, "support_count": 2},
            ],
            "fragments": [],
            "evidence_graph": None,
        }

        result = sanitizer.sanitize_response(response, "get_materials")

        # Should be exactly 1, not 2 (which would indicate double processing)
        assert result.stats.llm_fields_processed == 1


# ============================================================================
# Data Class Tests
# ============================================================================


class TestDataClasses:
    """Test data class functionality."""

    def test_llm_io_summary_to_dict(self) -> None:
        """Test LLMIOSummary.to_dict()."""
        summary = LLMIOSummary(
            content_hash="abc123def456",
            length=100,
            preview="Test preview...",
            had_sensitive_content=True,
        )

        result = summary.to_dict()

        assert result["hash"] == "abc123def456"
        assert result["length"] == 100
        assert result["preview"] == "Test preview..."
        assert result["had_sensitive"] is True

    def test_sanitized_exception_info_to_dict(self) -> None:
        """Test SanitizedExceptionInfo.to_dict()."""
        info = SanitizedExceptionInfo(
            exception_type="ValueError",
            sanitized_message="Invalid value",
            error_id="err_abc123",
        )

        result = info.to_dict()

        assert result["type"] == "ValueError"
        assert result["message"] == "Invalid value"
        assert result["error_id"] == "err_abc123"


# ============================================================================
# Module-level Function Tests
# ============================================================================


class TestModuleFunctions:
    """Test module-level convenience functions."""

    def test_get_secure_logger_without_name(self) -> None:
        """Test get_secure_logger returns singleton without name."""
        logger1 = get_secure_logger()
        logger2 = get_secure_logger()

        assert logger1 is logger2

    def test_get_secure_logger_with_name(self) -> None:
        """Test get_secure_logger creates new instance with name."""
        logger1 = get_secure_logger("module1")
        logger2 = get_secure_logger("module2")

        assert logger1 is not logger2
        assert logger1._name == "module1"
        assert logger2._name == "module2"

    def test_get_audit_logger_singleton(self) -> None:
        """Test get_audit_logger returns singleton."""
        logger1 = get_audit_logger()
        logger2 = get_audit_logger()

        assert logger1 is logger2


# ============================================================================
# Security Event Type Tests
# ============================================================================


class TestSecurityEventType:
    """Test SecurityEventType enum."""

    def test_all_event_types_have_values(self) -> None:
        """Test all event types have string values."""
        for event_type in SecurityEventType:
            assert isinstance(event_type.value, str)
            assert len(event_type.value) > 0

    def test_event_type_uniqueness(self) -> None:
        """Test all event type values are unique."""
        values = [e.value for e in SecurityEventType]
        assert len(values) == len(set(values))
