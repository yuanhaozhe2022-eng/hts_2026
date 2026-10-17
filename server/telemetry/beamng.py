"""BeamNG.drive telemetry: OutGauge, plus gear names from the PhoneWheel BeamNG mod.

Enable in BeamNG: Options > Other > OutGauge, IP 127.0.0.1, port 4444.

OutGauge only has a gear number, and BeamNG automatics report Park and Neutral both as 0.
The optional mod (beamng_mod/, `python main.py --install-beamng-mod`, then Options > Other >
"Other protocols") adds what the in-game dash shows (P, R, N, D, S3, M2...) and the redline.
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
# PhoneWheel mod packet: magic, gear name, redline (see beamng_mod/.../phonewheel.lua).
GEAR_PACKET = struct.Struct("<4s8sf")
GEAR_MAGIC = b"PWG1"
GEAR_FRESH_S = 1.0


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


def parse_gear_packet(data: bytes) -> tuple[str, float] | None:
    """(gear name, redline) from the mod, or None if it isn't one of its packets."""
    if len(data) != GEAR_PACKET.size or not data.startswith(GEAR_MAGIC):
        return None
    _, name, max_rpm = GEAR_PACKET.unpack(data)
    return name.split(b"\0", 1)[0].decode("ascii", "replace").strip(), max_rpm


def gear_display(name: str, gear: int) -> tuple[str, str | None, bool]:
    """(big label, small label, automatic) for a BeamNG gear name.

    Manuals send the gear as a number (-1 reverse, 0 neutral); automatics send their mode:
    P, R, N, D (shown with the actual gear small), S3 / M2 (sport / manual mode + gear).
    """
    try:
        n = int(float(name))
    except ValueError:
        n = None
    if n is not None:
        return ("R" if n < 0 else "N" if n == 0 else str(n)), None, False
    head, rest = name[:1].upper(), name[1:]
    if head in ("P", "R", "N"):
        return head, None, True
    if head in ("D", "S", "M"):
        return head, rest or (str(gear - 1) if gear >= 2 else None), True
    return name[:3], None, True


class _GearListener(asyncio.DatagramProtocol):
    def __init__(self, source):
        self.source = source

    def datagram_received(self, data, addr):
        self.source.handle_gear_packet(data, time.monotonic())


class BeamNGSource(asyncio.DatagramProtocol):
    name = "beamng"

    def __init__(self, host: str = "127.0.0.1", port: int = 4444, gear_port: int = 4445):
        self.host, self.port, self.gear_port = host, port, gear_port
        self._gear = None  # (name, redline, time) from the mod
        self._gear_transport = None
        self.latest: Sample | None = None
        self._car = None
        self._peak_rpm = DEFAULT_MAX_RPM
        self._has_turbo = False
        self._transport = None
        self._bad_sizes: set[int] = set()

    def handle_packet(self, data: bytes, now: float) -> None:
        p = parse_outgauge(data)
        if p is None:
            if len(data) not in self._bad_sizes:  # once per size, not 60 times a second
                self._bad_sizes.add(len(data))
                log.warning("Ignoring a %d-byte packet on the OutGauge port (expected %d or %d)",
                            len(data), OUTGAUGE.size, OUTGAUGE.size + 4)
            return
        if self._car is None:
            log.info("BeamNG telemetry: receiving OutGauge data")
        if p.car != self._car:
            self._car = p.car
            self._peak_rpm = DEFAULT_MAX_RPM
            self._has_turbo = False
        self._peak_rpm = max(self._peak_rpm, p.rpm)
        # Show boost once the car proves it has a turbo, so the readout doesn't flicker at idle.
        self._has_turbo = self._has_turbo or p.turbo_gauge or p.boost > 0.05

        label = sub = automatic = None
        max_rpm = self._peak_rpm
        if self._gear and now - self._gear[2] <= GEAR_FRESH_S:
            label, sub, automatic = gear_display(self._gear[0], p.gear)
            if self._gear[1] > 0:
                max_rpm = self._gear[1]
        self.latest = Sample(
            gear=p.gear,
            gear_label=label,
            gear_sub=sub,
            automatic=automatic,
            rpm=p.rpm,
            max_rpm=max_rpm,
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

    def handle_gear_packet(self, data: bytes, now: float) -> None:
        parsed = parse_gear_packet(data)
        if parsed is None:
            return
        if self._gear is None:
            log.info("BeamNG: PhoneWheel mod connected (real gear names, e.g. P)")
        self._gear = (*parsed, now)

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
        try:
            self._gear_transport, _ = await loop.create_datagram_endpoint(
                lambda: _GearListener(self), local_addr=(self.host, self.gear_port))
        except OSError as exc:
            log.warning("BeamNG gear names (mod) disabled: cannot bind UDP %s:%d (%s)",
                        self.host, self.gear_port, exc)

    def stop(self) -> None:
        for transport in (self._transport, self._gear_transport):
            if transport:
                transport.close()
