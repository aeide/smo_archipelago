# Handoff — P4 walk crash: FrameHeap abort re-entering Cascade post-moon-rock

> **RESOLVED (2026-07-08) — root cause + fix below; awaiting Devon's rebuild
> + retest.** Devon's repro matrix: R1 (fresh boot → PBP door) crashes iff
> Broode is DEFEATED, clean if undefeated; R2 (fly in normally) clean; R3
> (beat Broode → PBP door) crashed. Fresh-boot crash kills hypothesis #3
> (fragmentation); R2-clean + R3-crash-with-the-force-inactive kill #2's
> forced-scenario framing (the broode force is cabin-gated and never fired on
> these door commits). **Root cause: the door-entry ChangeStageInfo's own
> explicit `scenario=1`.** Remapped onto a kingdom HomeStage it becomes the
> scenario-jump load input for the whole kingdom; whenever the kingdom's live
> scenario is beyond 1 (Broode beaten / moon rock open) the mismatched commit
> loads an inconsistent, oversized placement set and exhausts stage-load
> memory — killing whichever allocator loses first. Two observed victims of
> the same pressure: the game's `sead::FrameHeap` on FileLoadThread
> (2026-07-07, this doc's original stack), and the MOD's own heap
> (2026-07-08 log: `smoap-worker` NULL-deref — `pumpOnce` →
> `Status.stage_name = "WaterfallWorldHomeStage"`, 23 chars > libc++'s
> 22-char SSO → `operator new` returned NULL mid-load → `memcpy(NULL,…)`;
> symbolized against the deployed `smo_archipelago.nss`, ELF integrity
> verified). Flight arrivals are clean because the world-warp path recomputes
> the scenario — same reason pipe exits (`scenario=-1`) always loaded clean.
>
> **Fixes shipped (switch-mod only, no re-seed):**
> 1. `EntranceShuffleHook::neutralizeScenarioForOverworldTarget` — every
>    remap-APPLIED commit whose FINAL target is an overworld HomeStage gets
>    `ChangeStageInfo.mScenarioNo → -1` (the ctor default, "engine resolves
>    the live scenario"; per OdysseyDecomp `ChangeStageInfo.h` +
>    `findScenarioNoByList`). Broode/cap-return overrides run after and still
>    force when their gates fire. Also kills the plan doc's
>    "scenario drag-down on a progressed kingdom" risk at the root.
> 2. `Status` (ApProtocol) switched to fixed char buffers so the worker's
>    pump can never allocate — a starved mod heap can no longer crash the
>    worker. Wire format unchanged; host `test_protocol` green.
>
> **Devon retest:** rebuild switch-mod → repeat R1 with Broode defeated
> (expect: `[entrance:remap-scenario] stale explicit scenario 1 -> -1` then a
> clean load at `WindBlowExStart` in the kingdom's true scenario). If it
> STILL crashes, the residual suspect is the door-path scene-heap shape →
> escalate to P5 approach B per the work order below. This session also
> shipped the chain-return flight scope in the same build — see
> plan-decoupled-entrances.md P4 section for its test matrix.

**For the next session on the decoupled entrance randomizer.** Context chain:
[plan-decoupled-entrances.md](plan-decoupled-entrances.md) (read the "P4
findings (2026-07-07)" section first — this doc is its continuation),
[handoff-decoupled-p3e-slot-data.md](handoff-decoupled-p3e-slot-data.md),
[devon-p0-decoupled-spike-results.md](devon-p0-decoupled-spike-results.md).
CLAUDE.md's standing rules apply in full (disk-truth file tools only, builds +
Generate on Windows, `install_apworld.py` after apworld edits, never commit
Nintendo IP).

## Where the feature stands (end of 2026-07-07 session)

All P0–P3f code is done and live-validated up to the crash below.
`PORT_SHUFFLE_SHIPPABLE = True` is flipped **locally only** (uncommitted, per
the P3e checklist — the flip's guard-site updates in
`test_port_shuffle_readiness_flag_defaults_off`, the option docstring, and the
OptionError text are all still pending). P3b–3f + this session's client fix
are ALL uncommitted — agree commit slicing with Devon.

Validated in-game this session (seed 11314520684955636324, slot "Aeide"):

- **§3e item-7 client fix** (see plan doc): the empty coupled mirror was
  shadowing the decoupled push (`applied 0 remap entries`). Fixed in
  `client/switch_server.py` (prefer configured AND non-empty mirror) + 2
  regression tests in `test_switch_server.py`. After the fix: 288 rows
  delivered in 6 chunks, confirmed applied.
- **Entry `from_id` exact tier + involution symmetry:** Cap "Frog Pond" door →
  Rumbling Floor Cave (Seaside interior) in AND back out. PASS.
- **Door→door cross-kingdom hop:** Cap PBP door → Gusty Bridges door mouth
  (Cascade). Row applied byte-correct. PASS with two findings (below).
- **Retrace edge:** Gusty Bridges side → PBP door mouth in Cap. PASS.

Findings/rulings recorded in the plan doc's P4 section (read them there in
full): (1) chain into an unvisited NEXT-story-kingdom triggers the engine's
arrival flow (`fwdWarpDemo=1`), marker ignored — P0's Luncheon control had
`fwdWarpDemo=0` and honored the marker; suspects (one-time first-visit
classification vs door-entries' explicit `scenario=1`) not yet separated.
(2) Scenario-gated target markers (Gusty Bridges is `{CascadeDeparture()}`-
gated) fall back to the kingdom default spawn — not a logic bug, but it breaks
the retrace guarantee while the door doesn't exist. (3) **Devon's rulings:**
free matching stays (no doors-must-lead-to-interiors constraint);
**chain-return flight is REQUIRED scope** — from a chain-reached kingdom the
Odyssey must allow flying back to ALREADY-VISITED kingdoms only.

## The crash (open blocker)

**Repro (1 occurrence):** ~30 min into the session — Frog Pond round trip →
Cap Tower cleared → PBP door → Cascade (arrival flow) → AP-granted Cascade
moons → opened the moon rock (moon pipes spawned) → Gusty Bridges entrance →
Cap (clean retrace) → **re-entered the PBP door → guest abort during the
Cascade load.**

**Guest stack (Ryujinx, 00:32:47):** `nn::diag::detail::AbortImpl` ←
`sead::system::HaltWithDetail` ← **`sead::FrameHeap::tryAlloc`** ←
`sead::ParallelSZSDecompressor::tryDecompFromDevice` ←
`sead::ResourceMgr::tryLoad` ← `al::ArchiveEntry::load`, thread
`FileLoadThread`. I.e. a frame-heap allocation failure while decompressing a
stage resource archive during the remapped commit into
`WaterfallWorldHomeStage`.

**Key delta vs the THREE earlier successful identical loads:** the moon rock
is now open (extra actors/archives in the stage). Also true on every one of
these commits: the CascadeBroodeRespawnHook forces `ChangeStageInfo.scenario
→ 1` (the Multi-Moon is still locally uncollected — AP grants don't set local
shines), and the door-entry ChangeStageInfo carries explicit `scenario=1`.

**Hypotheses, ranked:**

1. **Frame-heap exhaustion on the HomeStage→HomeStage door-path load.** The
   vanilla kingdom→kingdom transition is the world-warp path (different
   teardown/heap arrangement); door transitions normally load small subareas.
   A full kingdom loaded through the door path may have marginal heap
   headroom — the moon-rock-added resources pushed it over.
2. **Forced scenario 1 × moon-rock-open state loads an inconsistent/oversized
   placement set.** CLAUDE.md's MoonRockHook notes warn the moon-rock
   scenario's re-init path is delicate; forcing scenario on a commit into a
   moon-rock-active kingdom may combine both scenarios' actor sets.
3. **Cumulative heap fragmentation** from many cross-kingdom chain loads in
   one session (P0's single Cap→Luncheon load was fine).

## What the next session needs from Devon (cheap, no builds — do these first)

Repro matrix, fresh Ryujinx boot each time, same save:

- **R1:** boot → straight to PBP door → enter. Crash? (kills/keeps #3
  fragmentation; if it still crashes on a cold boot, it's #1/#2)
- **R2:** boot → fly to Cascade via the Odyssey (normal flight arrival).
  Crash? (if yes, the problem is Cascade's post-moon-rock state generally,
  not the door path — reweights toward #2)
- **R3 (only if R1 crashes and R2 doesn't):** collect the Cascade Multi-Moon
  locally (beat Broode) so broode-respawn stops forcing scenario 1, then
  re-enter the PBP door. Crash? (isolates the forced-scenario contribution)
- Attach the FULL Ryujinx log of any crashing run (the tail from the last
  `[entrance:remap-APPLIED]` onward at minimum; note copy-paste of these logs
  has been flaky — a fresh small `tail.txt` works).

## Next-session work order (after the repro data)

1. Diagnose per the matrix. If #2/scenario: scope the broode-respawn force
   (skip forcing while the moon-rock scenario is active — mirror
   MoonRockHook's own peace-gate rule; small switch-mod change). If #1/heap:
   READ THE DECOMP FIRST (CLAUDE.md rule) on the scene-heap setup difference
   between `changeNextStage` door loads and the world-warp path — and weigh
   jumping straight to **P5 approach B**
   (`tryChangeNextStageWithDemoWorldWarp` routing for overworld-mouth
   targets), which plausibly fixes the arrival-flow finding, the
   default-spawn cosmetics, AND the heap shape in one move.
2. **Chain-return flight scope** (Devon ruling, required): first determine
   what blocked Odyssey boarding in chain-reached pre-Broode Cascade — Devon
   AP-granted moons and subsequently DID leave via... (unconfirmed — ASK
   whether the Odyssey worked after the moon grant, and whether the second
   PBP entry skipped the kingdom splash; both answers are still outstanding
   from this session). Restriction to visited kingdoms rides the existing M7
   gate machinery — verify chain arrivals set the visited bit.
3. Still open from the P3e checklist: Lake town-zone `cur=`/`dest=` log check
   (`ZONE_STAGE_ALIAS` seam, pure data), walk 3 (coupled `simple`-seed
   regression), Mysterious Clouds → PBP interior → both exits diverging (the
   P2 multi-exit capability proof — was queued when the crash hit).
4. Then: real `PORT_SHUFFLE_SHIPPABLE` flip + its three guard sites, commit
   slicing for P3b–3f + the client fix + docs, and the rest of the P4 matrix
   (save/load mid-chain, moon pipes, early+late chain-reached kingdoms,
   scenario-drag-down check on a progressed kingdom).

## Suggested opening prompt for the next session

> Read CLAUDE.md, then docs/plan-decoupled-entrances.md (the P4 findings
> section) and docs/handoff-p4-cascade-reentry-crash.md. I've run the repro
> matrix from the handoff: R1=..., R2=..., R3=... [attach crash log tail if
> any]. Also: the Odyssey [did/didn't] work after the moon grant, and the
> second PBP entry [did/didn't] show the kingdom splash. Diagnose the crash
> and proceed per the handoff's work order.
