"""
Tests for pivot exploration module.

Tests entity expansion patterns per §3.1.1:
- Organization → subsidiaries, officers, location, domain
- Domain → subdomain, certificate SAN, organization
- Person → aliases, handles, affiliations
"""

import pytest

from src.research.pivot import (
    PivotExpander,
    PivotSuggestion,
    PivotType,
    EntityType,
    detect_entity_type,
    get_pivot_expander,
)


class TestPivotExpander:
    """Tests for PivotExpander class."""
    
    @pytest.fixture
    def expander(self):
        """Create a PivotExpander instance."""
        return PivotExpander()
    
    # ==========================================================================
    # Organization Expansion Tests (§3.1.1)
    # ==========================================================================
    
    def test_expand_organization_returns_suggestions(self, expander):
        """Organization entity should generate multiple pivot suggestions."""
        suggestions = expander.expand_entity(
            entity_text="株式会社トヨタ自動車",
            entity_type=EntityType.ORGANIZATION,
        )
        
        assert len(suggestions) > 0
        assert all(isinstance(s, PivotSuggestion) for s in suggestions)
    
    def test_expand_organization_includes_subsidiary_pivot(self, expander):
        """Organization should have subsidiary pivot (子会社)."""
        suggestions = expander.expand_entity(
            entity_text="ソニーグループ",
            entity_type=EntityType.ORGANIZATION,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.ORG_SUBSIDIARY in pivot_types
        
        subsidiary_pivot = next(
            s for s in suggestions if s.pivot_type == PivotType.ORG_SUBSIDIARY
        )
        assert "子会社" in " ".join(subsidiary_pivot.query_examples)
    
    def test_expand_organization_includes_officer_pivot(self, expander):
        """Organization should have officer pivot (役員)."""
        suggestions = expander.expand_entity(
            entity_text="株式会社日立製作所",
            entity_type=EntityType.ORGANIZATION,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.ORG_OFFICER in pivot_types
        
        officer_pivot = next(
            s for s in suggestions if s.pivot_type == PivotType.ORG_OFFICER
        )
        assert officer_pivot.target_entity_type == EntityType.PERSON
    
    def test_expand_organization_includes_location_pivot(self, expander):
        """Organization should have location pivot (所在地)."""
        suggestions = expander.expand_entity(
            entity_text="任天堂株式会社",
            entity_type=EntityType.ORGANIZATION,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.ORG_LOCATION in pivot_types
    
    def test_expand_organization_includes_domain_pivot(self, expander):
        """Organization should have domain pivot (公式サイト)."""
        suggestions = expander.expand_entity(
            entity_text="楽天グループ株式会社",
            entity_type=EntityType.ORGANIZATION,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.ORG_DOMAIN in pivot_types
    
    def test_expand_organization_includes_registration_pivot(self, expander):
        """Organization should have registration pivot (法人登記)."""
        suggestions = expander.expand_entity(
            entity_text="パナソニック株式会社",
            entity_type=EntityType.ORGANIZATION,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.ORG_REGISTRATION in pivot_types
        
        registration_pivot = next(
            s for s in suggestions if s.pivot_type == PivotType.ORG_REGISTRATION
        )
        # Should recommend government sites
        assert "site:houjin-bangou.nta.go.jp" in registration_pivot.operators
    
    def test_expand_organization_english(self, expander):
        """English organization names should also work."""
        suggestions = expander.expand_entity(
            entity_text="Google Inc",
            entity_type=EntityType.ORGANIZATION,
        )
        
        assert len(suggestions) > 0
        # Should include English query variants
        subsidiary_pivot = next(
            s for s in suggestions if s.pivot_type == PivotType.ORG_SUBSIDIARY
        )
        assert "subsidiary" in " ".join(subsidiary_pivot.query_examples).lower()
    
    # ==========================================================================
    # Domain Expansion Tests (§3.1.1)
    # ==========================================================================
    
    def test_expand_domain_returns_suggestions(self, expander):
        """Domain entity should generate multiple pivot suggestions."""
        suggestions = expander.expand_entity(
            entity_text="example.co.jp",
            entity_type=EntityType.DOMAIN,
        )
        
        assert len(suggestions) > 0
        assert all(isinstance(s, PivotSuggestion) for s in suggestions)
    
    def test_expand_domain_includes_certificate_pivot(self, expander):
        """Domain should have certificate transparency pivot."""
        suggestions = expander.expand_entity(
            entity_text="toyota.co.jp",
            entity_type=EntityType.DOMAIN,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.DOMAIN_CERTIFICATE in pivot_types
        
        cert_pivot = next(
            s for s in suggestions if s.pivot_type == PivotType.DOMAIN_CERTIFICATE
        )
        assert "crt.sh" in " ".join(cert_pivot.query_examples)
    
    def test_expand_domain_includes_whois_pivot(self, expander):
        """Domain should have WHOIS pivot."""
        suggestions = expander.expand_entity(
            entity_text="sony.com",
            entity_type=EntityType.DOMAIN,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.DOMAIN_WHOIS in pivot_types
    
    def test_expand_domain_includes_organization_pivot(self, expander):
        """Domain should have organization pivot (運営会社)."""
        suggestions = expander.expand_entity(
            entity_text="rakuten.co.jp",
            entity_type=EntityType.DOMAIN,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.DOMAIN_ORGANIZATION in pivot_types
        
        org_pivot = next(
            s for s in suggestions if s.pivot_type == PivotType.DOMAIN_ORGANIZATION
        )
        assert org_pivot.target_entity_type == EntityType.ORGANIZATION
    
    def test_expand_domain_normalizes_url(self, expander):
        """Domain with protocol should be normalized."""
        suggestions = expander.expand_entity(
            entity_text="https://www.example.com/",
            entity_type=EntityType.DOMAIN,
        )
        
        # Check that queries don't include protocol
        for suggestion in suggestions:
            for example in suggestion.query_examples:
                assert "https://" not in example
                assert "www.example.com" in example or "example.com" in example
    
    # ==========================================================================
    # Person Expansion Tests (§3.1.1)
    # ==========================================================================
    
    def test_expand_person_returns_suggestions(self, expander):
        """Person entity should generate multiple pivot suggestions."""
        suggestions = expander.expand_entity(
            entity_text="山田太郎",
            entity_type=EntityType.PERSON,
        )
        
        assert len(suggestions) > 0
        assert all(isinstance(s, PivotSuggestion) for s in suggestions)
    
    def test_expand_person_includes_alias_pivot(self, expander):
        """Person should have alias pivot (別名)."""
        suggestions = expander.expand_entity(
            entity_text="田中一郎",
            entity_type=EntityType.PERSON,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.PERSON_ALIAS in pivot_types
    
    def test_expand_person_includes_affiliation_pivot(self, expander):
        """Person should have affiliation pivot (所属)."""
        suggestions = expander.expand_entity(
            entity_text="佐藤花子",
            entity_type=EntityType.PERSON,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.PERSON_AFFILIATION in pivot_types
        
        affiliation_pivot = next(
            s for s in suggestions if s.pivot_type == PivotType.PERSON_AFFILIATION
        )
        assert affiliation_pivot.target_entity_type == EntityType.ORGANIZATION
    
    def test_expand_person_includes_publication_pivot(self, expander):
        """Person should have publication pivot (論文・著書)."""
        suggestions = expander.expand_entity(
            entity_text="鈴木教授",
            entity_type=EntityType.PERSON,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        assert PivotType.PERSON_PUBLICATION in pivot_types
    
    def test_expand_person_handle_is_low_priority(self, expander):
        """Person handle pivot should be low priority (social media caution)."""
        suggestions = expander.expand_entity(
            entity_text="高橋次郎",
            entity_type=EntityType.PERSON,
            include_low_priority=True,
        )
        
        handle_pivot = next(
            (s for s in suggestions if s.pivot_type == PivotType.PERSON_HANDLE),
            None,
        )
        assert handle_pivot is not None
        assert handle_pivot.priority == "low"
    
    # ==========================================================================
    # Priority Filtering Tests
    # ==========================================================================
    
    def test_exclude_low_priority_by_default(self, expander):
        """Low priority pivots should be excluded by default."""
        suggestions = expander.expand_entity(
            entity_text="example.com",
            entity_type=EntityType.DOMAIN,
        )
        
        priorities = [s.priority for s in suggestions]
        assert "low" not in priorities
    
    def test_include_low_priority_when_requested(self, expander):
        """Low priority pivots should be included when requested."""
        suggestions = expander.expand_entity(
            entity_text="example.com",
            entity_type=EntityType.DOMAIN,
            include_low_priority=True,
        )
        
        pivot_types = [s.pivot_type for s in suggestions]
        # DNS pivot is low priority
        assert PivotType.DOMAIN_DNS in pivot_types
    
    def test_suggestions_sorted_by_priority(self, expander):
        """Suggestions should be sorted by priority (high > medium > low)."""
        suggestions = expander.expand_entity(
            entity_text="テスト株式会社",
            entity_type=EntityType.ORGANIZATION,
            include_low_priority=True,
        )
        
        priority_order = {"high": 0, "medium": 1, "low": 2}
        priorities = [priority_order[s.priority] for s in suggestions]
        
        assert priorities == sorted(priorities)
    
    # ==========================================================================
    # Multi-Entity Tests
    # ==========================================================================
    
    def test_expand_all_entities(self, expander):
        """Should expand multiple entities."""
        entities = [
            {"text": "株式会社ABC", "type": "organization"},
            {"text": "example.com", "type": "domain"},
            {"text": "山田太郎", "type": "person"},
        ]
        
        results = expander.expand_all_entities(entities)
        
        assert "株式会社ABC" in results
        assert "example.com" in results
        assert "山田太郎" in results
    
    def test_get_priority_pivots(self, expander):
        """Should get top priority pivots across entities."""
        entities = [
            {"text": "ソニー株式会社", "type": "organization"},
            {"text": "sony.com", "type": "domain"},
        ]
        
        pivots = expander.get_priority_pivots(entities, max_per_entity=2)
        
        # Should have at most 4 pivots (2 per entity)
        assert len(pivots) <= 4
        # Should be sorted by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        priorities = [priority_order[p.priority] for p in pivots]
        assert priorities == sorted(priorities)
    
    # ==========================================================================
    # Entity Type Detection Tests
    # ==========================================================================
    
    def test_detect_japanese_organization(self):
        """Should detect Japanese organization patterns."""
        assert detect_entity_type("株式会社テスト") == EntityType.ORGANIZATION
        assert detect_entity_type("テスト株式会社") == EntityType.ORGANIZATION
        assert detect_entity_type("有限会社サンプル") == EntityType.ORGANIZATION
    
    def test_detect_english_organization(self):
        """Should detect English organization patterns."""
        assert detect_entity_type("Google Inc") == EntityType.ORGANIZATION
        assert detect_entity_type("Microsoft Corp") == EntityType.ORGANIZATION
        assert detect_entity_type("Apple Ltd") == EntityType.ORGANIZATION
    
    def test_detect_domain(self):
        """Should detect domain patterns."""
        assert detect_entity_type("example.com") == EntityType.DOMAIN
        assert detect_entity_type("test.co.jp") == EntityType.DOMAIN
        assert detect_entity_type("sample.org") == EntityType.DOMAIN
    
    def test_detect_location(self):
        """Should detect location patterns."""
        assert detect_entity_type("東京都") == EntityType.LOCATION
        assert detect_entity_type("大阪市") == EntityType.LOCATION
        assert detect_entity_type("神奈川県") == EntityType.LOCATION
    
    def test_detect_unknown_type(self):
        """Unknown patterns should return None."""
        assert detect_entity_type("something") is None
        assert detect_entity_type("12345") is None
    
    # ==========================================================================
    # String Entity Type Tests
    # ==========================================================================
    
    def test_accept_string_entity_type(self, expander):
        """Should accept string entity types."""
        suggestions = expander.expand_entity(
            entity_text="テスト株式会社",
            entity_type="organization",  # String instead of enum
        )
        
        assert len(suggestions) > 0
    
    def test_handle_unknown_string_entity_type(self, expander):
        """Should handle unknown string entity types gracefully."""
        suggestions = expander.expand_entity(
            entity_text="テスト",
            entity_type="unknown_type",
        )
        
        assert suggestions == []
    
    # ==========================================================================
    # Query Template Tests
    # ==========================================================================
    
    def test_query_examples_contain_entity(self, expander):
        """Query examples should contain the entity text."""
        entity = "テスト企業株式会社"
        suggestions = expander.expand_entity(
            entity_text=entity,
            entity_type=EntityType.ORGANIZATION,
        )
        
        for suggestion in suggestions:
            # At least one example should contain the entity
            has_entity = any(entity in ex for ex in suggestion.query_examples)
            assert has_entity, f"No example contains entity in {suggestion.pivot_type}"
    
    def test_operators_are_valid(self, expander):
        """Suggested operators should be valid search operators."""
        suggestions = expander.expand_entity(
            entity_text="テスト株式会社",
            entity_type=EntityType.ORGANIZATION,
        )
        
        valid_prefixes = ["site:", "filetype:", "intitle:", "inurl:", "author:"]
        
        for suggestion in suggestions:
            for operator in suggestion.operators:
                if operator:
                    # Should either be a valid operator or a search term
                    is_valid = (
                        any(operator.startswith(p) for p in valid_prefixes)
                        or not ":" in operator
                    )
                    assert is_valid, f"Invalid operator: {operator}"


class TestGetPivotExpander:
    """Tests for get_pivot_expander function."""
    
    def test_returns_expander_instance(self):
        """Should return a PivotExpander instance."""
        expander = get_pivot_expander()
        assert isinstance(expander, PivotExpander)
    
    def test_expander_is_functional(self):
        """Returned expander should be functional."""
        expander = get_pivot_expander()
        suggestions = expander.expand_entity(
            entity_text="テスト株式会社",
            entity_type=EntityType.ORGANIZATION,
        )
        assert len(suggestions) > 0

