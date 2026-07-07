"""P2 §3.5 — entrance_shuffle Choice conversion (off/simple/decoupled).

Validates the option class itself (text parsing, the true/false YAML
back-compat aliases) and that selecting `decoupled` fails generation loudly
rather than silently behaving like `simple`.

Needs the real AP `Options` machinery + the installed apworld zip (imports
`worlds.meatballs`, exactly like test_cascade_reachability.py), so — same as
that file — this is gated on SMOAP_LIVE_AP=1 and runs via a subprocess to
keep vendor/Archipelago off this process's sys.path (see conftest.py). Run
`python scripts/install_apworld.py` first if hooks/Options.py or
hooks/World.py changed since the last install.

    SMOAP_LIVE_AP=1 .venv/Scripts/python -m pytest -v \
        apworld/smo_archipelago/tests/test_entrance_shuffle_option_modes.py
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
    reason="set SMOAP_LIVE_AP=1 to run the entrance_shuffle option-mode tests "
           "(requires vendor/Archipelago checkout + AP pip deps installed)",
)

# Option-class probe: no multiworld needed, just the registered Choice class's
# text/alias parsing. Doesn't trigger worlds/__init__.py's discovery walk
# beyond the one AutoWorldRegister lookup every gated test here already pays.
_PROBE_PARSE = r"""
import sys, os
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)
from worlds.AutoWorld import AutoWorldRegister

wt = next((w for w in AutoWorldRegister.world_types.values()
           if w.game == "Spicy Meatball Overdrive"), None)
assert wt, "Spicy Meatball Overdrive not registered (install meatballs.apworld?)"

EntranceShuffle = wt.options_dataclass.type_hints["entrance_shuffle"]

print(f"RESULT off_text={EntranceShuffle.from_text('off').value}")
print(f"RESULT simple_text={EntranceShuffle.from_text('simple').value}")
print(f"RESULT decoupled_text={EntranceShuffle.from_text('decoupled').value}")
print(f"RESULT true_alias={EntranceShuffle.from_any(True).value}")
print(f"RESULT false_alias={EntranceShuffle.from_any(False).value}")
print(f"RESULT default={EntranceShuffle(EntranceShuffle.default).value}")
print(f"RESULT off_val={EntranceShuffle.option_off}")
print(f"RESULT simple_val={EntranceShuffle.option_simple}")
print(f"RESULT decoupled_val={EntranceShuffle.option_decoupled}")
"""

# Generation probe: entrance_shuffle=decoupled must fail loudly at
# create_regions (before_create_regions's raise), not silently degrade to the
# coupled `simple` bijection. Restricted to the first two gen_steps — the
# raise fires before any region/item work, so there's nothing to gain from
# running the full pipeline (and it's slower).
_PROBE_RAISE_DECOUPLED = r"""
import sys, os
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)
from worlds.AutoWorld import AutoWorldRegister
from test.general import setup_multiworld
from Options import OptionError

wt = next((w for w in AutoWorldRegister.world_types.values()
           if w.game == "Spicy Meatball Overdrive"), None)
assert wt, "Spicy Meatball Overdrive not registered (install meatballs.apworld?)"

try:
    setup_multiworld(
        wt, steps=("generate_early", "create_regions"),
        options={"entrance_shuffle": "decoupled"}, seed=1,
    )
    print("RESULT raised=0 is_option_error=0")
except OptionError:
    print("RESULT raised=1 is_option_error=1")
except Exception:
    print("RESULT raised=1 is_option_error=0")
"""

# Regression companion: `simple` must NOT raise and must still roll a
# bijection (guards against an overzealous fix that breaks the working mode
# while fixing decoupled).
_PROBE_SIMPLE_STILL_WORKS = r"""
import sys, os
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)
from worlds.AutoWorld import AutoWorldRegister
from test.general import setup_multiworld

wt = next((w for w in AutoWorldRegister.world_types.values()
           if w.game == "Spicy Meatball Overdrive"), None)
assert wt, "Spicy Meatball Overdrive not registered (install meatballs.apworld?)"

mw = setup_multiworld(
    wt, steps=("generate_early", "create_regions"),
    options={"entrance_shuffle": "simple"}, seed=1,
)
bijection = getattr(mw.worlds[1], "_entrance_map", None)
print(f"RESULT rolled={1 if bijection else 0} size={len(bijection or {})}")
"""


def _run_probe(probe: str, prefix: str = "RESULT") -> dict:
    res = subprocess.run(
        [sys.executable, "-c", probe, str(AP_ROOT)],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    lines = [l for l in res.stdout.splitlines() if l.startswith(prefix + " ")]
    if not lines:
        pytest.fail(f"probe produced no {prefix} line\n--- stdout ---\n{res.stdout}\n"
                    f"--- stderr ---\n{res.stderr}")
    out: dict = {}
    for line in lines:
        out.update(kv.split("=") for kv in line.split()[1:])
    return out


def test_entrance_shuffle_option_text_values():
    """off/simple/decoupled parse to their declared option_* ints."""
    r = _run_probe(_PROBE_PARSE)
    assert int(r["off_text"]) == int(r["off_val"]) == 0
    assert int(r["simple_text"]) == int(r["simple_val"]) == 1
    assert int(r["decoupled_text"]) == int(r["decoupled_val"]) == 2


def test_entrance_shuffle_boolean_yaml_aliases():
    """Old boolean YAMLs (`entrance_shuffle: true`/`false`) keep behaving
    exactly as before the Choice conversion: true -> simple, false -> off."""
    r = _run_probe(_PROBE_PARSE)
    assert int(r["true_alias"]) == int(r["simple_val"])
    assert int(r["false_alias"]) == int(r["off_val"])


def test_entrance_shuffle_default_is_off():
    r = _run_probe(_PROBE_PARSE)
    assert int(r["default"]) == int(r["off_val"])


def test_entrance_shuffle_decoupled_raises_at_generation():
    """decoupled (P3, not implemented yet) must fail generation loudly via
    Options.OptionError, not silently fall back to the coupled `simple`
    bijection."""
    r = _run_probe(_PROBE_RAISE_DECOUPLED)
    assert int(r["raised"]) == 1, "entrance_shuffle=decoupled did not raise at generation"
    assert int(r["is_option_error"]) == 1, (
        "entrance_shuffle=decoupled raised, but not an Options.OptionError — "
        "won't surface as a clean player-facing generation failure")


def test_entrance_shuffle_simple_still_rolls_a_bijection():
    """Regression guard for the Choice conversion: `simple` must still work
    exactly like the old `entrance_shuffle: true` did."""
    r = _run_probe(_PROBE_SIMPLE_STILL_WORKS)
    assert int(r["rolled"]) == 1, "entrance_shuffle=simple did not roll a bijection"
    assert int(r["size"]) > 0
