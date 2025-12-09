"""
Tests for DomainPolicyManager (§17.2.1 Domain Policy Externalization).

Test design follows §7.1 Test Code Quality Standards:
- No conditional assertions (§7.1.1)
- Specific assertions with concrete values (§7.1.2)
- Realistic test data (§7.1.3)
- AAA pattern (§7.1.5)

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
| TC-CV-N-03 | get_trust_level | Equivalence – normal | Correct level | - |
| TC-CV-N-04 | get_trust_weight | Equivalence – normal | Correct weight | - |
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

import tempfile

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.utils.domain_policy import (
    AllowlistEntrySchema,
    DefaultPolicySchema,
    DenylistEntrySchema,
    DomainPolicy,
    DomainPolicyConfigSchema,
    DomainPolicyManager,
    GraylistEntrySchema,
    InternalSearchTemplate,
    InternalSearchTemplateSchema,
    PolicyBoundsEntrySchema,
    PolicyBoundsSchema,
    SearchEnginePolicySchema,
    TrustLevel,
    SkipReason,
    get_domain_policy,
    get_domain_policy_manager,
    get_domain_qps,
    get_domain_trust_level,
    reset_domain_policy_manager,
    should_skip_domain,
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
  trust_level: "unverified"

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
    trust_level: "government"
    qps: 0.15
  - domain: "arxiv.org"
    trust_level: "academic"
    internal_search: true
    qps: 0.25
  - domain: "wikipedia.org"
    trust_level: "trusted"
    qps: 0.5
    headful_ratio: 0
  - domain: "example-primary.com"
    trust_level: "primary"
    qps: 0.1

graylist:
  - domain_pattern: "*.medium.com"
    trust_level: "unverified"
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
def policy_manager(temp_config_file: Path) -> DomainPolicyManager:
    """Create DomainPolicyManager with test config."""
    reset_domain_policy_manager()
    manager = DomainPolicyManager(
        config_path=temp_config_file,
        enable_hot_reload=False,  # Disable for deterministic tests
    )
    yield manager
    reset_domain_policy_manager()


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before and after each test."""
    reset_domain_policy_manager()
    yield
    reset_domain_policy_manager()


# =============================================================================
# Schema Validation Tests
# =============================================================================

class TestDefaultPolicySchema:
    """Tests for DefaultPolicySchema validation."""
    
    def test_default_values(self):
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
        assert schema.trust_level == TrustLevel.UNVERIFIED
    
    def test_custom_values(self):
        """Verify schema accepts valid custom values."""
        # Arrange & Act
        schema = DefaultPolicySchema(
            qps=0.5,
            concurrent=3,
            headful_ratio=0.3,
            tor_allowed=False,
            cooldown_minutes=120,
            max_retries=5,
            trust_level=TrustLevel.GOVERNMENT,
        )
        
        # Then
        assert schema.qps == 0.5
        assert schema.concurrent == 3
        assert schema.headful_ratio == 0.3
        assert schema.tor_allowed is False
        assert schema.cooldown_minutes == 120
        assert schema.max_retries == 5
        assert schema.trust_level == TrustLevel.GOVERNMENT
    
    def test_qps_validation_range(self):
        """Verify QPS validation rejects out-of-range values."""
        # Then - too low
        with pytest.raises(ValueError):
            DefaultPolicySchema(qps=0.001)
        
        # Then - too high
        with pytest.raises(ValueError):
            DefaultPolicySchema(qps=3.0)
    
    def test_headful_ratio_validation_range(self):
        """Verify headful_ratio validation enforces [0, 1] range."""
        # Then - negative
        with pytest.raises(ValueError):
            DefaultPolicySchema(headful_ratio=-0.1)
        
        # Then - over 1
        with pytest.raises(ValueError):
            DefaultPolicySchema(headful_ratio=1.5)


class TestAllowlistEntrySchema:
    """Tests for AllowlistEntrySchema validation."""
    
    def test_valid_entry(self):
        """Verify valid allowlist entry is accepted."""
        # Arrange & Act
        entry = AllowlistEntrySchema(
            domain="example.go.jp",
            trust_level=TrustLevel.GOVERNMENT,
            internal_search=True,
            qps=0.15,
        )
        
        # Then
        assert entry.domain == "example.go.jp"
        assert entry.trust_level == TrustLevel.GOVERNMENT
        assert entry.internal_search is True
        assert entry.qps == 0.15
    
    def test_domain_normalization(self):
        """Verify domain is normalized to lowercase."""
        # Arrange & Act
        entry = AllowlistEntrySchema(domain="EXAMPLE.COM")
        
        # Then
        assert entry.domain == "example.com"
    
    def test_empty_domain_rejected(self):
        """Verify empty domain is rejected."""
        with pytest.raises(ValueError):
            AllowlistEntrySchema(domain="")
    
    def test_short_domain_rejected(self):
        """Verify single-character domain is rejected."""
        with pytest.raises(ValueError):
            AllowlistEntrySchema(domain="x")


class TestGraylistEntrySchema:
    """Tests for GraylistEntrySchema validation."""
    
    def test_valid_pattern(self):
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
    
    def test_skip_with_reason(self):
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
    
    def test_valid_entry(self):
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
    
    def test_full_config_parsing(self, sample_config_yaml: str):
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
    
    def test_empty_config_uses_defaults(self):
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
    
    def test_trust_weight_primary(self):
        """Verify PRIMARY trust level has weight 1.0."""
        # Arrange & Act
        policy = DomainPolicy(domain="gov.example", trust_level=TrustLevel.PRIMARY)
        
        # Then
        assert policy.trust_weight == 1.0
    
    def test_trust_weight_government(self):
        """Verify GOVERNMENT trust level has weight 0.95."""
        # Arrange & Act
        policy = DomainPolicy(domain="gov.example", trust_level=TrustLevel.GOVERNMENT)
        
        # Then
        assert policy.trust_weight == 0.95
    
    def test_trust_weight_academic(self):
        """Verify ACADEMIC trust level has weight 0.90."""
        # Arrange & Act
        policy = DomainPolicy(domain="uni.example", trust_level=TrustLevel.ACADEMIC)
        
        # Then
        assert policy.trust_weight == 0.90
    
    def test_trust_weight_unknown(self):
        """Verify UNKNOWN trust level has weight 0.30."""
        # Arrange & Act
        policy = DomainPolicy(domain="unknown.example", trust_level=TrustLevel.UNVERIFIED)
        
        # Then
        assert policy.trust_weight == 0.30
    
    def test_min_request_interval(self):
        """Verify min_request_interval is calculated correctly from QPS."""
        # Arrange & Act
        policy = DomainPolicy(domain="example.com", qps=0.25)
        
        # Then
        assert policy.min_request_interval == 4.0  # 1 / 0.25
    
    def test_is_in_cooldown_true(self):
        """Verify is_in_cooldown returns True when cooldown is active."""
        # Given
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        policy = DomainPolicy(domain="example.com", cooldown_until=future_time)
        
        # Then
        assert policy.is_in_cooldown is True
    
    def test_is_in_cooldown_false_when_expired(self):
        """Verify is_in_cooldown returns False when cooldown has expired."""
        # Given
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        policy = DomainPolicy(domain="example.com", cooldown_until=past_time)
        
        # Then
        assert policy.is_in_cooldown is False
    
    def test_is_in_cooldown_false_when_none(self):
        """Verify is_in_cooldown returns False when no cooldown set."""
        # Given
        policy = DomainPolicy(domain="example.com", cooldown_until=None)
        
        # Then
        assert policy.is_in_cooldown is False
    
    def test_to_dict_contains_all_fields(self):
        """Verify to_dict includes all required fields."""
        # Given
        policy = DomainPolicy(
            domain="example.com",
            qps=0.2,
            trust_level=TrustLevel.GOVERNMENT,
        )
        
        # When
        result = policy.to_dict()
        
        # Then
        assert result["domain"] == "example.com"
        assert result["qps"] == 0.2
        assert result["trust_level"] == "government"
        assert "trust_weight" in result
        assert "min_request_interval" in result
        assert "is_in_cooldown" in result


# =============================================================================
# DomainPolicyManager Tests
# =============================================================================

class TestDomainPolicyManagerLoading:
    """Tests for DomainPolicyManager configuration loading."""
    
    def test_load_valid_config(self, policy_manager: DomainPolicyManager):
        """Verify valid config is loaded correctly."""
        # Then
        config = policy_manager.config
        assert config.default_policy.qps == 0.2
        assert len(config.allowlist) == 4
        assert len(config.graylist) == 3
        assert len(config.denylist) == 2
    
    def test_load_missing_config_uses_defaults(self, tmp_path: Path):
        """Verify missing config file results in default values."""
        # Given
        nonexistent_path = tmp_path / "nonexistent.yaml"
        
        # When
        manager = DomainPolicyManager(config_path=nonexistent_path)
        
        # Then
        assert manager.config.default_policy.qps == 0.2
        assert manager.config.allowlist == []
    
    def test_reload_clears_cache(self, policy_manager: DomainPolicyManager):
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
    
    def test_get_policy_allowlist_exact_match(self, policy_manager: DomainPolicyManager):
        """Verify allowlist exact domain match returns correct policy."""
        # When
        policy = policy_manager.get_policy("arxiv.org")
        
        # Then
        assert policy.trust_level == TrustLevel.ACADEMIC
        assert policy.qps == 0.25
        assert policy.internal_search is True
        assert policy.source == "allowlist"
    
    def test_get_policy_allowlist_suffix_match(self, policy_manager: DomainPolicyManager):
        """Verify allowlist suffix match works (e.g., 'go.jp' matches 'example.go.jp')."""
        # When
        policy = policy_manager.get_policy("example.go.jp")
        
        # Then
        assert policy.trust_level == TrustLevel.GOVERNMENT
        assert policy.qps == 0.15
        assert policy.source == "allowlist"
    
    def test_get_policy_graylist_pattern_match(self, policy_manager: DomainPolicyManager):
        """Verify graylist pattern match returns correct policy."""
        # When
        policy = policy_manager.get_policy("user.medium.com")
        
        # Then
        assert policy.qps == 0.1
        assert policy.source == "graylist"
    
    def test_get_policy_graylist_skip(self, policy_manager: DomainPolicyManager):
        """Verify graylist skip entry sets skip=True."""
        # When
        policy = policy_manager.get_policy("api.twitter.com")
        
        # Then
        assert policy.skip is True
        assert policy.skip_reason == "social_media"
        assert policy.source == "graylist"
    
    def test_get_policy_denylist(self, policy_manager: DomainPolicyManager):
        """Verify denylist entry sets skip=True with highest priority."""
        # When
        policy = policy_manager.get_policy("myblog.blogspot.com")
        
        # Then
        assert policy.skip is True
        assert policy.skip_reason == "low_quality_aggregator"
        assert policy.source == "denylist"
    
    def test_get_policy_cloudflare_site(self, policy_manager: DomainPolicyManager):
        """Verify cloudflare site sets headful_required and tor_blocked."""
        # When
        policy = policy_manager.get_policy("api.protected-site.com")
        
        # Then
        assert policy.headful_required is True
        assert policy.tor_blocked is True
        assert policy.tor_allowed is False  # tor_blocked implies tor_allowed=False
        assert policy.source == "cloudflare"
    
    def test_get_policy_default(self, policy_manager: DomainPolicyManager):
        """Verify unknown domain returns default policy."""
        # When
        policy = policy_manager.get_policy("unknown-domain.example")
        
        # Then
        assert policy.qps == 0.2
        assert policy.trust_level == TrustLevel.UNVERIFIED
        assert policy.source == "default"
    
    def test_get_policy_normalized_domain(self, policy_manager: DomainPolicyManager):
        """Verify domain normalization (lowercase, www removal)."""
        # When
        policy1 = policy_manager.get_policy("WWW.ARXIV.ORG")
        policy2 = policy_manager.get_policy("www.arxiv.org")
        policy3 = policy_manager.get_policy("arxiv.org")
        
        # Then - all should match the allowlist entry
        assert policy1.trust_level == TrustLevel.ACADEMIC
        assert policy2.trust_level == TrustLevel.ACADEMIC
        assert policy3.trust_level == TrustLevel.ACADEMIC


class TestDomainPolicyManagerConvenienceMethods:
    """Tests for convenience methods."""
    
    def test_should_skip_denylist(self, policy_manager: DomainPolicyManager):
        """Verify should_skip returns True for denylist domains."""
        # Then
        assert policy_manager.should_skip("test.blogspot.com") is True
    
    def test_should_skip_allowlist(self, policy_manager: DomainPolicyManager):
        """Verify should_skip returns False for allowlist domains."""
        # Then
        assert policy_manager.should_skip("arxiv.org") is False
    
    def test_get_trust_level(self, policy_manager: DomainPolicyManager):
        """Verify get_trust_level returns correct level."""
        # Then
        assert policy_manager.get_trust_level("arxiv.org") == TrustLevel.ACADEMIC
        assert policy_manager.get_trust_level("example.go.jp") == TrustLevel.GOVERNMENT
        assert policy_manager.get_trust_level("unknown.com") == TrustLevel.UNVERIFIED
    
    def test_get_trust_weight(self, policy_manager: DomainPolicyManager):
        """Verify get_trust_weight returns correct weight."""
        # Then
        assert policy_manager.get_trust_weight("arxiv.org") == 0.90  # academic
        assert policy_manager.get_trust_weight("example.go.jp") == 0.95  # government
    
    def test_get_qps_limit(self, policy_manager: DomainPolicyManager):
        """Verify get_qps_limit returns correct QPS."""
        # Then
        assert policy_manager.get_qps_limit("arxiv.org") == 0.25
        assert policy_manager.get_qps_limit("wikipedia.org") == 0.5
        assert policy_manager.get_qps_limit("unknown.com") == 0.2  # default


class TestDomainPolicyManagerInternalSearch:
    """Tests for internal search template functionality."""
    
    def test_get_internal_search_template_exists(self, policy_manager: DomainPolicyManager):
        """Verify existing template is returned."""
        # When
        template = policy_manager.get_internal_search_template("arxiv.org")
        
        # Then
        assert template is not None
        assert template.domain == "arxiv.org"
        assert template.search_input == "input[name='query']"
        assert template.search_button == "button[type='submit']"
        assert template.results_selector == ".arxiv-result"
    
    def test_get_internal_search_template_not_exists(self, policy_manager: DomainPolicyManager):
        """Verify None is returned for domain without template."""
        # When
        template = policy_manager.get_internal_search_template("unknown.com")
        
        # Then
        assert template is None
    
    def test_has_internal_search_true_from_allowlist(self, policy_manager: DomainPolicyManager):
        """Verify has_internal_search returns True for allowlist internal_search=True."""
        # Then
        assert policy_manager.has_internal_search("arxiv.org") is True
    
    def test_has_internal_search_true_from_template(self, policy_manager: DomainPolicyManager):
        """Verify has_internal_search returns True for domain with template."""
        # Then
        assert policy_manager.has_internal_search("pubmed.ncbi.nlm.nih.gov") is True
    
    def test_has_internal_search_false(self, policy_manager: DomainPolicyManager):
        """Verify has_internal_search returns False for unknown domains."""
        # Then
        assert policy_manager.has_internal_search("unknown.com") is False


class TestDomainPolicyManagerLists:
    """Tests for list retrieval methods."""
    
    def test_get_all_allowlist_domains(self, policy_manager: DomainPolicyManager):
        """Verify all allowlist domains are returned."""
        # When
        domains = policy_manager.get_all_allowlist_domains()
        
        # Then
        assert len(domains) == 4
        assert "go.jp" in domains
        assert "arxiv.org" in domains
        assert "wikipedia.org" in domains
        assert "example-primary.com" in domains
    
    def test_get_domains_by_trust_level_government(self, policy_manager: DomainPolicyManager):
        """Verify domains with GOVERNMENT trust level are returned."""
        # When
        domains = policy_manager.get_domains_by_trust_level(TrustLevel.GOVERNMENT)
        
        # Then
        assert len(domains) == 1
        assert "go.jp" in domains
    
    def test_get_domains_by_trust_level_academic(self, policy_manager: DomainPolicyManager):
        """Verify domains with ACADEMIC trust level are returned."""
        # When
        domains = policy_manager.get_domains_by_trust_level(TrustLevel.ACADEMIC)
        
        # Then
        assert len(domains) == 1
        assert "arxiv.org" in domains


class TestDomainPolicyManagerLearningState:
    """Tests for runtime learning state updates."""
    
    def test_update_learning_state(self, policy_manager: DomainPolicyManager):
        """Verify learning state update modifies cached policy."""
        # Given - get policy to populate cache
        policy = policy_manager.get_policy("example.com")
        assert policy.block_score == 0.0
        
        # When
        policy_manager.update_learning_state("example.com", {
            "block_score": 5.0,
            "captcha_rate": 0.3,
        })
        
        # Then - get policy again from cache
        updated_policy = policy_manager.get_policy("example.com")
        assert updated_policy.block_score == 5.0
        assert updated_policy.captcha_rate == 0.3
    
    def test_update_learning_state_cooldown(self, policy_manager: DomainPolicyManager):
        """Verify cooldown_until update affects is_in_cooldown."""
        # Given
        policy = policy_manager.get_policy("example.com")
        assert policy.is_in_cooldown is False
        
        # When
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        policy_manager.update_learning_state("example.com", {
            "cooldown_until": future_time,
        })
        
        # Then
        updated_policy = policy_manager.get_policy("example.com")
        assert updated_policy.is_in_cooldown is True


class TestDomainPolicyManagerCaching:
    """Tests for caching functionality."""
    
    def test_cache_hit(self, policy_manager: DomainPolicyManager):
        """Verify subsequent lookups use cache."""
        # Given
        _ = policy_manager.get_policy("arxiv.org")
        initial_stats = policy_manager.get_cache_stats()
        
        # When
        _ = policy_manager.get_policy("arxiv.org")
        final_stats = policy_manager.get_cache_stats()
        
        # Then - cache count should not increase
        assert initial_stats["cached_domains"] == final_stats["cached_domains"]
    
    def test_clear_cache(self, policy_manager: DomainPolicyManager):
        """Verify clear_cache empties the cache."""
        # Given
        _ = policy_manager.get_policy("example.com")
        _ = policy_manager.get_policy("arxiv.org")
        assert policy_manager.get_cache_stats()["cached_domains"] >= 2
        
        # When
        policy_manager.clear_cache()
        
        # Then
        assert policy_manager.get_cache_stats()["cached_domains"] == 0
    
    def test_cache_stats(self, policy_manager: DomainPolicyManager):
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
    
    def test_hot_reload_detects_file_change(self, tmp_path: Path):
        """Verify hot-reload detects and applies config file changes."""
        # Given - create initial config
        config_path = tmp_path / "domains.yaml"
        initial_config = """
default_policy:
  qps: 0.2
allowlist:
  - domain: "example.com"
    trust_level: "unverified"
"""
        config_path.write_text(initial_config, encoding="utf-8")
        
        manager = DomainPolicyManager(
            config_path=config_path,
            watch_interval=0.1,  # Short interval for testing
            enable_hot_reload=True,
        )
        
        # Verify initial state
        policy = manager.get_policy("example.com")
        assert policy.trust_level == TrustLevel.UNVERIFIED
        
        # When - modify config
        time.sleep(0.2)  # Ensure mtime changes
        updated_config = """
default_policy:
  qps: 0.3
allowlist:
  - domain: "example.com"
    trust_level: "government"
"""
        config_path.write_text(updated_config, encoding="utf-8")
        
        # Trigger reload check
        time.sleep(0.2)
        _ = manager.config  # This triggers the reload check
        
        # Then
        updated_policy = manager.get_policy("example.com")
        assert updated_policy.trust_level == TrustLevel.GOVERNMENT
    
    def test_reload_callback_called(self, tmp_path: Path):
        """Verify reload callbacks are called on config reload."""
        # Given
        config_path = tmp_path / "domains.yaml"
        config_path.write_text("default_policy:\n  qps: 0.2\n", encoding="utf-8")
        
        manager = DomainPolicyManager(config_path=config_path)
        callback_called = []
        
        def callback(config: DomainPolicyConfigSchema):
            callback_called.append(config.default_policy.qps)
        
        manager.add_reload_callback(callback)
        
        # When
        manager.reload()
        
        # Then
        assert len(callback_called) == 1
        assert callback_called[0] == 0.2
    
    def test_remove_reload_callback(self, tmp_path: Path):
        """Verify reload callbacks can be removed."""
        # Given
        config_path = tmp_path / "domains.yaml"
        config_path.write_text("default_policy:\n  qps: 0.2\n", encoding="utf-8")
        
        manager = DomainPolicyManager(config_path=config_path)
        callback_count = [0]
        
        def callback(config: DomainPolicyConfigSchema):
            callback_count[0] += 1
        
        manager.add_reload_callback(callback)
        manager.remove_reload_callback(callback)
        
        # When
        manager.reload()
        
        # Then
        assert callback_count[0] == 0


# =============================================================================
# Module-level Function Tests
# =============================================================================

class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""
    
    def test_get_domain_policy_manager_singleton(self, temp_config_file: Path):
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
    
    def test_reset_domain_policy_manager(self, temp_config_file: Path):
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
    
    def test_exact_match(self, policy_manager: DomainPolicyManager):
        """Verify exact domain match works."""
        # Then
        policy = policy_manager.get_policy("arxiv.org")
        assert policy.source == "allowlist"
    
    def test_glob_wildcard_match(self, policy_manager: DomainPolicyManager):
        """Verify glob wildcard pattern match works."""
        # Then - *.medium.com should match sub.medium.com
        policy = policy_manager.get_policy("blog.medium.com")
        assert policy.source == "graylist"
    
    def test_nested_subdomain_match(self, policy_manager: DomainPolicyManager):
        """Verify nested subdomain matches glob pattern."""
        # Then - *.twitter.com should match api.v2.twitter.com
        policy = policy_manager.get_policy("api.v2.twitter.com")
        assert policy.skip is True
    
    def test_suffix_match_go_jp(self, policy_manager: DomainPolicyManager):
        """Verify suffix match works for go.jp domains."""
        # Then - go.jp should match ministry.go.jp
        policy = policy_manager.get_policy("ministry.go.jp")
        assert policy.trust_level == TrustLevel.GOVERNMENT
        
        # Also test deeply nested
        policy2 = policy_manager.get_policy("sub.ministry.go.jp")
        assert policy2.trust_level == TrustLevel.GOVERNMENT
    
    def test_no_match_partial_domain(self, policy_manager: DomainPolicyManager):
        """Verify partial domain doesn't match (arxiv.org vs myarxiv.org)."""
        # Then - myarxiv.org should NOT match arxiv.org
        policy = policy_manager.get_policy("myarxiv.org")
        assert policy.source == "default"  # Not allowlist


# =============================================================================
# Trust Level Priority Tests
# =============================================================================

class TestTrustLevelPriority:
    """Tests for trust level hierarchy and weights."""
    
    def test_trust_level_hierarchy(self, policy_manager: DomainPolicyManager):
        """Verify trust level weights follow expected hierarchy."""
        # Given
        primary_policy = policy_manager.get_policy("example-primary.com")
        gov_policy = policy_manager.get_policy("example.go.jp")
        academic_policy = policy_manager.get_policy("arxiv.org")
        trusted_policy = policy_manager.get_policy("wikipedia.org")
        unknown_policy = policy_manager.get_policy("unknown.com")
        
        # Then - PRIMARY > GOVERNMENT > ACADEMIC > TRUSTED > UNKNOWN
        assert primary_policy.trust_weight > gov_policy.trust_weight
        assert gov_policy.trust_weight > academic_policy.trust_weight
        assert academic_policy.trust_weight > trusted_policy.trust_weight
        assert trusted_policy.trust_weight > unknown_policy.trust_weight


# =============================================================================
# Resolution Priority Tests
# =============================================================================

class TestResolutionPriority:
    """Tests for policy resolution priority order."""
    
    def test_denylist_has_highest_priority(self, tmp_path: Path):
        """Verify denylist overrides allowlist for same domain."""
        # Given - domain in both allowlist and denylist
        config = """
allowlist:
  - domain: "test.blogspot.com"
    trust_level: "trusted"
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
    
    def test_cloudflare_before_allowlist(self, tmp_path: Path):
        """Verify cloudflare settings are applied even to allowlist domains."""
        # Given
        config = """
allowlist:
  - domain: "example-protected.com"
    trust_level: "trusted"
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
    """Tests for SearchEnginePolicySchema (§3.1.4, §4.3)."""
    
    def test_default_values(self):
        """Verify default values are correctly set."""
        # Arrange & Act
        schema = SearchEnginePolicySchema()
        
        # Then
        assert schema.default_qps == 0.25
        assert schema.site_search_qps == 0.1
        assert schema.cooldown_min == 30
        assert schema.cooldown_max == 120
        assert schema.failure_threshold == 2
    
    def test_custom_values(self):
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
    
    def test_default_min_interval_property(self):
        """Verify default_min_interval is calculated correctly."""
        # Arrange & Act
        schema = SearchEnginePolicySchema(default_qps=0.25)
        
        # Then
        assert schema.default_min_interval == 4.0  # 1 / 0.25
    
    def test_site_search_min_interval_property(self):
        """Verify site_search_min_interval is calculated correctly."""
        # Arrange & Act
        schema = SearchEnginePolicySchema(site_search_qps=0.1)
        
        # Then
        assert schema.site_search_min_interval == 10.0  # 1 / 0.1
    
    def test_qps_validation_range(self):
        """Verify QPS validation enforces valid range."""
        # Then - too low
        with pytest.raises(ValueError):
            SearchEnginePolicySchema(default_qps=0.01)
        
        # Then - too high
        with pytest.raises(ValueError):
            SearchEnginePolicySchema(default_qps=2.0)


class TestPolicyBoundsEntrySchema:
    """Tests for PolicyBoundsEntrySchema (§4.6)."""
    
    def test_default_values(self):
        """Verify default values are set."""
        # Arrange & Act
        entry = PolicyBoundsEntrySchema()
        
        # Then
        assert entry.min == 0.0
        assert entry.max == 1.0
        assert entry.default == 0.5
        assert entry.step_up == 0.1
        assert entry.step_down == 0.1
    
    def test_custom_values(self):
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
    """Tests for PolicyBoundsSchema (§4.6)."""
    
    def test_default_bounds_exist(self):
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
    
    def test_engine_weight_defaults(self):
        """Verify engine_weight has correct default values."""
        # Arrange & Act
        schema = PolicyBoundsSchema()
        
        # Then
        assert schema.engine_weight.min == 0.1
        assert schema.engine_weight.max == 2.0
        assert schema.engine_weight.default == 1.0
    
    def test_domain_qps_defaults(self):
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
    
    def test_get_search_engine_policy(self, policy_manager: DomainPolicyManager):
        """Verify get_search_engine_policy returns SearchEnginePolicySchema."""
        # When
        policy = policy_manager.get_search_engine_policy()
        
        # Then
        assert isinstance(policy, SearchEnginePolicySchema)
        assert policy.default_qps == 0.25
        assert policy.site_search_qps == 0.1
    
    def test_get_search_engine_qps(self, policy_manager: DomainPolicyManager):
        """Verify get_search_engine_qps returns correct value."""
        # When
        qps = policy_manager.get_search_engine_qps()
        
        # Then
        assert qps == 0.25
    
    def test_get_search_engine_min_interval(self, policy_manager: DomainPolicyManager):
        """Verify get_search_engine_min_interval returns 1/QPS."""
        # When
        interval = policy_manager.get_search_engine_min_interval()
        
        # Then
        assert interval == 4.0  # 1 / 0.25
    
    def test_get_site_search_qps(self, policy_manager: DomainPolicyManager):
        """Verify get_site_search_qps returns correct value."""
        # When
        qps = policy_manager.get_site_search_qps()
        
        # Then
        assert qps == 0.1
    
    def test_get_site_search_min_interval(self, policy_manager: DomainPolicyManager):
        """Verify get_site_search_min_interval returns 1/QPS."""
        # When
        interval = policy_manager.get_site_search_min_interval()
        
        # Then
        assert interval == 10.0  # 1 / 0.1
    
    def test_get_circuit_breaker_cooldown_min(self, policy_manager: DomainPolicyManager):
        """Verify get_circuit_breaker_cooldown_min returns correct value."""
        # When
        cooldown = policy_manager.get_circuit_breaker_cooldown_min()
        
        # Then
        assert cooldown == 30
    
    def test_get_circuit_breaker_cooldown_max(self, policy_manager: DomainPolicyManager):
        """Verify get_circuit_breaker_cooldown_max returns correct value."""
        # When
        cooldown = policy_manager.get_circuit_breaker_cooldown_max()
        
        # Then
        assert cooldown == 120
    
    def test_get_circuit_breaker_failure_threshold(self, policy_manager: DomainPolicyManager):
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
    
    def test_get_policy_bounds(self, policy_manager: DomainPolicyManager):
        """Verify get_policy_bounds returns PolicyBoundsSchema."""
        # When
        bounds = policy_manager.get_policy_bounds()
        
        # Then
        assert isinstance(bounds, PolicyBoundsSchema)
        assert bounds.engine_weight is not None
        assert bounds.domain_qps is not None
    
    def test_get_bounds_for_parameter_engine_weight(self, policy_manager: DomainPolicyManager):
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
    
    def test_get_bounds_for_parameter_domain_qps(self, policy_manager: DomainPolicyManager):
        """Verify get_bounds_for_parameter returns correct bounds for domain_qps."""
        # When
        bounds = policy_manager.get_bounds_for_parameter("domain_qps")
        
        # Then
        assert bounds is not None
        assert bounds.min == 0.05
        assert bounds.max == 0.3
        assert bounds.default == 0.2
    
    def test_get_bounds_for_parameter_nonexistent(self, policy_manager: DomainPolicyManager):
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
    
    def test_missing_search_engine_policy_uses_defaults(self, tmp_path: Path):
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
    
    def test_missing_policy_bounds_uses_defaults(self, tmp_path: Path):
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

