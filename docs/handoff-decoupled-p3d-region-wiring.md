# Handoff — P3d: region-graph wiring for decoupled entrances

## ✅ STATUS: COMPLETE (2026-07-07) — do not re-implement

All six work-order items below shipped; full results + design rationale are
recorded in [plan-decoupled-entrances.md](plan-decoupled-entrances.md) §3d
(kept in §3c's style, including the real-data findings). Executive trail:

1. **Roll** — `_prepare_decoupled_entrance_shuffle` (hooks/World.py), called
   from before_create_regions under decoupled; stashes `world._port_graph` /
   `_port_matching` / `_port_subareas` + the shared simple-mode attrs
   (`_entrance_subareas`, `_entrance_shuffled_locs`, `_interior_requires`,
   `_entrance_moonpipe`). Deliberately never sets `_entrance_map` (slot_data/
   spoiler stay silent until 3e's new key).
2. **Mouth → region** — side+stage resolution inside
   `_wire_decoupled_entrances`; interior-stage-collision RuntimeError;
   nested-door branch (unused by current data — probe-verified zero nested
   doors, zero collisions); kingdom field → region name verified 1:1 for all
   14 kingdoms (no Night Metro issue).
3. **Entrances per pair** — both directions, `make_mouth_access_rule`
   (port_graph.py): mouth cost + peace fn + OW-side scenario fragments; the
   interior exit gate rides its own direction only (double-application trap
   avoided); lone-overworld fixed points get their vanilla credit edge, all
   other fixed points get nothing.
4. **Kingdom chain entrances** — the "{K} Arrival" two-channel structure:
   `K -> K Arrival` left rule-less so the Manual set_rules clobber installs
   K's own fullRegionCheck (honest flight arrival); chain edges land in /
   source from Arrival; free `Arrival -> K` presence edge; flight edges
   untouched (test-asserted clobber-owned). This is the egress-quirk
   compensation generalized to two channels — read the
   `_wire_decoupled_entrances` docstring before touching it.
5. **Location rules** — after_set_rules decoupled branch reuses simple's two
   location helpers verbatim; NO door pass (port entrances source from
   non-regions.json regions, so wiring-time rules survive the clobber).
6. **Readiness flag** — `PORT_SHUFFLE_SHIPPABLE = False` (hooks/World.py)
   short-circuits the P2 OptionError; tests flip the module attr. Guarded by
   a source-scan test in test_entrance_shuffle.py. Flipping it for real is
   3e's LAST step.

**Tests:** `tests/test_decoupled_region_wiring.py` — 7 SMOAP_LIVE_AP-gated
subprocess probes (god-state reachability of every pooled interior,
per-direction Mini-Rocket gating, fixed-point/credit shapes across seeds
1/11/22 — seed list is tuned so BOTH lone shapes occur, re-tune after any
data regen — arrival/flight-clobber invariants, determinism, simple-mode
no-machinery guard). Suite: 984 passed / 91 skipped (= the 983/84 baseline
+1 non-live +7 live-gated); cascade-reachability + option-modes re-run green.
Bonus finding: `distribute_items_restrictive` fills decoupled seeds cleanly
(3/3 seeds, 0 unfilled) — 3f is not load-bearing for fill health.

**Next session → P3e** (slot_data + client plumbing, Sonnet-tier per the plan
doc): new slot_data key for the port matching, `switch_server.py` /
`push_entrance_map` generalization, spoiler block, verify the Switch ENTRY
lookup branch consults `from_id` (P2 seam), then flip PORT_SHUFFLE_SHIPPABLE.
Original work order kept below for reference.

---

**For a Claude Code session (Fable/Opus tier — this is the highest-interlock
logic work in the feature) on Devon's Windows machine.** CLAUDE.md's
stale-shell warnings are Cowork-specific; you run pytest/Generate yourself.
Canonical interpreter: the repo venv `e:\smo_archipelago\.venv` (Python
3.12.10). If `tmp_path` tests ERROR with PermissionError, the broken-ACL dirs
from the plan doc's Step-0 note may still exist — use `--basetemp=<fresh dir>`
or ask Devon to delete them elevated.

Context chain, in order:
1. [plan-decoupled-entrances.md](plan-decoupled-entrances.md) — P0–P3c done.
   Read §3c's three real-data discoveries carefully; all three shape 3d.
2. [design-decoupled-kingdom-order.md](design-decoupled-kingdom-order.md) —
   signed off; D1–D9 are fixed constraints.
3. `port_graph.py` + `port_matching.py` module docstrings — the model spec.
4. `hooks/World.py`: `_wire_entrance_shuffle`, `_apply_entrance_shuffle_door_rules`,
   `_apply_entrance_shuffle_location_rules`, `_apply_subarea_scenario_gates`
   (the simple-mode wiring you are generalizing — including its Step 3
   clobber note about the Manual core overwriting entrance rules).
5. [handoff-region-gating-egress.md](handoff-region-gating-egress.md) — the
   Manual-engine quirk: a region's `requires` gates its OUTGOING entrances.

## The task

Under `entrance_shuffle == decoupled`, replace the star region graph with the
port graph:

1. **Roll:** in the before-create-regions path (where simple rolls its
   bijection): `graph = build_port_graph(..., festival=(goal==festival))`,
   `matching = roll_port_matching(graph, world.random)`; stash both on
   `world`. The roller's RuntimeErrors are intentionally loud — let them
   fail generation.
2. **Mouth → region resolution.** Interior mouth → its subarea's region.
   Overworld mouth → the region owning its STAGE: kingdom region for
   HomeStages and placement zones (build a stage→kingdom map; the P3c
   discoveries mean you CANNOT suffix-match — derive zone→kingdom from the
   subarea records' `kingdom` field), parent subarea's region for nested
   doors, and remember `LakeWorldHomeStage` can appear as an INTERIOR stage
   (zone-split doors) — region resolution is by mouth SIDE + stage, never by
   stage name alone.
3. **Entrances per matched pair (A,B), both directions:**
   region(A) → region(B) gated by cost(A); region(B) → region(A) gated by
   cost(B) — `mouth_cost` + `evaluate_full_requires` for the item/peace
   parts, PLUS door-side scenario fragments (`make_door_scenario_gate_rule`
   over the subarea's member fragments) for OVERWORLD mouths, exactly as
   `_apply_entrance_shuffle_door_rules` composes them today. Fixed points:
   no entrance (vanilla passthrough) EXCEPT the lone-overworld credit shape,
   which needs its vanilla directed entrance region(ow)→region(subarea)
   preserved. Beware double-application: under decoupled the interior exit
   gate rides the INTERIOR mouth's own cost — do NOT also AND it onto the
   partner door the way simple's `make_door_access_rule` does.
4. **Kingdom regions gain chain entrances** (D1): a kingdom overworld region
   becomes enterable from subarea regions via matched edges. Flight
   entrances (`{KingdomMoons}` from regions.json) unchanged. No discount
   either way.
5. **Location rules:** reuse simple's pattern — strip baked gates on pooled
   subarea moons to interior-only requires, re-apply D3 scenario gates.
   The shuffled-locs set now derives from the port pool's subareas.
6. **Keep `decoupled` generation-BLOCKED for players:** the P2 OptionError
   stays until 3e ships the wire path (a decoupled seed today would be
   logically shuffled but physically vanilla on the Switch). Introduce an
   internal readiness flag (e.g. `PORT_SHUFFLE_SHIPPABLE = False` checked by
   the raise) so your tests can exercise the full wiring by flipping it,
   without opening the option to YAMLs.

## Tests

Mirror `test_cascade_reachability.py`'s style (real generation probes,
SMOAP_LIVE_AP-gated where heavy): decoupled seed generates with the readiness
flag flipped; every pooled subarea's region reachable in a god-state sweep;
per-direction gating (an interior mouth with a Mini-Rocket exit cost is NOT
traversable without the rocket, IS with it); lone-overworld credit preserved;
kingdom chain-entrances exist and flight gates unchanged; determinism (same
seed ⇒ same entrances); simple + off modes byte-identical to today (zero
regression — the full suite's 983/84 must hold).

## Scope guard

3d only: no slot_data/client/Switch work (3e), no Mushroom junk exemption
(3f). Update the plan doc §3d with results + any new real-data discoveries in
the same style as §3c. IP: none involved; audit `git status` before commit.
