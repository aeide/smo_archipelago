"""P3e — slot_data + client wire round trip for the decoupled port matching.

Complements test_port_graph.py (pure compile_port_remaps unit tests, no AP)
and test_switch_server.py's mode-selection tests (push_entrance_map picks the
right compiler, monkeypatched compilers — no cross-package import). This file
covers what those two can't: the REAL before_fill_slot_data -> slot_data ->
SwitchServer.push_entrance_map -> real compile_port_remaps round trip, which
needs the installed apworld zip so `client` is genuinely nested under
`worlds.meatballs.client` (the relative imports inside push_entrance_map's
compilers only resolve in that shape — see test_switch_server.py's comment
block for why the loose test harness can't exercise them directly).

Gated on SMOAP_LIVE_AP=1 and run via subprocess, same pattern as
test_entrance_shuffle_option_modes.py. Run `python scripts/install_apworld.py`
first if hooks/World.py, port_graph.py, or the client/ modules changed since
the last install.

    SMOAP_LIVE_AP=1 .venv/Scripts/python -m pytest -v \
        apworld/smo_archipelago/tests/test_p3e_port_matching_wire.py
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
    reason="set SMOAP_LIVE_AP=1 to run the P3e port-matching wire tests "
           "(requires vendor/Archipelago checkout + AP pip deps installed)",
)

_PRELUDE = r"""
import sys, os
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)
from worlds.AutoWorld import AutoWorldRegister
from test.general import setup_multiworld

import worlds.meatballs.hooks.World as WorldHooks
WorldHooks.PORT_SHUFFLE_SHIPPABLE = True  # test-only readiness flip (P3d/P3e)

wt = next((w for w in AutoWorldRegister.world_types.values()
           if w.game == "Spicy Meatball Overdrive"), None)
assert wt, "Spicy Meatball Overdrive not registered (install meatballs.apworld?)"

def build(mode, seed=1):
    mw = setup_multiworld(wt, steps=("generate_early", "create_regions"),
                          options={"entrance_shuffle": mode}, seed=seed)
    return mw.worlds[1]
"""

# slot_data key exclusivity: decoupled ships port_matching and NOT
# entrance_map; simple ships entrance_map and NOT port_matching.
_PROBE_SLOT_DATA_KEYS = _PRELUDE + r"""
sd_simple = build("simple").fill_slot_data()
sd_decoupled = build("decoupled").fill_slot_data()

print(f"RESULT simple_has_entrance_map={'entrance_map' in sd_simple} "
      f"simple_has_port_matching={'port_matching' in sd_simple}")
print(f"RESULT decoupled_has_entrance_map={'entrance_map' in sd_decoupled} "
      f"decoupled_has_port_matching={'port_matching' in sd_decoupled} "
      f"port_matching_size={len(sd_decoupled.get('port_matching') or {})}")
"""

# Real client round trip: slot_data["port_matching"] -> SwitchServer mirror ->
# push_entrance_map -> the REAL compile_port_remaps (resolved against the
# client's own bundled entrance_stages.json/subareas.json, exactly as it
# would run for a real Switch connection).
_PROBE_CLIENT_ROUNDTRIP = _PRELUDE + r"""
import asyncio

world = build("decoupled", seed=1)
slot_data = world.fill_slot_data()
port_matching = slot_data["port_matching"]

from worlds.meatballs.client.state import BridgeState
from worlds.meatballs.client.switch_server import SwitchServer

state = BridgeState()
sent = []

async def fake_send(msg):
    sent.append(msg)

async def main():
    sw = SwitchServer("127.0.0.1", 0, state,
                      on_check=lambda _m: None, on_goal=lambda: None)
    sw._send = fake_send
    sw.set_port_matching(port_matching)
    await sw.push_entrance_map()

asyncio.run(main())

all_rows = []
for m in sent:
    all_rows.extend(m.entries)
kinds = {}
for r in all_rows:
    kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
entry_with_id = sum(1 for r in all_rows if r["kind"] == "entry" and r.get("from_id"))
exit_with_id = sum(1 for r in all_rows if r["kind"] == "exit" and r.get("from_id"))
first_chunk_reset = sent[0].reset if sent else None
print(f"RESULT rows={len(all_rows)} entry={kinds.get('entry', 0)} "
      f"exit={kinds.get('exit', 0)} entry_with_from_id={entry_with_id} "
      f"exit_with_from_id={exit_with_id} chunks={len(sent)} "
      f"first_chunk_reset={first_chunk_reset}")
"""

# Spoiler block: decoupled writes its own port-matching block; simple keeps
# writing the existing coupled block (regression — the branch in
# before_write_spoiler must not disturb the coupled path).
_PROBE_SPOILER = _PRELUDE + r"""
import io

w_simple = build("simple")
buf = io.StringIO()
w_simple.write_spoiler(buf)
simple_text = buf.getvalue()

w_decoupled = build("decoupled")
buf2 = io.StringIO()
w_decoupled.write_spoiler(buf2)
decoupled_text = buf2.getvalue()

print(f"RESULT simple_has_coupled_header={'Entrance Shuffle (' in simple_text} "
      f"simple_has_decoupled_header={'Entrance Shuffle - decoupled' in simple_text}")
print(f"RESULT decoupled_has_decoupled_header={'Entrance Shuffle - decoupled' in decoupled_text} "
      f"decoupled_has_coupled_header={'Entrance Shuffle (' in decoupled_text} "
      f"decoupled_has_moon_line={'moon inside' in decoupled_text}")
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
        out.append(d)
    return out


def test_slot_data_keys_are_mode_exclusive():
    r_simple, r_decoupled = _run_probe(_PROBE_SLOT_DATA_KEYS)
    assert r_simple["simple_has_entrance_map"] == "True"
    assert r_simple["simple_has_port_matching"] == "False"
    assert r_decoupled["decoupled_has_entrance_map"] == "False"
    assert r_decoupled["decoupled_has_port_matching"] == "True"
    assert int(r_decoupled["port_matching_size"]) > 0


def test_client_compiles_real_rows_from_port_matching():
    r = _run_probe(_PROBE_CLIENT_ROUNDTRIP)[0]
    assert int(r["rows"]) > 0
    assert int(r["entry"]) > 0
    assert int(r["exit"]) > 0
    # The P3e capability P2 built the substrate for: entry rows now carry a
    # real from_id (not just the pre-P3e empty wildcard).
    assert int(r["entry_with_from_id"]) > 0
    assert int(r["exit_with_from_id"]) > 0
    assert int(r["chunks"]) >= 1
    assert r["first_chunk_reset"] == "True"


def test_decoupled_spoiler_block_present_and_coupled_block_absent():
    r_simple, r_decoupled = _run_probe(_PROBE_SPOILER)
    assert r_simple["simple_has_coupled_header"] == "True"
    assert r_simple["simple_has_decoupled_header"] == "False"
    assert r_decoupled["decoupled_has_decoupled_header"] == "True"
    assert r_decoupled["decoupled_has_coupled_header"] == "False"
    assert r_decoupled["decoupled_has_moon_line"] == "True"
