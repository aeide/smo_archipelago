# Handoff — Cascade / Madame Broode multi-moon respawn

**Status: IN PROGRESS (investigation).** Running doc per Devon's request — likely to span
multiple sessions / usage windows. Keep this updated every session.

## The bug (Devon, 2026-06-25)

If Mario advances OUT of Cascade Kingdom **before** fighting Madame Broode, she is never
available to fight again, and her **Multi Moon ("Multi Moon Atop the Falls")** disappears
forever — the AP check becomes permanently uncollectable, which can brick a seed if that
moon is progression / needed for the goal.

**When it can happen:** only when the Odyssey leave-gate for Cascade requires **≤2 moons**
AND both of those moons are reachable *pre-Broode*. Then the player can satisfy the gate and
fly out without ever triggering the boss. Rare (needs `randomize_kingdom_gates` to roll
Cascade very low, or a naturally tiny gate) but possible.

Root mechanism (hypothesis, to confirm against decomp): Madame Broode + her Multi-Moon are
placed actors gated on Cascade **scenario 1** (the kingdom's main-story scenario). SMO's
`getScenarioNo(world)` is *recomputed from global quest state at every load* (documented in
`MoonRockHook.cpp` header). Once the player progresses the global story, Cascade's computed
scenario advances past 1, so the boss placement condition never matches again → no boss, no
moon.

## Desired fix (Devon's words)

> "spawn madame broode's triple moon in her normal location if it hasn't been collected yet
> once returning to cascade kingdom"

So: on (re)entering Cascade, if the Multi-Moon is **uncollected**, make it obtainable again
in its normal spot. Re-fighting Broode is acceptable (that's the vanilla way to get it).

## Key facts established

- AP location name: **`Cascade: Multi Moon Atop the Falls`**
  (moon_requirements key `Cascade Kingdom: Multi Moon Atop the Falls`).
- Cascade home stage internal name: `WaterfallWorldHomeStage` (Cascade = "WaterfallWorld").
- This is a **multi_moon** (boss) location — part of the `multi_moon_shuffle` set.
- It is almost certainly **progression** (gated-kingdom / story moon) — losing it is seed-fatal.

## Existing switch-mod machinery we can reuse

- **`MoonRockHook.cpp`** — the model for scenario-aware, per-kingdom, peace-gated hooks.
  Has `resolveGameCtx()` (GameDataHolder → GameDataFile + world_id), and resolved fn ptrs:
  `getScenarioNo`, `getMainScenarioNo`, `isClearWorldMainScenario`, `getMoonRockScenarioNo`,
  plus `setMainScenarioNo` via `kGameDataFileSetMainScenarioNo`. ⚠ Its header documents that
  forcing a scenario MID-story is destructive (skips bosses/quests) — but here we *want* the
  boss scenario, so that caveat may not apply. CONFIRM.
- **Shine collected check:** need to read whether the Multi-Moon's shine flag is set. Options:
  (a) `ApState::locations_checked` (session hash set — NOT persistent across reload), or
  (b) the game's own shine table via `GameDataFunction::isGotShine` / shine_uid from
  `shine_table.h` (persistent, authoritative). (b) is the right source.
- **`ShineAppearanceHook.cpp` line 461-467** has a load-bearing note: re-entering Cascade
  after the first multi-moon spawns the multi-moon shine as a **stub (no model keeper)** via
  `AppearSwitchTimer` — i.e. the moon actor IS placed on revisit but in already-collected
  form. This suggests the moon's placement may persist; the question is the *boss* gating.

## Open questions (investigate next)

1. **Decomp read REQUIRED** (per CLAUDE.md invariant — don't guess a hook chokepoint):
   - What exactly gates Madame Broode's spawn? (Cascade boss actor name in OdysseyDecomp.)
   - What scenario number is the Broode fight / the Multi-Moon placement?
   - How does `getScenarioNo(Cascade)` actually compute after leaving early? Does it really
     advance past the boss scenario, or is the boss gone for a different reason?
2. Will `setMainScenarioNo(Cascade, 1)` STICK, or get recomputed away on the next load (the
   MoonRockHook header warns Cap's scenario was recomputed back every load)?
3. If scenario-rollback is too destructive / non-sticky, the alternative is to **force-spawn
   just the Shine actor** at Broode's location — heavier (actor placement) but surgical.

## Candidate approaches (ranked, pre-decomp)

- **A. Scenario rollback on Cascade entry (preferred if it sticks):** hook stage-enter for
  `WaterfallWorldHomeStage`; if Multi-Moon shine flag unset AND `getScenarioNo(Cascade)` >
  Broode scenario, `setMainScenarioNo(Cascade, broodeScenario)` (or the quest-state lever that
  actually drives placement) so the next stage init re-places Broode + moon. Reuses all
  vanilla boss/moon logic.
- **B. Direct shine force-spawn:** place a Shine actor at Broode's coords when entering
  Cascade with the moon uncollected. No re-fight. More code, no scenario side effects.

## Next step

Fetch OdysseyDecomp for the Cascade boss + scenario placement to lock down the mechanism
before touching any hook (CLAUDE.md: READ THE DECOMP BEFORE PICKING A HOOK CHOKEPOINT).
