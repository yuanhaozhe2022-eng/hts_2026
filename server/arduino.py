"""USB serial link to a PocketWheel Arduino sketch (vibration motors, force feedback base).

Each sketch answers "?" with "POCKETWHEEL <KIND> <version>", e.g. "POCKETWHEEL FFB 1". With
port "auto" a link tries every Arduino-looking port in turn and keeps the one whose sketch is
its kind, so the vibration board and the force feedback board can be plugged in together.
Writes never block: the app calls send_line() about 100 times a second from its event loop.
"""

import logging

log = logging.getLogger(__name__)

# USB serial chips found on Arduinos and clones: Arduino, Arduino.org, CH340, FTDI, CP210x.
ARDUINO_VIDS = {0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4}
BOOT_S = 2.0    # an Arduino resets when the port opens; let the bootloader finish
RETRY_S = 3.0
HELLO_S = 3.0   # with port "auto", a board that hasn't introduced itself by then isn't ours


def candidate_ports() -> list[str]:
    from serial.tools import list_ports

    ports = []
    for port in list_ports.comports():
        text = f"{port.description} {port.manufacturer or ''}".lower()
        if port.vid in ARDUINO_VIDS or "arduino" in text or "ch340" in text:
            ports.append(port.device)
    return ports


def validate_settings(changes, current: dict, specs: dict, what: str) -> dict:
    """Merge settings changes from the phone; specs: key -> bool or (min, max). Raises ValueError."""
    if not isinstance(changes, dict):
        raise ValueError(f"{what} settings must be an object")
    out = dict(current)
    for key, value in changes.items():
        if key not in specs:
            continue
        spec = specs[key]
        if spec is bool:
            if not isinstance(value, bool):
                raise ValueError(f"{what} {key} must be true/false")
        elif not (isinstance(value, (int, float)) and not isinstance(value, bool)
                  and spec[0] <= value <= spec[1]):
            raise ValueError(f"{what} {key} must be {spec[0]}..{spec[1]}")
        out[key] = value
    return out


class SerialLink:
    """One sketch's Arduino, found and reopened by itself (unplugged, replugged...)."""

    def __init__(self, kind: str, name: str, port: str = "auto", baud: int = 115200,
                 ports=candidate_ports):
        self.kind = kind            # what the sketch says after "POCKETWHEEL ", e.g. "FFB"
        self.name = name            # for log messages, e.g. "Force feedback"
        self.port_setting, self.baud = port, baud
        self._ports = ports
        self.serial = None
        self.port = None
        self.ready_at = 0.0
        self.board = None           # the sketch's introduction
        self._next_try = 0.0
        self._warned = False
        self._buffer = b""
        self._asked = -1.0
        self._rejected = set()      # ports holding some other board

    @property
    def is_open(self) -> bool:
        return self.serial is not None

    def _warn(self, message: str, *args) -> None:
        if not self._warned:
            log.warning(f"{self.name}: {message}", *args)
            self._warned = True

    def try_open(self, now: float) -> bool:
        if self.serial is not None:
            return True
        if now < self._next_try:
            return False
        self._next_try = now + RETRY_S
        try:
            import serial
        except ImportError:
            self._warn("pip install pyserial")
            return False
        auto = self.port_setting == "auto"
        found = self._ports() if auto else [self.port_setting]
        ports = [p for p in found if p not in self._rejected]
        if auto and found and not ports:
            self._rejected.clear()  # all taken by other boards: maybe they were swapped
        if not ports:
            self._warn("no Arduino with the PocketWheel %s sketch found. Plug it in (or set the "
                       "port in config.json, e.g. \"COM5\"); still looking.", self.kind)
            return False
        for port in ports:
            try:
                self.serial = serial.Serial(port, self.baud, timeout=0, write_timeout=0)
            except (serial.SerialException, OSError) as exc:
                log.debug("%s: %s busy or unavailable (%s)", self.name, port, exc)
                continue
            self.port, self.ready_at, self.board, self._warned = port, now + BOOT_S, None, False
            self._buffer, self._asked = b"", -1.0
            log.info("%s: trying the Arduino on %s", self.name, port)
            return True
        self._warn("can't open %s (in use? close the Arduino IDE's Serial Monitor).", ", ".join(ports))
        return False

    def _reject(self, why: str) -> None:
        log.info("%s: %s is %s; looking for another.", self.name, self.port, why)
        self._rejected.add(self.port)
        self.close(stop_line=None)
        self._next_try = 0.0

    def _write(self, data: bytes) -> bool:
        import serial

        try:
            self.serial.write(data)
            if self.serial.in_waiting:
                self._read()
            return True
        except serial.SerialTimeoutException:
            return True  # buffer full this once; the next update replaces it anyway
        except (serial.SerialException, OSError) as exc:
            log.warning("%s: lost the Arduino on %s (%s)", self.name, self.port, exc)
            self.close(stop_line=None)
            return False

    def _read(self) -> None:
        self._buffer = (self._buffer + self.serial.read(256))[-256:]
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            text = line.decode("ascii", "replace").strip()
            if text.startswith("POCKETWHEEL") and self.board != text:
                self.board = text
                if self.matches:
                    log.info("%s: %s ready on %s", self.name, text, self.port)

    @property
    def matches(self) -> bool:
        return self.board is not None and self.board.startswith(f"POCKETWHEEL {self.kind}")

    def send_line(self, line: str, now: float) -> bool:
        if self.serial is None or now < self.ready_at:
            return False
        if self.board is not None and not self.matches:
            self._reject(f"running another sketch ({self.board})")
            return False
        if self.board is None:
            if self.port_setting == "auto" and now - self.ready_at > HELLO_S:
                self._reject("not answering as a PocketWheel board")
                return False
            if now - self._asked > 0.5:  # until the sketch introduces itself
                self._asked = now
                if not self._write(b"?\n"):
                    return False
        return self._write(f"{line}\n".encode())

    def close(self, stop_line: str | None = None) -> None:
        if self.serial is None:
            return
        try:
            if stop_line:
                self.serial.write(f"{stop_line}\n".encode())
                self.serial.flush()
            self.serial.close()
        except Exception:
            pass
        self.serial = None
        self.port = None
