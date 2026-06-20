# Scenario reachability — logic design

How to turn the extracted per-moon scenario data
([scenario-gating-logic-design.md](scenario-gating-logic-design.md)) into AP
reachability rules, expressed in the pipeline this world already uses. Companion
to that doc: that one is *what the data means*; this one is *how logic consumes it*.

## Status (2026-06-19)

- **COARSE tier — SHIPPED.** `post_peace` gating (`is_moon_rock OR min_scenario >=
  peace_bit` → `{<Kingdom>Peace()}`) live in `compile_moon_logic.py`
  (`build_post_peace_names`).
- **MID_STORY tier — SHIPPED.** `build_mid_story_anchors` gates 60 moons (Sand 4,
  Wooded 7, Luncheon 10, Metro 39) on `{canReachLocation(<bit-(m-1) grand advancer>)}`,
  over-gating to the kingdom peace fragment where no exact-bit grand exists (Metro's
  bit-1 gap), and skipping the peace-anchor moon itself to avoid self-reference
  (Metro's Festival). Validated: 22 unit tests, 16/16 fixed-seed fills + a full
  playthrough generate cleanly, `locations.json` diff is requires-only (no new IP).
- **Cascade — SHIPPED (dedicated pass, 2026-06-19).** Cascade is excluded from the
  generic mid_story chain (its `clear_main_scenario=7` is its *last* scenario,
  `after_ending=3` earlier, so its bit layers form no clean advancer chain) and is
  instead handled by `build_cascade_anchors`: every non-rock Cascade moon at
  `min_scenario` in `[CASCADE_GATE_MIN_LAYER=1, CASCADE_GATE_MAX_LAYER=3]` ANDs in
  `{CascadePeace()}` (== `canReach(Multi Moon Atop the Falls)`, the player-controlled
  first advance). 19 moons gated. The earlier FillError (routing Cascade to
  `{CascadePeace()}` starved early spheres — Crouch/Ground Pound/Cascade Power Moons
  unplaceable) was caused by the gate pulling **Broode's Chain Chomp** (Multi Moon's
  required capture) forward; the fix was to grant Broode's Chain Chomp as a **fixed
  starter** (`hooks/World.py` `FIXED_STARTER_CAPTURES`, and a `FREE_CAPTURES` entry in
  the compiler), which makes Multi Moon collectable from arrival and the gate cheap.
  Validated: 36/36 fixed-seed fills (1000-1015, 2000-2019) clean, `locations.json` diff
  requires-only.

## 0. TL;DR

- Scenario gating is a **new gate layer in `compile_moon_logic.py`**, ANDed onto
  each moon's `requires` exactly like the existing kingdom/subarea/peace gates.
- It is consumed at **build time** (on the machine that has the romfs dump), and
  emits only boolean `requires` fragments (item names + `{Peace()}`-style calls)
  into the committed `locations.json`. **No IP ships, no runtime dependency on
  `shine_map.json`.** This is the answer to the §6 "IP boundary" question.
- The model: classify each moon by its **minimum present scenario** into one of a
  few tiers, and map each tier to an existing predicate (kingdom entry / a story
  anchor `canReachLocation` / `{<Kingdom>Peace()}` / leave-and-return).

## 1. The pipeline as it stands

`compile_moon_logic.py` (run after `import_moon_requirements.py`) writes
`moon.requires` into `apworld/smo_archipelago/data/locations.json`:

```
moon.requires = OR(methods) AND kingdom-gate AND subarea-gate AND per-moon-gate
```

It **already encodes the coarsest scenario gate**: every `Moon Rock`-category
location gets `{<Kingdom>Peace()}` (`MOON_ROCK_PEACE_GATES`), and `*Peace()`
(hooks/Rules.py) = `canReachLocation(<kingdom story-completing moon>)`. Entrance
shuffle reuses the same peace funcs for moon-pipe doors
(`entrance_logic.MOON_PIPE_PEACE_FUNCS`).

What's missing is gating for **non-rock moons that are still story-gated** —
Devon's examples: Cap moons that don't exist until you leave; Cascade moons that
appear only after `Multi Moon Atop the Falls` / only after leaving+returning; Sand
subareas that open through the story.

## 2. The reachability model

### 2.1 Inputs (per moon, from the extractor)

- `progress_bit_flag` — the set of scenarios the moon is present in (bit S = scenario S).
- `is_moon_rock`, `is_grand`, `main_scenario_no` — already emitted.
- Per kingdom (`world_scenarios.json`): `scenario_num`, `clear_main_scenario`,
  `moon_rock_scenario`, `after_ending_scenario` (all 1-indexed → bit = n−1).

### 2.2 Derive two things per moon

1. **`min_scenario`** = lowest set bit of `progress_bit_flag` (the earliest the
   moon can ever be collected).
2. **`scenario_class`** ∈ {`first_visit`, `mid_story`, `post_peace`}, by comparing
   `min_scenario` to the kingdom's `peace_bit = clear_main_scenario − 1`:
   - `min_scenario` is the kingdom's first **playable** scenario → `first_visit`.
   - `min_scenario` ≥ `peace_bit` (or `is_moon_rock`) → `post_peace`.
   - otherwise → `mid_story`.

   "First playable scenario" is **not always bit 0**: Cap's moons start at bit 1
   (validated — Cap has no bit-0 moons). So compute it per kingdom as
   `min(bit set across all the kingdom's moons)`, don't hardcode 0.

### 2.3 Map class → `requires` fragment

| class | gate fragment | rationale |
|---|---|---|
| `first_visit` | *(none)* — moveset + kingdom/subarea gates only | available the moment you can be in the kingdom |
| `post_peace` | `{<Kingdom>Peace()}` | reuse the existing peace predicate (already true for rock moons) |
| `mid_story` | `canReachLocation(<anchor moon of min_scenario>)` | the story moon whose collection advances the kingdom into `min_scenario` |

The **anchor of scenario S** is the grand/story moon that advances the kingdom into
S — derivable as the `is_grand`/`main_scenario_no` moon for that scenario. Build a
per-kingdom `{scenario_index → anchor location name}` map in the compile step; a
`mid_story` moon ANDs in `canReachLocation(anchor)`.

> Why `canReachLocation(anchor)` and not a generic moon count: scenario advance
> in SMO is driven by collecting the kingdom's story moons specifically, and those
> are themselves AP locations. Gating on the anchor's reachability is the faithful
> model and composes correctly with the rest of the graph (the anchor itself
> carries its own moveset/gate requirements).

### 2.4 Why `min_scenario` (not the full set) is sufficient

Scenarios are entered sequentially and the player controls when to advance (by
choosing to collect story moons). So if a moon is present in *any* reachable
scenario, the player can collect it by pausing at its earliest one. The only moons
that "disappear" across scenarios are the mandatory grand/story moons themselves
(present only in their anchor scenario), which are never missable because collecting
them *is* the advance. Conclusion: reachable ⇔ can reach `min_scenario`. (Flagged
for validation — see §5.)

## 3. Special cases

- **Cap/Cloud/Lost/Moon (re-arrival, "leave and come back") — SHIPPED via
  `build_rearrival_names` (2026-06-20).** These four have no boss-style `*Peace()`;
  their post-first-visit layers need "having left and returned." Every non-rock moon
  with `min_scenario > first_playable_bit` (broader than the coarse `>= peace_bit`
  test the floor guard skips for Cap/Cloud) ANDs in a `canReachRegion`-based predicate
  (`hooks/Rules.py`): `{CapPeace}`→`Sand Kingdom`, `{CloudPeace}`/`{LostPeace}`→
  `Night Metro`, `{MoonPeace}`→`Mushroom Kingdom`. Cap/Cloud are redundant-but-harmless
  (region already behind the hub); **Lost is load-bearing** (the layer sits behind
  enough Lost moons to reach Night Metro); Moon is currently a no-op (Moon→Mushroom is
  ungated — the "leave Moon = win" coupling). Tests: `TestBuildRearrivalNames` /
  `TestRearrivalGatesFor` in `test_scenario_gating.py`.

### Moon Kingdom — three moon layers + goal coupling — SHIPPED (2026-06-20)

Devon's ground-truth breakdown of Moon Kingdom moon availability (total 38):

| layer | Devon count | when available | in logic for CURRENT goal? |
|---|---|---|---|
| arrival | 14 | from first arrival | **YES** — only these |
| re-arrival | 13 | after defeating Bowser, **leaving, and returning** | NO (current goal) / YES (Dark/Darker goal) |
| moon rock | 11 | after breaking the Moon Rock | NO (current goal) / YES (Dark/Darker goal) |

For the **current goal** (`mushroom_kingdom`; "leave Moon = win"), only the first-visit
moons are collectable. The re-arrival + moon-rock layers sit at/after the win and are
physically uncollectable, so **no progression/useful item may be stranded behind them.**

**Enforcement (filler restriction, not reachability):** default `accessibility` is
**full**, so the 24 post-win moons cannot simply be made unreachable (that FillErrors).
Instead they are forced to **filler** (junk-only strength: `not advancement and not
useful`) while staying reachable. This is the safe, accessibility-compatible way to keep
them out of the goal's logic.

- **Classification is shine_map-driven** (`build_moon_postwin_names` in
  `compile_moon_logic.py`): a Moon moon is post-win iff `is_moon_rock` OR
  `min_scenario > first_playable_bit`. By shine_map this is 23 AP locations (16
  re-arrival + 7 rock); the arrival layer is the 15 moons at `min_scenario ==
  first_playable_bit (0)`. (Devon's 14/13/11 split totals the same 38; the ±1 boundary
  is safe because any moon present in scenario 0 is collectable on the first visit even
  if it sits behind the boss, so leaving it progression-eligible can't strand anything.)
- The compiler tags each with `"moon_postwin": true` in `locations.json` (boolean, IP-safe;
  only adjusted when shine_map is present so a no-data run never wipes the flags).
- `hooks/World.py _apply_moon_postwin_rules` (run from `after_set_rules`) applies the
  filler item-rule, **gated on the goal** via `GOALS_WITH_MOON_POSTWIN` (empty today —
  both `mushroom_kingdom` and `festival`, which drops Moon entirely, leave the layer
  uncollectable). **A future Dark/Darker-Side goal** adds its option value to that
  frozenset to collect the post-win moons normally.
- `{MoonPeace}` remains a no-op marker (Moon→Mushroom ungated); the `moon_postwin` flag,
  not reachability, is the enforcement signal.

Validated: `TestBuildMoonPostwinNames`; compiler reports `moon-postwin-tagged: 23`;
Generate passes and the spoiler shows all 23 hold only filler-classified Power Moons
(no abilities/captures/Spark pylon/Multi-Moons).

### Moon Cave traversal gate — SHIPPED (2026-06-20)

To clear **Moon Cave** (subarea `Underground Caverns` in `subareas.json`, kingdom
`Moon Kingdom`) and beat the game, the player needs **either** full item set:

- **(Parabones AND Banzai Bill AND Spark pylon)**, OR
- **(Ground Pound Jump AND Cap Bounce AND Wall Slide)**

Implemented in `compile_moon_logic.py` as `MOON_CAVE_TRAVERSAL` (emitted fragment:
`((|Parabones| and |Banzai Bill| and |Spark pylon|) or ((|Ground Pound Jump| and
|Progressive Ground Pound:1|) and |Cap Bounce| and |Wall Slide|))`). GPJ folds in its
`Progressive Ground Pound:1` prerequisite exactly as elsewhere in the compiler — a
correctness tightening over the literal 3-item set B (you cannot ground-pound-jump
without ground pound); flip `JUMP_FRAG["GPJ"]` → bare `|Ground Pound Jump|` to revert.

ANDed onto:
- the 5 `Underground Caverns` moons (`Moon: Under the Bowser Statue`,
  `Moon: Fly to the Treasure Chest and Back`, `Moon: In a Hole in the Magma`,
  `Moon: Around the Barrier Wall`, `Moon: On Top of the Cannon`), built from
  `subareas.json`;
- `Moon: Up in the Rafters` (Wedding Room subarea, but only cave-reachable —
  `MOON_CAVE_EXTRA_LOCATIONS`);
- the game-clear **goal location** `Arrive in the Mushroom Kingdom` (`victory: true`),
  set directly in `main()` — this replaces the old `{ParabonesSkip()}` stub (which was a
  vacuous `return True`) so at least one set is guaranteed placeable-and-reachable before
  the end.

Because each cave location's `requires` now contains all six items, AP fill cannot place
any of the six there (the location would be unreachable without the item in hand) — that
satisfies "the items may hide in Moon Kingdom but not in Moon Cave moons" for free. The
ability set (B) is capture-independent, so the goal stays reachable even with capturesanity
off. Tests: `TestMoonCaveTraversal` in `test_scenario_gating.py`. Validated: 38 unit tests
green, `compile_moon_logic.py` reports `moon-cave-gated: 6/6 cave moons + goal`, Generate
passes (no FillError, with entrance shuffle + randomized kingdom gates active).
- **Cascade anomaly (SHIPPED via `build_cascade_anchors`).** `clear_main_scenario=7`
  is Cascade's *last* scenario, with `after_ending=3` earlier — don't treat Cascade's
  `clear` as a generic peace bit. Cascade is handled by a dedicated pass that derives
  its split from observed bit layers: bit 0 = first_visit (free); `min_scenario` in
  `[1, CASCADE_GATE_MAX_LAYER]` ANDs in `{CascadePeace()}` (== `canReach(Multi Moon
  Atop the Falls)`). The Multi-Moon anchor (bit 0) and rock moons are always excluded.
  `CASCADE_GATE_MAX_LAYER` caps the top layer gated and is fill-capacity-bounded — it
  ships at 3 (all post-first-visit layers) because granting **Broode's Chain Chomp**
  (Multi Moon's required capture) as a fixed starter removed the fill pressure that
  previously forced the cap down. The two moon rocks that are capture-gated to *reach*
  (Cap = Paragoomba, Luncheon = Lava Bubble) AND in that capture on every
  moon-pipe moon behind them (`MOON_ROCK_REACH_CAPTURE`).
- **Sentinels.** `*_scenario ≥ scenario_num` means "never" (Mushroom/Dark/Darker
  rock=9, no rocks). Treat as no gate of that type.
- **Narrow masks.** A moon present only in mid scenarios (e.g. Cascade `flag=12` =
  bits {2,3}, no peace bit). `min_scenario` rule still applies; just confirm none
  are force-skipped (§5).
- **junk_only locations** (MK/Dark/Darker filler) stay requirement-free, as today.
- **Entrance shuffle.** Moon-pipe doors already get the peace gate via
  `entrance_logic`. Scenario gating on the *interior moons* composes on top; under
  shuffle a moon-pipe moon is reached via its shuffled origin door, whose access
  rule already carries the peace check. Keep the two layers independent.

## 4. Where it plugs in (implementation sketch, not yet built)

1. `compile_moon_logic.py` loads `shine_map.json` + `world_scenarios.json` (Devon's
   machine; both already produced by the extractor).
2. Build, per kingdom: `first_playable_bit`, `peace_bit`, and
   `{scenario_index → anchor location name}`.
3. Join each location to its `shine_map` record by name → `progress_bit_flag` /
   `is_moon_rock`; compute `min_scenario` + `scenario_class`.
4. Extend `gates_for()` to append the §2.3 fragment. (Rock moons already get a peace
   gate there — fold the two so a rock moon isn't double-gated.)
5. Add `CapDeparture()` (and any Cloud/Lost equivalent) to hooks/Rules.py if the
   anchor-location approach needs a named predicate.
6. Re-run `compile_moon_logic.py` → committed `locations.json`; rebuild the apworld
   zip; Generate. No switch-mod change.

IP: steps 1–3 read gitignored data at build time; step 4 emits only functional
fragments. Committed output stays clean.

## 5. Validation plan (do before trusting it broadly)

- **`min_scenario` sufficiency**: confirm no *collectable* (non-junk, non-grand)
  moon is present only in a scenario the player is forced past. Scan for masks whose
  bits are all `< first_playable_bit`-adjacent gaps; spot-check a few in-game.
- **Anchor map correctness**: verify the derived `{scenario → anchor}` matches the
  real story moons for 2–3 kingdoms (Sand, Metro, Wooded) against the moon names.
- **Cap/Cascade special cases**: confirm Cap moons gate on departure and Cascade's
  3-then-more behavior reproduces (the documented ground truth).
- **No over-gating**: the `first_visit` majority must stay free (moveset only), or
  fill tightens needlessly. Diff the free-moon count before/after.

## 6. Open questions for Devon

1. **Fidelity tier to ship first.** Recommend starting with the coarse split
   (`first_visit` free / `post_peace` = peace gate, generalizing the existing rock
   rule to all post-peace moons) and adding the `mid_story` anchor gates only where
   reachability is actually wrong. Full `mid_story` anchoring is more faithful but
   more surface area to get wrong. Which tier?
2. **Cap/Cloud/Lost departure predicate** — add `CapDeparture()` etc., or reuse
   `canReachLocation(<next kingdom's first moon>)` inline?
3. **Interaction with `multi_moon_shuffle`/`randomize_kingdom_gates`** — the anchor
   moons are multi-moon-shuffle locations; confirm `canReachLocation(anchor)` stays
   correct when the MM item is demoted/relocated (it should — it's location-, not
   item-, reachability).
