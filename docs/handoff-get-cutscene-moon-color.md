# Handoff — get-cutscene held-up moon color (blue bug)

**Status:** fix #3 built + deployed **2026-07-05 11:59 PM**, NOT yet tested in-game.
Devon is low on spare overworld moons — get the confirmation in one collection.

Related memory: [[shine-color-per-frame-enforce]]. All code is switch-mod only
(`ShineAppearanceHook.cpp` + `ApState.hpp` + `MoonGetHook.cpp`) — **no apworld
rebuild, no reseed, no `sync_shine_table`.** The deployed `subsdk9`/`main.npdm`
are already in `%APPDATA%\Ryujinx\mods\contents\0100000000010000\exefs\`, so just
launch Ryujinx (mod enabled) and play.

---

## The bug (Devon's words)
Moons ARE recolored per granted kingdom in the overworld (correct), but during the
"You got a Power Moon!" collection cutscene the held-up moon shows a **fixed
Luncheon-blue** (frame 6) on **every** moon, regardless of granted kingdom or the
physical kingdom Mario is standing in. Controlled datapoint: a Bowser's-Kingdom
moon collected in Seaside was correctly **RED** in the overworld and turned
**BLUE** in the cutscene.

## Root cause (confirmed from the 2026-07-05 log)
The held-up cutscene moon is a **separate demo-model actor** created by
`Shine::addDemoModelActor` — it is **NOT a `Shine`**. So:
- `Shine::init` and `Shine::control` never run on it → the old "pin it when it
  inits within a window" (`s_demoModel`) approach could never catch it; it only
  false-matched real world moons at stage load.
- The **only** hook that touches the real demo model is
  `setStageShineAnimFrameOverride`. There it read garbage off the non-`Shine`
  bytes → `resolveShinePalIdx` returned a fixed pal **15** (Luncheon) → forced
  frame **6** (blue). **Our own override was painting it blue.** Vanilla was
  actually passing frame 3 (correct Bowser red).

Log fingerprint of the failure (collection at `00:01:17`):
```
[getprobe] showCurrentModel self=0x214253d718 pal=17           ← source shine, correct
MoonGetHook: reporting stage=SeaWorldUnderGlassZone id=obj400  ← real collection
[setframe-diag] actor=0x213b8e5350 pal=15 frame=3              ← held-up model, mis-resolved to 15
                                                                  (and NO [getdemo] pinned line)
```

## The fix that is deployed (fix #3)
1. **Ripped out** all `s_demoModel` machinery (the init-window pin and the
   `Shine::control` hold — both were pure collateral).
2. `setStageShineAnimFrameOverride` now forces the **source palette** that
   `Shine::showCurrentModel` latched (`ApState::beginGetDemo`) onto **any**
   setframe call **while a get-demo window is open** — but only when
   `ApState::recentMoonGet(3500ms)` is true.
3. The collection gate is the key: `showCurrentModel` also latches during ordinary
   stage loads, so without the gate, on-screen world moons would repaint. A real
   collection stamps `MoonGetHook::stampMoonGet()` microseconds before the demo
   model's single setframe call, and the game is frozen during the cutscene, so
   nothing else is colored in that window.
4. The demo model's single frame-set persists the whole cutscene — one correct
   call is all it needs (no per-frame re-assert).
5. The palette is forced explicitly to the **granted** kingdom's frame
   (pal 17 → frame 3), so it's correct even if vanilla passes the physical
   kingdom's frame.

Revert flag if it misbehaves: `kGetDemoPersistThroughCutscene = false` in
`ShineAppearanceHook.cpp` (reverts to per-actor resolve; cutscene goes back to
the blue bug, no crash).

---

## YOUR TEST (do this first)
Collect **ONE** clearly non-blue moon — a **Bowser's-Kingdom (red)** moon is
ideal, same as the last test so it's directly comparable. Watch the held-up moon
in the "You got a Power Moon!" cutscene.

**PASS:** the held-up moon is the **granted kingdom's color** (Bowser's = red),
matching the overworld moon. → Bug fixed. Ask me to strip the diagnostic logging
in a final build.

**FAIL — still blue (or wrong):** grab the Ryujinx log and hand it back. The tell
to look for right after the `MoonGetHook: reporting …` line:

- **`[getdemo] forcing source palette=17 onto held-up model 0x… (was resolve=15)`
  appears, but the moon is still wrong** → the latched palette or the
  palette→frame mapping is off. I'll check `kingdomColorFrameForPal` and the
  `showCurrentModel` palette value in the log.
- **That line does NOT appear at all** → either `showCurrentModel` didn't fire on
  this collection (so no palette was latched) or `recentMoonGet` didn't line up
  with the setframe call. I'll move the latch to a different collection chokepoint
  or widen/retime the gate.

Either way the `[setframe-diag] actor=… pal=… frame=…` line for the held-up model
plus the `showCurrentModel … pal=…` line together tell me exactly what happened —
send those.

### Optional second check (only if the first passes and you have a spare moon)
Collect a moon in a kingdom that grants a **different** kingdom (e.g. a Seaside
moon granting Cap, or any frame-override kingdom: Sand/Lake/Wooded/Metro/Snow/
Seaside/Luncheon/Bowser's/Moon). Confirms it forces the *granted* color, not the
physical-kingdom color. Skip if moons are scarce — the Bowser's test is the
decisive one.

---

## After confirmation
Strip the still-in-build diagnostics from `ShineAppearanceHook.cpp` (they were
left in only to read this one result):
- `[setframe-diag]` block (the `if (frame >= 0)` logger).
- `[getdemo] forcing source palette …` logger (keep or drop — cheap, capped at 8).
- The dead probe trampolines that never fire because they're inlined:
  `shineAddDemoModelActor`, `shineAddDemoActorWithModel`, `shineGetProbe`,
  `shineGetDirectWithDemoProbe`, and their symbol lookups/installs. The
  **`shineShowCurrentModelProbe` MUST STAY** — its `beginGetDemo` latch is the
  load-bearing part of the fix (rename it off "probe" when you strip the others).
- The now-unused `kShineGet` / `kShineGetDirectWithDemo` / `kShineAddDemo*`
  symbols in `HookSymbols.hpp` (keep `kShineShowCurrentModel`).
Then rebuild + redeploy (switch-mod only) and update [[shine-color-per-frame-enforce]].

## Build/deploy loop (Windows PowerShell — canonical)
No table regen needed (no `items.json`/`locations.json` change).
```powershell
cd E:\smo_archipelago
python scripts\build_switchmod.py "-DBRIDGE_HOST=192.168.4.100"   # ~30s; QUOTE the -D arg
$RYU = "$env:APPDATA\Ryujinx\mods\contents\0100000000010000\"
New-Item -ItemType Directory -Force "$RYU\exefs" | Out-Null
Copy-Item -Force E:\smo_archipelago\switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\subsdk9  "$RYU\exefs\subsdk9"
Copy-Item -Force E:\smo_archipelago\switch-mod\build\sd\atmosphere\contents\0100000000010000\exefs\main.npdm "$RYU\exefs\main.npdm"
```
(`192.168.4.100` is this PC's LAN IP as baked last build — re-derive if the
network changed; see CLAUDE.md switch-mod section.)

## Not-a-bug note
Devon saw the game audio cut out during the collection and return after the
animation. That's a Ryujinx emulator hitch, not our hook — the same log shows
`ServiceNv Wait: GPU processing thread is too slow` and `ComputeVoiceDrop:
Dropping voice` around the cutscene. Ignore it.
