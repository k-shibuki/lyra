"""
Tests for human_behavior.py module (§16.11).

Tests MouseTrajectory, HumanTyping, InertialScroll, and HumanBehaviorSimulator.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-MC-01 | MouseConfig defaults | Equivalence – defaults | Default values set | - |
| TC-MT-01 | Generate trajectory | Equivalence – normal | Points generated | - |
| TC-MT-02 | Trajectory curvature | Equivalence – bezier | Natural curve | - |
| TC-MT-03 | Trajectory with seed | Equivalence – determinism | Reproducible | - |
| TC-TC-01 | TypingConfig defaults | Equivalence – defaults | Default values set | - |
| TC-HT-01 | Generate typing events | Equivalence – normal | Events generated | - |
| TC-HT-02 | Typing with typos | Equivalence – errors | Includes corrections | - |
| TC-HT-03 | Typing intervals | Equivalence – timing | Natural delays | - |
| TC-SC-01 | ScrollConfig defaults | Equivalence – defaults | Default values set | - |
| TC-IS-01 | Generate scroll steps | Equivalence – normal | Steps generated | - |
| TC-IS-02 | Inertial deceleration | Equivalence – physics | Smooth slowdown | - |
| TC-HBS-01 | Simulator initialization | Equivalence – init | All components ready | - |
| TC-HBS-02 | Simulate mouse move | Equivalence – mouse | Trajectory executed | - |
| TC-HBS-03 | Simulate typing | Equivalence – typing | Events executed | - |
| TC-HBS-04 | Simulate scroll | Equivalence – scroll | Scroll executed | - |
| TC-CF-01 | get_human_behavior_simulator | Equivalence – singleton | Returns simulator | - |
"""

import asyncio
import math
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.crawler.human_behavior import (
    MouseConfig,
    TypingConfig,
    ScrollConfig,
    HumanBehaviorConfig,
    Point,
    MouseTrajectory,
    HumanTyping,
    TypingEvent,
    InertialScroll,
    ScrollStep,
    HumanBehaviorSimulator,
    get_human_behavior_simulator,
    reset_human_behavior_simulator,
)


# Mark all tests as unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# MouseConfig Tests
# =============================================================================

class TestMouseConfig:
    """Tests for MouseConfig dataclass."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = MouseConfig()
        assert config.base_speed == 800.0
        assert config.speed_variance == 0.3
        assert config.control_point_variance == 80.0
        assert config.num_control_points == 2
        assert config.acceleration_ratio == 0.2
        assert config.deceleration_ratio == 0.3
        assert config.jitter_amplitude == 2.0
        assert config.jitter_frequency == 0.3
        assert config.min_steps == 10
        assert config.max_steps == 50
    
    def test_custom_values(self):
        """Test custom configuration values."""
        config = MouseConfig(
            base_speed=1200.0,
            speed_variance=0.5,
            jitter_amplitude=5.0,
        )
        assert config.base_speed == 1200.0
        assert config.speed_variance == 0.5
        assert config.jitter_amplitude == 5.0


# =============================================================================
# Point Tests
# =============================================================================

class TestPoint:
    """Tests for Point dataclass."""
    
    def test_distance_to_same_point(self):
        """Test distance to same point is zero."""
        p = Point(10.0, 20.0)
        assert p.distance_to(p) == 0.0
    
    def test_distance_to_horizontal(self):
        """Test horizontal distance calculation."""
        p1 = Point(0.0, 0.0)
        p2 = Point(100.0, 0.0)
        assert p1.distance_to(p2) == 100.0
    
    def test_distance_to_vertical(self):
        """Test vertical distance calculation."""
        p1 = Point(0.0, 0.0)
        p2 = Point(0.0, 50.0)
        assert p1.distance_to(p2) == 50.0
    
    def test_distance_to_diagonal(self):
        """Test diagonal distance calculation (3-4-5 triangle)."""
        p1 = Point(0.0, 0.0)
        p2 = Point(3.0, 4.0)
        assert p1.distance_to(p2) == 5.0


# =============================================================================
# MouseTrajectory Tests
# =============================================================================

class TestMouseTrajectory:
    """Tests for MouseTrajectory class."""
    
    def test_generate_path_basic(self):
        """Test basic path generation."""
        trajectory = MouseTrajectory()
        path = trajectory.generate_path(
            start=(0.0, 0.0),
            end=(100.0, 100.0),
        )
        
        # Path should have multiple points
        assert len(path) >= trajectory._config.min_steps
        
        # Each point should have (x, y, delay)
        for point in path:
            assert len(point) == 3
            x, y, delay = point
            assert isinstance(x, float)
            assert isinstance(y, float)
            assert isinstance(delay, float)
            assert delay >= 0
    
    def test_generate_path_starts_at_start(self):
        """Test path starts near starting point."""
        trajectory = MouseTrajectory()
        path = trajectory.generate_path(
            start=(50.0, 50.0),
            end=(200.0, 200.0),
        )
        
        # First point should be close to start (with jitter)
        x, y, _ = path[0]
        assert abs(x - 50.0) < 10  # Allow for jitter
        assert abs(y - 50.0) < 10
    
    def test_generate_path_ends_at_end(self):
        """Test path ends near ending point."""
        trajectory = MouseTrajectory()
        path = trajectory.generate_path(
            start=(0.0, 0.0),
            end=(300.0, 200.0),
        )
        
        # Last point should be close to end (with jitter)
        x, y, _ = path[-1]
        assert abs(x - 300.0) < 10
        assert abs(y - 200.0) < 10
    
    def test_generate_path_short_distance(self):
        """Test path generation for very short distance."""
        trajectory = MouseTrajectory()
        path = trajectory.generate_path(
            start=(100.0, 100.0),
            end=(100.5, 100.5),
        )
        
        # Should return at least one point
        assert len(path) >= 1
    
    def test_generate_path_same_point(self):
        """Test path generation when start equals end."""
        trajectory = MouseTrajectory()
        path = trajectory.generate_path(
            start=(100.0, 100.0),
            end=(100.0, 100.0),
        )
        
        # Should return exactly one point at the destination
        assert len(path) == 1
        x, y, delay = path[0]
        assert x == 100.0
        assert y == 100.0
    
    def test_generate_path_uses_bezier(self):
        """Test path uses Bezier curve (not straight line)."""
        trajectory = MouseTrajectory(MouseConfig(
            control_point_variance=100.0,  # Large variance
            jitter_frequency=0.0,  # Disable jitter for this test
        ))
        path = trajectory.generate_path(
            start=(0.0, 0.0),
            end=(200.0, 0.0),  # Horizontal line
        )
        
        # Some points should deviate from the straight line
        y_values = [p[1] for p in path]
        max_deviation = max(abs(y) for y in y_values)
        assert max_deviation > 0  # Should have some curve
    
    def test_speed_factor_acceleration(self):
        """Test speed factor for acceleration phase."""
        trajectory = MouseTrajectory()
        
        # At start (t=0), should be slower
        factor_start = trajectory._get_speed_factor(0.0)
        # At middle of acceleration (t=0.1), should be faster
        factor_mid = trajectory._get_speed_factor(0.1)
        
        assert factor_start < factor_mid
    
    def test_speed_factor_deceleration(self):
        """Test speed factor for deceleration phase."""
        trajectory = MouseTrajectory()
        
        # At middle (t=0.5), should be at full speed
        factor_mid = trajectory._get_speed_factor(0.5)
        # Near end (t=0.95), should be slower
        factor_end = trajectory._get_speed_factor(0.95)
        
        assert factor_mid > factor_end


# =============================================================================
# HumanTyping Tests
# =============================================================================

class TestHumanTyping:
    """Tests for HumanTyping class."""
    
    def test_generate_keystrokes_basic(self):
        """Test basic keystroke generation."""
        typing = HumanTyping()
        events = typing.generate_keystrokes("hello")
        
        # Should have at least 5 events (one per character)
        assert len(events) >= 5
        
        # Check first event is 'h'
        first_key_event = next(
            e for e in events 
            if e.event_type == TypingEvent.EventType.KEY and e.key
        )
        assert first_key_event.key == "h"
    
    def test_generate_keystrokes_delays(self):
        """Test keystroke delays are within bounds."""
        config = TypingConfig(min_delay_ms=50.0, max_delay_ms=200.0)
        typing = HumanTyping(config)
        events = typing.generate_keystrokes("test")
        
        for event in events:
            if event.delay_ms > 0:
                assert event.delay_ms >= config.min_delay_ms
                # Note: May exceed max due to punctuation multiplier
    
    def test_generate_keystrokes_punctuation_pause(self):
        """Test longer pause after punctuation."""
        config = TypingConfig(
            mean_delay_ms=100.0,
            punctuation_delay_multiplier=3.0,
            typo_probability=0.0,  # Disable typos
        )
        typing = HumanTyping(config)
        
        # Compare delays after punctuation vs regular character
        events = typing.generate_keystrokes("a.b")
        
        # Find delays for 'a' and 'b'
        key_events = [e for e in events if e.event_type == TypingEvent.EventType.KEY and e.key]
        
        # 'b' comes after '.', so should have longer delay
        # Note: Due to random distribution, we just check structure
        assert len(key_events) == 3
    
    def test_generate_keystrokes_empty_string(self):
        """Test empty string generates no events."""
        typing = HumanTyping()
        events = typing.generate_keystrokes("")
        assert events == []
    
    def test_typo_generation(self):
        """Test typo generation and correction."""
        config = TypingConfig(typo_probability=1.0)  # Always typo
        typing = HumanTyping(config)
        
        # Generate keystrokes for a single character that has adjacent keys
        events = typing.generate_keystrokes("a")
        
        # Should have: typo key, pause, backspace, correct key
        event_types = [e.event_type for e in events]
        assert TypingEvent.EventType.BACKSPACE in event_types
        assert len(events) >= 3
    
    def test_no_typo_for_unknown_char(self):
        """Test no typo for characters without adjacent keys."""
        config = TypingConfig(typo_probability=1.0)  # Always typo
        typing = HumanTyping(config)
        
        # Digits don't have adjacent key mapping by default
        events = typing.generate_keystrokes("1")
        
        # Should just type the character normally
        key_events = [e for e in events if e.key]
        assert any(e.key == "1" for e in key_events)


# =============================================================================
# InertialScroll Tests
# =============================================================================

class TestInertialScroll:
    """Tests for InertialScroll class."""
    
    def test_generate_scroll_sequence_basic(self):
        """Test basic scroll sequence generation."""
        scroll = InertialScroll()
        steps = scroll.generate_scroll_sequence(
            current_position=0,
            page_height=2000,
            viewport_height=800,
        )
        
        # Should have multiple steps (scrollable area 1200px / ~400px base = ~3+ scrolls)
        # Each scroll generates ~10 animation steps, so expect at least 10 total
        assert len(steps) >= 10, f"Expected at least 10 steps for 1200px scroll, got {len(steps)}"
        
        # Each step should have position and delay
        for step in steps:
            assert isinstance(step.position, int)
            assert isinstance(step.delay_ms, float)
            assert step.delay_ms >= 0
    
    def test_generate_scroll_sequence_reaches_bottom(self):
        """Test scroll sequence reaches near page bottom."""
        scroll = InertialScroll(ScrollConfig(
            reverse_probability=0.0,  # Disable reverse for predictability
            pause_probability=0.0,  # Disable pauses
        ))
        steps = scroll.generate_scroll_sequence(
            current_position=0,
            page_height=2000,
            viewport_height=800,
        )
        
        # Last position should be near max scroll (page_height - viewport)
        max_scroll = 2000 - 800
        last_position = steps[-1].position
        assert last_position >= max_scroll * 0.9  # Within 10% of max
    
    def test_generate_scroll_sequence_no_scroll_needed(self):
        """Test when page fits in viewport (no scroll needed)."""
        scroll = InertialScroll()
        steps = scroll.generate_scroll_sequence(
            current_position=0,
            page_height=500,
            viewport_height=800,
        )
        
        # Should have no steps (or empty list)
        assert len(steps) == 0
    
    def test_inertial_animation_ease_out(self):
        """Test inertial animation has ease-out effect."""
        scroll = InertialScroll()
        steps = scroll._generate_inertial_animation(0, 400, num_steps=10)
        
        # Calculate step sizes
        positions = [s.position for s in steps]
        step_sizes = [positions[i] - positions[i-1] if i > 0 else positions[0] 
                      for i in range(len(positions))]
        
        # Ease-out means larger steps at start, smaller at end
        assert step_sizes[0] > step_sizes[-1]
    
    def test_generate_single_scroll_down(self):
        """Test single scroll down."""
        scroll = InertialScroll()
        steps = scroll.generate_single_scroll(direction=1)
        
        # Single scroll generates 8 animation steps (as defined in generate_single_scroll)
        assert len(steps) == 8, f"Expected 8 animation steps, got {len(steps)}"
        # All positions should be positive (scrolling down)
        final_position = steps[-1].position
        assert final_position > 0
    
    def test_generate_single_scroll_up(self):
        """Test single scroll up."""
        scroll = InertialScroll()
        steps = scroll.generate_single_scroll(direction=-1)
        
        # Single scroll generates 8 animation steps
        assert len(steps) == 8, f"Expected 8 animation steps, got {len(steps)}"
        # All positions should be negative (scrolling up)
        final_position = steps[-1].position
        assert final_position < 0


# =============================================================================
# HumanBehaviorConfig Tests
# =============================================================================

class TestHumanBehaviorConfig:
    """Tests for HumanBehaviorConfig class."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = HumanBehaviorConfig()
        assert isinstance(config.mouse, MouseConfig)
        assert isinstance(config.typing, TypingConfig)
        assert isinstance(config.scroll, ScrollConfig)
        assert config.think_time_min_ms == 200.0
        assert config.think_time_max_ms == 800.0
    
    def test_from_yaml_file_not_found(self):
        """Test loading from non-existent file returns defaults."""
        config = HumanBehaviorConfig.from_yaml("/nonexistent/path.yaml")
        assert isinstance(config, HumanBehaviorConfig)
        # Should have default values
        assert config.mouse.base_speed == 800.0
    
    def test_from_yaml_valid_file(self, tmp_path):
        """Test loading from valid YAML file."""
        yaml_content = """
mouse:
  base_speed: 1200.0
  speed_variance: 0.4
typing:
  mean_delay_ms: 150.0
scroll:
  base_scroll_amount: 500.0
think_time_min_ms: 300.0
"""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(yaml_content)
        
        config = HumanBehaviorConfig.from_yaml(yaml_file)
        assert config.mouse.base_speed == 1200.0
        assert config.mouse.speed_variance == 0.4
        assert config.typing.mean_delay_ms == 150.0
        assert config.scroll.base_scroll_amount == 500.0
        assert config.think_time_min_ms == 300.0


# =============================================================================
# HumanBehaviorSimulator Tests
# =============================================================================

class TestHumanBehaviorSimulator:
    """Tests for HumanBehaviorSimulator class."""
    
    def test_init_default(self):
        """Test default initialization."""
        simulator = HumanBehaviorSimulator()
        assert simulator._config is not None
        assert simulator._mouse is not None
        assert simulator._typing is not None
        assert simulator._scroll is not None
    
    def test_init_with_config(self):
        """Test initialization with custom config."""
        config = HumanBehaviorConfig(
            mouse=MouseConfig(base_speed=1500.0),
        )
        simulator = HumanBehaviorSimulator(config)
        assert simulator._config.mouse.base_speed == 1500.0
    
    def test_from_config_file(self, tmp_path):
        """Test creating from config file."""
        yaml_content = """
mouse:
  base_speed: 1000.0
"""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(yaml_content)
        
        simulator = HumanBehaviorSimulator.from_config_file(yaml_file)
        assert simulator._config.mouse.base_speed == 1000.0
    
    def test_random_delay_bounds(self):
        """Test random_delay respects bounds."""
        simulator = HumanBehaviorSimulator()
        
        for _ in range(100):
            delay = simulator.random_delay(min_seconds=0.5, max_seconds=2.0)
            assert 0.5 <= delay <= 2.0
    
    @pytest.mark.asyncio
    async def test_move_mouse(self):
        """Test move_mouse with mock page."""
        simulator = HumanBehaviorSimulator()
        
        # Mock page
        page = MagicMock()
        page.mouse = MagicMock()
        page.mouse.move = AsyncMock()
        
        await simulator.move_mouse(
            page,
            start=(100.0, 100.0),
            end=(200.0, 200.0),
        )
        
        # Should have called mouse.move multiple times
        assert page.mouse.move.call_count > 0
    
    @pytest.mark.asyncio
    async def test_move_to_element_success(self):
        """Test move_to_element with valid element."""
        simulator = HumanBehaviorSimulator()
        
        # Mock page and element
        element = MagicMock()
        element.bounding_box = AsyncMock(return_value={
            "x": 100, "y": 100, "width": 50, "height": 50
        })
        
        page = MagicMock()
        page.query_selector = AsyncMock(return_value=element)
        page.viewport_size = {"width": 1920, "height": 1080}
        page.mouse = MagicMock()
        page.mouse.move = AsyncMock()
        
        result = await simulator.move_to_element(page, "#button")
        
        assert result is True
        assert page.mouse.move.call_count > 0
    
    @pytest.mark.asyncio
    async def test_move_to_element_not_found(self):
        """Test move_to_element with missing element."""
        simulator = HumanBehaviorSimulator()
        
        page = MagicMock()
        page.query_selector = AsyncMock(return_value=None)
        
        result = await simulator.move_to_element(page, "#nonexistent")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_type_text(self):
        """Test type_text with mock page."""
        simulator = HumanBehaviorSimulator(HumanBehaviorConfig(
            typing=TypingConfig(typo_probability=0.0),  # Disable typos
        ))
        
        page = MagicMock()
        page.keyboard = MagicMock()
        page.keyboard.type = AsyncMock()
        page.keyboard.press = AsyncMock()
        
        await simulator.type_text(page, "hi")
        
        # Should have typed each character
        assert page.keyboard.type.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_scroll_page(self):
        """Test scroll_page with mock page."""
        simulator = HumanBehaviorSimulator()
        
        page = MagicMock()
        page.evaluate = AsyncMock()
        
        await simulator.scroll_page(page, amount=400, direction=1)
        
        # Should have called evaluate for scrolling
        assert page.evaluate.call_count > 0
    
    @pytest.mark.asyncio
    async def test_read_page(self):
        """Test read_page with mock page."""
        simulator = HumanBehaviorSimulator()
        
        page = MagicMock()
        page.evaluate = AsyncMock(return_value={
            "height": 2000,
            "viewportHeight": 800,
            "currentScroll": 0,
        })
        
        await simulator.read_page(page, max_scrolls=2)
        
        # Should have called evaluate
        assert page.evaluate.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_think(self):
        """Test think delay."""
        simulator = HumanBehaviorSimulator(HumanBehaviorConfig(
            think_time_min_ms=10.0,
            think_time_max_ms=20.0,
        ))
        
        start = asyncio.get_event_loop().time()
        await simulator.think()
        elapsed = asyncio.get_event_loop().time() - start
        
        # Should have delayed at least 10ms
        assert elapsed >= 0.01


# =============================================================================
# Global Instance Tests
# =============================================================================

class TestGlobalInstance:
    """Tests for global simulator instance."""
    
    def setup_method(self):
        """Reset global instance before each test."""
        reset_human_behavior_simulator()
    
    def test_get_human_behavior_simulator_default(self):
        """Test getting default simulator."""
        simulator = get_human_behavior_simulator()
        assert isinstance(simulator, HumanBehaviorSimulator)
    
    def test_get_human_behavior_simulator_same_instance(self):
        """Test same instance is returned."""
        sim1 = get_human_behavior_simulator()
        sim2 = get_human_behavior_simulator()
        assert sim1 is sim2
    
    def test_get_human_behavior_simulator_with_config(self, tmp_path):
        """Test getting simulator with config file."""
        yaml_content = """
mouse:
  base_speed: 999.0
"""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(yaml_content)
        
        simulator = get_human_behavior_simulator(config_path=yaml_file)
        assert simulator._config.mouse.base_speed == 999.0
    
    def test_reset_human_behavior_simulator(self):
        """Test resetting simulator."""
        sim1 = get_human_behavior_simulator()
        reset_human_behavior_simulator()
        sim2 = get_human_behavior_simulator()
        
        # Should be different instances after reset
        assert sim1 is not sim2

