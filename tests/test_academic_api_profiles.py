"""
Tests for Academic API profile-based rate limiting.

Profile switching based on credentials:
- Semantic Scholar: anonymous (no key) / authenticated (with API key)
- OpenAlex: anonymous (no email) / identified (with email for polite pool)

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|--------------------------------------|-----------------|-------|
| TC-CFG-01 | rate_limit_profiles with anonymous only | Equivalence – normal | Config loads, anonymous profile used | |
| TC-CFG-02 | rate_limit_profiles with all profiles | Equivalence – normal | Config loads, all profiles accessible | |
| TC-CFG-04 | Missing anonymous profile | Boundary – required field | ValidationError | |
| TC-PS-01 | S2 with API key set | Equivalence – normal | authenticated profile selected | wiring |
| TC-PS-02 | S2 without API key | Equivalence – normal | anonymous profile selected | wiring |
| TC-PS-03 | OpenAlex with email set | Equivalence – normal | identified profile selected | wiring |
| TC-PS-04 | OpenAlex without email | Equivalence – normal | anonymous profile selected | wiring |
| TC-PS-05 | Unknown provider | Boundary – edge case | anonymous profile (fallback) | |
| TC-RL-01 | S2 authenticated profile | Equivalence – normal | min_interval=2.0s, max_parallel=1 | effect |
| TC-RL-02 | S2 anonymous profile | Equivalence – normal | min_interval=3.0s, max_parallel=1 | effect |
| TC-RL-03 | OpenAlex identified profile | Equivalence – normal | min_interval=0.2s, max_parallel=2 | effect |
| TC-RL-04 | OpenAlex anonymous profile | Equivalence – normal | min_interval=0.5s, max_parallel=1 | effect |
| TC-DG-01 | downgrade_profile() called | Equivalence – normal | Profile changes to anonymous | wiring |
| TC-DG-02 | Double downgrade | Boundary – idempotent | No error, stays anonymous | |
| TC-DG-03 | Downgrade updates config_max_parallel | Equivalence – normal | backoff.config_max reduced | effect |
| TC-429-01 | Anonymous profile | Equivalence – normal | Returns base value (2) | |
| TC-429-02 | Authenticated profile | Equivalence – normal | Returns override value (5) | |
| TC-429-03 | Identified profile | Equivalence – normal | Returns override value (5) | |
| TC-WRN-01 | S2 without API key at init | Equivalence – normal | WARNING logged once | |
| TC-WRN-04 | Multiple inits don't re-log | Boundary – idempotent | WARNING logged only once | |
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from src.search.apis.rate_limiter import (
    AcademicAPIRateLimiter,
    RateLimitProfile,
    reset_academic_rate_limiter,
)
from src.utils.config import (
    AcademicAPIConfig,
    AcademicAPIRateLimitConfig,
    AcademicAPIRateLimitProfilesConfig,
    AcademicAPIRetryPolicyConfig,
    AcademicAPIRetryPolicyProfileOverrideConfig,
    AcademicAPIRetryPolicyProfilesConfig,
    AcademicAPIsConfig,
)


class TestConfigSchemaValidation:
    """Tests for config schema validation (TC-CFG-*)."""

    # =========================================================================
    # TC-CFG-01: rate_limit_profiles with anonymous only
    # =========================================================================
    def test_rate_limit_profiles_anonymous_only(self) -> None:
        """Test config with only anonymous profile.

        Given: rate_limit_profiles with only anonymous defined
        When: Config is created
        Then: Config loads successfully, anonymous profile accessible
        """
        # Given/When
        profiles = AcademicAPIRateLimitProfilesConfig(
            anonymous=AcademicAPIRateLimitConfig(min_interval_seconds=1.0, max_parallel=1)
        )

        # Then
        assert profiles.anonymous.min_interval_seconds == 1.0
        assert profiles.anonymous.max_parallel == 1
        assert profiles.authenticated is None
        assert profiles.identified is None

    # =========================================================================
    # TC-CFG-02: rate_limit_profiles with all profiles
    # =========================================================================
    def test_rate_limit_profiles_all_profiles(self) -> None:
        """Test config with all profiles defined.

        Given: rate_limit_profiles with anonymous, authenticated, and identified
        When: Config is created
        Then: All profiles accessible
        """
        # Given/When
        profiles = AcademicAPIRateLimitProfilesConfig(
            anonymous=AcademicAPIRateLimitConfig(min_interval_seconds=3.0, max_parallel=1),
            authenticated=AcademicAPIRateLimitConfig(min_interval_seconds=2.0, max_parallel=1),
            identified=AcademicAPIRateLimitConfig(min_interval_seconds=0.2, max_parallel=2),
        )

        # Then
        assert profiles.anonymous.min_interval_seconds == 3.0
        assert profiles.authenticated is not None
        assert profiles.authenticated.min_interval_seconds == 2.0
        assert profiles.identified is not None
        assert profiles.identified.min_interval_seconds == 0.2
        assert profiles.identified.max_parallel == 2

    # =========================================================================
    # TC-CFG-04: Missing anonymous profile (should fail)
    # =========================================================================
    def test_rate_limit_profiles_missing_anonymous(self) -> None:
        """Test that missing anonymous profile causes validation error.

        Given: rate_limit_profiles without anonymous
        When: Config is created
        Then: ValidationError raised
        """
        # Given/When/Then
        with pytest.raises(ValidationError):
            AcademicAPIRateLimitProfilesConfig(
                authenticated=AcademicAPIRateLimitConfig(min_interval_seconds=2.0, max_parallel=1)
            )  # type: ignore[call-arg]

    # =========================================================================
    # TC-CFG-05: retry_policy.profiles with overrides
    # =========================================================================
    def test_retry_policy_profiles_overrides(self) -> None:
        """Test retry_policy profile overrides.

        Given: retry_policy with profiles section
        When: Config is created
        Then: Profile overrides accessible
        """
        # Given/When
        retry_policy = AcademicAPIRetryPolicyConfig(
            max_retries=5,
            max_consecutive_429=2,
            profiles=AcademicAPIRetryPolicyProfilesConfig(
                authenticated=AcademicAPIRetryPolicyProfileOverrideConfig(max_consecutive_429=5),
                identified=AcademicAPIRetryPolicyProfileOverrideConfig(max_consecutive_429=5),
            ),
        )

        # Then
        assert retry_policy.max_consecutive_429 == 2  # Base
        assert retry_policy.profiles is not None
        assert retry_policy.profiles.authenticated is not None
        assert retry_policy.profiles.authenticated.max_consecutive_429 == 5
        assert retry_policy.profiles.identified is not None
        assert retry_policy.profiles.identified.max_consecutive_429 == 5


class TestProfileSelection:
    """Tests for profile selection logic (TC-PS-*)."""

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset global rate limiter before each test."""
        reset_academic_rate_limiter()

    def _create_mock_academic_apis_config(
        self,
        s2_api_key: str | None = None,
        s2_email: str | None = None,
        oa_email: str | None = None,
    ) -> MagicMock:
        """Create mock academic APIs config."""
        mock_config = MagicMock(spec=AcademicAPIsConfig)

        # S2 config
        s2_config = MagicMock(spec=AcademicAPIConfig)
        s2_config.api_key = s2_api_key
        s2_config.email = s2_email
        s2_config.rate_limit_profiles = MagicMock()
        s2_config.rate_limit_profiles.anonymous = MagicMock()
        s2_config.rate_limit_profiles.anonymous.min_interval_seconds = 3.0
        s2_config.rate_limit_profiles.anonymous.max_parallel = 1
        s2_config.rate_limit_profiles.authenticated = MagicMock()
        s2_config.rate_limit_profiles.authenticated.min_interval_seconds = 2.0
        s2_config.rate_limit_profiles.authenticated.max_parallel = 1
        s2_config.rate_limit_profiles.identified = None

        # OA config
        oa_config = MagicMock(spec=AcademicAPIConfig)
        oa_config.api_key = None
        oa_config.email = oa_email
        oa_config.rate_limit_profiles = MagicMock()
        oa_config.rate_limit_profiles.anonymous = MagicMock()
        oa_config.rate_limit_profiles.anonymous.min_interval_seconds = 0.5
        oa_config.rate_limit_profiles.anonymous.max_parallel = 1
        oa_config.rate_limit_profiles.authenticated = None
        oa_config.rate_limit_profiles.identified = MagicMock()
        oa_config.rate_limit_profiles.identified.min_interval_seconds = 0.2
        oa_config.rate_limit_profiles.identified.max_parallel = 2

        def get_api_config(name: str) -> MagicMock:
            if name == "semantic_scholar":
                return s2_config
            elif name == "openalex":
                return oa_config
            else:
                # Unknown provider - return minimal config
                unknown = MagicMock()
                unknown.api_key = None
                unknown.email = None
                unknown.rate_limit_profiles = None
                return unknown

        mock_config.get_api_config = get_api_config
        mock_config.retry_policy = MagicMock()
        mock_config.retry_policy.auto_backoff.recovery_stable_seconds = 60
        mock_config.retry_policy.auto_backoff.decrease_step = 1
        mock_config.retry_policy.max_consecutive_429 = 2
        mock_config.retry_policy.profiles = None

        return mock_config

    # =========================================================================
    # TC-PS-01: S2 with API key → authenticated
    # =========================================================================
    @pytest.mark.asyncio
    async def test_s2_with_api_key_selects_authenticated(self) -> None:
        """Test S2 with API key selects authenticated profile.

        Given: Semantic Scholar config with API key set
        When: Rate limiter initializes for semantic_scholar
        Then: authenticated profile selected (wiring)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_academic_apis_config(s2_api_key="test_api_key")

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("semantic_scholar")

        # Then
        profile = limiter.get_current_profile("semantic_scholar")
        assert profile == RateLimitProfile.AUTHENTICATED

    # =========================================================================
    # TC-PS-02: S2 without API key → anonymous
    # =========================================================================
    @pytest.mark.asyncio
    async def test_s2_without_api_key_selects_anonymous(self) -> None:
        """Test S2 without API key selects anonymous profile.

        Given: Semantic Scholar config without API key
        When: Rate limiter initializes for semantic_scholar
        Then: anonymous profile selected (wiring)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_academic_apis_config(s2_api_key=None)

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("semantic_scholar")

        # Then
        profile = limiter.get_current_profile("semantic_scholar")
        assert profile == RateLimitProfile.ANONYMOUS

    # =========================================================================
    # TC-PS-03: OpenAlex with email → identified
    # =========================================================================
    @pytest.mark.asyncio
    async def test_openalex_with_email_selects_identified(self) -> None:
        """Test OpenAlex with email selects identified profile.

        Given: OpenAlex config with email set
        When: Rate limiter initializes for openalex
        Then: identified profile selected (wiring)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_academic_apis_config(oa_email="test@example.com")

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("openalex")

        # Then
        profile = limiter.get_current_profile("openalex")
        assert profile == RateLimitProfile.IDENTIFIED

    # =========================================================================
    # TC-PS-04: OpenAlex without email → anonymous
    # =========================================================================
    @pytest.mark.asyncio
    async def test_openalex_without_email_selects_anonymous(self) -> None:
        """Test OpenAlex without email selects anonymous profile.

        Given: OpenAlex config without email
        When: Rate limiter initializes for openalex
        Then: anonymous profile selected (wiring)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_academic_apis_config(oa_email=None)

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("openalex")

        # Then
        profile = limiter.get_current_profile("openalex")
        assert profile == RateLimitProfile.ANONYMOUS

    # =========================================================================
    # TC-PS-05: Unknown provider → anonymous (fallback)
    # =========================================================================
    @pytest.mark.asyncio
    async def test_unknown_provider_selects_anonymous(self) -> None:
        """Test unknown provider selects anonymous profile.

        Given: Unknown provider name
        When: Rate limiter initializes
        Then: anonymous profile selected (fallback)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_academic_apis_config()

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("unknown_provider")

        # Then
        profile = limiter.get_current_profile("unknown_provider")
        assert profile == RateLimitProfile.ANONYMOUS


class TestRateLimitEffects:
    """Tests for rate limit values per profile (TC-RL-*)."""

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset global rate limiter before each test."""
        reset_academic_rate_limiter()

    def _create_mock_config(
        self,
        s2_api_key: str | None = None,
        oa_email: str | None = None,
    ) -> MagicMock:
        """Create mock config with profile values from academic_apis.yaml."""
        mock_config = MagicMock(spec=AcademicAPIsConfig)

        # S2 config with profile-based rate limits
        s2_config = MagicMock(spec=AcademicAPIConfig)
        s2_config.api_key = s2_api_key
        s2_config.email = None
        s2_config.rate_limit_profiles = MagicMock()
        s2_config.rate_limit_profiles.anonymous = MagicMock()
        s2_config.rate_limit_profiles.anonymous.min_interval_seconds = 3.0
        s2_config.rate_limit_profiles.anonymous.max_parallel = 1
        s2_config.rate_limit_profiles.authenticated = MagicMock()
        s2_config.rate_limit_profiles.authenticated.min_interval_seconds = 2.0
        s2_config.rate_limit_profiles.authenticated.max_parallel = 1
        s2_config.rate_limit_profiles.identified = None

        # OA config with profile-based rate limits
        oa_config = MagicMock(spec=AcademicAPIConfig)
        oa_config.api_key = None
        oa_config.email = oa_email
        oa_config.rate_limit_profiles = MagicMock()
        oa_config.rate_limit_profiles.anonymous = MagicMock()
        oa_config.rate_limit_profiles.anonymous.min_interval_seconds = 0.5
        oa_config.rate_limit_profiles.anonymous.max_parallel = 1
        oa_config.rate_limit_profiles.authenticated = None
        oa_config.rate_limit_profiles.identified = MagicMock()
        oa_config.rate_limit_profiles.identified.min_interval_seconds = 0.2
        oa_config.rate_limit_profiles.identified.max_parallel = 2

        def get_api_config(name: str) -> MagicMock:
            if name == "semantic_scholar":
                return s2_config
            elif name == "openalex":
                return oa_config
            else:
                # Unknown
                unknown = MagicMock()
                unknown.api_key = None
                unknown.email = None
                unknown.rate_limit_profiles = None
                return unknown

        mock_config.get_api_config = get_api_config
        mock_config.retry_policy = MagicMock()
        mock_config.retry_policy.auto_backoff.recovery_stable_seconds = 60
        mock_config.retry_policy.auto_backoff.decrease_step = 1

        return mock_config

    # =========================================================================
    # TC-RL-01: S2 authenticated profile rate limits
    # =========================================================================
    @pytest.mark.asyncio
    async def test_s2_authenticated_rate_limits(self) -> None:
        """Test S2 authenticated profile uses correct rate limits.

        Given: S2 with API key
        When: Rate limiter initializes
        Then: min_interval=2.0s, max_parallel=1 (effect)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(s2_api_key="test_key")

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            config = limiter._get_provider_config("semantic_scholar")

        # Then
        assert config.min_interval_seconds == 2.0
        assert config.max_parallel == 1
        assert config.profile == RateLimitProfile.AUTHENTICATED

    # =========================================================================
    # TC-RL-02: S2 anonymous profile rate limits
    # =========================================================================
    @pytest.mark.asyncio
    async def test_s2_anonymous_rate_limits(self) -> None:
        """Test S2 anonymous profile uses correct rate limits.

        Given: S2 without API key
        When: Rate limiter initializes
        Then: min_interval=3.0s, max_parallel=1 (effect)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(s2_api_key=None)

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            config = limiter._get_provider_config("semantic_scholar")

        # Then
        assert config.min_interval_seconds == 3.0
        assert config.max_parallel == 1
        assert config.profile == RateLimitProfile.ANONYMOUS

    # =========================================================================
    # TC-RL-03: OpenAlex identified profile rate limits
    # =========================================================================
    @pytest.mark.asyncio
    async def test_openalex_identified_rate_limits(self) -> None:
        """Test OpenAlex identified profile uses correct rate limits.

        Given: OpenAlex with email
        When: Rate limiter initializes
        Then: min_interval=0.2s, max_parallel=2 (effect)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(oa_email="test@example.com")

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            config = limiter._get_provider_config("openalex")

        # Then
        assert config.min_interval_seconds == 0.2
        assert config.max_parallel == 2
        assert config.profile == RateLimitProfile.IDENTIFIED

    # =========================================================================
    # TC-RL-04: OpenAlex anonymous profile rate limits
    # =========================================================================
    @pytest.mark.asyncio
    async def test_openalex_anonymous_rate_limits(self) -> None:
        """Test OpenAlex anonymous profile uses correct rate limits.

        Given: OpenAlex without email
        When: Rate limiter initializes
        Then: min_interval=0.5s, max_parallel=1 (effect)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(oa_email=None)

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            config = limiter._get_provider_config("openalex")

        # Then
        assert config.min_interval_seconds == 0.5
        assert config.max_parallel == 1
        assert config.profile == RateLimitProfile.ANONYMOUS


class TestProfileDowngrade:
    """Tests for profile downgrade functionality (TC-DG-*)."""

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset global rate limiter before each test."""
        reset_academic_rate_limiter()

    def _create_mock_config(self, s2_api_key: str | None = None) -> MagicMock:
        """Create mock config."""
        mock_config = MagicMock(spec=AcademicAPIsConfig)

        s2_config = MagicMock(spec=AcademicAPIConfig)
        s2_config.api_key = s2_api_key
        s2_config.email = None
        s2_config.rate_limit_profiles = MagicMock()
        s2_config.rate_limit_profiles.anonymous = MagicMock()
        s2_config.rate_limit_profiles.anonymous.min_interval_seconds = 3.0
        s2_config.rate_limit_profiles.anonymous.max_parallel = 1
        s2_config.rate_limit_profiles.authenticated = MagicMock()
        s2_config.rate_limit_profiles.authenticated.min_interval_seconds = 2.0
        s2_config.rate_limit_profiles.authenticated.max_parallel = 2  # Higher for authenticated
        s2_config.rate_limit_profiles.identified = None

        def get_api_config(name: str) -> Any:
            if name == "semantic_scholar":
                return s2_config
            unknown = MagicMock()
            unknown.api_key = None
            unknown.email = None
            unknown.rate_limit_profiles = None
            return unknown

        mock_config.get_api_config = get_api_config
        mock_config.retry_policy = MagicMock()
        mock_config.retry_policy.auto_backoff.recovery_stable_seconds = 60
        mock_config.retry_policy.auto_backoff.decrease_step = 1

        return mock_config

    # =========================================================================
    # TC-DG-01: downgrade_profile() changes to anonymous
    # =========================================================================
    @pytest.mark.asyncio
    async def test_downgrade_changes_to_anonymous(self) -> None:
        """Test downgrade_profile changes profile to anonymous.

        Given: Limiter with authenticated profile
        When: downgrade_profile() is called
        Then: Profile becomes anonymous (wiring)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(s2_api_key="test_key")

        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("semantic_scholar")

        assert limiter.get_current_profile("semantic_scholar") == RateLimitProfile.AUTHENTICATED

        # When - need to update mock for anonymous profile selection after downgrade
        mock_config_anon = self._create_mock_config(s2_api_key=None)
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config_anon):
            limiter.downgrade_profile("semantic_scholar")

        # Then
        assert limiter.get_current_profile("semantic_scholar") == RateLimitProfile.ANONYMOUS
        assert limiter._provider_states["semantic_scholar"].profile_downgraded is True

    # =========================================================================
    # TC-DG-02: Double downgrade is idempotent
    # =========================================================================
    @pytest.mark.asyncio
    async def test_double_downgrade_idempotent(self) -> None:
        """Test double downgrade is idempotent.

        Given: Already downgraded limiter
        When: downgrade_profile() is called again
        Then: No error, stays anonymous
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(s2_api_key="test_key")

        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("semantic_scholar")

        mock_config_anon = self._create_mock_config(s2_api_key=None)
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config_anon):
            limiter.downgrade_profile("semantic_scholar")

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config_anon):
            limiter.downgrade_profile("semantic_scholar")  # Second downgrade

        # Then - no error, still anonymous
        assert limiter.get_current_profile("semantic_scholar") == RateLimitProfile.ANONYMOUS

    # =========================================================================
    # TC-DG-03: Downgrade updates config_max_parallel
    # =========================================================================
    @pytest.mark.asyncio
    async def test_downgrade_updates_config_max_parallel(self) -> None:
        """Test downgrade updates backoff config_max_parallel.

        Given: Limiter with authenticated profile (max_parallel=2)
        When: downgrade_profile() is called (anonymous max_parallel=1)
        Then: backoff.config_max_parallel is reduced (effect)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(s2_api_key="test_key")

        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("semantic_scholar")

        # Verify initial state (authenticated = max_parallel 2)
        assert limiter._backoff_states["semantic_scholar"].config_max_parallel == 2

        # When
        mock_config_anon = self._create_mock_config(s2_api_key=None)
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config_anon):
            limiter.downgrade_profile("semantic_scholar")

        # Then - config_max_parallel reduced to anonymous level
        assert limiter._backoff_states["semantic_scholar"].config_max_parallel == 1


class TestMaxConsecutive429Profiles:
    """Tests for profile-aware max_consecutive_429 (TC-429-*)."""

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset global rate limiter before each test."""
        reset_academic_rate_limiter()

    def _create_mock_config(
        self,
        s2_api_key: str | None = None,
        base_max_429: int = 2,
        auth_max_429: int = 5,
    ) -> MagicMock:
        """Create mock config with retry policy profiles."""
        mock_config = MagicMock(spec=AcademicAPIsConfig)

        s2_config = MagicMock(spec=AcademicAPIConfig)
        s2_config.api_key = s2_api_key
        s2_config.email = None
        s2_config.rate_limit_profiles = MagicMock()
        s2_config.rate_limit_profiles.anonymous = MagicMock()
        s2_config.rate_limit_profiles.anonymous.min_interval_seconds = 3.0
        s2_config.rate_limit_profiles.anonymous.max_parallel = 1
        s2_config.rate_limit_profiles.authenticated = MagicMock()
        s2_config.rate_limit_profiles.authenticated.min_interval_seconds = 2.0
        s2_config.rate_limit_profiles.authenticated.max_parallel = 1
        s2_config.rate_limit_profiles.identified = None

        oa_config = MagicMock(spec=AcademicAPIConfig)
        oa_config.api_key = None
        oa_config.email = "test@example.com"
        oa_config.rate_limit_profiles = MagicMock()
        oa_config.rate_limit_profiles.anonymous = MagicMock()
        oa_config.rate_limit_profiles.anonymous.min_interval_seconds = 0.5
        oa_config.rate_limit_profiles.anonymous.max_parallel = 1
        oa_config.rate_limit_profiles.authenticated = None
        oa_config.rate_limit_profiles.identified = MagicMock()
        oa_config.rate_limit_profiles.identified.min_interval_seconds = 0.2
        oa_config.rate_limit_profiles.identified.max_parallel = 2

        def get_api_config(name: str) -> Any:
            if name == "semantic_scholar":
                return s2_config
            elif name == "openalex":
                return oa_config
            unknown = MagicMock()
            unknown.api_key = None
            unknown.email = None
            unknown.rate_limit_profiles = None
            return unknown

        mock_config.get_api_config = get_api_config

        # Retry policy with profiles
        mock_config.retry_policy = MagicMock()
        mock_config.retry_policy.max_consecutive_429 = base_max_429
        mock_config.retry_policy.auto_backoff.recovery_stable_seconds = 60
        mock_config.retry_policy.auto_backoff.decrease_step = 1
        mock_config.retry_policy.profiles = MagicMock()
        mock_config.retry_policy.profiles.authenticated = MagicMock()
        mock_config.retry_policy.profiles.authenticated.max_consecutive_429 = auth_max_429
        mock_config.retry_policy.profiles.identified = MagicMock()
        mock_config.retry_policy.profiles.identified.max_consecutive_429 = auth_max_429

        return mock_config

    # =========================================================================
    # TC-429-01: Anonymous profile returns base value
    # =========================================================================
    @pytest.mark.asyncio
    async def test_anonymous_returns_base_value(self) -> None:
        """Test anonymous profile returns base max_consecutive_429.

        Given: S2 without API key (anonymous profile)
        When: get_max_consecutive_429_for_provider is called
        Then: Returns base value (2)
        """
        from src.utils.api_retry import get_max_consecutive_429_for_provider

        # Given
        mock_config = self._create_mock_config(s2_api_key=None)

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            value = get_max_consecutive_429_for_provider("semantic_scholar")

        # Then
        assert value == 2  # Base value

    # =========================================================================
    # TC-429-02: Authenticated profile returns override
    # =========================================================================
    @pytest.mark.asyncio
    async def test_authenticated_returns_override(self) -> None:
        """Test authenticated profile returns override max_consecutive_429.

        Given: S2 with API key (authenticated profile)
        When: get_max_consecutive_429_for_provider is called
        Then: Returns override value (5)
        """
        from src.utils.api_retry import get_max_consecutive_429_for_provider

        # Given - First initialize the rate limiter with authenticated profile
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(s2_api_key="test_key")

        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("semantic_scholar")

        # When - Need to use the same mock but with rate limiter patched
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            with patch(
                "src.search.apis.rate_limiter.get_academic_rate_limiter", return_value=limiter
            ):
                value = get_max_consecutive_429_for_provider("semantic_scholar")

        # Then
        assert value == 5  # Override value

    # =========================================================================
    # TC-429-03: Identified profile returns override
    # =========================================================================
    @pytest.mark.asyncio
    async def test_identified_returns_override(self) -> None:
        """Test identified profile returns override max_consecutive_429.

        Given: OpenAlex with email (identified profile)
        When: get_max_consecutive_429_for_provider is called
        Then: Returns override value (5)
        """
        from src.utils.api_retry import get_max_consecutive_429_for_provider

        # Given - First initialize the rate limiter with identified profile
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(s2_api_key=None)  # OA email set in config

        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("openalex")

        # Verify profile
        assert limiter.get_current_profile("openalex") == RateLimitProfile.IDENTIFIED

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            with patch(
                "src.search.apis.rate_limiter.get_academic_rate_limiter", return_value=limiter
            ):
                value = get_max_consecutive_429_for_provider("openalex")

        # Then
        assert value == 5  # Override value


class TestWarningLogs:
    """Tests for WARNING log behavior (TC-WRN-*).

    Note: Lyra uses structlog which outputs to stdout, not standard logging.
    We verify warning_logged flags rather than relying on stdout capture,
    as stdout capture can be affected by other tests or coverage collection.
    """

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset global rate limiter before each test."""
        reset_academic_rate_limiter()

    def _create_mock_config(
        self,
        s2_api_key: str | None = None,
        oa_email: str | None = None,
    ) -> MagicMock:
        """Create mock config."""
        mock_config = MagicMock(spec=AcademicAPIsConfig)

        s2_config = MagicMock(spec=AcademicAPIConfig)
        s2_config.api_key = s2_api_key
        s2_config.email = None
        s2_config.rate_limit_profiles = MagicMock()
        s2_config.rate_limit_profiles.anonymous = MagicMock()
        s2_config.rate_limit_profiles.anonymous.min_interval_seconds = 3.0
        s2_config.rate_limit_profiles.anonymous.max_parallel = 1
        s2_config.rate_limit_profiles.authenticated = MagicMock()
        s2_config.rate_limit_profiles.authenticated.min_interval_seconds = 2.0
        s2_config.rate_limit_profiles.authenticated.max_parallel = 1
        s2_config.rate_limit_profiles.identified = None

        oa_config = MagicMock(spec=AcademicAPIConfig)
        oa_config.api_key = None
        oa_config.email = oa_email
        oa_config.rate_limit_profiles = MagicMock()
        oa_config.rate_limit_profiles.anonymous = MagicMock()
        oa_config.rate_limit_profiles.anonymous.min_interval_seconds = 0.5
        oa_config.rate_limit_profiles.anonymous.max_parallel = 1
        oa_config.rate_limit_profiles.authenticated = None
        oa_config.rate_limit_profiles.identified = MagicMock()
        oa_config.rate_limit_profiles.identified.min_interval_seconds = 0.2
        oa_config.rate_limit_profiles.identified.max_parallel = 2

        def get_api_config(name: str) -> Any:
            if name == "semantic_scholar":
                return s2_config
            elif name == "openalex":
                return oa_config
            unknown = MagicMock()
            unknown.api_key = None
            unknown.email = None
            unknown.rate_limit_profiles = None
            return unknown

        mock_config.get_api_config = get_api_config
        mock_config.retry_policy = MagicMock()
        mock_config.retry_policy.auto_backoff.recovery_stable_seconds = 60
        mock_config.retry_policy.auto_backoff.decrease_step = 1

        return mock_config

    # =========================================================================
    # TC-WRN-01: S2 without API key sets warning flag
    # =========================================================================
    @pytest.mark.asyncio
    async def test_s2_missing_key_sets_warning_flag(self) -> None:
        """Test S2 without API key sets startup_warning_logged flag.

        Given: S2 config without API key
        When: Rate limiter initializes
        Then: startup_warning_logged is set to True (wiring test)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(s2_api_key=None)

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("semantic_scholar")

        # Then - verify warning flag is set (wiring)
        state = limiter._provider_states.get("semantic_scholar")
        assert state is not None
        assert state.startup_warning_logged is True

    # =========================================================================
    # TC-WRN-02: OpenAlex without email sets warning flag
    # =========================================================================
    @pytest.mark.asyncio
    async def test_openalex_missing_email_sets_warning_flag(self) -> None:
        """Test OpenAlex without email sets startup_warning_logged flag.

        Given: OpenAlex config without email
        When: Rate limiter initializes
        Then: startup_warning_logged is set to True (wiring test)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(oa_email=None)

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("openalex")

        # Then - verify warning flag is set (wiring)
        state = limiter._provider_states.get("openalex")
        assert state is not None
        assert state.startup_warning_logged is True

    # =========================================================================
    # TC-WRN-04: Multiple inits don't re-set warning flag
    # =========================================================================
    @pytest.mark.asyncio
    async def test_multiple_inits_warning_flag_idempotent(self) -> None:
        """Test multiple initializations set warning flag only once.

        Given: S2 without API key
        When: Rate limiter initializes multiple times
        Then: startup_warning_logged stays True (idempotent)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(s2_api_key=None)

        # When - initialize twice
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("semantic_scholar")
            # Second init attempt - but already initialized, should skip
            await limiter._ensure_provider_initialized("semantic_scholar")

        # Then - warning flag set and stays set
        state = limiter._provider_states.get("semantic_scholar")
        assert state is not None
        assert state.startup_warning_logged is True

    # =========================================================================
    # TC-WRN-05: No warning for authenticated profile
    # =========================================================================
    @pytest.mark.asyncio
    async def test_no_warning_for_authenticated(self) -> None:
        """Test no warning flag when API key is set.

        Given: S2 config with API key
        When: Rate limiter initializes
        Then: startup_warning_logged is NOT set (no warning needed)
        """
        # Given
        limiter = AcademicAPIRateLimiter()
        mock_config = self._create_mock_config(s2_api_key="test_key")

        # When
        with patch("src.utils.config.get_academic_apis_config", return_value=mock_config):
            await limiter._ensure_provider_initialized("semantic_scholar")

        # Then - verify warning flag is NOT set (no warning for authenticated)
        state = limiter._provider_states.get("semantic_scholar")
        assert state is not None
        assert state.startup_warning_logged is False
