# Handoff — implement scenario reachability gating (coarse first)

Paste the section below as the opening prompt for the next session.

---

## Task

Implement **scenario-based moon reachability gating** in the build-time logic
compiler, per the design in [docs/scenario-reachability-design.md](scenario-reachability-design.md)
(data model: [docs/scenario-gating-logic-design.md](scenario-gating-logic-design.md)).

**Devon's decision: ship the COARSE tier first, then fine-tune `mid_story` later.**
Do NOT build the full per-scenario anchor map this pass. Build the coarse split,
validate it, commit, and leave `mid_story` anchoring as a documented follow-up.

## What "coarse" means (exactly what to build)

Classify every non-junk moon into the three tiers from design §2.2, but collapse
`mid_story` into the free tier for now:

| tier | how to detect | gate fragment to AND in |
|---|---|---|
| `post_peace` | `is_moon_rock` **OR** `min_scenario >= peace_bit` | `{<Kingdom>Peace()}` (existing) |
| everything else (`first_visit` + `mid_story`) | otherwise | *(none — moveset/kingdom/subarea gates only, unchanged)* |

- `min_scenario` = lowest set bit of `progress_bit_flag`.
- `peace_bit` = `clear_main_scenario - 1` from `world_scenarios.json`.
- This **generalizes the existing rock-only `{Peace()}` rule to all post-peace
  moons** — that's the whole coarse win. Rock moons already get the peace gate via
  `MOON_ROCK_PEACE_GATES`; fold the two so a rock moon is gated once, not twice.

**Special cases that MUST be honored even in coarse (design §3):**
- **Cascade**: do NOT use `clear_main_scenario=7` as the peace bit (it's Cascade's
  *last* scenario; `after_ending=3`). Keep Cascade's `post_peace` = `{CascadePeace()}`
  exactly as today, and derive its post-peace set from observed bit layers, not from
  `clear`. Simplest safe coarse behavior: leave Cascade on its current rock-only
  gate and don't add new post_peace gates there this pass.
- **Sentinels**: `*_scenario >= scenario_num` means "never" (Mushroom/Dark/Darker
  have `moon_rock_scenario=9`, no rocks) — no peace gate added.
- **Cap / Cloud / Lost** have no `*Peace()` predicate — coarse tier adds NO new gate
  for them (their leave-to-access gating is a `mid_story`/departure concern, deferred).
- **junk_only** locations stay requirement-free.

## Where it plugs in

`scripts/compile_moon_logic.py` (run after `import_moon_requirements.py`):
1. Load `shine_map.json` + `world_scenarios.json` from the client data dir
   (`apworld/smo_archipelago/client/data/` — Devon's machine has both; the
   extractor already produced them this session).
2. Per kingdom, compute `peace_bit` and `first_playable_bit` (= min set bit across
   the kingdom's moons; needed so Cap's bit-1 floor isn't mistaken for mid-story).
3. Join each location to its `shine_map` record **by name** → `progress_bit_flag` /
   `is_moon_rock`; compute `min_scenario` + coarse class.
4. Extend `gates_for()` to append `{<Kingdom>Peace()}` for the `post_peace` class,
   folding with the existing `MOON_ROCK_PEACE_GATES` so there's no double gate.
5. Re-run `compile_moon_logic.py` → committed `locations.json`.

## IP / build rules (do not violate)

- `shine_map.json` / `world_scenarios.json` are **read at build time only**; the
  compiler emits only boolean `requires` fragments (item names + `{Peace()}` calls)
  into committed `locations.json`. **No Nintendo IP ships.** Confirm the `git diff`
  of `locations.json` contains no new English moon-name lists beyond what's already
  there.
- Do NOT commit `shine_map.json`, `world_scenarios.json` (still gitignored), or any
  romfs-derived table. Never `git add -f` SMO content.
- Use Read/Write/Edit/Grep for file truth; the Linux shell serves STALE/truncated
  files. Run pytest / `compile_moon_logic.py` / `install_apworld.py` / Generate on
  **Windows PowerShell**.
- After editing `data/locations.json`: this is an apworld change → rebuild the zip
  with `python scripts/install_apworld.py` before Generate. (No switch-mod rebuild
  needed — logic is gen-side only.)

## Validation (design §5 — do before declaring done)

- **No over-gating**: diff the count of free (moveset-only) moons before/after. The
  `first_visit` majority must stay free, or fill tightens needlessly.
- **post_peace correctness**: spot-check that newly-gated moons are genuinely
  post-peace (Sand/Metro/Wooded), and that Cascade was not broken by the `clear=7`
  trap.
- Run `pytest apworld/smo_archipelago/tests/` (the extraction tests already cover
  the new fields; add a focused test if `compile_moon_logic.py` gains a unit-testable
  helper).
- Then `install_apworld.py` + `Generate.py` and confirm a seed generates (fill
  doesn't deadlock from over-gating).

## Explicit follow-up (the "fine-tune" half — NOT this pass)

Once coarse is committed and validated, the `mid_story` tier (design §2.3, §3):
- Build per-kingdom `{scenario_index → anchor location name}` from
  `is_grand`/`main_scenario_no`; gate `mid_story` moons on
  `canReachLocation(<anchor of min_scenario>)`.
- Add `CapDeparture()` (Cloud/Lost equivalents) to `hooks/Rules.py` for the
  leave-to-access moons.
- Confirm `min_scenario` sufficiency for narrow-mask moons in-game.
- Verify interaction with `multi_moon_shuffle` (anchors are MM-shuffle locations —
  `canReachLocation(anchor)` is location- not item-reachability, so it should hold).

## Pointers

- Design: [docs/scenario-reachability-design.md](scenario-reachability-design.md) §2 (model), §4 (impl sketch), §6 (the answered open questions).
- Data model + confirmed indexing rule: [docs/scenario-gating-logic-design.md](scenario-gating-logic-design.md) §6.
- Existing gate code: `scripts/compile_moon_logic.py` (`gates_for`, `MOON_ROCK_PEACE_GATES`, `KINGDOM_GATES`, `SUBAREA_GATES`); predicates in `apworld/smo_archipelago/hooks/Rules.py` (`*Peace()`, `canReachLocation`).
- Scratch probes (re-runnable, IP-safe): `scripts/_probe_*.py`.
