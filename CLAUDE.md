# CLAUDE.md — context for the next session

This file is a fast-load brief for the **Spicy Meatball Overdrive** project. The same project goes by several identifiers in different layers — keep them straight:

| Identifier | Value | Scope |
|---|---|---|
| AP-protocol game name | `Spicy Meatball Overdrive` | Wire-format `game` field in YAML seeds and AP `Connect` packets |
| Shipped apworld zip | `meatballs.apworld` | What lands in `vendor/Archipelago/custom_worlds/`; Archipelago imports it as `worlds.meatballs` |
| host.yaml settings key | `meatballs_options` | Derived by Archipelago from the zip stem `meatballs` |
| Per-player file extension | `.meatballsap` | Generated alongside the standard AP zip; SuffixIdentifier in the Component routes it to SMOClient |
| In-repo source folder | `apworld/smo_archipelago/` | Kept verbose to avoid churning every dev-workflow path reference; only the deployed artifact uses `meatballs` |
| Switch mod CMake project | `smo_archipelago` | Unrelated to the apworld; lives in `switch-mod/CMakeLists.txt` |

The zip stem `meatballs` was chosen 2026-05-20 because the `worlds.smo` slot was already claimed by another apworld (`.apsmo` namespace conflict). The in-repo folder `apworld/smo_archipelago/` did not change to avoid churning dev-workflow path references.

## ⚠️ Dev-environment gotcha: the Linux shell can serve STALE / byte-TRUNCATED files

Confirmed twice now (2026-06-12 and again 2026-06-13). There are two independent paths to
the repo and they can disagree within a session:

- **File tools (Read / Write / Edit) and VS Code read the real files on disk.** These are
  always correct and current.
- **The Linux shell** (`mcp__workspace__bash` — used for `pytest`, `git`, `g++`, the zip
  builder, etc.) mounts the repo through a separate layer. That layer snapshots files at
  workspace-boot, and the snapshot is **stale AND byte-truncated** — files are cut off
  mid-line well before EOF (e.g. `ApProtocol.hpp` served as 557 lines / 24,246 bytes ending
  mid-token at `void encodeHello(smoap::util:` while disk had the full ~592 lines). The
  shell's `stat` mtime reveals it: it reads *older* than your most recent edit. **Assume
  this is present in EVERY session** — it has reproduced in 100% of sessions to date
  (2026-06-12, -13, -14), and it truncates not just edited files but unedited deps too
  (`items.json` was served cut off mid-array at line 579 on 2026-06-14). Do not waste time
  re-confirming whether "this session" is affected; it is.

### How to avoid it: do file work through the disk-truth tools, not the shell

The Read / Write / Edit tools (and VS Code) always hit the real files on disk. The shell does
not. So:

- **Read / verify file contents → use the `Read` tool.** Never trust shell `cat` / `wc -l` /
  `head` / `tail` / `git diff` / `grep` over file bytes you care about — they read the
  truncated mirror. (The `Grep` tool also reads disk truth; prefer it over shell `grep`.)
- **Edit files → use `Edit` / `Write`.** These land on disk correctly and the editor never
  sees the stale mirror.
- **Run pytest / Generate / builds → do it on Windows (or a fresh session), NOT this shell.**
  The repo's normal workflow already runs `Generate.py` and the test suite on Windows; that is
  the reliable path and sidesteps the bug entirely. Hand verification back to the user (or a
  fresh shell) rather than fighting the mount.
- **If you MUST run something in the shell against your edits:** brand-new files written to a
  NEW path after boot ARE read correctly. So `Write` fresh copies of the changed files to a
  new dir (e.g. the outputs dir) and run there — but note even `cp`-ing "unedited" deps from
  the mount can copy truncated bytes, so `Write` those from `Read`-tool truth too, don't `cp`.
- **A shell `g++` / `pytest` failure pointing at a syntax error mid-declaration, or a
  `git diff` showing impossible deletions, is almost always the truncated mirror — NOT a real
  bug in your edit.** Confirm with `Read` before "fixing" anything.

Bottom line: **disk-truth edits are always safe** — the underlying files on disk are fine no
matter what the shell shows. The bug is purely a read-side illusion in `mcp__workspace__bash`.

## ⚠️ Generate runs the INSTALLED apworld zip, not your source edits

`Generate.py` imports `worlds.meatballs` from the bundled zip at
`vendor/Archipelago/custom_worlds/meatballs.apworld`, NOT from `apworld/smo_archipelago/`.
So **edits to the source apworld do nothing in Generate until you rebuild the zip** with
`python scripts/install_apworld.py` (run it on Windows — the Linux sandbox produces a
wrong-arcname zip that fails with `No module named 'worlds.meatballs'`). Confirmed bite
2026-06-14: a capture-pool fix was verified by the test suite (tests read the source tree
directly) yet Generate still failed byte-for-byte identically because it loaded the stale
2026-06-13 zip. **The tell:** the generation error/log is unchanged across a fix, AND the
installed `meatballs.apworld` mtime predates your edit. The regen loop is therefore:

1. `Edit`/`Write` source under `apworld/smo_archipelago/`.
2. `pytest apworld/smo_archipelago/tests/...` (validates source — fast, but does NOT exercise the zip).
3. **`python scripts/install_apworld.py`** to rebuild the zip — easy to forget, required every time.
   (Plain, no flags. The `--bundle-mod`/`--bundle-scripts` flags only add the switch-mod sources +
   wizard scripts *inside* the zip for release/first-run-wizard distribution; they do NOT affect
   generation. The world-gen data — `items.json`/`locations.json`/`regions.json`/`hooks/` — bundles
   every time regardless. Use plain for dev/gen-debug; reserve the flags for release builds.)
4. `python vendor/Archipelago/Generate.py`.

(The switch-mod binary in Ryujinx's exefs is independent of this zip; a Python-only bundle —
no `--bundle-mod`/`--bundle-scripts` — is ~500 KB and fine for quick gen-debug cycles.)

## Switch-mod build & deploy (build_switchmod.py → Ryujinx)

Whenever you change anything under `switch-mod/src/` (hooks, `ApState`, `CaptureGate`,
`ApProtocol`, etc.) the change does NOTHING in-game until you rebuild the subsdk9 binary AND
copy it into Ryujinx's exefs. This is a frequent loop — keep it handy.

**Prereqs (Windows, one-time):** Windows-native CMake, LLVM 19 (ABI-pinned by LibHakkun's
libc++ — not 18, not 20), Ninja, and mingw64 g++ (builds `sail`). The post-link tools
(`elf2nso.py` / `build_npdm.py` / `deploy.py`) shell out to bare `python`, so that Python must
be **3.11+ with `pip install lz4 pyelftools mmh3`**. `build_switchmod.py` puts its own
interpreter's dir first on PATH, so run it with that Python. Tool dirs can be overridden via
`SMOAP_CMAKE_BIN` / `SMOAP_LLVM_BIN` / `SMOAP_NINJA_BIN` / `SMOAP_MINGW_BIN` / `SMOAP_PYTHON_BIN`.

**Full build + deploy (PowerShell, Windows — the canonical copy-paste loop).** Run from a fresh
shell; the Linux sandbox can't build (and the stale-mount bug). Step 1's table sync is only
strictly needed after editing `data/items.json` / `data/locations.json`, but it's cheap and
idempotent so it's left in the always-run path.

```powershell
cd E:\smo_archipelago
# 1. Regenerate the joined tables (capture_table.h / shine_table.h)
python scripts\sync_capture_table.py
python scripts\sync_shine_table.py
# 2. Find this PC's LAN IP (the address the Switch/Ryujinx reaches it on)
$LAN_IP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' -and
    ($_.PrefixOrigin -eq 'Dhcp' -or $_.PrefixOrigin -eq 'Manual')
}).IPAddress
$LAN_IP   # eyeball this — if multiple lines print, pick the /24 that matches your Switch
# 3. Build (~30s). Pass the IP explicitly — CMake aborts without it.
python scripts\build_switchmod.py -DBRIDGE_HOST=$LAN_IP

$RYU = "$env:APPDATA\Ryujinx\mods\contents\0100000000010000\"
New-Item -ItemType Directory -Force "$RYU\exefs" | Out-Null
Copy-Item -Force E:\smo_archipelago\switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\subsdk9  "$RYU\exefs\subsdk9"
Copy-Item -Force E:\smo_archipelago\switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\main.npdm "$RYU\exefs\main.npdm"
```

Notes:
- Build artifacts land in `switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\`
  (`subsdk9` + `main.npdm`), staged by the `deploy.py` POST_BUILD step.
- Deploy target is `%APPDATA%\Ryujinx\mods\contents\0100000000010000\exefs\` — **NO per-mod
  subfolder** (the `...\0100000000010000\smo-archipelago\exefs\` layout the smo-build skill docs
  imply does NOT load; confirmed 2026-06-13). `0100000000010000` is SMO's US title id
  (`switch-mod/config/config.cmake`). Make sure the mod is **enabled** in Ryujinx's Mod Manager.
- The wrapper auto-runs `patch_hakkun.py`, the libc++ download, and the sail build, then does a
  clean CMake configure + `ninja`. Extra `-D…` args after the script name forward to CMake.

(The apworld zip is independent — a switch-mod change does NOT need `install_apworld.py`, and a
client/apworld change does NOT need a switch-mod rebuild. Know which tier you touched.)

## ⚠️ CRITICAL: Never commit Nintendo IP

This repository is open-source and built on a careful line: **functional identifiers and reference apworld names are okay; bulk-extracted Nintendo content is not.** A misstep here exposes the user to DMCA risk. Before any commit, audit `git status` + `git diff` and refuse to stage anything from this list:

**Must NEVER be committed (already gitignored — keep it that way):**
- `apworld/smo_archipelago/client/data/shine_map.json` — full extracted (stage, obj_id) → display-name table. Generated per-machine by `scripts/extract_shine_map.py`. ~775 verbatim Nintendo USen strings.
- `apworld/smo_archipelago/client/data/capture_map.json` — `hack_name → english_name` table. ~52 verbatim Nintendo USen strings.
- `apworld/smo_archipelago/client/data/shine_map_review.json` and `capture_map_review.json` — diagnostics that include the same strings.
- `switch-mod/src/ap/capture_table.h` — auto-generated by `scripts/sync_capture_table.py` from `items.json` + the gitignored `capture_map.json`. Each column is individually allowed (items.json + functional hack_name identifiers), but the joined (hack_name → English-name) table reproduces the load-bearing content of `capture_map.json`. Treated as IP for the same reason.
- `switch-mod/src/ap/shine_table.h` — auto-generated by `scripts/sync_shine_table.py` from `locations.json` + the gitignored `shine_map.json`. Same rule as capture_table.h: the join cross-references functional identifiers with English names in the load-bearing shape of `shine_map.json` (~435 of ~775 rows). When `shine_map.json` is absent the script emits a valid-but-empty stub so the bundled mod still compiles; the wizard re-runs it post-extraction to populate.
- `.romfs-cache/` — extracted RomFS (~5 GB of Nintendo assets).
- `scripts/.extract-venv/` — local Python 3.12 venv (not IP, but big and machine-specific).
- `docs/main-*.nso`, `*.nsp`, `*.nca`, `*.byml`, `*.szs`, `*.msbt` — any raw Nintendo binary.
- `prod.keys` / `dev.keys` / `title.keys` — Switch keys are themselves IP-sensitive.
- Any moon-name list, capture list, or stage list of more than ~5 entries pasted into a doc, comment, or commit message as illustrative content — bulk transcription is the same exposure as the file.

**Generally OK (already in the repo, established by upstream forks):**
- `apworld/smo_archipelago/data/locations.json` and `items.json` — the community-curated location and capture names (478 locations + 67 item entries — 42 Captures + 25 Moon items + 27 post-metro items — as of 2026-05-22). Forked from the public [empathy-mp3/SMO-manual-AP](https://github.com/empathy-mp3/SMO-manual-AP) upstream. Edits are fine; bulk additions from a romfs dump are not — alignment with Nintendo's MSBT should happen one mismatch at a time, not as a wholesale copy.
- Functional identifiers like `WaterfallWorldHomeStage`, `obj214`, `ScenarioName_<ObjId>`, `ShineList`, kingdom internal names (`CapWorld`/`SkyWorld`/etc.). These appear in every public SMO modding project (lunakit, MoonFlow, OdysseyDecomp) and are functional, not expressive.
- The one M5.7 anchor entry (`"Our First Power Moon"`) appears in CLAUDE.md, the test suite, and docs as a known ground-truth datapoint. One name as a verifiable test fixture is fine; a list of names is not.

**Safe pattern**: anything that requires a user to run `scripts/extract_shine_map.py` to produce stays in the gitignore. If you find yourself wanting to commit a piece of data so the next agent has a richer starting point, instead document where to regenerate it — see `docs/extract-moon-data.md` for the model.

**If you've staged something questionable**: `git restore --staged <path>` to unstage, then either delete the file or add it to `.gitignore` before retrying. Never override `.gitignore` with `git add -f` for SMO content. When in doubt, ask the user.

## Architecture

Two tiers: Switch/SMO subsdk9 mod ←TCP/JSON LAN→ PC client (Python, inside apworld) ←websocket→ AP server. The PC client lives at `apworld/smo_archipelago/client/` and ships in the .apworld zip — one process, one Kivy window, discovered by Archipelago's Launcher via `Component("SMO Client", ...)` in `__init__.py`. Full diagram and threading: [docs/architecture.md](docs/architecture.md). Wire format: [docs/wire-protocol.md](docs/wire-protocol.md).

## Load-bearing invariants

Non-obvious constraints that will silently break things if violated:

- **Subsdk pre-orig init ordering**: any subsdk init that allocates from `al::getStationedHeap()` MUST happen pre-orig in `gameSystemInit`, before SMO's engine has fragmented the heap. The FIRST statement in our `gameSystemInit` lambda is `smoap::ui::initDebugConsole()`. Deferring to first-draw silently hangs `drawMain.orig` with no log or crash report. See [docs/milestones.md](docs/milestones.md) for the full investigation.
- **Post-HELLO item replay: skip Moon items** — `OutstandingMsg` carries authoritative per-kingdom balance; re-sending Moons double-counts. See [docs/milestones.md#m6-phase-d](docs/milestones.md#m6-phase-d).
- **"Lie to the game" hooks** need the three-layer pattern (UI query → cinematic state → stage commit) — catch upstream of the visible state change. See [docs/milestones.md#m7-path-a--kingdom-order-gate](docs/milestones.md#m7-path-a--kingdom-order-gate).
- **Moon collection chokepoint**: SMO's Shine actor has FIVE entry points into `GameDataFunction::setGotShine`. The only universal chokepoint is `GameDataFile::setGotShine(ShineInfo*)`, hooked as `MoonGetHook`. Anything gating moon collection lives in that one trampoline. Don't bypass it.
- **READ THE DECOMP BEFORE PICKING A HOOK CHOKEPOINT — don't guess.** Repeatedly (P4 Side Flip, Cap Bounce, Ledge Grab, …) build/test cycles were burned guessing a hook target that turned out wrong because the actual control flow was never read. Before hooking ANY new function: pull its body (and its callers') from OdysseyDecomp (`https://raw.githubusercontent.com/MonsterDruide1/OdysseyDecomp/master/src/...`; the `WebFetch` tool works on raw URLs) and confirm what the decision actually depends on. Two compounding traps a decomp read catches that symbol-verification does NOT: (1) **a HIT symbol ≠ the decision flows through it** — tiny predicates/getters/setters/trivial-ctors are frequently *inlined* at the hot call site while the linker keeps an out-of-line copy (the hook installs and either logs nothing, or logs with no effect); (2) **you may be gating the wrong input** — e.g. Side Flip's `isEnableTurnJump()` is `mTrigger->isOn(QuickTurn) || mCounter>0`, so clamping `mCounter` can't work (the trigger is the primary path). When the target predicate is inlined, attack its out-of-line *inputs* (the trigger setter, the message sender, the arming function) rather than the predicate or its callers — and prefer a function called from many sites (those stay out-of-line). A decomp read is minutes; a wrong switch-mod build+deploy+in-game test is a full cycle of Devon's time. (`PlayerActorHakoniwa.cpp` is a 40-byte stub upstream — when the chokepoint lives in the undecompiled actor body, read the *helper* classes it calls, like `PlayerCounterQuickTurnJump`/`PlayerTrigger`, which ARE decompiled.)
- **Wire-format fixed-buffer shapes** (`FlatHashSet`, `LineBuffer`, fixed `char[N]` fields) are committed wire contracts — don't rewrite them unless retiring the protocol. Backstory: [docs/milestones.md#m61](docs/milestones.md).
- **Eager AP dial**: SMOClient dials AP immediately on Click-Connect regardless of Switch presence. Items received while Switch is offline queue in `BridgeState.received_items` and replay on HELLO. Default host is unset to avoid auto-dialing `archipelago.gg`. Tests: `apworld/smo_archipelago/tests/test_connect_gate.py`.
- **Capture/shine tables** (`capture_table.h`, `shine_table.h`) are gitignored and regenerated before every switch-mod build. After changing `data/items.json` or `data/locations.json`, manually re-run `scripts/sync_capture_table.py` and `scripts/sync_shine_table.py` (the wizard does this automatically).

## Known unknowns / risks for new work

1. **`PlayerHackKeeper::startHack` may not be a single chokepoint** — capture entry can split across multiple functions per cap-type. Secondary read-only check on `CapTargetInfo::isCaptureTarget` from the frame pump if the trampoline misses cases.
2. **Synthetic moon grant** must not retrigger our own hook — `ApState::synthetic_grant_this_frame` guard exists, plus belt-and-braces dedupe by `locations_checked` hash set.
3. **Goal-detection wiring (load-bearing, easy to break by accident).** The shipped fix is `CreditsStartHook` ([switch-mod/src/hooks/CreditsStartHook.cpp](switch-mod/src/hooks/CreditsStartHook.cpp)): a `HOOK_DEFINE_INLINE` patch at offset `0x4C54A4` (BL inside `StaffRollScene::init` — verified by Kgamer77/SuperMarioOdysseyArchipelago, MIT) calls `reportGoal()` gated by `ApState::goal_sent`. The credits scene only initializes when the post-wedding cutscene plays — never on portrait warp, Darker Side, or save load. Four earlier approaches all misfire: (a) `DemoPeachWedding::makeActorAlive` fires in Bowser's Kingdom too; (b) bridge-side location trigger fires on the Darker Side completion moon; (c) first Mushroom Kingdom arrival via `WorldMapSelectHook` AND (d) `ShineNumGetHook` both false-positive on the hidden Luncheon portrait warp (a painting in CookingWorld teleports Mario to PeachWorld pre-game-clear). Don't re-introduce a Mushroom-arrival, moon-check, or `DemoPeachWedding` trigger.

## Deferred work

- **HELLO `cap_table_hash` field** is empty — would close the Switch↔apworld cap-table drift detection loop. Low priority.
- **Dedicated AP-credit overlay** — the natural HUD shows AP-credit-only counts (locally collected moons don't bump it), which is visually odd. Cappy speech bubbles smooth most of this; a dedicated ImGui overlay would be cleaner.
- **Talkatoo% Gap #2** — named-set persistence across save+quit is an **explicit non-goal**. Re-talking to Talkatoo after save+quit is the intended UX. See [docs/handoff-talkatoo.md](docs/handoff-talkatoo.md) for the non-goal rationale and the shape a misguided implementation would take. Do not implement.
- **Later goals beyond the Mushroom festival** — Moon Kingdom "world peace" = beating the game (leaving Moon), which currently ENDS the AP. Its post-peace moon-pipe moons (added in P6.5) therefore sit at/after the goal. If a later goal is ever added past the festival, revisit Moon's "leave = win" coupling so those moons stay collectable. See [docs/p7-entrance-shuffle-spike.md](docs/p7-entrance-shuffle-spike.md) §6.

## Status

**v2 plan (Dark Side ability + capture randomizer) — P0–P3 COMPLETE + committed, P4 essentially complete.** Foundations, in brief:
- **P0** — CSV ingestion: `scripts/import_moon_requirements.py` parses the community "Moon Ability Requirements" CSV (repo root, Devon's authored work, safe to commit) → `data/moon_requirements.json` (435/435 current locations matched) + `data/subareas.json` (131 subareas). Vocabulary normalised to ability enums.
- **P1** — Cap-moon → coins: `coin_grant` wire msg (`total` = lifetime Cap moons × 100), `compute_cap_coin_total()`/`push_coin_grant()` on the client, `applyCoinGrant()` via lazy `GameDataFunction::addCoin` lookup on the Switch. **VERIFIED IN-GAME** (idempotent high-water catch-up).
- **P2** — capturesanity removed + fixed starters: `before_is_category_enabled` False for "Capture"; all capturesanity Rules branches gone; `_precollect_starting_captures()` gives Frog + Chain Chomp + 1 random each seed.
- **P3** — ability/capture item pool + tracking: `data/items.json` +20 ability items (new `Ability` category; progressive chains: Crouch ×3, Ground Pound ×3 [2 chain + 1 clone], Jump ×2); part-captures split into 4 variants with `VARIANT_CAP_HACK_OVERRIDE` (`maps.py`) pinning each to its SMO hack; `data/locations.json` +68 MK/Dark/Darker-Side `junk_only` checks (names verbatim from shine_map so the Switch matches); `ability_state` wire msg (full-overwrite per-ability count snapshot) → `ApState::ability_table` under a seqlock → Cappy unlock bubble; duplicate ability/capture → 100 coins via the P1 path. `compute_total_coin_grant()` folds all dups. Full 3a/3b detail (restored): [docs/plan-p3-detail.md](docs/plan-p3-detail.md).

**IP (Devon, 2026-06-13):** NEVER commit `shine_map.json`/`capture_map.json` or anything under `bridge/smo_ap_bridge/data/` (covered by the `bridge/` .gitignore rule). The 68 MK/DS names in locations.json were sourced from shine_map (romfs) at Devon's explicit direction; Devon owns the commit decision for that data.

**Capture/shine-table hack-name lesson (load-bearing for the sync scripts).** `capture_table.h`/`shine_table.h` must use **SMO-internal** hack_names (T-Rex=`TRex`, Goomba=`Kuribo`), because `CaptureGate::captureBlocked` matches on `PlayerHackKeeper::getCurrentHackName()` — an identity map (apworld display names) fails open. `sync_capture_table.py`/`sync_shine_table.py` resolve `capture_map.json`/`shine_map.json` from `%APPDATA%/SMOArchipelago/data/` (the wizard/client location) and apply `VARIANT_CAP_HACK_OVERRIDE` for the 4 split part-captures. After editing `data/items.json`/`data/locations.json`, re-run both before a switch-mod build; confirm the new `shine_table.h` `// Count:` is non-zero (an absent shine_map emits a `0 moons` stub).

**P7 — entrance shuffle: LIVE + VALIDATED IN-GAME (2026-06-19).** `kEntranceRemapApply` in `switch-mod/src/hooks/EntranceShuffleHook.cpp` is now `true` — the remap actually rewrites `mChangeStageName`/`mChangeStageId` in the ChangeStageInfo (was preview-only). Coupled bijection ships in slot_data over the wire, so the flip is **switch-mod-only** (no apworld rebuild / re-seed). Entry rows keyed on `dest` (inbound interior), exit rows keyed on `cur` (`getCurrentStageName`); both exit classes handled (`returnPrevStage` pops to origin already-correct; `changeNextStage` gets the exit-by-cur rewrite). `dest==cur` guard skips moon-rock same-stage reloads. Apply-mode walk passed every case: doors, pipes, moon pipes, multi-exit subareas (both exit pipes collapse to origin), forward + return, with story areas (Sky Garden Tower) and boss/cutscene warps (Spewart) correctly untouched. Logs + table: [docs/devon-p7-entrance-testing-results.md](docs/devon-p7-entrance-testing-results.md) (APPLY-MODE section); memory [[entrance-shuffle-live-validated]]. **Open follow-ups:** (a) Rules.py reachability watch — moon-pipe moons reached via shuffled origin (Devon's, when applicable); (b) kingdom-order gate exposes not-yet-reachable kingdoms as selectable, only the BACKSTOP enforces order — orthogonal, see [[kingdom-order-gate-premature-destinations]].

**P4 — ability enforcement (current phase, essentially complete).** Gate Mario's moveset on AP ability items: trampoline `PlayerJudge*::judge()` / `PlayerInput::isTrigger*` predicates / `rs::sendMsg*` senders and force-suppress when the gating ability is unowned. `ApState::abilityAtLeast(name, level)` reads the P3-3b `ability_table` (lock-free seqlock); `ability_gate_force_unlock` (atomic) is the fail-open safety net, recovery hatch is `/send <slot> <ability>`. All hooks in `hooks/AbilityGateHook.cpp`, symbols in `SmoApSymbols.sym`. **Every ability gate is now implemented** (Crouch/Roll/Roll Boost, Ground Pound/Dive, Wall Slide, Ledge Grab [via Wall Slide], Climb, Double/Triple Jump, Backflip/Long Jump [Option 3 squat-jump suppression], Ground Pound Jump, Cap Bounce, Spin Throw, **Up/Down Throw** [`isThrowTypeRolling` split by gesture `v.y` sign]). The two final items are code-complete and awaiting in-game confirmation: **Side Flip** (physics NEUTER of `PlayerConst::getTurnJump{Power,VelH,Gravity}` — the turn-jump STATE is inlined with no interception seam, so the flip animation stays but the height advantage is gone) and **Up/Down Throw** (sign convention `kUpThrowIsPositiveY` unverified — one constant to flip if reversed). **Canonical plan + full ability→hook mapping table + session log: `docs/plan-p4-detail.md` — keep it updated every P4 session.**

**Cap-Kingdom Spark Pylon exemption (load-bearing runtime behavior).** The forced Cap-Kingdom exit pylon is a REAL `ElectricWire` startHack capture, so the capture gate would eject Mario and soft-lock the opening kingdom. `hooks/CaptureStartHook.cpp::capIsExemptCapKingdomPylon` lets `ElectricWire` through ONLY at `getCurrentStageName`==`CapWorldHomeStage` (every other pylon gates on the "Spark pylon" item; fails closed if the stage can't be confirmed). Spark Pylon stays OUT of `kBaselineHacks`/precollect. Don't remove.

**Devon-fork features (2026-06-11/12):** `randomize_kingdom_gates` (sum-preserving ±5 rolls, total pinned to vanilla 124; rolled gates flow slot_data → `kingdom_gates` wire msg → `ApState::kingdom_gate[]` → `UnlockShineNumHook` so the in-game Odyssey cost matches logic), `multi_moon_shuffle` (default on; 13 MM items ↔ 13 `multi_moon`-tagged boss locations, PM-first demotion variant, one Metro MM dropped — "A Traditional Festival!" is the festival victory location and holds no item), Ruined moons promoted to progression + demotion-exempt (gated-kingdom moons MUST be progression or the reachability sweep can't satisfy their gate — guard test in test_randomize_kingdom_gates.py), and **peace-gated Moon Rocks** (`MoonRockHook`: openable after per-kingdom story completion instead of game clear; NEVER force while the moon-rock scenario is active — the vanilla rock-open is a scenario-jump stage reload whose re-init must take the wreckage/commit branch; mid-story forcing without the peace gate skips kingdom bosses and strands story-MM checks). Cap-peace-from-start experiment concluded OFF — scenario numbers are recomputed from quest state at every load; see MoonRockHook.cpp header. `install_apworld.py --out` exists so the bundling tests never clobber the real installed zip (zipimport TOC staleness presented as 'bad local file header').

Shipped as v0.1.x-alpha (see `git tag`). M0–M7 complete, real-Switch deploy validated end-to-end, PopTracker pack ships alongside the apworld zip on every tagged release. M8 polish: **on-Switch ImGui debug overlay shipped 2026-05-22** (`switch-mod/src/ui/ApDebugConsole.cpp`) — via upstream LibHakkun's `Nvn`/`ImGui`/`DebugRenderer` addons; renders the discovery report + last ~200 log lines when SMOClient is unreachable for >5s, hides on TCP-up. Cappy speech-bubble notifications still ship alongside (connect/disconnect/save-load status). Per-classification moon recolor via `Shine::init` post-trampoline, M7 demo-end retime. Talkatoo% mode shipped 2026-05-21 — substitutes Talkatoo's speech bubble with AP-pool moon names, blocks collection of non-named moons, exempts 22 audited scenario-advancing moons. Talkatoo follow-up gaps: [docs/handoff-talkatoo.md](docs/handoff-talkatoo.md). Per-milestone narratives (provenance for every wire-protocol decision, failed-iteration history): [docs/milestones.md](docs/milestones.md). Original implementation plan: `C:\Users\maxwe\.claude\plans\after-much-work-i-tender-thompson.md`.

Pattern invariants worth knowing even without reading the milestone narratives:

- **Subsdk pre-orig init ordering (load-bearing, 2026-05-22)**: any subsdk init that allocates from `al::getStationedHeap()` MUST happen pre-orig in `gameSystemInit`, before SMO's engine has fragmented the heap. The ImGui overlay's `ImGuiBackendNvn::tryInitialize()` was deferred-to-first-draw in seven earlier attempts and silently hung the first `drawMain.orig` — no log, no crash report. Fix is the FIRST statement in our `gameSystemInit` lambda: `smoap::ui::initDebugConsole();` (carves a 2 MiB ExpHeap + wires allocator + calls `tryInitialize`). Mirrors Kgamer77/SMOO-Plus-Hakkun's `imgui::setup()` placement. See memory `imgui-addon-pre-orig-setup` for the three ranked first-principles theories of WHY (heap fragmentation #1, addon state-machine ordering #2, ARMeilleure translation block #3) and the full list of fixes that DIDN'T work.
- **M6 phase D**: when sending the post-HELLO item replay, **skip Moon items** — `OutstandingMsg` carries authoritative per-kingdom balance, re-sending Moons double-counts. See [docs/milestones.md#m6-phase-d](docs/milestones.md#m6-phase-d).
- **M7 Path A**: future "lie to the game" hooks need the three-layer pattern (UI query → cinematic state → stage commit) — catch upstream of the visible state change, not just at commit. See [docs/milestones.md#m7-path-a--kingdom-order-gate](docs/milestones.md#m7-path-a--kingdom-order-gate).
- **Phase 4 (Talkatoo% block)**: SMO's Shine actor has FIVE entry points into `GameDataFunction::setGotShine` (`Shine::get`, `getDirect`, `getDirectWithDemo`, `receiveMsg`, `exeWaitRequestDemo`). Hooking any single one misses 4/5 collection paths. The universal chokepoint is `GameDataFile::setGotShine(ShineInfo*)` — already hooked since M4 as `MoonGetHook`. Anything that wants to gate moon collection lives in that one trampoline. See [docs/milestones.md#phase-4--talkatoo-mode](docs/milestones.md#phase-4--talkatoo-mode).
- **Wire-format fixed-buffer patterns** (`FlatHashSet`, `LineBuffer`, fixed `char[N]` fields) are vestigial M6.1 workarounds from the pre-Hakkun libstdc++ allocator NULL-deref. Hakkun's musl + libc++ + `HeapSourceDynamic` removed the constraint, but the shapes are committed contracts — don't rewrite them unless retiring the wire format. Backstory: [docs/milestones.md#m61](docs/milestones.md).

## Repository layout

```
E:\smo_archipelago\
  README.md                      Project overview
  CLAUDE.md                      ← this file
  LICENSE                        MIT
  .gitignore                     Note: third_party/ ignored; vendor/ tracked
  .gitmodules                    Submodules (vendor/Archipelago, switch-mod/sys,
                                 switch-mod/lib/OdysseyHeaders, switch-mod/lib/imgui)
  .claude/skills/                Project skills (smo-build, smo-loopback-test, ...)
  apworld/smo_archipelago/       The apworld + Python client
    __init__.py                  World class + SMOSettings + "SMO Client" Component reg
    data/                        categories.json / items.json / locations.json
                                 / meta.json / regions.json (game-level config
                                 lives in Data.py, not a JSON file)
    hooks/                       Generation hook surfaces (Rules, Options, World, ...)
    Data.py, Game.py, ...        World boilerplate (item/location/region tables, etc.)
    _setup/                      One-download setup wizard (Kivy) — first-time toolchain +
                                 deploy + extract, surfaces in Archipelago Launcher.
                                 wizard.py is the Kivy front-end; wizard_cli.py is a
                                 headless JSON-event orchestrator the wizard delegates
                                 to. Split sub-modules: audit, build, deploy, installers,
                                 launcher_errors, net, prereqs, smoap_file.
    client/                      Python client
      __init__.py                Empty / lightweight; never pulls Kivy
      main.py                    Launcher entry point; `def launch(*args)` invoked via Component
      context.py                 SMOContext(CommonContext) + SMOClientCommandProcessor
      gui.py                     SmoManager(GameManager) — Kivy UI; imported lazily inside run_gui
      switch_server.py           asyncio TCP server on :17777; replay on HELLO
      discovery.py               UDP bridge-discovery responder (the other side of ApDiscovery)
      protocol.py, state.py      Wire-format dataclasses + thread-safe state mirror
      datapackage.py, maps.py    AP id↔name + classifier + ShineMap / CaptureMap
      scout_cache.py, display.py Channel A: LocationScouts pre-fetch + label formatting
      commands.py                Pure `parse_command` for the /-commands in context.py
      config.py, logging_setup.py  Legacy TOML overlay (kept for back-compat) + log config
      net_util.py                detect_lan_ip helper shared by client + wizard
      setup_state.py             Pure helpers that locate wizard-produced map files
                                 (kept in client/ so SMOClient never imports _setup/)
      data/                      shine_map.json + capture_map.json (gitignored; regenerated)
    tests/                       50 test files. Live-AP tests gated on SMOAP_LIVE_AP=1;
                                 extraction tests skip when shine/capture maps absent.
      pyproject.toml             Self-contained pytest config (importmode=importlib)
      conftest.py                Inserts apworld/smo_archipelago/ into sys.path
      seeds/                     Loopback test seeds (smo_loopback.yaml + gitignored out/)
  switch-mod/                    LibHakkun C++ module (subsdk9)
    CMakeLists.txt               Builds subsdk9 via the Hakkun + sail CMake includes
    config/{config.cmake,npdm.json,VersionList.sym}
                                 Module-binary slot (subsdk9), title id, NPDM
                                 capabilities, SMO 1.0.0 build-id pin
    sys/                         LibHakkun submodule (musl + LLVM libc++ + HeapSourceDynamic
                                 addon + sail; Windows-port patches applied by
                                 scripts/patch_hakkun.py at build time)
    lib/OdysseyHeaders/          OdysseyHeaders submodule — SMO 1.0.0 type layouts
                                 (al::, agl::, game::, nn::, sead::, ...)
    lib/imgui/                   Dear ImGui submodule pinned at v1.92.8 — backs the
                                 on-Switch ApDebugConsole via LibHakkun's ImGui addon.
    syms/                        sail symbol DB
      game/SmoApSymbols.sym      All mangled SMO function + vtable symbols we hook
                                 (~47 entries; `grep -c '^_Z' switch-mod/syms/game/SmoApSymbols.sym`).
      nn/nifm.sym                nn::nifm symbols resolved against SMO's dynsym.
      nn/socket.sym              nn::socket symbols — uses SMO's socket session via a
                                 no-op trampoline; see commit 89632a7.
      nvn.sym                    NVN bootstrap symbol for the ImGui NVN backend;
                                 tagged `@sdk = nnSdk`.
    src/
      main.cpp                   hkMain entry — installs hooks, spawns worker
      ap/{ApClient,ApState,ApConfig,ApFrameBridge,ApProtocol,ApDiscovery}.{cpp,hpp}
                                 ApClient owns a parallel hk::socket::Socket client
                                 against bsd:u (separate from SMO's nn::socket); ApDiscovery
                                 runs the UDP probe chain — loopback (Ryujinx, 250ms) then
                                 unicast sweep across BRIDGE_HOST's /24 (real-Switch, 1s).
      ap/capture_table.h         AUTO-GENERATED (42 cap names) — run sync_capture_table.py
                                 (GITIGNORED — joins items.json with extracted capture_map.json)
      ap/shine_table.h           AUTO-GENERATED (~435 moons) — run sync_shine_table.py
                                 (GITIGNORED — joins locations.json with extracted shine_map.json;
                                 emits an empty stub when shine_map.json is absent so the bundled
                                 mod still compiles in release CI)
      ap/shine_lookup.hpp        Linear-scan helpers over shine_table.h (Phase 4)
      hooks/HookSymbols.hpp      C++ string constants mirroring syms/*.sym; used by
                                 HkTrampoline<>::installAtSym<> and hk::ro::lookupSymbol.
                                 Must stay in sync with the .sym files.
      hooks/*.cpp                One file per hook target. Covers moon get/label, capture
                                 start/lock, scenario flag, save load, world-map select,
                                 addPayShine debit, addHackDictionary gating, Cappy message
                                 routing, shine appearance, death-link, credits-roll goal,
                                 Talkatoo% speech substitution.
      game/{MoonApply,CaptureGate,KingdomUnlock,KingdomOrderGate}.{cpp,hpp}
                                 KingdomUnlock retains the kingdom name ↔ bit ↔ worldId
                                 tables despite its now-legacy name.
      ui/ApHudOverlay.{cpp,hpp}  Heartbeat-mode HUD (kept for debug logging surface).
      ui/ApDebugConsole.{cpp,hpp}  On-Switch ImGui debug overlay. Init MUST be the FIRST
                                 statement in `gameSystemInit` (pre-orig) — see invariants above.
      ui/EmbeddedFontKarla.hpp   Karla-Regular.ttf (OFL 1.1, ~17 KB) as a byte-array
                                 header — atlas swap replaces ProggyClean for crisp text.
      ui/CappyMessenger.{cpp,hpp}  In-game speech-bubble notifications. Settle gate requires
                                 BOTH a frame-counter threshold AND a wallclock interval
                                 (post-Hakkun Ryujinx JIT timing bug — see M9 in milestones.md).
      util/{Json,Log,MsgFontSafe}.{cpp,hpp}
    tests/                       Host-runnable C++ tests (test_json, test_protocol,
                                 test_cappy_messenger, test_msg_font_safe, test_shine_lookup).
                                 Run via smo-host-tests skill.
    romfs/ap_config.json         INFORMATIONAL ONLY — bridge IP/port are baked in at
                                 compile time via CMake -DBRIDGE_HOST/-DBRIDGE_PORT.
  scripts/
    switch_smoke_test.py         Fake-Switch end-to-end test
    sync_capture_table.py        items.json → capture_table.h
    sync_shine_table.py          locations.json × shine_map.json → shine_table.h
    extract_shine_map.py         NSP → romfs → shine_map.json + capture_map.json
    install_apworld.py           Zips apworld/smo_archipelago/ → vendor/.../custom_worlds/
    ap_generate.py, ap_server.py Archipelago Generate/MultiServer wrappers (auto-pip suppressed)
    build_poptracker_pack.py     PopTracker pack generator
    build_switchmod.py           One-shot Switch-mod build wrapper (LLVM 19 + sail +
                                 LibHakkun Windows-port patches; see smo-build skill)
    patch_hakkun.py              Applies the 5 remaining Windows-port patches to the
                                 pinned LibHakkun submodule (idempotent)
    setup_imgui_addons.py        Copies LibHakkun's Nvn/ImGui/DebugRenderer addon sources
                                 into the build tree alongside Dear ImGui
    setup_sail_winpath.py        One-time sail host-binary compile via msys2 mingw64
    fix_hakkun_symlinks.py       Stub for converting OdysseyHeaders symlinks (no-op currently)
    .extract-venv/               Auto-created Python 3.12 venv (gitignored)
  docs/
    architecture.md              Two-tier diagram, threading, responsibilities
    wire-protocol.md             Wire-format ref