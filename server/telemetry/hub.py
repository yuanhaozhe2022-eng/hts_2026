"""Chooses which telemetry source feeds the phone."""

import dataclasses
import math
import time

from ..state import InputState
from . import Sample
from .estimate import Estimator

STALE_AFTER_S = 1.0


class AutomaticDetector:
    """Guesses whether the gearbox shifts by itself, for games that don't say (BeamNG's
    OutGauge only sends the gear number): a change between forward gears with no shift
    button pressed shortly before means automatic; one that follows a press means manual.
    """

    PRESS_WINDOW_S = 1.5

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.automatic: bool | None = None
        self._gear = None
        self._last_press = -math.inf

    def on_shift_pressed(self, now: float) -> None:
        self._last_press = now

    def on_gear(self, gear: int, now: float) -> None:
        prev, self._gear = self._gear, gear
        if prev is None or gear == prev or prev < 2 or gear < 2:
            return  # only 1st..nth changes say anything (not N, R or the first reading)
        self.automatic = now - self._last_press > self.PRESS_WINDOW_S


class TelemetryHub:
    def __init__(self, sources, clock=time.monotonic):
        self.sources = list(sources)
        self.estimator = Estimator()
        self.detector = AutomaticDetector()
        self.clock = clock
        self._source = None

    def on_input(self, state: InputState) -> None:
        self.estimator.on_input(state)
        if state.pressed("shift_up") or state.pressed("shift_down"):
            self.detector.on_shift_pressed(self.clock())

    def latest(self, now: float) -> Sample:
        fresh = [s.latest for s in self.sources
                 if s.latest is not None and now - s.latest.time <= STALE_AFTER_S]
        if not fresh:
            self._source = None
            return self.estimator.sample(now)

        best = max(fresh, key=lambda sample: sample.time)
        self.estimator.sync(best)
        if best.source != self._source:  # new game or reconnect: forget the old guess
            self._source = best.source
            self.detector.reset()
        self.detector.on_gear(best.gear, now)
        if best.automatic is None and self.detector.automatic is not None:
            best = dataclasses.replace(best, automatic=self.detector.automatic)
        return best

    async def start(self) -> None:
        for source in self.sources:
            await source.start()

    def stop(self) -> None:
        for source in self.sources:
            source.stop()
