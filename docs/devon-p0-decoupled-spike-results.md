# P0 spike results — cross-kingdom overworld landing (decoupled entrance rando)

**Verdict: PASS.** Approach A (reuse an existing door-mouth transition to land in a
foreign kingdom's overworld) works. Devon's walk on 2026-07-06 confirmed Mario lands
in a chain-reached kingdom in a usable state, and the round-trip via save+quit+reload
degrades gracefully (reverts to the last officially-unlocked kingdom) rather than
crashing or corrupting state. Full method: [handoff-decoupled-p0-spike.md](handoff-decoupled-p0-spike.md).
Code: `kP0DecoupledSpike` in [EntranceShuffleHook.cpp](../switch-mod/src/hooks/EntranceShuffleHook.cpp).

## False start: first walk used an active entrance-shuffle seed

The first attempt connected to a save/slot whose seed had `entrance_shuffle` rolled
with a real, populated table (48 remap entries applied at HELLO). That table already
had a row keyed on `PushBlockExStageEnt` (the vanilla Cap→Push-Block-Peril entry)
redirecting to `Note2D3DRoomExStage`/`onpu` — a real shuffled door, unrelated to the
P0 spike. Walking into Push Block Peril landed in that shuffled 2D room instead of the
real Push Block Peril, so there was never a `PushBlockExStage` exit pipe to fire the
spike from. This also surfaced a latent logging bug: `processEntranceRemap`'s `dest`
is a pointer into the live `ChangeStageInfo` string buffer, not a copy — by the time
`applyEntranceMutation` logs `dest` in its `-APPLIED` line, the buffer has already been
overwritten, so `-APPLIED` lines show the *post*-mutation dest, not the pre-mutation
one. Cosmetic only (pre-mutation dest is available one line earlier from the paired
`[entrance:file]` log), not fixed as part of this spike.

**Fix:** re-tested on a slot connected to a seed with `entrance_shuffle` off (`[entrance]
applied 0 remap entries`), so the real table stayed empty and only the two hardcoded
spike rows applied.

## The real walk (2026-07-06, correct seed)

Entering Push Block Peril from Cap — vanilla, untouched by the spike (no entry row):
```
[entrance:file] stage='PushBlockExStage' id='PushBlockExStageEnt' isReturn=0 scenario=1 cur='CapWorldHomeStage'
```

Exiting via the pipe — Row 1 fires:
```
[entrance:try]  stage='CapWorldHomeStage' id='PushBlockExStageEntDokan' isReturn=0 scenario=-1 cur='PushBlockExStage'
[entrance:file] stage='CapWorldHomeStage' id='PushBlockExStageEntDokan' isReturn=0 scenario=-1 cur='PushBlockExStage'
[entrance:p0-spike] dest='CapWorldHomeStage' cur='PushBlockExStage' scenario=-1 -> stage='LavaWorldHomeStage' id='shop'
[entrance:p0-spike-APPLIED] dest='LavaWorldHomeStage'/'PushBlockExStageEntDokan' cur='PushBlockExStage' -> stage='LavaWorldHomeStage' id='shop'
```

Landing confirmed by the arrival poll and diagnostics:
```
[pump] arrival status kingdom=Luncheon stage=LavaWorldHomeStage
OdysseyRescue/diag: stage=LavaWorldHomeStage kingdom=Luncheon exist=0 activate=1 launch=1 crash=0 level=3
OdysseyRescue/warpdemo: stage=LavaWorldHomeStage kingdom=Luncheon worldId=10 alreadyGo=0 firstNext=0 fwdWarpDemo=0 playWarpDemo=0 enterFirst=0
```

## Checklist outcomes

1. **Enter Push Block Peril from Cap** — vanilla, unaffected. ✅ (expected)
2. **Exit via pipe → Luncheon shop door-mouth** — `[entrance:p0-spike]` fired, landed
   at the Luncheon shop exterior. ✅
3. **Kingdom sane?** Scenario is the initial (pre-peace) lava layout, as expected for
   a kingdom reached before any story progress there. HUD/moon counter behaved
   normally; walking around, moon collection, and checkpoints all worked (Devon
   collected a music-note pickup and walked through nearby costume doors with no
   issues). `reportArrival` correctly told the tracker `kingdom=Luncheon`.
   **Odyssey absent** (`exist=0`) — expected cosmetic gap, not a failure (Phase 5
   fidelity item if approach B is ever pursued).
4. **Retrace (Row 2, shop door → Push Block Peril)** — **confirmed working in a
   follow-up walk (still on the spike-ON build, before it was flipped off).** Walking
   into the Crazy Cap shop door landed Mario back inside
   Push Block Peril, at the spot tagged with entry id `PushBlockExStageEnt` (the
   vanilla main-entrance marker — Row 2 rewrites to that id, not the pipe's).

   **But this surfaced a real bug, and it's the interesting finding of this spike.**
   From that landing spot, walking back out through Push Block Peril's **main
   entrance door** also redirected to Luncheon — it should have gone to Cap (the
   vanilla entrance/exit pair). Root cause: **Row 1 matches on `cur ==
   "PushBlockExStage"` alone**, with no check on the exit's `id`. Push Block Peril
   has two exits with two different ids — the main door (`PushBlockExStageEnt`) and
   the pipe (`PushBlockExStageEntDokan`, confirmed in the §"real walk" log above) —
   and Row 1's `cur`-only match grabs *both*, redirecting all traffic out of the
   stage to Luncheon regardless of which door Mario used.

   Devon's expected topology for a correct two-route symmetric edge:
   - Cap → PBP entrance → **leave PBP via the exit pipe** → Luncheon shop exterior
   - Luncheon shop door → **appear at PBP's exit-pipe spot** → leave PBP via the
     **main entrance** → back to Cap

   This is **not a P0 failure** — it's exactly the ambiguity
   [Phase 2 (compound-key exit lookup)](plan-decoupled-entrances.md#phase-2--switch-compound-key-exit-lookup-the-from_parent-work-order)
   already exists to fix, now confirmed empirically instead of just reasoned about:
   `lookupEntranceRemap`'s exit branch needs the exit's `entry_id` (or equivalent) as
   a second match key, not just `cur`, so a multi-exit stage can route different
   physical exits to different destinations. The two-row P0 spike wasn't written to
   do this (the handoff scoped it to a single hardcoded row keyed on `cur` alone,
   deliberately minimal) — fixing it properly is Phase 2's job, not a P0 patch.
5. **Save + quit + reload while standing in Luncheon** — Mario reloaded into **Cap
   Kingdom**, not Luncheon. No crash, no corruption; Devon confirmed this is an
   acceptable outcome, not a failure. Likely explanation: the spike only rewrites the
   transient `ChangeStageInfo` for one load — it never touches whatever persistent
   save field records "current/last-unlocked world," so a reload falls back to the
   last kingdom Mario reached through the normal (unlock-gated) path. This is exactly
   the open question §3a of [plan-decoupled-entrances.md](plan-decoupled-entrances.md)
   already flagged ("how does peace/scenario state compose for a chain-reached
   kingdom") — now confirmed as a real, reproducible behavior rather than a guess:
   **a chain-reached kingdom does not durably become Mario's "current world" for
   save purposes.**
6. **Leave Luncheon by other means** — not applicable/not attempted (no Odyssey to
   board); no softlock observed from standing in Luncheon.
7. **KingdomOrderGate / detour-gate interference** — none observed in the logs. Origin
   `PushBlockExStage` is not a HomeStage, so `kingdomShortFromHomeStage` returns null
   and both gates no-op as predicted in the handoff.

## Pass/fail call

**PASS for approach A's core question.** Mario lands in a foreign, chain-reached
kingdom via an existing door-mouth transition in a sane scenario state, with no
crash and no corruption. Both directions of the port edge work (exit pipe → Luncheon,
shop door → back into PBP). Two real costs surfaced, both design inputs rather than
blockers:
- **Save/reload** doesn't preserve a chain-reached kingdom as Mario's "current world"
  (reverts to Cap) — Phase 3a's design doc needs to decide how to handle this.
- **Multi-exit ambiguity** (the `cur`-only match grabbing both of PBP's exits) is
  exactly what Phase 2's compound-key fix is for — now confirmed as a real, reproduced
  bug rather than a theoretical one. (Retrace testing above happened before the spike
  flag was turned back off, so this is real data from the live spike build, not a
  post-hoc guess.)

Feasibility estimate revised from ~65% up — see
[future-feasibility-decoupled-entrance-randomizer.md](v3-feasibility/future-feasibility-decoupled-entrance-randomizer.md)
for the updated write-up.

## Wrap-up

`kP0DecoupledSpike` flipped back to `false` in `EntranceShuffleHook.cpp` (kept, commented,
pointing at this doc) and the switch-mod rebuilt + redeployed to Ryujinx so normal
play (and any future coupled entrance-shuffle testing) isn't affected by the two
hardcoded rows.
