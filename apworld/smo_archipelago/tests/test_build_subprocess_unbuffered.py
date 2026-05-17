"""Tests for `_setup.build.run_extract_maps` subprocess-unbuffer setup.

Regression coverage for the v0.1.6-alpha wizard bug where the "Extract
moon + capture maps" step's log box stayed blank for 60+ seconds. Root
cause was the extractor child process buffering its stdout because (a)
Python defaults to block-buffering when stdout isn't a TTY, and (b) the
bootstrap calls `pip install --quiet oead` which suppresses pip's
progress lines. The wizard captures stdout via Popen — so anything
buffered inside the child is invisible until the child either fills the
buffer (~8 KB), exits, or explicitly flushes.

The fix is to pass `-u` AND set PYTHONUNBUFFERED=1; this test pins both
in place so a future refactor can't accidentally drop them.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from _setup import build


def test_run_extract_maps_passes_dash_u_to_python(tmp_path) -> None:
    """The extractor must be launched with `-u` so stdout/stderr are
    line-buffered. Without this the wizard log box looks frozen for the
    silent 30-90s of venv creation + oead install.

    `-u` must appear AFTER the python-invoker prefix (which can be either
    `[sys.executable]` or `["py", "-3.12"]`) and BEFORE the script path
    so it applies to the script's Python interpreter, not to the script
    itself as an argv arg."""
    captured: dict = {}

    def fake_stream(cmd, *, cwd=None, env=None, on_line=None):
        captured["cmd"] = cmd
        captured["env"] = env
        return build.BuildResult(ok=True, returncode=0, log="")

    with patch.object(build, "_stream_subprocess", fake_stream), \
         patch.object(build, "bundled_script",
                      lambda name: tmp_path / name):
        # Touch the bundled-script path so the FileNotFoundError check
        # in bundled_script doesn't fire (we've patched it anyway).
        (tmp_path / "extract_shine_map.py").write_text("")
        build.run_extract_maps(tmp_path / "fake.nsp")

    cmd = captured["cmd"]
    # Find the script path; -u must be immediately before it.
    script_idx = next(i for i, a in enumerate(cmd) if a.endswith(".py"))
    assert cmd[script_idx - 1] == "-u", (
        f"'-u' should be the last arg before the script path; got "
        f"{cmd[max(0, script_idx-2):script_idx+1]}"
    )


def test_run_extract_maps_sets_pythonunbuffered_env(tmp_path) -> None:
    """`os.execv` strips command-line flags but inherits env vars, so the
    bootstrap's post-execv child Python (the one running under the new
    venv) must rely on PYTHONUNBUFFERED=1 to stay unbuffered. Without
    this the second half of the extractor's output is invisible even
    though we passed -u to the first invocation."""
    captured: dict = {}

    def fake_stream(cmd, *, cwd=None, env=None, on_line=None):
        captured["env"] = env or {}
        return build.BuildResult(ok=True, returncode=0, log="")

    with patch.object(build, "_stream_subprocess", fake_stream), \
         patch.object(build, "bundled_script",
                      lambda name: tmp_path / name):
        (tmp_path / "extract_shine_map.py").write_text("")
        build.run_extract_maps(tmp_path / "fake.nsp")

    env = captured["env"]
    assert env.get("PYTHONUNBUFFERED") == "1", (
        f"PYTHONUNBUFFERED=1 must be set so the post-execv re-launched "
        f"Python stays unbuffered; got env keys: {sorted(env.keys())}"
    )


def test_run_extract_maps_preserves_existing_env(monkeypatch, tmp_path) -> None:
    """Setting PYTHONUNBUFFERED must NOT wipe the rest of os.environ —
    the child process needs PATH, DEVKITPRO (set by the prereq detector
    for the build step), TEMP, etc. Test that we merge into os.environ
    rather than overwriting it."""
    monkeypatch.setenv("DEVKITPRO", "C:/devkitPro")
    monkeypatch.setenv("MY_TEST_MARKER", "carry-me-through")
    captured: dict = {}

    def fake_stream(cmd, *, cwd=None, env=None, on_line=None):
        captured["env"] = env or {}
        return build.BuildResult(ok=True, returncode=0, log="")

    with patch.object(build, "_stream_subprocess", fake_stream), \
         patch.object(build, "bundled_script",
                      lambda name: tmp_path / name):
        (tmp_path / "extract_shine_map.py").write_text("")
        build.run_extract_maps(tmp_path / "fake.nsp")

    env = captured["env"]
    assert env.get("MY_TEST_MARKER") == "carry-me-through", (
        "existing env vars must be preserved alongside PYTHONUNBUFFERED"
    )
    assert env.get("DEVKITPRO") == "C:/devkitPro"


# ---- _python_invoker ----------------------------------------------------

def test_python_invoker_uses_sys_executable_when_real_python(monkeypatch) -> None:
    """Dev / source checkout: sys.executable is a real Python interp;
    don't fall through to the `py` launcher, just use it directly so the
    script runs under the developer's venv."""
    monkeypatch.setattr(build.sys, "executable", r"C:\Users\me\.venv\Scripts\python.exe")
    assert build._python_invoker() == [r"C:\Users\me\.venv\Scripts\python.exe"]


def test_python_invoker_uses_py_launcher_when_sys_executable_is_frozen_launcher(
    monkeypatch,
) -> None:
    """Frozen AP Launcher: sys.executable is ArchipelagoLauncher.exe, which
    is not a Python interpreter. Must fall back to `py -3.12` (already
    verified by the prereq check). Regression test for v0.1.8-alpha
    diagnostic-build crash: `[ArchipelagoLauncher.exe, '-u', script.py,
    ...]` runs the launcher with garbage argv and fails with
    'unrecognized arguments'."""
    monkeypatch.setattr(
        build.sys, "executable", r"C:\ProgramData\Archipelago\ArchipelagoLauncher.exe",
    )
    monkeypatch.setattr(build.shutil, "which",
                        lambda name: r"C:\Windows\py.exe" if name == "py" else None)
    assert build._python_invoker() == ["py", "-3.12"]


def test_python_invoker_falls_through_to_python312_when_no_py_launcher(
    monkeypatch,
) -> None:
    """POSIX or stripped-down Windows where `py` isn't installed: prefer
    `python3.12` (matches the extractor's bootstrap-venv version) over
    plain `python` so we don't end up running the extractor on 3.13+
    where `oead` has no wheel."""
    monkeypatch.setattr(
        build.sys, "executable", r"C:\ProgramData\Archipelago\ArchipelagoLauncher.exe",
    )
    monkeypatch.setattr(
        build.shutil, "which",
        lambda name: f"/usr/bin/{name}" if name in ("python3.12", "python3") else None,
    )
    assert build._python_invoker() == ["python3.12"]


def test_python_invoker_handles_pythonw(monkeypatch) -> None:
    """pythonw.exe (Windows no-console Python) is a real Python interp;
    must be recognized as such even though its name isn't 'python'."""
    monkeypatch.setattr(build.sys, "executable", r"C:\Python313\pythonw.exe")
    assert build._python_invoker() == [r"C:\Python313\pythonw.exe"]
