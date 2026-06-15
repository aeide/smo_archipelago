# SMO Archipelago v2 Vision — Implementation Plan

Drafted 2026-06-12 from Devon's full feature brief. This is the successor plan to the original
M0–M7 plan. Each phase is sized for execution by Sonnet 4.6 (apworld/Python/data work) or
Opus 4.8 (switch-mod hooking/symbol work) in dedicated sessions. Read CLAUDE.md first in every
session; the invariants there (MoonGetHook chokepoint, pre-orig init ordering, three-layer hook
pattern) all apply to this work.


## Session log — 2026-06-14c (P4 ability enforcement — judge-gate spike, CODE COMPLETE)

Capture gate confirmed working end-to-end in-game (un-owned caps eject; Zipper moon
→ Zipper capturable). Started **P4 enforcement**. Devon decisions this session:
spike-first; pivoted the spike target from jumps to **judge-backed moves** after
discovering backflip/side-flip have NO dedicated judge class (they're branches
inside the jump state — deferred), whereas crouch/roll/ground-pound each have a
clean `PlayerJudge*::judge()`.

### Architecture (load-bearing for all of P4)
SMO gates a move by calling a `PlayerJudge*`'s `IJudge::judge() const` (returns
bool: "should this move start?"). Trampolining `judge()` and returning false when
the gating AP ability isn't owned cleanly suppresses the move — `judge()` is const
and side-effect-free (`update()` does the state work), so a forced-false is a clean
"not now". This is the canonical P4 enforcement point (M7 lesson: hook the decision).
Judge classes exist for: crouch (`PlayerJudgeStartSquat`), roll
(`PlayerJudgeStartRolling`), ground pound (`PlayerJudgeStartHipDrop`), ground spin,
hip-drop, etc. **No judge for backflip/side-flip/long-jump** — those need jump-state
work in a later pass (long jump has `exeLongJump`/`PlayerStateLongJump`; backflip/
side-flip are stick+crouch-context branches with no single symbol).

### Implemented this session (CODE COMPLETE, uncommitted; needs Devon build+test)
- **`ApState` reader (P4):** `abilityCount(name)` — lock-free seqlock read over the
  existing `ability_table` (the seqlock was added in P3-3b exactly for this).
  `abilityAtLeast(name, level)` = count>=level, returns true when
  `ability_gate_force_unlock` is set. Counts are monotonic so a torn read can only
  under-report a frame, never over-grant. (`ap/ApState.{hpp,cpp}`)
- **`ability_gate_force_unlock`** atomic on ApState, default **false** (gates active,
  so the spike is testable out of the box). Hook point for a future "unlock all"
  toggle; not yet wired to a UI/command (see safety net below).
- **`hooks/AbilityGateHook.cpp`** — three `judge()` trampolines:
  - Crouch ← `Progressive Crouch >= 1`  (`PlayerJudgeStartSquat`)
  - Roll   ← `Progressive Crouch >= 2`  (`PlayerJudgeStartRolling`)
  - Ground Pound ← `Progressive Ground Pound >= 1` (`PlayerJudgeStartHipDrop`)
  Each calls orig first; only suppresses when the move WOULD start. Throttled log on
  suppression. Installed from `main.cpp` (`installAbilityGateHooks`, after
  CaptureStartHook). Source glob picks up the new file on reconfigure.
- **Symbols** added to `syms/game/SmoApSymbols.sym` (mangled, Itanium ABI, no args):
  `_ZNK21PlayerJudgeStartSquat5judgeEv`, `_ZNK23PlayerJudgeStartRolling5judgeEv`,
  `_ZNK23PlayerJudgeStartHipDrop5judgeEv`. No `HookSymbols.hpp` constants needed
  (trampoline `installAtSym<...>` takes the literal mangled name).

### Devon: build + verify + test
1. **Judge symbols VERIFIED present (2026-06-14)** in `.romfs-cache/main` (SMO 1.0.0)
   via `python scripts/check_nso_symbols.py .romfs-cache/main _ZNK21PlayerJudgeStartSquat5judgeEv _ZNK23PlayerJudgeStartRolling5judgeEv _ZNK23PlayerJudgeStartHipDrop5judgeEv`
   → all three HIT (project's verifier; NOT llvm-nm, which isn't on PATH). No
   sail loadSymbols-abort risk. (If a FUTURE judge is inlined/missing, hook the caller
   `PlayerActorHakoniwa::exe*` instead.)
2. Rebuild + redeploy the switch-mod (same loop as the capture fixes).
3. **Test:** on a save WITHOUT Progressive Crouch / Progressive Ground Pound, confirm
   Mario can't crouch / roll / ground-pound; watch for `AbilityGate: suppressed …`.
   Then `/send <slot> Progressive Crouch` (×1 → crouch works; ×2 → roll works) and
   `/send <slot> Progressive Ground Pound` (→ ground pound works). Confirm a Cappy
   bubble pops on receipt (P3-3b tracking).
4. **Assumption to confirm:** `PlayerJudgeStartRolling` == the crouch-roll (not dive-
   roll). If it gates the wrong thing, the test will show it — easy to remap.

### Safety net
No interactive force-unlock wired yet, BUT the spike moves carry low brick risk
(none are strictly required to leave a kingdom) AND there's a zero-code escape hatch:
`/send <slot> <ability>` from the AP server console unlocks any blocked move
immediately (ability_state is a full-overwrite snapshot). Wiring
`ability_gate_force_unlock` to a `/`-command (client→Switch msg, mirrors coin_grant)
is a clean follow-up if we want a one-shot "unlock everything" during later, riskier
passes (jumps, dive).

### Next (after the spike validates)
- Remaining judge-backed moves: ground spin (Spin Throw?), wall catch, etc. — map
  each judge to its ability item.
- Cap throws (Up/Down/Spin Throw) — find their judge/input-routing.
- Jump-context moves (backflip/side-flip via `PlayerStateJump`; long jump via
  `exeLongJump`) — the hard subset, do last.
- Wire the force-unlock `/`-command before the jump passes (higher brick risk).

---

## Session log — 2026-06-14b (Cap-Kingdom Spark Pylon soft-lock — FIXED)

### Symptom
After the capture-gate fix above started working, the forced "ride the sparks up
to the Odyssey" pylon that leaves Cap Kingdom turned out to be a **real startHack
capture** (`ElectricWire`), not a scripted cinematic as an earlier note assumed.
With Spark Pylon randomized (not yet owned), the gate ejected Mario from it →
**soft-lock inside Cap Kingdom.**

### Fix (keeps Spark Pylon randomized — Devon's preference)
Stage-scoped exemption in `hooks/CaptureStartHook.cpp`: a Spark Pylon
(`ElectricWire`) is allowed free ONLY when the current stage is Cap Kingdom
(`CapWorldHomeStage`); every other Spark Pylon stays gated on the "Spark pylon"
AP item. Implementation:
- New `s_getCurrentStageName` (resolves `GameDataFunction::getCurrentStageName` —
  already in `SmoApSymbols.sym`/`HookSymbols.hpp`, already used by
  `game/OdysseyRescue.cpp`, so resolution is proven).
- `capIsExemptCapKingdomPylon(hack)` — true iff hack==`ElectricWire` AND
  `getCurrentStageName(GameDataHolderAccessor{holder})`==`CapWorldHomeStage`.
  **Fails closed** (no exemption) if the symbol is unresolved or the holder
  isn't cached, so it never weakens the gate elsewhere; during the forced-pylon
  sequence the holder is reliably cached.
- In the hook: `blocked = captureBlocked(name); if (blocked &&
  capIsExemptCapKingdomPylon(name)) blocked = false;`
- Corrected the stale "scripted cinematic" claim in `game/CaptureGate.cpp`'s
  `kBaselineHacks` comment.

Spark Pylon stays in the randomized pool (NOT added to `kBaselineHacks` /
precollect). Cap Kingdom holds no pylon-gated AP progression, so "free pylons in
Cap Kingdom" only ever means "can leave Cap Kingdom."

### Next steps (Devon, Windows)
- Rebuild + redeploy the switch-mod (same loop as the capture-table fix — both
  ride in the same `subsdk9`). Test: (1) un-owned T-Rex elsewhere still ejects;
  (2) the Cap-Kingdom exit pylon is captureable WITHOUT owning "Spark pylon";
  (3) once you have a kingdom past Cap, an un-owned Spark Pylon there still ejects.
- Watch the log for `getCurrentStageName resolved @ …` at boot and
  `… in Cap Kingdom — exempt from gate` when you grab the exit pylon.

---

## Session log — 2026-06-14 (capturesanity gate fail-open — ROOT-CAUSED + FIXED)

### Symptom
Capturesanity re-enabled (real `DefaultOnToggle`, gated path), switch-mod rebuilt
+ redeployed, yet capturing an un-owned T-Rex did NOT eject Mario. Reported as
"same functionality" after last session's `kBaselineHacks` change.

### Root cause (not the gate logic — the lookup table)
The deny path in `CaptureStartHook.cpp` → `CaptureGate::captureBlocked(name)` is
correct. The bug is the data it matches against. `captureBlocked` gets `name`
from `PlayerHackKeeper::getCurrentHackName()`, which returns the **SMO-internal
hack_name** (T-Rex = `"TRex"`, Goomba = `"Kuribo"`, …). It looks that up in
`capture_table.h::kCaptureHackNames`. But that header had been generated with an
**identity** hack-name mapping — `kCaptureHackNames` == `kCaptureNames` (apworld
display names: `"T-Rex"`, `"Goomba"`). So `captureBitFor("TRex")` found no match
→ returned `0xff` → `captureBlocked` returned `false` → **fail-open for 46 of 51
captures** (only Frog/Cactus/Tree/Manhole/Yoshi matched by coincidence). The
header's own line 3 said it: `Hack-name mapping: identity (capture_map.json absent`.

Why identity: `sync_capture_table.py` looked for `capture_map.json` ONLY at
`apworld/smo_archipelago/client/data/` (doesn't exist in this checkout). The real
extracted map lives at `%APPDATA%/SMOArchipelago/data/capture_map.json` (where the
setup wizard's extractor writes it — same place the runtime client loads it via
`client/setup_state.py::_resolve_map_path`). So the build-loop's plain
`python scripts/sync_capture_table.py` silently emitted the identity table. The
runtime client was fine (it found the %APPDATA% map), which is why owned captures
worked and only the *block* path was broken.

### Fixes applied this session
1. **Regenerated `switch-mod/src/ap/capture_table.h`** with correct SMO-internal
   hack names (sourced from `bridge/smo_ap_bridge/data/capture_map.json`, 52
   entries, + the 4 split-variant overrides). 51 captures, 46 diverged, 0 aliases.
   Written via the disk-truth Write tool (shell mount is stale — confirmed again:
   the shell even executed a truncated mirror of the edited script). **This file is
   gitignored IP — do NOT commit it.**
2. **`scripts/sync_capture_table.py`** now resolves `capture_map.json` from
   `%APPDATA%/SMOArchipelago/data/` (then XDG, then legacy `client/data/`) —
   mirroring the client — so a plain run on Windows finds the same map the client
   uses. Also applies `VARIANT_CAP_HACK_OVERRIDE` (the 4 split part-captures whose
   item names aren't capture_map keys) so they no longer fall through to identity.

### Next steps (Devon, Windows)
1. **Rebuild + redeploy the switch-mod** — `capture_table.h` is compiled in, so the
   regenerated table only takes effect after a rebuild:
   `python scripts/build_switchmod.py -DBRIDGE_HOST=<LAN IP>`, then copy
   `subsdk9`+`main.npdm` into `%APPDATA%\Ryujinx\mods\contents\0100000000010000\exefs\`.
2. **Test:** with capturesanity ON, capture an un-owned T-Rex → Mario should be
   yanked back out the moment the dive-in cinematic ends (forceKillHack + playSE_NG).
   Owned captures still work; the 4 split part-captures (Puzzle/Picture Match) now
   gate too.
3. **Parallel issue — ALSO FIXED 2026-06-14:** `sync_shine_table.py` had the IDENTICAL
   default-path bug → `shine_table.h` was an EMPTY STUB (it couldn't find `shine_map.json`),
   which silently no-ops Phase 2 pre-marking, the Talkatoo% block, and per-moon recolor
   (NOT the capture gate). Applied the same `%APPDATA%/SMOArchipelago/data/` resolution helper.
   I did NOT hand-regenerate `shine_table.h` (it's ~435 rows joined from `locations.json`, which
   the stale shell mount truncates — unsafe to build here). It regenerates correctly on Devon's
   next Windows build: the build loop already runs `python scripts/sync_shine_table.py`, which now
   finds the %APPDATA% shine_map (775 entries verified present). Confirm the regenerated
   `shine_table.h` has a non-zero `// Count:` line (stub says `0 moons`).

---

## Session log — 2026-06-13 (P1 verify + P3-3a data)

### Accomplished

**P1 verified in-game** — Cap moon → 100 coins, idempotent catch-up confirmed. Build/deploy
gotchas recorded in CLAUDE.md (Python 3.11+/`lz4 pyelftools mmh3`; Ryujinx mods path is
`%APPDATA%\Ryujinx\mods\...`, not `E:\Ryubin`). Fixed a `context.py` truncation committed by
`5736ece`; added 4 MoonRock scenario symbols to `HookSymbols.hpp` (committed in `a00743a`).

**P3 detailed plan written** — `docs/plan-p3-detail.md` (reviewed + approved by Devon).

**P3-3a data half COMPLETE** (apworld generates; 756 pass — only the pre-existing
`test_moon_rock_checks.py` failures remain, which are for a separate unimplemented feature).
Full breakdown in CLAUDE.md "P3 progress". In brief: +20 ability items (`Ability` category),
capture roster completed (4 part-variants split; +Broode's/Letter/Yoshi/`Spark pylon`/Bowser;
6 clones), +68 junk-only MK/Dark Side/Darker Side locations (names verbatim from shine_map),
new regions + categories, `_apply_junk_only_rules` (filler/trap only), festival drops updated,
`test_moon_requirements` junk_only exemption.

### Next session (P3-3b, Opus + smo-build)

1. Ability classification (`ItemKind.ABILITY`) + `ability_unlock` wire + `ApState::ability_unlocked`
   bitfield + Cappy + duplicate→coins. Abilities TRACKED only (enforcement is P4).
2. **Variant capture cap→hack override** — `capture_map` keys both Puzzle Parts as `"Puzzle Part"`
   (`GotogotonLake`/`GotogotonCity`) and both Picture Match Parts as `"Picture Match Part"`
   (`FukuwaraiFacePartsKuribo`/`FukuwaraiFacePartsMario`); add a committed override mapping the 4
   variant item names → hacks in the bridge cap→hack resolution. (Generation doesn't depend on it.)
3. Tests for the new pool (ability counts, split variants, clones, ID stability, junk_only never
   progression/useful).

---

## Session log — 2026-06-13

### Accomplished this session

**P1 Python side complete.**
- `client/protocol.py`: `CoinGrant` dataclass (`t="coin_grant"`, `total: int`).
- `client/state.py`: `compute_cap_coin_total()` — reads `moons_received_by_kingdom["Cap"] * 100`, thread-safe under `_lock`, clamped to ≥0. Multi-Moons worth 3 weight so a Cap Multi-Moon = 300 coins.
- `client/switch_server.py`: `push_coin_grant()` — no-op when total=0; idempotent (Switch high-water-marks `coins_applied` so re-sending same total = delta 0). Called from `_run_post_hello_replay` (after `push_kingdom_gates`) and from `context.py`'s `_process_received_items` when `cap_moon_received_this_batch` is True.
- `docs/wire-protocol.md`: `coin_grant` documented.
- `tests/test_coin_grant.py`: 25 tests — all passing.

**P1 Switch side complete. Committed as `be993cc`.**
- `ApProtocol.hpp/cpp`: `CoinGrant` struct + `parseCoinGrant()` + dispatch in `decode()`.
- `syms/game/SmoApSymbols.sym`: `_ZN16GameDataFunction7addCoinE20GameDataHolderWriteri` added (mangling derived from `addPayShine`'s identical `(GameDataHolderWriter, s32)` shape).
- `hooks/HookSymbols.hpp`: `kGameDataFunctionAddCoin` constant + doc comment.
- `ApState.hpp/cpp`: `pending_coin_grant_total` (atomic\<int\>), `coins_applied` high-water mark, `add_coin_fn` lazy pointer; `applyCoinGrant()` implemented — lazy `hk::ro::lookupSymbol` (same pattern as `addHackDictionary`); soft-fails with WARN if symbol absent; calls `addCoin(GameDataHolderWriter{holder}, delta)` on frame thread; guarded by `game_data_holder_cache` null check (defers until game is running).
- `ApClient.cpp`: `coin_grant` dispatch stores total into `pending_coin_grant_total`.
- `main.cpp`: `applyCoinGrant()` wired into per-frame loop after `flushPendingCaptureGrants`.
- `scripts/check_nso_symbols.py`: utility to LZ4-decompress NSO rodata and search mangled symbol strings; verified `addCoin` HIT in SMO 1.0.0 dynsym.

**P1 in-game test — partial (debugging in progress).**
- Ryujinx mod was disabled in Mod Manager — enabled it; confirmed mod now loads (`[smoap]` lines appear in Ryujinx log). Connection to bridge established.
- Collected "Sand: A Rumble from the Sandy Floor" (a Cap moon check). AP returned `Cap Kingdom Power Moon`. Switch logs show `[m6-outstanding] … +1` Cap balance change — so `add_received_item` is called and `moons_received_by_kingdom["Cap"]` became 1. But **no `[p1-coins]` log lines from the Switch** — `coin_grant` message was never received.
- Added logging to `push_coin_grant()` and the `cap_moon_received_this_batch` branch in `context.py` to pinpoint which side is failing.
- **Blocked on apworld reinstall**: running `install_apworld.py` from the Linux sandbox produced a zip with `smo_archipelago/` as the root package name instead of `meatballs/` (the zip stem that Archipelago expects). Archipelago threw `ModuleNotFoundError: No module named 'worlds.meatballs'` on restart. **Next session must fix the apworld reinstall and retest.**
  - Root cause: custom zip script used wrong arcname prefix. `install_apworld.py` handles the `smo_archipelago/ → meatballs/` rename internally; always use it (or replicate its arcname logic exactly: `arcname = f"meatballs/{f.relative_to(SRC)}"`). The `.pytest_cache` directory throws `PermissionError` on `stat()` in the Linux sandbox — `install_apworld.py` skips it via `SKIP_NAMES`; any custom script must also skip it.
  - The original 4 MB apworld was built with `--bundle-mod --bundle-scripts`; the Python-only bundle (no flags) is ~500 KB and is correct for quick debug cycles (switch-mod binary is already in Ryujinx's exefs mod folder, independent of the apworld zip).

### Next session priorities (week of 2026-06-16)

**Immediate (Sonnet): finish P1 in-game verification.**
1. Reinstall the apworld correctly: `python scripts/install_apworld.py` from Windows (or replicate its arcname logic with `meatballs/` prefix and skip `SKIP_NAMES`). Restart SMOClient.
2. Collect a Cap moon check and look for the new log lines:
   - Bridge: `[p1-coins] cap_moon_received_this_batch=True switch=True` then `[p1-coins] push_coin_grant: total=100` then `[p1-coins] coin_grant sent: total=100`.
   - Switch (forwarded): `[p1-coins] coin_grant total=100 queued for frame thread` then `[p1-coins] addCoin delta=100`.
3. If `cap_moon_received_this_batch=False`: check whether `classify_item` is returning OTHER for the item (data package not loaded yet, or `_item_categories` miss). If `total=0`: `moons_received_by_kingdom["Cap"]` wasn't incremented — check `add_received_item`'s `kind == "moon"` branch. If no Switch log: check `_active_conn()` / confirm Switch stayed connected during the async task.
4. Once confirmed working, remove the debug log lines and commit.

**Then: P3** (ability items + MK/DS locations) — the largest remaining apworld phase. Recommended for Opus.

---

## Session log — 2026-06-12

### Accomplished this session

**P0 complete.**
- `scripts/import_moon_requirements.py` written and run: parses the community-authored "Moon
  Ability Requirements" CSV (775 moons, 3-rows-per-moon format) into:
  - `data/moon_requirements.json` — 775 entries keyed by CSV name; 435/435 current
    locations matched; 340 unmatched (post-game/Mushroom/Dark Side, not yet in apworld).
    Fields: `location_name`, `captures`, `locked_default_capture`, `methods` 1–5 with
    normalized vocabulary.
  - `data/subareas.json` — 131 subareas with kingdom assignments and location-name lists.
    Seed for P7's entrance pool.
- Vocabulary normalized: jump height (`none/single/double/cap_return/backflip/gpj/triple/
  long_jump`), cap throws (`none/neutral/up/down/spin`), other-required (20 terms).
- One name override required: `"Inverted Pyramid: Upper Interior: Hidden Room in the
  Inverted Pyramid"` → `"Sand: Hidden Room in the Inverted Pyramid"`.
- 13 tests in `tests/test_moon_requirements.py` — all passing.
- CSV file (`Public SMO Randomizer Moon Ability Requirements - Moons.csv`) committed to
  repo root (Devon's authored work, safe to commit).

**P2 complete.**
- `hooks/Helpers.py`: `before_is_category_enabled` returns `False` for `"Capture"` —
  all `Capture: X` locations retired regardless of the capturesanity option.
- `hooks/Rules.py`: all 24 capturesanity guard branches removed; affected functions
  (`SandPeace`, `WoodedPeace`, `PostNightMetro`, `PostTrumpeter`, `MetroPeace`,
  `SnowPeace`, `SeasidePeace`, `SnowSeasidePeace`, `LuncheonPeace`, `BowserPeace`,
  all 14 `Regional*` functions, `Meat`, `UprootOrFireBro`, `Lighthouse`) now `return True`.
- `hooks/Options.py`: `Capturesanity` deprecated-in-place — docstring says "no effect",
  display_name is "Capturesanity (Deprecated)". Kept for YAML back-compat.
- `data/items.json`: Frog and Chain Chomp added (pool is now 44 Capture items).
- `hooks/World.py`: `FIXED_STARTER_CAPTURES = ("Frog", "Chain Chomp")` + 
  `_precollect_starting_captures()` added; `before_create_items_starting` precollects
  all 3 starters via `multiworld.push_precollected` before the festival-goal trim.
- `tests/test_starting_captures.py`: 13 new tests (data + source-parse) — all passing.
- `scripts/sync_capture_table.py` run successfully after session — `capture_table.h`
  updated with Frog + Chain Chomp.

**Deferred from P2 (Switch-mod side):**
- `CaptureStartHook.cpp` still emits capture checks — needs a smo-build session to stop
  that (low urgency: the checks go nowhere since `Capture: X` locations are retired).

### Next session priorities (week of 2026-06-16)

**P1 — Cap Kingdom moons → 100 coins** (recommended starting point):
- Python side is fully unblocked (no Switch required to write + test):
  - Add `CoinGrant` dataclass to `client/protocol.py`.
  - In `client/switch_server.py`: when a received item is `Cap Kingdom Power Moon`,
    accumulate a count in `BridgeState` and send `coin_grant` with a running balance
    (idempotent on HELLO replay — same M6-D rule as moons; OutstandingMsg pattern).
  - Wire-protocol.md: document the new message.
  - Tests: extend `tests/test_outstanding.py` or add `test_coin_grant.py`.
- Switch side needs **smo-symbol-discovery** skill to find `GameDataFunction::addCoin`
  (or equivalent coin-counter path); then a small `ApFrameBridge` / `MoonApply`-style
  applier. Start a dedicated smo-build session for this.

**Before next smo-build session:** verify in-game whether the first Spark Pylon out of
Cap Kingdom is a cutscene trigger or a real capture (affects whether Spark Pylon becomes
a 4th fixed starter in P2/P3).

**Open question from design decisions:** `Puzzle Part` and `Picture Match Part` — does
the second variant (Metro vs Lake, Mario vs Goomba) need its own item entry?

---

## Design decisions locked in with Devon (2026-06-12)

1. **Bound-item model for repurposed kingdoms (corrected 2026-06-12).** Each shuffled
   Mushroom Kingdom moon item is bound to ONE specific capture, and each shuffled Dark Side
   moon item to ONE specific ability — independent items, no unlock ordering or counters.
   The only ordered items are the three progressive chains Devon specified
   (UPDATED 2026-06-12 — this list supersedes earlier drafts):
   Progressive Jump (Double Jump→Triple Jump), Progressive Crouch (Crouch→Roll→Roll Boost),
   Progressive Ground Pound (Ground Pound→Dive). Everything else is unique.
   Backflip and Long Jump are unique items but logically ALSO require Crouch
   (`|Progressive Crouch:1|`) — a logic dependency, not chain membership. Ground Pound Jump
   likewise requires `|Progressive Ground Pound:1|`.
   Only unlock-bearing moons enter the AP item pool — no filler MK/DS moon items.
   Cap Kingdom Power Moon items grant 100 coins (they currently do nothing).
   **Clones:** Ground Pound and Wall Slide each get a second copy in the pool; receiving a
   copy of an already-unlocked ability converts to 100 coins in-game. Capture clones
   (specified 2026-06-12): **Bullet Bill, Sherm, Parabones, Banzai Bill, Bowser,
   Spark Pylon** — same duplicate→coins behavior. Note: if Spark Pylon and/or Bowser end up
   precollected this iteration (see starting kit), their clones are deferred until those
   captures are actually randomized.
2. **MK / Dark Side vanilla locations are junk-only checks.** Their in-game moons remain
   collectible checks with vanilla (post-game) gating, but are AP-`excluded`: filled only with
   filler/traps, never progression or useful items.
3. **Captures are no longer checks.** Capturesanity location checks are removed entirely.
   Capture *items* remain and are now funded by Mushroom Kingdom moon items.
4. **Starting kit**: single jump + neutral cap throw only, plus Frog, Chain Chomp, and 1
   random extra capture (all visible in the map-menu capture list from the start).
   Frog and Chain Chomp are therefore precollected items, not pool items.
   **Likely also given at start this iteration**: Spark Pylon and Bowser — both are
   extremely progression-critical; randomizing them properly is the ideal end state but is
   deferred until their gating is tested. Devon believes the first pylon out of Cap Kingdom
   is a cutscene trigger rather than a real capture; needs an in-game test (P2 checklist).
   Big Chain Chomp may also need to be a starter — Devon verifying.
5. **Logic difficulties** from the Moon Ability Requirements CSV: Intended (Method 1),
   Basic Tricks/Skips (≤M2), Intermediate (≤M3), Advanced (≤M5).
6. **Entrance shuffle**: every non-storyline subarea entrance shuffled in one pool;
   exits always return you to the door you entered through. Devon authors the exclusion list.

## Feasibility answers

- **Per-kingdom moon colors: yes.** `ShineAppearanceHook.cpp` already recolors moons by AP
  classification via a palette index that the client ships per-location in `ShineScoutsMsg`.
  Extending the palette from 5 entries to 5 + ~17 kingdom colors and having the client emit a
  kingdom index when a location holds *our own game's* moon item is a small, low-risk change.
  Non-SMO items keep the existing classification colors. (Purple-coin model swap is a separate,
  much harder model-replacement problem — correctly deferred.)
- **Logic references items directly** — no indirection. "needs Dive" compiles to
  `|Progressive Ground Pound:2|`; "needs Triple Jump" to `|Progressive Jump:2|`; "needs
  Roll Boost" to `|Progressive Crouch:3|`; "needs Backflip" to `|Backflip| and
  |Progressive Crouch:1|`; capture requirements to `|Gushen|` etc. Plain manual-AP
  `requires` syntax, simpler and more robust than any counter scheme.

## Item accounting (corrected per Devon 2026-06-12)

- **Ability items: 18 unlocks + 2 clones = 20.** Unique (11): Up Throw, Down Throw,
  Spin Throw, Backflip, Side Flip, Cap Bounce, Ground Pound Jump, Long Jump, Wall Slide,
  Ledge Grab, Climb. Chain steps (7): Progressive Jump ×2 (Double→Triple),
  Progressive Crouch ×3 (Crouch→Roll→Roll Boost), Progressive Ground Pound ×2
  (Ground Pound→Dive). Clones (2): one extra Wall Slide (duplicate→100 coins) and one extra
  Progressive Ground Pound. **Chain-clone nuance:** an extra Progressive Ground Pound copy
  advances the chain (2nd copy found = Dive) rather than duplicating Ground Pound itself —
  with 3 copies in the pool, GP is easier to find early and the 3rd copy converts to coins.
  If Devon wants GP cloned *without* easing Dive, the chain-vs-clone interaction needs a
  different design (decide in P3). These ARE the "Dark Side moon" items (each presented as
  a Dark Side moon bound to its ability/chain step).
- **Capture items: 52 total in-game.** All independent — no progression chains. Shuffled
  count = 52 minus starters (Frog, Chain Chomp, 1 random, likely Spark Pylon + Bowser this
  iteration, possibly Big Chain Chomp). Capture clones per decision #1, duplicate→100 coins.
- **items.json capture reconciliation (audited vs Devon's canonical 52-list, 2026-06-12).**
  HEAD items.json has 42 Capture entries. KEEP existing names — do NOT rename variants
  (`Ty-foo`, `Snow Cheep Cheep`, `Mini Rocket` stay; locations.json rules and the extracted
  capture_map.json key off them). Actions:
  - **Add to pool**: `Broode's Chain Chomp` (progression — required for Cascade world peace
    → moon rock; logic must make it reachable pre-Cascade-peace, so it lands very early
    sphere in practice), `Letter`, `Yoshi`.
  - **Add as items but likely precollected this iteration**: `Spark Pylon`, `Bowser`
    (and `Big Chain Chomp` pending Devon's verification).
  - **Do not add** (precollected starters, never pool items): `Frog`, `Chain Chomp`.
  - **Open question**: items.json has single `Puzzle Part` and `Picture Match Part` entries
    (count 1 each) where the canonical list has Lake/Metro and Goomba/Mario variants —
    verify during P2/P3 whether the second variant of each needs its own item.
  - After any items.json edit: re-run `scripts/sync_capture_table.py`.
- **No filler MK/DS moon items.** The ~128 vanilla Mushroom Kingdom + Dark Side in-game
  locations join as junk-only (`excluded`) checks with vanilla post-game gating; the item
  pool's remainder is ordinary AP filler/traps.

---

## Phase order and rationale

Dependencies force most of this order: P1–P3 are independent quick wins; P4 (ability items)
must exist before P6 (CSV logic referencing abilities); P6's region/subarea data comes from
P0; P7 (entrance shuffle) needs both P0's subarea inventory and P6's per-moon requirements.

### P0 — CSV ingestion & data foundation  *(COMPLETE 2026-06-12)*

Convert the spreadsheet into committed machine-readable data. The CSV is Devon's own authored
work (community-curated names, same lineage as locations.json) — safe to commit.

- `scripts/import_moon_requirements.py`: parse the 3-rows-per-moon blocks (row 1 jump height,
  row 2 cap throws, row 3 other requirements; columns E–I = Methods 1–5; col C = captures that
  work) → `apworld/smo_archipelago/data/moon_requirements.json`.
- Reconcile CSV names ("Cap Kingdom: Frog-Jumping Above the Fog", "Frog Pond: Searching the
  Frog Pond") against locations.json names ("Cap: …"). Emit an unmatched-names report; fix
  mismatches one at a time (never bulk-import from romfs sources).
- Extract the subarea inventory from CSV name prefixes ("Frog Pond:", "Poison Tides:",
  "Push Block Peril:" …) → `data/subareas.json` (subarea → kingdom, moons inside). This is the
  seed of P7's entrance pool.
- Normalize vocabulary: jump-height strings ("Backflip/Vault/Side Flip (496)"), cap-throw
  sets, "Other Required" terms (Capture, Dive, Wall Jump, Ledge Grab, …) into enums. Note
  "Locked behind Default Capture" sentinel.
- Tests: every current location has an entry; vocabulary is closed (no unknown strings).

### P1 — Cap Kingdom moons → 100 coins  *(✅ VERIFIED IN-GAME 2026-06-13)*

Smallest end-to-end slice of the "moon item with an effect" pattern that P3 reuses.

- apworld: nothing (item already exists as filler).
- Client: on receiving `Cap Kingdom Power Moon`, send a new wire msg (e.g. `coin_grant`,
  amount 100) — see `client/switch_server.py` + `protocol.py`; replay-on-HELLO must be
  idempotent (count-based, mirroring the Moon-skip rule from M6 phase D — coins, like moons,
  need an authoritative outstanding balance, not naive replay).
- Switch: handle in `ApFrameBridge`/`MoonApply`-style applier; needs a coin-add symbol
  (likely `GameDataFunction::addCoin` or the player's coin counter path) via the
  **smo-symbol-discovery** skill. Wire-protocol.md update.

### P2 — Remove capturesanity checks + starting captures  *(COMPLETE 2026-06-12)*

- apworld: retire `Capturesanity` location generation (option becomes deprecated/no-op or is
  removed from YAML template); capture *items* stay. Rules.py references to capturesanity
  (`SandPeace`, `WoodedPeace`, `PostNightMetro`, …) flip to always use capture-item logic
  once P3 lands — in this phase just keep them consistent.
- Starting inventory: precollect Frog + Chain Chomp + 1 seed-random capture in
  `hooks/World.py`; exclude all three from P3's capture sequence.
- Switch: `CaptureStartHook` stops emitting checks; `AddHackDictionaryHook`/`CaptureGate`
  already gate unlocks — confirm precollected captures arrive pre-HELLO-replay and appear in
  the map-menu capture list (addHackDictionary is exactly what controls that list).
- Tests: update `test_connect_gate.py`-adjacent suites; new test that 3 captures are
  precollected and never placed.

### P3 — Mushroom→captures, DarkSide→abilities, junk-only MK/DS checks  *(3a data ✅ + 3b client/wire ✅ 2026-06-13; 3b Switch C++ pending)*

- apworld: add MK (104) and Dark Side (24) moon locations as `excluded` junk-only checks
  with vanilla gating in regions.json. Items per the accounting section: 20 ability items
  (11 unique + 3 progressive chains + 2 clones), capture roster completed per the
  reconciliation list (add Broode's Chain Chomp/Letter/Yoshi + Spark Pylon/Bowser as
  items, keep existing variant names), capture clones added, starters precollected.
  No sequences, no slot_data ordering — items are self-describing.
- Client: capture items already flow to the Switch via the existing capture-unlock path;
  ability items get a new `ability_unlock` wire msg keyed by ability id. Duplicate handling:
  if the Switch (or client mirror) already has the unlock, grant 100 coins instead — reuses
  P1's coin-grant path. Idempotent on HELLO replay (OutstandingMsg-style balance, not raw
  replay — same M6-D rule; clones make naive replay actively wrong).
- Switch: `ApState::ability_unlocked[]` bitfield + wire handling. Display: Cappy speech
  bubble on unlock (CappyMessenger).
- Note: ability *enforcement* is P4; in this phase abilities are tracked but not yet gated,
  which keeps the build playable throughout.

### P4 — Ability gating on Switch  *(Opus 4.8 — the hard hooking phase)*

> **Canonical, living P4 plan + progress tracker: [docs/plan-p4-detail.md](plan-p4-detail.md).**
> It holds the full ability→hook mapping table, rollout order, the judge() architecture,
> risks, and a per-session log. Keep THAT file updated each P4 session; the notes below
> are the original high-level sketch and are superseded by it.

Gate Mario's moveset by `ApState::ability_unlocked`. This is symbol-discovery-heavy work in
`PlayerActorHakoniwa` / `PlayerJudge*` / `rs::` trigger land; expect the same pattern as the
Talkatoo% block: find the *judge* (decision) functions, not the action implementations, per
the M7 three-layer lesson (catch upstream of the visible state change).

- Likely targets (verify against OdysseyDecomp): `PlayerJudgeStartRolling`,
  `PlayerJudgeStartSquat` (crouch), spin/up/down-throw judges in `PlayerSpinCapAttack` /
  cap-throw input routing, wall-slide/ledge-grab/climb judges, dive trigger. Dive is chain
  step 2 after Ground Pound, so its prerequisite is automatic. Backflip, Long Jump
  (need Crouch) and Ground Pound Jump (needs Ground Pound) are unique items whose
  prerequisites are NOT automatic — both the in-game gate and the logic must AND them.
- Double/triple jump: likely a combo counter on the jump state — gating may mean clamping the
  combo index rather than blocking the jump. Ground-pound jump and cap bounce are
  composite moves; gate at their judge functions.
- Ship incrementally: one ability gate per commit, each behind a debug force-unlock toggle in
  the ImGui console, so a missed edge case never bricks a save.
- Risks: judges may not be single chokepoints (same caveat as `PlayerHackKeeper::startHack`
  in CLAUDE.md known-unknowns).
- Host-mod tests via **smo-host-tests** where logic is extractable; otherwise Ryujinx + the
  smoke-test script.

### P5 — Per-kingdom moon colors  *(Sonnet 4.6; small)*

- Client: when a scouted location's item is our own slot's moon item, emit kingdom palette
  index (5 + kingdom_id) instead of classification index in `ShineScoutsMsg` entries
  (`scout_cache.py` / `display.py` already classify; `maps.py` knows kingdoms).
- Switch: extend `kPaletteColors3D/Dot` in `ShineAppearanceHook.cpp` with the kingdom colors
  (Cap yellow, Cascade orange, Sand teal… match the in-game kingdom flag/coin colors).
- Wire-protocol.md: document the widened palette-index range (additive, fixed-buffer safe).

### P6 — Logic difficulty tiers  *(Sonnet 4.6 for the compiler, Opus 4.8 review pass; apworld-only)*

- New `LogicDifficulty` Choice option: `intended` (M1) / `basic_tricks` (≤M2) /
  `intermediate_tricks` (≤M3) / `advanced_tricks` (≤M5).
- Rules compiler: per moon, OR across allowed methods; each method ANDs (jump-height term →
  set of qualifying ability items, cap-throw term, other-required terms → ability/capture
  items directly, "Capture" → col-C capture list OR). Generate into the manual-AP
  `requires` strings or a generated Rules module — prefer generated data over 836 hand-written
  rules.
- Sphere-1 audit: with the bare kit (single jump, neutral throw, Frog, Chomp, +1 random),
  generation must verify enough reachable sphere-1 checks in Cascade at every difficulty;
  add a guard test like the randomize_kingdom_gates reachability test.
- Tests: fill succeeds at all 4 difficulties × capturesanity-replacement state × kingdom-gate
  randomization; spot-check known moons (e.g. a Method-3-only moon unreachable on `intended`).

### P7 — Entrance shuffle  *(Opus 4.8; the headline feature, last because it consumes P0+P6)*

- apworld: entrance pool = all subarea entrances minus Devon's storyline exclusion list
  (`data/entrance_exclusions.json` — Devon authors; Top-Hat Tower, Inverted Pyramid, etc.).
  Because every exit returns to the entry door, shuffle is a simple bijection
  door → subarea (no two-way pairing problem): subarea moons are reachable iff the door's
  kingdom/region is reachable AND the subarea's own requirements hold. Regions: door-regions
  from P0's `subareas.json`; reachability sweep like the kingdom-gates guard.
- slot_data → new `entrance_map` wire msg → `ApState` fixed-size table (respect the committed
  fixed-buffer wire patterns).
- Switch: hook the stage-change path (`GameDataHolder::changeNextStage` /
  `ChangeStageInfo` consumption — symbol discovery needed): on subarea entry, remap
  (stage, entrance-id) per table and record the origin; on subarea exit, override the return
  destination with the recorded origin. Persist origin across save-load within a subarea
  (SaveLoadHook surface) so save+quit inside a subarea doesn't strand Mario.
- Risks to investigate first (a short Opus spike before committing to design):
  cross-kingdom subarea loads (different kingdom's stage from another kingdom — likely fine,
  subareas are separate stages, but verify scenario/time-of-day state), multi-moon story
  subareas (excluded anyway), checkpoint-flag side effects, Talkatoo%/moon-rock interactions.
- This phase re-uses the M7 "lie to the game" three-layer pattern for any UI that previews
  destinations.

### P7 data — subarea ↔ capture ↔ ability correlation (extracted 2026-06-14f)

Generated from P0's `data/moon_requirements.json` (775 CSV moons; 435 matched to current
apworld locations) + `data/subareas.json` (131 subareas) by `outputs/analyze_v3.py`. Full
per-moon detail in `outputs/subarea_analysis.json`. **Universe = the 435 ability-mapped
moons** (excludes Multi-Moons, boss/festival locations, and the P3 junk MK/DS checks, which
carry no ability requirements). "Required ability" uses the **easiest method** per moon (the
method with the fewest non-baseline requirements); starting kit = single jump + neutral/no
cap throw + walk/capture.

**Method/throw semantics (load-bearing for the logic compiler — P6/P7):** a method's
`cap_throws` is the SET of throws that satisfy it; if it contains `neutral` or `none`, a
baseline throw works and NO motion-throw ability is required. Consequence: across all 131
subareas, **no subarea's easiest path strictly requires Up/Down/Spin Throw** — every
throw-flavored moon has a baseline-throw alternative. So gating the motion throws (P4) never
strands a subarea. (They appear as *options* constantly, but never as the sole path.)
Likewise `jump_height` `single`/`none` = baseline; only `double/triple/backflip/long_jump/
gpj/cap_return` are gated.

**(1) Overworld vs subarea moons per kingdom** (435 mapped moons; a moon is "subarea" iff its
location_name appears in a subarea's `location_names`, else "overworld"; a subarea moon is
counted under the subarea's assigned kingdom — see cross-kingdom caveat below):

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

**(2) Subareas gated by a capture** (≥1 member moon requires a capture). "ALL" = the capture
is required by *every* matched moon in the subarea → strongest "you need this capture to do
anything here" signal; a capture matching the subarea's theme/name is the de-facto entrance
key. **Frog and Chain Chomp are fixed starters (P2 precollect), so their subareas are always
open**; all other captures here are shuffled pool items and genuinely gate the subarea.

- Cap: **Frog Pond** → Frog *(starter → always open)* (ALL). **Poison Tides** → Gushen,
  Parabones, Paragoomba, Pokio (ALL) + Dino/Glydon/Shiverian.
- Cascade: **Dinosaur Nest** → Dino (ALL). **Nice Shots with Chain Chomps** → Chain Chomp
  *(starter → always open)* (ALL).
- Sand: **Bullet Bill Maze** → Bullet Bill, Frog, Gushen, Hammer Bro, Parabones, Paragoomba,
  Pokio, Shiverian, Uproot (ALL — every moon needs all of these across methods). **Inverted
  Pyramid** → Bullet Bill, Glydon, Gushen, Parabones, Paragoomba, Shiverian, Yoshi (ALL).
  **Underground Ruins** → Gushen (ALL) + 9 others. **Deepest Underground** → Glydon, Gushen,
  Parabones, Paragoomba, "Locked behind Default Capture".
- Wooded: **Sky Garden Tower** → Uproot (ALL). **Walking on Clouds** → Uproot (ALL).
  **Shards in the Fog** → Paragoomba (ALL). **Crowded Elevator** → Tank (ALL).
  **Secret Flower Field** → Frog/Gushen/Pokio/Tank/Uproot. **Deep Woods** →
  Bullet Bill/Coin Coffer/Dino/Hammer Bro/Tank. **Flower Road** → Goomba.
- Lost: **Crazy Cap Store (Lost)** → Pokio (ALL).
- Metro: **Shards Under Siege** → Tank (ALL). **Bullet Billding** → Bullet Bill.
- Snow: **Shiveria Town** → Dino/Frog/Glydon/Gushen/Parabones/Paragoomba/Shiverian/Yoshi
  (the town hub — 9 matched moons, many captures).
- Seaside: **Flying Through the Narrow Valley** → Gushen (ALL).
- Luncheon: **Narrow Magma Path** → Lava Bubble (ALL). **Simmering in the Kitchen** → Lava
  Bubble (ALL). **Luncheon Treasure Vault** → Fire Bro + Lava Bubble (ALL). **Shards in the
  Cheese Rocks** → Hammer Bro (ALL). **Fork-Flickin to the Summit** → Forks (ALL).
- Bowser's: **Spinning Tower** → Pokio (ALL).
- Moon: **Underground Caverns** → Bullet Bill.

**(3) Capture → # of subareas it unlocks** (which captures are most load-bearing for subarea
access; shuffled captures only, so logic should weight these):

Gushen 8 · Paragoomba 7 · Parabones 6 · Pokio 6 · Bullet Bill 6 · Glydon 5 · Frog 5* ·
Uproot 5 · Shiverian 4 · Dino 4 · Tank 4 · Yoshi 3 · Hammer Bro 3 · Lava Bubble 3 ·
Goomba 2 · Chain Chomp 1* · Coin Coffer 1 · Fire Bro 1 · Forks 1 ·
"Locked behind Default Capture" 1 *(data marker, not a real capture — flag for cleanup)*.
(*Frog/Chain Chomp are starters → their subareas are always reachable.*)

**(4) Abilities required within subareas** (corrected throw logic; count = # subareas whose
easiest path needs the ability). These are the P4/P6 gates that actually constrain subarea
completion:

| Ability | # subareas | Notes |
|---|--:|---|
| Long Jump | 22 | by far the most common gated requirement — P4 Long-Jump gate has the widest logic reach |
| Ground Pound (`ground_pound`) | 7 | |
| Ledge Grab (`ledge_grab`) | 5 | |
| Wall Jump (`wall_jump`) | 5 | distinct from Wall Slide — verify which AP item maps here |
| 2D Jump (`2d_jump`) | 4 | 8-bit-tube sections; may be inherent, not an AP item |
| Dive (`dive`) | 4 | = Progressive Ground Pound L2 |
| Outfit (`outfit`) | 4 | a required costume, NOT a moveset ability — handle separately |
| Backflip | 4 | |
| Crouch (`crouch`) | 3 | Progressive Crouch L1 |
| Climb (`climb`) | 3 | |
| Cap Bounce (`cap_return`) | 2 | |
| Ground Pound Jump | 2 | |
| Triple Jump | 1 | Shiveria Town |
| Jaxi / Scooter / damage_boost / other_kingdom_trigger | 1 each | situational; not core moveset |
| **Up/Down/Spin Throw** | **0 (as hard req)** | never the sole path — see throw semantics above |

**Caveats / data oddities to resolve before P6/P7 logic uses this:**
- **Cross-kingdom subareas** count under the kingdom you *enter* them from (subareas.json
  `kingdom`), even when the moon physically lives in another kingdom's stage. Examples folded
  into the counts: Costume Room (Sand) holds `Wooded: Exploring for Treasure` +
  `Seaside: A Relaxing Dance`; Sphynx Treasure Vault (Sand) holds
  `Seaside: The Sphynx's Underwater Vault`; Picture Match (Goomba) (Lake) holds a `Cloud:`
  moon. For entrance shuffle this is the correct grouping (the door is in the enter-kingdom),
  but a P5 moon-recolor keyed on *physical* kingdom would disagree.
- **"Locked behind Default Capture"** appears in `captures` for Deepest Underground — it's a
  sentinel, not a capture; the logic compiler should special-case or strip it.
- `outfit` and `2d_jump` are listed as `other_required` but aren't moveset abilities (a
  costume gate / an inherent 8-bit mechanic) — don't map them to AP ability items.
- Numbers reflect **matched moons only**; subareas with `location_names: []` (their moons are
  post-game/unmatched, e.g. the Dark Side capless roads, boss re-fights, most Mushroom
  subareas) contribute 0 here and need their own pass if those moons ever become AP locations.

---

## Cross-cutting rules for every phase

- Wire changes are additive; never reshape committed fixed-buffer contracts.
- New moons/items: edit items.json/locations.json by hand, never bulk-import from romfs.
- After items.json/locations.json edits: re-run `sync_capture_table.py` / `sync_shine_table.py`.
- Re-read CLAUDE.md "Load-bearing invariants" at session start; update CLAUDE.md Status and
  docs/milestones.md at session end. Bundle via `install_apworld.py --out` in tests.
- Model guidance: Sonnet 4.6 for apworld/Python/data/tests; Opus 4.8 for switch-mod symbol
  discovery, new hooks, and the P7 spike. Always start switch-mod sessions with the
  **smo-build** and **smo-symbol-discovery** skills.

---

## Manual-start guide (Devon, easiest first)

Where to look if you want to hand-implement pieces while out of Claude usage. Ordered by
difficulty; each item is self-contained.

**1. Entrance exclusion list (no code).** Write `data/entrance_exclusions.json` — every
storyline entrance to keep vanilla (Top-Hat Tower, Inverted Pyramid, Ice Cave, Ruined Dragon
arena, …). P7 consumes it as-is; having it ready unblocks design questions early.

**2. Starting captures.** `apworld/smo_archipelago/hooks/World.py` — look for where
precollected/start-inventory items are pushed (manual-AP worlds use
`multiworld.push_precollected(world.create_item(name))` in `after_create_items` /
`before_generate_basic` hooks). Add Frog + Chain Chomp + one `world.random.choice` from the
capture list. While testing, check whether the first Spark Pylon out of Cap Kingdom is a
cutscene trigger or a real capture — if real, Spark Pylon becomes a 4th fixed starter.
The Switch side already unlocks captures it receives
(`AddHackDictionaryHook.cpp` / `game/CaptureGate.cpp`), including the map-menu list.

**3. CSV importer.** `scripts/import_moon_requirements.py` from scratch: 3 rows per moon,
columns E–I are Methods 1–5, row pattern is jump-height / cap-throws / other-required, col B
name, col C captures-that-work. Pure Python, testable with pytest next to the other suites.
Even just the name-reconciliation report against `data/locations.json` is valuable.

**4. Capturesanity removal.** `hooks/Options.py` (`Capturesanity` class),
`hooks/Locations.py` + `data/locations.json`/`categories.json` (where capture locations are
generated), `switch-mod/src/hooks/CaptureStartHook.cpp` (stops sending checks). Grep Rules.py
for `capturesanity` to find the rule branches that flip.

**5. Per-kingdom moon colors.** Client: `client/scout_cache.py` + `client/display.py`
(classification → palette index) and `client/maps.py` (kingdom lookup). Switch:
`switch-mod/src/hooks/ShineAppearanceHook.cpp` — add kingdom rows to `kPaletteColors3D/Dot`.
Wire: the palette index already travels in `ShineScoutsMsg` (`client/protocol.py`,
`docs/wire-protocol.md`).

**6. Cap moons → coins.** Client: item-receive path in `client/context.py` /
`client/switch_server.py` (follow how capture items become wire msgs); add a count-based
coin message. Switch: needs a new symbol (coin add) — read
`.claude/skills/smo-symbol-discovery/SKILL.md` first; this is the first item that requires
the full symbol workflow, which is why it's last on the manual list despite being "small".

**Don't start manually:** ability gating (P4) and entrance shuffle (P7) — both are
symbol-discovery + trampoline-heavy and depend on decisions earlier phases settle. Read
`docs/milestones.md` M7 Path A and Phase 4 sections before touching either.
