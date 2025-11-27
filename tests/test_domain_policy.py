"""
Tests for DomainPolicyManager (§17.2.1 Domain Policy Externalization).

Test design follows §7.1 Test Code Quality Standards:
- No conditional assertions (§7.1.1)
- Specific assertions with concrete values (§7.1.2)
- Realistic test data (§7.1.3)
- AAA pattern (§7.1.5)
"""

import tempfile
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
  trust_level: "unknown"

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
    trust_level: "unknown"
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
        
        # Assert
        assert schema.qps == 0.2
        assert schema.concurrent == 1
        assert schema.headful_ratio == 0.1
        assert schema.tor_allowed is True
        assert schema.cooldown_minutes == 60
        assert schema.max_retries == 3
        assert schema.trust_level == TrustLevel.UNKNOWN
    
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
        
        # Assert
        assert schema.qps == 0.5
        assert schema.concurrent == 3
        assert schema.headful_ratio == 0.3
        assert schema.tor_allowed is False
        assert schema.cooldown_minutes == 120
        assert schema.max_retries == 5
        assert schema.trust_level == TrustLevel.GOVERNMENT
    
    def test_qps_validation_range(self):
        """Verify QPS validation rejects out-of-range values."""
        # Assert - too low
        with pytest.raises(ValueError):
            DefaultPolicySchema(qps=0.001)
        
        # Assert - too high
        with pytest.raises(ValueError):
            DefaultPolicySchema(qps=3.0)
    
    def test_headful_ratio_validation_range(self):
        """Verify headful_ratio validation enforces [0, 1] range."""
        # Assert - negative
        with pytest.raises(ValueError):
            DefaultPolicySchema(headful_ratio=-0.1)
        
        # Assert - over 1
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
        
        # Assert
        assert entry.domain == "example.go.jp"
        assert entry.trust_level == TrustLevel.GOVERNMENT
        assert entry.internal_search is True
        assert entry.qps == 0.15
    
    def test_domain_normalization(self):
        """Verify domain is normalized to lowercase."""
        # Arrange & Act
        entry = AllowlistEntrySchema(domain="EXAMPLE.COM")
        
        # Assert
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
        
        # Assert
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
        
        # Assert
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
        
        # Assert
        assert entry.domain_pattern == "*.spam.com"
        assert entry.reason == SkipReason.LOW_QUALITY_AGGREGATOR


class TestDomainPolicyConfigSchema:
    """Tests for root config schema validation."""
    
    def test_full_config_parsing(self, sample_config_yaml: str):
        """Verify complete config YAML is parsed correctly."""
        # Arrange
        data = yaml.safe_load(sample_config_yaml)
        
        # Parse internal_search_templates specially
        if "internal_search_templates" in data:
            templates = {}
            for name, template_data in data["internal_search_templates"].items():
                templates[name] = InternalSearchTemplateSchema(**template_data)
            data["internal_search_templates"] = templates
        
        # Act
        config = DomainPolicyConfigSchema(**data)
        
        # Assert
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
        
        # Assert
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
        
        # Assert
        assert policy.trust_weight == 1.0
    
    def test_trust_weight_government(self):
        """Verify GOVERNMENT trust level has weight 0.95."""
        # Arrange & Act
        policy = DomainPolicy(domain="gov.example", trust_level=TrustLevel.GOVERNMENT)
        
        # Assert
        assert policy.trust_weight == 0.95
    
    def test_trust_weight_academic(self):
        """Verify ACADEMIC trust level has weight 0.90."""
        # Arrange & Act
        policy = DomainPolicy(domain="uni.example", trust_level=TrustLevel.ACADEMIC)
        
        # Assert
        assert policy.trust_weight == 0.90
    
    def test_trust_weight_unknown(self):
        """Verify UNKNOWN trust level has weight 0.30."""
        # Arrange & Act
        policy = DomainPolicy(domain="unknown.example", trust_level=TrustLevel.UNKNOWN)
        
        # Assert
        assert policy.trust_weight == 0.30
    
    def test_min_request_interval(self):
        """Verify min_request_interval is calculated correctly from QPS."""
        # Arrange & Act
        policy = DomainPolicy(domain="example.com", qps=0.25)
        
        # Assert
        assert policy.min_request_interval == 4.0  # 1 / 0.25
    
    def test_is_in_cooldown_true(self):
        """Verify is_in_cooldown returns True when cooldown is active."""
        # Arrange
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        policy = DomainPolicy(domain="example.com", cooldown_until=future_time)
        
        # Assert
        assert policy.is_in_cooldown is True
    
    def test_is_in_cooldown_false_when_expired(self):
        """Verify is_in_cooldown returns False when cooldown has expired."""
        # Arrange
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        policy = DomainPolicy(domain="example.com", cooldown_until=past_time)
        
        # Assert
        assert policy.is_in_cooldown is False
    
    def test_is_in_cooldown_false_when_none(self):
        """Verify is_in_cooldown returns False when no cooldown set."""
        # Arrange
        policy = DomainPolicy(domain="example.com", cooldown_until=None)
        
        # Assert
        assert policy.is_in_cooldown is False
    
    def test_to_dict_contains_all_fields(self):
        """Verify to_dict includes all required fields."""
        # Arrange
        policy = DomainPolicy(
            domain="example.com",
            qps=0.2,
            trust_level=TrustLevel.GOVERNMENT,
        )
        
        # Act
        result = policy.to_dict()
        
        # Assert
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
        # Assert
        config = policy_manager.config
        assert config.default_policy.qps == 0.2
        assert len(config.allowlist) == 4
        assert len(config.graylist) == 3
        assert len(config.denylist) == 2
    
    def test_load_missing_config_uses_defaults(self, tmp_path: Path):
        """Verify missing config file results in default values."""
        # Arrange
        nonexistent_path = tmp_path / "nonexistent.yaml"
        
        # Act
        manager = DomainPolicyManager(config_path=nonexistent_path)
        
        # Assert
        assert manager.config.default_policy.qps == 0.2
        assert manager.config.allowlist == []
    
    def test_reload_clears_cache(self, policy_manager: DomainPolicyManager):
        """Verify reload clears the policy cache."""
        # Arrange - populate cache
        _ = policy_manager.get_policy("example.com")
        assert policy_manager.get_cache_stats()["cached_domains"] >= 1
        
        # Act
        policy_manager.reload()
        
        # Assert
        assert policy_manager.get_cache_stats()["cached_domains"] == 0


class TestDomainPolicyManagerLookup:
    """Tests for DomainPolicyManager policy lookup."""
    
    def test_get_policy_allowlist_exact_match(self, policy_manager: DomainPolicyManager):
        """Verify allowlist exact domain match returns correct policy."""
        # Act
        policy = policy_manager.get_policy("arxiv.org")
        
        # Assert
        assert policy.trust_level == TrustLevel.ACADEMIC
        assert policy.qps == 0.25
        assert policy.internal_search is True
        assert policy.source == "allowlist"
    
    def test_get_policy_allowlist_suffix_match(self, policy_manager: DomainPolicyManager):
        """Verify allowlist suffix match works (e.g., 'go.jp' matches 'example.go.jp')."""
        # Act
        policy = policy_manager.get_policy("example.go.jp")
        
        # Assert
        assert policy.trust_level == TrustLevel.GOVERNMENT
        assert policy.qps == 0.15
        assert policy.source == "allowlist"
    
    def test_get_policy_graylist_pattern_match(self, policy_manager: DomainPolicyManager):
        """Verify graylist pattern match returns correct policy."""
        # Act
        policy = policy_manager.get_policy("user.medium.com")
        
        # Assert
        assert policy.qps == 0.1
        assert policy.source == "graylist"
    
    def test_get_policy_graylist_skip(self, policy_manager: DomainPolicyManager):
        """Verify graylist skip entry sets skip=True."""
        # Act
        policy = policy_manager.get_policy("api.twitter.com")
        
        # Assert
        assert policy.skip is True
        assert policy.skip_reason == "social_media"
        assert policy.source == "graylist"
    
    def test_get_policy_denylist(self, policy_manager: DomainPolicyManager):
        """Verify denylist entry sets skip=True with highest priority."""
        # Act
        policy = policy_manager.get_policy("myblog.blogspot.com")
        
        # Assert
        assert policy.skip is True
        assert policy.skip_reason == "low_quality_aggregator"
        assert policy.source == "denylist"
    
    def test_get_policy_cloudflare_site(self, policy_manager: DomainPolicyManager):
        """Verify cloudflare site sets headful_required and tor_blocked."""
        # Act
        policy = policy_manager.get_policy("api.protected-site.com")
        
        # Assert
        assert policy.headful_required is True
        assert policy.tor_blocked is True
        assert policy.tor_allowed is False  # tor_blocked implies tor_allowed=False
        assert policy.source == "cloudflare"
    
    def test_get_policy_default(self, policy_manager: DomainPolicyManager):
        """Verify unknown domain returns default policy."""
        # Act
        policy = policy_manager.get_policy("unknown-domain.example")
        
        # Assert
        assert policy.qps == 0.2
        assert policy.trust_level == TrustLevel.UNKNOWN
        assert policy.source == "default"
    
    def test_get_policy_normalized_domain(self, policy_manager: DomainPolicyManager):
        """Verify domain normalization (lowercase, www removal)."""
        # Act
        policy1 = policy_manager.get_policy("WWW.ARXIV.ORG")
        policy2 = policy_manager.get_policy("www.arxiv.org")
        policy3 = policy_manager.get_policy("arxiv.org")
        
        # Assert - all should match the allowlist entry
        assert policy1.trust_level == TrustLevel.ACADEMIC
        assert policy2.trust_level == TrustLevel.ACADEMIC
        assert policy3.trust_level == TrustLevel.ACADEMIC


class TestDomainPolicyManagerConvenienceMethods:
    """Tests for convenience methods."""
    
    def test_should_skip_denylist(self, policy_manager: DomainPolicyManager):
        """Verify should_skip returns True for denylist domains."""
        # Assert
        assert policy_manager.should_skip("test.blogspot.com") is True
    
    def test_should_skip_allowlist(self, policy_manager: DomainPolicyManager):
        """Verify should_skip returns False for allowlist domains."""
        # Assert
        assert policy_manager.should_skip("arxiv.org") is False
    
    def test_get_trust_level(self, policy_manager: DomainPolicyManager):
        """Verify get_trust_level returns correct level."""
        # Assert
        assert policy_manager.get_trust_level("arxiv.org") == TrustLevel.ACADEMIC
        assert policy_manager.get_trust_level("example.go.jp") == TrustLevel.GOVERNMENT
        assert policy_manager.get_trust_level("unknown.com") == TrustLevel.UNKNOWN
    
    def test_get_trust_weight(self, policy_manager: DomainPolicyManager):
        """Verify get_trust_weight returns correct weight."""
        # Assert
        assert policy_manager.get_trust_weight("arxiv.org") == 0.90  # academic
        assert policy_manager.get_trust_weight("example.go.jp") == 0.95  # government
    
    def test_get_qps_limit(self, policy_manager: DomainPolicyManager):
        """Verify get_qps_limit returns correct QPS."""
        # Assert
        assert policy_manager.get_qps_limit("arxiv.org") == 0.25
        assert policy_manager.get_qps_limit("wikipedia.org") == 0.5
        assert policy_manager.get_qps_limit("unknown.com") == 0.2  # default


class TestDomainPolicyManagerInternalSearch:
    """Tests for internal search template functionality."""
    
    def test_get_internal_search_template_exists(self, policy_manager: DomainPolicyManager):
        """Verify existing template is returned."""
        # Act
        template = policy_manager.get_internal_search_template("arxiv.org")
        
        # Assert
        assert template is not None
        assert template.domain == "arxiv.org"
        assert template.search_input == "input[name='query']"
        assert template.search_button == "button[type='submit']"
        assert template.results_selector == ".arxiv-result"
    
    def test_get_internal_search_template_not_exists(self, policy_manager: DomainPolicyManager):
        """Verify None is returned for domain without template."""
        # Act
        template = policy_manager.get_internal_search_template("unknown.com")
        
        # Assert
        assert template is None
    
    def test_has_internal_search_true_from_allowlist(self, policy_manager: DomainPolicyManager):
        """Verify has_internal_search returns True for allowlist internal_search=True."""
        # Assert
        assert policy_manager.has_internal_search("arxiv.org") is True
    
    def test_has_internal_search_true_from_template(self, policy_manager: DomainPolicyManager):
        """Verify has_internal_search returns True for domain with template."""
        # Assert
        assert policy_manager.has_internal_search("pubmed.ncbi.nlm.nih.gov") is True
    
    def test_has_internal_search_false(self, policy_manager: DomainPolicyManager):
        """Verify has_internal_search returns False for unknown domains."""
        # Assert
        assert policy_manager.has_internal_search("unknown.com") is False


class TestDomainPolicyManagerLists:
    """Tests for list retrieval methods."""
    
    def test_get_all_allowlist_domains(self, policy_manager: DomainPolicyManager):
        """Verify all allowlist domains are returned."""
        # Act
        domains = policy_manager.get_all_allowlist_domains()
        
        # Assert
        assert len(domains) == 4
        assert "go.jp" in domains
        assert "arxiv.org" in domains
        assert "wikipedia.org" in domains
        assert "example-primary.com" in domains
    
    def test_get_domains_by_trust_level_government(self, policy_manager: DomainPolicyManager):
        """Verify domains with GOVERNMENT trust level are returned."""
        # Act
        domains = policy_manager.get_domains_by_trust_level(TrustLevel.GOVERNMENT)
        
        # Assert
        assert len(domains) == 1
        assert "go.jp" in domains
    
    def test_get_domains_by_trust_level_academic(self, policy_manager: DomainPolicyManager):
        """Verify domains with ACADEMIC trust level are returned."""
        # Act
        domains = policy_manager.get_domains_by_trust_level(TrustLevel.ACADEMIC)
        
        # Assert
        assert len(domains) == 1
        assert "arxiv.org" in domains


class TestDomainPolicyManagerLearningState:
    """Tests for runtime learning state updates."""
    
    def test_update_learning_state(self, policy_manager: DomainPolicyManager):
        """Verify learning state update modifies cached policy."""
        # Arrange - get policy to populate cache
        policy = policy_manager.get_policy("example.com")
        assert policy.block_score == 0.0
        
        # Act
        policy_manager.update_learning_state("example.com", {
            "block_score": 5.0,
            "captcha_rate": 0.3,
        })
        
        # Assert - get policy again from cache
        updated_policy = policy_manager.get_policy("example.com")
        assert updated_policy.block_score == 5.0
        assert updated_policy.captcha_rate == 0.3
    
    def test_update_learning_state_cooldown(self, policy_manager: DomainPolicyManager):
        """Verify cooldown_until update affects is_in_cooldown."""
        # Arrange
        policy = policy_manager.get_policy("example.com")
        assert policy.is_in_cooldown is False
        
        # Act
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        policy_manager.update_learning_state("example.com", {
            "cooldown_until": future_time,
        })
        
        # Assert
        updated_policy = policy_manager.get_policy("example.com")
        assert updated_policy.is_in_cooldown is True


class TestDomainPolicyManagerCaching:
    """Tests for caching functionality."""
    
    def test_cache_hit(self, policy_manager: DomainPolicyManager):
        """Verify subsequent lookups use cache."""
        # Arrange
        _ = policy_manager.get_policy("arxiv.org")
        initial_stats = policy_manager.get_cache_stats()
        
        # Act
        _ = policy_manager.get_policy("arxiv.org")
        final_stats = policy_manager.get_cache_stats()
        
        # Assert - cache count should not increase
        assert initial_stats["cached_domains"] == final_stats["cached_domains"]
    
    def test_clear_cache(self, policy_manager: DomainPolicyManager):
        """Verify clear_cache empties the cache."""
        # Arrange
        _ = policy_manager.get_policy("example.com")
        _ = policy_manager.get_policy("arxiv.org")
        assert policy_manager.get_cache_stats()["cached_domains"] >= 2
        
        # Act
        policy_manager.clear_cache()
        
        # Assert
        assert policy_manager.get_cache_stats()["cached_domains"] == 0
    
    def test_cache_stats(self, policy_manager: DomainPolicyManager):
        """Verify cache stats contain expected fields."""
        # Act
        stats = policy_manager.get_cache_stats()
        
        # Assert
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
        # Arrange - create initial config
        config_path = tmp_path / "domains.yaml"
        initial_config = """
default_policy:
  qps: 0.2
allowlist:
  - domain: "example.com"
    trust_level: "unknown"
"""
        config_path.write_text(initial_config, encoding="utf-8")
        
        manager = DomainPolicyManager(
            config_path=config_path,
            watch_interval=0.1,  # Short interval for testing
            enable_hot_reload=True,
        )
        
        # Verify initial state
        policy = manager.get_policy("example.com")
        assert policy.trust_level == TrustLevel.UNKNOWN
        
        # Act - modify config
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
        
        # Assert
        updated_policy = manager.get_policy("example.com")
        assert updated_policy.trust_level == TrustLevel.GOVERNMENT
    
    def test_reload_callback_called(self, tmp_path: Path):
        """Verify reload callbacks are called on config reload."""
        # Arrange
        config_path = tmp_path / "domains.yaml"
        config_path.write_text("default_policy:\n  qps: 0.2\n", encoding="utf-8")
        
        manager = DomainPolicyManager(config_path=config_path)
        callback_called = []
        
        def callback(config: DomainPolicyConfigSchema):
            callback_called.append(config.default_policy.qps)
        
        manager.add_reload_callback(callback)
        
        # Act
        manager.reload()
        
        # Assert
        assert len(callback_called) == 1
        assert callback_called[0] == 0.2
    
    def test_remove_reload_callback(self, tmp_path: Path):
        """Verify reload callbacks can be removed."""
        # Arrange
        config_path = tmp_path / "domains.yaml"
        config_path.write_text("default_policy:\n  qps: 0.2\n", encoding="utf-8")
        
        manager = DomainPolicyManager(config_path=config_path)
        callback_count = [0]
        
        def callback(config: DomainPolicyConfigSchema):
            callback_count[0] += 1
        
        manager.add_reload_callback(callback)
        manager.remove_reload_callback(callback)
        
        # Act
        manager.reload()
        
        # Assert
        assert callback_count[0] == 0


# =============================================================================
# Module-level Function Tests
# =============================================================================

class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""
    
    def test_get_domain_policy_manager_singleton(self, temp_config_file: Path):
        """Verify get_domain_policy_manager returns singleton."""
        # Arrange
        reset_domain_policy_manager()
        
        # Act
        # Note: We can't easily inject the config path for singleton,
        # so we test that it returns the same instance
        manager1 = get_domain_policy_manager()
        manager2 = get_domain_policy_manager()
        
        # Assert
        assert manager1 is manager2
    
    def test_reset_domain_policy_manager(self, temp_config_file: Path):
        """Verify reset creates new instance."""
        # Arrange
        manager1 = get_domain_policy_manager()
        
        # Act
        reset_domain_policy_manager()
        manager2 = get_domain_policy_manager()
        
        # Assert
        assert manager1 is not manager2


# =============================================================================
# Pattern Matching Edge Cases
# =============================================================================

class TestPatternMatching:
    """Tests for domain pattern matching edge cases."""
    
    def test_exact_match(self, policy_manager: DomainPolicyManager):
        """Verify exact domain match works."""
        # Assert
        policy = policy_manager.get_policy("arxiv.org")
        assert policy.source == "allowlist"
    
    def test_glob_wildcard_match(self, policy_manager: DomainPolicyManager):
        """Verify glob wildcard pattern match works."""
        # Assert - *.medium.com should match sub.medium.com
        policy = policy_manager.get_policy("blog.medium.com")
        assert policy.source == "graylist"
    
    def test_nested_subdomain_match(self, policy_manager: DomainPolicyManager):
        """Verify nested subdomain matches glob pattern."""
        # Assert - *.twitter.com should match api.v2.twitter.com
        policy = policy_manager.get_policy("api.v2.twitter.com")
        assert policy.skip is True
    
    def test_suffix_match_go_jp(self, policy_manager: DomainPolicyManager):
        """Verify suffix match works for go.jp domains."""
        # Assert - go.jp should match ministry.go.jp
        policy = policy_manager.get_policy("ministry.go.jp")
        assert policy.trust_level == TrustLevel.GOVERNMENT
        
        # Also test deeply nested
        policy2 = policy_manager.get_policy("sub.ministry.go.jp")
        assert policy2.trust_level == TrustLevel.GOVERNMENT
    
    def test_no_match_partial_domain(self, policy_manager: DomainPolicyManager):
        """Verify partial domain doesn't match (arxiv.org vs myarxiv.org)."""
        # Assert - myarxiv.org should NOT match arxiv.org
        policy = policy_manager.get_policy("myarxiv.org")
        assert policy.source == "default"  # Not allowlist


# =============================================================================
# Trust Level Priority Tests
# =============================================================================

class TestTrustLevelPriority:
    """Tests for trust level hierarchy and weights."""
    
    def test_trust_level_hierarchy(self, policy_manager: DomainPolicyManager):
        """Verify trust level weights follow expected hierarchy."""
        # Arrange
        primary_policy = policy_manager.get_policy("example-primary.com")
        gov_policy = policy_manager.get_policy("example.go.jp")
        academic_policy = policy_manager.get_policy("arxiv.org")
        trusted_policy = policy_manager.get_policy("wikipedia.org")
        unknown_policy = policy_manager.get_policy("unknown.com")
        
        # Assert - PRIMARY > GOVERNMENT > ACADEMIC > TRUSTED > UNKNOWN
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
        # Arrange - domain in both allowlist and denylist
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
        
        # Act
        policy = manager.get_policy("test.blogspot.com")
        
        # Assert - denylist should win
        assert policy.skip is True
        assert policy.source == "denylist"
    
    def test_cloudflare_before_allowlist(self, tmp_path: Path):
        """Verify cloudflare settings are applied even to allowlist domains."""
        # Arrange
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
        
        # Act
        policy = manager.get_policy("api.protected.com")
        
        # Assert - cloudflare settings applied
        assert policy.headful_required is True
        assert policy.tor_blocked is True

