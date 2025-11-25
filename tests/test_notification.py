"""
Tests for notification and manual intervention module.

Test Classification (§7.1.7):
- All tests here are unit tests (no external dependencies)
- External dependencies (database, browser) are mocked

Requirements tested:
- §3.6: Manual intervention flows with 3-minute SLA
- §3.1: Skip domain after 3 consecutive failures
- §3.5: Cooldown after timeout (≥60 minutes)
"""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio

from src.utils.notification import (
    InterventionManager,
    InterventionStatus,
    InterventionType,
    InterventionResult,
    notify_user,
    get_intervention_manager,
    _get_manager,
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
    
    Note: Uses short timeout (5s) instead of production value (180s)
    for faster test execution per §7.1.4.2.
    """
    settings = MagicMock()
    settings.notification.intervention_timeout = 5  # Short timeout for test speed
    return settings


@pytest.fixture
def intervention_manager(mock_settings, mock_db):
    """Create InterventionManager with mocked dependencies.
    
    Per §7.1.7: External services should be mocked in unit tests.
    """
    with patch("src.utils.notification.get_settings", return_value=mock_settings):
        with patch("src.utils.notification.get_database", return_value=mock_db):
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
    page.content = AsyncMock(return_value="""
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
    """)
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
        # Arrange: Expected status mappings
        expected_statuses = {
            "PENDING": "pending",
            "IN_PROGRESS": "in_progress",
            "SUCCESS": "success",
            "TIMEOUT": "timeout",
            "FAILED": "failed",
            "SKIPPED": "skipped",
        }
        
        # Act & Assert: Check each status
        for attr_name, expected_value in expected_statuses.items():
            status = getattr(InterventionStatus, attr_name)
            assert status.value == expected_value, (
                f"InterventionStatus.{attr_name} should be '{expected_value}', "
                f"got '{status.value}'"
            )


@pytest.mark.unit
class TestInterventionType:
    """Tests for InterventionType enum.
    
    Verifies all required intervention types per §3.6.
    """
    
    def test_all_types_exist(self):
        """Verify all required intervention types are defined."""
        # Arrange: Expected type mappings per §3.6
        expected_types = {
            "CAPTCHA": "captcha",
            "LOGIN_REQUIRED": "login_required",
            "COOKIE_BANNER": "cookie_banner",
            "CLOUDFLARE": "cloudflare",
            "TURNSTILE": "turnstile",
            "JS_CHALLENGE": "js_challenge",
        }
        
        # Act & Assert: Check each type
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
        
        # Assert: All fields have expected values
        assert result.intervention_id == "test_123", (
            f"intervention_id should be 'test_123', got '{result.intervention_id}'"
        )
        assert result.status == InterventionStatus.SUCCESS, (
            f"status should be SUCCESS, got {result.status}"
        )
        assert result.elapsed_seconds == 30.5, (
            f"elapsed_seconds should be 30.5, got {result.elapsed_seconds}"
        )
        assert result.should_retry is False, (
            "should_retry should default to False for success"
        )
        assert result.cooldown_until is None, (
            "cooldown_until should default to None"
        )
        assert result.skip_domain_today is False, (
            "skip_domain_today should default to False"
        )
    
    def test_timeout_result_with_cooldown_per_spec(self):
        """Test creating a timeout intervention result per §3.6.
        
        Per §3.6: Timeout should trigger cooldown of ≥60 minutes.
        """
        # Arrange
        cooldown = datetime.now(timezone.utc) + timedelta(minutes=60)
        
        # Act
        result = InterventionResult(
            intervention_id="test_456",
            status=InterventionStatus.TIMEOUT,
            elapsed_seconds=180.0,
            should_retry=True,
            cooldown_until=cooldown,
            notes="Timed out after 180 seconds",
        )
        
        # Assert
        assert result.status == InterventionStatus.TIMEOUT, (
            f"status should be TIMEOUT, got {result.status}"
        )
        assert result.should_retry is True, (
            "should_retry should be True for timeout"
        )
        assert result.cooldown_until == cooldown, (
            f"cooldown_until should be {cooldown}, got {result.cooldown_until}"
        )
        assert result.notes is not None and "180" in result.notes, (
            f"notes should contain timeout duration, got '{result.notes}'"
        )
    
    def test_to_dict_serialization(self):
        """Test serialization to dict for JSON output."""
        # Arrange
        result = InterventionResult(
            intervention_id="test_789",
            status=InterventionStatus.SKIPPED,
            skip_domain_today=True,
        )
        
        # Act
        serialized = result.to_dict()
        
        # Assert: Check specific keys and values
        assert serialized["intervention_id"] == "test_789", (
            f"intervention_id should be 'test_789', got '{serialized['intervention_id']}'"
        )
        assert serialized["status"] == "skipped", (
            f"status should be 'skipped', got '{serialized['status']}'"
        )
        assert serialized["skip_domain_today"] is True, (
            "skip_domain_today should be True"
        )
        assert isinstance(serialized, dict), (
            f"Result should be dict, got {type(serialized)}"
        )


# =============================================================================
# InterventionManager Core Tests
# =============================================================================

@pytest.mark.unit
class TestInterventionManagerCore:
    """Core tests for InterventionManager.
    
    Tests configuration properties and basic functionality.
    """
    
    def test_intervention_timeout_from_settings(self, intervention_manager, mock_settings):
        """Test intervention timeout is read from settings."""
        expected_timeout = 5  # From mock_settings fixture
        actual_timeout = intervention_manager.intervention_timeout
        
        assert actual_timeout == expected_timeout, (
            f"intervention_timeout should be {expected_timeout}, got {actual_timeout}"
        )
    
    def test_max_domain_failures_is_three_per_spec(self, intervention_manager):
        """Test max domain failures is 3 per §3.1.
        
        Per §3.1: 3回失敗で当該ドメインを当日スキップ
        """
        expected_max = 3
        actual_max = intervention_manager.max_domain_failures
        
        assert actual_max == expected_max, (
            f"max_domain_failures should be {expected_max} per §3.1, got {actual_max}"
        )
    
    def test_cooldown_at_least_60_minutes_per_spec(self, intervention_manager):
        """Test cooldown is ≥60 minutes per §3.5.
        
        Per §3.5: クールダウン（最小60分）
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
        
        assert failures == 0, (
            f"Initial failure count for '{domain}' should be 0, got {failures}"
        )
    
    def test_domain_failure_tracking_set_and_get(self, intervention_manager):
        """Test setting and getting domain failure count."""
        domain = "example.com"
        expected_failures = 2
        
        # Act: Set failures
        intervention_manager._domain_failures[domain] = expected_failures
        actual_failures = intervention_manager.get_domain_failures(domain)
        
        # Assert
        assert actual_failures == expected_failures, (
            f"Failure count for '{domain}' should be {expected_failures}, got {actual_failures}"
        )
    
    def test_domain_failure_reset(self, intervention_manager):
        """Test resetting domain failure counter."""
        domain = "example.com"
        
        # Arrange: Set some failures
        intervention_manager._domain_failures[domain] = 2
        
        # Act: Reset
        intervention_manager.reset_domain_failures(domain)
        
        # Assert
        failures = intervention_manager.get_domain_failures(domain)
        assert failures == 0, (
            f"Failure count after reset should be 0, got {failures}"
        )


# =============================================================================
# Challenge Detection Tests
# =============================================================================

@pytest.mark.unit
class TestChallengeDetection:
    """Tests for challenge indicator detection.
    
    Verifies detection of various challenge types per §3.6.
    """
    
    def test_detects_cloudflare_verification(self, intervention_manager):
        """Test Cloudflare challenge detection."""
        content = """
        <html>
        <head><title>Cloudflare</title></head>
        <body>
            <div class="cf-browser-verification">
                Please wait while we verify your browser
            </div>
        </body>
        </html>
        """
        
        result = intervention_manager._has_challenge_indicators(content)
        
        assert result is True, (
            "Should detect 'cf-browser-verification' as Cloudflare challenge"
        )
    
    def test_detects_recaptcha(self, intervention_manager):
        """Test reCAPTCHA detection."""
        content = """
        <html>
        <body>
            <div class="g-recaptcha" data-sitekey="xyz"></div>
        </body>
        </html>
        """
        
        result = intervention_manager._has_challenge_indicators(content)
        
        assert result is True, (
            "Should detect 'g-recaptcha' as CAPTCHA challenge"
        )
    
    def test_detects_hcaptcha(self, intervention_manager):
        """Test hCaptcha detection."""
        content = """
        <html>
        <body>
            <div class="h-captcha" data-sitekey="xyz"></div>
        </body>
        </html>
        """
        
        result = intervention_manager._has_challenge_indicators(content)
        
        assert result is True, (
            "Should detect 'h-captcha' as CAPTCHA challenge"
        )
    
    def test_detects_turnstile(self, intervention_manager):
        """Test Turnstile detection per §3.6."""
        content = """
        <html>
        <body>
            <div class="cf-turnstile"></div>
        </body>
        </html>
        """
        
        result = intervention_manager._has_challenge_indicators(content)
        
        assert result is True, (
            "Should detect 'cf-turnstile' as Turnstile challenge"
        )
    
    def test_no_false_positive_on_normal_page(self, intervention_manager):
        """Test normal page has no challenge indicators (no false positive)."""
        content = """
        <html>
        <head><title>Normal Page</title></head>
        <body>
            <h1>Welcome to our website</h1>
            <p>This is normal content about cloud computing and captioning services.</p>
        </body>
        </html>
        """
        
        result = intervention_manager._has_challenge_indicators(content)
        
        assert result is False, (
            "Should not detect challenges on normal page content"
        )
    
    def test_empty_content_no_challenge(self, intervention_manager):
        """Test empty content is not detected as challenge (boundary case)."""
        content = ""
        
        result = intervention_manager._has_challenge_indicators(content)
        
        assert result is False, (
            "Empty content should not be detected as challenge"
        )


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
    
    Per §3.1: 3回失敗（回線更新・ヘッドフル昇格・冷却適用後）で当該ドメインを当日スキップ
    """
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure_count,should_skip", [
        (0, False),   # No failures - should not skip
        (1, False),   # 1 failure - should not skip
        (2, False),   # 2 failures - should not skip (boundary)
        (3, True),    # 3 failures - should skip (threshold)
        (4, True),    # 4 failures - should skip (above threshold)
    ])
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
        
        with patch("src.utils.notification.get_database", return_value=mock_db):
            # Arrange
            intervention_manager._domain_failures[domain] = failure_count
            
            # Act
            result = await intervention_manager._should_skip_domain(domain)
            
            # Assert
            assert result is should_skip, (
                f"With {failure_count} failures, should_skip should be {should_skip}, "
                f"got {result}"
            )
    
    @pytest.mark.asyncio
    async def test_skip_domain_with_active_cooldown(
        self, intervention_manager, mock_db
    ):
        """Test domain is skipped when in active cooldown period."""
        # Arrange: Future cooldown time
        future_time = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        mock_db.fetch_one = AsyncMock(return_value={"cooldown_until": future_time})
        
        with patch("src.utils.notification.get_database", return_value=mock_db):
            # Act
            result = await intervention_manager._should_skip_domain("test.com")
            
            # Assert
            assert result is True, (
                "Domain with future cooldown time should be skipped"
            )
    
    @pytest.mark.asyncio
    async def test_no_skip_with_expired_cooldown(
        self, intervention_manager, mock_db
    ):
        """Test domain is not skipped when cooldown has expired."""
        # Arrange: Past cooldown time
        past_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        mock_db.fetch_one = AsyncMock(return_value={"cooldown_until": past_time})
        
        with patch("src.utils.notification.get_database", return_value=mock_db):
            # Act
            result = await intervention_manager._should_skip_domain("test.com")
            
            # Assert
            assert result is False, (
                "Domain with expired cooldown should not be skipped"
            )


# =============================================================================
# Toast Notification Tests
# =============================================================================

@pytest.mark.unit
class TestToastNotification:
    """Tests for toast notification functionality."""
    
    def test_is_wsl_returns_boolean(self, intervention_manager):
        """Test WSL detection method returns boolean."""
        result = intervention_manager._is_wsl()
        
        assert isinstance(result, bool), (
            f"_is_wsl() should return bool, got {type(result)}"
        )
    
    @pytest.mark.asyncio
    async def test_send_toast_returns_boolean(self, intervention_manager):
        """Test send_toast returns boolean indicating success."""
        with patch.object(
            intervention_manager,
            "_send_linux_toast",
            new_callable=AsyncMock,
            return_value=True
        ):
            with patch.object(intervention_manager, "_is_wsl", return_value=False):
                with patch("platform.system", return_value="Linux"):
                    # Act
                    result = await intervention_manager.send_toast(
                        "Test Title",
                        "Test Message",
                        timeout_seconds=5,
                    )
                    
                    # Assert
                    assert isinstance(result, bool), (
                        f"send_toast should return bool, got {type(result)}"
                    )
                    assert result is True, (
                        "send_toast should return True when _send_linux_toast succeeds"
                    )


# =============================================================================
# Tab Bring-to-Front Tests
# =============================================================================

@pytest.mark.unit
class TestTabBringToFront:
    """Tests for browser tab bring-to-front functionality per §3.6.
    
    Per §3.6: 対象タブを自動で前面化（ヘッドフル）
    """
    
    @pytest.mark.asyncio
    async def test_bring_tab_to_front_uses_cdp(
        self, intervention_manager, mock_page
    ):
        """Test that bring tab to front uses CDP Page.bringToFront command."""
        # Arrange
        cdp_session = AsyncMock()
        cdp_session.send = AsyncMock()
        cdp_session.detach = AsyncMock()
        mock_page.context.new_cdp_session = AsyncMock(return_value=cdp_session)
        
        # Act
        await intervention_manager._bring_tab_to_front(mock_page)
        
        # Assert
        cdp_session.send.assert_any_call("Page.bringToFront")
    
    @pytest.mark.asyncio
    async def test_bring_tab_to_front_falls_back_on_error(
        self, intervention_manager
    ):
        """Test graceful fallback when CDP connection fails."""
        # Arrange
        page = AsyncMock()
        page.context.new_cdp_session = AsyncMock(side_effect=Exception("CDP error"))
        
        with patch.object(
            intervention_manager,
            "_platform_activate_window",
            new_callable=AsyncMock
        ) as mock_activate:
            # Act
            await intervention_manager._bring_tab_to_front(page)
            
            # Assert: Fallback should be called
            mock_activate.assert_called_once()


# =============================================================================
# Element Highlighting Tests
# =============================================================================

@pytest.mark.unit
class TestElementHighlighting:
    """Tests for element highlighting functionality per §3.6.
    
    Per §3.6: 該当要素へスクロール/ハイライト
    """
    
    @pytest.mark.asyncio
    async def test_highlight_element_returns_true_when_found(
        self, intervention_manager, mock_page
    ):
        """Test element highlighting returns True when element exists."""
        # Arrange
        mock_page.evaluate = AsyncMock(return_value=True)
        
        # Act
        result = await intervention_manager._highlight_element(
            mock_page,
            ".captcha-container",
        )
        
        # Assert
        assert result is True, (
            "highlight_element should return True when element is found"
        )
        mock_page.evaluate.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_highlight_element_returns_false_when_not_found(
        self, intervention_manager, mock_page
    ):
        """Test element highlighting returns False when element doesn't exist."""
        # Arrange
        mock_page.evaluate = AsyncMock(return_value=False)
        
        # Act
        result = await intervention_manager._highlight_element(
            mock_page,
            ".nonexistent",
        )
        
        # Assert
        assert result is False, (
            "highlight_element should return False when element is not found"
        )
    
    @pytest.mark.asyncio
    async def test_highlight_element_handles_errors_gracefully(
        self, intervention_manager, mock_page
    ):
        """Test graceful error handling during highlighting."""
        # Arrange
        mock_page.evaluate = AsyncMock(side_effect=Exception("Eval error"))
        
        # Act
        result = await intervention_manager._highlight_element(
            mock_page,
            ".captcha",
        )
        
        # Assert: Should not raise, should return False
        assert result is False, (
            "highlight_element should return False on error, not raise"
        )


# =============================================================================
# Full Intervention Flow Tests
# =============================================================================

@pytest.mark.unit
class TestInterventionFlow:
    """Tests for the full intervention flow."""
    
    @pytest.mark.asyncio
    async def test_skips_domain_with_three_failures(
        self, mock_settings, mock_db
    ):
        """Test intervention is skipped for domains with 3 failures per §3.1."""
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", return_value=mock_db):
                # Arrange
                manager = InterventionManager()
                domain = "blocked.com"
                manager._domain_failures[domain] = 3
                
                # Act
                result = await manager.request_intervention(
                    intervention_type=InterventionType.CAPTCHA,
                    url=f"https://{domain}/page",
                    domain=domain,
                )
                
                # Assert
                assert result.status == InterventionStatus.SKIPPED, (
                    f"Expected SKIPPED status, got {result.status}"
                )
                assert result.skip_domain_today is True, (
                    "skip_domain_today should be True"
                )
    
    @pytest.mark.asyncio
    async def test_logs_intervention_to_database(
        self, intervention_manager, mock_db, mock_page
    ):
        """Test intervention request logs to database."""
        with patch("src.utils.notification.get_database", return_value=mock_db):
            with patch.object(
                intervention_manager,
                "send_toast",
                new_callable=AsyncMock,
                return_value=True,
            ):
                with patch.object(
                    intervention_manager,
                    "_wait_for_intervention",
                    new_callable=AsyncMock,
                    return_value=InterventionResult(
                        intervention_id="test",
                        status=InterventionStatus.SUCCESS,
                    ),
                ):
                    with patch.object(
                        intervention_manager,
                        "_bring_tab_to_front",
                        new_callable=AsyncMock,
                    ):
                        # Act
                        await intervention_manager.request_intervention(
                            intervention_type=InterventionType.CAPTCHA,
                            url="https://example.com/page",
                            domain="example.com",
                            page=mock_page,
                        )
                        
                        # Assert
                        assert mock_db.execute.called, (
                            "Database execute should be called to log intervention"
                        )
    
    @pytest.mark.asyncio
    async def test_success_resets_failure_counter(
        self, intervention_manager, mock_db
    ):
        """Test successful intervention resets failure counter to 0."""
        # Arrange
        domain = "example.com"
        intervention_manager._domain_failures[domain] = 2
        
        with patch("src.utils.notification.get_database", return_value=mock_db):
            result = InterventionResult(
                intervention_id="test",
                status=InterventionStatus.SUCCESS,
            )
            
            # Act
            await intervention_manager._handle_intervention_result(
                result,
                {
                    "domain": domain,
                    "type": InterventionType.CAPTCHA,
                    "task_id": None,
                },
                mock_db,
            )
            
            # Assert
            failures = intervention_manager._domain_failures[domain]
            assert failures == 0, (
                f"Failure count after success should be 0, got {failures}"
            )
    
    @pytest.mark.asyncio
    async def test_failure_increments_counter(
        self, intervention_manager, mock_db
    ):
        """Test failed intervention increments failure counter."""
        # Arrange
        domain = "example.com"
        initial_failures = 1
        intervention_manager._domain_failures[domain] = initial_failures
        
        with patch("src.utils.notification.get_database", return_value=mock_db):
            result = InterventionResult(
                intervention_id="test",
                status=InterventionStatus.TIMEOUT,
            )
            
            # Act
            await intervention_manager._handle_intervention_result(
                result,
                {
                    "domain": domain,
                    "type": InterventionType.CAPTCHA,
                    "task_id": None,
                },
                mock_db,
            )
            
            # Assert
            failures = intervention_manager._domain_failures[domain]
            expected = initial_failures + 1
            assert failures == expected, (
                f"Failure count should be {expected}, got {failures}"
            )


# =============================================================================
# notify_user Function Tests
# =============================================================================

@pytest.mark.unit
class TestNotifyUserFunction:
    """Tests for the notify_user convenience function."""
    
    @pytest.mark.asyncio
    async def test_simple_event_returns_shown_and_event(self, mock_settings, mock_db):
        """Test notify_user with simple event (no intervention)."""
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", return_value=mock_db):
                # Reset global manager
                import src.utils.notification as notif_module
                notif_module._manager = None
                
                with patch.object(
                    InterventionManager,
                    "send_toast",
                    new_callable=AsyncMock,
                    return_value=True,
                ):
                    # Act
                    result = await notify_user(
                        "info",
                        {"message": "Task completed"},
                    )
                    
                    # Assert
                    assert result["shown"] is True, (
                        "Result 'shown' should be True when toast succeeds"
                    )
                    assert result["event"] == "info", (
                        f"Result 'event' should be 'info', got '{result['event']}'"
                    )
    
    @pytest.mark.asyncio
    async def test_captcha_event_triggers_intervention_flow(
        self, mock_settings, mock_db
    ):
        """Test notify_user with captcha event triggers intervention flow."""
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", return_value=mock_db):
                # Reset global manager
                import src.utils.notification as notif_module
                notif_module._manager = None
                
                with patch.object(
                    InterventionManager,
                    "request_intervention",
                    new_callable=AsyncMock,
                    return_value=InterventionResult(
                        intervention_id="test",
                        status=InterventionStatus.SUCCESS,
                    ),
                ):
                    # Act
                    result = await notify_user(
                        "captcha",
                        {
                            "url": "https://example.com",
                            "domain": "example.com",
                        },
                    )
                    
                    # Assert
                    assert result["status"] == "success", (
                        f"Result 'status' should be 'success', got '{result['status']}'"
                    )


# =============================================================================
# Integration-style Tests (still unit - using mocks)
# =============================================================================

@pytest.mark.unit
class TestInterventionIntegration:
    """Integration-style tests for intervention flows (mocked).
    
    Tests complete flows end-to-end with mocked dependencies.
    """
    
    @pytest.mark.asyncio
    async def test_full_lifecycle_success(
        self, mock_settings, mock_db, mock_page
    ):
        """Test full intervention lifecycle with successful outcome."""
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", return_value=mock_db):
                # Arrange
                manager = InterventionManager()
                domain = "example.com"
                
                async def success_callback():
                    return True
                
                with patch.object(manager, "send_toast", new_callable=AsyncMock, return_value=True):
                    with patch.object(manager, "_bring_tab_to_front", new_callable=AsyncMock):
                        with patch.object(manager, "_highlight_element", new_callable=AsyncMock):
                            with patch.object(
                                manager,
                                "_wait_for_intervention",
                                new_callable=AsyncMock,
                                return_value=InterventionResult(
                                    intervention_id="test",
                                    status=InterventionStatus.SUCCESS,
                                    elapsed_seconds=10.0,
                                ),
                            ):
                                # Act
                                result = await manager.request_intervention(
                                    intervention_type=InterventionType.CLOUDFLARE,
                                    url=f"https://{domain}",
                                    domain=domain,
                                    page=mock_page,
                                    element_selector="#cf-wrapper",
                                    on_success_callback=success_callback,
                                )
                                
                                # Assert
                                assert result.status == InterventionStatus.SUCCESS, (
                                    f"Expected SUCCESS status, got {result.status}"
                                )
                                assert manager.get_domain_failures(domain) == 0, (
                                    "Failure count should be 0 after success"
                                )
    
    @pytest.mark.asyncio
    async def test_timeout_applies_cooldown_per_spec(
        self, mock_settings, mock_db
    ):
        """Test intervention timeout applies cooldown per §3.5.
        
        Per §3.5: クールダウン（最小60分）
        """
        with patch("src.utils.notification.get_settings", return_value=mock_settings):
            with patch("src.utils.notification.get_database", return_value=mock_db):
                # Arrange
                manager = InterventionManager()
                cooldown_time = datetime.now(timezone.utc) + timedelta(minutes=60)
                
                with patch.object(manager, "send_toast", new_callable=AsyncMock, return_value=True):
                    with patch.object(
                        manager,
                        "_wait_for_intervention",
                        new_callable=AsyncMock,
                        return_value=InterventionResult(
                            intervention_id="test",
                            status=InterventionStatus.TIMEOUT,
                            elapsed_seconds=180.0,
                            should_retry=True,
                            cooldown_until=cooldown_time,
                        ),
                    ):
                        # Act
                        result = await manager.request_intervention(
                            intervention_type=InterventionType.CAPTCHA,
                            url="https://example.com",
                            domain="example.com",
                        )
                        
                        # Assert
                        assert result.status == InterventionStatus.TIMEOUT, (
                            f"Expected TIMEOUT status, got {result.status}"
                        )
                        assert result.cooldown_until is not None, (
                            "cooldown_until should be set on timeout"
                        )
                        
                        # Verify cooldown is at least 59 minutes (allowing for test execution time)
                        cooldown_delta = result.cooldown_until - datetime.now(timezone.utc)
                        min_expected_seconds = 59 * 60  # 59 minutes
                        assert cooldown_delta.total_seconds() >= min_expected_seconds, (
                            f"Cooldown should be >= 59 minutes, got {cooldown_delta.total_seconds()} seconds"
                        )
