"""
Tests for API retry utilities (§3.1.3, §4.3.5).

Test coverage per §7.1 (Test Strategy):
- §3.1.3: Official public APIs (e-Stat, OpenAlex, etc.)
- §4.3.5: "ネットワーク/APIリトライ（トランジェントエラー向け）"

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|---------------------|-------------|-----------------|-------|
| TC-P-01 | Default policy | Normal | max_retries=3 | Default config |
| TC-P-02 | Overlap in retryable/non-retryable | Boundary | ValueError | Invalid config |
| TC-P-03 | ConnectionError | Normal | should_retry=True | Network error |
| TC-P-04 | TimeoutError | Normal | should_retry=True | Network error |
| TC-P-05 | ValueError | Normal | should_retry=False | Non-network error |
| TC-P-06 | status=429 | Normal | should_retry=True | Rate limit |
| TC-P-07 | status=503 | Normal | should_retry=True | Server error |
| TC-P-08 | status=404 | Normal | should_retry=False | Not found |
| TC-P-09 | status=403 | Normal | should_retry=False | Forbidden |
| TC-R-01 | Success on first try | Normal | Returns result | No retry needed |
| TC-R-02 | Success after 2 retries | Normal | Returns result | Retry works |
| TC-R-03 | All retries exhausted | Boundary | APIRetryError | Max retries |
| TC-R-04 | Non-retryable exception | Boundary | Re-raises exception | No retry |
| TC-R-05 | Non-retryable status | Boundary | Re-raises HTTPStatusError | No retry |
| TC-R-06 | Retryable status (429) | Normal | Retries with backoff | Rate limit |
| TC-D-01 | @with_api_retry decorator | Normal | Adds retry logic | Decorator |
| TC-D-02 | Custom policy via decorator | Normal | Uses custom policy | Config |
"""

import asyncio

import pytest

from src.utils.api_retry import (
    ACADEMIC_API_POLICY,
    ENTITY_API_POLICY,
    JAPAN_GOV_API_POLICY,
    APIRetryError,
    APIRetryPolicy,
    HTTPStatusError,
    retry_api_call,
    with_api_retry,
)
from src.utils.backoff import BackoffConfig


class TestHTTPStatusError:
    """Tests for HTTPStatusError exception."""

    def test_status_attribute(self):
        """Test that status attribute is set correctly."""
        # Given: HTTP 429 status
        # When: Creating exception
        error = HTTPStatusError(429, "Rate limited")

        # Then: Status is accessible
        assert error.status == 429
        assert "Rate limited" in str(error)

    def test_default_message(self):
        """Test default message format."""
        # Given: Status only
        # When: Creating exception
        error = HTTPStatusError(500)

        # Then: Default message includes status
        assert "HTTP 500" in str(error)


class TestAPIRetryError:
    """Tests for APIRetryError exception."""

    def test_attributes(self):
        """Test that all attributes are set correctly."""
        # Given: Error details
        inner_error = ConnectionError("Connection refused")

        # When: Creating exception
        error = APIRetryError(
            "Failed after retries",
            attempts=4,
            last_error=inner_error,
            last_status=None,
        )

        # Then: All attributes are accessible
        assert error.attempts == 4
        assert error.last_error is inner_error
        assert error.last_status is None
        assert "Failed after retries" in str(error)

    def test_with_status(self):
        """Test exception with last HTTP status."""
        # Given: HTTP error details
        # When: Creating exception
        error = APIRetryError(
            "API failed",
            attempts=3,
            last_status=503,
        )

        # Then: Status is accessible
        assert error.last_status == 503


class TestAPIRetryPolicy:
    """Tests for APIRetryPolicy dataclass."""

    def test_default_values(self):
        """TC-P-01: Default policy has correct values."""
        # Given: No arguments
        # When: Creating default policy
        policy = APIRetryPolicy()

        # Then: Default values are set
        assert policy.max_retries == 3
        assert isinstance(policy.backoff, BackoffConfig)
        assert ConnectionError in policy.retryable_exceptions
        assert TimeoutError in policy.retryable_exceptions
        assert OSError in policy.retryable_exceptions
        assert 429 in policy.retryable_status_codes
        assert 503 in policy.retryable_status_codes
        assert 403 in policy.non_retryable_status_codes

    def test_overlap_raises_error(self):
        """TC-P-02: Overlapping status codes raise ValueError."""
        # Given: Same status in both sets
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="cannot be both retryable and non-retryable"):
            APIRetryPolicy(
                retryable_status_codes=frozenset({429, 403}),
                non_retryable_status_codes=frozenset({403}),
            )

    def test_negative_max_retries_raises_error(self):
        """Test that negative max_retries raises ValueError."""
        # Given: Negative max_retries
        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="max_retries must be non-negative"):
            APIRetryPolicy(max_retries=-1)

    def test_should_retry_exception_connection_error(self):
        """TC-P-03: ConnectionError is retryable."""
        # Given: Policy and ConnectionError
        policy = APIRetryPolicy()
        exc = ConnectionError("Connection refused")

        # When: Checking if retryable
        # Then: Returns True
        assert policy.should_retry_exception(exc) is True

    def test_should_retry_exception_timeout_error(self):
        """TC-P-04: TimeoutError is retryable."""
        # Given: Policy and TimeoutError
        policy = APIRetryPolicy()
        exc = TimeoutError("Timed out")

        # When: Checking if retryable
        # Then: Returns True
        assert policy.should_retry_exception(exc) is True

    def test_should_retry_exception_value_error(self):
        """TC-P-05: ValueError is not retryable."""
        # Given: Policy and ValueError
        policy = APIRetryPolicy()
        exc = ValueError("Invalid value")

        # When: Checking if retryable
        # Then: Returns False
        assert policy.should_retry_exception(exc) is False

    def test_should_retry_status_429(self):
        """TC-P-06: Status 429 is retryable."""
        # Given: Policy
        policy = APIRetryPolicy()

        # When: Checking if 429 is retryable
        # Then: Returns True
        assert policy.should_retry_status(429) is True

    def test_should_retry_status_503(self):
        """TC-P-07: Status 503 is retryable."""
        # Given: Policy
        policy = APIRetryPolicy()

        # When: Checking if 503 is retryable
        # Then: Returns True
        assert policy.should_retry_status(503) is True

    def test_should_retry_status_404(self):
        """TC-P-08: Status 404 is not retryable."""
        # Given: Policy
        policy = APIRetryPolicy()

        # When: Checking if 404 is retryable
        # Then: Returns False
        assert policy.should_retry_status(404) is False

    def test_should_retry_status_403(self):
        """TC-P-09: Status 403 is not retryable."""
        # Given: Policy
        policy = APIRetryPolicy()

        # When: Checking if 403 is retryable
        # Then: Returns False
        assert policy.should_retry_status(403) is False

    def test_should_retry_status_unknown(self):
        """Test that unknown status codes are not retryable."""
        # Given: Policy
        policy = APIRetryPolicy()

        # When: Checking unknown status
        # Then: Returns False (unknown is not in retryable set)
        assert policy.should_retry_status(418) is False  # I'm a teapot


class TestRetryApiCall:
    """Tests for retry_api_call function."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        """TC-R-01: Returns result when function succeeds immediately."""
        # Given: Function that succeeds
        async def success_func():
            return {"data": "test"}

        # When: Calling with retry
        result = await retry_api_call(success_func)

        # Then: Returns the result
        assert result == {"data": "test"}

    @pytest.mark.asyncio
    async def test_success_after_retries(self):
        """TC-R-02: Returns result after transient failures."""
        # Given: Function that fails twice then succeeds
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection failed")
            return {"success": True}

        # When: Calling with retry (use short delays for testing)
        policy = APIRetryPolicy(
            max_retries=3,
            backoff=BackoffConfig(base_delay=0.01, max_delay=0.1),
        )
        result = await retry_api_call(flaky_func, policy=policy)

        # Then: Returns the result after retries
        assert result == {"success": True}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        """TC-R-03: Raises APIRetryError when all retries exhausted."""
        # Given: Function that always fails
        async def always_fails():
            raise ConnectionError("Connection refused")

        # When/Then: APIRetryError is raised
        policy = APIRetryPolicy(
            max_retries=2,
            backoff=BackoffConfig(base_delay=0.01, max_delay=0.1),
        )
        with pytest.raises(APIRetryError) as exc_info:
            await retry_api_call(always_fails, policy=policy)

        assert exc_info.value.attempts == 3  # 1 initial + 2 retries
        assert isinstance(exc_info.value.last_error, ConnectionError)

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        """TC-R-04: Non-retryable exceptions are re-raised immediately."""
        # Given: Function that raises ValueError
        async def raises_value_error():
            raise ValueError("Invalid input")

        # When/Then: ValueError is raised immediately
        policy = APIRetryPolicy(max_retries=3)
        with pytest.raises(ValueError, match="Invalid input"):
            await retry_api_call(raises_value_error, policy=policy)

    @pytest.mark.asyncio
    async def test_non_retryable_http_status(self):
        """TC-R-05: Non-retryable HTTP status is re-raised immediately."""
        # Given: Function that returns 404
        async def returns_404():
            raise HTTPStatusError(404, "Not found")

        # When/Then: HTTPStatusError is raised immediately
        policy = APIRetryPolicy(max_retries=3)
        with pytest.raises(HTTPStatusError) as exc_info:
            await retry_api_call(returns_404, policy=policy)

        assert exc_info.value.status == 404

    @pytest.mark.asyncio
    async def test_retryable_http_status_429(self):
        """TC-R-06: Status 429 triggers retry with backoff."""
        # Given: Function that returns 429 twice then succeeds
        call_count = 0

        async def rate_limited_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise HTTPStatusError(429, "Too many requests")
            return {"data": "success"}

        # When: Calling with retry
        policy = APIRetryPolicy(
            max_retries=3,
            backoff=BackoffConfig(base_delay=0.01, max_delay=0.1),
        )
        result = await retry_api_call(rate_limited_func, policy=policy)

        # Then: Returns result after retries
        assert result == {"data": "success"}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_operation_name_in_error(self):
        """Test that operation name appears in error."""
        # Given: Function that always fails
        async def my_special_func():
            raise ConnectionError("Failed")

        # When: Calling with custom operation name
        policy = APIRetryPolicy(
            max_retries=0,
            backoff=BackoffConfig(base_delay=0.01),
        )
        with pytest.raises(APIRetryError) as exc_info:
            await retry_api_call(
                my_special_func,
                policy=policy,
                operation_name="fetch_data",
            )

        # Then: Operation name is in error message
        assert "fetch_data" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_last_status_in_error(self):
        """Test that last HTTP status is recorded in error."""
        # Given: Function that always returns 503
        async def server_error():
            raise HTTPStatusError(503, "Service unavailable")

        # When: Calling with retry
        policy = APIRetryPolicy(
            max_retries=1,
            backoff=BackoffConfig(base_delay=0.01),
        )
        with pytest.raises(APIRetryError) as exc_info:
            await retry_api_call(server_error, policy=policy)

        # Then: Last status is recorded
        assert exc_info.value.last_status == 503

    @pytest.mark.asyncio
    async def test_with_args_and_kwargs(self):
        """Test that args and kwargs are passed correctly."""
        # Given: Function with parameters
        async def func_with_params(a, b, c=None):
            return {"a": a, "b": b, "c": c}

        # When: Calling with args and kwargs
        result = await retry_api_call(func_with_params, 1, 2, c=3)

        # Then: Parameters are passed correctly
        assert result == {"a": 1, "b": 2, "c": 3}


class TestWithApiRetryDecorator:
    """Tests for @with_api_retry decorator."""

    @pytest.mark.asyncio
    async def test_decorator_basic(self):
        """TC-D-01: Decorator adds retry logic."""
        # Given: Decorated function
        call_count = 0

        policy = APIRetryPolicy(
            max_retries=2,
            backoff=BackoffConfig(base_delay=0.01),
        )

        @with_api_retry(policy)
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Failed")
            return "success"

        # When: Calling decorated function
        result = await flaky_func()

        # Then: Retries and succeeds
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_decorator_custom_policy(self):
        """TC-D-02: Decorator uses custom policy."""
        # Given: Custom policy with 0 retries
        policy = APIRetryPolicy(max_retries=0)

        @with_api_retry(policy)
        async def always_fails():
            raise ConnectionError("Failed")

        # When/Then: Fails immediately (no retries)
        with pytest.raises(APIRetryError) as exc_info:
            await always_fails()

        assert exc_info.value.attempts == 1

    @pytest.mark.asyncio
    async def test_decorator_preserves_function_metadata(self):
        """Test that decorator preserves function metadata."""
        # Given: Decorated function with docstring
        @with_api_retry()
        async def my_function():
            """This is my function."""
            return "result"

        # When: Checking function metadata
        # Then: Metadata is preserved
        assert my_function.__name__ == "my_function"
        assert "This is my function" in my_function.__doc__

    @pytest.mark.asyncio
    async def test_decorator_with_operation_name(self):
        """Test decorator with custom operation name."""
        # Given: Decorated function with custom name
        policy = APIRetryPolicy(
            max_retries=0,
            backoff=BackoffConfig(base_delay=0.01),
        )

        @with_api_retry(policy, operation_name="custom_operation")
        async def my_func():
            raise ConnectionError("Failed")

        # When/Then: Error includes custom name
        with pytest.raises(APIRetryError) as exc_info:
            await my_func()

        assert "custom_operation" in str(exc_info.value)


class TestPreConfiguredPolicies:
    """Tests for pre-configured policies."""

    def test_japan_gov_api_policy(self):
        """Test JAPAN_GOV_API_POLICY configuration."""
        # Given: Pre-configured policy
        policy = JAPAN_GOV_API_POLICY

        # Then: Has expected values
        assert policy.max_retries == 3
        assert policy.backoff.base_delay == 2.0
        assert policy.backoff.max_delay == 60.0

    def test_academic_api_policy(self):
        """Test ACADEMIC_API_POLICY configuration."""
        # Given: Pre-configured policy
        policy = ACADEMIC_API_POLICY

        # Then: Has expected values (more lenient)
        assert policy.max_retries == 5
        assert policy.backoff.base_delay == 1.0
        assert policy.backoff.max_delay == 120.0

    def test_entity_api_policy(self):
        """Test ENTITY_API_POLICY configuration."""
        # Given: Pre-configured policy
        policy = ENTITY_API_POLICY

        # Then: Has expected values (more aggressive)
        assert policy.max_retries == 3
        assert policy.backoff.base_delay == 0.5
        assert policy.backoff.max_delay == 30.0


class TestSpecCompliance:
    """Tests for compliance with specification sections."""

    def test_spec_3_1_3_no_bot_detection_for_official_apis(self):
        """Test that policy is designed for official APIs without bot detection (§3.1.3)."""
        # Given: Default policy
        policy = APIRetryPolicy()

        # Then: Retries network errors (safe for official APIs)
        assert policy.should_retry_exception(ConnectionError())
        assert policy.should_retry_exception(TimeoutError())

        # Then: Does NOT retry 403 (in case API uses it for auth errors)
        assert not policy.should_retry_status(403)

    def test_spec_4_3_5_network_transient_retry(self):
        """Test that policy handles network transient errors (§4.3.5)."""
        # Given: Policy
        policy = APIRetryPolicy()

        # Then: Retries appropriate transient errors
        assert 429 in policy.retryable_status_codes  # Rate limit
        assert 500 in policy.retryable_status_codes  # Internal server error
        assert 502 in policy.retryable_status_codes  # Bad gateway
        assert 503 in policy.retryable_status_codes  # Service unavailable
        assert 504 in policy.retryable_status_codes  # Gateway timeout

    def test_spec_4_3_5_not_for_search_engines(self):
        """Test that 403 is NOT retryable (search engine protection) per §4.3.5."""
        # Given: Policy
        policy = APIRetryPolicy()

        # Then: 403 is explicitly non-retryable
        # Per §4.3.5: "検索エンジン/ブラウザ取得では使用禁止"
        assert 403 in policy.non_retryable_status_codes
        assert not policy.should_retry_status(403)

    @pytest.mark.asyncio
    async def test_spec_backoff_applied(self):
        """Test that exponential backoff is applied per §4.3.5."""
        # Given: Track timing
        timestamps = []
        call_count = 0

        async def failing_func():
            nonlocal call_count
            timestamps.append(asyncio.get_running_loop().time())
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Failed")
            return "success"

        # When: Calling with retry
        policy = APIRetryPolicy(
            max_retries=3,
            backoff=BackoffConfig(base_delay=0.05, max_delay=1.0, jitter_factor=0),
        )
        await retry_api_call(failing_func, policy=policy)

        # Then: Delays are increasing (exponential backoff)
        delay1 = timestamps[1] - timestamps[0]
        delay2 = timestamps[2] - timestamps[1]

        # First delay ~0.05s, second delay ~0.10s
        assert delay1 >= 0.04  # Allow some tolerance
        assert delay2 >= delay1 * 1.5  # Second delay should be larger

