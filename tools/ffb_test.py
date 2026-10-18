"""Bench-test the force feedback base without a game or phone.

  python tools/ffb_test.py                 gentle push left, stop, push right, stop (repeats)
  python tools/ffb_test.py --sweep         slow back-and-forth sine
  python tools/ffb_test.py --force 0.2     hold one force (-1..1, positive = turn right)
  python tools/ffb_test.py --port COM5 --amp 0.3

Stop main.py first (only one program can use the serial port). Ctrl+C stops the motor.
Start with a small --amp and keep hands clear the first time.
"""

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.arduino import SerialLink  # noqa: E402
from server.ffb import force_line  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", default="auto", help="serial port, e.g. COM5 (default: find it)")
    parser.add_argument("--amp", type=float, default=0.25, help="force for the test, 0..1")
    parser.add_argument("--sweep", action="store_true", help="smooth sine instead of steps")
    parser.add_argument("--force", type=float, help="hold this one force")
    args = parser.parse_args()

    link = SerialLink("FFB", "Force feedback", args.port)
    start = time.monotonic()
    while not link.try_open(time.monotonic()):
        if time.monotonic() - start > 6:
            sys.exit("No Arduino found. Plug it in, close the Arduino Serial Monitor, or pass --port.")
        time.sleep(0.2)
    print(f"Arduino on {link.port}; waiting for it to boot...")
    amp = max(0.0, min(1.0, args.amp))
    steps = [(-amp, "push LEFT"), (0.0, "stop"), (amp, "push RIGHT"), (0.0, "stop")]
    shown = None
    try:
        while True:
            now = time.monotonic()
            t = now - start
            if args.force is not None:
                force, label = args.force, f"hold {args.force:+.2f}"
            elif args.sweep:
                force = amp * math.sin(2 * math.pi * t / 4)
                label = "sweep"
            else:
                force, label = steps[int(t / 1.5) % len(steps)]
            link.try_open(now)  # with "auto", moves on if this port is another board
            if link.send_line(force_line(force), now) and label != shown:
                shown = label
                print(f"  {label:<12} force {force:+.2f}" + (f"   ({link.board})" if link.matches else ""))
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        link.close(stop_line="F0")
        print("Stopped.")


if __name__ == "__main__":
    main()
