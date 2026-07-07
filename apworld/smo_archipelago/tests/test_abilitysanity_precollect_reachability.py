"""Real-logic regression guard for the abilitysanity precollect fix.

Why this exists: `abilitysanity: false` used to drop every Ability item from
the pool with nothing compensating logic-side. The compiled moon/door/victory
`requires` strings still demand ability tokens (`|Progressive Ground
Pound:1|`, `|Wall Slide|`, `|Cap Bounce|`, ...), so with zero such items ever
existing, every location gated behind one -- including progression anchors --
became permanently unreachable and fill collapsed with FillError (diagnosed
2026-07-07, Generate seed 81285200019472365252). See
docs/handoff-abilitysanity-precollect-fix.md.

test_abilitysanity.py checks the fix is source-present (pool drop + precollect
both wired into before_create_items_filler); this file builds a real
multiworld with abilitysanity off and asserts the resulting CollectionState
-- which auto-collects precollected items in its constructor -- actually
satisfies the deepest progressive ability tokens, and that the pool itself
still contains zero Ability-category items (the fix must not put them back in
the pool, only precollect them).

Gated on SMOAP_LIVE_AP=1 like the other tests that need vendor/Archipelago +
its deps (the suite's conftest deliberately keeps Archipelago off sys.path).
Run via a subprocess so importing AutoWorldRegister doesn't pollute the parent
process / collide the loose source with the installed zip.

    SMOAP_LIVE_AP=1 .venv/Scripts/python -m pytest -v \
        apworld/smo_archipelago/tests/test_abilitysanity_precollect_reachability.py

NOTE: exercises the INSTALLED meatballs.apworld zip (AutoWorldRegister loads
the zip, not the loose source). Run scripts/install_apworld.py first if
you've edited hooks/World.py -- otherwise this validates the previously
installed behavior.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
AP_ROOT = REPO / "vendor" / "Archipelago"

pytestmark = pytest.mark.skipif(
    os.environ.get("SMOAP_LIVE_AP") != "1",
    reason="set SMOAP_LIVE_AP=1 to run the abilitysanity precollect regression "
           "(requires vendor/Archipelago checkout + AP pip deps installed)",
)

# Standalone probe: prints a single RESULT line the test parses. Kept inline so
# there's no extra committed script to drift out of sync.
_PROBE = r"""
import sys, os
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)
from BaseClasses import CollectionState
from worlds.AutoWorld import AutoWorldRegister
from test.general import setup_multiworld

wt = next((w for w in AutoWorldRegister.world_types.values()
           if w.game == "Spicy Meatball Overdrive"), None)
assert wt, "Spicy Meatball Overdrive not registered (install meatballs.apworld?)"

# no_logic defaults off (real logic); abilitysanity explicitly off, the
# combo that reproduced the FillError.
mw = setup_multiworld(
    wt, steps=("generate_early", "create_regions", "create_items"),
    options={"abilitysanity": False}, seed=1,
)
p = 1
world = mw.worlds[p]

pool_has_ability = any(
    "Ability" in world.item_name_to_item.get(it.name, {}).get("category", [])
    for it in mw.itempool
)

# CollectionState() auto-collects multiworld.precollected_items in its
# constructor -- no explicit .collect() calls needed if the fix precollected
# correctly.
state = CollectionState(mw)
deepest_tokens = {
    "Progressive Crouch": 3,
    "Progressive Ground Pound": 3,
    "Progressive Jump": 2,
}
satisfied = {name: state.has(name, p, count) for name, count in deepest_tokens.items()}

print(
    "RESULT "
    f"pool_has_ability={int(pool_has_ability)} "
    f"crouch={int(satisfied['Progressive Crouch'])} "
    f"ground_pound={int(satisfied['Progressive Ground Pound'])} "
    f"jump={int(satisfied['Progressive Jump'])}"
)
"""


def _run_probe() -> dict:
    res = subprocess.run(
        [sys.executable, "-c", _PROBE, str(AP_ROOT)],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    lines = [l for l in res.stdout.splitlines() if l.startswith("RESULT ")]
    if not lines:
        pytest.fail(f"probe produced no RESULT line\n--- stdout ---\n{res.stdout}\n"
                    f"--- stderr ---\n{res.stderr}")
    out: dict = {}
    for line in lines:
        out.update(kv.split("=") for kv in line.split()[1:])
    return out


def test_abilitysanity_off_precollects_deepest_progressive_tokens():
    r = _run_probe()
    assert int(r["pool_has_ability"]) == 0, (
        "abilitysanity=false must still drop every Ability item from the "
        "pool (precollect is in addition to the drop, not instead of it)"
    )
    assert int(r["crouch"]) == 1, "Progressive Crouch:3 not satisfied by precollect"
    assert int(r["ground_pound"]) == 1, "Progressive Ground Pound:3 not satisfied by precollect"
    assert int(r["jump"]) == 1, "Progressive Jump:2 not satisfied by precollect"
