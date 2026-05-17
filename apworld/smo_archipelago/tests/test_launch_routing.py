"""Tests for `__init__.launch_smo_client` — making sure the file-association
entry path stays on the inline-when-no-Kivy `launch` helper rather than
falling back to `launch_subprocess` (which is broken under PyInstaller-frozen
Archipelago because the multiprocessing.Process child can't read its
bundled `kivy/data/style.kv` out of library.zip).

These tests intentionally import via `worlds.smo.*`, which requires
Archipelago itself to be on sys.path. We add it here rather than in the
package-wide conftest because the rest of the suite is deliberately
Archipelago-free (see conftest.py's docstring).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent.parent
_AP_ROOT = _REPO_ROOT / "vendor" / "Archipelago"

if not (_AP_ROOT / "Launcher.py").exists():
    pytest.skip("Archipelago submodule not initialized", allow_module_level=True)

_AP_ROOT_STR = str(_AP_ROOT)
if _AP_ROOT_STR not in sys.path:
    sys.path.insert(0, _AP_ROOT_STR)

import ModuleUpdate  # noqa: E402
ModuleUpdate.update_ran = True

import worlds  # noqa: F401,E402  (triggers custom_worlds discovery)
import worlds.smo as smo_mod  # noqa: E402


def test_launch_subprocess_not_imported() -> None:
    """`launch_subprocess` (multiprocessing.Process variant) must not be
    importable on `worlds.smo` — its presence on the namespace tempts
    future contributors to call it directly, reintroducing the frozen-Kivy
    crash. `launch_or_subprocess` (AP's `launch` helper) is the only
    sanctioned route."""
    assert not hasattr(smo_mod, "launch_subprocess"), (
        "launch_subprocess must not be imported into worlds.smo — use "
        "launch_or_subprocess (the `launch` helper) instead so file-association "
        "invocations stay inline."
    )
    assert hasattr(smo_mod, "launch_or_subprocess"), (
        "launch_or_subprocess must be imported; without it, the routing decoration "
        "for inline-vs-subprocess can't dispatch."
    )


@pytest.fixture
def spy() -> list:
    """Replace `launch_or_subprocess` with a recorder. The bare
    `launch_subprocess` import was removed in the .apmanual cleanup
    (v0.1.x) — `test_launch_subprocess_not_imported` is the regression
    test that keeps it out."""
    via_launch: list[tuple] = []

    def fake_launch(func, name=None, args=()):
        via_launch.append((name, func.__name__, args))

    with patch.object(smo_mod, "launch_or_subprocess", fake_launch):
        yield via_launch


@pytest.fixture
def isolated_setup_state(monkeypatch, tmp_path) -> Path:
    """Redirect %APPDATA% so each test gets a clean is_setup_complete()
    answer without touching the developer's real wizard state."""
    appdata = tmp_path / "AppData"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    yield appdata


def _make_setup_complete(appdata_root: Path) -> None:
    """Create the four sentinel files `is_setup_complete()` checks for."""
    data = appdata_root / "SMOArchipelago" / "data"
    build = appdata_root / "SMOArchipelago" / "build" / "cmake"
    data.mkdir(parents=True, exist_ok=True)
    build.mkdir(parents=True, exist_ok=True)
    for name in ("shine_map.json", "capture_map.json"):
        (data / name).touch()
    for name in ("subsdk9", "main.npdm"):
        (build / name).touch()


def _write_smoap(tmp_path: Path) -> Path:
    """Round-trip a SmoapFile to disk so the test exercises the real parser."""
    from _setup.smoap_file import SmoapFile  # type: ignore
    p = tmp_path / "AP_test_P1_Mario.smoap"
    SmoapFile(slot_name="Mario").write(p)
    return p


def test_pre_setup_click_routes_via_launch(
    spy, isolated_setup_state, tmp_path,
) -> None:
    """When the user double-clicks a .smoap and setup hasn't run yet, the
    wizard must dispatch through `launch_or_subprocess` (which inlines
    when Kivy isn't already running). The bare `launch_subprocess` route
    breaks Kivy bootstrap in the frozen Archipelago installer."""
    smoap = _write_smoap(tmp_path)

    smo_mod.launch_smo_client(str(smoap))

    assert len(spy) == 1
    name, func_name, args = spy[0]
    assert name == "SMOSetup"
    assert func_name == "_run_setup_wizard_with_smoap"
    assert args == (str(smoap),)


def test_post_setup_click_routes_via_launch(
    spy, isolated_setup_state, tmp_path,
) -> None:
    """Once setup is complete, the same double-click should still go
    through `launch_or_subprocess` — with the .smoap expanded to SMOClient
    CLI args."""
    _make_setup_complete(isolated_setup_state)
    smoap = _write_smoap(tmp_path)

    smo_mod.launch_smo_client(str(smoap))

    assert len(spy) == 1
    name, func_name, args = spy[0]
    assert name == "SMOClient"
    assert func_name == "launch"
    # SmoapFile(slot_name="Mario") → ["--name", "Mario"]
    assert args == ("--name", "Mario")


def test_wizard_done_launch_button_handoff_runs_after_kivy_shutdown(
    spy, isolated_setup_state, tmp_path,
) -> None:
    """The wizard's "Launch SMOClient" button must NOT spawn from inside
    its own Kivy app — instead, `run_setup_wizard` returns True and the
    parent does the launch after `App().run()` returns. This test sims
    that handoff: pretend the wizard ran and returned True, then confirm
    `_run_setup_wizard_with_smoap` recursively dispatches SMOClient via
    `launch_or_subprocess`."""
    _make_setup_complete(isolated_setup_state)
    smoap = _write_smoap(tmp_path)

    import worlds.smo._setup.wizard as wiz_mod
    with patch.object(wiz_mod, "run_setup_wizard", lambda _p: True):
        smo_mod._run_setup_wizard_with_smoap(str(smoap))

    # Expect exactly one inline-launch for SMOClient (the recursive
    # launch_smo_client invocation goes through the post-setup path).
    assert len(spy) == 1
    name, func_name, args = spy[0]
    assert name == "SMOClient"
    assert func_name == "launch"
    assert args == ("--name", "Mario")
