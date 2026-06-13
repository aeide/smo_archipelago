# SMO Archipelago v2 Vision — Implementation Plan

Drafted 2026-06-12 from Devon's full feature brief. This is the successor plan to the original
M0–M7 plan. Each phase is sized for execution by Sonnet 4.6 (apworld/Python/data work) or
Opus 4.8 (switch-mod hooking/symbol work) in dedicated sessions. Read CLAUDE.md first in every
session; the invariants there (MoonGetHook chokepoint, pre-orig init ordering, three-layer hook
pattern) all apply to this work.


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

### P1 — Cap Kingdom moons → 100 coins  *(COMPLETE 2026-06-13 — in-game test pending apworld reinstall fix)*

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

### P3 — Mushroom→captures, DarkSide→abilities, junk-only MK/DS checks  *(split: Sonnet apworld, Opus switch)*

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
  (`data/entrance_exclusions.json` — Devon authors; Top-Hat Tower, Invert