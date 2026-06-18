# SMO Archipelago v2 Vision — Implementation Plan

Drafted 2026-06-12 from Devon's full feature brief; successor to the original M0–M7 plan.
Read CLAUDE.md first every session — its invariants (MoonGetHook chokepoint, pre-orig init
ordering, three-layer "lie to the game" hook pattern, "read the decomp before picking a
chokepoint") all apply here.

## Status (2026-06-17)

**P0–P4 COMPLETE and verified in-game. Remaining: P5, P6, P7.**

| Phase | What | State |
|---|---|---|
| P0 | CSV ingestion → `moon_requirements.json` (435/435 matched) + `subareas.json` (131) | ✅ |
| P1 | Cap Kingdom moons → 100 coins (`coin_grant` wire msg, idempotent high-water) | ✅ in-game |
| P2 | Capturesanity removed; Frog + Chain Chomp + 1-random precollected starters | ✅ |
| P3 | MK→captures / DarkSide→abilities item pool; junk-only MK/DS checks; ability tracking | ✅ |
| P4 | Ability gating on Switch (every move gated; Side Flip neuter, Up/Down/Spin Throw) | ✅ in-game |
| **P5** | **Per-kingdom moon colors** | ⬜ Sonnet, small |
| **P6** | **Logic difficulty tiers** (apworld-only) | ⬜ |
| **P7** | **Entrance shuffle** (headline feature) | ⬜ Opus |

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
- **Starting kit**: single jump + neutral cap throw, plus Frog, Chain Chomp, 1 random capture.
  Spark Pylon + Bowser precollected this iteration (progression-critical; randomizing them
  properly is deferred).
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

### P6 — Logic difficulty tiers  *(Sonnet 4.6 compiler, Opus review; apworld-only)*

- New `LogicDifficulty` Choice option: `intended` (M1) / `basic_tricks` (≤M2) /
  `intermediate_tricks` (≤M3) / `advanced_tricks` (≤M5).
- Rules compiler: per moon, OR across allowed methods; each method ANDs (jump-height term →
  qualifying ability items, cap-throw term, other-required terms → ability/capture items
  directly, "Capture" → col-C capture list OR). Generate into manual-AP `requires` strings or
  a generated Rules module — prefer generated data over ~836 hand-written rules.
- **Throw semantics (load-bearing — see P7 data §"Method/throw semantics"):** a method's
  `cap_throws` is the SET of throws that satisfy it; if it contains `neutral`/`none`, no
  motion-throw ability is required. No subarea's easiest path strictly requires Up/Down/Spin
  Throw. Likewise `jump_height` `single`/`none` = baseline (ungated); only
  `double/triple/backflip/long_jump/gpj/cap_return` gate.
- Sphere-1 audit: with the bare kit, generation must verify enough reachable sphere-1 checks
  in Cascade at every difficulty; add a guard test like the randomize_kingdom_gates one.
- Tests: fill succeeds at all 4 difficulties × kingdom-gate randomization; spot-check known
  moons (e.g. a Method-3-only moon unreachable on `intended`).
- **Data oddities to strip/special-case:** `"Locked behind Default Capture"` is a sentinel,
  not a capture; `outfit` and `2d_jump` appear under `other_required` but are NOT moveset
  ability items (a costume gate / inherent 8-bit mechanic) — don't map them to AP items.

### P7 — Entrance shuffle  *(Opus 4.8; headline feature, last — consumes P0 + P6)*

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

**Don't start manually:** the P6 logic compiler (subtle method/throw semantics above) and the
P7 entrance shuffle (symbol-discovery + trampoline-heavy, depends on the exclusion list). Read
`docs/milestones.md` M7 Path A before touching P7's stage-change hooks.
