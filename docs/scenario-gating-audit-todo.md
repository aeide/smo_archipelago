# Scenario-gating audit & TODO — vs "Odyssey Scenario_Gating Logic.xlsx"

Working doc produced 2026-06-26 by diffing Devon's authored ground-truth spreadsheet
(`Odyssey Scenario_Gating Logic.xlsx`, 774 moons — every moon except Darker Side's lone
multi-moon) against our **compiled** scenario gating in
`apworld/smo_archipelago/data/locations.json` (the `requires` strings) and
`apworld/smo_archipelago/data/subarea_scenario_gates.json`.

Companion to [scenario-logic-revisit-june-20.md](scenario-logic-revisit-june-20.md) and
[handoff-scenario-logic-rewrite.md](handoff-scenario-logic-rewrite.md) — read those for the
data model and the Cascade no-op history. This doc is the **spreadsheet reconciliation**:
what matches, what doesn't, and the exact fix list.

## 0. How to reproduce this diff

All inputs are on the romfs machine:
- Spreadsheet at repo root (Devon-authored, safe).
- `apworld/smo_archipelago/data/locations.json` — compiled `requires`.
- `apworld/smo_archipelago/data/subarea_scenario_gates.json` — D3 per-member gates.
- `bridge/smo_ap_bridge/data/world_scenarios.json` — per-kingdom scenario IDs (gitignored).
- `bridge/smo_ap_bridge/data/shine_map.json` — `progress_bit_flag` / `is_grand` /
  `main_scenario_no` per moon (gitignored, **never commit**).

Sheet→our-name mapping is clean: only **2** name-casing nits (see §4). 774/774 moons resolve.

## 1. Headline finding

Our gating is **correct on the late tiers and wrong in the middle**:

- ✅ **Moon-rock / "after defeating Bowser in Moon" / Peach-toad tiers all match.** Every
  spreadsheet "after opening this kingdom's Moon Rock" and "after defeating Bowser in the
  Moon Kingdom" moon resolves to `{<Kingdom>Peace()}` (or a re-arrival peace predicate) in
  our data, which is exactly the moon-rock peace-gate + World-Traveling-Peach auto-start
  systems Devon described. No action needed on those ~250 moons beyond spot-checks.
- ✅ **"Available from the start" matches** for ~all 221 free moons (2 exceptions, §3).
- ❌ **Intermediate intra-kingdom STORY tiers leak to FREE.** The compiler models each
  kingdom as a **3-band** scheme — `free` / one `{canReachLocation(<grand>)}` mid-anchor /
  `{<Kingdom>Peace()}` — but several kingdoms have **4–5 real story scenarios**. Any band
  that sits *between* the single mid-anchor and the two ends falls through every branch and
  ships `requires: ""`. This is the same class of bug as the Cascade no-op (a story-gated
  moon that logic thinks is free in sphere 0), just intra-kingdom instead of at the leave-wall.

**Root cause in code:** `compile_moon_logic.py::build_mid_story_anchors` anchors on a single
`is_grand` moon per kingdom. Kingdoms whose pre-clear progression has more than one story
moon (Luncheon, Sand, Wooded, Metro, Snow) leave the un-anchored band ungated. See the
per-kingdom scenario map in [§6](#6-appendix--in-game-scenario-ids-per-kingdom).

## 2. P1 — genuine under-gates (fix these)

These are non-skilled-jump, non-complex-state moons that the spreadsheet gates behind an
in-kingdom story event but we currently ship FREE. Listed with the prescribed predicate.

### 2a. Luncheon — "Under the Cheese Rocks" band (BIGGEST gap)

Luncheon has 5 story moons (Broodals → **Under the Cheese Rocks** → Big Pot Dive In →
Climb Cascading Magma → Cookatiel). We anchor only **Big Pot Dive In** (mid) and
**Cookatiel** (peace). The entire `main_scenario_no=1` "Under the Cheese Rocks" band is FREE,
even though the later Big-Pot band IS gated — an inverted/inconsistent gate.

FREE today, should gate on **`{canReachLocation(Luncheon: Under the Cheese Rocks)}`** (new
anchor) — or fold into the Big-Pot anchor as a conservative floor:

```
Under the Cheese Rocks · Surrounded by Tall Mountains · Light the Lantern on the Small Island
Golden Turnip Recipe 3 · Beneath the Rolling Vegetables · All the Cracks Are Fixed
Taking Notes: Swimming in Magma · Magma Narrow Path · Crossing to the Magma
Spinning Athletics End Goal · Taking Notes: Spinning Athletics
Excavate 'n' Search the Cheese Rocks · Climb the Cheese Rocks
```

(Exclude the `main_scenario_no=0` Broodals-band moons and the 13 SKILLED_FREE Luncheon moons
in §5 — those are correctly free.)

### 2b. Snow — post-race band

The race "**The Bound Bowl Grand Prix**" is Snow's clear event; everything after it lives in
post-race subareas. We gate most with `{SnowPeace()}` but these 5 leaked to FREE:

```
Dashing Over Cold Water!   →  {SnowPeace()}
Dashing Above and Beyond!  →  {SnowPeace()}
Jump 'n' Swim in the Freezing Water  →  {SnowPeace()}
Freezing Water Near the Ceiling      →  {SnowPeace()}
Blowing and Sliding        →  {SnowPeace()}
```

### 2c. Wooded — "Flower Thieves of Sky Garden" band

We have the `{canReachLocation(Wooded: Flower Thieves of Sky Garden)}` anchor and apply it to
most of the band, but these 3 leaked to FREE (the rest of the leak list is SKILLED_FREE, §5):

```
Behind the Rock Wall    →  {canReachLocation(Wooded: Flower Thieves of Sky Garden)}
Elevator Escalation     →  {canReachLocation(Wooded: Flower Thieves of Sky Garden)}
Elevator Blind Spot     →  {canReachLocation(Wooded: Flower Thieves of Sky Garden)}
```

### 2d. Metro — "Pest Problem" / festival band

Anchor `{canReachLocation(Metro: New Donk City's Pest Problem)}` exists and covers the band,
but two crowd/festival moons leaked to FREE:

```
Pushing Through the Crowd  →  {canReachLocation(Metro: New Donk City's Pest Problem)}
High Over the Crowd        →  {canReachLocation(Metro: New Donk City's Pest Problem)}
```

(`A Traditional Festival!` itself is the festival multi — it ships FREE; it's the band's own
clear-ish moon, low harm, but for consistency anchor it on Pest Problem too.)

## 3. P2 — possible over-gate (investigate)

Two Sand moons the spreadsheet marks "Available from the start" carry a `{SandPeace()}` gate:

```
Sand: Jaxi Driver         => ({SandPeace()} or (|Bullet Bill| and |Progressive Ground Pound:2| and |Wall Slide|))
Sand: Jaxi Stunt Driving  => ({SandPeace()} or (|Bullet Bill| and |Progressive Ground Pound:2| and |Wall Slide|))
```

These are the Jaxi desert-ride moons, reachable from arrival (Jaxi is captured near the start).
Check their `progress_bit_flag` / subarea assignment in `compile_moon_logic.py` — the
`{SandPeace()}` term is likely a mis-tiered scenario bit. Over-gating is low-harm (it just
makes the moon required later than vanilla) but it contradicts ground truth and should be a
quick fix. `The Treasure of Jaxi Ruins` (same subarea) is correctly capture-gated only — use
it as the reference.

## 4. Data nits — name casing (silent gate misses)

The spreadsheet and our location names disagree in case for 2 moons. If the
`subarea_scenario_gates.json` **key** doesn't byte-match the `locations.json` `name`, the
gate silently does not apply (entrance-shuffle ON path). Verify both resolve to the exact
name in `locations.json`:

- `Metro: Vaulting up a High-Rise` (sheet) vs `Metro: Vaulting Up a High-Rise`
  (subarea_scenario_gates key). Confirm which casing `locations.json` ships and that the gate
  key matches it.
- `Sand: Round-the-World Tourist` — sheet name didn't resolve directly; confirm the
  `locations.json` name. (Cross-kingdom tourist moon; see §5 cross-kingdom note.)

## 5. Intentional-free — document, no action

These are FREE-on-purpose and should stay free for minimal-accessibility logic. Listed so a
future pass doesn't "fix" them back into over-gates:

- **Cascade early story tier** ("after Our First Power Moon" / "after Multi Moon Atop the
  Falls"): free because **Broode's Chain Chomp is a fixed starter** — the deliberate §11
  decision in [scenario-logic-revisit-june-20.md](scenario-logic-revisit-june-20.md). The
  bit-≥2 Cascade moons are correctly `{CascadeDeparture()}` (= `KingdomMoons(Cascade,5)`).
- **23 SKILLED_FREE moons** the spreadsheet itself marks *"intended after X but can be
  obtained from the start using skilled jumps."* All ship FREE — correct, since they're
  physically reachable from arrival. (Wooded: Back Way Up the Mountain, Over the Cliff's Edge,
  Cracked Nut on a Crumbling Tower, The Nut that Grew on the Tall Fence, Nut Planted in the
  Tower, Stretching Your Legs, Flower Road Run, Flower Road Reach. Luncheon: Atop the Jutting
  Crag, Is This an Ingredient Too?!, Atop a Column in a Row, Island of Salt Floating in the
  Lava, Overlooking a Bunch of Ingredients, Golden Turnip Recipe 1 & 2, Shopping in Mount
  Volbono, Luncheon Kingdom Slots, A Strong Simmer, An Extreme Simmer, Magma Swamp: Floating
  and Sinking, Corner of the Magma Swamp, Fork Flickin' to the Summit, Fork Flickin' Detour.)
  Optional future "hard logic" could gate these; out of scope now.
- **Sand pyramid-state-toggle moons** (Overlooking the Desert Town, Secret of the Inverted
  Mural, On the Statue's Tail, Hidden Room in the Inverted Pyramid, From a Crate in the Ruins,
  On the Lone Pillar, Herding Sheep in the Dunes, Walking the Desert!, On Top of the Stone
  Archway): spreadsheet text is "available from the start, *not* available while the pyramid
  floats, available again after The Hole in the Desert." Because they're reachable in the
  **initial** state, FREE is correct for minimal accessibility.

## 6. P3 — lower priority / verify (likely fine, document the call)

- **Bowser's linear castle story** (Infiltrate → Smart Bombing → Big Broodal bands, ~23 moons
  FREE; only the post-Showdown band is `{BowserPeace()}`). Defensible: the castle is linear
  but fully traversable once you're in the kingdom (parent `KingdomMoons` gate controls
  entry), so revisiting reaches all overworld moons. Confirm no Bowser's-internal **capture**
  needed to clear the castle is locked behind one of these moons; if clean, leave as-is and
  note the decision.
- **Dark Side Yoshi fruit-feast chains** — `Fruit Feast Under Siege` needs `Yoshi Under
  Siege` first (likewise Sinking Island, Magma Swamp). Genuine intra dependency, but Dark Side
  is post-goal, so low harm. Gate the three "Fruit Feast" moons on their paired Yoshi moon if
  tightening.
- **Mushroom chains** — Yoshi's Second Helping/All Filled Up, Picture Match: A Stellar Mario,
  Mushroom Master Cup, and the two `Peach in the Moon Kingdom`-gated moons. Within the free
  goal kingdom; low harm. The post-win-Peach-gated ones (`Hat-and-Seek: Mushroom Kingdom`,
  `Princess Peach, Home Again!`) sit at/after the goal boundary anyway.
- **Cap "after powering up the Odyssey in Cascade"** (11 moons FREE) — fine: Cap is
  effectively a free starting region and these moons are de-facto gated by their **capture/
  ability** requirements (Frog, poison-tide, push-block) under capturesanity/abilitysanity.
- **Cloud: Picture Match: A Stellar Goomba!** — FREE today; spreadsheet wants rock + the basic
  Goomba picture first. Should be `{CloudPeace()}` AND
  `{canReachLocation(Cloud: Picture Match: Basically a Goomba)}`. Cloud is late/post-game-ish;
  low harm but cheap to correct.
- **Moon-kingdom rock band** (Center of the Galaxy, Edge of the Galaxy, Navigating Giant
  Swings, A Swing on Top of a Swing) FREE — these sit past the "leave Moon = win" boundary, so
  irrelevant to the current goal (see [[moon-kingdom-layers-and-cave-gate]]). Revisit only if a
  post-festival goal is added.
- **Cross-kingdom "Secret Path to X" + Tourist + Round-the-World moons** — the spreadsheet
  ties these to *other* kingdoms' story moons (and they're reached via shuffled/landing doors).
  Most ship FREE. These are entrance-shuffle-sensitive; audit separately against the entrance
  map, not the in-kingdom scenario layer. Out of scope for this scenario-bit pass.

## 7. Recommended compiler change

In `compile_moon_logic.py::build_mid_story_anchors`, stop anchoring on a single grand moon.
Emit a gate for **every pre-clear story band**, keyed on that band's story moon
(`main_scenario_no`), so a kingdom with N pre-clear story scenarios produces N nested
`{canReachLocation(<story moon of band k>)}` floors instead of one. The story-moon per band is
exactly the `main_scenario_no → shine_id` map in §8. This closes 2a–2d in one structural fix
rather than per-moon patches, and is robust to the spreadsheet's finer granularity (e.g.
Luncheon's 5 bands vs the 4 scenario bits).

Keep the `{<Kingdom>Peace()}` band and the Cascade `{CascadeDeparture()}` special-case as-is.

## 8. Verification checklist (romfs machine only)

> ⚠ Never run `compile_moon_logic.py` without `shine_map.json` + `world_scenarios.json`
> present — it degrades to rock-only and wipes the compiled gates (CLAUDE.md).

1. Edit `compile_moon_logic.py` (§7) and/or patch the §2 moons + §3 Sand Jaxi.
2. Extend `tests/test_scenario_gating.py` with the §2 band cases (Luncheon Cheese-Rocks band
   gated; Snow post-race → SnowPeace; Wooded/Metro band leaks closed) and a §3 Jaxi guard.
3. `python scripts/compile_moon_logic.py` — confirm the Luncheon Cheese-Rocks band now carries
   a gate and the §2 FREE-leaks drop to 0.
4. `python scripts/sync_shine_table.py` — `// Count:` unchanged (names already match).
5. `python scripts/install_apworld.py`
6. `python vendor/Archipelago/Generate.py` — re-roll a representative sweep at
   `accessibility: full`, entrance-shuffle ON and OFF; no FillError.
7. Spot-check in-game: a Luncheon Cheese-Rocks moon is not reachable before clearing the
   cheese rocks.

## 9. Appendix — in-game scenario IDs per kingdom

`world_scenarios.json` gives each kingdom's scenario metadata; `shine_map.json`'s
`main_scenario_no` (the kingdom's internal story counter, 0-indexed) pins each story/grand
moon to its scenario. This is the table to line up against the spreadsheet's "Available after
collecting X" column. (`GRAND` = `is_grand` multi-moon that advances the main story.)

| Kingdom | scenario_num | clear | moon_rock | after_ending | Story moons (`main_scenario_no` → moon) |
|---|--:|--:|--:|--:|---|
| Cap | 6 | 2 | 4 | 3 | *(no story-flagged moons; post-Topper moons ride the Cascade Odyssey)* |
| Cascade | 7 | 7 | 4 | 3 | 0 Our First Power Moon · 1 **Multi Moon Atop the Falls** |
| Sand | 7 | 3 | 5 | 4 | 0 Atop the Highest Tower · 1 Moon Shards in the Sand · 2 **Showdown on the Inverted Pyramid** · 3 **The Hole in the Desert** |
| Lake | 6 | 2 | 4 | 3 | 0 **Broodals Over the Lake** |
| Wooded | 7 | 3 | 5 | 4 | 0 Road to Sky Garden · 1 **Flower Thieves of Sky Garden** · 2 Path to the Secret Flower Field · 3 **Defend the Secret Flower Field!** |
| Cloud | 4 | 2 | 4 | 3 | *(no story-flagged moons)* |
| Lost | 6 | 2 | 4 | 3 | *(no story-flagged moons)* |
| Metro | 11 | 4 | 8 | 5 | 1 **New Donk City's Pest Problem** · 3 Drummer/Guitarist/Bassist/Trumpeter on Board! · 4 Powering Up the Station · 7 **A Traditional Festival!** |
| Snow | 6 | 2 | 4 | 3 | 0 Icicle/Ice-Wall/Gusty/Snowy-Mountain Barrier · 1 **The Bound Bowl Grand Prix** |
| Seaside | 6 | 2 | 4 | 3 | 0 Stone-Pillar/Lighthouse/Hot-Spring/Above-the-Canyon Seal · 1 **The Glass Is Half Full!** |
| Luncheon | 10 | 3 | 8 | 7 | 0 The Broodals Are After Some Cookin' · 1 Under the Cheese Rocks · 2 **Big Pot on the Volcano: Dive In!** · 3 Climb Up the Cascading Magma · 4 **Cookatiel Showdown!** |
| Ruined | 4 | 2 | 4 | 3 | 0 **Battle with the Lord of Lightning!** |
| Bowser's | 6 | 2 | 4 | 3 | 0 Infiltrate Bowser's Castle! · 1 Smart Bombing · 2 Big Broodal Battle · 3 **Showdown at Bowser's Castle** |
| Moon | 5 | 2 | 3 | 2 | *(no story-flagged moons; arrival vs post-Bowser split is by bit)* |
| Mushroom | 5 | 1 | 9 | 2 | *(no story-flagged moons; boss-rematch moons by bit)* |
| Dark Side | 2 | 2 | 9 | 2 | 0 **Arrival at Rabbit Ridge!** |

Notes:
- `clear`/`moon_rock`/`after_ending` are **1-indexed** scenario IDs from `world_scenarios.json`;
  `main_scenario_no` above is **0-indexed**. They line up for most kingdoms (Sand clear=3 ↔ The
  Hole at no=3) except **Cascade**, whose `clear=7` is its *last* scenario while its story moon
  is at no=1 — the documented Cascade quirk (its post-advance moons gate on
  `{CascadeDeparture()}`, not peace).
- Kingdoms with **no story-flagged moons** (Cap, Cloud, Lost, Moon, Mushroom) have their
  layering entirely in the `progress_bit_flag` bitmask, not the `main_scenario_no` counter —
  the compiler bands those purely by min-set-bit. (Per-bit moon counts available from
  `shine_map.json` if a finer breakdown is needed.)

## 10. Authored bit-flag (spreadsheet-derived, IP-clean) — `docs/authored-scenario-gates.json`

Generated a per-moon gating table **purely from the spreadsheet** (no romfs
`progress_bit_flag`). It's a parallel, authored source of truth we control — usable to
cross-check `compile_moon_logic.py`'s romfs-derived output, or eventually to *replace* the
romfs bit as the gating input. 774 moons, each tagged with a `kind` and, where relevant,
`anchor` / `band` / `gate`:

| `kind` | count | meaning → compiled gate |
|---|--:|---|
| `start` | 221 | from the start → no gate |
| `start_skilled` | 23 | "intended later, skilled-jump from start" → no gate (logic floor) |
| `story` | 227 | after an in-kingdom story moon (`anchor`, `band`) → `{canReachLocation(anchor)}` |
| `peace` | 196 | after this kingdom's Moon Rock / clear → `{<Kingdom>Peace()}` |
| `moonclear` | 55 | after defeating Bowser in Moon → auto via moon-rock peace-gate |
| `this_bowser` | 13 | Moon Kingdom, after its own Bowser → bit-split |
| `odyssey_cascade` | 11 | post-Topper Cap → de-facto capture-gated |
| `peach` | 8 | Peach-toad → auto at peace (World-Traveling Peach) |
| `cross_story` | 7 | deterministic cross-kingdom chain (Tourist / Round-the-World) → `{canReachLocation(other)}` |
| `fork_secret_path` | 7 | **fork-order-dependent painting warp — see §11** |
| `cross_secret_path` | 3 | deterministic painting warp (single host) → `{canReachLocation(host story moon)}` |
| `complex` | 3 | multi-state Sand pyramid-toggle moons → keep free (§5) |

`band` is the kingdom-internal scenario index (from §9's `main_scenario_no`, +1 = the scenario
the moon *appears* in). The §2 under-gates are exactly the `story`-kind moons whose compiled
`requires` is currently `""`.

## 11. Fork-dependent painting warps — the "secret path" exceptions

Ten moons are reached through a one-way hidden **painting** in another kingdom. Seven of them
are **fork-order-dependent**: *which* kingdom hosts the painting (and when it appears) depends
on a choice the player makes on the fly at the Lake/Wooded or Snow/Seaside forks. Today their
`region`/`requires` bake in **one** fork order — e.g. `Cascade: Secret Path to Fossil Falls!`
is filed under region `Snow Kingdom`, which is simply wrong for a Seaside-first player.

The three painting warps with a **single fixed host** (`Metro: …New Donk City!` ← Sand pyramid,
`Bowser's: …Bowser's Castle!` ← post-Moon, `Mushroom: …Peach's Castle!` ← Luncheon cheese
rocks) are deterministic and gate normally — no special handling.

### The 7 fork moons and their order-independent gate

The key fact: **both branches of each fork are always completed before the player can
progress** (both Lake+Wooded before Cloud; both Snow+Seaside before Luncheon). So an
order-independent gate exists for every fork moon — pick the predicate that is true *only when
the moon is reachable in **every** consistent order* (drop any disjunct whose prerequisite a
wrong-order player could satisfy early):

| Moon | Spreadsheet branches | Order-independent gate |
|---|---|---|
| Cascade: Secret Path to Fossil Falls! | Snow GrandPrix / Seaside Glass | `({SnowPeace()} or {SeasidePeace()})` |
| Lake: Secret Path to Lake Lamode! | Snow / Seaside / Metro-Pest | `({SnowPeace()} or {SeasidePeace()})` |
| Wooded: Secret Path to the Steam Gardens! | Snow / Seaside / Metro-Pest | `({SnowPeace()} or {SeasidePeace()})` |
| Sand: Secret Path to Tostarena! | Lake-start / Wooded Flower Thieves | `{canReachLocation(Wooded: Flower Thieves of Sky Garden)}` |
| Luncheon: Secret Path to Mount Volbono! | Lake-start / Wooded Flower Thieves | `{canReachLocation(Wooded: Flower Thieves of Sky Garden)}` |
| Snow: Secret Path to Shiveria! | Mushroom-start / post-Moon | `{MoonPeace()}` |
| Seaside: Secret Path to Bubblaine! | Mushroom-start / post-Moon | `{MoonPeace()}` |

(For a *parallel* fork like Snow/Seaside the OR is safe: whichever clears **first** is the one
hosting the painting. For a *sequential* "from start of X" branch the loose disjunct is dropped
and we rely on the later branch — e.g. Tostarena keys on Flower Thieves, conservative but
never stranding for a Lake-first player, who also clears Wooded.)

### Recommendation — better than removing them from the pool

Removing the 7 moons from the location pool works, but throws away 7 checks. Preferred:

1. **Re-gate** each fork moon with its order-independent predicate above (and keep the existing
   movement-ability terms ANDed on). Re-file `region` to a region reachable at that gate so the
   parent-region check doesn't contradict it.
2. **Mark them progression-excluded** (`junk_only` / local-only) as belt-and-braces: the
   disjunction gates are correct, but progression-excluding them guarantees no fill can strand a
   seed even if a gate is slightly mis-tuned. They still exist as collectable checks (filler/
   traps), so nothing is lost.
3. **Pre-emptively exclude the paintings from any future entrance-shuffle pool.** They are
   *not* in `entrance_stages.json` today (so current entrance shuffle is unaffected), but a
   future any-to-any randomizer (see [[entrance-from-parent-fix-deferred]]) must never grab a
   one-way, fork-dependent painting — add the 7 host paintings to `entrance_exclusions.json`
   when that work happens.

Net: keep all 10 secret-path checks, gate the 7 fork ones deterministically, and progression-
exclude the 7 so non-determinism can never break a seed. Only fully remove them if you'd rather
not carry the `junk_only` complexity.
