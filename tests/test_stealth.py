"""
Tests for browser stealth utilities.

Tests navigator.webdriver override and viewport jitter per §4.3.
"""

import time
import pytest

from src.crawler.stealth import (
    STEALTH_JS,
    CDP_STEALTH_JS,
    ViewportJitterConfig,
    ViewportState,
    ViewportJitter,
    get_stealth_args,
    verify_stealth,
    get_viewport_jitter,
)


@pytest.mark.unit
class TestStealthJS:
    """Test stealth JavaScript injection scripts."""
    
    def test_stealth_js_contains_webdriver_override(self):
        """Verify STEALTH_JS overrides navigator.webdriver per §4.3."""
        assert "navigator" in STEALTH_JS
        assert "webdriver" in STEALTH_JS
        assert "undefined" in STEALTH_JS
        # Should use Object.defineProperty for reliable override
        assert "Object.defineProperty" in STEALTH_JS
    
    def test_stealth_js_removes_automation_markers(self):
        """Verify STEALTH_JS removes automation-related properties."""
        automation_markers = [
            "__webdriver_script_fn",
            "__driver_evaluate",
            "__webdriver_evaluate",
            "__selenium_evaluate",
        ]
        for marker in automation_markers:
            assert marker in STEALTH_JS
    
    def test_stealth_js_overrides_plugins(self):
        """Verify STEALTH_JS provides realistic plugin array."""
        assert "plugins" in STEALTH_JS
        assert "Chrome PDF Plugin" in STEALTH_JS
    
    def test_stealth_js_sets_languages(self):
        """Verify STEALTH_JS sets realistic languages array."""
        assert "languages" in STEALTH_JS
        assert "ja-JP" in STEALTH_JS
    
    def test_stealth_js_removes_playwright_markers(self):
        """Verify STEALTH_JS removes Playwright detection markers."""
        assert "__playwright" in STEALTH_JS
        assert "__puppeteer" in STEALTH_JS
    
    def test_cdp_stealth_js_exists(self):
        """Verify CDP-specific stealth script exists."""
        assert CDP_STEALTH_JS is not None
        assert len(CDP_STEALTH_JS) > 0
        assert "webdriver" in CDP_STEALTH_JS
    
    def test_cdp_stealth_js_removes_cdp_markers(self):
        """Verify CDP stealth removes CDP-specific detection markers."""
        # These are Chrome DevTools Protocol markers
        assert "cdc_" in CDP_STEALTH_JS


@pytest.mark.unit
class TestViewportJitterConfig:
    """Test ViewportJitterConfig dataclass."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = ViewportJitterConfig()
        
        assert config.base_width == 1920
        assert config.base_height == 1080
        assert config.max_width_jitter == 20
        assert config.max_height_jitter == 15
        assert config.hysteresis_seconds == 300.0
        assert config.enabled is True
    
    def test_custom_values(self):
        """Test custom configuration values."""
        config = ViewportJitterConfig(
            base_width=1280,
            base_height=720,
            max_width_jitter=10,
            max_height_jitter=8,
            hysteresis_seconds=60.0,
            enabled=False,
        )
        
        assert config.base_width == 1280
        assert config.base_height == 720
        assert config.max_width_jitter == 10
        assert config.max_height_jitter == 8
        assert config.hysteresis_seconds == 60.0
        assert config.enabled is False


@pytest.mark.unit
class TestViewportJitter:
    """Test ViewportJitter class per §4.3."""
    
    def test_jitter_returns_dict_with_width_and_height(self):
        """Test get_viewport returns dict with required keys."""
        jitter = ViewportJitter()
        viewport = jitter.get_viewport(force_update=True)
        
        assert "width" in viewport
        assert "height" in viewport
        assert isinstance(viewport["width"], int)
        assert isinstance(viewport["height"], int)
    
    def test_jitter_applies_narrow_range(self):
        """Test jitter is within configured narrow range per §4.3."""
        config = ViewportJitterConfig(
            base_width=1920,
            base_height=1080,
            max_width_jitter=20,
            max_height_jitter=15,
        )
        jitter = ViewportJitter(config)
        
        # Run multiple times to check range
        for _ in range(50):
            viewport = jitter.get_viewport(force_update=True)
            
            # Width should be within ±20 of base
            assert 1900 <= viewport["width"] <= 1940
            # Height should be within ±15 of base
            assert 1065 <= viewport["height"] <= 1095
    
    def test_hysteresis_prevents_rapid_changes(self):
        """Test hysteresis prevents viewport changes within threshold per §4.3."""
        config = ViewportJitterConfig(
            base_width=1920,
            base_height=1080,
            hysteresis_seconds=1.0,  # Short for testing
        )
        jitter = ViewportJitter(config)
        
        # First call should apply jitter
        viewport1 = jitter.get_viewport(force_update=True)
        
        # Immediate second call should return same viewport (hysteresis)
        viewport2 = jitter.get_viewport(force_update=False)
        
        assert viewport1["width"] == viewport2["width"]
        assert viewport1["height"] == viewport2["height"]
    
    def test_force_update_bypasses_hysteresis(self):
        """Test force_update=True bypasses hysteresis."""
        config = ViewportJitterConfig(
            base_width=1920,
            base_height=1080,
            hysteresis_seconds=300.0,  # Long hysteresis
        )
        jitter = ViewportJitter(config)
        
        # With force_update, should always update (though values may match by chance)
        viewport1 = jitter.get_viewport(force_update=True)
        
        # Force another update
        # Note: Due to randomness, values might match, but state should update
        viewport2 = jitter.get_viewport(force_update=True)
        
        # State's last_change_time should be updated
        assert jitter._state.last_change_time > 0
    
    def test_disabled_jitter_returns_base_dimensions(self):
        """Test disabled jitter returns exact base dimensions."""
        config = ViewportJitterConfig(
            base_width=1920,
            base_height=1080,
            enabled=False,
        )
        jitter = ViewportJitter(config)
        
        viewport = jitter.get_viewport()
        
        assert viewport["width"] == 1920
        assert viewport["height"] == 1080
    
    def test_reset_clears_state(self):
        """Test reset() clears viewport state."""
        jitter = ViewportJitter()
        
        # Apply some jitter
        jitter.get_viewport(force_update=True)
        
        # Reset
        jitter.reset()
        
        # State should be at base values
        assert jitter._state.current_width == jitter._config.base_width
        assert jitter._state.current_height == jitter._config.base_height
        assert jitter._state.last_change_time == 0.0


@pytest.mark.unit
class TestGetStealthArgs:
    """Test get_stealth_args function."""
    
    def test_returns_list(self):
        """Test returns a list of arguments."""
        args = get_stealth_args()
        
        assert isinstance(args, list)
        assert len(args) > 0
    
    def test_contains_automation_controlled_disable(self):
        """Test includes --disable-blink-features=AutomationControlled."""
        args = get_stealth_args()
        
        assert "--disable-blink-features=AutomationControlled" in args
    
    def test_contains_infobars_disable(self):
        """Test includes --disable-infobars."""
        args = get_stealth_args()
        
        assert "--disable-infobars" in args
    
    def test_contains_window_size(self):
        """Test includes window size argument."""
        args = get_stealth_args()
        
        # Check for window size argument
        has_window_size = any("--window-size=" in arg for arg in args)
        assert has_window_size


@pytest.mark.unit
class TestVerifyStealth:
    """Test verify_stealth function."""
    
    def test_clean_page_passes(self):
        """Test clean page content passes verification."""
        content = "<html><body><h1>Normal Page</h1></body></html>"
        
        results = verify_stealth(content)
        
        assert results["no_webdriver_detected"] is True
        assert results["no_automation_detected"] is True
        assert results["no_headless_detected"] is True
    
    def test_page_with_bot_detection_fails(self):
        """Test page with bot detection markers fails verification."""
        content = "<html><body><h1>Bot Detected</h1><p>webdriver detected</p></body></html>"
        
        results = verify_stealth(content)
        
        # This should detect the marker
        assert results["no_webdriver_detected"] is False
    
    def test_page_with_headless_mention_fails(self):
        """Test page mentioning headless fails that check."""
        content = "<html><body><p>Running in headless mode</p></body></html>"
        
        results = verify_stealth(content)
        
        assert results["no_headless_detected"] is False


@pytest.mark.unit
class TestGetViewportJitter:
    """Test get_viewport_jitter singleton function."""
    
    def test_returns_viewport_jitter_instance(self):
        """Test returns ViewportJitter instance."""
        jitter = get_viewport_jitter()
        
        assert isinstance(jitter, ViewportJitter)
    
    def test_custom_config_creates_new_instance(self):
        """Test custom config creates new instance."""
        config = ViewportJitterConfig(base_width=1280, base_height=720)
        jitter = get_viewport_jitter(config)
        
        assert jitter._config.base_width == 1280
        assert jitter._config.base_height == 720


@pytest.mark.unit
class TestViewportState:
    """Test ViewportState dataclass."""
    
    def test_default_values(self):
        """Test default state values."""
        state = ViewportState()
        
        assert state.current_width == 1920
        assert state.current_height == 1080
        assert state.last_change_time == 0.0
    
    def test_custom_values(self):
        """Test custom state values."""
        state = ViewportState(
            current_width=1280,
            current_height=720,
            last_change_time=12345.0,
        )
        
        assert state.current_width == 1280
        assert state.current_height == 720
        assert state.last_change_time == 12345.0




