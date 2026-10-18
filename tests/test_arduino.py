import serial

from server import arduino
from server.arduino import SerialLink


class FakePort:
    """A serial port with a PocketWheel sketch (or something else) on the other end."""

    def __init__(self, reply):
        self.reply = reply   # what the board answers to "?", or None
        self.lines = []
        self.out = b""
        self.closed = False

    @property
    def in_waiting(self):
        return len(self.out)

    def write(self, data):
        text = data.decode().strip()
        self.lines.append(text)
        if text == "?" and self.reply:
            self.out += (self.reply + "\n").encode()

    def read(self, n):
        data, self.out = self.out[:n], self.out[n:]
        return data

    def flush(self):
        pass

    def close(self):
        self.closed = True


def make_link(monkeypatch, boards, kind="FFB"):
    opened = {}

    def open_port(port, baud, timeout=None, write_timeout=None):
        if boards.get(port) == "busy":
            raise serial.SerialException("access denied")
        opened[port] = FakePort(boards[port])
        return opened[port]

    monkeypatch.setattr(serial, "Serial", open_port)
    link = SerialLink(kind, "Test", ports=lambda: list(boards))
    return link, opened


def run(link, start, seconds, line="F100"):
    t = start
    while t < start + seconds:
        if link.try_open(t):
            link.send_line(line, t)
        t += 0.05
    return t


def test_auto_skips_the_other_board_and_keeps_its_own(monkeypatch):
    boards = {"COM3": "POCKETWHEEL VIBRATION 1", "COM4": "POCKETWHEEL FFB 1"}
    link, opened = make_link(monkeypatch, boards)
    run(link, 0.0, 12.0)
    assert link.port == "COM4" and link.matches
    assert opened["COM3"].closed and "F100" in opened["COM4"].lines


def test_auto_skips_busy_ports_and_silent_devices(monkeypatch):
    boards = {"COM3": "busy", "COM5": None, "COM6": "POCKETWHEEL FFB 1"}
    link, opened = make_link(monkeypatch, boards)
    run(link, 0.0, 15.0)
    assert link.port == "COM6" and link.matches and opened["COM5"].closed


def test_lines_wait_for_the_bootloader_and_close_sends_the_stop_line(monkeypatch):
    link, opened = make_link(monkeypatch, {"COM4": "POCKETWHEEL FFB 1"})
    assert link.try_open(0.0)
    assert not link.send_line("F500", 1.0)       # still booting
    assert link.send_line("F500", arduino.BOOT_S)
    port = opened["COM4"]
    link.close(stop_line="F0")
    assert port.lines == ["?", "F500", "F0"] and port.closed and not link.is_open
