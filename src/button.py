"""Physical button handler for GPIO input."""

from __future__ import annotations

import logging
import threading
import warnings
from typing import Callable, Optional

from wifi.ap_mode import ExecutionMode

logger = logging.getLogger(__name__)


class ButtonHandler:
    """Handle physical button for AP mode escape and other functions.

    Uses gpiozero for GPIO handling, which provides a clean interface
    and works on both Pi and development machines (with mock support).
    """

    def __init__(
        self,
        gpio_pin: int = 27,
        pull_up: bool = True,
        hold_time: float = 3.0,
        mode: ExecutionMode = ExecutionMode.NORMAL,
    ):
        """Initialize button handler.

        Args:
            gpio_pin: GPIO pin number (BCM numbering).
            pull_up: Use internal pull-up resistor.
            hold_time: Long press recognition time in seconds.
            mode: Execution mode for testing.
        """
        self.gpio_pin = gpio_pin
        self.pull_up = pull_up
        self.hold_time = hold_time
        self.mode = mode

        self._button = None
        self._on_press: Optional[Callable[[], None]] = None
        self._on_hold: Optional[Callable[[], None]] = None
        self._available = False
        self._arm_timer: Optional[threading.Timer] = None

    @classmethod
    def from_config(cls, mode: Optional[ExecutionMode] = None) -> "ButtonHandler":
        """Create button handler from config.

        Args:
            mode: Override execution mode.

        Returns:
            ButtonHandler instance.
        """
        from config import get_config

        config = get_config()

        if mode is None:
            mode_str = config.get("web_ui.ap_execution_mode", "normal")
            try:
                mode = ExecutionMode(mode_str)
            except ValueError:
                mode = ExecutionMode.NORMAL

        return cls(
            gpio_pin=config.get("button.gpio_pin", 17),
            pull_up=config.get("button.pull_up", True),
            hold_time=config.get("button.hold_time", 3.0),
            mode=mode,
        )

    def setup(
        self,
        on_press: Optional[Callable[[], None]] = None,
        on_hold: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Setup button handler with callbacks.

        Args:
            on_press: Callback for button press (short press).
            on_hold: Callback for button hold (long press).

        Returns:
            True if setup successful.
        """
        self._on_press = on_press
        self._on_hold = on_hold

        if self.mode == ExecutionMode.DRY_RUN:
            logger.info(f"[DRY-RUN] Would setup GPIO {self.gpio_pin} button")
            logger.info(f"  pull_up={self.pull_up}, hold_time={self.hold_time}s")
            self._available = True
            return True

        elif self.mode == ExecutionMode.PREVIEW:
            print(f"[PREVIEW] Setting up GPIO {self.gpio_pin} button")
            print(f"  pull_up={self.pull_up}, hold_time={self.hold_time}s")
            self._available = True
            return True

        try:
            from gpiozero import Button

            if self._button is None:
                self._button = Button(
                    self.gpio_pin,
                    pull_up=self.pull_up,
                    hold_time=self.hold_time,
                    bounce_time=0.1,
                )
                logger.info(f"Button handler setup on GPIO {self.gpio_pin}")

            # cancel any pending stable-release arm timer
            if self._arm_timer is not None:
                self._arm_timer.cancel()
                self._arm_timer = None

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._button.when_released = None
                self._button.when_pressed = on_press if on_press else None
                self._button.when_held = on_hold if on_hold else None

            self._available = True
            return True

        except ImportError:
            logger.warning("gpiozero not available (not on Pi?)")
            self._available = False
            return False

        except Exception as e:
            logger.error(f"Failed to setup button: {e}")
            self._available = False
            return False

    def setup_after_release(
        self,
        on_press: Optional[Callable[[], None]] = None,
        on_hold: Optional[Callable[[], None]] = None,
        stable_secs: float = 1.0,
    ) -> bool:
        """버튼이 stable_secs 동안 HIGH(떼짐)를 유지한 후에 콜백을 등록한다.

        단순 엣지 감지 대신 안정 구간을 요구하므로 바운스에 강건하다.
        setup()이 호출되면 대기 타이머도 자동 취소된다.
        """
        if self._button is None:
            return self.setup(on_press=on_press, on_hold=on_hold)

        def _cancel():
            if self._arm_timer is not None:
                self._arm_timer.cancel()
                self._arm_timer = None

        def _arm():
            self._arm_timer = None
            if self._button is None or self._button.is_pressed:
                return
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._button.when_released = None
                self._button.when_pressed = None
            self.setup(on_press=on_press, on_hold=on_hold)
            logger.debug("Button exit callback armed after %.1fs stable release", stable_secs)

        def _start_wait():
            _cancel()
            self._arm_timer = threading.Timer(stable_secs, _arm)
            self._arm_timer.daemon = True
            self._arm_timer.start()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._button.when_released = lambda: _start_wait()
            self._button.when_pressed = lambda: _cancel()

        if not self._button.is_pressed:
            # 이미 떼진 상태 → 즉시 대기 시작
            _start_wait()

        logger.debug("Button held — waiting %.1fs stable release", stable_secs)
        return True

    def cleanup(self) -> None:
        """Cleanup button handler and release GPIO."""
        if self._button is not None:
            try:
                self._button.close()
            except Exception:
                pass
            self._button = None

        self._available = False
        logger.debug("Button handler cleaned up")

    def simulate_press(self) -> None:
        """Simulate button press (for testing)."""
        if self._on_press:
            logger.info("Simulating button press")
            self._on_press()

    def simulate_hold(self) -> None:
        """Simulate button hold (for testing)."""
        if self._on_hold:
            logger.info("Simulating button hold")
            self._on_hold()

    @property
    def is_available(self) -> bool:
        """Check if button handler is available."""
        return self._available

    @property
    def is_pressed(self) -> bool:
        """Check if button is currently pressed."""
        if self._button is None:
            return False
        return self._button.is_pressed


# Global instance
_button_handler: Optional[ButtonHandler] = None


def get_button_handler() -> ButtonHandler:
    """Get global button handler instance."""
    global _button_handler
    if _button_handler is None:
        _button_handler = ButtonHandler.from_config()
    return _button_handler


def reset_button_handler() -> None:
    """Reset global button handler (cleanup and recreate)."""
    global _button_handler
    if _button_handler is not None:
        _button_handler.cleanup()
    _button_handler = None
