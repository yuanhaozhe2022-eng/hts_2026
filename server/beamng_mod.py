"""Install the PocketWheel BeamNG mod (real gear names such as P, and the redline).

Copies beamng_mod/ into BeamNG's user folder as an unpacked mod:
  %LOCALAPPDATA%/BeamNG/BeamNG.drive/current/mods/unpacked/pocketwheel/
"""

import os
import shutil
from pathlib import Path

MOD_NAME = "pocketwheel"
OLD_MOD_NAME = "phonewheel"


def beamng_user_folder() -> Path | None:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    current = local / "BeamNG" / "BeamNG.drive" / "current"   # recent versions
    if current.is_dir():
        return current
    legacy = local / "BeamNG.drive"                             # older: one folder per version
    if legacy.is_dir():
        versions = sorted((p for p in legacy.iterdir() if p.is_dir() and p.name[:1].isdigit()),
                          key=lambda p: [int(x) for x in p.name.split(".") if x.isdigit()])
        if versions:
            return versions[-1]
    return None


def install_mod(project_root: Path) -> Path:
    """Copy the mod into BeamNG's mods folder and return where it went."""
    user = beamng_user_folder()
    if user is None:
        raise FileNotFoundError("BeamNG.drive user folder not found (has the game been started once?)")
    target = user / "mods" / "unpacked" / MOD_NAME
    # Remove the copy installed under the project's old name, so BeamNG doesn't run both.
    shutil.rmtree(user / "mods" / "unpacked" / OLD_MOD_NAME, ignore_errors=True)
    shutil.copytree(project_root / "beamng_mod", target, dirs_exist_ok=True)
    return target
