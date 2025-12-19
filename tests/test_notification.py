"""
Tests for notification and manual intervention module.

Test Classification (§7.1.7):
- All tests here are unit tests (no external dependencies)
- External dependencies (database, browser) are mocked

Requirements tested per §3.6.1 (Safe Operation Policy):
- Authentication queue with user-driven completion (no timeout)
- No DOM operations (scroll, highlight, focus) during auth sessions
- Window bring-to-front via OS API only
- Skip domain after 3 consecutive failures
- Cooldown after explicit failures (≥60 minutes)

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-IS-N-01 | InterventionStatus | Equivalence – normal | All statuses defined | - |
| TC-IT-N-01 | InterventionType | Equivalence – normal | All types defined | - |
| TC-IR-N-01 | Success result | Equivalence – normal | Correct defaults | - |
| TC-IR-N-02 | Timeout result | Equivalence – normal | Cooldown set | - |
| TC-IR-N-03 | to_dict | Equivalence – normal | Serializable | - |
| TC-IM-N-01 | max_domain_failures | Equivalence – normal | Returns 3 | §3.1 |
| TC-IM-N-02 | cooldown_minutes | Equivalence – normal | ≥60 min | §3.5 |
| TC-IM-N-03 | Initial failure count | Boundary – zero | Returns 0 | - |
| TC-IM-N-04 | Set/get failures | Equivalence – normal | Value stored | - |
| TC-IM-N-05 | Reset failures | Equivalence – normal | Returns to 0 | - |
| TC-MSG-N-01 | CAPTCHA message | Equivalence – normal | Contains type/domain | - |
| TC-MSG-N-02 | Cloudflare message | Equivalence – normal | Contains type/domain | - |
| TC-MSG-N-03 | Login message | Equivalence – normal | In Japanese | - |
| TC-SK-B-01 | Skip at 0/1/2 failures | Boundary – threshold | False | - |
| TC-SK-B-02 | Skip at 3/4 failures | Boundary – threshold | True | - |
| TC-SK-N-01 | Active cooldown | Equivalence – normal | Skipped | - |
| TC-SK-N-02 | Expired cooldown | Equivalence – normal | Not skipped | - |
| TC-TN-N-01 | is_wsl returns bool | Equivalence – normal | Boolean result | - |
| TC-TN-N-02 | send_toast | Equivalence – normal | Returns bool | - |
| TC-TB-N-01 | Safe CDP command | Equivalence – normal | Page.bringToFront | §3.6.1 |
| TC-TB-A-01 | Forbidden commands | Equivalence – abnormal | Not called | §3.6.1 |
| TC-TB-N-02 | CDP fail fallback | Equivalence – normal | OS API used | - |
| TC-IF-N-01 | Skip 3 failures | Equivalence – normal | SKIPPED status | - |
| TC-IF-N-02 | Returns PENDING | Equivalence – normal | Immediate return | §3.6.1 |
| TC-IF-N-03 | Logs to database | Equivalence – normal | execute called | - |
| TC-IF-N-04 | Success resets | Equivalence – normal | Counter = 0 | - |
| TC-IF-N-05 | Failure increments | Equivalence – normal | Counter +1 | - |
| TC-NU-N-01 | Simple event | Equivalence – normal | shown + event | - |
| TC-NU-N-02 | CAPTCHA event | Equivalence – normal | pending status | §3.6.1 |
| TC-II-N-01 | Full lifecycle | Equivalence – normal | Returns PENDING | §3.6.1 |
| TC-II-N-02 | Complete marks success | Equivalence – normal | Counter reset | - |
| TC-II-N-03 | Check status pending | Equivalence – normal | No timeout | §3.6.1 |
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.notification import (
    InterventionManager,
    InterventionResult,
    InterventionStatus,
    InterventionType,
    notify_user,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_db():
    """Mock database for intervention tests.

    Per §7.1.7: Database should be mocked in unit tests.
    """
    db = AsyncMock()
    db.execute = AsyncMock(return_value=None)
    db.fetch_one = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mock_settings():
    """Mock settings with notification config.

    Note: intervention_timeout has been removed per §3.6.1
    (user-driven completion, no timeout).
    """
    settings = MagicMock()
    return settings


@pytest.fixture
def intervention_manager(mock_settings, mock_db):
    """Create InterventionManager with mocked dependencies.

    Per §7.1.7: External services should be mocked in unit tests.
    """
    with patch("src.utils.notification.get_settings", return_value=mock_settings):
        with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
            manager = InterventionManager()
            yield manager


@pytest.fixture
def mock_page():
    """Mock Playwright page object.

    Per §7.1.7: Chrome/browser should be mocked in unit tests.
    """
    page = AsyncMock()
    page.context = MagicMock()
    page.context.browser = MagicMock()
    page.context.new_cdp_session = AsyncMock()
    page.evaluate = AsyncMock(return_value=True)
    page.content = AsyncMock(return_value="<html><body>Normal page</body></html>")
    return page


@pytest.fixture
def challenge_page():
    """Mock Playwright page with Cloudflare challenge content.

    Per §7.1.3: Test data should be realistic.
    """
    page = AsyncMock()
    page.context = MagicMock()
    page.context.browser = MagicMock()
    page.context.new_cdp_session = AsyncMock()
    page.evaluate = AsyncMock(return_value=True)
    page.content = AsyncMock(
        return_value="""
        <html>
        <head><title>Cloudflare</title></head>
        <body>
            <div id="cf-wrapper">
                <div class="cf-browser-verification">
                    <p>Please wait while we verify your browser...</p>
                    <p>Cloudflare Ray ID: abc123</p>
                </div>
            </div>
        </body>
        </html>
    """
    )
    return page


# =============================================================================
# InterventionStatus Tests
# =============================================================================


@pytest.mark.unit
class TestInterventionStatus:
    """Tests for InterventionStatus enum.

    Verifies all required status values exist per design spec.
    """

    def test_all_statuses_exist(self):
        """Verify all required statuses are defined with correct values."""
        # Given: Expected status mappings
        expected_statuses = {
            "PENDING": "pending",
            "IN_PROGRESS": "in_progress",
            "SUCCESS": "success",
            "TIMEOUT": "timeout",
            "FAILED": "failed",
            "SKIPPED": "skipped",
        }

        # When/Then: Check each status has correct value
        for attr_name, expected_value in expected_statuses.items():
            status = getattr(InterventionStatus, attr_name)
            assert status.value == expected_value, (
                f"InterventionStatus.{attr_name} should be '{expected_value}', got '{status.value}'"
            )


@pytest.mark.unit
class TestInterventionType:
    """Tests for InterventionType enum.

    Verifies all required intervention types per §3.6.
    """

    def test_all_types_exist(self):
        """Verify all required intervention types are defined."""
        # Given: Expected type mappings per §3.6
        expected_types = {
            "CAPTCHA": "captcha",
            "LOGIN_REQUIRED": "login_required",
            "COOKIE_BANNER": "cookie_banner",
            "CLOUDFLARE": "cloudflare",
            "TURNSTILE": "turnstile",
            "JS_CHALLENGE": "js_challenge",
        }

        # When: Assert: Check each type
        for attr_name, expected_value in expected_types.items():
            intervention_type = getattr(InterventionType, attr_name)
            assert intervention_type.value == expected_value, (
                f"InterventionType.{attr_name} should be '{expected_value}', "
                f"got '{intervention_type.value}'"
            )


# =============================================================================
# InterventionResult Tests
# =============================================================================


@pytest.mark.unit
class TestInterventionResult:
    """Tests for InterventionResult class.

    Verifies correct construction and serialization of intervention results.
    """

    def test_success_result_has_correct_defaults(self):
        """Test creating a successful intervention result with default values."""
        # Arrange & Act
        result = InterventionResult(
            intervention_id="test_123",
            status=InterventionStatus.SUCCESS,
            elapsed_seconds=30.5,
        )

        # Then: All fields have expected values
        assert result.intervention_id == "test_123", (
            f"intervention_id should be 'test_123', got '{result.intervention_id}'"
        )
        assert result.status == InterventionStatus.SUCCESS, (
            f"status should be SUCCESS, got {result.status}"
        )
        assert result.elapsed_seconds == 30.5, (
            f"elapsed_seconds should be 30.5, got {result.elapsed_seconds}"
        )
        assert result.should_retry is False, "should_retry should default to False for success"
        assert result.cooldown_until is None, "cooldown_until should default to None"
        assert result.skip_domain_today is False, "skip_domain_today should default to False"

    def test_timeout_result_with_cooldown_per_spec(self):
        """Test creating a timeout intervention result per §3.6.

        Per §3.6: Timeout should trigger cooldown of ≥60 minutes.
        """
        # Given
        cooldown = datetime.now(UTC) + timedelta(minutes=60)

        # When
        result = InterventionResult(
            intervention_id="test_456",
            status=InterventionStatus.TIMEOUT,
            elapsed_seconds=180.0,
            should_retry=True,
            cooldown_until=cooldown,
            notes="Timed out after 180 seconds",
        )

        # Then
        assert result.status == InterventionStatus.TIMEOUT, (
            f"status should be TIMEOUT, got {result.status}"
        )
        assert result.should_retry is True, "should_retry should be True for timeout"
        assert result.cooldown_until == cooldown, (
            f"cooldown_until should be {cooldown}, got {result.cooldown_until}"
        )
        assert result.notes is not None and "180" in result.notes, (
            f"notes should contain timeout duration, got '{result.notes}'"
        )

    def test_to_dict_serialization(self):
        """Test serialization to dict for JSON output."""
        # Given
        result = InterventionResult(
            intervention_id="test_789",
            status=InterventionStatus.SKIPPED,
            skip_domain_today=True,
        )

        # When
        serialized = result.to_dict()

        # Then: Check specific keys and values
        assert serialized["intervention_id"] == "test_789", (
            f"intervention_id should be 'test_789', got '{serialized['intervention_id']}'"
        )
        assert serialized["status"] == "skipped", (
            f"status should be 'skipped', got '{serialized['status']}'"
        )
        assert serialized["skip_domain_today"] is True, "skip_domain_today should be True"
        assert isinstance(serialized, dict), f"Result should be dict, got {type(serialized)}"


# =============================================================================
# InterventionManager Core Tests
# =============================================================================


@pytest.mark.unit
class TestInterventionManagerCore:
    """Core tests for InterventionManager.

    Tests configuration properties and basic functionality per §3.6.1.
    Note: intervention_timeout test removed (timeout no longer used).
    """

    def test_max_domain_failures_is_three_per_spec(self, intervention_manager):
        """Test max domain failures is 3 per §3.1.

        Per §3.1: Skip domain for the day after 3 failures.
        """
        expected_max = 3
        actual_max = intervention_manager.max_domain_failures

        assert actual_max == expected_max, (
            f"max_domain_failures should be {expected_max} per §3.1, got {actual_max}"
        )

    def test_cooldown_at_least_60_minutes_per_spec(self, intervention_manager):
        """Test cooldown is ≥60 minutes per §3.5.

        Per §3.5: Cooldown (minimum 60 minutes).
        """
        actual_cooldown = intervention_manager.cooldown_minutes
        min_cooldown = 60

        assert actual_cooldown >= min_cooldown, (
            f"cooldown_minutes should be >= {min_cooldown} per §3.5, got {actual_cooldown}"
        )

    def test_domain_failure_tracking_initial_state(self, intervention_manager):
        """Test domain failure counter starts at zero."""
        domain = "example.com"
        failures = intervention_manager.get_domain_failures(domain)

        assert failures == 0, f"Initial failure count for '{domain}' should be 0, got {failures}"

    def test_domain_failure_tracking_set_and_get(self, intervention_manager):
        """Test setting and getting domain failure count."""
        domain = "example.com"
        expected_failures = 2

        # When: Set failures
        intervention_manager._domain_failures[domain] = expected_failures
        actual_failures = intervention_manager.get_domain_failures(domain)

        # Then
        assert actual_failures == expected_failures, (
            f"Failure count for '{domain}' should be {expected_failures}, got {actual_failures}"
        )

    def test_domain_failure_reset(self, intervention_manager):
        """Test resetting domain failure counter."""
        domain = "example.com"

        # Given: Set some failures
        intervention_manager._domain_failures[domain] = 2

        # When: Reset
        intervention_manager.reset_domain_failures(domain)

        # Then
        failures = intervention_manager.get_domain_failures(domain)
        assert failures == 0, f"Failure count after reset should be 0, got {failures}"


# =============================================================================
# Challenge Detection Tests - REMOVED per §3.6.1
# =============================================================================
# NOTE: TestChallengeDetection class has been removed.
# _has_challenge_indicators method was deleted per §3.6.1 safe operation policy.
# DOM content inspection during auth sessions is forbidden.


# =============================================================================
# Intervention Message Tests
# =============================================================================


@pytest.mark.unit
class TestInterventionMessages:
    """Tests for intervention message generation.

    Messages should be user-friendly and include relevant context.
    """

    def test_captcha_message_includes_type_and_domain(self, intervention_manager):
        """Test CAPTCHA message includes intervention type and domain."""
        domain = "example.com"

        msg = intervention_manager._build_intervention_message(
            InterventionType.CAPTCHA,
            "https://example.com/page",
            domain,
        )

        assert "CAPTCHA" in msg, f"Message should contain 'CAPTCHA', got: {msg}"
        assert domain in msg, f"Message should contain domain '{domain}', got: {msg}"

    def test_cloudflare_message_includes_type_and_domain(self, intervention_manager):
        """Test Cloudflare message includes intervention type and domain."""
        domain = "example.com"

        msg = intervention_manager._build_intervention_message(
            InterventionType.CLOUDFLARE,
            "https://example.com/page",
            domain,
        )

        assert "Cloudflare" in msg, f"Message should contain 'Cloudflare', got: {msg}"
        assert domain in msg, f"Message should contain domain '{domain}', got: {msg}"

    def test_login_required_message_in_japanese(self, intervention_manager):
        """Test login required message is in Japanese."""
        domain = "example.com"

        msg = intervention_manager._build_intervention_message(
            InterventionType.LOGIN_REQUIRED,
            "https://example.com/page",
            domain,
        )

        assert "ログイン" in msg, f"Message should contain 'ログイン', got: {msg}"
        assert domain in msg, f"Message should contain domain '{domain}', got: {msg}"


# =============================================================================
# Domain Skip Logic Tests (§3.1)
# =============================================================================


@pytest.mark.unit
class TestDomainSkipLogic:
    """Tests for domain skip logic per §3.1.

    Per §3.1: Skip domain for the day after 3 failures (after connection refresh, headful escalation, cooldown applied).
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure_count,should_skip",
        [
            (0, False),  # No failures - should not skip
            (1, False),  # 1 failure - should not skip
            (2, False),  # 2 failures - should not skip (boundary)
            (3, True),  # 3 failures - should skip (threshold)
            (4, True),  # 4 failures - should skip (above threshold)
        ],
    )
    async def test_skip_domain_boundary_conditions(
        self,
        intervention_manager,
        mock_db,
        failure_count,
        should_skip,
    ):
        """Test domain skip at boundary conditions per §3.1.

        Parametrized test verifying skip behavior at 0, 1, 2, 3, 4 failures.
        Per §7.1.2.4: Boundary conditions should be tested.
        """
        domain = "test.com"

        with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
            # Given
            intervention_manager._domain_failures[domain] = failure_count

            # When
            result = await intervention_manager._should_skip_domain(domain)

            # Then
            assert result is should_skip, (
                f"With {failure_count} failures, should_skip should be {should_skip}, got {result}"
            )

    @pytest.mark.asyncio
    async def test_skip_domain_with_active_cooldown(self, intervention_manager, mock_db):
        """Test domain is skipped when in active cooldown period."""
        # Given: Future cooldown time
        future_time = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
        mock_db.fetch_one = AsyncMock(return_value={"cooldown_until": future_time})

        with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
            # When
            result = await intervention_manager._should_skip_domain("test.com")

            # Then
            assert result is True, "Domain with future cooldown time should be skipped"

    @pytest.mark.asyncio
    async def test_no_skip_with_expired_cooldown(self, intervention_manager, mock_db):
        """Test domain is not skipped when cooldown has expired."""
        # Given: Past cooldown time
        past_time = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        mock_db.fetch_one = AsyncMock(return_value={"cooldown_until": past_time})

        with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
            # When
            result = await intervention_manager._should_skip_domain("test.com")

            # Then
            assert result is False, "Domain with expired cooldown should not be skipped"


# =============================================================================
# Toast Notification Tests
# =============================================================================


@pytest.mark.unit
class TestToastNotification:
    """Tests for toast notification functionality.

    Updated for NotificationProvider abstraction.
    Toast notifications now use the provider registry.
    """

    def test_is_wsl_function_returns_boolean(self):
        """Test WSL detection function returns boolean.

        Note: is_wsl() is now a standalone function in notification_provider module,
        not a method of InterventionManager.
        """
        from src.utils.notification_provider import is_wsl

        result = is_wsl()

        assert isinstance(result, bool), f"is_wsl() should return bool, got {type(result)}"

    @pytest.mark.asyncio
    async def test_send_toast_returns_boolean(self, intervention_manager):
        """Test send_toast returns boolean indicating success.

        Updated: send_toast now uses NotificationProviderRegistry
        internally. We mock the registry's send() method.
        """
        from src.utils.notification_provider import (
            NotificationResult,
            reset_notification_registry,
        )

        # Reset registry to ensure clean state
        reset_notification_registry()

        # Mock the registry send method
        mock_result = NotificationResult.success(provider="test", message_id="test_123")

        with patch("src.utils.notification.get_notification_registry") as mock_get_registry:
            mock_registry = AsyncMock()
            mock_registry.send = AsyncMock(return_value=mock_result)
            mock_get_registry.return_value = mock_registry

            # When
            result = await intervention_manager.send_toast(
                "Test Title",
                "Test Message",
                timeout_seconds=5,
            )

            # Then
            assert isinstance(result, bool), f"send_toast should return bool, got {type(result)}"
            assert result is True, "send_toast should return True when provider registry succeeds"

            # Verify registry was called with correct parameters
            mock_registry.send.assert_called_once()

        # Cleanup
        reset_notification_registry()


# =============================================================================
# Tab Bring-to-Front Tests (Safe Mode per §3.6.1)
# =============================================================================


@pytest.mark.unit
class TestTabBringToFront:
    """Tests for browser window bring-to-front functionality per §3.6.1.

    Safe Operation Policy:
    - Uses CDP Page.bringToFront only (allowed)
    - Uses OS API fallback (SetForegroundWindow/wmctrl)
    - Does NOT use Runtime.evaluate or window.focus() (forbidden)
    """

    @pytest.mark.asyncio
    async def test_bring_tab_to_front_uses_cdp_safe_command(self, intervention_manager, mock_page):
        """Test that bring tab to front uses only CDP Page.bringToFront (safe)."""
        # Given
        cdp_session = AsyncMock()
        cdp_session.send = AsyncMock()
        cdp_session.detach = AsyncMock()
        mock_page.context.new_cdp_session = AsyncMock(return_value=cdp_session)

        # When
        await intervention_manager._bring_tab_to_front(mock_page)

        # Then: Uses Page.bringToFront (allowed per §3.6.1)
        cdp_session.send.assert_any_call("Page.bringToFront")

    @pytest.mark.asyncio
    async def test_bring_tab_does_not_use_forbidden_cdp(self, intervention_manager, mock_page):
        """Test that bring tab to front does NOT use forbidden CDP commands.

        Per §3.6.1: Runtime.evaluate, DOM.*, Input.* are forbidden.
        """
        # Given
        cdp_session = AsyncMock()
        cdp_session.send = AsyncMock()
        cdp_session.detach = AsyncMock()
        mock_page.context.new_cdp_session = AsyncMock(return_value=cdp_session)

        # When
        await intervention_manager._bring_tab_to_front(mock_page)

        # Then: No forbidden commands were called
        for call in cdp_session.send.call_args_list:
            command = call[0][0]
            forbidden_prefixes = ["Runtime.evaluate", "DOM.", "Input.", "Emulation."]
            for prefix in forbidden_prefixes:
                assert not command.startswith(prefix), (
                    f"Forbidden CDP command '{command}' was called. Per §3.6.1, "
                    f"only Page.navigate, Network.enable, Page.bringToFront are allowed."
                )

    @pytest.mark.asyncio
    async def test_bring_tab_to_front_falls_back_to_os_api(self, intervention_manager):
        """Test graceful fallback to OS API when CDP connection fails."""
        # Given
        page = AsyncMock()
        page.context.new_cdp_session = AsyncMock(side_effect=Exception("CDP error"))

        with patch.object(
            intervention_manager, "_platform_activate_window", new_callable=AsyncMock
        ) as mock_activate:
            # When
            await intervention_manager._bring_tab_to_front(page)

            # Then: OS API fallback should be called
            mock_activate.assert_called_once()


# =============================================================================
# Element Highlighting Tests - REMOVED per §3.6.1
# =============================================================================
# NOTE: TestElementHighlighting class has been removed.
# _highlight_element method was deleted per §3.6.1 safe operation policy.
# DOM operations (scroll, highlight) during auth sessions are forbidden.


# =============================================================================
# Full Intervention Flow Tests (Updated per §3.6.1)
# =============================================================================


@pytest.mark.unit
class TestInterventionFlow:
    """Tests for the intervention flow per §3.6.1.

    Key behavior changes per §3.6.1:
    - request_intervention returns PENDING immediately (no waiting)
    - No timeout enforcement (user-driven completion)
    - User calls complete_authentication when done
    """

    @pytest.mark.asyncio
    async def test_skips_domain_with_three_failures(self, mock_settings, mock_db):
        """Test intervention is skipped for domains with 3 failures per §3.1."""
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                # Given
                manager = InterventionManager()
                domain = "blocked.com"
                manager._domain_failures[domain] = 3

                # When
                result = await manager.request_intervention(
                    intervention_type=InterventionType.CAPTCHA,
                    url=f"https://{domain}/page",
                    domain=domain,
                )

                # Then
                assert result.status == InterventionStatus.SKIPPED, (
                    f"Expected SKIPPED status, got {result.status}"
                )
                assert result.skip_domain_today is True, "skip_domain_today should be True"

    @pytest.mark.asyncio
    async def test_returns_pending_immediately_per_spec(self, mock_settings, mock_db, mock_page):
        """Test intervention returns PENDING immediately per §3.6.1.

        Per §3.6.1: No waiting/polling. Returns PENDING for user to complete.
        """
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                # Given
                manager = InterventionManager()

                with patch.object(manager, "send_toast", new_callable=AsyncMock, return_value=True):
                    with patch.object(manager, "_bring_tab_to_front", new_callable=AsyncMock):
                        # When
                        result = await manager.request_intervention(
                            intervention_type=InterventionType.CAPTCHA,
                            url="https://example.com/page",
                            domain="example.com",
                            page=mock_page,
                        )

                        # Then: Should return PENDING immediately
                        assert result.status == InterventionStatus.PENDING, (
                            f"Expected PENDING status per §3.6.1, got {result.status}"
                        )
                        assert "complete_authentication" in (result.notes or ""), (
                            "Notes should mention complete_authentication method"
                        )

    @pytest.mark.asyncio
    async def test_logs_intervention_to_database(self, intervention_manager, mock_db, mock_page):
        """Test intervention request logs to database."""
        with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
            with patch.object(
                intervention_manager,
                "send_toast",
                new_callable=AsyncMock,
                return_value=True,
            ):
                with patch.object(
                    intervention_manager,
                    "_bring_tab_to_front",
                    new_callable=AsyncMock,
                ):
                    # When
                    await intervention_manager.request_intervention(
                        intervention_type=InterventionType.CAPTCHA,
                        url="https://example.com/page",
                        domain="example.com",
                        page=mock_page,
                    )

                    # Then
                    assert mock_db.execute.called, (
                        "Database execute should be called to log intervention"
                    )

    @pytest.mark.asyncio
    async def test_success_resets_failure_counter(self, intervention_manager, mock_db):
        """Test successful intervention resets failure counter to 0."""
        # Given
        domain = "example.com"
        intervention_manager._domain_failures[domain] = 2

        with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
            result = InterventionResult(
                intervention_id="test",
                status=InterventionStatus.SUCCESS,
            )

            # When
            await intervention_manager._handle_intervention_result(
                result,
                {
                    "domain": domain,
                    "type": InterventionType.CAPTCHA,
                    "task_id": None,
                },
                mock_db,
            )

            # Then
            failures = intervention_manager._domain_failures[domain]
            assert failures == 0, f"Failure count after success should be 0, got {failures}"

    @pytest.mark.asyncio
    async def test_failure_increments_counter(self, intervention_manager, mock_db):
        """Test failed intervention increments failure counter."""
        # Given
        domain = "example.com"
        initial_failures = 1
        intervention_manager._domain_failures[domain] = initial_failures

        with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
            result = InterventionResult(
                intervention_id="test",
                status=InterventionStatus.FAILED,  # Changed from TIMEOUT
            )

            # When
            await intervention_manager._handle_intervention_result(
                result,
                {
                    "domain": domain,
                    "type": InterventionType.CAPTCHA,
                    "task_id": None,
                },
                mock_db,
            )

            # Then
            failures = intervention_manager._domain_failures[domain]
            expected = initial_failures + 1
            assert failures == expected, f"Failure count should be {expected}, got {failures}"


# =============================================================================
# notify_user Function Tests
# =============================================================================


@pytest.mark.unit
class TestNotifyUserFunction:
    """Tests for the notify_user convenience function per §3.6.1."""

    @pytest.mark.asyncio
    async def test_simple_event_returns_shown_and_event(self, mock_settings, mock_db):
        """Test notify_user with simple event (no intervention)."""
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                # Reset global manager
                import src.utils.notification as notif_module

                notif_module._manager = None

                with patch.object(
                    InterventionManager,
                    "send_toast",
                    new_callable=AsyncMock,
                    return_value=True,
                ):
                    # When
                    result = await notify_user(
                        "info",
                        {"message": "Task completed"},
                    )

                    # Then
                    assert result["shown"] is True, (
                        "Result 'shown' should be True when toast succeeds"
                    )
                    assert result["event"] == "info", (
                        f"Result 'event' should be 'info', got '{result['event']}'"
                    )

    @pytest.mark.asyncio
    async def test_captcha_event_returns_pending_per_spec(self, mock_settings, mock_db):
        """Test notify_user with captcha event returns PENDING per §3.6.1.

        Per §3.6.1: Intervention returns PENDING immediately for user to complete.
        """
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                # Reset global manager
                import src.utils.notification as notif_module

                notif_module._manager = None

                with patch.object(
                    InterventionManager,
                    "request_intervention",
                    new_callable=AsyncMock,
                    return_value=InterventionResult(
                        intervention_id="test",
                        status=InterventionStatus.PENDING,
                        notes="Awaiting user completion via complete_authentication",
                    ),
                ):
                    # When
                    result = await notify_user(
                        "captcha",
                        {
                            "url": "https://example.com",
                            "domain": "example.com",
                        },
                    )

                    # Then: Should be PENDING per §3.6.1
                    assert result["status"] == "pending", (
                        f"Result 'status' should be 'pending' per §3.6.1, got '{result['status']}'"
                    )


# =============================================================================
# Integration-style Tests (still unit - using mocks) - Updated per §3.6.1
# =============================================================================


@pytest.mark.unit
class TestInterventionIntegration:
    """Integration-style tests for intervention flows (mocked) per §3.6.1.

    Tests complete flows end-to-end with mocked dependencies.

    Key changes per §3.6.1:
    - No timeout enforcement (user-driven completion)
    - Returns PENDING immediately
    - No element_selector or on_success_callback parameters
    """

    @pytest.mark.asyncio
    async def test_full_lifecycle_returns_pending_per_spec(self, mock_settings, mock_db, mock_page):
        """Test full intervention lifecycle returns PENDING per §3.6.1."""
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                # Given
                manager = InterventionManager()
                domain = "example.com"

                with patch.object(manager, "send_toast", new_callable=AsyncMock, return_value=True):
                    with patch.object(manager, "_bring_tab_to_front", new_callable=AsyncMock):
                        # When: Per §3.6.1, no element_selector or on_success_callback
                        result = await manager.request_intervention(
                            intervention_type=InterventionType.CLOUDFLARE,
                            url=f"https://{domain}",
                            domain=domain,
                            page=mock_page,
                        )

                        # Then: Should return PENDING immediately
                        assert result.status == InterventionStatus.PENDING, (
                            f"Expected PENDING status per §3.6.1, got {result.status}"
                        )

    @pytest.mark.asyncio
    async def test_complete_intervention_marks_success(self, mock_settings, mock_db):
        """Test complete_intervention marks intervention as successful.

        Per §3.6.1: User calls complete_authentication when done.
        """
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                # Given
                manager = InterventionManager()
                domain = "example.com"
                intervention_id = f"{domain}_test123"

                # Simulate pending intervention
                manager._pending_interventions[intervention_id] = {
                    "id": intervention_id,
                    "type": InterventionType.CAPTCHA,
                    "domain": domain,
                    "started_at": datetime.now(UTC),
                }
                manager._domain_failures[domain] = 2

                # When: User completes intervention
                await manager.complete_intervention(
                    intervention_id=intervention_id,
                    success=True,
                    notes="User resolved CAPTCHA",
                )

                # Then: Failure counter should be reset
                failures = manager.get_domain_failures(domain)
                assert failures == 0, f"Failure count after success should be 0, got {failures}"

                # Then: Intervention removed from pending
                assert intervention_id not in manager._pending_interventions, (
                    "Completed intervention should be removed from pending"
                )

    @pytest.mark.asyncio
    async def test_check_status_shows_pending_without_timeout(self, mock_settings, mock_db):
        """Test check_intervention_status shows pending without timeout per §3.6.1.

        Per §3.6.1: No timeout enforcement - user-driven completion only.
        """
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                # Given
                manager = InterventionManager()
                intervention_id = "test_domain_123"

                # Simulate a pending intervention started 10 minutes ago
                manager._pending_interventions[intervention_id] = {
                    "id": intervention_id,
                    "started_at": datetime.now(UTC) - timedelta(minutes=10),
                }

                # When
                status = await manager.check_intervention_status(intervention_id)

                # Then: Should still be pending (no timeout per §3.6.1)
                assert status["status"] == "pending", (
                    f"Expected 'pending' status per §3.6.1, got '{status['status']}'"
                )
                assert "elapsed_seconds" in status, "Status should include elapsed_seconds"
                assert "note" in status, "Status should include note about user completion"


# =============================================================================
# K.3-8: Domain Blocked Notification Tests
# =============================================================================


class TestDomainBlockedNotification:
    """Tests for domain_blocked notification (K.3-8).

    Test Perspectives Table:
    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-DB-N-01 | InterventionType.DOMAIN_BLOCKED | Equiv – normal | Enum value defined | - |
    | TC-DB-N-02 | notify_user domain_blocked | Equiv – normal | Queue + toast | - |
    | TC-DB-N-03 | notify_domain_blocked helper | Equiv – normal | Correct result | - |
    | TC-DB-A-01 | Missing domain | Boundary – empty | Uses "unknown" | - |
    | TC-DB-A-02 | Missing reason | Boundary – empty | Uses default | - |
    """

    def test_intervention_type_includes_domain_blocked(self):
        """
        TC-DB-N-01: InterventionType should include DOMAIN_BLOCKED.

        // Given: InterventionType enum
        // When: Checking values
        // Then: DOMAIN_BLOCKED should be defined with value "domain_blocked"
        """
        assert hasattr(InterventionType, "DOMAIN_BLOCKED")
        assert InterventionType.DOMAIN_BLOCKED.value == "domain_blocked"

    @pytest.mark.asyncio
    async def test_notify_user_domain_blocked_queues_and_notifies(self, mock_settings, mock_db):
        """
        TC-DB-N-02: notify_user with domain_blocked should queue and send toast.

        // Given: domain_blocked event with valid payload
        // When: Calling notify_user
        // Then: Item queued, toast sent, queue_id returned
        """
        from src.utils.notification import notify_user

        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                # Mock the queue
                mock_queue = AsyncMock()
                mock_queue.enqueue = AsyncMock(return_value="iq_test123")

                # Mock the manager
                mock_manager = MagicMock()
                mock_manager.send_toast = AsyncMock(return_value=True)

                with patch("src.utils.notification._get_manager", return_value=mock_manager):
                    with patch(
                        "src.utils.notification.get_intervention_queue", return_value=mock_queue
                    ):
                        # When
                        result = await notify_user(
                            event="domain_blocked",
                            payload={
                                "domain": "bad-site.com",
                                "reason": "High rejection rate (75%)",
                                "task_id": "task_123",
                                "url": "https://bad-site.com/page",
                            },
                        )

                        # Then: Queue was called
                        mock_queue.enqueue.assert_called_once()
                        call_kwargs = mock_queue.enqueue.call_args[1]
                        assert call_kwargs["domain"] == "bad-site.com"
                        assert call_kwargs["auth_type"] == "domain_blocked"
                        assert call_kwargs["priority"] == "low"

                        # Then: Toast was sent
                        mock_manager.send_toast.assert_called_once()

                        # Then: Result has expected fields
                        assert result["shown"] is True
                        assert result["event"] == "domain_blocked"
                        assert result["domain"] == "bad-site.com"
                        assert result["reason"] == "High rejection rate (75%)"
                        assert result["queue_id"] == "iq_test123"

    @pytest.mark.asyncio
    async def test_notify_domain_blocked_convenience_function(self, mock_settings, mock_db):
        """
        TC-DB-N-03: notify_domain_blocked helper should work correctly.

        // Given: Domain and reason
        // When: Calling notify_domain_blocked
        // Then: Correct result returned
        """
        from src.utils.notification import notify_domain_blocked

        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                mock_queue = AsyncMock()
                mock_queue.enqueue = AsyncMock(return_value="iq_conv123")

                mock_manager = MagicMock()
                mock_manager.send_toast = AsyncMock(return_value=True)

                with patch("src.utils.notification._get_manager", return_value=mock_manager):
                    with patch(
                        "src.utils.notification.get_intervention_queue", return_value=mock_queue
                    ):
                        # When
                        result = await notify_domain_blocked(
                            domain="blocked.example.com",
                            reason="Dangerous pattern detected",
                            task_id="task_456",
                        )

                        # Then
                        assert result["domain"] == "blocked.example.com"
                        assert result["reason"] == "Dangerous pattern detected"
                        assert result["queue_id"] == "iq_conv123"

    @pytest.mark.asyncio
    async def test_notify_user_domain_blocked_missing_domain(self, mock_settings, mock_db):
        """
        TC-DB-A-01: notify_user domain_blocked with missing domain uses "unknown".

        // Given: domain_blocked event without domain
        // When: Calling notify_user
        // Then: Uses "unknown" as domain
        """
        from src.utils.notification import notify_user

        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                mock_queue = AsyncMock()
                mock_queue.enqueue = AsyncMock(return_value="iq_unknown")

                mock_manager = MagicMock()
                mock_manager.send_toast = AsyncMock(return_value=True)

                with patch("src.utils.notification._get_manager", return_value=mock_manager):
                    with patch(
                        "src.utils.notification.get_intervention_queue", return_value=mock_queue
                    ):
                        # When: No domain provided
                        result = await notify_user(
                            event="domain_blocked",
                            payload={"reason": "Test reason"},
                        )

                        # Then: Uses "unknown" as domain
                        call_kwargs = mock_queue.enqueue.call_args[1]
                        assert call_kwargs["domain"] == "unknown"
                        assert result["domain"] == "unknown"

    @pytest.mark.asyncio
    async def test_notify_user_domain_blocked_missing_reason(self, mock_settings, mock_db):
        """
        TC-DB-A-02: notify_user domain_blocked with missing reason uses default.

        // Given: domain_blocked event without reason
        // When: Calling notify_user
        // Then: Uses default reason "Verification failure"
        """
        from src.utils.notification import notify_user

        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", new=AsyncMock(return_value=mock_db)):
                mock_queue = AsyncMock()
                mock_queue.enqueue = AsyncMock(return_value="iq_noreason")

                mock_manager = MagicMock()
                mock_manager.send_toast = AsyncMock(return_value=True)

                with patch("src.utils.notification._get_manager", return_value=mock_manager):
                    with patch(
                        "src.utils.notification.get_intervention_queue", return_value=mock_queue
                    ):
                        # When: No reason provided
                        result = await notify_user(
                            event="domain_blocked",
                            payload={"domain": "test.com"},
                        )

                        # Then: Uses default reason
                        assert result["reason"] == "Verification failure"
