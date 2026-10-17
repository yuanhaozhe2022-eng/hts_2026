"""User-defined phone controls: buttons, joysticks and axes.

A control is {"id": "c1a2", "label": "Cam", "kind": "button" | "joystick" | "axis",
"bind": ...}; the list is kept in config.json. Binds per kind:

  button    "pad:Y" (Xbox button) or "key:H" (keyboard key)
  joystick  "stick:right" | "stick:left" (Xbox sticks) or "keys:wasd" | "keys:arrows"
  axis      "axis:RX" | "axis:RY" | "axis:LY" (stick axes, -1..1) or "axis:LT" | "axis:RT" (0..1)

The phone sends the ids of held buttons ("c") and the values of controls being touched ("a").
"""

import re
from dataclasses import dataclass

from .keyboard import KEYS
from .state import XBOX_BUTTONS

MAX_BUTTONS = 12
MAX_LABEL = 12
ID_PATTERN = re.compile(r"^[a-z0-9]{1,12}$")

BIND_OPTIONS = {
    "button": tuple([f"pad:{b}" for b in XBOX_BUTTONS] + [f"key:{k}" for k in KEYS]),
    "joystick": ("stick:right", "stick:left", "keys:wasd", "keys:arrows"),
    "axis": ("axis:RX", "axis:RY", "axis:LY", "axis:LT", "axis:RT"),
}
TRIGGERS = {"LT", "RT"}
STICKS = {"stick:left": ("LX", "LY"), "stick:right": ("RX", "RY")}
# Joystick -> keys: (up, left, down, right). A key is held past half deflection.
KEY_SETS = {"keys:wasd": ("W", "A", "S", "D"), "keys:arrows": ("UP", "LEFT", "DOWN", "RIGHT")}
KEY_THRESHOLD = 0.5


def validate_custom(buttons) -> list[dict]:
    """Check a custom control list from the phone or config.json; raises ValueError."""
    if not isinstance(buttons, list):
        raise ValueError("custom controls must be a list")
    if len(buttons) > MAX_BUTTONS:
        raise ValueError(f"at most {MAX_BUTTONS} custom controls")
    out, seen = [], set()
    for b in buttons:
        if not isinstance(b, dict):
            raise ValueError("each custom control must be an object")
        bid, label, bind = b.get("id"), b.get("label"), b.get("bind")
        kind = b.get("kind", "button")  # lists saved before joysticks/axes existed
        if not isinstance(bid, str) or not ID_PATTERN.match(bid) or bid in seen:
            raise ValueError(f"bad or duplicate id {bid!r}")
        if not isinstance(label, str):
            raise ValueError(f"{bid}: label must be text")
        if kind not in BIND_OPTIONS:
            raise ValueError(f"{bid}: unknown kind {kind!r}")
        if bind not in BIND_OPTIONS[kind]:
            raise ValueError(f"{bid}: {bind!r} isn't a valid {kind} bind")
        seen.add(bid)
        out.append({"id": bid, "label": label.strip()[:MAX_LABEL] or "?", "kind": kind, "bind": bind})
    return out


@dataclass(frozen=True)
class Resolved:
    pad_buttons: frozenset = frozenset()   # Xbox buttons to hold
    keys: frozenset = frozenset()          # keyboard keys to hold
    axes: tuple = ()                       # (("RX", 0.4), ...) Xbox axes to set


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def resolve(controls: list[dict], pressed_ids, analog: dict) -> Resolved:
    """What the held / touched custom controls ask of the pad and the keyboard."""
    pad, keys, axes = set(), set(), {}
    for c in controls:
        cid, kind, bind = c["id"], c["kind"], c["bind"]
        if kind == "button":
            if cid in pressed_ids:
                target, name = bind.split(":", 1)
                (pad if target == "pad" else keys).add(name)
        elif kind == "joystick" and isinstance(analog.get(cid), tuple):
            x, y = analog[cid]
            if bind in STICKS:
                ax, ay = STICKS[bind]
                axes[ax], axes[ay] = x, y
            else:
                up, left, down, right = KEY_SETS[bind]
                keys.update(k for k, on in ((up, y > KEY_THRESHOLD), (down, y < -KEY_THRESHOLD),
                                            (left, x < -KEY_THRESHOLD), (right, x > KEY_THRESHOLD)) if on)
        elif kind == "axis" and isinstance(analog.get(cid), float):
            name = bind.split(":", 1)[1]
            v = analog[cid]
            axes[name] = _clamp(v, 0.0, 1.0) if name in TRIGGERS else v
    return Resolved(frozenset(pad), frozenset(keys), tuple(sorted(axes.items())))
