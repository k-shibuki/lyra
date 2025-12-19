"""
Tests for MCP Response Metadata (K.3-5, §4.4.1 L5).

Test Coverage:
- LancetMeta serialization
- ResponseMetaBuilder chain methods
- ClaimMeta with VerificationDetails
- attach_meta and create_minimal_meta helpers
"""

from datetime import datetime

from src.mcp.response_meta import (
    ClaimMeta,
    LancetMeta,
    ResponseMetaBuilder,
    SecurityWarning,
    VerificationDetails,
    VerificationStatus,
    attach_meta,
    create_minimal_meta,
    create_response_meta,
)


class TestVerificationDetails:
    """Tests for VerificationDetails dataclass."""

    def test_to_dict_default_values(self):
        """
        TC-N-01: VerificationDetails with default values.

        // Given: Default VerificationDetails
        // When: Converting to dict
        // Then: All fields present with defaults
        """
        details = VerificationDetails()
        result = details.to_dict()

        assert result["independent_sources"] == 0
        assert result["corroborating_claims"] == []
        assert result["contradicting_claims"] == []
        assert result["nli_scores"] == {}

    def test_to_dict_with_values(self):
        """
        TC-N-02: VerificationDetails with populated values.

        // Given: VerificationDetails with all fields set
        // When: Converting to dict
        // Then: All values serialized correctly
        """
        details = VerificationDetails(
            independent_sources=3,
            corroborating_claims=["claim_1", "claim_2"],
            contradicting_claims=["claim_3"],
            nli_scores={"supporting": 2, "refuting": 1},
        )
        result = details.to_dict()

        assert result["independent_sources"] == 3
        assert result["corroborating_claims"] == ["claim_1", "claim_2"]
        assert result["contradicting_claims"] == ["claim_3"]
        assert result["nli_scores"]["supporting"] == 2


class TestSecurityWarning:
    """Tests for SecurityWarning dataclass."""

    def test_to_dict_default_severity(self):
        """
        TC-N-03: SecurityWarning with default severity.

        // Given: SecurityWarning without explicit severity
        // When: Converting to dict
        // Then: Default severity is "warning"
        """
        warning = SecurityWarning(
            type="external_url",
            message="External URL detected",
        )
        result = warning.to_dict()

        assert result["type"] == "external_url"
        assert result["message"] == "External URL detected"
        assert result["severity"] == "warning"

    def test_to_dict_custom_severity(self):
        """
        TC-N-04: SecurityWarning with custom severity.

        // Given: SecurityWarning with critical severity
        // When: Converting to dict
        // Then: Custom severity preserved
        """
        warning = SecurityWarning(
            type="prompt_leakage",
            message="Prompt fragment detected",
            severity="critical",
        )
        result = warning.to_dict()

        assert result["severity"] == "critical"


class TestLancetMeta:
    """Tests for LancetMeta dataclass."""

    def test_to_dict_minimal(self):
        """
        TC-N-05: LancetMeta with minimal fields (empty lists).

        // Given: LancetMeta with default (empty) lists
        // When: Converting to dict
        // Then: Empty lists are excluded from output
        """
        meta = LancetMeta()
        result = meta.to_dict()

        assert "timestamp" in result
        assert result["data_quality"] == "normal"
        # Empty lists should not be included
        assert "security_warnings" not in result
        assert "blocked_domains" not in result
        assert "unverified_domains" not in result

    def test_to_dict_with_warnings(self):
        """
        TC-N-06: LancetMeta with security warnings.

        // Given: LancetMeta with security warnings
        // When: Converting to dict
        // Then: Warnings serialized as list of dicts
        """
        meta = LancetMeta(
            security_warnings=[
                SecurityWarning(type="test", message="Test warning"),
            ]
        )
        result = meta.to_dict()

        assert "security_warnings" in result
        assert len(result["security_warnings"]) == 1
        assert result["security_warnings"][0]["type"] == "test"

    def test_to_dict_with_domains(self):
        """
        TC-N-07: LancetMeta with blocked and unverified domains.

        // Given: LancetMeta with domain lists
        // When: Converting to dict
        // Then: Domain lists included in output
        """
        meta = LancetMeta(
            blocked_domains=["blocked.com"],
            unverified_domains=["unknown.com", "new.com"],
        )
        result = meta.to_dict()

        assert result["blocked_domains"] == ["blocked.com"]
        assert result["unverified_domains"] == ["unknown.com", "new.com"]

    def test_timestamp_is_iso_format(self):
        """
        TC-N-08: Timestamp is in ISO format.

        // Given: Default LancetMeta
        // When: Checking timestamp
        // Then: Timestamp is valid ISO format
        """
        meta = LancetMeta()
        # Should not raise
        datetime.fromisoformat(meta.timestamp.replace("Z", "+00:00"))


class TestClaimMeta:
    """Tests for ClaimMeta dataclass."""

    def test_to_dict_minimal(self):
        """
        TC-N-09: ClaimMeta with minimal required fields.

        // Given: ClaimMeta with only required fields
        // When: Converting to dict
        // Then: Required fields present, optional excluded
        """
        claim_meta = ClaimMeta(
            claim_id="claim_123",
            source_trust_level="academic",
        )
        result = claim_meta.to_dict()

        assert result["claim_id"] == "claim_123"
        assert result["source_trust_level"] == "academic"
        assert result["verification_status"] == "pending"
        assert "verification_details" not in result
        assert "source_domain" not in result

    def test_to_dict_with_all_fields(self):
        """
        TC-N-10: ClaimMeta with all fields populated.

        // Given: ClaimMeta with all optional fields
        // When: Converting to dict
        // Then: All fields serialized
        """
        claim_meta = ClaimMeta(
            claim_id="claim_456",
            source_trust_level="government",
            verification_status=VerificationStatus.VERIFIED,
            verification_details=VerificationDetails(independent_sources=2),
            source_domain="example.go.jp",
        )
        result = claim_meta.to_dict()

        assert result["claim_id"] == "claim_456"
        assert result["verification_status"] == "verified"
        assert result["source_domain"] == "example.go.jp"
        assert result["verification_details"]["independent_sources"] == 2


class TestResponseMetaBuilder:
    """Tests for ResponseMetaBuilder."""

    def test_builder_chain_methods(self):
        """
        TC-N-11: Builder methods return self for chaining.

        // Given: New ResponseMetaBuilder
        // When: Calling chain methods
        // Then: Each method returns self
        """
        builder = ResponseMetaBuilder()

        result = builder.add_security_warning("test", "Test")
        assert result is builder

        result = builder.add_blocked_domain("blocked.com")
        assert result is builder

        result = builder.add_unverified_domain("unknown.com")
        assert result is builder

        result = builder.set_data_quality("degraded")
        assert result is builder

    def test_build_empty(self):
        """
        TC-A-01: Build with no additions.

        // Given: Empty ResponseMetaBuilder
        // When: Building
        // Then: Minimal meta returned
        """
        builder = ResponseMetaBuilder()
        result = builder.build()

        assert "timestamp" in result
        assert result["data_quality"] == "normal"

    def test_build_with_warnings(self):
        """
        TC-N-12: Build with multiple security warnings.

        // Given: Builder with multiple warnings added
        // When: Building
        // Then: All warnings in output
        """
        builder = ResponseMetaBuilder()
        builder.add_security_warning("type1", "Message 1")
        builder.add_security_warning("type2", "Message 2", severity="critical")

        result = builder.build()

        assert len(result["security_warnings"]) == 2
        assert result["security_warnings"][1]["severity"] == "critical"

    def test_build_with_claims(self):
        """
        TC-N-13: Build with claim metadata.

        // Given: Builder with claim metas added
        // When: Building
        // Then: Claims array in output
        """
        builder = ResponseMetaBuilder()
        builder.add_claim_meta(
            ClaimMeta(
                claim_id="claim_1",
                source_trust_level="trusted",
            )
        )
        builder.add_claim_meta(
            ClaimMeta(
                claim_id="claim_2",
                source_trust_level="unverified",
            )
        )

        result = builder.build()

        assert "claims" in result
        assert len(result["claims"]) == 2
        assert result["claims"][0]["claim_id"] == "claim_1"

    def test_add_blocked_domain_deduplication(self):
        """
        TC-A-02: Duplicate blocked domains are deduplicated.

        // Given: Builder with same domain added twice
        // When: Building
        // Then: Domain appears only once
        """
        builder = ResponseMetaBuilder()
        builder.add_blocked_domain("blocked.com")
        builder.add_blocked_domain("blocked.com")

        result = builder.build()

        assert len(result["blocked_domains"]) == 1

    def test_add_unverified_domain_deduplication(self):
        """
        TC-A-03: Duplicate unverified domains are deduplicated.

        // Given: Builder with same domain added twice
        // When: Building
        // Then: Domain appears only once
        """
        builder = ResponseMetaBuilder()
        builder.add_unverified_domain("unknown.com")
        builder.add_unverified_domain("unknown.com")

        result = builder.build()

        assert len(result["unverified_domains"]) == 1


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_create_response_meta_returns_builder(self):
        """
        TC-N-14: create_response_meta returns new builder.

        // Given: Calling create_response_meta
        // When: Function called
        // Then: Returns ResponseMetaBuilder instance
        """
        builder = create_response_meta()
        assert isinstance(builder, ResponseMetaBuilder)

    def test_attach_meta_adds_key(self):
        """
        TC-B-01: attach_meta adds _lancet_meta key.

        // Given: Response dict and meta dict
        // When: Calling attach_meta
        // Then: Response has _lancet_meta key
        """
        response = {"ok": True, "data": "test"}
        meta = {"timestamp": "2024-01-01T00:00:00Z"}

        result = attach_meta(response, meta)

        assert result is response  # Modified in place
        assert "_lancet_meta" in result
        assert result["_lancet_meta"]["timestamp"] == "2024-01-01T00:00:00Z"

    def test_create_minimal_meta_structure(self):
        """
        TC-B-02: create_minimal_meta returns minimal structure.

        // Given: Calling create_minimal_meta
        // When: Function called
        // Then: Returns dict with timestamp and data_quality only
        """
        meta = create_minimal_meta()

        assert "timestamp" in meta
        assert meta["data_quality"] == "normal"
        assert len(meta) == 2  # Only timestamp and data_quality


class TestVerificationStatusEnum:
    """Tests for VerificationStatus enum."""

    def test_enum_values(self):
        """
        TC-N-15: VerificationStatus enum values.

        // Given: VerificationStatus enum
        // When: Accessing values
        // Then: All expected values present
        """
        assert VerificationStatus.PENDING.value == "pending"
        assert VerificationStatus.VERIFIED.value == "verified"
        assert VerificationStatus.REJECTED.value == "rejected"

    def test_enum_is_str(self):
        """
        TC-N-16: VerificationStatus is string enum.

        // Given: VerificationStatus enum member
        // When: Accessing value
        // Then: Value is string
        """
        status = VerificationStatus.VERIFIED
        assert status.value == "verified"
        assert isinstance(status.value, str)


class TestBoundaryAndEdgeCases:
    """Boundary value and edge case tests."""

    def test_claim_meta_empty_claim_id(self):
        """
        TC-A-04: ClaimMeta with empty claim_id.

        // Given: ClaimMeta with empty string claim_id
        // When: Creating and serializing
        // Then: Empty string preserved (no validation error)
        """
        claim_meta = ClaimMeta(
            claim_id="",
            source_trust_level="unverified",
        )
        result = claim_meta.to_dict()

        assert result["claim_id"] == ""

    def test_security_warning_empty_fields(self):
        """
        TC-A-05: SecurityWarning with empty type and message.

        // Given: SecurityWarning with empty strings
        // When: Creating and serializing
        // Then: Empty strings preserved
        """
        warning = SecurityWarning(type="", message="")
        result = warning.to_dict()

        assert result["type"] == ""
        assert result["message"] == ""

    def test_verification_details_negative_sources(self):
        """
        TC-A-06: VerificationDetails with negative independent_sources.

        // Given: VerificationDetails with negative value
        // When: Creating and serializing
        // Then: Value preserved (no validation at dataclass level)
        """
        details = VerificationDetails(independent_sources=-1)
        result = details.to_dict()

        assert result["independent_sources"] == -1

    def test_lancet_meta_many_warnings(self):
        """
        TC-B-03: LancetMeta with many security warnings.

        // Given: LancetMeta with 100 warnings
        // When: Converting to dict
        // Then: All warnings serialized
        """
        warnings = [SecurityWarning(type=f"type_{i}", message=f"Message {i}") for i in range(100)]
        meta = LancetMeta(security_warnings=warnings)
        result = meta.to_dict()

        assert len(result["security_warnings"]) == 100

    def test_attach_meta_modifies_response_in_place(self):
        """
        TC-B-04: attach_meta modifies response in place.

        // Given: Response dict
        // When: Attaching meta
        // Then: Original dict modified, returned same reference
        """
        response = {"ok": True}
        meta = {"test": "value"}

        result = attach_meta(response, meta)

        assert result is response
        assert response["_lancet_meta"] == meta

    def test_builder_add_claim_meta_returns_self(self):
        """
        TC-N-17: add_claim_meta returns self for chaining.

        // Given: Builder
        // When: Adding claim meta
        // Then: Returns self
        """
        builder = ResponseMetaBuilder()
        claim = ClaimMeta(claim_id="test", source_trust_level="unverified")

        result = builder.add_claim_meta(claim)

        assert result is builder

    def test_verification_details_empty_lists(self):
        """
        TC-A-07: VerificationDetails with explicitly empty lists.

        // Given: VerificationDetails with empty collections
        // When: Serializing
        // Then: Empty collections in output
        """
        details = VerificationDetails(
            independent_sources=0,
            corroborating_claims=[],
            contradicting_claims=[],
            nli_scores={},
        )
        result = details.to_dict()

        assert result["corroborating_claims"] == []
        assert result["contradicting_claims"] == []
        assert result["nli_scores"] == {}

    def test_claim_meta_all_verification_statuses(self):
        """
        TC-A-08: ClaimMeta with each verification status.

        // Given: ClaimMeta with each status
        // When: Serializing
        // Then: Status value correct
        """
        for status in VerificationStatus:
            claim = ClaimMeta(
                claim_id="test",
                source_trust_level="unverified",
                verification_status=status,
            )
            result = claim.to_dict()
            assert result["verification_status"] == status.value

    def test_data_quality_values(self):
        """
        TC-A-09: LancetMeta with different data_quality values.

        // Given: LancetMeta with various quality values
        // When: Serializing
        // Then: Values preserved
        """
        for quality in ["normal", "degraded", "limited"]:
            meta = LancetMeta(data_quality=quality)
            result = meta.to_dict()
            assert result["data_quality"] == quality
