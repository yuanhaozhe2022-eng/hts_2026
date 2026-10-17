"""Game telemetry (gear, RPM, speed, fuel, lights, laps...) for the phone's dashboard.

Gear convention everywhere: 0 = reverse, 1 = neutral, 2 = 1st, 3 = 2nd, ...
(this is what both OutGauge and the Assetto Corsa shared memory use).

Optional fields are None when the game doesn't provide them; the phone hides those.
"""

from dataclasses import dataclass, field

# Dashboard lights, in display order. A source reports only the ones its game supports.
LIGHTS = ("signal_l", "abs", "tc", "handbrake", "pit", "highbeam", "oil", "battery", "signal_r")


@dataclass(frozen=True)
class Lap:
    position: int | None = None
    lap: int | None = None          # lap being driven, from 1
    current_ms: int | None = None
    last_ms: int | None = None
    best_ms: int | None = None


@dataclass(frozen=True)
class Sample:
    gear: int = 1
    rpm: float = 0.0
    max_rpm: float = 7000.0
    speed_kmh: float | None = None
    shift_light: bool = False
    fuel: float | None = None          # 0..1 of the tank
    engine_temp: float | None = None   # °C
    boost: float | None = None         # bar
    lights: dict = field(default_factory=dict)  # supported light -> on/off
    lap: Lap | None = None
    source: str = "none"
    time: float = 0.0  # time.monotonic() when received

    def to_message(self) -> dict:
        r1 = lambda x: None if x is None else round(x, 1)
        msg = {
            "t": "tel",
            "g": self.gear,
            "r": round(self.rpm),
            "m": round(self.max_rpm),
            "v": r1(self.speed_kmh),
            "sl": self.shift_light,
            "f": None if self.fuel is None else round(self.fuel, 3),
            "et": r1(self.engine_temp),
            "bo": None if self.boost is None else round(self.boost, 2),
            "li": self.lights,
            "lp": None,
            "src": self.source,
        }
        if self.lap is not None:
            msg["lp"] = {"p": self.lap.position, "n": self.lap.lap, "c": self.lap.current_ms,
                         "l": self.lap.last_ms, "b": self.lap.best_ms}
        return msg
