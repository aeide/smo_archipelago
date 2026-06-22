# Relocate a save to Cap Kingdom in its peace state, Odyssey alongside (Devon, 2026-06-22)

**Goal.** Take a **minimally-progressed real save** (Devon's example: finished the
Cap prologue, beat the opening miniboss, flew to Cascade, saved — **zero moons
collected**) and transform it so that on load Mario is **standing back in Cap
Kingdom, Cap's story-complete/peace state set, and the Odyssey parked alongside
him** ready to fly. The hoped-for corollary: because the Odyssey would now be in a
*post-peace* (launched) state, **flying onward to Cascade would find the Odyssey
already at its landing pad** — instead of grounded in the rocks as it is during
Cascade's pre-departure scenario. That second point is the real prize: the
grounded-Cascade state is a genuine logic hazard (you can reach Cap from Cascade,
but if the Cascade Odyssey is still in the rocks you can't fly back until you launch
it — a softlock the randomizer's reachability assumes away).

**Status: investigated, NOT started. Estimate ~70% feasible, High effort — the
Cascade-landing corollary is a higher-confidence (~80%) sub-result, and the
recommended path is a runtime hook, NOT offline `.bin` editing.** (Originally scoped
for *Moon* as the destination — Devon corrected to **Cap** on 2026-06-22, which is
the *best* possible choice: it strips out the game-clear/AP-win coupling that made
Moon the worst case, and it sidesteps the exact intro-break that killed the earlier
`kCapPeaceFromStart` experiment.) It still collides with a constraint the project
**already proved the hard way** — the scenario-recompute wall — which is why it
isn't a slam dunk.

---

## The decisive prior finding (why naïve editing fails)

The project already attempted the close cousin of this — "fresh save starts at Cap
**peace** with the Odyssey" (the `kCapPeaceFromStart` experiment) — and concluded
**OFF** with a precise root cause, recorded in
[MoonRockHook.cpp:68-76](../../switch-mod/src/hooks/MoonRockHook.cpp#L68):

> *"Forcing Cap's stored main scenario is **recomputed away from quest state at
> every stage load** (observed: capScen pinned at 1 across reloads while capMain
> held 4; the game re-writes main=1 on transitions and only the write-upgrade kept
> it at 4). Reaching 'fresh save starts at Cap peace with the Odyssey' needs
> **new-save state surgery (initializeData post-hook: mIsPlayDemoOpening, meetCap,
> setActivateHome, unlockWorld, quest state)** — scoped as a possible future
> milestone."*

That is the load-bearing fact for Devon's whole request: **a kingdom's scenario
number (and therefore its peace state and the Odyssey's grounded-vs-landed pose) is
a *derived* value, recomputed from the underlying quest/moon completion state every
time the stage loads.** So poking "current world = Cap, scenario = peace" into the
save — whether by `.bin` edit or a one-shot runtime write — **does not stick** *if
the quest state doesn't back it*; the load path recomputes it and overwrites you. To
make peace *persist*, you set the **quest state peace is derived from**, using the
game's own writers so the recompute agrees with you instead of fighting you.

**Two reasons the Cap target turns this from a fight into a tailwind** (and why the
correction from Moon → Cap genuinely raised the estimate):

1. **The recompute *cooperates* for Cap, because the quest state is legitimately
   already complete.** The failed `kCapPeaceFromStart` experiment forced Cap peace
   on a *fresh* save *during* the scripted prologue, so the recompute kept yanking
   Cap back to scenario 1 (and forcing it risked breaking the intro — no Cappy meet,
   no path to Cascade). Devon's save has **genuinely finished Cap's prologue** — Cap's
   story *is* its prologue ([MoonRockHook.cpp:38](../../switch-mod/src/hooks/MoonRockHook.cpp#L38)),
   so its quest source-of-truth already reads complete and the recompute will land
   Cap at its post-prologue/revisit (≈peace) value **on its own**. We're no longer
   forcing a derived value against the quest state; we're *relocating to* a kingdom
   whose quest state already justifies the state we want.
2. **There is no intro left to break.** The exact failure mode that killed the
   fresh-save experiment (a forced Cap peace clobbering the scripted opening) simply
   doesn't exist on a save where the opening already happened.

**What the Cap target does NOT get for free — the Odyssey.** During the prologue
the Odyssey isn't in Cap at all (you don't *have* it yet; you first board it in
Cascade after launching it). So "standing in Cap **with the Odyssey alongside**"
requires the Odyssey to be **launched**, which in Devon's save it is not — he flew
to Cascade but the ship is still grounded in the rocks (0 moons, no Madame Broode
Multi-Moon). So the surgery's real work is **forcing the Odyssey launched** (force
Cascade's departure/peace), and *that* is the same multi-kingdom peace-forcing the
Cascade corollary below needs — they're the same lever. Net: Cap-as-destination
removes the *derive-against-quest-state* problem for the destination kingdom, but
the "get the Odyssey to it" half still rides on forcing Cascade complete.

---

## The save files (read-only recon this session)

`C:\Users\devon\AppData\Roaming\Ryujinx\bis\user\save\0000000000000006\0\`:

- `File1.bin`..`File5.bin` — each **exactly 2,097,164 bytes** (a fixed-size
  `GameDataHolder` serialization; the size is identical across slots regardless of
  progress, confirming a flat struct dump, not a packed delta).
- `Common.bin` — 1,036 bytes (shared/system settings).
- `100-percent-File1.bin.bk` and `cleared-but-unotuched-File1.bin.bk` — Devon
  **already keeps offline backups/swaps** of save states, so swap-and-restore is an
  established part of the workflow (good: any attempt here is reversible by design).

A 2 MB flat dump is editable in principle, but it's a serialized `GameDataHolder`
(per-world scenario ints, ShineGet bitfields, quest flags, current
stage/checkpoint, Home/Odyssey state, hat/cloth/coins). The repo holds **no
committed save-format map**, and per the IP rules we won't create one as bulk
content (offsets are functional, but a full layout transcription is the kind of
bulk artifact to avoid). Community SMO save editors exist as a *reference* for
offsets, but they're version-specific and, critically, **they edit the same derived
fields the recompute overwrites** unless they also set quest source-of-truth.

---

## Two approaches

### Approach A — offline `.bin` editing (NOT recommended)

Edit `File1.bin` directly to set Moon as current world, the peace/quest flags, and
the Home state. Honest assessment of why this is the weaker path:

- **The recompute caveat applies in full.** You'd have to locate and set every
  quest flag Moon-peace is *derived from*, not just the scenario int — without the
  game's helper functions, and without any committed offset map.
- **The Odyssey "alongside me" is not a stored coordinate you can poke.** Its
  landing pose is re-derived per-kingdom from the Home state machine + scenario on
  stage load (the same machinery the
  [Odyssey-always-available doc](future-feasibility-odyssey-always-available.md)
  covers). Get the state right and the pose follows; edit a position field and the
  load recomputes it.
- **It bypasses AP entirely.** The mod's deposit/outstanding accounting (M6 phase
  D) and the peace/moon-rock gates expect save state to be *consistent with what
  Archipelago has granted*. A save hand-forced to multi-kingdom peace with no
  corresponding AP item state can desync the credit accounting and let checks the
  logic assumed gated be collected for free.
- **Version-locked + fragile** (any SMO/format drift silently corrupts).

It *is* reversible (Devon keeps `.bk`s), so a throwaway experiment isn't dangerous
to the save — but it's low-confidence and doesn't generalize.

### Approach B — runtime "state surgery on load" hook (RECOMMENDED)

This is precisely the path the MoonRockHook header already scoped, and it reuses
machinery that's already shipping:

- **The chokepoint already exists and is already hooked.**
  `GameDataFile::initializeData()` is the load entry point, trampolined today as
  [SaveLoadHook.cpp](../../switch-mod/src/hooks/SaveLoadHook.cpp) (fires for both
  New Game and Load Save). Post-orig there, the `GameDataHolder` is fully
  rehydrated — the correct moment to drive state forward.
- **Drive state with the game's own named writers**, so the recompute *agrees*
  with you: `setMainScenarioNo`, `unlockWorld`, `activateHome`/`launchHome`,
  `findKoopa`, `enableCap`/`meetCap`, `startWorldTravelingPeach`, plus the
  moon/quest setters — every one already in
  [GameDataFunction.h](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataFunction.h)
  and several already called by this project (`unlockWorld`/`activateHome` in
  OdysseyRescue, `startWorldTravelingPeach` in MoonRockHook). Setting quest
  source-of-truth via these is the inlining-proof, recompute-proof move (same
  lesson as World Traveling Peach: *write the bit, don't hook the reader*).
- **Belt-and-braces re-apply** via the existing throttled `drawMain` sweep
  (OdysseyRescue's cadence) for any flag the game re-derives on transitions.
- **Composes with existing peace machinery** (MoonRockHook's per-kingdom peace
  gate, World Traveling Peach auto-start, OdysseyRescue) instead of duplicating it,
  and can be **seed/option-driven** (`start_kingdom` / `start_at_peace`) so it stays
  coordinated with the apworld's starting item state and AP accounting.

Approach B is more code than a hex edit but is the only path with a real shot at a
*persistent, AP-consistent, reproducible* result.

---

## The Cascade corollary — answer: YES, with a caveat (~80% confidence)

Devon's hoped-for side effect is sound and is essentially *documented behavior*. A
kingdom forced to its **post-peace scenario IS the launched/landed-Odyssey state** —
[MoonRockHook.cpp:13-16](../../switch-mod/src/hooks/MoonRockHook.cpp#L13) already
reasons that post-peace "is the vanilla post-game state" where everything in the
kingdom survives and the Odyssey is no longer grounded. So forcing each *visited*
kingdom to peace would put the Odyssey **at its landing pad, not in the Cascade
rocks** — which directly dissolves the "reach Cap from Cascade but can't fly back"
softlock and dovetails with the existing Cascade-departure / scenario-gating fixes
([[region-gating-egress-off-by-one]], [[scenario-gating-bit-rewrite-d1-d2]]) and the
[Odyssey-always-available backstop](future-feasibility-odyssey-always-available.md).
The caveat: Cascade's peace is *derived from* its story completion (the Madame
Broode Multi-Moon), so "I beat the opening miniboss" likely does **not** equal
Cascade-peace on its own — the surgery has to force Cascade's quest state to
complete (via `setMainScenarioNo` + the relevant quest flags), not assume the
miniboss kill did it. Once forced, the landed-pad pose is the high-confidence part.

---

## Why Cap is the *best* destination (not the worst)

Cap is the lowest-coupling kingdom in the game for this purpose, which is why the
Moon → Cap correction raised the estimate:

- **No game-clear / AP-win entanglement.** Moon would have been the worst case
  precisely because *its* peace == game-clear, dragging in goal/credits detection
  and the "leave Moon = win = ENDS the AP" coupling (CLAUDE.md *Deferred work*). Cap
  has none of that — it's the *opening* kingdom; nothing about Cap-peace touches
  `isGameClear`, the `CreditsStartHook` wedding gate, or the victory boundary.
- **Cap's "peace" is the natural revisit state**, which the moon-rock gate already
  treats as openable on first revisit ([MoonRockHook.cpp:28-29](../../switch-mod/src/hooks/MoonRockHook.cpp#L28)) —
  so we're aligning with existing, validated behavior rather than synthesizing a
  state the game never normally produces mid-run.
- **The recompute is on our side** (see above): Cap's quest state is already
  legitimately complete on Devon's save.

The residual Cap-specific care-work is small: confirm that relocating into
`CapWorldHomeStage` lands Mario at a sane spawn/checkpoint (not mid-prologue
trigger), and that the existing **Cap Spark-Pylon exemption** (the forced exit pylon
in `CapWorldHomeStage`, see CaptureStartHook) behaves under a revisit rather than a
first-arrival — both cheap to verify in the spike.

**Recommendation: prove the mechanism on Cap directly** (it's the target *and* the
lowest-risk kingdom), confirming the relocate + the recompute-cooperates result;
**then** force the Odyssey launched (the Cascade-departure lever) and verify the
landed-pad pose in both Cap and a subsequent Cascade flight — that second step is
the multi-kingdom "force visited kingdoms to peace" variant and is the part that
delivers the corollary Devon actually wants.

---

## Recommendation / first step (when pursued)

1. **Do not hand-edit `File1.bin`.** It's the weak path (Approach A) and bypasses
   AP. If a throwaway experiment is ever wanted, back it up first (Devon already
   keeps `.bk`s) — but Approach B is the real answer.
2. **Logger spike on `initializeData` post-orig:** from the existing SaveLoadHook,
   dump per-world scenario numbers + the `*Home` flags right after load on Devon's
   Cascade save. Confirm Cap's scenario *already* reads complete (the
   recompute-cooperates prediction) and the Odyssey flags read *not-launched*.
3. **Relocate to Cap + launch the Odyssey:** warp Mario to `CapWorldHomeStage` and
   force the Odyssey launched via `activateHome`/`launchHome` (+ `unlockWorld` /
   `setMainScenarioNo` for Cascade so the launch is quest-consistent). Confirm (a)
   Cap loads at a sane spawn with the Odyssey landed at its pad and boardable, (b)
   the state *sticks* across a stage reload (vs. the fresh-save recompute), (c) the
   Cap Spark-Pylon exemption behaves on revisit, (d) AP accounting stays sane.
4. **Re-test the Cascade landed-pad corollary** specifically — fly Cap → Cascade and
   confirm the Odyssey is at the pad, not the rocks (the result that motivates the
   whole idea).
5. Wire it behind a `start_kingdom` / `start_at_peace` debug option so it stays
   seed-coordinated with the apworld and is trivially reversible.

**Why ~70%:** the *mechanism* is well-supported — the load chokepoint is already
hooked, the state writers are all named SMO functions the project already calls, and
the "write the source-of-truth bit, let the recompute agree" pattern is proven
(World Traveling Peach). The **Cap target removes the two biggest hazards** the Moon
version carried: no game-clear/AP-win entanglement, and no intro to break (the
opening already happened on the save), with the scenario-recompute actually
*cooperating* for Cap because its quest state is legitimately complete. The points
off (→70%, not higher): (1) the **recompute-from-quest-state** wall still governs
the half that matters — getting the Odyssey to Cap means forcing Cascade's
departure/launch to be quest-consistent, the fiddly part where the Cap-peace
experiment originally died; (2) **AP-consistency** constrains it (a save forced
toward peace must not desync the M6 deposit/outstanding accounting), which is why
offline `.bin` editing (Approach A) is downgraded; (3) small unverified Cap-revisit
details (spawn/checkpoint, the Spark-Pylon exemption on revisit). The **Cascade
landed-pad corollary specifically is higher confidence (~80%)** because it's the
documented post-peace behavior — once the Odyssey is *actually* launched and Cascade
is at peace, the Odyssey-at-pad pose follows.

---

Sources consulted (disk-truth reads + headers + read-only save recon this session):
[MoonRockHook.cpp:1-103](../../switch-mod/src/hooks/MoonRockHook.cpp) (the
`kCapPeaceFromStart` OFF verdict + the "scenario recomputed from quest state" root
cause + "new-save state surgery via initializeData post-hook" scoping + the
post-peace = landed-Odyssey reasoning + World Traveling Peach precedent),
[SaveLoadHook.cpp](../../switch-mod/src/hooks/SaveLoadHook.cpp) (the already-hooked
`GameDataFile::initializeData` load chokepoint),
[GameDataFunction.h](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataFunction.h)
(`setMainScenarioNo`, `getWorldScenarioNo`, `unlockWorld`, `activateHome`/
`launchHome`, `meetCap`/`enableCap`, `findKoopa`, `isGameClear`, `initializeData`),
[OdysseyRescue.cpp](../../switch-mod/src/game/OdysseyRescue.cpp) (named-writer state
forcing precedent), save dir listing (5× 2,097,164-byte `File*.bin` + `.bk`
backups). Cross-refs:
[future-feasibility-odyssey-always-available.md](future-feasibility-odyssey-always-available.md)
(the Home-state-machine half), CLAUDE.md *Deferred work* (Moon "leave = win"
coupling) + *Goal-detection wiring* (CreditsStartHook narrow gate),
[[world-traveling-peach-auto-start]], [[region-gating-egress-off-by-one]],
[[scenario-gating-bit-rewrite-d1-d2]].
</content>
