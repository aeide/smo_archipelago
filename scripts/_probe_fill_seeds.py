#!/usr/bin/env python3
"""Scratch: run Generate fill across a range of fixed seeds and report pass/fail.

Validates that the logic graph isn't over-constrained (design §5 "fill doesn't
deadlock"). IP-safe (no names printed). Usage:
    .venv/Scripts/python scripts/_probe_fill_seeds.py <n_seeds>
"""
from __future__ import annotations
import os, runpy, sys, io, contextlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AP_ROOT = REPO / "vendor" / "Archipelago"
SOLO = REPO / "apworld/smo_archipelago/tests/seeds/out/_solo"

os.chdir(AP_ROOT)
sys.path.insert(0, str(AP_ROOT))
import ModuleUpdate  # type: ignore
ModuleUpdate.update_ran = True

n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
fails = []
for seed in range(1000, 1000 + n):
    sys.argv = ["Generate.py", "--player_files_path", str(SOLO),
                "--outputpath", str(SOLO / "out"), "--skip_output",
                "--seed", str(seed)]
    buf = io.StringIO()
    ok = True
    err = ""
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            runpy.run_path(str(AP_ROOT / "Generate.py"), run_name="__main__")
    except SystemExit:
        pass
    except Exception as e:  # FillError etc.
        ok = False
        err = f"{type(e).__name__}: {str(e).splitlines()[0]}"
    out = buf.getvalue()
    if "FillError" in out or "Traceback" in out:
        ok = False
        for line in out.splitlines():
            if "FillError" in line or "No more spots" in line:
                err = line.strip()
                break
    print(f"seed {seed}: {'OK ' if ok else 'FAIL'} {err}")
    if not ok:
        fails.append(seed)

print(f"\n{n - len(fails)}/{n} passed; failures: {fails}")
