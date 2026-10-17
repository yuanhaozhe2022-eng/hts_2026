import ctypes
import sys

import pytest

from server.app import Session
from server.custom import MAX_BUTTONS, resolve, validate_custom
from server.gamepad import Pad, stick_values
from server.keyboard import Keyboard
from server.telemetry.hub import TelemetryHub

HORN = {"id": "c1", "label": "Horn", "kind": "button", "bind": "key:H"}
LIGHTS = {"id": "c2", "label": "Lights", "kind": "button", "bind": "pad:Y"}
CAM = {"id": "j1", "label": "Cam", "kind": "joystick", "bind": "stick:right"}
WALK = {"id": "j2", "label": "Walk", "kind": "joystick", "bind": "keys:wasd"}
LOOK = {"id": "a1", "label": "Look", "kind": "axis", "bind": "axis:RX"}
GAS2 = {"id": "a2", "label": "Gas", "kind": "axis", "bind": "axis:RT"}


class RecordingPad(Pad):
    def _write(self, state):
        pass


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def make_session(saved=None):
    events = []
    keyboard = Keyboard(send=lambda name, down: events.append((name, down)))
    pad, clock = RecordingPad({"shift_up": "A", "shift_down": "X"}), Clock()
    session = Session(pad, TelemetryHub([]), watchdog_s=0.3, clock=clock, keyboard=keyboard,
                      custom_buttons=[HORN, LIGHTS, CAM, WALK],
                      on_custom=None if saved is None else saved.append)
    return session, pad, events, clock


def test_validate_trims_labels_and_rejects_bad_buttons():
    # No "kind": a list saved before joysticks/axes existed, read as buttons.
    assert validate_custom([{"id": "a1", "label": "  Wipers and more  ", "bind": "key:F5"}]) == [
        {"id": "a1", "label": "Wipers and m", "kind": "button", "bind": "key:F5"}]
    assert validate_custom([CAM, LOOK]) == [CAM, LOOK]
    for bad in ([{"id": "a1", "label": "x", "bind": "key:ALT"}],          # Alt isn't allowed
                [{"id": "a1", "label": "x", "bind": "pad:GUIDE"}],
                [{"id": "A B", "label": "x", "bind": "key:H"}],
                [{"id": "j", "label": "x", "kind": "joystick", "bind": "pad:A"}],  # wrong kind
                [{"id": "a", "label": "x", "kind": "axis", "bind": "axis:LX"}],    # that's steering
                [{"id": "x", "label": "x", "kind": "slider", "bind": "axis:RX"}],
                [HORN, dict(HORN)],                                       # duplicate id
                [{"id": f"c{i}", "label": "x", "bind": "key:H"} for i in range(MAX_BUTTONS + 1)],
                "nope"):
        with pytest.raises(ValueError):
            validate_custom(bad)


def test_resolve_splits_pad_and_keyboard():
    r = resolve([HORN, LIGHTS], {"c1", "c2", "unknown"}, {})
    assert (r.pad_buttons, r.keys, r.axes) == (frozenset({"Y"}), frozenset({"H"}), ())
    assert resolve([HORN, LIGHTS], set(), {}) == resolve([], set(), {})


def test_joysticks_and_axes_resolve_to_sticks_triggers_and_keys():
    r = resolve([CAM, LOOK, GAS2, WALK], set(),
                {"j1": (0.5, -0.25), "a2": -0.4, "j2": (-0.8, 0.9)})
    assert dict(r.axes) == {"RX": 0.5, "RY": -0.25, "RT": 0.0}   # trigger axis can't go negative
    assert r.keys == {"W", "A"}                                   # walk up-left
    r = resolve([LOOK, WALK], set(), {"a1": 0.3, "j2": (0.2, -0.1)})
    assert dict(r.axes) == {"RX": 0.3} and r.keys == set()        # small deflection: no key


def test_custom_buttons_press_keys_and_pad_buttons():
    session, pad, events, _ = make_session()
    session.on_input({"t": "in", "c": ["c1", "c2"], "b": 2})
    assert events == [("H", True)]
    assert pad.held_buttons(pad.state) == {"A", "Y"}  # shift up (A) + custom Y
    session.on_input({"t": "in", "c": []})
    assert events == [("H", True), ("H", False)]
    assert pad.held_buttons(pad.state) == set()


def test_watchdog_releases_held_keys():
    session, _, events, clock = make_session()
    session.on_input({"t": "in", "c": ["c1"]})
    clock.now = 1.0
    session.check_watchdog()
    assert events[-1] == ("H", False)


def test_editing_custom_buttons_persists_and_releases_everything():
    saved = []
    session, _, events, _ = make_session(saved)
    session.on_input({"t": "in", "c": ["c1"]})
    assert session.set_custom([LIGHTS])
    assert saved == [[LIGHTS]] and session.custom == [LIGHTS]
    assert events[-1] == ("H", False)
    assert not session.set_custom([{"id": "x", "label": "x", "bind": "key:WIN"}])
    assert session.custom == [LIGHTS]
    msg = session.bindings_message()
    assert msg["custom"] == [LIGHTS] and "SPACE" in msg["keys"] and "WIN" not in msg["keys"]


def test_joystick_messages_reach_the_pad_and_keyboard():
    session, pad, events, _ = make_session()
    session.on_input({"t": "in", "s": 0.2, "a": {"j1": [0.6, 0.1], "j2": [0, 1]}})
    assert stick_values(pad.state)[:4] == (0.2, 0.0, 0.6, 0.1)  # steering kept, camera on right stick
    assert events == [("W", True)]
    session.on_input({"t": "in", "s": 0.2})                      # thumbs off: all back
    assert stick_values(pad.state)[:4] == (0.2, 0.0, 0.0, 0.0) and events[-1] == ("W", False)


def test_left_stick_joystick_overrides_steering_only_while_touched():
    from server.state import InputState
    walking = InputState(steer=0.7, throttle=0.2, axes=(("LX", -0.5), ("LY", 0.8), ("RT", 0.9)))
    assert stick_values(walking) == (-0.5, 0.8, 0.0, 0.0, 0.0, 0.9)
    assert stick_values(InputState(steer=0.7, brake=0.3)) == (0.7, 0.0, 0.0, 0.0, 0.3, 0.0)


def test_parse_input_analog_values_are_clamped_and_sanitised():
    from server.state import parse_input
    s = parse_input({"a": {"j": [2, -0.5], "a": -3, "bad": "x", "b": True, "n": [1]}})
    assert dict(s.analog) == {"j": (1.0, -0.5), "a": -1.0}


@pytest.mark.skipif(sys.platform != "win32", reason="SendInput is Windows only")
def test_sendinput_structure_has_the_size_windows_expects():
    from server.keyboard import INPUT
    assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
