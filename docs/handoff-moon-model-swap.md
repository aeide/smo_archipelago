# Handoff: Per-check Power Moon MODEL swap (purple-coin / custom models)

**Status: research complete, not implemented.** Goal: show each moon check as a different
3D model based on its AP contents (Devon's ask: each kingdom's purple regional coin), the
way the recolor system already varies moon *color* per check. A community video (frame
analyzed 2026-07-19: Cap Kingdom bridge, vanilla purple top-hat coin on deck, the Wooded
Kingdom **Nut** model floating in the moon spot) proves a foreign mesh in the Shine slot
renders and plays fine in-game.

## Why this is architecturally native, not a hack

Decomp read (`OdysseyDecomp/src/Util/ItemUtil.cpp`, raw fetch 2026-07-19):

- `rs::getStageShineArchiveName(actor, stageName)` returns `"Shine"` — **except
  Mushroom Kingdom, where it returns `"PowerStar"`**. Vanilla SMO already swaps the
  Power Moon's entire model archive per kingdom (MK moons are Power Stars). There is a
  parallel `getStageShineEmptyArchiveName` → `"ShineEmpty"` / `"PowerStarEmpty"`.
- Regional purple coins are per-kingdom archives resolved by
  `GameDataHolder::getCoinCollectArchiveName(worldId)` (+ 2D and Empty variants) — so
  the per-kingdom coin models are individually addressable archives in `ObjectData/`.
  Enumerate exact names from `.romfs-cache` `ObjectData/CoinCollect*`.
- `rs::syncCoin2DAnimFrame` uses `al::setVisAnimFrameForAction` /
  `al::getVisAnimFrameMax` — vanilla picks a coin's visual variant by driving a
  **visibility-anim frame**. Frame-indexed model variation is an engine-idiomatic
  pattern, same shape as the Shine "Color" Mcl anim we already drive.
- `Shine.h` (OdysseyHeaders): `getCurrentModel()`, `addDemoModelActor()`,
  `tryChangeCoin()` / `exeCoin()` — the Shine already hosts multiple child model actors
  and switches between them (world model, get-cutscene demo model, already-collected
  coin form). Shine.cpp itself is **undecompiled** — exact init ordering (when
  `mShineIdx` is set vs. when the model actor is created) cannot be read, only probed.

## The video's mod (IDENTIFIED 2026-07-19)

The video is SmallAnt's "I Challenged the SMO World Record Holder and Moarf to a
Randomized Race" (youtube.com/watch?v=ibRhyoIFz4E, July 2026). Per Devon: the
randomizer is **authored by CraftyBoss, private / unreleased, and NOT Archipelago**.
Storyboard-frame analysis of the 6:30-7:10 window confirms per-check model swaps in
the wild, including the two hardest cases:

- ~6:40, Lost Kingdom: a floating sparkling BLUE CRESCENT model in a moon slot.
- ~7:05: the **"You got a Moon!" get cutscene showing Mario holding up a yellow
  crescent model** — banner reads "Caught on the Iron Fence (Snow)" while Mario is
  visibly NOT in Snow. So his mod (a) relocates checks across kingdoms and (b) swaps
  the display model per check, and the swap **survives the get-cutscene demo model**
  (our uniform-Luncheon-blue war zone). The thumbnail also shows a giant Super Star
  in Cap; Devon's frame shows the Wooded Nut in Cap.

Implication: since the swapped model appears in BOTH the world Shine and the held-up
demo model, the swap must happen at model-archive/creation level (Option A shape),
not per-frame material driving. CraftyBoss builds on exlaunch (SMO-Exlaunch-Base) —
same runtime-hooking capability class as our LibHakkun setup, so nothing he did is
out of reach for us. He has a public-collaboration track record (SMOO is MIT;
Kgamer77's AP mod builds on his work) — **worth simply asking him** how the swap is
plumbed before reverse-engineering it (Devon's call).

Public prior art for the asset side: GameBanana's Shine.szs replacement scene
("Power Star over Moon (WIP)" by TheSunCat, custom-model tutorials/questions). The
standard pipeline: open `ObjectData/Shine.szs` (SARC+Yaz0) in **Switch Toolbox**
(KillzXGaming), replace the mesh inside the bfres while keeping the skeleton /
materials / anim set, repack.

## Three implementation options, ranked

### Option C (RECOMMENDED): one modified Shine.szs + vis-anim frame selection
Bake all variant meshes into ONE Shine bfres, add a visibility anim (e.g. `ApModel`)
where frame k shows mesh k (frame 0 = vanilla moon). At runtime drive
`al::startVisAnimAndSetFrameAndStop(actor, "ApModel", frame)` from the SAME places the
recolor already runs (`Shine::init` post-orig, `Shine::control` per-frame enforce,
demo-model path via `getCurrentModel()`), guarded by `al::isVisAnimExist(actor,
"ApModel")` so an absent/vanilla archive fails open. Full al vis-anim API confirmed in
OdysseyHeaders `ActorAnimFunction.h` (`startVisAnimAndSetFrameAndStop`,
`setVisAnimFrameAndStop`, `isVisAnimExist`, `getVisAnimFrameMax`).

Why ranked first: the decision point is post-init where `resolveShinePalIdx` already
works (no unknown init-ordering risk); one archive means one load path, no per-stage
memory question, no new game-function hook (al functions are called-from-our-code, not
trampolined — no inlining concern); and it reuses the per-frame enforcement that
already survives cutscenes/spawn paths. Cost is asset authoring: importing meshes and
authoring a vis anim in Switch Toolbox (bfvis). Risk: get-cutscene demo model + dot
(2D) shines + grand shines need the same guard-and-skip treatment the recolor grew.

### Option A: per-check ARCHIVE swap via the vanilla seam
Build N variant archives (clone Shine.szs, swap mesh, keep anims) shipped via
LayeredFS, then make the Shine load the right one per check. Chokepoint:
`rs::getStageShineArchiveName`. ⚠ CLAUDE.md hook rule applies: it's called from
UNDECOMPILED Shine.cpp, so a resolving symbol ≠ the decision flows through it (may be
inlined), and it's unknown whether `mShineIdx` is populated when it's called — needs a
logging probe build. More moving parts than C; only worth it if variants need
different materials/anims that can't share one bfres.

### Option B: global romfs replace (zero code)
Replace/patch Shine.szs so ALL moons become one model — what the video likely did. No
per-check variation; useful only as a 30-minute pipeline validation before investing
in C (confirm a swapped mesh + kept anim set doesn't crash appear/get/demo paths).

## Asset pipeline + IP line (both options need this)

Modified Shine.szs contains Nintendo meshes → **NEVER commit, never ship in releases.**
Same treatment as shine_map.json: a script (wizard step) builds the archive(s) on the
user's machine from their own `.romfs-cache` dump, output gitignored, deployed to
Ryujinx LayeredFS — romfs goes at
`%APPDATA%\Ryujinx\mods\contents\0100000000010000\romfs\ObjectData\` (next to the
confirmed-loading exefs, no per-mod subfolder in our setup). Tools: Switch Toolbox for
bfres mesh import + SARC/Yaz0 repack; scriptable alternatives for the repack step:
SarcLib + libyaz0 (Python). The mesh-merge/vis-anim authoring step is the main
open engineering question — prototype by hand in Switch Toolbox first, automate later.

## Suggested next steps

0. (Cheap, possibly decisive) Reach out to CraftyBoss about how his private
   randomizer swaps moon models — it demonstrably solves the get-cutscene case.
1. Option B smoke test by hand (validate mesh swap survives appear/get/demo).
2. Author a 2-mesh vis-anim Shine.szs prototype (vanilla moon + one coin), hand-driven
   via a debug `/`-command before wiring palette→frame mapping.
3. Wire palette→frame into ShineAppearanceHook alongside the color logic (same
   pal_idx, `kKingdomModelFrame[]` table analogous to `kKingdomColorFrame[]`).
4. Only if C's single-archive constraint fails, probe Option A's chokepoint.
