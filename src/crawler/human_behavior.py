"""
Human-like browser behavior simulation for Lyra.

Implements realistic human interaction patterns per ADR-0006:
- Mouse trajectory with Bezier curves and natural acceleration/deceleration
- Typing rhythm with Gaussian-distributed delays and occasional typos
- Inertial scrolling with ease-out animation
- Configurable parameters via external YAML

This module is separated from stealth.py to maintain single responsibility:
- stealth.py: Anti-bot detection (navigator.webdriver, fingerprint)
- human_behavior.py: Natural interaction patterns
"""

import asyncio
import math
import random
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = get_logger(__name__)


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class MouseConfig:
    """Configuration for mouse movement behavior."""

    # Speed parameters
    base_speed: float = 800.0  # pixels per second (base)
    speed_variance: float = 0.3  # ±30% variance

    # Bezier curve parameters
    control_point_variance: float = 80.0  # pixels
    num_control_points: int = 2  # number of intermediate control points

    # Acceleration/deceleration
    acceleration_ratio: float = 0.2  # first 20% of path accelerates
    deceleration_ratio: float = 0.3  # last 30% of path decelerates

    # Micro-jitter
    jitter_amplitude: float = 2.0  # pixels
    jitter_frequency: float = 0.3  # probability per step

    # Steps
    min_steps: int = 10
    max_steps: int = 50


@dataclass
class TypingConfig:
    """Configuration for typing behavior."""

    # Key delay parameters (milliseconds)
    mean_delay_ms: float = 100.0
    std_delay_ms: float = 30.0
    min_delay_ms: float = 30.0
    max_delay_ms: float = 300.0

    # Post-punctuation pause (longer delay after . , ; : ! ?)
    punctuation_delay_multiplier: float = 2.5
    punctuation_chars: str = ".,;:!?"

    # Typo simulation
    typo_probability: float = 0.01  # 1% chance per character
    typo_adjacent_keys: dict = field(
        default_factory=lambda: {
            "a": "sqwz",
            "b": "vghn",
            "c": "xdfv",
            "d": "erfcxs",
            "e": "wrsdf",
            "f": "rtgvcd",
            "g": "tyhbvf",
            "h": "yujnbg",
            "i": "uojkl",
            "j": "uikmnh",
            "k": "ioljm",
            "l": "opk",
            "m": "njk",
            "n": "bhjm",
            "o": "iplk",
            "p": "ol",
            "q": "wa",
            "r": "etdf",
            "s": "wedxza",
            "t": "ryfg",
            "u": "yihj",
            "v": "cfgb",
            "w": "qeas",
            "x": "zsdc",
            "y": "tugh",
            "z": "asx",
        }
    )

    # Correction timing
    typo_detection_delay_ms: float = 300.0  # delay before noticing typo
    backspace_delay_ms: float = 80.0  # delay for backspace


@dataclass
class ScrollConfig:
    """Configuration for scrolling behavior."""

    # Scroll amount parameters
    base_scroll_amount: float = 400.0  # pixels (base scroll)
    scroll_variance: float = 0.4  # ±40% variance

    # Inertial animation
    animation_duration_ms: float = 400.0  # duration of scroll animation
    ease_out_power: float = 3.0  # cubic ease-out (higher = more pronounced)

    # Reading pauses
    pause_probability: float = 0.2  # probability of pausing mid-scroll
    pause_min_ms: float = 500.0
    pause_max_ms: float = 2000.0

    # Scroll direction variance
    reverse_probability: float = 0.05  # small chance to scroll back slightly


@dataclass
class HumanBehaviorConfig:
    """Complete human behavior configuration."""

    mouse: MouseConfig = field(default_factory=MouseConfig)
    typing: TypingConfig = field(default_factory=TypingConfig)
    scroll: ScrollConfig = field(default_factory=ScrollConfig)

    # General timing
    think_time_min_ms: float = 200.0  # minimum "thinking" delay between actions
    think_time_max_ms: float = 800.0

    @classmethod
    def from_yaml(cls, path: str | Path) -> HumanBehaviorConfig:
        """Load configuration from YAML file.

        Args:
            path: Path to YAML configuration file.

        Returns:
            HumanBehaviorConfig instance.
        """
        path = Path(path)
        if not path.exists():
            logger.warning(f"Config file not found: {path}, using defaults")
            return cls()

        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}

            mouse_data = data.get("mouse", {})
            typing_data = data.get("typing", {})
            scroll_data = data.get("scroll", {})

            return cls(
                mouse=MouseConfig(
                    **{k: v for k, v in mouse_data.items() if k in MouseConfig.__dataclass_fields__}
                ),
                typing=TypingConfig(
                    **{
                        k: v
                        for k, v in typing_data.items()
                        if k in TypingConfig.__dataclass_fields__
                    }
                ),
                scroll=ScrollConfig(
                    **{
                        k: v
                        for k, v in scroll_data.items()
                        if k in ScrollConfig.__dataclass_fields__
                    }
                ),
                think_time_min_ms=data.get("think_time_min_ms", 200.0),
                think_time_max_ms=data.get("think_time_max_ms", 800.0),
            )
        except Exception as e:
            logger.error(f"Failed to load config from {path}: {e}")
            return cls()


# =============================================================================
# Mouse Trajectory
# =============================================================================


@dataclass
class Point:
    """2D point."""

    x: float
    y: float

    def distance_to(self, other: Point) -> float:
        """Calculate Euclidean distance to another point."""
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)


class MouseTrajectory:
    """Generates human-like mouse movement trajectories.

    Uses Bezier curves with natural acceleration/deceleration patterns
    to create realistic mouse paths.
    """

    def __init__(self, config: MouseConfig | None = None):
        """Initialize mouse trajectory generator.

        Args:
            config: Mouse configuration. Uses defaults if not provided.
        """
        self._config = config or MouseConfig()

    def generate_path(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> list[tuple[float, float, float]]:
        """Generate a human-like mouse movement path.

        Args:
            start: Starting (x, y) coordinates.
            end: Ending (x, y) coordinates.

        Returns:
            List of (x, y, delay_ms) tuples representing the path.
        """
        start_pt = Point(start[0], start[1])
        end_pt = Point(end[0], end[1])

        distance = start_pt.distance_to(end_pt)
        if distance < 1:
            return [(end[0], end[1], 0)]

        # Calculate number of steps based on distance
        num_steps = max(self._config.min_steps, min(self._config.max_steps, int(distance / 20)))

        # Generate control points for Bezier curve
        control_points = self._generate_control_points(start_pt, end_pt)

        # Generate path points using Bezier interpolation
        path: list[tuple[float, float, float]] = []

        # Calculate speed with variance
        speed = self._config.base_speed * (
            1 + random.uniform(-self._config.speed_variance, self._config.speed_variance)
        )

        for i in range(num_steps + 1):
            t = i / num_steps

            # Calculate position on Bezier curve
            x, y = self._bezier_point(t, control_points)

            # Add micro-jitter
            if random.random() < self._config.jitter_frequency:
                x += random.uniform(-self._config.jitter_amplitude, self._config.jitter_amplitude)
                y += random.uniform(-self._config.jitter_amplitude, self._config.jitter_amplitude)

            # Calculate delay with acceleration/deceleration
            delay_factor = self._get_speed_factor(t)
            base_delay = (distance / num_steps) / speed * 1000  # ms
            delay = base_delay / delay_factor

            path.append((x, y, delay))

        return path

    def _generate_control_points(
        self,
        start: Point,
        end: Point,
    ) -> list[Point]:
        """Generate Bezier control points.

        Args:
            start: Starting point.
            end: Ending point.

        Returns:
            List of control points including start and end.
        """
        points = [start]

        # Generate intermediate control points
        for i in range(self._config.num_control_points):
            t = (i + 1) / (self._config.num_control_points + 1)

            # Interpolate between start and end
            base_x = start.x + t * (end.x - start.x)
            base_y = start.y + t * (end.y - start.y)

            # Add variance perpendicular to the line
            variance = self._config.control_point_variance
            angle = math.atan2(end.y - start.y, end.x - start.x) + math.pi / 2
            offset = random.uniform(-variance, variance)

            ctrl_x = base_x + offset * math.cos(angle)
            ctrl_y = base_y + offset * math.sin(angle)

            points.append(Point(ctrl_x, ctrl_y))

        points.append(end)
        return points

    def _bezier_point(
        self,
        t: float,
        control_points: list[Point],
    ) -> tuple[float, float]:
        """Calculate point on Bezier curve.

        Uses de Casteljau's algorithm for arbitrary-order Bezier curves.

        Args:
            t: Parameter (0 to 1).
            control_points: Control points of the curve.

        Returns:
            (x, y) coordinates at parameter t.
        """
        points = [(p.x, p.y) for p in control_points]

        while len(points) > 1:
            new_points = []
            for i in range(len(points) - 1):
                x = (1 - t) * points[i][0] + t * points[i + 1][0]
                y = (1 - t) * points[i][1] + t * points[i + 1][1]
                new_points.append((x, y))
            points = new_points

        return points[0]

    def _get_speed_factor(self, t: float) -> float:
        """Calculate speed factor for acceleration/deceleration.

        Creates natural movement where mouse accelerates at start
        and decelerates at end.

        Args:
            t: Parameter (0 to 1).

        Returns:
            Speed multiplier (>1 = faster, <1 = slower).
        """
        accel_ratio: float = float(self._config.acceleration_ratio)
        decel_ratio: float = float(self._config.deceleration_ratio)

        if t < accel_ratio:
            # Acceleration phase: ease-in (slow to fast)
            normalized: float = t / accel_ratio
            return float(0.3 + 0.7 * (normalized**0.5))  # Starts at 0.3, reaches 1.0
        elif t > (1 - decel_ratio):
            # Deceleration phase: ease-out (fast to slow)
            normalized_decel: float = (t - (1 - decel_ratio)) / decel_ratio
            return float(1.0 - 0.7 * (normalized_decel**2))  # Starts at 1.0, reaches 0.3
        else:
            # Constant speed phase
            return 1.0


# =============================================================================
# Human Typing
# =============================================================================


@dataclass
class TypingEvent:
    """Represents a single typing event."""

    class EventType(Enum):
        KEY = "key"
        BACKSPACE = "backspace"

    event_type: TypingEvent.EventType
    key: str
    delay_ms: float


class HumanTyping:
    """Simulates human-like typing patterns.

    Features:
    - Gaussian-distributed key delays
    - Longer pauses after punctuation
    - Occasional typos with natural correction
    """

    def __init__(self, config: TypingConfig | None = None):
        """Initialize human typing simulator.

        Args:
            config: Typing configuration. Uses defaults if not provided.
        """
        self._config = config or TypingConfig()

    def generate_keystrokes(self, text: str) -> list[TypingEvent]:
        """Generate typing events for a text string.

        Args:
            text: Text to type.

        Returns:
            List of TypingEvent objects representing keystrokes.
        """
        events: list[TypingEvent] = []

        for i, char in enumerate(text):
            # Check for typo
            if (
                char.lower() in self._config.typo_adjacent_keys
                and random.random() < self._config.typo_probability
            ):
                # Generate typo
                typo_events = self._generate_typo(char)
                events.extend(typo_events)
            else:
                # Normal keystroke
                delay = self._get_key_delay(char, i > 0 and text[i - 1] or None)
                events.append(
                    TypingEvent(
                        event_type=TypingEvent.EventType.KEY,
                        key=char,
                        delay_ms=delay,
                    )
                )

        return events

    def _get_key_delay(self, char: str, prev_char: str | None) -> float:
        """Calculate delay before typing a character.

        Args:
            char: Character to type.
            prev_char: Previous character (for context).

        Returns:
            Delay in milliseconds.
        """
        # Base delay from Gaussian distribution
        delay = random.gauss(
            self._config.mean_delay_ms,
            self._config.std_delay_ms,
        )

        # Clamp to valid range
        delay = max(self._config.min_delay_ms, min(delay, self._config.max_delay_ms))

        # Apply punctuation multiplier
        if prev_char and prev_char in self._config.punctuation_chars:
            delay *= self._config.punctuation_delay_multiplier

        return delay

    def _generate_typo(self, intended_char: str) -> list[TypingEvent]:
        """Generate a typo and its correction.

        Args:
            intended_char: The character user intended to type.

        Returns:
            List of events: typo + pause + backspace + correct char.
        """
        events: list[TypingEvent] = []

        # Get adjacent keys for typo
        adjacent = self._config.typo_adjacent_keys.get(intended_char.lower(), "")
        if not adjacent:
            # No adjacent keys defined, just type normally
            delay = self._get_key_delay(intended_char, None)
            events.append(
                TypingEvent(
                    event_type=TypingEvent.EventType.KEY,
                    key=intended_char,
                    delay_ms=delay,
                )
            )
            return events

        # Type wrong character
        wrong_char = random.choice(adjacent)
        if intended_char.isupper():
            wrong_char = wrong_char.upper()

        events.append(
            TypingEvent(
                event_type=TypingEvent.EventType.KEY,
                key=wrong_char,
                delay_ms=self._get_key_delay(wrong_char, None),
            )
        )

        # Pause to "notice" the typo
        events.append(
            TypingEvent(
                event_type=TypingEvent.EventType.KEY,
                key="",  # No actual key, just delay
                delay_ms=self._config.typo_detection_delay_ms,
            )
        )

        # Backspace to correct
        events.append(
            TypingEvent(
                event_type=TypingEvent.EventType.BACKSPACE,
                key="",
                delay_ms=self._config.backspace_delay_ms,
            )
        )

        # Type correct character
        events.append(
            TypingEvent(
                event_type=TypingEvent.EventType.KEY,
                key=intended_char,
                delay_ms=self._get_key_delay(intended_char, None),
            )
        )

        return events


# =============================================================================
# Inertial Scroll
# =============================================================================


@dataclass
class ScrollStep:
    """Represents a single scroll animation step."""

    position: int  # Scroll position in pixels
    delay_ms: float  # Delay before this step


class InertialScroll:
    """Simulates human-like scrolling with inertia.

    Features:
    - Ease-out animation (fast start, slow end)
    - Variable scroll amounts
    - Occasional reading pauses
    - Small reverse scrolls for natural adjustment
    """

    def __init__(self, config: ScrollConfig | None = None):
        """Initialize inertial scroll simulator.

        Args:
            config: Scroll configuration. Uses defaults if not provided.
        """
        self._config = config or ScrollConfig()

    def generate_scroll_sequence(
        self,
        current_position: int,
        page_height: int,
        viewport_height: int,
    ) -> list[ScrollStep]:
        """Generate a sequence of scroll steps to read a page.

        Args:
            current_position: Current scroll position.
            page_height: Total page height.
            viewport_height: Viewport height.

        Returns:
            List of ScrollStep objects representing the scroll sequence.
        """
        steps: list[ScrollStep] = []
        position = current_position
        max_scroll = max(0, page_height - viewport_height)

        while position < max_scroll:
            # Calculate scroll amount with variance
            base_amount = self._config.base_scroll_amount
            variance = self._config.scroll_variance
            amount = base_amount * (1 + random.uniform(-variance, variance))

            # Small chance to scroll back slightly
            if random.random() < self._config.reverse_probability and position > amount * 0.3:
                reverse_amount = amount * random.uniform(0.1, 0.3)
                position = max(0, position - int(reverse_amount))
                steps.append(ScrollStep(position=position, delay_ms=100))

                # Pause after reverse
                if random.random() < 0.5:
                    steps.append(
                        ScrollStep(
                            position=position,
                            delay_ms=random.uniform(200, 500),
                        )
                    )

            # Generate inertial scroll animation
            target_position = min(position + int(amount), max_scroll)
            animation_steps = self._generate_inertial_animation(position, target_position)
            steps.extend(animation_steps)
            position = target_position

            # Maybe add reading pause
            if random.random() < self._config.pause_probability:
                pause_duration = random.uniform(
                    self._config.pause_min_ms,
                    self._config.pause_max_ms,
                )
                steps.append(ScrollStep(position=position, delay_ms=pause_duration))

        return steps

    def _generate_inertial_animation(
        self,
        start: int,
        end: int,
        num_steps: int = 10,
    ) -> list[ScrollStep]:
        """Generate scroll animation with ease-out effect.

        Args:
            start: Starting scroll position.
            end: Ending scroll position.
            num_steps: Number of animation steps.

        Returns:
            List of ScrollStep objects for the animation.
        """
        steps: list[ScrollStep] = []
        distance = end - start
        step_duration = self._config.animation_duration_ms / num_steps

        for i in range(1, num_steps + 1):
            t = i / num_steps

            # Ease-out function: 1 - (1 - t)^power
            eased_t = 1 - (1 - t) ** self._config.ease_out_power

            position = start + int(distance * eased_t)
            steps.append(ScrollStep(position=position, delay_ms=step_duration))

        return steps

    def generate_single_scroll(
        self,
        direction: int = 1,  # 1 = down, -1 = up
        intensity: float = 1.0,
    ) -> list[ScrollStep]:
        """Generate a single scroll gesture.

        Args:
            direction: Scroll direction (1 = down, -1 = up).
            intensity: Scroll intensity multiplier.

        Returns:
            List of ScrollStep objects for the scroll animation.
        """
        base_amount = self._config.base_scroll_amount * intensity * direction
        variance = self._config.scroll_variance
        amount = int(base_amount * (1 + random.uniform(-variance, variance)))

        # Generate relative animation steps
        steps: list[ScrollStep] = []
        num_steps = 8
        step_duration = self._config.animation_duration_ms / num_steps

        for i in range(1, num_steps + 1):
            t = i / num_steps
            eased_t = 1 - (1 - t) ** self._config.ease_out_power
            relative_position = int(amount * eased_t)
            steps.append(ScrollStep(position=relative_position, delay_ms=step_duration))

        return steps


# =============================================================================
# Unified Human Behavior Interface
# =============================================================================


class HumanBehaviorSimulator:
    """Unified interface for human-like browser interactions.

    Combines mouse, typing, and scroll behaviors with a convenient API
    for use with Playwright pages.
    """

    def __init__(self, config: HumanBehaviorConfig | None = None):
        """Initialize human behavior simulator.

        Args:
            config: Complete behavior configuration. Uses defaults if not provided.
        """
        self._config = config or HumanBehaviorConfig()
        self._mouse = MouseTrajectory(self._config.mouse)
        self._typing = HumanTyping(self._config.typing)
        self._scroll = InertialScroll(self._config.scroll)

    @classmethod
    def from_config_file(cls, path: str | Path) -> HumanBehaviorSimulator:
        """Create simulator from YAML configuration file.

        Args:
            path: Path to YAML configuration file.

        Returns:
            HumanBehaviorSimulator instance.
        """
        config = HumanBehaviorConfig.from_yaml(path)
        return cls(config)

    async def move_mouse(
        self,
        page: Page,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        """Move mouse from start to end with human-like trajectory.

        Args:
            page: Playwright page object.
            start: Starting (x, y) coordinates.
            end: Ending (x, y) coordinates.
        """
        path = self._mouse.generate_path(start, end)

        for x, y, delay_ms in path:
            await page.mouse.move(x, y)
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)

    async def move_to_element(self, page: Page, selector: str) -> bool:
        """Move mouse to element with human-like trajectory.

        Args:
            page: Playwright page object.
            selector: CSS selector for target element.

        Returns:
            True if element found and mouse moved successfully.
        """
        try:
            element = await page.query_selector(selector)
            if not element:
                return False

            box = await element.bounding_box()
            if not box:
                return False

            # Current position (assume center of viewport)
            viewport = page.viewport_size or {"width": 1920, "height": 1080}
            start = (viewport["width"] / 2, viewport["height"] / 2)

            # Target: center of element with slight randomization
            end = (
                box["x"] + box["width"] / 2 + random.uniform(-5, 5),
                box["y"] + box["height"] / 2 + random.uniform(-5, 5),
            )

            await self.move_mouse(page, start, end)
            return True

        except Exception as e:
            logger.debug(f"Failed to move to element: {e}")
            return False

    async def type_text(
        self,
        page: Page,
        text: str,
        selector: str | None = None,
    ) -> None:
        """Type text with human-like rhythm.

        Args:
            page: Playwright page object.
            text: Text to type.
            selector: Optional CSS selector to focus first.
        """
        if selector:
            element = await page.query_selector(selector)
            if element:
                await element.focus()

        events = self._typing.generate_keystrokes(text)

        for event in events:
            if event.delay_ms > 0:
                await asyncio.sleep(event.delay_ms / 1000)

            if event.event_type == TypingEvent.EventType.BACKSPACE:
                await page.keyboard.press("Backspace")
            elif event.key:
                await page.keyboard.type(event.key)

    async def scroll_page(
        self,
        page: Page,
        amount: int | None = None,
        direction: int = 1,
    ) -> None:
        """Scroll page with human-like inertia.

        Args:
            page: Playwright page object.
            amount: Scroll amount in pixels (None for default).
            direction: Scroll direction (1 = down, -1 = up).
        """
        if amount is None:
            steps = self._scroll.generate_single_scroll(direction=direction)
        else:
            steps = self._scroll._generate_inertial_animation(0, amount * direction)

        for step in steps:
            await page.evaluate(f"window.scrollBy(0, {step.position})")
            if step.delay_ms > 0:
                await asyncio.sleep(step.delay_ms / 1000)

    async def read_page(
        self,
        page: Page,
        max_scrolls: int = 5,
    ) -> None:
        """Simulate reading a page with natural scrolling.

        Args:
            page: Playwright page object.
            max_scrolls: Maximum number of scroll actions.
        """
        try:
            dimensions = await page.evaluate(
                """
                () => ({
                    height: document.body.scrollHeight,
                    viewportHeight: window.innerHeight,
                    currentScroll: window.scrollY
                })
            """
            )

            page_height = dimensions.get("height", 2000)
            viewport_height = dimensions.get("viewportHeight", 1080)
            current = dimensions.get("currentScroll", 0)

            steps = self._scroll.generate_scroll_sequence(
                current_position=current,
                page_height=page_height,
                viewport_height=viewport_height,
            )

            # Limit scroll steps
            for step in steps[: max_scrolls * 10]:  # ~10 steps per scroll
                await page.evaluate(f"window.scrollTo(0, {step.position})")
                if step.delay_ms > 0:
                    await asyncio.sleep(step.delay_ms / 1000)

        except Exception as e:
            logger.debug(f"Read page simulation error: {e}")

    async def think(self) -> None:
        """Add a human-like "thinking" delay between actions."""
        delay_ms = random.uniform(
            self._config.think_time_min_ms,
            self._config.think_time_max_ms,
        )
        await asyncio.sleep(delay_ms / 1000)

    def random_delay(
        self,
        min_seconds: float = 0.5,
        max_seconds: float = 2.0,
    ) -> float:
        """Generate a random delay following human-like distribution.

        Uses log-normal distribution to better simulate human reaction times.

        Args:
            min_seconds: Minimum delay.
            max_seconds: Maximum delay.

        Returns:
            Delay in seconds.
        """
        # Log-normal distribution parameters (median ~= 1.0s)
        mu = 0.0
        sigma = 0.5

        delay = random.lognormvariate(mu, sigma)
        return max(min_seconds, min(delay, max_seconds))


# =============================================================================
# Global Instance and Factory
# =============================================================================

_simulator: HumanBehaviorSimulator | None = None
_config_path: Path | None = None


def get_human_behavior_simulator(
    config_path: str | Path | None = None,
) -> HumanBehaviorSimulator:
    """Get or create the global human behavior simulator.

    Args:
        config_path: Optional path to YAML configuration file.
            If provided and different from current, reloads config.

    Returns:
        HumanBehaviorSimulator instance.
    """
    global _simulator, _config_path

    # Check if we need to reload
    if config_path is not None:
        config_path = Path(config_path)
        if _config_path != config_path or _simulator is None:
            _config_path = config_path
            _simulator = HumanBehaviorSimulator.from_config_file(config_path)
            return _simulator

    # Create default instance if needed
    if _simulator is None:
        # Try default config path
        default_path = Path("config/human_behavior.yaml")
        if default_path.exists():
            _config_path = default_path
            _simulator = HumanBehaviorSimulator.from_config_file(default_path)
        else:
            _simulator = HumanBehaviorSimulator()

    return _simulator


def reset_human_behavior_simulator() -> None:
    """Reset the global simulator (mainly for testing)."""
    global _simulator, _config_path
    _simulator = None
    _config_path = None
