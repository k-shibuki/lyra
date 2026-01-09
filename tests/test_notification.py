"""
Tests for notification and manual intervention module.

Test Classification (.1.7):
- All tests here are unit tests (no external dependencies)
- External dependencies (database, browser) are mocked

Requirements tested per ADR-0007 (Safe Operation Policy):
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
| TC-IM-N-01 | max_domain_failures | Equivalence – normal | Returns 3 | ADR-0010 |
| TC-IM-N-02 | cooldown_minutes | Equivalence – normal | ≥60 min | ADR-0006 |
| TC-IM-N-03 | Initial failure count | Boundary – zero | Returns 0 | - |
| TC-IM-N-04 | Set/get failures | Equivalence – normal | Value stored | - |
| TC-IM-N-05 | Reset failures | Equivalence – normal | Returns to 0 | - |
| TC-MSG-N-01 | CAPTCHA message | Equivalence – normal | Generic title + domain | ADR-0007 |
| TC-MSG-N-02 | Cloudflare message | Equivalence – normal | Generic title + domain | ADR-0007 |
| TC-MSG-N-03 | Login message | Equivalence – normal | In English | Unified language |
| TC-SK-B-01 | Skip at 0/1/2 failures | Boundary – threshold | False | - |
| TC-SK-B-02 | Skip at 3/4 failures | Boundary – threshold | True | - |
| TC-SK-N-01 | Active cooldown | Equivalence – normal | Skipped | - |
| TC-SK-N-02 | Expired cooldown | Equivalence – normal | Not skipped | - |
| TC-TN-N-01 | is_wsl returns bool | Equivalence – normal | Boolean result | - |
| TC-TN-N-02 | send_toast | Equivalence – normal | Returns bool | - |
| TC-TB-N-01 | Safe CDP command | Equivalence – normal | Page.bringToFront | ADR-0007 |
| TC-TB-A-01 | Forbidden commands | Equivalence – abnormal | Not called | ADR-0007 |
| TC-TB-N-02 | CDP fail fallback | Equivalence – normal | OS API used | - |
| TC-IF-N-01 | Skip 3 failures | Equivalence – normal | SKIPPED status | - |
| TC-IF-N-02 | Returns PENDING | Equivalence – normal | Immediate return | ADR-0007 |
| TC-IF-N-03 | Logs to database | Equivalence – normal | execute called | - |
| TC-IF-N-04 | Success resets | Equivalence – normal | Counter = 0 | - |
| TC-IF-N-05 | Failure increments | Equivalence – normal | Counter +1 | - |
| TC-NU-N-01 | Simple event | Equivalence – normal | shown + event | - |
| TC-NU-N-02 | CAPTCHA event | Equivalence – normal | pending status | ADR-0007 |
| TC-II-N-01 | Full lifecycle | Equivalence – normal | Returns PENDING | ADR-0007 |
| TC-II-N-02 | Complete marks success | Equivalence – normal | Counter reset | - |
| TC-II-N-03 | Check status pending | Equivalence – normal | No timeout | ADR-0007 |
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.intervention_manager import InterventionManager, notify_user
from src.utils.intervention_types import (
    InterventionResult,
    InterventionStatus,
    InterventionType,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_db() -> AsyncMock:
    """Mock database for intervention tests.

    Per .1.7: Database should be mocked in unit tests.
    """
    db = AsyncMock()
    db.execute = AsyncMock(return_value=None)
    db.fetch_one = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mock_settings() -> MagicMock:
    """Mock settings with notification config.

    Note: intervention_timeout has been removed per ADR-0007
    (user-driven completion, no timeout).
    """
    settings = MagicMock()
    return settings


@pytest.fixture
def intervention_manager(
    mock_settings: MagicMock, mock_db: AsyncMock
) -> Generator[InterventionManager]:
    """Create InterventionManager with mocked dependencies.

    Per .1.7: External services should be mocked in unit tests.
    """
    with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
        with patch(
            "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
        ):
            manager = InterventionManager()
            yield manager


@pytest.fixture
def mock_page() -> AsyncMock:
    """Mock Playwright page object.

    Per .1.7: Chrome/browser should be mocked in unit tests.
    """
    page = AsyncMock()
    page.context = MagicMock()
    page.context.browser = MagicMock()
    page.context.new_cdp_session = AsyncMock()
    page.evaluate = AsyncMock(return_value=True)
    page.content = AsyncMock(return_value="<html><body>Normal page</body></html>")
    return page


@pytest.fixture
def challenge_page() -> AsyncMock:
    """Mock Playwright page with Cloudflare challenge content.

    Per .1.3: Test data should be realistic.
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

    def test_all_statuses_exist(self) -> None:
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
            assert (
                status.value == expected_value
            ), f"InterventionStatus.{attr_name} should be '{expected_value}', got '{status.value}'"


@pytest.mark.unit
class TestInterventionType:
    """Tests for InterventionType enum.

    Verifies all required intervention types per ADR-0007.
    """

    def test_all_types_exist(self) -> None:
        """Verify all required intervention types are defined."""
        # Given: Expected type mappings per ADR-0007
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

    def test_success_result_has_correct_defaults(self) -> None:
        """Test creating a successful intervention result with default values."""
        # Arrange & Act
        result = InterventionResult(
            intervention_id="test_123",
            status=InterventionStatus.SUCCESS,
            elapsed_seconds=30.5,
        )

        # Then: All fields have expected values
        assert (
            result.intervention_id == "test_123"
        ), f"intervention_id should be 'test_123', got '{result.intervention_id}'"
        assert (
            result.status == InterventionStatus.SUCCESS
        ), f"status should be SUCCESS, got {result.status}"
        assert (
            result.elapsed_seconds == 30.5
        ), f"elapsed_seconds should be 30.5, got {result.elapsed_seconds}"
        assert result.should_retry is False, "should_retry should default to False for success"
        assert result.cooldown_until is None, "cooldown_until should default to None"
        assert result.skip_domain_today is False, "skip_domain_today should default to False"

    def test_timeout_result_with_cooldown_per_spec(self) -> None:
        """Test creating a timeout intervention result per ADR-0007.

        Per ADR-0007: Timeout should trigger cooldown of ≥60 minutes.
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
        assert (
            result.status == InterventionStatus.TIMEOUT
        ), f"status should be TIMEOUT, got {result.status}"
        assert result.should_retry is True, "should_retry should be True for timeout"
        assert (
            result.cooldown_until == cooldown
        ), f"cooldown_until should be {cooldown}, got {result.cooldown_until}"
        assert (
            result.notes is not None and "180" in result.notes
        ), f"notes should contain timeout duration, got '{result.notes}'"

    def test_to_dict_serialization(self) -> None:
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
        assert (
            serialized["intervention_id"] == "test_789"
        ), f"intervention_id should be 'test_789', got '{serialized['intervention_id']}'"
        assert (
            serialized["status"] == "skipped"
        ), f"status should be 'skipped', got '{serialized['status']}'"
        assert serialized["skip_domain_today"] is True, "skip_domain_today should be True"
        assert isinstance(serialized, dict), f"Result should be dict, got {type(serialized)}"


# =============================================================================
# InterventionManager Core Tests
# =============================================================================


@pytest.mark.unit
class TestInterventionManagerCore:
    """Core tests for InterventionManager.

    Tests configuration properties and basic functionality per ADR-0007.
    """

    def test_cooldown_at_least_60_minutes_per_spec(
        self, intervention_manager: InterventionManager
    ) -> None:
        """Test cooldown is ≥60 minutes per ADR-0006.

        Per ADR-0006: Cooldown (minimum 60 minutes).
        """
        actual_cooldown = intervention_manager.cooldown_minutes
        min_cooldown = 60

        assert (
            actual_cooldown >= min_cooldown
        ), f"cooldown_minutes should be >= {min_cooldown} per ADR-0006, got {actual_cooldown}"


# =============================================================================
# Challenge Detection Tests - REMOVED per ADR-0007
# =============================================================================
# NOTE: TestChallengeDetection class has been removed.
# _has_challenge_indicators method was deleted per ADR-0007 safe operation policy.
# DOM content inspection during auth sessions is forbidden.


# =============================================================================
# Intervention Message Tests
# =============================================================================


@pytest.mark.unit
class TestInterventionMessages:
    """Tests for intervention message generation.

    Messages should be user-friendly and include relevant context.
    Uses unified challenge messages from intervention_types module.
    """

    def test_captcha_message_uses_generic_title(self) -> None:
        """Test CAPTCHA message uses generic title (no type exposure)."""
        from src.utils.intervention_types import InterventionType, get_challenge_message

        domain = "example.com"
        url = "https://example.com/page"
        msg = get_challenge_message(InterventionType.CAPTCHA)
        title, body = msg.format_popup(domain, url)

        # Title should be generic (not expose challenge type per ADR-0007)
        assert "Manual Action Required" in title, f"Title should be generic, got: {title}"
        assert domain in body, f"Body should contain domain '{domain}', got: {body}"

    def test_cloudflare_message_uses_generic_title(self) -> None:
        """Test Cloudflare message uses generic title (no type exposure)."""
        from src.utils.intervention_types import InterventionType, get_challenge_message

        domain = "example.com"
        url = "https://example.com/page"
        msg = get_challenge_message(InterventionType.CLOUDFLARE)
        title, body = msg.format_popup(domain, url)

        # Title should be generic (not expose challenge type per ADR-0007)
        assert "Manual Action Required" in title, f"Title should be generic, got: {title}"
        assert domain in body, f"Body should contain domain '{domain}', got: {body}"

    def test_login_required_message_in_english(self) -> None:
        """Test login required message is in English (unified language)."""
        from src.utils.intervention_types import InterventionType, get_challenge_message

        domain = "example.com"
        url = "https://example.com/page"
        msg = get_challenge_message(InterventionType.LOGIN_REQUIRED)
        title, body = msg.format_popup(domain, url)

        assert "Login" in title, f"Title should contain 'Login', got: {title}"
        assert domain in body, f"Body should contain domain '{domain}', got: {body}"

    def test_message_includes_action_instructions(self) -> None:
        """Test messages include resolve/skip action instructions."""
        from src.utils.intervention_types import InterventionType, get_challenge_message

        domain = "example.com"
        url = "https://example.com/page"
        msg = get_challenge_message(InterventionType.CAPTCHA)
        title, body = msg.format_popup(domain, url)

        assert "resolved" in body.lower(), f"Body should mention 'resolved' action, got: {body}"
        assert "skip" in body.lower(), f"Body should mention 'skip' action, got: {body}"

    def test_mcp_format_structure(self) -> None:
        """Test MCP format returns proper structure."""
        from src.utils.intervention_types import InterventionType, get_challenge_message

        domain = "example.com"
        url = "https://example.com/page"
        queue_id = "iq_abc123"
        msg = get_challenge_message(InterventionType.CAPTCHA)
        mcp_data = msg.format_mcp(domain, url, queue_id)

        assert mcp_data["challenge_detected"] is True
        assert mcp_data["domain"] == domain
        assert mcp_data["url"] == url
        assert mcp_data["queue_id"] == queue_id
        assert "actions" in mcp_data
        assert "resolve" in mcp_data["actions"]
        assert "skip" in mcp_data["actions"]


# =============================================================================
# Domain Skip Logic Tests (ADR-0010)
# =============================================================================

# =============================================================================
# Toast Notification Tests
# =============================================================================


@pytest.mark.unit
class TestToastNotification:
    """Tests for toast notification functionality.

    Updated for NotificationProvider abstraction.
    Toast notifications now use the provider registry.
    """

    def test_is_wsl_function_returns_boolean(self) -> None:
        """Test WSL detection function returns boolean.

        Note: is_wsl() is now a standalone function in notification_provider module,
        not a method of InterventionManager.
        """
        from src.utils.notification_provider import is_wsl

        result = is_wsl()

        assert isinstance(result, bool), f"is_wsl() should return bool, got {type(result)}"

    @pytest.mark.asyncio
    async def test_send_toast_returns_boolean(
        self, intervention_manager: InterventionManager
    ) -> None:
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

        with patch("src.utils.intervention_manager.get_notification_registry") as mock_get_registry:
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
# Tab Bring-to-Front Tests (Safe Mode per ADR-0007)
# =============================================================================


@pytest.mark.unit
class TestTabBringToFront:
    """Tests for browser window bring-to-front functionality per ADR-0007.

    Safe Operation Policy:
    - Uses CDP Page.bringToFront only (allowed)
    - Uses OS API fallback (SetForegroundWindow/wmctrl)
    - Does NOT use Runtime.evaluate or window.focus() (forbidden)
    """

    @pytest.mark.asyncio
    async def test_bring_tab_to_front_uses_cdp_safe_command(
        self, intervention_manager: InterventionManager, mock_page: AsyncMock
    ) -> None:
        """Test that bring tab to front uses only CDP Page.bringToFront (safe)."""
        # Given
        cdp_session = AsyncMock()
        cdp_session.send = AsyncMock()
        cdp_session.detach = AsyncMock()
        mock_page.context.new_cdp_session = AsyncMock(return_value=cdp_session)

        # When
        await intervention_manager._bring_tab_to_front(mock_page)

        # Then: Uses Page.bringToFront (allowed per ADR-0007)
        cdp_session.send.assert_any_call("Page.bringToFront")

    @pytest.mark.asyncio
    async def test_bring_tab_does_not_use_forbidden_cdp(
        self, intervention_manager: InterventionManager, mock_page: AsyncMock
    ) -> None:
        """Test that bring tab to front does NOT use forbidden CDP commands.

        Per ADR-0007: Runtime.evaluate, DOM.*, Input.* are forbidden.
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
                    f"Forbidden CDP command '{command}' was called. Per ADR-0007, "
                    f"only Page.navigate, Network.enable, Page.bringToFront are allowed."
                )

    @pytest.mark.asyncio
    async def test_bring_tab_to_front_falls_back_to_os_api(
        self, intervention_manager: InterventionManager
    ) -> None:
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
# Element Highlighting Tests - REMOVED per ADR-0007
# =============================================================================
# NOTE: TestElementHighlighting class has been removed.
# _highlight_element method was deleted per ADR-0007 safe operation policy.
# DOM operations (scroll, highlight) during auth sessions are forbidden.


# =============================================================================
# Full Intervention Flow Tests (Updated per ADR-0007)
# =============================================================================


@pytest.mark.unit
class TestInterventionFlow:
    """Tests for the intervention flow per ADR-0007.

    Key behavior changes per ADR-0007:
    - request_intervention returns PENDING immediately (no waiting)
    - No timeout enforcement (user-driven completion)
    - User calls complete_authentication when done
    """

    @pytest.mark.asyncio
    async def test_returns_pending_immediately_per_spec(
        self, mock_settings: MagicMock, mock_db: AsyncMock, mock_page: AsyncMock
    ) -> None:
        """Test intervention returns PENDING immediately per ADR-0007.

        Per ADR-0007: No waiting/polling. Returns PENDING for user to complete.
        """
        with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
            with patch(
                "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
            ):
                # Given
                manager = InterventionManager()

                with patch.object(manager, "send_toast", new_callable=AsyncMock, return_value=True):
                    with patch.object(
                        manager, "_bring_tab_to_front", new_callable=AsyncMock
                    ) as mock_bring:
                        # When
                        result = await manager.request_intervention(
                            intervention_type=InterventionType.CAPTCHA,
                            url="https://example.com/page",
                            domain="example.com",
                            page=mock_page,
                        )

                        # Then: Should return PENDING immediately
                        assert (
                            result.status == InterventionStatus.PENDING
                        ), f"Expected PENDING status per ADR-0007, got {result.status}"
                        assert "complete_authentication" in (
                            result.notes or ""
                        ), "Notes should mention complete_authentication method"
                        # Then: Must NOT steal focus during request_intervention
                        mock_bring.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_logs_intervention_to_database(
        self, intervention_manager: InterventionManager, mock_db: AsyncMock, mock_page: AsyncMock
    ) -> None:
        """Test intervention request logs to database."""
        with patch(
            "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
        ):
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
                ) as mock_bring:
                    # When
                    await intervention_manager.request_intervention(
                        intervention_type=InterventionType.CAPTCHA,
                        url="https://example.com/page",
                        domain="example.com",
                        page=mock_page,
                    )

                    # Then
                    assert (
                        mock_db.execute.called
                    ), "Database execute should be called to log intervention"
                    # Then: Must NOT steal focus during request_intervention
                    mock_bring.assert_not_awaited()


# =============================================================================
# notify_user Function Tests
# =============================================================================


@pytest.mark.unit
class TestNotifyUserFunction:
    """Tests for the notify_user convenience function per ADR-0007."""

    @pytest.mark.asyncio
    async def test_simple_event_returns_shown_and_event(
        self, mock_settings: MagicMock, mock_db: AsyncMock
    ) -> None:
        """Test notify_user with simple event (no intervention)."""
        with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
            with patch(
                "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
            ):
                # Reset global manager
                import src.utils.intervention_manager as intervention_module

                intervention_module._manager = None

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
                    assert (
                        result["shown"] is True
                    ), "Result 'shown' should be True when toast succeeds"
                    assert (
                        result["event"] == "info"
                    ), f"Result 'event' should be 'info', got '{result['event']}'"

    @pytest.mark.asyncio
    async def test_captcha_event_returns_pending_per_spec(
        self, mock_settings: MagicMock, mock_db: AsyncMock
    ) -> None:
        """Test notify_user with captcha event returns PENDING per ADR-0007.

        Per ADR-0007: Intervention returns PENDING immediately for user to complete.
        """
        with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
            with patch(
                "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
            ):
                # Reset global manager
                import src.utils.intervention_manager as intervention_module

                intervention_module._manager = None

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

                    # Then: Should be PENDING per ADR-0007
                    assert (
                        result["status"] == "pending"
                    ), f"Result 'status' should be 'pending' per ADR-0007, got '{result['status']}'"


# =============================================================================
# Integration-style Tests (still unit - using mocks) - Updated per ADR-0007
# =============================================================================


@pytest.mark.unit
class TestInterventionIntegration:
    """Integration-style tests for intervention flows (mocked) per ADR-0007.

    Tests complete flows end-to-end with mocked dependencies.

    Key changes per ADR-0007:
    - No timeout enforcement (user-driven completion)
    - Returns PENDING immediately
    - No element_selector or on_success_callback parameters
    """

    @pytest.mark.asyncio
    async def test_full_lifecycle_returns_pending_per_spec(
        self, mock_settings: MagicMock, mock_db: AsyncMock, mock_page: AsyncMock
    ) -> None:
        """Test full intervention lifecycle returns PENDING per ADR-0007."""
        with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
            with patch(
                "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
            ):
                # Given
                manager = InterventionManager()
                domain = "example.com"

                with patch.object(manager, "send_toast", new_callable=AsyncMock, return_value=True):
                    with patch.object(manager, "_bring_tab_to_front", new_callable=AsyncMock):
                        # When: Per ADR-0007, no element_selector or on_success_callback
                        result = await manager.request_intervention(
                            intervention_type=InterventionType.CLOUDFLARE,
                            url=f"https://{domain}",
                            domain=domain,
                            page=mock_page,
                        )

                        # Then: Should return PENDING immediately
                        assert (
                            result.status == InterventionStatus.PENDING
                        ), f"Expected PENDING status per ADR-0007, got {result.status}"

    @pytest.mark.asyncio
    async def test_complete_intervention_marks_success(
        self, mock_settings: MagicMock, mock_db: AsyncMock
    ) -> None:
        """Test complete_intervention marks intervention as successful.

        Per ADR-0007: User calls complete_authentication when done.
        """
        with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
            with patch(
                "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
            ):
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

                # When: User completes intervention
                await manager.complete_intervention(
                    intervention_id=intervention_id,
                    success=True,
                    notes="User resolved CAPTCHA",
                )

                # Then: Intervention removed from pending
                assert (
                    intervention_id not in manager._pending_interventions
                ), "Completed intervention should be removed from pending"

                # Then: Database updated with success
                assert mock_db.execute.called, "Database should be updated"

    @pytest.mark.asyncio
    async def test_check_status_shows_pending_without_timeout(
        self, mock_settings: MagicMock, mock_db: AsyncMock
    ) -> None:
        """Test check_intervention_status shows pending without timeout per ADR-0007.

        Per ADR-0007: No timeout enforcement - user-driven completion only.
        """
        with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
            with patch(
                "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
            ):
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

                # Then: Should still be pending (no timeout per ADR-0007)
                assert (
                    status["status"] == "pending"
                ), f"Expected 'pending' status per ADR-0007, got '{status['status']}'"
                assert "elapsed_seconds" in status, "Status should include elapsed_seconds"
                assert "note" in status, "Status should include note about user completion"


# =============================================================================
# Domain blocked notifications: Domain Blocked Notification Tests
# =============================================================================


class TestDomainBlockedNotification:
    """Tests for domain_blocked notification (Domain blocked notifications).

    Test Perspectives Table:
    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|---------------------|-------------|-----------------|-------|
    | TC-DB-N-01 | InterventionType.DOMAIN_BLOCKED | Equiv – normal | Enum value defined | - |
    | TC-DB-N-02 | notify_user domain_blocked | Equiv – normal | Queue + toast | - |
    | TC-DB-N-03 | notify_domain_blocked helper | Equiv – normal | Correct result | - |
    | TC-DB-A-01 | Missing domain | Boundary – empty | Uses "unknown" | - |
    | TC-DB-A-02 | Missing reason | Boundary – empty | Uses default | - |
    """

    def test_intervention_type_includes_domain_blocked(self) -> None:
        """
        TC-DB-N-01: InterventionType should include DOMAIN_BLOCKED.

        // Given: InterventionType enum
        // When: Checking values
        // Then: DOMAIN_BLOCKED should be defined with value "domain_blocked"
        """
        assert hasattr(InterventionType, "DOMAIN_BLOCKED")
        assert InterventionType.DOMAIN_BLOCKED.value == "domain_blocked"

    @pytest.mark.asyncio
    async def test_notify_user_domain_blocked_queues_and_notifies(
        self, mock_settings: MagicMock, mock_db: AsyncMock
    ) -> None:
        """
        TC-DB-N-02: notify_user with domain_blocked should queue and send toast.

        // Given: domain_blocked event with valid payload
        // When: Calling notify_user
        // Then: Item queued, toast sent, queue_id returned
        """
        from src.utils.intervention_manager import notify_user

        with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
            with patch(
                "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
            ):
                # Mock the queue
                mock_queue = AsyncMock()
                mock_queue.enqueue = AsyncMock(return_value="iq_test123")

                # Mock the manager
                mock_manager = MagicMock()
                mock_manager.send_toast = AsyncMock(return_value=True)

                with patch(
                    "src.utils.intervention_manager._get_manager", return_value=mock_manager
                ):
                    with patch(
                        "src.utils.intervention_queue.get_intervention_queue",
                        return_value=mock_queue,
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
    async def test_notify_domain_blocked_convenience_function(
        self, mock_settings: MagicMock, mock_db: AsyncMock
    ) -> None:
        """
        TC-DB-N-03: notify_domain_blocked helper should work correctly.

        // Given: Domain and reason
        // When: Calling notify_domain_blocked
        // Then: Correct result returned
        """
        from src.utils.intervention_manager import notify_domain_blocked

        with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
            with patch(
                "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
            ):
                mock_queue = AsyncMock()
                mock_queue.enqueue = AsyncMock(return_value="iq_conv123")

                mock_manager = MagicMock()
                mock_manager.send_toast = AsyncMock(return_value=True)

                with patch(
                    "src.utils.intervention_manager._get_manager", return_value=mock_manager
                ):
                    with patch(
                        "src.utils.intervention_queue.get_intervention_queue",
                        return_value=mock_queue,
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
    async def test_notify_user_domain_blocked_missing_domain(
        self, mock_settings: MagicMock, mock_db: AsyncMock
    ) -> None:
        """
        TC-DB-A-01: notify_user domain_blocked with missing domain uses "unknown".

        // Given: domain_blocked event without domain
        // When: Calling notify_user
        // Then: Uses "unknown" as domain
        """
        from src.utils.intervention_manager import notify_user

        with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
            with patch(
                "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
            ):
                mock_queue = AsyncMock()
                mock_queue.enqueue = AsyncMock(return_value="iq_unknown")

                mock_manager = MagicMock()
                mock_manager.send_toast = AsyncMock(return_value=True)

                with patch(
                    "src.utils.intervention_manager._get_manager", return_value=mock_manager
                ):
                    with patch(
                        "src.utils.intervention_queue.get_intervention_queue",
                        return_value=mock_queue,
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
    async def test_notify_user_domain_blocked_missing_reason(
        self, mock_settings: MagicMock, mock_db: AsyncMock
    ) -> None:
        """
        TC-DB-A-02: notify_user domain_blocked with missing reason uses default.

        // Given: domain_blocked event without reason
        // When: Calling notify_user
        // Then: Uses default reason "Verification failure"
        """
        from src.utils.intervention_manager import notify_user

        with patch("src.utils.intervention_manager.get_settings", return_value=mock_settings):
            with patch(
                "src.utils.intervention_manager.get_database", new=AsyncMock(return_value=mock_db)
            ):
                mock_queue = AsyncMock()
                mock_queue.enqueue = AsyncMock(return_value="iq_noreason")

                mock_manager = MagicMock()
                mock_manager.send_toast = AsyncMock(return_value=True)

                with patch(
                    "src.utils.intervention_manager._get_manager", return_value=mock_manager
                ):
                    with patch(
                        "src.utils.intervention_queue.get_intervention_queue",
                        return_value=mock_queue,
                    ):
                        # When: No reason provided
                        result = await notify_user(
                            event="domain_blocked",
                            payload={"domain": "test.com"},
                        )

                        # Then: Uses default reason
                        assert result["reason"] == "Verification failure"
