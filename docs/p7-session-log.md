# P7 Entrance Shuffle — Session Log

Bloat-free tracking doc for multi-session P7 work. Update completed items on
each session; keep the Pending queue ordered by dependency.

---

## Status as of 2026-06-18 (session 3, Steps 1+2 complete)

**Phase**: Switch-mod logger (Step 3 of 4). Steps 1+2 are done; Steps 3+4 require a switch-mod build+deploy cycle (do on Windows with Ryujinx running).

---

## Completed

- **Pre-work analysis**: Read CLAUDE.md, plan-v2-vision.md §P7, p7-entrance-shuffle-spike.md.
  Pool confirmed = 119 subareas (134 after data fixes minus 15 actually excluded from subareas.json).
- **subareas.json data fixes** (all done, tests passing):
  - `"Costume Room"` → split into `"Costume Room (Sand)"`, `"(Wooded)"`, `"(Seaside)"`.
  - `"Sphynx Treasure Vault"` → split into `"(Sand)"`, `"(Seaside)"`.
  - `"Shiveria Town"` kingdom corrected: Seaside → Snow.
  - `"Class A Race"` kingdom corrected: Seaside → Snow.
- **entrance_logic.py** created — gate constants, `compile_interior_requires`, `build_interior_requires_map`, `build_entrance_pool`, `build_moonpipe_subarea_set`, `evaluate_interior_requires`, `make_door_access_rule`.
- **`hooks/Options.py`** — `EntranceShuffle(Toggle)` added.
- **`hooks/World.py`** — full bijection roll + region-graph wiring:
  - `before_create_regions`: bijection + per-world caches (`world._entrance_map`, `_interior_requires`, `_entrance_shuffled_locs`, `_entrance_moonpipe`, `_entrance_pool`).
  - `after_create_regions`: creates `"{sub} Interior"` regions, moves locations, creates door Entrances with `make_door_access_rule` lambdas.
  - `after_set_rules`: overrides shuffled location rules with interior-only check (strips incorrect regionCheck from original kingdom).
  - `before_fill_slot_data`: emits `slot_data["entrance_map"]`.
- **Tests** — 20 tests in `test_entrance_shuffle.py`, all passing.
- **Generate.py** — verified generation succeeds with `entrance_shuffle: 1` (seed 1).
- **apworld zip** rebuilt: `python scripts/install_apworld.py` → 303.3 KiB, 65 files.

### Step 1 — apworld ✅ COMPLETE

### Step 2 — wire protocol ✅ COMPLETE

- `client/protocol.py`: `EntranceMapMsg` added (`t="entrance_map"`, `entries=[{"door":..., "interior":...}]`).
- `client/state.py`: `entrance_map: dict[str,str]`, `set_entrance_map`, `get_entrance_map`, `is_entrance_map_configured` on `BridgeState`.
- `client/switch_server.py`: `set_entrance_map`, `push_entrance_map`; called in `_run_post_hello_replay` after `push_kingdom_gates`.
- `client/context.py`: extracts `slot_data["entrance_map"]` on AP Connected → `set_entrance_map` + `push_entrance_map`.
- `tests/test_commands.py`: `_StubSwitch` updated with stub `set_entrance_map`/`push_entrance_map`.
- 557 tests passing (no new failures).

### Step 3 — Switch mod (logger)

- [x] Decomp read (`GameDataFunction.cpp` / `GameDataHolder.cpp` / `ChangeStageInfo.h`): chokepoint = `GameDataFunction::tryChangeNextStage(GameDataHolderWriter, const ChangeStageInfo*)`. Doors/areas/pipes/paintings reach it via `findAreaAndChangeNextStage` + direct triggers. **Fields not inlined** (ChangeStageInfo passed by pointer). See "Step 4 decomp facts" below.
- [x] Symbol verified HIT in `main.nso` dynsym: `_ZN16GameDataFunction18tryChangeNextStageE20GameDataHolderWriterPK15ChangeStageInfo` (`check_nso_symbols.py`).
- [x] Added to `SmoApSymbols.sym` + `HookSymbols.hpp` (`kGameDataFunctionTryChangeNextStage`).
- [x] `hooks/EntranceShuffleHook.cpp` — pure logger: logs `stage / id / isReturn / scenario / cur` per call. Registered in `main.cpp`.
- [x] Built + deployed to Ryujinx (subsdk9 + main.npdm, 2026-06-18).
- [x] **Walk #1 results in (Devon, 2026-06-18; logs in `devon-p7-entrance-testing-results.md` + raw SMOClient txt).** `tryChangeNextStage` is NOT the universal chokepoint — see Step 3.5 below.

### Step 3.5 — DEEPENED logger (chokepoint was too shallow)

**Walk #1 finding.** `GameDataFunction::tryChangeNextStage` fired for: Odyssey entry,
Crazy Cap Store entry (`SandWorldShopStage`/`bar1`), Rumbling Floor House pipe in+out
(`SandWorldVibrationStage`/`shindo`), Tostarena Slots entry (`SandWorldSlotStage`/`town`),
and the Push-Block-Peril EXIT pipe (`CapWorldHomeStage`/`PushBlockExStageEntDokan`). It did
**NOT** fire for: Push-Block-Peril **ENTRY**, Dinosaur Nest (in+out), Top-Hat Tower (in+out,
but that one is *excluded* so it doesn't matter). Both Push-Block-Peril and Dinosaur Nest
ARE in the shuffle pool, so this is a real coverage hole. Also: `isReturn` was **never 1**
in any line (even the pipe exit was a forward `isReturn=0` to the home stage), and empty
`stage='' id=''` lines fire ~1s after each moon collect (get-shine demo — Step 4 must skip
empty stages).

**Decomp (OdysseyDecomp, verified 2026-06-18).** All forward paths converge:
`tryChangeNextStage(writer,info)` → `writer->changeNextStage(info)` (operator-> →
`GameDataHolder`) → `GameDataHolder::changeNextStage(info, raceType)` (mIsStageChanging
guard) → `mPlayingFile->changeNextStage(info, raceType)` = **`GameDataFile::changeNextStage`**.
The direct-actor entries (Push-Block, Dinosaur) bypass the GameDataFunction free function and
call `writer->changeNextStage` directly, so they only show up at the `GameDataFile` level.
This is the same pattern as MoonGetHook (5 entry points → 1 chokepoint at GameDataFile).

- [x] Symbols verified HIT [rodata] in `.romfs-cache/main` (`check_nso_symbols.py`):
  `_ZN12GameDataFile15changeNextStageEPK15ChangeStageInfoi` + `_ZN12GameDataFile15returnPrevStageEv`.
  Added to `SmoApSymbols.sym` + `HookSymbols.hpp`.
- [x] `EntranceShuffleHook.cpp` now installs **3 loggers** with distinct prefixes:
  `[entrance:try]` (GameDataFunction path), `[entrance:file]` (GameDataFile::changeNextStage —
  universal forward commit), `[entrance:return]` (GameDataFile::returnPrevStage — exit path).
- [x] Built + deployed to Ryujinx (2026-06-18, `-DBRIDGE_HOST=192.168.4.100`).
- [x] **GATE CLEARED (Devon Walk #2, 2026-06-18 22:48–22:54).** Logs in
  `devon-p7-entrance-testing-results.md`. Results:
  1. **`[entrance:file]` is the universal forward chokepoint — CONFIRMED.** Push-Block-Peril ENTRY,
     Dinosaur Nest enter/exit, and Poison Tides enter/exit all now emit `[entrance:file]` (were
     silent in Walk #1). Hooking `GameDataFile::changeNextStage` alone catches every forward
     transition.
  2. **Exits are FORWARD transitions, not return-stack pops.** `returnPrevStage`/`[entrance:return]`
     fired for **no** door. Every door exit logged `[entrance:file]` with `stage`==parent home stage,
     `isReturn=0`, `scenario=-1`. ⇒ **Step 4 needs explicit exit handling — exits are not free, and
     `isReturn` cannot distinguish entry from exit.**
  3. Classification confirmed: the end-of-area PIPE (GameDataFunction path) logged BOTH `:try` and
     `:file`; plain doors (direct-actor path) logged ONLY `:file`.
  4. **Door `id` is constant per pair; direction is in the destination stage.** Entry and exit both
     carry the same `id` (e.g. `PushBlockExStageEnt`); entry dest = subarea stage, exit dest = parent
     stage. A transition is fully identified live by `(cur, id, dest)` at the chokepoint — no moon
     data / romfs needed to *recognize* one at runtime. `scenario`=1 on entry, `-1` on exit.
  - Observed (subarea → parent stage / entry id / subarea stage):
    Push Block Peril → CapWorldHomeStage / `PushBlockExStageEnt` / `PushBlockExStage`;
    Poison Tides → CapWorldHomeStage / `PoisonWaveExEnt` / `PoisonWaveExStage`;
    Dinosaur Nest → WaterfallWorldHomeStage / `RexPoppunEx` / `TrexPoppunExStage`.

**Step 4 implications.** `[entrance:file]` (`GameDataFile::changeNextStage`) is THE remap seam — the
logger trampoline becomes the rewrite point. Recognize an entrance by `(cur, id, dest)`; the static
shuffle map at gen time still needs a `(subarea → parent_stage, entry_id, subarea_stage)` table whose
`entry_id` is NOT in moon data — source is a romfs StageData (`ChangeStageList`) extraction (functional
identifiers, allowed) or a full log walk (impractical for 134 subareas). Decision pending.

### Step 4 — Switch mod (remap)

- [ ] Entry remap: on entry (`!mIsReturn`), look up `entrance_map[door]`, load remapped stage.
- [ ] Exit override: on exit (`mIsReturn`), load entry door's ORIGIN kingdom (no re-remap).
- [ ] Moon-rock guard: skip remap when `mChangeStageName == getCurrentStageName()` (same-stage scenario reload).
- [ ] SaveLoadHook: persist origin-door per subarea across save+quit.
- [ ] Build + deploy + in-game verification.

---

## Translation data observed in Walk #1 (informs the §1 translation-source decision)

`mChangeStageId` is a per-connection spawn/placement id, NOT derivable from moon data:

| Subarea (door) | target stage (`mChangeStageName`) | entrance id (`mChangeStageId`) | scenario |
|---|---|---|---|
| Crazy Cap Store (Sand) | `SandWorldShopStage` | `bar1` | -1 |
| Rumbling Floor House (Sand) | `SandWorldVibrationStage` | `shindo` | 1 |
| Tostarena Slots (Sand) | `SandWorldSlotStage` | `town` | 1 |
| (Odyssey, out of scope) | `HomeShipInsideStage` | `HomeEntrance` | -1 |
| Push-Block-Peril EXIT pipe | `CapWorldHomeStage` | `PushBlockExStageEntDokan` | -1 |

Note the Rumbling Floor House **exit** reused id `shindo` (same as entry) — the id is a
connection label shared between the two stages, and the **exit went FORWARD** to
`SandWorldHomeStage` (not via returnPrevStage). So Step 4 must collect, per interior
subarea, the `(stage, entry_id)` tuple to remap into it. The *stage* is derivable from moon
data (approach C); the *entry_id* (`bar1`/`shindo`/`town`/…) is **not** — it needs either a
log walk (A) or a romfs StageData entrance-list source. Decide before writing remap code.

## Step 4 decomp facts (load-bearing — verified 2026-06-18 from OdysseyDecomp)

- `tryChangeNextStage(writer, info)` → `writer->changeNextStage(info)` → `GameDataFile::changeNextStage`. The single entry chokepoint for door/area/pipe/painting transitions.
- **`returnPrevStage(writer)` → `writer->returnPrevStage()` — a SEPARATE path that does NOT go through `changeNextStage`.** If door-exits use this (not an `isReturn=1` ChangeStageInfo through `tryChangeNextStage`), Step 4's exit-override needs a second hook on `returnPrevStage` / `GameDataFile::returnPrevStage`. Step 3's walkthrough resolves which.
- The `With{StartRaceFlag,StartRaceYukimaru,DemoWorldWarp,WorldWarpHole,Closet,TimeBalloon}` variants call `writer->changeNextStage` directly, BYPASSING `tryChangeNextStage` (race/closet/world-warp — not subarea doors, so out of scope for remap).
- `ChangeStageInfo` (OdysseyHeaders `game/Sequence/ChangeStageInfo.h`, sizeof 0x278): `mChangeStageId`@0x00 (entrance/door name), `mChangeStageName`@0x98 (TARGET stage — this is what Step 4 rewrites), `mIsReturn`@0x1C8, `mScenarioNo`@0x1CC. Each `FixedSafeString<0x80>`=0x98 bytes; live cstr ptr at +0x08.
- For Step 4 remap, the ChangeStageInfo's strings are `FixedSafeString` (fixed 0x80 buffer) — rewrite via the buffer, not pointer swap, so the copy survives.

## Key invariants / load-bearing notes

- **`entrance_exclusions.json`** is the ground truth for excluded subareas. The 15 excluded are keyed by subarea name under their kingdom. Don't re-include.
- **Moon-pipe peace gate is a DOOR property** (the door requires peace; the interior does not). Strip peace gate from location["requires"]; put it on the Entrance access rule.
- **Cross-kingdom subareas** (Costume Room split, Sphynx Vault split, Picture Match (Goomba)): each physical instance gets its own entry in subareas.json with the CORRECT kingdom.
- **Moon-rock guard on Switch**: `ChangeStageInfo.mChangeStageName == getCurrentStageName()` + scenario change = moon-rock reload, NOT a subarea enter. NEVER remap.
- **`regionMap` is module-level global** — do NOT mutate it at runtime (concurrent-generation safety). Instead override location access rules in `after_set_rules` via `set_rule()`.
- **Shared `location_table`** — do NOT mutate location dicts' `"requires"` or `"region"` keys at generation-time. Store per-world state on `world._interior_requires` etc.

---

## Files touched / to-touch

| File | Purpose |
|------|---------|
| `apworld/smo_archipelago/data/subareas.json` | Data fixes (Costume Room, Sphynx, kingdoms) |
| `apworld/smo_archipelago/entrance_logic.py` | NEW: gate constants + compile helpers |
| `apworld/smo_archipelago/hooks/Options.py` | Add EntranceShuffle option |
| `apworld/smo_archipelago/hooks/World.py` | Core shuffle logic |
| `apworld/smo_archipelago/client/protocol.py` | EntranceMapMsg (Step 2) |
| `apworld/smo_archipelago/client/state.py` | entrance_map storage (Step 2) |
| `switch-mod/src/hooks/EntranceShuffleHook.cpp` | NEW: logger + remap (Steps 3-4) |
| `switch-mod/syms/game/SmoApSymbols.sym` | tryChangeNextStage symbol (Step 3) |
| `switch-mod/src/hooks/HookSymbols.hpp` | symbol constant (Step 3) |
| `apworld/smo_archipelago/tests/test_entrance_*.py` | Tests |
