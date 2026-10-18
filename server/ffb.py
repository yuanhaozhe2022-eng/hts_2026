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
    "strength": (0.0, 1.0),  # overall
    "spring": (0.0, 1.0),    # estimated centering (games without their own force feedback)
    "damping": (0.0, 1.0),   # resists fast wheel movement; raise it if the wheel oscillates
    "road": (0.0, 1.0),      # shake from game rumble and ABS
}

GAME_FFB_HOLD_S = 5.0  # keep using the game's force this long after it was last non-zero
SHAKE_HZ = 20.0
FULL_SPRING_KMH = 60.0


def validate_settings(changes, current: dict) -> dict:
    """Merge changes from the phone into the settings; raises ValueError."""
    return arduino.validate_settings(changes, current, SETTINGS, "force feedback")


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, x))


class FfbModel:
    """Steering force from telemetry, the wheel position and the game's rumble."""

    def __init__(self):
        self._prev_steer = None
        self._velocity = 0.0  # wheel speed, full-lock units per second (smoothed)
        self._game_seen = -math.inf
        self.using_game = False

    def force(self, settings: dict, sample, steer: float, rumble: float, now: float, dt: float) -> float:
        if self._prev_steer is not None and dt > 0:
            raw = (steer - self._prev_steer) / dt
            self._velocity += (raw - self._velocity) * min(1.0, dt / 0.03)
        self._prev_steer = steer

        game = sample.ffb if sample is not None else None
        if game is not None and abs(game) > 0.002:
            self._game_seen = now
        self.using_game = game is not None and now - self._game_seen < GAME_FFB_HOLD_S
        if self.using_game:
            base = _clamp(game)
        else:
            speed = (sample.speed_kmh if sample is not None else None) or 0.0
            stiffness = 0.15 + 0.85 * min(1.0, speed / FULL_SPRING_KMH)  # light when parked
            base = -settings["spring"] * stiffness * steer

        abs_on = bool(sample is not None and sample.lights.get("abs"))
        shake = max(rumble, 0.5 if abs_on else 0.0) * settings["road"] * 0.4
        if shake > 0.01:
            base += shake if int(now * SHAKE_HZ * 2) % 2 else -shake

        damping = -settings["damping"] * _clamp(0.12 * self._velocity, -0.6, 0.6)
        total = settings["strength"] * (base + damping)
        return _clamp(-total if settings["invert"] else total)

    def reset(self) -> None:
        self._prev_steer = None
        self._velocity = 0.0


def force_line(force: float) -> str:
    return f"F{round(_clamp(force) * 1000)}"


class ForceFeedback:
    """Settings, the model and the serial link, updated by the app's loop."""

    def __init__(self, config: dict, link: arduino.SerialLink | None = None, on_settings=None):
        self.settings = {key: config[key] for key in SETTINGS}
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
        source = "game force" if self.model.using_game else "estimated"
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
