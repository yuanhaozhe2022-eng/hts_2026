"""The control state the phone sends, and parsing of its wire format."""

import math
from dataclasses import dataclass

# Bits of the "b" field in an input message.
BTN_SHIFT_DOWN = 1 << 0
BTN_SHIFT_UP = 1 << 1

BUTTON_BITS = {
    "shift_down": BTN_SHIFT_DOWN,
    "shift_up": BTN_SHIFT_UP,
}

# Xbox buttons a phone button can be bound to (vgamepad XUSB_GAMEPAD_* names).
# GUIDE is left out: on Windows it opens the Game Bar instead of reaching the game.
XBOX_BUTTONS = (
    "A", "B", "X", "Y",
    "LEFT_SHOULDER", "RIGHT_SHOULDER",
    "LEFT_THUMB", "RIGHT_THUMB",
    "START", "BACK",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
)


def validate_bindings(bindings) -> dict[str, str]:
    """Check a {phone action: Xbox button} map covers every action with known buttons."""
    if not isinstance(bindings, dict):
        raise ValueError("bindings must be an object")
    out = {}
    for action in BUTTON_BITS:
        button = bindings.get(action)
        if button not in XBOX_BUTTONS:
            raise ValueError(f"{action}: unknown Xbox button {button!r}")
        out[action] = button
    return out


@dataclass(frozen=True)
class InputState:
    steer: float = 0.0     # -1 (full left) .. 1 (full right)
    throttle: float = 0.0  # 0 .. 1
    brake: float = 0.0     # 0 .. 1
    buttons: int = 0       # bitmask of BTN_*

    def pressed(self, name: str) -> bool:
        return bool(self.buttons & BUTTON_BITS[name])


NEUTRAL = InputState()


def _num(value, lo: float, hi: float) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(x):
        return 0.0
    return min(hi, max(lo, x))


def parse_input(msg: dict) -> InputState:
    """Turn an input message {"s", "th", "br", "b"} into a clamped InputState."""
    try:
        buttons = int(msg.get("b", 0)) & 0xFFFF
    except (TypeError, ValueError):
        buttons = 0
    return InputState(
        steer=_num(msg.get("s"), -1.0, 1.0),
        throttle=_num(msg.get("th"), 0.0, 1.0),
        brake=_num(msg.get("br"), 0.0, 1.0),
        buttons=buttons,
    )
