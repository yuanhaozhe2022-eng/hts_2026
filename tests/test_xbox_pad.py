"""XboxPad against a stand-in vgamepad module (the real one needs the ViGEmBus driver)."""

import sys
import types

import pytest

from server.gamepad import XboxPad
from server.state import BTN_SHIFT_DOWN, BTN_SHIFT_UP, InputState


class FakeGamepad:
    def __init__(self):
        self.calls = []
        self.down = set()

    def press_button(self, button):
        self.down.add(button)
        self.calls.append(("press", button))

    def release_button(self, button):
        self.down.discard(button)
        self.calls.append(("release", button))

    def __getattr__(self, name):  # sticks, triggers, update, reset, notifications
        return lambda *args, **kwargs: None


@pytest.fixture
def pad(monkeypatch):
    fake = types.ModuleType("vgamepad")
    fake.VX360Gamepad = FakeGamepad
    fake.XUSB_BUTTON = types.SimpleNamespace(
        XUSB_GAMEPAD_A="A", XUSB_GAMEPAD_X="X",
        XUSB_GAMEPAD_LEFT_SHOULDER="LB", XUSB_GAMEPAD_RIGHT_SHOULDER="RB")
    monkeypatch.setitem(sys.modules, "vgamepad", fake)
    return XboxPad({"shift_up": "A", "shift_down": "X"}, loop=None)


def test_presses_bound_buttons(pad):
    pad.apply(InputState(buttons=BTN_SHIFT_UP))
    assert pad._pad.down == {"A"}
    pad.apply(InputState(buttons=BTN_SHIFT_DOWN))
    assert pad._pad.down == {"X"}
    pad.neutral()
    assert pad._pad.down == set()


def test_rebind_while_held_releases_old_button(pad):
    pad.apply(InputState(buttons=BTN_SHIFT_UP))
    pad.set_bindings({"shift_up": "RIGHT_SHOULDER", "shift_down": "LEFT_SHOULDER"})
    assert pad._pad.down == {"RB"}
    assert ("release", "A") in pad._pad.calls


def test_shared_button_stays_down_until_both_released(pad):
    pad.set_bindings({"shift_up": "A", "shift_down": "A"})
    pad.apply(InputState(buttons=BTN_SHIFT_UP | BTN_SHIFT_DOWN))
    pad.apply(InputState(buttons=BTN_SHIFT_DOWN))
    assert pad._pad.down == {"A"}
    pad.apply(InputState())
    assert pad._pad.down == set()
    assert pad._pad.calls.count(("press", "A")) == 1
