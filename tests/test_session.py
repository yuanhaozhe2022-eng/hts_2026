import asyncio
import math

import pytest

from server.app import Session
from server.gamepad import Pad
from server.state import BTN_SHIFT_DOWN, BTN_SHIFT_UP, NEUTRAL, InputState, parse_input, validate_bindings
from server.telemetry.hub import TelemetryHub


class RecordingPad(Pad):
    def __init__(self, bindings=None):
        super().__init__(bindings)
        self.writes = []

    def _write(self, state):
        self.writes.append(state)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeWs:
    def __init__(self):
        self.closed = False
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)

    async def close(self):
        self.closed = True


DEFAULT_BINDINGS = {"shift_up": "RIGHT_SHOULDER", "shift_down": "LEFT_SHOULDER"}


def make_session(saved=None):
    pad, clock = RecordingPad(DEFAULT_BINDINGS), Clock()
    session = Session(pad, TelemetryHub([]), watchdog_s=0.3, clock=clock,
                      on_bindings=None if saved is None else saved.append)
    return session, pad, clock


def test_parse_input_clamps_and_sanitizes():
    s = parse_input({"s": -3, "th": 1.5, "br": "0.25", "b": 3})
    assert s == InputState(steer=-1.0, throttle=1.0, brake=0.25, buttons=3)
    assert s.pressed("shift_down") and s.pressed("shift_up")
    assert parse_input({"s": math.nan, "th": None, "b": "x"}) == NEUTRAL


def test_input_reaches_pad():
    session, pad, _ = make_session()
    session.on_input({"t": "in", "s": 0.5, "th": 0.8, "br": 0, "b": 2})
    assert pad.state == InputState(steer=0.5, throttle=0.8, brake=0.0, buttons=2)


def test_watchdog_releases_controls_after_silence():
    session, pad, clock = make_session()
    session.on_input({"s": 0.3, "th": 1.0})
    clock.now = 0.25
    session.check_watchdog()
    assert pad.state.throttle == 1.0
    clock.now = 0.35
    session.check_watchdog()
    assert pad.state == NEUTRAL
    writes = len(pad.writes)
    clock.now = 1.0
    session.check_watchdog()  # already neutral: no repeated writes
    assert len(pad.writes) == writes


def test_new_phone_takes_over_and_old_one_is_told():
    session, pad, _ = make_session()
    first, second = FakeWs(), FakeWs()
    asyncio.run(session.attach(first, "10.0.0.1", "a"))
    session.on_input({"th": 1.0})
    asyncio.run(session.attach(second, "10.0.0.2", "b"))
    assert first.closed and first.sent == [{"t": "kicked", "by": "10.0.0.2"}]
    assert session.ws is second
    assert pad.state == NEUTRAL  # takeover starts from released controls
    session.detach(first)        # the old socket's cleanup must not drop the new phone
    assert session.ws is second
    session.on_input({"th": 0.4})
    session.detach(second)
    assert session.ws is None and pad.state == NEUTRAL


def test_automatic_reconnects_dont_steal_control_from_a_driving_phone():
    session, pad, clock = make_session()
    a, b = FakeWs(), FakeWs()
    asyncio.run(session.attach(a, "10.0.0.1", "a"))
    session.on_input({"th": 1.0})
    # Phone B reconnects by itself while A drives: refused, A keeps control.
    assert not asyncio.run(session.attach(b, "10.0.0.2", "b", auto=True))
    assert b.closed and b.sent == [{"t": "kicked", "by": "10.0.0.1"}]
    assert session.ws is a and not a.closed and pad.state != NEUTRAL
    # A's own page coming back after a dropout always gets in.
    a2 = FakeWs()
    assert asyncio.run(session.attach(a2, "10.0.0.1", "a", auto=True))
    assert session.ws is a2
    # Once A has gone quiet, an automatic reconnect may take over.
    clock.now += 2
    b2 = FakeWs()
    assert asyncio.run(session.attach(b2, "10.0.0.2", "b", auto=True))
    assert session.ws is b2 and a2.closed
    # Tapping "Take control back" always works.
    session.on_input({"th": 0.5})
    a3 = FakeWs()
    assert asyncio.run(session.attach(a3, "10.0.0.1", "a"))
    assert session.ws is a3 and b2.sent == [{"t": "kicked", "by": "10.0.0.1"}]


def test_rebind_from_phone_applies_and_persists():
    saved = []
    session, pad, _ = make_session(saved)
    assert session.set_bindings({"shift_up": "A"})  # partial: shift_down keeps its button
    assert pad.bindings == {"shift_up": "A", "shift_down": "LEFT_SHOULDER"}
    assert saved == [pad.bindings]
    msg = session.bindings_message()
    assert msg["t"] == "binds" and msg["buttons"]["shift_up"] == "A" and "X" in msg["options"]


def test_rebind_rejects_unknown_buttons_and_actions():
    saved = []
    session, pad, _ = make_session(saved)
    assert not session.set_bindings({"shift_up": "GUIDE"})
    assert not session.set_bindings({"shift_up": None})
    assert not session.set_bindings("A")
    assert pad.bindings == DEFAULT_BINDINGS and saved == []
    with pytest.raises(ValueError):
        validate_bindings({"shift_up": "A"})  # every action must be bound


def test_held_buttons_follow_bindings_and_may_share_a_button():
    pad = RecordingPad({"shift_up": "A", "shift_down": "X"})
    both = InputState(buttons=BTN_SHIFT_UP | BTN_SHIFT_DOWN)
    assert pad.held_buttons(both) == {"A", "X"}
    pad.set_bindings({"shift_up": "A", "shift_down": "A"})
    assert pad.held_buttons(both) == {"A"}
    assert pad.held_buttons(InputState(buttons=BTN_SHIFT_DOWN)) == {"A"}


def test_rebinding_while_held_moves_the_press():
    pad = RecordingPad({"shift_up": "RIGHT_SHOULDER", "shift_down": "LEFT_SHOULDER"})
    pad.apply(InputState(buttons=BTN_SHIFT_UP))
    pad.set_bindings({"shift_up": "A", "shift_down": "LEFT_SHOULDER"})
    assert pad.writes[-1] == InputState(buttons=BTN_SHIFT_UP)  # re-applied with the new map
    assert pad.held_buttons(pad.state) == {"A"}
