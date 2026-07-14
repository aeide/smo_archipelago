# Handoff — in-Odyssey takeoff gauge shows the true required moon count

**Playtest 2026-07-13 (branch `complete-entrance-randomizer`).** In every kingdom
except Cascade, the in-Odyssey takeoff gauge reads **"full on moons"** and never shows
the required moon count; the true threshold is only visible in the SMO Client tracker.
Devon wants the gauge to show the real rolled count (like vanilla, like Cascade already
does) **without** undoing the chain-arrival takeoff / backtracking behavior.

This is a **two-phase, switch-mod-only** change. Phase 1 (this commit) is a safe,
behavior-preserving **measurement build** that enumerates the caller PCs. Phase 2 is a
one-line edit that activates the fix. Nothing here touches the apworld / client / seed.

---

## Why it can't be a one-shot guess (the causal chain)

The in-Odyssey takeoff **gate** is `getPayShineNum(cur) >= findUnlockShineNum(cur)`,
reading the **current-world** free `GameDataFunction::findUnlockShineNum` **out-of-line**.
To open takeoff in free-detour kingdoms (Lake/Wooded/Snow/Seaside) and in entrance-shuffle
**chain-reached** kingdoms, `UnlockShineNumHook` forces that read to **0** — the proven
lever (free-detour iterations 2–4; confirmed in-game).

The problem: the in-kingdom takeoff **gauge** (the "needs N moons" / "full on moons" text)
reads the **same** out-of-line function. Force it to 0 for the gate and the gauge reads 0
too → "full." Established facts that pin this down:

- **`isUnlockedNextWorld` is NOT the seam.** Decomp: it *inlines* its own copy of
  `findUnlockShineNum`, and forcing it true never fired in the 2026-06-25 log. So the
  in-kingdom takeoff reads the free function out-of-line, not through `isUnlockedNextWorld`.
- **The globe labels are already correct.** They read the *by-world* member variant
  (`findUnlockShineNumByWorldId` → `GameDataHolder::findUnlockShineNum(bool*, worldId)`),
  which we leave at the rolled value. That's a *different function* from the current-world
  gauge read.
- **Gauge and gate share the current-world read.** At free-detour iteration 4 (before the
  P5 member hook existed), zeroing the free current-world function both opened takeoff *and*
  turned the gauge to "full." So a single out-of-line function feeds both.

Two consumers of one out-of-line function can only be separated by **caller PC**. The gate
and gauge call sites both live in `StageSceneStateWorldMap.cpp`, which is **undecompiled**
in OdysseyDecomp (only the header is checked in) — so the split cannot be read from source,
and the project rule is *don't guess a hook target*. Hence: measure the caller PCs live,
then apply.

### How the probe reads the caller PC

`HkTrampoline` redirects the function entry with a plain **`B`** (`Trampoline.h`
`writeBranch`), not a `BL`. So on entry to our handler, `x30`/`LR` still holds the **game
caller's return address**. `__builtin_return_address(0)`, captured as the *first* statement
of the handler, yields it. We convert it to a **main.nso text offset** (the same units
`ShopItemMessageHook` documents) and log each distinct caller once. The `BL` that made the
call sits at `(offset - 4)`.

---

## Phase 1 — the measurement walk (this build)

Build + deploy the switch-mod as usual (commands at the bottom), then:

1. Start a seed on `complete-entrance-randomizer` and reach any **non-Cascade** kingdom
   whose takeoff gauge currently reads "full on moons" — i.e. any chain-reached kingdom, or
   a free-detour kingdom (Lake/Wooded after Sand, Snow/Seaside after Metro).
2. Board the Odyssey and open the **world map / takeoff UI** so the gauge is on screen for a
   few seconds (leave it open — the reads fire per-frame).
3. Line up a flight and actually **take off** once (confirm a destination).
4. Pull the Ryujinx log and grep for `[gate-probe]`.

You'll get a handful of lines like:

```
[gate-probe] NEW caller ret=+0x2ab1c8 (BL@+0x2ab1c4) via chain-return[FORCED-0] kingdom=Sand(bit=2) origVanilla=16 — record this offset
[gate-probe] NEW caller ret=+0x2ac0f0 (BL@+0x2ac0ec) via chain-return[FORCED-0] kingdom=Sand(bit=2) origVanilla=16 — record this offset
```

Expect **2–3 distinct offsets**. Tags tell you the family:
`free-detour[FORCED-0]` / `chain-return[FORCED-0]` = current-world free read forced to 0
(the gauge is almost certainly one of these); `member[...]` = the by-world member seam (only
appears if the gauge reads *that* instead); `honest-rolled` = the same callers in a normal
kingdom.

**Report every distinct `ret=+0x…` offset** (and its tag) back to the next session.

### Identifying which offset is the gauge vs the gate

If exactly **one** current-world offset fires while the map is open, the gauge and gate
*share* the call site and this approach cannot split them (fall to "If it can't be split"
below). If there are **two+**, one is the display and one is the takeoff-enable. The fastest
disambiguation is the Phase-2 A/B itself (below): put one offset in the table, rebuild
(~30 s), and check in-game whether the gauge now shows the real number **and** takeoff still
works. If takeoff broke, that offset was the gate — move it out and use the other.

---

## Phase 2 — activate the fix (one edit)

In [switch-mod/src/hooks/UnlockShineNumHook.cpp](../switch-mod/src/hooks/UnlockShineNumHook.cpp),
append the confirmed **display / gauge** offset(s) to `kDisplayCallerOffsets` (keep the `0`
sentinel):

```cpp
constexpr std::uintptr_t kDisplayCallerOffsets[] = {
    0,          // sentinel
    0x2ab1c8,   // gauge "needs N moons" read — StageSceneStateWorldMap (from the walk)
};
```

That's the whole change. The apply logic is already wired and dormant: for a read whose
caller is in the set, the hook returns the **rolled required count** (`displayCountForBit`)
instead of 0, so the gauge shows the true threshold; every other caller (the gate) still
gets 0 and takeoff stays open. Rebuild + deploy, then run the regression checklist.

The offsets are stable because we pin SMO 1.0.0 (build-id `3ca12dfaaf9c82da064d1698df79cda1`);
document each one inline the way `ShopItemMessageHook` documents its BL offsets.

### If it can't be split (single shared call site)

If the walk shows the gauge and gate are one call site, the display can't be made honest
without reworking the takeoff-enable consumer (undecompiled). Options, in order: (a) accept
the cosmetic and close this out — the globe labels + SMO Client tracker already carry the
true counts; (b) go deeper and locate the takeoff-enable comparison in
`StageSceneStateWorldMap` by disassembly (smo-symbol-discovery), leave `findUnlockShineNum`
honest everywhere, and force *that* comparison — larger effort, only if Devon wants it.

---

## Regression checklist (in-game test script for the Phase-2 build)

Run after activating the fix. Nothing here should change from pre-fix behavior except the
gauge number.

- [ ] **Gauge shows the true count.** In a chain-reached / free-detour kingdom the takeoff
      gauge now reads the rolled required moons (e.g. "needs 10"), not "full on moons".
- [ ] **Free-detour crossings still open at 0 moons.** Lake↔Wooded (post-Sand),
      Snow↔Seaside (post-Metro) — the Odyssey still takes off immediately on arrival, and
      `evaluateDetourExitGate` still gates the *combined* exit (can't leave the pair until
      both siblings' moons are in).
- [ ] **Chain-reached kingdoms still fly out unpaid.** You can still take off from a
      chain-reached kingdom with its rolled gate unpaid, and the `[chain-return] BOUNCE`
      to un-visited picks still fires (chain_allowance_bit stays coherent with
      WorldMapSelectHook's bounce — the gauge read and gate read share the same allowance).
- [ ] **Paying the gate reverts to honest.** Once deposited ≥ threshold, the gauge and gate
      both behave vanilla (no forced 0, no forced display value).
- [ ] **Cascade unchanged.** Its gauge still shows the true count (it never used the forced
      0), and the door-divert escape (`processCascadeOdysseyDivert`) is untouched.
- [ ] **Globe labels unchanged.** Per-kingdom required counts on the world-map globe still
      read the rolled values (`findUnlockShineNumByWorldId` untouched).
- [ ] **Log sanity.** `[gate-probe]` still enumerates the same offsets; `[kingdom-gates]`
      substitution lines unchanged for non-display callers.

---

## Build + deploy (from CLAUDE.md switch-mod section; Windows PowerShell)

```powershell
cd E:\smo_archipelago
python scripts\sync_capture_table.py
python scripts\sync_shine_table.py
$LAN_IP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' -and
    ($_.PrefixOrigin -eq 'Dhcp' -or $_.PrefixOrigin -eq 'Manual')
}).IPAddress
$LAN_IP   # eyeball — pick the /24 that matches your Switch/Ryujinx
python scripts\build_switchmod.py "-DBRIDGE_HOST=192.168.x.x"   # QUOTE the dotted IP

$RYU = "$env:APPDATA\Ryujinx\mods\contents\0100000000010000\"
New-Item -ItemType Directory -Force "$RYU\exefs" | Out-Null
Copy-Item -Force E:\smo_archipelago\switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\subsdk9  "$RYU\exefs\subsdk9"
Copy-Item -Force E:\smo_archipelago\switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\main.npdm "$RYU\exefs\main.npdm"
```

Switch-mod only — no `install_apworld.py`, no reseed, no `sync_shine_table` dependency for
the fix itself (the table sync in step 1 is the always-run hygiene step).
