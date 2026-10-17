"""BeamNG.drive OutGauge UDP telemetry.

Enable in BeamNG: Options > Other > Protocols > OutGauge, IP 127.0.0.1, port 4444.
"""

import asyncio
import logging
import struct
import time
from typing import NamedTuple

from . import Sample

log = logging.getLogger(__name__)

# time, car[4], flags, gear, plid, speed, rpm, turbo, engTemp, fuel, oilPressure,
# oilTemp, dashLights, showLights, throttle, brake, clutch, display1[16], display2[16]
OUTGAUGE = struct.Struct("<I4sHBBfffffffIIfff16s16s")  # 92 bytes; +4 if the optional id is sent
OG_TURBO = 1 << 13   # flags: the car has a turbo gauge

# OutGauge dash light bits. dashLights says which ones the car has, showLights which are on.
DL_SHIFT = 1 << 0
DASH_LIGHTS = {
    "highbeam": 1 << 1,
    "handbrake": 1 << 2,
    "pit": 1 << 3,
    "tc": 1 << 4,
    "signal_l": 1 << 5,
    "signal_r": 1 << 6,
    "oil": 1 << 8,
    "battery": 1 << 9,
    "abs": 1 << 10,
}
# OutGauge has no redline field; start here and learn the real one from the highest RPM seen.
DEFAULT_MAX_RPM = 4000.0


class OutGauge(NamedTuple):
    car: str
    gear: int
    rpm: float
    speed_kmh: float
    shift_light: bool
    turbo_gauge: bool
    boost: float
    engine_temp: float
    fuel: float
    lights: dict


def parse_outgauge(data: bytes) -> OutGauge | None:
    """Decode a packet, or None if it's malformed."""
    if len(data) not in (OUTGAUGE.size, OUTGAUGE.size + 4):
        return None
    f = OUTGAUGE.unpack_from(data)
    flags, dash_lights, show_lights = f[2], f[12], f[13]
    return OutGauge(
        car=f[1].rstrip(b"\0").decode("ascii", "replace"),
        gear=f[3],
        rpm=f[6],
        speed_kmh=f[5] * 3.6,
        shift_light=bool(show_lights & DL_SHIFT),
        turbo_gauge=bool(flags & OG_TURBO),
        boost=f[7],
        engine_temp=f[8],
        fuel=min(1.0, max(0.0, f[9])),
        lights={name: bool(show_lights & bit) for name, bit in DASH_LIGHTS.items() if dash_lights & bit},
    )


class BeamNGSource(asyncio.DatagramProtocol):
    name = "beamng"

    def __init__(self, host: str = "127.0.0.1", port: int = 4444):
        self.host, self.port = host, port
        self.latest: Sample | None = None
        self._car = None
        self._peak_rpm = DEFAULT_MAX_RPM
        self._has_turbo = False
        self._transport = None

    def handle_packet(self, data: bytes, now: float) -> None:
        p = parse_outgauge(data)
        if p is None:
            return
        if p.car != self._car:
            self._car = p.car
            self._peak_rpm = DEFAULT_MAX_RPM
            self._has_turbo = False
        self._peak_rpm = max(self._peak_rpm, p.rpm)
        # Show boost once the car proves it has a turbo, so the readout doesn't flicker at idle.
        self._has_turbo = self._has_turbo or p.turbo_gauge or p.boost > 0.05
        self.latest = Sample(
            gear=p.gear,
            rpm=p.rpm,
            max_rpm=self._peak_rpm,
            speed_kmh=p.speed_kmh,
            shift_light=p.shift_light,
            fuel=p.fuel,
            engine_temp=p.engine_temp if p.engine_temp > 0 else None,
            boost=max(0.0, p.boost) if self._has_turbo else None,
            lights=p.lights,
            source=self.name,
            time=now,
        )

    def datagram_received(self, data, addr):
        self.handle_packet(data, time.monotonic())

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: self, local_addr=(self.host, self.port)
            )
            log.info("Listening for BeamNG OutGauge on %s:%d", self.host, self.port)
        except OSError as exc:
            log.warning("BeamNG telemetry disabled: cannot bind UDP %s:%d (%s). Is another "
                        "copy of PhoneWheel running?", self.host, self.port, exc)

    def stop(self) -> None:
        if self._transport:
            self._transport.close()
