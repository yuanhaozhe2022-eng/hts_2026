"""Vibration motors in the phone mount, driven by an Arduino over USB serial.

Like an Xbox controller's rumble, there are two motors, left and right (one is fine too). An
Arduino (arduino/pocketwheel_vibration) runs them; this module decides how hard they buzz,
about 100 times a second:
  game     the rumble the game sends to the virtual Xbox controller (left = large motor)
  gears    a thump on every gear change
  shift    pulses at the shift point (redline)
  abs      a buzz while ABS is working
  engine   a light hum that rises with RPM (off by default)
Everything stops whenever no phone is driving (or the safety watchdog released the controls).

Serial protocol, 115200 baud, one line per message:
  PC -> Arduino  "V<left 0..255>,<right 0..255>\\n";  "?\\n"  who are you?
  Arduino -> PC  "POCKETWHEEL VIBRATION <version>\\n"
"""

import logging

from . import arduino

log = logging.getLogger(__name__)

# Adjustable from the phone (and config.json): key -> (min, max), or bool.
SETTINGS = {
    "enabled": bool,
    "strength": (0.0, 1.0),
    "game": bool,
    "gears": bool,
    "shift": bool,
    "abs": bool,
    "engine": bool,
}

THUMP_S = 0.12     # gear change
SHIFT_AT = 0.92    # fraction of max RPM, same as the phone's shift light
SHIFT_ON_S, SHIFT_PERIOD_S = 0.06, 0.18
TEST_S = 0.6


def validate_settings(changes, current: dict) -> dict:
    """Merge changes from the phone into the settings; raises ValueError."""
    return arduino.validate_settings(changes, current, SETTINGS, "vibration")


class VibrationModel:
    """How hard each motor should run (0..1) right now."""

    def __init__(self):
        self._gear = None
        self._thump_until = -1.0

    def levels(self, settings: dict, sample, rumble: tuple, now: float) -> tuple[float, float]:
        left = right = 0.0
        if settings["game"]:
            left, right = rumble
        if sample is not None:
            if self._gear is not None and sample.gear != self._gear and settings["gears"]:
                self._thump_until = now + THUMP_S
            self._gear = sample.gear
            ratio = sample.rpm / sample.max_rpm if sample.max_rpm > 0 else 0.0
            both = 0.0
            if now < self._thump_until:
                both = 1.0
            elif settings["shift"] and (sample.shift_light or ratio >= SHIFT_AT):
                both = 0.7 if (now % SHIFT_PERIOD_S) < SHIFT_ON_S else 0.0
            if settings["abs"] and sample.lights.get("abs"):
                both = max(both, 0.55)
            if settings["engine"] and sample.rpm > 0:
                both = max(both, 0.08 + 0.17 * min(1.0, ratio))
            left, right = max(left, both), max(right, both)
        k = settings["strength"]
        return min(1.0, left * k), min(1.0, right * k)

    def reset(self) -> None:
        self._gear = None
        self._thump_until = -1.0


def levels_line(left: float, right: float) -> str:
    to_byte = lambda x: round(min(1.0, max(0.0, x)) * 255)
    return f"V{to_byte(left)},{to_byte(right)}"


class Vibration:
    """Settings, the model and the serial link, updated by the app's loop."""

    def __init__(self, config: dict, link: arduino.SerialLink | None = None, on_settings=None):
        self.settings = {key: config[key] for key in SETTINGS}
        self.rate_hz = config.get("rate_hz", 100)
        self.link = link or arduino.SerialLink("VIBRATION", "Vibration motors",
                                               config.get("port", "auto"), config.get("baud", 115200))
        self.model = VibrationModel()
        self.on_settings = on_settings  # callable(settings) to persist
        self.rumble = (0.0, 0.0)        # game rumble (large, small) 0..1, set by the app
        self.levels = (0.0, 0.0)
        self._test_until = -1.0

    def set_settings(self, changes) -> bool:
        try:
            self.settings = validate_settings(changes, self.settings)
        except ValueError as exc:
            log.warning("Ignored vibration settings: %s", exc)
            return False
        if self.on_settings:
            self.on_settings(dict(self.settings))
        return True

    def test(self, now: float) -> None:
        """Buzz both motors briefly (the phone's Test button), even without driving."""
        self._test_until = now + TEST_S

    @property
    def status(self) -> str:
        if not self.settings["enabled"]:
            return "off"
        if not self.link.is_open:
            return "No Arduino found"
        return f"{self.link.board if self.link.matches else 'Arduino'} on {self.link.port}"

    def message(self) -> dict:
        return {"t": "vib", "settings": self.settings, "status": self.status}

    def tick(self, now: float, sample, active: bool) -> None:
        if not self.settings["enabled"]:
            if self.link.is_open:
                self.link.close(stop_line="V0,0")
            self.levels = (0.0, 0.0)
            return
        if not self.link.try_open(now):
            return
        if now < self._test_until:
            # Left, then right, then both: shows which motor is which.
            part = (TEST_S - (self._test_until - now)) / TEST_S
            k = self.settings["strength"]
            self.levels = (k, 0.0) if part < 0.33 else (0.0, k) if part < 0.66 else (k, k)
        elif active:
            self.levels = self.model.levels(self.settings, sample, self.rumble, now)
        else:
            self.model.reset()
            self.levels = (0.0, 0.0)
        self.link.send_line(levels_line(*self.levels), now)

    def close(self) -> None:
        self.link.close(stop_line="V0,0")
