"""
Tests for DomainPolicyManager ( Domain Policy Externalization).

Test design follows .1 Test Code Quality Standards:
- No conditional assertions (.1.1)
- Specific assertions with concrete values (.1.2)
- Realistic test data (.1.3)
- AAA pattern (.1.5)

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-DP-N-01 | Default values | Equivalence – normal | Correct defaults | - |
| TC-DP-N-02 | Custom values | Equivalence – normal | Values stored | - |
| TC-DP-B-01 | QPS too low | Boundary – min | ValueError | - |
| TC-DP-B-02 | QPS too high | Boundary – max | ValueError | - |
| TC-DP-B-03 | headful_ratio <0 | Boundary – min | ValueError | - |
| TC-DP-B-04 | headful_ratio >1 | Boundary – max | ValueError | - |
| TC-AL-N-01 | Valid entry | Equivalence – normal | Entry created | - |
| TC-AL-N-02 | Domain normalized | Equivalence – normal | Lowercase | - |
| TC-AL-B-01 | Empty domain | Boundary – empty | ValueError | - |
| TC-AL-B-02 | Short domain | Boundary – min | ValueError | - |
| TC-GL-N-01 | Valid pattern | Equivalence – normal | Pattern stored | - |
| TC-GL-N-02 | Skip with reason | Equivalence – normal | Reason stored | - |
| TC-DL-N-01 | Valid entry | Equivalence – normal | Entry created | - |
| TC-CF-N-01 | Full config | Equivalence – normal | All parsed | - |
| TC-CF-N-02 | Empty config | Equivalence – normal | Uses defaults | - |
| TC-PO-N-01 | PRIMARY weight | Equivalence – normal | 1.0 | - |
| TC-PO-N-02 | GOVERNMENT weight | Equivalence – normal | 0.95 | - |
| TC-PO-N-03 | ACADEMIC weight | Equivalence – normal | 0.90 | - |
| TC-PO-N-04 | UNKNOWN weight | Equivalence – normal | 0.30 | - |
| TC-PO-N-05 | min_interval | Equivalence – normal | 1/QPS | - |
| TC-PO-N-06 | cooldown active | Equivalence – normal | is_in_cooldown=True | - |
| TC-PO-N-07 | cooldown expired | Equivalence – normal | is_in_cooldown=False | - |
| TC-PO-N-08 | cooldown None | Equivalence – normal | is_in_cooldown=False | - |
| TC-PO-N-09 | to_dict | Equivalence – normal | All fields | - |
| TC-ML-N-01 | Load valid config | Equivalence – normal | Correct values | - |
| TC-ML-N-02 | Load missing config | Equivalence – normal | Uses defaults | - |
| TC-ML-N-03 | Reload clears cache | Equivalence – normal | Cache empty | - |
| TC-LU-N-01 | Allowlist exact | Equivalence – normal | Policy found | - |
| TC-LU-N-02 | Allowlist suffix | Equivalence – normal | Policy found | - |
| TC-LU-N-03 | Graylist pattern | Equivalence – normal | Policy found | - |
| TC-LU-N-04 | Graylist skip | Equivalence – normal | skip=True | - |
| TC-LU-N-05 | Denylist | Equivalence – normal | skip=True | - |
| TC-LU-N-06 | Cloudflare site | Equivalence – normal | headful_required | - |
| TC-LU-N-07 | Default policy | Equivalence – normal | Default values | - |
| TC-LU-N-08 | Normalized domain | Equivalence – normal | All match | - |
| TC-CV-N-01 | should_skip deny | Equivalence – normal | True | - |
| TC-CV-N-02 | should_skip allow | Equivalence – normal | False | - |
| TC-CV-N-03 | get_domain_category | Equivalence – normal | Correct category | - |
| TC-CV-N-04 | get_category_weight | Equivalence – normal | Correct weight | - |
| TC-CV-N-05 | get_qps_limit | Equivalence – normal | Correct QPS | - |
| TC-IS-N-01 | Template exists | Equivalence – normal | Template returned | - |
| TC-IS-A-01 | Template missing | Equivalence – abnormal | None | - |
| TC-IS-N-02 | has_internal allow | Equivalence – normal | True | - |
| TC-IS-N-03 | has_internal template | Equivalence – normal | True | - |
| TC-IS-A-02 | has_internal unknown | Equivalence – abnormal | False | - |
| TC-LS-N-01 | All allowlist | Equivalence – normal | All domains | - |
| TC-LS-N-02 | By trust GOVERNMENT | Equivalence – normal | Filtered list | - |
| TC-LS-N-03 | By trust ACADEMIC | Equivalence – normal | Filtered list | - |
| TC-LN-N-01 | Update state | Equivalence – normal | Cache updated | - |
| TC-LN-N-02 | Update cooldown | Equivalence – normal | is_in_cooldown=True | - |
| TC-CH-N-01 | Cache hit | Equivalence – normal | No recompute | - |
| TC-CH-N-02 | Clear cache | Equivalence – normal | Cache empty | - |
| TC-CH-N-03 | Cache stats | Equivalence – normal | All fields | - |
| TC-HR-N-01 | Hot reload detect | Equivalence – normal | Config updated | - |
| TC-HR-N-02 | Callback called | Equivalence – normal | Callback fired | - |
| TC-HR-N-03 | Remove callback | Equivalence – normal | Not called | - |
| TC-HR-N-04 | user_override removed | Equivalence – normal | Domain reverts to allowlist/default | Wiring test |
| TC-HR-A-01 | Callback throws exception | Equivalence – abnormal | Other callbacks still called, reload completes | Error logged |
| TC-HR-A-02 | YAML parse error on reload | Equivalence – abnormal | Previous config retained | Error logged |
| TC-HR-B-01 | watch_interval=0 | Boundary – min | Every config access checks file | May impact performance |
| TC-HR-B-02 | enable_hot_reload=False + manual reload() | Boundary – disabled | Manual reload works | Hot-reload disabled only affects auto-check |
| TC-MF-N-01 | Singleton | Equivalence – normal | Same instance | - |
| TC-MF-N-02 | Reset creates new | Equivalence – normal | Different instance | - |
| TC-PM-N-01 | Exact match | Equivalence – normal | Found | - |
| TC-PM-N-02 | Glob wildcard | Equivalence – normal | Found | - |
| TC-PM-N-03 | Nested subdomain | Equivalence – normal | Found | - |
| TC-PM-N-04 | Suffix match | Equivalence – normal | Found | - |
| TC-PM-A-01 | No partial match | Equivalence – abnormal | Default used | - |
| TC-TP-N-01 | Trust hierarchy | Equivalence – normal | Correct order | - |
| TC-RP-N-01 | Denylist priority | Equivalence – normal | Denylist wins | - |
| TC-RP-N-02 | Cloudflare settings | Equivalence – normal | Applied to allow | - |
| TC-SE-N-01 | Default values | Equivalence – normal | Correct defaults | - |
| TC-SE-N-02 | Custom values | Equivalence – normal | Values stored | - |
| TC-SE-N-03 | default_min_interval | Equivalence – normal | 1/QPS | - |
| TC-SE-N-04 | site_search_interval | Equivalence – normal | 1/QPS | - |
| TC-SE-B-01 | QPS too low | Boundary – min | ValueError | - |
| TC-SE-B-02 | QPS too high | Boundary – max | ValueError | - |
| TC-PB-N-01 | Default entry | Equivalence – normal | Values set | - |
| TC-PB-N-02 | Custom entry | Equivalence – normal | Values stored | - |
| TC-PB-N-03 | All bounds exist | Equivalence – normal | All parameters | - |
| TC-PB-N-04 | engine_weight default | Equivalence – normal | Correct values | - |
| TC-PB-N-05 | domain_qps default | Equivalence – normal | Correct values | - |
| TC-SA-N-01 | get_search_engine_policy | Equivalence – normal | Schema returned | - |
| TC-SA-N-02 | get_search_engine_qps | Equivalence – normal | Correct value | - |
| TC-SA-N-03 | get_min_interval | Equivalence – normal | Correct value | - |
| TC-SA-N-04 | get_site_search_qps | Equivalence – normal | Correct value | - |
| TC-SA-N-05 | get_site_search_interval | Equivalence – normal | Correct value | - |
| TC-SA-N-06 | get_cooldown_min | Equivalence – normal | Correct value | - |
| TC-SA-N-07 | get_cooldown_max | Equivalence – normal | Correct value | - |
| TC-SA-N-08 | get_failure_threshold | Equivalence – normal | Correct value | - |
| TC-BA-N-01 | get_policy_bounds | Equivalence – normal | Schema returned | - |
| TC-BA-N-02 | get_bounds engine_weight | Equivalence – normal | Correct values | - |
| TC-BA-N-03 | get_bounds domain_qps | Equivalence – normal | Correct values | - |
| TC-BA-A-01 | get_bounds unknown | Equivalence – abnormal | None | - |
| TC-FB-N-01 | Missing SE policy | Equivalence – normal | Defaults used | - |
| TC-FB-N-02 | Missing bounds | Equivalence – normal | Defaults used | - |
"""

from collections.abc import Generator

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from src.utils.domain_policy import (
    AllowlistEntrySchema,
    DefaultPolicySchema,
    DenylistEntrySchema,
    DomainCategory,
    DomainPolicy,
    DomainPolicyConfigSchema,
    DomainPolicyManager,
    GraylistEntrySchema,
    InternalSearchTemplateSchema,
    PolicyBoundsEntrySchema,
    PolicyBoundsSchema,
    SearchEnginePolicySchema,
    SkipReason,
    UserOverrideEntrySchema,
    get_domain_policy_manager,
    reset_domain_policy_manager,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_config_yaml() -> str:
    """Sample domains.yaml content for testing."""
    return """
default_policy:
  qps: 0.2
  concurrent: 1
  headful_ratio: 0.1
  tor_allowed: true
  cooldown_minutes: 60
  max_retries: 3
  domain_category: "unverified"
  max_requests_per_day: 200
  max_pages_per_day: 100

search_engine_policy:
  default_qps: 0.25
  site_search_qps: 0.1
  cooldown_min: 30
  cooldown_max: 120
  failure_threshold: 2

policy_bounds:
  engine_weight:
    min: 0.1
    max: 2.0
    default: 1.0
    step_up: 0.1
    step_down: 0.2
  engine_qps:
    min: 0.1
    max: 0.5
    default: 0.25
    step_up: 0.05
    step_down: 0.1
  domain_qps:
    min: 0.05
    max: 0.3
    default: 0.2
    step_up: 0.02
    step_down: 0.05

allowlist:
  - domain: "go.jp"
    domain_category: "government"
    qps: 0.15
  - domain: "arxiv.org"
    domain_category: "academic"
    internal_search: true
    qps: 0.25
  - domain: "wikipedia.org"
    domain_category: "trusted"
    qps: 0.5
    headful_ratio: 0
    max_requests_per_day: 500
    max_pages_per_day: 250
  - domain: "example-primary.com"
    domain_category: "primary"
    qps: 0.1

user_overrides: []

graylist:
  - domain_pattern: "*.medium.com"
    domain_category: "unverified"
    qps: 0.1
  - domain_pattern: "*.twitter.com"
    skip: true
    reason: "social_media"
  - domain_pattern: "*.nikkei.com"
    headful_ratio: 0.5
    cooldown_minutes: 120

denylist:
  - domain_pattern: "*.blogspot.com"
    reason: "low_quality_aggregator"
  - domain_pattern: "spam-site.example"
    reason: "ad_heavy"

cloudflare_sites:
  - domain_pattern: "*.protected-site.com"
    headful_required: true
    tor_blocked: true

internal_search_templates:
  arxiv:
    domain: "arxiv.org"
    search_input: "input[name='query']"
    search_button: "button[type='submit']"
    results_selector: ".arxiv-result"
  pubmed:
    domain: "pubmed.ncbi.nlm.nih.gov"
    search_input: "#id_term"
    search_button: "button.search-btn"
    results_selector: ".docsum-content"
"""


@pytest.fixture
def temp_config_file(sample_config_yaml: str, tmp_path: Path) -> Path:
    """Create temporary config file for testing."""
    config_path = tmp_path / "domains.yaml"
    config_path.write_text(sample_config_yaml, encoding="utf-8")
    return config_path


@pytest.fixture
def policy_manager(temp_config_file: Path) -> Generator[DomainPolicyManager, None, None]:
    """Create DomainPolicyManager with test config."""
    reset_domain_policy_manager()
    manager = DomainPolicyManager(
        config_path=temp_config_file,
        enable_hot_reload=False,  # Disable for deterministic tests
    )
    yield manager
    reset_domain_policy_manager()


@pytest.fixture(autouse=True)
def reset_singleton() -> Generator[None, None, None]:
    """Reset singleton before and after each test."""
    reset_domain_policy_manager()
    yield
    reset_domain_policy_manager()


# =============================================================================
# Schema Validation Tests
# =============================================================================


class TestDefaultPolicySchema:
    """Tests for DefaultPolicySchema validation."""

    def test_default_values(self) -> None:
        """Verify default policy has expected default values."""
        # Arrange & Act
        schema = DefaultPolicySchema()

        # Then
        assert schema.qps == 0.2
        assert schema.concurrent == 1
        assert schema.headful_ratio == 0.1
        assert schema.tor_allowed is True
        assert schema.cooldown_minutes == 60
        assert schema.max_retries == 3
        assert schema.domain_category == DomainCategory.UNVERIFIED
        # Daily budget limits (ADR-0006 - Problem 11)
        assert schema.max_requests_per_day == 200
        assert schema.max_pages_per_day == 100

    def test_custom_values(self) -> None:
        """Verify schema accepts valid custom values."""
        # Arrange & Act
        schema = DefaultPolicySchema(
            qps=0.5,
            concurrent=3,
            headful_ratio=0.3,
            tor_allowed=False,
            cooldown_minutes=120,
            max_retries=5,
            domain_category=DomainCategory.GOVERNMENT,
            max_requests_per_day=500,
            max_pages_per_day=250,
        )

        # Then
        assert schema.qps == 0.5
        assert schema.concurrent == 3
        assert schema.headful_ratio == 0.3
        assert schema.tor_allowed is False
        assert schema.cooldown_minutes == 120
        assert schema.max_retries == 5
        assert schema.domain_category == DomainCategory.GOVERNMENT
        # Daily budget limits (ADR-0006 - Problem 11)
        assert schema.max_requests_per_day == 500
        assert schema.max_pages_per_day == 250

    def test_qps_validation_range(self) -> None:
        """Verify QPS validation rejects out-of-range values."""
        # Then - too low
        with pytest.raises(ValueError):
            DefaultPolicySchema(qps=0.001)

        # Then - too high
        with pytest.raises(ValueError):
            DefaultPolicySchema(qps=3.0)

    def test_headful_ratio_validation_range(self) -> None:
        """Verify headful_ratio validation enforces [0, 1] range."""
        # Then - negative
        with pytest.raises(ValueError):
            DefaultPolicySchema(headful_ratio=-0.1)

        # Then - over 1
        with pytest.raises(ValueError):
            DefaultPolicySchema(headful_ratio=1.5)


class TestAllowlistEntrySchema:
    """Tests for AllowlistEntrySchema validation."""

    def test_valid_entry(self) -> None:
        """Verify valid allowlist entry is accepted."""
        # Arrange & Act
        entry = AllowlistEntrySchema(
            domain="example.go.jp",
            domain_category=DomainCategory.GOVERNMENT,
            internal_search=True,
            qps=0.15,
        )

        # Then
        assert entry.domain == "example.go.jp"
        assert entry.domain_category == DomainCategory.GOVERNMENT
        assert entry.internal_search is True
        assert entry.qps == 0.15

    def test_domain_normalization(self) -> None:
        """Verify domain is normalized to lowercase."""
        # Arrange & Act
        entry = AllowlistEntrySchema(domain="EXAMPLE.COM")

        # Then
        assert entry.domain == "example.com"

    def test_empty_domain_rejected(self) -> None:
        """Verify empty domain is rejected."""
        with pytest.raises(ValueError):
            AllowlistEntrySchema(domain="")

    def test_short_domain_rejected(self) -> None:
        """Verify single-character domain is rejected."""
        with pytest.raises(ValueError):
            AllowlistEntrySchema(domain="x")

    def test_daily_budget_fields(self) -> None:
        """Verify daily budget fields are accepted (ADR-0006 - Problem 11)."""
        # Arrange & Act
        entry = AllowlistEntrySchema(
            domain="example.com",
            max_requests_per_day=500,
            max_pages_per_day=250,
        )

        # Then
        assert entry.max_requests_per_day == 500
        assert entry.max_pages_per_day == 250

    def test_daily_budget_defaults_none(self) -> None:
        """Verify daily budget fields default to None (use global default)."""
        # Arrange & Act
        entry = AllowlistEntrySchema(domain="example.com")

        # Then
        assert entry.max_requests_per_day is None
        assert entry.max_pages_per_day is None


class TestUserOverrideEntrySchema:
    """Tests for UserOverrideEntrySchema validation."""

    def test_valid_exact_domain(self) -> None:
        """Verify valid exact domain entry is accepted."""
        # Arrange & Act
        entry = UserOverrideEntrySchema(
            domain="example.com",
            domain_category=DomainCategory.LOW,
            qps=0.3,
        )

        # Then
        assert entry.domain == "example.com"
        assert entry.domain_category == DomainCategory.LOW
        assert entry.qps == 0.3

    def test_domain_with_category_override(self) -> None:
        """Verify domain with category override is accepted."""
        # Arrange & Act
        entry = UserOverrideEntrySchema(
            domain="test.org",
            domain_category=DomainCategory.GOVERNMENT,
        )

        # Then
        assert entry.domain == "test.org"
        assert entry.domain_category == DomainCategory.GOVERNMENT

    def test_domain_with_qps_override(self) -> None:
        """Verify domain with QPS override is accepted."""
        # Arrange & Act
        entry = UserOverrideEntrySchema(domain="example.net", qps=0.5)

        # Then
        assert entry.domain == "example.net"
        assert entry.qps == 0.5

    def test_domain_with_all_fields(self) -> None:
        """Verify domain with all fields is accepted."""
        # Arrange & Act
        entry = UserOverrideEntrySchema(
            domain="full.example.com",
            domain_category=DomainCategory.ACADEMIC,
            qps=0.25,
            headful_ratio=0.2,
            tor_allowed=False,
            concurrent=2,
            cooldown_minutes=90,
            max_retries=5,
            max_requests_per_day=300,
            max_pages_per_day=150,
            reason="Manual review: false positive",
            added_at="2025-12-22",
        )

        # Then
        assert entry.domain == "full.example.com"
        assert entry.domain_category == DomainCategory.ACADEMIC
        assert entry.qps == 0.25
        assert entry.headful_ratio == 0.2
        assert entry.tor_allowed is False
        assert entry.concurrent == 2
        assert entry.cooldown_minutes == 90
        assert entry.max_retries == 5
        assert entry.max_requests_per_day == 300
        assert entry.max_pages_per_day == 150
        assert entry.reason == "Manual review: false positive"
        assert entry.added_at == "2025-12-22"

    def test_domain_normalization(self) -> None:
        """Verify domain is normalized to lowercase."""
        # Arrange & Act
        entry = UserOverrideEntrySchema(domain="EXAMPLE.COM")

        # Then
        assert entry.domain == "example.com"

    def test_empty_domain_rejected(self) -> None:
        """Verify empty domain is rejected."""
        # Then
        with pytest.raises(ValueError, match="Domain must be at least 2 characters"):
            UserOverrideEntrySchema(domain="")

    def test_short_domain_rejected(self) -> None:
        """Verify single-character domain is rejected."""
        # Then
        with pytest.raises(ValueError, match="Domain must be at least 2 characters"):
            UserOverrideEntrySchema(domain="x")

    def test_domain_with_wildcard_rejected(self) -> None:
        """Verify domain with wildcard is rejected (exact match only)."""
        # Then
        with pytest.raises(ValueError, match="user_overrides only supports exact domain match"):
            UserOverrideEntrySchema(domain="*.example.com")

    def test_domain_with_leading_dot_rejected(self) -> None:
        """Verify domain with leading dot is rejected (no suffix match)."""
        # Then
        with pytest.raises(ValueError, match="user_overrides only supports exact domain match"):
            UserOverrideEntrySchema(domain=".example.com")

    def test_qps_boundary_min(self) -> None:
        """Verify QPS at minimum boundary (0.01) is accepted."""
        # Given & When
        entry = UserOverrideEntrySchema(domain="example.com", qps=0.01)

        # Then
        assert entry.qps == 0.01

    def test_qps_boundary_max(self) -> None:
        """Verify QPS at maximum boundary (2.0) is accepted."""
        # Given & When
        entry = UserOverrideEntrySchema(domain="example.com", qps=2.0)

        # Then
        assert entry.qps == 2.0

    def test_qps_below_min_rejected(self) -> None:
        """Verify QPS below minimum (0.01) is rejected."""
        # Then
        with pytest.raises(ValueError):
            UserOverrideEntrySchema(domain="example.com", qps=0.001)

    def test_qps_above_max_rejected(self) -> None:
        """Verify QPS above maximum (2.0) is rejected."""
        # Then
        with pytest.raises(ValueError):
            UserOverrideEntrySchema(domain="example.com", qps=3.0)

    def test_headful_ratio_boundary_min(self) -> None:
        """Verify headful_ratio at minimum boundary (0.0) is accepted."""
        # Given & When
        entry = UserOverrideEntrySchema(domain="example.com", headful_ratio=0.0)

        # Then
        assert entry.headful_ratio == 0.0

    def test_headful_ratio_boundary_max(self) -> None:
        """Verify headful_ratio at maximum boundary (1.0) is accepted."""
        # Given & When
        entry = UserOverrideEntrySchema(domain="example.com", headful_ratio=1.0)

        # Then
        assert entry.headful_ratio == 1.0

    def test_headful_ratio_below_min_rejected(self) -> None:
        """Verify headful_ratio below minimum (0.0) is rejected."""
        # Then
        with pytest.raises(ValueError):
            UserOverrideEntrySchema(domain="example.com", headful_ratio=-0.1)

    def test_headful_ratio_above_max_rejected(self) -> None:
        """Verify headful_ratio above maximum (1.0) is rejected."""
        # Then
        with pytest.raises(ValueError):
            UserOverrideEntrySchema(domain="example.com", headful_ratio=1.5)


class TestGraylistEntrySchema:
    """Tests for GraylistEntrySchema validation."""

    def test_valid_pattern(self) -> None:
        """Verify valid graylist pattern is accepted."""
        # Arrange & Act
        entry = GraylistEntrySchema(
            domain_pattern="*.example.com",
            headful_ratio=0.5,
            skip=False,
        )

        # Then
        assert entry.domain_pattern == "*.example.com"
        assert entry.headful_ratio == 0.5
        assert entry.skip is False

    def test_skip_with_reason(self) -> None:
        """Verify skip entry with reason is accepted."""
        # Arrange & Act
        entry = GraylistEntrySchema(
            domain_pattern="*.twitter.com",
            skip=True,
            reason=SkipReason.SOCIAL_MEDIA,
        )

        # Then
        assert entry.skip is True
        assert entry.reason == SkipReason.SOCIAL_MEDIA


class TestDenylistEntrySchema:
    """Tests for DenylistEntrySchema validation."""

    def test_valid_entry(self) -> None:
        """Verify valid denylist entry is accepted."""
        # Arrange & Act
        entry = DenylistEntrySchema(
            domain_pattern="*.spam.com",
            reason=SkipReason.LOW_QUALITY_AGGREGATOR,
        )

        # Then
        assert entry.domain_pattern == "*.spam.com"
        assert entry.reason == SkipReason.LOW_QUALITY_AGGREGATOR


class TestDomainPolicyConfigSchema:
    """Tests for root config schema validation."""

    def test_full_config_parsing(self, sample_config_yaml: str) -> None:
        """Verify complete config YAML is parsed correctly."""
        # Given
        data = yaml.safe_load(sample_config_yaml)

        # Parse internal_search_templates specially
        if "internal_search_templates" in data:
            templates = {}
            for name, template_data in data["internal_search_templates"].items():
                templates[name] = InternalSearchTemplateSchema(**template_data)
            data["internal_search_templates"] = templates

        # When
        config = DomainPolicyConfigSchema(**data)

        # Then
        assert config.default_policy.qps == 0.2
        assert len(config.allowlist) == 4
        assert len(config.graylist) == 3
        assert len(config.denylist) == 2
        assert len(config.cloudflare_sites) == 1
        assert len(config.internal_search_templates) == 2

    def test_empty_config_uses_defaults(self) -> None:
        """Verify empty config uses default values."""
        # Arrange & Act
        config = DomainPolicyConfigSchema()

        # Then
        assert config.default_policy.qps == 0.2
        assert config.allowlist == []
        assert config.graylist == []
        assert config.denylist == []


# =============================================================================
# DomainPolicy Data Class Tests
# =============================================================================


class TestDomainPolicy:
    """Tests for DomainPolicy data class."""

    def test_category_weight_primary(self) -> None:
        """Verify PRIMARY trust level has weight 1.0."""
        # Arrange & Act
        policy = DomainPolicy(domain="gov.example", domain_category=DomainCategory.PRIMARY)

        # Then
        assert policy.category_weight == 1.0

    def test_category_weight_government(self) -> None:
        """Verify GOVERNMENT trust level has weight 0.95."""
        # Arrange & Act
        policy = DomainPolicy(domain="gov.example", domain_category=DomainCategory.GOVERNMENT)

        # Then
        assert policy.category_weight == 0.95

    def test_category_weight_academic(self) -> None:
        """Verify ACADEMIC trust level has weight 0.90."""
        # Arrange & Act
        policy = DomainPolicy(domain="uni.example", domain_category=DomainCategory.ACADEMIC)

        # Then
        assert policy.category_weight == 0.90

    def test_category_weight_unknown(self) -> None:
        """Verify UNKNOWN trust level has weight 0.30."""
        # Arrange & Act
        policy = DomainPolicy(domain="unknown.example", domain_category=DomainCategory.UNVERIFIED)

        # Then
        assert policy.category_weight == 0.30

    def test_min_request_interval(self) -> None:
        """Verify min_request_interval is calculated correctly from QPS."""
        # Arrange & Act
        policy = DomainPolicy(domain="example.com", qps=0.25)

        # Then
        assert policy.min_request_interval == 4.0  # 1 / 0.25

    def test_is_in_cooldown_true(self) -> None:
        """Verify is_in_cooldown returns True when cooldown is active."""
        # Given
        future_time = datetime.now(UTC) + timedelta(hours=1)
        policy = DomainPolicy(domain="example.com", cooldown_until=future_time)

        # Then
        assert policy.is_in_cooldown is True

    def test_is_in_cooldown_false_when_expired(self) -> None:
        """Verify is_in_cooldown returns False when cooldown has expired."""
        # Given
        past_time = datetime.now(UTC) - timedelta(hours=1)
        policy = DomainPolicy(domain="example.com", cooldown_until=past_time)

        # Then
        assert policy.is_in_cooldown is False

    def test_is_in_cooldown_false_when_none(self) -> None:
        """Verify is_in_cooldown returns False when no cooldown set."""
        # Given
        policy = DomainPolicy(domain="example.com", cooldown_until=None)

        # Then
        assert policy.is_in_cooldown is False

    def test_to_dict_contains_all_fields(self) -> None:
        """Verify to_dict includes all required fields."""
        # Given
        policy = DomainPolicy(
            domain="example.com",
            qps=0.2,
            domain_category=DomainCategory.GOVERNMENT,
        )

        # When
        result = policy.to_dict()

        # Then
        assert result["domain"] == "example.com"
        assert result["qps"] == 0.2
        assert result["domain_category"] == "government"
        assert "category_weight" in result
        assert "min_request_interval" in result
        assert "is_in_cooldown" in result
        # Daily budget limits (ADR-0006 - Problem 11)
        assert "max_requests_per_day" in result
        assert "max_pages_per_day" in result

    def test_daily_budget_defaults(self) -> None:
        """Verify DomainPolicy has correct daily budget defaults (ADR-0006 - Problem 11)."""
        # Given & When
        policy = DomainPolicy(domain="example.com")

        # Then
        assert policy.max_requests_per_day == 200
        assert policy.max_pages_per_day == 100

    def test_daily_budget_custom_values(self) -> None:
        """Verify DomainPolicy accepts custom daily budget values (ADR-0006 - Problem 11)."""
        # Given & When
        policy = DomainPolicy(
            domain="example.com",
            max_requests_per_day=500,
            max_pages_per_day=250,
        )

        # Then
        assert policy.max_requests_per_day == 500
        assert policy.max_pages_per_day == 250


# =============================================================================
# DomainPolicyManager Tests
# =============================================================================


class TestDomainPolicyManagerLoading:
    """Tests for DomainPolicyManager configuration loading."""

    def test_load_valid_config(self, policy_manager: DomainPolicyManager) -> None:
        """Verify valid config is loaded correctly."""
        # Then
        config = policy_manager.config
        assert config.default_policy.qps == 0.2
        assert len(config.allowlist) == 4
        assert len(config.graylist) == 3
        assert len(config.denylist) == 2

    def test_load_missing_config_uses_defaults(self, tmp_path: Path) -> None:
        """Verify missing config file results in default values."""
        # Given
        nonexistent_path = tmp_path / "nonexistent.yaml"

        # When
        manager = DomainPolicyManager(config_path=nonexistent_path)

        # Then
        assert manager.config.default_policy.qps == 0.2
        assert manager.config.allowlist == []

    def test_reload_clears_cache(self, policy_manager: DomainPolicyManager) -> None:
        """Verify reload clears the policy cache."""
        # Given - populate cache
        _ = policy_manager.get_policy("example.com")
        assert policy_manager.get_cache_stats()["cached_domains"] >= 1

        # When
        policy_manager.reload()

        # Then
        assert policy_manager.get_cache_stats()["cached_domains"] == 0


class TestDomainPolicyManagerLookup:
    """Tests for DomainPolicyManager policy lookup."""

    def test_get_policy_allowlist_exact_match(self, policy_manager: DomainPolicyManager) -> None:
        """Verify allowlist exact domain match returns correct policy."""
        # When
        policy = policy_manager.get_policy("arxiv.org")

        # Then
        assert policy.domain_category == DomainCategory.ACADEMIC
        assert policy.qps == 0.25
        assert policy.internal_search is True
        assert policy.source == "allowlist"

    def test_get_policy_allowlist_suffix_match(self, policy_manager: DomainPolicyManager) -> None:
        """Verify allowlist suffix match works (e.g., 'go.jp' matches 'example.go.jp')."""
        # When
        policy = policy_manager.get_policy("example.go.jp")

        # Then
        assert policy.domain_category == DomainCategory.GOVERNMENT
        assert policy.qps == 0.15
        assert policy.source == "allowlist"

    def test_get_policy_graylist_pattern_match(self, policy_manager: DomainPolicyManager) -> None:
        """Verify graylist pattern match returns correct policy."""
        # When
        policy = policy_manager.get_policy("user.medium.com")

        # Then
        assert policy.qps == 0.1
        assert policy.source == "graylist"

    def test_get_policy_graylist_skip(self, policy_manager: DomainPolicyManager) -> None:
        """Verify graylist skip entry sets skip=True."""
        # When
        policy = policy_manager.get_policy("api.twitter.com")

        # Then
        assert policy.skip is True
        assert policy.skip_reason == "social_media"
        assert policy.source == "graylist"

    def test_get_policy_denylist(self, policy_manager: DomainPolicyManager) -> None:
        """Verify denylist entry sets skip=True with highest priority."""
        # When
        policy = policy_manager.get_policy("myblog.blogspot.com")

        # Then
        assert policy.skip is True
        assert policy.skip_reason == "low_quality_aggregator"
        assert policy.source == "denylist"

    def test_get_policy_cloudflare_site(self, policy_manager: DomainPolicyManager) -> None:
        """Verify cloudflare site sets headful_required and tor_blocked."""
        # When
        policy = policy_manager.get_policy("api.protected-site.com")

        # Then
        assert policy.headful_required is True
        assert policy.tor_blocked is True
        assert policy.tor_allowed is False  # tor_blocked implies tor_allowed=False
        assert policy.source == "cloudflare"

    def test_get_policy_default(self, policy_manager: DomainPolicyManager) -> None:
        """Verify unknown domain returns default policy."""
        # When
        policy = policy_manager.get_policy("unknown-domain.example")

        # Then
        assert policy.qps == 0.2
        assert policy.domain_category == DomainCategory.UNVERIFIED
        assert policy.source == "default"

    def test_get_policy_normalized_domain(self, policy_manager: DomainPolicyManager) -> None:
        """Verify domain normalization (lowercase, www removal)."""
        # When
        policy1 = policy_manager.get_policy("WWW.ARXIV.ORG")
        policy2 = policy_manager.get_policy("www.arxiv.org")
        policy3 = policy_manager.get_policy("arxiv.org")

        # Then - all should match the allowlist entry
        assert policy1.domain_category == DomainCategory.ACADEMIC
        assert policy2.domain_category == DomainCategory.ACADEMIC
        assert policy3.domain_category == DomainCategory.ACADEMIC

    def test_get_policy_daily_budget_from_allowlist(
        self, policy_manager: DomainPolicyManager
    ) -> None:
        """Verify daily budget limits from allowlist are applied (ADR-0006 - Problem 11)."""
        # When - wikipedia.org has custom limits in config/domains.yaml
        policy = policy_manager.get_policy("wikipedia.org")

        # Then - should have custom limits from allowlist
        assert policy.max_requests_per_day == 500
        assert policy.max_pages_per_day == 250
        assert policy.source == "allowlist"

    def test_get_policy_daily_budget_default(self, policy_manager: DomainPolicyManager) -> None:
        """Verify unknown domain gets default daily budget limits (ADR-0006 - Problem 11)."""
        # When
        policy = policy_manager.get_policy("unknown-domain.example")

        # Then - should have default limits
        assert policy.max_requests_per_day == 200
        assert policy.max_pages_per_day == 100
        assert policy.source == "default"


class TestUserOverridesLookup:
    """Tests for user_overrides lookup functionality."""

    def test_get_policy_user_override_exact_match(self, tmp_path: Path) -> None:
        """Verify user_override exact domain match returns correct policy."""
        # Given
        config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
user_overrides:
  - domain: "override.example.com"
    domain_category: "low"
    qps: 0.3
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        policy = manager.get_policy("override.example.com")

        # Then
        assert policy.domain_category == DomainCategory.LOW
        assert policy.qps == 0.3
        assert policy.source == "user_override"

    def test_user_override_vs_allowlist_priority(self, tmp_path: Path) -> None:
        """Verify user_override takes precedence over allowlist for same domain."""
        # Given - same domain in both allowlist and user_overrides
        config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
allowlist:
  - domain: "conflict.example.com"
    domain_category: "trusted"
    qps: 0.5
user_overrides:
  - domain: "conflict.example.com"
    domain_category: "low"
    qps: 0.3
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        policy = manager.get_policy("conflict.example.com")

        # Then - user_override should win
        assert policy.domain_category == DomainCategory.LOW
        assert policy.qps == 0.3
        assert policy.source == "user_override"

    def test_user_override_vs_denylist_priority(self, tmp_path: Path) -> None:
        """Verify denylist takes precedence over user_override."""
        # Given - same domain in both denylist and user_overrides
        config = """
default_policy:
  qps: 0.2
denylist:
  - domain_pattern: "blocked.example.com"
    reason: "low_quality_aggregator"
user_overrides:
  - domain: "blocked.example.com"
    domain_category: "low"
    qps: 0.3
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        policy = manager.get_policy("blocked.example.com")

        # Then - denylist should win (skip=True)
        assert policy.skip is True
        assert policy.source == "denylist"

    def test_user_override_normalized_domain_match(self, tmp_path: Path) -> None:
        """Verify normalized domain (WWW.EXAMPLE.COM -> example.com) matches."""
        # Given
        config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
user_overrides:
  - domain: "example.com"
    domain_category: "low"
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When - query with uppercase and www prefix
        policy1 = manager.get_policy("WWW.EXAMPLE.COM")
        policy2 = manager.get_policy("www.example.com")
        policy3 = manager.get_policy("example.com")

        # Then - all should match the user_override entry
        assert policy1.domain_category == DomainCategory.LOW
        assert policy1.source == "user_override"
        assert policy2.domain_category == DomainCategory.LOW
        assert policy2.source == "user_override"
        assert policy3.domain_category == DomainCategory.LOW
        assert policy3.source == "user_override"

    def test_user_override_hot_reload_reflects_changes(self, tmp_path: Path) -> None:
        """Verify hot reload reflects user_override changes."""
        # Given - create initial config
        config_path = tmp_path / "domains.yaml"
        initial_config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
user_overrides: []
"""
        config_path.write_text(initial_config, encoding="utf-8")

        manager = DomainPolicyManager(
            config_path=config_path,
            watch_interval=0.1,  # Short interval for testing
            enable_hot_reload=True,
        )

        # Verify initial state
        policy = manager.get_policy("test.example.com")
        assert policy.domain_category == DomainCategory.UNVERIFIED
        assert policy.source == "default"

        # When - add user_override
        time.sleep(0.2)  # Ensure mtime changes
        updated_config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
user_overrides:
  - domain: "test.example.com"
    domain_category: "low"
    qps: 0.3
"""
        config_path.write_text(updated_config, encoding="utf-8")

        # Trigger reload check
        time.sleep(0.2)
        _ = manager.config  # This triggers the reload check

        # Then
        updated_policy = manager.get_policy("test.example.com")
        assert updated_policy.domain_category == DomainCategory.LOW
        assert updated_policy.qps == 0.3
        assert updated_policy.source == "user_override"

    def test_user_override_multiple_entries_first_match_used(self, tmp_path: Path) -> None:
        """Verify first matching user_override entry is used."""
        # Given - multiple user_overrides (should not happen, but test behavior)
        config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
user_overrides:
  - domain: "test.example.com"
    domain_category: "low"
    qps: 0.3
  - domain: "test.example.com"
    domain_category: "government"
    qps: 0.4
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        policy = manager.get_policy("test.example.com")

        # Then - first match should be used
        assert policy.domain_category == DomainCategory.LOW
        assert policy.qps == 0.3
        assert policy.source == "user_override"

    def test_user_override_all_fields_applied(self, tmp_path: Path) -> None:
        """Verify all user_override fields are applied correctly."""
        # Given
        config = """
default_policy:
  qps: 0.2
  concurrent: 1
  headful_ratio: 0.1
  tor_allowed: true
  cooldown_minutes: 60
  max_retries: 3
  domain_category: "unverified"
  max_requests_per_day: 200
  max_pages_per_day: 100
user_overrides:
  - domain: "full.example.com"
    domain_category: "academic"
    qps: 0.25
    headful_ratio: 0.2
    tor_allowed: false
    concurrent: 2
    cooldown_minutes: 90
    max_retries: 5
    max_requests_per_day: 300
    max_pages_per_day: 150
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        policy = manager.get_policy("full.example.com")

        # Then
        assert policy.domain_category == DomainCategory.ACADEMIC
        assert policy.qps == 0.25
        assert policy.headful_ratio == 0.2
        assert policy.tor_allowed is False
        assert policy.concurrent == 2
        assert policy.cooldown_minutes == 90
        assert policy.max_retries == 5
        assert policy.max_requests_per_day == 300
        assert policy.max_pages_per_day == 150
        assert policy.source == "user_override"

    def test_user_override_partial_fields_applied(self, tmp_path: Path) -> None:
        """Verify partial user_override fields (only category) are applied."""
        # Given
        config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
user_overrides:
  - domain: "partial.example.com"
    domain_category: "low"
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        policy = manager.get_policy("partial.example.com")

        # Then - only category should be overridden, other fields use defaults
        assert policy.domain_category == DomainCategory.LOW
        assert policy.qps == 0.2  # Default
        assert policy.source == "user_override"


class TestDomainPolicyManagerConvenienceMethods:
    """Tests for convenience methods."""

    def test_should_skip_denylist(self, policy_manager: DomainPolicyManager) -> None:
        """Verify should_skip returns True for denylist domains."""
        # Then
        assert policy_manager.should_skip("test.blogspot.com") is True

    def test_should_skip_allowlist(self, policy_manager: DomainPolicyManager) -> None:
        """Verify should_skip returns False for allowlist domains."""
        # Then
        assert policy_manager.should_skip("arxiv.org") is False

    def test_get_domain_category(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_domain_category returns correct level."""
        # Then
        assert policy_manager.get_domain_category("arxiv.org") == DomainCategory.ACADEMIC
        assert policy_manager.get_domain_category("example.go.jp") == DomainCategory.GOVERNMENT
        assert policy_manager.get_domain_category("unknown.com") == DomainCategory.UNVERIFIED

    def test_get_category_weight(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_category_weight returns correct weight."""
        # Then
        assert policy_manager.get_category_weight("arxiv.org") == 0.90  # academic
        assert policy_manager.get_category_weight("example.go.jp") == 0.95  # government

    def test_get_qps_limit(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_qps_limit returns correct QPS."""
        # Then
        assert policy_manager.get_qps_limit("arxiv.org") == 0.25
        assert policy_manager.get_qps_limit("wikipedia.org") == 0.5
        assert policy_manager.get_qps_limit("unknown.com") == 0.2  # default

    def test_get_domain_category_user_override(self, tmp_path: Path) -> None:
        """Verify get_domain_category reflects user_override (wiring test)."""
        # Given
        config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
user_overrides:
  - domain: "override.example.com"
    domain_category: "low"
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        category = manager.get_domain_category("override.example.com")

        # Then - user_override should be reflected
        assert category == DomainCategory.LOW

    def test_get_category_weight_user_override(self, tmp_path: Path) -> None:
        """Verify get_category_weight reflects user_override (effect test)."""
        # Given
        config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
user_overrides:
  - domain: "weight.example.com"
    domain_category: "academic"
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        weight = manager.get_category_weight("weight.example.com")

        # Then - academic category weight should be applied
        assert weight == 0.90  # academic category weight


class TestDomainPolicyManagerInternalSearch:
    """Tests for internal search template functionality."""

    def test_get_internal_search_template_exists(self, policy_manager: DomainPolicyManager) -> None:
        """Verify existing template is returned."""
        # When
        template = policy_manager.get_internal_search_template("arxiv.org")

        # Then
        assert template is not None
        assert template.domain == "arxiv.org"
        assert template.search_input == "input[name='query']"
        assert template.search_button == "button[type='submit']"
        assert template.results_selector == ".arxiv-result"

    def test_get_internal_search_template_not_exists(
        self, policy_manager: DomainPolicyManager
    ) -> None:
        """Verify None is returned for domain without template."""
        # When
        template = policy_manager.get_internal_search_template("unknown.com")

        # Then
        assert template is None

    def test_has_internal_search_true_from_allowlist(
        self, policy_manager: DomainPolicyManager
    ) -> None:
        """Verify has_internal_search returns True for allowlist internal_search=True."""
        # Then
        assert policy_manager.has_internal_search("arxiv.org") is True

    def test_has_internal_search_true_from_template(
        self, policy_manager: DomainPolicyManager
    ) -> None:
        """Verify has_internal_search returns True for domain with template."""
        # Then
        assert policy_manager.has_internal_search("pubmed.ncbi.nlm.nih.gov") is True

    def test_has_internal_search_false(self, policy_manager: DomainPolicyManager) -> None:
        """Verify has_internal_search returns False for unknown domains."""
        # Then
        assert policy_manager.has_internal_search("unknown.com") is False


class TestDomainPolicyManagerLists:
    """Tests for list retrieval methods."""

    def test_get_all_allowlist_domains(self, policy_manager: DomainPolicyManager) -> None:
        """Verify all allowlist domains are returned."""
        # When
        domains = policy_manager.get_all_allowlist_domains()

        # Then
        assert len(domains) == 4
        assert "go.jp" in domains
        assert "arxiv.org" in domains
        assert "wikipedia.org" in domains
        assert "example-primary.com" in domains

    def test_get_domains_by_category_government(self, policy_manager: DomainPolicyManager) -> None:
        """Verify domains with GOVERNMENT trust level are returned."""
        # When
        domains = policy_manager.get_domains_by_category(DomainCategory.GOVERNMENT)

        # Then
        assert len(domains) == 1
        assert "go.jp" in domains

    def test_get_domains_by_category_academic(self, policy_manager: DomainPolicyManager) -> None:
        """Verify domains with ACADEMIC trust level are returned."""
        # When
        domains = policy_manager.get_domains_by_category(DomainCategory.ACADEMIC)

        # Then
        assert len(domains) == 1
        assert "arxiv.org" in domains


class TestDomainPolicyManagerLearningState:
    """Tests for runtime learning state updates."""

    def test_update_learning_state(self, policy_manager: DomainPolicyManager) -> None:
        """Verify learning state update modifies cached policy."""
        # Given - get policy to populate cache
        policy = policy_manager.get_policy("example.com")
        assert policy.block_score == 0.0

        # When
        policy_manager.update_learning_state(
            "example.com",
            {
                "block_score": 5.0,
                "captcha_rate": 0.3,
            },
        )

        # Then - get policy again from cache
        updated_policy = policy_manager.get_policy("example.com")
        assert updated_policy.block_score == 5.0
        assert updated_policy.captcha_rate == 0.3

    def test_update_learning_state_cooldown(self, policy_manager: DomainPolicyManager) -> None:
        """Verify cooldown_until update affects is_in_cooldown."""
        # Given
        policy = policy_manager.get_policy("example.com")
        assert policy.is_in_cooldown is False

        # When
        future_time = datetime.now(UTC) + timedelta(hours=1)
        policy_manager.update_learning_state(
            "example.com",
            {
                "cooldown_until": future_time,
            },
        )

        # Then
        updated_policy = policy_manager.get_policy("example.com")
        assert updated_policy.is_in_cooldown is True


class TestDomainPolicyManagerCaching:
    """Tests for caching functionality."""

    def test_cache_hit(self, policy_manager: DomainPolicyManager) -> None:
        """Verify subsequent lookups use cache."""
        # Given
        _ = policy_manager.get_policy("arxiv.org")
        initial_stats = policy_manager.get_cache_stats()

        # When
        _ = policy_manager.get_policy("arxiv.org")
        final_stats = policy_manager.get_cache_stats()

        # Then - cache count should not increase
        assert initial_stats["cached_domains"] == final_stats["cached_domains"]

    def test_clear_cache(self, policy_manager: DomainPolicyManager) -> None:
        """Verify clear_cache empties the cache."""
        # Given
        _ = policy_manager.get_policy("example.com")
        _ = policy_manager.get_policy("arxiv.org")
        assert policy_manager.get_cache_stats()["cached_domains"] >= 2

        # When
        policy_manager.clear_cache()

        # Then
        assert policy_manager.get_cache_stats()["cached_domains"] == 0

    def test_cache_stats(self, policy_manager: DomainPolicyManager) -> None:
        """Verify cache stats contain expected fields."""
        # When
        stats = policy_manager.get_cache_stats()

        # Then
        assert "cached_domains" in stats
        assert "allowlist_count" in stats
        assert "graylist_count" in stats
        assert "denylist_count" in stats
        assert "cloudflare_count" in stats
        assert "search_templates_count" in stats


class TestDomainPolicyManagerHotReload:
    """Tests for hot-reload functionality."""

    def test_hot_reload_detects_file_change(self, tmp_path: Path) -> None:
        """Verify hot-reload detects and applies config file changes."""
        # Given - create initial config
        config_path = tmp_path / "domains.yaml"
        initial_config = """
default_policy:
  qps: 0.2
allowlist:
  - domain: "example.com"
    domain_category: "unverified"
"""
        config_path.write_text(initial_config, encoding="utf-8")

        manager = DomainPolicyManager(
            config_path=config_path,
            watch_interval=0.1,  # Short interval for testing
            enable_hot_reload=True,
        )

        # Verify initial state
        policy = manager.get_policy("example.com")
        assert policy.domain_category == DomainCategory.UNVERIFIED

        # When - modify config
        time.sleep(0.2)  # Ensure mtime changes
        updated_config = """
default_policy:
  qps: 0.3
allowlist:
  - domain: "example.com"
    domain_category: "government"
"""
        config_path.write_text(updated_config, encoding="utf-8")

        # Trigger reload check
        time.sleep(0.2)
        _ = manager.config  # This triggers the reload check

        # Then
        updated_policy = manager.get_policy("example.com")
        assert updated_policy.domain_category == DomainCategory.GOVERNMENT

    def test_reload_callback_called(self, tmp_path: Path) -> None:
        """Verify reload callbacks are called on config reload."""
        # Given
        config_path = tmp_path / "domains.yaml"
        config_path.write_text("default_policy:\n  qps: 0.2\n", encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)
        callback_called = []

        def callback(config: DomainPolicyConfigSchema) -> None:
            callback_called.append(config.default_policy.qps)

        manager.add_reload_callback(callback)

        # When
        manager.reload()

        # Then
        assert len(callback_called) == 1
        assert callback_called[0] == 0.2

    def test_remove_reload_callback(self, tmp_path: Path) -> None:
        """Verify reload callbacks can be removed."""
        # Given
        config_path = tmp_path / "domains.yaml"
        config_path.write_text("default_policy:\n  qps: 0.2\n", encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)
        callback_count = [0]

        def callback(config: DomainPolicyConfigSchema) -> None:
            callback_count[0] += 1

        manager.add_reload_callback(callback)
        manager.remove_reload_callback(callback)

        # When
        manager.reload()

        # Then
        assert callback_count[0] == 0

    def test_reload_callback_exception_does_not_block_others(self, tmp_path: Path) -> None:
        """Verify callback exception does not prevent other callbacks from running."""
        # Given: TC-HR-A-01
        config_path = tmp_path / "domains.yaml"
        config_path.write_text("default_policy:\n  qps: 0.2\n", encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)
        callback_results = []

        def failing_callback(config: DomainPolicyConfigSchema) -> None:
            raise ValueError("Callback error")

        def succeeding_callback(config: DomainPolicyConfigSchema) -> None:
            callback_results.append(config.default_policy.qps)

        manager.add_reload_callback(failing_callback)
        manager.add_reload_callback(succeeding_callback)

        # When: reload is called
        manager.reload()

        # Then: succeeding callback should still be called despite exception
        assert len(callback_results) == 1
        assert callback_results[0] == 0.2

    def test_reload_yaml_error_retains_previous_config(self, tmp_path: Path) -> None:
        """Verify YAML parse error on reload retains previous valid config."""
        # Given: TC-HR-A-02 - initial valid config
        config_path = tmp_path / "domains.yaml"
        initial_config = """
default_policy:
  qps: 0.3
  domain_category: "government"
allowlist:
  - domain: "example.com"
    domain_category: "academic"
"""
        config_path.write_text(initial_config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)
        initial_policy = manager.get_policy("example.com")
        assert initial_policy.domain_category == DomainCategory.ACADEMIC
        assert manager.config.default_policy.qps == 0.3

        # When: write invalid YAML
        time.sleep(0.1)  # Ensure mtime changes
        invalid_config = """
default_policy:
  qps: 0.5
  domain_category: "government"
allowlist:
  - domain: "example.com"
    domain_category: "academic"
invalid_yaml: [unclosed
"""
        config_path.write_text(invalid_config, encoding="utf-8")

        # Trigger reload check
        time.sleep(0.1)
        _ = manager.config  # This triggers the reload check

        # Then: previous config should be retained
        retained_policy = manager.get_policy("example.com")
        assert retained_policy.domain_category == DomainCategory.ACADEMIC
        assert manager.config.default_policy.qps == 0.3

    def test_watch_interval_zero_checks_every_access(self, tmp_path: Path) -> None:
        """Verify watch_interval=0 checks file on every config access."""
        # Given: TC-HR-B-01
        config_path = tmp_path / "domains.yaml"
        initial_config = """
default_policy:
  qps: 0.2
allowlist:
  - domain: "example.com"
    domain_category: "unverified"
"""
        config_path.write_text(initial_config, encoding="utf-8")

        manager = DomainPolicyManager(
            config_path=config_path,
            watch_interval=0.0,  # Check on every access
            enable_hot_reload=True,
        )

        # Verify initial state
        policy = manager.get_policy("example.com")
        assert policy.domain_category == DomainCategory.UNVERIFIED

        # When: modify config
        time.sleep(0.1)  # Ensure mtime changes
        updated_config = """
default_policy:
  qps: 0.2
allowlist:
  - domain: "example.com"
    domain_category: "government"
"""
        config_path.write_text(updated_config, encoding="utf-8")

        # Access config (should trigger reload check immediately)
        _ = manager.config

        # Then: changes should be reflected immediately
        updated_policy = manager.get_policy("example.com")
        assert updated_policy.domain_category == DomainCategory.GOVERNMENT

    def test_manual_reload_works_when_hot_reload_disabled(self, tmp_path: Path) -> None:
        """Verify manual reload() works even when enable_hot_reload=False."""
        # Given: TC-HR-B-02
        config_path = tmp_path / "domains.yaml"
        initial_config = """
default_policy:
  qps: 0.2
allowlist:
  - domain: "example.com"
    domain_category: "unverified"
"""
        config_path.write_text(initial_config, encoding="utf-8")

        manager = DomainPolicyManager(
            config_path=config_path,
            enable_hot_reload=False,  # Hot-reload disabled
        )

        # Verify initial state
        policy = manager.get_policy("example.com")
        assert policy.domain_category == DomainCategory.UNVERIFIED

        # When: modify config and manually reload
        updated_config = """
default_policy:
  qps: 0.2
allowlist:
  - domain: "example.com"
    domain_category: "government"
"""
        config_path.write_text(updated_config, encoding="utf-8")

        # Manual reload should work even when hot-reload is disabled
        manager.reload()

        # Then: changes should be reflected
        updated_policy = manager.get_policy("example.com")
        assert updated_policy.domain_category == DomainCategory.GOVERNMENT

    def test_user_override_removal_reverts_to_default(self, tmp_path: Path) -> None:
        """Verify removing user_override reverts domain to default policy."""
        # Given: TC-HR-N-04 - initial config with user_override
        config_path = tmp_path / "domains.yaml"
        initial_config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
allowlist:
  - domain: "example.com"
    domain_category: "academic"
    qps: 0.25
user_overrides:
  - domain: "example.com"
    domain_category: "low"
    qps: 0.3
"""
        config_path.write_text(initial_config, encoding="utf-8")

        manager = DomainPolicyManager(
            config_path=config_path,
            watch_interval=0.1,
            enable_hot_reload=True,
        )

        # Verify initial state: user_override takes precedence
        policy = manager.get_policy("example.com")
        assert policy.domain_category == DomainCategory.LOW
        assert policy.qps == 0.3
        assert policy.source == "user_override"

        # When: remove user_override
        time.sleep(0.2)  # Ensure mtime changes
        updated_config = """
default_policy:
  qps: 0.2
  domain_category: "unverified"
allowlist:
  - domain: "example.com"
    domain_category: "academic"
    qps: 0.25
user_overrides: []
"""
        config_path.write_text(updated_config, encoding="utf-8")

        # Trigger reload check
        time.sleep(0.2)
        _ = manager.config  # This triggers the reload check

        # Then: domain should revert to allowlist policy
        updated_policy = manager.get_policy("example.com")
        assert updated_policy.domain_category == DomainCategory.ACADEMIC
        assert updated_policy.qps == 0.25
        assert updated_policy.source == "allowlist"


# =============================================================================
# Module-level Function Tests
# =============================================================================


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_domain_policy_manager_singleton(self, temp_config_file: Path) -> None:
        """Verify get_domain_policy_manager returns singleton."""
        # Given
        reset_domain_policy_manager()

        # When
        # Note: We can't easily inject the config path for singleton,
        # so we test that it returns the same instance
        manager1 = get_domain_policy_manager()
        manager2 = get_domain_policy_manager()

        # Then
        assert manager1 is manager2

    def test_reset_domain_policy_manager(self, temp_config_file: Path) -> None:
        """Verify reset creates new instance."""
        # Given
        manager1 = get_domain_policy_manager()

        # When
        reset_domain_policy_manager()
        manager2 = get_domain_policy_manager()

        # Then
        assert manager1 is not manager2


# =============================================================================
# Pattern Matching Edge Cases
# =============================================================================


class TestPatternMatching:
    """Tests for domain pattern matching edge cases."""

    def test_exact_match(self, policy_manager: DomainPolicyManager) -> None:
        """Verify exact domain match works."""
        # Then
        policy = policy_manager.get_policy("arxiv.org")
        assert policy.source == "allowlist"

    def test_glob_wildcard_match(self, policy_manager: DomainPolicyManager) -> None:
        """Verify glob wildcard pattern match works."""
        # Then - *.medium.com should match sub.medium.com
        policy = policy_manager.get_policy("blog.medium.com")
        assert policy.source == "graylist"

    def test_nested_subdomain_match(self, policy_manager: DomainPolicyManager) -> None:
        """Verify nested subdomain matches glob pattern."""
        # Then - *.twitter.com should match api.v2.twitter.com
        policy = policy_manager.get_policy("api.v2.twitter.com")
        assert policy.skip is True

    def test_suffix_match_go_jp(self, policy_manager: DomainPolicyManager) -> None:
        """Verify suffix match works for go.jp domains."""
        # Then - go.jp should match ministry.go.jp
        policy = policy_manager.get_policy("ministry.go.jp")
        assert policy.domain_category == DomainCategory.GOVERNMENT

        # Also test deeply nested
        policy2 = policy_manager.get_policy("sub.ministry.go.jp")
        assert policy2.domain_category == DomainCategory.GOVERNMENT

    def test_no_match_partial_domain(self, policy_manager: DomainPolicyManager) -> None:
        """Verify partial domain doesn't match (arxiv.org vs myarxiv.org)."""
        # Then - myarxiv.org should NOT match arxiv.org
        policy = policy_manager.get_policy("myarxiv.org")
        assert policy.source == "default"  # Not allowlist


# =============================================================================
# Trust Level Priority Tests
# =============================================================================


class TestDomainCategoryPriority:
    """Tests for domain category hierarchy and weights."""

    def test_domain_category_hierarchy(self, policy_manager: DomainPolicyManager) -> None:
        """Verify trust level weights follow expected hierarchy."""
        # Given
        primary_policy = policy_manager.get_policy("example-primary.com")
        gov_policy = policy_manager.get_policy("example.go.jp")
        academic_policy = policy_manager.get_policy("arxiv.org")
        trusted_policy = policy_manager.get_policy("wikipedia.org")
        unknown_policy = policy_manager.get_policy("unknown.com")

        # Then - PRIMARY > GOVERNMENT > ACADEMIC > TRUSTED > UNKNOWN
        assert primary_policy.category_weight > gov_policy.category_weight
        assert gov_policy.category_weight > academic_policy.category_weight
        assert academic_policy.category_weight > trusted_policy.category_weight
        assert trusted_policy.category_weight > unknown_policy.category_weight


# =============================================================================
# Resolution Priority Tests
# =============================================================================


class TestResolutionPriority:
    """Tests for policy resolution priority order."""

    def test_denylist_has_highest_priority(self, tmp_path: Path) -> None:
        """Verify denylist overrides allowlist for same domain."""
        # Given - domain in both allowlist and denylist
        config = """
allowlist:
  - domain: "test.blogspot.com"
    domain_category: "trusted"
denylist:
  - domain_pattern: "*.blogspot.com"
    reason: "low_quality_aggregator"
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        policy = manager.get_policy("test.blogspot.com")

        # Then - denylist should win
        assert policy.skip is True
        assert policy.source == "denylist"

    def test_cloudflare_before_allowlist(self, tmp_path: Path) -> None:
        """Verify cloudflare settings are applied even to allowlist domains."""
        # Given
        config = """
allowlist:
  - domain: "example-protected.com"
    domain_category: "trusted"
cloudflare_sites:
  - domain_pattern: "*.protected.com"
    headful_required: true
    tor_blocked: true
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        policy = manager.get_policy("api.protected.com")

        # Then - cloudflare settings applied
        assert policy.headful_required is True
        assert policy.tor_blocked is True


# =============================================================================
# Search Engine Policy Schema Tests
# =============================================================================


class TestSearchEnginePolicySchema:
    """Tests for SearchEnginePolicySchema (ADR-0006, ADR-0006)."""

    def test_default_values(self) -> None:
        """Verify default values are correctly set."""
        # Arrange & Act
        schema = SearchEnginePolicySchema()

        # Then
        assert schema.default_qps == 0.25
        assert schema.site_search_qps == 0.1
        assert schema.cooldown_min == 30
        assert schema.cooldown_max == 120
        assert schema.failure_threshold == 2

    def test_custom_values(self) -> None:
        """Verify custom values are accepted."""
        # Arrange & Act
        schema = SearchEnginePolicySchema(
            default_qps=0.5,
            site_search_qps=0.2,
            cooldown_min=60,
            cooldown_max=180,
            failure_threshold=3,
        )

        # Then
        assert schema.default_qps == 0.5
        assert schema.site_search_qps == 0.2
        assert schema.cooldown_min == 60
        assert schema.cooldown_max == 180
        assert schema.failure_threshold == 3

    def test_default_min_interval_property(self) -> None:
        """Verify default_min_interval is calculated correctly."""
        # Arrange & Act
        schema = SearchEnginePolicySchema(default_qps=0.25)

        # Then
        assert schema.default_min_interval == 4.0  # 1 / 0.25

    def test_site_search_min_interval_property(self) -> None:
        """Verify site_search_min_interval is calculated correctly."""
        # Arrange & Act
        schema = SearchEnginePolicySchema(site_search_qps=0.1)

        # Then
        assert schema.site_search_min_interval == 10.0  # 1 / 0.1

    def test_qps_validation_range(self) -> None:
        """Verify QPS validation enforces valid range."""
        # Then - too low
        with pytest.raises(ValueError):
            SearchEnginePolicySchema(default_qps=0.01)

        # Then - too high
        with pytest.raises(ValueError):
            SearchEnginePolicySchema(default_qps=2.0)


class TestPolicyBoundsEntrySchema:
    """Tests for PolicyBoundsEntrySchema ."""

    def test_default_values(self) -> None:
        """Verify default values are set."""
        # Arrange & Act
        entry = PolicyBoundsEntrySchema()

        # Then
        assert entry.min == 0.0
        assert entry.max == 1.0
        assert entry.default == 0.5
        assert entry.step_up == 0.1
        assert entry.step_down == 0.1

    def test_custom_values(self) -> None:
        """Verify custom values are accepted."""
        # Arrange & Act
        entry = PolicyBoundsEntrySchema(
            min=0.1,
            max=2.0,
            default=1.0,
            step_up=0.1,
            step_down=0.2,
        )

        # Then
        assert entry.min == 0.1
        assert entry.max == 2.0
        assert entry.default == 1.0
        assert entry.step_up == 0.1
        assert entry.step_down == 0.2


class TestPolicyBoundsSchema:
    """Tests for PolicyBoundsSchema ."""

    def test_default_bounds_exist(self) -> None:
        """Verify all expected bounds parameters exist with defaults."""
        # Arrange & Act
        schema = PolicyBoundsSchema()

        # Then - all parameters should exist
        assert schema.engine_weight is not None
        assert schema.engine_qps is not None
        assert schema.domain_qps is not None
        assert schema.domain_cooldown is not None
        assert schema.headful_ratio is not None
        assert schema.tor_usage_ratio is not None
        assert schema.browser_route_ratio is not None

    def test_engine_weight_defaults(self) -> None:
        """Verify engine_weight has correct default values."""
        # Arrange & Act
        schema = PolicyBoundsSchema()

        # Then
        assert schema.engine_weight.min == 0.1
        assert schema.engine_weight.max == 2.0
        assert schema.engine_weight.default == 1.0

    def test_domain_qps_defaults(self) -> None:
        """Verify domain_qps has correct default values."""
        # Arrange & Act
        schema = PolicyBoundsSchema()

        # Then
        assert schema.domain_qps.min == 0.05
        assert schema.domain_qps.max == 0.3
        assert schema.domain_qps.default == 0.2


# =============================================================================
# Search Engine Policy Access Tests
# =============================================================================


class TestSearchEnginePolicyAccess:
    """Tests for DomainPolicyManager search engine policy methods."""

    def test_get_search_engine_policy(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_search_engine_policy returns SearchEnginePolicySchema."""
        # When
        policy = policy_manager.get_search_engine_policy()

        # Then
        assert isinstance(policy, SearchEnginePolicySchema)
        assert policy.default_qps == 0.25
        assert policy.site_search_qps == 0.1

    def test_get_search_engine_qps(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_search_engine_qps returns correct value."""
        # When
        qps = policy_manager.get_search_engine_qps()

        # Then
        assert qps == 0.25

    def test_get_search_engine_min_interval(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_search_engine_min_interval returns 1/QPS."""
        # When
        interval = policy_manager.get_search_engine_min_interval()

        # Then
        assert interval == 4.0  # 1 / 0.25

    def test_get_site_search_qps(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_site_search_qps returns correct value."""
        # When
        qps = policy_manager.get_site_search_qps()

        # Then
        assert qps == 0.1

    def test_get_site_search_min_interval(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_site_search_min_interval returns 1/QPS."""
        # When
        interval = policy_manager.get_site_search_min_interval()

        # Then
        assert interval == 10.0  # 1 / 0.1

    def test_get_circuit_breaker_cooldown_min(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_circuit_breaker_cooldown_min returns correct value."""
        # When
        cooldown = policy_manager.get_circuit_breaker_cooldown_min()

        # Then
        assert cooldown == 30

    def test_get_circuit_breaker_cooldown_max(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_circuit_breaker_cooldown_max returns correct value."""
        # When
        cooldown = policy_manager.get_circuit_breaker_cooldown_max()

        # Then
        assert cooldown == 120

    def test_get_circuit_breaker_failure_threshold(
        self, policy_manager: DomainPolicyManager
    ) -> None:
        """Verify get_circuit_breaker_failure_threshold returns correct value."""
        # When
        threshold = policy_manager.get_circuit_breaker_failure_threshold()

        # Then
        assert threshold == 2


# =============================================================================
# Policy Bounds Access Tests
# =============================================================================


class TestPolicyBoundsAccess:
    """Tests for DomainPolicyManager policy bounds methods."""

    def test_get_policy_bounds(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_policy_bounds returns PolicyBoundsSchema."""
        # When
        bounds = policy_manager.get_policy_bounds()

        # Then
        assert isinstance(bounds, PolicyBoundsSchema)
        assert bounds.engine_weight is not None
        assert bounds.domain_qps is not None

    def test_get_bounds_for_parameter_engine_weight(
        self, policy_manager: DomainPolicyManager
    ) -> None:
        """Verify get_bounds_for_parameter returns correct bounds for engine_weight."""
        # When
        bounds = policy_manager.get_bounds_for_parameter("engine_weight")

        # Then
        assert bounds is not None
        assert bounds.min == 0.1
        assert bounds.max == 2.0
        assert bounds.default == 1.0
        assert bounds.step_up == 0.1
        assert bounds.step_down == 0.2

    def test_get_bounds_for_parameter_domain_qps(self, policy_manager: DomainPolicyManager) -> None:
        """Verify get_bounds_for_parameter returns correct bounds for domain_qps."""
        # When
        bounds = policy_manager.get_bounds_for_parameter("domain_qps")

        # Then
        assert bounds is not None
        assert bounds.min == 0.05
        assert bounds.max == 0.3
        assert bounds.default == 0.2

    def test_get_bounds_for_parameter_nonexistent(
        self, policy_manager: DomainPolicyManager
    ) -> None:
        """Verify get_bounds_for_parameter returns None for unknown parameter."""
        # When
        bounds = policy_manager.get_bounds_for_parameter("nonexistent_param")

        # Then
        assert bounds is None


# =============================================================================
# Default Config Fallback Tests
# =============================================================================


class TestDefaultConfigFallback:
    """Tests for fallback behavior when config sections are missing."""

    def test_missing_search_engine_policy_uses_defaults(self, tmp_path: Path) -> None:
        """Verify missing search_engine_policy section uses defaults."""
        # Given - config without search_engine_policy
        config = """
default_policy:
  qps: 0.2
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        qps = manager.get_search_engine_qps()

        # Then - should use default value
        assert qps == 0.25

    def test_missing_policy_bounds_uses_defaults(self, tmp_path: Path) -> None:
        """Verify missing policy_bounds section uses defaults."""
        # Given - config without policy_bounds
        config = """
default_policy:
  qps: 0.2
"""
        config_path = tmp_path / "domains.yaml"
        config_path.write_text(config, encoding="utf-8")

        manager = DomainPolicyManager(config_path=config_path)

        # When
        bounds = manager.get_policy_bounds()

        # Then - should use default values
        assert bounds.engine_weight.default == 1.0
        assert bounds.domain_qps.default == 0.2
