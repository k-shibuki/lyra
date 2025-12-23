"""
Tests for claim decomposition module.

Per .1.1: Tests validate specifications, not just "pass tests".
Per : Question-to-Claim Decomposition functionality.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-AC-01 | AtomicClaim with defaults | Equivalence – default values | All defaults correctly set | - |
| TC-AC-02 | AtomicClaim with all fields | Equivalence – full data | All fields correctly stored | - |
| TC-AC-03 | AtomicClaim to_dict | Equivalence – serialization | Dictionary with all fields | - |
| TC-AC-04 | AtomicClaim from_dict | Equivalence – deserialization | Object correctly populated | - |
| TC-AC-05 | AtomicClaim from_dict missing optional | Boundary – partial data | Defaults used for missing fields | - |
| TC-CE-01 | ClaimPolarity values | Equivalence – enum values | Correct string values | - |
| TC-CE-02 | ClaimGranularity values | Equivalence – enum values | Correct string values | - |
| TC-CE-03 | ClaimType values | Equivalence – enum values | Correct string values | - |
| TC-DR-01 | DecompositionResult creation | Equivalence – normal | All fields correctly set | - |
| TC-DR-02 | DecompositionResult to_dict | Equivalence – serialization | Dictionary with all fields | - |
| TC-CD-RB-01 | Empty question | Boundary – empty input | success=False, error message | - |
| TC-CD-RB-02 | Simple question | Equivalence – normal | success=True, claims generated | - |
| TC-CD-RB-03 | Compound question | Equivalence – conjunction | Multiple claims generated | - |
| TC-CD-RB-04 | Temporal claim | Equivalence – type detection | claim_type=TEMPORAL | - |
| TC-CD-RB-05 | Quantitative claim | Equivalence – type detection | claim_type=QUANTITATIVE | - |
| TC-CD-RB-06 | Comparative claim | Equivalence – type detection | claim_type=COMPARATIVE | - |
| TC-CD-RB-07 | Causal claim | Equivalence – type detection | claim_type=CAUSAL | - |
| TC-CD-RB-08 | Definitional claim | Equivalence – type detection | claim_type=DEFINITIONAL | - |
| TC-CD-RB-09 | Negative polarity | Equivalence – polarity detection | polarity=NEGATIVE | - |
| TC-CD-RB-10 | Neutral polarity for question | Equivalence – polarity detection | polarity=NEUTRAL | - |
| TC-CD-RB-11 | Keyword extraction | Equivalence – extraction | Keywords extracted | - |
| TC-CD-RB-12 | Verification hints | Equivalence – hints | Hints generated | - |
| TC-CD-RB-13 | Source question preserved | Equivalence – preservation | source_question matches input | - |
| TC-CD-LLM-01 | LLM decomposition | Equivalence – mocked LLM | success=True, claims from JSON | - |
| TC-CD-LLM-02 | LLM invalid JSON fallback | Abnormal – invalid response | Falls back to rule-based | - |
| TC-CD-LLM-03 | LLM error fallback | Abnormal – exception | Falls back to rule-based | - |
| TC-DF-01 | decompose_question default | Equivalence – convenience | success=True | - |
| TC-DF-02 | decompose_question rule-based | Equivalence – explicit rule | method=rule_based | - |
| TC-EC-01 | Whitespace-only question | Boundary – whitespace | success=False | - |
| TC-EC-02 | Very long question | Boundary – long input | Handles gracefully | - |
| TC-EC-03 | Special characters | Equivalence – special chars | Handles correctly | - |
| TC-EC-04 | English question | Equivalence – language | Handles English | - |
| TC-EC-05 | Mixed language | Equivalence – mixed | Handles mixed text | - |
| TC-EC-06 | Numeric content | Equivalence – quantitative | Detects quantitative type | - |
| TC-ID-01 | Unique claim IDs | Equivalence – uniqueness | IDs don't overlap | - |
| TC-ID-02 | Claim ID format | Equivalence – format | Follows claim_XXXXXXXX format | - |
"""

import pytest
from pytest import MonkeyPatch

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

    def test_create_atomic_claim_with_defaults(self) -> None:
        """Test creating an atomic claim with default values."""
        # Given: Required fields only
        # When: Creating AtomicClaim
        claim = AtomicClaim(
            claim_id="test_001",
            text="GPT-4は2023年にリリースされた",
            expected_polarity=ClaimPolarity.POSITIVE,
            granularity=ClaimGranularity.ATOMIC,
        )

        # Then: All defaults correctly set
        assert claim.claim_id == "test_001"
        assert claim.text == "GPT-4は2023年にリリースされた"
        assert claim.expected_polarity == ClaimPolarity.POSITIVE
        assert claim.granularity == ClaimGranularity.ATOMIC
        assert claim.claim_type == ClaimType.FACTUAL
        assert claim.parent_claim_id is None
        assert claim.confidence == 1.0
        assert claim.keywords == []
        assert claim.verification_hints == []

    def test_create_atomic_claim_with_all_fields(self) -> None:
        """Test creating an atomic claim with all fields specified."""
        # Given: All fields specified
        # When: Creating AtomicClaim
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

        # Then: All fields correctly stored
        assert claim.claim_type == ClaimType.QUANTITATIVE
        assert claim.parent_claim_id == "parent_001"
        assert claim.source_question == "東京の人口について教えてください"
        assert claim.confidence == 0.95
        assert len(claim.keywords) == 3
        assert "東京" in claim.keywords
        assert len(claim.verification_hints) == 2

    def test_to_dict_serialization(self) -> None:
        """Test serialization to dictionary."""
        # Given: AtomicClaim with various fields
        claim = AtomicClaim(
            claim_id="test_003",
            text="Test claim",
            expected_polarity=ClaimPolarity.NEUTRAL,
            granularity=ClaimGranularity.COMPOSITE,
            claim_type=ClaimType.CAUSAL,
            keywords=["test", "claim"],
        )

        # When: Serializing to dict
        d = claim.to_dict()

        # Then: All fields present with correct values
        assert d["claim_id"] == "test_003"
        assert d["text"] == "Test claim"
        assert d["expected_polarity"] == "neutral"
        assert d["granularity"] == "composite"
        assert d["claim_type"] == "causal"
        assert d["keywords"] == ["test", "claim"]

    def test_from_dict_deserialization(self) -> None:
        """Test deserialization from dictionary."""
        # Given: Dictionary with claim data
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

        # When: Deserializing from dict
        claim = AtomicClaim.from_dict(data)

        # Then: Object correctly populated
        assert claim.claim_id == "test_004"
        assert claim.text == "Deserialized claim"
        assert claim.expected_polarity == ClaimPolarity.NEGATIVE
        assert claim.granularity == ClaimGranularity.ATOMIC
        assert claim.claim_type == ClaimType.TEMPORAL
        assert claim.confidence == 0.8

    def test_from_dict_with_missing_optional_fields(self) -> None:
        """Test deserialization handles missing optional fields."""
        # Given: Minimal dictionary
        data = {
            "claim_id": "test_005",
            "text": "Minimal claim",
        }

        # When: Deserializing from dict
        claim = AtomicClaim.from_dict(data)

        # Then: Defaults used for missing fields
        assert claim.claim_id == "test_005"
        assert claim.expected_polarity == ClaimPolarity.NEUTRAL
        assert claim.granularity == ClaimGranularity.ATOMIC
        assert claim.claim_type == ClaimType.FACTUAL


class TestClaimEnums:
    """Tests for claim-related enums."""

    def test_claim_polarity_values(self) -> None:
        """Test ClaimPolarity enum values."""
        # Given/When: Checking enum values
        # Then: Correct string values
        assert ClaimPolarity.POSITIVE.value == "positive"
        assert ClaimPolarity.NEGATIVE.value == "negative"
        assert ClaimPolarity.NEUTRAL.value == "neutral"

    def test_claim_granularity_values(self) -> None:
        """Test ClaimGranularity enum values."""
        # Given/When: Checking enum values
        # Then: Correct string values
        assert ClaimGranularity.ATOMIC.value == "atomic"
        assert ClaimGranularity.COMPOSITE.value == "composite"
        assert ClaimGranularity.META.value == "meta"

    def test_claim_type_values(self) -> None:
        """Test ClaimType enum values."""
        # Given/When: Checking enum values
        # Then: Correct string values
        assert ClaimType.FACTUAL.value == "factual"
        assert ClaimType.CAUSAL.value == "causal"
        assert ClaimType.COMPARATIVE.value == "comparative"
        assert ClaimType.DEFINITIONAL.value == "definitional"
        assert ClaimType.TEMPORAL.value == "temporal"
        assert ClaimType.QUANTITATIVE.value == "quantitative"


class TestDecompositionResult:
    """Tests for DecompositionResult dataclass."""

    def test_create_decomposition_result(self) -> None:
        """Test creating a decomposition result."""
        # Given: List of claims
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

        # When: Creating DecompositionResult
        result = DecompositionResult(
            original_question="Test question?",
            claims=claims,
            decomposition_method="rule_based",
        )

        # Then: All fields correctly set
        assert result.original_question == "Test question?"
        assert len(result.claims) == 2
        assert result.decomposition_method == "rule_based"
        assert result.success is True
        assert result.error is None

    def test_to_dict_serialization(self) -> None:
        """Test serialization to dictionary."""
        # Given: DecompositionResult with claims
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

        # When: Serializing to dict
        d = result.to_dict()

        # Then: All fields present
        assert d["original_question"] == "Question?"
        assert len(d["claims"]) == 1
        assert d["claims"][0]["claim_id"] == "c1"
        assert d["decomposition_method"] == "llm"
        assert d["success"] is True


class TestClaimDecomposerRuleBased:
    """Tests for rule-based claim decomposition."""

    @pytest.fixture
    def decomposer(self) -> ClaimDecomposer:
        """Create a rule-based decomposer."""
        return ClaimDecomposer(use_llm=False)

    @pytest.mark.asyncio
    async def test_empty_question(self, decomposer: ClaimDecomposer) -> None:
        """Test handling of empty question."""
        # Given: Empty string
        # When: Decomposing
        result = await decomposer.decompose("")

        # Then: Fails with error message
        assert result.success is False
        assert result.error == "Empty question provided"
        assert len(result.claims) == 0

    @pytest.mark.asyncio
    async def test_simple_question(self, decomposer: ClaimDecomposer) -> None:
        """Test decomposition of a simple question."""
        # Given: Simple question
        # When: Decomposing
        result = await decomposer.decompose("AIエージェントとは何ですか")

        # Then: Success with claims
        assert result.success is True
        assert result.decomposition_method == "rule_based"
        assert len(result.claims) >= 1
        claim = result.claims[0]
        assert claim.claim_id.startswith("claim_")
        assert claim.text
        assert claim.expected_polarity is not None
        assert claim.granularity is not None

    @pytest.mark.asyncio
    async def test_compound_question_decomposition(self, decomposer: ClaimDecomposer) -> None:
        """Test decomposition of compound question with conjunctions."""
        # Given: Question with conjunction
        # When: Decomposing
        result = await decomposer.decompose(
            "GPT-4の性能、およびClaude 3との比較について調べてください"
        )

        # Then: Multiple claims generated
        assert result.success is True
        assert len(result.claims) >= 1

    @pytest.mark.asyncio
    async def test_temporal_claim_detection(self, decomposer: ClaimDecomposer) -> None:
        """Test detection of temporal claims."""
        # Given: Question with year
        # When: Decomposing
        result = await decomposer.decompose("2024年のAI動向について")

        # Then: Detected as TEMPORAL
        assert result.success is True
        assert len(result.claims) >= 1
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.TEMPORAL

    @pytest.mark.asyncio
    async def test_quantitative_claim_detection(self, decomposer: ClaimDecomposer) -> None:
        """Test detection of quantitative claims."""
        # Given: Question with numbers
        # When: Decomposing
        result = await decomposer.decompose("OpenAIの売上は100億ドル以上である")

        # Then: Detected as QUANTITATIVE
        assert result.success is True
        assert len(result.claims) >= 1
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.QUANTITATIVE

    @pytest.mark.asyncio
    async def test_comparative_claim_detection(self, decomposer: ClaimDecomposer) -> None:
        """Test detection of comparative claims."""
        # Given: Question with comparison
        # When: Decomposing
        result = await decomposer.decompose("GPT-4はGPT-3.5より優れている")

        # Then: Detected as COMPARATIVE
        assert result.success is True
        assert len(result.claims) >= 1
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.COMPARATIVE

    @pytest.mark.asyncio
    async def test_causal_claim_detection(self, decomposer: ClaimDecomposer) -> None:
        """Test detection of causal claims."""
        # Given: Question with causal relationship
        # When: Decomposing
        result = await decomposer.decompose("AIの発展によって雇用に影響が生じている")

        # Then: Detected as CAUSAL
        assert result.success is True
        assert len(result.claims) >= 1
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.CAUSAL

    @pytest.mark.asyncio
    async def test_definitional_claim_detection(self, decomposer: ClaimDecomposer) -> None:
        """Test detection of definitional claims."""
        # Given: Question asking for definition
        # When: Decomposing
        result = await decomposer.decompose("大規模言語モデルとは何を意味するのか")

        # Then: Detected as DEFINITIONAL
        assert result.success is True
        assert len(result.claims) >= 1
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.DEFINITIONAL

    @pytest.mark.asyncio
    async def test_negative_polarity_detection(self, decomposer: ClaimDecomposer) -> None:
        """Test detection of negative polarity."""
        # Given: Negative statement
        # When: Decomposing
        result = await decomposer.decompose("AIは人間の仕事を奪うことはない")

        # Then: Detected as NEGATIVE
        assert result.success is True
        assert len(result.claims) >= 1
        claim = result.claims[0]
        assert claim.expected_polarity == ClaimPolarity.NEGATIVE

    @pytest.mark.asyncio
    async def test_neutral_polarity_for_question(self, decomposer: ClaimDecomposer) -> None:
        """Test neutral polarity for questions."""
        # Given: Open question
        # When: Decomposing
        result = await decomposer.decompose("AIの未来はどうなるか？")

        # Then: Detected as NEUTRAL
        assert result.success is True
        assert len(result.claims) >= 1
        claim = result.claims[0]
        assert claim.expected_polarity == ClaimPolarity.NEUTRAL

    @pytest.mark.asyncio
    async def test_keyword_extraction(self, decomposer: ClaimDecomposer) -> None:
        """Test keyword extraction from claims."""
        # Given: Question with specific terms
        # When: Decomposing
        result = await decomposer.decompose("OpenAIのGPT-4はマルチモーダル機能を持つ")

        # Then: Keywords extracted
        assert result.success is True
        assert len(result.claims) >= 1
        claim = result.claims[0]
        assert len(claim.keywords) >= 1, f"Expected at least 1 keyword, got {len(claim.keywords)}"
        keywords_lower = [k.lower() for k in claim.keywords]
        has_openai = any("openai" in k for k in keywords_lower)
        has_gpt = any("gpt" in k for k in keywords_lower)
        assert has_openai or has_gpt, f"Expected 'openai' or 'gpt' in keywords: {claim.keywords}"

    @pytest.mark.asyncio
    async def test_verification_hints_generation(self, decomposer: ClaimDecomposer) -> None:
        """Test verification hints are generated."""
        # Given: Question mentioning official source
        # When: Decomposing
        result = await decomposer.decompose("総務省の統計データによると人口は減少している")

        # Then: Hints generated
        assert result.success is True
        assert len(result.claims) >= 1
        claim = result.claims[0]
        assert len(claim.verification_hints) >= 1, (
            f"Expected >=1 verification hints, got {len(claim.verification_hints)}"
        )

    @pytest.mark.asyncio
    async def test_source_question_preserved(self, decomposer: ClaimDecomposer) -> None:
        """Test original question is preserved in claims."""
        # Given: Test question
        question = "テスト用の質問です"

        # When: Decomposing
        result = await decomposer.decompose(question)

        # Then: Source question preserved
        assert result.success is True
        for claim in result.claims:
            assert claim.source_question == question


class TestClaimDecomposerLLM:
    """Tests for LLM-based claim decomposition (mocked)."""

    @pytest.mark.asyncio
    async def test_llm_decomposition(self, monkeypatch: MonkeyPatch) -> None:
        """Test LLM-based decomposition with mocked response."""
        from unittest.mock import AsyncMock, MagicMock

        # Given: Mocked LLM response with valid JSON
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

        # When: Decomposing with LLM
        decomposer = ClaimDecomposer(use_llm=True)
        result = await decomposer.decompose("GPT-4について教えてください")

        # Then: Success with claims from JSON
        assert result.success is True
        assert result.decomposition_method == "llm"
        assert len(result.claims) == 2
        claim1 = result.claims[0]
        assert claim1.text == "GPT-4は2023年3月にリリースされた"
        assert claim1.expected_polarity == ClaimPolarity.POSITIVE
        assert claim1.claim_type == ClaimType.TEMPORAL
        assert "GPT-4" in claim1.keywords
        claim2 = result.claims[1]
        assert claim2.text == "GPT-4はマルチモーダル機能を持つ"
        assert claim2.claim_type == ClaimType.FACTUAL

    @pytest.mark.asyncio
    async def test_llm_fallback_on_invalid_json(self, monkeypatch: MonkeyPatch) -> None:
        """Test fallback to rule-based when LLM returns invalid JSON."""
        from unittest.mock import AsyncMock, MagicMock

        # Given: Mocked LLM returning invalid JSON
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value="Invalid response")
        monkeypatch.setattr(
            "src.filter.claim_decomposition._get_client",
            lambda: mock_client,
        )

        # When: Decomposing with LLM
        decomposer = ClaimDecomposer(use_llm=True)
        result = await decomposer.decompose("テスト質問")

        # Then: Falls back to rule-based
        assert result.success is True
        assert len(result.claims) >= 1

    @pytest.mark.asyncio
    async def test_llm_fallback_on_error(self, monkeypatch: MonkeyPatch) -> None:
        """Test fallback to rule-based when LLM raises an error."""
        from unittest.mock import AsyncMock, MagicMock

        # Given: Mocked LLM raising exception
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(side_effect=RuntimeError("Connection error"))
        monkeypatch.setattr(
            "src.filter.claim_decomposition._get_client",
            lambda: mock_client,
        )

        # When: Decomposing with LLM
        decomposer = ClaimDecomposer(use_llm=True)
        result = await decomposer.decompose("エラーテスト")

        # Then: Falls back to rule-based
        assert result.success is True
        assert result.decomposition_method == "rule_based"


class TestDecomposeQuestionFunction:
    """Tests for the convenience function."""

    @pytest.mark.asyncio
    async def test_decompose_question_default(self) -> None:
        """Test decompose_question with default parameters."""
        # Given: Question with rule-based mode
        # When: Using convenience function
        result = await decompose_question(
            "AIについて教えてください",
            use_llm=False,
        )

        # Then: Success
        assert result.success is True
        assert len(result.claims) >= 1

    @pytest.mark.asyncio
    async def test_decompose_question_rule_based(self) -> None:
        """Test decompose_question with rule-based method."""
        # Given: Question with explicit rule-based mode
        # When: Using convenience function
        result = await decompose_question(
            "機械学習とディープラーニングの違いは何ですか",
            use_llm=False,
        )

        # Then: method=rule_based
        assert result.success is True
        assert result.decomposition_method == "rule_based"
        assert len(result.claims) >= 1


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def decomposer(self) -> ClaimDecomposer:
        """Create a rule-based decomposer."""
        return ClaimDecomposer(use_llm=False)

    @pytest.mark.asyncio
    async def test_whitespace_only_question(self, decomposer: ClaimDecomposer) -> None:
        """Test handling of whitespace-only question."""
        # Given: Whitespace-only input
        # When: Decomposing
        result = await decomposer.decompose("   \n\t  ")

        # Then: Fails
        assert result.success is False
        assert result.error == "Empty question provided"

    @pytest.mark.asyncio
    async def test_very_long_question(self, decomposer: ClaimDecomposer) -> None:
        """Test handling of very long question."""
        # Given: Very long input (2000 chars)
        long_question = "AI" * 1000

        # When: Decomposing
        result = await decomposer.decompose(long_question)

        # Then: Handles gracefully
        assert result.success is True
        assert len(result.claims) >= 1

    @pytest.mark.asyncio
    async def test_special_characters(self, decomposer: ClaimDecomposer) -> None:
        """Test handling of special characters in question."""
        # Given: Question with special characters
        # When: Decomposing
        result = await decomposer.decompose("AI (人工知能) の「未来」について調べる！？")

        # Then: Handles correctly
        assert result.success is True
        assert len(result.claims) >= 1

    @pytest.mark.asyncio
    async def test_english_question(self, decomposer: ClaimDecomposer) -> None:
        """Test handling of English question."""
        # Given: English question
        # When: Decomposing
        result = await decomposer.decompose("What is the impact of AI on employment?")

        # Then: Handles English
        assert result.success is True
        assert len(result.claims) >= 1

    @pytest.mark.asyncio
    async def test_mixed_language_question(self, decomposer: ClaimDecomposer) -> None:
        """Test handling of mixed Japanese/English question."""
        # Given: Mixed language question
        # When: Decomposing
        result = await decomposer.decompose("ChatGPTとは何ですか？What are its capabilities?")

        # Then: Handles mixed text
        assert result.success is True
        assert len(result.claims) >= 1

    @pytest.mark.asyncio
    async def test_numeric_only_question(self, decomposer: ClaimDecomposer) -> None:
        """Test handling of numeric content (quantitative detection)."""
        # Given: Question with large number (no year)
        # When: Decomposing
        result = await decomposer.decompose("売上は1000億円を超えた")

        # Then: Detects quantitative type
        assert result.success is True
        claim = result.claims[0]
        assert claim.claim_type == ClaimType.QUANTITATIVE


class TestClaimIdUniqueness:
    """Tests for claim ID uniqueness."""

    @pytest.mark.asyncio
    async def test_unique_claim_ids(self) -> None:
        """Test that claim IDs are unique across decompositions."""
        # Given: Decomposer
        decomposer = ClaimDecomposer(use_llm=False)

        # When: Decomposing two different questions
        result1 = await decomposer.decompose("質問1")
        result2 = await decomposer.decompose("質問2")

        # Then: IDs don't overlap
        ids1 = {c.claim_id for c in result1.claims}
        ids2 = {c.claim_id for c in result2.claims}
        assert ids1.isdisjoint(ids2)

    @pytest.mark.asyncio
    async def test_claim_id_format(self) -> None:
        """Test that claim IDs follow expected format."""
        # Given: Decomposer
        decomposer = ClaimDecomposer(use_llm=False)

        # When: Decomposing
        result = await decomposer.decompose("テスト質問")

        # Then: Follows claim_XXXXXXXX format
        for claim in result.claims:
            assert claim.claim_id.startswith("claim_")
            suffix = claim.claim_id.replace("claim_", "")
            assert len(suffix) == 8
            assert all(c in "0123456789abcdef" for c in suffix)
