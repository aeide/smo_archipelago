# Handoff: entrance shuffle — cross-kingdom subarea loads with NO Mario / no entry pipe (softlock)

**Recommended model: Fable 5 (or Opus 4.8 if unavailable).** This is the hardest of the
current batch: cross-layer C++ hook debugging where every wrong guess costs Devon a full
build → deploy → in-game-repro cycle. CLAUDE.md's "READ THE DECOMP BEFORE PICKING A HOOK
CHOKEPOINT" invariant exists because cheaper models burned cycles guessing here before.
Maximum reasoning per in-game test is the whole economy of this task.

## Symptom (Devon, 2026-07-17)

Entered a Sand Kingdom subarea entrance (`SandWorldPressExStage` / id `arijigoku`, from
`SandWorldHomeStage`); the shuffle remapped it to the Luncheon subarea
`CapAppearLavaLiftExStage` (id `LavaLiftExdokan`). The stage loaded but **neither Mario
nor the entry pipe ever spawned** — softlock, reset recovered. Full log:
[logs/luncheon-subarea-no-mario-2026-07-17.log](logs/luncheon-subarea-no-mario-2026-07-17.log).

Key lines:

```
[entrance:file] stage='SandWorldPressExStage' id='arijigoku' isReturn=0 scenario=-1 cur='SandWorldHomeStage'
[entrance:remap-APPLIED] dest='CapAppearLavaLiftExStage'/'arijigoku' cur='SandWorldHomeStage' -> stage='CapAppearLavaLiftExStage' id='LavaLiftExdokan'
[p5-prearm] ARMED world=10 dest='CapAppearLavaLiftExStage' (resident=2)
[p5-worldreq] DESTROY resident_was=2 -> -1 #1
[p5-worldreq] request world=10 scenario=1 (resident_was=2) -> LOAD STARTED #4
[p5-hold] exeLoadStage held 1490 ms for world 10 -> done
[p5-worldreq] request(plain) REDIRECTED stale=2 -> 10 (resident_was=10, stage_world=10) -> LOAD STARTED #3
[p5-reswatch] resident=10 engineCurWorld=2 #3        <-- mismatch AFTER the redirect
```

## Hypotheses (rank/verify, don't assume)

1. **`engineCurWorld` stayed 2 (Sand) while resident world became 10 (Luncheon).**
   The final `p5-reswatch` line shows the engine's current-world index was never
   updated. If scenario/placement resolution keys off engineCurWorld, the scene may
   have initialized against the wrong world's scenario data → placement/actor
   creation (entry dokan + PlayerActor) silently fails. Find what consumes
   engineCurWorld and whether the p5 machinery is supposed to sync it.
2. **Entry id `LavaLiftExdokan` doesn't exist in the scenario that was loaded
   (scenario=1 was forced; the original request carried scenario=-1).** If the
   destination's PlayerStartInfo/appear point for that id is scenario-conditional,
   Mario has no start point. Check how the remap table chose scenario for
   cross-kingdom subarea entries.
3. **`CapAppear*` stage class is special.** These are scarecrow-triggered subareas;
   their vanilla entry may run appear/demo logic that a plain ChangeStageInfo entry
   skips. Check whether the in-game-validated P7 walk
   ([devon-p7-entrance-testing-results.md](devon-p7-entrance-testing-results.md),
   APPLY-MODE table) ever covered a **cross-kingdom** entry into a `CapAppear*`
   stage — if not, this is an untested stage class, and other `CapAppear*`
   destinations in the current seed are probably also softlocks.

## Method (in order — desk work before any build)

1. Read `switch-mod/src/hooks/EntranceShuffleHook.cpp` end-to-end: how entry rows
   rewrite stage/id, what happens to `scenario`, what the p5-prearm/worldreq/hold/
   redirect machinery does, where engineCurWorld is (and isn't) written.
2. Read the P7 docs: [p7-entrance-shuffle-spike.md](p7-entrance-shuffle-spike.md),
   [devon-p7-entrance-testing-results.md](devon-p7-entrance-testing-results.md).
   Identify the nearest WORKING analogue (cross-kingdom subarea entry that passed)
   and diff its log signature against this one.
3. Decomp read (WebFetch raw OdysseyDecomp) BEFORE proposing a fix:
   `ChangeStageInfo`, scenario resolution on stage load, player start/appear-point
   lookup, and whatever consumes the engine current-world index. Per CLAUDE.md:
   confirm the decision flow in the decomp, don't guess a chokepoint.
4. Only then propose the minimal fix + added diagnostics (log the start-point
   lookup result so a future miss is visible instead of a silent softlock), build
   via `scripts/build_switchmod.py` on Windows (QUOTE `-DBRIDGE_HOST`; verify
   CMakeCache `BRIDGE_HOST` is the full dotted IP), and hand Devon a precise
   repro script: which entrance to take, what log lines prove the fix.

## Guardrails

- Switch-mod tier only — no apworld rebuild/re-seed needed unless the fix turns
  out to require slot_data changes (flag that loudly if so).
- File reads via Read/Grep tools only (stale shell mount, CLAUDE.md).
- Don't touch the validated exit-row logic (`returnPrevStage` / `changeNextStage`)
  or the `dest==cur` moon-rock guard — the bug is on the entry path.
- If the root cause is hypothesis 3, also enumerate which remap-table rows land on
  `CapAppear*` stages and propose either a fix or a shuffle-pool exclusion.

## Session prompt (paste to start)

> Read E:\smo_archipelago\CLAUDE.md in full (stale-shell-mount warning, switch-mod
> build loop, decomp-before-chokepoint invariant), then
> docs/handoff-entrance-subarea-no-mario.md and the log it references, and run the
> investigation in the order the handoff specifies: EntranceShuffleHook.cpp →
> P7 docs (find whether cross-kingdom CapAppear* entry was ever validated) →
> OdysseyDecomp reads for ChangeStageInfo/scenario/player-start resolution. Rank
> the three hypotheses with evidence before writing any code. Deliver: root-cause
> writeup, minimal fix + added start-point diagnostics in the hook, and an exact
> in-game repro/verification script for Devon (he runs builds and Ryujinx). Do NOT
> guess-and-build — every in-game test costs a full cycle.
