# "Spin" ability gate — the high spin jump (Devon, 2026-06-22)

**Goal.** Rotating the control stick quickly makes Mario do a ground spin; jumping
out of that spin gives a **much higher jump** (the "spin jump"), and you can also
**ground pound** out of it. Both work today even with zero AP abilities owned. Devon
wants:

1. A new **"Spin"** ability item that gates the **high spin jump** itself (no Spin →
   no height advantage from spinning).
2. The **ground pound out of a spin** gated behind owning **Ground Pound** (as it
   should be).

**Status: investigated, NOT started. Estimate ~85% feasible, Low–Medium effort.**
This is a textbook fit for the existing P4 ability-gate machinery — there's a clean
judge seam *and* a proven neuter fallback for part 1, and **part 2 already works**.

---

## How it works today (decomp-confirmed this session)

The spin is a real, named SMO move chain with dedicated state, judge, and physics
constants — none of it is hand-rolled:

- **Ground spin entry**: `PlayerJudgeStartGroundSpin::judge()` returns
  `mInput->isSpinInput() && rs::isOnGround(mPlayer, mCollider)` — a normal `IJudge`
  override, *structurally identical* to the Crouch / Roll / HipDrop judges this
  project already gates cleanly. (`isSpinInput()` is the stick-rotation gesture; it
  is **not** the cap-throw gesture, so this is fully separate from the already-shipped
  Spin Throw gate.)
- **Ground spin state**: `PlayerStateGroundSpin` — auto-terminates after
  `PlayerConst::getGroundSpinFrame()`. Per the decomp it has **no jump branch of its
  own**; the spin jump is launched elsewhere (the undecompiled
  `PlayerActorHakoniwa` body / jump state) reading dedicated constants.
- **Spin-jump physics**: `PlayerConst` exposes a dedicated getter family
  ([PlayerConst.h:376-381](../../switch-mod/lib/OdysseyHeaders/game/Player/PlayerConst.h#L376)):
  `getSpinJumpPower()`, `getSpinJumpGravity()`, `getSpinJumpMoveSpeedMax()`,
  `getSpinJumpDownFallInitSpeed()`, `getSpinJumpDownFallPower()`,
  `getSpinJumpDownFallSpeedMax()`. These are `PlayerConst` **virtuals** — exactly the
  shape of the turn-jump getters (`getTurnJump{Power,VelH,Gravity}`) that the shipped
  **Side Flip** gate already neuters.
- **Ground pound out of the spin**: `PlayerJudgeStartHipDrop::judge()` is
  `!mModelChanger->is2DModel() && mInput->isTriggerHipDrop() &&
  rs::getGroundHeight(...) >= mConst->getHipDropHeight()` — **generic**, with **no
  spin-specific branch**. So a hip drop launched from a spin jump goes through the
  *same* judge as every other hip drop.

---

## What the change requires

### Tier 1 — apworld: add one "Spin" item (low effort, known pattern)

Add a single entry to the `Ability` category in
[data/items.json](../../apworld/smo_archipelago/data/items.json), a verbatim mirror
of how Side Flip / Cap Bounce / etc. were added in P3:

```json
{ "name": "Spin", "category": ["Ability"], "count": 1, "progression": true }
```

The bridge already ships every `Ability`-category name to the Switch verbatim in the
`ability_state` snapshot (→ `ApState::ability_table`), so `abilityAtLeast("Spin", 1)`
becomes available on the mod side automatically — no new wire field. Adding a pool
item requires a regenerate/re-seed (this part is **not** switch-mod-only, unlike the
entrance-shuffle apply), and the usual item/location pool-balance bump that every new
ability item needed.

**Spin also joins the jump-height ladder in the logic (Devon, 2026-06-22).** The spin
jump's apex is **490 units** — effectively the same as the existing **496-unit "vault"
tier** (Backflip / Side Flip / Cap Bounce). So Spin is not just a movement-flavor item
that gates only its own move; it's a genuine **height satisfier** and must be folded
into the same logical flow those three already use in
[scripts/compile_moon_logic.py](../../scripts/compile_moon_logic.py). Concretely, the
mechanical edit is:

- Add a fragment: `"SPIN_JUMP": "|Spin|"` to `JUMP_FRAG` (no movement prerequisite —
  the spin jump needs no Crouch, exactly like `SIDE_FLIP`).
- Add `"SPIN_JUMP"` to the satisfier lists for every tier the 496 jumps satisfy —
  i.e. the `double`, `cap_return`, and `backflip` entries of `HEIGHT_SATISFIERS`
  (the ≤496 band), **but not** `gpj` (514) or `triple` (550), since 490 < both.
- Add `JUMP_FRAG["SPIN_JUMP"]` to the `_HIGH_JUMP` overworld-gate fragment for the
  same reason Backflip/Side Flip are in it.

Effect: any moon whose `requires` currently reads "reach the 496 tier" (an OR over
Backflip/Side Flip/Cap Bounce/GPJ/Triple) gains `|Spin|` as one more way to satisfy it.
This only ever **loosens** logic — it adds OR-terms, so it cannot strand an existing
moon — and it makes Spin a real progression item the fill can use to open height-gated
checks (consistent with the `progression: true` flag above), exactly mirroring Side
Flip. It does **not** edit `moon_requirements.json` by hand: the height band is encoded
per-moon already; the new satisfier flows in centrally through the compiler's tier
tables. Two process consequences: (a) this needs a **`compile_moon_logic.py` re-run**
(romfs/`shine_map.json` present — never run it without, per CLAUDE.md, or it wipes the
scenario gates) followed by `install_apworld.py` + regenerate; (b) it is therefore not
switch-mod-only on the apworld side.

### Tier 2a — switch-mod: the "Spin" gate (the high spin jump)

Two clean options; both satisfy "no high spin jump without the item."

**Approach A — suppress ground-spin entry (RECOMMENDED, cleanest).** Trampoline
`PlayerJudgeStartGroundSpin::judge()` and force `false` when `Spin` is unowned —
*identical* to the shipped `squatJudgeHook` / `hipDropJudgeHook` pattern (orig-first;
only suppress when it would have fired). No ground spin → no spin jump. The judge is a
real out-of-line `IJudge` override (same family as the judges that already gate
correctly), so it should hook without the inlining trouble that dogged Side Flip.
Side effect: the spin *animation* also goes away when Spin is unowned — arguably
desirable ("no spin move at all without the item"), and it does **not** touch Spin
Throw (different input) or the spin-cap mechanics.

Illustrative symbol (verify via the `smo-symbol-discovery` pipeline):
`_ZNK26PlayerJudgeStartGroundSpin5judgeEv`.

**Approach B — neuter the spin-jump physics (proven fallback).** If A leaks (e.g. the
jump boost is armed by a *post-spin window* set in the undecompiled jump code rather
than requiring you stay in the spin state, so the jump still boosts after a 1-frame
spin), fall back to the **exact Side Flip mechanism**: hook
`PlayerConst::getSpinJumpPower` / `getSpinJumpGravity` / `getSpinJumpMoveSpeedMax`
and return normal-jump values (`getJumpPowerMax()` scaled / `getJumpGravity()`) when
Spin is unowned, so the spin jump provides no height/distance advantage while the spin
animation stays. This is already shipped and validated for the sibling turn-jump
getters, so confidence is high; it may need a small power-scale constant like
`kSideFlipPowerScale` if a bare ballistic launch undershoots a normal full jump.

Illustrative symbols: `_ZNK11PlayerConst16getSpinJumpPowerEv`,
`_ZNK11PlayerConst18getSpinJumpGravityEv`,
`_ZNK11PlayerConst23getSpinJumpMoveSpeedMaxEv`.

A reasonable plan is to ship A and keep B in reserve (or layer B under A as
belt-and-braces, the way Side Flip neuters rather than suppresses).

### Tier 2b — ground pound out of spin: ALREADY GATED (just verify)

Because the hip drop launched from a spin jump routes through the generic
`PlayerJudgeStartHipDrop::judge()`, and that judge is **already** trampolined and
gated on `Progressive Ground Pound >= 1` (the shipped `hipDropJudgeHook` in
[AbilityGateHook.cpp](../../switch-mod/src/hooks/AbilityGateHook.cpp)), the
ground-pound-out-of-spin is **already behind owning Ground Pound**. No new hook
needed — just confirm in-game (spin-jump without Ground Pound owned → the down-attack
should be blocked).

**One edge to check:** the spin-jump-specific `getSpinJumpDownFall*` getters. Confirm
the down-attack out of a spin jump is the *standard* hip drop (gated above) and not a
separate "spin plunge" that bypasses `PlayerJudgeStartHipDrop`. If it turns out
separate, neuter those three getters the same way as Tier 2a-B (return the normal
hip-drop fall values when Ground Pound is unowned) — a small, mechanical add.

---

## Recommendation / first step (when pursued)

1. **Symbol-discovery + logger spike (no behavior change):** resolve
   `PlayerJudgeStartGroundSpin::judge` and the `getSpinJump*` getters via sail; log
   each while doing a spin jump in-game. Confirm (a) the judge fires on spin entry,
   (b) the getters are called when the spin jump launches, and (c) a Ground-Pound-less
   spin-jump down-attack is already blocked by the existing hip-drop gate. That walk
   decides A-vs-B and closes the `getSpinJumpDownFall*` question.
2. Add the `Spin` item + the height-ladder edit (Tier 1) + the Approach A judge hook;
   re-run `compile_moon_logic.py`, rebuild the subsdk, and regenerate a seed. Verify:
   no Spin → spinning gives a normal-height jump (or no spin at all under A) and no
   spin-plunge without Ground Pound; with Spin → full spin jump returns; and a moon
   gated at the 496 tier is now satisfiable by Spin in the logic.

**Why ~85%:** every piece maps onto already-working machinery — part 2 (GP-out) is
literally already done via the generic hip-drop judge; part 1 has a clean judge seam
(Approach A, same shape as the judges that work) *and* a fully-proven neuter fallback
(Approach B = the shipped Side Flip mechanism); the apworld side is a one-line copy of
an existing ability item; and the logic integration is a known, mechanical add to the
`compile_moon_logic.py` height ladder — Spin slots into the 496 "vault" tier next to
Backflip/Side Flip/Cap Bounce (490 ≈ 496) and only ever loosens logic, so it can't
strand a moon. The points off are the usual unknowns that only an
in-game walk resolves: confirming the spin-jump launch reads these out-of-line getters
(vs. an inlined constant — though dedicated `PlayerConst` virtuals strongly imply
out-of-line, and the sibling turn-jump getters were confirmed in-path), confirming
ground-spin suppression fully kills the jump (vs. a post-spin window), the
`getSpinJumpDownFall*` edge case, and possible neuter-scale tuning.

---

Sources consulted (disk-truth reads + decomp this session):
[AbilityGateHook.cpp](../../switch-mod/src/hooks/AbilityGateHook.cpp),
[PlayerConst.h](../../switch-mod/lib/OdysseyHeaders/game/Player/PlayerConst.h)
(getSpinJump*/getGroundSpin* getter family),
[data/items.json](../../apworld/smo_archipelago/data/items.json) (Ability category),
[scripts/compile_moon_logic.py](../../scripts/compile_moon_logic.py)
(`JUMP_FRAG` / `HEIGHT_SATISFIERS` / `_HIGH_JUMP` — the 496 "vault" tier =
Backflip/Side Flip/Cap Bounce that Spin joins),
[data/moon_requirements.json](../../apworld/smo_archipelago/data/moon_requirements.json);
OdysseyDecomp `PlayerStateGroundSpin.cpp`, `PlayerJudgeStartGroundSpin.cpp`
(`isSpinInput() && isOnGround`), `PlayerJudgeStartHipDrop.cpp`
(generic `isTriggerHipDrop`, no spin branch) — no `PlayerStateSpinJump`/
`PlayerJudgeStartSpinJump` exists in the decomp (spin jump lives in the undecompiled
actor body, reached via the `getSpinJump*` PlayerConst virtuals). Cross-refs:
plan-p4-detail.md (Side Flip neuter precedent), CLAUDE.md P4 status.
