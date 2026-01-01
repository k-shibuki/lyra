"""
Tests for pagination strategy.

See ADR-0010 and ADR-0014 for pagination design.
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

from src.search.pagination_strategy import (
    PaginationConfig,
    PaginationContext,
    PaginationStrategy,
)


class TestPaginationStrategy:
    """Tests for PaginationStrategy."""

    def test_should_fetch_next_fixed_strategy(self) -> None:
        """Test fixed strategy: always fetch up to max_pages."""
        # Given: Fixed strategy with max_pages=5
        config = PaginationConfig(serp_max_pages=5, strategy="fixed")
        strategy = PaginationStrategy(config)

        # When: Current page is 3
        context = PaginationContext(current_page=3)

        # Then: Should fetch next
        assert strategy.should_fetch_next(context) is True

        # When: Current page reaches max_pages
        context = PaginationContext(current_page=5)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

    def test_should_fetch_next_auto_strategy_novelty_rate(self) -> None:
        """Test auto strategy: stop when novelty_rate < min_novelty_rate."""
        # Given: Auto strategy with min_novelty_rate=0.1
        config = PaginationConfig(serp_max_pages=10, min_novelty_rate=0.1, strategy="auto")
        strategy = PaginationStrategy(config)

        # When: Novelty rate is above threshold
        context = PaginationContext(current_page=2, novelty_rate=0.2)

        # Then: Should fetch next
        assert strategy.should_fetch_next(context) is True

        # When: Novelty rate is below threshold
        context = PaginationContext(current_page=3, novelty_rate=0.05)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

    def test_should_fetch_next_auto_strategy_harvest_rate(self) -> None:
        """Test auto strategy: stop when harvest_rate < min_harvest_rate."""
        # Given: Auto strategy with min_harvest_rate=0.05
        config = PaginationConfig(serp_max_pages=10, min_harvest_rate=0.05, strategy="auto")
        strategy = PaginationStrategy(config)

        # When: Harvest rate is above threshold
        context = PaginationContext(current_page=2, harvest_rate=0.1)

        # Then: Should fetch next
        assert strategy.should_fetch_next(context) is True

        # When: Harvest rate is below threshold
        context = PaginationContext(current_page=3, harvest_rate=0.03)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

    def test_should_fetch_next_auto_strategy_both_conditions(self) -> None:
        """Test auto strategy: both novelty_rate and harvest_rate checked."""
        # Given: Auto strategy
        config = PaginationConfig(
            serp_max_pages=10,
            min_novelty_rate=0.1,
            min_harvest_rate=0.05,
            strategy="auto",
        )
        strategy = PaginationStrategy(config)

        # When: Both rates are above threshold
        context = PaginationContext(current_page=2, novelty_rate=0.2, harvest_rate=0.1)

        # Then: Should fetch next
        assert strategy.should_fetch_next(context) is True

        # When: Novelty rate is below threshold (harvest rate OK)
        context = PaginationContext(current_page=3, novelty_rate=0.05, harvest_rate=0.1)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

        # When: Harvest rate is below threshold (novelty rate OK)
        context = PaginationContext(current_page=4, novelty_rate=0.2, harvest_rate=0.03)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

    def test_should_fetch_next_max_pages_boundary(self) -> None:
        """Test boundary: max_pages limit."""
        # Given: Strategy with max_pages=10
        config = PaginationConfig(serp_max_pages=10)
        strategy = PaginationStrategy(config)

        # When: Current page is max_pages
        context = PaginationContext(current_page=10)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

        # When: Current page exceeds max_pages
        context = PaginationContext(current_page=11)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

    def test_should_fetch_next_none_rates(self) -> None:
        """Test auto strategy: None rates should not stop pagination."""
        # Given: Auto strategy
        config = PaginationConfig(serp_max_pages=10, strategy="auto")
        strategy = PaginationStrategy(config)

        # When: Rates are None
        context = PaginationContext(current_page=2, novelty_rate=None, harvest_rate=None)

        # Then: Should fetch next (no rate information means continue)
        assert strategy.should_fetch_next(context) is True

    def test_calculate_novelty_rate_empty_new_urls(self) -> None:
        """Test novelty rate calculation: empty new_urls."""
        # Given: Strategy instance
        strategy = PaginationStrategy()

        # When: new_urls is empty
        novelty_rate = strategy.calculate_novelty_rate([], set())

        # Then: Should return 0.0
        assert novelty_rate == 0.0

    def test_calculate_novelty_rate_no_seen_urls(self) -> None:
        """Test novelty rate calculation: no seen URLs."""
        # Given: Strategy instance
        strategy = PaginationStrategy()

        # When: No URLs seen before
        new_urls = ["https://example.com/1", "https://example.com/2"]
        novelty_rate = strategy.calculate_novelty_rate(new_urls, set())

        # Then: Should return 1.0 (all new)
        assert novelty_rate == 1.0

    def test_calculate_novelty_rate_all_seen(self) -> None:
        """Test novelty rate calculation: all URLs seen."""
        # Given: Strategy instance
        strategy = PaginationStrategy()

        # When: All URLs already seen
        new_urls = ["https://example.com/1", "https://example.com/2"]
        seen_urls = {"https://example.com/1", "https://example.com/2"}
        novelty_rate = strategy.calculate_novelty_rate(new_urls, seen_urls)

        # Then: Should return 0.0 (no new URLs)
        assert novelty_rate == 0.0

    def test_calculate_novelty_rate_partial_seen(self) -> None:
        """Test novelty rate calculation: partial URLs seen."""
        # Given: Strategy instance
        strategy = PaginationStrategy()

        # When: Some URLs already seen
        new_urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]
        seen_urls = {"https://example.com/1"}
        novelty_rate = strategy.calculate_novelty_rate(new_urls, seen_urls)

        # Then: Should return 2/3 = 0.666...
        assert abs(novelty_rate - 2.0 / 3.0) < 0.001

    def test_should_fetch_next_exhaustive_strategy(self) -> None:
        """Test exhaustive strategy: fetch all pages up to max_pages."""
        # Given: Exhaustive strategy with max_pages=10
        config = PaginationConfig(serp_max_pages=10, strategy="exhaustive")
        strategy = PaginationStrategy(config)

        # When: Current page is 5
        context = PaginationContext(current_page=5)

        # Then: Should fetch next
        assert strategy.should_fetch_next(context) is True

        # When: Current page reaches max_pages
        context = PaginationContext(current_page=10)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

    def test_should_fetch_next_boundary_novelty_rate_threshold(self) -> None:
        """Test boundary: novelty_rate exactly at threshold."""
        # Given: Auto strategy with min_novelty_rate=0.1
        config = PaginationConfig(serp_max_pages=10, min_novelty_rate=0.1, strategy="auto")
        strategy = PaginationStrategy(config)

        # When: Novelty rate exactly at threshold
        context = PaginationContext(current_page=2, novelty_rate=0.1)

        # Then: Should fetch next (threshold uses <, so 0.1 is not < 0.1)
        assert strategy.should_fetch_next(context) is True

        # When: Novelty rate just below threshold
        context = PaginationContext(current_page=2, novelty_rate=0.0999)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

    def test_should_fetch_next_boundary_harvest_rate_threshold(self) -> None:
        """Test boundary: harvest_rate exactly at threshold."""
        # Given: Auto strategy with min_harvest_rate=0.05
        config = PaginationConfig(serp_max_pages=10, min_harvest_rate=0.05, strategy="auto")
        strategy = PaginationStrategy(config)

        # When: Harvest rate exactly at threshold
        context = PaginationContext(current_page=2, harvest_rate=0.05)

        # Then: Should fetch next (threshold uses <, so 0.05 is not < 0.05)
        assert strategy.should_fetch_next(context) is True

        # When: Harvest rate just below threshold
        context = PaginationContext(current_page=2, harvest_rate=0.0499)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

    def test_should_fetch_next_boundary_zero_novelty_rate(self) -> None:
        """Test boundary: novelty_rate = 0.0."""
        # Given: Auto strategy
        config = PaginationConfig(serp_max_pages=10, min_novelty_rate=0.1, strategy="auto")
        strategy = PaginationStrategy(config)

        # When: Novelty rate is zero
        context = PaginationContext(current_page=2, novelty_rate=0.0)

        # Then: Should not fetch next
        assert strategy.should_fetch_next(context) is False

    def test_should_fetch_next_boundary_max_novelty_rate(self) -> None:
        """Test boundary: novelty_rate = 1.0."""
        # Given: Auto strategy
        config = PaginationConfig(serp_max_pages=10, min_novelty_rate=0.1, strategy="auto")
        strategy = PaginationStrategy(config)

        # When: Novelty rate is maximum
        context = PaginationContext(current_page=2, novelty_rate=1.0)

        # Then: Should fetch next
        assert strategy.should_fetch_next(context) is True

    def test_should_fetch_next_boundary_page_one(self) -> None:
        """Test boundary: current_page = 1."""
        # Given: Strategy with max_pages=10
        config = PaginationConfig(serp_max_pages=10)
        strategy = PaginationStrategy(config)

        # When: Current page is 1
        context = PaginationContext(current_page=1)

        # Then: Should fetch next
        assert strategy.should_fetch_next(context) is True


class TestPaginationWiringEffect:
    """Wiring/Effect tests for pagination parameters."""

    def test_cache_key_includes_serp_max_pages(self) -> None:
        """TC-E-02: Effect test - cache key differs for different serp_max_pages.

        // Given: Same query with different serp_max_pages
        // When: Generating cache keys
        // Then: Cache keys differ
        """
        # Given: Cache key generator
        from src.search.search_api import _get_cache_key

        # When: Generate cache keys for different serp_max_pages
        key1 = _get_cache_key("test query", None, "all", serp_max_pages=1)
        key2 = _get_cache_key("test query", None, "all", serp_max_pages=3)
        key3 = _get_cache_key("test query", None, "all", serp_max_pages=1)

        # Then: Different serp_max_pages produce different keys
        assert key1 != key2, "Different serp_max_pages should produce different cache keys"

        # And: Same serp_max_pages produce same key
        assert key1 == key3, "Same serp_max_pages should produce same cache key"

    def test_pagination_config_wiring(self) -> None:
        """TC-W-04: Wiring test - PaginationConfig receives serp_max_pages.

        // Given: serp_max_pages=5
        // When: Creating PaginationConfig
        // Then: Config stores the value
        """
        # Given/When: Create config with custom serp_max_pages
        config = PaginationConfig(serp_max_pages=5)

        # Then: Value is stored
        assert config.serp_max_pages == 5

    def test_pagination_config_default(self) -> None:
        """Test default PaginationConfig values.

        // Given: No parameters
        // When: Creating PaginationConfig
        // Then: Defaults are applied
        """
        # Given/When: Default config
        config = PaginationConfig()

        # Then: Defaults applied
        assert config.serp_max_pages == 10
        assert config.min_novelty_rate == 0.1
        assert config.min_harvest_rate == 0.05
        assert config.strategy == "auto"

    def test_search_options_serp_params_propagation(self) -> None:
        """TC-E-03b: Effect test - SearchProviderOptions propagates serp parameters.

        // Given: SearchProviderOptions with custom serp_page and serp_max_pages
        // When: Accessing options
        // Then: Values are accessible
        """
        # Given: Import SearchProviderOptions
        from src.search.provider import SearchProviderOptions

        # When: Create options with pagination params
        options = SearchProviderOptions(serp_page=2, serp_max_pages=5)

        # Then: Values are stored and accessible
        assert options.serp_page == 2
        assert options.serp_max_pages == 5

        # And: Can be used in calculations
        max_page = options.serp_page + options.serp_max_pages - 1
        assert max_page == 6  # 2 + 5 - 1 = 6


class TestHarvestRatePropagation:
    """Wiring/Effect tests for harvest_rate propagation."""

    def test_harvest_rate_passed_to_pagination_context(self) -> None:
        """TC-W-04: Wiring test - harvest_rate passed to PaginationContext.

        // Given: harvest_rate = 0.8
        // When: Creating PaginationContext
        // Then: context.harvest_rate == 0.8
        """
        # Given/When: Create PaginationContext with harvest_rate
        context = PaginationContext(
            current_page=2,
            novelty_rate=0.5,
            harvest_rate=0.8,
        )

        # Then: harvest_rate is stored
        assert context.harvest_rate == 0.8

    def test_harvest_rate_none_allowed(self) -> None:
        """TC-W-05: Wiring test - harvest_rate=None is allowed.

        // Given: harvest_rate = None
        // When: Creating PaginationContext
        // Then: context.harvest_rate is None
        """
        # Given/When: Create PaginationContext with None harvest_rate
        context = PaginationContext(
            current_page=2,
            novelty_rate=0.5,
            harvest_rate=None,
        )

        # Then: harvest_rate is None
        assert context.harvest_rate is None

    def test_harvest_rate_effect_on_should_fetch_next(self) -> None:
        """TC-E-04: Effect test - harvest_rate affects should_fetch_next decision.

        // Given: Auto strategy with min_harvest_rate=0.05
        // When: harvest_rate is above/below threshold
        // Then: Decision changes based on harvest_rate
        """
        # Given: Auto strategy with min_harvest_rate=0.05
        config = PaginationConfig(
            serp_max_pages=10,
            min_harvest_rate=0.05,
            strategy="auto",
        )
        strategy = PaginationStrategy(config)

        # When: harvest_rate above threshold (0.1 > 0.05)
        context_above = PaginationContext(
            current_page=2,
            novelty_rate=0.5,
            harvest_rate=0.1,
        )
        result_above = strategy.should_fetch_next(context_above)

        # Then: Should continue
        assert result_above is True

        # When: harvest_rate below threshold (0.03 < 0.05)
        context_below = PaginationContext(
            current_page=2,
            novelty_rate=0.5,
            harvest_rate=0.03,
        )
        result_below = strategy.should_fetch_next(context_below)

        # Then: Should stop
        assert result_below is False

    def test_harvest_rate_boundary_at_threshold(self) -> None:
        """TC-B-05: Boundary test - harvest_rate exactly at threshold.

        // Given: min_harvest_rate=0.05
        // When: harvest_rate = 0.05 (exactly at threshold)
        // Then: Should continue (threshold uses <, not <=)
        """
        # Given: Strategy with min_harvest_rate=0.05
        config = PaginationConfig(
            serp_max_pages=10,
            min_harvest_rate=0.05,
            strategy="auto",
        )
        strategy = PaginationStrategy(config)

        # When: harvest_rate exactly at threshold
        context = PaginationContext(
            current_page=2,
            novelty_rate=0.5,
            harvest_rate=0.05,
        )
        result = strategy.should_fetch_next(context)

        # Then: Should continue (0.05 is not < 0.05)
        assert result is True

    def test_harvest_rate_boundary_zero(self) -> None:
        """TC-B-06: Boundary test - harvest_rate = 0.0.

        // Given: min_harvest_rate=0.05
        // When: harvest_rate = 0.0
        // Then: Should stop (0.0 < 0.05)
        """
        # Given: Strategy with min_harvest_rate=0.05
        config = PaginationConfig(
            serp_max_pages=10,
            min_harvest_rate=0.05,
            strategy="auto",
        )
        strategy = PaginationStrategy(config)

        # When: harvest_rate = 0.0
        context = PaginationContext(
            current_page=2,
            novelty_rate=0.5,
            harvest_rate=0.0,
        )
        result = strategy.should_fetch_next(context)

        # Then: Should stop
        assert result is False

    def test_harvest_rate_none_does_not_stop(self) -> None:
        """TC-N-05: Negative test - None harvest_rate does not cause stop.

        // Given: Auto strategy
        // When: harvest_rate = None
        // Then: Should continue (None means no data, not failure)
        """
        # Given: Auto strategy
        config = PaginationConfig(
            serp_max_pages=10,
            min_harvest_rate=0.05,
            strategy="auto",
        )
        strategy = PaginationStrategy(config)

        # When: harvest_rate = None
        context = PaginationContext(
            current_page=2,
            novelty_rate=0.5,
            harvest_rate=None,
        )
        result = strategy.should_fetch_next(context)

        # Then: Should continue
        assert result is True


class TestParsedResultToSearchResult:
    """Wiring tests for ParsedResult.to_search_result() with serp_page parameter."""

    def test_serp_page_default_is_one(self) -> None:
        """TC-W-06: Wiring test - serp_page default is 1.

        // Given: ParsedResult
        // When: Calling to_search_result without serp_page
        // Then: page_number is 1
        """
        from src.search.search_parsers import ParsedResult

        # Given: ParsedResult
        parsed = ParsedResult(
            title="Test",
            url="https://example.com",
            snippet="Test snippet",
            rank=1,
        )

        # When: Calling to_search_result without serp_page
        result = parsed.to_search_result("test_engine")

        # Then: page_number is 1
        assert result.page_number == 1

    def test_serp_page_custom_value(self) -> None:
        """TC-W-07: Wiring test - serp_page custom value is propagated.

        // Given: ParsedResult
        // When: Calling to_search_result with serp_page=3
        // Then: page_number is 3
        """
        from src.search.search_parsers import ParsedResult

        # Given: ParsedResult
        parsed = ParsedResult(
            title="Test",
            url="https://example.com",
            snippet="Test snippet",
            rank=1,
        )

        # When: Calling to_search_result with serp_page=3
        result = parsed.to_search_result("test_engine", serp_page=3)

        # Then: page_number is 3
        assert result.page_number == 3

    def test_serp_page_boundary_values(self) -> None:
        """TC-B-07: Boundary test - serp_page boundary values.

        // Given: ParsedResult
        // When: Calling to_search_result with serp_page=1 and serp_page=10
        // Then: page_number matches serp_page
        """
        from src.search.search_parsers import ParsedResult

        # Given: ParsedResult
        parsed = ParsedResult(
            title="Test",
            url="https://example.com",
            snippet="Test snippet",
            rank=1,
        )

        # When/Then: serp_page=1 (minimum)
        result_min = parsed.to_search_result("test_engine", serp_page=1)
        assert result_min.page_number == 1

        # When/Then: serp_page=10 (expected maximum)
        result_max = parsed.to_search_result("test_engine", serp_page=10)
        assert result_max.page_number == 10
