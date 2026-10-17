"""Fallback dashboard data when no game telemetry is arriving.

Gear is counted from shift presses; RPM just follows the throttle. It can drift
from the game (e.g. after auto-shifts), which is why the phone shows an EST badge.
"""

from ..state import InputState
from . import Sample

IDLE_RPM = 900.0
MAX_RPM = 7000.0
MAX_GEAR = 8 + 1  # 8th gear in the 0=R, 1=N, 2=1st convention


class Estimator:
    name = "est"

    def __init__(self):
        self.gear = 1
        self.rpm = IDLE_RPM
        self._prev = InputState()

    def on_input(self, state: InputState) -> None:
        if state.pressed("shift_up") and not self._prev.pressed("shift_up"):
            self.gear = min(MAX_GEAR, self.gear + 1)
        if state.pressed("shift_down") and not self._prev.pressed("shift_down"):
            self.gear = max(0, self.gear - 1)
        self._prev = state
        target = IDLE_RPM + state.throttle * (MAX_RPM - IDLE_RPM)
        self.rpm += (target - self.rpm) * 0.15

    def sync(self, sample: Sample) -> None:
        """Follow real telemetry so the estimate continues sensibly if it drops out."""
        self.gear = sample.gear

    def sample(self, now: float) -> Sample:
        return Sample(gear=self.gear, rpm=self.rpm, max_rpm=MAX_RPM, source=self.name, time=now)
