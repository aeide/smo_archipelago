# Handoff: entrance shuffle — cross-kingdom subarea loads with NO Mario / no entry pipe (softlock)

## ✅ RESOLVED 2026-07-17 — root cause found, minimal fix landed (apworld-only, NO reseed)

**Root cause (hypothesis 2, refined — NOT 1 or 3).** The decoupled port shuffle
routed the inbound Sand entrance to arrive at `CapAppearLavaLiftExStage` with
arrival id `LavaLiftExdokan` — the **switch-gated GOAL pipe** of Luncheon's
"Volcano Cave Cruising", not an entrance. On arrival SMO places Mario at the
placement object whose `ChangeStageId` matches the arrival id (the exact
mechanic already documented in `extract_entrance_stages.py`'s
`PRIMARY_EXIT_OVERRIDE` note). That object (`obj650`, romfs-verified in all 15
scenario slots) carries a `SwitchAppear` link, so it is **not placed until the
in-stage switch is flipped** — i.e. after completing the course. On a fresh
arrival the switch is off, the id resolves to nothing, and the stage loads with
**no PlayerStartInfo and no entry pipe** → the observed softlock. Its parent-side
mouth (`obj5660` in `LavaWorldHomeStage` scenario 7) is `IsExitOnly=true`,
confirming the same thing from the overworld side: `LavaLiftExdokan` is a
one-way emergence pipe, never a walkable entrance.

- **Hypothesis 1 (engineCurWorld=2) ruled out**: the world loaded fine — all 76
  objects across every scenario slot are present in the romfs. The
  `[p5-reswatch] resident=10 engineCurWorld=2` line is the EXPECTED
  stale-bookkeeping artifact the T-A redirect (`CrossWorldLoad.cpp`) is designed
  for; scenario/placement resolution succeeded. Only the arrival start-point +
  entry pipe (both keyed on the gated `obj650`) failed.
- **Hypothesis 3 (`CapAppear*` special) ruled out**: `CapAppearExStage`
  (Mysterious Clouds) was validated cross-kingdom in the P7 walk. `CapAppear` is
  a gameplay prefix, not an arrival class. The distinguishing factor is the
  switch-gated arrival marker, nothing about the stage class.

**Why the coupled P7 walk never hit this**: coupled (stage-level) shuffle uses
each subarea's `primary_entry` (the ungated `LavaLiftEx`). Only the decoupled
(port/mouth) shuffle can route an arrival to a specific *non-primary* mouth —
and `entrance_stages.json` mislabels the exit-only/switch-gated mouths as
entry-capable because `extract_entrance_stages.collect_doors` ignores
`IsExitOnly` (parent side) and `SwitchAppear` (interior side).

**Fix (landed, apworld-only)** — `apworld/smo_archipelago/port_graph.py`:
`GATED_INTERIOR_ARRIVAL` lists the `(interior_stage, ChangeStageId)` markers that
never spawn Mario; `build_port_graph` drops such a door from the pool **only
while its subarea keeps another entry-capable door** (connectivity-preserving —
a sole-entry subarea like Shards Under Siege's `taxi` is kept + warned, not
stranded). The confirmed culprit `LavaLiftExdokan` has a safe sibling
(`LavaLiftEx`), so its door drops; the subarea stays reachable. Provenance /
regeneration: `scripts/detect_gated_arrival_markers.py` (romfs-gated, IP-safe,
independently reproduces the 4-marker set). Tests: 117 entrance/port tests green
(`test_port_graph` + `test_port_matching` + `test_entrance_shuffle`).

**Ships with NO reseed and NO switch-mod rebuild.** The decoupled remap rows are
compiled client-side at connect (`switch_server._compile_decoupled_rows` →
`build_port_graph` → `compile_port_remaps`) from the bundled data; a mouth the
rebuilt graph no longer pools is dropped from the matching **both ends**
(existing drift path), so the offending door reverts to vanilla.

### Devon's repro / verify (one controlled pass)
1. `python scripts/install_apworld.py` — rebundle the apworld (picks up the
   `port_graph.py` fix; no `--bundle-*` flags needed).
2. Reconnect the SMOClient to AP (Click-Connect). It recompiles + re-ships
   `entrance_map`. Watch the client log for a line like
   `[entrance] N/M port-matching mouths unresolved ... (shipping … rows)` — the
   dropped `LavaLiftExdokan` pair is the expected delta.
3. In-game, walk the **same Sand door** that previously warped to Luncheon's
   Volcano Cave goal pipe. It should now go to its **vanilla Sand destination**
   (the softlock edge is gone) — Mario + entrance present, no softlock.
4. A fresh seed excludes the door from the roll entirely (cleaner than the
   drift-drop, same end state).

### Open follow-ups (not softlocks; left for a deliberate pass)
- **The 42 exit-only overworld mouths (`ow!enter`) wrongly tagged `entry`**: these
  create *dead* shuffle edges (Mario can't walk into an `IsExitOnly` pipe) — and,
  because the roller currently TREATS them as entrances, a roll can make one the
  sole directed route into a subarea, a latent reachability risk. **A blanket fix
  was ATTEMPTED 2026-07-17 and reverted** — it does NOT work as a drop-in.
  Approach tried: `extract_entrance_stages.collect_doors` capture `IsExitOnly` →
  emit `enterable` per door_mouth → `build_port_graph` gate `ow.ingest` on it.
  Correctly reclassified all 42 (romfs-verified: Ice Cave enters via `arijigoku`
  not `arijigoku1/2`; Jaxi Driving via `aaa` not `run00`), tests updated, extract
  drift-clean. BUT removing 30 overworld ingest mouths converts ~30 interior
  mouths from entry-capable → far-side, dropping the entry-capable supply below
  what `port_matching.directed_full_interior_strands` needs: **0/200 single rolls
  and 0/60 seeds were directionally solvable** (widespread strands across many
  kingdoms). The `roll_port_matching` directed model DEPENDS on counting these
  exit-only mouths as entrances. So the real fix requires a **port-matching roller
  rework** — model the emerge-edge (walking into the interior EXIT pipe →
  emerging at the overworld mouth is a real directed root-edge the current model
  ignores once the overworld mouth is unpooled) so directed reachability is
  satisfiable from real entrances alone. That is a design task + fresh-seed
  generation + a walk, not a quick fix. The `enterable`/`IsExitOnly` extraction
  work + the 42-mouth romfs-verified set are the starting point; detector for the
  set: `scripts/detect_gated_arrival_markers.py` (extend for `IsExitOnly`) and the
  `ow!enter` lines in the 2026-07-17 session's safety scan.
- **Sole-entry gated subareas** (`taxi` / Shards Under Siege, `SnowUGExit` /
  Shiveria, `ppp` / Wedding Room): kept pooled with a warning because dropping
  them strands the interior. `taxi` is an on-rails ride, not a plain pipe warp —
  its true arrival mechanic needs an in-game walk before we know if it softlocks.
- **In-game start-point-miss diagnostic**: deferred. The arrival chokepoint
  (`PlayerStartInfoHolder::tryFindInitInfoByStartId`) is NOT decompiled, so a
  switch-mod hook would violate the "read the decomp before picking a chokepoint"
  rule. The gen/client-time guard above PREVENTS the class instead of logging it,
  which is strictly better; an in-game hook needs sail symbol-verification first.

---


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
