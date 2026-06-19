# Scenario-gating logic design

How per-moon and per-subarea availability is gated by kingdom story progression,
and how to turn the romfs data into AP reachability rules. This is the design
note behind the "Scenario >= N / MoonRockBroken / WorldPeace" question — the
gating is fully machine-extractable; nothing here needs hand-authoring per moon.

> IP note: the gating model is built from BYML **field names + scenario numbers**
> (functional, safe). The generated tables that join these to English moon names
> stay gitignored exactly like `shine_map.json` / `shine_table.h`. Do not paste
> moon-name lists into this doc.

## 1. The data sources

| Source | Grain | Gives us |
|---|---|---|
| `SystemData/ShineInfo.szs` → `ShineList_<HomeStage>.byml` | per-moon (775) | `ProgressBitFlag`, `MainScenarioNo`, `IsMoonRock`, `IsGrand`, `IsAchievement` |
| `SystemData/WorldList.szs` → `WorldList.byml` / `WorldListFromDb.byml` | per-kingdom (17) | `ScenarioNum`, `ClearMainScenario`, `MoonRockScenario`, `AfterEndingScenario`, `MainQuestInfo` |
| `StageData/<Stage>Map.szs` (BYML = **array of scenario layers**) | per-placement | warp/door/object gating: `ScenarioNo`, `FixScenarioNo`, `ScenarioNoLv1/Lv2`, `OnCondition`, `ProhibitCondision`, `IsAfterClearOnly`, `IsKillGameClear`, `QuestNo` |

`ShineInfo` + `WorldList` answer **moon** reachability. `StageData` placement
fields answer **subarea / entrance / object** reachability.

## 2. The per-moon model (validated)

A kingdom is in exactly one **scenario** (`0 .. ScenarioNum-1`) at any time.
Each moon carries `ProgressBitFlag`, a bitmask over scenarios:

> **A moon is placed/collectable in scenario `S` iff `(ProgressBitFlag >> S) & 1`.**
> (0-indexed, LSB = scenario 0.) It is a **set** of scenarios, not a `>=` threshold.

`MainScenarioNo` = the story scenario this moon *anchors* (grand/story moons that
advance the kingdom); `-1` for the ~735 ordinary moons.

### Validated against Cascade ground truth (`WaterfallWorldHomeStage`)

(names omitted per IP — the join was checked in-session against documented availability)

- The grand story moon (`IsGrand`, `MainScenarioNo=1`) → flag `1` = bit 0 only →
  present **only in scenario 0** (first-visit state). ✓
- The documented "available before the grand moon" moons → flag `79` =
  bits `{0,1,2,3,6}` → present from arrival onward. They all carry **bit 0**. ✓
- The Chain-Chomp-area moons → flag `126` = bits `{1..6}`, **no bit 0** →
  absent on first arrival, appear after the first story advance. ✓
- Moon-rock moons (`IsMoonRock`) and the post-peace moon-pipe moons → flag `8` =
  bit 3 only → the post-peace revisit scenario. ✓

The non-contiguous masks (e.g. `44` = `{2,3,5}`, skipping 4) confirm this is a
precomputed **per-scenario placement membership**, mirroring the stage byml being
a literal array of scenario layers (Cascade home = 15 layers).

## 3. Scenario number → semantics (per kingdom)

`ProgressBitFlag` bits are raw scenario indices; `WorldList.byml` resolves the
ones that matter to AP gates, per kingdom:

| WorldList field | AP meaning |
|---|---|
| `ClearMainScenario` | **WorldPeace** — kingdom story beaten |
| `MoonRockScenario` | **MoonRockBroken** — rock available |
| `AfterEndingScenario` | post-credits free-roam |
| `ScenarioNum` | scenario count (mask width) |

So "MoonRockBroken" for a kingdom = "the moon's bit at `MoonRockScenario` is set"
(and these moons also have `IsMoonRock=true`, a redundant cross-check).

## 4. From masks to AP reachability

The data gives *which scenarios a moon lives in*. The logic layer supplies the
other half: **which scenarios the player can reach given AP progress.**

Define, per kingdom, a monotonic progression of reachable scenarios driven by AP
items / story anchors:

- **First visit** → scenario `0` reachable.
- Collecting the kingdom's `MainScenarioNo` anchor(s) advances the reachable
  scenario (this is the existing multi-moon / story plumbing).
- **WorldPeace** (`ClearMainScenario`) reached → the post-peace revisit scenario
  (`AfterEndingScenario`) becomes reachable. Moon-pipe / cloud moons unlock here.
- **MoonRockBroken** (`MoonRockScenario`) → moon-rock moons unlock (gate this on
  the existing `MoonRockHook` peace-gate condition, not raw scenario).

A moon is **logically reachable** iff its `ProgressBitFlag` intersects the set of
**reachable scenarios** (plus the usual ability/capture/entrance requirements).

### The one nuance to get right

Because the flag is a *set*, a moon present **only** in an early scenario
(narrow low-bit masks — e.g. bit-0-only) is the case to model deliberately: in
vanilla SMO uncollected moons are re-presented on later visits, but our AP rules
shouldn't *assume* a narrow-mask moon is always collectable. For the common
"always" masks (bit 0 set + a wide tail) it's trivially reachable from first
visit. Lock the exact reachable-scenario progression per kingdom against 2–3
kingdoms beyond Cascade before building rules on the narrow-mask minority.

## 5. Subareas / entrances

Subarea + door availability is **not** in `ShineInfo` — it's on the warp/door
placement objects in `StageData/<Stage>Map.szs`, which is itself scenario-layered.
Relevant placement fields:

- `ScenarioNo` / `FixScenarioNo` — scenario binding for the placement.
- `ScenarioNoLv1` / `ScenarioNoLv2` (+ `StageNameLv1/Lv2`, `StartPosLv1/Lv2`) —
  the multi-version entrance pattern (e.g. a door whose destination changes by
  scenario, or the moon-rock variant of an entrance).
- `IsAfterClearOnly` — **WorldPeace gate as a boolean** (cleaner than computing it
  from `ClearMainScenario`).
- `OnCondition` / `ProhibitCondision` / `QuestNo` — quest/condition gates.
- `IsKillGameClear` — present pre-clear, removed post-clear.

This is the data behind "Sand has subareas that unlock through the story" — each
such subarea entrance carries a `ScenarioNo` / `IsAfterClearOnly` we can read.

## 6. Extraction work

Done in `scripts/extract_shine_map.py`:

1. **DONE** — `shine_map.json` records now carry `progress_bit_flag`,
   `main_scenario_no`, `is_moon_rock`, `is_grand` per moon (added to `RawShine`
   / `ResolvedShine` / `walk_shine_lists` / `write_outputs`). All 775 moons
   populate; `progress_bit_flag` is never 0; 40 story anchors, 134 rocks,
   22 grand. Stays gitignored (it's joined with English names).
2. **DONE** — `extract_world_scenarios()` emits `world_scenarios.json` next to
   `shine_map.json` (`--world-out` overrides). 17 kingdoms keyed by the apworld
   display name (`Cap`..`Darker Side`), each with `scenario_num`,
   `clear_main_scenario`, `moon_rock_scenario`, `after_ending_scenario`,
   `home_stage`, `world_name`. One alias bridges WorldList's
   `BossRaidWorldHomeStage` → `AttackWorldHomeStage` (Ruined). Tests in
   `tests/test_shine_map_extraction.py`.
3. **TODO (later, subareas)** — a placement pass over `StageData/*Map.szs`
   collecting entrance gating fields keyed by stage + warp id.

### CONFIRMED indexing rule (validated across all 17 kingdoms)

- **`progress_bit_flag` bit `S` (0-indexed) ⇔ moon present in kingdom scenario `S`**,
  for `S` in `[0, scenario_num)`. `scenario_num` equals the bit width in every
  kingdom (Cap 6→max bit 5, Cascade 7→6, Metro 11→10, Darker Side 2→1, …).
- **The `world_scenarios.json` numbers are 1-indexed**, so each maps to bit
  `(number − 1)`. Moon-rock moons sit exactly at bit `(moon_rock_scenario − 1)` in
  every kingdom that has rocks (Cap 4→bit 3, Sand 5→bit 4, Luncheon 8→bit 7,
  Moon 3→bit 2…), and persist into higher layers where applicable (Metro).
- **A `*_scenario` value ≥ `scenario_num` is a "never"/N-A sentinel** — Mushroom,
  Dark Side, Darker Side report `moon_rock_scenario=9` and have zero rock moons.

So: `is_present_in_scenario(moon, S) = (progress_bit_flag >> S) & 1`;
`moon_rock_bit(kingdom) = moon_rock_scenario - 1`;
`peace_bit(kingdom) = clear_main_scenario - 1`.

**Two anomalies (data-confirmed, match game behavior):**
- **Cap has no bit 0** — its moons don't exist until you first leave; scenario 0 is
  the pre-departure arrival. Cap moons start at bit 1.
- **Cascade's `clear_main_scenario=7`** is its *last* scenario with `after_ending=3`
  earlier — Cascade is the Odyssey-acquisition kingdom; don't use its `clear` value
  as a generic "peace" gate. The per-moon bit placement model still holds for it.

### Open decision for the logic phase (IP boundary)

Rules.py keys locations by **English moon name** (`locations.json`). To gate a moon
by its `progress_bit_flag`, logic needs a name → gating-fields map — but that map
*is* `shine_map.json` content (IP, gitignored). Options to resolve before building:
- **(A)** Generate a committed table keyed by **functional** `(stage_name,
  object_id)` → `{progress_bit_flag, main_scenario_no}` (numbers + functional ids,
  no English names — same IP category as `items.json`), plus have Rules join it via
  a name→(stage,obj) link. The catch: that link is itself shine_map-shaped.
- **(B)** Keep gating data runtime-only (client/switch already require the user's
  dump) and gate in the **client/switch** layer rather than AP generation logic.
- **(C)** Hand-derive a small committed per-location scenario tag only for the moons
  whose gating actually changes reachability (the narrow-mask + post-peace minority),
  leaving the "always available" majority ungated.

`world_scenarios.json` (numbers + functional names only) is IP-safe and *could* be
committed for Rules.py regardless of which option wins; it's gitignored for now
pending that call.

## 7. Scratch probes (this analysis)

Untracked, IP-safe (field names + counts only; any name join is session-only):
`scripts/_probe_shine_scenario.py`, `_probe_scenario_meaning.py`,
`_probe_bitflag_decode.py`. Re-runnable against `.romfs-cache/`.
