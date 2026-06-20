# Logic + entrance status (consolidated)

Single current-state doc for the two areas whose history was spread across a pile
of handoff/session-log docs (now deleted). Supersedes: `p7-step4-handoff.md`,
`p7-step4-morning-handoff.md`, `p7-session-log.md`, `scenario-reachability-handoff.md`,
`scenario-reachability-cascade-handoff.md`. Design rationale still lives in the
design docs cited below; this file is the "what is true now" index.

Last updated 2026-06-19.

## 1. Scenario reachability gating — SHIPPED (all three tiers)

Build-time logic compiler `scripts/compile_moon_logic.py` emits boolean `requires`
fragments into committed `data/locations.json`. Design + per-tier detail:
[scenario-reachability-design.md](scenario-reachability-design.md); data model:
[scenario-gating-logic-design.md](scenario-gating-logic-design.md).

| tier | detection | gate | status |
|---|---|---|---|
| `first_visit` | `min_scenario == first_playable_bit` | none (moveset/kingdom/subarea only) | n/a |
| `post_peace` | `is_moon_rock` OR `min_scenario >= peace_bit` | `{<Kingdom>Peace()}` (`build_post_peace_names`) | **SHIPPED** |
| `mid_story` | `first_playable_bit < min_scenario < peace_bit` | `{canReachLocation(<grand advancer>)}` (`build_mid_story_anchors`) | **SHIPPED** |
| Cascade (special) | non-rock, `min_scenario` in `[1,3]` | `{CascadePeace()}` (`build_cascade_anchors`) | **SHIPPED** |

- Inputs `shine_map.json` / `world_scenarios.json` are gitignored Nintendo-IP, read at
  BUILD TIME ONLY. Compiler emits only functional fragments; no names ship. Absent →
  degrades to rock-only peace gating.
- The Cascade FillError was resolved by making **Broode's Chain Chomp** a fixed starter
  (`hooks/World.py` `FIXED_STARTER_CAPTURES`), which makes `{CascadePeace()}` cheap.
- Tests: `tests/test_scenario_gating.py` (pure helpers, no IP).

## 2. Entrance shuffle (P7) — LIVE + validated in-game

`kEntranceRemapApply = true` in `switch-mod/src/hooks/EntranceShuffleHook.cpp`; the
apply-mode walk passed end-to-end 2026-06-19. Coupled-bijection return handling means
no runtime origin tracking (return target is precomputed PC-side). Design rationale:
[p7-step4-return-design.md](p7-step4-return-design.md); spike + exclusion-list
validation: [p7-entrance-shuffle-spike.md](p7-entrance-shuffle-spike.md); in-game
results: [devon-p7-entrance-testing-results.md](devon-p7-entrance-testing-results.md).

- apworld option `entrance_shuffle` (default OFF). Bijection rolled in
  `hooks/World.py before_create_regions`, shipped in slot_data as `entrance_map`.
- Open follow-ups (orthogonal, tracked in CLAUDE.md): Rules.py reachability for
  moon-pipe moons reached via a shuffled origin; the kingdom-order gate exposing
  not-yet-reachable kingdoms (only the BACKSTOP enforces order); Costume Room /
  Sphynx Treasure Vault still merge multiple physical doors into one shuffle node
  (memory `entrance-from-parent-fix-deferred`).

## 3. Promoting the 213 omitted moons → AP locations (2026-06-19)

`data/moon_requirements.json` describes **775** SMO moons; the curated upstream pool
only exposed **562** as AP locations. The other **213** (Koopa Freerunning Cups,
"Peach in the X Kingdom", Hint Art, Hat-and-Seek, Taking Notes, Caught Hopping, Timer
Challenges, and ~140 plain overworld moons) are now added as AP checks, tagged into
opt-out cluster categories. `data/locations.json` is now **818** locations.

Done by `scripts/add_missing_moon_locations.py` (committed-data-only, idempotent):
- Derives each AP name `<ShortKingdom>: <suffix>` via the importer's prefix /
  subarea→kingdom maps; back-fills `location_name` into `moon_requirements.json`.
- Appends `locations.json` entries `category=[<Kingdom> Kingdom, <cluster>]`
  (+ `post-metro` where applicable). **No `progression` flag** — that flag is the
  hand-audited 38-moon Talkatoo% scenario-advancer set (`tests/test_progression_moons.py`),
  which these regular moons are NOT part of.
- Grows each kingdom's `<Kingdom> Kingdom Power Moon` item count by the number added.
- New cluster toggles (all `DefaultOnToggle`): `include_cup_moons`,
  `include_peach_moons`, `include_taking_notes_moons`, `include_timer_challenge_moons`,
  `include_hat_and_seek_moons`, `include_caught_hopping_moons`, `include_extra_moons`
  (+ reuse of existing `include_hint_art_moons` / `include_tourist_moons`). Categories
  in `data/categories.json`; options in `hooks/Options.py`.
- Per-kingdom `*MoonCount` Range ceilings (`range_end`/`default`) grown by the same
  delta so the new moons aren't trimmed back to filler.

Per-kingdom additions: Cap +18, Cascade +15, Sand +21, Lake +14, Wooded +20, Cloud +5,
Lost +10, Metro +20, Snow +18, Seaside +17, Luncheon +13, Ruined +4, Bowser's +20,
Moon +18 (= 213).

### Logic coverage — do the 213 inherit ALL prior logic?

Yes, once `compile_moon_logic.py` runs. The compiler applies, per moon:
`OR(methods) AND kingdom-gate AND subarea-gate AND post_peace/mid_story scenario-gate`.
For the 213:
- **movement/capture** — from each moon's `methods` in `moon_requirements.json` (present). ✓
- **kingdom gates** (Metro/Bowser's = Spark pylon, Lake) — by name prefix. ✓
- **subarea entrance gates** (Sewers→Manhole, Narrow Valley, …) — keyed off
  `subareas.json` `location_names`. The importer was **re-run 2026-06-19** so all 16
  new subarea moons are now listed there (was the one real gap). ✓
- **peace / scenario gates** — from `shine_map.json` / `world_scenarios.json`, joined by
  the moon's `<Kingdom>: <name>`. ✓ on the romfs machine (see below).
- **Inherent caveat (unchanged from existing moons):** Cap/Cloud/Lost/Moon have no
  `*Peace()` predicate, so their post-peace moons (e.g. "Peach in the Cap Kingdom",
  Moon-Kingdom post-game moons) get no peace gate — same treatment the existing moons in
  those kingdoms already receive. Moon moons are filler items, so this can't FillError.

### ⚠ MANDATORY follow-up on the machine WITH the gitignored romfs data

The 213 new entries ship with `requires: ""`. **Do NOT run `compile_moon_logic.py`
without `shine_map.json` + `world_scenarios.json` present** — it degrades peace/scenario
gating to rock-only and would WIPE the scenario gates already compiled into the existing
562 moons. With the romfs data present:

```powershell
# import was already re-run this session; re-run only if SMO Requirements.xlsx changed:
# python scripts\import_moon_requirements.py
python scripts\compile_moon_logic.py     # fills requires + peace/scenario gates for all 775
python scripts\sync_shine_table.py        # joins names against shine_map.json — VERIFY the
                                          # printed "// Count:" grew by ~213 (a name that does
                                          # not byte-match shine_map yields NO row → the Switch
                                          # cannot award that moon in-game)
python scripts\install_apworld.py
python vendor\Archipelago\Generate.py     # fill-test (watch for FillError)
```

The name-match is the one unverified link: `moon_requirements.json` names came from
`SMO Requirements.xlsx`, not from `shine_map.json`. `sync_shine_table.py`'s count +
any unmatched-name report is the verification gate. Fix mismatches one name at a time
(IP rule: align with the MSBT individually, never bulk-paste).
