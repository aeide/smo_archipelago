"""Pure-function helpers for locating wizard-produced map files.

Lives in `client/` rather than `_setup/` because SMOClient (`client/main.py`)
imports these on every launch to decide where to find maps. Keeping it
here means SMOClient never has to import the `_setup` package — which is
important because `_setup.wizard` pulls in Kivy.
"""

from __future__ import annotations

import os
from pathlib import Path


MAPS_SENTINEL_FILENAME = ".maps-updated"


def _user_data_dir() -> Path:
    """Per-user data dir for wizard-generated maps.

    Mirrors `_setup.__init__.data_dir()` but without importing `_setup` —
    `_setup.wizard` would pull in Kivy and we don't want SMOClient startup
    blocked on Kivy availability for environments that should never see
    the wizard (e.g. headless AP generation host).
    """
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "SMOArchipelago" / "data"
    return Path.home() / ".local" / "share" / "SMOArchipelago" / "data"


def _resolve_map_path(explicit: str, filename: str) -> Path | None:
    """Locate a shine_map.json / capture_map.json file on the filesystem.

    Search order (first hit wins):
      1. `explicit` host.yaml / CLI override path
      2. `%APPDATA%/SMOArchipelago/data/<filename>` (where the setup
         wizard writes its extractor output)
      3. legacy bundled-with-source `client/data/<filename>` (dev-only;
         release zips do NOT contain these — they'd be Nintendo IP)

    Returning None means the caller falls through to the `from_package`
    lookup in `client/main.py` (importlib.resources inside the zip).
    On a release zip that also misses (we never ship extracted maps), at
    which point the maps are simply empty and SMOClient logs warnings
    when moons don't resolve — that's the "user hasn't run setup yet"
    signal.
    """
    if explicit:
        return Path(explicit)
    user_data = _user_data_dir() / filename
    if user_data.exists():
        return user_data
    here = Path(__file__).resolve().parent / "data" / filename
    return here if here.exists() else None


def _sentinel_path() -> Path:
    """Path the wizard touches after a successful extract, and that the
    running SMOClient stats on AP-Connect to decide whether to reload
    its in-memory shine_map / capture_map.

    Co-located with the extracted maps (`%APPDATA%/SMOArchipelago/`)
    rather than the `data/` subdir so a stale extraction run can't leave
    the sentinel orphaned in a directory the wizard would later wipe.
    """
    return _user_data_dir().parent / MAPS_SENTINEL_FILENAME


def touch_maps_sentinel() -> None:
    """Stamp `<%APPDATA%>/SMOArchipelago/.maps-updated` with `mtime=now`.

    Called by `_setup/wizard_cli.py` after every successful extraction
    (whether the subprocess actually ran or the hash-match short-circuit
    fired) so a long-running SMOClient picks up the just-extracted maps
    on its next AP-Connect without needing a restart.
    """
    p = _sentinel_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()


def maps_sentinel_mtime() -> float | None:
    """Sentinel mtime in seconds, or None when the file does not exist.

    Returning None lets SMOClient distinguish "wizard never ran on this
    machine" (skip reload) from "wizard ran but mtime hasn't advanced
    since our last load" (also skip reload).
    """
    p = _sentinel_path()
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return None
