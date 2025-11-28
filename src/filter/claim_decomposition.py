"""
Claim decomposition for Lancet.

Decomposes high-level research questions into atomic claims
for systematic verification.

Per §3.3.1: 問い→主張分解
- 上位の問いを原子主張へ分解
- スキーマ: claim_id, text, expected_polarity, granularity

Per §2.1.4: ローカルLLMの役割
- 断片からの事実/主張抽出は許可される用途
- サブクエリの設計・候補生成は禁止（Cursor AIの専権）
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.filter.llm import _get_client
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ClaimPolarity(str, Enum):
    """Expected polarity of a claim."""
    
    POSITIVE = "positive"  # Claim asserts something is true
    NEGATIVE = "negative"  # Claim asserts something is false
    NEUTRAL = "neutral"    # Claim is a question or neutral statement


class ClaimGranularity(str, Enum):
    """Granularity level of a claim."""
    
    ATOMIC = "atomic"      # Cannot be further decomposed
    COMPOSITE = "composite"  # Can be decomposed into sub-claims
    META = "meta"          # Meta-level claim about the research itself


class ClaimType(str, Enum):
    """Type of claim based on content."""
    
    FACTUAL = "factual"        # Verifiable fact
    CAUSAL = "causal"          # Cause-effect relationship
    COMPARATIVE = "comparative"  # Comparison between entities
    DEFINITIONAL = "definitional"  # Definition or classification
    TEMPORAL = "temporal"      # Time-related claim
    QUANTITATIVE = "quantitative"  # Numerical/statistical claim


@dataclass
class AtomicClaim:
    """
    An atomic claim extracted from a research question.
    
    Per §3.3.1: スキーマ: claim_id, text, expected_polarity, granularity
    """
    
    claim_id: str
    text: str
    expected_polarity: ClaimPolarity
    granularity: ClaimGranularity
    claim_type: ClaimType = ClaimType.FACTUAL
    parent_claim_id: str | None = None
    source_question: str = ""
    confidence: float = 1.0
    keywords: list[str] = field(default_factory=list)
    verification_hints: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "expected_polarity": self.expected_polarity.value,
            "granularity": self.granularity.value,
            "claim_type": self.claim_type.value,
            "parent_claim_id": self.parent_claim_id,
            "source_question": self.source_question,
            "confidence": self.confidence,
            "keywords": self.keywords,
            "verification_hints": self.verification_hints,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AtomicClaim":
        """Create from dictionary."""
        return cls(
            claim_id=data["claim_id"],
            text=data["text"],
            expected_polarity=ClaimPolarity(data.get("expected_polarity", "neutral")),
            granularity=ClaimGranularity(data.get("granularity", "atomic")),
            claim_type=ClaimType(data.get("claim_type", "factual")),
            parent_claim_id=data.get("parent_claim_id"),
            source_question=data.get("source_question", ""),
            confidence=data.get("confidence", 1.0),
            keywords=data.get("keywords", []),
            verification_hints=data.get("verification_hints", []),
        )


@dataclass
class DecompositionResult:
    """Result of claim decomposition."""
    
    original_question: str
    claims: list[AtomicClaim]
    decomposition_method: str  # "llm" or "rule_based"
    success: bool = True
    error: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "original_question": self.original_question,
            "claims": [c.to_dict() for c in self.claims],
            "decomposition_method": self.decomposition_method,
            "success": self.success,
            "error": self.error,
        }


# LLM prompt for claim decomposition
DECOMPOSE_PROMPT = """あなたは情報分析の専門家です。以下のリサーチクエスチョンを検証可能な原子主張（atomic claims）に分解してください。

リサーチクエスチョン:
{question}

各主張について以下の情報を含むJSON配列を出力してください：
- text: 主張の内容（検証可能な形式で記述）
- polarity: "positive"（真であることを主張）, "negative"（偽であることを主張）, "neutral"（中立的な問い）
- granularity: "atomic"（これ以上分解不可）, "composite"（さらに分解可能）
- type: "factual", "causal", "comparative", "definitional", "temporal", "quantitative"
- keywords: 検索に有用なキーワードのリスト
- hints: 検証のためのヒント（どこで情報を探すべきか）

出力例:
[
  {{
    "text": "GPT-4は2023年3月にリリースされた",
    "polarity": "positive",
    "granularity": "atomic",
    "type": "temporal",
    "keywords": ["GPT-4", "リリース", "2023年"],
    "hints": ["OpenAI公式発表", "テクノロジーニュース"]
  }}
]

注意:
- 各主張は独立して検証可能であること
- 曖昧な表現は避け、具体的に記述すること
- 複合的な問いは複数の原子主張に分解すること
- 日本語で出力すること

JSON配列のみを出力してください："""


class ClaimDecomposer:
    """
    Decomposes research questions into atomic claims.
    
    Per §3.3.1: 問い→主張分解
    - 上位の問いを原子主張へ分解
    - LLMまたはルールベースでの分解ロジック
    
    Per §2.1.4: ローカルLLMの許可される用途
    - 断片からの事実/主張抽出は許可
    """
    
    def __init__(self, use_llm: bool = True):
        """
        Initialize claim decomposer.
        
        Args:
            use_llm: Whether to use LLM for decomposition.
                     If False, uses rule-based decomposition.
        """
        self.use_llm = use_llm
        self._settings = get_settings()
    
    async def decompose(
        self,
        question: str,
        use_slow_model: bool = False,
    ) -> DecompositionResult:
        """
        Decompose a research question into atomic claims.
        
        Args:
            question: The research question to decompose.
            use_slow_model: Whether to use the slower, more capable model.
            
        Returns:
            DecompositionResult containing atomic claims.
        """
        if not question.strip():
            return DecompositionResult(
                original_question=question,
                claims=[],
                decomposition_method="none",
                success=False,
                error="Empty question provided",
            )
        
        try:
            if self.use_llm:
                return await self._decompose_with_llm(question, use_slow_model)
            else:
                return self._decompose_with_rules(question)
        except Exception as e:
            logger.error("Claim decomposition failed", error=str(e), question=question)
            # Fallback to rule-based if LLM fails
            if self.use_llm:
                logger.info("Falling back to rule-based decomposition")
                return self._decompose_with_rules(question)
            return DecompositionResult(
                original_question=question,
                claims=[],
                decomposition_method="failed",
                success=False,
                error=str(e),
            )
    
    async def _decompose_with_llm(
        self,
        question: str,
        use_slow_model: bool,
    ) -> DecompositionResult:
        """Decompose using LLM."""
        client = _get_client()
        model = (
            self._settings.llm.slow_model
            if use_slow_model
            else self._settings.llm.fast_model
        )
        
        prompt = DECOMPOSE_PROMPT.format(question=question)
        
        response = await client.generate(
            prompt=prompt,
            model=model,
            temperature=0.3,  # Lower temperature for more consistent output
            max_tokens=2000,
        )
        
        # Parse LLM response
        claims = self._parse_llm_response(response, question)
        
        return DecompositionResult(
            original_question=question,
            claims=claims,
            decomposition_method="llm",
            success=len(claims) > 0,
        )
    
    def _parse_llm_response(
        self,
        response: str,
        source_question: str,
    ) -> list[AtomicClaim]:
        """Parse LLM response into atomic claims."""
        claims = []
        
        # Try to extract JSON array from response
        try:
            # Find JSON array in response
            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if not json_match:
                logger.warning("No JSON array found in LLM response")
                return self._decompose_with_rules(source_question).claims
            
            parsed = json.loads(json_match.group())
            
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                
                text = item.get("text", "").strip()
                if not text:
                    continue
                
                # Map polarity
                polarity_str = item.get("polarity", "neutral").lower()
                try:
                    polarity = ClaimPolarity(polarity_str)
                except ValueError:
                    polarity = ClaimPolarity.NEUTRAL
                
                # Map granularity
                granularity_str = item.get("granularity", "atomic").lower()
                try:
                    granularity = ClaimGranularity(granularity_str)
                except ValueError:
                    granularity = ClaimGranularity.ATOMIC
                
                # Map type
                type_str = item.get("type", "factual").lower()
                try:
                    claim_type = ClaimType(type_str)
                except ValueError:
                    claim_type = ClaimType.FACTUAL
                
                claim = AtomicClaim(
                    claim_id=f"claim_{uuid.uuid4().hex[:8]}",
                    text=text,
                    expected_polarity=polarity,
                    granularity=granularity,
                    claim_type=claim_type,
                    source_question=source_question,
                    confidence=item.get("confidence", 0.9),
                    keywords=item.get("keywords", []),
                    verification_hints=item.get("hints", []),
                )
                claims.append(claim)
                
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse LLM response as JSON", error=str(e))
            return self._decompose_with_rules(source_question).claims
        
        return claims
    
    def _decompose_with_rules(self, question: str) -> DecompositionResult:
        """
        Decompose using rule-based approach.
        
        This is a fallback when LLM is not available or fails.
        Uses pattern matching and linguistic heuristics.
        """
        claims = []
        
        # Normalize question
        question = question.strip()
        
        # Split by common conjunctions and delimiters
        segments = self._split_by_conjunctions(question)
        
        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue
            
            # Analyze segment
            polarity = self._infer_polarity(segment)
            claim_type = self._infer_claim_type(segment)
            keywords = self._extract_keywords(segment)
            
            claim = AtomicClaim(
                claim_id=f"claim_{uuid.uuid4().hex[:8]}",
                text=segment,
                expected_polarity=polarity,
                granularity=ClaimGranularity.ATOMIC,
                claim_type=claim_type,
                source_question=question,
                confidence=0.7,  # Lower confidence for rule-based
                keywords=keywords,
                verification_hints=self._generate_hints(claim_type, keywords),
            )
            claims.append(claim)
        
        # If no claims were generated, create a single claim from the question
        if not claims:
            claims.append(AtomicClaim(
                claim_id=f"claim_{uuid.uuid4().hex[:8]}",
                text=question,
                expected_polarity=ClaimPolarity.NEUTRAL,
                granularity=ClaimGranularity.COMPOSITE,
                claim_type=ClaimType.FACTUAL,
                source_question=question,
                confidence=0.5,
                keywords=self._extract_keywords(question),
                verification_hints=["一般的な検索で調査"],
            ))
        
        return DecompositionResult(
            original_question=question,
            claims=claims,
            decomposition_method="rule_based",
            success=True,
        )
    
    def _split_by_conjunctions(self, text: str) -> list[str]:
        """Split text by conjunctions and delimiters."""
        # Japanese and English conjunctions
        patterns = [
            r"[、。]",           # Japanese punctuation
            r"(?:および|かつ|また|そして|さらに)",  # Japanese conjunctions
            r"(?:and|or|but|also|moreover)",  # English conjunctions
            r"[,;]",            # English punctuation
        ]
        
        result = [text]
        for pattern in patterns:
            new_result = []
            for segment in result:
                parts = re.split(pattern, segment)
                new_result.extend(parts)
            result = new_result
        
        # Filter short segments
        return [s.strip() for s in result if len(s.strip()) > 5]
    
    def _infer_polarity(self, text: str) -> ClaimPolarity:
        """Infer the polarity of a claim from its text."""
        text_lower = text.lower()
        
        # Negative indicators
        negative_patterns = [
            r"ない", r"しない", r"できない", r"不可能",
            r"否定", r"反対", r"誤り", r"間違い",
            r"not", r"never", r"cannot", r"impossible",
            r"false", r"incorrect", r"wrong",
        ]
        
        for pattern in negative_patterns:
            if re.search(pattern, text_lower):
                return ClaimPolarity.NEGATIVE
        
        # Question indicators
        question_patterns = [
            r"\?$", r"？$",
            r"^(what|who|when|where|why|how|which)",
            r"^(何|誰|いつ|どこ|なぜ|どう|どの)",
            r"(か|のか|でしょうか)$",
        ]
        
        for pattern in question_patterns:
            if re.search(pattern, text_lower):
                return ClaimPolarity.NEUTRAL
        
        return ClaimPolarity.POSITIVE
    
    def _infer_claim_type(self, text: str) -> ClaimType:
        """Infer the type of claim from its text."""
        text_lower = text.lower()
        
        # Temporal patterns
        temporal_patterns = [
            r"\d{4}年", r"\d{4}/\d{1,2}",
            r"(いつ|when|年|月|日|時)",
            r"(以前|以後|before|after|during)",
        ]
        for pattern in temporal_patterns:
            if re.search(pattern, text_lower):
                return ClaimType.TEMPORAL
        
        # Quantitative patterns
        quant_patterns = [
            r"\d+%", r"\d+億", r"\d+万",
            r"(数|量|率|比率|割合)",
            r"(how many|how much|percentage|ratio)",
        ]
        for pattern in quant_patterns:
            if re.search(pattern, text_lower):
                return ClaimType.QUANTITATIVE
        
        # Comparative patterns
        comp_patterns = [
            r"(より|compared to|than|versus|vs)",
            r"(比較|違い|difference|similar|different)",
        ]
        for pattern in comp_patterns:
            if re.search(pattern, text_lower):
                return ClaimType.COMPARATIVE
        
        # Causal patterns
        causal_patterns = [
            r"(なぜ|原因|理由|結果|影響)",
            r"(because|cause|effect|result|impact|why)",
            r"(によって|ため|から)",
        ]
        for pattern in causal_patterns:
            if re.search(pattern, text_lower):
                return ClaimType.CAUSAL
        
        # Definitional patterns
        def_patterns = [
            r"(とは|定義|意味|what is|define|definition)",
        ]
        for pattern in def_patterns:
            if re.search(pattern, text_lower):
                return ClaimType.DEFINITIONAL
        
        return ClaimType.FACTUAL
    
    def _extract_keywords(self, text: str) -> list[str]:
        """Extract keywords from text."""
        # Remove common stopwords and extract significant terms
        stopwords = {
            # Japanese
            "の", "は", "が", "を", "に", "で", "と", "も", "や", "か",
            "です", "ます", "した", "する", "される", "ている", "いる",
            "こと", "もの", "ため", "よう", "など", "これ", "それ",
            # English
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "may", "might", "can", "this", "that",
            "these", "those", "what", "which", "who", "whom", "whose",
            "where", "when", "why", "how", "and", "or", "but", "if",
            "then", "else", "for", "of", "to", "from", "by", "with",
        }
        
        # Split by whitespace and common delimiters
        words = re.split(r"[\s、。,.\-:;()（）「」『』]+", text)
        
        # Filter stopwords and short words
        keywords = []
        for word in words:
            word = word.strip()
            if word and len(word) > 1 and word.lower() not in stopwords:
                keywords.append(word)
        
        # Return unique keywords (preserve order)
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)
        
        return unique_keywords[:10]  # Limit to 10 keywords
    
    def _generate_hints(
        self,
        claim_type: ClaimType,
        keywords: list[str],
    ) -> list[str]:
        """Generate verification hints based on claim type."""
        hints = []
        
        type_hints = {
            ClaimType.FACTUAL: ["公式発表・プレスリリース", "信頼できるニュースソース"],
            ClaimType.TEMPORAL: ["タイムラインや年表", "アーカイブ・履歴資料"],
            ClaimType.QUANTITATIVE: ["統計データ・公式レポート", "学術論文・調査報告"],
            ClaimType.COMPARATIVE: ["比較分析レポート", "レビュー・評価記事"],
            ClaimType.CAUSAL: ["研究論文・分析", "専門家の解説"],
            ClaimType.DEFINITIONAL: ["辞書・用語集", "公式ドキュメント"],
        }
        
        hints.extend(type_hints.get(claim_type, ["一般的な検索"]))
        
        # Add keyword-based hints
        for kw in keywords[:3]:
            if any(c in kw for c in ["株式会社", "会社", "Inc", "Corp", "Ltd"]):
                hints.append(f"{kw}の公式サイト・IR情報")
            elif any(c in kw for c in ["省", "庁", "局"]):
                hints.append(f"{kw}の公式サイト")
        
        return hints[:5]  # Limit to 5 hints


async def decompose_question(
    question: str,
    use_llm: bool = True,
    use_slow_model: bool = False,
) -> DecompositionResult:
    """
    Convenience function to decompose a research question.
    
    Args:
        question: The research question to decompose.
        use_llm: Whether to use LLM (True) or rule-based (False).
        use_slow_model: Whether to use the slower, more capable LLM model.
        
    Returns:
        DecompositionResult containing atomic claims.
    """
    decomposer = ClaimDecomposer(use_llm=use_llm)
    return await decomposer.decompose(question, use_slow_model=use_slow_model)




