"""Assetto Corsa / Assetto Corsa Competizione shared-memory telemetry (Windows only).

The game publishes named file mappings "Local\\acpmf_physics", "Local\\acpmf_static" and
"Local\\acpmf_graphics" (laps, position).
We only ever *open* them (OpenFileMappingW). Python's mmap(tagname=...) would create
an empty mapping when the game isn't running yet, which can break the game's own
mapping when it starts, so it is deliberately not used here.
"""

import asyncio
import ctypes
import logging
import sys
import time

from . import Lap, Sample

log = logging.getLogger(__name__)


f32, i32 = ctypes.c_float, ctypes.c_int32


class Physics(ctypes.Structure):
    """Leading fields of SPageFilePhysics, up to turboBoost (same layout in AC and ACC)."""

    _pack_ = 4
    _fields_ = [
        ("packetId", i32),
        ("gas", f32),
        ("brake", f32),
        ("fuel", f32),                 # litres
        ("gear", i32),
        ("rpms", i32),
        ("steerAngle", f32),
        ("speedKmh", f32),
        ("velocity", f32 * 3),
        ("accG", f32 * 3),
        ("wheelSlip", f32 * 4),
        ("wheelLoad", f32 * 4),
        ("wheelsPressure", f32 * 4),
        ("wheelAngularSpeed", f32 * 4),
        ("tyreWear", f32 * 4),
        ("tyreDirtyLevel", f32 * 4),
        ("tyreCoreTemperature", f32 * 4),
        ("camberRAD", f32 * 4),
        ("suspensionTravel", f32 * 4),
        ("drs", f32),
        ("tc", f32),
        ("heading", f32),
        ("pitch", f32),
        ("roll", f32),
        ("cgHeight", f32),
        ("carDamage", f32 * 5),
        ("numberOfTyresOut", i32),
        ("pitLimiterOn", i32),
        ("abs", f32),
        ("kersCharge", f32),
        ("kersInput", f32),
        ("autoShifterOn", i32),
        ("rideHeight", f32 * 2),
        ("turboBoost", f32),
    ]


class Graphics(ctypes.Structure):
    """Leading fields of SPageFileGraphic, up to iBestTime (same layout in AC and ACC)."""

    _pack_ = 4
    _fields_ = [
        ("packetId", i32),
        ("status", i32),               # 0 off, 1 replay, 2 live, 3 pause
        ("session", i32),
        ("currentTime", ctypes.c_uint16 * 15),
        ("lastTime", ctypes.c_uint16 * 15),
        ("bestTime", ctypes.c_uint16 * 15),
        ("split", ctypes.c_uint16 * 15),
        ("completedLaps", i32),
        ("position", i32),
        ("iCurrentTime", i32),         # ms
        ("iLastTime", i32),
        ("iBestTime", i32),
    ]


AC_LIVE = 2


class Static(ctypes.Structure):
    """Leading fields of SPageFileStatic, up to maxFuel."""

    _pack_ = 4
    _fields_ = [
        ("smVersion", ctypes.c_uint16 * 15),
        ("acVersion", ctypes.c_uint16 * 15),
        ("numberOfSessions", ctypes.c_int32),
        ("numCars", ctypes.c_int32),
        ("carModel", ctypes.c_uint16 * 33),
        ("track", ctypes.c_uint16 * 33),
        ("playerName", ctypes.c_uint16 * 33),
        ("playerSurname", ctypes.c_uint16 * 33),
        ("playerNick", ctypes.c_uint16 * 33),
        ("sectorCount", ctypes.c_int32),
        ("maxTorque", ctypes.c_float),
        ("maxPower", ctypes.c_float),
        ("maxRpm", ctypes.c_int32),
        ("maxFuel", ctypes.c_float),   # litres
    ]


class SharedPage:
    """Read-only view of an existing named file mapping."""

    FILE_MAP_READ = 0x0004

    def __init__(self, name: str, struct_type):
        self.name, self.struct_type = name, struct_type
        self._handle = self._view = None
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        k32.OpenFileMappingW.restype = ctypes.c_void_p
        k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_uint32, ctypes.c_size_t]
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._k32 = k32

    def read(self):
        """Return a copy of the struct, or None if the game hasn't created the mapping."""
        if self._view is None and not self._open():
            return None
        return self.struct_type.from_buffer_copy(
            ctypes.string_at(self._view, ctypes.sizeof(self.struct_type))
        )

    def _open(self) -> bool:
        handle = self._k32.OpenFileMappingW(self.FILE_MAP_READ, False, self.name)
        if not handle:
            return False
        view = self._k32.MapViewOfFile(handle, self.FILE_MAP_READ, 0, 0,
                                       ctypes.sizeof(self.struct_type))
        if not view:
            self._k32.CloseHandle(handle)
            return False
        self._handle, self._view = handle, view
        return True

    def close(self) -> None:
        if self._view:
            self._k32.UnmapViewOfFile(self._view)
        if self._handle:
            self._k32.CloseHandle(self._handle)
        self._handle = self._view = None


def _lap_time(ms: int) -> int | None:
    # The game uses 0 or INT_MAX for "no time yet".
    return ms if 0 < ms < 24 * 3600 * 1000 else None


def _lap(graphics) -> Lap | None:
    if graphics is None or graphics.status != AC_LIVE:
        return None
    return Lap(
        position=graphics.position if graphics.position > 0 else None,
        lap=graphics.completedLaps + 1,
        current_ms=_lap_time(graphics.iCurrentTime),
        last_ms=_lap_time(graphics.iLastTime),
        best_ms=_lap_time(graphics.iBestTime),
    )


class AssettoSource:
    name = "assetto"
    POLL_HZ = 60
    # Let go of the mapping after this long without updates, so a game restart is picked up cleanly.
    RELEASE_AFTER_S = 5.0

    def __init__(self, read_pages=None):
        """read_pages() -> (Physics, Static, Graphics or None) or None.

        Defaults to the real shared memory."""
        self.latest: Sample | None = None
        self._read_pages = read_pages
        self._pages = None
        self._last_packet = None
        self._last_change = 0.0
        self._task = None

    def poll(self, now: float) -> None:
        pages = self._read_pages() if self._read_pages else self._read_shared()
        if pages is None:
            return
        physics, static, graphics = pages
        if physics.packetId == self._last_packet:
            # Game closed, paused or in a menu: the data is frozen, so it isn't "fresh".
            if now - self._last_change > self.RELEASE_AFTER_S:
                self._release()
            return
        self._last_packet = physics.packetId
        self._last_change = now
        self.latest = Sample(
            gear=physics.gear,
            rpm=float(physics.rpms),
            max_rpm=float(static.maxRpm) if static.maxRpm > 0 else 8000.0,
            speed_kmh=physics.speedKmh,
            shift_light=False,  # derived on the phone from rpm / max_rpm
            fuel=min(1.0, physics.fuel / static.maxFuel) if static.maxFuel > 0 else None,
            boost=max(0.0, physics.turboBoost) if physics.turboBoost > 0.01 else None,
            lights={"pit": bool(physics.pitLimiterOn)},
            lap=_lap(graphics),
            automatic=bool(physics.autoShifterOn),
            source=self.name,
            time=now,
        )

    def _read_shared(self):
        if self._pages is None:
            self._pages = (SharedPage("Local\\acpmf_physics", Physics),
                           SharedPage("Local\\acpmf_static", Static),
                           SharedPage("Local\\acpmf_graphics", Graphics))
        physics = self._pages[0].read()
        static = self._pages[1].read()
        if physics is None or static is None:
            return None
        return physics, static, self._pages[2].read()

    def _release(self) -> None:
        if self._pages:
            for page in self._pages:
                page.close()
            self._pages = None
        self._last_change = time.monotonic()

    async def start(self) -> None:
        if sys.platform != "win32" and self._read_pages is None:
            log.info("Assetto Corsa telemetry needs Windows; skipped.")
            return
        self._task = asyncio.create_task(self._run())
        log.info("Watching for Assetto Corsa / ACC shared memory")

    async def _run(self) -> None:
        while True:
            try:
                self.poll(time.monotonic())
            except Exception:
                log.exception("Assetto Corsa telemetry read failed")
                self._release()
            await asyncio.sleep(1 / self.POLL_HZ)

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
        self._release()
