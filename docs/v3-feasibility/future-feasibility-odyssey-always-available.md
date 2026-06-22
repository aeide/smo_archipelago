# Odyssey always present + usable in any visited overworld (Devon, 2026-06-22)

**Goal.** No matter which overworld kingdom Mario is standing in, as long as it's
a kingdom he's already **unlocked/visited**, the **Odyssey must be parked and
boardable** so he can always open the world map and fly back to an earlier
kingdom. This is first a **safety net** — Devon hit a seed where he wound up in
**Bowser's Kingdom overworld extremely early and the Odyssey simply was not
there**, so there was no way to leave; collecting a moon would have fully
stranded the save and a hard reset was the only escape — and second a
**prerequisite for full entrance randomization**, where you can drop into an
overworld via a shuffled door/pipe at a scenario state the vanilla arrival flow
never produces.

**Status: investigated, NOT started. Estimate ~85% feasible, Low–Medium effort.**
This is a near-direct generalization of the **already-shipped `OdysseyRescue`
module** ([switch-mod/src/game/OdysseyRescue.cpp](../../switch-mod/src/game/OdysseyRescue.cpp)),
which today force-repairs the Odyssey in exactly one kingdom (Lost) by calling
SMO's own named state-machine entry points from a throttled per-frame sweep. The
machinery, the chokepoint, the symbol-resolution scaffold, and the per-frame call
site **all already exist** — the work is widening the sweep from one state in one
kingdom to "the Odyssey is flightworthy in any visited overworld," plus careful
gating so it never fires during the intro/story states where a grounded Odyssey
is intentional.

---

## How it works today (disk-truth reads this session)

The Odyssey ("Home") is a named SMO state machine fully exposed as
`GameDataFunction::` free functions over `GameDataHolderAccessor`/`Writer`
([GameDataFunction.h:454-466, 412-413](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataFunction.h#L454)):

| Query | Mutator | Meaning |
|---|---|---|
| `isExistHome` | — | Odyssey exists in the current scene |
| `isActivateHome` / `getHomeLevel` | `activateHome` / `upHomeLevel` | Odyssey activated (boardable) / upgrade tier |
| `isLaunchHome` | `launchHome` | Odyssey has been launched / is flightworthy |
| `isCrashHome` | `crashHome` / `repairHome` | Lost-Kingdom "in disrepair" grounding |
| `isBossAttackedHome` | `bossAttackHome` / `repairHomeByCrashedBoss` | Ruined Lord-of-Lightning grounding |

These are the **same `GameDataFunction` entry points the project already drives**.
The shipped `OdysseyRescue` resolves five of them by mangled name via
`hk::ro::lookupSymbol` (cached in module-local fn-pointers) and, from a per-frame
sweep on `drawMain` throttled to ~60 frames
([main.cpp:230-239](../../switch-mod/src/main.cpp#L230)), does:

```cpp
if (isCrashHome(acc)) {                       // Odyssey grounded
    if (currentStage == "ClashWorldHomeStage") // Lost specifically
        repairHome(wr); unlockWorld(wr, getWorldIndexClash());
    else
        repairHome(wr);                        // stray mid-cinematic crash
}
```

So the load-bearing pattern Devon's request needs — *detect a bad Odyssey state in
the current overworld and force it good via SMO's own functions, from an
already-running throttled sweep* — is **already in the codebase and validated
in-game** (the Lost softlock fix). Two existing facts make the generalization
land cleanly:

- **A "visited" signal already exists.** `ApState::visited_kingdoms` is a sticky
  bitset OR'd every frame from `getCurrentWorldIdNoDevelop`, used by the M7
  kingdom-order gate ([KingdomOrderGate.hpp:18-21](../../switch-mod/src/game/KingdomOrderGate.hpp#L18)).
  That answers "has Mario actually played in this kingdom?" — exactly the
  unlocked/visited predicate the request is scoped to.
- **An overworld-stage classifier already exists.** `kingdomShortFromHomeStage()`
  ([KingdomUnlock.hpp:60-64](../../switch-mod/src/game/KingdomUnlock.hpp#L60)) maps a
  `*WorldHomeStage` name to a kingdom short name (nullptr for non-overworld
  stages). Combined with the existing `getCurrentStageName` resolve, that gives a
  clean "am I standing in a visited overworld right now?" test for free.

---

## What the change requires

This is **switch-mod-only** — no apworld logic, no re-seed, no wire-protocol
change (it reads in-game state the mod already has a handle to and writes via
named functions). It does **not** alter reachability logic; the apworld fill
already assumes you can leave a kingdom, so this only makes the game match what
the logic already believes (same framing as the costume-doors and Lost-softlock
fixes).

### Tier 1 — generalize the sweep (the core change)

Rename/extend `runOdysseySoftlockSweep()` into a general **"keep the Odyssey
boardable in any visited overworld"** sweep. Per throttled call:

1. Resolve the current stage via the already-bound `getCurrentStageName`; bail
   unless `kingdomShortFromHomeStage(stage) != nullptr` (i.e. we're in an
   overworld home stage, not a subarea/boss/cutscene stage).
2. Bail unless that kingdom's bit is set in `ApState::visited_kingdoms` **and**
   the global Odyssey-acquired precondition holds (see Tier 2) — so we never
   force the ship into a pre-acquisition intro state.
3. If the Odyssey is in any *grounded/absent* state for this overworld, force it
   good via the existing primitives: `repairHome` (clears crash) and, newly,
   `activateHome` / `launchHome` when `!isActivateHome` / `!isLaunchHome`.

The existing Lost branch stays as a special case (it additionally needs
`unlockWorld(getWorldIndexClash())` so the post-repair autopilot can backtrack);
Ruined stays deliberately untouched for the boss-counter-overshoot reason already
documented in [OdysseyRescue.hpp:22-30](../../switch-mod/src/game/OdysseyRescue.hpp#L22).

### Tier 2 — the gating that keeps it safe (the careful part)

A blanket "always force the Odyssey present" would **break the legitimate intro**:
in Cap and Cascade the player genuinely does not have the Odyssey yet, and Lost
/ Ruined ground it *as gameplay*. The request's own wording — "kingdoms you've
already **unlocked/visited**" — is the guard rail, and it maps onto signals the
mod already has:

- **Global "Odyssey acquired" precondition.** Don't force activation in *any*
  kingdom until the Odyssey has been launched at least once in the run. `getHomeLevel
  > 0` or a one-shot sticky "have we ever seen `isLaunchHome` true" latch on
  `ApState` is the cheap test; this keeps Cap/Cascade's pre-Odyssey opening intact.
- **Per-kingdom "visited" bit** (above) ensures we only ever *restore* access to a
  kingdom the player legitimately reached, never *grant* premature access to one
  the kingdom-order gate hasn't released. This keeps the feature orthogonal to the
  [[kingdom-order-gate-premature-destinations]] follow-up.
- **Story-grounded exemptions.** Leave the two intentional groundings to their
  vanilla release: Lost via the existing repair branch, Ruined via the dragon
  (pinned Multi-Moon). The only open question is whether **Bowser's Kingdom** (the
  reported bug) or **Moon** have their own intentional mid-story grounded windows
  that the sweep must *not* stomp — resolved by the in-game walk below.

### Tier 3 — symbols to add

Five `GameDataFunction` manglings already ship for `OdysseyRescue`. This adds at
most four more, all the same trivial `GameDataHolderAccessor`/`Writer` shape, to
[HookSymbols.hpp](../../switch-mod/src/hooks/HookSymbols.hpp) + `SmoApSymbols.sym`
and verified through the `smo-symbol-discovery` pipeline (illustrative, to verify):

- `isExistHome` → `_ZN16GameDataFunction10isExistHomeE22GameDataHolderAccessor`
- `isActivateHome` → `_ZN16GameDataFunction13isActivateHomeE22GameDataHolderAccessor`
- `activateHome` → `_ZN16GameDataFunction12activateHomeE20GameDataHolderWriter`
- `isLaunchHome` / `launchHome` →
  `_ZN16GameDataFunction12isLaunchHomeE22GameDataHolderAccessor` /
  `_ZN16GameDataFunction10launchHomeE20GameDataHolderWriter`

---

## The dominant unknown (why not 95%)

The Odyssey you see in an overworld is rendered by an **actor** (`Odyssey`/the home
ship), and the `GameDataFunction` flags above are the *save-state* it reads. The
core uncertainty is whether **setting the flags is sufficient to make a
not-currently-spawned Odyssey appear and become boardable mid-scene**, or whether
the actor only consults those flags **at stage init** — in which case forcing the
flags helps on the *next* load but not the frame you're stranded. There are three
graded outcomes, only an in-game spike distinguishes them:

1. **Best case:** the home actor polls `isActivateHome`/`isExistHome` per-frame (or
   the sweep + a benign self-reload makes it re-init) → the ship appears and is
   boardable, full fix, exactly the Lost path's proven shape.
2. **Middle:** flags only take at stage init → the sweep still fixes the strand on
   the next scene load, and we can *force* that reload cheaply (the project already
   does scenario-jump stage reloads in `MoonRockHook`) — a slightly less seamless
   but still complete safety net.
3. **Worst:** the absent-Odyssey case is driven by something other than these flags
   (e.g. a placement/scenario condition on the actor itself) → needs a `main.nso`
   read of the home-ship actor's appear condition, bumping effort toward Medium.

The reported **Bowser's-Kingdom-early** repro is now characterized (Devon,
2026-06-22): Mario **exited a subarea and was dropped into Bowser's Kingdom
overworld in its basest state — as if freshly arrived — instead of returning to
Cascade as he should have.** This was an entrance-shuffle **exit-routing bug** (the
exit returned to the wrong overworld), *since cleaned up*. The tell is decisive for
this feature: the overworld loaded fresh at its base scenario with **no arrival
cutscene having run**, so the home-ship `activate`/`launch` flags that cutscene
normally sets were never set — i.e. **outcome 1 or 2, exactly what Tier 1 fixes**,
and a `main.nso` actor read (outcome 3) is unlikely. Even with that specific routing
bug fixed, the same class of "land in an overworld at a scenario state the arrival
flow never produced" will recur under full entrance randomization, which is why this
backstop is worth building. Secondary unknowns: confirming `activateHome`
alone vs. `activateHome + launchHome` is what gates the boardable/world-map state,
and that none of the forced flags perturb the kingdom-order gate or the
deposit/peace accounting (all read the same holder).

---

## Recommendation / first step (when pursued)

1. **Logger-only spike (no behavior change).** Bind the four new getters and, from
   the existing sweep, log `isExistHome / isActivateHome / isLaunchHome /
   isCrashHome` + `getCurrentStageName` every ~1s. Reproduce the Bowser's-Kingdom
   strand (or force it via early arrival) and read which flags are false in the
   stranded overworld vs. a normal one. That single trace decides outcome 1/2/3 and
   confirms which mutator(s) restore the boardable ship.
2. **Extend the sweep** (Tier 1+2) behind a default-on safety toggle
   (`odyssey_always_available`), reusing `kingdomShortFromHomeStage` +
   `visited_kingdoms` for scoping and the `getHomeLevel>0` latch for the intro
   guard. Rebuild the subsdk only. Verify: rush into a normally-Odyssey-grounded
   overworld → ship is parked and boardable, world map opens, fly back works; and
   the Cap/Cascade intro, Lost, Ruined, and the kingdom-order gate are all
   unchanged.
3. Once validated, this becomes the **landing-safety backstop** the full
   any-to-any entrance randomizer depends on
   ([future-feasibility-decoupled-entrance-randomizer.md](future-feasibility-decoupled-entrance-randomizer.md)
   flags "landing in an overworld via a door/pipe" as a top risk — this directly
   de-risks it).

**Why ~85%:** the exact pattern is already shipped and in-game-validated for one
kingdom — same chokepoint, same per-frame sweep, same named `GameDataFunction`
mutators — and every supporting signal the generalization needs (overworld-stage
classifier, sticky visited bitset, throttled call site, holder cache) is already
present, so the bulk is widening a working function and adding four trivial
same-shape symbols, with zero apworld/logic/wire change. The points off are the
genuine in-game unknown of whether forcing the save-state flags makes a
not-yet-spawned Odyssey appear *this frame* vs. only on the next load (worst case a
`main.nso` read of the home-ship actor's appear condition), plus the care-work of
exempting the intro/story-grounded states (Cap/Cascade pre-acquisition, Lost,
Ruined, and any Bowser/Moon mid-story window) so the safety net never stomps an
intentional grounding.

---

Sources consulted (disk-truth reads + headers this session):
[switch-mod/src/game/OdysseyRescue.cpp](../../switch-mod/src/game/OdysseyRescue.cpp) /
[OdysseyRescue.hpp](../../switch-mod/src/game/OdysseyRescue.hpp) (the shipped Lost
softlock sweep this generalizes),
[switch-mod/src/main.cpp:230-279](../../switch-mod/src/main.cpp#L230) (per-frame
sweep call site + symbol resolve),
[switch-mod/src/hooks/HookSymbols.hpp:610-646](../../switch-mod/src/hooks/HookSymbols.hpp#L610)
(the five `OdysseyRescue` manglings + style for adding more),
[GameDataFunction.h:454-466, 412-413](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataFunction.h#L454)
(the full `*Home` Odyssey state machine: exist/activate/launch/crash/bossAttacked),
[KingdomUnlock.hpp:60-64](../../switch-mod/src/game/KingdomUnlock.hpp#L60)
(`kingdomShortFromHomeStage` overworld classifier),
[KingdomOrderGate.hpp:18-21](../../switch-mod/src/game/KingdomOrderGate.hpp#L18)
(`ApState::visited_kingdoms` sticky bitset). Cross-refs: the
decoupled-entrance-randomizer feasibility doc (this is its landing-safety
backstop), [[kingdom-order-gate-premature-destinations]],
[[region-gating-egress-off-by-one]].
</content>
</invoke>
