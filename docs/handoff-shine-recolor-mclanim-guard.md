# Handoff — P5 moon recolor frame-override crash guard (`isExistMclAnim` lookup failed)

**Date:** 2026-06-21
**Status:** RESOLVED IN SOURCE (awaiting build + in-game confirmation). The guard symbol
name was wrong — the al convention is `is<Family>AnimExist`, so the function is
**`al::isMclAnimExist`**, not `isExistMclAnim` (verified against OdysseyHeaders
`ActorAnimFunction.h:167`). Constant + references renamed on disk; the guard remains
permissive-on-miss but now resolves. **Rebuild + deploy, then check the boot log for
`isMclAnimExist resolved @ 0x…`** and re-test the Pyramid/Sand stub-shine case.

### Resolution (2026-06-21)
- [HookSymbols.hpp:463-464](../switch-mod/src/hooks/HookSymbols.hpp#L463-L464) — constant
  renamed `kAlIsExistMclAnim` → `kAlIsMclAnimExist`, value
  `_ZN2al14isMclAnimExistEPKNS_9LiveActorEPKc` (only the name token changed; both names are
  14 chars so the length prefix already matched — that's why the wrong name looked plausible).
- [ShineAppearanceHook.cpp](../switch-mod/src/hooks/ShineAppearanceHook.cpp) — function
  pointer `s_isExistMclAnim` → `s_isMclAnimExist`, guard + `resolveSymbol` registration +
  log label updated.
- The stub shine has a model (passes `isExistModel`) but a null Mcl AnimPlayerMat;
  `al::isMclAnimExist` null-checks the player (`getMcl` may return null) and returns false,
  so the frame path is skipped and the actor falls through to the material-tint fallback.

Everything below is the pre-resolution analysis, kept for provenance.

---

## TL;DR for the next session

1. The kingdom-color pipeline is **working end-to-end**. Client assigns palette by the
   *granted item's* kingdom (not physical stage — confirmed correct). Stale installed zip
   was the original "no colors" cause; fixed via `install_apworld.py`.
2. The frame-override path (authentic vanilla per-kingdom color via
   `rs::setStageShineAnimFrame` → Mcl "Color" anim) **fires and recolors correctly** for
   normal shines. `kColorAnimIsMatAnim = false` (Mcl) is VERIFIED correct — do NOT flip it.
3. A **stub Pyramid-linked Shine** (`Pyramid::init` → `createLinksActorFromFactory`) has a
   model (passes `isExistModel`) but **no Mcl "Color" anim player**, so the frame call
   null-derefs in `al::AnimPlayerSimple::startAnim`. We added a guard:
   `al::isExistMclAnim(self, "Color")`.
4. **The guard symbol fails to resolve**: `[smoap err] isExistMclAnim lookup FAILED`.
   Because the guard is permissive-on-miss, the frame path runs unguarded → **the crash
   will recur** on any stage that spawns a stub linked-Shine (Pyramid / Sand Kingdom).

---

## Immediate problem (do this first)

`resolveSymbol(kAlIsExistMclAnim, s_isExistMclAnim, ...)` logs FAILED, leaving
`s_isExistMclAnim == nullptr`. The guard in
[ShineAppearanceHook.cpp:295-296](../switch-mod/src/hooks/ShineAppearanceHook.cpp#L295-L296):

```cpp
const bool color_anim_ok =
    s_isExistMclAnim == nullptr || s_isExistMclAnim(self, "Color");
```

`nullptr` → `color_anim_ok == true` → frame override runs for the stub shine → **crash**.

**Two ways forward — pick based on whether you want recolor live while debugging:**

- **(A) Make the build crash-safe right now (interim):** flip the permissive default to
  restrictive so a missing guard symbol *disables* the frame path entirely (everything
  falls through to the material-tint fallback — the 6 "tint" kingdoms look right, the 11
  frame kingdoms lose authentic color but DON'T crash). One-line change:
  ```cpp
  const bool color_anim_ok =
      s_isExistMclAnim != nullptr && s_isExistMclAnim(self, "Color");
  ```
  (i.e. `!= nullptr &&` instead of `== nullptr ||`). Rebuild + deploy → no crash, no
  authentic frame color until the symbol is fixed.

- **(B) Fix the symbol so the guard actually works** (preferred — restores authentic color
  AND crash safety). See next section.

---

## Why `al::isExistMclAnim` doesn't resolve — ranked hypotheses

`hk::ro::lookupSymbol(mangled)` resolves against **SMO's dynsym export table**. A miss means
the mangled name is not an exported dynamic symbol. Reasons, most → least likely:

1. **Not exported / inlined.** Unlike `al::isExistMaterial` and `al::isExistModel` (both
   resolve fine — they're exported and used out-of-line), `al::isExistMclAnim` may be a
   tiny inlined accessor with **no out-of-line copy in the dynsym**. This is the classic
   CLAUDE.md inlining trap. If so, `lookupSymbol` can never find it — need a different
   probe or a sail entry with a hard address.
2. **Wrong symbol name.** The al anim-existence API may not be spelled `isExistMclAnim`.
   Candidates to verify in OdysseyDecomp: `al::isExistMclAnim`, `al::isMclAnimExist`,
   `al::isExistMclAnimResource`, or a generic `al::isExistAnim(actor, name, type)`. The
   current constant is
   [`kAlIsExistMclAnim = "_ZN2al14isExistMclAnimEPKNS_9LiveActorEPKc"`](../switch-mod/src/hooks/HookSymbols.hpp#L463-L464)
   — `al::isExistMclAnim(const al::LiveActor*, const char*)`. The mangling shape is
   correct *if* that's the real name/signature (mirrors `kAlIsExistMaterial`).
3. **Wrong signature mangling.** If the real param list differs (e.g. takes an enum, or no
   `const`), the mangled string won't match even if the function is exported.

### How to verify (do NOT guess — read the decomp + the dynsym)

- **Decomp:** `WebFetch` the al anim headers from OdysseyDecomp to find the exact name +
  signature. Good starting points:
  - `https://raw.githubusercontent.com/MonsterDruide1/OdysseyDecomp/master/src/Library/Anim/MtpAnimHolder.h`
  - `.../src/Library/LiveActor/ActorAnimFunction.h`  (the `al::startMclAnim*` /
    `al::isExist*Anim*` family usually lives here)
  - grep the decomp for `isExist` + `Mcl` / `Mtp` to see the actual spelling.
- **Dynsym (is it exported?):** the function MUST be in `main.nso`'s dynamic symbol table
  for `lookupSymbol` to find it. Use LLVM tools on the (gitignored) extracted NSO, e.g.
  `llvm-nm --dynamic .romfs-cache/...main.nso | grep isExist` (or `llvm-objdump -T`).
  If `isExistMaterial`/`isExistModel` show up but the Mcl variant does NOT, hypothesis #1
  is confirmed → you need an alternative probe, not a name fix.

---

## If the symbol is genuinely not exported — alternative guards

The goal of the guard is only: *"does this Shine have an Mcl 'Color' anim player, or is it
a stub that will null-deref?"* Options that don't depend on the missing symbol:

1. **Probe a DIFFERENT exported al function** that null-safely reports Mcl-anim presence.
   Whatever the decomp shows as actually-exported (check dynsym). `al::isMclAnimEnd` /
   `al::getMclAnimFrameMax` etc. are NOT safe (they deref the player). Look specifically
   for an `isExist`-style probe that early-returns false on a null player.
2. **Structural guard on the stub.** The crashing shines are created by
   `rs::tryInitLinkShine` / `createLinksActorFromFactory` without a full model archive.
   If there's a cheap, null-safe way to detect "linked stub" (a flag/field on the Shine, or
   the model keeper's anim-holder pointer being null), gate on that. Requires reading
   `Shine.h` + the link-shine init path in the decomp. NOTE: keying on `unique_id` being a
   known scouted moon will NOT help — the crashing stub (override#1 was `unique_id=893`,
   logged success; the crash was a *later* stub) also carries an in-range uid and a
   kingdom palette.
3. **Wrap the call defensively.** Not really possible from C++ (the null-deref is inside
   the engine call), so a pre-call existence probe is the only real option — hence #1/#2.
4. **Add the symbol to sail with a hard address** (`SmoApSymbols.sym` + an address from the
   NSO) only if you find an out-of-line copy at a fixed offset. Last resort; brittle across
   builds, and the whole point of `lookupSymbol` was to avoid pinning addresses.

---

## What was changed this session (all on disk, NOT yet crash-correct)

- [HookSymbols.hpp:463-464](../switch-mod/src/hooks/HookSymbols.hpp#L463-L464) — new
  `kAlIsExistMclAnim` constant. **This name is unverified — likely the bug.**
- [ShineAppearanceHook.cpp:224](../switch-mod/src/hooks/ShineAppearanceHook.cpp#L224) — new
  `s_isExistMclAnim` function pointer.
- [ShineAppearanceHook.cpp:295-310](../switch-mod/src/hooks/ShineAppearanceHook.cpp#L295-L310)
  — the `color_anim_ok` guard (permissive-on-miss — change to restrictive for interim
  safety, see option A above).
- [ShineAppearanceHook.cpp:370-371](../switch-mod/src/hooks/ShineAppearanceHook.cpp#L370-L371)
  — `resolveSymbol` registration (this is what logs FAILED).
- [ShineAppearanceHook.cpp:158-165](../switch-mod/src/hooks/ShineAppearanceHook.cpp#L158-L165)
  — comment marking `kColorAnimIsMatAnim = false` (Mcl) VERIFIED. Keep false.
- `apworld/smo_archipelago/client/context.py` — removed `[shine-color][dbg]`
  instrumentation (cosmetic; client logic confirmed correct). Needs `install_apworld.py`
  + SMOClient restart to land (no re-seed).

---

## Established facts (don't re-derive)

- Client palette is keyed to the **granted item's kingdom** (`item_player == self.slot`,
  classify item → `for_kingdom`), with AP classification color fallback. Devon confirmed
  this is the desired behavior: a Bowser's-Kingdom *item* physically located in Sand
  Kingdom must get **Bowser's** color. WORKING.
- Palette index layout: idx 0-4 classification, idx 5..21 = 17 kingdoms
  (`kKingdomPaletteBase = 5`). `kingdom_id = pal_idx - 5`. `kKingdomColorFrame[kingdom_id]`
  → vanilla frame (-1 = `kColorFrameTint` = fall to material tint).
- Mcl vs Mtp: the Shine "Color" anim is **Mcl (material color)**, so
  `kColorAnimIsMatAnim = false`. Verified in-game (normal shine `unique_id=893` recolored,
  no crash). Mtp has no "Color" anim → flipping to true would null-deref every moon.
- The crash is ONLY the stub Pyramid-linked Shine (model present, no Mcl anim player).
  Crash site: `setStageShineAnimFrame` → `startMclAnimAndSetFrameAndStop` →
  `AnimPlayerSimple::startAnim` (null player). `Invalid memory access at vaddr 0x0`.
- `Shine.cpp` is NOT decompiled upstream (only `Shine.h`); color setup is inlined in the
  undecompiled actor. `setStageShineAnimFrame` body IS in `src/Util/ItemUtil.cpp`.

## Rebuild + deploy loop (Switch-mod change)

```powershell
cd E:\smo_archipelago
$LAN_IP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' -and
    ($_.PrefixOrigin -eq 'Dhcp' -or $_.PrefixOrigin -eq 'Manual') }).IPAddress
python scripts\build_switchmod.py -DBRIDGE_HOST=$LAN_IP
$RYU = "$env:APPDATA\Ryujinx\mods\contents\0100000000010000\"
Copy-Item -Force ...\exefs\subsdk9  "$RYU\exefs\subsdk9"
Copy-Item -Force ...\exefs\main.npdm "$RYU\exefs\main.npdm"
```
Boot-log tells: success = `isExistMclAnim resolved @ 0x…`; failure = `[smoap err]
isExistMclAnim lookup FAILED` (current state).
