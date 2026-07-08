"""P3f — Mushroom Kingdom junk_only promotion under decoupled entrance shuffle
(design D9). Covers the `_apply_junk_only_rules` decoupled exemption added in
`hooks/World.py`: Mushroom Kingdom's junk_only locations become eligible for
progression/useful items when `entrance_shuffle == decoupled`; Dark Side and
Darker Side junk_only locations stay non-exempt in every mode (D5).

Gated on SMOAP_LIVE_AP=1 and run via subprocess, same pattern as
test_p3e_port_matching_wire.py / test_decoupled_region_wiring.py — the item
rule is only observable after a real AP Location object is built (requires
the vendor/Archipelago checkout), so there is no in-process "pure" tier for
the behavioral checks; the fast/always-run tier lives in
test_junk_only_fill.py's source-scan style plus the data-shape assertions
below (no AP import, run unconditionally).

    SMOAP_LIVE_AP=1 .venv/Scripts/python -m pytest -v \
        apworld/smo_archipelago/tests/test_p3f_mushroom_promotion.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
AP_ROOT = REPO / "vendor" / "Archipelago"
APWORLD_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APWORLD_ROOT / "data"

# A representative junk_only location per category, used by the live probes
# below. Picked arbitrarily from the sets asserted in
# test_mushroom_junk_only_locations_have_moon_requirements_record.
MUSHROOM_JUNK_LOC = "Mushroom: Perched on the Castle Roof"
DARK_SIDE_JUNK_LOC = "Dark Side: Captain Toad on the Dark Side!"


# ---------------------------------------------------------------------------
# Step 0 data-shape assertions (no AP import — run unconditionally)
# ---------------------------------------------------------------------------

def _locations() -> list[dict]:
    return json.loads((DATA_DIR / "locations.json").read_text(encoding="utf-8"))


def _moon_requirements() -> dict:
    return json.loads((DATA_DIR / "moon_requirements.json").read_text(encoding="utf-8"))


def test_mushroom_junk_only_locations_have_moon_requirements_record():
    """Step 0 finding: the handoff's 25-vs-36 'gap' was a key-prefix-filter
    artifact (moon_requirements.json keys are subarea-prefixed CSV names,
    e.g. "Peach's Castle: ..." / "Castle Courtyard 64: ...", not all
    "Mushroom Kingdom: ..."). Diffed by the `location_name` field instead,
    every junk_only Mushroom Kingdom location already has a record — so
    Devon's compile_moon_logic.py re-run can backfill `requires` for all of
    them with no further data-import work needed."""
    locs = _locations()
    reqs = _moon_requirements()
    mushroom_junk_names = {
        loc["name"] for loc in locs
        if loc.get("junk_only", False) and "Mushroom Kingdom" in loc.get("category", [])
    }
    assert len(mushroom_junk_names) == 36, (
        f"expected 36 junk_only Mushroom Kingdom locations, found "
        f"{len(mushroom_junk_names)} — re-verify Step 0's counts before "
        f"trusting the rest of this test file"
    )
    req_location_names = {
        v.get("location_name") for v in reqs.values() if v.get("location_name")
    }
    missing = mushroom_junk_names - req_location_names
    assert not missing, (
        f"{len(missing)} junk_only Mushroom locations have no "
        f"moon_requirements.json record (diffed by location_name): {missing} "
        f"— this is a real data gap, stop and report to Devon per the "
        f"handoff's Step 0 rather than proceeding"
    )


def test_dark_side_junk_only_locations_present():
    """Sanity: the D5 non-exemption has something to exempt-from. Dark Side/
    Darker Side junk_only locations must still exist for the probes below to
    be meaningful."""
    locs = _locations()
    dark_side_junk = [
        loc["name"] for loc in locs
        if loc.get("junk_only", False) and "Dark Side" in loc.get("category", [])
    ]
    assert MUSHROOM_JUNK_LOC in {
        loc["name"] for loc in locs
        if loc.get("junk_only", False) and "Mushroom Kingdom" in loc.get("category", [])
    }
    assert DARK_SIDE_JUNK_LOC in dark_side_junk


# ---------------------------------------------------------------------------
# Live behavioral probes (SMOAP_LIVE_AP-gated subprocess)
# ---------------------------------------------------------------------------

# Applied per-test (not as a module-level `pytestmark`) so the data-shape
# tests above keep running unconditionally — a module-level pytestmark
# would skip every test in the file, including those.
_live_ap_only = pytest.mark.skipif(
    os.environ.get("SMOAP_LIVE_AP") != "1",
    reason="set SMOAP_LIVE_AP=1 to run the P3f Mushroom-promotion wire tests "
           "(requires vendor/Archipelago checkout + AP pip deps installed)",
)

_PRELUDE = r"""
import sys, os
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)
from worlds.AutoWorld import AutoWorldRegister
from test.general import setup_multiworld
from BaseClasses import Item, ItemClassification

import worlds.meatballs.hooks.World as WorldHooks
WorldHooks.PORT_SHUFFLE_SHIPPABLE = True  # test-only readiness flip (P3d/P3e/P3f)

wt = next((w for w in AutoWorldRegister.world_types.values()
           if w.game == "Spicy Meatball Overdrive"), None)
assert wt, "Spicy Meatball Overdrive not registered (install meatballs.apworld?)"

MUSHROOM_JUNK_LOC = "Mushroom: Perched on the Castle Roof"
DARK_SIDE_JUNK_LOC = "Dark Side: Captain Toad on the Dark Side!"

def build(mode, steps=("generate_early", "create_regions", "create_items", "set_rules"), seed=1):
    mw = setup_multiworld(wt, steps=steps,
                          options={"entrance_shuffle": mode}, seed=seed)
    return mw
"""

# Item-rule probe: build through set_rules (item_rule callables are attached
# there via after_set_rules -> _apply_junk_only_rules) for all three modes,
# then evaluate each junk_only location's item_rule against a real
# progression-classified Item.
_PROBE_ITEM_RULE = _PRELUDE + r"""
adv_item = Item("ProgressionProbe", ItemClassification.progression, None, 1)

for mode in ("off", "simple", "decoupled"):
    mw = build(mode)
    mushroom_loc = mw.get_location(MUSHROOM_JUNK_LOC, 1)
    dark_side_loc = mw.get_location(DARK_SIDE_JUNK_LOC, 1)
    print(f"RESULT mode={mode} "
          f"mushroom_accepts_advancement={mushroom_loc.item_rule(adv_item)} "
          f"dark_side_accepts_advancement={dark_side_loc.item_rule(adv_item)}")
"""

# Full-generation probe: the real Generate.py -> Main.py pipeline (same two
# calls Generate.py's own __main__ block makes), patched between them so the
# decoupled OptionError guard is bypassed for this in-process run only. This
# is the actual Fill pass (not just create_regions/set_rules), so a FillError
# from the promoted Mushroom checks competing for progression placement would
# surface here.
_PROBE_FULL_GENERATION = r"""
import sys, os, tempfile
from pathlib import Path
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)

import ModuleUpdate
ModuleUpdate.update_ran = True

import Generate

with tempfile.TemporaryDirectory() as td:
    td_path = Path(td)
    (td_path / "Mario.yaml").write_text(
        "name: Mario\n"
        "game: Spicy Meatball Overdrive\n"
        "description: p3f gen test\n"
        "\n"
        "Spicy Meatball Overdrive:\n"
        "  entrance_shuffle: decoupled\n",
        encoding="utf-8",
    )
    out_dir = td_path / "out"
    out_dir.mkdir()
    argv = Generate.mystery_argparse([
        "--player_files_path", str(td_path),
        "--outputpath", str(out_dir),
        "--skip_output",
        "--seed", "20260708",
    ])
    erargs, seed = Generate.main(argv)

    import worlds.meatballs.hooks.World as WorldHooks
    WorldHooks.PORT_SHUFFLE_SHIPPABLE = True  # test-only readiness flip

    from Main import main as ERmain
    try:
        ERmain(erargs, seed)
        print("RESULT status=ok")
    except Exception:
        # Message/traceback can contain spaces and newlines, which would
        # corrupt the whitespace-split RESULT-line parsing below — print the
        # traceback separately (to stderr) instead of embedding it inline.
        import traceback
        traceback.print_exc()
        print("RESULT status=error")
"""


def _run_probe(probe: str, prefix: str = "RESULT") -> list[dict]:
    res = subprocess.run(
        [sys.executable, "-c", probe, str(AP_ROOT)],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    lines = [l for l in res.stdout.splitlines() if l.startswith(prefix + " ")]
    if not lines:
        pytest.fail(f"probe produced no {prefix} line\n--- stdout ---\n{res.stdout}\n"
                    f"--- stderr ---\n{res.stderr}")
    out = []
    for line in lines:
        d: dict = {}
        d.update(kv.split("=", 1) for kv in line.split()[1:])
        d["_stderr"] = res.stderr
        out.append(d)
    return out


@_live_ap_only
def test_mushroom_junk_only_exempt_only_under_decoupled():
    r_off, r_simple, r_decoupled = _run_probe(_PROBE_ITEM_RULE)
    assert r_off["mode"] == "off"
    assert r_off["mushroom_accepts_advancement"] == "False", (
        "off mode must keep Mushroom junk_only rejecting advancement items "
        "(regression: decoupled exemption leaked into off mode)"
    )
    assert r_simple["mode"] == "simple"
    assert r_simple["mushroom_accepts_advancement"] == "False", (
        "simple mode must keep Mushroom junk_only rejecting advancement "
        "items (regression: decoupled exemption leaked into simple mode)"
    )
    assert r_decoupled["mode"] == "decoupled"
    assert r_decoupled["mushroom_accepts_advancement"] == "True", (
        "decoupled mode must exempt Mushroom junk_only locations (D9) so "
        "progression items can be placed there"
    )


@_live_ap_only
def test_dark_side_junk_only_never_exempt():
    r_off, r_simple, r_decoupled = _run_probe(_PROBE_ITEM_RULE)
    for r in (r_off, r_simple, r_decoupled):
        assert r["dark_side_accepts_advancement"] == "False", (
            f"Dark Side junk_only must reject advancement items in every "
            f"mode (D5: excluded from the port pool, decoupled doesn't "
            f"change its reachability) — mode={r['mode']}"
        )


@_live_ap_only
def test_decoupled_generates_with_promoted_mushroom_checks_no_fill_error():
    r = _run_probe(_PROBE_FULL_GENERATION)[0]
    assert r["status"] == "ok", (
        f"decoupled generation with promoted Mushroom checks failed:\n"
        f"{r.get('_stderr', '')}"
    )
