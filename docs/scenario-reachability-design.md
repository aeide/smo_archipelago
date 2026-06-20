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
- **Cascade — DEFERRED (the remaining follow-up).** Cascade was intentionally left
  OUT of mid_story: its `clear_main_scenario=7` is its *last* scenario (`after_ending=3`
  earlier), so its bit layers don't form a clean advancer chain, and routing its ~19
  post-first-visit moons to `{CascadePeace()}` starved the early fill spheres enough to
  fail generation on some seeds (FillError: Crouch/Ground Pound/Cascade Power Moons
  unplaceable). Its first advance (Multi Moon Atop the Falls) is mandatory-early and
  player-controlled, so leaving those moons free is safe. A dedicated Cascade pass —
  deriving its scenario split from observed bit layers + the after-ending revisit, and
  re-checking fill capacity — is the next step.

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

- **Cap (leave-to-access).** Cap has no `*Peace()` and its moons need "having left
  Cap once." In the linear chain that's "Cascade reachable." Gate Cap's
  `first_visit`-but-bit≥1 moons on `canReachLocation(<first Cascade moon>)` or a
  dedicated `CapDeparture()` predicate. Cloud/Lost similarly have no peace gate.
- **Cascade anomaly.** `clear_main_scenario=7` is Cascade's *last* scenario, with
  `after_ending=3` earlier — don't treat Cascade's `clear` as a generic peace bit.
  Special-case Cascade: `post_peace` = `{CascadePeace()}` (Multi Moon Atop the
  Falls) as today; derive its `mid_story`/`post_peace` split from the observed bit
  layers, not from `clear_main_scenario`.
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
