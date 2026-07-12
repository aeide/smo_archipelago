# Execution handoff — P5 fixes T1–T5 (2026-07-09 sixth-session triage)

**Model: Sonnet.** Every task below is mechanical and fully specified — exact
file, exact function, the decided approach, and the verification step. There
are no seam choices, no decomp navigation, and no design decisions left; all
of that was done in the sixth triage session (docs/plan-p5-cross-world-loads.md
§6). If you find yourself needing to choose a hook target or redesign a
predicate, STOP and report back instead — that means a premise below is wrong.

## Read first (in this order)

1. `CLAUDE.md` — all of it. The dev-environment rules (disk-truth tools only,
   install_apworld regen loop, never commit Nintendo IP) apply in full.
2. `docs/plan-p5-cross-world-loads.md` **§5 and §6** — §6.1 is the crash
   triage T1 fixes, §6.2 the unlock-overshoot T2 fixes, §6.4 the Lost/Ruined
   ruling T3 implements, §6.5 the T4/T5 root causes, §6.6 the walk matrix
   Devon runs after your edits are built.
3. `docs/plan-decoupled-entrances.md` — the "P5 session 2026-07-09 (sixth)"
   block.
4. Memories: `p5-cross-world-load-crash-class`, `p4-chain-return-open-findings`.

## Standing constraints (verbatim — do not relax)

- **Never stage `switch-mod/sys` or `cap-start.bin`.**
- **Never commit Nintendo IP** — the full list is in CLAUDE.md ("⚠️ CRITICAL:
  Never commit Nintendo IP"). Everything you touch below is functional
  identifiers; keep it that way.
- Pytest ONLY via `.venv\Scripts\python -m pytest apworld\smo_archipelago\tests`
  (bare pytest lacks pytest-asyncio; 157 async "failures" = env noise).
  Baseline at last session end: **1013 passed / 98 skipped**.
- Symbol constants go in `switch-mod/src/hooks/HookSymbols.hpp`; the sail
  `.sym` DB is only for `installAtSym` targets. (No task below needs a NEW
  symbol; if one seems to, a premise is wrong.)
- Symbol presence checks, if needed:
  `python scripts\check_nso_symbols.py .romfs-cache\main.nso <mangled>`.
- **Devon builds and walks.** You edit, run pytest where applicable, run
  `python scripts\install_apworld.py` after the apworld change, and update
  docs/memories. Nothing more — no builds, no Ryujinx deploys, no reseeds,
  no commits.

---

## T1 — serialize the B2 world load: HOLD exeLoadStage until the world
## resources finish loading

- **File/function:** `switch-mod/src/game/CrossWorldLoad.cpp`,
  the `exeLoadStageHook` lambda (and a new file-local helper).
- **Why (one line):** the pre-arm fired concurrently with the stage load and
  produced `nn::g3d::ResFile` setup races on `al::InitializeThread` — both
  foreign-interior entries crashed; serialization is mandatory (P5 doc §6.1).
- **Approach (decided):** add a file-local helper and call it in
  `exeLoadStageHook` pre-orig, AFTER `firePendingPreload("exeLoadStage")` and
  `universalCrossWorldCheck()`, BEFORE `exeLoadStageHook.orig(self)`:

  ```cpp
  // P5 §6.1: a world-resource load running concurrently with the stage load
  // races nn::g3d ResFile setup on the scene InitializeThread (both walked
  // foreign-interior entries crashed). Block HERE, inside the exe body, until
  // the loader is done — transparent to the nerve step counter (no ticks are
  // skipped, first-step init still runs when orig finally executes). The
  // loader's AsyncFunctorThread + the SZS decompressor threads do not need
  // the main thread to progress. Timeout fails open to orig (the old crash
  // risk, logged loudly).
  constexpr int kHoldTimeoutMs = 30000;
  void holdForWorldLoad() {
      if (!s_isEndLoadWorldResource) return;
      WorldResourceLoader* loader = resolveLoader();
      if (!loader || s_isEndLoadWorldResource(loader)) return;
      const int world = s_getLoadWorldId ? s_getLoadWorldId(loader) : -1;
      int waited_ms = 0;
      while (!s_isEndLoadWorldResource(loader) && waited_ms < kHoldTimeoutMs) {
          hk::svc::SleepThread(10'000'000LL);  // 10 ms
          waited_ms += 10;
      }
      const bool done = s_isEndLoadWorldResource(loader);
      if (done)
          SMOAP_LOG_INFO("[p5-hold] exeLoadStage held %d ms for world %d -> done",
                         waited_ms, world);
      else
          SMOAP_LOG_WARN("[p5-hold] exeLoadStage held %d ms for world %d -> "
                         "TIMEOUT (fail-open, crash risk)", waited_ms, world);
  }
  ```

  Copy the include that `switch-mod/src/ap/ApClient.cpp` uses for
  `hk::svc::SleepThread` (grep its `#include` block). `s_isEndLoadWorldResource`
  is already resolved at install and currently unused — this is its consumer.
  Do NOT touch the destroySceneHeap trigger, the arm bookkeeping, or the
  universal backstop; the hold serializes all of them by construction.
- **Verification:** no host-test surface, no new symbols. State in your
  wrap-up that Devon's walk must show `[p5-hold] ... -> done` followed by a
  clean load on P5 doc §6.6 item 1 (Cap "Precision Rolling" door → 8-Bit
  Chasm Lifts — the exact door that crashed in
  `E:\Ryubin\Logs\crash-entering-8bit-chasm.txt`).

## T2 — stop the Lost softlock sweep from unlocking the world prefix

- **File/function:** `switch-mod/src/game/OdysseyRescue.cpp`,
  `runOdysseySoftlockSweep()`, the "--- Lost Kingdom ---" branch
  (currently ~lines 545–575).
- **Why:** `unlockWorld(getWorldIndexClash())` is the LAST surviving
  unlockWorld caller; per the GameProgressData decomp it monotonically
  unlocks every earlier kingdom AND persists to the save — this produced
  Devon's "Lost unlocked itself and everything before it" globe and polluted
  his save (P5 doc §6.2).
- **Approach (decided):** keep `repairHome` unconditional; guard ONLY the
  unlock:

  ```cpp
  g_fns.repairHome(wr);
  const int clashWorld = g_fns.getWorldIndexClash();
  const int clashBit   = smoap::game::kingdomBitFor("Lost");
  if (isKingdomChainReachedOnly(clashBit, clashWorld)) {
      // Chain-reached-only Lost: departure is governed by the allowance +
      // visited-only bounce; unlocking here is the prefix-overshoot bug.
      SMOAP_LOG_INFO("OdysseyRescue: Lost crashHome → repair "
                     "(unlock SKIPPED, chain-reached-only)");
  } else {
      g_fns.unlockWorld(wr, clashWorld);
  }
  ```

  (`isKingdomChainReachedOnly(int bit, int world_id)` is declared in
  `OdysseyRescue.hpp:167` — same translation unit, call it unqualified or as
  `smoap::game::`. `kingdomBitFor` lives in KingdomUnlock — check the include
  is already present; EntranceShuffleHook uses it as
  `smoap::game::kingdomBitFor`.) Keep the existing throttled heartbeat log
  for the repair itself. Rewrite the branch's comment block: delete the
  "unlocks the world Mario is already in … doesn't perturb" claim (it was
  wrong — the counter is a monotonic prefix) and cite P5 doc §6.2.
- **Verification:** Devon's walk item 7 must show the `unlock SKIPPED` line
  when chaining into Lost, and the globe must NOT list Sand/Lake/Wooded/Cloud
  on a fresh save afterwards. Legit story arrivals are unaffected (Lost is
  already unlocked there → `isKingdomChainReachedOnly` is false → unlock runs
  and is a no-op).

## T3 — lift the Lost/Ruined exemption with the decided story guards

- **Files/functions:**
  `switch-mod/src/game/CrossWorldLoad.{hpp,cpp}` (one new helper),
  `switch-mod/src/hooks/EntranceShuffleHook.cpp`
  (`isChainExemptOverworld` → replaced; `processChainArrival`;
  `routeRemappedCrossWorld`).
- **Why:** Devon's ruling (P5 doc §6.4): lift the exemption. Lost's guard is
  T2 (sweep repairs, never over-unlocks). Ruined's guard is scenario-based:
  pre-dragon arrivals must stay story-managed so the Lord-of-Lightning fight
  arms (the pinned progression Multi-Moon depends on it); post-dragon chain
  arrivals were the true hard strand (no ship, no dragon) and must normalize.
- **Approach (decided):**
  1. In `CrossWorldLoad.hpp/.cpp` add:
     ```cpp
     // Live per-world scenario via GameDataFile::getScenarioNo(worldId)
     // (symbol already resolved as s_getScenarioNoByWorldId). -1 when the
     // symbol or the game_data_file_cache is unavailable.
     int scenarioNoForWorld(int world_id);
     ```
     Body mirrors the scenario lookup already inside `firePendingPreload`
     (lines ~94–102): read `game_data_file_cache`, call
     `s_getScenarioNoByWorldId`, return -1 on any miss.
  2. In `EntranceShuffleHook.cpp` replace `isChainExemptOverworld` with:
     ```cpp
     // P5 §6.4 (Devon ruling): the Lost/Ruined normalization exemption is
     // LIFTED. Lost lifts fully (its guard is the sweep's unlock skip, T2).
     // Ruined stays story-managed ONLY pre-dragon: the Lord-of-Lightning
     // fight must arm (the pinned progression Multi-Moon is earned there)
     // and its vanilla completion repairs the ship — the in-game escape.
     // Post-dragon (quest-recomputed scenario >= 2) chain arrivals normalize
     // like everyone else. Scenario read unavailable (-1) => story-managed
     // (fail toward vanilla behavior).
     bool chainArrivalStoryManaged(const char* dest) {
         const bool ruined =
             std::strcmp(dest, "AttackWorldHomeStage") == 0 ||
             std::strcmp(dest, "BossRaidWorldHomeStage") == 0;
         if (!ruined) return false;
         const int w  = smoap::game::worldIdFromKingdomShort("Ruined");
         const int sc = smoap::game::scenarioNoForWorld(w);
         return sc < 2;
     }
     ```
     Before coding, confirm `"Ruined"` is the short the
     `worldIdFromKingdomShort` table uses (grep KingdomUnlock.cpp; the
     `[chain-arrival] kingdom=...` log printed kingdom shorts like `Lost`,
     `Luncheon`). If the table spells it differently, use the table's
     spelling.
  3. `processChainArrival`: `const bool exempt = chainArrivalStoryManaged(dest);`
     — the rest of the flow (`if (exempt || already_go || world_id < 0) return;`)
     is unchanged. Extend the `[chain-arrival]` log with the Ruined scenario
     when dest is Ruined (or just always append `storyManaged=%d`).
  4. `routeRemappedCrossWorld`: change the B1 condition to
     `if (overworld && !chainArrivalStoryManaged(dest) && s_tryChangeDemoWarp)`.
     The B2 fallthrough (`armCrossWorldPreload`) is unchanged — pre-dragon
     Ruined keeps plain commit + pre-arm (now safe under T1's hold).
  5. Update the comment block at the old `isChainExemptOverworld` site
     (lines ~143–151) to the new semantics.
- **Verification:** Devon's walk item 7 (chain into Lost → normalization runs,
  ship present). Ruined pre/post-dragon is opportunistic — note it in the
  walk instructions but don't block on it.

## T4 — capturesanity OFF must strip AND precollect the capture items

- **File/function:** `apworld/smo_archipelago/hooks/World.py`, next to the
  abilitysanity pair (`_drop_ability_items_if_disabled` /
  `_precollect_ability_items_if_disabled`, lines ~910–950), wired into
  `before_create_items_filler` (~line 1072).
- **Why:** Devon found a moon holding **Jizo** with capturesanity off —
  capturesanity currently drops capture LOCATIONS only; the ITEMS still ride
  the pool (P5 doc §6.5). The abilitysanity pattern is the proven fix shape
  (see `docs/handoff-abilitysanity-precollect-fix.md`).
- **Approach (decided):** add `_drop_capture_items_if_disabled` and
  `_precollect_capture_items_if_disabled`, exact mirrors of the ability pair
  with `"Ability"` → `"Capture"` and option `"abilitysanity"` →
  `"capturesanity"`, with ONE addition in the precollect: skip copies already
  precollected by `_precollect_starting_captures` (it runs earlier, in
  `before_create_items_starting`) so the 3 fixed starters + 1 random starter
  don't double-precollect into spurious dup-coin grants:

  ```python
  already = [it.name for it in multiworld.precollected_items[player]]
  for name in _names_in_item_category(world, "Capture"):
      count = int(name_to_item.get(name, {}).get("count", 1))
      count -= already.count(name)
      for _ in range(count):
          multiworld.push_precollected(world.create_item(name))
  ```

  Call both in `before_create_items_filler` immediately after the
  `_precollect_ability_items_if_disabled` call, with a comment mirroring the
  ability one. NO client change: precollected items ride the normal
  received-items path (the 3 fixed starters prove it — the Switch capture
  gate opens from received captures). Read-only sanity check: confirm
  `client/context.py::_process_received_items` has no capturesanity-specific
  branch that would skip precollected captures.
- **Verification:**
  1. Grep `apworld/smo_archipelago/tests/` for the abilitysanity-off test
     (the one asserting no Ability items in the pool + all precollected) and
     add the capturesanity mirror: capturesanity off ⇒ zero Capture-category
     items in `multiworld.itempool`, every Capture name present in
     `multiworld.precollected_items[player]` at its items.json count
     (starters counted once, not twice), and generation/fill completes.
  2. Full suite: `.venv\Scripts\python -m pytest apworld\smo_archipelago\tests`
     — expect the 1013-passed baseline plus your new tests, zero new failures.
  3. `python scripts\install_apworld.py` (plain, no flags).
  4. State in your wrap-up: **Devon must RESEED** (pool change) and start a
     fresh save before the §6.6 walk.

## T5 — gate the Cap return-scenario floor on the prologue being over

- **File/function:** `switch-mod/src/hooks/CapReturnScenarioHook.cpp`,
  `capArrivalScenarioOverride()`.
- **Why:** the floor is unconditional; with `start_at_cap_peace=false` on a
  fresh vanilla save, exiting the Cap tower during the prologue commits into
  `CapWorldHomeStage` below scenario 2 and the floor force-advanced Cap to
  its peace layout (Devon's note 1; P5 doc §6.5).
- **Approach (decided):** after the `effective >= kCapReturnScenario` check,
  before returning the force, add:

  ```cpp
  // Vanilla-prologue guard (P5 doc §6.5): never force the return layout
  // while the Cap prologue is still in progress. isWorldAlreadyGo(Cascade)
  // is save-backed — true on the cap-peace bootstrap save (the prologue
  // story-drop sets it) and on any vanilla save after the first flight to
  // Cascade; false only mid-prologue. Degraded read (getter unresolved)
  // returns false => floor off; acceptable — the same getter backs the whole
  // chain-return machinery and has resolved on every logged boot.
  if (!smoap::game::isWorldAlreadyGo(
          smoap::game::worldIdFromKingdomShort("Cascade")))
      return -1;
  ```

  Add the needed includes (`../game/OdysseyRescue.hpp`, and whichever header
  declares `worldIdFromKingdomShort` — grep EntranceShuffleHook.cpp's
  includes). Note this automatically gates the `forceAcquireOdyssey` +
  `forceUnlockCascadeDestination` calls too — EntranceShuffleHook only runs
  them when `capSc >= 0` (EntranceShuffleHook.cpp ~742–766); do not touch
  that site. Update `installCapReturnScenarioHook`'s armed log to mention the
  prologue guard.
- **Verification:** Devon's walk item 8 — fresh vanilla save,
  `start_at_cap_peace=false`: exiting the Cap tower must produce NO
  `[cap-return] changeNextStage floor` line and the prologue must play
  vanilla. On the cap-peace bootstrap save the floor must still fire
  (Cascade alreadyGo=1 there).

---

## After the code tasks

1. **Docs:** append an "IMPLEMENTED (session N)" note to
   `docs/plan-p5-cross-world-loads.md` §6 (one line per task, what changed,
   file), and a matching one-liner block to `docs/plan-decoupled-entrances.md`
   under the sixth-session block. Do not rewrite the triage text.
2. **Memories:** update `p5-cross-world-load-crash-class` and
   `p4-chain-return-open-findings` (status lines only: T1–T5 implemented,
   build + §6.6 walk pending, reseed + fresh save required).
3. **Wrap-up message to Devon** must state: build via the CLAUDE.md
   PowerShell block (QUOTE `-DBRIDGE_HOST`), deploy, **reseed** (T4 changed
   the pool), **fresh save** (his current save carries the persisted unlock
   overshoot), then walk `docs/plan-p5-cross-world-loads.md` **§6.6** — the
   routes there are valid for a reseed only if the entrance layout is
   re-rolled, so tell him to re-derive item routes from the NEW spoiler's
   entrance section if the seed changes (the §6.6 log expectations stay
   valid verbatim; only the door names move).

## Explicitly OUT of scope (do not attempt)

- Making chain kingdoms LISTED on the globe — ruled an accepted interim gap;
  the seam (StageSceneStateWorldMap) is undecompiled and needs a research
  session (P5 doc §6.2).
- Finding 11's story-launch verdict — that's Devon's walk, not code.
- Any wire-format or slot_data change — none of T1–T5 needs one.
- Committing anything. Devon reviews the working tree himself.
