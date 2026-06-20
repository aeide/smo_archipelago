# SMO Archipelago v2 Vision — Implementation Plan

Drafted 2026-06-12 from Devon's full feature brief; successor to the original M0–M7 plan.
Read CLAUDE.md first every session — its invariants (MoonGetHook chokepoint, pre-orig init
ordering, three-layer "lie to the game" hook pattern, "read the decomp before picking a
chokepoint") all apply here.

## Status (2026-06-18)

**P0–P4 + P6 + P6.5 + P7 COMPLETE. Remaining: P5 (per-kingdom moon colors).**

| Phase | What | State |
|---|---|---|
| P0 | CSV ingestion → `moon_requirements.json` (435/435 matched) + `subareas.json` (131) | ✅ (superseded by P6) |
| P1 | Cap Kingdom moons → 100 coins (`coin_grant` wire msg, idempotent high-water) | ✅ in-game |
| P2 | Capturesanity (later re-added as a live toggle); Frog + Chain Chomp + Broode's Chain Chomp + 1-random precollected starters | ✅ |
| P3 | MK→captures / DarkSide→abilities item pool; junk-only MK/DS checks; ability tracking | ✅ |
| P4 | Ability gating on Switch (every move gated; Side Flip neuter, Up/Down/Spin Throw) | ✅ in-game |
| **P5** | **Per-kingdom moon colors** | ⬜ Sonnet, small |
| **P6** | **Update logic** (xlsx ingest → recompile all moon `requires`) | ✅ Generate-validated (2026-06-17) |
| **P6.5** | **Moon-pipe moons → AP** (54 new locations + `<Kingdom>Peace` gates) | ✅ Generate-validated (2026-06-18); [spike §6](p7-entrance-shuffle-spike.md) |
| **P7** | **Entrance shuffle** (headline feature) | ✅ LIVE + validated in-game 2026-06-19 (`kEntranceRemapApply=true`, coupled-bijection return) |

P0–P4 implementation detail lives in git history, CLAUDE.md, and `docs/plan-p4-detail.md`
(the P4 canonical record). This file now covers only the design context that the remaining
phases consume + the P5–P7 plans + the P7 subarea/ability/capture correlation data.

---

## Design model (locked with Devon 2026-06-12 — context for P6/P7)

- **Bound-item model.** Each shuffled Mushroom-Kingdom moon item is bound to ONE capture, each
  Dark-Side moon item to ONE ability — independent items, no unlock ordering. The only ordered
  items are three progressive chains: Progressive Jump (Double→Triple), Progressive Crouch
  (Crouch→Roll→Roll Boost), Progressive Ground Pound (Ground Pound→Dive). Backflip, Long Jump
  and Ground Pound Jump are unique items that ALSO require their prerequisite in logic
  (Backflip/Long Jump need `|Progressive Crouch:1|`; Ground Pound Jump needs
  `|Progressive Ground Pound:1|`) — a logic AND, not chain membership.
- **Logic references items directly** — no indirection. "needs Dive" → `|Progressive Ground
  Pound:2|`; "needs Triple Jump" → `|Progressive Jump:2|`; "needs Roll Boost" →
  `|Progressive Crouch:3|`; "needs Backflip" → `|Backflip| and |Progressive Crouch:1|`;
  capture requirements → `|Gushen|` etc. Plain manual-AP `requires` syntax.
- **MK / Dark Side vanilla locations are junk-only checks** (`excluded`: filler/traps only,
  never progression/useful), vanilla post-game gating retained.
- **Starting kit**: single jump + neutral cap throw, plus Frog, Chain Chomp, **Broode's Chain
  Chomp** (added later for the Cascade scenario-gating fix), and 1 random capture.
  (SUPERSEDED: Spark Pylon + Bowser are NO LONGER precollected — they now ride the pool as
  progression gating items. See `hooks/World.py` `FIXED_STARTER_CAPTURES`.)
- **Logic difficulties** (P6) from the CSV methods: Intended (M1), Basic Tricks/Skips (≤M2),
  Intermediate (≤M3), Advanced (≤M5).
- **Entrance shuffle** (P7): every non-storyline subarea entrance in one pool; exits always
  return to the door entered through (so it's a simple bijection, no two-way pairing). Devon
  authors the exclusion list.
- **Per-kingdom moon colors** (P5): confirmed feasible — `ShineAppearanceHook.cpp` already
  recolors by classification via a palette index shipped per-location in `ShineScoutsMsg`;
  extend the palette with kingdom colors and have the client emit a kingdom index for our own
  slot's moon items. (Purple-coin model swap is a separate, deferred problem.)

---

## Remaining phases

### P5 — Per-kingdom moon colors  *(Sonnet 4.6; small)*

- Client: when a scouted location's item is our own slot's moon item, emit kingdom palette
  index (`5 + kingdom_id`) instead of the classification index in `ShineScoutsMsg` entries
  (`scout_cache.py` / `display.py` already classify; `maps.py` knows kingdoms).
- Switch: extend `kPaletteColors3D/Dot` in `ShineAppearanceHook.cpp` with the kingdom colors
  (Cap yellow, Cascade orange, Sand teal… match the in-game kingdom flag/coin colors).
- Wire-protocol.md: document the widened palette-index range (additive, fixed-buffer safe).
- **Caveat (from P7 data):** cross-kingdom subareas mean a recolor keyed on the *physical*
  kingdom of a moon can disagree with the subarea's enter-kingdom grouping — decide which
  keying P5 uses (physical kingdom is the natural choice for a moon-color feature).

### P6 — Update logic  ✅ *(Sonnet 4.6; apworld-only; done + Generate-validated 2026-06-17)*

**Reframed 2026-06-17** from the original "logic difficulty tiers" idea. Devon supplied a
fully corrected requirements spreadsheet (`SMO Requirements.xlsx`, sheet "Moons", 775 moons)
and difficulty tiers were dropped — there is now ONE logic, the corrected intended logic.
Two-stage pipeline:

**Stage 1 — faithful ingest** ([scripts/import_moon_requirements.py](../scripts/import_moon_requirements.py), rewritten for xlsx via openpyxl):
- Reads the 3-row/5-method blocks (jump height / cap throws / other required), records the
  structured data verbatim into `data/moon_requirements.json` + `data/subareas.json`.
- Corrected vocabulary: `other_required` collapsed to a clean moveset set
  (`Wall Slide`, `Cap Bounce` added; the legacy junk tokens outfit/2d_jump/scooter/jaxi/
  wall_jump/ledge_grab/… are gone). Capture names map 1:1 to items.json (3 normalisations:
  Wiggler→Tropical Wiggler, Ty-Foo→Ty-foo, Spark Pylon→Spark pylon).
- **Capture AND/OR model:** commas within one C cell = AND; a broken-up (unmerged) C cell =
  OR alternatives → `capture_groups` (list of AND-groups). 14 such moons; 0 use a literal
  "None" capture cell. Result: 775 blocks, 0 parse errors, 435/436 AP locations covered (the
  1 gap is the `Arrive in the Mushroom Kingdom` event location).

**Stage 2 — compile to `requires`** ([scripts/compile_moon_logic.py](../scripts/compile_moon_logic.py), new):
- `moon.requires = OR(methods) AND kingdom-gate AND subarea-gate AND per-moon-gate`, each
  method = `AND(height-term, throw-term, other-terms, capture-term)`. Writes the strings back
  into `locations.json`; skips junk_only locations (stay requirement-free). Emits
  [docs/logic-compile-review.md](logic-compile-review.md) listing assumptions + flagged moons.
- **Locked decisions (Devon 2026-06-17):**
  - Height is a FLOOR — a min-height requirement = OR of every jump item reaching ≥ that
    height (the ladder). Long Jump is its own horizontal axis.
  - **Vault == Cap Bounce** (corrects the earlier "dive = dive + cap bounce" note — Dive is
    just `Progressive Ground Pound:2`). So the 496 tier = `Backflip OR Side Flip OR Cap Bounce`.
    Consequence: Cap Bounce satisfies any height ≤496 — a high-reach logic item.
  - **Free captures (never gating): Frog + Chain Chomp only.** Spark pylon & Bowser GATE
    (so the Metro/Bowser-overworld Spark-pylon gates from the notes stay meaningful); the
    +1 random starter can't be relied on.
  - **Movement prerequisites:** Backflip & Long Jump each also need `Progressive Crouch:1`;
    Ground Pound Jump also needs `Progressive Ground Pound:1`. Side Flip: none.
- **Kingdom/subarea entrance gates** from [docs/capture-requirement-notes.md](capture-requirement-notes.md)
  lines 1–16 are ANDed onto every moon in the gated kingdom/subarea (Metro/Bowser overworld →
  Spark pylon; Lake overworld → Zipper OR jump-combo; subarea entrances → Manhole/Mini Rocket/
  Taxi/Zipper/Lava Bubble/Hammer Bro/Gushen; Employees Only → Crouch).
- **assume-MORE flags (Devon to review in logic-compile-review.md):** Bonk(Roll)→Roll;
  Narrow-Valley "max-height jump"→Triple; kingdom gates applied to ALL kingdom moons; cross-
  kingdom subareas keyed by physical kingdom.
- Result: 435 moons compiled (96 free, 118 kingdom-gated, 28 subarea-gated), all 56 item
  tokens resolve to real pool items.
- **Validated:** `install_apworld.py` + a full `Generate.py` fill SUCCEEDED (Full
  accessibility, 22-sphere playthrough to Victory under the Mushroom-Kingdom festival goal).
  Spot-check confirmed gate ordering — Spark pylon lands sphere 9 and every Metro moon is
  sphere 12+ (after it), so the Metro/Bowser kingdom-gates hold.
- **Open for Devon (post-commit, low priority):** the assume-MORE flags in
  [logic-compile-review.md](logic-compile-review.md) — chiefly whether the kingdom gates
  should apply to ALL kingdom moons (current) or only overworld moons. Loosening is a
  one-line change in `compile_moon_logic.py` + a recompile; nothing downstream depends on it.
- **Regen loop (any future moon-logic edit):** `import_moon_requirements.py` (if the xlsx
  changed) → `compile_moon_logic.py` → `install_apworld.py` → `Generate.py`. Needs `openpyxl`.

**Devon's review resolutions (2026-06-17) — all assume-MORE flags CONFIRMED, no recompile
needed for P6:**
- Bonk (Roll) → `Progressive Crouch:2` — ✅ correct.
- Narrow Valley "max-height jump" → Triple (`Progressive Jump:2`) — ✅ correct.
- Cross-kingdom subareas keyed by physical kingdom — ✅ correct.
- All capture OR/AND moons — ✅ correct.
- Kingdom-gates-apply-to-ALL-kingdom-moons — ✅ correct **for now**, but see P7 carry-over.

**P7 carry-over TODO (the two "matters for the entrance randomizer, not now" items):**
1. **Kingdom gates must split overworld vs subarea on entrance shuffle.** Today the Metro/
   Bowser/Lake kingdom gate is ANDed onto *every* moon in the kingdom (overworld + subarea
   interiors). Once entrances shuffle, the correct model is: the kingdom gate applies to all
   *overworld* moons AND to each *subarea entrance* — NOT blanket-ANDed onto every interior
   subarea moon (whose reachability then flows through whatever door the shuffle assigns).
2. **Narrow Valley (and any subarea with an entrance-gate ≠ interior requirement) needs the
   entrance vs interior requirement split.** Current compile ANDs both onto each interior
   moon: `(|Gushen| and (|Gushen| or (|Progressive Jump:2| and |Wall Slide| and |Cap Bounce|)))`.
   The `(Gushen OR jump-combo)` is the *entrance* requirement; once inside, Gushen alone is
   required. P7 must attach the entrance term to the door, not the interior moon. So
   `compile_moon_logic.py`'s `SUBAREA_GATES` / `gates_for()` should become P7-aware: emit
   per-door entrance requirements separately from per-moon interior requirements.

### P7 — Entrance shuffle  *(Opus 4.8; headline feature, last — consumes P0 + P6)*

**Pre-design spike DONE (2026-06-18): [docs/p7-entrance-shuffle-spike.md](p7-entrance-shuffle-spike.md).**
Chokepoint found + viable (`GameDataFunction::tryChangeNextStage(GameDataHolderWriter, const
ChangeStageInfo*)`; `ChangeStageInfo.mIsReturn` splits entry/exit at one hook). Exclusion list
validated (shuffle pool = 85 checked subareas). All four risk items investigated; build order +
3 open design questions for Devon recorded there. Symbol still needs sail verification.

- apworld: entrance pool = all subarea entrances minus Devon's storyline exclusion list
  (`data/entrance_exclusions.json` — Devon authors; Top-Hat Tower, Inverted Pyramid, etc.).
  Every exit returns to the entry door, so shuffle is a simple bijection door → subarea:
  subarea moons reachable iff the door's kingdom/region is reachable AND the subarea's own
  requirements hold. Door-regions from P0's `subareas.json`; reachability sweep like the
  kingdom-gates guard.
- slot_data → new `entrance_map` wire msg → `ApState` fixed-size table (respect committed
  fixed-buffer wire patterns).
- Switch: hook the stage-change path (`GameDataHolder::changeNextStage` / `ChangeStageInfo`
  consumption — symbol discovery needed): on subarea entry, remap (stage, entrance-id) per
  table and record the origin; on subarea exit, override the return destination with the
  recorded origin. Persist origin across save-load within a subarea (SaveLoadHook surface) so
  save+quit inside a subarea doesn't strand Mario.
- Pre-design Opus spike — investigate first: cross-kingdom subarea loads (scenario/time-of-day
  state), multi-moon story subareas (excluded anyway), checkpoint-flag side effects,
  Talkatoo%/moon-rock interactions.
- Re-uses the M7 "lie to the game" three-layer pattern for any UI previewing destinations.

---

## P7 data — subarea ↔ capture ↔ ability correlation (extracted 2026-06-14f)

Generated from P0's `data/moon_requirements.json` (775 CSV moons; 435 matched to current
apworld locations) + `data/subareas.json` (131 subareas) by `outputs/analyze_v3.py`. Full
per-moon detail in `outputs/subarea_analysis.json`. **Universe = the 435 ability-mapped
moons** (excludes Multi-Moons, boss/festival locations, and the P3 junk MK/DS checks).
"Required ability" uses the **easiest method** per moon (fewest non-baseline requirements);
starting kit = single jump + neutral/no cap throw + walk/capture.

**Method/throw semantics (load-bearing for the logic compiler — P6/P7):** a method's
`cap_throws` is the SET of throws that satisfy it; if it contains `neutral` or `none`, a
baseline throw works and NO motion-throw ability is required. Consequence: across all 131
subareas, **no subarea's easiest path strictly requires Up/Down/Spin Throw** — every
throw-flavored moon has a baseline-throw alternative, so gating the motion throws (P4) never
strands a subarea. Likewise `jump_height` `single`/`none` = baseline; only
`double/triple/backflip/long_jump/gpj/cap_return` are gated.

**(1) Overworld vs subarea moons per kingdom** (435 mapped; a moon is "subarea" iff its
location_name appears in a subarea's `location_names`; subarea moons count under the subarea's
assigned kingdom — see cross-kingdom caveat):

| Kingdom | Overworld | Subarea | Total |
|---|--:|--:|--:|
| Cap | 5 | 6 | 11 |
| Cascade | 15 | 6 | 21 |
| Sand | 42 | 23 | 65 |
| Lake | 21 | 7 | 28 |
| Wooded | 26 | 23 | 49 |
| Lost | 20 | 1 | 21 |
| Metro | 32 | 21 | 53 |
| Snow | 11 | 22 | 33 |
| Seaside | 39 | 9 | 48 |
| Luncheon | 34 | 15 | 49 |
| Ruined | 2 | 2 | 4 |
| Bowser's | 28 | 10 | 38 |
| Moon | 11 | 3 | 14 |
| Mushroom | 1 | 0 | 1 |
| **Total** | **287** | **148** | **435** |

**(2) Subareas gated by a capture** (≥1 member moon requires it). "ALL" = required by *every*
matched moon in the subarea → strongest entrance-key signal. **Frog and Chain Chomp are fixed
starters (P2), so their subareas are always open**; all other captures here are shuffled pool
items and genuinely gate the subarea.

- Cap: **Frog Pond** → Frog *(starter)* (ALL). **Poison Tides** → Gushen, Parabones,
  Paragoomba, Pokio (ALL) + Dino/Glydon/Shiverian.
- Cascade: **Dinosaur Nest** → Dino (ALL). **Nice Shots with Chain Chomps** → Chain Chomp
  *(starter)* (ALL).
- Sand: **Bullet Bill Maze** → Bullet Bill, Frog, Gushen, Hammer Bro, Parabones, Paragoomba,
  Pokio, Shiverian, Uproot (ALL). **Inverted Pyramid** → Bullet Bill, Glydon, Gushen,
  Parabones, Paragoomba, Shiverian, Yoshi (ALL). **Underground Ruins** → Gushen (ALL) + 9
  others. **Deepest Underground** → Glydon, Gushen, Parabones, Paragoomba, "Locked behind
  Default Capture".
- Wooded: **Sky Garden Tower** → Uproot (ALL). **Walking on Clouds** → Uproot (ALL). **Shards
  in the Fog** → Paragoomba (ALL). **Crowded Elevator** → Tank (ALL). **Secret Flower Field**
  → Frog/Gushen/Pokio/Tank/Uproot. **Deep Woods** → Bullet Bill/Coin Coffer/Dino/Hammer
  Bro/Tank. **Flower Road** → Goomba.
- Lost: **Crazy Cap Store (Lost)** → Pokio (ALL).
- Metro: **Shards Under Siege** → Tank (ALL). **Bullet Billding** → Bullet Bill.
- Snow: **Shiveria Town** → Dino/Frog/Glydon/Gushen/Parabones/Paragoomba/Shiverian/Yoshi (hub,
  9 matched moons).
- Seaside: **Flying Through the Narrow Valley** → Gushen (ALL).
- Luncheon: **Narrow Magma Path** → Lava Bubble (ALL). **Simmering in the Kitchen** → Lava
  Bubble (ALL). **Luncheon Treasure Vault** → Fire Bro + Lava Bubble (ALL). **Shards in the
  Cheese Rocks** → Hammer Bro (ALL). **Fork-Flickin to the Summit** → Forks (ALL).
- Bowser's: **Spinning Tower** → Pokio (ALL).
- Moon: **Underground Caverns** → Bullet Bill.

**(3) Capture → # of subareas it unlocks** (shuffled captures only; weight these in logic):

Gushen 8 · Paragoomba 7 · Parabones 6 · Pokio 6 · Bullet Bill 6 · Glydon 5 · Frog 5* ·
Uproot 5 · Shiverian 4 · Dino 4 · Tank 4 · Yoshi 3 · Hammer Bro 3 · Lava Bubble 3 ·
Goomba 2 · Chain Chomp 1* · Coin Coffer 1 · Fire Bro 1 · Forks 1 ·
"Locked behind Default Capture" 1 *(data marker, not a real capture — flag for cleanup)*.
(*Frog/Chain Chomp are starters → their subareas always reachable.*)

**(4) Abilities required within subareas** (corrected throw logic; count = # subareas whose
easiest path needs it):

| Ability | # subareas | Notes |
|---|--:|---|
| Long Jump | 22 | by far the most common gated requirement — widest logic reach |
| Ground Pound (`ground_pound`) | 7 | |
| Ledge Grab (`ledge_grab`) | 5 | |
| Wall Jump (`wall_jump`) | 5 | distinct from Wall Slide — verify which AP item maps here |
| 2D Jump (`2d_jump`) | 4 | 8-bit-tube sections; may be inherent, NOT an AP item |
| Dive (`dive`) | 4 | = Progressive Ground Pound L2 |
| Outfit (`outfit`) | 4 | a required costume, NOT a moveset ability — handle separately |
| Backflip | 4 | |
| Crouch (`crouch`) | 3 | Progressive Crouch L1 |
| Climb (`climb`) | 3 | |
| Cap Bounce (`cap_return`) | 2 | |
| Ground Pound Jump | 2 | |
| Triple Jump | 1 | Shiveria Town |
| Jaxi / Scooter / damage_boost / other_kingdom_trigger | 1 each | situational; not core moveset |
| **Up/Down/Spin Throw** | **0 (as hard req)** | never the sole path — see throw semantics |

**Caveats before P6/P7 logic uses this:**
- **Cross-kingdom subareas** count under the kingdom you *enter* them from, even when the moon
  lives in another kingdom's stage (Costume Room (Sand) holds `Wooded:`/`Seaside:` moons;
  Sphynx Treasure Vault (Sand) holds a `Seaside:` moon; Picture Match (Goomba) (Lake) holds a
  `Cloud:` moon). Correct grouping for entrance shuffle (door is in the enter-kingdom); a P5
  recolor keyed on *physical* kingdom would disagree.
- **"Locked behind Default Capture"** is a sentinel, not a capture — special-case or strip it.
- `outfit` / `2d_jump` are `other_required` but not moveset abilities — don't map to AP items.
- Numbers reflect **matched moons only**; subareas with `location_names: []` (post-game/Dark
  Side/most Mushroom subareas) contribute 0 and need their own pass if those moons ever become
  AP locations.

---

## Cross-cutting rules for every phase

- Wire changes are additive; never reshape committed fixed-buffer contracts.
- New moons/items: edit items.json/locations.json by hand, never bulk-import from romfs.
- After items.json/locations.json edits: re-run `sync_capture_table.py` / `sync_shine_table.py`.
- Re-read CLAUDE.md "Load-bearing invariants" at session start; update CLAUDE.md Status and
  docs/milestones.md at session end. Bundle via `install_apworld.py --out` in tests.
- Model guidance: Sonnet 4.6 for apworld/Python/data/tests; Opus 4.8 for switch-mod symbol
  discovery, new hooks, and the P7 spike. Start switch-mod sessions with the **smo-build** and
  **smo-symbol-discovery** skills.

---

## Manual-start guide (Devon — remaining phases)

**Entrance exclusion list (no code, unblocks P7 design early).** Write
`data/entrance_exclusions.json` — every storyline entrance to keep vanilla (Top-Hat Tower,
Inverted Pyramid, Ice Cave, Ruined Dragon arena, …). P7 consumes it as-is.

**Per-kingdom moon colors (P5).** Client: `client/scout_cache.py` + `client/display.py`
(classification → palette index) and `client/maps.py` (kingdom lookup). Switch:
`switch-mod/src/hooks/ShineAppearanceHook.cpp` — add kingdom rows to `kPaletteColors3D/Dot`.
Wire: the palette index already travels in `ShineScoutsMsg` (`client/protocol.py`,
`docs/wire-protocol.md`).

**Don't start manually:** the P7 entrance shuffle (symbol-discovery + trampoline-heavy, depends
on the exclusion list). Read `docs/milestones.md` M7 Path A before touching P7's stage-change
hooks. (P6 logic update is done — the corrected `requires` are already compiled into
locations.json; P7 reachability builds on top of them.)
