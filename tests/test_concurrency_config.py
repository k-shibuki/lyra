"""
Tests for ConcurrencyConfig and related config classes.

Per ADR-0013/ADR-0014: Worker Resource Contention Control.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|--------------------------------------|-----------------|-------|
| TC-C-01 | Valid concurrency config | Equivalence – normal | Parse success, default values | - |
| TC-C-02 | num_workers: 1 (minimum) | Boundary – minimum | Parse success, num_workers=1 | - |
| TC-C-03 | num_workers: 0 (below min) | Boundary – below minimum | ValidationError | ge=1 constraint |
| TC-C-04 | max_tabs: 1 (minimum) | Boundary – minimum | Parse success, max_tabs=1 | - |
| TC-C-05 | max_tabs: 0 (below min) | Boundary – below minimum | ValidationError | ge=1 constraint |
| TC-C-06 | num_workers: 10 (large) | Equivalence – large value | Parse success | No upper limit |
| TC-C-07 | Missing concurrency section | Boundary – missing section | Default values used | - |
| TC-C-08 | recovery_stable_seconds: 0 | Boundary – below minimum | ValidationError | ge=1 constraint |
| TC-C-09 | decrease_step: 0 | Boundary – below minimum | ValidationError | ge=1 constraint |
| TC-W-01 | Settings with concurrency | Effect – wiring | concurrency field accessible | - |
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.utils.config import (
    AcademicAPIBackoffConfig,
    BackoffConfig,
    BrowserSerpBackoffConfig,
    BrowserSerpConcurrencyConfig,
    ConcurrencyConfig,
    Settings,
    TargetQueueConcurrencyConfig,
)


class TestTargetQueueConcurrencyConfig:
    """Tests for TargetQueueConcurrencyConfig."""

    # =========================================================================
    # TC-C-01: Valid config with defaults
    # =========================================================================
    def test_default_values(self) -> None:
        """Test default configuration values.

        Given: No explicit values provided
        When: TargetQueueConcurrencyConfig is created
        Then: Default num_workers=2 is set
        """
        # Given/When
        config = TargetQueueConcurrencyConfig()

        # Then
        assert config.num_workers == 2

    # =========================================================================
    # TC-C-02: Minimum valid value (num_workers=1)
    # =========================================================================
    def test_num_workers_minimum(self) -> None:
        """Test minimum valid num_workers value.

        Given: num_workers=1 (minimum valid)
        When: Config is created
        Then: Config is valid with num_workers=1
        """
        # Given/When
        config = TargetQueueConcurrencyConfig(num_workers=1)

        # Then
        assert config.num_workers == 1

    # =========================================================================
    # TC-C-03: Below minimum (num_workers=0)
    # =========================================================================
    def test_num_workers_below_minimum(self) -> None:
        """Test num_workers below minimum raises ValidationError.

        Given: num_workers=0 (below minimum)
        When: Config is created
        Then: ValidationError is raised with ge=1 constraint
        """
        # Given/When/Then
        with pytest.raises(ValidationError) as exc_info:
            TargetQueueConcurrencyConfig(num_workers=0)

        # Verify error message contains constraint info
        error_str = str(exc_info.value)
        assert "num_workers" in error_str or "greater than or equal to 1" in error_str

    # =========================================================================
    # TC-C-06: Large value (num_workers=10)
    # =========================================================================
    def test_num_workers_large_value(self) -> None:
        """Test large num_workers value is accepted.

        Given: num_workers=10 (large value)
        When: Config is created
        Then: Config is valid (no upper limit)
        """
        # Given/When
        config = TargetQueueConcurrencyConfig(num_workers=10)

        # Then
        assert config.num_workers == 10


class TestBrowserSerpConcurrencyConfig:
    """Tests for BrowserSerpConcurrencyConfig."""

    # =========================================================================
    # TC-C-04: Minimum valid value (max_tabs=1)
    # =========================================================================
    def test_max_tabs_minimum(self) -> None:
        """Test minimum valid max_tabs value.

        Given: max_tabs=1 (minimum valid, also default)
        When: Config is created
        Then: Config is valid with max_tabs=1
        """
        # Given/When
        config = BrowserSerpConcurrencyConfig(max_tabs=1)

        # Then
        assert config.max_tabs == 1

    # =========================================================================
    # TC-C-05: Below minimum (max_tabs=0)
    # =========================================================================
    def test_max_tabs_below_minimum(self) -> None:
        """Test max_tabs below minimum raises ValidationError.

        Given: max_tabs=0 (below minimum)
        When: Config is created
        Then: ValidationError is raised with ge=1 constraint
        """
        # Given/When/Then
        with pytest.raises(ValidationError) as exc_info:
            BrowserSerpConcurrencyConfig(max_tabs=0)

        # Verify error message contains constraint info
        error_str = str(exc_info.value)
        assert "max_tabs" in error_str or "greater than or equal to 1" in error_str

    def test_default_values(self) -> None:
        """Test default configuration values.

        Given: No explicit values provided
        When: BrowserSerpConcurrencyConfig is created
        Then: Default max_tabs=1 is set
        """
        # Given/When
        config = BrowserSerpConcurrencyConfig()

        # Then
        assert config.max_tabs == 1


class TestBackoffConfig:
    """Tests for BackoffConfig and sub-configs."""

    # =========================================================================
    # TC-C-08: recovery_stable_seconds below minimum
    # =========================================================================
    def test_recovery_stable_seconds_below_minimum(self) -> None:
        """Test recovery_stable_seconds below minimum raises ValidationError.

        Given: recovery_stable_seconds=0 (below minimum)
        When: AcademicAPIBackoffConfig is created
        Then: ValidationError is raised
        """
        # Given/When/Then
        with pytest.raises(ValidationError) as exc_info:
            AcademicAPIBackoffConfig(recovery_stable_seconds=0)

        error_str = str(exc_info.value)
        assert "recovery_stable_seconds" in error_str or "greater than or equal to 1" in error_str

    # =========================================================================
    # TC-C-09: decrease_step below minimum
    # =========================================================================
    def test_decrease_step_below_minimum_academic(self) -> None:
        """Test decrease_step below minimum raises ValidationError (academic).

        Given: decrease_step=0 (below minimum)
        When: AcademicAPIBackoffConfig is created
        Then: ValidationError is raised
        """
        # Given/When/Then
        with pytest.raises(ValidationError) as exc_info:
            AcademicAPIBackoffConfig(decrease_step=0)

        error_str = str(exc_info.value)
        assert "decrease_step" in error_str or "greater than or equal to 1" in error_str

    def test_decrease_step_below_minimum_browser(self) -> None:
        """Test decrease_step below minimum raises ValidationError (browser).

        Given: decrease_step=0 (below minimum)
        When: BrowserSerpBackoffConfig is created
        Then: ValidationError is raised
        """
        # Given/When/Then
        with pytest.raises(ValidationError) as exc_info:
            BrowserSerpBackoffConfig(decrease_step=0)

        error_str = str(exc_info.value)
        assert "decrease_step" in error_str or "greater than or equal to 1" in error_str

    def test_default_values(self) -> None:
        """Test default backoff configuration values.

        Given: No explicit values provided
        When: BackoffConfig is created
        Then: Default values are set for both academic and browser
        """
        # Given/When
        config = BackoffConfig()

        # Then
        assert config.academic_api.recovery_stable_seconds == 60
        assert config.academic_api.decrease_step == 1
        assert config.browser_serp.decrease_step == 1


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig composite class."""

    # =========================================================================
    # TC-C-01: Valid config with defaults
    # =========================================================================
    def test_default_values(self) -> None:
        """Test default ConcurrencyConfig values.

        Given: No explicit values provided
        When: ConcurrencyConfig is created
        Then: All sub-configs have default values
        """
        # Given/When
        config = ConcurrencyConfig()

        # Then
        assert config.target_queue.num_workers == 2
        assert config.browser_serp.max_tabs == 1
        assert config.backoff.academic_api.recovery_stable_seconds == 60
        assert config.backoff.browser_serp.decrease_step == 1

    # =========================================================================
    # TC-C-07: Missing concurrency section uses defaults
    # =========================================================================
    def test_settings_without_concurrency_section(self) -> None:
        """Test Settings without concurrency section uses defaults.

        Given: Settings created with no concurrency data
        When: Accessing concurrency field
        Then: Default ConcurrencyConfig is used
        """
        # Given/When
        settings = Settings()

        # Then
        assert settings.concurrency.target_queue.num_workers == 2
        assert settings.concurrency.browser_serp.max_tabs == 1

    # =========================================================================
    # TC-W-01: Wiring test - Settings includes concurrency
    # =========================================================================
    def test_settings_includes_concurrency(self) -> None:
        """Test Settings includes concurrency field.

        Given: Settings class
        When: Checking for concurrency attribute
        Then: concurrency field exists and is ConcurrencyConfig type
        """
        # Given/When
        settings = Settings()

        # Then
        assert hasattr(settings, "concurrency")
        assert isinstance(settings.concurrency, ConcurrencyConfig)

    def test_custom_values(self) -> None:
        """Test ConcurrencyConfig with custom values.

        Given: Custom values for all sub-configs
        When: ConcurrencyConfig is created
        Then: Custom values are preserved
        """
        # Given
        target_queue = TargetQueueConcurrencyConfig(num_workers=5)
        browser_serp = BrowserSerpConcurrencyConfig(max_tabs=3)
        backoff = BackoffConfig(
            academic_api=AcademicAPIBackoffConfig(
                recovery_stable_seconds=120,
                decrease_step=2,
            ),
            browser_serp=BrowserSerpBackoffConfig(decrease_step=2),
        )

        # When
        config = ConcurrencyConfig(
            target_queue=target_queue,
            browser_serp=browser_serp,
            backoff=backoff,
        )

        # Then
        assert config.target_queue.num_workers == 5
        assert config.browser_serp.max_tabs == 3
        assert config.backoff.academic_api.recovery_stable_seconds == 120
        assert config.backoff.academic_api.decrease_step == 2
        assert config.backoff.browser_serp.decrease_step == 2
