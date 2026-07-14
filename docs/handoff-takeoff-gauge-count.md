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

## Phase 1 — the measurement walk

### Walk #1 result (2026-07-13, Sand via chain) — narrowed it to the MEMBER seam

The first probe build captured two current-world callers during the Sand chain arrival:

```
[gate-probe] ... ret=+0x52a0f4 (BL@+0x52a0f0) via member[FORCED-0]      kingdom=Sand origVanilla=16
[gate-probe] ... ret=+0x1ff308 (BL@+0x1ff304) via chain-return[FORCED-0] kingdom=Sand origVanilla=0
```

Two facts fall out:

- The **free current-world** read (`+0x1ff308`) is *structurally 0* in this state
  (`origVanilla=0`), so it cannot be what the gauge shows — vanilla would render "16", not
  0. **The takeoff GATE reads this free seam**, which is already 0 here, so takeoff is open
  independent of the member seam.
- The **member** read (`+0x52a0f4`) carries Sand's real requirement (`origVanilla=16`) and
  our P5 `holderFindUnlockShineNumHook` (`[chain-launch]`) forces it to 0. **So the gauge
  reads the member seam, and that P5 hook is what blanks it to "full."**

**Caveat:** `+0x52a0f4` fired *once, at scene-load*, immediately before the `[chain-launch]`
line — the signature of a story/sequence check at load (the P5 finding-11 target), **not** a
per-frame gauge render. The gauge's own read didn't fire because the takeoff / world-map UI
was never opened during that walk (screenshot was the overworld). So `+0x52a0f4` is probably
the story-launch caller, **not** the gauge — do **not** blindly add it to the display table
(it would risk re-closing the P5 story launch and likely wouldn't fix the gauge). We still
need the gauge's own caller.

### Walk #2 result (2026-07-14, Metro via chain, takeoff UI held open) — GAUGE IDENTIFIED

With the takeoff screen held on-screen ~30s, three callers fired **per-frame** (windowed to
once/sec by the probe), plus a couple of transient one-shots:

```
[gate-probe] ... ret=+0x30b96c  via chain-return[FORCED-0]  kingdom=Metro origVanilla=0   (from start, per-frame)
[gate-probe] ... ret=+0x533c10  via member[FORCED-0]        kingdom=Metro origVanilla=20  (from start, per-frame)
[gate-probe] ... ret=+0x2c83d88 via member[FORCED-0]        kingdom=Metro origVanilla=20  (ONLY after Odyssey-board reload, per-frame)
```

The model that fits every data point:

- **`+0x30b96c` (free wrapper caller) = the takeoff GATE.** `origVanilla=0` — it's already 0,
  so it's the gate we force open; stays forced to 0.
- **`+0x533c10` (member) feeds the gate.** It fires whenever `+0x30b96c` polls (one-for-one),
  i.e. it is the free wrapper's internal member read; zeroing it is what makes the free wrapper
  return 0. Stays forced to 0.
- **`+0x2c83d88` (member) = the GAUGE.** It is the *only* caller that appears **exclusively
  after the Odyssey-board reload** — read only while the takeoff screen renders — and it carries
  the current world's real threshold (`origVanilla=20`). This is the display read.

The gauge reads the **member seam** (only the member reads carry the real 20; the free seam
reads 0), which is the safe lever: the gate reads the free wrapper separately, so making the
member gauge-caller honest cannot re-close takeoff. `+0x52a0f4` (the Walk #1 Sand one-shot
story-launch check) did **not** appear here — confirming it is a discrete launch check, not a
per-frame display read, and it must stay at 0.

**Phase 2 is APPLIED** (`kDisplayCallerOffsets[] = { 0, 0x2c83d88 }`) — `+0x533c10`,
`+0x30b96c`, and `+0x52a0f4` are deliberately excluded (documented inline in the hook). Build,
deploy, and run the regression checklist below.

### Walk #3 result (2026-07-14, Sand via chain, `+0x2c83d88` applied) — STILL "Full on 🌙"

With `kDisplayCallerOffsets = { 0, 0x2c83d88 }` deployed and the overworld steering-globe
bubble showing **"Full on 🌙!"** (Sand, 4/20 collected, 0 deposited), the bubble did NOT flip
to "needs 20", and the top-left moon-count HUD still showed no empty circles. Takeoff still
fired correctly (only to already-visited kingdoms). `+0x2c83d88` again fired per-frame as
`member[FORCED-0] origVanilla=16` — but the `[gate-probe]` tag is printed **before** the apply
logic, so it looks identical whether or not the override ran. **The log therefore cannot tell
us whether the override fired at all** (build not redeployed?) or fired-and-was-ignored.

Two live hypotheses remain, needing different fixes:

- **Model A — the bubble/HUD read the *free wrapper* (`+0x30b96c`) = the GATE.** Then
  "Full on Power Moons!" is the game's **readiness** state: the same `getPayShineNum(cur) >=
  findUnlockShineNum(cur)` boolean we force true (by zeroing the free wrapper) to open takeoff.
  It can *never* say "needs 20" while takeoff works — "needs 20" IS the not-ready state that
  blocks flight. This is a **semantic contradiction, not a caller-split** — no member-level
  change can fix it. Supporting evidence: only **one** persistent free caller (`+0x30b96c`)
  ever appears, so the gate poll and any readiness display are the same call site; and it polls
  per-frame (globe object checking "am I full?").
- **Model B — the bubble reads the *member* seam for its required count separately.** Then the
  fix is achievable and either (a) the build wasn't redeployed, or (b) the bubble reads a
  *different* member caller than `+0x2c83d88` (e.g. `+0x533c10`).

### Walk #4 result (2026-07-14, Sand→Wooded, `[gauge-fix]` build) — HUD reader IDENTIFIED, retargeted

Decisive. Devon had meanwhile **cleared Cascade**, so Sand is now a legitimately-progressed
kingdom while Wooded is still reached as a free-detour. The contrast splits it cleanly:

- **Sand (legit):** every read logs `member[honest]` / `honest-rolled`; the free-wrapper caller
  **`+0x202dcc`** returns the rolled `20`; the **top-left HUD renders correctly**. Crucially, of
  the free callers **only `+0x202dcc` executes — `+0x30b96c` does not fire at all here.**
- **Wooded (free-detour, forced):** `+0x202dcc` is forced to 0 → **HUD blanks to "Full"**. The
  `[gauge-fix]` line confirms my member override fired (`+0x2c83d88 … shown=18`) yet the HUD
  stayed blank — proving the **HUD does not read the member seam**.

Conclusion (Model B after all, but at the FREE wrapper, not the member):

- **`+0x202dcc` = the top-left moon-count HUD.** It renders in every kingdom (fires in legit
  Sand where the HUD is correct) and returns the rolled required count. This is Devon's target —
  he explicitly wants the **HUD** correct in every kingdom and does not care about the globe bubble.
- **`+0x30b96c` = the takeoff GATE / readiness check.** It does *not* execute in a
  legit-unlocked kingdom (Sand) — only when the world isn't legitimately unlocked (Wooded/chain).
  That's the unlock-check signature, distinct from a per-frame HUD render. Keep it forced to 0.

**Retargeted:** `kDisplayCallerOffsets = { 0, 0x202dcc }` (dropped the member `0x2c83d88`).
Now `+0x202dcc` returns the rolled count (HUD honest) while `+0x30b96c`/`+0x1ff308` stay forced
to 0 (gate open). This is the minimal single-variable change; the `[gauge-fix]` log will confirm
it fires for `+0x202dcc`.

**Test in a free-detour / chain kingdom (e.g. Wooded):**
- **HUD shows the real count AND takeoff still opens** → SPLIT SUCCESS, done. (`+0x202dcc` was
  HUD-only.)
- **HUD correct but takeoff now refuses** → `+0x202dcc` also feeds the gate; they're coupled.
  Revert to `{ 0 }` and fall back to the honest-gate rework below.

### ✅ RESOLVED (2026-07-14) — `+0x202dcc` was HUD-only, split confirmed in-game

Devon walked a free-detour kingdom with `kDisplayCallerOffsets = { 0, 0x202dcc }`: the top-left
moon-count HUD now shows the real required count in every kingdom **and takeoff still fires** —
the clean split. `+0x202dcc` is HUD-only; the gate rides `+0x30b96c` (kept forced 0). The globe
bubble still reads "Full on 🌙" (it's the gate readiness — accepted, Devon doesn't care about it).
No further work; the honest-gate rework below is NOT needed.

### (Superseded) decisive diagnostic build — `[gauge-fix]` confirmation log

Added a distinct `[gauge-fix] DISPLAY override FIRED … orig=N -> shown=M` line that logs **only
when the Phase-2 override actually runs** (rate-limited once/sec per caller), at all three
override sites. `+0x2c83d88` stays in the table. Rebuild, deploy, walk into a chain kingdom's
takeoff globe, and grep `[gauge-fix]`:

1. **No `[gauge-fix]` line at all** → the Phase-2 build was never deployed (Walk #3 ran the old
   binary). Re-deploy and repeat — the fix may simply not have been on the Switch.
2. **`[gauge-fix] … shown=20` appears AND the bubble now reads "needs 20"** → Model B, FIXED.
   Done (run the regression checklist).
3. **`[gauge-fix] … shown=20` appears BUT the bubble still reads "Full"** → **Model A confirmed.**
   `+0x2c83d88` is a real member consumer but NOT what drives the overworld bubble/HUD; those
   read the free-wrapper gate. This is the semantic-contradiction case — see below. (Optional
   one-shot to rule out "wrong member caller": also add `+0x533c10`; it is gate-safe because the
   free-wrapper hook re-forces 0 for the gate caller and the one-shot story-launch `+0x52a0f4`
   stays excluded. If neither member offset flips the bubble, Model A is certain.)
- **Neither member offset fixes it** → the gauge reads the free wrapper (`+0x30b96c`), which is
  the same call site as the gate → "can't be split" case below.

---

## Phase 2 — activate the fix (one edit)

In [switch-mod/src/hooks/UnlockShineNumHook.cpp](../switch-mod/src/hooks/UnlockShineNumHook.cpp),
append the confirmed **display / gauge** offset(s) to `kDisplayCallerOffsets` (keep the `0`
sentinel):

```cpp
constexpr std::uintptr_t kDisplayCallerOffsets[] = {
    0,         // sentinel
    0x202dcc,  // Walk #4: top-left moon-count HUD read (free wrapper) — APPLIED
};
```

That's the whole change. The apply logic is already wired: for a read whose caller is in the
set, the hook returns the **rolled required count** (`displayCountForBit`) instead of 0, and
now also emits a `[gauge-fix]` line so we can confirm it fired. Every other caller (the gate)
still gets 0 and takeoff stays open. **Status after Walk #3: this did NOT flip the overworld
bubble** — see Walk #3 and the Model A / Model B split above; the next build's `[gauge-fix]`
line decides between "not deployed", "Model B fixed", and "Model A contradiction".

The offsets are stable because we pin SMO 1.0.0 (build-id `3ca12dfaaf9c82da064d1698df79cda1`);
document each one inline the way `ShopItemMessageHook` documents its BL offsets.

### If Model A is confirmed (readiness contradiction, not a caller-split)

If the `[gauge-fix]` diagnostic shows the override fires yet the bubble stays "Full", the
overworld steering-globe bubble and the takeoff meter are the game's **readiness** state, read
from the same forced-0 `findUnlockShineNum` the gate uses. "Full on Power Moons!" *means* "you
can fly now" — which is exactly the state we manufactured. To make it read "needs 20" it would
have to be the not-ready state, which blocks flight. So for any kingdom that leaves via the
globe→map→fly flow, the honest bubble and working takeoff are **mutually exclusive under the
game's own UI model** — this is why it's a documented cosmetic trade-off, and why the member
seam can't fix it.

**Why Cascade is the exception (and the only real path to a fix).** Cascade already shows its
true rolled count because we do NOT force `findUnlockShineNum` there — the gate stays honest and
the escape is a *door divert* (`processCascadeOdysseyDivert`: walking into the Odyssey door warps
straight to Cap, bypassing the globe entirely). The globe still honestly says "needs 8" and you
genuinely can't use it. A clean fix for the other kingdoms would have to follow that model:
**keep `findUnlockShineNum` honest (bubble shows the real count) and open the flight through a
separate lever** — i.e. locate and force the world-map flight *launch/selection* predicate in
the undecompiled `StageSceneStateWorldMap` confirm path, leaving the fuel readiness untouched.
That is a real disassembly/probe spike (smo-symbol-discovery), not a one-line edit, and it only
matters if Devon wants the polish. Otherwise: (a) accept the cosmetic — the per-kingdom globe
*labels* (pause-map) and the SMO Client tracker already carry the true counts.

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
