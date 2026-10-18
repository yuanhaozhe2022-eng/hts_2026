"""Bench-test the vibration motors without a game or phone.

  python tools/vibration_test.py              left, right, both, then a ramp up (repeats)
  python tools/vibration_test.py --level 0.5  hold both motors at one strength (0..1)
  python tools/vibration_test.py --port COM5

Stop main.py first (only one program can use the serial port). Ctrl+C stops the motors.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.arduino import SerialLink  # noqa: E402
from server.vibration import levels_line  # noqa: E402

STEPS = [((1.0, 0.0), "LEFT motor"), ((0.0, 0.0), "off"), ((0.0, 1.0), "RIGHT motor"),
         ((0.0, 0.0), "off"), ((1.0, 1.0), "both"), ((0.0, 0.0), "off")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", default="auto", help="serial port, e.g. COM5 (default: find it)")
    parser.add_argument("--level", type=float, help="hold both motors at this strength, 0..1")
    args = parser.parse_args()

    link = SerialLink("VIBRATION", "Vibration motors", args.port)
    start = time.monotonic()
    while not link.try_open(time.monotonic()):
        if time.monotonic() - start > 6:
            sys.exit("No Arduino found. Plug it in, close the Arduino Serial Monitor, or pass --port.")
        time.sleep(0.2)
    print(f"Arduino on {link.port}; waiting for it to boot...")
    shown = None
    try:
        while True:
            now = time.monotonic()
            t = now - start
            if args.level is not None:
                levels, label = (args.level, args.level), f"both at {args.level:.0%}"
            else:
                cycle = t % 9
                if cycle < 6:
                    levels, label = STEPS[int(cycle)]
                else:  # ramp: finds the weakest buzz you can still feel
                    k = (cycle - 6) / 3
                    levels, label = (k, k), "ramp up"
            link.try_open(now)  # with "auto", moves on if this port is another board
            if link.send_line(levels_line(*levels), now) and label != shown:
                shown = label
                print(f"  {label}" + (f"   ({link.board})" if link.matches else ""))
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        link.close(stop_line="V0,0")
        print("Stopped.")


if __name__ == "__main__":
    main()
