"""Android over USB: `adb reverse` makes the phone's localhost:<port> reach this PC.

The phone then opens http://localhost:<port>. Chrome treats localhost as a secure
context, so the motion sensors work without any certificate, and the connection
doesn't depend on the Wi-Fi at all (campus networks often block phone <-> PC traffic).

Needs Android platform-tools (adb) and USB debugging enabled on the phone.
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

PLATFORM_TOOLS_URL = "https://developer.android.com/tools/releases/platform-tools"


def find_adb(root: Path) -> str | None:
    candidates = [
        shutil.which("adb"),
        root / "platform-tools" / "adb.exe",           # unzipped next to main.py
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        Path("C:/platform-tools/adb.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None


async def _adb(adb: str, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        adb, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace").strip()


async def keep_reverse(adb: str, port: int, every_s: float = 3.0) -> None:
    """Keep `adb reverse` in place, re-applying it when the phone is (re)plugged."""
    last = None
    while True:
        code, devices = await _adb(adb, "devices")
        lines = [l for l in devices.splitlines()[1:] if l.strip()]
        if not lines:
            state = "Waiting for an Android phone on USB (USB debugging on)..."
        elif any(l.endswith("unauthorized") for l in lines):
            state = "Phone found: tap 'Allow USB debugging' on the phone."
        else:
            code, out = await _adb(adb, "reverse", f"tcp:{port}", f"tcp:{port}")
            state = (f"USB ready: open http://localhost:{port} in Chrome on the phone." if code == 0
                     else f"adb reverse failed: {out}")
        if state != last:
            log.info(state)
            last = state
        await asyncio.sleep(every_s)
