# 2D Power Moon recolor — Phase 1 research notes

Context: the existing `ShineAppearanceHook` recolors 3D Power Moons by AP
classification, but in-game 2D moons (collected in side-scrolling mural rooms)
still render as vanilla yellow. The previous working hypothesis — "2D moons go
through a different actor class" — turned out to be **wrong**. This note
records what's actually true and lays out what to verify on the Windows box
before writing C++.

## Finding #1 — there is no `Shine2D`

Both lunakit-vendor and OdysseyDecomp confirm: SMO 1.0.0 has one `Shine` class
that handles every variant. Three different placement names route to the same
constructor:

```cpp
// switch-mod/lunakit-vendor/src/al/factory/ActorFactoryEntries100.h
{"Shine",                &al::createActorFunction<Shine>},
{"ShineWithAppearCamera", &al::createActorFunction<class Shine>},
{"ShineDot",             &al::createActorFunction<class Shine>},
```

`Shine` inherits from `al::LiveActor` and `IUseDimension`; it has a
`ActorDimensionKeeper* mDimensionKeeper` at offset `0x288` and `int shineId`
at offset `0x290` (the same offset the current 3D hook reads via
`kShineMShineIdxOffset`).

`"ShineDot"` is the 2D variant — the "Dot" suffix mirrors the 2D coin naming
convention (`CoinDot` archive used by `Coin2D::init`,
`OdysseyDecomp/src/Item/Coin2D.cpp:44`).

## Finding #2 — `setStageShineAnimFrame` plays a *named animation*

From `OdysseyDecomp/src/Util/ItemUtil.cpp:621`:

```cpp
void setStageShineAnimFrame(al::LiveActor* actor, const char* stageName,
                            s32 shineAnimFrame, bool isMatAnim) {
    if (shineAnimFrame != -1) {
        if (shineAnimFrame == 99) return;
        return startShineAnimAndSetFrameAndStop(actor, "Color", shineAnimFrame, isMatAnim);
    }
    // ... fallback paths that look up the stage's default frame
}
```

`startShineAnimAndSetFrameAndStop` dispatches to either
`al::startMtpAnimAndSetFrameAndStop` (material parameter animation) or
`al::startMclAnimAndSetFrameAndStop` (material color animation) on the
animation named `"Color"`. So **the recolor only works if the actor's
loaded archive contains a `Color` matanim with multiple frames**.

## Finding #3 — the existing hook's comment is the smoking gun

`switch-mod/src/hooks/ShineAppearanceHook.cpp:66-67`:

> "Per-shine, each Shine::init fires 2 of the 4 patches, so 2 fires per
> moon is the natural rate — 16 substitutions covers ~8 shines."

The 4 patched offsets are paired — pair 1 (`setShineColor` + `setShineModelColor`)
and pair 2 (same, repeated). Only 2 fire per moon. That suggests an
`if/else` inside `Shine::init` selecting between two model-application paths
(likely: main shine model vs. empty/shadow model, OR 3D model vs. 2D model).
We can't tell from the source alone which branching exists; the disassembly
will say.

## Most likely diagnosis (to verify, not assume)

There are two consistent explanations for the user's observation that
vanilla 2D moons all share one color:

**A. ShineDot's `Color` matanim is single-frame.**
The same 4 inline patches fire on `ShineDot` instances; W2 gets substituted
correctly; but the loaded `ShineDot.bcmpa` only has one frame (the vanilla
yellow), so the frame index has no visible effect.

**B. ShineDot takes a different branch inside `Shine::init`.**
The branch loads `ShineDot.szs` and either bypasses the
`setStageShineAnimFrame` calls entirely or routes them through a different
codepath that our 4 offsets don't cover.

(A) is more consistent with the lunakit factory layout — same `Shine` ctor,
no separate init function — but only the binary will tell us for sure.

## What to do next — Windows-side runbook

The remote sandbox doesn't have `main.nso` or Ryujinx. The user runs these
on the Windows dev box. Either step is enough to disambiguate A vs B; run
the quick one first.

### Step 1 — observe whether existing patches fire on 2D shines (5 min)

1. Build & deploy with the current ShineAppearanceHook (use the `smo-build`
   skill).
2. Boot a save with a 2D moon nearby. Easiest: **Cap Kingdom → "Behind the
   Big Wall"** is a 2D mural room near the start of the game.
3. Walk into the 2D section, but **don't collect the moon yet**. Tail
   Ryujinx `lm.log` for `[shine-color] subst#…` lines.
4. The hook logs every substitution (lines 65-73). If lines appear for the
   2D shine's UID → patches fire, diagnosis is (A), the fix is a material-
   color override on the loaded ShineDot model.
5. If no log line appears for that UID → diagnosis is (B), the fix is to
   find ShineDot's separate BL offsets and patch them too.

To know the 2D shine's UID, cross-reference the kingdom + obj_id in
`apworld/smo_archipelago/client/data/shine_map.json` (gitignored — already
generated locally via `scripts/extract_shine_map.py`).

### Step 2 — disassemble `Shine::init` (10 min, only if Step 1 inconclusive)

```bash
# Mangled init symbol — Itanium ABI for `Shine::init(const al::ActorInitInfo&)`:
SYM=_ZN5Shine4initERKN2al13ActorInitInfoE

# Cross-check it's in the binary first
python scripts/check_nso_symbols.py --symbol "$SYM" \
  C:/Users/maxwe/Downloads/main.nso

# Disassemble its body
aarch64-none-elf-objdump -d --disassemble="$SYM" \
  C:/Users/maxwe/Downloads/main.nso > shine_init.s

# Look for branch decisions and BL targets
grep -nE "^ *[0-9a-f]+:.*\b(bl|cbz|cbnz|b\.eq|b\.ne)\b" shine_init.s | head -60
```

What to look for:
- BLs to `rs::setStageShineAnimFrame` — should see the 4 known offsets
  (`0x1cdce4 / 0x1cdd3c / 0x1cddcc / 0x1cde24`) plus any additional ones
  in a separate branch.
- BLs to `al::initActorWithArchiveName` — note the string args (likely
  `"Shine"` for 3D, `"ShineDot"` for 2D). The branch that picks between
  them is the dimension/name selector.
- BLs to `al::startMtpAnimAndSetFrameAndStop` /
  `al::startMclAnimAndSetFrameAndStop` — these are the actual color-animation
  starters; might be called directly outside of `setStageShineAnimFrame`.
- BLs to `al::setMaterialProgrammableColor` / `al::setModelMaterialColor` —
  if the ShineDot path uses a uniform override instead of an animation.

### Step 3 — inspect `ShineDot.szs` color animation (5 min, optional)

In the locally extracted romfs (`.romfs-cache/` per CLAUDE.md, gitignored):

```bash
# Find the archive
find .romfs-cache -iname 'ShineDot.szs' -o -iname 'ShineDot.*'

# Inspect via switchToolbox or any szs viewer — look for a *.bcmpa file
# inside the archive named "Color".
# - Multiple frames -> diagnosis (A) is wrong about the matanim being flat;
#   recheck whether patches actually fire.
# - Single frame -> diagnosis (A) confirmed; need material-color override.
```

## Pre-designed implementations (chosen after Step 1/2)

### Branch A (most likely): `ShineDot` matanim is flat — apply material color override

The cleanest fix:

- Add a post-`Shine::init` hook (symbol-hook the init, run after the
  trampoline) that detects 2D mode via `mDimensionKeeper->is2D()` and,
  for any shine with a non-default palette, calls a material-color setter
  on the loaded model.
- Candidate setters (need symbol-resolve against main.nso):
  - `al::setMaterialProgrammableColor(actor, materialName, sead::Color4f)`
  - `al::setMaterialColor(actor, sead::Color4f)`
  - `al::setModelMaterialColor(...)` — exact name varies by SMO build
- Add a tiny static palette → `sead::Color4f` table (5 entries: classification
  default + 4 AP classifications) — RGBA values to match what the 3D
  per-stage palette resolves to for the "canonical" stage.

### Branch B (less likely): `Shine::init` has a separate ShineDot branch

- Disassemble (Step 2) gives the new BL offsets inside Shine::init's 2D
  branch.
- Add a second offset array in
  `switch-mod/src/hooks/ShineAppearanceHook.cpp` and a second
  `HOOK_DEFINE_INLINE` (or reuse the existing callback if X0/W2 calling
  convention matches). ~30 lines, very low risk.

Either branch reuses the existing `ApState::shine_palette[]` table — no
wire-protocol changes, no apworld changes.

## Critical files

- `switch-mod/src/hooks/ShineAppearanceHook.cpp` — 3D pattern, the place
  to extend.
- `switch-mod/src/hooks/HookSymbols.hpp` — if Branch A needs a new symbol
  (a material setter), it goes here. Use the `smo-symbol-discovery` skill.
- `switch-mod/src/ap/ApState.hpp` — `shine_palette[]` is shared, no change.
- `apworld/smo_archipelago/client/data/shine_map.json` (gitignored, regenerated
  per CLAUDE.md) — cross-reference 2D shine UIDs for the live test.

## References

- `OdysseyDecomp/src/Item/Shine.h` — class layout (sizeof = 0x380),
  `getCurrentModel()` confirms multi-model support.
- `OdysseyDecomp/src/Item/Coin2D.cpp:44` — 2D-variant naming precedent
  (`"CoinDot"` archive for `Coin2D`).
- `OdysseyDecomp/src/Util/ItemUtil.cpp:279-342` — `initShineByPlacementInfo`
  + `initLinkShineChipShine` show how `"ShineDotActor"` link gets routed.
- `OdysseyDecomp/src/Util/ItemUtil.cpp:621` — `setStageShineAnimFrame` plays
  the named `"Color"` animation.
- `lunakit-vendor/src/al/factory/ActorFactoryEntries100.h:480-483` — proof
  that `"Shine"`, `"ShineWithAppearCamera"`, and `"ShineDot"` all map to
  the same `Shine` constructor.
- `lunakit-vendor/src/game/Actors/Shine.h:36-37` — confirms
  `mDimensionKeeper @ 0x288` and `shineId @ 0x290`.
