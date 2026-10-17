"""Chooses which telemetry source feeds the phone."""

from ..state import InputState
from . import Sample
from .estimate import Estimator

STALE_AFTER_S = 1.0


class TelemetryHub:
    def __init__(self, sources):
        self.sources = list(sources)
        self.estimator = Estimator()

    def on_input(self, state: InputState) -> None:
        self.estimator.on_input(state)

    def latest(self, now: float) -> Sample:
        fresh = [s.latest for s in self.sources
                 if s.latest is not None and now - s.latest.time <= STALE_AFTER_S]
        if fresh:
            best = max(fresh, key=lambda sample: sample.time)
            self.estimator.sync(best)
            return best
        return self.estimator.sample(now)

    async def start(self) -> None:
        for source in self.sources:
            await source.start()

    def stop(self) -> None:
        for source in self.sources:
            source.stop()
