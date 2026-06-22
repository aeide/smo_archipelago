# Randomize all background music (Devon, 2026-06-22)

**Goal.** Shuffle the game's background music so each track plays in place of a
different one (kingdom themes, sub-area themes, boss themes, etc.) for a fresh-audio
run. Sound effects and voice stay untouched — BGM only.

**Status: investigated, NOT started. Estimate ~70% feasible, Medium effort.**
The *hook* is genuinely minor — a one-function "lie to the game" name swap, the exact
shape of the entrance-shuffle rewrite. What pushes it to Medium (and off "trivial")
is the supporting work: enumerating the BGM name set, SMO's *interactive/layered*
music system degrading on a swap, and a handful of **music-synced moons** that a blind
shuffle would break.

---

## How BGM works in SMO (decomp-confirmed this session)

BGM is **string-keyed**, not enum/id-keyed. The decomp's `CollectBgm` shows literal
names like `"StmRsBgmHat"`, `"StmRsBgmForest"`, `"StmRsBgmBossBreeda"` (the `Stm`
prefix = *streamed* audio). Everything funnels through a small `al::` free-function
API ([lib/al/Library/Bgm/BgmLineFunction.h](https://github.com/MonsterDruide1/OdysseyDecomp/blob/master/lib/al/Library/Bgm/BgmLineFunction.h)):

```cpp
al::startBgm(const IUseAudioKeeper*, const char* name, s32, s32);          // base track
al::startBgmWithSuffix(const IUseAudioKeeper*, const char* name, const char* suffix, s32, s32);
al::stopBgm / pauseBgm / resumeBgm / isPlayingBgm / isRunningBgm (...)      // queries/control
al::startBgmSituation(const IUseAudioKeeper*, const char* situation, bool[, bool]);  // LAYERS
al::forceStartBgmSituation / endBgmSituation (...)
```

Two layers matter here:

- **Base track** — started by `al::startBgm(user, name, …)`. This is the single clean
  chokepoint: one string argument identifies the whole track.
- **Interactive "situations"** — `al::startBgmSituation(user, "<situation>", …)` fades
  per-context layers in/out of the *currently playing* track (capture, underwater,
  combat, the New Donk band, etc.). Situations are resolved relative to the active
  BGM line, so they're keyed to whatever track is playing, not to a global id.

---

## What the change requires

### The chokepoint — trivial (this is the "minor" part)

Trampoline `al::startBgm` (and `startBgmWithSuffix`), look the incoming `name` up in a
**per-seed permutation table**, and overwrite it with the mapped name before calling
orig — byte-for-byte the same "rewrite a string arg in place, then orig" move the
entrance shuffle already does in
[EntranceShuffleHook.cpp](../../switch-mod/src/hooks/EntranceShuffleHook.cpp). One new
hook file, one symbol. Illustrative symbol (verify via `smo-symbol-discovery`):
`_ZN2al8startBgmEPKNS_15IUseAudioKeeperEPKcii`.

### The permutation table — needs the name set (the real work)

To map name → shuffled-name you need the **full set of valid BGM names**, and they
must map only to names that exist in the loaded `BgmDataBase` (an invalid name makes
`alBgmFunction::tryFindBgmUserInfo` return null — likely a silent no-op, but unverified;
mapping only to known-valid names sidesteps it). That set lives in the sound archive /
`SoundItem` tables (`SoundItemHolder` / `SoundItemEntry` exist in the decomp), so it's
a **romfs extraction** — IP-sensitive, and therefore gitignored exactly like
`shine_map.json`. This is a **known model in this project**: generate the shuffle table
the same way `shine_table.h` / `capture_table.h` are produced — an extractor writes a
gitignored `bgm_map.json`, a `sync_bgm_table.py` emits a compiled `bgm_table.h`
(name → shuffled-name) the mod links, with an empty stub when the map is absent so the
bundled mod still builds. The permutation is seeded for determinism.

### Seed + toggle — minor

A `randomize_music` YAML `Toggle` plus a seed value can ride the existing slot_data →
wire-msg → `ApState` path the other toggles use; or the mod can derive the permutation
seed from the AP seed it already receives. **No logic involvement and no re-seed of the
item fill** — music is cosmetic, so this can even be a switch-mod-only feature keyed on
a fixed RNG. (Generating `bgm_table.h` does require a rebuild, but not a re-generate of
the world.)

---

## Risks / gotchas (why it's 70%, not 90%)

1. **Music-synced gameplay — the sharpest content risk.** A few moons/sequences are
   timed to their specific track: the New Donk City festival ("Jump Up, Super Star!"
   build-up), the jump-rope and beach-volleyball challenges, the Luncheon/Sand musical
   set pieces, Toad/▷ band sections. A blind shuffle desyncs the cues and can make
   those challenges confusing or near-unplayable. The feature should **exclude a
   curated blocklist** of synced tracks (Devon supplies the list, like the
   scenario-advancer moon audit), or accept the breakage as a known quirk.
2. **Situation/layer degradation.** Swapping only the base `startBgm` name means the
   later `startBgmSituation("Capture"/"Water"/…)` calls resolve against the *new*
   track, which may not define those situations → those dynamic layers simply don't
   activate. Result: you hear track B's base loop without track A's interactive
   layering. Graceful and acceptable for "randomized music," but it means the swapped
   audio is slightly less rich than vanilla. (Could also remap situation names, but
   leaving them to no-op is the safe default.)
3. **Stream residency — needs an in-game check.** `Stm*` tracks are *streamed*, which
   usually means any track can start at any time (the stream is opened from the
   filesystem on request) — encouraging — but SMO may scope which streams are mounted
   per-scene. If a mapped track's stream isn't resident in the current area it could
   play silent. Mitigation if it bites: restrict the permutation to a mutually-resident
   pool (e.g. permute within a category), or confirm the global stream pool covers all.
   A one-build spike answers this binary question.
4. **Cutscene / demo-synced music may bypass `al::startBgm`.** The decomp has a
   separate `DemoSyncedBgmCtrl` / `DemoSoundSynchronizer` path for cutscene-locked
   music. Those may not flow through `al::startBgm`, so some demo tracks could stay
   vanilla (probably desirable — leaving cutscene music intact avoids audio/visual
   desync). Confirm coverage; add `startBgmWithSuffix` and, if needed, the demo path.

---

## Recommendation / first step (when pursued)

1. **One-build hook+log spike:** trampoline `al::startBgm`, log every `name` requested
   across a play session (overworld, capture, water, boss, cutscenes), and — as a
   smoke test — hard-swap two known overworld tracks and confirm in-game that (a) the
   swap plays, (b) it isn't silent in a foreign kingdom (residency), and (c) nothing
   crashes. That log also **bootstraps the name set** for the extractor and reveals
   which tracks bypass `startBgm` (demo path).
2. If clean: build the `bgm_map.json` extractor + `sync_bgm_table.py` → `bgm_table.h`
   (mirror the shine_table pipeline), add the seeded permutation + `randomize_music`
   toggle, and apply the synced-track blocklist.

**Why ~70%:** the interception point is a known-good, already-proven pattern (string
arg rewrite + orig), BGM is cleanly string-keyed through one funnel, and the
table-generation infrastructure already exists in the project (shine_table model). The
points off are all supporting-work unknowns rather than a wall: enumerating the valid
name set (romfs extraction, IP-sensitive but standard here), confirming stream
residency for cross-area swaps, the graceful-but-real loss of interactive layering, the
demo-path coverage gap, and — the one that needs human judgment — curating the
music-synced moons out of the shuffle so a "minor" cosmetic feature doesn't quietly
break a handful of checks.

---

Sources consulted (decomp + disk-truth this session):
[lib/al/Library/Bgm/BgmLineFunction.h](https://github.com/MonsterDruide1/OdysseyDecomp/blob/master/lib/al/Library/Bgm/BgmLineFunction.h)
(the `al::startBgm` / `startBgmSituation` API),
`src/System/CollectBgm.cpp` (BGM identified by `const char*` names like `StmRsBgm*`),
`src/MapObj/FixMapPartsBgmChangeAction.cpp` (`al::isRunningBgm` query pattern),
local stubs [BgmFunction.h](../../switch-mod/lib/OdysseyHeaders/al/Library/Bgm/BgmFunction.h)
/ [BgmKeeper.h](../../switch-mod/lib/OdysseyHeaders/al/Library/Bgm/BgmKeeper.h);
decomp tree (`src/Audio/DemoSoundSynchronizer`, `lib/al/Project/File/SoundItemHolder`
for the name tables). Cross-ref: shine_table/capture_table generation model
(CLAUDE.md), entrance-shuffle string-rewrite pattern.
