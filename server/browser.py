"""Open the webcam-tap page in its own Chrome / Edge window that keeps running behind the game.

Browsers pause pages that are hidden or covered (no animation frames, slowed timers, video
suspended) to save power. The webcam page has to keep watching while BeamNG is in front and
focused (the game only reads the controller then), so it gets a separate app window with
those savings switched off. A separate profile folder makes the switches apply even when the
browser is already open, and remembers the camera permission.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

KEEP_RUNNING = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-media-suspend",
    "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling",
]


def find_browser() -> str | None:
    """Chrome, then Edge (always present on Windows 10/11)."""
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    return shutil.which("chrome") or shutil.which("msedge")


def browser_command(browser: str, url: str, profile: Path) -> list[str]:
    return [browser, f"--app={url}", f"--user-data-dir={profile}", "--window-size=900,820",
            "--no-first-run", "--no-default-browser-check", *KEEP_RUNNING]


def open_cam_window(url: str, profile: Path) -> bool:
    browser = find_browser()
    if browser is None:
        return False
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(browser_command(browser, url, profile),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.info("Webcam taps: opened %s in %s. Press Start webcam there, then click into the game.",
             url, Path(browser).stem)
    return True
