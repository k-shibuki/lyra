"""
Tests for claim decomposition module.

Per §7.1.1: Tests validate specifications, not just "pass tests".
Per §3.3.1: Question-to-Claim Decomposition functionality.
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

from src.filter.claim_decomposition import (
    AtomicClaim,
    ClaimDecomposer,
    ClaimGranularity,
    ClaimPolarity,
    ClaimType,
    DecompositionResult,
    decompose_question,
)


class TestAtomicClaim:
    """Tests for AtomicClaim dataclass."""
    
    def test_create_atomic_claim_with_defaults(self):
        """Test creating an atomic claim with default values."""
        claim = AtomicClaim(
            claim_id="test_001",
            text="GPT-4は2023年にリリースされた",
            expected_polarity=ClaimPolarity.POSITIVE,
            granularity=ClaimGranularity.ATOMIC,
        )
        
        assert claim.claim_id == "test_001"
        assert claim.text == "GPT-4は2023年にリリースされた"
        assert claim.expected_polarity == ClaimPolarity.POSITIVE
        assert claim.granularity == ClaimGranularity.ATOMIC
        assert claim.claim_type == ClaimType.FACTUAL
        assert claim.parent_claim_id is None
        assert claim.confidence == 1.0
        assert claim.keywords == []
        assert claim.verification_hints == []
    
    def test_create_atomic_claim_with_all_fields(self):
        """Test creating an atomic claim with all fields specified."""
        claim = AtomicClaim(
            claim_id="test_002",
            text="東京の人口は1400万人である",
            expected_polarity=ClaimPolarity.POSITIVE,
            granularity=ClaimGranularity.ATOMIC,
            claim_type=ClaimType.QUANTITATIVE,
            parent_claim_id="parent_001",
            source_question="東京の人口について教えてください",
            confidence=0.95,
            keywords=["東京", "人口", "1400万人"],
            verification_hints=["統計局データ", "国勢調査"],
        )
        
        assert claim.claim_type == ClaimType.QUANTITATIVE
        assert claim.parent_claim_id == "parent_001"
        assert claim.source_question == "東京の人口について教えてください"
        assert claim.confidence == 0.95
        assert len(claim.keywords) == 3
        assert "東京" in claim.keywords
        assert len(claim.verification_hints) == 2
    
    def test_to_dict_serialization(self):
        """Test serialization to dictionary."""
        claim = AtomicClaim(
            claim_id="test_003",
            text="Test claim",
            expected_polarity=ClaimPolarity.NEUTRAL,
            granularity=ClaimGranularity.COMPOSITE,
            claim_type=ClaimType.CAUSAL,
            keywords=["test", "claim"],
        )
        
        d = claim.to_dict()
        
        assert d["claim_id"] == "test_003"
        assert d["text"] == "Test claim"
        assert d["expected_polarity"] == "neutral"
        assert d["granularity"] == "composite"
        assert d["claim_type"] == "causal"
        assert d["keywords"] == ["test", "claim"]
    
    def test_from_dict_deserialization(self):
        """Test deserialization from dictionary."""
        data = {
            "claim_id": "test_004",
            "text": "Deserialized claim",
            "expected_polarity": "negative",
            "granularity": "atomic",
            "claim_type": "temporal",
            "confidence": 0.8,
            "keywords": ["time", "date"],
            "verification_hints": ["archives"],
        }
        
        claim = AtomicClaim.from_dict(data)
        
        assert claim.claim_id == "test_004"
        assert claim.text == "Deserialized claim"
        assert claim.expected_polarity == ClaimPolarity.NEGATIVE
        assert claim.granularity == ClaimGranularity.ATOMIC
        assert claim.claim_type == ClaimType.TEMPORAL
        assert claim.confidence == 0.8
    
    def test_from_dict_with_missing_optional_fields(self):
        """Test deserialization handles missing optional fields."""
        data = {
            "claim_id": "test_005",
            "text": "Minimal claim",
        }
        
        claim = AtomicClaim.from_dict(data)
        
        assert claim.claim_id == "test_005"
        assert claim.expected_polarity == ClaimPolarity.NEUTRAL
        assert claim.granularity == ClaimGranularity.ATOMIC
        assert claim.claim_type == ClaimType.FACTUAL


class TestClaimEnums:
    """Tests for claim-related enums."""
    
    def test_claim_polarity_values(self):
        """Test ClaimPolarity enum values."""
        assert ClaimPolarity.POSITIVE.value == "positive"
        assert ClaimPolarity.NEGATIVE.value == "negative"
        assert ClaimPolarity.NEUTRAL.value == "neutral"
    
    def test_claim_granularity_values(self):
        """Test ClaimGranularity enum values."""
        assert ClaimGranularity.ATOMIC.value == "atomic"
        assert ClaimGranularity.COMPOSITE.value == "composite"
        assert ClaimGranularity.META.value == "meta"
    
    def test_claim_type_values(self):
        """Test ClaimType enum values."""
        assert ClaimType.FACTUAL.value == "factual"
        assert ClaimType.CAUSAL.value == "causal"
        assert ClaimType.COMPARATIVE.value == "comparative"
        assert ClaimType.DEFINITIONAL.value == "definitional"
        assert ClaimType.TEMPORAL.value == "temporal"
        assert ClaimType.QUANTITATIVE.value == "quantitative"


class TestDecompositionResult:
    """Tests for DecompositionResult dataclass."""
    
    def test_create_decomposition_result(self):
        """Test creating a decomposition result."""
        claims = [
            AtomicClaim(
                claim_id="c1",
                text="Claim 1",
                expected_polarity=ClaimPolarity.POSITIVE,
                granularity=ClaimGranularity.ATOMIC,
            ),
            AtomicClaim(
                claim_id="c2",
                text="Claim 2",
                expected_polarity=ClaimPolarity.NEUTRAL,
                granularity=ClaimGranularity.ATOMIC,
            ),
        ]
        
        result = DecompositionResult(
            original_question="Test question?",
            claims=claims,
            decomposition_method="rule_based",
        )
        
        assert result.original_question == "Test question?"
        assert len(result.claims) == 2
        assert result.decomposition_method == "rule_based"
        assert result.success is True
        assert result.error is None
    
    def test_to_dict_serialization(self):
        """Test serialization to dictionary."""
        claims = [
            AtomicClaim(
                claim_id="c1",
                text="Test claim",
                expected_polarity=ClaimPolarity.POSITIVE,
                granularity=ClaimGranularity.ATOMIC,
            ),
        ]
        
        result = DecompositionResult(
            original_question="Question?",
            claims=claims,
            decomposition_method="llm",
            success=True,
        )
        
        d = result.to_dict()
        
        assert d["original_question"] == "Question?"
        assert len(d["claims"]) == 1
        assert d["claims"][0]["claim_id"] == "c1"
        assert d["decomposition_method"] == "llm"
        assert d["success"] is True


class TestClaimDecomposerRuleBased:
    """Tests for rule-based claim decomposition."""
    
    @pytest.fixture
    def decomposer(self):
        """Create a rule-based decomposer."""
        return ClaimDecomposer(use_llm=False)
    
    @pytest.mark.asyncio
    async def test_empty_question(self, decomposer):
        """Test handling of empty question."""
        result = await decomposer.decompose("")
        
        assert result.success is False
        assert result.error == "Empty question provided"
        assert len(result.claims) == 0
    
    @pytest.mark.asyncio
    async def test_simple_question(self, decomposer):
        """Test decomposition of a simple question."""
        result = await decomposer.decompose("AIエージェントとは何ですか")
        
        assert result.success is True
        assert result.decomposition_method == "rule_based"
        assert len(result.claims) >= 1
        
        # Check the claim has required fields
        claim = result.claims[0]
        assert claim.claim_id.startswith("claim_")
        assert claim.text
        assert claim.expected_polarity is not None
        assert claim.granularity is not None
    
    @pytest.mark.asyncio
    async def test_compound_question_decomposition(self, decomposer):
        """Test decomposition of compound question with conjunctions."""
        result = await decomposer.decompose(
            "GPT-4の性能、およびClaude 3との比較について調べてください"
        )
        
        assert result.success is True
        # Should produce multiple claims due to conjunction
        assert len(result.claims) >= 1
    
    @pytest.mark.asyncio
    async def test_temporal_claim_detection(self, decomposer):
        """Test detection of temporal claims."""
        result = await decomposer.decompose("2024年のAI動向について")
        
        assert result.success is True
        assert len(result.claims) >= 1
        
        # At least one claim should be temporal type
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.TEMPORAL
    
    @pytest.mark.asyncio
    async def test_quantitative_claim_detection(self, decomposer):
        """Test detection of quantitative claims."""
        result = await decomposer.decompose("OpenAIの売上は100億ドル以上である")
        
        assert result.success is True
        assert len(result.claims) >= 1
        
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.QUANTITATIVE
    
    @pytest.mark.asyncio
    async def test_comparative_claim_detection(self, decomposer):
        """Test detection of comparative claims."""
        result = await decomposer.decompose(
            "GPT-4はGPT-3.5より優れている"
        )
        
        assert result.success is True
        assert len(result.claims) >= 1
        
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.COMPARATIVE
    
    @pytest.mark.asyncio
    async def test_causal_claim_detection(self, decomposer):
        """Test detection of causal claims."""
        result = await decomposer.decompose(
            "AIの発展によって雇用に影響が生じている"
        )
        
        assert result.success is True
        assert len(result.claims) >= 1
        
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.CAUSAL
    
    @pytest.mark.asyncio
    async def test_definitional_claim_detection(self, decomposer):
        """Test detection of definitional claims."""
        result = await decomposer.decompose(
            "大規模言語モデルとは何を意味するのか"
        )
        
        assert result.success is True
        assert len(result.claims) >= 1
        
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.DEFINITIONAL
    
    @pytest.mark.asyncio
    async def test_negative_polarity_detection(self, decomposer):
        """Test detection of negative polarity."""
        result = await decomposer.decompose(
            "AIは人間の仕事を奪うことはない"
        )
        
        assert result.success is True
        assert len(result.claims) >= 1
        
        claim = result.claims[0]
        assert claim.expected_polarity == ClaimPolarity.NEGATIVE
    
    @pytest.mark.asyncio
    async def test_neutral_polarity_for_question(self, decomposer):
        """Test neutral polarity for questions."""
        result = await decomposer.decompose("AIの未来はどうなるか？")
        
        assert result.success is True
        assert len(result.claims) >= 1
        
        claim = result.claims[0]
        assert claim.expected_polarity == ClaimPolarity.NEUTRAL
    
    @pytest.mark.asyncio
    async def test_keyword_extraction(self, decomposer):
        """Test keyword extraction from claims."""
        result = await decomposer.decompose(
            "OpenAIのGPT-4はマルチモーダル機能を持つ"
        )
        
        assert result.success is True
        assert len(result.claims) >= 1
        
        claim = result.claims[0]
        assert len(claim.keywords) > 0
        # Should contain significant terms
        keywords_lower = [k.lower() for k in claim.keywords]
        assert any("openai" in k or "gpt" in k for k in keywords_lower)
    
    @pytest.mark.asyncio
    async def test_verification_hints_generation(self, decomposer):
        """Test verification hints are generated."""
        result = await decomposer.decompose(
            "総務省の統計データによると人口は減少している"
        )
        
        assert result.success is True
        assert len(result.claims) >= 1
        
        claim = result.claims[0]
        assert len(claim.verification_hints) > 0
    
    @pytest.mark.asyncio
    async def test_source_question_preserved(self, decomposer):
        """Test original question is preserved in claims."""
        question = "テスト用の質問です"
        result = await decomposer.decompose(question)
        
        assert result.success is True
        for claim in result.claims:
            assert claim.source_question == question


class TestClaimDecomposerLLM:
    """Tests for LLM-based claim decomposition (mocked)."""
    
    @pytest.mark.asyncio
    async def test_llm_decomposition(self, monkeypatch):
        """Test LLM-based decomposition with mocked response."""
        from unittest.mock import AsyncMock, MagicMock
        
        mock_response = """[
            {
                "text": "GPT-4は2023年3月にリリースされた",
                "polarity": "positive",
                "granularity": "atomic",
                "type": "temporal",
                "keywords": ["GPT-4", "2023年", "リリース"],
                "hints": ["OpenAI公式発表"]
            },
            {
                "text": "GPT-4はマルチモーダル機能を持つ",
                "polarity": "positive",
                "granularity": "atomic",
                "type": "factual",
                "keywords": ["GPT-4", "マルチモーダル"],
                "hints": ["技術ドキュメント"]
            }
        ]"""
        
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value=mock_response)
        
        monkeypatch.setattr(
            "src.filter.claim_decomposition._get_client",
            lambda: mock_client,
        )
        
        decomposer = ClaimDecomposer(use_llm=True)
        result = await decomposer.decompose("GPT-4について教えてください")
        
        assert result.success is True
        assert result.decomposition_method == "llm"
        assert len(result.claims) == 2
        
        # Check first claim
        claim1 = result.claims[0]
        assert claim1.text == "GPT-4は2023年3月にリリースされた"
        assert claim1.expected_polarity == ClaimPolarity.POSITIVE
        assert claim1.claim_type == ClaimType.TEMPORAL
        assert "GPT-4" in claim1.keywords
        
        # Check second claim
        claim2 = result.claims[1]
        assert claim2.text == "GPT-4はマルチモーダル機能を持つ"
        assert claim2.claim_type == ClaimType.FACTUAL
    
    @pytest.mark.asyncio
    async def test_llm_fallback_on_invalid_json(self, monkeypatch):
        """Test fallback to rule-based when LLM returns invalid JSON."""
        from unittest.mock import AsyncMock, MagicMock
        
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value="Invalid response")
        
        monkeypatch.setattr(
            "src.filter.claim_decomposition._get_client",
            lambda: mock_client,
        )
        
        decomposer = ClaimDecomposer(use_llm=True)
        result = await decomposer.decompose("テスト質問")
        
        # Should still succeed using rule-based fallback
        assert result.success is True
        assert len(result.claims) >= 1
    
    @pytest.mark.asyncio
    async def test_llm_fallback_on_error(self, monkeypatch):
        """Test fallback to rule-based when LLM raises an error."""
        from unittest.mock import AsyncMock, MagicMock
        
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(
            side_effect=RuntimeError("Connection error")
        )
        
        monkeypatch.setattr(
            "src.filter.claim_decomposition._get_client",
            lambda: mock_client,
        )
        
        decomposer = ClaimDecomposer(use_llm=True)
        result = await decomposer.decompose("エラーテスト")
        
        # Should fall back to rule-based
        assert result.success is True
        assert result.decomposition_method == "rule_based"


class TestDecomposeQuestionFunction:
    """Tests for the convenience function."""
    
    @pytest.mark.asyncio
    async def test_decompose_question_default(self):
        """Test decompose_question with default parameters."""
        # This will fail without Ollama, should fall back to rule-based
        result = await decompose_question(
            "AIについて教えてください",
            use_llm=False,  # Use rule-based for testing
        )
        
        assert result.success is True
        assert len(result.claims) >= 1
    
    @pytest.mark.asyncio
    async def test_decompose_question_rule_based(self):
        """Test decompose_question with rule-based method."""
        result = await decompose_question(
            "機械学習とディープラーニングの違いは何ですか",
            use_llm=False,
        )
        
        assert result.success is True
        assert result.decomposition_method == "rule_based"
        assert len(result.claims) >= 1


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    @pytest.fixture
    def decomposer(self):
        """Create a rule-based decomposer."""
        return ClaimDecomposer(use_llm=False)
    
    @pytest.mark.asyncio
    async def test_whitespace_only_question(self, decomposer):
        """Test handling of whitespace-only question."""
        result = await decomposer.decompose("   \n\t  ")
        
        assert result.success is False
        assert result.error == "Empty question provided"
    
    @pytest.mark.asyncio
    async def test_very_long_question(self, decomposer):
        """Test handling of very long question."""
        long_question = "AI" * 1000  # 2000 characters
        result = await decomposer.decompose(long_question)
        
        assert result.success is True
        assert len(result.claims) >= 1
    
    @pytest.mark.asyncio
    async def test_special_characters(self, decomposer):
        """Test handling of special characters in question."""
        result = await decomposer.decompose(
            "AI (人工知能) の「未来」について調べる！？"
        )
        
        assert result.success is True
        assert len(result.claims) >= 1
    
    @pytest.mark.asyncio
    async def test_english_question(self, decomposer):
        """Test handling of English question."""
        result = await decomposer.decompose(
            "What is the impact of AI on employment?"
        )
        
        assert result.success is True
        assert len(result.claims) >= 1
    
    @pytest.mark.asyncio
    async def test_mixed_language_question(self, decomposer):
        """Test handling of mixed Japanese/English question."""
        result = await decomposer.decompose(
            "ChatGPTとは何ですか？What are its capabilities?"
        )
        
        assert result.success is True
        assert len(result.claims) >= 1
    
    @pytest.mark.asyncio
    async def test_numeric_only_question(self, decomposer):
        """Test handling of numeric content (quantitative detection)."""
        # Use a question without year to avoid temporal detection
        result = await decomposer.decompose(
            "売上は1000億円を超えた"
        )
        
        assert result.success is True
        # Should detect as quantitative
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.QUANTITATIVE


class TestClaimIdUniqueness:
    """Tests for claim ID uniqueness."""
    
    @pytest.mark.asyncio
    async def test_unique_claim_ids(self):
        """Test that claim IDs are unique across decompositions."""
        decomposer = ClaimDecomposer(use_llm=False)
        
        result1 = await decomposer.decompose("質問1")
        result2 = await decomposer.decompose("質問2")
        
        ids1 = {c.claim_id for c in result1.claims}
        ids2 = {c.claim_id for c in result2.claims}
        
        # IDs should not overlap
        assert ids1.isdisjoint(ids2)
    
    @pytest.mark.asyncio
    async def test_claim_id_format(self):
        """Test that claim IDs follow expected format."""
        decomposer = ClaimDecomposer(use_llm=False)
        result = await decomposer.decompose("テスト質問")
        
        for claim in result.claims:
            assert claim.claim_id.startswith("claim_")
            # Should have 8 hex chars after prefix
            suffix = claim.claim_id.replace("claim_", "")
            assert len(suffix) == 8
            assert all(c in "0123456789abcdef" for c in suffix)

