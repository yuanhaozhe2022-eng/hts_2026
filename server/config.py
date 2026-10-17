"""Settings: defaults merged with an optional config.json next to main.py."""

import copy
import json
from pathlib import Path

DEFAULTS = {
    "host": "0.0.0.0",
    "port": 8443,
    # Plain HTTP: redirects LAN visitors to HTTPS, and serves the app on localhost
    # (Android over USB via adb reverse, where no certificate is needed). 0 = off.
    "http_port": 8080,
    # Pad goes neutral if the phone stops sending for this long.
    "watchdog_ms": 300,
    "telemetry_hz": 30,
    # Xbox button names from vgamepad's XUSB_BUTTON, without the XUSB_GAMEPAD_ prefix
    # (see state.XBOX_BUTTONS). Also changeable from the phone's Settings.
    "buttons": {
        "shift_down": "LEFT_SHOULDER",
        "shift_up": "RIGHT_SHOULDER",
    },
    # Extra phone buttons: [{"id", "label", "bind": "pad:Y" | "key:H"}]. Edited from the phone.
    "custom_buttons": [],
    "beamng": {"enabled": True, "host": "127.0.0.1", "port": 4444, "gear_port": 4445},
    "assetto": {"enabled": True},
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Path) -> dict:
    """Load config.json, writing the defaults there on first run."""
    if not path.exists():
        save_config(path, DEFAULTS)
        return copy.deepcopy(DEFAULTS)
    return _merge(DEFAULTS, json.loads(path.read_text(encoding="utf-8")))


def save_config(path: Path, config: dict) -> None:
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
