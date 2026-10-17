"""Keyboard presses for custom phone buttons, via Windows SendInput (no extra install).

Keys are sent as hardware scan codes, which games read (many ignore virtual-key-only
events). Only the keys in KEYS can be pressed: no Alt or Windows key, so a phone can't
trigger Alt+F4, the Start menu and the like.
"""

import ctypes
import logging
import sys

log = logging.getLogger(__name__)

KEYS: dict[str, int] = {  # name -> Windows virtual-key code
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): ord(str(d)) for d in range(10)},
    **{f"F{n}": 0x6F + n for n in range(1, 13)},
    "SPACE": 0x20, "ENTER": 0x0D, "TAB": 0x09, "ESCAPE": 0x1B, "BACKSPACE": 0x08,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "LSHIFT": 0xA0, "LCTRL": 0xA2,
    **{f"NUMPAD{d}": 0x60 + d for d in range(10)},
}
# Keys that live on the "extended" part of the keyboard need a flag, or games see numpad keys.
EXTENDED = {"UP", "DOWN", "LEFT", "RIGHT", "INSERT", "DELETE", "HOME", "END", "PAGEUP", "PAGEDOWN"}


class Keyboard:
    """Holds down exactly the keys it's given; anything no longer given is released."""

    def __init__(self, send=None):
        self._send = send or _send_input
        self.held: set[str] = set()

    def apply(self, keys) -> None:
        keys = set(keys)
        for name in self.held - keys:
            self._send(name, False)
        for name in keys - self.held:
            self._send(name, True)
        self.held = keys

    def release_all(self) -> None:
        self.apply(())


class NoKeyboard(Keyboard):
    """Dry-run / non-Windows: remembers presses but types nothing."""

    def __init__(self):
        super().__init__(send=lambda name, down: None)


def create_keyboard(dry_run: bool) -> Keyboard:
    if dry_run:
        return NoKeyboard()
    if sys.platform != "win32":
        log.warning("Keyboard binds need Windows; custom buttons bound to keys will do nothing.")
        return NoKeyboard()
    return Keyboard()


# ---- Windows SendInput -------------------------------------------------------------

if sys.platform == "win32":
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):  # only here so the union has INPUT's real size
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]

    INPUT_KEYBOARD, KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 1, 0x1, 0x2, 0x8


def _send_input(name: str, down: bool) -> None:
    scan = _user32.MapVirtualKeyW(KEYS[name], 0)  # MAPVK_VK_TO_VSC
    flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
    if name in EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    event = INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags)))
    if _user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
        log.warning("Key %s could not be sent (error %d)", name, ctypes.get_last_error())
