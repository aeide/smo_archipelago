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

**Status: investigated, NOT started.**
- **Recolor: ~95% feasible, SMALL** — this is essentially the already-scoped P5; the
  whole pipeline exists and only needs extending.
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

## Part 2 — Coin-model swap (the caveat): ~55%, high effort

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
