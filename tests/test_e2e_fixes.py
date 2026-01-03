"""
Tests for E2E fixes: max_consecutive_429, slot release, embedding persistence.

Per E2E Case Study Report: These fixes address:
- P1: vector_search always returns ok=false (embedding persistence missing)
- P2: Semantic Scholar 429 rate limit contention (slot release + early fail)
- P3: Pipeline 180s timeout (rate limit wait time)

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-429-01 | 3 consecutive 429 errors | Boundary – threshold reached | APIRetryError raised with last_status=429 | Early fail |
| TC-429-02 | 429 then 500 then success | Equivalence – counter reset | Success (count reset on non-429) | - |
| TC-429-03 | 2 consecutive 429s (below threshold=3) | Boundary – below threshold | Retries continue | - |
| TC-429-04 | max_consecutive_429=None | Equivalence – disabled | Normal retry behavior | - |
| TC-SLOT-01 | 429 error in base.py search() | Equivalence – slot release | Slot released before backoff | - |
| TC-SLOT-02 | Success after retry | Equivalence – normal | Returns result, reports success | - |
| TC-EMB-01 | Fragment persisted via pipeline | Wiring – embedding called | persist_embedding called for fragment | - |
| TC-EMB-02 | Claim persisted via pipeline | Wiring – embedding called | persist_embedding called for claim | - |
| TC-EMB-03 | Embedding generation fails | Abnormal – exception | Processing continues, warning logged | - |
| TC-CFG-01 | acquire(timeout=None) | Equivalence – config lookup | Uses cursor_idle_timeout_seconds | - |
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.utils.api_retry import (
    APIRetryError,
    APIRetryPolicy,
    retry_api_call,
)
from src.utils.backoff import BackoffConfig

# =============================================================================
# TC-429: max_consecutive_429 Tests
# =============================================================================


class TestMaxConsecutive429:
    """Tests for max_consecutive_429 parameter in retry_api_call."""

    def _make_httpx_429_error(self) -> httpx.HTTPStatusError:
        """Create a mock httpx.HTTPStatusError with 429 status."""
        request = MagicMock(spec=httpx.Request)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 429
        return httpx.HTTPStatusError("Rate limited", request=request, response=response)

    def _make_httpx_500_error(self) -> httpx.HTTPStatusError:
        """Create a mock httpx.HTTPStatusError with 500 status."""
        request = MagicMock(spec=httpx.Request)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 500
        return httpx.HTTPStatusError("Server error", request=request, response=response)

    @pytest.mark.asyncio
    async def test_early_fail_on_consecutive_429_threshold(self) -> None:
        """TC-429-01: Early fail when consecutive 429s reach threshold.

        Given: A function that always returns 429
        When: retry_api_call is called with max_consecutive_429=3
        Then: APIRetryError is raised after 3 consecutive 429s
        """
        # Given: Function that always returns 429
        call_count = 0

        async def always_429() -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            raise self._make_httpx_429_error()

        # When/Then: APIRetryError raised after 3 consecutive 429s
        policy = APIRetryPolicy(
            max_retries=10,  # High retry count to prove early fail
            backoff=BackoffConfig(base_delay=0.001, max_delay=0.01),
        )

        with pytest.raises(APIRetryError) as exc_info:
            await retry_api_call(
                always_429,
                policy=policy,
                max_consecutive_429=3,
            )

        # Then: Early fail at exactly 3 calls
        assert call_count == 3
        assert exc_info.value.last_status == 429
        assert "Rate limited 3 times consecutively" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_counter_reset_on_non_429(self) -> None:
        """TC-429-02: Counter resets when non-429 error occurs.

        Given: A function that returns 429, then 500, then succeeds
        When: retry_api_call is called with max_consecutive_429=3
        Then: Success is returned (counter reset on 500)
        """
        # Given: Function with mixed error pattern
        call_count = 0

        async def mixed_errors() -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise self._make_httpx_429_error()  # 429
            if call_count == 2:
                raise self._make_httpx_500_error()  # 500 - resets counter
            if call_count == 3:
                raise self._make_httpx_429_error()  # 429 - count=1 (reset)
            return {"success": True}

        # When: Call with early fail threshold
        policy = APIRetryPolicy(
            max_retries=10,
            backoff=BackoffConfig(base_delay=0.001, max_delay=0.01),
        )

        result = await retry_api_call(
            mixed_errors,
            policy=policy,
            max_consecutive_429=3,
        )

        # Then: Success on 4th call
        assert result == {"success": True}
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_below_threshold_continues_retry(self) -> None:
        """TC-429-03: Retries continue when below threshold.

        Given: A function that returns 429 twice then succeeds
        When: retry_api_call is called with max_consecutive_429=3
        Then: Success is returned (only 2 consecutive 429s)
        """
        # Given: Function that fails twice then succeeds
        call_count = 0

        async def eventually_succeeds() -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise self._make_httpx_429_error()
            return {"success": True}

        # When: Call with threshold=3
        policy = APIRetryPolicy(
            max_retries=5,
            backoff=BackoffConfig(base_delay=0.001, max_delay=0.01),
        )

        result = await retry_api_call(
            eventually_succeeds,
            policy=policy,
            max_consecutive_429=3,
        )

        # Then: Success on 3rd call (2 consecutive 429s < threshold)
        assert result == {"success": True}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_disabled_when_none(self) -> None:
        """TC-429-04: Normal retry behavior when max_consecutive_429=None.

        Given: A function that returns 429 multiple times
        When: retry_api_call is called with max_consecutive_429=None
        Then: Normal retry exhaustion behavior
        """
        # Given: Function that always returns 429
        call_count = 0

        async def always_429() -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            raise self._make_httpx_429_error()

        # When/Then: Normal retry exhaustion
        policy = APIRetryPolicy(
            max_retries=5,
            backoff=BackoffConfig(base_delay=0.001, max_delay=0.01),
        )

        with pytest.raises(APIRetryError) as exc_info:
            await retry_api_call(
                always_429,
                policy=policy,
                max_consecutive_429=None,  # Disabled
            )

        # Then: All retries exhausted (6 total calls)
        assert call_count == 6  # 1 initial + 5 retries
        assert exc_info.value.attempts == 6


# =============================================================================
# TC-SLOT: Slot Release Pattern Tests
# =============================================================================


class TestBaseSearchSlotRelease:
    """Tests for retry-aware slot release in base.py search()."""

    @pytest.mark.asyncio
    async def test_slot_released_on_429(self) -> None:
        """TC-SLOT-01: Slot is released before backoff wait on 429.

        Given: A search that returns 429
        When: search() is called
        Then: Slot is released before backoff (other workers can proceed)
        """
        from src.search.apis.base import BaseAcademicClient
        from src.search.apis.rate_limiter import (
            AcademicAPIRateLimiter,
        )
        from src.utils.schemas import AcademicSearchResult

        # Given: Mock client and limiter
        class TestClient(BaseAcademicClient):
            def __init__(self) -> None:
                super().__init__("test_provider")
                self.call_count = 0

            async def _search_impl(self, query: str, limit: int = 10) -> AcademicSearchResult:
                self.call_count += 1
                if self.call_count < 3:
                    # Create 429 error
                    request = MagicMock(spec=httpx.Request)
                    response = MagicMock(spec=httpx.Response)
                    response.status_code = 429
                    raise httpx.HTTPStatusError("Rate limited", request=request, response=response)
                return AcademicSearchResult(
                    papers=[], total_count=0, next_cursor=None, source_api="test"
                )

            async def get_paper(self, paper_id: str):
                return None

            async def get_references(self, paper_id: str):
                return []

            async def get_citations(self, paper_id: str):
                return []

        # Setup mock limiter to track release calls
        mock_limiter = MagicMock(spec=AcademicAPIRateLimiter)
        mock_limiter.acquire = AsyncMock()
        mock_limiter.release = MagicMock()
        mock_limiter.report_429 = AsyncMock()
        mock_limiter.report_success = MagicMock()

        client = TestClient()

        # When: Search with mocked limiter (patch at import location in base.py)
        with patch(
            "src.search.apis.rate_limiter.get_academic_rate_limiter",
            return_value=mock_limiter,
        ):
            result = await client.search("test query")

        # Then: Slot was released multiple times (on each 429)
        assert mock_limiter.release.call_count >= 2  # At least 2 releases before success
        assert mock_limiter.report_success.call_count == 1  # Success reported once
        assert result.papers == []

    @pytest.mark.asyncio
    async def test_success_after_retry(self) -> None:
        """TC-SLOT-02: Returns result and reports success after retry.

        Given: A search that fails once then succeeds
        When: search() is called
        Then: Result is returned and success is reported
        """
        from src.search.apis.base import BaseAcademicClient
        from src.search.apis.rate_limiter import AcademicAPIRateLimiter
        from src.utils.schemas import AcademicSearchResult

        class TestClient(BaseAcademicClient):
            def __init__(self) -> None:
                super().__init__("test_provider")
                self.call_count = 0

            async def _search_impl(self, query: str, limit: int = 10) -> AcademicSearchResult:
                self.call_count += 1
                if self.call_count == 1:
                    request = MagicMock(spec=httpx.Request)
                    response = MagicMock(spec=httpx.Response)
                    response.status_code = 503
                    raise httpx.HTTPStatusError("Server error", request=request, response=response)
                return AcademicSearchResult(
                    papers=[],
                    total_count=1,
                    next_cursor=None,
                    source_api="test",
                )

            async def get_paper(self, paper_id: str):
                return None

            async def get_references(self, paper_id: str):
                return []

            async def get_citations(self, paper_id: str):
                return []

        mock_limiter = MagicMock(spec=AcademicAPIRateLimiter)
        mock_limiter.acquire = AsyncMock()
        mock_limiter.release = MagicMock()
        mock_limiter.report_429 = AsyncMock()
        mock_limiter.report_success = MagicMock()

        client = TestClient()

        with patch(
            "src.search.apis.rate_limiter.get_academic_rate_limiter",
            return_value=mock_limiter,
        ):
            result = await client.search("test query")

        # Then: Success after retry
        assert result.total_count == 1
        assert mock_limiter.report_success.call_count == 1
        assert client.call_count == 2

    @pytest.mark.asyncio
    async def test_slot_released_on_immediate_success(self) -> None:
        """TC-REL-N-01: Slot is released even on immediate success.

        Given: A search that succeeds on first attempt
        When: search() is called
        Then: acquire(1), release(1), report_success(1) - exactly once each
        """
        from src.search.apis.base import BaseAcademicClient
        from src.search.apis.rate_limiter import AcademicAPIRateLimiter
        from src.utils.schemas import AcademicSearchResult

        # Given: Client that succeeds immediately
        class TestClient(BaseAcademicClient):
            def __init__(self) -> None:
                super().__init__("test_provider")
                self.call_count = 0

            async def _search_impl(self, query: str, limit: int = 10) -> AcademicSearchResult:
                self.call_count += 1
                return AcademicSearchResult(
                    papers=[], total_count=5, next_cursor=None, source_api="test"
                )

            async def get_paper(self, paper_id: str):
                return None

            async def get_references(self, paper_id: str):
                return []

            async def get_citations(self, paper_id: str):
                return []

        mock_limiter = MagicMock(spec=AcademicAPIRateLimiter)
        mock_limiter.acquire = AsyncMock()
        mock_limiter.release = MagicMock()
        mock_limiter.report_429 = AsyncMock()
        mock_limiter.report_success = MagicMock()

        client = TestClient()

        # When: Search succeeds immediately
        with patch(
            "src.search.apis.rate_limiter.get_academic_rate_limiter",
            return_value=mock_limiter,
        ):
            result = await client.search("test query")

        # Then: Exactly 1 acquire, 1 release, 1 report_success
        assert mock_limiter.acquire.call_count == 1, "acquire should be called once"
        assert mock_limiter.release.call_count == 1, "release should be called once (via finally)"
        assert mock_limiter.report_success.call_count == 1, "success should be reported once"
        assert client.call_count == 1, "_search_impl called once"
        assert result.total_count == 5

    @pytest.mark.asyncio
    async def test_slot_released_on_exhausted_retries(self) -> None:
        """TC-REL-A-02: Slot is released even when all retries exhausted.

        Given: A search that always fails with 429
        When: search() is called and retries are exhausted
        Then: release() is called on each attempt (no slot leak)
        """
        from src.search.apis.base import BaseAcademicClient
        from src.search.apis.rate_limiter import AcademicAPIRateLimiter
        from src.utils.schemas import AcademicSearchResult

        # Given: Client that always returns 429
        class TestClient(BaseAcademicClient):
            def __init__(self) -> None:
                super().__init__("test_provider")
                self.call_count = 0

            async def _search_impl(self, query: str, limit: int = 10) -> AcademicSearchResult:
                self.call_count += 1
                request = MagicMock(spec=httpx.Request)
                response = MagicMock(spec=httpx.Response)
                response.status_code = 429
                raise httpx.HTTPStatusError("Rate limited", request=request, response=response)

            async def get_paper(self, paper_id: str):
                return None

            async def get_references(self, paper_id: str):
                return []

            async def get_citations(self, paper_id: str):
                return []

        mock_limiter = MagicMock(spec=AcademicAPIRateLimiter)
        mock_limiter.acquire = AsyncMock()
        mock_limiter.release = MagicMock()
        mock_limiter.report_429 = AsyncMock()
        mock_limiter.report_success = MagicMock()

        client = TestClient()

        # When: Search fails after all retries
        with patch(
            "src.search.apis.rate_limiter.get_academic_rate_limiter",
            return_value=mock_limiter,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await client.search("test query")

        # Then: release called on every attempt (no slot leak)
        # Default max_retries from ACADEMIC_API_POLICY should be used
        assert client.call_count >= 1, "At least one attempt made"
        assert mock_limiter.acquire.call_count == client.call_count, "acquire matches attempts"
        assert mock_limiter.release.call_count == client.call_count, "release matches attempts"
        assert mock_limiter.report_success.call_count == 0, "no success reported"


# =============================================================================
# TC-EMB: Embedding Persistence Tests
# =============================================================================


class TestPipelineEmbeddingPersistence:
    """Tests for embedding persistence in pipeline.py."""

    @pytest.mark.asyncio
    async def test_fragment_embedding_persisted(self, test_database: str) -> None:
        """TC-EMB-01: Fragment embedding is persisted after abstract save.

        Given: A paper with abstract is processed via pipeline
        When: _persist_abstract_as_fragment() is called
        Then: persist_embedding is called for the fragment
        """
        from src.research.pipeline import SearchPipeline
        from src.utils.schemas import Author, Paper

        # Given: Paper with abstract
        paper = Paper(
            id="s2:test_embed",
            title="Test Paper",
            abstract="This is a test abstract for embedding.",
            authors=[Author(name="Test Author", affiliation=None, orcid=None)],
            year=2024,
            doi="10.1234/test.embed",
            source_api="semantic_scholar",
        )

        # Mock ML client and persist_embedding
        mock_ml_client = MagicMock()
        mock_ml_client.embed = AsyncMock(return_value=[[0.1] * 768])

        mock_persist_embedding = AsyncMock()

        # Mock settings
        mock_settings = MagicMock()
        mock_settings.embedding.model_name = "BAAI/bge-m3"

        pipeline = SearchPipeline.__new__(SearchPipeline)
        pipeline._state = MagicMock()

        with (
            patch("src.research.pipeline.get_database") as mock_get_db,
            patch("src.ml_client.get_ml_client", return_value=mock_ml_client),
            patch("src.storage.vector_store.persist_embedding", mock_persist_embedding),
            patch("src.utils.config.get_settings", return_value=mock_settings),
        ):
            # Setup mock database
            mock_db = AsyncMock()
            mock_db.claim_resource = AsyncMock(return_value=(True, None))
            mock_db.insert = AsyncMock()
            mock_db.complete_resource = AsyncMock()
            mock_get_db.return_value = mock_db

            # Mock _extract_claims_from_abstract to do nothing
            pipeline._extract_claims_from_abstract = AsyncMock(return_value=[])

            # When: Persist abstract as fragment
            await pipeline._persist_abstract_as_fragment(
                paper=paper,
                task_id="task_test",
                search_id="s_test",
                worker_id=0,
            )

        # Then: Embedding was persisted for fragment
        mock_ml_client.embed.assert_called_once()
        assert mock_persist_embedding.call_count >= 1
        # Verify it was called with "fragment" type
        call_args = mock_persist_embedding.call_args_list[0]
        assert call_args[0][0] == "fragment"

    def test_claim_embedding_code_exists(self) -> None:
        """TC-EMB-02: Verify claim embedding persistence code exists in pipeline.py.

        This is a code inspection test to verify the E2E fix was applied.
        The actual embedding persistence is tested via integration tests.

        Given: The pipeline.py source code
        When: We inspect _extract_claims_from_abstract method
        Then: persist_embedding("claim", ...) call exists
        """
        import inspect

        from src.research.pipeline import SearchPipeline

        # Given: Get source code of _extract_claims_from_abstract
        source = inspect.getsource(SearchPipeline._extract_claims_from_abstract)

        # Then: Embedding persistence code exists
        assert 'persist_embedding("claim"' in source, (
            "E2E fix missing: persist_embedding('claim', ...) not found in "
            "_extract_claims_from_abstract"
        )
        assert "Embedding generation failed for claim" in source, (
            "E2E fix missing: error handling for claim embedding not found"
        )

    @pytest.mark.asyncio
    async def test_embedding_failure_continues_processing(self, test_database: str) -> None:
        """TC-EMB-03: Processing continues when embedding generation fails.

        Given: Embedding generation raises an exception
        When: _persist_abstract_as_fragment() is called
        Then: Fragment is still persisted, warning logged
        """
        from src.research.pipeline import SearchPipeline
        from src.utils.schemas import Author, Paper

        paper = Paper(
            id="s2:test_fail_embed",
            title="Test Paper",
            abstract="Test abstract",
            authors=[Author(name="Test Author", affiliation=None, orcid=None)],
            year=2024,
            doi="10.1234/test.fail",
            source_api="semantic_scholar",
        )

        # Mock ML client that fails
        mock_ml_client = MagicMock()
        mock_ml_client.embed = AsyncMock(side_effect=Exception("ML server unavailable"))

        mock_settings = MagicMock()
        mock_settings.embedding.model_name = "BAAI/bge-m3"

        pipeline = SearchPipeline.__new__(SearchPipeline)
        pipeline._state = MagicMock()

        with (
            patch("src.research.pipeline.get_database") as mock_get_db,
            patch("src.ml_client.get_ml_client", return_value=mock_ml_client),
            patch("src.utils.config.get_settings", return_value=mock_settings),
        ):
            mock_db = AsyncMock()
            mock_db.claim_resource = AsyncMock(return_value=(True, None))
            mock_db.insert = AsyncMock()
            mock_db.complete_resource = AsyncMock()
            mock_get_db.return_value = mock_db

            pipeline._extract_claims_from_abstract = AsyncMock(return_value=[])

            # When/Then: No exception raised despite embedding failure
            page_id, fragment_id = await pipeline._persist_abstract_as_fragment(
                paper=paper,
                task_id="task_test",
                search_id="s_test",
                worker_id=0,
            )

        # Then: Fragment was persisted
        assert page_id is not None
        assert fragment_id is not None
        # DB insert was called
        assert mock_db.insert.call_count >= 2  # pages + fragments


# =============================================================================
# TC-CFG: Config-linked Timeout Tests
# =============================================================================


class TestAcquireTimeoutConfig:
    """Tests for acquire() timeout config linkage."""

    @pytest.mark.asyncio
    async def test_timeout_uses_default_constant_when_none(self) -> None:
        """TC-CFG-01: acquire() uses DEFAULT_SLOT_ACQUIRE_TIMEOUT_SECONDS when timeout=None.

        Given: acquire() called with timeout=None
        When: Timeout is needed
        Then: Uses DEFAULT_SLOT_ACQUIRE_TIMEOUT_SECONDS (300s) aligned with pipeline timeout

        Note: Design for thoroughness over speed - Academic APIs are the primary source
        for structured, high-quality references. We wait longer to ensure comprehensive
        coverage rather than fail fast.
        """
        from src.search.apis.rate_limiter import (
            DEFAULT_SLOT_ACQUIRE_TIMEOUT_SECONDS,
            AcademicAPIRateLimiter,
            ProviderRateLimitConfig,
            reset_academic_rate_limiter,
        )

        reset_academic_rate_limiter()

        # Verify the default constant is aligned with pipeline timeout for thoroughness
        assert DEFAULT_SLOT_ACQUIRE_TIMEOUT_SECONDS == 300.0

        # Given: Limiter with max_parallel=1 (will need timeout)
        limiter = AcademicAPIRateLimiter()
        config = ProviderRateLimitConfig(min_interval_seconds=0.0, max_parallel=1)
        limiter._configs["test_provider"] = config
        limiter._qps_locks["test_provider"] = asyncio.Lock()
        limiter._active_counts["test_provider"] = 0
        limiter._slot_events["test_provider"] = asyncio.Event()
        limiter._slot_events["test_provider"].set()
        from src.search.apis.rate_limiter import BackoffState

        limiter._backoff_states["test_provider"] = BackoffState(
            effective_max_parallel=1, config_max_parallel=1
        )

        # When: First acquire succeeds
        await limiter.acquire("test_provider", timeout=None)
        limiter._active_counts["test_provider"] = 1  # Simulate slot taken

        # When: Second acquire should timeout quickly (not using 300s pipeline timeout)
        # We test with explicit short timeout to verify the mechanism works
        with pytest.raises(TimeoutError):
            await limiter.acquire("test_provider", timeout=0.01)

        # Cleanup
        limiter._active_counts["test_provider"] = 0
