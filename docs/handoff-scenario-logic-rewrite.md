# Handoff — scenario-reachability rewrite (bit-driven, game-wide)

Start-here prompt for the implementation session that follows the 2026-06-20 Cascade
deadlock diagnosis. **Read [scenario-logic-revisit-june-20.md](scenario-logic-revisit-june-20.md)
first, end to end** — it is the full diagnosis and the decisions (§9) you are implementing.
This file is the task list + gotchas, not the rationale.

## TL;DR of what you're doing

The current `scripts/compile_moon_logic.py` gates moon reachability on a mix of the
game's `min_scenario` bit AND two unreliable proxies (`shine_map.is_moon_rock`, the
`locations.json "Moon Rock"` category). Those two proxies are a **disjoint set** from
each other and from the bit, which strands or free-passes moons across the whole game
(133 miscategorized, 39 shipped fully logic-free — including Cascade's Progressive Ground
Pound, which created an unwinnable starting kingdom). **Rewrite all scenario reachability
to key purely off `min_scenario`, game-wide, and attach subarea moons' gates to the
subarea, not the moon.**

## The three decisions (from §9 of the diagnosis — authoritative)

1. **D1 — fix everywhere.** General defect, applies to every kingdom. Not a Cascade
   special-case. Expect fill to tighten game-wide → mandatory seed sweep.
2. **D2 — retire `is_moon_rock` + `"Moon Rock"` category as reachability inputs.** Gate
   purely on `min_scenario` (game-provided, validated 1:1 in-game). Keep the category only
   for `MOON_ROCK_REACH_CAPTURE` capture gates / labeling; retire it outright if nothing
   else needs it (audit `moon_rock_names` consumers first).
3. **D3 — gate subarea moons at the SUBAREA, not the moon** (entrance-randomizer-safe).
   The scenario predicate for a moon inside a subarea must ride the subarea
   entrance/region, NOT the moon's own `requires`. See the "D3 is the hard part" section.

## Task list

### 1. New uniform bit classifier in `compile_moon_logic.py`

Replace the `is_moon_rock`/category branching with one function: given a moon's
`progress_bit_flag` and its kingdom's scenario numbers (`after_ending_scenario`,
`clear_main_scenario`, `moon_rock_scenario`), return the gate.

- `m = min_scenario(progress_bit_flag)` (lowest set bit).
- `first_bit` = the kingdom's first playable bit; `peace_bit = clear_main_scenario - 1`;
  `ae_bit = after_ending_scenario - 1`.
- Classify:
  - `m == first_bit` → first-visit, no scenario gate.
  - `first_bit < m < peace_bit` (and kingdom HAS a peace cutscene) → `mid_story` anchor
    (`{canReachLocation(<grand advancer>)}`) as today.
  - `m >= peace_bit` → `{<Kingdom>Peace()}` (boss kingdoms) — this is where the 39 freed
    rock moons land.
  - **Cascade special** (`clear` is the last scenario, no peace cutscene): `m < ae_bit` →
    `{CascadePeace()}` (vacuous-but-correct); `m >= ae_bit` → **`{CascadeDeparture()}`**.
  - **Cap/Cloud/Lost/Moon re-arrival** kingdoms: keep `build_rearrival_names` semantics
    but drive them from the same bit classifier instead of `is_moon_rock`.
- **Remove every `if e.get("is_moon_rock"): continue`** in `build_post_peace_names` /
  `build_cascade_anchors`. No code path reads `is_moon_rock` after this.

### 2. `hooks/Rules.py`

- Add `CascadeDeparture()` = `canReachRegion("Sand Kingdom")` (mirror of `CapPeace`/
  `CloudPeace`/`LostPeace`).
- Confirm `CascadePeace` stays (still used for the bit-1 layer; vacuous today but kept to
  document intent / survive a future starter change).

### 3. D3 — subarea gating (the hard part)

`compile_moon_logic.py` today writes **per-location `requires` only** — it ANDs the
subarea gate onto each moon string via `loc_subarea_gate[location_name]`
(`compile_moon_logic.py:672`). It NEVER writes a region/entrance `requires`. So "gate at
the subarea" needs a **new emission target**. Investigate and pick:

- **Option A — emit into `regions.json` subarea entrances.** Check how subareas are
  represented in `data/regions.json` (are subareas their own regions with an entrance from
  the parent kingdom, or are subarea moons just locations in the kingdom region?). If they
  are real sub-regions, put the scenario predicate on the connecting entrance's `requires`.
  This is the cleanest and is what the entrance randomizer actually rewires.
- **Option B — World.py hook at create-regions.** If subareas aren't first-class regions
  in regions.json, inject the per-subarea scenario gate via a `hooks/World.py` step that
  the entrance shuffle already runs through (`before_create_regions`). Make sure it runs in
  an order consistent with the bijection so the gate rides the shuffled connection.

Cross-check: `data/subareas.json` maps each subarea → `location_names`. The compiler must
group a subarea's moons, compute the subarea's effective scenario layer (min over its
moons, unless the subarea carries its own scenario), and emit ONE gate for the subarea.
Subarea moons' own `requires` then keep only moveset/capture terms. Overworld (non-subarea)
moons keep the gate on the moon as today.

**Edge case to handle explicitly:** a subarea whose moons span multiple scenario layers.
Gate the subarea entrance at the *earliest* layer that opens it; any genuinely later-layer
moon inside still needs its own bit gate ANDed on top. Flag these in the compiler's report
output so they're auditable.

**Verify against entrance shuffle BOTH ways:** OFF (vanilla door → gate applies as before)
and ON (shuffled door → gate enforced once, on the subarea, regardless of which door leads
there). This is the whole point of D3 — don't ship it without checking the ON path doesn't
double-gate or contradict the bijection.

### 4. Tests — `tests/test_scenario_gating.py`

Extend with bit-layer cases (no IP — pure helpers):
- first-visit bit → no gate; mid bit → mid_story anchor; `>= peace_bit` → Peace.
- Cascade: `m < ae_bit` → CascadePeace; `m >= ae_bit` → CascadeDeparture.
- The disjoint case: an `is_moon_rock=True` moon with NO `"Moon Rock"` category is now
  gated by its bit (regression guard for the exact §4b bug).
- D3: a subarea moon's per-moon `requires` does NOT contain the scenario predicate; the
  subarea entrance/region does.

### 5. Regen + verify (romfs machine only)

Per §8 of the diagnosis:
```powershell
python scripts\compile_moon_logic.py    # Cascade post-leave count jumps; "fully free" rock count → ~0
python scripts\sync_shine_table.py       # // Count unchanged (names already match)
python scripts\install_apworld.py
python vendor\Archipelago\Generate.py    # re-roll seed 16146892779757521032 + a representative sweep
```
Then in-game: 7 Cascade moons collectable **before leaving**; Progressive Ground Pound no
longer behind the leave-wall.

## Hard constraints / gotchas

- **⚠ NEVER run `compile_moon_logic.py` without `shine_map.json` + `world_scenarios.json`
  present.** It degrades to rock-only and WIPES the compiled scenario gates for all 775
  moons (CLAUDE.md). The romfs machine is mandatory for this whole task.
- **Seed sweep is not optional (D1).** Freeing 39 rock moons into `{Peace()}` gates and
  tightening Cascade both increase fill pressure. Watch for FillError across kingdoms, not
  just Cascade. Cascade pre-leave capacity is 19 locations vs max gate 10, so Cascade
  itself is safe; the risk is elsewhere.
- **Don't break the entrance randomizer (load-bearing).** Devon confirmed in-game that a
  shuffled cross-kingdom door makes `Luncheon: Treasure of the Lava Islands` (a Cascade
  Power Moon) reachable from Cascade — one of his two legit pre-leave moons. The fix must
  keep entrance-shuffle-reachable cross-kingdom moons as valid pre-leave sources. D3 exists
  precisely to keep this correct.
- **IP:** the gitignored `shine_map.json`/`world_scenarios.json` are read at BUILD TIME
  ONLY; the compiler emits functional fragments, never names. Never paste moon-name lists
  (>~5) into docs/commits/tests. The bit classifier is fed by flags, not names.
- **Stale-mount / installed-zip gotchas (CLAUDE.md):** do file work via Read/Write/Edit;
  run compile/Generate on Windows; `install_apworld.py` is required before Generate reflects
  apworld edits.

## Suggested tooling follow-up (not blocking)

The spoiler log does **not** print the entrance map (it lives in
`slot_data["entrance_map"]`). That's why the shuffled-door reachability path was invisible
during diagnosis. A small dump of the rolled entrance bijection into the spoiler/output
would make future logic debugging much easier. Optional, but cheap and high-value.

## D3 implementation plan (investigated 2026-06-20 — core D1/D2 already shipped)

**Status:** D1 + D2 are implemented, tested, swept (see
[scenario-logic-revisit-june-20.md §10](scenario-logic-revisit-june-20.md)). D3 below is
NOT yet implemented. The handoff's "Option A — emit into regions.json subarea entrances"
is **impossible as written**: investigation showed `data/regions.json` has only 20
kingdom/hub regions and **no subarea regions**. Subareas become real AP `Region`s ONLY
when `entrance_shuffle` is ON, built dynamically in `hooks/World.py::_wire_entrance_shuffle`
(creates `"<sub> Interior"` regions, moves member locations in, connects a door `Entrance`
with `make_door_access_rule`). With shuffle OFF, subarea moons just live in their kingdom
region with per-moon `requires`. `subareas.json` carries no scenario field. So D3 is
**Option B** with a compiler→World.py data thread:

### D3.1 — compiler emits a subarea→gate map (new committed file)

In `compile_moon_logic.py` add `build_subarea_scenario_gates(subareas, shine_map, world_scen)`:
- For each subarea, group its member moons; effective layer = `min(min_scenario)` over
  members. Map that layer → fragment via the SAME bit classifier already used
  (first-visit→none, mid→`canReachLocation(advancer)`, ≥peace→`{KingdomPeace()}`,
  Cascade→`CascadePeace`/`CascadeDeparture`, re-arrival kingdoms→`{*Peace()}`).
- Emit `data/subarea_scenario_gates.json` = `{subarea_name: fragment}` (IP-safe:
  functional fragments + already-committed subarea names only).
- **Multi-layer edge case:** if a member's own bit is strictly higher than the subarea's
  earliest layer, keep that member's higher bit gate on the MOON's `requires` (residual);
  flag these in the compile report.
- **Critically:** stop routing the subarea-member location names through the per-moon
  scenario passes. Today the scenario gate rides each subarea moon by location name via the
  post_peace/mid/cascade passes; D3 must route those names OUT of the per-moon gate and INTO
  the subarea map (overworld non-subarea moons keep the per-moon gate as today). Member
  moons' own `requires` then keep only moveset/capture (+ any residual higher-bit gate).

### D3.2 — World.py applies the map in both shuffle modes

Load `subarea_scenario_gates.json` once. The fragments are manual-AP `requires` strings;
convert each to a callable rule (reuse Manual's requires→rule path — find how
`set_rules`/`Helpers` turns a `requires` string into a Location/Entrance access rule, then
compose with a wrapper lambda):
- **Shuffle ON** (`_wire_entrance_shuffle`): AND the interior subarea's fragment into the
  door `Entrance`'s access rule (compose with `make_door_access_rule`). The scenario gate
  rides the interior region's entrance → enforced **once**, regardless of which door maps
  there. This is the whole point of D3.
- **Shuffle OFF**: subareas aren't regions, so apply each subarea's fragment to its member
  `Location` access rules (`add_rule` in `after_create_regions`), OR re-bake into member
  `requires` in the OFF branch only. Net behaviour identical to today.

### D3.3 — the load-bearing correctness question for Devon

The gate is computed from the **interior subarea's own member bits** (interior-intrinsic),
NOT the door kingdom's scenario. Confirm in-game: when a shuffled foreign door leads to a
subarea, that subarea's moons are present per the **interior kingdom's** quest/scenario
state (which is what makes interior-intrinsic correct). The entrance shuffle is
switch-mod-side and moon presence is driven by each moon's own kingdom quest state, so this
should hold — but verify before shipping, since it's the hinge of D3's correctness.

### D3.4 — tests + both-ways verification

- compiler: a subarea moon's per-moon `requires` does NOT contain the scenario predicate;
  `subarea_scenario_gates.json` carries it (the exact §4 D3 test).
- World.py: shuffle ON → interior entrance rule enforces the gate once; shuffle OFF →
  member location enforces it. (Likely lives in `test_entrance_shuffle.py`.)
- Generate sweep entrance-shuffle **ON and OFF**: gate enforced exactly once, no
  double-gate, no contradiction with the bijection, no FillError.

### D3 risk note

D3 only changes WHERE the scenario gate attaches for subarea moons; it does not change the
§3 bit layers (D1/D2 already shipped). It is therefore additive to the already-validated
reachability, but it touches the entrance-shuffle wiring (load-bearing — see CLAUDE.md P7 /
the entrance-shuffle-live-validated memory), so the ON/OFF sweep is mandatory.

## D3 — what actually shipped (2026-06-20)

Implemented as an **additive, OFF-path-preserving** variant of the plan above (chosen over
the "route names OUT of the per-moon gate" framing to keep the default/shuffle-OFF path
byte-identical to today — lowest risk to the load-bearing default behaviour). Net result is
the same: subarea moons are scenario-gated correctly under entrance-shuffle ON, which they
previously were NOT (the bug).

- **The actual bug D3 fixes:** under entrance-shuffle ON, `_apply_entrance_shuffle_location_rules`
  REPLACES each pooled-subarea moon's access rule with its move-set-only interior requires —
  silently dropping the scenario gate that `compile_moon_logic.py` baked into `locations.json`.
  (Kingdom + subarea-item gates survive because they ride the door entrance via
  `make_door_access_rule`; only the *scenario* gate was lost.) OFF mode was always correct.
- **Compiler** (`scripts/compile_moon_logic.py`): `scenario_fragments_for()` isolates the
  post_peace / mid_story / re-arrival fragment(s) (exactly what `gates_for` appends);
  `build_subarea_scenario_gates()` groups POOLED-subarea moons (subareas minus
  `entrance_exclusions.json`) → `data/subarea_scenario_gates.json` = `{location_name: fragment}`.
  `locations.json` is **unchanged** (hash-verified) — the baked gate still drives OFF mode; the
  export is a parallel emission from the same compile pass, so the two can never drift (guarded
  by `TestSubareaScenarioGatesFileIntegrity`). 97 pooled-subarea moons exported this seed.
- **World.py** (`_apply_subarea_scenario_gates`, runs last in `after_set_rules`, ON branch
  only, AFTER the rule replacement): `add_rule`s each exported fragment back onto the **member
  location** (which moves with the interior region under shuffle), via
  `entrance_logic.make_scenario_gate_rule` (a small `{Func(args)}` dispatcher against
  `hooks/Rules.py` — fragments are predicate-only, never `|item|`, so the full Manual parser
  isn't needed). The gate rides the LOCATION, not the door entrance — logically equivalent for
  per-location reachability, entrance-shuffle-safe, and enforced exactly once.
- **Interior-intrinsic** (resolves D3.3 on the logic side): the fragment is computed from the
  moon's OWN kingdom quest state, independent of which door now leads in. The remaining D3.3
  item is purely an **in-game play-test** for Devon: confirm that when a shuffled foreign door
  leads to a subarea, that subarea's moons are present per the INTERIOR kingdom's scenario
  state (which is what makes interior-intrinsic correct). The switch-mod entrance shuffle is
  stage-remap-only and moon presence is driven by each moon's own kingdom quest flags, so this
  should hold — but it's the hinge of correctness, so verify before relying on it.
- **Multi-layer subareas:** only 3 subareas span >1 gate-fragment (Deepest Underground,
  Secret Flower Field, Sewers). Because the gate is applied **per member** (each moon keeps its
  own fragment, not a min-layer aggregate), the multi-layer case needs NO special handling —
  each member is gated by its own bit-correct fragment. (Sewers is excluded from the pool
  anyway.)
- **Verification:** 14 new unit tests green (`TestScenarioFragmentsFor`,
  `TestBuildSubareaScenarioGates`, `TestSubareaScenarioGatesFileIntegrity`,
  `parse_scenario_fragment` ×3). Generate sweep **4 seeds ON + 4 seeds OFF** at
  `accessibility: full`, multi_moon_shuffle on, capturesanity + abilitysanity on = **8/8 clean**.
  ON-path log confirms `re-applied 97 interior scenario gates (D3)` per seed.
- **Pre-existing, NOT D3:** 6 failing tests in `test_entrance_shuffle.py` are stale subareas.json
  data-state asserts (Shiveria/Class A kingdom tag, Costume Room / Sphynx Vault split, pool-size
  `==119`) — a separate data-hygiene pass, untouched here.

## Done = 

- [x] `compile_moon_logic.py` reads no `is_moon_rock`; all scenario gates derive from
  `min_scenario`; report shows 0 fully-free rock moons. **(D1/D2 shipped 2026-06-20)**
- [x] Subarea moons gated at the subarea (D3), verified entrance-shuffle ON and OFF.
  **(SHIPPED 2026-06-20 — see "D3 — what actually shipped" below)**
- [x] `CascadeDeparture()` in Rules.py; tests extended and green (39/39).
- [x] Generate clean on the report seed + 8-seed sweep at `accessibility: full`; report
  seed winnable (Progressive Ground Pound no longer behind the leave-wall).
- [x] Diagnosis doc's §5/§7 reconciled with what actually shipped (see §10 there).
