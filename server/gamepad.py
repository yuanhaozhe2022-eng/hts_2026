"""Virtual Xbox 360 pad driven by the phone's InputState.

Uses vgamepad (ViGEmBus). If the driver or package is missing, DryRunPad keeps
the rest of the app usable so the phone UI and telemetry can still be tested.
"""

import logging

from .state import BUTTON_BITS, NEUTRAL, InputState

log = logging.getLogger(__name__)


def stick_values(state: InputState) -> tuple[float, float, float, float, float, float]:
    """(LX, LY, RX, RY, LT, RT) for the pad: steering and pedals, plus custom axes/joysticks.

    A joystick on the left stick takes over steering only while it's being touched; an axis
    on a trigger combines with its pedal (the stronger one wins)."""
    axes = dict(state.axes)
    return (axes.get("LX", state.steer), axes.get("LY", 0.0),
            axes.get("RX", 0.0), axes.get("RY", 0.0),
            max(state.brake, axes.get("LT", 0.0)), max(state.throttle, axes.get("RT", 0.0)))


class Pad:
    """Base: remembers the last applied state. Subclasses push it somewhere."""

    name = "pad"

    def __init__(self, bindings: dict[str, str] | None = None):
        self.state = NEUTRAL
        self.bindings = dict(bindings or {})  # phone action -> Xbox button name
        self.on_rumble = None  # callable(large: float, small: float), set by the app

    def apply(self, state: InputState) -> None:
        self.state = state
        self._write(state)

    def neutral(self) -> None:
        self.apply(NEUTRAL)

    def set_bindings(self, bindings: dict[str, str]) -> None:
        """Rebind buttons; anything held is moved to its new button straight away."""
        self.bindings = dict(bindings)
        self.apply(self.state)

    def held_buttons(self, state: InputState) -> set[str]:
        """Xbox buttons that should be down: bound shift buttons plus custom buttons.
        Several may share one Xbox button."""
        return {self.bindings[action] for action in BUTTON_BITS
                if action in self.bindings and state.pressed(action)} | set(state.extra_buttons)

    def close(self) -> None:
        pass

    def _write(self, state: InputState) -> None:
        raise NotImplementedError


class DryRunPad(Pad):
    """Accepts input but drives nothing."""

    name = "dry-run (no virtual controller)"

    def _write(self, state: InputState) -> None:
        pass


class XboxPad(Pad):
    name = "virtual Xbox 360 controller"

    def __init__(self, bindings: dict[str, str], loop):
        super().__init__(bindings)
        import vgamepad as vg  # raises if the package or ViGEmBus driver is missing

        self._vg = vg
        self._pad = vg.VX360Gamepad()
        self._held: set[str] = set()

        # vgamepad checks the callback's parameter names, so they must match exactly.
        # It fires on a ViGEm thread; hop back onto the event loop.
        def notification(client, target, large_motor, small_motor, led_number, user_data):
            if self.on_rumble:
                loop.call_soon_threadsafe(self.on_rumble, large_motor / 255, small_motor / 255)

        self._notification = notification
        self._pad.register_notification(callback_function=notification)
        self._pad.reset()
        self._pad.update()

    def _button(self, name: str):
        return getattr(self._vg.XUSB_BUTTON, "XUSB_GAMEPAD_" + name)

    def _write(self, state: InputState) -> None:
        x, y, rx, ry, lt, rt = stick_values(state)
        self._pad.left_joystick_float(x_value_float=x, y_value_float=y)
        self._pad.right_joystick_float(x_value_float=rx, y_value_float=ry)
        self._pad.right_trigger_float(value_float=rt)
        self._pad.left_trigger_float(value_float=lt)
        held = self.held_buttons(state)
        for name in self._held - held:
            self._pad.release_button(button=self._button(name))
        for name in held - self._held:
            self._pad.press_button(button=self._button(name))
        self._held = held
        self._pad.update()

    def close(self) -> None:
        self.neutral()
        self._pad.unregister_notification()


def create_pad(bindings: dict[str, str], loop, dry_run: bool = False) -> Pad:
    if dry_run:
        return DryRunPad(bindings)
    try:
        return XboxPad(bindings, loop)
    except Exception as exc:  # ImportError, or ViGEmBus not installed / not running
        log.warning("Virtual controller unavailable (%s). Running in dry-run mode.", exc)
        log.warning("Install it with: pip install vgamepad  (accept the ViGEmBus driver installer)")
        return DryRunPad(bindings)
