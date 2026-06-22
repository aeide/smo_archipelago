# Scenario logic revisit — 2026-06-20

Investigation log for the **Cascade leave-deadlock** Devon hit while playtesting the
first real logic seed. Supersedes nothing; this is the working diagnosis behind a
planned rewrite of the Cascade (and general moon-rock) scenario gating in
`scripts/compile_moon_logic.py`. Companion to
[scenario-reachability-design.md](scenario-reachability-design.md) and
[scenario-gating-logic-design.md](scenario-gating-logic-design.md) — read those for
the data model; this doc is *what's actually broken and how to fix it*.

## 1. The report

Seed `16146892779757521032` (`AP_27441512801635815860`). Options: entrance shuffle ON,
capturesanity + abilitysanity ON, `randomize_kingdom_gates` ON, multi-moon shuffle ON,
goal `mushroom_kingdom`.

In-game: stuck in Cascade. The Odyssey shows **7 moons to leave**. Player can physically
collect only a couple of Cascade moons; the rest — including the moon holding
**Progressive Ground Pound** — only appear *after breaking the moon rock*, which requires
leaving and returning to the kingdom. Classic chicken-and-egg: you need the moons to
leave, but you can't reach them until after you've left.

## 2. Confirmed facts

- **Gate value is consistent, not a logic/in-game mismatch.** The Generate log
  (`Generate_16146892779757521032_2026_06_20_15_14_31.txt`) shows:
  `randomize_kingdom_gates rolled: {'Cascade': 7, ...}`. Both `Rules.KingdomMoons`
  (logic) and the Switch's `UnlockShineNumHook` consume the same `world.rolled_kingdom_gates`
  table via `slot_data["kingdom_gates"]`, so logic and the game agree on **7**. Fill
  *succeeded* with gate 7 — it genuinely believed 7 effective Cascade moons were reachable
  before Sand.
- **The scenario flags are present and correct.** `bridge/smo_ap_bridge/data/shine_map.json`
  carries `progress_bit_flag` / `is_moon_rock` / `is_grand` for all 40 Cascade moons;
  `world_scenarios.json` gives Cascade `scenario_num=7, clear_main_scenario=7,
  moon_rock_scenario=4, after_ending_scenario=3`. All 40 committed `Cascade:` locations
  match a shine_map record by name (no name-mismatch problem in Cascade).
- **`compile_moon_logic.py` ran with the romfs data** — the Cascade moons in
  `locations.json` carry `{CascadePeace()}` fragments, which only appear when scenario
  data is present.

## 3. Cascade scenario layers (from the flags)

Bit `S` of `progress_bit_flag` set ⇔ moon present in kingdom scenario `S`. For Cascade
(`after_ending_scenario=3 → bit 2`, `moon_rock_scenario=4 → bit 3`):

| min_scenario bit | # moons | meaning | reachable when (in-game) |
|---|---|---|---|
| 0 | 6 | first-visit | on arrival |
| 1 | 13 | post-first-advance (after Madame Broode) | after collecting the grand moon, **before leaving** |
| 2 | 6 | after-ending | only after **leaving + returning** |
| 3 | 15 | moon-rock-era | only after **leaving + breaking the rock** |

So **19 moons (bits 0+1) are pre-leave**; **21 moons (bits ≥2) are post-leave**. Validated
against Devon's ground truth:

- `Cascade: Inside the Busted Fossil` → `flag=8` (bit 3) → POST-LEAVE → holds **Progressive
  Ground Pound**. Matches "GP is behind the moon rock." ✓
- `Cascade: Cascade Kingdom Timer Challenge 1` → `flag=78` (bits 1,2,3,6) → min bit 1 →
  post-advance/pre-leave. Reachable after Broode without leaving. ✓

That confirms the **scenario bit is the reliable reachability signal**, and that Devon's
"there are Cascade moons collectable after Broode but before leaving" is real (the 13 bit-1
moons).

## 4. Root causes

Four distinct defects compound here.

### 4a. `{CascadePeace()}` is a no-op (always true)

`CascadePeace()` = `canReachLocation("Cascade: Multi Moon Atop the Falls")`. That location
has `requires: ""` and lives in the **starting** Cascade region (Broode's Chain Chomp is a
fixed starter), so `canReachLocation` is **true from sphere 0**. Every Cascade scenario
gate that resolves to `{CascadePeace()}` therefore constrains nothing.

`build_cascade_anchors` gates `min_scenario` in `[1,3]` *all* on `{CascadePeace()}`. The
design ([scenario-reachability-design.md:207-218](scenario-reachability-design.md#L207))
explicitly calls this "a safe under-floor" for the after-ending layers. That reasoning is
the core mistake: a gate that is *always true* is not a floor at all. It is "safe" only in
the sense of never causing a FillError — it optimizes for *generation succeeding* at the
expense of the seed being *winnable*.

### 4b. `is_moon_rock` (shine_map) and `"Moon Rock"` (locations.json category) are DISJOINT

This is the surprise. They track different moons:

- `locations.json` `"Moon Rock"` category for Cascade = the 4 cloud moons (`Across the
  Mysterious Clouds`, `Atop a Wall Among the Clouds`, `Across the Gusty Bridges`, `Flying
  Far Away from Gusty Bridges`). In shine_map these are `flag=8` (bit 3) but
  **`is_moon_rock=False`**.
- `shine_map` `is_moon_rock=True` for Cascade = 11 *different*, overworld-named moons
  (`Inside the Busted Fossil`, `Next to the Stone Arch`, `Guarded by a Colossal Fossil`,
  `Under the Ground`, `Bottom of the Waterfall Basin`, …), none of which carry the
  category. Most ship `requires: ""`.

`compile_moon_logic.py` depends on **both** signals and they don't agree:

- `build_post_peace_names` and `build_cascade_anchors` both `continue` (skip) on
  `is_moon_rock`, expecting the locations.json `"Moon Rock"` **category** (`moon_rock_names`)
  to gate those moons instead.
- But the category set ≠ the `is_moon_rock` set, so an `is_moon_rock` moon without the
  category falls through **every** gating branch → `requires: ""`.

Blast radius across all kingdoms (shine_map `is_moon_rock` vs `"Moon Rock"` category):

```
Kingdom    | is_moon_rock | miscategorized (no category) | of those, requires=="" (FULLY FREE)
Bowser's   |  13 | 13 | 0
Cap        |  12 | 12 | 1
Cascade    |  11 | 11 | 6
Cloud      |   5 |  4 | 1
Lake       |   7 |  7 | 0
Lost       |   6 |  6 | 2
Luncheon   |   6 |  6 | 0
Metro      |   9 |  9 | 0
Moon       |   7 |  7 | 6
Ruined     |   3 |  3 | 0
Sand       |  14 | 14 | 4
Seaside    |  15 | 15 | 9
Snow       |  10 | 10 | 7
Wooded     |  16 | 16 | 3
TOTAL: 133 miscategorized rock moons; 39 shipped FULLY FREE.
```

So 39 post-rock moons across the game are currently logic-free (collectable in sphere 1
per AP), and the rest are only "gated" by the no-op peace fragment. Cascade is the kingdom
where this bites hardest because it is the *starting* kingdom — there is nothing reachable
before it, so a stranded item is unrecoverable.

> **Open question on `is_moon_rock` semantics.** The flag appears NOT to mean "moon in the
> rock-revealed cloud subarea" (those are `is_moon_rock=False`). It flags overworld moons
> that read like *buried/dig-up* moons (`Inside the Busted Fossil`, `Under the Ground`,
> `Guarded by a Colossal Fossil`). Whatever it means precisely, it is **not** a reliable
> "needs the rock broken" signal — the **bit** is. Recommendation below stops using
> `is_moon_rock` as a gate input entirely.

### 4c. The after-ending / rock layers need a real "you have left" gate, not peace

For Cascade, `clear_main_scenario=7` is its *last* scenario, so the generic `peace_bit`
rule doesn't apply (that's why it has a dedicated pass). The correct gate for the bits-≥2
layers is the same **re-arrival** model already shipped for Cap/Cloud/Lost
(`build_rearrival_names` → `canReachRegion(<hub>)`): "you have left the kingdom." For
Cascade that is `canReachRegion("Sand Kingdom")`. The post-advance (bit 1) layer stays on
`{CascadePeace()}` (genuinely reachable pre-leave once you can beat Broode).

### 4d. Net effect on this seed

Joining the spoiler placements with the bit layers, of the Cascade Power Moons that fill
put in **Cascade-region** locations:

```
[post-advance(pre-leave)] Cascade Kingdom Timer Challenge 1  <- Cascade Kingdom Power Moon
[POST-LEAVE(bit3)]        Next to the Stone Arch             <- Cascade Kingdom Power Moon
[POST-LEAVE(bit3)]        Guarded by a Colossal Fossil       <- Cascade Kingdom Power Moon
[POST-LEAVE(bit3)]        Cascade Kingdom Master Cup         <- Cascade Kingdom Power Moon
=> effective Cascade moons obtainable BEFORE leaving (Cascade region): 1
=> stranded behind the leave-wall: 3      leave-gate: 7
```

Fill scattered the leave-critical Cascade moons (and Ground Pound) behind post-leave moons
because the no-op gates made all 40 Cascade moons look reachable in sphere 1. The 19
genuinely pre-leave Cascade locations exist and could easily hold 7 Cascade moons — fill
just wasn't forced to use them.

**Reconciliation with "I only have 2 Cascade moons" (confirmed by Devon).** The two
Cascade Power Moons actually reachable pre-leave are:

- `Cascade Kingdom Timer Challenge 1` — bit-1 (post-Broode, pre-leave); collectable because
  Devon has Long Jump. = 1
- `Luncheon: Treasure of the Lava Islands` — a **Cascade** Power Moon reached from Cascade
  via an **entrance-shuffle** door (the sole sphere-4 moon in the playthrough). = 1

= **2**, exactly what Devon has. The other five the gate wants are behind bit-3 rock moons
(`Next to the Stone Arch`, `Guarded by a Colossal Fossil`, `Cascade Kingdom Master Cup`)
and post-Sand kingdoms (`Cap: Bonneter Blockade`, …) — all unreachable until after the
leave-wall. Deadlock fully accounted for.

Note this means the **entrance randomizer logic is working correctly** and is in fact
*load-bearing*: without that shuffled cross-kingdom moon, fill's "7 reachable" claim would
have been even more fictional. The fix below must preserve this — entrance-shuffle-reachable
cross-kingdom moons are a legitimate pre-leave source and may count toward the leave-gate.

## 5. Proposed fix — gate purely on the scenario bit

Rewrite the Cascade pass (and the rock handling generally) to key off `min_scenario`, not
`is_moon_rock`/category.

### 5a. Cascade dedicated pass (`build_cascade_anchors`)

For each non-junk Cascade moon, compute `m = min_scenario(progress_bit_flag)` and
`ae_bit = after_ending_scenario - 1` (= 2 for Cascade):

| `m` | gate |
|---|---|
| `0` (first-visit) | none (moveset/subarea only) |
| `1 .. ae_bit-1` (post-advance, pre-leave) | `{CascadePeace()}` (vacuous-but-correct; documents intent if Broode's Chain Chomp ever stops being a starter) |
| `≥ ae_bit` (after-ending + rock) | **`{CascadeDeparture()}`** = `canReachRegion("Sand Kingdom")` |

Stop excluding `is_moon_rock` moons — classify everything by its bit. Add a
`CascadeDeparture()` predicate to `hooks/Rules.py` (mirror of `CapPeace`/`CloudPeace`).

### 5b. General rock handling (`build_post_peace_names`)

Remove the `if e.get("is_moon_rock"): continue` skip. Classify every non-junk moon by
`min_scenario >= peace_bit` (rocks naturally qualify — `moon_rock_bit >= peace_bit` in the
boss kingdoms). This recovers the 39 currently-free rock moons under `{<Kingdom>Peace()}`,
which is the correct gate (the runtime `MoonRockHook` opens the rock on peace; the
moon-pipe entrance already carries a peace gate). Keep `moon_rock_names` (category) only
for the `MOON_ROCK_REACH_CAPTURE` capture gates and any in-game labeling — not as the
scenario-reachability source.

### 5c. Capacity / fill safety

- Cascade pre-leave capacity = 19 locations (6 bit-0 + 13 bit-1), well above the
  `randomize_kingdom_gates` max roll of `vanilla(5)+SPREAD(5)=10`. So forcing the leave-gate
  to be satisfied from pre-leave moons is feasible; **no Cascade-specific clamp needed** as
  long as ≥ gate Cascade Power-Moon *items* can be placed among those 19 (plenty in the
  pool). Confirm with a fixed-seed fill sweep after the change.
- No new circular dependency: post-leave Cascade moons require `canReachRegion("Sand")`,
  Sand requires `KingdomMoons(Cascade,N)` satisfiable from the 19 pre-leave moons. Fill
  will place the N gate moons pre-leave and the rest post-leave.
- Watch for FillError on the *other* kingdoms once §5b stops free-gating 39 rock moons —
  that tightening is correct but increases fill pressure. Sweep seeds.

## 6. Why this matches the original design intent

[scenario-gating-logic-design.md §2](scenario-gating-logic-design.md) already says "reachable
⇔ can reach `min_scenario`" and that the bit mask is the source of truth. The implementation
drifted to a *category/boolean* proxy for "moon rock" that turned out to be a different set.
The fix is to honor the doc: gate on the bit. The only genuinely new design decision is
mapping Cascade's bits-≥2 to a **departure** predicate (since Cascade's `clear` isn't a
peace bit) — and that decision is already precedented by the Cap/Cloud/Lost re-arrival pass.

## 7. Open items / follow-ups

1. **`is_moon_rock` true meaning** — worth a one-line probe against the romfs (what
   `IsMoonRock` actually marks) so we document it, but the fix does not depend on the
   answer.
2. **Entrance-shuffle cross-kingdom reachability — CONFIRMED WORKING (Devon, in-game).**
   `Luncheon: Treasure of the Lava Islands` (a Cascade Power Moon) is reachable from
   Cascade via a shuffled door, and Devon verified the in-game remap actually connects it —
   so logic-reachable == game-reachable here. This is *not* a bug; it is load-bearing for
   the seed (one of the two Cascade moons Devon can collect). The §5 fix must keep treating
   such cross-kingdom moons as valid pre-leave sources. Caveat: the spoiler log does **not**
   print the entrance map (it lives in `slot_data["entrance_map"]`, not the spoiler), so
   these reachability paths are invisible in the spoiler — a dedicated entrance-map dump in
   the spoiler/output would make future debugging far easier (suggested tooling follow-up).
3. **Generalize the after-ending vs peace split** — verify the other re-arrival/odyssey
   kingdoms don't have the same "clear is the last scenario" quirk that would mis-map their
   post-leave layers.
4. **Audit the 213-promotion categorizer** (`add_missing_moon_locations.py`) — it assigned
   cluster categories without consulting scenario flags, which is how the category/flag
   drift arose. Decide whether the `"Moon Rock"` category should be regenerated from
   shine_map or retired in favor of bit-driven gating.

## 8. Implementation + regen checklist (on the romfs machine)

1. Edit `compile_moon_logic.py` (§5a/§5b) + add `CascadeDeparture()` to `hooks/Rules.py`.
2. Extend `tests/test_scenario_gating.py` with the bit-layer cases (first-visit free,
   bit-1 → CascadePeace, bit-≥2 → CascadeDeparture; the disjoint is_moon_rock case).
3. `python scripts/compile_moon_logic.py` — confirm Cascade post-leave count jumps and the
   "fully free" rock count drops to ~0.
4. `python scripts/sync_shine_table.py` — verify `// Count:` unchanged (names already match).
5. `python scripts/install_apworld.py`
6. `python vendor/Archipelago/Generate.py` — re-roll the same/representative seeds; verify
   no FillError and that the spoiler places ≥ gate Cascade moons in pre-leave Cascade
   locations.
7. Spot-check the new seed in-game: 7 Cascade moons collectable before leaving.

> ⚠ Never run `compile_moon_logic.py` without `shine_map.json` + `world_scenarios.json`
> present — it degrades to rock-only and wipes the compiled gates (CLAUDE.md).

## 9. Decisions (Devon, 2026-06-20)

These resolve the two open scoping questions from §5/§7 and add one architectural
constraint. They are the authoritative direction for the implementation session.

### D1. Fix it everywhere, not just Cascade

This is a general defect, not a Cascade quirk — `is_moon_rock`/category drift strands
moons (or free-passes them) across the whole game (§4b: 133 miscategorized, 39 fully
free). The rewrite applies to **every kingdom**, not a Cascade special-case. Cascade is
just where it surfaced first (starting kingdom → unrecoverable). Expect this to tighten
fill across all kingdoms; the §5c seed sweep is mandatory, not optional.

### D2. Retire `is_moon_rock` and the `"Moon Rock"` category as reachability inputs

Stop trusting either signal for scenario reachability. **Rebuild all scenario
"reachability" gating to key off the game-provided `min_scenario` bit**, which is
guaranteed correct (validated 1:1 against in-game in §3). Concretely:

- `compile_moon_logic.py` no longer reads `is_moon_rock`, and no longer `continue`s on it.
- The `"Moon Rock"` **category** in `locations.json` is no longer a reachability source.
  Keep it ONLY where it still earns its place: the `MOON_ROCK_REACH_CAPTURE` capture
  gates and any in-game labeling. If nothing else depends on it, retire it outright
  (decide during implementation — audit `moon_rock_names` consumers first).
- Every moon's scenario gate is derived from its `min_scenario` bit vs the kingdom's
  `after_ending` / `peace` / `clear` bits — one uniform classifier, no per-flag proxies.

### D3. Gate SUBAREA MOONS at the subarea, not the moon (entrance-randomizer-safe)

New constraint, load-bearing for entrance shuffle. A moon that lives inside a subarea
must NOT carry the scenario predicate on the moon's own `requires`. Instead the
scenario gate belongs on the **subarea entrance/region** (the thing the entrance
randomizer rewires).

Why: with the entrance randomizer ON, a subarea's door can be relocated, so "can I reach
this subarea" is answered by the (possibly shuffled) entrance — not by the moon. If the
scenario predicate is baked onto each moon, it double-gates (and can contradict the
shuffled entrance: a subarea reachable early via a shuffled door would still have its
moons falsely gated by the origin kingdom's scenario). Putting the scenario gate on the
subarea region means:

- **Entrance shuffle OFF** — subarea reached through its vanilla door; the scenario gate
  on the subarea region applies exactly as before. No behavior change.
- **Entrance shuffle ON** — subarea reached through whatever door now maps to it; the
  scenario gate rides the subarea region, so it's enforced once, in the right place,
  regardless of which door leads there.

Implementation shape (to be confirmed against `regions.json`/`subareas.json` in the
impl session): the per-subarea scenario predicate is emitted onto the **subarea
region's entrance `requires`** (alongside the existing subarea-entrance/capture gates),
and the moons inside inherit reachability by region membership — their own `requires`
keep only moveset/capture terms. Overworld (non-subarea) moons keep the scenario gate on
the moon as today. The §3 bit layers still decide *what* the gate is; D3 only changes
*where* it is attached for subarea moons.

> Cross-check needed in impl: `subareas.json` maps subareas → `location_names`. The
> compiler must group a subarea's moons, compute the subarea's effective `min_scenario`
> (the min over its moons, or the subarea's own scenario if the data carries one), and
> emit one gate on the subarea region. Watch for subareas whose moons span multiple
> scenario layers — the gate should be the *earliest* layer that opens the subarea, with
> any later-layer moons inside still individually gated by their own bit on top (rare;
> flag and handle explicitly).

## 10. What actually shipped (2026-06-20 impl session) — reconciles §5/§7

D1 + D2 + **D3 are all implemented, tested, and seed-swept** (D3 shipped later the same day;
full writeup in [handoff-scenario-logic-rewrite.md](handoff-scenario-logic-rewrite.md)
§"D3 — what actually shipped"). D3 in brief: subarea moons LOST their scenario gate under
entrance-shuffle ON (the rule-replacement dropped it); the compiler now exports
`data/subarea_scenario_gates.json` (pooled-subarea moons → fragment) and World.py
re-applies it per-member after the rule replacement. `locations.json` is unchanged
(shuffle-OFF stays byte-identical); 8/8 clean Generate sweep ON+OFF at `accessibility: full`.
The one open D3 item is a pure in-game play-test (D3.3 interior-intrinsic confirmation).
Deviations from the literal §5/§9 wording:

- **Kept the four-pass structure** (`build_post_peace_names` / `build_rearrival_names` /
  `build_mid_story_anchors` / `build_cascade_anchors`) rather than collapsing to a single
  function. Each pass was already bit-classified; the fix removed the `is_moon_rock`
  skips and the category seed, so behaviour is now purely `min_scenario`-driven (D2)
  without a risky full rewrite of the well-tested passes.
- **`is_moon_rock` is no longer read anywhere in the compiler for gating OR for the Moon
  post-win filler tag.** `build_moon_postwin_names` now tags purely on
  `min_scenario > first_playable` — verified safe because all 7 Moon rock moons already
  sit at a later scenario than arrival (so the bit rule catches them; the synthetic
  "rock shares arrival bit" case can't occur in real data).
- **`build_post_peace_names` dropped the `moon_rock_names` category seed** — post_peace is
  now pure bit classification. Boss-kingdom rocks land there on their own bit
  (`min_scenario >= peace_bit`), recovering the 39 previously-free rocks. The `"Moon
  Rock"` category is retained ONLY for (a) `MOON_ROCK_REACH_CAPTURE` (Cap/Luncheon reach
  captures) and (b) the `moon_rock_checks` location-enable toggle in `categories.json` —
  never as a reachability source.
- **Cascade pass split at `ae_bit = after_ending_scenario - 1` (= 2).** bit 0 = free,
  bit 1 = `{CascadePeace()}` (pre-leave, vacuous-but-correct), bit ≥ 2 =
  **`{CascadeDeparture()}` = canReachRegion("Sand Kingdom")**. The old
  `CASCADE_GATE_MAX_LAYER` fill-capacity cap was removed (no longer needed — Broode's
  Chain Chomp is a fixed starter, so the pre-leave layer is free).
- **Rocks in Cap/Cloud/Lost/Moon** now get their kingdom's re-arrival `{*Peace()}` gate
  (rock exclusion removed from `build_rearrival_names`).

**Verification (this machine, romfs present):**
- `compile_moon_logic.py`: **0 fully-free rock moons** (was 39); Cascade = 6 first-visit
  free + 13 `CascadePeace` + 21 `CascadeDeparture` (= the §3 19-pre / 21-post split).
- `test_scenario_gating.py`: 39/39 green (extended with the §4 bit-layer cases + the §4b
  disjoint-rock regression guard).
- **Seed sweep, 8 seeds incl. the report seed `16146892779757521032`, all-options-on,
  `accessibility: full`: 8/8 generate cleanly, no FillError.** Because `full` proves
  every location reachable via sphere search, a clean gen is proof the deadlock can't
  recur. In the report seed's spoiler, **Progressive Ground Pound moved out of the
  post-leave Cascade location** (`Inside the Busted Fossil`, bit 3 → `CascadeDeparture`)
  into Sand/Snow/Bowser's; the leave-critical Cascade Power Moons sit in pre-leave
  locations; post-leave Cascade locations hold other kingdoms' non-leave-critical moons.

**Pre-existing failures NOT caused by this change** (data the tests read is unmodified):
`test_entrance_shuffle.py` (pool size assertion is stale: asserts 119, real pool is 116)
and `test_moon_requirements.py::test_subarea_csv_names_in_requirements` ("Underground
Caverns" csv_names vs requirements drift). Both predate this work; flagged for a separate
data-hygiene pass.

## 11. CORRECTION (2026-06-21) — `CascadeDeparture` was STILL a no-op; the §8 "8/8 clean" proof was false

The §5a/§10 fix replaced `CascadePeace` (no-op #1) with
`CascadeDeparture() = canReachRegion("Sand Kingdom")` — and that is **no-op #2**. Devon hit
the *same* unwinnable Cascade deadlock on a fresh seed (`69832988328664538026`, Cascade gate
9): the leave-gate wanted 9 Cascade moons but most were behind `{CascadeDeparture()}`,
which evaluated **True from sphere 0**.

**Root cause (verified empirically with a solo-multiworld `can_reach_region` probe):** the
Manual region engine (`apworld/.../Rules.py::set_rules`, the region loop at ~L231-238)
applies a region's `requires` to that region's **OUTGOING** entrances — it gates *leaving* a
region, not *entering* it. Cascade is the free starting region, so the Cascade→Sand entrance
inherits Cascade's empty requires and **reaching the Sand region is free from sphere 0**; the
leave-gate `{KingdomMoons(Cascade,N)}` written on Sand actually rides Sand's *exits*
(Sand→Cap/Lake). Probe at empty state: `can_reach_region("Sand Kingdom") = True`,
`Cap/Lake/Wooded = False`. So `canReachRegion("Sand Kingdom")` is a constant-True predicate.

Why §8's `accessibility: full` sweep "passed" anyway: a no-op gate never causes a FillError —
it makes generation *easier*, not harder. `full` proves a valid sphere order EXISTS under the
logic *as written*; if the logic says the moons are free at sphere 0, fill is trivially
satisfiable and the "proof" is vacuous. This is the **exact §4a trap** ("a gate that is always
true is not a floor") — the rewrite identified it for `CascadePeace` and then walked straight
back into it for `CascadeDeparture`.

**Why ONLY Cascade is catastrophic:** non-starting kingdoms' moons are also gated by their
own region's `requires` string at the *location* level (`set_rules` L249-259 ANDs
`locationRegion`'s requires onto each location) **and** by AP parent-region reachability — so a
Sand/Lake/etc. location is still correctly gated. Cascade is the starting region with empty
`requires`, so its moons have **no** region-level gate; their only gate is their own
`{CascadeDeparture()}` predicate — which was the no-op.

**The fix (shipped 2026-06-21):** gate the predicate on the leave-moon count directly instead
of a free region's reachability:

```python
def CascadeDeparture(...): return KingdomMoons(world, multiworld, state, player, "Cascade", 5)
```

`KingdomMoons` reads `world.rolled_kingdom_gates`, so it tracks the rolled gate (N=5→rolled).
`CapPeace` had the identical `canReachRegion("Sand Kingdom")` no-op and was repointed the same
way (redundant in effect — Cap locations are already gated by parent-region reachability =
`KM(Cascade,N)` — but corrected for clarity/robustness). `CloudPeace`/`LostPeace`
(`Night Metro`) and `MoonPeace` (`Mushroom`) target genuinely-gated regions (False at sphere 0)
and were left as-is.

**Verification:** empirical probe — the three sampled `CascadeDeparture` moons are False at
empty state, False at gate-1, and all True at exactly the rolled gate; `Multi Moon Atop the
Falls` (`CascadePeace`, the starting story moon) stays True. Report seed re-generated:
**0 Cascade departure moons in sphere 1** (was 6). 5-seed `accessibility: full` sweep clean
(Cascade gates 3–9). New guard `tests/test_cascade_reachability.py` (SMOAP_LIVE_AP) builds a
real multiworld and asserts the gate — closing the blind spot that let a syntactically-present
but semantically-dead gate ship twice.

**Latent, non-blocking (NOT fixed here):** the egress-vs-ingress region-gating is a *systemic*
off-by-one — every kingdom's region is reachable "one kingdom early" at the **region** level.
It is masked for kingdom progression by the location-level region-requires AND parent-region
reachability checks, and now masked for the scenario predicates by keying them off
`KingdomMoons` rather than `canReachRegion`. A proper engine fix (apply region `requires` to a
region's *incoming* entrances) would remove the off-by-one globally but shifts every gate and
needs a full re-tune + re-sweep of `KINGDOM_MOON_GATES` / the demotion logic — deferred; do NOT
attempt without a full-sweep budget. Until then: **never use `canReachRegion(<kingdom>)` as a
"player has left kingdom K" predicate** — use `KingdomMoons(K, ...)`.

## 12. Item-1 audit (2026-06-22) — `CloudPeace`/`LostPeace`/`MoonPeace` off-by-one

Deferred item 1 of [handoff-region-gating-egress.md](handoff-region-gating-egress.md). Audited
the three re-arrival predicates still on `canReachRegion` with a solo-multiworld collection
walk (the `setup_multiworld` + `can_reach_region` probe pattern from
`tests/test_cascade_reachability.py`, randomize-gates OFF so gates == `KINGDOM_MOON_GATES`).
Empirical result — region first reachable after collecting all of:

| Region | Opens after | Authored ingress | Verdict |
|---|---|---|---|
| Night Metro | **+Wooded** (zero Lost moons) | after Lost (`KingdomMoons(Lost,10)`) | **one kingdom early** |
| Cloud Kingdom | +Lost | parent edge `KingdomMoons(Lost,10)` | correct |
| Mushroom Kingdom | **+Bowser's** | after Moon | **one kingdom early** |

Cause is the egress engine (§11): Night Metro is reached via the `Lost→Night Metro` edge, which
inherits **Lost's** requires `{KingdomMoons(Wooded,16)}`; Mushroom via `Moon→Mushroom` inheriting
**Moon's** `{KingdomMoons(Bowser's,8)}`. Cloud is reached via `Night Metro→Cloud` inheriting Night
Metro's `{KingdomMoons(Lost,10)}`, so its *region* is correctly gated at Lost(10) — `CloudPeace`'s
old `canReachRegion("Night Metro")` was looser (Wooded) but masked by that parent edge.

**Fixes (this session):** `LostPeace` and `CloudPeace` repointed to `KingdomMoons("Lost",10)`
(rolled-gate aware). `MoonPeace` **deliberately left** on `canReachRegion("Mushroom Kingdom")`:
leaving Moon == reaching Mushroom == winning (the "leave Moon = win" coupling), so its post-peace
moon-pipe re-arrival moons inherently sit at/after the goal boundary — there is no faithful
pre-win threshold (the documented "later goals" deferred item; revisit only if a post-festival
goal is added).

**Verification:** the 3 pure-predicate Lost/Cloud re-arrival moons are closed at empty, closed at
the Lost gate−1 (boundary), and all open at exactly the Lost gate. New guard
`tests/test_rearrival_reachability.py` (SMOAP_LIVE_AP) builds a real multiworld and asserts it;
both it and `test_cascade_reachability.py` pass against the installed zip.
(Note: Lost-region locations also inherit Lost's own region requires `{KingdomMoons(Wooded,16)}`
ANDed at the location level — so the off-by-one over-permit was already masked for *progression*;
the predicate fix tightens the *scenario layer* gate from Wooded to Lost, the faithful threshold.)
