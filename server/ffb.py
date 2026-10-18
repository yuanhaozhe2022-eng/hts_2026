"""Force feedback for a motorised phone base.

The phone sits on a base turned by a geared motor; an Arduino drives the motor's RC-style ESC
(see arduino/pocketwheel_ffb). This module works out a steering force and streams it to the
Arduino over USB serial (server/arduino.py), about 100 times a second.

Force is -1..1: positive turns the wheel right (clockwise, seen from the driver).
  Assetto Corsa / ACC: the game's own force feedback (physics.finalFF).
  Everything else: an estimate. A centering spring that firms up with speed, plus road feel
  (the game's controller rumble, ABS) as a light shake.
  Damping, from how fast the wheel is turning, is added on top so the motor doesn't overshoot.
  With no phone driving (or the controls released by the watchdog) the force is 0.

Serial lines: PC -> Arduino "F<-1000..1000>"; the sketch introduces itself as
"POCKETWHEEL FFB <version>".
"""

import logging
import math

from . import arduino

log = logging.getLogger(__name__)

# Adjustable from the phone (and config.json): key -> (min, max), or bool.
SETTINGS = {
    "enabled": bool,
    "invert": bool,
    "strength": (0.0, 2.0),  # overall gain; over 1 boosts (anything past full is capped)
    "spring": (0.0, 1.0),    # estimated centering (games without their own force feedback)
    "damping": (0.0, 1.0),   # resists fast wheel movement; raise it if the wheel oscillates
    "road": (0.0, 1.0),      # shake from game rumble and ABS
    "game": (0.0, 1.0),      # how much of the game's own force (AC self-aligning) vs the spring
    "minimum": (0.0, 0.6),   # lifts small forces: any push is at least this strong
}
# For settings missing from an older config.json.
DEFAULTS = {"enabled": False, "invert": False, "strength": 0.5, "spring": 0.6, "damping": 0.3,
            "road": 0.3, "game": 1.0, "minimum": 0.0}

GAME_FFB_HOLD_S = 5.0  # keep using the game's force this long after it was last non-zero
SHAKE_HZ = 20.0
FULL_SPRING_KMH = 60.0
# Centering builds up fast and levels off, like a real car's self-aligning torque: with
# tanh(3 x steer), 10% of full lock already gives ~30% of the spring, 30% gives ~70%.
SPRING_SHAPE = 3.0


def validate_settings(changes, current: dict) -> dict:
    """Merge changes from the phone into the settings; raises ValueError."""
    return arduino.validate_settings(changes, current, SETTINGS, "force feedback")


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, x))


class FfbModel:
    """Steering force from telemetry, the wheel position and the game's rumble."""

    def __init__(self):
        self._prev_steer = None
        self._changed_at = 0.0  # when the phone's steering value last changed
        self._velocity = 0.0    # wheel speed, full-lock units per second (smoothed)
        self._game_seen = -math.inf
        self.using_game = False

    def force(self, settings: dict, sample, steer: float, rumble: float, now: float, dt: float) -> float:
        self._track_velocity(steer, now)

        game = sample.ffb if sample is not None else None
        if game is not None and abs(game) > 0.002:
            self._game_seen = now
        self.using_game = game is not None and now - self._game_seen < GAME_FFB_HOLD_S
        speed = (sample.speed_kmh if sample is not None else None) or 0.0
        stiffness = 0.15 + 0.85 * min(1.0, speed / FULL_SPRING_KMH)  # light when parked
        spring = -settings["spring"] * stiffness * math.tanh(SPRING_SHAPE * steer)
        if self.using_game:
            # The game's force follows the car's path (self-aligning); "game" < 1 swaps some
            # of it for the plain spring, which only pulls towards straight.
            mix = settings.get("game", 1.0)
            base = mix * _clamp(game) + (1 - mix) * spring
        else:
            base = spring

        abs_on = bool(sample is not None and sample.lights.get("abs"))
        shake = max(rumble, 0.5 if abs_on else 0.0) * settings["road"] * 0.4
        if shake > 0.01:
            base += shake if int(now * SHAKE_HZ * 2) % 2 else -shake

        push = _clamp(settings["strength"] * base)
        # Minimum force lifts the real push (spring / game / road) only, never damping's
        # small corrections, which it would turn into twitching.
        minimum = settings.get("minimum", 0.0)
        if minimum > 0 and abs(push) > 0.02:
            push = math.copysign(minimum + (1 - minimum) * abs(push), push)
        damping = -settings["damping"] * _clamp(0.12 * self._velocity, -0.6, 0.6)
        total = push + settings["strength"] * damping
        return _clamp(-total if settings["invert"] else total)

    def _track_velocity(self, steer: float, now: float) -> None:
        """How fast the wheel turns, from the phone's own updates (~60 a second, unevenly
        spaced over Wi-Fi) rather than this loop's 100 Hz ticks: measuring between ticks
        reads 0, then a spike, which damping would turn into twitching."""
        if self._prev_steer is None:
            self._prev_steer, self._changed_at = steer, now
            return
        if steer != self._prev_steer:
            gap = now - self._changed_at
            if 0 < gap < 0.25:
                raw = (steer - self._prev_steer) / gap
                self._velocity += (raw - self._velocity) * 0.3
            self._prev_steer, self._changed_at = steer, now
        elif now - self._changed_at > 0.08:  # no news for a while: the wheel has stopped
            self._velocity *= 0.85

    def reset(self) -> None:
        self._prev_steer = None
        self._velocity = 0.0


def force_line(force: float) -> str:
    return f"F{round(_clamp(force) * 1000)}"


class ForceFeedback:
    """Settings, the model and the serial link, updated by the app's loop."""

    def __init__(self, config: dict, link: arduino.SerialLink | None = None, on_settings=None):
        self.settings = {key: config.get(key, DEFAULTS[key]) for key in SETTINGS}
        self.rate_hz = config.get("rate_hz", 100)
        self.link = link or arduino.SerialLink("FFB", "Force feedback",
                                               config.get("port", "auto"), config.get("baud", 115200))
        self.model = FfbModel()
        self.on_settings = on_settings  # callable(settings) to persist
        self.rumble = 0.0               # game rumble 0..1, set by the app
        self.force = 0.0
        self._last = None

    def set_settings(self, changes) -> bool:
        try:
            self.settings = validate_settings(changes, self.settings)
        except ValueError as exc:
            log.warning("Ignored force feedback settings: %s", exc)
            return False
        if self.on_settings:
            self.on_settings(dict(self.settings))
        return True

    @property
    def status(self) -> str:
        if not self.settings["enabled"]:
            return "off"
        if not self.link.is_open:
            return "No Arduino found"
        if not self.model.using_game:
            source = "estimated"
        elif self.settings["game"] <= 0:
            source = "centering spring (game force off)"
        else:
            source = f"game force {round(self.settings['game'] * 100)}%"
        board = self.link.board if self.link.matches else "Arduino"
        return f"{board} on {self.link.port} · {source}"

    def message(self) -> dict:
        return {"t": "ffb", "settings": self.settings, "status": self.status}

    def tick(self, now: float, sample, steer: float, active: bool) -> None:
        dt = 0.0 if self._last is None else now - self._last
        self._last = now
        if not self.settings["enabled"]:
            if self.link.is_open:
                self.link.close(stop_line="F0")
            self.force = 0.0
            return
        if not self.link.try_open(now):
            return
        if active:
            self.force = self.model.force(self.settings, sample, steer, self.rumble, now, dt)
        else:
            self.model.reset()
            self.force = 0.0
        self.link.send_line(force_line(self.force), now)

    def close(self) -> None:
        self.link.close(stop_line="F0")
