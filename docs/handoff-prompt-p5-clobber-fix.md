# Handoff prompt — P5 clobber fix (T-A/T-B) + honest chain-only read (T-C)

Paste-ready brief for the next session. Read
[plan-p5-cross-world-loads.md](plan-p5-cross-world-loads.md) §8–§9 first
(§9 is the 2026-07-11 walk triage this handoff executes on), plus memory
`[[p5-cross-world-load-crash-class]]`.

## Where things stand (2026-07-11 walk, logs `swinging-crash.txt` + `reroute.txt`)

Validated in-game, DONE, do not re-litigate:

- **Strand fix (§8.1)**: `liveGameDataFile()` (holder `mPlayingFile`) +
  `tickChainKingdomListing()` on every `exeLoadStage` tick. Boot of the
  stranded Wooded save placed a boardable ship with no S&Q. The
  `[odyssey-strand-watch]` watchdog stayed silent — keep it that way.
- **B2 pre-arm + T1 hold**: foreign-interior entries load clean
  (`[p5-hold] ... -> done`), retrace clean, B1 demo warp into locked
  Luncheon clean with a parked ship.
- **Ledger probes** (`[p5-worldreq]` request / request(plain) / DESTROY +
  1 Hz `[p5-reswatch]`): shipped and decisive. Keep them installed for
  the verification walk; they cost nothing.

Two bugs remain. Both are switch-mod-only — **NO reseed, NO apworld
change, KEEP Devon's current save** (seed `AP_57213197975398613665`).

## Bug 1 — the residency clobber (the last crasher in the P5 class)

Mechanism, probe-confirmed (§9.2): the engine calls the PLAIN
`WorldResourceLoader::requestLoadWorldResource(currentWorld)` at every
scene entry. After a B2 pre-arm the engine's current-world bookkeeping is
STALE (door commits never update it; only flights/demo warps do — the
reswatch shows `resident=7 engineCurWorld=3` post-hold, and it flipped to
10 correctly after the B1 Luncheon demo warp). So at a foreign-interior
scene entry the plain request reloads the ORIGIN world
(`request(plain) world=3 (resident_was=7) -> LOAD STARTED`), destroying
the pre-armed set. Small stages survive on per-stage fallback; Swinging
Along the High-Rises (city delta) ExpHeap-aborts ~8 s later.

### T-B (preferred): fix the engine's current-world bookkeeping at commit

**Decomp read FIRST (CLAUDE.md rule — do not guess the seam):** pull
`GameDataFunction::getCurrentWorldId` / `getCurrentWorldIdNoDevelop` from
OdysseyDecomp (raw URLs work with WebFetch,
`https://raw.githubusercontent.com/MonsterDruide1/OdysseyDecomp/master/src/System/GameDataFunction.cpp`,
GameDataFile.cpp/.h, GameDataHolder.cpp) and answer: which FIELD backs
the current world id, who WRITES it (stage-change path? world-warp
path?), and what else reads it. Cross-check offsets against
`switch-mod/lib/OdysseyHeaders/game/System/GameDataFile.h`.

If the field is a plain stored s32 with a clear writer: at the remapped
cross-world commit (both B2 interior targets and — check whether needed —
the exempt/story-managed plain commits), write the DEST world id into it
post-orig in `fileChangeNextStageHook` (EntranceShuffleHook.cpp; it
already knows the dest world id from `resolveWorldIdForStage`). Vanilla
consistency argument: in vanilla, standing in a Metro subarea means
current world == Metro; the remap breaks that, this write restores it.
The plain request then loads the RIGHT world by itself — no request
suppression needed, and every other stale-current-world consumer
(regional coins? map? checkpoint list?) is fixed too. The decomp read
must list those consumers so the in-game walk can spot-check them.
The return trip needs no special handling: exits target overworld
HomeStages, which `calcNextWorldId` resolves natively (proven by the
clean retraces).

### T-A (fallback if T-B's field is messy/inlined): redirect the stale plain request

In `requestLoadWorldPlainHook` (CrossWorldLoad.cpp), pre-orig: let
`resident = getLoadWorldId(loader)`, `stage_world =
resolveWorldIdForStage(getCurrentStageName())`. If
`world != resident && stage_world == resident` — the loaded set matches
the stage we are actually standing in, so the request is the
stale-bookkeeping artifact — call `orig(loader, resident)` instead (log
`[p5-worldreq] request(plain) REDIRECTED stale=N -> M`). Do NOT simply
skip: the plain request also refreshes scenario resources, and the
redirect keeps that for the correct world. Everything needed is already
bound; zero new symbols.

Ship ONE of these (T-B preferred), not both.

## Bug 2 (T-C) — the listing force poisons the chain-only derivation (§9.3)

`reroute.txt`, Luncheon chain arrival: `[chain-launch] member
findUnlockShineNum worldId=10 orig=18 -> 18` — the allowance did NOT
zero. Cause: `tickChainKingdomListing` forces `mIsUnlockWorld[w]=true`
(required for `isExistHome`, §8.1), and `isWorldUnlockedRaw` reads that
same array → chain-reached kingdoms read as "legitimately unlocked" →
`isKingdomChainReachedOnly` returns false → allowance zeroing,
visited-only bounce, and the T2 Lost-sweep unlock guard are all neutered
wherever the force has run.

Fix (OdysseyRescue.cpp + ApState):

1. Add an ApState atomic bitmask `chain_unlock_forced_bits` (mirror the
   existing kingdom-bit mask patterns). `tickChainKingdomListing` sets
   bit w whenever it forces `mIsUnlockWorld[w]` (idempotent set each
   re-assert is fine).
2. `isWorldUnlockedRaw(w)` (or a new `isWorldUnlockedHonest`) returns
   `raw_unlocked && !forced(w)`. Route BOTH
   `isKingdomChainReachedOnlySave` and `isKingdomChainReachedOnly`
   through the honest read. Careful with the internal consumer:
   `tickChainKingdomListing` itself calls `isKingdomChainReachedOnlySave`
   — with the honest read it will keep re-asserting a forced world
   (correct; the `if (unlock_arr[w]) continue` guard stops log spam).
3. Clear bit w when the kingdom becomes LEGITIMATELY unlocked, so a
   later-paid Sand fork (etc.) restores normal behavior: trampoline
   `GameDataFunction::unlockWorld` (symbol already resolved out-of-line
   at boot, `kGameDataFunctionUnlockWorld`) — per the GameProgressData
   decomp it is the monotonic-counter loop, so on a call with world w',
   clear the forced bits of w' AND every world whose unlock it implies
   (simplest: clear any forced world that now reads unlocked on the next
   tick AFTER an updateList rebuild — or just clear ALL forced bits in
   the trampoline and let the next tick re-force the ones still
   chain-only; that self-heals and needs no story-order table).
4. Regression guard: a legit-unlocked kingdom must NEVER read chain-only
   (the 2026-07-09 Cascade lesson) — the honest read only SUBTRACTS our
   own forces, it must not flip kingdoms we never forced.

## Verification walk (same seed, same save)

Boot lines: §8.3 set (probes still installed) + whatever install line the
T-B/T-A fix logs.

1. **Swinging verdict**: Wooded "Flower Road" (EX_RailCollision) →
   PoleGrabCeilExStage. Expect ARMED → hold → NO stale
   `request(plain)` for world 3 (T-B: the plain request now asks for 7 /
   T-A: `REDIRECTED` line) → `[p5-reswatch]` stays `resident=7` → no
   ExpHeap abort. Clean = **the P5 crash class is CLOSED**.
2. **Survivor regression**: Cap "Poison Tides" ↔ Swinging Scaffolding
   round trip — still clean, reswatch coherent, retrace still lands in
   the origin scenario.
3. **Finding 11, at last**: Cascade "Gusty Bridges" → Simmering in the
   Kitchen → 'CostumeOut' → Luncheon. Expect `[chain-arrival] ...
   unlocked=0`, ship parked, AND `[chain-launch] ... orig=20 -> 0
   (allowance ZERO)` at the globe/launch. Then AP-grant + deposit the
   rolled gate (20) and attempt the story launch — does the zero open
   it, and does the resulting firstNext flight bounce to a visited
   kingdom? That is the finding-11 verdict this whole thread has been
   chasing.
4. **T-B only — stale-consumer spot-check**: while standing in the
   foreign interior, glance at whatever the decomp read flagged as
   current-world consumers (kingdom name on the pause map, regional coin
   counter) for obvious wrongness.

## Constraints / reminders

- Decomp read before ANY new hook target (CLAUDE.md invariant; this walk
  is the payoff of that rule — do not skip it for T-B).
- Verify any new mangled symbol with `scripts/check_nso_symbols.py`
  against `.romfs-cache/main.nso` (works on Windows).
- Build: `python scripts\build_switchmod.py "-DBRIDGE_HOST=192.168.4.100"`
  (QUOTE it; verify `^BRIDGE_HOST:` in CMakeCache shows the full dotted
  IP). Deploy = copy subsdk9 + main.npdm into
  `%APPDATA%\Ryujinx\mods\contents\0100000000010000\exefs\`.
- Update plan-p5-cross-world-loads.md (add §10) and memory
  `p5-cross-world-load-crash-class` with the outcome.
