# Moon recolor (by granted kingdom + AP classification) and purple-coin model swap (Devon, 2026-06-20)

This is the updated, fleshed-out form of the original plan's **P5**. It has two
clearly-separable halves with very different difficulty, so they're rated separately:

1. **Recolor** — tint each AP-check moon by meaning:
   - SMO moon item → the **granted moon's kingdom** color (e.g. a Cascade-located
     check that grants a *Sand* moon is Sand-green), *not* the kingdom the check
     physically sits in.
   - Foreign-game **progression** → green, **useful** → yellow, **junk** → dull grey,
     **trap** → red.
2. **Coin-model swap (the caveat)** — replace the moon *model* with a moon-sized,
   color-correct version of that kingdom's **purple (regional) coin** model (Cap =
   bright yellow, Cascade = orange, …; Ruined uses the game's unused purple-coin
   model since it has none of its own).

**Status: Part 1 (recolor) IMPLEMENTED + in-game (per-kingdom recolored moons ship and
look good). Part 2 (coin-model swap) — SHELVED 2026-06-28 after 4 in-game build cycles
+ an NSO-disasm research spike proved every viable mechanism has a hard blocker. The
shipped build has `kCoinModelSwap = false` (crash-free). See "Part 2 — FINAL STATUS
(2026-06-28): SHELVED" immediately below; the v1/v2/v3 sections after it are the
historical iteration record that section supersedes.**
- **Recolor: ~95% feasible, SMALL** — this is essentially the already-scoped P5; the
  whole pipeline exists and only needs extending. **DONE in source:** Switch palette
  table widened to 22 entries (idx 0 recolored grey=junk, idx 2 recolored yellow=useful,
  idx 5..21 = 17 kingdom colors incl. Cloud + Dark/Darker), the `pal < 5 ? pal : 0`
  clamp bug fixed (it was collapsing every kingdom index back to 0), client
  `ColorsConfig.for_kingdom()` + `KINGDOM_PALETTE_*` added, and
  `_push_palette_for_scout_batch` now colors our-own-slot moon items by the granted
  moon's kingdom (keyed on the item, not the check's physical kingdom). Lock-step tables:
  `switch-mod/src/hooks/ShineAppearanceHook.cpp` ↔ `client/config.py`. Requires a
  switch-mod rebuild (subsdk9) AND `install_apworld.py` (client config ships in the zip)
  to take effect.
- **CORRECTION (2026-06-20, from Devon):** vanilla SMO already colors Power Moons per
  kingdom (Sand = green, etc.). The mechanism is a shader-param color animation named
  "Color" (`Color_fcl`) on the `BodyMT` material in the shared `ObjectData/Shine.szs`
  → `Shine.bfres`; `Shine::getColorFrame()` returns the per-kingdom frame index, and the
  animation is global (a frame is the same color in every stage). **The authentic
  implementation is therefore to drive that color frame to the GRANTED kingdom's value,
  not to invent Color4f tints.** The 17 kingdom Color4f entries currently in
  ShineAppearanceHook are a PLACEHOLDER approximation pending: (1) the al:: setter that
  sets a named shader-param-anim frame on a LiveActor, and (2) the kingdom→frame map
  (cheapest to capture by logging `getColorFrame()` per kingdom in-game, since
  `Shine`/`getColorFrame` is undecompiled). Foreign-game classification colors
  (green/yellow/red/grey) stay as material tints — they have no vanilla frame.
- **CAPTURED kingdom→frame map (2026-06-21, in-game `[shine-colorframe]` harvest).**
  Sampled `Shine::getColorFrame()` on **uncollected** moons in each home stage (a 100%
  save yields nothing — collected moons are grey ghosts with a null color anim at
  `this->[0x2E8]` and no frame to read). Vanilla uses only **10 distinct frames**, and
  **8 kingdoms share frame 0** (the default moon color), which is why the throwaway
  diagnostic — deduped by frame value — only emitted one line for that whole group:

  | Kingdom | Home stage | Vanilla frame |
  |---|---|---|
  | Cap | CapWorldHomeStage | 0 |
  | Mushroom | PeachWorldHomeStage | 0 |
  | Cascade | (shares frame 0) | 0 |
  | Cloud | (shares frame 0) | 0 |
  | Lost | (shares frame 0) | 0 |
  | Ruined | (shares frame 0) | 0 |
  | Dark Side | (shares frame 0) | 0 |
  | Darker Side | (shares frame 0) | 0 |
  | Metro | CityWorldHomeStage | 1 |
  | Wooded | ForestWorldHomeStage | 2 |
  | Bowser's | SkyWorldHomeStage | 3 |
  | Snow | SnowWorldHomeStage | 4 |
  | Sand | SandWorldHomeStage | 5 |
  | Luncheon | LavaWorldHomeStage | 6 |
  | Lake | LakeWorldHomeStage | 7 |
  | Seaside | SeaWorldHomeStage | 8 |
  | Moon | MoonWorldHomeStage | 9 |

  Because vanilla collapses 8 kingdoms onto frame 0, the frame-override alone cannot
  give 17 distinct colors. **Devon's decision (2026-06-21):** keep Cap + Mushroom on
  vanilla frame 0; give the other six frame-0 kingdoms **custom material tints** (the
  existing Color4f path — they have no vanilla frame of their own): Cascade `#f99a0f`,
  Lost `#eb1bc4`, Cloud `#e4e9ec`, Ruined `#d1a9cb`, Dark Side + Darker Side `#e4bb8f`
  (shared). The 10 distinct-frame kingdoms use the authentic frame-override; these six
  use tints — a **hybrid**.
- **IMPLEMENTED (2026-06-21), awaiting in-game confirmation.** The hybrid recolor is live
  in `switch-mod/src/hooks/ShineAppearanceHook.cpp` (switch-mod-only — no apworld rebuild):
  - The **authentic frame-override** re-drives the vanilla "Color" material anim to the
    granted kingdom's frame via `rs::setStageShineAnimFrame(actor, nullptr, frame, isMatAnim)`
    (OdysseyDecomp `src/Util/ItemUtil.cpp`; HIT in 1.0.0 dynsym). Per-kingdom frames live in
    `kKingdomColorFrame[17]` (indexed by `pal_idx - kKingdomPaletteBase`); `kColorFrameTint`
    (-1) marks the six tint kingdoms. The frame-override path **returns before** the material
    write — the two never combine (`setMaterialProgrammable` would freeze the anim we just set).
  - The **six custom tints** are Devon's hex scaled up to a max channel of ~2.6 (hue preserved,
    brightness normalized to neighbors — the material write is multiplicative against the gold
    base, so a tuning pass is expected). They sit in the existing `kPaletteColors3D/Dot` rows
    6/10/11/16/20/21; the 11 frame-override kingdoms keep their old placeholder Color4f rows as
    a symbol-miss fallback (unused on the happy path).
  - **Two unverified knobs (single-flip each, like `kUpThrowIsPositiveY`):** (1) `kColorAnimIsMatAnim`
    — `false` (Mcl, material-color) is the expected family for a "Color" anim; flip to `true` (Mtp)
    if the `[shine-frame]` log fires but moons don't recolor. (2) **2D dot shines** (`shine_type==1`):
    `setStageShineAnimFrame` operates on the actor's "Color" anim regardless of type; if dot models
    lack that anim the override is a graceful no-op (dot moons would stay vanilla gold) — watch for it
    and, if so, route dots to the tint path by `shine_type`.
  - The throwaway `[shine-colorframe]` diagnostic (+ its `getColorFrame` symbol) is **removed**;
    a small one-time `[shine-frame] override#N ...` log confirms the path fires.
- **STUB-SHINE CRASH + GUARD (2026-06-21).** The frame-override null-derefs on a **stub
  linked-Shine** — `Pyramid::init` → `createLinksActorFromFactory` spawns a Shine that has a
  model (passes `isExistModel`) but **no Mcl "Color" anim player**, so
  `rs::setStageShineAnimFrame` → `startMclAnimAndSetFrameAndStop` → `AnimPlayerSimple::startAnim`
  reads a null player (`Invalid memory access at vaddr 0x0`). Guard added before the frame call:
  `al::isMclAnimExist(self, "Color")` (skips the frame path → falls through to material tint when
  the anim player is absent). The guard is permissive-on-miss (proceeds if the symbol doesn't
  resolve).
  - **Symbol-name bug (fixed 2026-06-21):** the guard first shipped as `al::isExistMclAnim`,
    which **does not exist** in the binary — `lookupSymbol` logged `isExistMclAnim lookup FAILED`,
    leaving the guard permissive-on-miss → unguarded → crash would recur. The al convention is
    **`is<Family>AnimExist`** (`isMclAnimExist`, `isMtpAnimExist`, `isMatAnimExist`), verified
    against `switch-mod/lib/OdysseyHeaders/al/Library/LiveActor/ActorAnimFunction.h:167`. Renamed
    in source: `kAlIsExistMclAnim` → `kAlIsMclAnimExist` (`_ZN2al14isMclAnimExistEPKNS_9LiveActorEPKc`;
    only the name token changed — both names are 14 chars, so the demangled length prefix already
    matched, which is why the wrong spelling looked plausible). Function pointer `s_isExistMclAnim`
    → `s_isMclAnimExist`, guard + `resolveSymbol` + log label updated. `isMclAnimExist` is an
    out-of-line al util (same family as `isExistMaterial`/`isExistModel`, both of which resolve)
    and null-checks the Mcl player (`getMcl` may return null) → returns false for the stub. **Boot
    log tell:** success = `isMclAnimExist resolved @ 0x…`; failure = `isMclAnimExist lookup FAILED`.
    Awaiting build + in-game re-test of the Pyramid/Sand stub-shine case. Handoff:
    [handoff-shine-recolor-mclanim-guard.md](../handoff-shine-recolor-mclanim-guard.md).
- **SPAWNED-MOON RECOLOR FIX (2026-06-21, built + deployed, awaiting in-game confirm).**
  Devon reported that moons present at stage load recolored perfectly, but moons that
  **spawn at runtime** — opening a treasure chest, starting a kingdom timer challenge,
  any popup/appear moon — reverted to their **vanilla per-kingdom color**. Root cause
  read from the decomp: the recolor was only in the `Shine::init` trampoline, but a
  spawning moon runs an appear/popup sequence *after* `init` that calls
  `rs::setStageShineAnimFrame(shine, …, "Color", …)` to drive the vanilla color anim,
  silently overwriting our init-time override. (`Shine.cpp` is undecompiled, but the
  setter is in OdysseyDecomp `src/Util/ItemUtil.cpp`: it's the only thing that drives
  the "Color" Mcl anim, and its actor arg is always the Shine — confirmed it tail-calls
  `startShineAnimAndSetFrameAndStop(actor, "Color", frame, isMatAnim)`.)
  - **Fix:** added a second trampoline on `rs::setStageShineAnimFrame` in
    `ShineAppearanceHook.cpp` that re-asserts our palette decision whenever the game
    re-drives a shine's color (init *or* runtime spawn). Frame-override kingdoms →
    substitute our granted kingdom's frame into the vanilla call (single `.orig()` call,
    no recursion); tint kingdoms + classification colors (idx 0..4) → let vanilla drive
    its frame, then multiply our material tint back on top; no override → pass through.
  - Shared resolution refactored into `resolveShinePalIdx` / `kingdomColorFrameForPal` /
    `tryWriteShineTint` so the `Shine::init` hook and the new hook can't drift. Installed
    by ptr at the already-resolved `s_setStageShineAnimFrame` address (the symbol is
    intentionally kept out of the sail `.sym`, so install-by-ptr with graceful skip on a
    lookup miss; boot tell = `installing SetStageShineAnimFrameOverride -> rs::setStageShineAnimFrame`).
  - Note this also routes vanilla's *own* internal `setStageShineAnimFrame` call from
    inside `Shine::init`'s body through the new hook — harmless (frame kingdoms re-derive
    the same frame; tint path is `isExistModel`-guarded), and the `Shine::init` post-orig
    hook still runs as a belt-and-suspenders second application.
  - **Testing still needed (in-game, Ryujinx restart to load the new subsdk9):**
    1. **Treasure-chest moon** — open a chest moon; confirm it shows the AP
       classification/kingdom color, not vanilla. Watch the log for `[shine-frame]` /
       `[shine-color]` lines firing on the spawn.
    2. **Timer-challenge moon** — start a kingdom timer challenge; same check on the
       spawned moon.
    3. **Tint-kingdom spawned moons** (Cascade/Cloud/Lost/Ruined/Dark/Darker) — these
       take the "tint after vanilla frame" branch (different timing than frame kingdoms);
       verify the custom hue holds for a *spawned* one, not just load-time.
    4. **Regression check** — load-time/placed moons still look correct (the original
       behavior must be unchanged).
    5. **Other spawn sources** — Hint Art, Hat-and-Seek, Koopa Freerunning, any
       popup/appear-warp moon — spot-check that they recolor too (all should route
       through the same setter).
    6. **Stub-shine safety** — re-confirm no crash on the Pyramid/Sand stub linked-Shine
       (the new hook only fires when vanilla itself calls the setter, so it should be
       safe, but verify the `isMclAnimExist` guard path is still intact).
- **Coin-model swap: ~55% feasible, HIGH effort** — a different class of problem
  (3D model/actor swap, undecompiled actor, romfs unknowns).

---

## Part 1 — Recolor (the planned P5): ~95%, small

The entire per-check recolor pipeline already ships and works in-game; this part is
extending tables, not building machinery.

### How it works today

- **Switch:** `ShineAppearanceHook.cpp`
  ([switch-mod/src/hooks/ShineAppearanceHook.cpp](../../switch-mod/src/hooks/ShineAppearanceHook.cpp))
  trampolines `Shine::init`, resolves the shine's `unique_id`, looks up a **palette
  index** via `ApState::getShinePalette(unique_id)`, and tints the body material
  (`BodyMT` / `BodyMT00`) with the matching `Color4f`. The palette is a fixed table —
  currently **5 entries** (`kPaletteColors3D` / `kPaletteColorsDot`): index 0 white,
  1 green, 2 cyan, 3 red, 4 light-green. (`Shine::init`'s symbol is hookable even
  though the actor body is undecompiled — this hook only needs the symbol + al::
  material setters, not the body. That distinction matters for Part 2.)
- **Client:** the LocationScouts handler classifies each scouted location's item and
  emits a palette index per location in `ShineScoutsMsg`, keyed to the shine
  unique_id. The classification→index map is `ColorsConfig`
  ([client/config.py:47-77](../../apworld/smo_archipelago/client/config.py)):
  `progression=1, useful=2, trap=3, filler=0`. `maps.py` already exposes the item's
  **kingdom** (a reverse kingdom map keyed for exactly this palette use,
  [maps.py:68,165](../../apworld/smo_archipelago/client/maps.py)).

So the system already routes a per-location, per-classification color end-to-end. The
P5 plan ([plan-v2-vision.md §P5](../plan-v2-vision.md)) already specified the extension:
emit `5 + kingdom_id` for our own slot's moon items and add kingdom rows to the
palette tables.

### What this request changes / adds

- **Foreign-game classification colors** (small value edits):
  - progression → green = current index 1 ✓ (no change).
  - trap → red = current index 3 ✓ (no change).
  - useful → **yellow**: currently maps to cyan (index 2) — add a yellow `Color4f`
    and point `useful` at it.
  - junk → **dull grey**: `filler` currently maps to 0 ("leave default / white"); add
    a grey `Color4f` and point `filler` at it.
- **SMO own-moon kingdom colors** (the core of P5):
  - Extend `kPaletteColors3D` / `kPaletteColorsDot` with **16 kingdom colors** (Cap
    yellow, Cascade orange, Sand teal, … matching the in-game flag/coin colors).
    Reserve a contiguous block (the plan's `5 + kingdom_id`).
  - Client: when a scouted location's item is **our own slot's moon item**, emit the
    kingdom index of the **granted moon** (from `maps.py`) instead of the
    classification index. This is keyed on the *item's* kingdom, which the client
    already knows — so it naturally satisfies "color by the moon it's FOR, not where
    it is," and **sidesteps** the cross-kingdom-subarea caveat the P5 plan worried
    about (that caveat was about keying on a check's *physical* kingdom; we key on the
    item).
- **Wire protocol:** widening the palette index range is additive and fixed-buffer
  safe (it's a single small int per entry); document the new range in
  [wire-protocol.md](../wire-protocol.md). Keep the switch palette table and the client
  index scheme in lock-step (they're two hand-maintained tables — the usual
  HookSymbols-style sync discipline).

### Why ~95% and not 100%

The only real work is choosing 16 readable kingdom colors that stay distinct under
the material-multiply tint (the palette values are multiplicative — note the existing
entries exceed 1.0 to brighten), and verifying the Dot (2D/8-bit) moon variant reads
well too. No new mechanism, no Switch-actor reverse engineering. This is the "small"
task the plan always called it.

---

## Part 2 — FINAL STATUS (2026-06-28): SHELVED — Route A is a dead end

This is the authoritative summary. The "v2 CRASH FIX", "IMPLEMENTED v1", and original
~55% analysis sections below are the historical iteration record and are superseded by
this section. **Shipped state: `kCoinModelSwap = false` (crash-free recolored moons).**

### Iteration history (4 in-game build/test cycles)

| Build | Change | In-game result |
|---|---|---|
| v1 | placed `initActorWithArchiveName` | "rainbow outline of a moon"; **crash** re-entering Cap from a subarea (`StageSceneStateWorldMap::tryCreate`, corrupt-vtable). The placed init registered the coin in scene actor groups → world-map state enumerated our bare LiveActor. |
| v2 | `initChildActorWithArchiveNameNoPlacementInfo` (no scene registration) | crash gone, but moon "clear/colorless, still moon-shaped" — **no coin visible**. |
| v3 | `+ al::copyPose(child, shine)` (position) | Logs: `childModel=1`, `coinPos == moonPos` exactly. Positioning + model load **work**. Still no coin on screen. **Crash** on Odyssey round-trip. |
| v4 | crash-fix (drop per-frame stale-ptr deref) + diagnostic: moon left visible, coin 8× + bright magenta | **No magenta anywhere.** Decisive: a hand-built coin actor, fully init'd + positioned + scaled + tinted, does **not render**. Also crashed loading Sand (DigPoint stub link-shine → our `Shine::init` hook read `0x3F800000` = float 1.0 as a pointer). |

### Research spike — NSO disassembly (capstone on `.romfs-cache/main.nso`, 2026-06-28)

`Shine.cpp` is undecompiled, so the relevant functions were read as machine code.
Three findings, each killing a candidate approach:

1. **In-world the moon IS the Shine's own model — there is no separate model actor to
   target.** `Shine::getCurrentModel` @0x1ce7b0 returns the demo-model-actor at
   `this+0x2e0`/`+0x2e8` (selected by flag `+0x11c`) **only if present**, else returns
   `this`. Those demo actors exist only during the get/appear cutscenes. So an
   uncollected in-world moon draws through the Shine actor's own ModelKeeper (this is
   why the Part-1 `BodyMT` recolor works in-world).

2. **The native coin path self-destructs the shine — unusable.** `Shine::tryChangeCoin`
   @0x1d09c8 (gate `0x5324d8` → sets the Coin nerve `0x1cbe5c8`) and `Shine::exeCoin`
   @0x1d31b0: drives a model actor, increments a counter at `this+0x2f8`, and at
   `counter >= 5` does `ldr x8,[this]; ldr x8,[x8,#0x28]; blr x8` — a virtual call to
   kill/`makeActorDead`. This is SMO's "duplicate moon → spit out coins → vanish"
   animation. Forcing a real collectable shine into it would **destroy the moon**,
   violating the one hard invariant (collection must stay intact). Dead end.

3. **Route A's draw failure is an al-internals subtlety, not a missing call.**
   `initChildActorWithArchiveNameNoPlacementInfo` actually uses **`initViewIdHost`** (the
   child DOES get a view id — my earlier "no view id" guess was wrong) and routes through
   `initActorImpl`, which calls `initActorExecutor` → `initExecutorDraw`. So the child got
   model + view-id + executor/draw init + pose + alive and **still didn't render**. The
   missing piece is the **scene-level LiveActorKit/ExecuteDirector registration** that
   placement actors receive via `createPlacementActorFromFactory` / the scene init flow —
   `initActorImpl` does not do it for a hand-built actor.

### Verdict & the only two real paths (if ever resumed)

NO-GO for a cheap win. Achievable only as a dedicated multi-session RE task:

- **(A) Swap the Shine's own ModelKeeper model resource** to the regional-coin model.
  Draws for free (Shine already draws) and leaves collection untouched — but al exposes
  no clean "replace model" API, so this means reverse-engineering ModelKeeper internals.
- **(B) Properly register a runtime child with the scene's executor/draw system**
  (replicate what `createPlacementActorFromFactory` does, getting the scene/kit from the
  init info). Plus a **mandatory DigPoint stub-link-shine guard** in our `Shine::init`
  hook (those reach the hook during stage load and crashed v3/v4).

What already works and should be kept for any future attempt: cross-kingdom
`CoinCollect<letter>` archive load, `initChildActorWithArchiveNameNoPlacementInfo` (no
crash), `al::copyPose(child, shine)` for positioning. Verified manglings (dumped from
dynstr, NOT g++-guessed — Itanium substitutions bit the first attempt):
`al::copyPose` = `_ZN2al8copyPoseEPNS_9LiveActorEPKS0_`,
`al::getTrans` = `_ZN2al8getTransEPKNS_9LiveActorE`.

**Recommendation: leave shelved.** The recolored moons look good and never crash; the
coin swap is a large RE investment for a purely cosmetic result.

---

## Part 2 — v2 CRASH FIX (2026-06-28) — placed init → child/no-placement init

**v1 result (in-game, 2026-06-28):** moons rendered "a rainbow outline of a moon,
not a coin," and the game **crashed** re-entering Cap Kingdom from a subarea —
undefined-instruction at `0xa2729b0` (opcode `0x08e11dcc`) inside
`StageSceneStateWorldMap::tryCreate` (a corrupted-vtable virtual call).

**Root cause:** v1 loaded the coin child with `al::initActorWithArchiveName`, which
== `initChildActorWithArchiveNameWithPlacementInfo` (lib/al `ActorInitUtil.cpp`): it
reuses the Shine's `ActorInitInfo`, registering the coin as a **placed** actor
(view-id + clipping + scene actor groups). On scene re-entry the world-map state
enumerates placed actors and virtual-dispatches on our bare `al::LiveActor` — wrong
vtable → branch into `.rodata` → crash. The same corrupt placement state is the most
likely cause of the "outline not coin" visual (phantom placed actor draws with broken
transform/state).

**Fix (v2):** use **`al::initChildActorWithArchiveNameNoPlacementInfo`** — it builds a
fresh empty `PlacementInfo` + `ActorInitInfo` (`initNoViewId`), so the coin is never
registered scene-wide. Symbol confirmed in 1.0.0 dynsym (`check_nso_symbols.py`).
**Built + deployed to Ryujinx 2026-06-28; awaiting Devon retest.** Expect this to fix
BOTH the crash and the visual; verify the visual before chasing it separately.

**In-game data that v1 DID establish (good news):** cross-kingdom archive load WORKS —
`CoinCollectD/N/C/I/L` all loaded fine while standing in Cap/Snow (children created,
no hitch/assert). On-device unknown #1 below is effectively resolved.

**Next lever if v2's coin is invisible or doesn't die on collect:** the sub-actor sync
flag. Coin uses `registerSubActorSyncAll` (cAll = clipping+hide+dead/alive); LiveActor
lifecycle sync is per-flag conditional (`alSubActorFunction::trySyncDead/Alive/Clipping*`).
cAll's **cHide** may hide the coin if `Shine::hideAllModel` toggles the host's al-level
hide flag (UNVERIFIED — read `Shine::hideAllModel` decomp first). Do NOT just drop to
`registerSubActorSyncClipping` — that also drops dead-sync and orphans the coin after
collection; the right move is a clipping+dead (no-hide) combo or hiding the host without
an al-hide path.

---

## Part 2 — IMPLEMENTED v1 (2026-06-28) — Route A (decorative child coin model)

Built, compiles + links clean (`build_switchmod.py`, `[98/98]`), staged but NOT yet
deployed/tested in-game. All in `switch-mod/src/hooks/ShineAppearanceHook.cpp`
(switch-mod-only — no apworld rebuild / re-seed; the existing palette-index wire
field already encodes "our-own-slot moon for kingdom X"). Symbols added to
`HookSymbols.hpp` (all CALL-only via `lookupSymbol`, **not** in the sail `.sym` —
graceful-skip on miss, like `setStageShineAnimFrame`).

**Scope (Devon, 2026-06-28):** in-world only · uncollected only · 3D moons only
(2D dot shines keep Part-1 color-only).

**How it works (Route A — chosen over archive-swap):** `Shine::init` builds its
model via `al::initActorWithArchiveName(this, info, rs::getStageShineArchiveName(this), …)`
(confirmed by `main.nso` disasm) — and that SAME archive drives the Shine's collect
sensor + state actions, so swapping the string (the trivial route) would risk
breaking collection / crashing on missing Shine anims. **Unacceptable for a cosmetic
feature.** Instead we leave the Shine 100% intact and, in the existing `Shine::init`
post-orig hook, for our-own 3D kingdom moons:
1. resolve the granted kingdom's worldId (palette bit → `kingdomBitForWorldId`
   inverse; honors the Sea/Snow swap),
2. `GameDataHolder::getCoinCollectArchiveName(worldId)` → the `CoinCollect<letter>`
   archive (runtime, data-driven, not IP),
3. spawn a decorative model-only child `al::LiveActor` from that archive
   (`operator new` on the stage heap + `al::LiveActor` ctor + `initActorWithArchiveName`),
   strip its sensors/collision (`invalidateHitSensors`/`offCollide`), scale it
   (`setScaleAll`, `kCoinModelScale`), `makeActorAlive`, `registerSubActorSyncAll(shine, child)`
   so it follows transform + show/hide + alive/dead,
4. `Shine::hideAllModel(shine)` so only the coin shows in-world,
5. color the coin once via the existing `writeBodyTint` on material **`BodyMT`**
   (the coin model uses the SAME material name as the moon — verified in the bfres —
   so the Part-1 recolor path works unchanged; coins have no "Color" Mcl anim so it's
   always the material-tint path, never the frame override).

Per-frame `Shine::control` hook re-hides the moon model + re-tints the coin (guarded
flags), keyed by a `uid → child` map. The get cutscene shows a SEPARATE demo model
(`hideAllModel` doesn't touch it) which the existing visible-model pass still recolors
→ cutscene = normal moon in the kingdom color (consistent with Part 1).

**Coinless kingdoms** (CollectCoinNum=0 in `SystemData/WorldList`): Cloud, Ruined,
Dark, Darker — `kHasRegionalCoin[]` skips them (their `WorldItemTypeInfo` entry may be
null → `getCoinCollectArchiveName` would null-deref), so those moons stay recolored
moons. (Ruined's "unused purple-coin model" the plan mentions is a future add.)

**Revert:** `kCoinModelSwap = false` (master) — every moon reverts to a recolored moon.

**On-device unknowns to verify (build → deploy → test; cannot be settled off-Switch):**
1. **Cross-kingdom archive load** — the #1 risk. Loading e.g. `CoinCollectK`
   (Bowser's) while standing in Cascade: regional-coin archives are normally only
   resident in their home kingdom. `initActorWithArchiveName` may hitch or assert if
   the archive isn't loadable on demand. *Test a same-kingdom moon first* (archive
   resident), then a foreign-kingdom one.
2. **Scale** (`kCoinModelScale`, currently 2.0) — coins are smaller than moons; tune.
   `registerSubActorSyncAll` may sync the host scale and clobber it (the per-frame
   re-tint doesn't re-apply scale — add if needed).
3. **`hideAllModel` re-show** — if a Shine state re-shows the moon model alongside the
   coin, the per-frame `kCoinReHidePerFrame` re-hide should catch it; confirm.
4. **Cutscene/coin visibility** — confirm the coin child hides during the get cutscene
   (sub-actor sync) and the demo moon shows kingdom-colored; confirm coin dies on
   collect.
5. **Coin color** — frame-override kingdoms' `kPaletteColors3D` rows are approximations
   ("BodyMT" tint multiplies against the coin's own albedo); expect a per-kingdom tuning
   pass to match the moon colors.
6. **Sensor-less child** — confirm Mario can't interact with / isn't pushed by the coin
   and collection still works by walking into the (hidden) moon.

Build log tells: `[coin-swap] uid=… kingdom_bit=… worldId=… archive=CoinCollect… child=…`
on each swap; `getCoinCollectArchiveName resolved @ …` etc. at boot.

---

## Part 2 — Coin-model swap (the caveat): ~55%, high effort (original analysis)

This is a fundamentally harder, explicitly-deferred problem ("Purple-coin model swap
is a separate, deferred problem" — plan-v2-vision.md). The recolor above changes
*material color*; this changes the *model itself*.

### What makes it hard

1. **The Shine actor is UNDECOMPILED.** `Shine.cpp` does **not** exist in
   OdysseyDecomp (only `Shine.h` / `ShineInfo.h` — confirmed this session). So how
   `Shine::init` builds its model, what `tryChangeCoin()` / `exeCoin()` do, and how
   the model keeper is wired must be recovered from a **Ghidra/objdump pass on
   `main.nso`** — not a decomp read. (Same situation as the cappy-commentary doc.)
   The material-tint hook gets away without the body; a model swap does not.

2. **The purple/regional coins are a distinct model from the gold `Coin`.** `Coin.h`
   is the ordinary gold coin (uniform shape). Regional coins are per-kingdom models
   with **kingdom-specific silhouettes** — so achieving the requested look needs the
   actual per-kingdom regional-coin **model archives** (their names, and confirmation
   they load correctly *outside* their home kingdom). Identifying those is a
   **romfs/decomp investigation on Devon's machine** and is **IP-sensitive** — archive
   names/models stay gitignored, same regime as `shine_map` extraction. The plan can
   only document where to regenerate, not commit the data.

3. **Ruined's "unused purple-coin model"** needs romfs confirmation that such an
   archive exists and its name. Devon asserts it does; treat as a to-verify.

### Promising leads (from `Shine.h`)

`Shine` already exposes `hideAllModel()`, `getCurrentModel()`, `showCurrentModel()`,
`tryChangeCoin()`, and an `exeCoin()` state — SMO **already has an internal
"shine renders as a coin" path** (already-collected shines appear as a coin). Two
candidate implementation routes:

- **Route A — hide + attach.** `hideAllModel()` on the shine, spawn/attach a
  coin-model sub-actor at the shine's transform, scale to moon size, and retarget the
  existing tint code at *that* model's material name (BodyMT differs on the coin
  model). Cleaner separation; the attached model must follow the shine through its
  states (at minimum the in-world `Wait`/`Appear` states) and must not interfere with
  collection (the kill-sensor / `get` path stays on the original shine).
- **Route B — archive swap at init.** Intercept the model archive `Shine::init`
  loads and substitute the regional-coin archive. Needs the disasm to find the seam;
  risk it's inlined/awkward inside the big init.
- **Route C — repurpose the built-in coin path** (`tryChangeCoin`/`exeCoin`). Lowest
  effort *if* it's drivable at spawn, BUT it yields the **gold** coin (uniform shape),
  not the per-kingdom purple silhouettes the request wants — so it only satisfies the
  ask if Devon would accept "recolored gold coin shape" instead of true regional-coin
  shapes. Worth confirming the visual expectation before ruling it in or out.

### Other unknowns / risks

- **Cutscene surface.** The moon-get cutscene shows the model prominently; a swapped
  model may look broken there. Scope could be limited to the **in-world wait
  appearance only** (the most visible/wanted state), leaving the get-cutscene as the
  normal moon. Decide scope early.
- **Resource/memory.** Loading 16+ regional-coin archives that aren't normally
  resident in a given kingdom is an unknown — heap pressure and archive availability
  when you're not in that coin's home kingdom. May need on-demand load or a shared
  atlas.
- **Per-machine + IP.** Archive names and any extracted model data stay gitignored;
  the wizard/extraction-style "regenerate locally" pattern applies.

---

## Recommendation

- **Ship Part 1 (recolor) as P5 proper** — it's small, self-contained, high-value,
  and the pipeline already exists. The kingdom-of-the-granted-moon keying is the
  natural and easy choice here.
- **Treat Part 2 (coin models) as its own later spike.** First decisions that gate
  effort: (a) does Devon require true per-kingdom purple-coin *shapes*, or would a
  recolored coin silhouette do (Route C)? (b) in-world-only or also the get-cutscene?
  Then do the `main.nso` disasm of `Shine::init` + `tryChangeCoin`/`exeCoin` and the
  romfs hunt for regional-coin archive names (incl. the unused Ruined one) before any
  build cycle — per CLAUDE.md's "read the decomp/disasm before picking a chokepoint."

**Why the split rating:** Part 1 reuses a shipped, proven pipeline (≈95%, small).
Part 2 is genuine model/actor reverse-engineering against an undecompiled actor plus a
romfs data hunt (~55%, high) — feasible (the `hideAllModel`/coin-state hooks are real
seams and SMO already renders shines as coins internally), but with several
load-bearing unknowns that can only be resolved on Devon's machine.

Sources consulted (disk-truth reads this session):
[ShineAppearanceHook.cpp](../../switch-mod/src/hooks/ShineAppearanceHook.cpp),
[Shine.h](../../switch-mod/lib/OdysseyHeaders/game/Item/Shine.h),
[Coin.h](../../switch-mod/lib/OdysseyHeaders/game/Item/Coin.h),
[client/config.py](../../apworld/smo_archipelago/client/config.py),
[client/maps.py](../../apworld/smo_archipelago/client/maps.py),
[plan-v2-vision.md §P5](../plan-v2-vision.md); OdysseyDecomp `src/Item/` listing
(confirmed `Shine.cpp` absent — actor body undecompiled).
