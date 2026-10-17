"""Send fake BeamNG OutGauge packets so the phone dashboard can be tested without the game.

    python tools/fake_outgauge.py [--port 4444] [--mod]

--mod also sends what the PocketWheel BeamNG mod sends (gear names: P while parked, then D),
as an automatic car would.

Revs up through the gears and back to neutral in a loop, with fuel, engine temperature,
boost and dash lights (blinking signals, handbrake in neutral, ABS/TC flickers).
"""

import argparse
import math
import socket
import struct
import time

OUTGAUGE = struct.Struct("<I4sHBBfffffffIIfff16s16s")
OG_TURBO = 1 << 13
DL = {"shift": 1 << 0, "highbeam": 1 << 1, "handbrake": 1 << 2, "tc": 1 << 4, "signal_l": 1 << 5,
      "signal_r": 1 << 6, "oil": 1 << 8, "battery": 1 << 9, "abs": 1 << 10}
CAR_HAS = sum(DL.values())
IDLE, REDLINE, SHIFT_AT = 900.0, 7200.0, 6800.0
GEAR_PACKET = struct.Struct("<4s8sf")


def lights(t: float, gear: int, rpm: float) -> int:
    on = DL["highbeam"]
    if rpm >= SHIFT_AT:
        on |= DL["shift"]
    if gear == 1:
        on |= DL["handbrake"]
    blink = int(t * 2) % 2 == 0                # 1 Hz turn signal
    if blink and int(t / 6) % 2 == 0:
        on |= DL["signal_l"]
    elif blink:
        on |= DL["signal_r"]
    if gear == 2 and rpm < 3000:
        on |= DL["tc"]                         # wheelspin pulling away
    if int(t * 3) % 17 == 0:
        on |= DL["abs"]
    return on


def packet(t: float, gear: int, rpm: float, speed_ms: float) -> bytes:
    fuel = 0.6 - (t % 120) / 120 * 0.55        # drains to 5% every two minutes
    eng_temp = min(92.0, 70 + t * 0.5)
    boost = max(0.0, (rpm - 2500) / 4700 * 1.2) if gear > 1 else 0.0
    return OUTGAUGE.pack(int(t * 1000) & 0xFFFFFFFF, b"fake", OG_TURBO, gear, 0, speed_ms, rpm,
                         boost, eng_temp, fuel, 4.0, 90, CAR_HAS, lights(t, gear, rpm),
                         0.8 + 0.2 * math.sin(t), 0, 0, b"", b"")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4444)
    parser.add_argument("--mod", action="store_true", help="also send BeamNG mod gear names")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Sending fake OutGauge to {args.host}:{args.port} (Ctrl+C to stop)")
    gear, rpm, t0 = 1, IDLE, time.monotonic()
    neutral_since = t0
    try:
        while True:
            now = time.monotonic()
            if gear == 1:                      # neutral: idle briefly, then 1st
                rpm = IDLE
                if now - neutral_since > 1.5:
                    gear = 2
            else:
                rpm += (REDLINE - rpm) * 0.03 + 25
                if rpm >= REDLINE - 50:        # shift up; after 6th go back to neutral
                    gear, rpm = (gear + 1, 4200.0) if gear < 7 else (1, IDLE)
                    neutral_since = now
            speed = (gear - 1) * 8 + (rpm - IDLE) / 400 if gear > 1 else 0.0
            sock.sendto(packet(now - t0, gear, rpm, speed), (args.host, args.port))
            if args.mod:
                name = b"P" if gear == 1 else b"D"   # parked between runs, then Drive
                sock.sendto(GEAR_PACKET.pack(b"PWG1", name, REDLINE), (args.host, args.port + 1))
            time.sleep(1 / 60)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
