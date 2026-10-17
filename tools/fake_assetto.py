"""Publish fake Assetto Corsa shared memory so the phone dashboard can be tested without the game.

    python tools/fake_assetto.py [--auto]    (--auto: report the auto-shifter as on)

Windows only. Don't run it while AC/ACC itself is running: it creates the same named
memory the game uses.
"""

import ctypes
import mmap
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.telemetry.assetto import AC_LIVE, Graphics, Physics, Static  # noqa: E402

IDLE, REDLINE, TANK = 1000, 8500, 110.0


def page(name: str, struct_type):
    return mmap.mmap(-1, ctypes.sizeof(struct_type), tagname=name)


def write(mem, struct_obj) -> None:
    mem.seek(0)
    mem.write(bytes(struct_obj))


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Assetto Corsa shared memory only exists on Windows.")
    automatic = int("--auto" in sys.argv)
    physics_mem = page("Local\\acpmf_physics", Physics)
    static_mem = page("Local\\acpmf_static", Static)
    graphics_mem = page("Local\\acpmf_graphics", Graphics)
    write(static_mem, Static(maxRpm=REDLINE, maxFuel=TANK))
    print("Publishing fake Assetto Corsa telemetry (Ctrl+C to stop)")

    packet, gear, rpm, laps = 0, 2, float(IDLE), 0
    t0 = lap_start = time.monotonic()
    last_lap = best_lap = 0
    try:
        while True:
            now = time.monotonic()
            rpm += (REDLINE - rpm) * 0.03 + 30
            if rpm >= REDLINE - 60:
                gear, rpm = (gear + 1, 5600.0) if gear < 7 else (2, float(IDLE))
            lap_ms = int((now - lap_start) * 1000)
            if lap_ms > 20000:                 # 20 s "laps" so the times change while watching
                laps += 1
                last_lap = lap_ms
                best_lap = min(best_lap or lap_ms, lap_ms)
                lap_start, lap_ms = now, 0
            packet += 1
            write(physics_mem, Physics(
                packetId=packet, gear=gear, rpms=int(rpm),
                speedKmh=(gear - 1) * 35 + (rpm - IDLE) / 120,
                fuel=TANK * (0.8 - ((now - t0) % 180) / 180 * 0.75),
                pitLimiterOn=int(laps % 3 == 2), autoShifterOn=automatic, turboBoost=max(0.0, (rpm - 3000) / 5500 * 1.4)))
            write(graphics_mem, Graphics(
                status=AC_LIVE, completedLaps=laps, position=3 if laps % 2 else 5,
                iCurrentTime=lap_ms, iLastTime=last_lap, iBestTime=best_lap or 2147483647))
            time.sleep(1 / 60)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
