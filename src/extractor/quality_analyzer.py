"""
Content Quality Analyzer for Lyra.

Detects low-quality and AI-generated content based on structural and textual features.

Features analyzed (ADR-0010):
- Template/boilerplate density
- Advertisement density
- Text structure anomalies
- Expression repetition (AI-generated content indicator)
- SEO spam patterns
- Aggregator/curation site patterns
- LLM-based quality assessment (optional, for difficult cases)

Quality scores are used to deprioritize low-quality sources in the ranking pipeline.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.filter.llm_output import parse_and_validate
from src.filter.llm_schemas import QualityAssessmentOutput
from src.utils.logging import get_logger
from src.utils.prompt_manager import render_prompt

if TYPE_CHECKING:
    from src.filter.llm import OllamaClient

logger = get_logger(__name__)


class QualityIssue(Enum):
    """Types of quality issues detected."""

    AGGREGATOR = "aggregator"  # Content aggregator/curation site
    AI_GENERATED = "ai_generated"  # AI-generated content suspected
    SEO_SPAM = "seo_spam"  # SEO spam patterns
    THIN_CONTENT = "thin_content"  # Very little actual content
    AD_HEAVY = "ad_heavy"  # High advertisement density
    TEMPLATE_HEAVY = "template_heavy"  # High boilerplate/template ratio
    REPETITIVE = "repetitive"  # Repetitive text patterns
    KEYWORD_STUFFING = "keyword_stuffing"  # Excessive keyword repetition
    CLICKBAIT = "clickbait"  # Clickbait patterns
    SCRAPER = "scraper"  # Content scraper/copy site


@dataclass
class QualityFeatures:
    """Extracted features for quality analysis."""

    # Text statistics
    total_text_length: int = 0
    word_count: int = 0
    sentence_count: int = 0
    paragraph_count: int = 0
    avg_sentence_length: float = 0.0
    avg_paragraph_length: float = 0.0

    # Structural features
    html_length: int = 0
    text_to_html_ratio: float = 0.0
    heading_count: int = 0
    link_count: int = 0
    link_density: float = 0.0
    image_count: int = 0
    script_count: int = 0
    ad_element_count: int = 0

    # Content patterns
    unique_word_ratio: float = 0.0
    stopword_ratio: float = 0.0
    capitalization_ratio: float = 0.0
    punctuation_density: float = 0.0

    # Repetition metrics
    ngram_repetition_score: float = 0.0
    phrase_repetition_count: int = 0
    sentence_similarity_score: float = 0.0

    # AI-generated indicators
    perplexity_proxy: float = 0.0  # Proxy for perplexity based on n-gram patterns
    burstiness_score: float = 0.0  # Variation in sentence length
    uniformity_score: float = 0.0  # How uniform the text structure is

    # SEO/Spam indicators
    keyword_density: float = 0.0
    external_link_ratio: float = 0.0
    affiliate_link_count: int = 0
    call_to_action_count: int = 0

    # Template/Boilerplate
    boilerplate_ratio: float = 0.0
    navigation_ratio: float = 0.0
    footer_ratio: float = 0.0

    # Aggregator indicators
    has_multiple_sources: bool = False
    has_attribution_pattern: bool = False
    has_curated_list_pattern: bool = False
    source_mention_count: int = 0

    # LLM-based assessment (optional)
    llm_quality_score: float | None = None
    llm_is_ai_generated: bool | None = None
    llm_is_spam: bool | None = None
    llm_assessment_reason: str | None = None


@dataclass
class QualityResult:
    """Result of content quality analysis."""

    quality_score: float  # 0.0 (worst) to 1.0 (best)
    issues: list[QualityIssue] = field(default_factory=list)
    issue_details: dict[str, Any] = field(default_factory=dict)
    features: QualityFeatures = field(default_factory=QualityFeatures)
    penalty: float = 0.0  # Penalty to apply to ranking score
    reason: str = ""
    llm_assessed: bool = False  # Whether LLM was used for assessment

    @property
    def is_low_quality(self) -> bool:
        """Check if content is considered low quality."""
        return self.quality_score < 0.5 or len(self.issues) >= 2


class ContentQualityAnalyzer:
    """Analyzer for detecting low-quality and AI-generated content.

    Supports two modes:
    1. Rule-based analysis (fast, no external dependencies)
    2. LLM-assisted analysis (more accurate for difficult cases)

    LLM analysis is optional and triggered when:
    - Explicitly requested via use_llm=True
    - Rule-based analysis is ambiguous (score between 0.4 and 0.6)
    """

    # Common stopwords (English + Japanese)
    STOPWORDS_EN = frozenset(
        [
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "as",
            "is",
            "was",
            "are",
            "were",
            "been",
            "be",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "need",
            "this",
            "that",
            "these",
            "those",
            "it",
            "its",
            "they",
            "them",
            "their",
            "we",
            "us",
            "our",
            "you",
            "your",
            "he",
            "she",
            "him",
            "her",
            "his",
            "i",
            "me",
            "my",
            "not",
            "no",
            "yes",
            "so",
            "if",
            "then",
            "than",
            "when",
            "where",
            "what",
            "which",
            "who",
            "whom",
            "how",
            "why",
            "all",
            "each",
            "every",
            "both",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "only",
            "own",
            "same",
            "just",
            "also",
            "very",
        ]
    )

    STOPWORDS_JA = frozenset(
        [
            "の",
            "に",
            "は",
            "を",
            "た",
            "が",
            "で",
            "て",
            "と",
            "し",
            "れ",
            "さ",
            "ある",
            "いる",
            "も",
            "する",
            "から",
            "な",
            "こと",
            "として",
            "い",
            "や",
            "れる",
            "など",
            "なっ",
            "ない",
            "この",
            "ため",
            "その",
            "あっ",
            "よう",
            "また",
            "もの",
            "という",
            "あり",
            "まで",
            "られ",
            "なる",
            "へ",
            "か",
            "だ",
            "これ",
            "によって",
            "により",
            "おり",
            "より",
            "による",
            "ず",
            "なり",
            "られる",
            "において",
            "ば",
            "なかっ",
            "なく",
            "しかし",
            "について",
            "せ",
            "だっ",
            "その後",
            "できる",
            "それ",
            "う",
            "ので",
            "なお",
            "のみ",
            "でき",
            "き",
            "つ",
            "における",
            "および",
            "いう",
            "さらに",
            "でも",
        ]
    )

    # Ad-related patterns
    AD_PATTERNS = [
        r'class=["\'][^"\']*\b(ad|ads|advert|advertisement|banner|sponsor)\b',
        r'id=["\'][^"\']*\b(ad|ads|advert|advertisement|banner|sponsor)\b',
        r"data-ad-",
        r"googlesyndication",
        r"doubleclick",
        r"adsense",
        r"adsbygoogle",
        r'class=["\'][^"\']*\b(pr|sponsored|promotion)\b',
    ]

    # Affiliate link patterns
    AFFILIATE_PATTERNS = [
        r"amazon\.[^/]+/.*[?&]tag=",
        r"amzn\.to/",
        r"a]\.co/",
        r"linksynergy\.com",
        r"shareasale\.com",
        r"awin1\.com",
        r"commission-junction",
        r"clickbank\.net",
        r"rakuten\.co\.jp/.*\?scid=",
        r"valuecommerce\.com",
        r"accesstrade\.net",
        r"a8\.net",
    ]

    # Call-to-action patterns
    CTA_PATTERNS = [
        r"click\s+here",
        r"buy\s+now",
        r"sign\s+up",
        r"subscribe\s+now",
        r"get\s+started",
        r"learn\s+more",
        r"try\s+free",
        r"download\s+now",
        r"今すぐ",
        r"申し込む",
        r"購入する",
        r"登録する",
        r"無料で",
        r"詳しくはこちら",
    ]

    # Aggregator/curation patterns
    AGGREGATOR_PATTERNS = [
        r"(source|出典|引用元|via|from)\s*[:：]\s*",
        r"(according\s+to|によると|によれば)",
        r"(originally\s+published|元記事)",
        r"(top\s+\d+|best\s+\d+|まとめ|\d+選)",
        r"(roundup|curated|collection|compilation)",
        r"(この記事は.*から|from\s+.*\s+article)",
    ]

    # Clickbait patterns
    CLICKBAIT_PATTERNS = [
        r"you\s+won\'?t\s+believe",
        r"shocking",
        r"amazing",
        r"incredible",
        r"unbelievable",
        r"mind-?blowing",
        r"jaw-?dropping",
        r"this\s+one\s+trick",
        r"doctors\s+hate",
        r"what\s+happened\s+next",
        r"number\s+\d+\s+will\s+shock",
        r"驚きの",
        r"衝撃の",
        r"まさかの",
        r"ヤバい",
        r"信じられない",
    ]

    # SEO spam patterns
    SEO_SPAM_PATTERNS = [
        r"<h\d[^>]*>.*keyword.*</h\d>",  # Keywords in headings
        r"(best|top|cheap|free|buy)\s+([\w\s]+\s+){0,3}(online|near\s+me|2024|2025)",
        r"(\w+\s+){0,2}(review|reviews|guide|tips|tricks)\s+2024",
        r"<a[^>]*>\s*click\s+here\s*</a>",  # Generic anchor text
    ]

    # AI-generated content patterns
    AI_PATTERNS = [
        # Common AI phrases (use non-capturing groups to ensure findall returns full matches)
        r"as\s+an\s+ai",
        r"i\s+cannot\s+provide",
        r"it\'?s\s+important\s+to\s+note",
        r"it\'?s\s+worth\s+noting",
        r"in\s+conclusion",
        r"in\s+summary",
        r"to\s+summarize",
        r"firstly.*secondly.*thirdly",
        r"on\s+the\s+other\s+hand",
        r"having\s+said\s+that",
        r"with\s+that\s+being\s+said",
        r"it\s+is\s+important\s+to\s+understand",
        r"there\s+are\s+several\s+(?:factors|reasons|ways)",  # Non-capturing group
        r"let\'?s\s+delve\s+into",
        r"let\'?s\s+explore",
        r"delve\s+into",
        r"dive\s+into",
        r"landscape",  # "the X landscape"
        r"leverage",  # Overused in AI text
        r"utilize",  # Overused in AI text
        r"facilitate",  # Overused in AI text
        r"comprehensive\s+(?:guide|overview|analysis)",  # Non-capturing group
    ]

    def __init__(self, ollama_client: OllamaClient | None = None):
        """Initialize the quality analyzer.

        Args:
            ollama_client: Optional OllamaClient for LLM-based assessment.
        """
        self._ollama_client = ollama_client

        # Compile patterns
        self._ad_pattern = re.compile("|".join(self.AD_PATTERNS), re.IGNORECASE)
        self._affiliate_pattern = re.compile("|".join(self.AFFILIATE_PATTERNS), re.IGNORECASE)
        self._cta_pattern = re.compile("|".join(self.CTA_PATTERNS), re.IGNORECASE)
        self._aggregator_pattern = re.compile("|".join(self.AGGREGATOR_PATTERNS), re.IGNORECASE)
        self._clickbait_pattern = re.compile("|".join(self.CLICKBAIT_PATTERNS), re.IGNORECASE)
        self._seo_spam_pattern = re.compile("|".join(self.SEO_SPAM_PATTERNS), re.IGNORECASE)
        self._ai_pattern = re.compile("|".join(self.AI_PATTERNS), re.IGNORECASE)

    def set_ollama_client(self, client: OllamaClient) -> None:
        """Set the Ollama client for LLM-based assessment.

        Args:
            client: OllamaClient instance.
        """
        self._ollama_client = client

    def analyze(
        self,
        html: str,
        text: str | None = None,
        url: str | None = None,
        use_llm: bool = False,
        use_llm_on_ambiguous: bool = True,
    ) -> QualityResult:
        """Analyze content quality (synchronous version).

        Args:
            html: Raw HTML content.
            text: Extracted plain text (optional, will extract if not provided).
            url: Page URL (optional, for additional context).
            use_llm: Force LLM-based assessment.
            use_llm_on_ambiguous: Use LLM if rule-based score is ambiguous (0.4-0.6).

        Returns:
            QualityResult with quality score and detected issues.
        """
        # For sync API, run the async version
        try:
            # Check if we're already in an async context
            asyncio.get_running_loop()
            # If we get here, we're in an async context - use thread pool
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run, self.analyze_async(html, text, url, use_llm, use_llm_on_ambiguous)
                )
                return future.result()
        except RuntimeError:
            # No running event loop, safe to use asyncio.run()
            return asyncio.run(self.analyze_async(html, text, url, use_llm, use_llm_on_ambiguous))

    async def analyze_async(
        self,
        html: str,
        text: str | None = None,
        url: str | None = None,
        use_llm: bool = False,
        use_llm_on_ambiguous: bool = True,
    ) -> QualityResult:
        """Analyze content quality (async version).

        Args:
            html: Raw HTML content.
            text: Extracted plain text (optional, will extract if not provided).
            url: Page URL (optional, for additional context).
            use_llm: Force LLM-based assessment.
            use_llm_on_ambiguous: Use LLM if rule-based score is ambiguous (0.4-0.6).

        Returns:
            QualityResult with quality score and detected issues.
        """
        # Extract text if not provided
        if text is None:
            text = self._extract_text(html)

        # Extract features
        features = self._extract_features(html, text)

        # Detect issues
        issues, issue_details = self._detect_issues(html, text, features, url)

        # Calculate quality score (rule-based)
        quality_score = self._calculate_quality_score(features, issues)

        # Determine if LLM assessment is needed
        llm_assessed = False
        if use_llm or (use_llm_on_ambiguous and 0.4 <= quality_score <= 0.6):
            if self._ollama_client is not None:
                llm_result = await self._llm_assess_quality(text)
                if llm_result:
                    llm_assessed = True
                    # Update features with LLM assessment
                    features.llm_quality_score = llm_result.get("quality_score")
                    features.llm_is_ai_generated = llm_result.get("is_ai_generated")
                    features.llm_is_spam = llm_result.get("is_spam")
                    features.llm_assessment_reason = llm_result.get("reason")

                    # Incorporate LLM score into final score
                    if features.llm_quality_score is not None:
                        # Weight: 60% LLM, 40% rule-based
                        quality_score = 0.6 * features.llm_quality_score + 0.4 * quality_score

                    # Add LLM-detected issues
                    if features.llm_is_ai_generated:
                        if QualityIssue.AI_GENERATED not in issues:
                            issues.append(QualityIssue.AI_GENERATED)
                            issue_details["ai_generated_llm"] = {
                                "detected_by": "llm",
                                "reason": features.llm_assessment_reason,
                            }

                    if features.llm_is_spam:
                        if QualityIssue.SEO_SPAM not in issues:
                            issues.append(QualityIssue.SEO_SPAM)
                            issue_details["seo_spam_llm"] = {
                                "detected_by": "llm",
                                "reason": features.llm_assessment_reason,
                            }

                    if llm_result.get("is_aggregator"):
                        if QualityIssue.AGGREGATOR not in issues:
                            issues.append(QualityIssue.AGGREGATOR)
                            issue_details["aggregator_llm"] = {
                                "detected_by": "llm",
                                "reason": features.llm_assessment_reason,
                            }

        # Calculate penalty for ranking
        penalty = self._calculate_penalty(issues, issue_details)

        # Generate reason
        reason = self._generate_reason(issues, issue_details)
        if llm_assessed and features.llm_assessment_reason:
            reason = f"{reason}; LLM: {features.llm_assessment_reason}"

        logger.debug(
            "Content quality analysis complete",
            quality_score=quality_score,
            issues=[i.value for i in issues],
            penalty=penalty,
            llm_assessed=llm_assessed,
        )

        return QualityResult(
            quality_score=quality_score,
            issues=issues,
            issue_details=issue_details,
            features=features,
            penalty=penalty,
            reason=reason,
            llm_assessed=llm_assessed,
        )

    async def _llm_assess_quality(self, text: str) -> dict[str, Any] | None:
        """Use LLM to assess content quality.

        Args:
            text: Plain text content.

        Returns:
            Assessment dict or None if LLM unavailable/failed.
        """
        if self._ollama_client is None:
            return None

        client = self._ollama_client

        try:
            # Detect language for response
            is_japanese = self._is_japanese_text(text)

            # Truncate text to first 2000 chars and render prompt
            truncated_text = text[:2000]
            formatted_prompt = render_prompt(
                "quality_assessment",
                text=truncated_text,
                lang="ja" if is_japanese else "en",
            )

            # Generate assessment
            response = await client.generate(
                prompt=formatted_prompt,
                temperature=0.1,  # Low temperature for consistent assessment
                max_tokens=500,
                response_format="json",
            )

            async def _retry_llm_call(retry_prompt: str) -> str:
                return await client.generate(
                    prompt=retry_prompt,
                    temperature=0.1,
                    max_tokens=500,
                    response_format="json",
                )

            validated = await parse_and_validate(
                response=response,
                schema=QualityAssessmentOutput,
                template_name="quality_assessment",
                expect_array=False,
                llm_call=_retry_llm_call,
                max_retries=1,
                context={
                    "component": "quality_analyzer",
                    "input_len": len(truncated_text),
                    "lang": "ja" if is_japanese else "en",
                },
            )

            if validated is None:
                logger.warning("LLM quality assessment: invalid structured output")
                return None

            return validated.model_dump()
        except Exception as e:
            logger.warning("LLM quality assessment failed", error=str(e))
            return None

    def _is_japanese_text(self, text: str) -> bool:
        """Check if text is primarily Japanese.

        Args:
            text: Text to check.

        Returns:
            True if text appears to be Japanese.
        """
        if not text:
            return False

        # Count Japanese characters (hiragana, katakana, kanji)
        japanese_chars = sum(
            1
            for c in text
            if "\u3040" <= c <= "\u309f"  # Hiragana
            or "\u30a0" <= c <= "\u30ff"  # Katakana
            or "\u4e00" <= c <= "\u9fff"  # CJK Unified Ideographs
        )

        # If more than 10% Japanese characters, consider it Japanese
        return japanese_chars / len(text) > 0.1 if text else False

    def _extract_text(self, html: str) -> str:
        """Extract plain text from HTML."""
        # Remove script and style elements
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _extract_features(self, html: str, text: str) -> QualityFeatures:
        """Extract quality-related features from content."""
        features = QualityFeatures()

        html_lower = html.lower()

        # Text statistics
        features.total_text_length = len(text)
        features.html_length = len(html)

        # Word count (simple tokenization)
        words = re.findall(r"\b\w+\b", text.lower())
        features.word_count = len(words)

        # Sentence count
        sentences = re.split(r"[.!?。！？]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        features.sentence_count = len(sentences)

        # Paragraph count - count HTML block elements and text paragraphs
        # Count various block-level elements that indicate paragraph/content breaks
        p_tags = len(re.findall(r"<p\b[^>]*>", html, re.IGNORECASE))
        li_tags = len(re.findall(r"<li\b[^>]*>", html, re.IGNORECASE))
        # <br> tags (count consecutive <br> as single break, <br><br> = paragraph break)
        br_breaks = len(re.findall(r"(?:<br\s*/?>[\s\n]*){2,}", html, re.IGNORECASE))
        # <div> with substantial content (not just wrappers)
        len(re.findall(r"<div\b[^>]*>", html, re.IGNORECASE))
        # Blockquote, article, section also indicate content blocks
        blockquote_tags = len(re.findall(r"<blockquote\b[^>]*>", html, re.IGNORECASE))
        len(re.findall(r"<article\b[^>]*>", html, re.IGNORECASE))
        len(re.findall(r"<section\b[^>]*>", html, re.IGNORECASE))

        # HTML-based paragraph count: prioritize semantic elements
        # p and li are primary content blocks, others are structural
        html_paragraph_count = p_tags + li_tags + blockquote_tags
        # Add br breaks only if no p tags (indicates <br>-based formatting)
        if p_tags == 0:
            html_paragraph_count += br_breaks

        # Also count text paragraphs (double newlines) as fallback
        text_paragraphs = re.split(r"\n\s*\n", text)
        text_paragraphs = [p.strip() for p in text_paragraphs if p.strip()]
        text_paragraph_count = len(text_paragraphs)

        # Use the larger of the two counts (HTML structure or text structure)
        features.paragraph_count = max(html_paragraph_count, text_paragraph_count)

        # Average lengths
        if features.sentence_count > 0:
            features.avg_sentence_length = features.word_count / features.sentence_count
        if features.paragraph_count > 0:
            features.avg_paragraph_length = features.word_count / features.paragraph_count

        # Text to HTML ratio
        if features.html_length > 0:
            features.text_to_html_ratio = features.total_text_length / features.html_length

        # Structural features
        features.heading_count = len(re.findall(r"<h[1-6][^>]*>", html_lower))
        features.link_count = len(re.findall(r"<a[^>]*href", html_lower))
        features.image_count = len(re.findall(r"<img[^>]*>", html_lower))
        features.script_count = len(re.findall(r"<script[^>]*>", html_lower))

        # Link density
        if features.total_text_length > 0:
            link_text_len = self._extract_link_text_length(html)
            features.link_density = link_text_len / features.total_text_length

        # Ad element count
        features.ad_element_count = len(self._ad_pattern.findall(html_lower))

        # Unique word ratio
        if features.word_count > 0:
            unique_words = set(words)
            features.unique_word_ratio = len(unique_words) / features.word_count

        # Stopword ratio
        if features.word_count > 0:
            stopword_count = sum(
                1 for w in words if w in self.STOPWORDS_EN or w in self.STOPWORDS_JA
            )
            features.stopword_ratio = stopword_count / features.word_count

        # Capitalization ratio (for English text)
        if features.total_text_length > 0:
            upper_count = sum(1 for c in text if c.isupper())
            features.capitalization_ratio = upper_count / features.total_text_length

        # Punctuation density
        if features.total_text_length > 0:
            punct_count = sum(1 for c in text if c in ".,!?;:()[]{}\"'-")
            features.punctuation_density = punct_count / features.total_text_length

        # N-gram repetition
        features.ngram_repetition_score = self._calculate_ngram_repetition(words)

        # Phrase repetition
        features.phrase_repetition_count = self._count_phrase_repetitions(text)

        # Sentence similarity (uniformity indicator)
        if len(sentences) >= 2:
            features.sentence_similarity_score = self._calculate_sentence_similarity(sentences)

        # Burstiness (variation in sentence length)
        if len(sentences) >= 2:
            features.burstiness_score = self._calculate_burstiness(sentences)

        # Uniformity score
        features.uniformity_score = self._calculate_uniformity(sentences)

        # Keyword density (top words)
        features.keyword_density = self._calculate_keyword_density(words)

        # External link ratio
        features.external_link_ratio = self._calculate_external_link_ratio(html)

        # Affiliate link count
        features.affiliate_link_count = len(self._affiliate_pattern.findall(html))

        # Call-to-action count
        features.call_to_action_count = len(self._cta_pattern.findall(text))

        # Boilerplate/Navigation ratio
        features.boilerplate_ratio = self._calculate_boilerplate_ratio(html)
        features.navigation_ratio = self._calculate_navigation_ratio(html)
        features.footer_ratio = self._calculate_footer_ratio(html)

        # Aggregator indicators
        aggregator_matches = self._aggregator_pattern.findall(text)
        features.has_multiple_sources = len(aggregator_matches) >= 3
        features.has_attribution_pattern = len(aggregator_matches) >= 1
        features.source_mention_count = len(aggregator_matches)

        # Curated list pattern
        features.has_curated_list_pattern = bool(
            re.search(r"(top\s+\d+|best\s+\d+|\d+\s+(best|top)|まとめ|\d+選)", text.lower())
        )

        return features

    def _detect_issues(
        self,
        html: str,
        text: str,
        features: QualityFeatures,
        url: str | None,
    ) -> tuple[list[QualityIssue], dict[str, Any]]:
        """Detect quality issues in content."""
        issues: list[QualityIssue] = []
        details: dict[str, Any] = {}

        text_lower = text.lower()

        # Thin content
        if features.word_count < 100 or features.paragraph_count < 2:
            issues.append(QualityIssue.THIN_CONTENT)
            details["thin_content"] = {
                "word_count": features.word_count,
                "paragraph_count": features.paragraph_count,
            }

        # Ad-heavy
        if features.ad_element_count >= 5 or (
            features.ad_element_count >= 3 and features.word_count < 500
        ):
            issues.append(QualityIssue.AD_HEAVY)
            details["ad_heavy"] = {
                "ad_count": features.ad_element_count,
            }

        # Template-heavy (low text to HTML ratio)
        if features.text_to_html_ratio < 0.1 and features.html_length > 5000:
            issues.append(QualityIssue.TEMPLATE_HEAVY)
            details["template_heavy"] = {
                "text_to_html_ratio": features.text_to_html_ratio,
            }

        # Repetitive content
        if features.ngram_repetition_score > 0.3 or features.phrase_repetition_count >= 5:
            issues.append(QualityIssue.REPETITIVE)
            details["repetitive"] = {
                "ngram_score": features.ngram_repetition_score,
                "phrase_count": features.phrase_repetition_count,
            }

        # Keyword stuffing
        if features.keyword_density > 0.05:
            issues.append(QualityIssue.KEYWORD_STUFFING)
            details["keyword_stuffing"] = {
                "keyword_density": features.keyword_density,
            }

        # AI-generated content detection
        # Use finditer to count actual matches (findall with groups can be unreliable)
        ai_match_count = sum(1 for _ in self._ai_pattern.finditer(text_lower))
        ai_score = self._calculate_ai_score(features, ai_match_count)
        if ai_score > 0.6:
            issues.append(QualityIssue.AI_GENERATED)
            details["ai_generated"] = {
                "score": ai_score,
                "pattern_matches": ai_match_count,
                "uniformity": features.uniformity_score,
                "burstiness": features.burstiness_score,
            }

        # SEO spam
        seo_matches = self._seo_spam_pattern.findall(html.lower())
        if len(seo_matches) >= 2 or (len(seo_matches) >= 1 and features.keyword_density > 0.03):
            issues.append(QualityIssue.SEO_SPAM)
            details["seo_spam"] = {
                "pattern_matches": len(seo_matches),
                "keyword_density": features.keyword_density,
            }

        # Aggregator/curation site
        if features.has_multiple_sources or (
            features.has_curated_list_pattern and features.source_mention_count >= 2
        ):
            issues.append(QualityIssue.AGGREGATOR)
            details["aggregator"] = {
                "source_mentions": features.source_mention_count,
                "has_curated_pattern": features.has_curated_list_pattern,
            }

        # Clickbait
        clickbait_matches = self._clickbait_pattern.findall(text_lower)
        if len(clickbait_matches) >= 2:
            issues.append(QualityIssue.CLICKBAIT)
            details["clickbait"] = {
                "pattern_matches": len(clickbait_matches),
            }

        # Scraper/copy site detection
        if self._is_scraper_site(html, features, url):
            issues.append(QualityIssue.SCRAPER)
            details["scraper"] = {
                "indicators": self._get_scraper_indicators(html, features),
            }

        return issues, details

    def _calculate_quality_score(
        self,
        features: QualityFeatures,
        issues: list[QualityIssue],
    ) -> float:
        """Calculate overall quality score (0.0 to 1.0)."""
        # Start with base score
        score = 1.0

        # Deduct for each issue
        issue_penalties = {
            QualityIssue.THIN_CONTENT: 0.3,
            QualityIssue.AD_HEAVY: 0.2,
            QualityIssue.TEMPLATE_HEAVY: 0.15,
            QualityIssue.REPETITIVE: 0.2,
            QualityIssue.KEYWORD_STUFFING: 0.25,
            QualityIssue.AI_GENERATED: 0.3,
            QualityIssue.SEO_SPAM: 0.35,
            QualityIssue.AGGREGATOR: 0.2,
            QualityIssue.CLICKBAIT: 0.25,
            QualityIssue.SCRAPER: 0.4,
        }

        for issue in issues:
            score -= issue_penalties.get(issue, 0.1)

        # Positive signals
        if features.unique_word_ratio > 0.5:
            score += 0.05
        if features.text_to_html_ratio > 0.3:
            score += 0.05
        if features.burstiness_score > 0.3:  # Natural variation
            score += 0.05
        if features.paragraph_count >= 5 and features.heading_count >= 2:
            score += 0.05

        # Clamp to [0, 1]
        return max(0.0, min(1.0, score))

    def _calculate_penalty(
        self,
        issues: list[QualityIssue],
        details: dict[str, Any],
    ) -> float:
        """Calculate penalty to apply to ranking score."""
        if not issues:
            return 0.0

        # Base penalties per issue type
        penalties = {
            QualityIssue.THIN_CONTENT: 0.2,
            QualityIssue.AD_HEAVY: 0.15,
            QualityIssue.TEMPLATE_HEAVY: 0.1,
            QualityIssue.REPETITIVE: 0.15,
            QualityIssue.KEYWORD_STUFFING: 0.2,
            QualityIssue.AI_GENERATED: 0.25,
            QualityIssue.SEO_SPAM: 0.3,
            QualityIssue.AGGREGATOR: 0.15,
            QualityIssue.CLICKBAIT: 0.2,
            QualityIssue.SCRAPER: 0.35,
        }

        total_penalty = sum(penalties.get(issue, 0.1) for issue in issues)

        # Cap at 0.8 (don't completely eliminate)
        return min(0.8, total_penalty)

    def _generate_reason(
        self,
        issues: list[QualityIssue],
        details: dict[str, Any],
    ) -> str:
        """Generate human-readable reason for quality assessment."""
        if not issues:
            return "No quality issues detected"

        reasons = []

        for issue in issues:
            if issue == QualityIssue.THIN_CONTENT:
                d = details.get("thin_content", {})
                reasons.append(f"thin content ({d.get('word_count', 0)} words)")
            elif issue == QualityIssue.AD_HEAVY:
                d = details.get("ad_heavy", {})
                reasons.append(f"high ad density ({d.get('ad_count', 0)} ad elements)")
            elif issue == QualityIssue.TEMPLATE_HEAVY:
                d = details.get("template_heavy", {})
                reasons.append(f"high template ratio ({d.get('text_to_html_ratio', 0):.2%})")
            elif issue == QualityIssue.REPETITIVE:
                d = details.get("repetitive", {})
                reasons.append(f"repetitive content (score: {d.get('ngram_score', 0):.2f})")
            elif issue == QualityIssue.KEYWORD_STUFFING:
                d = details.get("keyword_stuffing", {})
                reasons.append(f"keyword stuffing ({d.get('keyword_density', 0):.2%})")
            elif issue == QualityIssue.AI_GENERATED:
                d = details.get("ai_generated", {})
                reasons.append(f"AI-generated content suspected (score: {d.get('score', 0):.2f})")
            elif issue == QualityIssue.SEO_SPAM:
                reasons.append("SEO spam patterns detected")
            elif issue == QualityIssue.AGGREGATOR:
                d = details.get("aggregator", {})
                reasons.append(f"aggregator/curation site ({d.get('source_mentions', 0)} sources)")
            elif issue == QualityIssue.CLICKBAIT:
                reasons.append("clickbait patterns detected")
            elif issue == QualityIssue.SCRAPER:
                reasons.append("content scraper suspected")

        return "; ".join(reasons)

    # Helper methods

    def _extract_link_text_length(self, html: str) -> int:
        """Extract total length of link text."""
        link_pattern = re.compile(r"<a[^>]*>(.*?)</a>", re.DOTALL | re.IGNORECASE)
        total_length = 0
        for match in link_pattern.finditer(html):
            link_text = re.sub(r"<[^>]+>", "", match.group(1))
            total_length += len(link_text.strip())
        return total_length

    def _calculate_ngram_repetition(self, words: list[str], n: int = 3) -> float:
        """Calculate n-gram repetition score."""
        if len(words) < n:
            return 0.0

        ngrams = []
        for i in range(len(words) - n + 1):
            ngram = tuple(words[i : i + n])
            ngrams.append(ngram)

        if not ngrams:
            return 0.0

        counter = Counter(ngrams)
        repeated = sum(count - 1 for count in counter.values() if count > 1)

        return repeated / len(ngrams)

    def _count_phrase_repetitions(self, text: str) -> int:
        """Count repeated phrases (4+ words)."""
        # Extract phrases of 4-8 words
        words = text.lower().split()
        phrases = []

        for length in range(4, 9):
            for i in range(len(words) - length + 1):
                phrase = " ".join(words[i : i + length])
                phrases.append(phrase)

        counter = Counter(phrases)
        return sum(1 for count in counter.values() if count > 1)

    def _calculate_sentence_similarity(self, sentences: list[str]) -> float:
        """Calculate average similarity between consecutive sentences."""
        if len(sentences) < 2:
            return 0.0

        similarities = []
        for i in range(len(sentences) - 1):
            words1 = set(sentences[i].lower().split())
            words2 = set(sentences[i + 1].lower().split())

            if not words1 or not words2:
                continue

            intersection = len(words1 & words2)
            union = len(words1 | words2)

            if union > 0:
                similarities.append(intersection / union)

        return sum(similarities) / len(similarities) if similarities else 0.0

    def _calculate_burstiness(self, sentences: list[str]) -> float:
        """Calculate burstiness (variation in sentence length).

        Higher burstiness = more natural (human) text.
        Lower burstiness = more uniform (AI-like) text.
        """
        if len(sentences) < 2:
            return 0.0

        lengths = [len(s.split()) for s in sentences]
        mean_length = sum(lengths) / len(lengths)

        if mean_length == 0:
            return 0.0

        variance = sum((length - mean_length) ** 2 for length in lengths) / len(lengths)
        std_dev = math.sqrt(variance)

        # Coefficient of variation
        cv = std_dev / mean_length

        # Normalize to 0-1 range (typical CV is 0.3-0.8 for natural text)
        return min(1.0, cv / 0.8)

    def _calculate_uniformity(self, sentences: list[str]) -> float:
        """Calculate uniformity score (how uniform the text structure is).

        Higher uniformity = more AI-like.
        """
        if len(sentences) < 3:
            return 0.0

        # Check sentence length uniformity
        lengths = [len(s.split()) for s in sentences]
        mean_length = sum(lengths) / len(lengths)

        if mean_length == 0:
            return 0.0

        # Calculate how many sentences are within 20% of mean length
        within_range = sum(1 for length in lengths if abs(length - mean_length) / mean_length < 0.2)

        return within_range / len(lengths)

    def _calculate_keyword_density(self, words: list[str]) -> float:
        """Calculate keyword density (most frequent non-stopword)."""
        if not words:
            return 0.0

        # Filter out stopwords
        content_words = [
            w
            for w in words
            if w not in self.STOPWORDS_EN and w not in self.STOPWORDS_JA and len(w) > 2
        ]

        if not content_words:
            return 0.0

        counter = Counter(content_words)
        most_common = counter.most_common(1)

        if not most_common:
            return 0.0

        return most_common[0][1] / len(words)

    def _calculate_external_link_ratio(self, html: str) -> float:
        """Calculate ratio of external links to total links."""
        # Find all links
        all_links = re.findall(r'<a[^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)

        if not all_links:
            return 0.0

        # Count external links (starting with http/https)
        external = sum(1 for link in all_links if link.startswith(("http://", "https://")))

        return external / len(all_links)

    def _calculate_boilerplate_ratio(self, html: str) -> float:
        """Calculate boilerplate content ratio."""
        html_lower = html.lower()

        # Common boilerplate patterns
        boilerplate_patterns = [
            r"<header[^>]*>.*?</header>",
            r"<footer[^>]*>.*?</footer>",
            r"<nav[^>]*>.*?</nav>",
            r"<aside[^>]*>.*?</aside>",
            r'class=["\'][^"\']*sidebar',
            r'class=["\'][^"\']*widget',
            r'class=["\'][^"\']*menu',
        ]

        boilerplate_length = 0
        for pattern in boilerplate_patterns:
            matches = re.findall(pattern, html_lower, re.DOTALL)
            boilerplate_length += sum(len(m) for m in matches)

        if len(html) == 0:
            return 0.0

        return boilerplate_length / len(html)

    def _calculate_navigation_ratio(self, html: str) -> float:
        """Calculate navigation element ratio."""
        html_lower = html.lower()

        nav_length = 0
        nav_matches = re.findall(r"<nav[^>]*>.*?</nav>", html_lower, re.DOTALL)
        nav_length += sum(len(m) for m in nav_matches)

        menu_matches = re.findall(
            r'class=["\'][^"\']*menu[^"\']*["\'][^>]*>.*?</\w+>', html_lower, re.DOTALL
        )
        nav_length += sum(len(m) for m in menu_matches)

        if len(html) == 0:
            return 0.0

        return nav_length / len(html)

    def _calculate_footer_ratio(self, html: str) -> float:
        """Calculate footer content ratio."""
        html_lower = html.lower()

        footer_length = 0
        footer_matches = re.findall(r"<footer[^>]*>.*?</footer>", html_lower, re.DOTALL)
        footer_length += sum(len(m) for m in footer_matches)

        if len(html) == 0:
            return 0.0

        return footer_length / len(html)

    def _calculate_ai_score(self, features: QualityFeatures, pattern_matches: int) -> float:
        """Calculate AI-generated content likelihood score."""
        score = 0.0

        # Pattern matches - many AI phrases is a strong signal
        if pattern_matches >= 10:
            score += 0.65  # Very strong signal - almost certainly AI
        elif pattern_matches >= 5:
            score += 0.5  # Strong signal
        elif pattern_matches >= 3:
            score += 0.3
        elif pattern_matches >= 1:
            score += 0.1

        # High uniformity (AI tends to be uniform)
        if features.uniformity_score > 0.6:
            score += 0.2
        elif features.uniformity_score > 0.4:
            score += 0.1

        # Low burstiness (AI tends to have consistent sentence lengths)
        if features.burstiness_score < 0.2:
            score += 0.2
        elif features.burstiness_score < 0.3:
            score += 0.1

        # High sentence similarity
        if features.sentence_similarity_score > 0.3:
            score += 0.15

        # Very structured (many headings relative to content)
        if features.word_count > 0:
            heading_ratio = features.heading_count / (features.word_count / 100)
            if heading_ratio > 0.5:
                score += 0.1

        return min(1.0, score)

    def _is_scraper_site(
        self,
        html: str,
        features: QualityFeatures,
        url: str | None,
    ) -> bool:
        """Detect if this is a content scraper site."""
        indicators = 0

        # Very high external link ratio
        if features.external_link_ratio > 0.8:
            indicators += 1

        # Multiple source attributions
        if features.source_mention_count >= 5:
            indicators += 1

        # High boilerplate ratio
        if features.boilerplate_ratio > 0.5:
            indicators += 1

        # Low unique word ratio
        if features.unique_word_ratio < 0.3:
            indicators += 1

        # Check for common scraper patterns in HTML
        scraper_patterns = [
            r"(scraped|crawled|aggregated)\s+from",
            r"(original|source)\s+(article|content)\s*:",
            r"content\s+(from|via)\s+",
        ]

        html_lower = html.lower()
        for pattern in scraper_patterns:
            if re.search(pattern, html_lower):
                indicators += 1

        return indicators >= 3

    def _get_scraper_indicators(
        self,
        html: str,
        features: QualityFeatures,
    ) -> list[str]:
        """Get list of scraper indicators found."""
        indicators = []

        if features.external_link_ratio > 0.8:
            indicators.append("high_external_links")
        if features.source_mention_count >= 5:
            indicators.append("many_source_mentions")
        if features.boilerplate_ratio > 0.5:
            indicators.append("high_boilerplate")
        if features.unique_word_ratio < 0.3:
            indicators.append("low_unique_words")

        return indicators


# Singleton instance
_analyzer: ContentQualityAnalyzer | None = None


def get_quality_analyzer() -> ContentQualityAnalyzer:
    """Get or create the singleton ContentQualityAnalyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = ContentQualityAnalyzer()
    return _analyzer


def analyze_content_quality(
    html: str,
    text: str | None = None,
    url: str | None = None,
) -> QualityResult:
    """Analyze content quality.

    Convenience function that uses the singleton analyzer.

    Args:
        html: Raw HTML content.
        text: Extracted plain text (optional).
        url: Page URL (optional).

    Returns:
        QualityResult with quality score and detected issues.
    """
    analyzer = get_quality_analyzer()
    return analyzer.analyze(html, text, url)
