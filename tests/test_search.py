"""
Tests for src/search/search_api.py

Tests query processing, source classification, and query expansion.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-NQ-01 | Normalize basic query | Equivalence – simple | Lowercase string | - |
| TC-NQ-02 | Normalize with spaces | Equivalence – whitespace | Trimmed and collapsed | - |
| TC-CK-01 | Cache key deterministic | Equivalence – determinism | Same key for same input | - |
| TC-CK-02 | Cache key unique | Equivalence – uniqueness | Different keys for different input | - |
| TC-SC-01 | Classify primary source | Equivalence – primary | source_type=PRIMARY | - |
| TC-SC-02 | Classify secondary source | Equivalence – secondary | source_type=SECONDARY | - |
| TC-SC-03 | Classify tertiary source | Equivalence – tertiary | source_type=TERTIARY | - |
| TC-QE-01 | Expand query basic | Equivalence – expansion | Expanded query list | - |
| TC-QE-02 | Expand query with operators | Equivalence – operators | Operators applied | - |
| TC-QE-03 | Expand empty query | Boundary – empty | Empty or original | - |
| TC-SE-01 | Execute search | Equivalence – search | SearchResult returned | - |
| TC-SE-02 | Execute with cache hit | Equivalence – caching | Cached result | - |
| TC-SE-03 | Execute with error | Abnormal – error | Handles gracefully | - |
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestNormalizeQuery:
    """Tests for query normalization."""

    def test_normalize_query_basic(self):
        """Test basic query normalization."""
        from src.search.search_api import _normalize_query

        assert _normalize_query("Test Query") == "test query"
        assert _normalize_query("  Multiple   Spaces  ") == "multiple spaces"
        assert _normalize_query("UPPERCASE") == "uppercase"


class TestGetCacheKey:
    """Tests for cache key generation."""

    def test_cache_key_deterministic(self):
        """Test cache key is deterministic for same inputs."""
        from src.search.search_api import _get_cache_key

        key1 = _get_cache_key("test query", ["google"], "day")
        key2 = _get_cache_key("test query", ["google"], "day")

        assert key1 == key2

    def test_cache_key_different_for_different_queries(self):
        """Test cache key differs for different queries."""
        from src.search.search_api import _get_cache_key

        key1 = _get_cache_key("query 1", ["google"], "day")
        key2 = _get_cache_key("query 2", ["google"], "day")

        assert key1 != key2

    def test_cache_key_different_for_different_engines(self):
        """Test cache key differs for different engines."""
        from src.search.search_api import _get_cache_key

        key1 = _get_cache_key("query", ["google"], "day")
        key2 = _get_cache_key("query", ["bing"], "day")

        assert key1 != key2

    def test_cache_key_engine_order_independent(self):
        """Test cache key is same regardless of engine order."""
        from src.search.search_api import _get_cache_key

        key1 = _get_cache_key("query", ["google", "bing"], "day")
        key2 = _get_cache_key("query", ["bing", "google"], "day")

        assert key1 == key2


class TestClassifySource:
    """Tests for source classification."""

    def test_classify_academic(self):
        """Test academic source classification."""
        from src.search.search_api import _classify_source

        assert _classify_source("https://arxiv.org/abs/1234.5678") == "academic"
        assert _classify_source("https://pubmed.ncbi.nlm.nih.gov/12345") == "academic"
        assert _classify_source("https://www.jstage.jst.go.jp/article/xxx") == "academic"

    def test_classify_government(self):
        """Test government source classification."""
        from src.search.search_api import _classify_source

        assert _classify_source("https://www.go.jp/ministry/report") == "government"
        assert _classify_source("https://www.gov.uk/policy") == "government"
        assert _classify_source("https://example.gov/data") == "government"

    def test_classify_standards(self):
        """Test standards source classification."""
        from src.search.search_api import _classify_source

        assert _classify_source("https://www.iso.org/standard/12345") == "standards"
        assert _classify_source("https://tools.ietf.org/html/rfc1234") == "standards"
        assert _classify_source("https://www.w3.org/TR/html5") == "standards"

    def test_classify_knowledge(self):
        """Test knowledge source classification."""
        from src.search.search_api import _classify_source

        assert _classify_source("https://en.wikipedia.org/wiki/Test") == "knowledge"
        assert _classify_source("https://www.wikidata.org/wiki/Q123") == "knowledge"

    def test_classify_news(self):
        """Test news source classification."""
        from src.search.search_api import _classify_source

        assert _classify_source("https://www.bbc.com/news/article") == "news"
        assert _classify_source("https://www.reuters.com/article/xyz") == "news"
        assert _classify_source("https://www.nhk.or.jp/news/html/xxx") == "news"

    def test_classify_technical(self):
        """Test technical source classification."""
        from src.search.search_api import _classify_source

        assert _classify_source("https://github.com/user/repo") == "technical"
        assert _classify_source("https://stackoverflow.com/questions/123") == "technical"
        assert _classify_source("https://docs.python.org/3/") == "technical"

    def test_classify_blog(self):
        """Test blog source classification."""
        from src.search.search_api import _classify_source

        assert _classify_source("https://medium.com/@user/article") == "blog"
        assert _classify_source("https://qiita.com/user/items/xxx") == "blog"
        assert _classify_source("https://zenn.dev/user/articles/xxx") == "blog"
        assert _classify_source("https://example.com/blog/post") == "blog"

    def test_classify_unknown(self):
        """Test unknown source classification."""
        from src.search.search_api import _classify_source

        assert _classify_source("https://random-site.com/page") == "unknown"
        assert _classify_source("https://example.org/article") == "unknown"


# search_serp() uses BrowserSearchProvider via provider abstraction
# Tests for provider-based search are in test_browser_search_provider.py


class TestQueryExpander:
    """Tests for QueryExpander class."""

    def test_tokenize_basic(self):
        """Test basic tokenization."""
        from src.search.search_api import QueryExpander

        expander = QueryExpander()
        tokens = expander.tokenize("人工知能の研究")

        # Should return list of token dicts (Japanese text should have >=2 tokens)
        assert isinstance(tokens, list)
        assert len(tokens) >= 2, f"Expected >=2 tokens for Japanese text, got {len(tokens)}"
        assert all("surface" in t for t in tokens)

    def test_get_synonyms_known_word(self):
        """Test getting synonyms for known words.

        Validates §3.1.1 synonym expansion for search query diversification.
        """
        from src.search.search_api import QueryExpander

        expander = QueryExpander()
        expander._ensure_initialized()

        synonyms = expander.get_synonyms("AI")

        # STRICT: AI's synonyms are defined in _init_synonym_dict as ["人工知能", "エーアイ", "機械知能"]
        assert "人工知能" in synonyms, f"Expected '人工知能' in synonyms, got {synonyms}"
        assert "エーアイ" in synonyms, f"Expected 'エーアイ' in synonyms, got {synonyms}"
        assert "機械知能" in synonyms, f"Expected '機械知能' in synonyms, got {synonyms}"

    def test_get_synonyms_unknown_word(self):
        """Test getting synonyms for unknown words."""
        from src.search.search_api import QueryExpander

        expander = QueryExpander()
        expander._ensure_initialized()

        synonyms = expander.get_synonyms("xyzabc123")

        # Should return empty for unknown words
        assert synonyms == []

    def test_expand_with_normalized_forms(self):
        """Test normalized form expansion.

        Validates query variant generation for §3.1.1 search diversification.
        Original query must always be included in results.
        """
        from src.search.search_api import QueryExpander

        expander = QueryExpander()

        # Test with a query that might have normalization variations
        query = "テスト"
        variants = expander.expand_with_normalized_forms(query)

        # STRICT: Original query must always be included as first element
        assert isinstance(variants, list), f"Expected list, got {type(variants)}"
        assert variants[0] == query, (
            f"First element should be original query '{query}', got '{variants[0]}'"
        )
        assert query in variants, f"Original query '{query}' must be in variants"

    def test_expand_with_synonyms(self):
        """Test synonym-based expansion.

        Validates §3.1.1 query diversification via synonyms.
        Original query must always be first, additional variants expected.
        """
        from src.search.search_api import QueryExpander

        expander = QueryExpander()

        query = "AI の 問題"
        variants = expander.expand_with_synonyms(query)

        # STRICT: Original query must be first element
        assert variants[0] == query, f"First element should be '{query}', got '{variants[0]}'"
        # STRICT: Should have additional variants (AI -> 人工知能 and 問題 -> 課題 exist in synonym dict)
        assert len(variants) >= 2, (
            f"Expected at least 2 variants (original + synonym), got {len(variants)}"
        )

    def test_generate_variants_all(self):
        """Test generating all variants.

        Validates combined query expansion for §3.1.1.
        人工知能 has synonyms ["AI", "エーアイ", "機械知能"].
        """
        from src.search.search_api import QueryExpander

        expander = QueryExpander()

        query = "人工知能"
        variants = expander.generate_variants(
            query,
            include_normalized=True,
            include_synonyms=True,
            max_results=5,
        )

        # STRICT: Original must be first element
        assert variants[0] == query, f"First element should be '{query}', got '{variants[0]}'"
        # STRICT: Upper bound respected
        assert len(variants) <= 5, f"Expected at most 5 variants, got {len(variants)}"
        # STRICT: Should have synonym variants (人工知能 has synonyms in dict)
        assert len(variants) >= 2, f"Expected at least 2 variants, got {len(variants)}"

    def test_generate_variants_respects_max_results(self):
        """Test that variant generation respects max_results."""
        from src.search.search_api import QueryExpander

        expander = QueryExpander()

        variants = expander.generate_variants(
            "問題 方法 結果",
            include_normalized=True,
            include_synonyms=True,
            max_results=3,
        )

        assert len(variants) <= 3


class TestExpandQuery:
    """Tests for expand_query function."""

    @pytest.mark.asyncio
    async def test_expand_query_returns_base(self):
        """Test expand_query returns at least the base query."""
        from src.search.search_api import expand_query

        results = await expand_query("test query")

        assert "test query" in results

    @pytest.mark.asyncio
    async def test_expand_query_japanese(self):
        """Test expand_query with Japanese query.

        Validates §3.1.1 query expansion for Japanese text.
        """
        from src.search.search_api import expand_query

        query = "人工知能 の 影響"
        results = await expand_query(query, language="ja")

        # STRICT: Original query must be first element
        assert results[0] == query, f"First element should be '{query}', got '{results[0]}'"
        # STRICT: Should have variants (人工知能 and 影響 both have synonyms)
        assert len(results) >= 2, (
            f"Expected at least 2 variants for query with known synonyms, got {len(results)}"
        )

    @pytest.mark.asyncio
    async def test_expand_query_synonyms_only(self):
        """Test expand_query with synonyms expansion only."""
        from src.search.search_api import expand_query

        results = await expand_query("AI", expansion_type="synonyms", language="ja")

        assert "AI" in results

    @pytest.mark.asyncio
    async def test_expand_query_normalized_only(self):
        """Test expand_query with normalized expansion only."""
        from src.search.search_api import expand_query

        results = await expand_query("テスト", expansion_type="normalized", language="ja")

        assert "テスト" in results

    @pytest.mark.asyncio
    async def test_expand_query_non_japanese(self):
        """Test expand_query with non-Japanese language returns original."""
        from src.search.search_api import expand_query

        results = await expand_query("artificial intelligence", language="en")

        # Should only return original for non-Japanese
        assert results == ["artificial intelligence"]

    @pytest.mark.asyncio
    async def test_expand_query_empty_string(self):
        """Test expand_query with empty string."""
        from src.search.search_api import expand_query

        results = await expand_query("")

        assert results == [""]

    @pytest.mark.asyncio
    async def test_expand_query_max_results(self):
        """Test expand_query respects max_results."""
        from src.search.search_api import expand_query

        results = await expand_query(
            "問題 方法 影響 分析",
            max_results=3,
            language="ja",
        )

        assert len(results) <= 3


# ============================================================================
# Mirror Query Generation Tests (§3.1.1)
# ============================================================================


@pytest.mark.unit
class TestGenerateMirrorQuery:
    """Tests for generate_mirror_query function.

    Implements cross-language (JA↔EN) mirror query auto-generation (§3.1.1).
    LLM calls are mocked to avoid external dependencies.
    """

    @pytest.mark.asyncio
    async def test_valid_query_with_llm_success(self):
        """MQ-N-01: Test successful translation with LLM."""
        from unittest.mock import patch

        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        # Given: A valid Japanese query and mocked LLM returning translation
        query = "テストクエリ"
        _mirror_query_cache.clear()

        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value="test query")

        # When: generate_mirror_query is called
        with patch("src.filter.llm._get_client", return_value=mock_client):
            result = await generate_mirror_query(query, "ja", "en")

        # Then: Returns translated query
        assert result == "test query"

    @pytest.mark.asyncio
    async def test_same_language_returns_original(self):
        """MQ-N-02: Test same language returns original query without LLM call."""
        from src.search.search_api import generate_mirror_query

        # Given: A query with same source and target language
        query = "テストクエリ"

        # When: generate_mirror_query is called with same languages
        result = await generate_mirror_query(query, "ja", "ja")

        # Then: Returns original query without modification
        assert result == query

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_value(self):
        """MQ-N-03: Test cache hit returns cached value."""
        from unittest.mock import patch

        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        # Given: A query already in cache
        query = "キャッシュテスト"
        cache_key = f"mirror:ja:en:{query}"
        _mirror_query_cache.clear()
        _mirror_query_cache[cache_key] = "cached translation"

        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value="new translation")

        # When: generate_mirror_query is called
        with patch("src.filter.llm._get_client", return_value=mock_client):
            result = await generate_mirror_query(query, "ja", "en")

        # Then: Returns cached value, LLM not called
        assert result == "cached translation"
        mock_client.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_double_quote_removal(self):
        """MQ-N-04: Test double quote removal from LLM response."""
        from unittest.mock import patch

        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        # Given: LLM returns response wrapped in double quotes
        query = "クォートテスト"
        _mirror_query_cache.clear()

        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value='"quoted response"')

        # When: generate_mirror_query is called
        with patch("src.filter.llm._get_client", return_value=mock_client):
            result = await generate_mirror_query(query, "ja", "en")

        # Then: Returns response without quotes
        assert result == "quoted response"

    @pytest.mark.asyncio
    async def test_single_quote_removal(self):
        """MQ-N-05: Test single quote removal from LLM response."""
        from unittest.mock import patch

        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        # Given: LLM returns response wrapped in single quotes
        query = "シングルクォート"
        _mirror_query_cache.clear()

        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value="'single quoted'")

        # When: generate_mirror_query is called
        with patch("src.filter.llm._get_client", return_value=mock_client):
            result = await generate_mirror_query(query, "ja", "en")

        # Then: Returns response without quotes
        assert result == "single quoted"

    @pytest.mark.asyncio
    async def test_empty_string_returns_none(self):
        """MQ-A-01: Test empty string returns None."""
        from src.search.search_api import generate_mirror_query

        # Given: An empty query string
        query = ""

        # When: generate_mirror_query is called
        result = await generate_mirror_query(query, "ja", "en")

        # Then: Returns None (early return)
        assert result is None

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_none(self):
        """MQ-A-02: Test whitespace-only string returns None."""
        from src.search.search_api import generate_mirror_query

        # Given: A query with only whitespace
        query = "   "

        # When: generate_mirror_query is called
        result = await generate_mirror_query(query, "ja", "en")

        # Then: Returns None (strip makes it empty)
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self):
        """MQ-A-03: Test LLM exception returns None."""
        from unittest.mock import patch

        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        # Given: LLM raises an exception
        query = "例外テスト"
        _mirror_query_cache.clear()

        mock_client = MagicMock()
        mock_client.generate = AsyncMock(side_effect=Exception("LLM error"))

        # When: generate_mirror_query is called
        with patch("src.filter.llm._get_client", return_value=mock_client):
            result = await generate_mirror_query(query, "ja", "en")

        # Then: Returns None (exception handled)
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_empty_response_returns_none(self):
        """MQ-A-04: Test LLM returning empty string returns None."""
        from unittest.mock import patch

        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        # Given: LLM returns empty string
        query = "空レスポンス"
        _mirror_query_cache.clear()

        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value="")

        # When: generate_mirror_query is called
        with patch("src.filter.llm._get_client", return_value=mock_client):
            result = await generate_mirror_query(query, "ja", "en")

        # Then: Returns None (validation failed)
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_same_as_original_returns_none(self):
        """MQ-A-05: Test LLM returning same query as original returns None."""
        from unittest.mock import patch

        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        # Given: LLM returns the same query (translation failed)
        query = "同一クエリ"
        _mirror_query_cache.clear()

        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value="同一クエリ")

        # When: generate_mirror_query is called
        with patch("src.filter.llm._get_client", return_value=mock_client):
            result = await generate_mirror_query(query, "ja", "en")

        # Then: Returns None (translation considered failed)
        assert result is None


# ============================================================================
# Query Operator Processing Tests (§3.1.1, §3.1.4)
# ============================================================================


@pytest.mark.unit
class TestParsedOperator:
    """Tests for ParsedOperator dataclass.

    Validates the data structure for parsed search operators (§3.1.1).
    """

    def test_parsed_operator_creation(self):
        """Test basic ParsedOperator creation.

        Verifies that ParsedOperator correctly stores operator_type, value,
        and raw_text fields as specified.
        """
        from src.search.search_api import ParsedOperator

        op = ParsedOperator(
            operator_type="site",
            value="example.com",
            raw_text="site:example.com",
        )

        assert op.operator_type == "site", (
            f"Expected operator_type='site', got '{op.operator_type}'"
        )
        assert op.value == "example.com", f"Expected value='example.com', got '{op.value}'"
        assert op.raw_text == "site:example.com", (
            f"Expected raw_text='site:example.com', got '{op.raw_text}'"
        )


@pytest.mark.unit
class TestParsedQuery:
    """Tests for ParsedQuery dataclass.

    Validates the data structure for parsed queries with operators (§3.1.1).
    """

    def test_parsed_query_has_operator(self):
        """Test ParsedQuery.has_operator method.

        Verifies that has_operator correctly identifies presence/absence
        of specific operator types in the parsed query.
        """
        from src.search.search_api import ParsedOperator, ParsedQuery

        parsed = ParsedQuery(
            base_query="test",
            operators=[
                ParsedOperator("site", "go.jp", "site:go.jp"),
                ParsedOperator("filetype", "pdf", "filetype:pdf"),
            ],
        )

        assert parsed.has_operator("site") is True, "Expected has_operator('site') to be True"
        assert parsed.has_operator("filetype") is True, (
            "Expected has_operator('filetype') to be True"
        )
        assert parsed.has_operator("intitle") is False, (
            "Expected has_operator('intitle') to be False"
        )

    def test_parsed_query_get_operators(self):
        """Test ParsedQuery.get_operators method.

        Verifies that get_operators returns correct list of operators
        filtered by type.
        """
        from src.search.search_api import ParsedOperator, ParsedQuery

        parsed = ParsedQuery(
            base_query="test",
            operators=[
                ParsedOperator("exclude", "spam", "-spam"),
                ParsedOperator("exclude", "ads", "-ads"),
                ParsedOperator("site", "go.jp", "site:go.jp"),
            ],
        )

        exclude_ops = parsed.get_operators("exclude")
        assert len(exclude_ops) == 2, f"Expected 2 exclude operators, got {len(exclude_ops)}"

        site_ops = parsed.get_operators("site")
        assert len(site_ops) == 1, f"Expected 1 site operator, got {len(site_ops)}"
        assert site_ops[0].value == "go.jp", (
            f"Expected site value='go.jp', got '{site_ops[0].value}'"
        )


@pytest.mark.unit
class TestQueryOperatorProcessor:
    """Tests for QueryOperatorProcessor class.

    Validates §3.1.1 (query operators: site:, filetype:, intitle:, "...", +/-, after:)
    and §3.1.4 (engine normalization: mapping operators to engine-specific syntax).
    """

    def test_parse_site_operator(self):
        """Test parsing site: operator.

        Validates §3.1.1: site: operator for domain restriction (e.g., site:go.jp).
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("AI規制 site:go.jp")

        assert parsed.base_query == "AI規制", (
            f"Expected base_query='AI規制', got '{parsed.base_query}'"
        )
        assert len(parsed.operators) == 1, f"Expected 1 operator, got {len(parsed.operators)}"
        assert parsed.operators[0].operator_type == "site", (
            f"Expected operator_type='site', got '{parsed.operators[0].operator_type}'"
        )
        assert parsed.operators[0].value == "go.jp", (
            f"Expected value='go.jp', got '{parsed.operators[0].value}'"
        )

    def test_parse_filetype_operator(self):
        """Test parsing filetype: operator.

        Validates §3.1.1: filetype: operator for file type restriction.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("技術仕様 filetype:pdf")

        assert parsed.base_query == "技術仕様", (
            f"Expected base_query='技術仕様', got '{parsed.base_query}'"
        )
        assert len(parsed.operators) == 1, f"Expected 1 operator, got {len(parsed.operators)}"
        assert parsed.operators[0].operator_type == "filetype", (
            f"Expected operator_type='filetype', got '{parsed.operators[0].operator_type}'"
        )
        assert parsed.operators[0].value == "pdf", (
            f"Expected value='pdf', got '{parsed.operators[0].value}'"
        )

    def test_parse_intitle_operator_unquoted(self):
        """Test parsing intitle: operator with unquoted value.

        Validates §3.1.1: intitle: operator for title search.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("intitle:重要 調査レポート")

        assert "調査レポート" in parsed.base_query, (
            f"Expected '調査レポート' in base_query, got '{parsed.base_query}'"
        )
        assert len(parsed.operators) == 1, f"Expected 1 operator, got {len(parsed.operators)}"
        assert parsed.operators[0].operator_type == "intitle", (
            f"Expected operator_type='intitle', got '{parsed.operators[0].operator_type}'"
        )
        assert parsed.operators[0].value == "重要", (
            f"Expected value='重要', got '{parsed.operators[0].value}'"
        )

    def test_parse_intitle_operator_quoted(self):
        """Test parsing intitle: operator with quoted value.

        Validates §3.1.1: intitle:"phrase" for multi-word title search.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse('intitle:"重要なお知らせ" 情報')

        assert "情報" in parsed.base_query, (
            f"Expected '情報' in base_query, got '{parsed.base_query}'"
        )
        assert len(parsed.operators) == 1, f"Expected 1 operator, got {len(parsed.operators)}"
        assert parsed.operators[0].operator_type == "intitle", (
            f"Expected operator_type='intitle', got '{parsed.operators[0].operator_type}'"
        )
        assert parsed.operators[0].value == "重要なお知らせ", (
            f"Expected value='重要なお知らせ', got '{parsed.operators[0].value}'"
        )

    def test_parse_exact_phrase(self):
        """Test parsing exact phrase with quotes.

        Validates §3.1.1: Phrase fixing ("...") for exact phrase matching.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse('"人工知能の発展" 影響')

        assert "影響" in parsed.base_query, (
            f"Expected '影響' in base_query, got '{parsed.base_query}'"
        )
        assert len(parsed.operators) == 1, f"Expected 1 operator, got {len(parsed.operators)}"
        assert parsed.operators[0].operator_type == "exact", (
            f"Expected operator_type='exact', got '{parsed.operators[0].operator_type}'"
        )
        assert parsed.operators[0].value == "人工知能の発展", (
            f"Expected value='人工知能の発展', got '{parsed.operators[0].value}'"
        )

    def test_parse_exclude_operator(self):
        """Test parsing exclude (-) operator.

        Validates §3.1.1: Required/Exclude (+/-) for term exclusion.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("AI -spam -広告")

        assert "AI" in parsed.base_query, f"Expected 'AI' in base_query, got '{parsed.base_query}'"
        assert len(parsed.operators) == 2, f"Expected 2 operators, got {len(parsed.operators)}"

        exclude_values = [op.value for op in parsed.operators if op.operator_type == "exclude"]
        assert "spam" in exclude_values, f"Expected 'spam' in exclude values, got {exclude_values}"
        assert "広告" in exclude_values, f"Expected '広告' in exclude values, got {exclude_values}"

    def test_parse_required_operator(self):
        """Test parsing required (+) operator.

        Validates §3.1.1: Required/Exclude (+/-) for required terms.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("機械学習 +Python +TensorFlow")

        assert "機械学習" in parsed.base_query, (
            f"Expected '機械学習' in base_query, got '{parsed.base_query}'"
        )
        assert len(parsed.operators) == 2, f"Expected 2 operators, got {len(parsed.operators)}"

        required_values = [op.value for op in parsed.operators if op.operator_type == "required"]
        assert "Python" in required_values, (
            f"Expected 'Python' in required values, got {required_values}"
        )
        assert "TensorFlow" in required_values, (
            f"Expected 'TensorFlow' in required values, got {required_values}"
        )

    def test_parse_date_after_operator(self):
        """Test parsing after: operator for date filtering.

        Validates §3.1.1: after: operator for time range filtering.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("最新技術 after:2024-01-01")

        assert "最新技術" in parsed.base_query, (
            f"Expected '最新技術' in base_query, got '{parsed.base_query}'"
        )
        assert len(parsed.operators) == 1, f"Expected 1 operator, got {len(parsed.operators)}"
        assert parsed.operators[0].operator_type == "date_after", (
            f"Expected operator_type='date_after', got '{parsed.operators[0].operator_type}'"
        )
        assert parsed.operators[0].value == "2024-01-01", (
            f"Expected value='2024-01-01', got '{parsed.operators[0].value}'"
        )

    def test_parse_date_after_year_only(self):
        """Test parsing after: with year only.

        Validates §3.1.1: after: operator with abbreviated date format.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("研究 after:2023")

        assert parsed.operators[0].operator_type == "date_after", (
            f"Expected operator_type='date_after', got '{parsed.operators[0].operator_type}'"
        )
        assert parsed.operators[0].value == "2023", (
            f"Expected value='2023', got '{parsed.operators[0].value}'"
        )

    def test_parse_multiple_operators(self):
        """Test parsing query with multiple operators.

        Validates §3.1.1: systematic application of multiple operators in a single query.
        Tests the combination of site:, filetype:, "...", -, and after: operators.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        query = 'AI規制 site:go.jp filetype:pdf "ガイドライン" -draft after:2023'
        parsed = processor.parse(query)

        # Base query should only contain "AI規制"
        assert "AI規制" in parsed.base_query, (
            f"Expected 'AI規制' in base_query, got '{parsed.base_query}'"
        )

        # Should have 5 operators
        assert len(parsed.operators) == 5, f"Expected 5 operators, got {len(parsed.operators)}"

        # Verify each operator type is present
        op_types = [op.operator_type for op in parsed.operators]
        assert "site" in op_types, f"Expected 'site' in operator types, got {op_types}"
        assert "filetype" in op_types, f"Expected 'filetype' in operator types, got {op_types}"
        assert "exact" in op_types, f"Expected 'exact' in operator types, got {op_types}"
        assert "exclude" in op_types, f"Expected 'exclude' in operator types, got {op_types}"
        assert "date_after" in op_types, f"Expected 'date_after' in operator types, got {op_types}"

        # Verify specific values
        site_op = next(op for op in parsed.operators if op.operator_type == "site")
        assert site_op.value == "go.jp", f"Expected site value='go.jp', got '{site_op.value}'"

        filetype_op = next(op for op in parsed.operators if op.operator_type == "filetype")
        assert filetype_op.value == "pdf", (
            f"Expected filetype value='pdf', got '{filetype_op.value}'"
        )

    def test_parse_no_operators(self):
        """Test parsing query without operators.

        Verifies that plain text queries are handled correctly without operator extraction.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("simple query text")

        assert parsed.base_query == "simple query text", (
            f"Expected base_query='simple query text', got '{parsed.base_query}'"
        )
        assert len(parsed.operators) == 0, f"Expected 0 operators, got {len(parsed.operators)}"

    def test_parse_exclude_not_negative_number(self):
        """Test that negative numbers are not treated as exclude operators.

        Validates edge case: -10 (negative number) should not be parsed as exclude operator.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("temperature -10 degrees")

        # "-10" should NOT be parsed as an exclude operator (it's a number)
        exclude_values = [op.value for op in parsed.operators if op.operator_type == "exclude"]
        assert "10" not in exclude_values, (
            f"'10' should not be in exclude values, got {exclude_values}"
        )

    def test_transform_for_google(self):
        """Test transforming query for Google engine.

        Validates §3.1.4: Google supports all standard operators including after:.
        """
        from src.search.search_api import ParsedOperator, ParsedQuery, QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = ParsedQuery(
            base_query="AI研究",
            operators=[
                ParsedOperator("site", "arxiv.org", "site:arxiv.org"),
                ParsedOperator("filetype", "pdf", "filetype:pdf"),
                ParsedOperator("date_after", "2024", "after:2024"),
            ],
        )

        result = processor.transform_for_engine(parsed, "google")

        assert "AI研究" in result, f"Expected 'AI研究' in result, got '{result}'"
        assert "site:arxiv.org" in result, f"Expected 'site:arxiv.org' in result, got '{result}'"
        assert "filetype:pdf" in result, f"Expected 'filetype:pdf' in result, got '{result}'"
        assert "after:2024" in result, f"Expected 'after:2024' in result, got '{result}'"

    def test_transform_for_duckduckgo(self):
        """Test transforming query for DuckDuckGo engine.

        Validates §3.1.4: DuckDuckGo doesn't support date_after operator,
        which should be omitted from the transformed query.
        """
        from src.search.search_api import ParsedOperator, ParsedQuery, QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = ParsedQuery(
            base_query="AI研究",
            operators=[
                ParsedOperator("site", "arxiv.org", "site:arxiv.org"),
                ParsedOperator("date_after", "2024", "after:2024"),
            ],
        )

        result = processor.transform_for_engine(parsed, "duckduckgo")

        assert "AI研究" in result, f"Expected 'AI研究' in result, got '{result}'"
        assert "site:arxiv.org" in result, f"Expected 'site:arxiv.org' in result, got '{result}'"
        # DuckDuckGo doesn't support after:, so it should be omitted
        assert "after:2024" not in result, (
            f"'after:2024' should be omitted for DuckDuckGo, got '{result}'"
        )

    def test_transform_preserves_exact_phrases(self):
        """Test that exact phrases are preserved with quotes.

        Validates §3.1.4: exact phrase quotes must be preserved in transformation.
        """
        from src.search.search_api import ParsedOperator, ParsedQuery, QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = ParsedQuery(
            base_query="研究",
            operators=[
                ParsedOperator("exact", "人工知能", '"人工知能"'),
            ],
        )

        result = processor.transform_for_engine(parsed, "google")

        assert '"人工知能"' in result, f"Expected '\"人工知能\"' in result, got '{result}'"

    def test_process_query_end_to_end(self):
        """Test process_query convenience method.

        Validates end-to-end query processing: parse + transform in one call.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()

        result = processor.process_query(
            "AI site:go.jp filetype:pdf -spam",
            engine="google",
        )

        assert "AI" in result, f"Expected 'AI' in result, got '{result}'"
        assert "site:go.jp" in result, f"Expected 'site:go.jp' in result, got '{result}'"
        assert "filetype:pdf" in result, f"Expected 'filetype:pdf' in result, got '{result}'"
        assert "-spam" in result, f"Expected '-spam' in result, got '{result}'"

    def test_build_query_programmatic(self):
        """Test building queries programmatically.

        Validates §3.1.1: systematic query construction using build_query API.
        This is used for OSINT vertical templates (§3.1.3).
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()

        result = processor.build_query(
            base_query="AI規制",
            site="go.jp",
            filetype="pdf",
            exact_phrases=["ガイドライン"],
            exclude_terms=["draft"],
            engine="google",
        )

        assert "AI規制" in result, f"Expected 'AI規制' in result, got '{result}'"
        assert "site:go.jp" in result, f"Expected 'site:go.jp' in result, got '{result}'"
        assert "filetype:pdf" in result, f"Expected 'filetype:pdf' in result, got '{result}'"
        assert '"ガイドライン"' in result, f"Expected '\"ガイドライン\"' in result, got '{result}'"
        assert "-draft" in result, f"Expected '-draft' in result, got '{result}'"

    def test_build_query_multiple_exact_phrases(self):
        """Test building query with multiple exact phrases.

        Validates that multiple exact phrases are correctly quoted and included.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()

        result = processor.build_query(
            base_query="search",
            exact_phrases=["phrase one", "phrase two"],
            engine="default",
        )

        assert '"phrase one"' in result, f"Expected '\"phrase one\"' in result, got '{result}'"
        assert '"phrase two"' in result, f"Expected '\"phrase two\"' in result, got '{result}'"

    def test_get_supported_operators(self):
        """Test getting list of supported operators for engine.

        Validates §3.1.4: operator support varies by engine.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()

        google_ops = processor.get_supported_operators("google")

        # Google should support all common operators
        assert "site" in google_ops, f"Expected 'site' in google operators, got {google_ops}"
        assert "filetype" in google_ops, (
            f"Expected 'filetype' in google operators, got {google_ops}"
        )
        assert "intitle" in google_ops, f"Expected 'intitle' in google operators, got {google_ops}"
        assert "exact" in google_ops, f"Expected 'exact' in google operators, got {google_ops}"
        assert "exclude" in google_ops, f"Expected 'exclude' in google operators, got {google_ops}"
        assert "date_after" in google_ops, (
            f"Expected 'date_after' in google operators, got {google_ops}"
        )


@pytest.mark.unit
class TestQueryOperatorHelperFunctions:
    """Tests for module-level helper functions.

    Validates convenience functions for query operator processing.
    """

    def test_parse_query_operators_function(self):
        """Test parse_query_operators helper function.

        Validates the module-level parse_query_operators() function.
        """
        from src.search.search_api import parse_query_operators

        parsed = parse_query_operators("test site:example.com")

        assert parsed.base_query == "test", f"Expected base_query='test', got '{parsed.base_query}'"
        assert parsed.has_operator("site") is True, "Expected has_operator('site') to be True"

    def test_transform_query_for_engine_function(self):
        """Test transform_query_for_engine helper function.

        Validates the module-level transform_query_for_engine() function.
        """
        from src.search.search_api import transform_query_for_engine

        result = transform_query_for_engine("AI site:go.jp", "duckduckgo")

        assert "AI" in result, f"Expected 'AI' in result, got '{result}'"
        assert "site:go.jp" in result, f"Expected 'site:go.jp' in result, got '{result}'"

    def test_build_search_query_function(self):
        """Test build_search_query helper function.

        Validates §3.1.1/§3.1.3: programmatic query construction for OSINT templates.
        Example from §3.1.3: `site:go.jp 企業名`, `filetype:pdf 会社名 仕様`
        """
        from src.search.search_api import build_search_query

        # Build a query matching OSINT template pattern from §3.1.3
        result = build_search_query(
            base_query="企業名",
            site="go.jp",
            filetype="pdf",
        )

        assert "企業名" in result, f"Expected '企業名' in result, got '{result}'"
        assert "site:go.jp" in result, f"Expected 'site:go.jp' in result, got '{result}'"
        assert "filetype:pdf" in result, f"Expected 'filetype:pdf' in result, got '{result}'"

    def test_build_search_query_with_date_filter(self):
        """Test build_search_query with date filter.

        Validates §3.1.1: after: operator for time-based filtering.
        """
        from src.search.search_api import build_search_query

        result = build_search_query(
            base_query="最新ニュース",
            date_after="2024-01-01",
            engine="google",
        )

        assert "最新ニュース" in result, f"Expected '最新ニュース' in result, got '{result}'"
        assert "after:2024-01-01" in result, (
            f"Expected 'after:2024-01-01' in result, got '{result}'"
        )


@pytest.mark.unit
class TestQueryOperatorEdgeCases:
    """Edge case tests for query operator processing.

    Validates boundary conditions and unusual inputs per §7.1.2.
    """

    def test_empty_query(self):
        """Test handling of empty query.

        Boundary condition: empty string input should produce empty result.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("")

        assert parsed.base_query == "", f"Expected empty base_query, got '{parsed.base_query}'"
        assert len(parsed.operators) == 0, f"Expected 0 operators, got {len(parsed.operators)}"

    def test_only_operators_no_base(self):
        """Test query with only operators, no base text.

        Boundary condition: query consisting only of operators.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("site:example.com filetype:pdf")

        # Base query should be empty or minimal whitespace
        assert parsed.base_query.strip() == "", (
            f"Expected empty base_query, got '{parsed.base_query}'"
        )
        assert len(parsed.operators) == 2, f"Expected 2 operators, got {len(parsed.operators)}"

    def test_special_characters_in_domain(self):
        """Test handling of special characters in site domain.

        Validates parsing of complex domain names with subdomains and hyphens.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse("test site:sub.domain-name.co.jp")

        assert parsed.operators[0].value == "sub.domain-name.co.jp", (
            f"Expected value='sub.domain-name.co.jp', got '{parsed.operators[0].value}'"
        )

    def test_unicode_in_operators(self):
        """Test handling of Unicode characters in operators.

        Validates Japanese text in intitle: and exact phrase operators.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse('intitle:日本語タイトル "検索テスト"')

        intitle_op = next(op for op in parsed.operators if op.operator_type == "intitle")
        assert intitle_op.value == "日本語タイトル", (
            f"Expected intitle value='日本語タイトル', got '{intitle_op.value}'"
        )

        exact_op = next(op for op in parsed.operators if op.operator_type == "exact")
        assert exact_op.value == "検索テスト", (
            f"Expected exact value='検索テスト', got '{exact_op.value}'"
        )

    def test_multiple_exact_phrases(self):
        """Test parsing multiple exact phrases.

        Validates that multiple quoted phrases are correctly extracted.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()
        parsed = processor.parse('"phrase one" test "phrase two"')

        exact_ops = [op for op in parsed.operators if op.operator_type == "exact"]
        assert len(exact_ops) == 2, f"Expected 2 exact phrase operators, got {len(exact_ops)}"

        values = [op.value for op in exact_ops]
        assert "phrase one" in values, f"Expected 'phrase one' in values, got {values}"
        assert "phrase two" in values, f"Expected 'phrase two' in values, got {values}"

    def test_case_insensitive_operators(self):
        """Test that operators are case-insensitive.

        Validates that SITE:, Site:, and site: are all recognized as site operator.
        """
        from src.search.search_api import QueryOperatorProcessor

        processor = QueryOperatorProcessor()

        # Test various cases
        parsed1 = processor.parse("test SITE:example.com")
        parsed2 = processor.parse("test Site:example.com")
        parsed3 = processor.parse("test site:example.com")

        assert len(parsed1.operators) == 1, (
            f"Expected 1 operator for SITE:, got {len(parsed1.operators)}"
        )
        assert len(parsed2.operators) == 1, (
            f"Expected 1 operator for Site:, got {len(parsed2.operators)}"
        )
        assert len(parsed3.operators) == 1, (
            f"Expected 1 operator for site:, got {len(parsed3.operators)}"
        )

        assert parsed1.operators[0].operator_type == "site", (
            f"Expected 'site' for SITE:, got '{parsed1.operators[0].operator_type}'"
        )
        assert parsed2.operators[0].operator_type == "site", (
            f"Expected 'site' for Site:, got '{parsed2.operators[0].operator_type}'"
        )
        assert parsed3.operators[0].operator_type == "site", (
            f"Expected 'site' for site:, got '{parsed3.operators[0].operator_type}'"
        )


class TestMirrorQueryGeneration:
    """Tests for cross-language mirror query generation (§3.1.1)."""

    @pytest.fixture
    def mock_ollama_client(self):
        """Create a mock Ollama client for translation tests."""

        class MockOllamaClient:
            async def generate(self, prompt, model=None, temperature=None, max_tokens=None):
                # Extract query from prompt and return translation
                if "機械学習" in prompt:
                    return "machine learning"
                elif "machine learning" in prompt:
                    return "機械学習"
                elif "セキュリティ" in prompt:
                    return "security"
                elif "AIエージェント" in prompt:
                    return "AI agent"
                return "translated query"

        return MockOllamaClient()

    @pytest.mark.asyncio
    async def test_generate_mirror_query_ja_to_en(self, mock_ollama_client):
        """Test Japanese to English translation (§3.1.1)."""
        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        # Clear cache
        _mirror_query_cache.clear()

        with patch("src.filter.llm._get_client", return_value=mock_ollama_client):
            result = await generate_mirror_query(
                "機械学習の最新動向", source_lang="ja", target_lang="en"
            )

        assert result is not None, "Translation should succeed"
        assert result != "機械学習の最新動向", "Result should be different from original"

    @pytest.mark.asyncio
    async def test_generate_mirror_query_en_to_ja(self, mock_ollama_client):
        """Test English to Japanese translation (§3.1.1)."""
        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        _mirror_query_cache.clear()

        with patch("src.filter.llm._get_client", return_value=mock_ollama_client):
            result = await generate_mirror_query(
                "machine learning trends", source_lang="en", target_lang="ja"
            )

        assert result is not None, "Translation should succeed"
        assert result != "machine learning trends", "Result should be different from original"

    @pytest.mark.asyncio
    async def test_generate_mirror_query_same_language(self):
        """Test that same-language returns original query."""
        from src.search.search_api import generate_mirror_query

        result = await generate_mirror_query("test query", source_lang="en", target_lang="en")

        assert result == "test query", "Same language should return original"

    @pytest.mark.asyncio
    async def test_generate_mirror_query_empty_input(self):
        """Test handling of empty input."""
        from src.search.search_api import generate_mirror_query

        result = await generate_mirror_query("", source_lang="ja", target_lang="en")
        assert result is None, "Empty input should return None"

        result = await generate_mirror_query("   ", source_lang="ja", target_lang="en")
        assert result is None, "Whitespace-only input should return None"

    @pytest.mark.asyncio
    async def test_generate_mirror_query_caching(self):
        """Test that translations are cached."""
        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        _mirror_query_cache.clear()

        call_count = 0

        class CountingMockClient:
            async def generate(self, prompt, model=None, temperature=None, max_tokens=None):
                nonlocal call_count
                call_count += 1
                return "security"

        with patch("src.filter.llm._get_client", return_value=CountingMockClient()):
            # First call
            result1 = await generate_mirror_query("セキュリティ", "ja", "en")
            # Second call (should use cache)
            result2 = await generate_mirror_query("セキュリティ", "ja", "en")

        assert result1 == result2, "Cached result should match"
        assert call_count == 1, f"LLM should only be called once, was called {call_count} times"

    @pytest.mark.asyncio
    async def test_generate_mirror_queries_multiple_languages(self, mock_ollama_client):
        """Test generating mirrors in multiple target languages."""
        from src.search.search_api import _mirror_query_cache, generate_mirror_queries

        _mirror_query_cache.clear()

        with patch("src.filter.llm._get_client", return_value=mock_ollama_client):
            results = await generate_mirror_queries(
                "AIエージェント", source_lang="ja", target_langs=["en"]
            )

        assert "ja" in results, "Source language should be in results"
        assert results["ja"] == "AIエージェント", "Original query should be preserved"
        # en result depends on mock response
        assert len(results) >= 1, "Should have at least source language"

    @pytest.mark.asyncio
    async def test_generate_mirror_query_error_handling(self):
        """Test graceful handling of LLM errors."""
        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        _mirror_query_cache.clear()

        class FailingMockClient:
            async def generate(self, *args, **kwargs):
                raise RuntimeError("LLM unavailable")

        with patch("src.filter.llm._get_client", return_value=FailingMockClient()):
            result = await generate_mirror_query("test", "ja", "en")

        assert result is None, "Error should return None, not raise"

    @pytest.mark.asyncio
    async def test_generate_mirror_query_cleans_response(self):
        """Test that quoted responses are cleaned."""
        from src.search.search_api import _mirror_query_cache, generate_mirror_query

        _mirror_query_cache.clear()

        class QuotedMockClient:
            async def generate(self, *args, **kwargs):
                return '"quoted translation"'

        with patch("src.filter.llm._get_client", return_value=QuotedMockClient()):
            result = await generate_mirror_query("test", "ja", "en")

        assert result == "quoted translation", "Quotes should be stripped"

        assert result == "quoted translation", "Quotes should be stripped"
